"""Hybrid ISO9660/Joliet/UDF mastering for original SDAL Builder pipeline.

The existing build.sh -> main.py -> build_iso API is preserved. Mastering
requires a real ISO/UDF-capable external mkisofs/genisoimage executable.
There is deliberately NO silent fallback to pure ISO9660.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile


SECTOR = 2048
_NAME = re.compile(r"[A-Z0-9_]{1,8}\.SDL\Z")
_LABEL = re.compile(r"[A-Z0-9_]{1,32}\Z")


class MasteringError(RuntimeError):
    pass


def _mirror4(blob: bytes, offset: int) -> int:
    le = int.from_bytes(blob[offset:offset + 4], "little")
    be = int.from_bytes(blob[offset + 4:offset + 8], "big")
    if le != be:
        raise MasteringError("ISO9660 mirrored BE/LE values disagree")
    return le


def _descriptor(fd, sector: int, kind: int) -> tuple[bytes, int, int, int]:
    fd.seek(sector * SECTOR)
    raw = fd.read(SECTOR)
    if len(raw) != SECTOR or raw[:7] != bytes([kind])+b"CD001\x01":
        raise MasteringError(f"Missing ISO9660 descriptor type {kind} at LBA {sector}")
    block_size = int.from_bytes(raw[128:130], "little")
    if block_size != SECTOR or int.from_bytes(raw[130:132], "big") != SECTOR:
        raise MasteringError("Unexpected ISO9660 logical block size")
    root = raw[156:190]
    return raw, _mirror4(raw, 80), _mirror4(root, 2), _mirror4(root, 10)


def _entries(fd, root_lba: int, root_bytes: int, *, joliet: bool) -> dict[str, tuple[int, int]]:
    if root_bytes < 34 or root_bytes > (1<<20):
        raise MasteringError("Unreasonable ISO root directory size")
    fd.seek(root_lba * SECTOR)
    contents = fd.read(root_bytes)
    if len(contents) != root_bytes:
        raise MasteringError("Truncated ISO root directory")
    found = {}
    i = 0
    while i < root_bytes:
        n = contents[i]
        if n == 0:
            i += SECTOR - i % SECTOR
            continue
        if n < 34 or i + n > root_bytes:
            raise MasteringError("Invalid ISO directory record")
        row = contents[i:i+n]
        i += n
        namebytes = row[33:33 + row[32]]
        if namebytes in (b"\x00", b"\x01"):
            continue
        if row[25] & 2:
            raise MasteringError("Unexpected subdirectory in SDL-only volume")
        try:
            name = namebytes.decode("utf-16-be" if joliet else "ascii")
        except UnicodeError as err:
            raise MasteringError("Invalid ISO file name encoding") from err
        size = _mirror4(row, 10)
        extent = _mirror4(row, 2)
        if name in found:
            raise MasteringError("Duplicate ISO root filename")
        found[name] = (extent, size)
    return found


def _udf_anchor(fd, lba: int) -> bool:
    fd.seek(lba * SECTOR)
    raw = fd.read(16)
    if len(raw) != 16 or struct.unpack_from("<H", raw)[0] != 2:
        return False
    if struct.unpack_from("<I", raw, 12)[0] != lba:
        return False
    return raw[4] == sum(raw[i] for i in range(16) if i != 4) & 255


def _verify_hybrid(path: Path, expected: dict[str, int], volume_id: str) -> None:
    with path.open("rb") as fd:
        pvd, blocks, root, root_size = _descriptor(fd, 16, 1)
        svd, svd_blocks, jroot, jroot_size = _descriptor(fd, 17, 2)
        if svd_blocks != blocks:
            raise MasteringError("ISO/Joliet volume extents disagree")
        fd.seek(18 * SECTOR)
        if fd.read(7) != b"\xffCD001\x01":
            raise MasteringError("Missing ISO descriptor terminator")
        if svd[88:91] not in (b"%/@", b"%/C", b"%/E"):
            raise MasteringError("Joliet escape sequence missing")
        label = pvd[40:72].decode("ascii").rstrip(" \x00")
        jlabel = svd[40:72].decode("utf-16-be").rstrip(" \x00")
        if label != volume_id or jlabel != volume_id:
            raise MasteringError("Volume labels in ISO/Joliet differ from requested label")
        iso = _entries(fd, root, root_size, joliet=False)
        joliet = _entries(fd, jroot, jroot_size, joliet=True)
        if iso != joliet:
            raise MasteringError("ISO/Joliet files and extents differ: " + repr(iso)[:750] + " vs " + repr(joliet)[:750])
        normalized = {k.removesuffix(";1"): v for k, v in iso.items()}
        if set(normalized) != set(expected):
            raise MasteringError("ISO contains missing/unexpected SDL files")
        for name, (lba, length) in normalized.items():
            if length != expected[name] or lba < 256:
                raise MasteringError("ISO file size or extent mismatches source: "+name)
            if lba + (length + SECTOR-1)//SECTOR > blocks:
                raise MasteringError("File extent outside ISO volume: "+name)
        ranges = sorted((lba,lba + (length+SECTOR-1)//SECTOR,name)
                        for name,(lba,length) in normalized.items())
        if any(a[1] > b[0] for a,b in zip(ranges,ranges[1:])):
            raise MasteringError("Overlapping SDL data extents")
        fd.seek(19*SECTOR)
        marker = [fd.read(SECTOR)[1:6] for _ in range(3)]
        if marker != [b"BEA01",b"NSR02",b"TEA01"]:
            raise MasteringError("UDF volume recognition sequence missing")
        if not _udf_anchor(fd, 256):
            raise MasteringError("UDF primary anchor at sector 256 missing")
        fd.seek(0, 2)
        bytes_on_disc = fd.tell()
        if bytes_on_disc % SECTOR or bytes_on_disc != blocks*SECTOR:
            raise MasteringError("ISO header volume geometry does not match actual image")
        if not _udf_anchor(fd, blocks-1):
            raise MasteringError("Terminal UDF anchor at last sector missing")


def build_iso(sdl_files: list[Path], out_iso: Path) -> None:
    """Build and verify a real hybrid ISO without interrupting the original CLI.

    This function **does not** validate SDL parcel content. Its scope is
    filesystem mastering only, while content has its own stricter gate.
    """
    out_iso = Path(out_iso)
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    executable = shutil.which("genisoimage") or shutil.which("mkisofs")
    if not executable:
        raise MasteringError("Hybrid ISO mastering requires genisoimage or mkisofs "
                             "with -udf support; pure-ISO fallback is forbidden")
    sources = {}
    for source in sdl_files:
        p = Path(source).resolve(strict=True)
        name = p.name.upper()
        if not p.is_file() or not _NAME.fullmatch(name):
            raise MasteringError("Only regular 8.3 SDL inputs are supported: "+str(source))
        if name in sources:
            raise MasteringError("Duplicate SDL source name: "+name)
        sources[name] = p
    if not sources or "INIT.SDL" not in sources or "MTOC.SDL" not in sources:
        raise MasteringError("OEM ISO requires its INIT.SDL and MTOC.SDL")
    requested_label = os.environ.get("SDAL_VOLUME_ID", out_iso.stem.upper())
    if not _LABEL.fullmatch(requested_label):
        raise MasteringError("SDAL_VOLUME_ID must match [A-Z0-9_]{1,32}")
    before = {name: (p.stat().st_size, p.stat().st_mtime_ns)
              for name,p in sources.items()}
    # To avoid copying many gigabytes of SDL payload, graft files directly.
    # Genisoimage interprets backslash and '=' in graft paths specially.
    def escape_graft(path: str) -> str:
        return path.replace("\\", "\\\\").replace("=", "\\=")
    fd, workfile = tempfile.mkstemp(prefix=".sdal_master_", suffix=".iso",
                                    dir=out_iso.parent)
    os.close(fd)
    output = Path(workfile)
    cmd = [executable, "-udf", "-J", "-iso-level", "3",
           "-V", requested_label, "-graft-points", "-o", str(output)]
    cmd.extend(name + "=" + escape_graft(str(sources[name]))
               for name in sorted(sources))
    logpath = output.with_suffix(".master.log")
    try:
        with logpath.open("wb") as logfile:
            # The process writes the ISO itself. Keep diagnostics in a
            # DIFFERENT file to avoid corrupting the image's output inode.
            run = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                 stderr=logfile, check=False)
        if run.returncode:
            detail = logpath.read_text(errors="replace")[-1500:]
            raise MasteringError("Hybrid ISO generator exited with "
                                 f"code {run.returncode}: {detail}")
        after = {name: (p.stat().st_size,p.stat().st_mtime_ns)
                 for name,p in sources.items()}
        if after != before:
            raise MasteringError("Source SDL changed during ISO mastering")
        _verify_hybrid(output, {name: status[0] for name,status in before.items()},
                       requested_label)
        os.replace(output, out_iso)
    finally:
        output.unlink(missing_ok=True)
        logpath.unlink(missing_ok=True)

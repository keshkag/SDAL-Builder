#!/usr/bin/env python3
"""Read-only OEM ISO9660, Joliet and UDF edge-sample structure verifier.

Accepts the first and last 1MiB of the *same* original DVD ISO. This is
an evidence reader, NOT a device compatibility or complete UDF validator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

SECTOR = 2048
EDGE = 1 << 20
REFERENCE_SIZES = {
    "INIT.SDL": 172032,
    "BENELUX1.SDL": 350914560,
    "SWIAUS1.SDL": 364488704,
    "DENSWE0.SDL": 319488,
    "DENSWE1.SDL": 912990208,
    "SWIAUS0.SDL": 319488,
}


class EvidenceError(ValueError):
    pass


def sector(data: bytes, index: int) -> bytes:
    start = index * SECTOR
    if start < 0 or start + SECTOR > len(data):
        raise EvidenceError(f"Missing sampled sector {index}")
    return data[start:start + SECTOR]


def mirror(data: bytes, le: int, be: int, width: int) -> int:
    a = int.from_bytes(data[le:le + width], "little")
    b = int.from_bytes(data[be:be + width], "big")
    if a != b:
        raise EvidenceError(f"ISO big/little endian fields differ: {le}/{be}")
    return a


def descriptor(data: bytes, index: int, code: int) -> dict:
    d = sector(data, index)
    if d[:7] != bytes([code]) + b"CD001\x01":
        raise EvidenceError(f"Missing ISO descriptor {index}, type {code}")
    blocks = mirror(d, 80, 84, 4)
    block_len = mirror(d, 128, 130, 2)
    if blocks < 512 or block_len != SECTOR:
        raise EvidenceError("Invalid volume geometry")
    root = d[156:190]
    extent = mirror(root, 2, 6, 4)
    size = mirror(root, 10, 14, 4)
    label = (d[40:72].decode("utf-16-be") if code == 2
             else d[40:72].decode("ascii"))
    return {
        "descriptor_sector": index,
        "volume_id": label.rstrip(" \x00"),
        "volume_blocks": blocks,
        "logical_block_bytes": block_len,
        "root_extent_lba": extent,
        "root_size_bytes": size,
        "path_table_bytes": mirror(d, 132, 136, 4),
        "path_table_le_lba": struct.unpack_from("<I", d, 140)[0],
        "path_table_be_lba": struct.unpack_from(">I", d, 148)[0],
        "joliet_escape": d[88:91].hex() if code == 2 else None,
    }


def parse_root(sample: bytes, info: dict, *, joliet: bool) -> list[dict]:
    extent, size = info["root_extent_lba"], info["root_size_bytes"]
    start = extent * SECTOR
    if not size or start + size > len(sample):
        raise EvidenceError("Root directory outside first 1MiB")
    data = sample[start:start + size]
    i = 0
    result = []
    while i < len(data):
        rec_len = data[i]
        if not rec_len:
            i += SECTOR - (i % SECTOR)
            continue
        if rec_len < 34 or i + rec_len > len(data):
            raise EvidenceError("Invalid ISO root record length")
        rec = data[i:i + rec_len]
        n = rec[32]
        if 33 + n > rec_len:
            raise EvidenceError("Invalid ISO filename length")
        rawname = rec[33:33 + n]
        i += rec_len
        if rawname in (b"\x00", b"\x01"):
            continue
        try:
            name = rawname.decode("utf-16-be" if joliet else "ascii")
        except UnicodeError as exc:
            raise EvidenceError("Invalid encoded filename") from exc
        length = mirror(rec, 10, 14, 4)
        lba = mirror(rec, 2, 6, 4)
        result.append({
            "name": name,
            "extent_lba": lba,
            "size_bytes": length,
            "sectors": (length + SECTOR - 1) // SECTOR,
            "is_directory": bool(rec[25] & 2),
        })
    if len({row["name"] for row in result}) != len(result):
        raise EvidenceError("Duplicate ISO filename")
    return result


def udf_tag(sample: bytes, sector_in_sample: int, expected_lba: int) -> dict:
    raw = sector(sample, sector_in_sample)
    identifier, version = struct.unpack_from("<HH", raw)
    loc = struct.unpack_from("<I", raw, 12)[0]
    checksum = sum(raw[i] for i in range(16) if i != 4) & 255
    return {"tag_id": identifier, "tag_version": version,
            "tag_lba": loc, "expected_lba": expected_lba,
            "checksum_ok": checksum == raw[4],
            "location_ok": loc == expected_lba}


def analyze(first: bytes, last: bytes, expected_volume: str = "WE_06Q4") -> dict:
    if len(first) != EDGE or len(last) != EDGE:
        raise EvidenceError("Need exact first and last 1048576 bytes of the same ISO")
    pvd = descriptor(first, 16, 1)
    svd = descriptor(first, 17, 2)
    if sector(first, 18)[:7] != b"\xffCD001\x01":
        raise EvidenceError("ISO9660 volume descriptor terminator missing")
    if pvd["volume_blocks"] != svd["volume_blocks"]:
        raise EvidenceError("ISO9660 and Joliet volume space disagrees")
    if pvd["volume_id"] != expected_volume or svd["volume_id"] != expected_volume:
        raise EvidenceError("Incorrect ISO volume label")
    if svd["joliet_escape"] not in ("252f40", "252f43", "252f45"):
        raise EvidenceError("Unknown Joliet escape sequence")
    primary = parse_root(first, pvd, joliet=False)
    supplementary = parse_root(first, svd, joliet=True)
    def refs(rows):
        return {row["name"]: (row["extent_lba"], row["size_bytes"], row["is_directory"])
                for row in rows}
    if refs(primary) != refs(supplementary):
        raise EvidenceError("ISO9660/Joliet file entries differ")
    if any(row["is_directory"] or not row["name"].endswith(".SDL;1")
           for row in primary):
        raise EvidenceError("Unexpected OEM directory entry")
    ordered = sorted(primary, key=lambda row: row["extent_lba"])
    for i, row in enumerate(ordered):
        if row["extent_lba"] + row["sectors"] > pvd["volume_blocks"]:
            raise EvidenceError("SDL extent exceeds declared volume")
        if i and ordered[i-1]["extent_lba"] + ordered[i-1]["sectors"] > row["extent_lba"]:
            raise EvidenceError("SDL file extents overlap")
    names = {row["name"].removesuffix(";1"): row for row in ordered}
    for name, size in REFERENCE_SIZES.items():
        if name not in names or names[name]["size_bytes"] != size:
            raise EvidenceError("OEM reference size missing or wrong: " + name)
    vrs = [sector(first, k)[1:6].decode("ascii", "replace")
           for k in (19, 20, 21)]
    if vrs != ["BEA01", "NSR02", "TEA01"]:
        raise EvidenceError("UDF volume recognition sequence missing")
    anchor = udf_tag(first, 256, 256)
    last_anchor = udf_tag(last, EDGE // SECTOR - 1, pvd["volume_blocks"] - 1)
    main = [udf_tag(first, i, i) for i in range(32, 38)]
    if ([x["tag_id"] for x in main] != [1, 4, 5, 6, 7, 8]
            or not all(x["checksum_ok"] and x["location_ok"] for x in main)):
        raise EvidenceError("UDF main descriptor sequence invalid")
    if any(x["tag_id"] != 2 or not x["checksum_ok"] or not x["location_ok"]
           for x in (anchor, last_anchor)):
        raise EvidenceError("UDF anchor descriptor invalid")
    return {
        "schema": "sdal-iter011-iso-evidence-v1",
        "source_sha256": {
            "first_1MiB": hashlib.sha256(first).hexdigest(),
            "last_1MiB": hashlib.sha256(last).hexdigest(),
        },
        "volume": {
            "id": pvd["volume_id"],
            "sectors": pvd["volume_blocks"],
            "total_bytes_from_descriptors": pvd["volume_blocks"] * SECTOR,
            "sector_bytes": SECTOR,
            "root_file_count": len(primary),
        },
        "iso9660": pvd,
        "joliet": svd,
        "udf": {
            "recognition_sequence": vrs,
            "begin_anchor": anchor,
            "end_anchor": last_anchor,
            "main_descriptor_tags": main,
        },
        "physical_file_extents": ordered,
        "all_iso9660_joliet_names_and_extents_identical": True,
        "all_file_extents_nonoverlapping": True,
        "source_pair_sizes_match_iso_directory": True,
        "limits": [
            "First/last 1MiB cannot validate UDF directory tree inside the volume.",
            "The OEM fingerprint is not a universal SDAL constraint or head-unit compatibility proof.",
            "Physical file order and volume label are observations; hardware necessity unverified.",
        ],
    }


def markdown(result: dict) -> str:
    vol = result["volume"]
    lines = ["# Iter011 — original OEM WE_06Q4 ISO evidence", "",
             f"Volume: `{vol['id']}`. {vol['sectors']} sectors × "
             f"{vol['sector_bytes']} bytes = {vol['total_bytes_from_descriptors']} bytes.",
             "", "## Volume descriptors", "",
             "- ISO9660 PVD sector 16; Joliet SVD sector 17; terminator sector 18.",
             "- UDF BEA01 / NSR02 / TEA01 recognition sequence: sectors 19–21.",
             "- UDF descriptor sequence: sectors 32–37.",
             f"- UDF anchors: sectors 256 and {vol['sectors']-1}.",
             f"- {vol['root_file_count']} SDL entries with matching ISO9660/Joliet root records.",
             "", "## Physical extent ordering", "",
             "| File | Start LBA | Bytes |", "|---|---:|---:|"]
    for row in result["physical_file_extents"]:
        lines.append(f"| `{row['name']}` | {row['extent_lba']} | {row['size_bytes']} |")
    lines += ["", "## Evidence limits", ""] + ["- "+item for item in result["limits"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("first", "last", "json", "md"):
        p.add_argument("--"+key, type=Path, required=True)
    p.add_argument("--volume", default="WE_06Q4")
    a = p.parse_args()
    try:
        for f in (a.first, a.last):
            if f.is_symlink() or not f.is_file():
                raise EvidenceError("Expected regular sample file: " + str(f))
        result = analyze(a.first.read_bytes(), a.last.read_bytes(), a.volume)
    except (EvidenceError, OSError) as e:
        p.exit(2, "ERROR: "+str(e)+"\n")
    a.json.parent.mkdir(parents=True, exist_ok=True)
    a.md.parent.mkdir(parents=True, exist_ok=True)
    a.json.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    a.md.write_text(markdown(result), encoding="utf-8")
    print(f"Validated OEM ISO9660/Joliet/UDF markers and {result['volume']['root_file_count']} SDL extents")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

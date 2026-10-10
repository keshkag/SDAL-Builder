#!/usr/bin/env python3
"""Read-only, evidence-constrained OEM PclHdr_t scanner for SDAL Builder.

A candidate does not establish a complete parcel or its decompressed length.
This program does not write SDL files or claim device compatibility.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

HEADER = struct.Struct(">IHBBBBHHHHH")  # SDAL 1.7 PclHdr_t; 20 bytes
SECTOR_BYTES = 256  # verified byte-offset relationship on this donor only
REGION_PREFIX = 0x2000
REGION_STEP = 0x4000
REQUIRED = ("INIT.SDL", "BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")
OBSERVED_PROFILES = {(19, 0, 0), (255, 1, 0), (1, 1, 0xB8)}


class EvidenceError(ValueError):
    pass


def read_header(data: bytes, at: int) -> dict:
    if at < 0 or at + HEADER.size > len(data):
        raise EvidenceError("Out-of-bounds 20-byte header")
    (pid, descriptor, kind, region, swap, comp_hi, comp_lo,
     compression, cmp_data_offset, uncomp_size, extension) = HEADER.unpack_from(data, at)
    return {
        "offset": at, "raw_header_hex": data[at:at + 20].hex(),
        "parcel_id": f"0x{pid:08X}",
        "size_index": (pid >> 24) & 63,
        "offset_units_low24": pid & 0xFFFFFF,
        "inferred_address_bytes": (pid & 0xFFFFFF) * SECTOR_BYTES,
        "self_addressed": (pid & 0xFFFFFF) * SECTOR_BYTES == at,
        "external_bit": bool(pid & (1 << 31)),
        "redundancy_bit": bool(pid & (1 << 30)),
        "descriptor": descriptor, "parcel_type": kind, "region": region,
        "endian_swap": swap, "compressed_size_hi": comp_hi,
        "compressed_size_lo": comp_lo, "compression_type": compression,
        "compressed_data_offset": cmp_data_offset,
        "uncompressed_size": uncomp_size, "extension_offset": extension,
    }


def candidate(header: dict) -> bool:
    return (
        header["offset"] > 0 and header["self_addressed"] and
        not header["external_bit"] and not header["redundancy_bit"] and
        header["endian_swap"] == 0 and
        (header["parcel_type"], header["region"], header["descriptor"])
            in OBSERVED_PROFILES and
        header["compressed_size_hi"] == 0 and
        header["compressed_size_lo"] == 0 and
        header["compression_type"] == 0 and
        header["compressed_data_offset"] == 0 and
        header["extension_offset"] == 0
    )


def scan(data: bytes) -> list[dict]:
    return [h for offset in range(SECTOR_BYTES, len(data) - HEADER.size + 1, SECTOR_BYTES)
            if candidate(h := read_header(data, offset))]


def analyze(files: dict[str, bytes], strict: bool = True) -> dict:
    missing = sorted(set(REQUIRED) - files.keys())
    if missing:
        raise EvidenceError("Missing donor file: " + ", ".join(missing))
    manifest = {}
    for name in REQUIRED:
        data = files[name]
        headers = scan(data)
        for i, header in enumerate(headers):
            end = headers[i + 1]["offset"] if i + 1 < len(headers) else len(data)
            span = data[header["offset"] + HEADER.size:end]
            nz = [i for i, value in enumerate(span) if value]
            header["observed_next_candidate_or_eof"] = end
            header["observed_gap_bytes"] = end - header["offset"]
            header["following_window_nonzero_bytes"] = len(nz)
            header["following_window_leading_zero_bytes"] = (
                nz[0] if nz else len(span))
        counts = Counter((h["parcel_type"], h["size_index"]) for h in headers)
        manifest[name] = {
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "candidates": headers,
            "type_size_index_counts": [
                {"type": kind, "size_index": index, "count": count}
                for (kind, index), count in sorted(counts.items())],
        }
    regions = {}
    for name in ("BENELUX0.SDL", "FRANCE0.SDL"):
        offsets = [h["offset"] for h in manifest[name]["candidates"]]
        expected = list(range(REGION_PREFIX, len(files[name]), REGION_STEP))
        regions[name] = {
            "candidate_offsets": offsets,
            "expected_offsets": expected,
            "matches_observed_19_by_16k": len(expected) == 19 and offsets == expected,
            "header_type_and_index": all(
                (h["parcel_type"], h["region"], h["size_index"]) == (19, 0, 56)
                for h in manifest[name]["candidates"]),
        }
    init, ben = files["INIT.SDL"], files["BENELUX0.SDL"]
    relocation = []
    for dst, src in ((0x6000, 0x2000), (0xA000, 0x6000), (0xE000, 0x16000)):
        a, b = init[dst:dst + REGION_STEP], ben[src:src + REGION_STEP]
        h = read_header(init, dst)
        relocation.append({
            "init_offset": dst, "benelux_offset": src, "bytes_compared": REGION_STEP,
            "equal": len(a) == len(b) == REGION_STEP and a == b,
            "embedded_address_targets_source": h["inferred_address_bytes"] == src,
            "embedded_address_is_not_destination": h["inferred_address_bytes"] != dst,
        })
    carto = [(h["offset"], h["parcel_type"], h["size_index"])
             for h in manifest["CARTOTOP.SDL"]["candidates"]]
    validation = {
        "regions": all(r["matches_observed_19_by_16k"] and r["header_type_and_index"]
                       for r in regions.values()),
        "cartotop": carto == [(0x2000, 255, 56), (0x6000, 1, 56),
                              (0xA000, 1, 46), (0x12000, 1, 0)],
        "init_relations": all(r["equal"] and r["embedded_address_targets_source"]
                              and r["embedded_address_is_not_destination"]
                              for r in relocation),
    }
    if strict and not all(validation.values()):
        raise EvidenceError("Donor profile mismatch: " +
                            ", ".join(k for k, ok in validation.items() if not ok))
    return {
        "schema": "sdal-iter004-candidate-evidence-v1",
        "interpretation": "byte-level evidence only; no OEM compliance claim",
        "header_struct_bytes": HEADER.size,
        "observed_sector_bytes": SECTOR_BYTES,
        "observed_regions": regions,
        "files": manifest,
        "init_relocated_copies": relocation,
        "validation": validation,
        "unresolved": [
            "ucaParcelSizes table location and 0/46/56 size-index meanings",
            "Full parcel boundaries; next detected header is not a proven length",
            "Compression and uncompressed-size field semantics in this OEM layout",
            "Cartography/index record semantics and actual OEM boot sequence",
        ],
    }


def read_donor(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        raise EvidenceError("Donor directory not found")
    files = {}
    for name in REQUIRED:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise EvidenceError("Missing regular donor file: " + str(path))
        files[name] = path.read_bytes()
    return files


def format_markdown(result: dict) -> str:
    lines = [
        "# Iter004 — observed OEM parcel-header evidence", "",
        "All offsets and byte matches refer to supplied original binary files.", "",
        "| File | Candidate headers | Type / size-index observations |",
        "|---|---:|---|",
    ]
    for name, data in result["files"].items():
        counts = ", ".join(f"{v['type']}/{v['size_index']} ×{v['count']}"
                           for v in data["type_size_index_counts"]) or "none"
        lines.append(f"| {name} | {len(data['candidates'])} | {counts} |")
    lines += ["", "## CARTOTOP candidates", "",
              "| Offset | ID | Type | Size index | Bytes until next candidate / EOF |",
              "|---:|---|---:|---:|---:|"]
    for h in result["files"]["CARTOTOP.SDL"]["candidates"]:
        lines.append(f"| 0x{h['offset']:X} | {h['parcel_id']} | {h['parcel_type']} "
                     f"| {h['size_index']} | {h['observed_gap_bytes']} |")
    lines += ["", "## INIT relocation proofs", ""]
    for r in result["init_relocated_copies"]:
        lines.append(f"- INIT 0x{r['init_offset']:X} equals BENELUX0 "
                     f"0x{r['benelux_offset']:X}, exact={r['equal']}, "
                     f"embedded address references source={r['embedded_address_targets_source']}")
    lines += ["", "## Donor invariant checks", ""]
    for label, passed in result["validation"].items():
        lines.append(f"- {label}: {'PASS' if passed else 'FAIL'}")
    lines += ["", "## Unresolved", ""]
    lines += ["- " + s for s in result["unresolved"]]
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    parser.add_argument("--non-strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = analyze(read_donor(args.directory), strict=not args.non_strict)
    except (OSError, EvidenceError) as e:
        parser.exit(2, f"ERROR: {e}\n")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                                encoding="utf-8")
    args.output_md.write_text(format_markdown(result), encoding="utf-8")
    print("Detected:", sum(len(f["candidates"]) for f in result["files"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

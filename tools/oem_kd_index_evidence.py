#!/usr/bin/env python3
"""Read-only original BENELUX1/SWIAUS1 KD-tree index provenance report."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.oem_index import (
    EvidenceError, OEM_INDEX_BYTES, OEM_SECTOR,
    decode_index_parcel, header_fields,
)

FIRST_MAP_HEADERS = (0x2000, 0x7100)
FIRST_INDEX = 0xC200


def audit_map(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("Missing original OEM map file: " + str(path))
    size = path.stat().st_size
    map_headers, indexes = [], []
    with path.open("rb") as source:
        for start in FIRST_MAP_HEADERS:
            source.seek(start)
            h = header_fields(source.read(20))
            if ((h["parcel_type"], h["region"], h["size_index"]) != (24, 1, 9)
                    or not h["redundancy"] or h["external"]
                    or h["offset_units"] * OEM_SECTOR != start):
                raise EvidenceError("Map Header type-24 structure mismatches OEM bytes")
            map_headers.append({
                "offset": start, "parcel_id": f"0x{h['parcel_id']:08X}",
                "size_index": h["size_index"],
                "spacing_to_next_header_or_index": 0x5100,
            })
        at = FIRST_INDEX
        while at + OEM_INDEX_BYTES <= size:
            source.seek(at)
            raw = source.read(OEM_INDEX_BYTES)
            h = header_fields(raw[:20])
            if h["parcel_type"] != 255 or h["region"] != 1:
                break
            decoded = decode_index_parcel(raw, absolute_offset=at)
            if decoded.reassemble() != raw:
                raise EvidenceError("Codec failed to reconstruct an OEM index")
            indexes.append({
                "offset": at, "parcel_id": f"0x{h['parcel_id']:08X}",
                "size_index": h["size_index"],
                "root_count": len(decoded.root_offsets),
                "first_root_offset": decoded.root_offsets[0],
                "last_root_offset": decoded.root_offsets[-1],
                "first_root_is_table_end": (
                    decoded.root_offsets[0] == 24 + 2 * len(decoded.root_offsets)),
                "root_offsets_strictly_increasing": True,
                "exact_reassembly_sha256": sha256(raw).hexdigest(),
                "byte_identical_after_reassembly": True,
            })
            at += OEM_INDEX_BYTES
    if not indexes:
        raise EvidenceError("No OEM type-255 global KD index parcels found")
    return {
        "file": path.name, "source_bytes": size,
        "map_header_candidates": map_headers,
        "index_parcels": indexes,
        "index_parcel_count": len(indexes),
        "total_roots": sum(x["root_count"] for x in indexes),
        "index_chain_next_boundary": at,
    }


def audit_init(init_file: Path) -> dict:
    if init_file.is_symlink() or not init_file.is_file():
        raise EvidenceError("Missing original INIT.SDL")
    data = init_file.read_bytes()
    evidence = []
    for i in range(8):
        offset_desc = 0x1C8 + i * 16
        if offset_desc + 8 > len(data):
            raise EvidenceError("Missing INIT 0x1800 descriptor")
        addr, length = struct.unpack_from(">II", data, offset_desc)
        if length != 0x1800 or addr + 28 > len(data):
            raise EvidenceError("Invalid INIT long-table address/length")
        word = data[addr:addr + 4]
        if data[addr:addr + 28] != word * 7:
            raise EvidenceError("Seven repeated words in INIT table did not match")
        evidence.append({
            "group": i + 1, "repeat_count": 7,
            "word": f"0x{int.from_bytes(word, 'big'):08X}",
            "candidate_direct_byte_address": (int.from_bytes(word, "big") & 0xffffff) * OEM_SECTOR,
        })
    return {"file": init_file.name, "eight_group_references": evidence}


def audit(maps: dict[str, Path], init_path: Path | None = None) -> dict:
    if not maps:
        raise EvidenceError("No original map supplied")
    data = {name: audit_map(path) for name, path in sorted(maps.items())}
    init = audit_init(init_path) if init_path is not None else None
    if init:
        expected = data[next(iter(data))]["index_parcels"][0]["parcel_id"]
        if not all(x["word"] == expected and
                   x["candidate_direct_byte_address"] == FIRST_INDEX
                   for x in init["eight_group_references"]):
            raise EvidenceError("INIT repeated marker does not match first OEM index")
        for name, entry in data.items():
            if entry["index_parcels"][0]["parcel_id"] != expected:
                raise EvidenceError("INIT first index differs from " + name)
    return {
        "schema": "sdal-oem-iter012-kd-index-v1",
        "maps": data, "init_reference": init,
        "evidence_scope": "Verified candidate index structure and reversible raw trees, not decoded tree nodes",
        "limitations": [
            "Tree node content is opaque; route traversal is not implemented.",
            "Only OEM map file index profile (0x5000 and 256-byte addresses) is validated.",
            "An exactly reconstructed index parcel alone does not make a map bootable.",
            "No changes to ISO mastering or OEM DVD filesystem have been attempted.",
        ],
    }


def render_md(report: dict) -> str:
    lines = ["# Iter012: OEM KD-tree Index parcel verification", "",
             "This is a structural index codec, not a KD-tree navigation implementation.", "",
             "| Map | Index parcels | Total roots | 0x5000-byte extents reversible |",
             "|---|---:|---:|---|"]
    for name, row in report["maps"].items():
        lines.append(f"| {name} | {row['index_parcel_count']} | "
                     f"{row['total_roots']} | "
                     f"{all(x['byte_identical_after_reassembly'] for x in row['index_parcels'])} |")
    lines += ["", "## Index records", "",
              "| File | Offset | Parcel ID | Roots | First root offset | Last root offset |",
              "|---|---:|---|---:|---:|---:|"]
    for name, map_data in report["maps"].items():
        for record in map_data["index_parcels"]:
            lines.append(f"| {name} | 0x{record['offset']:X} | {record['parcel_id']} | "
                         f"{record['root_count']} | {record['first_root_offset']} | "
                         f"{record['last_root_offset']} |")
    lines += ["", "## Evidence limits", ""] + ["- " + x for x in report["limitations"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--init", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    try:
        maps = {}
        for item in args.map:
            if "=" not in item:
                raise EvidenceError("Expected NAME=PATH for each map")
            name, filename = item.split("=", 1)
            if not name or name in maps:
                raise EvidenceError("Empty or duplicate map label")
            maps[name] = Path(filename)
        result = audit(maps, args.init)
    except (EvidenceError, OSError) as err:
        parser.exit(2, "ERROR: " + str(err) + "\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    args.md.write_text(render_md(result), encoding="utf-8")
    print("Verified", sum(x["index_parcel_count"] for x in result["maps"].values()),
          "OEM type-255 index parcels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

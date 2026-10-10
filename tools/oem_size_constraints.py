#!/usr/bin/env python3
"""Read-only constraints on SDAL ucaParcelSizes inferred from OEM boundaries.

Observed gaps are not verified parcel lengths. This tool never writes SDLs.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct

HEADER = struct.Struct(">IHBBBBHHHHH")
UNIT = 256  # Verified observed ParcelID address unit for supplied OEM corpus.
PROFILES = {(19, 0, 0), (255, 1, 0), (1, 1, 0xB8)}
SOURCE_FILES = ("BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")
SEARCH_FILES = ("INIT.SDL", "MTOC.SDL", "REGION.SDL", "REGIONS.SDL",
                "BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")


class EvidenceError(ValueError):
    pass


def parse_candidate(data: bytes, offset: int) -> dict | None:
    if offset <= 0 or offset % UNIT or offset + HEADER.size > len(data):
        return None
    (pid, desc, typ, region, swap, size_hi, size_lo, compress,
     compressed_data, uncomp_size, extension) = HEADER.unpack_from(data, offset)
    if not ((pid >> 30) == 0 and (pid & 0xFFFFFF) * UNIT == offset
            and (typ, region, desc) in PROFILES and swap == 0
            and size_hi == 0 and size_lo == 0 and compress == 0
            and compressed_data == 0 and extension == 0):
        return None
    return {"offset": offset, "pid_be": f"0x{pid:08X}",
            "size_index": (pid >> 24) & 0x3F,
            "parcel_type": typ, "region": region,
            "uncompressed_size_header_field": uncomp_size}


def find_candidates(data: bytes) -> list[dict]:
    return [header for offset in range(UNIT, len(data) - HEADER.size + 1, UNIT)
            if (header := parse_candidate(data, offset)) is not None]


def derive_constraints(files: dict[str, bytes], *, enforce_we06q4: bool = False) -> dict:
    missing = sorted(set(SOURCE_FILES) - files.keys())
    if missing:
        raise EvidenceError("Missing OEM files: " + ", ".join(missing))
    observations = []
    by_index = defaultdict(list)
    candidate_counts = {}
    for name in SOURCE_FILES:
        data = files[name]
        headers = find_candidates(data)
        candidate_counts[name] = len(headers)
        for i, header in enumerate(headers):
            next_at = headers[i + 1]["offset"] if i + 1 < len(headers) else len(data)
            gap = next_at - header["offset"]
            if gap <= 0 or gap % UNIT or gap // UNIT > 255:
                raise EvidenceError(f"Invalid candidate boundary gap in {name} at 0x{header['offset']:X}")
            record = {
                "file": name, "start": header["offset"],
                "next_candidate_or_eof": next_at, "eof_boundary": i == len(headers) - 1,
                "size_index": header["size_index"],
                "gap_bytes": gap, "gap_units": gap // UNIT,
                "status": "hypothesis_from_next_header_or_eof",
            }
            observations.append(record)
            by_index[header["size_index"]].append(record)
    inconsistent = {
        idx: sorted(set(row["gap_units"] for row in rows))
        for idx, rows in by_index.items()
        if len(set(row["gap_units"] for row in rows)) != 1
    }
    if inconsistent:
        raise EvidenceError(f"Conflicting boundary lengths for the same index: {inconsistent}")
    values = [
        {"size_index": idx,
         "candidate_size_units": rows[0]["gap_units"],
         "candidate_size_bytes": rows[0]["gap_bytes"],
         "observations": len(rows),
         "files": sorted(set(r["file"] for r in rows)),
         "eof_based_observations": sum(r["eof_boundary"] for r in rows)}
        for idx, rows in sorted(by_index.items())
    ]
    if enforce_we06q4:
        expected = {0: 94, 42: 50, 45: 157, 46: 128, 52: 60, 56: 64, 59: 71}
        observed = {row["size_index"]: row["candidate_size_units"] for row in values}
        if observed != expected or candidate_counts != {
                "BENELUX0.SDL": 19, "FRANCE0.SDL": 19, "CARTOTOP.SDL": 8}:
            raise EvidenceError(f"WE_06Q4 evidence profile changed: {observed} {candidate_counts}")
    return {
        "schema": "sdal-iter005-size-constraints-v1",
        "status": "provisional_boundaries_not_a_decoded_ucaParcelSizes_table",
        "address_unit_bytes": UNIT,
        "candidate_counts": candidate_counts,
        "index_constraints": values,
        "individual_observations": observations,
    }


def locate_direct_uint8_patterns(files: dict[str, bytes], values: list[dict]) -> list[dict]:
    """Search for a continuous byte array with ALL index/length pairs.

    Positive hits are patterns, NOT authenticated GlbMediaHeader_t fields.
    Negative hits do not exclude encoded or absent global header records.
    """
    expected = {x["size_index"]: x["candidate_size_units"] for x in values}
    if not expected:
        return []
    width = max(expected) + 1
    hits = []
    for name, data in sorted(files.items()):
        for at in range(len(data) - width + 1):
            if all(data[at + idx] == value for idx, value in expected.items()):
                hits.append({"file": name, "offset": at,
                             "minimal_pattern_width_bytes": width})
    return hits


def analyze(files: dict[str, bytes], *, enforce_we06q4: bool = False) -> dict:
    result = derive_constraints(files, enforce_we06q4=enforce_we06q4)
    result["source_files"] = [
        {"file": name, "size_bytes": len(blob), "sha256": sha256(blob).hexdigest()}
        for name, blob in sorted(files.items())
    ]
    result["direct_uint8_pattern_matches"] = locate_direct_uint8_patterns(
        files, result["index_constraints"])
    result["limitations"] = [
        "Next candidate/EOF gap is not independently validated parcel length.",
        "Last candidate to EOF assumes there is no trailing file padding.",
        "Original ucaParcelSizes array and its GlbMediaHeader_t location are unverified.",
        "Missing raw array pattern does not establish that no encoded or indirect table exists.",
        "SDAL 1.7 mentions 6 size-index bits but also defines MAX_PARCEL_SIZES=128.",
        "No OEM boot-order or head-unit compatibility claim.",
    ]
    return result


def markdown(report: dict) -> str:
    lines = [
        "# Iter005 — provisional ucaParcelSizes constraints", "",
        "These are exact header-spacing observations, NOT verified size-table contents.", "",
        "| Index | Candidate units (256 B) | Bytes | Observations | Files |",
        "|---:|---:|---:|---:|---|",
    ]
    for r in report["index_constraints"]:
        lines.append(f"| {r['size_index']} | {r['candidate_size_units']} | "
                     f"{r['candidate_size_bytes']} | {r['observations']} | "
                     f"{', '.join(r['files'])} |")
    lines += ["", f"Direct contiguous uint8 pattern matches: {len(report['direct_uint8_pattern_matches'])}",
              "", "## Caveats", ""]
    lines.extend("- " + item for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path, required=True)
    parser.add_argument("--md", dest="md_path", type=Path, required=True)
    parser.add_argument("--require-we06q4", action="store_true")
    args = parser.parse_args(argv)
    try:
        files = {}
        for name in SEARCH_FILES:
            path = args.directory / name
            if path.is_file() and not path.is_symlink():
                files[name] = path.read_bytes()
        report = analyze(files, enforce_we06q4=args.require_we06q4)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.md_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    args.md_path.write_text(markdown(report), encoding="utf-8")
    print(f"{sum(report['candidate_counts'].values())} candidate headers; "
          f"{len(report['index_constraints'])} provisional size-index values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Evidence-driven PclHdr_t candidates in OEM WE_06Q4 data.

READ ONLY. Matching a header pattern does not establish its complete SDAL
meaning or certify that a head unit can load a generated image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

PCL_HEADER = struct.Struct(">IHBBBBHHHHH")  # 20 bytes, SDAL 1.7 section 1.2.4.3
PAGE_BYTES = 4096
OBSERVED_UNIT_BYTES = 256
REGION_PREFIX_BYTES = 8192
REGION_RUN_BYTES = 16384
NAMES = ("INIT.SDL", "BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")


class EvidenceError(ValueError):
    """Observed donor invariants could not be verified."""


def decode_at(data: bytes, offset: int) -> dict:
    if offset < 0 or offset + PCL_HEADER.size > len(data):
        raise EvidenceError("Header offset out of range")
    raw = data[offset:offset + PCL_HEADER.size]
    (pid, desc, typ, region, endian, size_hi, size_lo, compress_type,
     compressed_offset, uncompressed_size, extension_offset) = PCL_HEADER.unpack(raw)
    stored_position = (pid & 0xFFFFFF) * OBSERVED_UNIT_BYTES
    return {
        "offset": offset,
        "raw_header_hex": raw.hex(),
        "pid_be": f"0x{pid:08X}",
        "external_bit": (pid >> 31) & 1,
        "redundancy_bit": (pid >> 30) & 1,
        "size_index_bits_29_to_24": (pid >> 24) & 0x3F,
        "offset_units_low24": pid & 0xFFFFFF,
        "inferred_position_bytes": stored_position,
        "matches_current_offset": stored_position == offset,
        "descriptor": desc, "parcel_type": typ, "region_id": region,
        "endian_swap": endian,
        "compressed_size_hi": size_hi, "compressed_size_lo": size_lo,
        "compression_type": compress_type,
        "compressed_data_offset": compressed_offset,
        "uncompressed_size": uncompressed_size,
        "extension_offset": extension_offset,
    }


def candidates(data: bytes) -> list[dict]:
    """Inspect page-aligned bytes; do not scan arbitrary data as parcel headers."""
    result = []
    for offset in range(0, len(data) - PCL_HEADER.size + 1, PAGE_BYTES):
        h = decode_at(data, offset)
        # Type 19 = global/media data, 1 = cartography in SDAL 1.7.
        # Type 0xFF is OEM-observed but NOT supported by generic SDAL schema.
        if (h["parcel_type"] in (19, 1, 255) and
            h["region_id"] in (0, 1) and
            h["endian_swap"] == 0 and
            h["descriptor"] in (0, 0xB8) and
            h["external_bit"] == 0 and h["redundancy_bit"] == 0 and
            h["offset_units_low24"] != 0):
            result.append(h)
    return result


def analyze(blobs: dict[str, bytes], *, strict: bool = True) -> dict:
    missing = sorted(set(NAMES) - blobs.keys())
    if missing:
        raise EvidenceError("Missing input: " + ", ".join(missing))
    result = {}
    for name in NAMES:
        raw = blobs[name]
        result[name] = {
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "header_candidates": candidates(raw),
        }
    partitions = {}
    for name in ("BENELUX0.SDL", "FRANCE0.SDL"):
        expected = list(range(REGION_PREFIX_BYTES, len(blobs[name]), REGION_RUN_BYTES))
        actual = [h["offset"] for h in result[name]["header_candidates"]]
        partitions[name] = {
            "preamble_bytes": REGION_PREFIX_BYTES,
            "repeating_region_bytes": REGION_RUN_BYTES,
            "count": len(expected),
            "fits_exactly": (len(blobs[name]) >= REGION_PREFIX_BYTES and
                             (len(blobs[name]) - REGION_PREFIX_BYTES) % REGION_RUN_BYTES == 0),
            "all_candidates_at_expected_positions": actual == expected,
            "all_low24_address_fields_match_position": all(
                h["matches_current_offset"] for h in result[name]["header_candidates"]),
        }
    copied_runs = []
    init = blobs["INIT.SDL"]
    for hdr in result["INIT.SDL"]["header_candidates"]:
        offset = hdr["offset"]
        fragment = init[offset:offset + REGION_RUN_BYTES]
        if len(fragment) != REGION_RUN_BYTES:
            continue
        for name in ("BENELUX0.SDL", "FRANCE0.SDL"):
            for source in result[name]["header_candidates"]:
                pos = source["offset"]
                if fragment == blobs[name][pos:pos + REGION_RUN_BYTES]:
                    copied_runs.append({
                        "init_offset": offset, "source_file": name,
                        "source_offset": pos,
                        "length_bytes": REGION_RUN_BYTES,
                        "embedded_address_matches_source": (
                            hdr["inferred_position_bytes"] == pos),
                        "sha256": hashlib.sha256(fragment).hexdigest(),
                    })
    copied_runs.sort(key=lambda x: (x["init_offset"], x["source_file"]))
    report = {
        "schema": "sdal-oem-iter003-pclhdr-candidates-v1",
        "method": "exact_byte_comparison_plus_spec_layout_hypothesis",
        "sdal_spec": "1.7 sections 1.2.4.3 and 1.4.0.2",
        "observed_address_unit_bytes": OBSERVED_UNIT_BYTES,
        "input_files": result,
        "regional_partition": partitions,
        "exact_relocated_16k_fragments": copied_runs,
        "not_established": [
            "Interpretation of all header/compression fields",
            "Validity of individual parcels and their size tables",
            "CARTOTOP cross references and loader order",
            "Compatibility with OEM hardware",
        ],
    }
    if strict:
        for name, entry in partitions.items():
            if not all((entry["fits_exactly"],
                        entry["all_candidates_at_expected_positions"],
                        entry["all_low24_address_fields_match_position"])):
                raise EvidenceError("Regional pattern failed validation in " + name)
        needed = {(0x6000, "BENELUX0.SDL", 0x2000),
                  (0xA000, "BENELUX0.SDL", 0x6000),
                  (0xE000, "BENELUX0.SDL", 0x16000)}
        observed = {(x["init_offset"], x["source_file"], x["source_offset"])
                    for x in copied_runs}
        if not needed <= observed:
            raise EvidenceError("Expected copied INIT fragments were not verified")
    return report


def markdown(report: dict) -> str:
    lines = [
        "# Iter003: OEM parcel header candidate analysis", "",
        "SDAL 1.7 field-layout *hypotheses*, not a fully decoded OEM parser.", "",
        "## Exact regional partition", "",
        "| File | Preamble | Repeat unit | Candidates | Exact partition |",
        "|---|---:|---:|---:|---|",
    ]
    for name, item in report["regional_partition"].items():
        lines.append(
            f'| {name} | {item["preamble_bytes"]} | '
            f'{item["repeating_region_bytes"]} | {item["count"]} | '
            f'{item["fits_exactly"] and item["all_candidates_at_expected_positions"]} |')
    lines += ["", "## Exact copied 16KiB fragments", "",
              "| INIT offset | Source file | Source offset | Stored address matches source |",
              "|---:|---|---:|---|"]
    for item in report["exact_relocated_16k_fragments"]:
        lines.append(
            f'| 0x{item["init_offset"]:X} | {item["source_file"]} | '
            f'0x{item["source_offset"]:X} | {item["embedded_address_matches_source"]} |')
    lines += ["", "## Candidate field details", "",
              "| File | Offset | Parcel ID | Type | Region | Self-addressed |",
              "|---|---:|---|---:|---:|---|"]
    for name, entry in report["input_files"].items():
        for h in entry["header_candidates"]:
            lines.append(
                f'| {name} | 0x{h["offset"]:X} | {h["pid_be"]} | '
                f'{h["parcel_type"]} | {h["region_id"]} | {h["matches_current_offset"]} |')
    lines += ["", "## Not yet established", ""]
    lines += ["- " + item for item in report["not_established"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", dest="json_path", required=True, type=Path)
    parser.add_argument("--md", dest="md_path", required=True, type=Path)
    parser.add_argument("--non-strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = analyze({name: (args.directory / name).read_bytes()
                          for name in NAMES}, strict=not args.non_strict)
    except (OSError, ValueError) as err:
        parser.exit(2, f"ERROR: {err}\n")
    args.json_path.parent.mkdir(parents=True, exist_ok=True)
    args.md_path.parent.mkdir(parents=True, exist_ok=True)
    args.json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    args.md_path.write_text(markdown(report), encoding="utf-8")
    print("Analyzed candidate headers in", len(NAMES), "original OEM SDL files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

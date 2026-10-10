#!/usr/bin/env python3
"""Read-only decoder of an *observed* OEM SDL catalog, not a generic SDAL implementation."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

NAMES = ("INIT.SDL", "MTOC.SDL", "REGION.SDL", "REGIONS.SDL",
         "CARTOTOP.SDL", "BENELUX0.SDL", "FRANCE0.SDL")
BASE = 0x40
STRIDE = 0x44
INIT_MTOC_OFFSET = 0x12000
FILENAME_PATTERN = re.compile(rb"^[A-Z0-9_-]+\.SDL$")


def load(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    result = {}
    for name in NAMES:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        result[name] = path.read_bytes()
    return result


def decode_entries(raw: bytes) -> list[dict]:
    """Decode only observed offsets; preserve uninterpreted bytes."""
    result = []
    for pos in range(BASE, len(raw) - STRIDE + 1, STRIDE):
        entry = raw[pos:pos + STRIDE]
        name = entry[8:24].split(b"\x00", 1)[0]
        if not FILENAME_PATTERN.fullmatch(name):
            break
        word = int.from_bytes(entry[24:28], "big")
        result.append({
            "position": pos, "filename_offset": pos + 8,
            "filename": name.decode("ascii"),
            "observed_high_byte": word >> 24,
            "observed_low_24_bits": word & 0xFFFFFF,
            "word_be_hex": f"0x{word:08X}", "raw_entry_hex": entry.hex()
        })
    if not result:
        raise ValueError("No observed catalog entries at 0x40")
    return result


def compare(left: bytes, right: bytes) -> dict:
    compared = min(len(left), len(right))
    bad = [i for i in range(compared) if left[i] != right[i]]
    return {
        "compared_bytes": compared,
        "equal_bytes": compared - len(bad),
        "different_bytes": len(bad),
        "first_difference": bad[0] if bad else None,
        "last_difference": bad[-1] if bad else None,
        "length_difference": len(left) - len(right)
    }


def analyze(files: dict[str, bytes]) -> dict:
    for name in NAMES:
        if name not in files:
            raise ValueError(f"Missing OEM sample: {name}")
    mtoc = files["MTOC.SDL"]
    init = files["INIT.SDL"]
    end = INIT_MTOC_OFFSET + len(mtoc)
    if end > len(init):
        raise ValueError("INIT shorter than MTOC comparison window")
    init_window = init[INIT_MTOC_OFFSET:end]
    mtoc_records = decode_entries(mtoc)
    init_records = decode_entries(init_window)
    entry_end = BASE + len(mtoc_records) * STRIDE
    counts = Counter(f"0x{r['observed_high_byte']:02X}" for r in mtoc_records)
    files_report = {}
    for name, data in sorted(files.items()):
        nonzero = sum(b != 0 for b in data)
        files_report[name] = {
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "nonzero_bytes": nonzero,
        }
    return {
        "schema": "oem-observation-iter001-v1",
        "compliance_claimed": False,
        "files": files_report,
        "catalog": {
            "record_count": len(mtoc_records), "record_stride": STRIDE,
            "entry_start": BASE, "entries": mtoc_records,
            "high_byte_counts": dict(sorted(counts.items())),
            "numeric_suffixes_1_to_n": [
                r["observed_low_24_bits"] for r in mtoc_records
            ] == list(range(1, len(mtoc_records) + 1)),
        },
        "init_mtoc": {
            "init_offset": INIT_MTOC_OFFSET,
            "entries_byte_identical": (
                mtoc[:entry_end] == init_window[:entry_end] and
                len(init_records) == len(mtoc_records)
            ),
            "byte_comparison": compare(mtoc, init_window)
        },
        "region_and_regions": {
            "byte_identical": files["REGION.SDL"] == files["REGIONS.SDL"]
        },
        "benelux_and_france": {
            "byte_comparison": compare(files["BENELUX0.SDL"], files["FRANCE0.SDL"])
        },
        "qualification": (
            "Observed fields only. The binary record word's OEM semantics, "
            "loading sequence, physical ISO sector layout, and head-unit "
            "compatibility have not been established."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", "-o", type=Path, required=True)
    args = parser.parse_args()
    try:
        evidence = analyze(load(args.directory))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                           encoding="utf-8")
    print(f"Saved {evidence['catalog']['record_count']} observed entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

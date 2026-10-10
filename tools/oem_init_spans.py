#!/usr/bin/env python3
"""Read-only OEM INIT offset/length evidence from independently sourced discs.

Offset-length interpretation is supported by cross-release byte continuity.
It is not a generic SDAL parser or a validated OEM boot sequence.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import pairwise
import json
from pathlib import Path
import re
from struct import Struct

PAIR = Struct(">II")
MAIN_FIELDS = tuple(range(0x08, 0x50, 8))
TAIL_FIELDS = tuple(range(0x1C0, 0x240, 8))
REGION_FIELDS = (0x240, 0x248, 0x250)
BLOCK = 0x4000
FILES = ("INIT.SDL", "MTOC.SDL", "BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")


class EvidenceError(ValueError):
    pass


def pair_at(data: bytes, at: int) -> dict:
    if at < 0 or at + PAIR.size > len(data):
        raise EvidenceError(f"Descriptor beyond INIT at 0x{at:X}")
    start, length = PAIR.unpack_from(data, at)
    if length <= 0 or start >= len(data) or length > len(data) - start:
        raise EvidenceError(f"Invalid descriptor at 0x{at:X}: 0x{start:X}+0x{length:X}")
    blob = data[start:start + length]
    return {"at": at, "offset": start, "length": length, "end": start + length,
            "sha256": sha256(blob).hexdigest(), "nonzero": sum(b != 0 for b in blob)}


def copy_refs(init: bytes, region: bytes, destinations: list[dict]) -> list[dict]:
    result = []
    for target in destinations:
        dest = target["offset"]
        fragment = init[dest:dest + BLOCK]
        if len(fragment) != BLOCK:
            raise EvidenceError("Partial INIT regional fragment")
        matches = []
        for start in range(0x2000, len(region) - BLOCK + 1, BLOCK):
            if fragment == region[start:start + BLOCK]:
                source_id = int.from_bytes(fragment[0:4], "big") & 0xFFFFFF
                matches.append({"source": start, "bytes": BLOCK,
                                "source_id_matches": source_id * 256 == start})
        result.append({"destination": dest, "matches": matches})
    return result


def analyze_release(files: dict[str, bytes], strict: bool = True) -> dict:
    if any(k not in files for k in ("INIT.SDL", "MTOC.SDL", "BENELUX0.SDL")):
        raise EvidenceError("INIT, MTOC and BENELUX0 donor files required")
    init, mtoc, benelux = files["INIT.SDL"], files["MTOC.SDL"], files["BENELUX0.SDL"]
    main = [pair_at(init, n) for n in MAIN_FIELDS]
    trailing = [pair_at(init, n) for n in TAIL_FIELDS]
    regional = [pair_at(init, n) for n in REGION_FIELDS]
    m = {p["at"]: p for p in main}
    chain = [m[0x40], m[0x48], *trailing]
    copies = copy_refs(init, benelux, regional)
    checks = {
        "INIT_file_length_BE32": int.from_bytes(init[:4], "big") == len(init),
        "catalog_start_and_length": (m[0x08]["offset"], m[0x08]["length"]) == (0x12000, 0x94C),
        "INIT_catalog_matches_MTOC": init[0x12000:0x1294C] == mtoc[:0x94C],
        "first_reference_chain": (m[0x10]["end"] == m[0x18]["offset"] and
                                   m[0x18]["end"] == m[0x20]["offset"] and
                                   m[0x20]["end"] == regional[0]["offset"]),
        "catalog_end_to_following": m[0x08]["end"] == m[0x38]["offset"],
        "catalog_tail_to_next": m[0x38]["end"] == m[0x30]["offset"],
        "large_span_ends_at_pointer_0x40": m[0x28]["end"] == m[0x40]["offset"],
        "long_descriptor_chain": all(a["end"] == b["offset"] for a, b in pairwise(chain)),
        "alternating_0x19c_0x1800": [x["length"] for x in chain] == [0x19C, 0x1800] * 9,
        "file_tail_padding_0x184": len(init) - chain[-1]["end"] == 0x184,
        "INIT_0x1800_exactly_duplicated": init[0x800:0x2000] == init[0x2000:0x3800],
        "regional_descriptor_chain": ([(p["offset"], p["length"]) for p in regional] ==
                                     [(0x6000, BLOCK), (0xA000, BLOCK), (0xE000, BLOCK)]),
        "regional_sources_exact_and_self_addressed": all(
            len(x["matches"]) == 1 and x["matches"][0]["source_id_matches"] for x in copies),
    }
    if strict and not all(checks.values()):
        raise EvidenceError("INIT layout proof failed: " +
                            ", ".join(k for k, value in checks.items() if not value))
    return {
        "size_bytes": len(init),
        "init_sha256": sha256(init).hexdigest(),
        "unknown_header_word_at_0x04": int.from_bytes(init[4:8], "big"),
        "header_offset_length_candidates": main,
        "long_chain_16_following_descriptors": trailing,
        "three_region_descriptors": regional,
        "region_copy_proofs": copies,
        "interstitial_gap_bytes": m[0x28]["offset"] - m[0x30]["end"],
        "trailing_padding_bytes": len(init) - chain[-1]["end"],
        "checks": checks,
    }


def analyze(donors: dict[str, dict[str, bytes]]) -> dict:
    if len(donors) < 2:
        raise EvidenceError("At least two OEM releases needed")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name) for name in donors):
        raise EvidenceError("Invalid release label")
    entries = {name: analyze_release(donors[name]) for name in sorted(donors)}
    common = []
    for at in range(0x00, 0x50, 4):
        observed = {int.from_bytes(donors[name]["INIT.SDL"][at:at+4], "big")
                    for name in entries}
        if len(observed) == 1:
            common.append({"at": at, "be32": next(iter(observed))})
    return {
        "schema": "oem-init-span-evidence-iter008-v1",
        "source": "original OEM binary bytes, not generated 0.SDL",
        "releases": entries, "common_initial_be32_words": common,
        "limitations": [
            "These fields are observed offsets and lengths; functional names are not proven.",
            "Identical bytes and contiguous spans do not establish OEM boot order.",
            "Authoritative ucaParcelSizes[] remains unidentified.",
            "Never treat copied raw OEM blocks as valid for arbitrary generated data.",
        ],
    }


def markdown(result: dict) -> str:
    labels = sorted(result["releases"])
    lines = ["# Iter008 — INIT byte-span evidence", "",
             "Offset/length candidates are independently checked on all OEM releases.", "",
             "| Descriptor at | " + " | ".join(labels) + " |",
             "|---|" + "---:|" * len(labels)]
    for at in MAIN_FIELDS:
        items = []
        for label in labels:
            p = next(x for x in result["releases"][label]["header_offset_length_candidates"] if x["at"] == at)
            items.append(f"0x{p['offset']:X} + 0x{p['length']:X}")
        lines.append(f"| 0x{at:X} | " + " | ".join(items) + " |")
    lines += ["", "## Repeating chain and cross-file checks", ""]
    for label in labels:
        row = result["releases"][label]
        lines.append(f"### {label}")
        lines.append(f"- 16 trailing descriptors: {len(row['long_chain_16_following_descriptors'])}")
        lines.append(f"- Last end to file EOF: {row['trailing_padding_bytes']} bytes")
        for key, value in row["checks"].items():
            lines.append(f"- {key}: {'PASS' if value else 'FAIL'}")
        for proof in row["region_copy_proofs"]:
            for m in proof["matches"]:
                lines.append(f"- INIT 0x{proof['destination']:X} = BENELUX0 0x{m['source']:X}, "
                             f"16KiB exact, embedded address proof={m['source_id_matches']}")
    lines += ["", "## Limitations", ""] + ["- " + x for x in result["limitations"]]
    return "\n".join(lines) + "\n"


def load(folder: Path) -> dict[str, bytes]:
    if not folder.is_dir():
        raise EvidenceError("OEM directory not found: " + str(folder))
    out = {}
    for name in FILES:
        file = folder / name
        if file.is_file() and not file.is_symlink():
            out[name] = file.read_bytes()
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release", action="append", required=True, metavar="LABEL=DIR")
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--md", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        files = {}
        for item in args.release:
            if "=" not in item:
                raise EvidenceError("Expected LABEL=DIR")
            label, folder = item.split("=", 1)
            if label in files:
                raise EvidenceError("Duplicate release label")
            files[label] = load(Path(folder))
        result = analyze(files)
    except (EvidenceError, OSError) as exc:
        p.exit(2, f"ERROR: {exc}\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.md.write_text(markdown(result), encoding="utf-8")
    print("Validated", len(result["releases"]), "OEM INIT files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

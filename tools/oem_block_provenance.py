#!/usr/bin/env python3
"""Read-only exact-block cross-file provenance for OEM SDL evidence.

Exact matching byte ranges are not proofs of SDAL parcel identity, ownership,
pointer semantics, boot order, or firmware compatibility.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path

DEFAULT_BLOCK_BYTES = 4096


def informative(chunk: bytes, block_bytes: int) -> bool:
    """Reject partial blocks and uniform filler (including 0x00 and 0xFF)."""
    return len(chunk) == block_bytes and len(set(chunk)) > 1


def _runs(pairs: set[tuple[int, int]], block_bytes: int) -> list[dict]:
    remaining = set(pairs)
    result = []
    for i, j in sorted(pairs):
        if (i, j) not in remaining:
            continue
        count = 0
        while (i + count * block_bytes, j + count * block_bytes) in remaining:
            remaining.remove((i + count * block_bytes, j + count * block_bytes))
            count += 1
        result.append({"left_offset": i, "right_offset": j,
                       "block_count": count, "length_bytes": block_bytes * count})
    return sorted(result, key=lambda r: (-r["block_count"], r["left_offset"], r["right_offset"]))


def _first_difference(left: bytes, right: bytes) -> int | None:
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return i
    return min(len(left), len(right)) if len(left) != len(right) else None


def analyze(inputs: dict[str, bytes], *, block_bytes: int = DEFAULT_BLOCK_BYTES) -> dict:
    if block_bytes <= 0:
        raise ValueError("block_bytes must be positive")
    if len(inputs) < 2:
        raise ValueError("At least two SDL files are required")
    if any(not isinstance(blob, bytes) for blob in inputs.values()):
        raise TypeError("Input values must be bytes")
    names = sorted(inputs)
    digests: dict[str, dict[bytes, list[int]]] = {}
    overview = []
    for name in names:
        blob = inputs[name]
        index: dict[bytes, list[int]] = defaultdict(list)
        eligible = 0
        for at in range(0, len(blob) - block_bytes + 1, block_bytes):
            chunk = blob[at:at + block_bytes]
            if informative(chunk, block_bytes):
                index[sha256(chunk).digest()].append(at)
                eligible += 1
        digests[name] = index
        overview.append({"name": name, "size_bytes": len(blob),
                         "sha256": sha256(blob).hexdigest(),
                         "complete_informative_blocks": eligible,
                         "partial_tail_bytes": len(blob) % block_bytes})
    comparisons = []
    for a, b in combinations(names, 2):
        left, right = inputs[a], inputs[b]
        pairs = set()
        for digest in digests[a].keys() & digests[b].keys():
            for i in digests[a][digest]:
                for j in digests[b][digest]:
                    if left[i:i+block_bytes] == right[j:j+block_bytes]:
                        pairs.add((i, j))
        comparisons.append({
            "left": a, "right": b,
            "first_difference_same_offset": _first_difference(left, right),
            "entire_file_identical": left == right,
            "matching_offset_pairs": len(pairs),
            "distinct_matching_left_blocks": len({i for i, _ in pairs}),
            "distinct_matching_right_blocks": len({j for _, j in pairs}),
            "same_offset_matching_blocks": sum(i == j for i, j in pairs),
            "runs": _runs(pairs, block_bytes),
        })
    return {
        "schema": "sdal-oem-exact-block-provenance/iter002-v1",
        "status": "byte_level_observations_only",
        "block_bytes": block_bytes,
        "selection": "full_length_blocks_with_more_than_one_distinct_byte",
        "files": overview, "comparisons": comparisons,
        "cautions": [
            "Exact block reuse does not prove shared parcel or runtime reference.",
            "Uniform and partial blocks are omitted from cross-file matches.",
            "Runs group consecutive file byte offsets; no SDAL interpretation.",
            "The seven-file corpus cannot establish OEM boot order or ISO layout.",
        ],
    }


def read_paths(paths: list[Path]) -> dict[str, bytes]:
    if len(paths) < 2:
        raise ValueError("At least two paths are required")
    result = {}
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Expected regular OEM file: {path}")
        if path.name in result:
            raise ValueError(f"Duplicate filename: {path.name}")
        result[path.name] = path.read_bytes()
    return result


def markdown(report: dict) -> str:
    lines = ["# OEM SDL — exact block provenance (Iter002)", "",
             "Read-only byte comparison, not SDAL structure validation.", "",
             f"Block size: {report['block_bytes']} bytes; non-uniform full blocks only.",
             "", "## Pairwise comparisons", "",
             "| Left | Right | Identical file | Block pairs | Same-offset pairs | First differing byte |",
             "|---|---|---|---:|---:|---:|"]
    for pair in report["comparisons"]:
        lines.append("| `{left}` | `{right}` | {entire_file_identical} | {matching_offset_pairs} | {same_offset_matching_blocks} | {first_difference_same_offset} |".format(**pair))
    lines += ["", "## Contiguous exact runs", ""]
    for pair in report["comparisons"]:
        if not pair["runs"]:
            continue
        lines.append(f"### {pair['left']} ↔ {pair['right']}")
        for r in pair["runs"]:
            lines.append("- left `0x{left_offset:X}` ↔ right `0x{right_offset:X}`, {block_count} blocks ({length_bytes} bytes)".format(**r))
        lines.append("")
    lines += ["## Interpretation restrictions", ""] + ["- " + s for s in report["cautions"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--block-bytes", type=int, default=DEFAULT_BLOCK_BYTES)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = analyze(read_paths(args.paths), block_bytes=args.block_bytes)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    args.output_md.write_text(markdown(report), encoding="utf-8")
    print(f"Analyzed {len(report['files'])} files and {len(report['comparisons'])} file pairs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

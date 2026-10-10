#!/usr/bin/env python3
"""Coverage ledger for all genuine OEM type-255 Global KD-tree roots.

Classifies exact two-byte 0x1000 leaf records independently of any
heuristic node graph parser. Larger roots are deliberately retained
as unclassified until all child-link encodings can be proven.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from oem_kd_graph_integrity import read_indexes, validate_initial_tree, GraphError

SINGLETON_LEAF = b"\x10\x00"


def inspect_map(path: Path) -> dict:
    indexes = read_indexes(path)
    if not indexes:
        raise GraphError("No real OEM type-255 index parcel found")
    root_zero = validate_initial_tree(indexes)
    totals = Counter()
    complex_roots = []
    file_size = path.stat().st_size
    for index_id, index in enumerate(indexes):
        locations = index["root_offsets"]
        buf = index["blob"]
        for tree_id, start in enumerate(locations):
            end = locations[tree_id + 1] if tree_id+1 < len(locations) else len(buf)
            raw = buf[start:end]
            if not raw:
                raise GraphError("Empty root in OEM root-offset table")
            if len(raw) == 2 and raw == SINGLETON_LEAF:
                totals["verified_singleton_0x1000"] += 1
            else:
                totals["unclassified_multibyte_root"] += 1
                initial_control = int.from_bytes(raw[:2], "big") if len(raw) >= 2 else None
                ff_tail = len(raw) - len(raw.rstrip(b"\xff"))
                complex_roots.append({
                    "index": index_id, "tree": tree_id,
                    "root_bytes_including_possible_padding": len(raw),
                    "initial_be16_control_candidate": (
                        f"0x{initial_control:04X}" if initial_control is not None else None),
                    "possible_trailing_ff_padding_bytes": ff_tail,
                    "sha256": sha256(raw).hexdigest(),
                    "is_fully_validated_first_root": index_id == 0 and tree_id == 0,
                })
            totals["root_total"] += 1
    assert totals["root_total"] == sum(x["root_count"] for x in indexes)
    return {
        "file": path.name,
        "bytes": file_size,
        "index_parcel_count": len(indexes),
        "root_counts": [x["root_count"] for x in indexes],
        "coverage": dict(totals),
        "verified_first_root_graph": root_zero,
        "unclassified_multibyte_roots": complex_roots,
        "unclassified_initial_control_distribution": dict(sorted(Counter(
            item["initial_be16_control_candidate"] for item in complex_roots).items())),
        "limitations": [
            "A 0x1000 two-byte root is a structurally empty leaf; its spatial role is not proven.",
            "All multi-byte roots except first index/root are explicitly not validated here.",
            "Last-root slices may contain 0xFF parcel padding: reported lengths are upper bounds.",
            "No claim that the present OSM generator serializes this KD-tree representation.",
        ],
    }


def analyze(files: dict[str, Path]) -> dict:
    if not files:
        raise GraphError("No OEM map provided")
    results = {name: inspect_map(path) for name, path in sorted(files.items())}
    return {
        "schema": "sdal-iter014-kd-root-coverage-v1",
        "source": "verified source root boundary arrays",
        "maps": results,
        "combined": {
            "index_parcels": sum(v["index_parcel_count"] for v in results.values()),
            "roots": sum(v["coverage"]["root_total"] for v in results.values()),
            "verified_singleton_roots": sum(
                v["coverage"]["verified_singleton_0x1000"] for v in results.values()),
            "complex_roots_still_unclassified": sum(
                v["coverage"]["unclassified_multibyte_root"] for v in results.values()),
        },
    }


def markdown(r: dict) -> str:
    lines = ["# Iter014 — global KD-tree root coverage ledger", "",
             "Only source-proven two-byte leaf roots and first-root graph are validated.",
             "", "| Map | Index parcels | Roots | Exact 0x1000 leaf | Other roots |",
             "|---|---:|---:|---:|---:|"]
    for name, item in r["maps"].items():
        c = item["coverage"]
        lines.append(f"| {name} | {item['index_parcel_count']} | {c['root_total']} | "
                     f"{c['verified_singleton_0x1000']} | "
                     f"{c['unclassified_multibyte_root']} |")
    lines += ["", "## Remaining work", "",
              "The 0x1000 control code has no child-offset or parcel-descriptor flags.",
              "All larger records remain a separate decoding problem; do not pass",
              "them through the simple-leaf interpretation.",
              "The first larger root on each map was independently graph-validated in Iter013."]
    return "\n".join(lines)+"\n"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", action="append", required=True, metavar="LABEL=FILE")
    p.add_argument("--json", type=Path, required=True)
    p.add_argument("--md", type=Path, required=True)
    a = p.parse_args()
    try:
        paths = {}
        for raw in a.map:
            if "=" not in raw:
                raise GraphError("Expected LABEL=FILE")
            name, fname = raw.split("=",1)
            if not name or name in paths:
                raise GraphError("Blank or duplicate map label")
            paths[name] = Path(fname)
        result = analyze(paths)
    except (GraphError, OSError) as e:
        p.exit(2, "ERROR: "+str(e)+"\n")
    a.json.parent.mkdir(parents=True,exist_ok=True)
    a.md.parent.mkdir(parents=True,exist_ok=True)
    a.json.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    a.md.write_text(markdown(result),encoding="utf-8")
    print("Analyzed", result["combined"]["roots"], "indexed OEM KD-tree roots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

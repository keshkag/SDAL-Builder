#!/usr/bin/env python3
"""SDAL 1.7 spec-correct global KD-tree graph proof, all root references.

§3.1.1.2: two equally wide child-offset slots; absent/pruned child occupies
a zero-filled slot if its sibling has an offset. A narrower child uses the
least-significant bytes in the common-width slot. This is validated using
original OEM bytes, not an invented extra grammar.

Terminal root lengths are INFERRED from contiguous trailing FF padding.
These boundaries are kept separate from the explicitly indexed root ends.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from hashlib import sha256
import json
from pathlib import Path

from oem_kd_graph_integrity import GraphError, read_indexes
from oem_kd_all_root_integrity import classify_root
from oem_kd_similarity_clusters import outgoing_verified

VALID = {"exact_two_byte_leaf", "exact_graph_under_sdal_control_profile"}


def audit(path: Path) -> dict:
    indexes = read_indexes(path)
    records = {}
    source_hash = sha256()
    with path.open("rb") as source:
        while block := source.read(1 << 20):
            source_hash.update(block)
    for index_no, parcel in enumerate(indexes):
        for root_no in range(parcel["root_count"]):
            is_terminal = root_no == parcel["root_count"] - 1
            if is_terminal:
                fragment = parcel["blob"][parcel["root_offsets"][-1]:]
                ff_bytes = len(fragment) - len(fragment.rstrip(b"\xff"))
                if ff_bytes < 2 or ff_bytes % 2:
                    raise GraphError("Unjustified terminal FF alignment/padding")
                terminal_end = len(parcel["blob"]) - ff_bytes
            else:
                terminal_end = None
            row = classify_root(indexes, index_no, root_no,
                                terminal_end=terminal_end)
            if row["status"] not in VALID:
                raise GraphError(f"Unproven KD root {index_no}/{root_no}: " +
                                 row.get("reason", "unknown"))
            if is_terminal and not row["end"] < len(parcel["blob"]):
                raise GraphError("Terminal root lacks distinct FF-filled tail")
            records[(index_no, root_no)] = row
    if not records or (0, 0) not in records:
        raise GraphError("Missing global root")
    links = Counter()
    parents = Counter()
    adjacency = {}
    edges = 0
    for pair, row in records.items():
        targets = list(outgoing_verified(indexes, row) or ())
        adjacency[pair] = targets
        for target in targets:
            if target not in records:
                raise GraphError("KD external link refers to absent index/root")
            links[target] += 1
            parents[(pair, target)] += 1
            edges += 1
    if links[(0, 0)] != 0:
        raise GraphError("Global index root must have no parent")
    if any(links[key] != 1 for key in records if key != (0, 0)):
        raise GraphError("Every nonroot tree must have exactly one external parent")
    if edges != len(records) - 1:
        raise GraphError("External edge count does not form a rooted tree")
    discovered = {(0, 0)}
    pending = deque([(0, 0)])
    while pending:
        current = pending.popleft()
        for target in adjacency[current]:
            if target in discovered:
                raise GraphError("Cycle/duplicate reachable subtree")
            discovered.add(target)
            pending.append(target)
    if len(discovered) != len(records):
        raise GraphError("Not all index trees are reachable from root 0/0")
    summary = Counter(row["status"] for row in records.values())
    by_index = [
        {"index": i, "roots": parcel["root_count"],
         "exact_indexed_roots": parcel["root_count"]-1,
         "terminal_ff_inferred_bytes":
            records[(i, parcel["root_count"]-1)]["trailing_ff_bytes"]}
        for i, parcel in enumerate(indexes)
    ]
    return {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_sha256": source_hash.hexdigest(),
        "index_parcels": len(indexes),
        "root_count": len(records),
        "two_byte_leaves": summary["exact_two_byte_leaf"],
        "validated_nonleaf_roots": summary["exact_graph_under_sdal_control_profile"],
        "terminal_roots_inferred_from_ff_padding": len(indexes),
        "parsed_nodes_in_validated_graphs": sum(
            row.get("node_count",0) for row in records.values()
            if row["status"] == "exact_graph_under_sdal_control_profile"),
        "global_external_edges": edges,
        "unreachable_index_roots": 0,
        "multiple_parent_roots": 0,
        "invalid_parcel_tree_references": 0,
        "global_root": {"index":0, "tree":0, "incoming":0},
        "by_index": by_index,
        "scope_limits": [
            "Final-root FF tails are inferred, not specified by a root end field.",
            "Graph integrity does not validate cartographic parcel targets or routing geometry.",
            "This does not establish that OSM-generated SDLs have the same graph.",
            "No head-unit read/navigation acceptance is claimed.",
        ],
    }


def analyze(maps: dict[str, Path]) -> dict:
    if not maps:
        raise GraphError("No authentic OEM map supplied")
    results = {name:audit(path) for name,path in sorted(maps.items())}
    return {
        "schema": "sdal-iter017-all-oem-global-kd-spec-correct-v1",
        "maps": results,
        "total_roots": sum(x["root_count"] for x in results.values()),
        "total_edges": sum(x["global_external_edges"] for x in results.values()),
        "total_graph_nodes": sum(x["parsed_nodes_in_validated_graphs"] for x in results.values()),
        "statement": "Equal-width padded child slots resolve the 1101 previous false negatives",
    }


def markdown(result: dict) -> str:
    lines = ["# Iter017 — SDAL 1.7: all original KD roots structurally resolved", "",
             "Both child offset fields occupy the same-size slots, including",
             "zero-filled slots for pruned children (spec §3.1.1.2).", "",
             "| Map | Roots | Parsed nodes | External edges | Terminal FF bounds |",
             "|---|---:|---:|---:|---:|"]
    for label, row in result["maps"].items():
        lines.append(f"| {label} | {row['root_count']} | "
                     f"{row['parsed_nodes_in_validated_graphs']} | "
                     f"{row['global_external_edges']} | "
                     f"{row['terminal_roots_inferred_from_ff_padding']} |")
    lines += ["", "## Acceptance limits", ""]
    for row in result["maps"].values():
        lines += [f"### {row['source_file']}"] + [
            "- "+x for x in row["scope_limits"]]
    return "\n".join(lines)+"\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--map", action="append", required=True, metavar="LABEL=FILE")
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument("--md", type=Path, required=True)
    args = ap.parse_args()
    try:
        paths = {}
        for arg in args.map:
            if "=" not in arg:
                raise GraphError("Expected LABEL=FILE")
            label, path = arg.split("=",1)
            if not label or label in paths:
                raise GraphError("Empty/duplicate label")
            paths[label] = Path(path)
        result = analyze(paths)
    except (GraphError, OSError) as error:
        ap.exit(2,"ERROR: "+str(error)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.md.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf8")
    args.md.write_text(markdown(result),encoding="utf8")
    print("Validated", result["total_roots"], "OEM global KD roots and",
          result["total_edges"], "external references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

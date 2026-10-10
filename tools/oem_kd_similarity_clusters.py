#!/usr/bin/env python3
"""Compare authentic OEM KD-root families and their proven incoming links.

Never auto-decodes ambiguous roots. The output only contains metadata,
root identifiers, SHA-256 and control codes, not copyrighted OEM payload.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import json
from pathlib import Path

from oem_kd_all_root_integrity import classify_root
from oem_kd_graph_integrity import GraphError, parse_node, read_indexes

STATUS_FAMILY = {
    "exact_two_byte_leaf": "A_exact_1000_leaf",
    "exact_graph_under_sdal_control_profile": "verified_graph",
    "unresolved_node_encoding": "unresolved",
    "terminal_boundary_undetermined": "Z_terminal_unbounded",
}
REASON_FAMILY = {
    "nonforward_local_reference": "F_zero_or_reverse_local_edge",
    "root_node_gaps_or_overlaps": "G_node_boundary_conflict",
    "root_bytes_not_fully_covered": "G_node_boundary_conflict",
    "unrecognized_node_record": "H_descriptor_or_node_parse_failure",
    "local_target_outside_root": "J_out_of_range_edge",
    "external_tree_target_missing": "J_out_of_range_edge",
    "local_edges_do_not_form_tree": "K_invalid_topology",
    "local_edges_have_multiple_parents": "K_invalid_topology",
    "node_budget_exceeded": "K_invalid_topology",
    "nonprogressing_node": "K_invalid_topology",
}


def family(row: dict) -> str:
    status = row["status"]
    if status == "exact_graph_under_sdal_control_profile":
        return ("B_single_node_descriptor_record" if row["node_count"] == 1
                else "C_multinode_tree")
    if status == "unresolved_node_encoding":
        return REASON_FAMILY.get(row["reason"], "Y_other_unresolved")
    return STATUS_FAMILY[status]


def control_signature(value: int) -> str:
    """MSB-first SDAL 1.7 control bits, independent of spatial cut value."""
    return (f"L{(value >> 6) & 3}R{(value >> 4) & 3}"
            f"_I{(value >> 2) & 3}"
            f"_D{1 if value & 0x8000 else 0}{1 if value & 0x4000 else 0}")


def outgoing_verified(indexes: list[dict], record: dict):
    """Cross-index links only from roots already proven by the strict graph test."""
    if record["status"] != "exact_graph_under_sdal_control_profile":
        return
    i = record["index_parcel"]
    blob = indexes[i]["blob"]
    start = record["start"]
    end = record["end"]
    to_visit = deque([start])
    seen = set()
    while to_visit:
        pos = to_visit.popleft()
        if pos in seen:
            continue
        seen.add(pos)
        node = parse_node(blob, pos, end)
        for edge in node["edges"]:
            if edge["mode"] == "external":
                target = (edge["index_delta"], edge["tree_id"])
                if (target[0] >= len(indexes)
                        or target[1] >= indexes[target[0]]["root_count"]):
                    raise GraphError("Previously verified external target no longer exists")
                yield target
            else:
                to_visit.append(edge["target"])
    if len(seen) != record["node_count"]:
        raise GraphError("Verified graph changed its reachable node count")


def inspect_map(path: Path) -> dict:
    indexes = read_indexes(path)
    records = [
        classify_root(indexes, i, root)
        for i, entry in enumerate(indexes)
        for root in range(entry["root_count"])
    ]
    by_id = {(r["index_parcel"], r["tree_id"]): r for r in records}
    families, signatures, index_groups = Counter(), defaultdict(Counter), defaultdict(Counter)
    ambiguity_controls, zero_val = Counter(), Counter()
    for record in records:
        status = family(record)
        families[status] += 1
        word = int(record["first_control_be16"], 16)
        signatures[control_signature(word)][status] += 1
        index_groups[record["index_parcel"]][status] += 1
        if status.startswith("F_"):
            ambiguity_controls[record["first_control_be16"]] += 1
    incoming = Counter()
    provenance = defaultdict(Counter)
    external_total = 0
    source_graphs = 0
    for record in records:
        src = (record["index_parcel"], record["tree_id"])
        if record["status"] != "exact_graph_under_sdal_control_profile":
            continue
        source_graphs += 1
        for target in outgoing_verified(indexes, record):
            incoming[target] += 1
            provenance[target][src] += 1
            external_total += 1
    leaf_refs = [incoming[(r["index_parcel"], r["tree_id"])]
                 for r in records if r["status"] == "exact_two_byte_leaf"]
    if len(leaf_refs) != families["A_exact_1000_leaf"]:
        raise GraphError("Missing singleton-root accounting")
    incoming_by_family, inbound_targets_by_family = Counter(), Counter()
    frontier = []
    for target, count in sorted(incoming.items()):
        rec = by_id[target]
        kind = family(rec)
        incoming_by_family[kind] += count
        inbound_targets_by_family[kind] += 1
        if rec["status"] in ("unresolved_node_encoding",
                             "terminal_boundary_undetermined"):
            frontier.append({
                "index": target[0], "tree": target[1],
                "family": kind, "incoming_edges": count,
                "from_verified_roots": [
                    {"index": src[0], "tree": src[1], "edges": n}
                    for src, n in sorted(provenance[target].items())],
                "root_size_bytes": rec["bytes_including_possible_padding"],
                "initial_control_be16": rec["first_control_be16"],
                "initial_control_signature": control_signature(
                    int(rec["first_control_be16"], 16)),
                "failure_reason": rec.get("reason"),
                "root_sha256": rec["source_sha256"],
            })
    if sum(incoming_by_family.values()) != external_total:
        raise GraphError("External KD reference count mismatch")
    grouped = []
    for code, counts in signatures.items():
        total = sum(counts.values())
        grouped.append({"control_signature": code, "roots": total,
                        "families": dict(sorted(counts.items()))})
    grouped.sort(key=lambda row: (-row["roots"], row["control_signature"]))
    return {
        "file": path.name,
        "index_parcels": len(indexes),
        "root_total": len(records),
        "family_counts": dict(sorted(families.items())),
        "control_families": grouped,
        "per_index_family_counts": [
            {"index": i, "root_count": indexes[i]["root_count"],
             "families": dict(sorted(index_groups[i].items()))}
            for i in range(len(indexes))],
        "verified_graph_roots": source_graphs,
        "verified_graph_external_edges": external_total,
        "singleton_roots_targeted_exactly_once": sum(n == 1 for n in leaf_refs),
        "singleton_roots_without_verified_parent": sum(n == 0 for n in leaf_refs),
        "singleton_roots_with_multiple_verified_parents": sum(n > 1 for n in leaf_refs),
        "verified_edges_by_target_family": dict(sorted(incoming_by_family.items())),
        "distinct_referenced_roots_by_family": dict(sorted(inbound_targets_by_family.items())),
        "unresolved_frontier_from_verified_graphs": frontier,
        "zero_or_backward_initial_control_frequency": [
            {"word": k, "roots": n}
            for k, n in ambiguity_controls.most_common()],
        "caveat": "Classification is byte/graph evidence, not spatial or routing semantics.",
    }


def compare(sources: dict[str, Path]) -> dict:
    if not sources:
        raise GraphError("At least one OEM map required")
    maps = {label: inspect_map(path) for label, path in sorted(sources.items())}
    families = Counter()
    for source in maps.values():
        families.update(source["family_counts"])
    return {
        "schema": "sdal-iter016-kd-similarity-clusters-v1",
        "maps": maps,
        "combined": {
            "root_total": sum(m["root_total"] for m in maps.values()),
            "family_counts": dict(sorted(families.items())),
            "confirmed_singleton_roots_with_one_parent": sum(
                m["singleton_roots_targeted_exactly_once"] for m in maps.values()),
            "verified_external_edges": sum(
                m["verified_graph_external_edges"] for m in maps.values()),
            "unresolved_frontier_roots": sum(
                len(m["unresolved_frontier_from_verified_graphs"]) for m in maps.values()),
        },
        "limitations": [
            "Grouping by control word is diagnostic, not proof of additional encoding classes.",
            "Only previously verified graph nodes contribute links; unknown roots may have more.",
            "The index/tree target pair does not prove spatial or routing semantics.",
            "Zero offsets are not silently reinterpreted as pruned child references.",
            "No new production map encoding or ISO modifications are made.",
        ],
    }


def markdown(report: dict) -> str:
    lines = ["# Iter016 — OEM KD-root similarity and reference clusters", "",
             "Original byte evidence, fail-closed root classification.", "",
             "| Group | " + " | ".join(report["maps"]) + " |",
             "|---|" + "---:|" * len(report["maps"])]
    kinds = sorted(set().union(*(m["family_counts"] for m in report["maps"].values())))
    for kind in kinds:
        lines.append("| " + kind + " | " + " | ".join(
            str(m["family_counts"].get(kind, 0))
            for m in report["maps"].values()) + " |")
    lines += ["", "## Verified external reference links", ""]
    for label, row in report["maps"].items():
        lines += [f"### {label}",
                  f"- From verified graphs: {row['verified_graph_external_edges']} links",
                  f"- Singleton roots with exactly one verified incoming link: "
                  f"{row['singleton_roots_targeted_exactly_once']}",
                  f"- Unresolved or unbounded target roots: "
                  f"{len(row['unresolved_frontier_from_verified_graphs'])}",
                  f"- Breakdown by target family: {row['verified_edges_by_target_family']}",
                  "", "### Most frequent control signatures", ""]
        for item in row["control_families"][:12]:
            lines.append(f"- {item['control_signature']}: "
                         f"{item['roots']} roots, {item['families']}")
    lines += ["", "## Important limits", ""] + [
        "- " + limit for limit in report["limitations"]]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", required=True, metavar="LABEL=FILE")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    sources = {}
    try:
        for spec in args.map:
            if "=" not in spec:
                raise GraphError("Map argument must be LABEL=FILE")
            label, path = spec.split("=", 1)
            if not label or label in sources:
                raise GraphError("Empty or duplicate map label")
            sources[label] = Path(path)
        result = compare(sources)
    except (GraphError, OSError) as err:
        parser.exit(2, "ERROR: " + str(err) + "\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    args.md.write_text(markdown(result), encoding="utf-8")
    print("Clustered", result["combined"]["root_total"],
          "OEM KD roots without accepting ambiguous formats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

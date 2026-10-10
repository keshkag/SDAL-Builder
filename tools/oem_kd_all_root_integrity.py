#!/usr/bin/env python3
"""Evidence-limited full-corpus OEM KD root audit (SDAL 1.7).

Every root is accounted for. Only exact singleton leaves and roots whose
whole bounded byte range forms one forward-linked KD node tree are accepted.
Last-root padding is intentionally unresolved rather than guessed away.
Unknown records never become silently 'compatible' records.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from hashlib import sha256
import json
from pathlib import Path

from oem_kd_graph_integrity import GraphError, parse_node, read_indexes

LEAF = b"\x10\x00"
LIMIT_NODES = 15000


def classify_root(indexes: list[dict], parcel_number: int, root_number: int,
                  *, terminal_end: int | None = None) -> dict:
    parcel = indexes[parcel_number]
    starts = parcel["root_offsets"]
    start = starts[root_number]
    last = root_number + 1 == len(starts)
    end = (starts[root_number + 1] if not last
           else terminal_end if terminal_end is not None else len(parcel["blob"]))
    if end <= start or end > len(parcel["blob"]):
        raise GraphError("Invalid authenticated/inferred root boundary")
    blob = parcel["blob"]
    raw = blob[start:end]
    if len(raw) < 2:
        raise GraphError("A root is shorter than the two-byte KD control record")
    base = {
        "index_parcel": parcel_number,
        "tree_id": root_number,
        "start": start, "end": end, "bytes_including_possible_padding": len(raw),
        "source_sha256": sha256(raw).hexdigest(),
        "first_control_be16": f"0x{int.from_bytes(raw[:2], 'big'):04X}",
    }
    if last and terminal_end is None:
        # Last root lacks an explicit end. Preserve this uncertainty unless
        # caller supplies a separately justified/checked bound. Never make
        # an inference by default in generic SDAL format decoding.
        return {**base, "status": "terminal_boundary_undetermined",
                "reason": "last U16 root has no authenticated content end",
                "trailing_ff_bytes": len(raw) - len(raw.rstrip(b"\xff"))}
    if last:
        base["terminal_bound_inferred_from_trailing_ff"] = True
        base["trailing_ff_bytes"] = len(parcel["blob"]) - end
    if raw == LEAF:
        return {**base, "status": "exact_two_byte_leaf",
                "node_count": 1, "local_edges": 0, "external_edges": 0}
    queue = deque([start])
    decoded = {}
    local = []
    external = []
    reason = None
    while queue:
        address = queue.popleft()
        if address in decoded:
            continue
        if address < start or address >= end:
            reason = "local_target_outside_root"
            break
        if len(decoded) >= LIMIT_NODES:
            reason = "node_budget_exceeded"
            break
        try:
            node = parse_node(blob, address, end)
        except (GraphError, ValueError, IndexError):
            reason = "unrecognized_node_record"
            break
        if node["end"] <= address:
            reason = "nonprogressing_node"
            break
        decoded[address] = node
        for edge in node["edges"]:
            if edge["mode"] == "external":
                i, tree = edge["index_delta"], edge["tree_id"]
                if i >= len(indexes) or tree >= len(indexes[i]["root_offsets"]):
                    reason = "external_tree_target_missing"
                    break
                external.append((i, tree))
            else:
                target = edge["target"]
                if target <= address:
                    reason = "nonforward_local_reference"
                    break
                if target < start or target >= end or target % 2:
                    reason = "local_target_outside_root"
                    break
                local.append((address, target))
                if target not in decoded:
                    queue.append(target)
        if reason:
            break
    if not reason:
        locations = sorted(decoded)
        if (not locations or locations[0] != start
                or decoded[locations[-1]]["end"] != end):
            reason = "root_bytes_not_fully_covered"
        elif any(decoded[a]["end"] != b for a, b in zip(locations, locations[1:])):
            reason = "root_node_gaps_or_overlaps"
        elif len(local) != len(decoded) - 1:
            reason = "local_edges_do_not_form_tree"
        else:
            incoming = Counter(dst for _, dst in local)
            if (incoming[start] or
                    any(incoming[address] != 1 for address in locations[1:])):
                reason = "local_edges_have_multiple_parents"
    if reason:
        return {**base, "status": "unresolved_node_encoding",
                "reason": reason,
                "decoded_nodes_before_failure": len(decoded)}
    return {
        **base, "status": "exact_graph_under_sdal_control_profile",
        "node_count": len(decoded),
        "local_edges": len(local),
        "external_edges": len(external),
        "distinct_external_tree_targets": len(set(external)),
        "descriptor_pairs": sum(len(node["descriptors"]) for node in decoded.values()),
    }


def audit(path: Path) -> dict:
    indexes = read_indexes(path)
    entries = [
        classify_root(indexes, parcel_id, tree_id)
        for parcel_id, parcel in enumerate(indexes)
        for tree_id in range(len(parcel["root_offsets"]))
    ]
    status = Counter(row["status"] for row in entries)
    reasons = Counter(row["reason"] for row in entries if row["status"] !=
                      "exact_graph_under_sdal_control_profile" and "reason" in row)
    verified = status["exact_two_byte_leaf"] + status["exact_graph_under_sdal_control_profile"]
    if verified + status["terminal_boundary_undetermined"] + status["unresolved_node_encoding"] != len(entries):
        raise GraphError("Root accounting mismatch")
    whole_hash = sha256()
    with path.open("rb") as source:
        for fragment in iter(lambda: source.read(1 << 20), b""):
            whole_hash.update(fragment)
    return {
        "source_file": path.name,
        "source_size": path.stat().st_size,
        "source_sha256": whole_hash.hexdigest(),
        "index_parcels": len(indexes),
        "index_root_counts": [len(p["root_offsets"]) for p in indexes],
        "root_total": len(entries),
        "strictly_covered_roots": verified,
        "status_counts": dict(sorted(status.items())),
        "unresolved_reason_counts": dict(sorted(reasons.items())),
        "verified_graph_nodes": sum(row.get("node_count", 0) for row in entries
                                    if row["status"] == "exact_graph_under_sdal_control_profile"),
        "verified_graph_external_edges": sum(row.get("external_edges", 0)
                                             for row in entries),
        "entries": entries,
        "qualifications": [
            "Last root of each parcel has no authenticated end; FF is padding candidate only.",
            "Passing a structural parse does not establish correct geography or KD cut semantics.",
            "Unresolved records are not accepted as valid trees.",
            "Parcel reference descriptors and target map payloads remain separately unvalidated.",
        ],
    }


def compare(sources: dict[str, Path]) -> dict:
    if not sources:
        raise GraphError("At least one original OEM map is required")
    result = {label: audit(path) for label, path in sorted(sources.items())}
    counts = Counter()
    for item in result.values():
        counts.update(item["status_counts"])
    return {
        "schema": "sdal-iter015-full-root-audit-v1",
        "maps": result,
        "combined_root_count": sum(r["root_total"] for r in result.values()),
        "combined_status_counts": dict(sorted(counts.items())),
        "limitation": "Strict graph evidence applies only to root spans with exact U16 boundaries",
    }


def markdown(result: dict) -> str:
    lines = ["# Iter015 — strict KD-root coverage across authentic maps", "",
             "Failure is evidence: unresolved records are explicitly not decoded.",
             "", "| Map | Roots | Exact leaves | Exact graph spans | Unknown | Last-root boundary unknown |",
             "|---|---:|---:|---:|---:|---:|"]
    for label, item in result["maps"].items():
        c = item["status_counts"]
        lines.append(f"| {label} | {item['root_total']} | "
                     f"{c.get('exact_two_byte_leaf',0)} | "
                     f"{c.get('exact_graph_under_sdal_control_profile',0)} | "
                     f"{c.get('unresolved_node_encoding',0)} | "
                     f"{c.get('terminal_boundary_undetermined',0)} |")
    for label, item in result["maps"].items():
        lines.extend(["", f"## {label} — unresolved evidence", ""])
        lines.extend(f"- {key}: {value}" for key, value in item["unresolved_reason_counts"].items())
    lines.extend(["", "## Limits", "",
                  "- Exact graphs here mean complete byte partition, in-bound local edges, "
                  "single parent and valid external index/tree IDs.",
                  "- The semantic meaning of KD tree cuts and referenced parcels is NOT proven.",
                  "- No production OSM serializer or ISO change is introduced in this iteration."])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", required=True, metavar="LABEL=FILE")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    try:
        sources = {}
        for item in args.map:
            if "=" not in item:
                raise GraphError("Expected LABEL=FILE")
            label, path = item.split("=", 1)
            if not label or label in sources:
                raise GraphError("Empty or duplicate map name")
            sources[label] = Path(path)
        result = compare(sources)
    except (GraphError, OSError) as error:
        parser.exit(2, "ERROR: " + str(error) + "\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.md.write_text(markdown(result), encoding="utf-8")
    print("Classified", result["combined_root_count"], "OEM KD roots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

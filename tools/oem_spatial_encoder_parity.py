#!/usr/bin/env python3
"""Original-OEM acceptance evidence for the production SDAL KD-node writer.

Proof points:
  - every OEM KD node can decode and *re-encode byte-for-byte*;
  - every typed Parcel Descriptor has a validated 5-byte representation;
  - every direct referenced parcel header is checked against PID/type/region.
Ten genuine SWIAUS1 maneuver anomalies must stay visible, never corrected
by guesses, and are rejected in generated-output strict mode.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.oem_kd_codec import (
    CodecError, decode_kd_node, encode_kd_node, verify_direct_spatial_target,
)
from oem_kd_graph_integrity import GraphError, read_indexes
from oem_kd_complete_graph import audit as audit_complete_graph


def audit(path: Path, *, strict_targets: bool = False) -> dict:
    if path.is_symlink() or not path.is_file():
        raise GraphError("Expected original regular .SDL file")
    graph = audit_complete_graph(path)
    indexes = read_indexes(path)
    totals = Counter()
    typed = Counter()
    layered = Counter()
    reasons = Counter()
    bad = []
    pids = set()
    with path.open("rb") as source:
        for ix, index in enumerate(indexes):
            data, roots = index["blob"], index["root_offsets"]
            for root_id, start in enumerate(roots):
                terminal = root_id == len(roots)-1
                if terminal:
                    rest = data[start:]
                    padding = len(rest) - len(rest.rstrip(b"\xff"))
                    if not padding or padding % 2:
                        raise GraphError("Unproven terminal root padding")
                    end = len(data)-padding
                else:
                    end = roots[root_id+1]
                pending = deque([start])
                seen = set()
                covered = {}
                while pending:
                    at = pending.popleft()
                    if at in seen:
                        continue
                    seen.add(at)
                    try:
                        node, nxt = decode_kd_node(data, at, end)
                    except CodecError as exc:
                        raise GraphError(f"KD codec disagrees with original {path.name}, "
                                         f"index={ix}, root={root_id}, at={at}: {exc}") from exc
                    if data[at:nxt] != encode_kd_node(node):
                        raise GraphError("OEM KD encode/decode parity violation")
                    covered[at] = nxt
                    totals["nodes_byte_identical"] += 1
                    for child in (node.left_child, node.right_child):
                        if child is None:
                            continue
                        if child.mode == 1:
                            totals["external_kd_child_links"] += 1
                        else:
                            pending.append(at + child.value * 2)
                            totals["local_kd_child_links"] += 1
                    for side, refs in (("left", node.left_parcels),
                                       ("right", node.right_parcels)):
                        for ref in refs:
                            totals["spatial_references"] += 1
                            pids.add(ref.parcel_id)
                            typed[ref.parcel_type] += 1
                            layered[(ref.parcel_type, ref.layer)] += 1
                            valid, why = verify_direct_spatial_target(source, ref)
                            reasons[why] += 1
                            if not valid and len(bad) < 50:
                                bad.append({
                                    "index": ix, "root": root_id,
                                    "node_offset_in_index": at,
                                    "side": side, "parcel_type": ref.parcel_type,
                                    "layer": ref.layer,
                                    "parcel_id": f"0x{ref.parcel_id:08X}",
                                    "expected_byte_offset": (ref.parcel_id & 0xffffff)*256,
                                    "reason": why,
                                })
                ordered = sorted(covered)
                if not ordered or ordered[0] != start or covered[ordered[-1]] != end:
                    raise GraphError("KD root not fully covered by decoded nodes")
                if any(covered[a] != b for a,b in zip(ordered,ordered[1:])):
                    raise GraphError("Gap/overlap in OEM KD node byte coverage")
                totals["fully_reencoded_roots"] += 1
        if totals["fully_reencoded_roots"] != graph["root_count"]:
            raise GraphError("Node re-encoding root count diverges from graph")
        if totals["external_kd_child_links"] != graph["global_external_edges"]:
            raise GraphError("Graph link count differs from exact codec traversal")
    if strict_targets and reasons["exact_header_match"] != totals["spatial_references"]:
        raise GraphError(f"Direct spatial references invalid: {dict(reasons)}")
    return {
        "file": path.name,
        "file_size": path.stat().st_size,
        "source_sha256": graph["source_sha256"],
        "global_graph_verified": True,
        "all_nodes_byte_identical_after_decode_encode": True,
        "all_roots_byte_covered_by_nodes": True,
        "counts": dict(sorted(totals.items())),
        "unique_direct_parcel_ids": len(pids),
        "parcel_types": {str(k):v for k,v in sorted(typed.items())},
        "parcel_type_layers": {f"{t}/{l}":n for (t,l),n in sorted(layered.items())},
        "target_header_checks": dict(sorted(reasons.items())),
        "unmatched_target_examples": bad,
        "strict_targets": strict_targets,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", required=True, metavar="NAME=PATH")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--strict-generated-parity", action="store_true",
                        help="Fail closed on any unresolved direct PID/type/region target")
    args = parser.parse_args()
    try:
        maps = {}
        for entry in args.map:
            if "=" not in entry:
                raise GraphError("Expected NAME=PATH")
            name, filename = entry.split("=",1)
            if not name or name in maps:
                raise GraphError("Empty or duplicated map label")
            maps[name] = Path(filename)
        results = {name:audit(path, strict_targets=args.strict_generated_parity)
                   for name,path in sorted(maps.items())}
    except (GraphError, OSError, CodecError) as exc:
        parser.exit(2, "ERROR: "+str(exc)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    report = {
        "schema":"sdal-iter018-spatial-encoder-parity-v1",
        "maps":results,
        "limitations":[
            "Codec parity validates node bytes, not OSM spatial cut construction.",
            "A direct target mismatch is not silently repaired or called compatible.",
            "Routing, geometry, compression, region/global media headers remain separate.",
        ],
    }
    args.json.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Re-encoded",sum(v["counts"]["nodes_byte_identical"] for v in results.values()),
          "original KD nodes; verified",sum(v["counts"]["spatial_references"]
                                             for v in results.values()),
          "spatial descriptors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

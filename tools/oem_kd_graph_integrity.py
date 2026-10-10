#!/usr/bin/env python3
"""Evidence-constrained SDAL 1.7 Global KD-tree *first-root* graph validator.

Reads the original map file's type-255 index parcels. Fully validates
the first root of the first index parcel, including local node edges
and four-byte inter-parcel references. Other roots are only inventoried
from their U16 offset tables; their internal node layouts remain unproven.

Source specification: SDAL PSF 1.7 v0.4, sections 3.1.1.2 / 3.1.1.3.
No ISO output or data fabrication occurs.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from hashlib import sha256
import json
from pathlib import Path
import struct

HEADER = struct.Struct(">IHBBBBHHHHH")
INDEX_BYTES = 0x5000
ADDRESS_UNIT = 256
INDEX_START = 0xC200


class GraphError(ValueError):
    """Reject inconsistent source bytes, rather than guessing their meaning."""


def index_record(blob: bytes, physical: int) -> dict:
    if len(blob) != INDEX_BYTES:
        raise GraphError("Truncated 0x5000-byte index parcel")
    pid, desc, kind, region, endian, size_hi, size_lo, compression, comp_offset, uncomp, ext = HEADER.unpack_from(blob)
    if ((pid & 0xFFFFFF) * ADDRESS_UNIT != physical
            or not pid & (1 << 30) or pid & (1 << 31)
            or (pid >> 24) & 0x3F != 8
            or (desc, kind, region, endian) != (0, 255, 1, 0)
            or (size_hi, size_lo, compression, comp_offset, uncomp, ext)
                != (0, 0, 0, 0, 0, 0)):
        raise GraphError(f"Unrecognized OEM index header at 0x{physical:X}")
    root_count, extension = struct.unpack_from(">HH", blob, 20)
    if extension or not 1 < root_count <= (INDEX_BYTES-24)//2:
        raise GraphError("Unsupported index root count or extension")
    offsets = struct.unpack_from(">" + str(root_count) + "H", blob, 24)
    if (offsets[0] != 24 + 2 * root_count or offsets[-1] >= INDEX_BYTES
            or any(b <= a for a,b in zip(offsets, offsets[1:]))):
        raise GraphError("Invalid global KD root-offset array")
    return {"offset": physical, "pid": f"0x{pid:08X}",
            "root_count": root_count, "root_offsets": offsets,
            "blob": blob}


def read_indexes(path: Path) -> list[dict]:
    if path.is_symlink() or not path.is_file():
        raise GraphError("Original map must be a regular file")
    output = []
    with path.open("rb") as fd:
        physical = INDEX_START
        for _ in range(512):
            fd.seek(physical)
            fragment = fd.read(INDEX_BYTES)
            if len(fragment) != INDEX_BYTES or fragment[6] != 255:
                break
            output.append(index_record(fragment, physical))
            physical += INDEX_BYTES
        else:
            raise GraphError("More than 512 consecutive OEM index parcels")
    if not output:
        raise GraphError("Missing first type-255 OEM index parcel")
    return output


def parse_node(blob: bytes, position: int, limit: int) -> dict:
    """Decode exactly one variable-length node; bit 0 means MSB, per spec."""
    start = position
    if start < 0 or start % 2 or start + 2 > limit:
        raise GraphError("Truncated or unaligned KD node")
    control = struct.unpack_from(">H", blob, position)[0]
    position += 2
    if control & 3:
        raise GraphError("Reserved KD control bits are nonzero")
    entity_mode = (control >> 2) & 3
    if entity_mode == 1:
        if position + 6 > limit:
            raise GraphError("Truncated node/segment entity IDs")
        position += 6
    # SDAL 1.7 §3.1.1.2: the left/right child OFFSET FIELDS occupy
    # EQUAL-WIDTH slots. The width is their maximum encoded width.
    # A pruned/absent child still has a physically present zero-filled
    # slot when the other side has an offset. A narrower child's
    # value lives in the least-significant bytes of its shared-width slot.
    modes = (("left", (control >> 6) & 3),
             ("right", (control >> 4) & 3))
    widths = (0, 4, 1, 2)
    slot_width = max(widths[mode] for _, mode in modes)
    edges = []
    pruned_slots = 0
    for side, mode in modes:
        if not slot_width:
            continue
        if position + slot_width > limit:
            raise GraphError("Truncated equal-width KD child offset slot")
        slot = blob[position:position + slot_width]
        position += slot_width
        if mode == 0:
            if any(slot):
                raise GraphError("Nonzero bytes in pruned KD child slot")
            pruned_slots += 1
            continue
        width = widths[mode]
        if width < slot_width and any(slot[:-width]):
            raise GraphError("Nonzero high-order bytes in padded KD child slot")
        value = int.from_bytes(slot[-width:], "big")
        if mode == 1:
            edges.append({"side": side, "mode": "external",
                          "index_delta": value >> 16,
                          "tree_id": value & 0xFFFF})
        else:
            edges.append({"side": side, "mode": "local",
                          "width_bytes": width,
                          "offset_two_byte_units": value,
                          "target": start + value * 2})
    descriptors = []
    for side, enabled in (("left", control & 0x8000), ("right", control & 0x4000)):
        if enabled:
            for _ in range(128):
                if position + 5 > limit:
                    raise GraphError("Unterminated or truncated parcel descriptor list")
                raw_type = blob[position]
                parcel_id = int.from_bytes(blob[position+1:position+5], "big")
                descriptors.append({
                    "side": side,
                    "type": (raw_type >> 3) & 7,
                    "layer": raw_type & 7,
                    "last": bool(raw_type & 0x80),
                    "parcel_id": f"0x{parcel_id:08X}",
                })
                position += 5
                if raw_type & 0x80:
                    break
            else:
                raise GraphError("Too many parcel descriptors")
    if (position-start) & 1:
        position += 1
    if position > limit:
        raise GraphError("KD node extends beyond root boundary")
    return {
        "start": start, "end": position, "control": f"0x{control:04X}",
        "axis": "horizontal" if control & 0x2000 else "vertical",
        "cut_32nds": (control >> 8) & 31,
        "entity_id_mode": entity_mode,
        "edges": edges, "descriptors": descriptors,
        "child_slot_bytes": slot_width, "pruned_slot_count": pruned_slots,
    }


def validate_initial_tree(indexes: list[dict]) -> dict:
    """Root 0 is verified as a complete, forward-linked arborescence."""
    first = indexes[0]
    if first["root_count"] < 2:
        raise GraphError("Need root boundary for proof")
    blob = first["blob"]
    begin, end = first["root_offsets"][:2]
    todo = deque([(begin, 0)])
    nodes = {}
    local_refs = []
    external_refs = []
    max_depth = 0
    while todo:
        at, depth = todo.popleft()
        if at in nodes:
            continue
        if at < begin or at >= end or len(nodes) >= 12000:
            raise GraphError("Node outside first root or node-count ceiling exceeded")
        node = parse_node(blob, at, end)
        nodes[at] = node
        max_depth = max(max_depth, depth)
        for edge in node["edges"]:
            if edge["mode"] == "external":
                i, tree = edge["index_delta"], edge["tree_id"]
                if i >= len(indexes) or tree >= indexes[i]["root_count"]:
                    raise GraphError("External KD reference has no target index/tree")
                external_refs.append((at, edge["side"], i, tree))
            else:
                dest = edge["target"]
                if dest <= at or dest >= end or dest % 2:
                    raise GraphError("Invalid forward local child offset")
                local_refs.append((at, dest))
                if dest not in nodes:
                    todo.append((dest, depth+1))
    ordered = sorted(nodes)
    if ordered[0] != begin or nodes[ordered[-1]]["end"] != end:
        raise GraphError("Root record range is not fully covered")
    for left, right in zip(ordered, ordered[1:]):
        if nodes[left]["end"] != right:
            raise GraphError("Node bytes are overlapping or unvisited")
    indegree = Counter(dest for _, dest in local_refs)
    if (len(local_refs) != len(nodes)-1 or indegree.get(begin, 0) != 0
            or any(indegree.get(pos, 0) != 1 for pos in ordered[1:])):
        raise GraphError("KD local child links do not form a single rooted tree")
    widths = Counter()
    modes = Counter()
    axes = Counter()
    descriptor_entries = 0
    for node in nodes.values():
        axes[node["axis"]] += 1
        modes[node["entity_id_mode"]] += 1
        descriptor_entries += len(node["descriptors"])
        for edge in node["edges"]:
            widths[("external-4" if edge["mode"] == "external" else
                    f"local-{edge['width_bytes']}")] += 1
    by_index = Counter(i for _, _, i, _ in external_refs)
    return {
        "root0_start": begin, "root0_end": end, "root0_bytes": end-begin,
        "root0_sha256": sha256(blob[begin:end]).hexdigest(),
        "node_count": len(nodes),
        "local_child_links": len(local_refs),
        "external_child_links": len(external_refs),
        "max_local_depth": max_depth,
        "unreachable_node_count": 0,
        "non_tree_local_edges": 0,
        "invalid_cross_index_refs": 0,
        "edge_mode_counts": dict(sorted(widths.items())),
        "cut_axis_counts": dict(sorted(axes.items())),
        "entity_mode_counts": {str(k): v for k,v in sorted(modes.items())},
        "parcel_descriptor_entries": descriptor_entries,
        "cross_index_reference_counts": {str(k): v for k,v in sorted(by_index.items())},
        "cross_index_reference_examples": [
            {"node_offset": at, "side": side, "index_delta": i, "tree_id": tree}
            for at, side, i, tree in external_refs[:20]],
    }


def audit_map(path: Path) -> dict:
    indexes = read_indexes(path)
    graph = validate_initial_tree(indexes)
    return {
        "source_file": path.name, "source_bytes": path.stat().st_size,
        "index_count": len(indexes),
        "roots_in_index_parcels": [x["root_count"] for x in indexes],
        "all_root_offset_arrays_in_bounds": True,
        "initial_root_graph": graph,
        "not_yet_validated": [
            "Tree node graphs in all roots other than index 0 root 0",
            "Meanings of parcel descriptors and spatial cut coordinates",
            "Cartographic type-1/2/3 parcel serialization and compression",
            "Device loading and routing outcomes",
        ],
    }


def markdown(rows: dict[str, dict]) -> str:
    lines = ["# Iter013: real OEM global KD-tree graph integrity", "",
             "Validated profile: FIRST root in FIRST Global KD Index parcel only.", "",
             "| OEM map | Index parcels | Root0 nodes | Local links | External references |",
             "|---|---:|---:|---:|---:|"]
    for label, entry in sorted(rows.items()):
        r = entry["initial_root_graph"]
        lines.append(f"| {label} | {entry['index_count']} | {r['node_count']} | "
                     f"{r['local_child_links']} | {r['external_child_links']} |")
    lines += ["", "## Unresolved", "",
              "- Remaining index roots are inventoried, not graph-validated.",
              "- No ISO-mastering changes or device compatibility claim."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", required=True, metavar="LABEL=FILE")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = {}
        for item in args.map:
            if "=" not in item:
                raise GraphError("Expected LABEL=FILE")
            label, name = item.split("=",1)
            if not label or label in records:
                raise GraphError("Empty or duplicate source label")
            records[label] = audit_map(Path(name))
    except (GraphError, OSError) as error:
        parser.exit(2, "ERROR: " + str(error) + "\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(records, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    args.md.write_text(markdown(records), encoding="utf-8")
    print("Validated initial KD graph of", len(records), "OEM maps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

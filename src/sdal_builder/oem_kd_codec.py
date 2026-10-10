"""SDAL PSF 1.7 spatial KD-node and Parcel Descriptor encoder/decoder.

Production codec building block for OSM->SDAL. It does not infer an OSM
partition, geographic cut placement, compressed map contents, or a loader.
Sources: SDAL PSF 1.7 v0.4 sections 3.1.1.2 and 3.1.1.3.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct


class CodecError(ValueError):
    pass


@dataclass(frozen=True)
class SpatialRef:
    parcel_type: int
    layer: int
    parcel_id: int


@dataclass(frozen=True)
class KDChild:
    # Mode 1: external [index parcel, tree ID] as packed U32.
    # Mode 2: 1-byte local offset; mode 3: 2-byte local offset.
    mode: int
    value: int


@dataclass(frozen=True)
class KDNode:
    horizontal_cut: bool
    cut_32nds: int
    entity_mode: int
    entity_ids: tuple[int, int] | None
    left_child: KDChild | None
    right_child: KDChild | None
    left_parcels: tuple[SpatialRef, ...] = ()
    right_parcels: tuple[SpatialRef, ...] = ()


_WIDTHS = (0, 4, 1, 2)


def _uint(field: str, value: int, maxval: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= maxval:
        raise CodecError(f"{field} must be in 0..{maxval}")


def encode_descriptor_list(refs: tuple[SpatialRef, ...]) -> bytes:
    if not 1 <= len(refs) <= 128:
        raise CodecError("A present descriptor list must contain 1..128 entries")
    result = bytearray()
    for i, ref in enumerate(refs):
        _uint("spatial parcel type", ref.parcel_type, 7)
        _uint("spatial layer", ref.layer, 7)
        _uint("ParcelID", ref.parcel_id, 0xffffffff)
        first = ((0x80 if i == len(refs)-1 else 0)
                 | (ref.parcel_type << 3) | ref.layer)
        result += struct.pack(">BI", first, ref.parcel_id)
    return bytes(result)


def decode_descriptor_list(data: bytes, pos: int, end: int) -> tuple[tuple[SpatialRef, ...], int]:
    items = []
    for _ in range(128):
        if pos + 5 > end:
            raise CodecError("Truncated spatial descriptor list")
        first, pid = struct.unpack_from(">BI", data, pos)
        pos += 5
        if first & 0x40:
            raise CodecError("Reserved parcel descriptor bit set")
        items.append(SpatialRef((first >> 3) & 7, first & 7, pid))
        if first & 0x80:
            return tuple(items), pos
    raise CodecError("Unterminated spatial descriptor list")


def _mode(child: KDChild | None) -> int:
    if child is None:
        return 0
    if not isinstance(child, KDChild) or child.mode not in (1, 2, 3):
        raise CodecError("Unsupported KD child mode")
    maximum = (0, 0xffffffff, 255, 65535)[child.mode]
    _uint("KD child address", child.value, maximum)
    if child.mode != 1 and child.value == 0:
        raise CodecError("Local child must move forward")
    return child.mode


def encode_kd_node(node: KDNode) -> bytes:
    if not isinstance(node, KDNode):
        raise CodecError("Expected KDNode")
    _uint("cut position", node.cut_32nds, 31)
    _uint("entity ID mode", node.entity_mode, 3)
    if node.entity_mode == 1:
        if node.entity_ids is None or len(node.entity_ids) != 2:
            raise CodecError("Explicit entity IDs missing")
        for val in node.entity_ids:
            _uint("24-bit entity ID", val, 0xffffff)
    elif node.entity_ids is not None:
        raise CodecError("Cannot provide explicit IDs for implicit entity mode")
    left, right = _mode(node.left_child), _mode(node.right_child)
    word = ((0x8000 if node.left_parcels else 0)
            | (0x4000 if node.right_parcels else 0)
            | (0x2000 if node.horizontal_cut else 0)
            | (node.cut_32nds << 8) | (left << 6) | (right << 4)
            | (node.entity_mode << 2))
    result = bytearray(struct.pack(">H", word))
    if node.entity_mode == 1:
        for val in node.entity_ids:
            result += val.to_bytes(3, "big")
    slot = max(_WIDTHS[left], _WIDTHS[right])
    for child in (node.left_child, node.right_child):
        if slot:
            result += (0 if child is None else child.value).to_bytes(slot, "big")
    for descriptors in (node.left_parcels, node.right_parcels):
        if descriptors:
            result += encode_descriptor_list(descriptors)
    if len(result) & 1:
        result.append(0)
    return bytes(result)


def decode_kd_node(data: bytes, pos: int, end: int) -> tuple[KDNode, int]:
    if pos < 0 or pos % 2 or pos + 2 > end or end > len(data):
        raise CodecError("Unaligned/truncated KD control record")
    start = pos
    word = struct.unpack_from(">H", data, pos)[0]
    if word & 3:
        raise CodecError("Reserved KD control bits are nonzero")
    pos += 2
    emode = (word >> 2) & 3
    entity_ids = None
    if emode == 1:
        if pos + 6 > end:
            raise CodecError("Truncated entity IDs")
        entity_ids = (int.from_bytes(data[pos:pos+3], "big"),
                      int.from_bytes(data[pos+3:pos+6], "big"))
        pos += 6
    modes = ((word >> 6) & 3, (word >> 4) & 3)
    slot = max(_WIDTHS[modes[0]], _WIDTHS[modes[1]])
    children = []
    for mode in modes:
        if not slot:
            children.append(None)
            continue
        if pos + slot > end:
            raise CodecError("Truncated equal-width KD child slots")
        raw = data[pos:pos+slot]
        pos += slot
        if mode == 0:
            if any(raw):
                raise CodecError("Nonzero pruned KD child slot")
            children.append(None)
            continue
        width = _WIDTHS[mode]
        if any(raw[:-width]):
            raise CodecError("Nonzero high-order bytes in padded KD child")
        value = int.from_bytes(raw[-width:], "big")
        if mode != 1 and not value:
            raise CodecError("Local KD child self-reference")
        children.append(KDChild(mode, value))
    lists = []
    for bit in (0x8000, 0x4000):
        if word & bit:
            refs, pos = decode_descriptor_list(data, pos, end)
            lists.append(refs)
        else:
            lists.append(())
    if (pos-start) & 1:
        if pos >= end or data[pos] != 0:
            raise CodecError("Invalid KD padding byte")
        pos += 1
    node = KDNode(bool(word & 0x2000), (word >> 8) & 31, emode,
                  entity_ids, children[0], children[1], lists[0], lists[1])
    if data[start:pos] != encode_kd_node(node):
        raise CodecError("KD codec byte parity failed")
    return node, pos


def verify_direct_spatial_target(fileobj, ref: SpatialRef,
                                 *, sector_bytes: int = 256) -> tuple[bool, str]:
    """Validate the target parcel header against a direct KD descriptor.

    Direct references must match PID, type and region exactly.
    External handles require a validated external indirection table.
    """
    if ref.parcel_id & 0x80000000:
        return False, "external_indirection_not_available"
    _uint("sector bytes", sector_bytes, 65535)
    if not sector_bytes:
        raise CodecError("Invalid zero-byte sector unit")
    addr = (ref.parcel_id & 0xffffff) * sector_bytes
    fileobj.seek(0, 2)
    if addr + 20 > fileobj.tell():
        return False, "target_out_of_bounds"
    fileobj.seek(addr)
    header = fileobj.read(20)
    if len(header) != 20:
        return False, "truncated_target_header"
    pid, _desc, typ, region, *_ = struct.unpack(">IHBBBBHHHHH", header)
    if pid != ref.parcel_id:
        return False, "target_pid_mismatch"
    if typ != ref.parcel_type:
        return False, "target_type_mismatch"
    if region != 1:
        return False, "target_region_mismatch"
    return True, "exact_header_match"


def encode_index_from_nodes(*, file_offset: int,
                            roots: tuple[tuple[KDNode, ...], ...]) -> bytes:
    """Build a complete SDAL type-255 index parcel from planned KD records.

    The caller supplies nodes in physical byte order, with local child
    offsets already expressed in 2-byte units. This verifies that every
    local child targets an actual node start and that every root's local
    graph is complete, singly parented and reachable. It does not invent
    spatial cuts or OSM parcel content; cross-index references are
    validated when the full cross-index graph is available.
    """
    from .oem_index import encode_new_index_parcel, decode_index_parcel
    from collections import Counter, deque

    if not roots:
        raise CodecError("Index must have at least one tree root")
    serialized_roots = []
    for root_number, nodes in enumerate(roots):
        if not nodes:
            raise CodecError(f"Empty KD root {root_number}")
        chunks = [encode_kd_node(node) for node in nodes]
        starts = []
        pos = 0
        for chunk in chunks:
            starts.append(pos)
            pos += len(chunk)
        position_to_index = {start: i for i, start in enumerate(starts)}
        if len(position_to_index) != len(starts):
            raise CodecError("Duplicate KD node address")
        incoming = Counter()
        edges = {}
        for index, node in enumerate(nodes):
            child_indexes = []
            for child in (node.left_child, node.right_child):
                if child is not None and child.mode in (2, 3):
                    target = starts[index] + 2 * child.value
                    if target not in position_to_index or target <= starts[index]:
                        raise CodecError("Local KD link is not an aligned node start")
                    next_index = position_to_index[target]
                    incoming[next_index] += 1
                    child_indexes.append(next_index)
            edges[index] = child_indexes
        if incoming[0] or any(incoming[i] != 1 for i in range(1, len(nodes))):
            raise CodecError("KD root has missing or multiple local node parents")
        if sum(incoming.values()) != len(nodes)-1:
            raise CodecError("Local KD links do not form a rooted tree")
        visited = {0}
        queue = deque([0])
        while queue:
            for child in edges[queue.popleft()]:
                if child not in visited:
                    visited.add(child)
                    queue.append(child)
        if len(visited) != len(nodes):
            raise CodecError("KD root contains unreachable node records")
        serialized_roots.append(b"".join(chunks))
    try:
        raw = encode_new_index_parcel(file_offset=file_offset,
                                      size_index=8,
                                      root_blobs=tuple(serialized_roots))
        parsed = decode_index_parcel(raw, absolute_offset=file_offset)
    except ValueError as exc:
        raise CodecError(f"SDAL KD index packing failed: {exc}") from exc
    if parsed.reassemble() != raw:
        raise CodecError("Generated index is not byte-for-byte reproducible")
    return raw

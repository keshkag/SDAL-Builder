"""SDAL 1.7 typed spatial record-array physical assembler (bounded profile).

PSF v0.4 §§1.4.0.2, 3.2.2.1/.6, 3.5.2.3, 3.5.3.2/.3 and 3.5.6.

Builds *actual bytes*: typed fixed header, 16-bit block-offset tables,
(N+1) Type-1 variable-length record blocks and Cartographic positions.
Offsets, counts, max record/block sizes, parcel size-index and direct PID
must all agree. Other SDAL record families are NOT silently synthesized.
This output is a bounded record-bearing spatial parcel; it is not yet a
complete Denso navigation dataset (ghosts/conditions/local attrs/KD etc.).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping
import struct

from .oem_spatial_header import PCL, decode_spatial_header
from .oem_typed_headers import (
    TypedFixedHeader, encode_typed_fixed_header, decode_typed_fixed_header,
)
from .oem_record_blocks import encode_record_block, decode_record_block
from .oem_line_geometry import (
    FullPolyline, CartographicPosition, encode_full_polyline,
    decode_full_polyline, encode_carto_positions, decode_carto_positions,
)
from .oem_typed_records import (
    RoutingNodeBasic, encode_route_node_basic, decode_route_node_basic,
    RecordError,
)
from .oem_route_segments import (
    RoutingSegmentRegular, encode_route_segment_regular,
    decode_route_segment_regular, verify_routing_node_segment_links,
)


class ParcelAssemblyError(ValueError):
    pass


@dataclass(frozen=True)
class SizeAuthority:
    """Sector bytes and *verified* actual sizes indexed by ucaParcelSizes.

    Values are declared parcel byte capacities, already resolved from
    GlbMediaHeader_t. This object does not derive/guess the size table.
    """
    sector_bytes: int
    sizes_by_index: Mapping[int, int]

    def check(self, pid: int, file_offset: int) -> int:
        if (self.sector_bytes not in (256, 512, 1024, 2048)
                or not isinstance(pid, int) or isinstance(pid, bool)
                or not 0 <= pid <= 0xffffffff):
            raise ParcelAssemblyError("Invalid SDAL direct PID or logical sector")
        if pid & 0xc0000000:
            raise ParcelAssemblyError("External/redundant ParcelID needs table authority")
        index = (pid >> 24) & 63
        if index not in self.sizes_by_index:
            raise ParcelAssemblyError("Unresolved ucaParcelSizes index")
        length = self.sizes_by_index[index]
        if (not isinstance(length, int) or isinstance(length, bool)
                or length < self.sector_bytes or length % self.sector_bytes
                or length > 65535):
            raise ParcelAssemblyError("Invalid declared physical parcel size")
        if (pid & 0xffffff) * self.sector_bytes != file_offset:
            raise ParcelAssemblyError("Direct ParcelID/physical offset mismatch")
        return length


@dataclass(frozen=True)
class CartographicRoad:
    polyline: FullPolyline
    positions: tuple[CartographicPosition, ...]


@dataclass(frozen=True)
class PhysicalParcel:
    blob: bytes
    used_bytes: int
    parcel_id: int
    parcel_type: int
    block_offsets: tuple[tuple[str, tuple[int, ...]], ...]
    verification: str = "typed-record-arrays-only"


def _align2(buffer: bytearray) -> None:
    if len(buffer) & 1:
        buffer.append(0)


def _template(template: TypedFixedHeader, required_type: int) -> tuple:
    if template.parcel_type != required_type or template.layer != 0:
        raise ParcelAssemblyError("Only bounded Cartographic/Layer-0 Routing implemented")
    prefix = decode_spatial_header(template.spatial_prefix)
    fields = PCL.unpack(prefix.pcl_raw)
    if fields[7] or fields[3] != 1 or fields[4] != 0:
        raise ParcelAssemblyError("Only uncompressed, normal-endian region-1 parcels")
    for name, row in template.descriptors:
        if any(v != 0 and v != b"\x00\x00" for v in row):
            raise ParcelAssemblyError("Input descriptor is already populated: " + name)
    if any(prefix.xrf_fields[:5]) or any(prefix.kd_fields[:5]):
        raise ParcelAssemblyError("Other spatial arrays require their own serialized authority")
    return fields, prefix


def _block_array(buffer: bytearray, records: tuple[bytes, ...],
                 shift: int, capacity: int) -> tuple[tuple, tuple[int, ...]]:
    if not records or shift not in range(0, 9):
        raise ParcelAssemblyError("Nonempty records and valid 2^K block shift required")
    if len(records) > 65535:
        raise ParcelAssemblyError("Record count exceeds BlkDesc")
    per_block = 1 << shift
    groups = [records[i:i+per_block] for i in range(0, len(records), per_block)]
    if len(groups) > 255:
        raise ParcelAssemblyError("More than 255 record blocks")
    blocks = [encode_record_block(tuple(group)).raw for group in groups]
    _align2(buffer)
    array_at = len(buffer)
    buffer.extend(bytes(2 * len(blocks)))
    _align2(buffer)
    first_data = len(buffer)
    offsets = []
    for block in blocks:
        # Blkoffset_t is a Ushort_t relative to the parcel start.
        at = len(buffer)
        if at > 65535 or at + len(block) > capacity:
            raise ParcelAssemblyError("Block offset/extent exceeds physical parcel")
        offsets.append(at)
        buffer.extend(block)
    for i, at in enumerate(offsets):
        struct.pack_into(">H", buffer, array_at + i * 2, at)
    desc = (
        array_at, len(records), len(blocks), shift,
        max(len(record) for record in records), first_data,
        max(len(block) for block in blocks),
    )
    return desc, tuple(offsets)


def _build(template: TypedFixedHeader, *,
           arrays: Mapping[str, tuple[bytes, ...]],
           min_ids: Mapping[str, int],
           positions: bytes | None,
           position_count: int,
           position_max: int,
           shift: int,
           authority: SizeAuthority, file_offset: int) -> PhysicalParcel:
    head, spatial = _template(template, template.parcel_type)
    pid = head[0]
    capacity = authority.check(pid, file_offset)
    if capacity < template.size:
        raise ParcelAssemblyError("Type-specific header exceeds declared parcel size")
    if template.parcel_type == 1:
        if set(arrays) != {"lineDesc"} or set(min_ids):
            raise ParcelAssemblyError("Cartographic bounded profile requires line records only")
    elif template.parcel_type == 0:
        if set(arrays) != {"nodeDesc", "segmentDesc"} or set(min_ids) != {
                "nodeDesc", "segmentDesc"}:
            raise ParcelAssemblyError("Routing requires explicit node/segment ID authority")
    else:
        raise ParcelAssemblyError("Unsupported type")
    buf = bytearray(template.size)
    descriptors = dict(template.descriptors)
    locations = []
    for name in (("lineDesc",) if template.parcel_type == 1
                 else ("nodeDesc", "segmentDesc")):
        desc, offsets = _block_array(buf, arrays[name], shift, capacity)
        if template.parcel_type == 0:
            minimum = min_ids[name]
            if not isinstance(minimum, int) or isinstance(minimum, bool) or not (
                    0 < minimum <= 0xffffffff):
                raise ParcelAssemblyError("Routing minimum ID must be explicitly allocated")
            # BlkDesc1_t inserts the 32-bit minimum after usCount.
            desc = (desc[0], desc[1], minimum, *desc[2:])
        descriptors[name] = desc
        locations.append((name, offsets))
    if template.parcel_type == 1:
        if positions is None or not positions or len(positions) != position_count * 3:
            raise ParcelAssemblyError("Cartographic position array count/width mismatch")
        _align2(buf)
        posat = len(buf)
        if position_count > 65535 or posat + len(positions) > capacity:
            raise ParcelAssemblyError("Position array exceeds declared parcel")
        buf.extend(positions)
        descriptors["positionDesc"] = (position_count, position_max, posat, b"\x00\x00")
        locations.append(("positionDesc", (posat,)))
    # The typed maxima must describe the generated records; leaving zero
    # would produce a byte-valid header with semantically false metadata.
    if template.parcel_type == 1:
        derived_maxima = (0, max(
            decode_full_polyline(record, min_lat=spatial.bounding_rect.min_lat,
                                 min_lon=spatial.bounding_rect.min_long,
                                 scale=spatial.kd_fields[-2]).position_count
            for record in arrays["lineDesc"]), 0, 0)
    else:
        decoded_nodes = [decode_route_node_basic(
            record, min_lat_ntu=spatial.bounding_rect.min_lat,
            min_long_ntu=spatial.bounding_rect.min_long,
            scale=spatial.kd_fields[-2])[0]
            for record in arrays["nodeDesc"]]
        derived_maxima = (0, max(len(node.segment_indices)
                                 for node in decoded_nodes),
                          *([0] * 7))
    header = replace(template, descriptors=tuple(
        (key, descriptors[key]) for key, _ in template.descriptors),
        maxima=derived_maxima)
    encoded_header = encode_typed_fixed_header(header)
    buf[:len(encoded_header)] = encoded_header
    used = len(buf)
    if used > capacity or used > 65535:
        raise ParcelAssemblyError("Parcel body exceeds physical or Ushort_t offset")
    buf.extend(bytes(capacity - used))  # Zeroed unused allocation, not OEM fill evidence.
    payload = bytes(buf)
    verify_bounded_parcel(payload, authority=authority, file_offset=file_offset,
                          expected_arrays=arrays, expected_positions=positions)
    return PhysicalParcel(payload, used, pid, template.parcel_type,
                          tuple(locations))


def _read_block_array(raw: bytes, desc: tuple, *,
                      minimum_id: bool, available: int,
                      header_size: int) -> tuple[tuple[bytes, ...], tuple[int, ...],
                                                tuple[tuple[int, int], ...]]:
    if minimum_id:
        off, count, minimum, blocks, shift, max_rec, data, max_block = desc
        if minimum == 0:
            raise ParcelAssemblyError("Missing routing minimum ID")
    else:
        off, count, blocks, shift, max_rec, data, max_block = desc
    if (not 1 <= count <= 65535 or not 1 <= blocks <= 255
            or not 0 <= shift <= 8
            or blocks != (count + (1 << shift) - 1) // (1 << shift)):
        raise ParcelAssemblyError("Wrong declared record count/block geometry")
    if off < header_size or off + 2 * blocks > available:
        raise ParcelAssemblyError("Block-offset table overlaps fixed header/escapes body")
    offsets = tuple(struct.unpack_from(">H", raw, off + i*2)[0]
                    for i in range(blocks))
    if data != offsets[0] or any(a >= b for a, b in zip(offsets, offsets[1:])):
        raise ParcelAssemblyError("Block data start/order disagrees with descriptor")
    records = []
    occupied = [(off, off + 2 * blocks)]
    for i, start in enumerate(offsets):
        end = offsets[i+1] if i+1 < len(offsets) else available
        if not (off + 2 * blocks <= start < end <= available):
            raise ParcelAssemblyError("Block extent overlaps table/escapes parcel")
        actual_count = min(1 << shift, count - (i << shift))
        # The final block may be followed by additional arrays: find its
        # canonical exact extent from the length prefix and record sizes.
        first, p = _measure_block(raw, start, actual_count, end)
        piece = raw[start:p]
        occupied.append((start, p))
        result = decode_record_block(piece, actual_count)
        if result.first_record_offset != first:
            raise ParcelAssemblyError("Block prefix does not match")
        if len(piece) > max_block or max(map(len, result.records)) > max_rec:
            raise ParcelAssemblyError("BlkDesc maximum record/block size is false")
        records.extend(result.records)
        if i + 1 < len(offsets) and p != end:
            raise ParcelAssemblyError("Unexpected bytes between successive record blocks")
    if len(records) != count:
        raise ParcelAssemblyError("Record table lost entries")
    return tuple(records), offsets, tuple(occupied)


def _measure_block(raw: bytes, at: int, count: int, end: int) -> tuple[int, int]:
    from .oem_typed_records import decode_type1
    first, p = decode_type1(raw, at)
    lengths = []
    for _ in range(count):
        value, p = decode_type1(raw, p)
        if not value:
            raise ParcelAssemblyError("Empty record")
        lengths.append(value)
    if at + first != p:
        raise ParcelAssemblyError("Incorrect first record offset")
    finish = p + sum(lengths)
    if finish > end:
        raise ParcelAssemblyError("Record length table exceeds block bound")
    return first, finish


def verify_bounded_parcel(raw: bytes, *, authority: SizeAuthority,
                          file_offset: int,
                          expected_arrays: Mapping[str, tuple[bytes, ...]] | None = None,
                          expected_positions: bytes | None = None) -> dict:
    """Independently walk physical pointers; reject corrupted produced bytes."""
    if len(raw) < 192:
        raise ParcelAssemblyError("Physical parcel too short")
    header = decode_typed_fixed_header(raw)
    pid = PCL.unpack(header.spatial_prefix[:20])[0]
    if len(raw) != authority.check(pid, file_offset):
        raise ParcelAssemblyError("Physical length not backed by size authority")
    desc = dict(header.descriptors)
    if header.parcel_type == 1:
        active = ("lineDesc",)
    elif header.parcel_type == 0 and header.layer == 0:
        active = ("nodeDesc", "segmentDesc")
    else:
        raise ParcelAssemblyError("Unsupported bounded typed parcel")
    if any(any(v != 0 and v != b"\x00\x00" for v in fields)
           for name, fields in header.descriptors if name not in active
           and name != ("positionDesc" if header.parcel_type == 1 else "")):
        raise ParcelAssemblyError("Unverified auxiliary descriptor populated")
    posat = None
    if header.parcel_type == 1:
        count, size, at, reserve = desc["positionDesc"]
        if not count or size != 3 or reserve != b"\x00\x00":
            raise ParcelAssemblyError("Invalid position array descriptor")
        if at < header.size or at + count*3 > len(raw):
            raise ParcelAssemblyError("Position array outside parcel")
        posat = at
        if expected_positions is not None and raw[at:at+count*3] != expected_positions:
            raise ParcelAssemblyError("Cartographic position payload mismatch")
    decoded = {}
    offsets_by_kind = {}
    occupied = [(0, header.size, "fixed typed header")]
    if posat is not None:
        occupied.append((posat, posat+count*3, "Cartographic Position array"))
    for name in active:
        records, offsets, intervals = _read_block_array(raw, desc[name],
                 minimum_id=header.parcel_type == 0,
                 available=posat if posat is not None else len(raw),
                 header_size=header.size)
        decoded[name] = records
        offsets_by_kind[name] = offsets
        occupied.extend((a,b,name) for a,b in intervals)
        if expected_arrays is not None and records != expected_arrays[name]:
            raise ParcelAssemblyError("Encoded record array differs from source: " + name)
    occupied.sort()
    if any(end > following_start
           for (_,end,_),(following_start,_,_) in zip(occupied,occupied[1:])):
        raise ParcelAssemblyError("Overlapping SDAL typed header, block or Position arrays")
        if expected_arrays is not None and records != expected_arrays[name]:
            raise ParcelAssemblyError("Encoded record array differs from source: " + name)
    spatial = decode_spatial_header(header.spatial_prefix)
    rect = spatial.bounding_rect
    scale = spatial.kd_fields[-2]
    if header.parcel_type == 1:
        position_count, _, position_start, _ = desc["positionDesc"]
        position_bytes = raw[position_start:position_start+position_count*3]
        index = 0
        for record in decoded["lineDesc"]:
            line = decode_full_polyline(record, min_lat=rect.min_lat,
                                        min_lon=rect.min_long, scale=scale)
            if not (rect.min_lat <= line.start_lat <= rect.max_lat
                    and rect.min_long <= line.start_lon <= rect.max_long):
                raise ParcelAssemblyError("Polyline start escapes spatial bounding rectangle")
            if (line.text_offsets or line.position_count == 0
                    or (line.attribute_index is not None and
                        line.attribute_index > 255)):
                raise ParcelAssemblyError("Cartographic ancillary arrays not present")
            if line.position_offset != index:
                raise ParcelAssemblyError("Polyline PositionOffset is not contiguous")
            start = index*3
            end = start + line.position_count*3
            if end > len(position_bytes):
                raise ParcelAssemblyError("Polyline points extend beyond PositionDesc")
            points = decode_carto_positions(position_bytes[start:end],
                        start_lat=line.start_lat, start_lon=line.start_lon,
                        scale=scale)
            if len(points) != line.position_count:
                raise ParcelAssemblyError("Position record count incorrect")
            if any(not (rect.min_lat <= p.latitude_ntu <= rect.max_lat and
                        rect.min_long <= p.longitude_ntu <= rect.max_long)
                   for p in points):
                raise ParcelAssemblyError("Cartographic geometry escapes parcel bounds")
            index += line.position_count
        if index != position_count or header.maxima[1] < max(
                decode_full_polyline(r, min_lat=rect.min_lat,
                                     min_lon=rect.min_long,
                                     scale=scale).position_count
                for r in decoded["lineDesc"]):
            raise ParcelAssemblyError("Cartographic descriptor count/maxima mismatch")
    else:
        nodes = []
        for record in decoded["nodeDesc"]:
            node, end = decode_route_node_basic(record,
                    min_lat_ntu=rect.min_lat,
                    min_long_ntu=rect.min_long,scale=scale)
            if end != len(record):
                raise ParcelAssemblyError("Unparsed routing node bytes")
            if not (rect.min_lat <= node.latitude_ntu <= rect.max_lat
                    and rect.min_long <= node.longitude_ntu <= rect.max_long):
                raise ParcelAssemblyError("Routing node escapes spatial bounding rectangle")
            nodes.append(node)
        segments = tuple(decode_route_segment_regular(
                 record,node_count=len(nodes))
                 for record in decoded["segmentDesc"])
        if any(s.attribute_index > 255 for s in segments):
            raise ParcelAssemblyError("Local attributes missing")
        verify_routing_node_segment_links(tuple(nodes),segments)
        if header.maxima[1] < max(len(n.segment_indices) for n in nodes):
            raise ParcelAssemblyError("Routing maximum segments/node understated")
    return {"parcel_id": pid, "type": header.parcel_type,
            "record_counts": {key: len(v) for key, v in decoded.items()},
            "block_offsets": offsets_by_kind}


def assemble_cartographic_roads(
    template: TypedFixedHeader,
    roads: tuple[CartographicRoad, ...], *,
    authority: SizeAuthority, file_offset: int, block_shift: int = 3
) -> PhysicalParcel:
    """Compose actual polylines + position records with checked 15-bit indexes."""
    if not roads or template.parcel_type != 1:
        raise ParcelAssemblyError("Cartographic source roads missing")
    spatial = decode_spatial_header(template.spatial_prefix)
    box = spatial.bounding_rect
    records = []
    positions = bytearray()
    position_index = 0
    for entry in roads:
        line = entry.polyline
        if (line.position_count != len(entry.positions)
                or line.text_offsets or
                (line.attribute_index is not None and line.attribute_index > 255)):
            raise ParcelAssemblyError(
                "Position count/text/local attributes need separately encoded arrays")
        if position_index > 32767:
            raise ParcelAssemblyError("Polyline position index exceeds 15 bits")
        line = replace(line, position_offset=position_index)
        raw_line = encode_full_polyline(line, min_lat=box.min_lat,
                          min_lon=box.min_long, scale=spatial.kd_fields[-2])
        records.append(raw_line)
        points = encode_carto_positions(start_lat=line.start_lat,
            start_lon=line.start_lon, points=entry.positions,
            scale=spatial.kd_fields[-2])
        if decode_carto_positions(points, start_lat=line.start_lat,
              start_lon=line.start_lon, scale=spatial.kd_fields[-2]) != entry.positions:
            raise ParcelAssemblyError("Cartographic polyline vertices changed")
        positions.extend(points)
        position_index += len(entry.positions)
    return _build(template, arrays={"lineDesc": tuple(records)}, min_ids={},
                 positions=bytes(positions), position_count=position_index,
                 position_max=3, shift=block_shift, authority=authority,
                 file_offset=file_offset)


def assemble_routing_regular(
    template: TypedFixedHeader,
    nodes: tuple[RoutingNodeBasic, ...],
    segments: tuple[RoutingSegmentRegular, ...], *,
    minimum_node_id: int, minimum_segment_id: int,
    authority: SizeAuthority, file_offset: int, block_shift: int = 3
) -> PhysicalParcel:
    """Write actual bottom-layer nodes and segments with reciprocal edges."""
    if template.parcel_type != 0 or template.layer != 0:
        raise ParcelAssemblyError("Only normal bottom-layer routing supported")
    verify_routing_node_segment_links(nodes, segments)
    spatial = decode_spatial_header(template.spatial_prefix)
    rect = spatial.bounding_rect
    scale = spatial.kd_fields[-2]
    if any(s.attribute_index > 255 for s in segments):
        raise ParcelAssemblyError("Local normalized attributes not serialized")
    node_raw = tuple(encode_route_node_basic(n, min_lat_ntu=rect.min_lat,
               min_long_ntu=rect.min_long, scale=scale) for n in nodes)
    seg_raw = tuple(encode_route_segment_regular(s, node_count=len(nodes))
                    for s in segments)
    for a, n in zip(node_raw, nodes):
        roundtrip, end = decode_route_node_basic(a, min_lat_ntu=rect.min_lat,
                                   min_long_ntu=rect.min_long, scale=scale)
        if roundtrip != n or end != len(a):
            raise ParcelAssemblyError("Routing node byte parity failed")
    for a, s in zip(seg_raw, segments):
        if decode_route_segment_regular(a, node_count=len(nodes)) != s:
            raise ParcelAssemblyError("Routing segment byte parity failed")
    return _build(template, arrays={"nodeDesc": node_raw, "segmentDesc": seg_raw},
                 min_ids={"nodeDesc": minimum_node_id,
                          "segmentDesc": minimum_segment_id},
                 positions=None, position_count=0, position_max=0,
                 shift=block_shift, authority=authority, file_offset=file_offset)

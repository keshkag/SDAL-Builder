"""SDAL 1.7 Global Media Index and typed global-header link codec.

Source: PSF v0.4 §§2.1.1.3–2.1.1.4. The first 2048 bytes
are a bootstrap GlbMediaHeader_t WITHOUT PclHdr_t; the next parcel,
starting at byte 2048, is a raw variable-length index WITHOUT PclHdr_t.
Offsets in the first parcel are relative to the START of the second.

Only published, structurally specified arrays are authored here.
Other header fields (including unspecified MAX_GENERIC_REF_DATA count)
remain caller-owned, are never guessed or erased. This is not a complete
media catalog/renderer until every required reference-data family,
metadata and regional index is supplied and validated.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import struct

from .oem_media_allocator import (
    MediaLayoutError, MediaSizeTable, parse_media_size_fields, HEADER_BYTES
)
from .oem_spatial_header import PCL

REF_FAMILIES = ("chain_id", "feature_type", "facility_type", "attribute_value",
                "language_code", "country_info", "time_zone", "dst")
# The first triple begins after normalized attrs (1024), ext bitmap (8),
# int bitmap (4) and five Ushort metadata offset/count/hash fields (10).
METADATA_LEVEL_AT = 1036
METADATA_LEVEL_COUNT_AT = 1038
METADATA_MODULE_AT = 1040
METADATA_MODULE_COUNT_AT = 1042
METADATA_HASH_AT = 1044
REF_TRIPLES_AT = 1046
ICONS_AT = 1094
VOICE_AT = 1102
COMPRESS_AT = 1108
HUFF_AT = 1112
LOCALE_AT = 1118
EXTERNAL_BITMAP_AT = 1024
EXTERNAL_BITMAP_BYTES = 8
INTERNAL_BITMAP_AT = 1032
INTERNAL_BITMAP_BYTES = 4
REF = struct.Struct(">IHHH2s")         # RefDataIndex_t: 12 bytes
LEVEL = struct.Struct(">HH")            # MetadataLevel_t: 4 bytes
MODULE = struct.Struct(">HHHHII")       # MetadataModule_t: 16 bytes
COMPRESS = struct.Struct(">IBBBB")      # CompressInfo_t: 8 bytes
ICON = struct.Struct(">HHHH")          # GlbIconHdr_t: 8 bytes


class GlobalIndexError(ValueError):
    pass


def _ushort(name: str, value: int, *, nonzero: bool = False) -> None:
    if (not isinstance(value, int) or isinstance(value, bool)
            or not (1 if nonzero else 0) <= value <= 0xffff):
        raise GlobalIndexError(name + " must fit unsigned16")


def _pid(name: str, value: int) -> None:
    if (not isinstance(value, int) or isinstance(value, bool)
            or not 0 <= value <= 0xffffffff or value & 0xc0000000):
        raise GlobalIndexError(name + " must be a direct, nonredundant ParcelID")


@dataclass(frozen=True)
class RefDataEntry:
    parcel_id: int
    index_offset: int
    description_offset: int
    last_index: int

    def __post_init__(self) -> None:
        _pid("Reference-data PID", self.parcel_id)
        _ushort("usIndexOffset", self.index_offset, nonzero=True)
        _ushort("usDescrOffset", self.description_offset, nonzero=True)
        _ushort("usLastIndex", self.last_index)

    def encode(self) -> bytes:
        return REF.pack(self.parcel_id, self.index_offset,
                        self.description_offset, self.last_index, b"\x00\x00")

    @classmethod
    def decode(cls, raw: bytes) -> "RefDataEntry":
        if len(raw) != REF.size:
            raise GlobalIndexError("RefDataIndex_t must be 12 bytes")
        pid, idx, desc, end, reserve = REF.unpack(raw)
        if reserve != b"\x00\x00":
            raise GlobalIndexError("RefDataIndex_t reserved bytes must be zero")
        return cls(pid, idx, desc, end)


@dataclass(frozen=True)
class MetadataLevel:
    library_version: int
    level: int

    def __post_init__(self) -> None:
        _ushort("Library version", self.library_version, nonzero=True)
        _ushort("Metadata level", self.level, nonzero=True)

    def encode(self) -> bytes:
        return LEVEL.pack(self.library_version, self.level)


@dataclass(frozen=True)
class MetadataModule:
    level: int
    module_id: int
    byte_length: int
    flags: int
    first_parcel_id: int
    second_parcel_id: int

    def __post_init__(self) -> None:
        _ushort("Module level", self.level, nonzero=True)
        _ushort("Module ID", self.module_id, nonzero=True)
        _ushort("Module bytes", self.byte_length, nonzero=True)
        _ushort("Module flags", self.flags)
        _pid("First metadata PID", self.first_parcel_id)
        _pid("Second metadata PID", self.second_parcel_id)

    def encode(self) -> bytes:
        return MODULE.pack(self.level, self.module_id, self.byte_length,
                           self.flags, self.first_parcel_id, self.second_parcel_id)


@dataclass(frozen=True)
class CompressionEntry:
    compression: int
    huffman_location: int
    huffman_extent: int

    def __post_init__(self) -> None:
        if not 0 <= self.compression <= 7:
            raise GlobalIndexError("Unsupported compression type")
        if not 0 <= self.huffman_location <= 2 or not 0 <= self.huffman_extent <= 2:
            raise GlobalIndexError("Invalid Huffman location/extent")
        if self.compression == 7 and (self.huffman_location or self.huffman_extent):
            raise GlobalIndexError("Uncompressed entry cannot reference Huffman metadata")

    def encode(self) -> bytes:
        return COMPRESS.pack(0, self.compression, self.huffman_location,
                             self.huffman_extent, 0)


def validate_locale(raw: bytes) -> None:
    if not isinstance(raw, bytes) or not 514 <= len(raw) <= 65535:
        raise GlobalIndexError("LocaleTable_t must have size+256 UTF16 mappings")
    declared = struct.unpack_from(">H", raw)[0]
    if declared != len(raw) or struct.unpack_from(">H", raw, 2)[0] != 0:
        raise GlobalIndexError("Locale size or zero-character mapping inconsistent")
    for i in range(256):
        value = struct.unpack_from(">H", raw, 2 + 2*i)[0]
        if value >= 0x8000:
            # Negative signed Ushort is distance to an appended string.
            destination = (-((value ^ 0xffff) + 1)) & 0xffff
            if not 514 <= destination < len(raw):
                raise GlobalIndexError("Locale ligature offset is outside Strings[]")
            if b"\x00" not in raw[destination:]:
                raise GlobalIndexError("Locale ligature lacks terminator")


def ordered_root_index_types(bitmap: bytes) -> tuple[int, ...]:
    """External bitmap MSB-first: spec Figure 2-8, index 0 at first MSB."""
    if not isinstance(bitmap, bytes) or len(bitmap) != EXTERNAL_BITMAP_BYTES:
        raise GlobalIndexError("Global external bitmap requires 8 bytes")
    return tuple(i for i in range(64)
                 if bitmap[i // 8] & (0x80 >> (i % 8)))


def verify_region_root_order(*, media_header: bytes, index_root_pids: tuple[int, ...],
                             global_kd_pid: int) -> tuple[int, ...]:
    """Link the media external-index bitmap to a supplied region root array.

    Root offsets/count reside in GlbMapHeader_t, a separate authority.
    The caller must supply that separately decoded root array. All
    spatial index entries 0..7 must point to the SAME global KD root.
    """
    if len(media_header) != HEADER_BYTES:
        raise GlobalIndexError("Missing actual 2048-byte GlbMediaHeader_t")
    bitmap = media_header[EXTERNAL_BITMAP_AT:
                          EXTERNAL_BITMAP_AT + EXTERNAL_BITMAP_BYTES]
    positions = ordered_root_index_types(bitmap)
    if len(index_root_pids) != len(positions):
        raise GlobalIndexError("Root PID count disagrees with external-index bitmap")
    if global_kd_pid & 0x80000000:
        raise GlobalIndexError("External Global KD root is not a direct regional parcel")
    for t, pid in zip(positions, index_root_pids):
        if t < 8 and pid != global_kd_pid:
            raise GlobalIndexError("Spatial root PID disagrees with Global KD authority")
        if not isinstance(pid, int) or not 0 <= pid <= 0xffffffff:
            raise GlobalIndexError("Root ParcelID is not an unsigned32 value")
    return positions


def _check_ref_sequence(name: str, entries: tuple[RefDataEntry, ...]) -> int:
    if not entries:
        return 0
    if not all(isinstance(x, RefDataEntry) for x in entries):
        raise GlobalIndexError("Invalid reference-data entry type for " + name)
    if len({x.parcel_id for x in entries}) != len(entries):
        raise GlobalIndexError("Same physical reference parcel repeated in " + name)
    previous = -1
    for e in entries:
        if e.last_index <= previous:
            raise GlobalIndexError("Reference-data record extents must strictly ascend")
        previous = e.last_index
    return entries[-1].last_index


@dataclass(frozen=True)
class BuiltGlobalIndex:
    media_header: bytes
    index_parcel: bytes
    ref_tables: tuple[tuple[str, tuple[RefDataEntry, ...]], ...]
    levels: tuple[MetadataLevel, ...]
    modules: tuple[MetadataModule, ...]
    locale: bytes | None

    @property
    def index_start(self) -> int:
        return HEADER_BYTES

    @property
    def next_data_start(self) -> int:
        return HEADER_BYTES + len(self.index_parcel)


def build_global_media_index(
    source_header: bytes, *,
    references: Mapping[str, tuple[RefDataEntry, ...]],
    metadata_levels: tuple[MetadataLevel, ...] = (),
    metadata_modules: tuple[MetadataModule, ...] = (),
    compression: tuple[CompressionEntry, ...] = (),
    locale: bytes | None = None,
) -> BuiltGlobalIndex:
    """Compile all implemented index sections with 2-byte alignment.

    The source header's OTHER fields are preserved; if they already refer
    to unsupported icon, voice, Huffman and generic index tables, refuse
    the rebuild rather than detach those links.
    """
    if not isinstance(source_header, bytes) or len(source_header) != HEADER_BYTES:
        raise GlobalIndexError("Complete caller-supplied 2048-byte header is required")
    fields = parse_media_size_fields(source_header)
    if not isinstance(references, Mapping) or set(references) - set(REF_FAMILIES):
        raise GlobalIndexError("Unknown Global Media Reference Data index family")
    if not isinstance(metadata_levels, tuple) or not all(
            isinstance(x, MetadataLevel) for x in metadata_levels):
        raise GlobalIndexError("Invalid MetadataLevel_t entries")
    if not isinstance(metadata_modules, tuple) or not all(
            isinstance(x, MetadataModule) for x in metadata_modules):
        raise GlobalIndexError("Invalid MetadataModule_t entries")
    if not isinstance(compression, tuple) or not all(
            isinstance(x, CompressionEntry) for x in compression):
        raise GlobalIndexError("Invalid CompressInfo_t entries")
    if locale is not None:
        validate_locale(locale)
    # Header has known offset/count pairs for unimplemented families.
    # Never erase them. Rebuilding a nonempty structure requires its writer.
    if any(source_header[i:i+2] != b"\x00\x00"
           for i in (ICONS_AT, ICONS_AT+2, ICONS_AT+4, ICONS_AT+6,
                     VOICE_AT, VOICE_AT+2, VOICE_AT+4, HUFF_AT,
                     HUFF_AT+2)):
        raise GlobalIndexError("Icon/voice/Huffman tables need dedicated array producer")
    if metadata_levels and not metadata_modules:
        raise GlobalIndexError("Metadata levels without referenced modules")
    available_levels = {x.level for x in metadata_levels}
    if metadata_modules and (not metadata_levels or
                             any(x.level not in available_levels for x in metadata_modules)):
        raise GlobalIndexError("Metadata module does not belong to a declared level")
    if len({(x.level, x.module_id) for x in metadata_modules}) != len(metadata_modules):
        raise GlobalIndexError("Duplicate metadata module (level, ID)")
    if len({x.library_version for x in metadata_levels}) != len(metadata_levels):
        raise GlobalIndexError("Duplicate Access Library version")
    if any(c.compression != 7 for c in compression):
        raise GlobalIndexError("Compression trees need their own authenticated writer")

    mutable = bytearray(source_header)
    space = bytearray()

    def put(data: bytes) -> int:
        if not data:
            return 0
        if len(space) & 1:
            space.append(0)
        position = len(space)
        if position + len(data) > fields.next_index_sectors * fields.table.sector_bytes:
            raise GlobalIndexError("Global Media Index exceeds ucNextParcelLen capacity")
        space.extend(data)
        return position

    if metadata_levels:
        offset = put(b"".join(x.encode() for x in metadata_levels))
        struct.pack_into(">HH", mutable, METADATA_LEVEL_AT, offset, len(metadata_levels))
    else:
        struct.pack_into(">HH", mutable, METADATA_LEVEL_AT, 0, 0)
    if metadata_modules:
        offset = put(b"".join(x.encode() for x in metadata_modules))
        struct.pack_into(">HH", mutable, METADATA_MODULE_AT, offset, len(metadata_modules))
    else:
        struct.pack_into(">HH", mutable, METADATA_MODULE_AT, 0, 0)
    # The caller owns usMetadataHashvalue. It cannot be derived here from
    # an unknown vendor module-hash algorithm.
    if metadata_modules and mutable[METADATA_HASH_AT:METADATA_HASH_AT+2] == b"\x00\x00":
        raise GlobalIndexError("Metadata modules require supplied vendor hash authority")

    owned_refs = []
    for i, family in enumerate(REF_FAMILIES):
        entries = tuple(references.get(family, ()))
        if len(entries) > 65535:
            raise GlobalIndexError("Too many reference-data parcels")
        max_index = _check_ref_sequence(family, entries)
        start = put(b"".join(e.encode() for e in entries)) if entries else 0
        struct.pack_into(">HHH", mutable, REF_TRIPLES_AT + i*6,
                         start, len(entries), max_index)
        owned_refs.append((family, entries))

    if len(compression) > 65535:
        raise GlobalIndexError("Too many compression entries")
    comp_at = put(b"".join(x.encode() for x in compression)) if compression else 0
    struct.pack_into(">HH", mutable, COMPRESS_AT, comp_at, len(compression))
    if locale is not None:
        loc_at = put(locale)
        struct.pack_into(">HH", mutable, LOCALE_AT, loc_at, len(locale))
    else:
        struct.pack_into(">HH", mutable, LOCALE_AT, 0, 0)
    if not space:
        raise GlobalIndexError("Cannot emit an empty Global Media Index")
    capacity = fields.next_index_sectors * fields.table.sector_bytes
    if len(space) > capacity:
        raise GlobalIndexError("Global Media Index exceeded physical capacity")
    out = BuiltGlobalIndex(bytes(mutable), bytes(space).ljust(capacity,b"\x00"),
                           tuple(owned_refs), metadata_levels, metadata_modules, locale)
    verify_global_media_index(out)
    return out


def verify_global_media_index(out: BuiltGlobalIndex) -> None:
    if not isinstance(out, BuiltGlobalIndex):
        raise GlobalIndexError("Global media index object required")
    fields = parse_media_size_fields(out.media_header)
    capacity = fields.next_index_sectors * fields.table.sector_bytes
    if len(out.index_parcel) != capacity:
        raise GlobalIndexError("Global Media Index physical size incorrect")
    raw = out.index_parcel
    regions = []

    def visit(start: int, count: int, record_size: int, name: str) -> bytes:
        if not count:
            if start:
                raise GlobalIndexError(name + " has nonzero offset with zero count")
            return b""
        if start & 1 or start < 0 or start + count*record_size > len(raw):
            raise GlobalIndexError(name + " index offset/extent invalid")
        regions.append((start,start+count*record_size,name))
        return raw[start:start+count*record_size]

    ml_at, ml_count = struct.unpack_from(">HH",out.media_header,METADATA_LEVEL_AT)
    level_bytes = visit(ml_at,ml_count,LEVEL.size,"MetadataLevel")
    if level_bytes != b"".join(x.encode() for x in out.levels):
        raise GlobalIndexError("MetadataLevel array differs from declared source")
    mm_at, mm_count = struct.unpack_from(">HH",out.media_header,METADATA_MODULE_AT)
    module_bytes = visit(mm_at,mm_count,MODULE.size,"MetadataModule")
    if module_bytes != b"".join(x.encode() for x in out.modules):
        raise GlobalIndexError("MetadataModule array differs from declared source")
    if len(out.ref_tables) != len(REF_FAMILIES):
        raise GlobalIndexError("Reference index families incomplete")
    for i,(name, entries) in enumerate(out.ref_tables):
        if name != REF_FAMILIES[i]:
            raise GlobalIndexError("Unexpected reference family order")
        start,count,last = struct.unpack_from(">HHH",out.media_header,REF_TRIPLES_AT+i*6)
        payload = visit(start,count,REF.size,name)
        if count != len(entries) or last != _check_ref_sequence(name,entries):
            raise GlobalIndexError("RefDataIndex counts or maxima disagree")
        decoded = tuple(RefDataEntry.decode(payload[k:k+REF.size])
                        for k in range(0,len(payload),REF.size))
        if decoded != entries:
            raise GlobalIndexError("RefDataIndex contents differ from source")
    cs,cc = struct.unpack_from(">HH",out.media_header,COMPRESS_AT)
    comp_data=visit(cs,cc,COMPRESS.size,"Compression")
    if cc:
        for i in range(0,len(comp_data),COMPRESS.size):
            if comp_data[i:i+COMPRESS.size] != COMPRESS.pack(0,7,0,0,0):
                raise GlobalIndexError("Unsupported compression metadata bytes")
    loc_at,loc_len = struct.unpack_from(">HH",out.media_header,LOCALE_AT)
    if loc_len:
        raw_locale = visit(loc_at,1,loc_len,"Locale")
        validate_locale(raw_locale)
        if raw_locale != out.locale:
            raise GlobalIndexError("Locale data differs from supplied original bytes")
    elif loc_at or out.locale is not None:
        raise GlobalIndexError("Missing or unexpected locale index")
    # Allow no gaps other than alignment and final sector padding;
    # forbid overlapping arrays, including metadata and reference indices.
    regions.sort()
    for (a,b,_),(c,d,_) in zip(regions,regions[1:]):
        if c < b:
            raise GlobalIndexError("Global Media Index arrays overlap")
    if any(raw[b:c] != bytes(c-b)
           for (_,b,_),(c,_,_) in zip(regions,regions[1:])):
        raise GlobalIndexError("Nonzero garbage between Global Media Index arrays")
    if regions and raw[regions[-1][1]:].strip(b"\x00"):
        raise GlobalIndexError("Global Media Index contains unowned trailing bytes")


def verify_global_reference_targets(out: BuiltGlobalIndex, media_file: bytes,
                                    *, referenced_metadata: bool = True) -> None:
    """Check actual region-0 PclHdr and offsets for every indexed target.

    The data parcel bytes must already exist. No phantom reference
    catalog can pass. Record CONTENT semantics are a separate codec gate.
    """
    if len(media_file) < out.next_data_start:
        raise GlobalIndexError("Truncated Global Media File")
    if media_file[:HEADER_BYTES] != out.media_header or (
            media_file[HEADER_BYTES:out.next_data_start] != out.index_parcel):
        raise GlobalIndexError("Global bootstrap header/index differ from source")
    table=parse_media_size_fields(out.media_header).table

    def target(pid: int, first_offset: int) -> tuple[int,int]:
        _pid("Global Media target",pid)
        sizeindex=(pid>>24)&63
        length=table.bytes_for(sizeindex)
        at=(pid&0xffffff)*table.sector_bytes
        if at < out.next_data_start or at + length > len(media_file):
            raise GlobalIndexError("Global data PID points outside reference parcel section")
        record=PCL.unpack_from(media_file,at)
        if record[0] != pid or record[3] != 0:
            raise GlobalIndexError("Actual global reference PclHdr PID/region mismatch")
        if not PCL.size <= first_offset < length:
            raise GlobalIndexError("Reference descriptor offset outside physical data parcel")
        return at,length

    for _,entries in out.ref_tables:
        for entry in entries:
            target(entry.parcel_id,entry.index_offset)
            target(entry.parcel_id,entry.description_offset)
    if referenced_metadata:
        for module in out.modules:
            at,length=target(module.first_parcel_id,PCL.size)
            if module.byte_length > length-PCL.size:
                raise GlobalIndexError("Metadata module byte length exceeds parcel payload")
            target(module.second_parcel_id,PCL.size)

"""Evidence-constrained SDAL 1.7 global KD index parcel codec.

Only the observed OEM 0x5000-byte, 256-byte-addressed, type-255
IDxPclHdr_t profile is supported. Tree NODE semantics are not decoded.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

PCL = struct.Struct(">IHBBBBHHHHH")  # SDAL 1.7 PclHdr_t, 20 bytes
OEM_SECTOR = 256
OEM_INDEX_BYTES = 0x5000


class EvidenceError(ValueError):
    pass


def compose_parcel_id(*, file_offset: int, size_index: int,
                      redundancy: bool, external: bool = False,
                      address_unit: int = OEM_SECTOR) -> int:
    """Construct direct ParcelID_t fields using bits 30 and 29..24.

    External ParcelID entries are indirect references. Never combine an
    external flag and physical direct address as if they were equivalent.
    """
    if external:
        raise EvidenceError("External ParcelID needs an indirection table")
    if not isinstance(file_offset, int) or not isinstance(size_index, int):
        raise EvidenceError("Offset and size index must be integers")
    if not isinstance(address_unit, int) or address_unit <= 0:
        raise EvidenceError("Invalid address unit")
    if file_offset < 0 or file_offset % address_unit:
        raise EvidenceError("File offset is not sector-aligned")
    units = file_offset // address_unit
    if units > 0xFFFFFF or not 0 <= size_index <= 63:
        raise EvidenceError("ParcelID address or size index out of range")
    return units | (size_index << 24) | ((1 << 30) if redundancy else 0)


def header_fields(raw: bytes) -> dict:
    if len(raw) != PCL.size:
        raise EvidenceError("PclHdr_t must occupy exactly 20 bytes")
    pid, desc, typ, region, swap, hi, low, cmpkind, cmpoffset, uncomp, extension = PCL.unpack(raw)
    return {
        "parcel_id": pid, "parcel_type": typ, "region": region,
        "descriptor": desc, "endian_swap": swap,
        "size_index": (pid >> 24) & 63,
        "external": bool(pid & (1 << 31)),
        "redundancy": bool(pid & (1 << 30)),
        "offset_units": pid & 0xFFFFFF,
        "compressed_bits": (hi << 16) | low,
        "compression_type": cmpkind,
        "compression_data_offset": cmpoffset,
        "uncompressed_size_field": uncomp,
        "extension_offset": extension,
    }


@dataclass(frozen=True)
class IndexParcel:
    raw_header: bytes
    absolute_offset: int
    root_offsets: tuple[int, ...]
    root_blobs: tuple[bytes, ...]

    def reassemble(self) -> bytes:
        """Recompute the U16 offset table from raw tree slices.

        The final slice intentionally includes OEM parcel padding, so
        exact read->write comparison retains the complete source extent.
        """
        n = len(self.root_blobs)
        if not 0 < n <= 65535:
            raise EvidenceError("Invalid number of roots")
        cursor = 24 + 2 * n
        locations = []
        for tree in self.root_blobs:
            if not tree or cursor > 65535:
                raise EvidenceError("Empty root or U16 location overflow")
            locations.append(cursor)
            cursor += len(tree)
        if tuple(locations) != self.root_offsets:
            raise EvidenceError("Tree spans and index offsets disagree")
        if cursor != OEM_INDEX_BYTES:
            raise EvidenceError("Index parcel must fit measured OEM extent")
        return (self.raw_header + struct.pack(">HH", n, 0)
                + struct.pack(">" + str(n) + "H", *locations)
                + b"".join(self.root_blobs))


def decode_index_parcel(blob: bytes, *, absolute_offset: int) -> IndexParcel:
    """Fail-closed decoder for independently observed type-255 index parcels."""
    if len(blob) != OEM_INDEX_BYTES:
        raise EvidenceError("Expected 0x5000-byte OEM index span")
    h = header_fields(blob[:20])
    if (h["parcel_type"], h["region"], h["endian_swap"]) != (255, 1, 0):
        raise EvidenceError("Not a type-255 region-one index header")
    if (h["external"] or not h["redundancy"]
            or h["size_index"] != 8
            or h["offset_units"] * OEM_SECTOR != absolute_offset):
        raise EvidenceError("Index ParcelID address, index or flags mismatch")
    if (h["descriptor"] or h["compressed_bits"] or h["compression_type"]
            or h["compression_data_offset"] or h["uncompressed_size_field"]
            or h["extension_offset"]):
        raise EvidenceError("Unsupported OEM index header fields")
    count, ext = struct.unpack_from(">HH", blob, 20)
    if ext or not 0 < count <= (len(blob) - 24) // 2:
        raise EvidenceError("Invalid IDxPclHdr_t count or extension")
    offsets = struct.unpack_from(">" + str(count) + "H", blob, 24)
    if offsets[0] != 24 + 2 * count:
        raise EvidenceError("First root must follow the offset table")
    if offsets[-1] >= len(blob) or any(b <= a for a, b in zip(offsets, offsets[1:])):
        raise EvidenceError("Root offsets are not strictly ascending and in bounds")
    spans = tuple(blob[a:b] for a, b in zip(offsets, (*offsets[1:], len(blob))))
    result = IndexParcel(blob[:20], absolute_offset, offsets, spans)
    if result.reassemble() != blob:
        raise EvidenceError("Index parcel reconstruction disagrees with input")
    return result


def encode_new_index_parcel(*, file_offset: int, root_blobs: tuple[bytes, ...],
                            size_index: int, capacity_bytes: int = OEM_INDEX_BYTES) -> bytes:
    """Encode a type-255 index with caller-supplied, independently valid KD nodes.

    This function does NOT generate KD trees, map geometry or global headers.
    """
    if capacity_bytes != OEM_INDEX_BYTES:
        raise EvidenceError("Unverified index size profile")
    pid = compose_parcel_id(file_offset=file_offset, size_index=size_index,
                            redundancy=True)
    header = PCL.pack(pid, 0, 255, 1, 0, 0, 0, 0, 0, 0, 0)
    if not 0 < len(root_blobs) <= 65535:
        raise EvidenceError("Missing or excessive roots")
    cursor, positions = 24 + 2 * len(root_blobs), []
    for root in root_blobs:
        if not root or cursor > 65535:
            raise EvidenceError("Empty tree or U16 offset overflow")
        positions.append(cursor)
        cursor += len(root)
    if cursor > capacity_bytes:
        raise EvidenceError("Roots exceed available parcel capacity")
    return (header + struct.pack(">HH", len(root_blobs), 0)
            + struct.pack(">" + str(len(root_blobs)) + "H", *positions)
            + b"".join(root_blobs) + bytes(capacity_bytes - cursor))

import io
import struct
from typing import List, Tuple, Optional
from .routing_format import deg_to_ntu 

# Импортируем всё из constants, чтобы encoder видел MAX_USHORT и PIDs
from .constants import (
    NO_COMPRESSION, 
    PCL_HEADER_SIZE, 
    MAX_USHORT,
    UNCOMPRESSED_FLAG
)

"""
encoder.py — SDAL/PSF parcel encoder.
"""

# Канонический PclHdr_t (20 байт): I H B B B B H H H H H
_PCL_STRUCT = struct.Struct(">I H B B B B H H H H H")

# ────────────────────────────────────────────────────────────────
# Parcel Encoding
# ────────────────────────────────────────────────────────────────

def encode_bytes(
    pid: int,
    payload: bytes,
    *,
    region: int = 1,
    parcel_type: int = 0,
    parcel_desc: int = 0, 
    offset_units: Optional[int] = None,
    compress_type: int = NO_COMPRESSION,
    size_index: int = 0,
    external_to_region: bool = False,
    redundancy: bool = False,
    block_size: int = 4096,
) -> bytes:
    """
    Encodes a payload into a full SDAL parcel (PclHdr_t + data).
    """
    if offset_units is None:
        offset_units = 0

    # SDAL 1.7 ParcelID_t: bit31=external reference, bit30=redundancy,
    # bits29..24=size index, bits23..0=sector offset OR external-index handle.
    # Callers passing an already-composed nonzero PID retain that PID unchanged.
    if pid == 0:
        if not isinstance(offset_units, int) or not 0 <= offset_units <= 0xFFFFFF:
            raise ValueError("ParcelID offset/index must fit into 24 bits")
        if not isinstance(size_index, int) or not 0 <= size_index <= 63:
            raise ValueError("ParcelID size index must fit into 6 bits")
        final_pid = offset_units | (size_index << 24)
        if external_to_region:
            final_pid |= 1 << 31
        if redundancy:
            final_pid |= 1 << 30
    else:
        final_pid = pid

    payload_len = len(payload)
    
    # Сжатие не используется (NO_COMPRESSION), поэтому размеры равны
    cmp_size_hi = 0
    cmp_size_lo = 0
    
    if compress_type != NO_COMPRESSION:
        # Если вдруг включим сжатие в будущем
        compressed_size_bits = payload_len * 8
        cmp_size_hi = (compressed_size_bits >> 16) & 0xFF 
        cmp_size_lo = compressed_size_bits & MAX_USHORT

    us_cmp_data_offset = PCL_HEADER_SIZE
    
    total_uncompressed_size = PCL_HEADER_SIZE + payload_len
    us_cmp_data_uncomp_size = total_uncompressed_size if total_uncompressed_size <= MAX_USHORT else MAX_USHORT
    
    # Упаковка заголовка
    header = _PCL_STRUCT.pack(
        final_pid,                  # ParcelID
        parcel_desc,                # ParcelDesc
        parcel_type,                # ParcelType
        region,                     # Region
        0,                          # EndianSwap (0=Big)
        cmp_size_hi,                # SizeHi
        cmp_size_lo,                # SizeLo
        compress_type,              # CompressType
        us_cmp_data_offset,         # Offset to data
        us_cmp_data_uncomp_size,    # Uncompressed Size
        0                           # Extension Offset
    )

    return header + payload


def encode_strings(
    pid: int,
    strings: List[str],
    *,
    compress_type: int = NO_COMPRESSION, 
    region: int = 1,
    parcel_type: int = 0,
    parcel_desc: int = 0,
    offset_units: Optional[int] = None,
    size_index: int = 0,
    external_to_region: bool = False,
    redundancy: bool = False,
    block_size: int = 4096,
) -> bytes:
    """Encodes a list of strings into a single parcel with offsets table."""
    string_buffer = io.BytesIO()
    for s in strings:
        s_bytes = s.encode('ascii', 'replace') + b'\x00'
        string_buffer.write(s_bytes)
    string_data = string_buffer.getvalue()
    
    offsets_table_buffer = io.BytesIO()
    offsets_table_buffer.write(struct.pack(">I", len(strings)))
    
    current_string_offset = 0
    for s in strings:
        offsets_table_buffer.write(struct.pack(">I", current_string_offset))
        current_string_offset += len(s.encode('ascii', 'replace') + b'\x00')

    payload = offsets_table_buffer.getvalue() + string_data

    return encode_bytes(pid, payload, compress_type=compress_type, region=region, parcel_type=parcel_type, parcel_desc=parcel_desc, offset_units=offset_units)


def encode_cartography(
    pid: int,
    records: List[Tuple[int, List[Tuple[float, float]]]],
    *,
    compress_type: int = NO_COMPRESSION,
    region: int = 1,
    parcel_type: int = 0,
    parcel_desc: int = 0,
    offset_units: Optional[int] = None,
    rect_ntu: Tuple[int, int, int, int] = (0, 0, 0, 0),
    **kwargs
) -> bytes:
    """Encodes a Cartography Parcel (PID 110)."""
    buf = io.BytesIO()
    buf.write(struct.pack(">iiiiH", rect_ntu[2], rect_ntu[0], rect_ntu[3], rect_ntu[1], len(records)))
    for way_id, coords in records:
        buf.write(struct.pack(">I", way_id))
        buf.write(struct.pack(">H", len(coords)))
        for lon, lat in coords:
            lat_ntu, lon_ntu = deg_to_ntu(lat, lon)
            buf.write(struct.pack(">ii", lon_ntu, lat_ntu))
    return encode_bytes(pid, buf.getvalue(), compress_type=compress_type, region=region, parcel_type=parcel_type, parcel_desc=parcel_desc, offset_units=offset_units)


def encode_btree(
    pid: int,
    offsets: List[Tuple[int, int]],
    *,
    compress_type: int = NO_COMPRESSION,
    region: int = 1,
    parcel_type: int = 0,
    parcel_desc: int = 0,
    offset_units: Optional[int] = None,
    **kwargs
) -> bytes:
    """Encodes a B-tree or POI index parcel."""
    buf = io.BytesIO()
    buf.write(struct.pack(">IH", len(offsets), 1))
    for id_val, offset_val in offsets:
        buf.write(struct.pack(">IQ", id_val, offset_val))
    return encode_bytes(pid, buf.getvalue(), compress_type=compress_type, region=region, parcel_type=parcel_type, parcel_desc=parcel_desc, offset_units=offset_units)


def encode_poi_index(pid: int, offsets: List[Tuple[int, int]], **kwargs) -> bytes:
    return encode_btree(pid, offsets, **kwargs)
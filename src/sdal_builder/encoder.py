import bitstruct, zlib, io, struct
from typing import List, Tuple
# Removed dahuffman dependency to avoid KeyError issues

from .constants import PARCEL_HEADER_FMT, HUFFMAN_TABLE

# Convert bitstring table -> (bitsize, value) tuples required by HuffmanCodec
# code_table = {sym: (len(bits), int(bits, 2)) for sym, bits in HUFFMAN_TABLE.items()}

def _hdr(pid: int, body: bytes) -> bytes:
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return bitstruct.pack(PARCEL_HEADER_FMT, pid, len(body), crc, 0, 1, 0, 0)

# Encode raw bytes without compression

def encode_strings(pid: int, strings: List[str]) -> bytes:
    raw = b''.join(s.encode('utf8') + b'\x00' for s in strings)
    return encode_bytes(pid, raw)


def encode_bytes(pid: int, payload: bytes) -> bytes:
    # Return header + raw payload (no Huffman compression)
    return _hdr(pid, payload) + payload


def encode_road_records(
    pid: int,
    records: List[Tuple[int, List[Tuple[float, float]]]]
) -> bytes:
    buf = io.BytesIO()
    for way_id, coords in records:
        buf.write(struct.pack('<IH', way_id, len(coords)))
        for x, y in coords:
            buf.write(struct.pack('<ii', int(x * 1e6), int(y * 1e6)))
    return encode_bytes(pid, buf.getvalue())

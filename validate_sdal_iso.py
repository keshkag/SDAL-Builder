#!/usr/bin/env python3
import sys, io, zlib

# Dependency checks
try:
    import bitstruct
except ImportError:
    print("ERROR: pip install bitstruct")
    sys.exit(1)

try:
    from pycdlib import PyCdlib
except ImportError:
    print("ERROR: pip install pycdlib")
    sys.exit(1)

# SDAL header format and header-size in bytes
FMT    = 'u16u32u32u16u16u8u8'
HDR_LEN = bitstruct.calcsize(FMT) // 8

def validate_sdal_iso(iso_path):
    iso = PyCdlib()
    iso.open(iso_path)

    # list all root files ending with .SDL;1
    recs = iso.list_children(iso_path='/')
    sdl_files = [
        r.file_identifier().decode()
        for r in recs
        if r.is_file() and r.file_identifier().decode().upper().endswith('.SDL;1')
    ]

    ok = True
    for fname in sdl_files:
        print(f"\n=== Validating {fname} ===")
        buf = io.BytesIO()
        iso.get_file_from_iso_fp(buf, iso_path=f"/{fname}")
        data = buf.getvalue()

        ptr, parcel_no, total = 0, 1, len(data)
        while ptr < total:
            if total - ptr < HDR_LEN:
                print(f"  Parcel {parcel_no}: FAIL – incomplete header ({total-ptr} bytes left)")
                ok = False
                break

            header = data[ptr:ptr+HDR_LEN]
            pid, length, crc, *_ = bitstruct.unpack(FMT, header)

            start, end = ptr + HDR_LEN, ptr + HDR_LEN + length
            if end > total:
                print(f"  Parcel {parcel_no}: FAIL – length mismatch (hdr={length}, remain={total-start})")
                ok = False
                break

            payload = data[start:end]
            calc_crc = zlib.crc32(payload) & 0xFFFFFFFF
            if calc_crc != crc:
                print(f"  Parcel {parcel_no}: FAIL – CRC mismatch (hdr={crc:08x}, calc={calc_crc:08x})")
                ok = False
                break

            print(f"  Parcel {parcel_no}: OK (pid={pid}, size={length})")
            ptr, parcel_no = end, parcel_no + 1

    iso.close()
    return ok

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: validate_sdal_iso.py <path/to/sdal.iso>")
        sys.exit(1)
    sys.exit(0 if validate_sdal_iso(sys.argv[1]) else 2)

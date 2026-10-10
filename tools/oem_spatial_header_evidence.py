#!/usr/bin/env python3
"""Read-only audit of real SDAL 1.7 spatial fixed-header profiles.

A compressed parcel header has a 20-byte readable PclHdr_t but its
subsequent spatial header bytes require the documented decompressor.
We therefore record compression and do not pretend raw compressed
bytes are a valid SptlPclHdr_t.
"""
from __future__ import annotations
from collections import Counter
import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_spatial_header import (
    PCL,FIXED_HEADER_BYTES,decode_spatial_header,encode_spatial_header,
    SpatialHeaderError,
)


class SourceError(ValueError):
    pass


def inspect(mapfile: Path, report: Path) -> dict:
    if not mapfile.is_file() or mapfile.is_symlink():
        raise SourceError("Expected one regular authentic SDL map")
    original=json.loads(report.read_text(encoding="utf8"))
    entries=original.get("samples")
    if not isinstance(entries,dict):
        raise SourceError("Missing previously sourced spatial descriptor samples")
    count=Counter()
    found=[]
    with mapfile.open("rb") as f:
        for type_layer,samples in sorted(entries.items()):
            for sample in samples[:3]:
                pid=int(sample["pid"],16)
                if pid&0x80000000:
                    count["external_handles_not_resolved"]+=1
                    continue
                offset=(pid&0xffffff)*256
                f.seek(offset)
                raw=f.read(FIXED_HEADER_BYTES)
                if len(raw)!=FIXED_HEADER_BYTES:
                    count["source_truncated"]+=1
                    continue
                p=PCL.unpack_from(raw)
                if p[0]!=pid or p[2] not in range(7) or p[3]!=1:
                    count["direct_header_mismatch"]+=1
                    continue
                typ=p[2]
                comp=p[7]
                if comp:
                    count["compressed_payload_requires_decoder"]+=1
                    found.append({
                        "pid":f"0x{pid:08X}","parcel_type":typ,
                        "compression_type":comp,"status":"not_decoded_compressed"})
                    continue
                try:
                    decoded=decode_spatial_header(raw)
                except SpatialHeaderError as exc:
                    count["uncompressed_bad_fixed_header"]+=1
                    found.append({
                        "pid":f"0x{pid:08X}","parcel_type":typ,
                        "status":"bad_fixed_header","reason":str(exc)})
                    continue
                if encode_spatial_header(decoded)!=raw:
                    raise SourceError("SptlPclHdr_t wire bytes do not roundtrip")
                count["uncompressed_exact_fixed_header"]+=1
                found.append({
                    "pid":f"0x{pid:08X}","parcel_type":typ,
                    "status":"92_byte_header_roundtrip",
                    "source_offset":offset,
                    "bounding":list(vars(decoded.bounding_rect).values()),
                    "tile":list(vars(decoded.tile_rect).values()),
                    "ancestor":list(vars(decoded.ancestor_rect).values()),
                    "scale":decoded.kd_fields[-2],
                    "layer":decoded.kd_fields[-1]})
    return {
        "schema":"sdal-iter019-spatial-header-source-profiles-v1",
        "original_file":mapfile.name,
        "sptl_fixed_header_bytes":FIXED_HEADER_BYTES,
        "counts":dict(sorted(count.items())),
        "sampled_profiles":found,
        "qualification":(
            "92-byte byte parity is proved only on uncompressed sampled "
            "headers. A compressed parcel must first be decompressed "
            "under its documented compression profile."),
    }


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",type=Path,required=True)
    p.add_argument("--reference-report",type=Path,required=True)
    p.add_argument("--json",type=Path,required=True)
    args=p.parse_args()
    try:
        result=inspect(args.map,args.reference_report)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        p.exit(2,"ERROR: "+str(exc)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print("Verified",result["counts"].get("uncompressed_exact_fixed_header",0),
          "uncompressed spatial common headers")
    return 0


if __name__=="__main__":
    raise SystemExit(main())

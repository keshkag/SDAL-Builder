#!/usr/bin/env python3
"""Read-only source evidence for the SDAL 1.7 GlbMediaHeader size table.

Requires the actual PSF Global Media File header, NOT an OEM INIT.SDL
assumed to have that role merely because of its filename. Emits only
media field/parcel ID metadata, never proprietary parcel payload bytes.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_media_allocator import (
    parse_media_size_fields,MediaLayoutError,HEADER_BYTES,
)
from sdal_builder.oem_spatial_header import PCL

def inspect(media_path:Path,region_path:Path,parcel_ids:tuple[int,...])->dict:
    if (media_path.is_symlink() or not media_path.is_file()
            or region_path.is_symlink() or not region_path.is_file()):
        raise MediaLayoutError("Actual regular global media and regional SDL files required")
    with media_path.open("rb") as stream:
        image=stream.read(HEADER_BYTES)
    fields=parse_media_size_fields(image)
    table=fields.table
    results=[]
    file_bytes=region_path.stat().st_size
    with region_path.open("rb") as stream:
        for pid in parcel_ids:
            if not isinstance(pid,int) or not 0<=pid<=0xffffffff:
                raise MediaLayoutError("Invalid 32-bit source ParcelID")
            if pid&0xc0000000:
                raise MediaLayoutError("External/redundant source IDs need their authority tables")
            index=(pid>>24)&63
            length=table.bytes_for(index)
            at=(pid&0xffffff)*table.sector_bytes
            if at+length>file_bytes:
                raise MediaLayoutError("Source ParcelID size/offset exceeds region file")
            stream.seek(at)
            header=stream.read(PCL.size)
            actual=PCL.unpack(header)
            if actual[0]!=pid:
                raise MediaLayoutError("Original parcel header disagrees with global size authority")
            results.append({"pid":f"0x{pid:08X}","size_index":index,
                            "physical_byte_offset":at,
                            "declared_parcel_bytes":length,
                            "parcel_type":actual[2],"region":actual[3]})
    return {"schema":"sdal-iter023-media-size-evidence-v1",
            "media_file":media_path.name,"region_file":region_path.name,
            "sector_exponent":table.sector_shift,
            "sector_bytes":table.sector_bytes,
            "active_size_count":len(table.sector_counts),
            "referenced_parcels":results,
            "limitation":"No raw OEM payload exported; requires genuine GlbMediaHeader_t"}


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--media",type=Path,required=True)
    p.add_argument("--region",type=Path,required=True)
    p.add_argument("--parcel-id",action="append",required=True)
    p.add_argument("--json",type=Path,required=True)
    args=p.parse_args()
    try:
        ids=tuple(int(v,0) for v in args.parcel_id)
        result=inspect(args.media,args.region,ids)
    except (ValueError,OSError) as exc:
        p.exit(2,"ERROR: "+str(exc)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Verified",len(result["referenced_parcels"]),
          "original parcel IDs against supplied global size authority")
    return 0

if __name__=="__main__":raise SystemExit(main())

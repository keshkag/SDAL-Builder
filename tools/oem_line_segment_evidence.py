#!/usr/bin/env python3
"""Read-only original-source parity audit: SDAL type1 polyline/type0 segment blocks.

Use original KD descriptor sample JSON from Iter018, never copy OEM bytes to
the report or repository. Uncompressed blocks only. Unsupported records are
measured explicitly; they are NOT silently called compatible.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_headers import decode_typed_fixed_header
from sdal_builder.oem_spatial_header import decode_spatial_header,PCL
from sdal_builder.oem_typed_records import decode_type1,RecordError
from sdal_builder.oem_line_geometry import (
    decode_full_polyline,encode_full_polyline,decode_short_polyline_two_point,
    encode_short_polyline_two_point,
)
from sdal_builder.oem_route_segments import (
    decode_route_segment_regular,encode_route_segment_regular,
)

class OEMEvidenceError(ValueError): pass


def decode_block(data:bytes, count:int)->tuple[tuple[bytes,...],int]:
    if not 1<=count<=4096:raise OEMEvidenceError("Invalid records-per-block")
    first,pos=decode_type1(data)
    lengths=[]
    for _ in range(count):
        length,pos=decode_type1(data,pos)
        if not length:raise OEMEvidenceError("Empty source record")
        lengths.append(length)
    if first!=pos:raise OEMEvidenceError("First-record offset contradicts length table")
    finish=pos+sum(lengths)
    if finish>len(data):raise OEMEvidenceError("Source block overruns physical extent")
    result=[]
    for n in lengths:
        result.append(data[pos:pos+n]);pos+=n
    return tuple(result),finish


def audit(source_path:Path,source_report:Path,*,max_parcels:int=32,
          max_blocks_per_parcel:int=16)->dict:
    if (source_path.is_symlink() or not source_path.is_file()
            or source_report.is_symlink() or not source_report.is_file()):
        raise OEMEvidenceError("Original SDL and original-PID evidence report required")
    report=json.loads(source_report.read_text(encoding="utf-8"))
    samples=report.get("samples")
    if not isinstance(samples,dict):raise OEMEvidenceError("Missing typed OEM PID samples")
    counters=Counter();failures=[];profiles=[]
    visited=set()
    with source_path.open("rb") as f:
        f.seek(0,2);size=f.tell()
        for group,items in sorted(samples.items()):
            if not group.startswith(("(0,","(1,")):
                continue
            for item in items:
                if counters["parcels_attempted"]>=max_parcels:break
                pid=int(item["pid"],16)
                if pid in visited:continue
                visited.add(pid)
                if pid&0x80000000:
                    counters["external_parcels_skipped"]+=1
                    continue
                at=(pid&0xffffff)*256
                if at+192>size:
                    counters["invalid_source_extent"]+=1
                    continue
                f.seek(at);header_bytes=f.read(192)
                head=PCL.unpack_from(header_bytes)
                if head[0]!=pid or head[2] not in (0,1) or head[3]!=1:
                    counters["header_mismatch"]+=1
                    continue
                counters["parcels_attempted"]+=1
                if head[7]:
                    counters["compressed_parcels_not_parsed"]+=1
                    continue
                try:
                    header=decode_typed_fixed_header(header_bytes)
                    spatial=decode_spatial_header(header_bytes)
                except ValueError:
                    counters["uncompressed_header_unsupported"]+=1
                    continue
                kind=head[2]
                label="lineDesc" if kind==1 else "segmentDesc"
                desc=dict(header.descriptors)[label]
                arr_offset,rec_total,blocks,shift,max_record,data_offset,max_block=(
                    (desc[0],desc[1],desc[2],desc[3],desc[4],desc[5],desc[6])
                    if kind==1 else
                    (desc[0],desc[1],desc[3],desc[4],desc[5],desc[6],desc[7])
                )
                if (blocks<1 or shift>12 or not 0<max_block<=65535
                        or arr_offset+(blocks*2)>head[9] or data_offset>=head[9]):
                    counters["invalid_block_descriptor"]+=1
                    continue
                for blk in range(min(blocks,max_blocks_per_parcel)):
                    f.seek(at+arr_offset+blk*2)
                    raw_off=f.read(2)
                    if len(raw_off)!=2:raise OEMEvidenceError("Truncated block index")
                    start=int.from_bytes(raw_off,"big")
                    if start>=head[9]:
                        counters["source_block_outside_payload"]+=1
                        continue
                    count=min((1<<shift),rec_total-(blk<<shift))
                    if not count:continue
                    cap=min(max_block,head[9]-start,size-at-start)
                    f.seek(at+start);blob=f.read(cap)
                    try:
                        records,used=decode_block(blob,count)
                    except (ValueError,RecordError):
                        counters["source_block_unsupported"]+=1
                        continue
                    counters["exact_length_table_blocks"]+=1
                    for rid,rec in enumerate(records):
                        counters["records_seen"]+=1
                        try:
                            if kind==1:
                                opts=dict(min_lat=spatial.bounding_rect.min_lat,
                                          min_lon=spatial.bounding_rect.min_long,
                                          scale=spatial.kd_fields[-2])
                                if rec[0]&0x80:
                                    value=decode_short_polyline_two_point(rec,**opts)
                                    reencoded=encode_short_polyline_two_point(value,**opts)
                                    result="short_two_point"
                                else:
                                    value=decode_full_polyline(rec,**opts)
                                    reencoded=encode_full_polyline(value,**opts)
                                    result="full_polyline"
                            else:
                                node_count=dict(header.descriptors)["nodeDesc"][1]
                                value=decode_route_segment_regular(rec,node_count=node_count)
                                reencoded=encode_route_segment_regular(value,node_count=node_count)
                                result="regular_route_segment"
                            if reencoded!=rec:
                                raise OEMEvidenceError("OEM record byte mismatch")
                            counters[result+"_byte_exact"]+=1
                        except (RecordError,ValueError) as exc:
                            counters["unsupported_record_profile"]+=1
                            if len(failures)<32:
                                failures.append({
                                    "parcel_pid":f"0x{pid:08X}",
                                    "record_index":blk*(1<<shift)+rid,
                                    "kind":kind,"record_bytes":len(rec),
                                    "reason":type(exc).__name__+":"+str(exc)[:160],
                                    "sha256":sha256(rec).hexdigest(),
                                })
                profiles.append({"pid":f"0x{pid:08X}","type":kind,
                                 "layer":spatial.kd_fields[-1],
                                 "declared_record_count":rec_total,
                                 "blocks":blocks,"block_shift":shift})
    return {
        "schema":"sdal-iter021-original-line-segment-evidence-v1",
        "source":source_path.name,
        "source_report":source_report.name,
        "counts":dict(sorted(counters.items())),
        "unsupported_record_examples":failures,
        "block_descriptor_profiles":profiles,
        "limitations":[
            "Compressed parcels are explicitly excluded until SZIP is validated.",
            "Only the bounded regular-routing and supported short-polyline grammar is accepted.",
            "Header and record parity does not establish complete graph routing semantics.",
        ],
    }


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",type=Path,required=True)
    p.add_argument("--reference-report",type=Path,required=True)
    p.add_argument("--json",type=Path,required=True)
    p.add_argument("--max-parcels",type=int,default=32)
    args=p.parse_args()
    try:
        output=audit(args.map,args.reference_report,
                     max_parcels=args.max_parcels)
    except (OSError,ValueError,TypeError,KeyError) as exc:
        p.exit(2,"ERROR: "+str(exc)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n",
                         encoding="utf-8")
    print("Exact OEM Cartographic full polylines:",
          output["counts"].get("full_polyline_byte_exact",0),
          "regular route segments:",
          output["counts"].get("regular_route_segment_byte_exact",0))
    return 0

if __name__=="__main__":raise SystemExit(main())

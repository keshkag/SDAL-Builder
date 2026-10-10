#!/usr/bin/env python3
"""Audit uncompressed original SDAL type-0/type-1 typed fixed headers.

The input list of IDs is sourced from the earlier genuine KD descriptor
census, NOT generated/guessed PIDs. Compressed source parcels are recorded
but NEVER parsed as plaintext. Exact re-encoding tests all fixed fields,
including descriptor and maxima bytes. No OEM binary payload is exported.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from hashlib import sha256
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_headers import (
    decode_typed_fixed_header, encode_typed_fixed_header,TypedHeaderError,
)
from sdal_builder.oem_spatial_header import PCL


class SourceAuditError(ValueError):
    pass


def audit(map_path:Path, reference_report:Path, *, max_per_group:int=6)->dict:
    if (not map_path.is_file() or map_path.is_symlink()
            or not reference_report.is_file() or reference_report.is_symlink()):
        raise SourceAuditError("Both source map and independent reference report required")
    source=json.loads(reference_report.read_text(encoding="utf8"))
    samples=source.get("samples")
    if not isinstance(samples,dict):
        raise SourceAuditError("Missing original KD descriptor source samples")
    counts=Counter()
    results=[]
    by_layer=Counter()
    with map_path.open("rb") as fd:
        for group,items in sorted(samples.items()):
            if not (group.startswith("(0,") or group.startswith("(1,")):
                continue
            if not isinstance(items,list):
                raise SourceAuditError("Malformed original descriptor sample")
            for item in items[:max_per_group]:
                pid=int(item["pid"],16)
                if pid&0x80000000:
                    counts["external_id"]+=1
                    continue
                at=(pid&0xffffff)*256
                fd.seek(at)
                buf=fd.read(192)
                if len(buf)<20:
                    counts["truncated"]+=1
                    continue
                head=PCL.unpack_from(buf)
                if head[0]!=pid or head[2] not in (0,1) or head[3]!=1:
                    counts["target_header_does_not_match"]+=1
                    continue
                if head[7]:
                    counts["compressed_unparsed"]+=1
                    continue
                try:
                    parsed=decode_typed_fixed_header(buf)
                    reencoded=encode_typed_fixed_header(parsed)
                except TypedHeaderError as exc:
                    counts["uncompressed_header_failed"]+=1
                    results.append({"pid":f"0x{pid:08X}",
                                    "source_offset":at,"status":"decode_failure",
                                    "cause":str(exc)})
                    continue
                if reencoded!=buf[:len(reencoded)]:
                    raise SourceAuditError("OEM typed fixed header byte mismatch")
                counts["uncompressed_exact_roundtrip"]+=1
                by_layer[(parsed.parcel_type,parsed.layer)]+=1
                desc_info=[]
                for name,fields in parsed.descriptors:
                    desc_info.append({"name":name,"data":fields[:2]})
                results.append({
                    "pid":f"0x{pid:08X}","source_offset":at,
                    "status":"exact_fixed_header_roundtrip",
                    "typed_header_bytes":len(reencoded),
                    "fixed_header_sha256":sha256(reencoded).hexdigest(),
                    "parcel_type":parsed.parcel_type,"layer":parsed.layer,
                    "block_descriptor_count":len(parsed.descriptors),
                    "first_record_ids":(
                        [parsed.first_polyline_id,parsed.first_point_id]
                        if parsed.parcel_type==1 else None),
                    "block_descriptors":desc_info,
                })
    return {
        "schema":"sdal-iter020-genuine-fixed-header-evidence-v1",
        "source_file":map_path.name,
        "counts":dict(sorted(counts.items())),
        "uncompressed_by_type_layer":{
            f"{kind}/{layer}":amount for (kind,layer),amount in sorted(by_layer.items())},
        "metadata_only_samples":results,
        "limitations":[
            "Only original uncompressed type-0/type-1 header bytes are decoded.",
            "This does not parse compressed block payloads or actual road/polyline records.",
            "Cartographic 2-byte initial entity fields are a WE_06Q4 OEM observation",
            "rather than a universal override of the specification's Ulong_t typedef.",
        ],
    }


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",type=Path,required=True)
    p.add_argument("--reference-report",type=Path,required=True)
    p.add_argument("--json",type=Path,required=True)
    args=p.parse_args()
    try:
        output=audit(args.map,args.reference_report)
    except (SourceAuditError,OSError,ValueError,KeyError) as err:
        p.exit(2,"ERROR: "+str(err)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(output,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print("Byte-exact original uncompressed typed headers:",
          output["counts"].get("uncompressed_exact_roundtrip",0))
    return 0

if __name__=="__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Diagnose ten OEM maneuver ParcelID mismatches using SDAL 1.7 §1.4.0.2.

The specification distinguishes direct, external-to-region and redundant
ParcelIDs. Neither indirect nor redundant mechanisms may be invoked when
their flag bits are zero. An exact PID at another physical byte position
is forensic evidence, NOT permission to alter the generator's address law.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import mmap
from pathlib import Path
import struct


class AnomalyError(ValueError):
    pass


def inspect_direct_pid_map(filepath: Path, identifiers: list[int],
                           *, sector_bytes: int = 256) -> dict:
    if filepath.is_symlink() or not filepath.is_file():
        raise AnomalyError("Expected original regular spatial SDL file")
    if not identifiers or len(set(identifiers)) != len(identifiers):
        raise AnomalyError("Must supply unique Parcel IDs")
    if sector_bytes not in (256,512,1024,2048):
        raise AnomalyError("Sector size is not a documented SDAL value")
    results=[]
    with filepath.open("rb") as fd:
        with mmap.mmap(fd.fileno(), 0, access=mmap.ACCESS_READ) as image:
            length=len(image)
            for pid in identifiers:
                if not isinstance(pid,int) or not 0<=pid<=0xffffffff:
                    raise AnomalyError("Parcel ID outside 32-bit range")
                external=bool(pid&0x80000000)
                redundant=bool(pid&0x40000000)
                expected=(pid&0xffffff)*sector_bytes
                if external:
                    raise AnomalyError("External IDs need a validated region-indirection table")
                observed=None
                if expected+20<=length:
                    observed=struct.unpack_from(">I",image,expected)[0]
                physical_headers=[]
                search=0
                raw=pid.to_bytes(4,"big")
                while True:
                    at=image.find(raw,search)
                    if at<0:break
                    search=at+1
                    if (at%sector_bytes==0 and at+20<=length
                            and image[at+6]==3 and image[at+7]==1):
                        physical_headers.append(at)
                results.append({
                    "parcel_id":f"0x{pid:08X}",
                    "size_index":(pid>>24)&63,
                    "external_to_region_bit_31":external,
                    "redundancy_bit_30":redundant,
                    "direct_target_offset":expected,
                    "direct_target_header_pid":(
                        f"0x{observed:08X}" if observed is not None else None),
                    "nominal_target_exact":observed==pid,
                    "matching_type3_region1_header_positions":physical_headers,
                    "matching_header_deltas_from_target":
                        [x-expected for x in physical_headers],
                    "interpretation":(
                        "strict_direct_header_match" if observed==pid
                        else "direct_reference_unresolved_no_implicit_relocation"),
                })
    return {
        "schema":"sdal-iter019-maneuver-id-address-evidence-v1",
        "source":filepath.name,
        "source_bytes":filepath.stat().st_size,
        "sector_bytes":sector_bytes,
        "results":results,
        "counts":{
            "ids":len(results),
            "nominal_mismatch":sum(not r["nominal_target_exact"] for r in results),
            "found_exact_type3_header_elsewhere":sum(
                bool(r["matching_type3_region1_header_positions"]) and
                not r["nominal_target_exact"] for r in results),
            "no_corresponding_type3_header":sum(
                not r["matching_type3_region1_header_positions"] for r in results),
            "matching_header_at_minus_0x5000":sum(
                -0x5000 in r["matching_header_deltas_from_target"] for r in results),
        },
        "specification": [
            "SDAL 1.7 §1.4.0.2: bit31 external-to-region indirection",
            "SDAL 1.7 §1.4.0.2: bit30 redundancy table",
            "SDAL 1.7 §1.4.0.2: bits29..24 size-index into ucaParcelSizes",
            "SDAL 1.7 §1.4.0.2: low24 direct sector offset times 2**usBlockSize",
            "Alternate physical occurrences never validate a shifted direct-reference rule.",
        ],
    }


def ids_from_reference_report(path: Path) -> list[int]:
    report=json.loads(path.read_text(encoding="utf-8"))
    raw=report.get("bad_target_examples")
    if not isinstance(raw,list):
        raise AnomalyError("Expected original source bad_target_examples")
    result=[]
    for row in raw:
        if not isinstance(row,list) or len(row)<2:
            raise AnomalyError("Invalid historical source evidence row")
        pid=int(row[0],16)
        address=int(row[1],16)
        if (pid&0xffffff)*256 != address:
            raise AnomalyError("Historical offset differs from PID sector law")
        result.append(pid)
    return result


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",type=Path,required=True)
    p.add_argument("--reference-report",type=Path,required=True)
    p.add_argument("--json",type=Path,required=True)
    args=p.parse_args()
    try:
        ids=ids_from_reference_report(args.reference_report)
        result=inspect_direct_pid_map(args.map,ids)
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        p.exit(2,"ERROR: "+str(exc)+"\n")
    args.json.parent.mkdir(parents=True,exist_ok=True)
    args.json.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
    print("Verified",result["counts"]["ids"],
          "source Parcel IDs; unresolved direct addresses:",
          result["counts"]["nominal_mismatch"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())

"""Actual generated type-0/type-1 blocks examined by the OEM evidence checker.

The fixtures create real 20-byte PclHdr, typed fixed header, BlkDesc,
indexed record blocks and declared physical Parcel IDs, not mock readers.
"""
from __future__ import annotations
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tools"))
from test_oem_typed_headers import sample
from sdal_builder.oem_spatial_header import PCL
from sdal_builder.oem_typed_headers import encode_typed_fixed_header
from sdal_builder.oem_line_geometry import FullPolyline,encode_full_polyline
from sdal_builder.oem_route_segments import RoutingSegmentRegular,encode_route_segment_regular
from sdal_builder.oem_record_blocks import encode_record_block
from oem_line_segment_evidence import audit

def typed_at(kind,pid,records):
    base=sample(kind,0)
    new_pcl=PCL.pack(pid,184 if kind==1 else 192,kind,1,0,0,0,0,0,2048,0)
    fields=list(base.descriptors)
    key="lineDesc" if kind==1 else "segmentDesc"
    for i,(name,old) in enumerate(fields):
        if name==key:
            if kind==1:
                fields[i]=(name,(768,len(records),1,3,30,512,200))
            else:
                fields[i]=(name,(768,len(records),0,1,1,30,512,200))
        elif kind==0 and name=="nodeDesc":
            fields[i]=(name,(0,2,0,0,0,0,0,0))
    base=replace(base,spatial_prefix=new_pcl+base.spatial_prefix[20:],
                 descriptors=tuple(fields))
    block=encode_record_block(records)
    if len(block.raw)>200:raise AssertionError("Exceeds fixture descriptor")
    src=bytearray(2048)
    header=encode_typed_fixed_header(base)
    src[:len(header)]=header
    src[512:512+len(block.raw)]=block.raw
    src[768:770]=(512).to_bytes(2,"big")
    return src

class OriginalBlockEvidenceTests(unittest.TestCase):
    def build(self,root):
        # Seven generated originals-shaped display polylines.
        lines=tuple(encode_full_polyline(
            FullPolyline(487+i*3,12,512+i*2,1022+i*2,False,0,0,2),
            min_lat=0,min_lon=0) for i in range(7))
        edges=tuple(encode_route_segment_regular(
            RoutingSegmentRegular(0,1,3,0,128,0,0,False,False,0,
                                  30+i,100+i,0),node_count=2)
                    for i in range(2))
        data=bytearray(0x6000)
        data[0x2000:0x2800]=typed_at(1,0x18000020,lines)
        data[0x4000:0x4800]=typed_at(0,0x18000040,edges)
        source=root/"GENERATED1.SDL"
        source.write_bytes(data)
        report=root/"original_descriptor_samples.json"
        report.write_text(json.dumps({"samples":{
            "(1, 0)":[{"pid":"0x18000020"}],
            "(0, 0)":[{"pid":"0x18000040"}],
        }}),encoding="utf-8")
        return source,report

    def test_real_serialized_type0_and_type1_block_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            original,report=self.build(Path(td))
            result=audit(original,report)
            count=result["counts"]
            self.assertEqual(count["full_polyline_byte_exact"],7)
            self.assertEqual(count["regular_route_segment_byte_exact"],2)
            self.assertEqual(count["exact_length_table_blocks"],2)
            self.assertEqual(count["unsupported_record_profile"] if
                             "unsupported_record_profile" in count else 0,0)
            self.assertEqual(original.read_bytes(),original.read_bytes())

    def test_mutated_polyline_block_is_not_counted_successful(self):
        with tempfile.TemporaryDirectory() as td:
            original,report=self.build(Path(td))
            raw=bytearray(original.read_bytes())
            # First full polyline's first record format bit; forces short
            # interpretation, which is invalid for this physical length.
            raw[0x2000+512+8] |= 0x80
            original.write_bytes(raw)
            result=audit(original,report)
            self.assertGreaterEqual(
                result["counts"].get("unsupported_record_profile",0),1)
            self.assertLess(result["counts"].get("full_polyline_byte_exact",0),7)

    def test_read_only_evidence_run_repeatable(self):
        with tempfile.TemporaryDirectory() as td:
            original,report=self.build(Path(td))
            initial=original.read_bytes()
            self.assertEqual(audit(original,report),audit(original,report))
            self.assertEqual(initial,original.read_bytes())

if __name__=="__main__":
    unittest.main()

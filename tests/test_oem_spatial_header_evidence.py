"""Generated-source proof of OEM spatial fixed headers and compression gate."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
sys.path.insert(0,str(ROOT/"src"))
from sdal_builder.oem_spatial_header import DBRect,make_spatial_header
from oem_spatial_header_evidence import inspect


class SpatialHeaderEvidenceTests(unittest.TestCase):
    def write_sample(self,root:Path):
        p=root/"REGION1.SDL"
        data=bytearray(0x5000)
        r=DBRect(0,5242880,524288,5767168)
        data[0x2000:0x2000+92]=make_spatial_header(
            parcel_id=0x18000020,parcel_type=0,
            bounds=r,tile=r,ancestor=r,scale=1,layer=0)
        c=bytearray(make_spatial_header(
            parcel_id=0x18000040,parcel_type=1,
            bounds=r,tile=r,ancestor=r,scale=2,layer=0))
        c[12:14]=b"\x02\x02"
        data[0x4000:0x4000+92]=c
        p.write_bytes(data)
        report=root/"previous.json"
        report.write_text(json.dumps({"samples":{
            "(0,0)":[{"pid":"0x18000020"}],
            "(1,0)":[{"pid":"0x18000040"}],
        }}))
        return p,report

    def test_uncompressed_header_roundtrips_but_compressed_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            source,report=self.write_sample(Path(td))
            result=inspect(source,report)
            self.assertEqual(result["counts"]["uncompressed_exact_fixed_header"],1)
            self.assertEqual(result["counts"]["compressed_payload_requires_decoder"],1)
            entry=next(x for x in result["sampled_profiles"]
                       if x["status"]=="92_byte_header_roundtrip")
            self.assertEqual(entry["source_offset"],0x2000)
            self.assertEqual(entry["parcel_type"],0)
            self.assertEqual(entry["bounding"],[0,5242880,524288,5767168])

    def test_bad_source_pid_is_reported_without_repair(self):
        with tempfile.TemporaryDirectory() as td:
            source,report=self.write_sample(Path(td))
            damaged=bytearray(source.read_bytes())
            damaged[0x2000]^=1
            source.write_bytes(damaged)
            result=inspect(source,report)
            self.assertEqual(result["counts"]["direct_header_mismatch"],1)

    def test_read_only_and_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            source,report=self.write_sample(Path(td))
            before=source.read_bytes()
            self.assertEqual(inspect(source,report),inspect(source,report))
            self.assertEqual(source.read_bytes(),before)


if __name__=="__main__":
    unittest.main()

"""Source-free audit tests for actual typed Cartographic and Routing headers."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tools"))
from sdal_builder.oem_typed_headers import encode_typed_fixed_header
from sdal_builder.oem_spatial_header import DBRect,make_spatial_header
from test_oem_typed_headers import sample
from oem_typed_parcel_evidence import audit,SourceAuditError


class OriginalTypedHeaderAuditTests(unittest.TestCase):
    def files(self,dirname):
        root=Path(dirname)
        src=root/"SAMPLE1.SDL"
        data=bytearray(0x6000)
        route=encode_typed_fixed_header(sample(0,0))
        data[0x2000:0x2000+len(route)]=route
        carto=sample(1,0)
        # The Cartographic sample uses a distinct physical address at 0x4000.
        from dataclasses import replace
        box=DBRect(0,0,100000,100000)
        other=make_spatial_header(parcel_id=0x18000040,
            parcel_type=1,bounds=box,tile=box,ancestor=box,scale=0,layer=0)
        second=encode_typed_fixed_header(replace(carto,spatial_prefix=other))
        data[0x4000:0x4000+len(second)]=second
        src.write_bytes(data)
        references=root/"reference.json"
        references.write_text(json.dumps({"samples":{
            "(0, 0)":[{"pid":"0x18000020"}],
            "(1, 0)":[{"pid":"0x18000040"}],
        }}),encoding="utf8")
        return src,references

    def test_two_physically_placed_generated_typed_headers(self):
        with tempfile.TemporaryDirectory() as td:
            source,refs=self.files(td)
            result=audit(source,refs)
            self.assertEqual(result["counts"]["uncompressed_exact_roundtrip"],2)
            self.assertEqual(result["uncompressed_by_type_layer"],
                             {"0/0":1,"1/0":1})
            self.assertEqual({r["typed_header_bytes"]
                              for r in result["metadata_only_samples"]},
                             {184,192})
            self.assertTrue(all("fixed_header_sha256" in r
                                for r in result["metadata_only_samples"]))

    def test_compressed_target_is_not_misdecoded(self):
        with tempfile.TemporaryDirectory() as td:
            source,refs=self.files(td)
            data=bytearray(source.read_bytes())
            data[0x4000+12:0x4000+14]=b"\x02\x02"
            source.write_bytes(data)
            r=audit(source,refs)
            self.assertEqual(r["counts"]["compressed_unparsed"],1)
            self.assertEqual(r["counts"]["uncompressed_exact_roundtrip"],1)

    def test_wrong_physical_id_preserved_as_error(self):
        with tempfile.TemporaryDirectory() as td:
            source,refs=self.files(td)
            buf=bytearray(source.read_bytes())
            buf[0x2000] ^= 1
            source.write_bytes(buf)
            r=audit(source,refs)
            self.assertEqual(r["counts"]["target_header_does_not_match"],1)

    def test_no_mutations_or_order_nondeterminism(self):
        with tempfile.TemporaryDirectory() as td:
            source,refs=self.files(td)
            before=source.read_bytes()
            self.assertEqual(audit(source,refs),audit(source,refs))
            self.assertEqual(source.read_bytes(),before)


if __name__=="__main__":
    unittest.main()

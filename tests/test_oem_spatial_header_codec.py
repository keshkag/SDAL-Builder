"""SDAL 1.7 fixed spatial header encoder tests: type 0 and 1 prefixes."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_spatial_header import (
    DBRect,SpatialFixedHeader,SpatialHeaderError,
    FIXED_HEADER_BYTES,decode_spatial_header,encode_spatial_header,
    make_spatial_header,PCL,
)


class SpatialHeaderTests(unittest.TestCase):
    def setUp(self):
        self.tile=DBRect(0,5242880,524288,5767168)
        self.ancestor=DBRect(0,5242880,1048576,5767168)

    def test_full_sptl_header_92_bytes_and_header_roundtrip(self):
        for kind in (0,1,2,3,4,5,6):
            original=make_spatial_header(parcel_id=0x18000020,
                                         parcel_type=kind,bounds=self.tile,
                                         tile=self.tile,ancestor=self.ancestor,
                                         scale=2,layer=0)
            self.assertEqual(len(original),FIXED_HEADER_BYTES)
            self.assertEqual(FIXED_HEADER_BYTES,92)
            parsed=decode_spatial_header(original)
            self.assertEqual(parsed.parcel_type,kind)
            self.assertEqual(parsed.parcel_id,0x18000020)
            self.assertEqual(parsed.tile_rect,self.tile)
            self.assertEqual(parsed.ancestor_rect,self.ancestor)
            self.assertEqual(parsed.kd_fields[-2:],(2,0))
            self.assertEqual(encode_spatial_header(parsed),original)

    def test_preserve_nonzero_xref_fields_and_header_fields(self):
        common=PCL.pack(0x18000020,0x0123,0,1,0,0,0,0,0,40,124)
        expected=SpatialFixedHeader(
            common,(200,5,0,0,0,0,0),
            self.tile,self.tile,DBRect(0,0,0,0),
            (92,64,156,80,0,1,4))
        raw=encode_spatial_header(expected)
        self.assertEqual(decode_spatial_header(raw),expected)
        self.assertEqual(encode_spatial_header(expected),raw)

    def test_compressed_body_cannot_be_read_as_plain_spatial_header(self):
        raw=bytearray(make_spatial_header(parcel_id=0x18000020,
            parcel_type=1,bounds=self.tile,tile=self.tile,
            ancestor=self.ancestor,scale=0,layer=0))
        # usCompressType is common PclHdr field #8 (tuple index 7).
        raw[12:14]=b"\x02\x02"
        with self.assertRaisesRegex(SpatialHeaderError,"Compressed"):
            decode_spatial_header(bytes(raw))

    def test_unsupported_region_and_type_fails_closed(self):
        raw=bytearray(make_spatial_header(parcel_id=0x18000020,
            parcel_type=0,bounds=self.tile,tile=self.tile,
            ancestor=self.ancestor,scale=0,layer=0))
        raw[7]=2
        with self.assertRaisesRegex(SpatialHeaderError,"region 1"):
            decode_spatial_header(bytes(raw))
        raw[7]=1
        raw[6]=255
        with self.assertRaisesRegex(SpatialHeaderError,"type 0..6"):
            decode_spatial_header(bytes(raw))

    def test_invalid_rectangle_or_wire_size_fails(self):
        with self.assertRaises(SpatialHeaderError):
            DBRect(0,0,1<<34,2)
        with self.assertRaisesRegex(SpatialHeaderError,"Truncated"):
            decode_spatial_header(bytes(91))
        with self.assertRaisesRegex(SpatialHeaderError,"scale"):
            make_spatial_header(parcel_id=0x18000020,
                parcel_type=0,bounds=self.tile,tile=self.tile,
                ancestor=self.ancestor,scale=256,layer=0)
        with self.assertRaisesRegex(SpatialHeaderError,"field outside"):
            invalid=SpatialFixedHeader(
                PCL.pack(0x18000020,0,0,1,0,0,0,0,0,0,0),
                (1<<20,0,0,0,0,0,0),
                self.tile,self.tile,self.ancestor,(0,0,0,0,0,0,0))
            encode_spatial_header(invalid)

    def test_no_source_mutation_or_nondeterminism(self):
        raw=make_spatial_header(parcel_id=0x18000020,parcel_type=0,
            bounds=self.tile,tile=self.tile,ancestor=self.ancestor,
            scale=0,layer=0)
        self.assertEqual(raw,encode_spatial_header(decode_spatial_header(raw)))
        self.assertEqual(raw,make_spatial_header(parcel_id=0x18000020,
            parcel_type=0,bounds=self.tile,tile=self.tile,ancestor=self.ancestor,
            scale=0,layer=0))


if __name__=="__main__":
    unittest.main()

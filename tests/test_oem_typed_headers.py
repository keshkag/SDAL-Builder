"""Iter020 specification regression: Route/Cartographic typed fixed headers."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_spatial_header import DBRect,make_spatial_header
from sdal_builder.oem_typed_headers import (
    CARTO_FIELDS, ROUTING0_FIELDS,ROUTING1_FIELDS,DESCRIPTOR_LAYOUTS,
    TypedFixedHeader,TypedHeaderError,encode_typed_fixed_header,
    decode_typed_fixed_header,
)

def sample(kind,layer):
    rect=DBRect(0,5242880,524288,5767168)
    prefix=make_spatial_header(
        parcel_id=0x18000020,parcel_type=kind,bounds=rect,
        tile=rect,ancestor=rect,scale=0,layer=layer)
    schema=(CARTO_FIELDS if kind==1 else ROUTING0_FIELDS
            if layer==0 else ROUTING1_FIELDS)
    fields=[]
    for name,dtype in schema:
        count=len(DESCRIPTOR_LAYOUTS[dtype].unpack(bytes(DESCRIPTOR_LAYOUTS[dtype].size)))
        vals=(0,)*(count-1)+(b"\x00\x00",) if dtype=="BlkDesc3" else (0,)*count
        fields.append((name,vals))
    return TypedFixedHeader(kind,layer,prefix,
                            17 if kind==1 else None,
                            19 if kind==1 else None,
                            tuple(fields),
                            (0,)*4 if kind==1 else (0,)*9 if layer==0 else (0,)*10,
                            b"\x00\x00" if kind==1 or layer==0 else b"",
                            b"\x00\x00" if kind==1 else b"")


class TypedHeaderCodecTests(unittest.TestCase):
    def test_three_spec_layouts_full_byte_parity(self):
        for kind,layer,size in ((1,0,184),(1,4,184),(0,0,192),
                                (0,1,164),(0,4,164)):
            with self.subTest(kind=kind,layer=layer):
                example=sample(kind,layer)
                raw=encode_typed_fixed_header(example)
                self.assertEqual(len(raw),size)
                self.assertEqual(decode_typed_fixed_header(raw),example)
                self.assertEqual(encode_typed_fixed_header(
                    decode_typed_fixed_header(raw)),raw)

    def test_observed_16_bit_first_carto_ids_and_two_byte_alignment(self):
        raw=encode_typed_fixed_header(sample(1,0))
        self.assertEqual(raw[92:96],bytes.fromhex("00110013"))
        self.assertEqual(raw[-2:],b"\x00\x00")
        with self.assertRaisesRegex(TypedHeaderError,"16-bit"):
            encode_typed_fixed_header(replace(sample(1,0),
                                             first_polyline_id=0x10000))
        corrupt=raw[:-1]+b"\x01"
        with self.assertRaisesRegex(TypedHeaderError,"alignment"):
            decode_typed_fixed_header(corrupt)

    def test_wrong_descriptor_order_fails(self):
        good=sample(1,0)
        bad=replace(good,descriptors=tuple(reversed(good.descriptors)))
        with self.assertRaisesRegex(TypedHeaderError,"order"):
            encode_typed_fixed_header(bad)

    def test_wrong_type_or_layer_in_common_header_fails(self):
        a=sample(0,0)
        b=sample(0,1)
        with self.assertRaisesRegex(TypedHeaderError,"type/layer"):
            encode_typed_fixed_header(replace(a,spatial_prefix=b.spatial_prefix))

    def test_unsupported_or_truncated_formats_are_rejected(self):
        for kind,layer in ((1,0),(0,0),(0,2)):
            raw=encode_typed_fixed_header(sample(kind,layer))
            with self.assertRaisesRegex(TypedHeaderError,"Truncated"):
                decode_typed_fixed_header(raw[:-1])
        a=sample(0,0)
        with self.assertRaisesRegex(TypedHeaderError,"Routing"):
            encode_typed_fixed_header(replace(a,first_polyline_id=2))

    def test_preserve_nonzero_descriptor_fields(self):
        a=sample(0,0)
        fields=list(a.descriptors)
        fields[0]=("nodeDesc",(0x456,21,3000,1,4,32,0x789,35))
        raw=encode_typed_fixed_header(replace(a,descriptors=tuple(fields)))
        result=decode_typed_fixed_header(raw)
        self.assertEqual(result.descriptors[0],fields[0])
        self.assertEqual(encode_typed_fixed_header(result),raw)


if __name__=="__main__":
    unittest.main()

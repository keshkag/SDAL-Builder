"""Iter020 signed-off SDAL Type1/Type4 and bounded route/carto record parity."""
from __future__ import annotations
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_records import (
    TYPE1_MAX,TYPE4_MAX,RecordError,encode_type1,decode_type1,
    encode_type4,decode_type4,CartographicPointBasic,
    encode_carto_point_basic,decode_carto_point_basic,
    RoutingNodeBasic,encode_route_node_basic,decode_route_node_basic,
)

class TypedRecordTests(unittest.TestCase):
    def test_type1_all_spec_transition_boundaries(self):
        specimens={
            0:"00",239:"ef",240:"f000",4079:"feff",
            4080:"ff0000",65519:"ffefff",65520:"fff00000",
            TYPE1_MAX:"ffffffff",
        }
        for number,wire in specimens.items():
            with self.subTest(number=number):
                raw=encode_type1(number)
                self.assertEqual(raw.hex(),wire)
                self.assertEqual(decode_type1(raw),(number,len(raw)))
        with self.assertRaises(RecordError):
            encode_type1(TYPE1_MAX+1)
        with self.assertRaises(RecordError):
            encode_type1(-1)

    def test_type4_exact_wire_limit_and_spec_printed_typo(self):
        specimens={
            0:"0000",61439:"efff",
            61440:"f00000",TYPE4_MAX:"ffffff",
        }
        for number,wire in specimens.items():
            with self.subTest(number=number):
                raw=encode_type4(number)
                self.assertEqual(raw.hex(),wire)
                self.assertEqual(decode_type4(raw),(number,len(raw)))
        self.assertEqual(TYPE4_MAX,1110015)
        # Printed 1,110,095 is 80 higher than encoded 20-bit capacity.
        with self.assertRaises(RecordError):
            encode_type4(1110095)

    def test_reject_truncation_and_noncanonical_sequences(self):
        for raw in (b"",b"\xf0",b"\xff",b"\xff\xf0",
                    b"\xff\xef",b"\xff\xf1\x00"):
            with self.subTest(raw=raw),self.assertRaises(RecordError):
                decode_type1(raw)
        for raw in (b"",b"\x0a",b"\xf0",b"\xff\xff"):
            with self.subTest(raw=raw),self.assertRaises(RecordError):
                decode_type4(raw)

    def test_random_2000_integer_roundtrips(self):
        rng=random.Random(2020)
        for _ in range(2000):
            a=rng.randrange(TYPE1_MAX+1)
            b=rng.randrange(TYPE4_MAX+1)
            self.assertEqual(decode_type1(encode_type1(a))[0],a)
            self.assertEqual(decode_type4(encode_type4(b))[0],b)

    def test_carto_point_basic_is_actual_encoded_record(self):
        item=CartographicPointBasic(4,5243000,700100,0)
        raw=encode_carto_point_basic(item,min_lat_ntu=5242880,
                                     min_long_ntu=700000,scale=0)
        self.assertEqual(raw.hex(),"04007800640f0000")
        self.assertEqual(decode_carto_point_basic(raw,min_lat_ntu=5242880,
                        min_long_ntu=700000),(item,len(raw)))
        with self.assertRaises(RecordError):
            decode_carto_point_basic(raw[:5]+b"\x01"+raw[6:],
                min_lat_ntu=5242880,min_long_ntu=700000)

    def test_route_node_basic_and_name_change_bits(self):
        # Three arms: three pairwise name-change bits, stored MSB first.
        item=RoutingNodeBasic(5243000,700100,(0,1,255),b"\xa0")
        raw=encode_route_node_basic(item,min_lat_ntu=5242880,
                                    min_long_ntu=700000)
        self.assertEqual(raw[:7].hex(),"00000078006403")
        self.assertEqual(decode_route_node_basic(raw,min_lat_ntu=5242880,
                         min_long_ntu=700000),(item,len(raw)))
        with self.assertRaisesRegex(RecordError,"name-change"):
            encode_route_node_basic(RoutingNodeBasic(5243000,700100,
                                                    (0,1,2),b"\x01"),
                                    min_lat_ntu=5242880,min_long_ntu=700000)

    def test_partial_or_unsupported_records_fail_closed(self):
        p=CartographicPointBasic(1,0,0,0)
        with self.assertRaises(RecordError):
            encode_carto_point_basic(p,min_lat_ntu=1,min_long_ntu=0)
        with self.assertRaises(RecordError):
            encode_carto_point_basic(
                CartographicPointBasic(1,0,0,32768),min_lat_ntu=0,min_long_ntu=0)
        q=RoutingNodeBasic(0,0,(1,),b"")
        raw=encode_route_node_basic(q,min_lat_ntu=0,min_long_ntu=0)
        with self.assertRaisesRegex(RecordError,"Unsupported"):
            decode_route_node_basic(b"\x00\x01"+raw[2:],
                                    min_lat_ntu=0,min_long_ntu=0)
        with self.assertRaisesRegex(RecordError,"Truncated"):
            decode_route_node_basic(raw[:-1],min_lat_ntu=0,min_long_ntu=0)

    def test_scaled_coordinates_do_not_truncate_osm_geometry(self):
        p=CartographicPointBasic(0,20,100,0)
        with self.assertRaisesRegex(RecordError,"not exactly representable"):
            encode_carto_point_basic(p,min_lat_ntu=0,min_long_ntu=0,scale=3)
        good=CartographicPointBasic(0,24,104,0)
        raw=encode_carto_point_basic(good,min_lat_ntu=0,min_long_ntu=0,scale=3)
        self.assertEqual(decode_carto_point_basic(raw,min_lat_ntu=0,
                                                   min_long_ntu=0,scale=3)[0],good)


if __name__=="__main__":
    unittest.main()

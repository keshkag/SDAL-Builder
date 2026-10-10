"""Iter021 Cartographic geometry: actual spec bit layout and strict inverses."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_records import RecordError
from sdal_builder.oem_line_geometry import (
    FullPolyline,CartographicPosition,ShortPolylineTwoPoint,
    encode_full_polyline,decode_full_polyline,
    encode_carto_position,decode_carto_position,
    encode_carto_positions,decode_carto_positions,
    encode_short_polyline_two_point,decode_short_polyline_two_point,
)

class CartographicGeometryTests(unittest.TestCase):
    def test_real_oem_shaped_full_nonnavigable_polyline(self):
        # Independent source forensic observation:
        # initial line of BENELUX1 type1 0x00092d7a, record length 10.
        sample=FullPolyline(487,12,512,1022,False,0,0,19)
        raw=encode_full_polyline(sample,min_lat=0,min_lon=0)
        self.assertEqual(raw.hex(),"01e7000c020003fe0013")
        self.assertEqual(decode_full_polyline(raw,min_lat=0,min_lon=0),sample)

    def test_navigable_road_fields_and_canonical_offsets(self):
        sample=FullPolyline(25,0,5243000,300100,True,3,1,2,(35,50),
                            rank=2,divider_loc=1,divider_legal=True,
                            attribute_index=6)
        raw=encode_full_polyline(sample,min_lat=5242880,min_lon=300000)
        self.assertEqual(decode_full_polyline(raw,min_lat=5242880,min_lon=300000),
                         sample)
        with self.assertRaisesRegex(RecordError,"Reserved"):
            bad=bytearray(raw)
            pos=3+1+2+2
            bad[pos]|=0x10
            decode_full_polyline(bytes(bad),min_lat=5242880,min_lon=300000)

    def test_nonroad_cannot_silently_keep_navigation_attributes(self):
        bad=FullPolyline(0,3,100,100,False,3,0,0)
        with self.assertRaisesRegex(RecordError,"Non-navigable"):
            encode_full_polyline(bad,min_lat=0,min_lon=0)
        bad=FullPolyline(0,0,100,100,True,0,0,0,rank=0,attribute_index=0)
        with self.assertRaisesRegex(RecordError,"direction"):
            encode_full_polyline(bad,min_lat=0,min_lon=0)

    def test_signed_11_bit_position_edges_and_bitflags(self):
        for lat,lon in ((-1024,1023),(1023,-1024),(0,0),(-1,-1)):
            point=CartographicPosition(-lat,-lon,True,True)
            raw=encode_carto_position(point,prev_lat=0,prev_lon=0)
            self.assertEqual(len(raw),3)
            self.assertEqual(raw[0]&0xc0,0xc0)
            self.assertEqual(decode_carto_position(raw,prev_lat=0,prev_lon=0),
                             point)
        with self.assertRaisesRegex(RecordError,"out of bounds"):
            encode_carto_position(CartographicPosition(-1024,0),
                                  prev_lat=0,prev_lon=0)

    def test_true_osm_vertex_geometry_roundtrip(self):
        vertices=(CartographicPosition(512,1024),
                  CartographicPosition(520,1032,pen_toggle=True),
                  CartographicPosition(528,1048))
        raw=encode_carto_positions(start_lat=500,start_lon=1000,
                                   points=vertices,scale=2)
        self.assertEqual(len(raw),9)
        self.assertEqual(decode_carto_positions(raw,start_lat=500,
                         start_lon=1000,scale=2),vertices)
        with self.assertRaisesRegex(RecordError,"precision"):
            encode_carto_positions(start_lat=500,start_lon=1000,
                points=(CartographicPosition(501,1000),),scale=2)
        with self.assertRaisesRegex(RecordError,"Misaligned"):
            decode_carto_positions(raw[:-1],start_lat=500,start_lon=1000)

    def test_short_2point_refuses_unproven_multipoint_delta(self):
        record=ShortPolylineTwoPoint(12,500,500,488,480)
        raw=encode_short_polyline_two_point(record,min_lat=0,min_lon=0)
        self.assertEqual(decode_short_polyline_two_point(raw,min_lat=0,min_lon=0),
                         record)
        tampered=bytearray(raw);tampered[1]|=0x80
        with self.assertRaises(RecordError):
            decode_short_polyline_two_point(bytes(tampered),min_lat=0,min_lon=0)
        with self.assertRaises(RecordError):
            encode_short_polyline_two_point(
                ShortPolylineTwoPoint(12,500,500,700,480),min_lat=0,min_lon=0)

if __name__=="__main__":
    unittest.main()

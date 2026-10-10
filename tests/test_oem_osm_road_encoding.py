"""Normalized OSM road -> two true SDAL record types, preserving all vertices."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_records import RecordError
from sdal_builder.osm_road_encoding import (
    NormalizedOSMRoad,encode_osm_road_records
)
from sdal_builder.oem_line_geometry import (
    decode_full_polyline,decode_carto_positions
)
from sdal_builder.oem_route_segments import decode_route_segment_regular

class OSMRoadToSDALTests(unittest.TestCase):
    def road(self,**kw):
        init=dict(osm_way_id=1234,from_node_index=1,to_node_index=0,
                  vertices_ntu=((100,300),(108,292),(120,280)),
                  source_direction=1,cost_seconds=25,length_meters=122,
                  left_bearing=40,right_bearing=160,rank=1,route_type=2,
                  highlight_layer=1,attribute_index=6)
        init.update(kw)
        return NormalizedOSMRoad(**init)

    def encode(self,road=None,**kw):
        return encode_osm_road_records(
            road or self.road(),
            source_nodes=((120,280),(100,300)),
            parcel_min_lat=0,parcel_min_lon=0,
            parcel_max_lat=1024,parcel_max_lon=1024,
            cartographic_position_offset=400,node_count=2,scale=2,**kw)

    def test_osm_oneway_geometry_and_routing_direction_reversal(self):
        value=self.encode()
        self.assertTrue(value.reversed_from_osm)
        self.assertEqual((value.left_node_index,value.right_node_index),(0,1))
        line=decode_full_polyline(value.polyline,min_lat=0,min_lon=0,scale=2)
        self.assertEqual(line.direction,2)
        self.assertEqual(line.position_offset,400)
        self.assertEqual(line.position_count,2)
        pts=decode_carto_positions(value.cartographic_positions,
                 start_lat=line.start_lat,start_lon=line.start_lon,scale=2)
        self.assertEqual([(p.latitude_ntu,p.longitude_ntu) for p in pts],
                         [(108,292),(100,300)])
        segment=decode_route_segment_regular(value.routing_segment,node_count=2)
        self.assertEqual((segment.left_node_index,segment.right_node_index,
                          segment.direction,segment.length_meters,
                          segment.cost_seconds),(0,1,2,122,25))

    def test_bidirectional_and_ascending_osm_order(self):
        way=NormalizedOSMRoad(55,0,1,((120,280),(108,292),(100,300)),
            3,15,120,20,140,1,1,1,6)
        actual=self.encode(way)
        self.assertFalse(actual.reversed_from_osm)
        self.assertEqual(decode_full_polyline(actual.polyline,min_lat=0,
                         min_lon=0,scale=2).direction,3)

    def test_input_coordinate_precision_and_clipping_must_be_exact(self):
        with self.assertRaisesRegex(RecordError,"outside physical"):
            self.encode(replace(self.road(),
                vertices_ntu=((100,300),(108,1080),(120,280))))
        with self.assertRaisesRegex(RecordError,"endpoint"):
            self.encode(replace(self.road(),
                vertices_ntu=((100,300),(108,292),(120,284))))
        with self.assertRaisesRegex(RecordError,"precision"):
            self.encode(replace(self.road(),
                vertices_ntu=((100,300),(109,292),(120,280))))

    def test_all_cost_and_attribute_information_is_required(self):
        with self.assertRaises(RecordError):
            self.encode(replace(self.road(),cost_seconds=-1))
        with self.assertRaises(RecordError):
            self.encode(replace(self.road(),attribute_index=-1))
        with self.assertRaises(RecordError):
            self.encode(replace(self.road(),source_direction=0))

    def test_end_to_end_determinism(self):
        a=self.encode();b=self.encode()
        self.assertEqual(a,b)
        self.assertEqual(a.source_osm_way_id,1234)
        self.assertTrue(a.cartographic_positions)
        self.assertTrue(a.routing_segment)

if __name__=="__main__":
    unittest.main()

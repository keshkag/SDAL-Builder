"""Iter021 actual regular Routing Segment wire and two-way OSM graph references."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_records import RecordError,RoutingNodeBasic
from sdal_builder.oem_route_segments import (
    RoutingSegmentRegular,encode_route_segment_regular,
    decode_route_segment_regular,verify_routing_node_segment_links,
)
from sdal_builder.oem_record_blocks import encode_record_block,decode_record_block

def segment(**overrides):
    src=dict(left_node_index=0,right_node_index=1,direction=3,
        left_bearing=0,right_bearing=128,rank=0,divider_loc=0,
        divider_legal=False,detailed_city=False,highlight_layer=0,
        cost_seconds=10,length_meters=100,attribute_index=0)
    src.update(overrides)
    return RoutingSegmentRegular(**src)

class RouteSegmentTests(unittest.TestCase):
    def test_two_endpoints_and_actual_byte_record(self):
        value=segment()
        raw=encode_route_segment_regular(value,node_count=2)
        self.assertEqual(raw.hex(),"0c000080000000010a6400")
        self.assertEqual(decode_route_segment_regular(raw,node_count=2),value)

    def test_segment_records_are_real_type1_length_table_records(self):
        vals=(segment(),segment(right_node_index=2,rank=1,
                               cost_seconds=450,length_meters=900))
        block=encode_record_block(tuple(encode_route_segment_regular(v,node_count=3)
                                        for v in vals))
        self.assertEqual(decode_record_block(block.raw,2),block)
        self.assertEqual(tuple(decode_route_segment_regular(r,node_count=3)
                               for r in block.records),vals)

    def test_complete_node_backreferences(self):
        nodes=(RoutingNodeBasic(0,0,(0,),b""),
               RoutingNodeBasic(0,100,(0,1),b"\x00"),
               RoutingNodeBasic(0,200,(1,),b""))
        edges=(segment(),segment(left_node_index=1,right_node_index=2))
        verify_routing_node_segment_links(nodes,edges)
        with self.assertRaisesRegex(RecordError,"backreferences"):
            wrong=(nodes[0],RoutingNodeBasic(0,100,(0,),b""),nodes[2])
            verify_routing_node_segment_links(wrong,edges)

    def test_reject_unsupported_optional_segment_flags(self):
        raw=encode_route_segment_regular(segment(),node_count=2)
        for index,bit in ((0,0x80),(0,0x40),(0,0x20),(1,0x10),
                          (1,0x08),(1,0x04),(1,0x02),(1,0x01),(5,0x01)):
            broken=bytearray(raw);broken[index]|=bit
            with self.subTest(index=index,bit=bit),self.assertRaises(RecordError):
                decode_route_segment_regular(bytes(broken),node_count=2)

    def test_missing_nodes_and_direction_are_not_silently_accepted(self):
        with self.assertRaises(RecordError):
            encode_route_segment_regular(segment(right_node_index=5),node_count=2)
        with self.assertRaises(RecordError):
            encode_route_segment_regular(segment(left_node_index=0,
                                      right_node_index=0),node_count=2)
        with self.assertRaises(RecordError):
            encode_route_segment_regular(segment(direction=0),node_count=2)

    def test_attr_length_and_cost_are_not_guessed(self):
        with self.assertRaises(RecordError):
            encode_route_segment_regular(segment(cost_seconds=70000),node_count=2)
        with self.assertRaises(RecordError):
            encode_route_segment_regular(segment(length_meters=-1),node_count=2)
        record=encode_route_segment_regular(segment(),node_count=2)
        with self.assertRaises(RecordError):
            decode_route_segment_regular(record[:-1],node_count=2)

if __name__=="__main__":
    unittest.main()

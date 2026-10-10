"""SDAL point/routing record blocks: own produced bytes, not fake OEM payloads."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_typed_records import (
    CartographicPointBasic, RoutingNodeBasic,
    encode_carto_point_basic, decode_carto_point_basic,
    encode_route_node_basic, decode_route_node_basic, RecordError,
)
from sdal_builder.oem_record_blocks import (
    encode_record_block, decode_record_block,
)


class TypedRecordBlockTests(unittest.TestCase):
    def test_two_cartographic_points_in_real_length_table(self):
        points=(CartographicPointBasic(1,100,200),
                CartographicPointBasic(4,1000,2000))
        records=tuple(encode_carto_point_basic(p,min_lat_ntu=0,min_long_ntu=0)
                      for p in points)
        assembled=encode_record_block(records)
        self.assertEqual(assembled.first_record_offset,3)
        self.assertEqual(assembled.record_lengths,(8,8))
        self.assertEqual(assembled.raw[:3],bytes([3,8,8]))
        self.assertEqual(decode_record_block(assembled.raw,2),assembled)
        self.assertEqual(tuple(decode_carto_point_basic(r,
              min_lat_ntu=0,min_long_ntu=0)[0] for r in assembled.records),points)

    def test_route_nodes_in_length_table(self):
        nodes=(RoutingNodeBasic(100,200,(0,),b""),
               RoutingNodeBasic(200,300,(0,1),b"\x00"))
        records=tuple(encode_route_node_basic(node,min_lat_ntu=0,
                     min_long_ntu=0) for node in nodes)
        result=encode_record_block(records)
        self.assertEqual(decode_record_block(result.raw,2),result)
        self.assertEqual(tuple(decode_route_node_basic(r,
                         min_lat_ntu=0,min_long_ntu=0)[0]
                         for r in result.records),nodes)

    def test_type1_offset_transition_is_resolved_without_guessing(self):
        records=(b"a",)*240
        block=encode_record_block(records)
        self.assertEqual(block.first_record_offset,242)
        self.assertEqual(block.raw[:2],bytes.fromhex("f002"))
        self.assertEqual(decode_record_block(block.raw,240).records,records)

    def test_length_table_mismatches_are_rejected(self):
        source=encode_record_block((b"A",b"B"))
        raw=bytearray(source.raw)
        raw[0]=99
        with self.assertRaisesRegex(RecordError,"first-record offset"):
            decode_record_block(bytes(raw),2)
        truncated=source.raw[:-1]
        with self.assertRaisesRegex(RecordError,"beyond"):
            decode_record_block(truncated,2)
        with self.assertRaises(RecordError):
            decode_record_block(source.raw+b"z",2)

    def test_reject_missing_or_oversized_records(self):
        with self.assertRaises(RecordError):
            encode_record_block(())
        with self.assertRaises(RecordError):
            encode_record_block((b"",))
        with self.assertRaisesRegex(RecordError,"16-bit"):
            encode_record_block((bytes(40000),bytes(40000)))

    def test_deterministic_large_record(self):
        raw=bytes(range(256))*20
        record=encode_record_block((raw,))
        self.assertEqual(record.record_lengths,(5120,))
        self.assertEqual(decode_record_block(record.raw,1),record)
        self.assertEqual(encode_record_block((raw,)).raw,record.raw)


if __name__=="__main__":
    unittest.main()

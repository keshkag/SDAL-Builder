"""Physical SDAL 1.7 type-0/type-1 parcel tests: actual bytes and pointers.

The fixed typed headers and payload arrays are produced by the real writer,
then re-read using independent physical offsets, never mocked handles.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_oem_typed_headers import sample
from sdal_builder.oem_typed_headers import (decode_typed_fixed_header,
    encode_typed_fixed_header)
from sdal_builder.oem_spatial_header import PCL
from sdal_builder.oem_typed_records import RoutingNodeBasic
from sdal_builder.oem_route_segments import RoutingSegmentRegular
from sdal_builder.oem_line_geometry import FullPolyline, CartographicPosition
from sdal_builder.oem_parcel_assembly import (
    SizeAuthority, ParcelAssemblyError, CartographicRoad,
    assemble_cartographic_roads, assemble_routing_regular,
    verify_bounded_parcel,
)

PID1=0x18000020
PID0=0x18000040

def authority(byte_size=4096):
    return SizeAuthority(256,{24:byte_size})

def route_template():
    template=sample(0,0)
    fields=list(PCL.unpack(template.spatial_prefix[:20]))
    fields[0]=PID0
    return replace(template,spatial_prefix=PCL.pack(*fields)+template.spatial_prefix[20:])

def cartographic():
    return (CartographicRoad(
        FullPolyline(0,0,5243000,300100,True,3,1,2,rank=1,
                     attribute_index=5),
        (CartographicPosition(5243004,300096),
         CartographicPosition(5243008,300088))),
        CartographicRoad(
        FullPolyline(0,0,5243500,300200,True,1,2,1,rank=2,
                     attribute_index=6),
        (CartographicPosition(5243496,300196),)))

def routing():
    nodes=(RoutingNodeBasic(5243000,300100,(0,),b""),
           RoutingNodeBasic(5243010,300120,(0,1),b"\x00"),
           RoutingNodeBasic(5243020,300140,(1,),b""))
    def segment(a,b,cost):
        return RoutingSegmentRegular(a,b,3,20,200,1,0,False,False,1,
                                     cost,100,5)
    return nodes,(segment(0,1,12),segment(1,2,15))


class PhysicalParcelAssemblyTests(unittest.TestCase):
    def test_carto_actual_physical_offsets_positions_and_block_table(self):
        result=assemble_cartographic_roads(sample(1,0),cartographic(),
                     authority=authority(),file_offset=0x2000,block_shift=1)
        self.assertEqual(len(result.blob),4096)
        self.assertEqual(result.parcel_id,PID1)
        self.assertEqual(result.parcel_type,1)
        self.assertEqual(result.verification,"typed-record-arrays-only")
        self.assertLess(result.used_bytes,len(result.blob))
        header=decode_typed_fixed_header(result.blob)
        d=dict(header.descriptors)
        self.assertEqual(d["lineDesc"][1:4],(2,1,1))
        self.assertEqual(d["positionDesc"][0:2],(3,3))
        first_block=struct.unpack_from(">H",result.blob,d["lineDesc"][0])[0]
        self.assertEqual(first_block,d["lineDesc"][5])
        self.assertEqual(result.blob[d["positionDesc"][2]:d["positionDesc"][2]+9].__len__(),9)
        self.assertEqual(
            verify_bounded_parcel(result.blob,authority=authority(),
                                  file_offset=0x2000)["record_counts"],
            {"lineDesc":2})

    def test_route_real_node_segment_blocks_min_ids_and_reciprocal_graph(self):
        nodes,segments=routing()
        result=assemble_routing_regular(route_template(),nodes,segments,
                      minimum_node_id=1234,minimum_segment_id=8000,
                      authority=authority(),file_offset=0x4000,block_shift=1)
        header=decode_typed_fixed_header(result.blob)
        n=dict(header.descriptors)["nodeDesc"]
        s=dict(header.descriptors)["segmentDesc"]
        self.assertEqual((n[1],n[2],n[3],n[4]),(3,1234,2,1))
        self.assertEqual((s[1],s[2],s[3],s[4]),(2,8000,1,1))
        self.assertLess(n[0],n[6])
        self.assertLess(n[6],s[0])
        self.assertEqual(
            verify_bounded_parcel(result.blob,authority=authority(),
                                  file_offset=0x4000)["record_counts"],
            {"nodeDesc":3,"segmentDesc":2})

    def test_truncated_record_and_bad_block_pointer_fail_independent_reader(self):
        item=assemble_cartographic_roads(sample(1,0),cartographic(),
               authority=authority(),file_offset=0x2000)
        buf=bytearray(item.blob)
        header=decode_typed_fixed_header(buf)
        entry=dict(header.descriptors)["lineDesc"]
        struct.pack_into(">H",buf,entry[0],entry[5]+500)
        with self.assertRaises(ParcelAssemblyError):
            verify_bounded_parcel(bytes(buf),authority=authority(),
                                  file_offset=0x2000)
        buf=bytearray(item.blob)
        buf[entry[5]] = 255  # Invalid length table start
        with self.assertRaises((ParcelAssemblyError,ValueError)):
            verify_bounded_parcel(bytes(buf),authority=authority(),
                                  file_offset=0x2000)

    def test_wrong_parcel_size_index_or_physical_offset_not_accepted(self):
        with self.assertRaisesRegex(ParcelAssemblyError,"ucaParcelSizes"):
            assemble_cartographic_roads(sample(1,0),cartographic(),
                 authority=SizeAuthority(256,{23:4096}),file_offset=0x2000)
        with self.assertRaisesRegex(ParcelAssemblyError,"physical offset"):
            assemble_cartographic_roads(sample(1,0),cartographic(),
                 authority=authority(),file_offset=0x2100)
        with self.assertRaisesRegex(ParcelAssemblyError,"exceeds"):
            assemble_cartographic_roads(sample(1,0),cartographic()*5,
                 authority=authority(256),file_offset=0x2000)

    def test_unsupported_cartography_cannot_drop_text_or_local_attributes(self):
        originals=cartographic()
        text=replace(originals[0],
                     polyline=replace(originals[0].polyline,
                                      text_offsets=(10,)))
        with self.assertRaisesRegex(ParcelAssemblyError,"text"):
            assemble_cartographic_roads(sample(1,0),(text,),
                authority=authority(),file_offset=0x2000)
        local=replace(originals[0],
                     polyline=replace(originals[0].polyline,
                                      attribute_index=256))
        with self.assertRaisesRegex(ParcelAssemblyError,"attributes"):
            assemble_cartographic_roads(sample(1,0),(local,),
                authority=authority(),file_offset=0x2000)
        mismatch=replace(originals[0],
                     polyline=replace(originals[0].polyline,
                                      position_count=50))
        with self.assertRaisesRegex(ParcelAssemblyError,"Position count"):
            assemble_cartographic_roads(sample(1,0),(mismatch,),
                authority=authority(),file_offset=0x2000)

    def test_missing_routing_backreferences_and_minima_fail_closed(self):
        nodes,segments=routing()
        with self.assertRaisesRegex(ValueError,"backreferences"):
            assemble_routing_regular(route_template(),
                (nodes[0],RoutingNodeBasic(5243010,300120,(1,),b""),
                 nodes[2]),segments,minimum_node_id=1,
                minimum_segment_id=2,authority=authority(),file_offset=0x4000)
        with self.assertRaisesRegex(ParcelAssemblyError,"minimum ID"):
            assemble_routing_regular(route_template(),nodes,segments,
                minimum_node_id=0,minimum_segment_id=2,
                authority=authority(),file_offset=0x4000)

    def test_reproducibility_and_input_header_untouched(self):
        t=sample(1,0)
        before=t
        a=assemble_cartographic_roads(t,cartographic(),
                     authority=authority(),file_offset=0x2000)
        b=assemble_cartographic_roads(t,cartographic(),
                     authority=authority(),file_offset=0x2000)
        self.assertEqual(a,b)
        self.assertEqual(t,before)

    def test_fixed_header_or_position_array_overlap_rejected(self):
        item=assemble_cartographic_roads(sample(1,0),cartographic(),
            authority=authority(),file_offset=0x2000)
        header=decode_typed_fixed_header(item.blob)
        for changed_name,changed_offset in (
            ("lineDesc",header.size-2),
            ("positionDesc",dict(header.descriptors)["lineDesc"][5])):
            descriptions=dict(header.descriptors)
            fields=list(descriptions[changed_name])
            fields[0 if changed_name=="lineDesc" else 2]=changed_offset
            descriptions[changed_name]=tuple(fields)
            updated=replace(header,descriptors=tuple(
                (name,descriptions[name]) for name,_ in header.descriptors))
            raw=bytearray(item.blob)
            raw[:header.size]=encode_typed_fixed_header(updated)
            with self.subTest(changed_name=changed_name):
                with self.assertRaises(ParcelAssemblyError):
                    verify_bounded_parcel(bytes(raw),authority=authority(),
                                          file_offset=0x2000)

    def test_carto_and_routing_maxima_cannot_understate_real_counts(self):
        for kind,raw,start in (
            (1,assemble_cartographic_roads(sample(1,0),cartographic(),
                 authority=authority(),file_offset=0x2000).blob,0x2000),
            (0,assemble_routing_regular(route_template(),*routing(),
                 minimum_node_id=1234,minimum_segment_id=8000,
                 authority=authority(),file_offset=0x4000).blob,0x4000)):
            header=decode_typed_fixed_header(raw)
            lowered=list(header.maxima)
            lowered[1]=0
            bad=bytearray(raw)
            bad[:header.size]=encode_typed_fixed_header(
                replace(header,maxima=tuple(lowered)))
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ParcelAssemblyError,"maximum|Maxima|segments/node"):
                    verify_bounded_parcel(bytes(bad),authority=authority(),
                                          file_offset=start)

    def test_wrong_owner_type_is_rejected(self):
        with self.assertRaises(ParcelAssemblyError):
            assemble_cartographic_roads(sample(0,0),cartographic(),
                        authority=authority(),file_offset=0x4000)

if __name__=="__main__":
    unittest.main()

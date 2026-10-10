"""SDAL 1.7 actual GlbMediaHeader sector-count authority and physical layout."""
from __future__ import annotations
from dataclasses import replace
import io
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sdal_builder.oem_media_allocator import (
    MediaSizeTable,MediaSizeFields,parse_media_size_fields,
    write_media_size_fields,ParcelRequest,MediaLayoutError,allocate_region,
    SIZES_AT,COUNT_AT,NEXT_AT,SHIFT_AT,
)
from sdal_builder.oem_index import decode_index_parcel
from sdal_builder.oem_spatial_header import DBRect,make_spatial_header
from sdal_builder.oem_typed_records import RoutingNodeBasic
from sdal_builder.oem_line_geometry import FullPolyline,CartographicPosition
from sdal_builder.oem_route_segments import RoutingSegmentRegular
from sdal_builder.oem_parcel_assembly import (
    CartographicRoad,assemble_cartographic_roads,
    assemble_routing_regular,verify_bounded_parcel,
)
from sdal_builder.oem_kd_codec import SpatialRef
from sdal_builder.osm_spatial_plan import (
    Rect,Footprint,plan_spatial_partition,leaf_inventory,compile_planned_index,
)
from test_oem_typed_headers import sample

REGION=Rect(0,5242880,524288,5767168)

def size_table():
    # Deliberately test-supplied metadata, NOT claimed to be the OEM
    # WE_06Q4 GlbMediaHeader_t. Direct index8 has 80 sectors for KD.
    sizes=[16]*25
    sizes[8]=80
    return MediaSizeTable(8,tuple(sizes))

def test_region():
    table=size_table()
    layout=allocate_region(table,(
        ParcelRequest("left-carto",1,500,size_index=24),
        ParcelRequest("right-routing",0,500,size_index=24),
        ParcelRequest("global-kd",255,0x5000,size_index=8,
                      fixed_offset=0xC200,redundant=True),
    ),prefix_bytes=0x2000)
    features=(Footprint(1,1,0,100000,5300000,100300,5300300),
              Footprint(2,0,0,400000,5300000,400300,5300300))
    plan=plan_spatial_partition(REGION,features,max_features_per_leaf=1)
    cells=leaf_inventory(plan)
    def header(kind,key,cell):
        p=layout.get(key)
        r=DBRect(cell.west,cell.south,cell.east,cell.north)
        ancestor=DBRect(REGION.west,REGION.south,REGION.east,REGION.north)
        return replace(sample(kind,0),spatial_prefix=make_spatial_header(
            parcel_id=p.pid,parcel_type=kind,bounds=r,tile=r,
            ancestor=ancestor,scale=0,layer=0))
    c=layout.get("left-carto")
    carto=assemble_cartographic_roads(header(1,"left-carto",cells["L"].rect),
        (CartographicRoad(
            FullPolyline(0,0,5300000,100000,True,3,1,1,
                         rank=1,attribute_index=5),
            (CartographicPosition(5300200,100300),)),),
        authority=table.size_authority(),file_offset=c.start)
    r=layout.get("right-routing")
    nodes=(RoutingNodeBasic(5300000,400000,(0,),b""),
           RoutingNodeBasic(5300200,400300,(0,),b""))
    segments=(RoutingSegmentRegular(0,1,3,10,220,1,0,False,False,
                                    1,25,300,5),)
    route=assemble_routing_regular(header(0,"right-routing",cells["R"].rect),
         nodes,segments,minimum_node_id=1234,minimum_segment_id=4321,
         authority=table.size_authority(),file_offset=r.start)
    provisional=bytearray(layout.file_bytes)
    provisional[c.start:c.end]=carto.blob
    provisional[r.start:r.end]=route.blob
    refs={"L":(SpatialRef(1,0,c.pid),),"R":(SpatialRef(0,0,r.pid),)}
    idx=layout.get("global-kd")
    index=compile_planned_index(plan,parcel_refs=refs,
        entity_id_bounds={"":(1234,4321)},target_file=io.BytesIO(provisional),
        file_offset=idx.start)
    final=layout.render({"left-carto":carto.blob,
       "right-routing":route.blob,"global-kd":index},
       prefix=bytes(layout.prefix_bytes))
    return table,layout,final,plan,carto,route,index,refs


class MediaSizeFieldTests(unittest.TestCase):
    def test_exact_field_offsets_and_only_expected_bytes_change(self):
        raw=bytes([0xa5])*2048
        fields=MediaSizeFields(size_table(),8,24,6)
        result=write_media_size_fields(raw,fields)
        self.assertEqual(parse_media_size_fields(result),fields)
        self.assertEqual(result[SIZES_AT+8],80)
        self.assertEqual(result[SIZES_AT+24],16)
        self.assertEqual(result[COUNT_AT],25)
        self.assertEqual(result[NEXT_AT],8)
        self.assertEqual(result[SHIFT_AT:SHIFT_AT+6],
                         bytes.fromhex("000800180006"))
        self.assertEqual(result[:SIZES_AT],raw[:SIZES_AT])
        self.assertEqual(result[SHIFT_AT+6:],raw[SHIFT_AT+6:])
        self.assertEqual(result,write_media_size_fields(result,fields))

    def test_128_physical_entries_but_only_64_direct_addressable(self):
        table=MediaSizeTable(9,tuple([3]*127+[4]))
        self.assertEqual(table.bytes_for(63),1536)
        with self.assertRaisesRegex(MediaLayoutError,"index"):
            table.bytes_for(64)
        with self.assertRaises(MediaLayoutError):
            MediaSizeTable(8,(1,0,2))
        with self.assertRaises(MediaLayoutError):
            parse_media_size_fields(bytes(2048))
        with self.assertRaises(MediaLayoutError):
            write_media_size_fields(bytes(2047),MediaSizeFields(size_table(),1,24,6))

    def test_deterministic_smallest_fitting_index_and_sector_exponent(self):
        t=MediaSizeTable(9,(3,8,4))
        self.assertEqual(t.sector_bytes,512)
        self.assertEqual(t.bytes_for(2),2048)
        self.assertEqual(t.best_index(1500),0)
        self.assertEqual(t.best_index(1600),2)
        self.assertEqual(t.best_index(2500),1)
        with self.assertRaisesRegex(MediaLayoutError,"fits"):
            t.best_index(5000)


class RegionAllocatorTests(unittest.TestCase):
    def test_real_type0_type1_payloads_and_index_get_canonical_pids(self):
        table,layout,raw,plan,carto,route,index,refs=test_region()
        c=layout.get("left-carto")
        r=layout.get("right-routing")
        idx=layout.get("global-kd")
        self.assertEqual((c.start,r.start,idx.start),(0x2000,0x3000,0xC200))
        self.assertEqual((c.pid,r.pid,idx.pid),
                         (0x18000020,0x18000030,0x480000C2))
        self.assertEqual(idx.length,80*256)
        self.assertEqual(c.length,16*256)
        self.assertEqual(len(raw),idx.end)
        self.assertEqual(raw[c.start:c.end],carto.blob)
        self.assertEqual(raw[r.start:r.end],route.blob)
        self.assertEqual(raw[idx.start:idx.end],index)
        decode_index_parcel(index,absolute_offset=idx.start)
        layout.verify(raw)
        for item in (c,r):
            verify_bounded_parcel(raw[item.start:item.end],
                 authority=table.size_authority(),file_offset=item.start)

    def test_reverse_request_order_yields_byte_identical_region(self):
        a=test_region()
        self.assertEqual(a,test_region())
        r=list(reversed((
            ParcelRequest("left-carto",1,500,size_index=24),
            ParcelRequest("right-routing",0,500,size_index=24),
            ParcelRequest("global-kd",255,0x5000,size_index=8,
                          fixed_offset=0xC200,redundant=True))))
        alternate=allocate_region(size_table(),r,prefix_bytes=0x2000)
        self.assertEqual(alternate,a[1])

    def test_physical_overlaps_size_table_mismatches_and_missing_payload(self):
        table=size_table()
        requests=(ParcelRequest("a",1,500,size_index=24,fixed_offset=0x2000),
                  ParcelRequest("b",0,500,size_index=24,fixed_offset=0x2800))
        with self.assertRaisesRegex(MediaLayoutError,"overlaps"):
            allocate_region(table,requests,prefix_bytes=0x2000)
        with self.assertRaisesRegex(MediaLayoutError,"does not fit"):
            allocate_region(table,(ParcelRequest("a",1,5000,size_index=24),),
                            prefix_bytes=0x2000)
        with self.assertRaisesRegex(MediaLayoutError,"region prefix"):
            allocate_region(table,(ParcelRequest("a",1,500),),
                            prefix_bytes=0x2001)
        t,layout,raw,_,carto,route,index,_=test_region()
        with self.assertRaisesRegex(MediaLayoutError,"published"):
            layout.render({"left-carto":carto.blob},
                          prefix=bytes(layout.prefix_bytes))
        bad=bytearray(raw)
        bad[layout.get("right-routing").start]^=1
        with self.assertRaisesRegex(MediaLayoutError,"PID"):
            layout.verify(bytes(bad))

    def test_interior_cartographic_pointers_and_unknown_types_fail_publication(self):
        table,layout,raw,_,_,_,_,_=test_region()
        carto=layout.get("left-carto")
        from sdal_builder.oem_typed_headers import decode_typed_fixed_header
        header=decode_typed_fixed_header(raw[carto.start:carto.end])
        table_at=dict(header.descriptors)["lineDesc"][0]
        damaged=bytearray(raw)
        damaged[carto.start+table_at] ^= 1
        with self.assertRaisesRegex(MediaLayoutError,"physical graph"):
            layout.verify(bytes(damaged))
        with self.assertRaisesRegex(MediaLayoutError,"No verified physical"):
            ParcelRequest("unsupported-crossroads",6,500,size_index=24)

    def test_index_fixed_reservation_prevents_dynamic_collision(self):
        t=MediaSizeTable(8,tuple([16]*8+[80]+[16]*16))
        with self.assertRaisesRegex(MediaLayoutError,"overlaps"):
            allocate_region(t,(ParcelRequest("kd",255,0x5000,size_index=8,
                fixed_offset=0x2000,redundant=True),),prefix_bytes=0x3000)
        with self.assertRaisesRegex(MediaLayoutError,"index"):
            allocate_region(t,(ParcelRequest("kd",255,0x5000,size_index=24,
                fixed_offset=0xC200,redundant=True),),prefix_bytes=0x2000)

if __name__=="__main__":
    unittest.main()

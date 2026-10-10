"""Global Media Header/Index real wire regressions (SDAL 1.7 §2.1.1)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from sdal_builder.oem_media_allocator import (
    MediaSizeTable,MediaSizeFields,write_media_size_fields,
)
from sdal_builder.oem_spatial_header import PCL
from sdal_builder.oem_global_media_index import (
    BuiltGlobalIndex,CompressionEntry,GlobalIndexError,
    MetadataLevel,MetadataModule,RefDataEntry,
    build_global_media_index,verify_global_media_index,
    verify_global_reference_targets,verify_region_root_order,
    ordered_root_index_types,validate_locale,
    REF_TRIPLES_AT,METADATA_LEVEL_AT,METADATA_MODULE_AT,COMPRESS_AT,LOCALE_AT
)

def media_base(*, index_sectors=8, extra_bitmap=b"\x00"*8):
    sizes=[16]*25
    sizes[8]=80
    table=MediaSizeTable(8,tuple(sizes))
    original=bytearray(2048)
    original[0:4]=bytes.fromhex("12345678")  # supplied normalized attrs
    original[1024:1032]=extra_bitmap
    original[1258:1265]=bytes([1,7,0,4,2,11,10]) # externally set PSF version
    return write_media_size_fields(bytes(original),
                    MediaSizeFields(table,index_sectors,24,6))

def locale_identity():
    return struct.pack(">H",514)+struct.pack(">"+str(256)+"H",*range(256))

def global_parcel(pid,*,kind=12,capacity=4096):
    return PCL.pack(pid,0,kind,0,0,0,0,0,0,0,0)+bytes(
        [((i//16)%251)+1 for i in range(capacity-20)])

def reference_data_image(index,parcels):
    full=bytearray(max([index.next_data_start]+[p+len(raw) for p,raw in parcels.items()]))
    full[:2048]=index.media_header
    full[2048:index.next_data_start]=index.index_parcel
    for address,content in parcels.items():
        full[address:address+len(content)]=content
    return bytes(full)

class GlobalIndexStructureTests(unittest.TestCase):
    def setUp(self):
        self.p1=(24<<24)|0x10 # 0x1000 at 256-byte sectors
        self.p2=(24<<24)|0x20 # 0x2000
        self.refs={
            "feature_type":(
                RefDataEntry(self.p1,20,24,3),
                RefDataEntry(self.p2,20,24,7)),
            "language_code":(RefDataEntry(self.p2,20,28,0),)
        }

    def test_refdataindex_is_exactly_12_bytes_and_reserved_zero(self):
        rec=RefDataEntry(self.p1,20,24,3)
        self.assertEqual(len(rec.encode()),12)
        self.assertEqual(RefDataEntry.decode(rec.encode()),rec)
        with self.assertRaisesRegex(GlobalIndexError,"reserved"):
            RefDataEntry.decode(rec.encode()[:-1]+b"\x01")

    def test_second_bootstrap_parcel_is_index_without_pclhdr(self):
        original=media_base()
        idx=build_global_media_index(original,
            references=self.refs,compression=(CompressionEntry(7,0,0),),
            locale=locale_identity())
        self.assertEqual(idx.index_start,2048)
        self.assertEqual(len(idx.index_parcel),8*256)
        self.assertEqual(idx.next_data_start,4096)
        self.assertEqual(idx.media_header[:4],original[:4])
        self.assertEqual(idx.media_header[1258:1265],original[1258:1265])
        off,count,last=struct.unpack_from(">HHH",idx.media_header,
                                          REF_TRIPLES_AT+6)
        self.assertEqual((count,last),(2,7))
        self.assertEqual(idx.index_parcel[off:off+12],
                         self.refs["feature_type"][0].encode())
        loc,loc_size=struct.unpack_from(">HH",idx.media_header,LOCALE_AT)
        self.assertEqual(idx.index_parcel[loc:loc+loc_size],locale_identity())
        comp_at,comp_count=struct.unpack_from(">HH",idx.media_header,COMPRESS_AT)
        self.assertEqual(comp_count,1)
        self.assertEqual(idx.index_parcel[comp_at:comp_at+8],
                         struct.pack(">IBBBB",0,7,0,0,0))
        verify_global_media_index(idx)

    def test_reference_data_target_parcel_ids_and_regions_are_real(self):
        idx=build_global_media_index(media_base(),references=self.refs,
                                      locale=locale_identity())
        image=reference_data_image(idx,{
            0x1000:global_parcel(self.p1),
            0x2000:global_parcel(self.p2)})
        verify_global_reference_targets(idx,image)
        damaged=bytearray(image)
        damaged[0x2000+7]=1 # physically wrong region (expect region zero)
        with self.assertRaisesRegex(GlobalIndexError,"PID/region"):
            verify_global_reference_targets(idx,bytes(damaged))
        damaged=bytearray(image)
        damaged[0x1000]^=1
        with self.assertRaisesRegex(GlobalIndexError,"PID/region"):
            verify_global_reference_targets(idx,bytes(damaged))

    def test_reference_interval_order_is_strict(self):
        bad=dict(self.refs)
        bad["feature_type"]=(
            RefDataEntry(self.p1,20,24,7),RefDataEntry(self.p2,20,24,3))
        with self.assertRaisesRegex(GlobalIndexError,"strictly"):
            build_global_media_index(media_base(),references=bad)
        bad["feature_type"]=(
            RefDataEntry(self.p1,20,24,3),RefDataEntry(self.p1,20,24,7))
        with self.assertRaisesRegex(GlobalIndexError,"repeated"):
            build_global_media_index(media_base(),references=bad)

    def test_byte_corruption_in_index_or_header_rejected(self):
        idx=build_global_media_index(media_base(),references=self.refs)
        off,_,_=struct.unpack_from(">HHH",idx.media_header,REF_TRIPLES_AT+6)
        wrong=bytearray(idx.index_parcel)
        wrong[off+3]^=1
        with self.assertRaisesRegex(GlobalIndexError,"contents"):
            verify_global_media_index(replace(idx,index_parcel=bytes(wrong)))
        wrong_header=bytearray(idx.media_header)
        struct.pack_into(">H",wrong_header,REF_TRIPLES_AT+6,2047)
        with self.assertRaisesRegex(GlobalIndexError,"extent"):
            verify_global_media_index(replace(idx,media_header=bytes(wrong_header)))

    def test_locale_length_and_ligature_offset_are_validated(self):
        good=locale_identity()
        validate_locale(good)
        with self.assertRaisesRegex(GlobalIndexError,"size"):
            validate_locale(good[:-1])
        bad=bytearray(good)
        bad[2]=0x80
        bad[3]=0x00
        with self.assertRaisesRegex(GlobalIndexError,"zero-character"):
            validate_locale(bytes(bad))

    def test_metadata_levels_and_modules_are_true_binary_records(self):
        base=bytearray(media_base())
        base[1044:1046]=b"\x01\x22"  # source-owned metadata-hash authority
        levels=(MetadataLevel(170,1),)
        modules=(MetadataModule(1,5,256,0,self.p1,self.p2),)
        idx=build_global_media_index(bytes(base),references=self.refs,
              metadata_levels=levels,metadata_modules=modules)
        off,n=struct.unpack_from(">HH",idx.media_header,METADATA_LEVEL_AT)
        self.assertEqual(n,1)
        self.assertEqual(idx.index_parcel[off:off+4],levels[0].encode())
        off,n=struct.unpack_from(">HH",idx.media_header,METADATA_MODULE_AT)
        self.assertEqual(n,1)
        self.assertEqual(idx.index_parcel[off:off+16],modules[0].encode())
        verify_global_reference_targets(idx,reference_data_image(idx,{
            0x1000:global_parcel(self.p1),
            0x2000:global_parcel(self.p2)}))
        with self.assertRaisesRegex(GlobalIndexError,"hash"):
            build_global_media_index(media_base(),references=self.refs,
                                    metadata_levels=levels,metadata_modules=modules)

    def test_unimplemented_huffman_icons_and_voice_not_silently_erased(self):
        for at in (1094,1096,1098,1100,1102,1104,1106,1112,1114):
            with self.subTest(at=at):
                raw=bytearray(media_base())
                raw[at+1]=1
                with self.assertRaisesRegex(GlobalIndexError,"dedicated"):
                    build_global_media_index(bytes(raw),references=self.refs)
        with self.assertRaisesRegex(GlobalIndexError,"tree"):
            build_global_media_index(media_base(),references=self.refs,
                                    compression=(CompressionEntry(0,0,0),))

    def test_fixed_capacity_enforced(self):
        with self.assertRaisesRegex(GlobalIndexError,"capacity"):
            build_global_media_index(media_base(index_sectors=1),
                references=self.refs,locale=locale_identity())

    def test_no_index_fabricated_when_no_real_sections(self):
        with self.assertRaisesRegex(GlobalIndexError,"empty"):
            build_global_media_index(media_base(),references={})

    def test_external_bitmap_reaches_real_physical_global_kd_region(self):
        from test_oem_media_allocator import test_region
        _,layout,region,_,_,_,_,_=test_region()
        kd=layout.get("global-kd")
        self.assertEqual(kd.pid,0x480000c2)
        header=media_base(extra_bitmap=b"\xc0"+bytes(7))
        positions=verify_region_root_order(media_header=header,
                       index_root_pids=(kd.pid,kd.pid),
                       global_kd_pid=kd.pid,
                       region_bytes=region,sector_bytes=256)
        self.assertEqual(positions,(0,1))
        broken=bytearray(region)
        broken[kd.start]^=1
        with self.assertRaisesRegex(GlobalIndexError,"PID/region"):
            verify_region_root_order(media_header=header,
                index_root_pids=(kd.pid,kd.pid),
                global_kd_pid=kd.pid,
                region_bytes=bytes(broken),sector_bytes=256)

    def test_root_bitmap_maps_spatial_indices_to_same_physical_kd(self):
        # External index IDs: bit0, bit1 and bit10; stored in index-ID
        # ascending order, spatial indices 0/1 share same Global KD.
        bitmap=b"\xc0\x20"+bytes(6)
        media=media_base(extra_bitmap=bitmap)
        kd=0x480000c2
        self.assertEqual(ordered_root_index_types(bitmap),(0,1,10))
        self.assertEqual(
            verify_region_root_order(media_header=media,
                index_root_pids=(kd,kd,0x18000100),global_kd_pid=kd),
            (0,1,10))
        with self.assertRaisesRegex(GlobalIndexError,"Spatial"):
            verify_region_root_order(media_header=media,
                index_root_pids=(kd,0x18000200,0x18000100),global_kd_pid=kd)
        with self.assertRaisesRegex(GlobalIndexError,"count"):
            verify_region_root_order(media_header=media,
                index_root_pids=(kd,kd),global_kd_pid=kd)

if __name__=="__main__":
    unittest.main()

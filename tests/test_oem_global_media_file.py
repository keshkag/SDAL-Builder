"""Global Media 0.SDL real bootstrapping + reference parcel physical integration."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from test_oem_global_media_index import media_base, locale_identity
from sdal_builder.oem_global_media_file import (
    ReferenceSource,assemble_global_media,BuiltGlobalMedia
)
from sdal_builder.oem_global_media_index import GlobalIndexError
from sdal_builder.oem_spatial_header import PCL

def build():
    return assemble_global_media(media_base(),(
        ReferenceSource("feature_type","z-feature-part-b",12,
            b"\x01\x00\x00\x00\x08"+bytes(range(1,64)),
            20,24,7),
        ReferenceSource("feature_type","a-feature-part-a",12,
            b"\x01\x00\x00\x00\x04"+bytes(range(1,48)),
            20,24,3),
        ReferenceSource("language_code","language-lookup",14,
            b"\x00\x02\x02\x00"+bytes([0x41,0x42,0x43,0x44]),
            20,22,1),
    ),locale=locale_identity())

class GlobalMediaFileTests(unittest.TestCase):
    def test_full_bootstrap_and_reference_parcel_physical_parity(self):
        result=build()
        self.assertEqual(result.image[:2048],result.index.media_header)
        self.assertEqual(result.image[2048:4096],result.index.index_parcel)
        self.assertEqual(len(result.placements),3)
        self.assertEqual(result.placements[0].source.owner,"a-feature-part-a")
        self.assertEqual([p.file_offset for p in result.placements],
                         [0x1000,0x2000,0x3000])
        self.assertEqual([p.parcel_id for p in result.placements],
                         [0x18000010,0x18000020,0x18000030])
        self.assertEqual(len(result.image),0x4000)
        self.assertEqual(result.image[1250],25)
        self.assertEqual(result.image[1251],8)
        result.verify()

    def test_reverse_input_order_is_bit_identical(self):
        base=build()
        sources=tuple(p.source for p in reversed(base.placements))
        self.assertEqual(base,assemble_global_media(media_base(),sources,
                                                   locale=locale_identity()))

    def test_tampered_actual_global_data_is_rejected(self):
        expected=build()
        source=expected.placements[1]
        corrupted=bytearray(expected.image)
        corrupted[source.file_offset+PCL.size+3]^=1
        with self.assertRaisesRegex(GlobalIndexError,"modified"):
            replace(expected,image=bytes(corrupted)).verify()
        corrupted=bytearray(expected.image)
        corrupted[source.file_offset+7]^=1
        with self.assertRaisesRegex(GlobalIndexError,"PID/region|differs"):
            replace(expected,image=bytes(corrupted)).verify()

    def test_missing_reference_data_is_not_silently_accepted(self):
        with self.assertRaisesRegex(GlobalIndexError,"Nonempty"):
            assemble_global_media(media_base(),())
        with self.assertRaisesRegex(GlobalIndexError,"source"):
            ReferenceSource("invalid","item",12,b"x",20,20,0)
        with self.assertRaisesRegex(GlobalIndexError,"outside"):
            ReferenceSource("feature_type","item",12,b"x",23,23,0)

    def test_index_capacity_and_unavailable_sector_entries_fail_closed(self):
        raw=media_base(index_sectors=1)
        with self.assertRaisesRegex(GlobalIndexError,"capacity"):
            assemble_global_media(raw,(
                ReferenceSource("feature_type","item",12,b"abcde",20,22,0),
            ),locale=locale_identity())

    def test_no_guessing_of_oversized_global_reference_table(self):
        with self.assertRaisesRegex(ValueError,"fits"):
            assemble_global_media(media_base(),(
                ReferenceSource("feature_type","huge",12,bytes(50000),
                                20,21,0),))

    def test_duplicate_owner_or_nonascending_index_is_rejected(self):
        a=ReferenceSource("feature_type","same",12,b"\x00\x00\x00",20,21,3)
        b=ReferenceSource("language_code","same",12,b"\x00\x00\x00",20,21,0)
        with self.assertRaisesRegex(GlobalIndexError,"Duplicate"):
            assemble_global_media(media_base(),(a,b))
        c=ReferenceSource("feature_type","another",12,b"\x00\x00\x00",20,21,3)
        with self.assertRaisesRegex(GlobalIndexError,"Nonascending"):
            assemble_global_media(media_base(),(a,c))

if __name__=="__main__":
    unittest.main()

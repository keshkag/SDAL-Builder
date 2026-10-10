"""Exact PSF 1.7 global normalized attribute and identity wire tests."""
from __future__ import annotations
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from test_oem_global_media_index import media_base
from sdal_builder.oem_global_media_header import (
    NormalizedAttribute,PSFIdentity,HeaderCoreFields,
    encode_normalized_attributes,decode_normalized_attributes,
    decode_header_core,write_header_core,
)
from sdal_builder.oem_global_media_index import (
    GlobalIndexError,build_global_media_index,verify_region_root_order
)

def core():
    attrs=list(NormalizedAttribute(7,0,1,1) for _ in range(256))
    attrs[0]=NormalizedAttribute(0,3,0b1010101010,0x1ffff)
    attrs[1]=NormalizedAttribute(5,2,0b1,0x40)
    return HeaderCoreFields(tuple(attrs),b"\xc0"+bytes(7),bytes(4),
        PSFIdentity(1,7,0,4,2,11,10,2026),tuple(range(32)),
        0x01020304)

class GlobalMediaHeaderCoreTests(unittest.TestCase):
    def test_exact_256_normalized_attribute_wire_array(self):
        sample=core()
        raw=encode_normalized_attributes(sample.normalized_attributes)
        self.assertEqual(len(raw),1024)
        self.assertEqual(struct.unpack_from(">I",raw,0)[0],
                         (0<<29)|(3<<27)|(0b1010101010<<17)|0x1ffff)
        self.assertEqual(struct.unpack_from(">I",raw,4)[0],
                         (5<<29)|(2<<27)|(1<<17)|0x40)
        bad=bytearray(media_base())
        bad[:1024]=raw
        self.assertEqual(decode_normalized_attributes(bytes(bad)),
                         sample.normalized_attributes)

    def test_full_core_writing_preserves_unrelated_catalog_fields(self):
        original=media_base()
        core_fields=core()
        generated=write_header_core(original,core_fields)
        self.assertEqual(decode_header_core(generated),core_fields)
        self.assertEqual(generated[1036:1258],original[1036:1258])
        self.assertEqual(generated[1343:],original[1343:])
        self.assertEqual(generated[1258:1267],
                         bytes.fromhex("01070004020b0a07ea"))
        self.assertEqual(generated[1335:1339],bytes.fromhex("01020304"))
        self.assertEqual(write_header_core(generated,core_fields),generated)

    def test_psf_version_and_normalized_fields_reject_nonwire_values(self):
        with self.assertRaisesRegex(GlobalIndexError,"date"):
            PSFIdentity(1,7,0,4,2,0,10,2026)
        with self.assertRaisesRegex(GlobalIndexError,"bitfield"):
            NormalizedAttribute(8,0,0,0)
        with self.assertRaisesRegex(GlobalIndexError,"256"):
            encode_normalized_attributes((NormalizedAttribute(7,0,0,0),))
        with self.assertRaisesRegex(GlobalIndexError,"node cost"):
            from dataclasses import replace
            write_header_core(media_base(),replace(core(),node_costs=tuple([0]*31+[65536])))

    def test_global_core_bitmap_used_to_validate_regional_spatial_roots(self):
        fixed=write_header_core(media_base(),core())
        kd=0x480000c2
        self.assertEqual(verify_region_root_order(
            media_header=fixed,index_root_pids=(kd,kd),global_kd_pid=kd),(0,1))
        self.assertEqual(build_global_media_index(
            fixed,references={"feature_type":(
                __import__("sdal_builder.oem_global_media_index",
                           fromlist=["RefDataEntry"]).RefDataEntry(
                               0x18000010,20,22,0),)}).media_header[:1024],
            fixed[:1024])

if __name__=="__main__":
    unittest.main()

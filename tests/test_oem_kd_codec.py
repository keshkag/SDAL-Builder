"""Regression suite for the *encoder*, not merely for an OEM reader."""
from __future__ import annotations

import io
import random
import struct
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.oem_kd_codec import (
    CodecError, SpatialRef, KDChild, KDNode, encode_descriptor_list,
    decode_descriptor_list, encode_kd_node, decode_kd_node,
    verify_direct_spatial_target,
)


def node(*, left=None, right=None, lp=(), rp=(), emode=0, ids=None,
         axis=False, cut=16):
    return KDNode(axis, cut, emode, ids, left, right, tuple(lp), tuple(rp))


class KDSpatialEncoderTests(unittest.TestCase):
    def roundtrip(self, sample):
        raw = encode_kd_node(sample)
        decoded, end = decode_kd_node(raw, 0, len(raw))
        self.assertEqual(end, len(raw))
        self.assertEqual(decoded, sample)
        self.assertEqual(encode_kd_node(decoded), raw)
        return raw

    def test_oem_leaf_control_word(self):
        self.assertEqual(self.roundtrip(node()), bytes.fromhex("1000"))

    def test_1038_zero_padded_absent_child(self):
        self.assertEqual(self.roundtrip(node(right=KDChild(3,3),emode=2)),
                         bytes.fromhex("103800000003"))
        with self.assertRaisesRegex(CodecError, "pruned"):
            decode_kd_node(bytes.fromhex("103800010003"), 0, 6)

    def test_oem_external_child_field_width(self):
        ref = KDChild(1, (3<<16)|712)
        parsed = self.roundtrip(node(left=ref, right=KDChild(2, 7)))
        self.assertEqual(len(parsed),10)
        self.assertEqual(parsed[2:6], bytes.fromhex("000302c8"))
        self.assertEqual(parsed[6:10], bytes.fromhex("00000007"))

    def test_spatial_descriptor_wire_format_and_last_flag(self):
        refs = (SpatialRef(0, 2, 0x11000100),
                SpatialRef(3, 0, 0x1f0d6318))
        packed = encode_descriptor_list(refs)
        self.assertEqual(packed, bytes.fromhex("0211000100981f0d6318"))
        self.assertEqual(decode_descriptor_list(packed,0,len(packed)), (refs,10))
        with self.assertRaisesRegex(CodecError, "Reserved"):
            decode_descriptor_list(bytes.fromhex("c200000020"),0,5)

    def test_encoder_contains_all_ref_lists_and_explicit_ids(self):
        lp=(SpatialRef(1,4,0x3101feee),SpatialRef(2,4,0x0509fef0))
        rp=(SpatialRef(0,0,0x0504e888),)
        source=node(left=KDChild(2,17),right=None,lp=lp,rp=rp,
                    emode=1,ids=(0x112233,0x445566),cut=7,axis=True)
        raw=self.roundtrip(source)
        self.assertEqual(raw[:2], bytes.fromhex("e784"))
        self.assertEqual(raw[2:8], bytes.fromhex("112233445566"))
        self.assertEqual(len(raw)%2,0)

    def test_implicit_entity_modes_are_not_written(self):
        for e in (0,2,3):
            self.assertEqual(len(self.roundtrip(node(emode=e))),2)
        with self.assertRaisesRegex(CodecError,"implicit entity mode"):
            encode_kd_node(node(emode=2,ids=(1,2)))
        with self.assertRaisesRegex(CodecError,"Explicit"):
            encode_kd_node(node(emode=1))

    def test_deterministic_many_variants(self):
        rng=random.Random(170018)
        for i in range(400):
            children=[]
            for _ in range(2):
                mode=rng.randint(0,3)
                children.append(None if mode==0 else
                                KDChild(mode,rng.randint(1,(0,0xffffffff,255,65535)[mode])))
            emode=rng.randint(0,3)
            ids=(rng.randint(0,0xffffff),rng.randint(0,0xffffff)) if emode==1 else None
            refs=tuple(SpatialRef(rng.randint(0,7),rng.randint(0,7),
                                  rng.randint(0,0x7fffffff)) for _ in range(i%4))
            self.roundtrip(node(left=children[0],right=children[1],
                                emode=emode,ids=ids,cut=rng.randint(0,31),
                                axis=bool(i%2),lp=refs,rp=refs[::-1]))

    def test_bad_child_slot_and_padding_rejected(self):
        sample=bytearray(self.roundtrip(node(left=KDChild(2,9),
                                             right=KDChild(1,0x00010002))))
        sample[2]=1
        with self.assertRaisesRegex(CodecError,"high-order"):
            decode_kd_node(bytes(sample),0,len(sample))
        raw=bytearray(self.roundtrip(node(lp=(SpatialRef(1,1,0x100001),))))
        self.assertEqual(raw[-1],0)
        raw[-1]=1
        with self.assertRaisesRegex(CodecError,"padding"):
            decode_kd_node(bytes(raw),0,len(raw))

    def test_out_of_range_inputs_rejected(self):
        with self.assertRaises(CodecError):
            encode_kd_node(node(cut=32))
        with self.assertRaises(CodecError):
            encode_kd_node(node(left=KDChild(2,0)))
        with self.assertRaises(CodecError):
            encode_descriptor_list((SpatialRef(8,1,100),))
        with self.assertRaises(CodecError):
            encode_descriptor_list(())
        with self.assertRaises(CodecError):
            encode_kd_node(node(emode=1,ids=(1,0x1000000)))

    def test_direct_target_header_checks_and_one_byte_corruption(self):
        pid=0x18000020
        ref=SpatialRef(3,0,pid)
        data=bytearray(0x5000)
        struct.pack_into(">IHBBBBHHHHH",data,0x2000,pid,0,3,1,0,0,0,0,0,0,0)
        source=io.BytesIO(data)
        self.assertEqual(verify_direct_spatial_target(source,ref),
                         (True,"exact_header_match"))
        source.seek(0x2000+6)
        source.write(b"\x01")
        self.assertEqual(verify_direct_spatial_target(source,ref),
                         (False,"target_type_mismatch"))
        self.assertEqual(verify_direct_spatial_target(source,SpatialRef(3,0,pid|0x80000000)),
                         (False,"external_indirection_not_available"))

    def test_guardrail_external_pid_not_repaired(self):
        pid=0x1f0d6318
        blob=io.BytesIO(b"\0"*(0x2000))
        self.assertEqual(verify_direct_spatial_target(blob,SpatialRef(3,0,pid)),
                         (False,"target_out_of_bounds"))


if __name__=="__main__":
    unittest.main()

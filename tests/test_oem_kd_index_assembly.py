"""Production writer: assemble and validate real SDAL type-255 index parcels."""
from __future__ import annotations
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.oem_kd_codec import (
    CodecError, KDChild, KDNode, encode_index_from_nodes, decode_kd_node,
)
from sdal_builder.oem_index import decode_index_parcel


def leaf():
    return KDNode(False, 16, 0, None, None, None)


class KDIndexAssemblyTests(unittest.TestCase):
    def test_encode_three_node_local_tree(self):
        # Two locally addressed child nodes start at relative byte offsets
        # 4 and 6; the parent is a 4-byte record at relative offset 0.
        parent = KDNode(False, 16, 0, None, KDChild(2,2), KDChild(2,3))
        payload = encode_index_from_nodes(file_offset=0xC200,
                                          roots=((parent, leaf(), leaf()),))
        self.assertEqual(len(payload),0x5000)
        self.assertEqual(payload[:4],bytes.fromhex("480000c2"))
        self.assertTrue(payload.endswith(b"\xff" * 512))
        parsed = decode_index_parcel(payload,absolute_offset=0xC200)
        self.assertEqual(parsed.reassemble(),payload)
        self.assertEqual(len(parsed.root_offsets),1)
        self.assertEqual(parsed.root_offsets[0],26)
        actual, end = decode_kd_node(payload,26,len(payload))
        self.assertEqual(actual,parent)
        self.assertEqual(end,30)

    def test_incomplete_or_multiply_parented_graph_fails(self):
        with self.assertRaisesRegex(CodecError, "parents"):
            encode_index_from_nodes(file_offset=0xC200,
                                    roots=((leaf(),leaf()),))
        parent=KDNode(False,16,0,None,KDChild(2,2),KDChild(2,2))
        with self.assertRaisesRegex(CodecError, "parents"):
            encode_index_from_nodes(file_offset=0xC200,
                                    roots=((parent,leaf()),))

    def test_out_of_bounds_child_fails(self):
        parent=KDNode(False,16,0,None,KDChild(2,9),None)
        with self.assertRaisesRegex(CodecError, "node start"):
            encode_index_from_nodes(file_offset=0xC200,
                                    roots=((parent,leaf()),))

    def test_multiple_roots_and_determinism(self):
        roots=((leaf(),),(leaf(),),(leaf(),))
        a=encode_index_from_nodes(file_offset=0xC200,roots=roots)
        b=encode_index_from_nodes(file_offset=0xC200,roots=roots)
        self.assertEqual(a,b)
        parsed=decode_index_parcel(a,absolute_offset=0xC200)
        self.assertEqual(parsed.root_offsets,(30,32,34))
        self.assertEqual(a[34:36],bytes.fromhex("1000"))

    def test_empty_root_rejected(self):
        with self.assertRaisesRegex(CodecError,"Empty"):
            encode_index_from_nodes(file_offset=0xC200,roots=((),))
        with self.assertRaisesRegex(CodecError,"at least one"):
            encode_index_from_nodes(file_offset=0xC200,roots=())

    def test_refuses_unverified_fixed_index_capacity(self):
        # A genuine index parcel is 0x5000 bytes; overflow cannot truncate.
        with self.assertRaisesRegex(CodecError,"packing failed"):
            encode_index_from_nodes(file_offset=0xC200,
                                    roots=((leaf(),)*12000,))


if __name__=="__main__":
    unittest.main()

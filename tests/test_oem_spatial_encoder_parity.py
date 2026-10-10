"""Integration: write SDAL KD tree + spatial parcel, then validate entire graph."""
from __future__ import annotations
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"tools"))
from sdal_builder.oem_kd_codec import KDNode, KDChild, SpatialRef, encode_index_from_nodes
from oem_kd_graph_integrity import HEADER, INDEX_BYTES, INDEX_START, GraphError
from oem_spatial_encoder_parity import audit


def generated_map(root: Path) -> Path:
    destination = root/"GENERATED1.SDL"
    ref = SpatialRef(3, 0, 0x18000020)
    parent = KDNode(False,16,0,None,KDChild(1,1),KDChild(1,2),
                    left_parcels=(ref,))
    leaf = KDNode(False,16,0,None,None,None)
    index = encode_index_from_nodes(file_offset=INDEX_START,
                                    roots=((parent,), (leaf,), (leaf,)))
    assert len(index) == INDEX_BYTES
    data = bytearray(INDEX_START+INDEX_BYTES)
    struct.pack_into(">IHBBBBHHHHH",data,0x2000,ref.parcel_id,0,3,1,0,0,0,0,0,0,0)
    data[INDEX_START:] = index
    destination.write_bytes(data)
    return destination


class SpatialEncoderEndToEndTests(unittest.TestCase):
    def test_generated_content_graph_and_descriptor_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            path=generated_map(Path(directory))
            outcome=audit(path,strict_targets=True)
            self.assertEqual(outcome["counts"]["fully_reencoded_roots"],3)
            self.assertEqual(outcome["counts"]["nodes_byte_identical"],3)
            self.assertEqual(outcome["counts"]["spatial_references"],1)
            self.assertEqual(outcome["target_header_checks"],{"exact_header_match":1})
            self.assertTrue(outcome["all_nodes_byte_identical_after_decode_encode"])

    def test_generated_target_corruption_fails_strict_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path=generated_map(Path(directory))
            data=bytearray(path.read_bytes())
            data[0x2000+6]=1
            path.write_bytes(data)
            outcome=audit(path)
            self.assertEqual(outcome["target_header_checks"],{"target_type_mismatch":1})
            with self.assertRaisesRegex(GraphError,"Direct spatial references invalid"):
                audit(path,strict_targets=True)

    def test_generated_reference_corruption_fails_strict_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path=generated_map(Path(directory))
            data=bytearray(path.read_bytes())
            # ParcelID in first and only spatial descriptor, after the
            # 2-byte control and two 4-byte child offset slots.
            data[INDEX_START+30+10+4] ^= 1
            path.write_bytes(data)
            with self.assertRaises(GraphError):
                audit(path,strict_targets=True)

    def test_no_source_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path=generated_map(Path(directory))
            before=path.read_bytes()
            self.assertEqual(audit(path),audit(path))
            self.assertEqual(before,path.read_bytes())


if __name__ == "__main__":
    unittest.main()

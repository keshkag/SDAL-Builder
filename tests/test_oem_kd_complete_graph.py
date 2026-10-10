"""Synthetic exact full-tree references and OEM padded terminal bounds."""
from __future__ import annotations

from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from oem_kd_graph_integrity import GraphError, HEADER, INDEX_BYTES, INDEX_START
import oem_kd_complete_graph as m


def fixture(root: Path) -> Path:
    p = root/"BENELUX1.SDL"
    buf = bytearray([0xff] * (INDEX_START + INDEX_BYTES))
    idx = bytearray([0xff] * INDEX_BYTES)
    HEADER.pack_into(idx,0,0x480000C2,0,255,1,0,0,0,0,0,0,0)
    struct.pack_into(">HH",idx,20,3,0)
    struct.pack_into(">3H",idx,24,30,40,42)
    # control 0x1050: both offsets are 4-byte external entries
    idx[30:40] = bytes.fromhex("10500000000100000002")
    idx[40:44] = bytes.fromhex("10001000")
    buf[INDEX_START:] = idx
    p.write_bytes(buf)
    return p


class CompleteGraphTest(unittest.TestCase):
    def test_complete_index_is_one_connected_tree(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            row = m.audit(path)
            self.assertEqual(row["root_count"],3)
            self.assertEqual(row["index_parcels"],1)
            self.assertEqual(row["validated_nonleaf_roots"],1)
            self.assertEqual(row["two_byte_leaves"],2)
            self.assertEqual(row["parsed_nodes_in_validated_graphs"],1)
            self.assertEqual(row["global_external_edges"],2)
            self.assertEqual(row["terminal_roots_inferred_from_ff_padding"],1)
            self.assertEqual(row["unreachable_index_roots"],0)
            self.assertEqual(row["multiple_parent_roots"],0)
            self.assertIn("all original KD roots",m.markdown(m.analyze({"OEM":path})))

    def test_bad_target_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            data=bytearray(path.read_bytes())
            data[INDEX_START+39]=3
            path.write_bytes(data)
            with self.assertRaises(GraphError):
                m.audit(path)

    def test_duplicate_parent_and_missing_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            data=bytearray(path.read_bytes())
            data[INDEX_START+39]=1
            path.write_bytes(data)
            with self.assertRaisesRegex(GraphError,"one external parent"):
                m.audit(path)

    def test_terminal_boundary_requires_trailing_ff(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            data=bytearray(path.read_bytes())
            data[-1]=0
            path.write_bytes(data)
            with self.assertRaises(GraphError):
                m.audit(path)

    def test_bad_leaf_record_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            data=bytearray(path.read_bytes())
            data[INDEX_START+41]=1
            path.write_bytes(data)
            with self.assertRaises(GraphError):
                m.audit(path)

    def test_source_unchanged_and_repeatable(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            before=path.read_bytes()
            a=m.analyze({"MAP":path})
            self.assertEqual(a,m.analyze({"MAP":path}))
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(a["total_roots"],3)
            self.assertEqual(a["total_edges"],2)

    def test_empty_input_fails_closed(self):
        with self.assertRaises(GraphError):
            m.analyze({})


if __name__ == "__main__":
    unittest.main()

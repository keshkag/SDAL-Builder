"""Synthetic, source-free regression cases for first-root global KD-tree graph."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oem_kd_graph_integrity", ROOT / "tools" / "oem_kd_graph_integrity.py")
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def index_bytes(physical: int, *, with_child_links: bool) -> bytes:
    raw = bytearray([0xFF]*mod.INDEX_BYTES)
    pid = 0x48000000 | (physical // 256)
    header = mod.HEADER.pack(pid, 0, 255, 1, 0, 0, 0, 0, 0, 0, 0)
    raw[:20] = header
    if with_child_links:
        struct.pack_into(">HH", raw, 20, 3, 0)
        struct.pack_into(">3H", raw, 24, 30, 42, 44)
        # Tree 0 has one internal branch and two child nodes.
        # Child A contains an external reference to index 1, tree 1.
        raw[30:42] = bytes.fromhex("10a002051010000100011000")
        raw[42:46] = bytes.fromhex("10001000")
    else:
        struct.pack_into(">HH", raw, 20, 2, 0)
        struct.pack_into(">2H", raw, 24, 28, 30)
        raw[28:32] = bytes.fromhex("10001000")
    return bytes(raw)


def fixture(tmp: Path) -> Path:
    original = tmp / "BENELUX1.SDL"
    data = bytearray(mod.INDEX_START + 2 * mod.INDEX_BYTES)
    data[mod.INDEX_START:mod.INDEX_START + mod.INDEX_BYTES] = index_bytes(
        mod.INDEX_START, with_child_links=True)
    data[mod.INDEX_START + mod.INDEX_BYTES:] = index_bytes(
        mod.INDEX_START + mod.INDEX_BYTES, with_child_links=False)
    original.write_bytes(data)
    return original


class KDGraphIntegrityTests(unittest.TestCase):
    def test_realistic_first_tree_is_fully_connected(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            row = mod.audit_map(path)
            self.assertEqual(row["index_count"], 2)
            self.assertEqual(row["roots_in_index_parcels"], [3, 2])
            r = row["initial_root_graph"]
            self.assertEqual((r["node_count"], r["local_child_links"],
                              r["external_child_links"]), (3, 2, 1))
            self.assertEqual(r["unreachable_node_count"], 0)
            self.assertEqual(r["non_tree_local_edges"], 0)
            self.assertEqual(r["cross_index_reference_counts"], {"1": 1})
            self.assertEqual(r["max_local_depth"], 1)
            self.assertIn("FIRST root", mod.markdown({"BENELUX1": row}))

    def test_bad_local_child_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = bytearray(path.read_bytes())
            data[mod.INDEX_START+33] = 6  # right child at end of root
            path.write_bytes(data)
            with self.assertRaisesRegex(mod.GraphError, "local child"):
                mod.audit_map(path)

    def test_bad_external_index_or_tree_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = bytearray(path.read_bytes())
            data[mod.INDEX_START+38] = 5  # external index 5 does not exist
            path.write_bytes(data)
            with self.assertRaisesRegex(mod.GraphError, "External KD"):
                mod.audit_map(path)

    def test_cycles_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = bytearray(path.read_bytes())
            data[mod.INDEX_START+32] = 0
            path.write_bytes(data)
            with self.assertRaisesRegex(mod.GraphError, "forward local"):
                mod.audit_map(path)

    def test_reserved_control_bits_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = bytearray(path.read_bytes())
            data[mod.INDEX_START+31] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(mod.GraphError, "Reserved"):
                mod.audit_map(path)

    def test_descriptor_list_is_byte_aligned(self):
        # A 2-byte control + five-byte last-descriptor + one pad byte.
        raw = bytes.fromhex("900080480000c200")
        node = mod.parse_node(raw,0,len(raw))
        self.assertEqual(node["end"],8)
        self.assertEqual(len(node["descriptors"]),1)
        self.assertTrue(node["descriptors"][0]["last"])
        self.assertEqual(node["descriptors"][0]["parcel_id"],"0x480000C2")

    def test_explicit_entity_ids_are_six_bytes(self):
        raw = bytes.fromhex("1004"+"11"*6)
        node = mod.parse_node(raw,0,len(raw))
        self.assertEqual(node["end"],8)
        self.assertEqual(node["entity_id_mode"],1)

    def test_corrupted_root_table_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            data=bytearray(path.read_bytes())
            struct.pack_into(">H",data,mod.INDEX_START+24,33)
            path.write_bytes(data)
            with self.assertRaisesRegex(mod.GraphError, "root-offset"):
                mod.audit_map(path)

    def test_read_only_reproducibility(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            before=path.read_bytes()
            a=mod.audit_map(path)
            b=mod.audit_map(path)
            self.assertEqual(a,b)
            self.assertEqual(path.read_bytes(),before)

    def test_truncated_map_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            path=fixture(root)
            path.write_bytes(path.read_bytes()[:mod.INDEX_START+64])
            with self.assertRaisesRegex(mod.GraphError,"Missing first"):
                mod.audit_map(path)
            link=root/"LINK1.SDL"
            link.symlink_to(path)
            with self.assertRaisesRegex(mod.GraphError,"regular file"):
                mod.audit_map(link)


if __name__ == "__main__":
    unittest.main()

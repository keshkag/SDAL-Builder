"""Source-free Iter016 regressions: clustering does not invent KD formats."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_oem_kd_graph_integrity import fixture
from oem_kd_graph_integrity import GraphError
import oem_kd_similarity_clusters as m


class KDClusterTests(unittest.TestCase):
    def test_control_bit_grouping_is_msb_first(self):
        self.assertEqual(m.control_signature(0xD004), "L0R0_I1_D11")
        self.assertEqual(m.control_signature(0xD0F4), "L3R3_I1_D11")
        self.assertEqual(m.control_signature(0x9034), "L0R3_I1_D10")
        self.assertEqual(m.control_signature(0x1000), "L0R0_I0_D00")

    def test_full_root_accounting_and_reference_frontier(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            out = m.compare({"BENELUX": path})
            row = out["maps"]["BENELUX"]
            self.assertEqual(row["root_total"], 5)
            self.assertEqual(row["verified_graph_roots"], 1)
            self.assertEqual(row["verified_graph_external_edges"], 1)
            self.assertEqual(row["singleton_roots_targeted_exactly_once"], 0)
            self.assertEqual(row["singleton_roots_without_verified_parent"], 2)
            self.assertEqual(row["singleton_roots_with_multiple_verified_parents"], 0)
            self.assertEqual(row["family_counts"]["A_exact_1000_leaf"], 2)
            self.assertEqual(row["family_counts"]["C_multinode_tree"], 1)
            self.assertEqual(row["family_counts"]["Z_terminal_unbounded"], 2)
            frontier = row["unresolved_frontier_from_verified_graphs"]
            self.assertEqual([(r["index"], r["tree"]) for r in frontier], [(1,1)])
            self.assertEqual(frontier[0]["incoming_edges"], 1)
            self.assertEqual(frontier[0]["family"], "Z_terminal_unbounded")
            self.assertIn("Verified external reference links", m.markdown(out))

    def test_zero_edge_is_unresolved_not_declared_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            buf = bytearray(path.read_bytes())
            buf[0xC200+32] = 0
            path.write_bytes(buf)
            row = m.inspect_map(path)
            self.assertEqual(row["verified_graph_roots"], 0)
            self.assertEqual(row["verified_graph_external_edges"], 0)
            self.assertEqual(row["family_counts"]["F_zero_or_reverse_local_edge"], 1)
            self.assertEqual(row["singleton_roots_without_verified_parent"], 2)

    def test_external_target_switches_to_authenticated_leaf(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            buf = bytearray(path.read_bytes())
            # In the verified root's 4-byte external link at 0xC200+36,
            # change parcel offset to 0 and root ID to 1 (a known leaf).
            buf[0xC200+36:0xC200+40] = b"\x00\x00\x00\x01"
            path.write_bytes(buf)
            row = m.inspect_map(path)
            self.assertEqual(row["singleton_roots_targeted_exactly_once"], 1)
            self.assertEqual(row["singleton_roots_without_verified_parent"], 1)
            self.assertEqual(row["verified_edges_by_target_family"]
                             ["A_exact_1000_leaf"], 1)
            self.assertEqual(row["unresolved_frontier_from_verified_graphs"], [])

    def test_optional_oem_cohort_contract_is_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            # Valid generic KD graph: leaves need not have inbound edges
            # in this tiny synthetic fixture. The *observed original* WE_06Q4
            # cohort-specific 1-parent contract therefore must not be assumed.
            self.assertEqual(m.compare({"SAMPLE": path})["combined"]["root_total"], 5)
            with self.assertRaisesRegex(GraphError, "singleton-link invariant"):
                m.compare({"SAMPLE": path},
                          require_unique_singleton_parent=True)

    def test_corrupt_index_parcel_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            buf = bytearray(path.read_bytes())
            buf[0xC200+24] ^= 1
            path.write_bytes(buf)
            with self.assertRaises(GraphError):
                m.inspect_map(path)

    def test_compare_is_deterministic_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = fixture(Path(directory))
            untouched = path.read_bytes()
            a = m.compare({"Z": path, "A": path})
            b = m.compare({"A": path, "Z": path})
            self.assertEqual(a, b)
            self.assertEqual(a["combined"]["root_total"], 10)
            self.assertEqual(path.read_bytes(), untouched)

    def test_empty_inputs_rejected(self):
        with self.assertRaises(GraphError):
            m.compare({})


if __name__ == "__main__":
    unittest.main()

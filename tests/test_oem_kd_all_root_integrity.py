"""Donor-free tests for full 5,008-root accounting without false decodes."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_oem_kd_graph_integrity import fixture
from oem_kd_graph_integrity import GraphError
import oem_kd_all_root_integrity as m


class FullRootIntegrityTests(unittest.TestCase):
    def test_all_five_synthetic_roots_accounted_for(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = m.audit(path)
            self.assertEqual(data["root_total"], 5)
            self.assertEqual(data["index_parcels"], 2)
            self.assertEqual(data["status_counts"], {
                "exact_graph_under_sdal_control_profile": 1,
                "exact_two_byte_leaf": 2,
                "terminal_boundary_undetermined": 2,
            })
            self.assertEqual(data["strictly_covered_roots"], 3)
            self.assertEqual(data["verified_graph_nodes"], 3)
            self.assertEqual(data["verified_graph_external_edges"], 1)

    def test_last_root_never_implicitly_trimmed_and_certified(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            data = m.audit(path)
            terminals = [e for e in data["entries"]
                         if e["status"] == "terminal_boundary_undetermined"]
            self.assertEqual(len(terminals), 2)
            self.assertTrue(all(e["trailing_ff_bytes"] > 0 for e in terminals))
            self.assertTrue(all("source_sha256" in e for e in terminals))

    def test_invalid_local_graph_is_unresolved_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            raw = bytearray(path.read_bytes())
            # The original node has a one-byte local child delta; zero targets self.
            raw[0xC200+32] = 0
            path.write_bytes(raw)
            record = m.audit(path)["entries"][0]
            self.assertEqual(record["status"], "unresolved_node_encoding")
            self.assertEqual(record["reason"], "nonforward_local_reference")

    def test_silent_graph_gap_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            raw = bytearray(path.read_bytes())
            # The first node's offsets may remain in bounds but a node must
            # still cover the exact byte range without gaps or overlaps.
            raw[0xC200+32] = 4
            path.write_bytes(raw)
            record = m.audit(path)["entries"][0]
            self.assertEqual(record["status"], "unresolved_node_encoding")
            self.assertIn(record["reason"], (
                "root_node_gaps_or_overlaps", "root_bytes_not_fully_covered",
                "unrecognized_node_record", "local_edges_do_not_form_tree",
                "local_target_outside_root"))

    def test_bad_root_table_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            raw = bytearray(path.read_bytes())
            raw[0xC200+24] ^= 1
            path.write_bytes(raw)
            with self.assertRaises(GraphError):
                m.audit(path)

    def test_compare_preserves_inputs_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path = fixture(Path(td))
            before = path.read_bytes()
            a = m.compare({"MAP_A": path, "MAP_B": path})
            b = m.compare({"MAP_B": path, "MAP_A": path})
            self.assertEqual(a, b)
            self.assertEqual(a["combined_root_count"], 10)
            self.assertEqual(a["combined_status_counts"]
                             ["exact_graph_under_sdal_control_profile"], 2)
            self.assertEqual(path.read_bytes(), before)
            self.assertIn("strict KD-root coverage", m.markdown(a))

    def test_missing_source_and_empty_input(self):
        with self.assertRaises(GraphError):
            m.compare({})
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "missing.SDL"
            with self.assertRaises(GraphError):
                m.audit(path)


if __name__ == "__main__":
    unittest.main()

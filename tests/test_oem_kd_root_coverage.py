"""Iter014 fail-closed coverage tracking for actual OEM KD index root tables."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
from test_oem_kd_graph_integrity import fixture

spec = importlib.util.spec_from_file_location(
    "oem_kd_root_coverage", ROOT/"tools"/"oem_kd_root_coverage.py")
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CoverageTests(unittest.TestCase):
    def test_every_root_accounted_for_without_false_full_decode(self):
        with tempfile.TemporaryDirectory() as td:
            src = fixture(Path(td))
            result = m.analyze({"BENELUX1": src})
            c = result["maps"]["BENELUX1"]["coverage"]
            self.assertEqual(c["root_total"], 5)
            self.assertEqual(c["verified_singleton_0x1000"], 2)
            self.assertEqual(c["unclassified_multibyte_root"], 3)
            self.assertEqual(result["maps"]["BENELUX1"]["index_parcel_count"],2)
            self.assertEqual(result["combined"]["roots"],5)
            self.assertEqual(len(result["maps"]["BENELUX1"]["unclassified_multibyte_roots"]),3)

    def test_first_root_must_be_proven_graph(self):
        with tempfile.TemporaryDirectory() as td:
            src = fixture(Path(td))
            bad=bytearray(src.read_bytes())
            bad[0xC200 + 31] ^= 1
            src.write_bytes(bad)
            with self.assertRaises(ValueError):
                m.analyze({"BENELUX1":src})

    def test_mutation_is_not_silently_called_a_leaf(self):
        with tempfile.TemporaryDirectory() as td:
            src=fixture(Path(td))
            first = m.analyze({"A": src})["maps"]["A"]["coverage"]
            data=bytearray(src.read_bytes())
            data[0xC200+42+1]=1
            src.write_bytes(data)
            second=m.analyze({"A": src})["maps"]["A"]["coverage"]
            self.assertEqual(first["root_total"], second["root_total"])
            self.assertEqual(first["verified_singleton_0x1000"]-1,
                             second["verified_singleton_0x1000"])
            self.assertEqual(second["unclassified_multibyte_root"],
                             first["unclassified_multibyte_root"]+1)

    def test_outputs_are_deterministic_and_sources_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            path=fixture(Path(td))
            raw=path.read_bytes()
            a=m.analyze({"A":path})
            self.assertEqual(a,m.analyze({"A":path}))
            self.assertEqual(path.read_bytes(),raw)
            self.assertIn("Exact 0x1000 leaf",m.markdown(a))

    def test_no_input_is_rejected(self):
        with self.assertRaises(ValueError):
            m.analyze({})


if __name__ == "__main__":
    unittest.main()

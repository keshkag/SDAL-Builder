"""Source-free checks for the original SWIAUS1 Maneuver ParcelID exceptions."""
from __future__ import annotations
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"tools"))
from oem_maneuver_pid_spec_audit import (
    AnomalyError,ids_from_reference_report,inspect_direct_pid_map,
)


class ManeuverPIDSpecTests(unittest.TestCase):
    def fake_map(self,root: Path) -> Path:
        raw=bytearray(0x9000)
        # PID's direct sector position is at 0x5000.
        # Exact type-3 header appears only 0x5000 bytes EARLIER, at 0x0.
        pid=0x08000050
        struct.pack_into(">IHBBBBHHHHH",raw,0,pid,0,3,1,0,0,0,0,0,0,0)
        p=root/"SWIAUS1.SDL"
        p.write_bytes(raw)
        return p

    def test_non_redundant_direct_ids_must_not_be_relocated(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fake_map(Path(td))
            data=inspect_direct_pid_map(path,[0x08000050,0x08000080])
            self.assertEqual(data["counts"],{
                "ids":2,
                "nominal_mismatch":2,
                "found_exact_type3_header_elsewhere":1,
                "no_corresponding_type3_header":1,
                "matching_header_at_minus_0x5000":1,
            })
            a=data["results"][0]
            self.assertEqual(a["matching_header_deltas_from_target"],[-0x5000])
            self.assertFalse(a["nominal_target_exact"])
            self.assertFalse(a["redundancy_bit_30"])
            self.assertFalse(a["external_to_region_bit_31"])
            self.assertEqual(a["interpretation"],
                             "direct_reference_unresolved_no_implicit_relocation")

    def test_external_indirection_cannot_be_treated_as_direct(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fake_map(Path(td))
            with self.assertRaisesRegex(AnomalyError,"indirection"):
                inspect_direct_pid_map(path,[0x88000050])

    def test_corrupt_header_must_not_be_considered_a_match(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fake_map(Path(td))
            raw=bytearray(path.read_bytes())
            raw[6]=1  # wrong type
            path.write_bytes(raw)
            r=inspect_direct_pid_map(path,[0x08000050])
            self.assertEqual(r["counts"]["no_corresponding_type3_header"],1)

    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fake_map(Path(td))
            with self.assertRaisesRegex(AnomalyError,"unique"):
                inspect_direct_pid_map(path,[0x08000050,0x08000050])

    def test_reference_report_enforces_direct_address_formula(self):
        with tempfile.TemporaryDirectory() as td:
            r=Path(td)/"ref.json"
            r.write_text(json.dumps({"bad_target_examples":[
                ["0x08000050","0x5000",1,"missing","raw"]]}))
            self.assertEqual(ids_from_reference_report(r),[0x08000050])
            r.write_text(json.dumps({"bad_target_examples":[
                ["0x08000050","0x5100",1,"missing","raw"]]}))
            with self.assertRaisesRegex(AnomalyError,"sector law"):
                ids_from_reference_report(r)

    def test_source_unmodified_and_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            path=self.fake_map(Path(td))
            before=path.read_bytes()
            a=inspect_direct_pid_map(path,[0x08000050])
            self.assertEqual(a,inspect_direct_pid_map(path,[0x08000050]))
            self.assertEqual(path.read_bytes(),before)


if __name__=="__main__":
    unittest.main()

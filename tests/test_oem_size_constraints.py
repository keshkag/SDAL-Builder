"""Synthetic, donor-free regressions for Iter005 size-index hypotheses."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / "tools" / "oem_size_constraints.py"
SPEC = importlib.util.spec_from_file_location("oem_size_constraints", PATH)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def header(offset: int, index: int, typ: int, region: int, desc: int) -> bytes:
    return m.HEADER.pack((index << 24) | (offset // 256), desc,
                         typ, region, 0, 0, 0, 0, 0, 0, 0)


def donor() -> dict[str, bytes]:
    inputs = {}
    for name in ("BENELUX0.SDL", "FRANCE0.SDL"):
        data = bytearray(319488)
        for offset in range(0x2000, len(data), 0x4000):
            data[offset:offset + 20] = header(offset, 56, 19, 0, 0)
        inputs[name] = bytes(data)
    carto = bytearray(184320)
    for offset, idx, typ, desc in (
            (0x2000, 56, 255, 0), (0x6000, 56, 1, 0xB8),
            (0xA000, 46, 1, 0xB8), (0x12000, 0, 1, 0xB8),
            (0x17E00, 45, 1, 0xB8), (0x21B00, 52, 1, 0xB8),
            (0x25700, 42, 1, 0xB8), (0x28900, 59, 1, 0xB8)):
        carto[offset:offset + 20] = header(offset, idx, typ, 1, desc)
    inputs["CARTOTOP.SDL"] = bytes(carto)
    return inputs


class SizeConstraintsTests(unittest.TestCase):
    def test_expected_46_headers_and_seven_constraints(self):
        result = m.analyze(donor(), enforce_we06q4=True)
        self.assertEqual(result["candidate_counts"],
                         {"BENELUX0.SDL": 19, "FRANCE0.SDL": 19, "CARTOTOP.SDL": 8})
        self.assertEqual(sum(result["candidate_counts"].values()), 46)
        self.assertEqual({r["size_index"]: r["candidate_size_units"]
                          for r in result["index_constraints"]},
                         {0: 94, 42: 50, 45: 157, 46: 128,
                          52: 60, 56: 64, 59: 71})
        i56 = next(row for row in result["index_constraints"] if row["size_index"] == 56)
        self.assertEqual(i56["observations"], 40)
        self.assertIn("not verified", result["status"].replace("_", " "))

    def test_header_endianness_and_self_address(self):
        h = m.parse_candidate(header(0x17E00, 45, 1, 1, 0xB8), 0x17E00)
        self.assertEqual(h["size_index"], 45)
        self.assertEqual(h["offset"], 0x17E00)
        self.assertIsNone(m.parse_candidate(header(0x17E00, 45, 1, 1, 0xB8), 0x18000))

    def test_injected_false_boundary_fails(self):
        files = donor()
        carto = bytearray(files["CARTOTOP.SDL"])
        carto[0x7000:0x7014] = header(0x7000, 46, 1, 1, 0xB8)
        files["CARTOTOP.SDL"] = bytes(carto)
        with self.assertRaisesRegex(m.EvidenceError, "Conflicting"):
            m.derive_constraints(files)

    def test_missing_file_fails_closed(self):
        files = donor()
        del files["FRANCE0.SDL"]
        with self.assertRaisesRegex(m.EvidenceError, "Missing OEM"):
            m.derive_constraints(files)

    def test_boundary_offset_validation(self):
        self.assertIsNone(m.parse_candidate(bytes(19), 0))
        self.assertIsNone(m.parse_candidate(header(0x2000, 56, 19, 0, 0), 0x201))
        self.assertIsNone(m.parse_candidate(header(0x2000, 56, 19, 0, 0), 0x4000))

    def test_direct_pattern_search_without_claiming_authenticity(self):
        values = [{"size_index": 0, "candidate_size_units": 94},
                  {"size_index": 56, "candidate_size_units": 64}]
        blob = bytearray(64)
        blob[0] = 94
        blob[56] = 64
        self.assertEqual(m.locate_direct_uint8_patterns({"TABLE.SDL": bytes(blob)}, values),
                         [{"file": "TABLE.SDL", "offset": 0,
                           "minimal_pattern_width_bytes": 57}])
        blob[56] = 63
        self.assertEqual(m.locate_direct_uint8_patterns({"TABLE.SDL": bytes(blob)}, values), [])

    def test_report_is_deterministic_and_read_only(self):
        files = donor()
        before = dict(files)
        a = m.analyze(files)
        b = m.analyze(dict(reversed(list(files.items()))))
        self.assertEqual(a, b)
        self.assertEqual(files, before)
        self.assertIn("provisional", m.markdown(a).lower())

    def test_explicit_eof_assumption(self):
        r = m.derive_constraints(donor())
        self.assertEqual(sum(x["eof_boundary"] for x in r["individual_observations"]), 3)


if __name__ == "__main__":
    unittest.main()

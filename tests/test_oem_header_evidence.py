"""Synthetic verification of Iter004 OEM header evidence; no proprietary donor bytes."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

P = Path(__file__).resolve().parents[1] / "tools" / "oem_header_evidence.py"
S = importlib.util.spec_from_file_location("oem_header_evidence", P)
assert S is not None and S.loader is not None
mod = importlib.util.module_from_spec(S)
S.loader.exec_module(mod)


def header(pos: int, kind: int, region: int, size_index: int, descriptor: int = 0) -> bytes:
    return mod.HEADER.pack(
        (size_index << 24) | (pos // 256),
        descriptor, kind, region, 0, 0, 0, 0, 0, 0, 0)


def donor() -> dict[str, bytes]:
    a = bytearray(319488)
    b = bytearray(319488)
    for pos in range(0x2000, 0x4E000, 0x4000):
        a[pos:pos + 20] = header(pos, 19, 0, 56)
        b[pos:pos + 20] = header(pos, 19, 0, 56)
    # Make the content non-uniform without creating a new candidate header.
    a[0x2000 + 100] = 9
    b[0x2000 + 100] = 10
    c = bytearray(184320)
    for pos, kind, idx, desc in ((0x2000, 255, 56, 0),
                                 (0x6000, 1, 56, 0xB8),
                                 (0xA000, 1, 46, 0xB8),
                                 (0x12000, 1, 0, 0xB8),
                                 (0x17E00, 1, 45, 0xB8),
                                 (0x21B00, 1, 52, 0xB8),
                                 (0x25700, 1, 42, 0xB8),
                                 (0x28900, 1, 59, 0xB8)):
        c[pos:pos + 20] = header(pos, kind, 1, idx, desc)
    i = bytearray(172032)
    for dst, src in ((0x6000, 0x2000), (0xA000, 0x6000),
                     (0xE000, 0x16000)):
        i[dst:dst + 0x4000] = a[src:src + 0x4000]
    return {"INIT.SDL": bytes(i), "BENELUX0.SDL": bytes(a),
            "FRANCE0.SDL": bytes(b), "CARTOTOP.SDL": bytes(c)}


class EvidenceTests(unittest.TestCase):
    def test_layout_and_pid_index(self):
        self.assertEqual(mod.HEADER.size, 20)
        h = mod.read_header(header(0xA000, 1, 1, 46, 0xB8), 0)
        self.assertEqual(h["size_index"], 46)
        self.assertEqual(h["inferred_address_bytes"], 0xA000)
        self.assertFalse(h["self_addressed"])

    def test_exact_donor_profile(self):
        evidence = mod.analyze(donor())
        self.assertTrue(all(evidence["validation"].values()))
        self.assertEqual([len(v["candidates"]) for v in evidence["files"].values()],
                         [0, 19, 19, 8])
        self.assertEqual(evidence["files"]["CARTOTOP.SDL"]["candidates"][2]
                         ["size_index"], 46)
        self.assertEqual(evidence["files"]["CARTOTOP.SDL"]["candidates"][3]
                         ["size_index"], 0)

    def test_relocated_bytes_cannot_be_self_addressed(self):
        evidence = mod.analyze(donor())
        for alias in evidence["init_relocated_copies"]:
            self.assertTrue(alias["equal"])
            self.assertTrue(alias["embedded_address_targets_source"])
            self.assertTrue(alias["embedded_address_is_not_destination"])

    def test_rejects_corrupted_regional_header(self):
        files = donor()
        corrupted = bytearray(files["FRANCE0.SDL"])
        corrupted[0x6000 + 6] = 255
        files["FRANCE0.SDL"] = bytes(corrupted)
        with self.assertRaisesRegex(mod.EvidenceError, "regions"):
            mod.analyze(files)

    def test_rejects_corrupted_carto_index(self):
        files = donor()
        corrupted = bytearray(files["CARTOTOP.SDL"])
        corrupted[0xA000] = 0x3F
        files["CARTOTOP.SDL"] = bytes(corrupted)
        with self.assertRaisesRegex(mod.EvidenceError, "cartotop"):
            mod.analyze(files)

    def test_rejects_broken_relocation(self):
        files = donor()
        corrupted = bytearray(files["INIT.SDL"])
        corrupted[0x6000 + 100] ^= 1
        files["INIT.SDL"] = bytes(corrupted)
        with self.assertRaisesRegex(mod.EvidenceError, "init_relations"):
            mod.analyze(files)

    def test_does_not_treat_pattern_in_middle_as_header(self):
        b = bytearray(8192)
        b[0x101:0x115] = header(0x100, 19, 0, 56)
        self.assertEqual(mod.scan(bytes(b)), [])

    def test_malformed_input_and_determinism(self):
        with self.assertRaises(mod.EvidenceError):
            mod.read_header(b"123", 0)
        files = donor()
        a = mod.analyze(files)
        self.assertEqual(a, mod.analyze(dict(reversed(list(files.items())))))
        self.assertIn("CARTOTOP candidates", mod.format_markdown(a))
        del files["INIT.SDL"]
        with self.assertRaises(mod.EvidenceError):
            mod.analyze(files)


if __name__ == "__main__":
    unittest.main()

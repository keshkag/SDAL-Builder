"""Offline regression for observed OEM catalog record offsets."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "tools" / "oem_catalog_decoder.py"
spec = importlib.util.spec_from_file_location("oem_catalog_decoder", PATH)
assert spec is not None and spec.loader is not None
decoder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(decoder)


def donor_like():
    mtoc = bytearray(4096)
    mtoc[0x48:0x48 + 12] = b"BENELUX1.SDL"
    mtoc[0x58:0x5C] = bytes.fromhex("52000001")
    mtoc[0x8C:0x8C + 11] = b"FRANCE1.SDL"
    mtoc[0x9C:0xA0] = bytes.fromhex("52000002")
    init = bytearray(0x13000)
    init[0x12000:0x13000] = mtoc
    return {
        "INIT.SDL": bytes(init), "MTOC.SDL": bytes(mtoc),
        "REGION.SDL": b"SDAL", "REGIONS.SDL": b"SDAL",
        "CARTOTOP.SDL": bytes(4096),
        "BENELUX0.SDL": b"ABC", "FRANCE0.SDL": b"AXC"
    }


class DecoderTest(unittest.TestCase):
    def test_entries(self):
        raw = donor_like()["MTOC.SDL"]
        entries = decoder.decode_entries(raw)
        self.assertEqual([x["filename"] for x in entries],
                         ["BENELUX1.SDL", "FRANCE1.SDL"])
        self.assertEqual([x["filename_offset"] for x in entries], [0x48, 0x8C])
        self.assertEqual(entries[0]["word_be_hex"], "0x52000001")

    def test_copied_table_but_not_whole_mtoc(self):
        raw = donor_like()
        modified = bytearray(raw["INIT.SDL"])
        modified[0x12000 + 0x200] = 1
        raw["INIT.SDL"] = bytes(modified)
        report = decoder.analyze(raw)
        self.assertTrue(report["init_mtoc"]["entries_byte_identical"])
        self.assertEqual(report["init_mtoc"]["byte_comparison"]["first_difference"],
                         0x200)
        self.assertEqual(report["benelux_and_france"]["byte_comparison"]["different_bytes"], 1)

    def test_detects_changed_entry(self):
        raw = donor_like()
        corrupted = bytearray(raw["MTOC.SDL"])
        corrupted[0x58] = 0x43
        raw["MTOC.SDL"] = bytes(corrupted)
        self.assertFalse(decoder.analyze(raw)["init_mtoc"]["entries_byte_identical"])

    def test_missing_file_is_not_silent(self):
        raw = donor_like()
        del raw["INIT.SDL"]
        with self.assertRaises(ValueError):
            decoder.analyze(raw)

    def test_reads_without_modification(self):
        original = donor_like()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name, data in original.items():
                (root / name).write_bytes(data)
            self.assertEqual(decoder.load(root), original)


if __name__ == "__main__":
    unittest.main()

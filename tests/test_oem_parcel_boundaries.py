"""Synthetic invariants for the read-only OEM parcel candidate analyzer."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "oem_parcel_boundaries.py"
SPEC = importlib.util.spec_from_file_location("oem_parcel_boundaries", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
decoder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(decoder)


def header(position: int, ptype: int = 19) -> bytes:
    return decoder.PCL_HEADER.pack(
        (0x38 << 24) | (position // 256), 0, ptype, 0, 0, 0, 0, 0, 0, 0, 0)


def synthetic_corpus() -> dict[str, bytes]:
    benelux = bytearray(0x4E000)
    france = bytearray(0x4E000)
    for pos in range(0x2000, 0x4E000, 0x4000):
        benelux[pos:pos + 20] = header(pos)
        france[pos:pos + 20] = header(pos)
    france[0x100] = 0x33
    init = bytearray(0x2A000)
    for left, right in ((0x6000, 0x2000), (0xA000, 0x6000),
                        (0xE000, 0x16000)):
        init[left:left + 0x4000] = benelux[right:right + 0x4000]
    return {"INIT.SDL": bytes(init), "BENELUX0.SDL": bytes(benelux),
            "FRANCE0.SDL": bytes(france),
            "CARTOTOP.SDL": bytes(8192) + header(0x2000, 1) + bytes(4096 - 20)}


class CandidateTests(unittest.TestCase):
    def test_spec_record_width_and_endianness(self):
        self.assertEqual(decoder.PCL_HEADER.size, 20)
        item = decoder.decode_at(header(0x2000), 0)
        self.assertEqual(item["pid_be"], "0x38000020")
        self.assertEqual(item["offset_units_low24"], 32)
        self.assertEqual(item["inferred_position_bytes"], 8192)
        self.assertEqual(item["size_index_bits_29_to_24"], 56)
        self.assertFalse(item["matches_current_offset"])

    def test_regional_partition_and_copy_proofs(self):
        r = decoder.analyze(synthetic_corpus())
        self.assertEqual(r["regional_partition"]["BENELUX0.SDL"]["count"], 19)
        self.assertTrue(r["regional_partition"]["FRANCE0.SDL"]
                        ["all_low24_address_fields_match_position"])
        pairs = {(x["init_offset"], x["source_offset"])
                 for x in r["exact_relocated_16k_fragments"]
                 if x["source_file"] == "BENELUX0.SDL"}
        self.assertEqual(pairs, {(0x6000, 0x2000), (0xA000, 0x6000),
                                 (0xE000, 0x16000)})

    def test_corrupt_region_fails_closed(self):
        files = synthetic_corpus()
        changed = bytearray(files["BENELUX0.SDL"])
        changed[0x2000 + 6] = 0x7F
        files["BENELUX0.SDL"] = bytes(changed)
        with self.assertRaisesRegex(decoder.EvidenceError, "Regional pattern"):
            decoder.analyze(files)

    def test_changed_copy_fails_closed(self):
        files = synthetic_corpus()
        changed = bytearray(files["INIT.SDL"])
        changed[0x6000 + 30] = 1
        files["INIT.SDL"] = bytes(changed)
        with self.assertRaisesRegex(decoder.EvidenceError, "Expected copied INIT"):
            decoder.analyze(files)

    def test_missing_input_not_silent(self):
        files = synthetic_corpus()
        del files["CARTOTOP.SDL"]
        with self.assertRaisesRegex(decoder.EvidenceError, "Missing input"):
            decoder.analyze(files)

    def test_deterministic_report_and_non_mutation(self):
        files = synthetic_corpus()
        before = dict(files)
        self.assertEqual(decoder.analyze(files), decoder.analyze(files))
        self.assertEqual(files, before)
        self.assertIn("Candidate field details", decoder.markdown(
            decoder.analyze(files)))

    def test_out_of_range_header_rejected(self):
        with self.assertRaises(decoder.EvidenceError):
            decoder.decode_at(bytes(19), 0)
        with self.assertRaises(decoder.EvidenceError):
            decoder.decode_at(bytes(20), -1)


if __name__ == "__main__":
    unittest.main()

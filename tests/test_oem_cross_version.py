"""Synthetic regression for cross-release OEM SDAL comparison."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "oem_cross_version.py"
SPEC = importlib.util.spec_from_file_location("oem_cross_version", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def pack(offset: int, index: int, typ: int, region: int, descriptor: int) -> bytes:
    return mod.PCL.pack((index << 24) | (offset // 256), descriptor,
                        typ, region, 0, 0, 0, 0, 0, 0, 0)


def fixture(sections: int, newer: bool) -> dict[str, bytes]:
    assert sections in (16, 19)
    size = 0x2000 + sections * 0x4000
    benelux = bytearray(size)
    france = bytearray(size)
    for off in range(0x2000, size, 0x4000):
        benelux[off:off + 20] = pack(off, 56, 19, 0, 0)
        france[off:off + 20] = pack(off, 56, 19, 0, 0)
    benelux[0x100] = 5
    france[0x100] = 9
    carto = bytearray(184320 if newer else 159744)
    candidate_list = (
        [(0x2000, 56), (0x6000, 56), (0xA000, 46),
         (0x12000, 0), (0x17E00, 45), (0x21B00, 52),
         (0x25700, 42), (0x28900, 59)]
        if newer else
        [(0x2000, 56), (0x6000, 36), (0x8C00, 48),
         (0x11100, 0), (0x18600, 10), (0x19800, 38),
         (0x21100, 43), (0x24400, 15), (0x25B00, 12)])
    for pos, index in candidate_list:
        carto[pos:pos + 20] = pack(pos, index, 255 if pos == 0x2000 else 1,
                                   1, 0 if pos == 0x2000 else 0xB8)
    mtoc = bytearray(4096)
    mtoc[0x48:0x54] = b"BENELUX1.SDL"
    mtoc[0x58:0x5C] = bytes.fromhex("52000001")
    init = bytearray(172032 if newer else 165888)
    init[0:4] = len(init).to_bytes(4, "big")
    init[8:12] = (0x12000).to_bytes(4, "big")
    init[12:16] = (0x94C).to_bytes(4, "big")
    init[0x12000:0x12000 + 0x94C] = mtoc[:0x94C]
    for dest, src in ((0x6000, 0x2000), (0xA000, 0x6000),
                      (0xE000, 0x16000 if newer else 0x12000)):
        copied_bytes = 0x3000 if (not newer and dest == 0xE000) else 0x4000
        init[dest:dest + copied_bytes] = benelux[src:src + copied_bytes]
    if not newer:
        init[0x11000] = 0x7B  # fourth block is deliberately not a byte-identical copy
    region = b"SDAL" + bytes([1 if newer else 2]) + bytes(4091)
    return {
        "INIT.SDL": bytes(init), "MTOC.SDL": bytes(mtoc),
        "REGION.SDL": region, "REGIONS.SDL": region,
        "CARTOTOP.SDL": bytes(carto),
        "BENELUX0.SDL": bytes(benelux), "FRANCE0.SDL": bytes(france),
    }


class CrossVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old = fixture(16, False)
        self.new = fixture(19, True)

    def test_candidate_counts_and_dynamic_layout(self):
        report = mod.analyze({"Z_NEW": self.new, "A_OLD": self.old})
        old, new = report["releases"]["A_OLD"], report["releases"]["Z_NEW"]
        self.assertEqual(len(old["headers"]["BENELUX0.SDL"]), 16)
        self.assertEqual(len(new["headers"]["BENELUX0.SDL"]), 19)
        self.assertEqual(len(old["headers"]["CARTOTOP.SDL"]), 9)
        self.assertEqual(len(new["headers"]["CARTOTOP.SDL"]), 8)
        self.assertTrue(all(p["exact_partition"] and p["candidate_headers_at_every_section"]
                            for rel in (old, new) for p in rel["region_layout"].values()))

    def test_catalog_independent_of_map_revision(self):
        report = mod.analyze({"old": self.old, "new": self.new})
        self.assertTrue(report["comparisons"][0]["mtoc_byte_identical"])
        for rel in report["releases"].values():
            self.assertTrue(rel["init_mtoc_catalog_slice_identical"])
            self.assertTrue(rel["init_first_be32_is_file_size"])
            self.assertEqual(rel["init_catalog_offset_field_be32"], 0x12000)
            self.assertEqual(rel["init_catalog_length_field_be32"], 0x94C)

    def test_relocated_exact_sections_differ_by_revision(self):
        report = mod.analyze({"old": self.old, "new": self.new})
        o = report["releases"]["old"]["init_benelux_aligned_prefix_matches"]
        n = report["releases"]["new"]["init_benelux_aligned_prefix_matches"]
        self.assertIn((0xE000, 0x12000), [(a["init_offset"], a["benelux_offset"]) for a in o])
        self.assertIn((0xE000, 0x16000), [(a["init_offset"], a["benelux_offset"]) for a in n])
        self.assertTrue(all(x["stored_address_points_to_benelux"] for x in o+n))
        old_fragment = next(x for x in o if x["init_offset"] == 0xE000)
        new_fragment = next(x for x in n if x["init_offset"] == 0xE000)
        self.assertEqual(old_fragment["matching_complete_4k_blocks"], 3)
        self.assertFalse(old_fragment["full_16k_identical"])
        self.assertEqual(new_fragment["matching_complete_4k_blocks"], 4)
        self.assertTrue(new_fragment["full_16k_identical"])

    def test_index_zero_gap_is_version_scoped(self):
        old, new = mod.profile(self.old), mod.profile(self.new)
        self.assertNotEqual(old["gap_units_by_size_index_unverified"]["0"],
                            new["gap_units_by_size_index_unverified"]["0"])

    def test_cross_release_change_detected_without_global_assertion(self):
        changed = dict(self.new)
        altered = bytearray(changed["MTOC.SDL"])
        altered[0x48] ^= 1
        changed["MTOC.SDL"] = bytes(altered)
        report = mod.analyze({"old": self.old, "new": changed})
        self.assertFalse(report["comparisons"][0]["mtoc_byte_identical"])
        self.assertFalse(report["releases"]["new"]["init_mtoc_catalog_slice_identical"])

    def test_repeated_analysis_deterministic(self):
        a = mod.analyze({"old": self.old, "new": self.new})
        b = mod.analyze({"new": self.new, "old": self.old})
        self.assertEqual(a, b)
        self.assertIn("Candidate PclHdr_t counts", mod.markdown(a))

    def test_bad_release_label_or_missing_source_rejected(self):
        with self.assertRaisesRegex(mod.EvidenceError, "Invalid release label"):
            mod.analyze({"!bad": self.old, "new": self.new})
        with self.assertRaisesRegex(mod.EvidenceError, "Missing samples"):
            mod.analyze({"old": {"INIT.SDL": b"abc"}, "new": self.new})

    def test_reader_rejects_missing_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name, blob in self.old.items():
                (root / name).write_bytes(blob)
            self.assertEqual(mod.load(root), self.old)
            (root / "INIT.SDL").unlink()
            (root / "INIT.SDL").symlink_to(root / "MTOC.SDL")
            with self.assertRaisesRegex(mod.EvidenceError, "Missing regular file"):
                mod.load(root)


if __name__ == "__main__":
    unittest.main()

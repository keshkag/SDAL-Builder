"""Iter007: three-release invariants and source-backed differences (synthetic only)."""
from __future__ import annotations

import unittest

from test_oem_cross_version import fixture, mod


class ThreeReleaseTests(unittest.TestCase):
    def setUp(self):
        old = fixture(16, False)
        mid = fixture(18, True)
        latest = fixture(19, True)
        # Create exactly three byte positions of REGION difference between mid/latest.
        region = bytearray(mid["REGION.SDL"])
        for offset, value in ((5, 3), (7, 31), (11, 5)):
            region[offset] = value
        mid["REGION.SDL"] = bytes(region)
        mid["REGIONS.SDL"] = bytes(region)
        self.releases = {"OLD_1": old, "OLD_2": mid, "WE_06Q4": latest}

    def test_three_pairs_and_region_counts(self):
        result = mod.analyze(self.releases)
        self.assertEqual(len(result["comparisons"]), 3)
        self.assertEqual(
            [len(result["releases"][x]["headers"]["BENELUX0.SDL"])
             for x in ("OLD_1", "OLD_2", "WE_06Q4")],
            [16, 18, 19])
        self.assertEqual(
            [len(result["releases"][x]["headers"]["CARTOTOP.SDL"])
             for x in ("OLD_1", "OLD_2", "WE_06Q4")],
            [9, 8, 8])

    def test_all_release_catalog_and_common_header_words(self):
        result = mod.analyze(self.releases)
        inv = result["cross_release_invariants"]
        self.assertTrue(inv["all_mtoc_byte_identical"])
        self.assertTrue(inv["all_region_equals_regions"])
        self.assertTrue(inv["all_init_catalog_matches_own_mtoc"])
        self.assertEqual(inv["sample_release_count"], 3)
        words = {x["offset"]: x["be32"] for x in inv["common_init_be32_first_0x50"]}
        self.assertEqual(words[0x08], 0x12000)
        self.assertEqual(words[0x0C], 0x94C)
        self.assertIn("Cross-release observations", mod.markdown(result))

    def test_sparse_region_byte_offsets_and_values(self):
        result = mod.analyze(self.releases)
        comparison = next(x for x in result["comparisons"]
                          if (x["left"], x["right"]) == ("OLD_2", "WE_06Q4"))
        region = comparison["per_file"]["REGION.SDL"]
        self.assertEqual(region["all_changed_byte_offsets"], [5, 7, 11])
        self.assertEqual([x["left"] for x in region["changed_byte_values"]],
                         [3, 31, 5])

    def test_three_complete_relocated_sections(self):
        result = mod.analyze(self.releases)
        for label, profile in result["releases"].items():
            copies = profile["init_benelux_aligned_prefix_matches"]
            matched = {(x["init_offset"], x["benelux_offset"]): x for x in copies}
            self.assertTrue(matched[(0x6000, 0x2000)]["full_16k_identical"])
            self.assertTrue(matched[(0xA000, 0x6000)]["full_16k_identical"])
            source = 0x16000 if label == "WE_06Q4" else 0x12000
            self.assertTrue(matched[(0xE000, source)]["full_16k_identical"])
            self.assertTrue(matched[(0xE000, source)]["stored_address_points_to_benelux"])

    def test_dynamic_mtoc_change_is_detected(self):
        altered = {k: dict(v) for k, v in self.releases.items()}
        raw = bytearray(altered["OLD_2"]["MTOC.SDL"])
        raw[0x48] ^= 1
        altered["OLD_2"]["MTOC.SDL"] = bytes(raw)
        inv = mod.analyze(altered)["cross_release_invariants"]
        self.assertFalse(inv["all_mtoc_byte_identical"])
        self.assertFalse(inv["all_init_catalog_matches_own_mtoc"])

    def test_order_independent_and_read_only(self):
        before = {k: dict(v) for k, v in self.releases.items()}
        self.assertEqual(mod.analyze(self.releases),
                         mod.analyze(dict(reversed(list(self.releases.items())))))
        self.assertEqual(before, self.releases)


if __name__ == "__main__":
    unittest.main()

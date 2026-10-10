"""Synthetic regression for OEM SDL1 parcel candidates and SDL0 regional layout."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "oem_real_map_probe.py"
spec = importlib.util.spec_from_file_location("oem_real_map_probe", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def header(at: int, kind: int, region: int, size: int, *, redundant: bool = False) -> bytes:
    pid = (size << 24) | at//256
    if redundant:
        pid |= 1 << 30
    return m.HEADER.pack(pid, 0, kind, region, 0, 0, 0, 0, 0, 0, 0)


def source():
    a = bytearray(0x2000 + 2*m.SECTION)
    b = bytearray(0x2000 + 2*m.SECTION)
    for at in (0x2000, 0x6000):
        a[at:at+20] = header(at, 19, 0, 56)
        b[at:at+20] = header(at, 19, 0, 56)
    a[0x3000] = 7
    b[0x3000] = 8
    map1 = bytearray(0xA000)
    map1[0x2000:0x2014] = header(0x2000, 24, 1, 9, redundant=True)
    map1[0x6000:0x6014] = header(0x6000, 3, 1, 11)
    map1[0x800:0x81c] = bytes.fromhex("480000c2")*7
    init = bytearray(0x11000)
    for i in range(8):
        off=0x1c8 + 16*i
        pos=0x2000 + i*0x1800
        init[off:off+8] = (pos).to_bytes(4,"big") + (0x1800).to_bytes(4,"big")
        init[pos:pos+28] = bytes.fromhex("480000c2")*7
    return bytes(init), bytes(a), bytes(b), bytes(map1)


class RealMapTests(unittest.TestCase):
    def test_map_header_flags_and_address(self):
        init,a,b,map1=source()
        h=m.header_at(map1,0x2000)
        self.assertEqual(h["parcel_type"],24)
        self.assertTrue(h["redundancy_bit_30"])
        self.assertTrue(h["self_addressed_at_256_bytes"])
        self.assertFalse(h["external_bit_31"])

    def test_map_candidates_are_not_proven_parcels(self):
        h=m.cartographic_candidate_scan(source()[3])
        self.assertEqual(h["candidate_count_not_proven_parcels"],2)
        self.assertEqual({x["type"] for x in h["types"]},{3,24})

    def test_region0_has_real_sections(self):
        init,a,b,map1=source()
        self.assertEqual(m.region0_profile(a)["sections"],2)
        self.assertEqual(m.region0_profile(b)["sections"],2)
        r=m.analyze(init,a,b,map1)
        self.assertEqual(r["SDL0_first_difference"],0x3000)
        self.assertEqual(r["DENSWE0_region_index"]["sections"],2)

    def test_repeated_word_bytes_only(self):
        init,a,b,map1=source()
        r=m.analyze(init,a,b,map1)
        self.assertEqual(len(r["INIT_word_pool_to_BENELUX1_literal_signature"]),8)
        self.assertEqual(r["INIT_word_pool_to_BENELUX1_literal_signature"][0]
                         ["map1_exact_28_byte_matches"],[0x800])

    def test_broken_region_and_truncated_header_rejected(self):
        init,a,b,map1=source()
        with self.assertRaisesRegex(m.EvidenceError, "SDL0"):
            m.region0_profile(a[:-1])
        with self.assertRaises(m.EvidenceError):
            m.header_at(map1, len(map1)-19)
        bad = bytearray(a);bad[0x2000+6]=18
        with self.assertRaisesRegex(m.EvidenceError, "SDL0"):
            m.region0_profile(bytes(bad))

    def test_broken_init_marker_fails_closed(self):
        init,a,b,map1=source()
        bad=bytearray(init);bad[0x2000] ^= 1
        with self.assertRaisesRegex(m.EvidenceError, "seven-word"):
            m.analyze(bytes(bad),a,b,map1)

    def test_no_mutation_and_determinism(self):
        inputs=source()
        self.assertEqual(m.analyze(*inputs),m.analyze(*inputs))
        self.assertEqual(inputs,source())


if __name__ == "__main__":
    unittest.main()

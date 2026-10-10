"""Iter008 synthetic OEM INIT chain regressions, no proprietary donor data."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "oem_init_spans", Path(__file__).resolve().parents[1] / "tools" / "oem_init_spans.py")
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def donor(size: int, bigstart: int, biglen: int, smallstart: int,
          smalllen: int, aftercatalog: int, chainstart: int, source3: int,
          count: int) -> dict[str, bytes]:
    region = bytearray(0x2000 + count * m.BLOCK)
    for offset in range(0x2000, len(region), m.BLOCK):
        region[offset:offset + 4] = ((0x38 << 24) | (offset // 256)).to_bytes(4, "big")
        region[offset + 150] = (offset // m.BLOCK) + 1
    init = bytearray(size)
    mtoc = bytearray(4096)
    mtoc[0x48:0x54] = b"BENELUX1.SDL"
    init[0:4] = size.to_bytes(4, "big")
    init[4:8] = count.to_bytes(4, "big")
    desc = [(0x08, 0x12000, 0x94C), (0x10, 0x258, 0x5A8),
            (0x18, 0x800, 0x1800), (0x20, 0x2000, 0x4000),
            (0x28, bigstart, biglen), (0x30, smallstart, smalllen),
            (0x38, 0x1294C, aftercatalog), (0x40, chainstart, 0x19C),
            (0x48, chainstart + 0x19C, 0x1800),
            (0x240, 0x6000, m.BLOCK), (0x248, 0xA000, m.BLOCK),
            (0x250, 0xE000, m.BLOCK)]
    current = chainstart + 0x19C + 0x1800
    for index, at in enumerate(m.TAIL_FIELDS):
        length = (0x19C, 0x1800)[index % 2]
        desc.append((at, current, length))
        current += length
    assert size - current == 0x184
    for at, address, length in desc:
        m.PAIR.pack_into(init, at, address, length)
    for at, source in ((0x6000, 0x2000), (0xA000, 0x6000),
                       (0xE000, source3)):
        init[at:at+m.BLOCK] = region[source:source+m.BLOCK]
    init[0x800:0x2000] = bytes((j*11+7) & 255 for j in range(0x1800))
    init[0x2000:0x3800] = init[0x800:0x2000]
    init[0x12000:0x1294C] = mtoc[:0x94C]
    return {"INIT.SDL": bytes(init), "MTOC.SDL": bytes(mtoc),
            "BENELUX0.SDL": bytes(region)}


def donors():
    return {
        "OLDER_1": donor(0x28800, 0x13800, 0x6800, 0x13660, 0xF4,
                         0xD14, 0x1A000, 0x12000, 16),
        "OLDER_2": donor(0x29800, 0x13800, 0x7800, 0x136D8, 0x10C,
                         0xD8C, 0x1B000, 0x12000, 18),
        "WE_06Q4": donor(0x2A000, 0x14000, 0x7800, 0x13D50, 0x118,
                          0x1404, 0x1B800, 0x16000, 19),
    }


class SpanEvidenceTest(unittest.TestCase):
    def test_three_independent_release_profiles(self):
        result = m.analyze(donors())
        self.assertEqual(len(result["releases"]), 3)
        for row in result["releases"].values():
            self.assertTrue(all(row["checks"].values()))
            self.assertEqual(row["trailing_padding_bytes"], 0x184)
            self.assertEqual(len(row["long_chain_16_following_descriptors"]), 16)
            self.assertEqual([p["length"] for p in row["long_chain_16_following_descriptors"]],
                             [0x19C, 0x1800] * 8)

    def test_relocated_exact_copies(self):
        result = m.analyze(donors())
        for name, source3 in (("OLDER_1", 0x12000), ("OLDER_2", 0x12000),
                              ("WE_06Q4", 0x16000)):
            proof = result["releases"][name]["region_copy_proofs"]
            self.assertEqual([m["matches"][0]["source"] for m in proof],
                             [0x2000, 0x6000, source3])

    def test_pointer_corruption_rejected(self):
        d = donors()
        d["OLDER_1"] = dict(d["OLDER_1"])
        blob = bytearray(d["OLDER_1"]["INIT.SDL"])
        blob[0x40:0x44] = (0x300).to_bytes(4, "big")
        d["OLDER_1"]["INIT.SDL"] = bytes(blob)
        with self.assertRaises(m.EvidenceError):
            m.analyze(d)

    def test_catalog_corruption_rejected(self):
        d = donors()
        d["OLDER_2"] = dict(d["OLDER_2"])
        b = bytearray(d["OLDER_2"]["MTOC.SDL"])
        b[0x48] ^= 1
        d["OLDER_2"]["MTOC.SDL"] = bytes(b)
        with self.assertRaisesRegex(m.EvidenceError, "catalog"):
            m.analyze(d)

    def test_copy_corruption_rejected(self):
        d = donors()
        d["WE_06Q4"] = dict(d["WE_06Q4"])
        b = bytearray(d["WE_06Q4"]["INIT.SDL"])
        b[0xE000+100] ^= 1
        d["WE_06Q4"]["INIT.SDL"] = bytes(b)
        with self.assertRaisesRegex(m.EvidenceError, "regional_sources"):
            m.analyze(d)

    def test_duplicate_region_corruption_rejected(self):
        d = donors()
        d["OLDER_1"] = dict(d["OLDER_1"])
        b = bytearray(d["OLDER_1"]["INIT.SDL"])
        b[0x2000] ^= 1
        d["OLDER_1"]["INIT.SDL"] = bytes(b)
        with self.assertRaisesRegex(m.EvidenceError, "duplicated"):
            m.analyze(d)

    def test_repeat_is_deterministic_and_read_only(self):
        d = donors()
        baseline = {label: dict(files) for label, files in d.items()}
        first = m.analyze(d)
        self.assertEqual(first, m.analyze(dict(reversed(list(d.items())))))
        self.assertEqual(d, baseline)
        self.assertIn("Structural links checked", m.markdown(first))


if __name__ == "__main__":
    unittest.main()

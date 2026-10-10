"""Offline deterministic tests for exact OEM SDL block provenance."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "oem_block_provenance.py"
spec = importlib.util.spec_from_file_location("oem_block_provenance", SCRIPT)
assert spec is not None and spec.loader is not None
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

def block(salt: int) -> bytes:
    return bytes([1, salt, 2, 3, 4, 5, 6, 7])

class ProvenanceTests(unittest.TestCase):
    def test_relocated_consecutive_blocks(self):
        b1, b2, b3 = block(11), block(12), block(13)
        pair = p.analyze({"L.SDL": b1+b2+b3,
                          "R.SDL": bytes(8)+b1+b2}, block_bytes=8)["comparisons"][0]
        self.assertEqual(pair["matching_offset_pairs"], 2)
        self.assertEqual(pair["distinct_matching_left_blocks"], 2)
        self.assertEqual(pair["runs"], [{"left_offset": 0, "right_offset": 8,
                                         "block_count": 2, "length_bytes": 16}])

    def test_filters_filler_and_partial_blocks(self):
        raw = bytes(8) + bytes([255])*8 + b"\x01\x03"
        result = p.analyze({"A.SDL": raw, "B.SDL": raw}, block_bytes=8)
        self.assertTrue(result["comparisons"][0]["entire_file_identical"])
        self.assertEqual(result["comparisons"][0]["matching_offset_pairs"], 0)
        self.assertEqual(result["files"][0]["partial_tail_bytes"], 2)

    def test_repeated_block_pairs_are_counted_exactly(self):
        shared = block(44)
        pair = p.analyze({"A.SDL": shared+shared, "B.SDL": shared},
                         block_bytes=8)["comparisons"][0]
        self.assertEqual(pair["matching_offset_pairs"], 2)
        self.assertEqual(pair["distinct_matching_left_blocks"], 2)
        self.assertEqual(pair["distinct_matching_right_blocks"], 1)

    def test_order_independent(self):
        one = {"Z.SDL": block(5), "A.SDL": block(6)}
        two = {"A.SDL": block(6), "Z.SDL": block(5)}
        self.assertEqual(p.analyze(one, block_bytes=8), p.analyze(two, block_bytes=8))

    def test_fails_closed_on_bad_arguments(self):
        with self.assertRaises(ValueError):
            p.analyze({"A": b"abc"})
        with self.assertRaises(ValueError):
            p.analyze({"A": b"a", "B": b"b"}, block_bytes=0)
        with self.assertRaises(TypeError):
            p.analyze({"A": bytearray(b"a"), "B": b"a"})

    def test_file_input_safety(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root/"A.SDL"
            b = root/"B.SDL"
            a.write_bytes(b"one")
            b.write_bytes(b"two")
            self.assertEqual(p.read_paths([b,a]), {"A.SDL": b"one", "B.SDL": b"two"})
            with self.assertRaises(ValueError):
                p.read_paths([a,a])
            (root/"SYMLINK.SDL").symlink_to(a)
            with self.assertRaises(ValueError):
                p.read_paths([a, root/"SYMLINK.SDL"])

if __name__ == "__main__":
    unittest.main()

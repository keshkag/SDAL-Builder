"""Offline regression tests for the read-only OEM inventory."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "oem_inventory.py"
spec = importlib.util.spec_from_file_location("oem_inventory", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OemInventoryTest(unittest.TestCase):
    def test_stats_ascii_positions_and_missing_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            blob = b"\0" * 4092 + b"ABCD.SDL\0" + b"\x01" + b"\0" * 4078
            (root / "INIT.SDL").write_bytes(blob)
            (root / "ABCD.SDL").write_bytes(b"\x01\x02")
            report = module.inventory(root)
            self.assertEqual(report["total_files"], 2)
            record = next(r for r in report["files"] if r["path"] == "INIT.SDL")
            self.assertEqual(record["size_bytes"], len(blob))
            self.assertEqual(record["nonzero_bytes"], 9)
            self.assertEqual(len(record["blocks"]), 2)
            self.assertEqual(record["ascii_sdl_candidates"], [
                {"offset": 4092, "name": "ABCD.SDL", "present_in_corpus_by_basename": True}])
            self.assertEqual(sum(b["nonzero_bytes"] for b in record["blocks"]), 9)

    def test_empty_corpus_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "No SDL files"):
                module.inventory(Path(td))

    def test_symlinks_not_followed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "SAFE.SDL").write_bytes(b"good")
            (root / "ALIAS.SDL").symlink_to(root / "SAFE.SDL")
            self.assertEqual(module.inventory(root)["total_files"], 1)

    def test_stream_match_crosses_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = b"\0" * (module.CHUNK_SIZE - 3) + b"INIT.SDL\0"
            (root / "CROSS.SDL").write_bytes(payload)
            refs = module.inventory(root)["files"][0]["ascii_sdl_candidates"]
            self.assertEqual(refs, [{"offset": module.CHUNK_SIZE - 3,
                                     "name": "INIT.SDL", "present_in_corpus_by_basename": False}])


if __name__ == "__main__":
    unittest.main()

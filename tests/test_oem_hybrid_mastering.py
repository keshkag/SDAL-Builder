"""Hybrid mastering smoke-test: real genisoimage binary plus ISO/Joliet/UDF verification.

This tests filesystem layout, NOT SDAL content or Denso hardware acceptance.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.iso import MasteringError, _verify_hybrid, build_iso


class HybridISOTests(unittest.TestCase):
    def _sources(self, root: Path) -> list[Path]:
        names = ("INIT.SDL", "MTOC.SDL", "CARTOTOP.SDL", "BENELUX0.SDL",
                 "BENELUX1.SDL", "DENSWE0.SDL", "DENSWE1.SDL")
        result = []
        for i, name in enumerate(names):
            f = root / name
            f.write_bytes(bytes([i+1]) * (4096 + i*233))
            result.append(f)
        return result

    def test_real_udf_iso9660_joliet(self):
        if not (shutil.which("genisoimage") or shutil.which("mkisofs")):
            self.fail("An ISO/UDF-capable genisoimage or mkisofs is required")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._sources(root)
            out = root / "WE_06Q4.iso"
            build_iso(paths, out)
            self.assertTrue(out.is_file())
            self.assertEqual(out.stat().st_size % 2048, 0)
            _verify_hybrid(out, {p.name: p.stat().st_size for p in paths}, "WE_06Q4")
            before = out.read_bytes()
            self.assertNotEqual(before[:2048], b"")
            self.assertGreater(len(before), 1<<18)

    def test_iso_payload_corruption_is_detected_by_sha256(self):
        if not (shutil.which("genisoimage") or shutil.which("mkisofs")):
            self.fail("Hybrid mastering executable missing")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._sources(root)
            out = root / "WE_06Q4.iso"
            build_iso(paths, out)
            with out.open("r+b") as fd:
                # Locate a known data byte using independently decoded ISO9660 root.
                from sdal_builder.iso import _descriptor, _entries
                _, _, loc, length = _descriptor(fd, 16, 1)
                row = _entries(fd, loc, length, joliet=False)["BENELUX1.SDL;1"]
                fd.seek(row[0] * 2048 + 10)
                original = fd.read(1)
                fd.seek(row[0] * 2048 + 10)
                fd.write(bytes([original[0] ^ 0xFF]))
            with self.assertRaisesRegex(MasteringError, "hash mismatch"):
                _verify_hybrid(out, {p.name:p.stat().st_size for p in paths},
                               "WE_06Q4", {p.name:p for p in paths})

    def test_invalid_input_fails_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._sources(root)
            src = root / "BAD-NAME.SDL"
            src.write_bytes(b"bad")
            out = root / "out.iso"
            with self.assertRaisesRegex(MasteringError,"8.3"):
                build_iso(sources+[src],out)
            self.assertFalse(out.exists())

    def test_no_iso9660_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._sources(root)
            dest = root / "sample.iso"
            original_which = shutil.which
            try:
                shutil.which = lambda _: None
                with self.assertRaisesRegex(MasteringError,"requires genisoimage"):
                    build_iso(sources,dest)
            finally:
                shutil.which = original_which
            self.assertFalse(dest.exists())

    def test_source_name_collision_is_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = self._sources(root)
            with self.assertRaisesRegex(MasteringError, "Duplicate SDL"):
                build_iso([sources[0],sources[0],sources[1]],root/"dup.iso")

    def test_volume_name_must_be_valid_iso(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = self._sources(root)
            old = os.environ.get("SDAL_VOLUME_ID")
            os.environ["SDAL_VOLUME_ID"] = "BAD LABEL"
            try:
                with self.assertRaisesRegex(MasteringError,"SDAL_VOLUME_ID"):
                    build_iso(paths,root/"my.iso")
            finally:
                if old is None:
                    os.environ.pop("SDAL_VOLUME_ID",None)
                else:
                    os.environ["SDAL_VOLUME_ID"] = old


if __name__ == "__main__":
    unittest.main()

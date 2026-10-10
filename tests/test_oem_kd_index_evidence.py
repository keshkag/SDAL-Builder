"""Offline synthetic evidence-report regressions for the OEM KD index chain."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from sdal_builder.oem_index import PCL, EvidenceError, encode_new_index_parcel

spec = importlib.util.spec_from_file_location(
    "oem_kd_index_evidence", ROOT / "tools" / "oem_kd_index_evidence.py")
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def original_style_map() -> bytes:
    data = bytearray(0x20000)
    for pos in (0x2000, 0x7100):
        pid = 0x49000000 | (pos // 256)
        data[pos:pos+20] = PCL.pack(pid, 0, 24, 1, 0, 0, 0, 0, 0, 0, 0)
    for pos in (0xC200, 0x11200):
        blob = encode_new_index_parcel(
            file_offset=pos, size_index=8,
            root_blobs=(bytes([pos // 256 % 256]) * 17, b"\x10\x00\xff\xff"))
        data[pos:pos+len(blob)] = blob
    return bytes(data)


def original_style_init() -> bytes:
    data = bytearray(0x2A000)
    for i in range(8):
        offset = 0x14000 + i * 0x1800
        struct.pack_into(">II", data, 0x1C8 + i*16, offset, 0x1800)
        data[offset:offset+28] = (0x480000C2).to_bytes(4, "big") * 7
    return bytes(data)


class IndexInventoryTests(unittest.TestCase):
    def test_reports_2_map_headers_and_index_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "BENELUX1.SDL"
            path.write_bytes(original_style_map())
            init = root / "INIT.SDL"
            init.write_bytes(original_style_init())
            report = m.audit({"BENELUX1": path, "SWIAUS1": path}, init)
            self.assertEqual(report["maps"]["BENELUX1"]["index_parcel_count"], 2)
            self.assertEqual(report["maps"]["SWIAUS1"]["total_roots"], 4)
            self.assertTrue(report["maps"]["BENELUX1"]["index_parcels"][1]
                            ["byte_identical_after_reassembly"])
            self.assertEqual(report["init_reference"]["eight_group_references"][0]
                             ["candidate_direct_byte_address"], 0xC200)
            self.assertIn("Index records", m.render_md(report))

    def test_corrupted_map_header_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BENELUX1.SDL"
            data = bytearray(original_style_map())
            data[0x2000 + 6] = 1
            path.write_bytes(data)
            with self.assertRaisesRegex(EvidenceError, "Map Header"):
                m.audit_map(path)

    def test_corrupted_kd_index_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "BENELUX1.SDL"
            data = bytearray(original_style_map())
            struct.pack_into(">H", data, 0xC200+24, 0)
            path.write_bytes(data)
            with self.assertRaises(EvidenceError):
                m.audit_map(path)

    def test_mismatched_init_marker_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "SWIAUS1.SDL"
            path.write_bytes(original_style_map())
            init = root / "INIT.SDL"
            data = bytearray(original_style_init())
            data[0x14000:0x14004] = (0x480000D2).to_bytes(4, "big")
            init.write_bytes(data)
            with self.assertRaisesRegex(EvidenceError, "Seven repeated"):
                m.audit({"SWIAUS1": path}, init)


if __name__ == "__main__":
    unittest.main()

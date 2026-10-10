"""Synthetic regressions for reversible SDAL global KD-tree index parcels."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import struct
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "src" / "sdal_builder" / "oem_index.py"
spec = importlib.util.spec_from_file_location("oem_index", SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def sample() -> bytes:
    return m.encode_new_index_parcel(
        file_offset=0xC200, size_index=8,
        root_blobs=(b"first-tree", b"other-tree"))


class OEMKDIndexTests(unittest.TestCase):
    def test_oem_parcel_id_bits_and_physical_offsets(self):
        self.assertEqual(m.compose_parcel_id(
            file_offset=0xC200, size_index=8, redundancy=True), 0x480000C2)
        self.assertEqual(m.compose_parcel_id(
            file_offset=0x2000, size_index=9, redundancy=True), 0x49000020)
        with self.assertRaises(m.EvidenceError):
            m.compose_parcel_id(file_offset=0xC201, size_index=8, redundancy=True)
        with self.assertRaises(m.EvidenceError):
            m.compose_parcel_id(file_offset=0xC200, size_index=64, redundancy=True)
        with self.assertRaises(m.EvidenceError):
            m.compose_parcel_id(file_offset=0xC200, size_index=8, redundancy=True,
                                external=True)

    def test_reversible_root_table(self):
        raw = sample()
        self.assertEqual(len(raw), 0x5000)
        parsed = m.decode_index_parcel(raw, absolute_offset=0xC200)
        self.assertEqual(parsed.root_offsets, (28, 38))
        self.assertEqual(parsed.reassemble(), raw)
        self.assertEqual(len(parsed.root_blobs), 2)

    def test_parcel_header_fields(self):
        parsed = m.decode_index_parcel(sample(), absolute_offset=0xC200)
        h = m.header_fields(parsed.raw_header)
        self.assertEqual((h["parcel_id"], h["parcel_type"], h["region"]),
                         (0x480000C2, 255, 1))
        self.assertEqual(h["size_index"], 8)
        self.assertTrue(h["redundancy"])
        self.assertFalse(h["external"])
        self.assertEqual(parsed.root_offsets[0], 24 + 2 * len(parsed.root_offsets))

    def test_first_array_boundary_fails_closed(self):
        data = bytearray(sample())
        struct.pack_into(">H", data, 24, 29)
        with self.assertRaisesRegex(m.EvidenceError, "First root"):
            m.decode_index_parcel(bytes(data), absolute_offset=0xC200)

    def test_nonmonotonic_fails_closed(self):
        data = bytearray(sample())
        struct.pack_into(">H", data, 26, 27)
        with self.assertRaisesRegex(m.EvidenceError, "ascending"):
            m.decode_index_parcel(bytes(data), absolute_offset=0xC200)

    def test_wrong_sector_and_wrong_type_rejected(self):
        with self.assertRaisesRegex(m.EvidenceError, "ParcelID"):
            m.decode_index_parcel(sample(), absolute_offset=0xD200)
        data = bytearray(sample())
        data[6] = 1
        with self.assertRaisesRegex(m.EvidenceError, "type-255"):
            m.decode_index_parcel(bytes(data), absolute_offset=0xC200)

    def test_root_overflow_rejected(self):
        with self.assertRaisesRegex(m.EvidenceError, "capacity"):
            m.encode_new_index_parcel(
                file_offset=0xC200, size_index=8, root_blobs=(bytes(0x5000),))

    def test_index_extension_rejected(self):
        data = bytearray(sample())
        struct.pack_into(">H", data, 22, 42)
        with self.assertRaisesRegex(m.EvidenceError, "extension"):
            m.decode_index_parcel(bytes(data), absolute_offset=0xC200)

    def test_wrong_size_and_invalid_input_rejected(self):
        with self.assertRaisesRegex(m.EvidenceError, "0x5000"):
            m.decode_index_parcel(sample()[:-1], absolute_offset=0xC200)
        with self.assertRaises(m.EvidenceError):
            m.encode_new_index_parcel(
                file_offset=0xC200, size_index=8, root_blobs=())

    def test_rebuild_is_deterministic(self):
        raw = sample()
        a = m.decode_index_parcel(raw, absolute_offset=0xC200)
        b = m.decode_index_parcel(raw, absolute_offset=0xC200)
        self.assertEqual(a, b)
        self.assertEqual(a.reassemble(), b.reassemble())


if __name__ == "__main__":
    unittest.main()

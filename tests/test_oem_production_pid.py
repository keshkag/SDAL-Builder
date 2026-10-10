"""Regression of production encoder's SDAL ParcelID_t 32-bit layout."""
from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sdal_builder.encoder import encode_bytes


class ProductionParcelIDTests(unittest.TestCase):
    def pid(self, **kwargs) -> int:
        raw = encode_bytes(0, b"", region=1, parcel_type=255, **kwargs)
        return struct.unpack_from(">I", raw)[0]

    def test_oem_index_0x480000c2(self):
        self.assertEqual(self.pid(offset_units=0xC2, size_index=8, redundancy=True),
                         0x480000C2)

    def test_oem_map_header_0x49000020(self):
        self.assertEqual(self.pid(offset_units=0x20, size_index=9, redundancy=True),
                         0x49000020)

    def test_external_reference_bit_31(self):
        # External entries are indirect handles, not local byte positions.
        self.assertEqual(self.pid(offset_units=5, size_index=8, external_to_region=True),
                         0x88000005)

    def test_both_flags(self):
        self.assertEqual(self.pid(offset_units=0xC2, size_index=8,
                                  redundancy=True, external_to_region=True),
                         0xC80000C2)

    def test_precomposed_pid_is_not_replaced(self):
        result = encode_bytes(0x480000C2, b"", offset_units=0x20, size_index=9)
        self.assertEqual(struct.unpack_from(">I", result)[0], 0x480000C2)

    def test_unsupported_address_or_index_rejected(self):
        for kwargs in ({"offset_units": -1}, {"offset_units": 1 << 24},
                       {"size_index": -1}, {"size_index": 64}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.pid(**kwargs)


if __name__ == "__main__":
    unittest.main()

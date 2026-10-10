"""Independent original-media CLI contract exercised on generated SDAL bytes."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"tools"))
from test_oem_media_allocator import test_region
from sdal_builder.oem_media_allocator import (
    MediaSizeFields,write_media_size_fields,MediaLayoutError,
)
from oem_media_size_evidence import inspect


class MediaSourceAuditTests(unittest.TestCase):
    def test_exact_media_size_index_resolves_region_parcel_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            table,layout,region,*_=test_region()
            media=root/"0.SDL"
            regionfile=root/"1.SDL"
            media.write_bytes(write_media_size_fields(bytes(2048),
                MediaSizeFields(table,8,24,6)))
            regionfile.write_bytes(region)
            carto=layout.get("left-carto")
            routing=layout.get("right-routing")
            result=inspect(media,regionfile,(carto.pid,routing.pid))
            self.assertEqual(result["sector_bytes"],256)
            self.assertEqual(result["active_size_count"],25)
            self.assertEqual({p["parcel_type"] for p in result["referenced_parcels"]},
                             {0,1})
            self.assertEqual(len(result["referenced_parcels"]),2)
            self.assertEqual(media.stat().st_size,2048)

    def test_rejects_wrong_header_or_global_size_before_claiming_parity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            table,layout,region,*_=test_region()
            media=root/"0.SDL";regionfile=root/"1.SDL"
            media.write_bytes(write_media_size_fields(bytes(2048),
                MediaSizeFields(table,8,24,6)))
            regionfile.write_bytes(region)
            p=layout.get("left-carto")
            buf=bytearray(region);buf[p.start]^=1
            regionfile.write_bytes(buf)
            with self.assertRaisesRegex(MediaLayoutError,"header disagrees"):
                inspect(media,regionfile,(p.pid,))
            regionfile.write_bytes(region)
            b=bytearray(media.read_bytes());b[1250]=0
            media.write_bytes(b)
            with self.assertRaisesRegex(MediaLayoutError,"Count"):
                inspect(media,regionfile,(p.pid,))

if __name__=="__main__":
    unittest.main()

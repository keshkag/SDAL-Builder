"""Donor-free, deterministic tests for ISO9660/Joliet/UDF edge evidence."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import struct
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "oem_iso_layout.py"
SPEC = importlib.util.spec_from_file_location("oem_iso_layout", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def put_mirror4(arr: bytearray, at: int, value: int) -> None:
    arr[at:at+4] = struct.pack("<I", value)
    arr[at+4:at+8] = struct.pack(">I", value)


def record(name: str | None, lba: int, size: int, *, joliet: bool) -> bytes:
    raw = (bytes([0 if name is None else 1]) if name is None else
           name.encode("utf-16-be" if joliet else "ascii"))
    n = 33 + len(raw) + (0 if len(raw) & 1 else 1)
    b = bytearray(n)
    b[0] = n
    put_mirror4(b, 2, lba)
    put_mirror4(b, 10, size)
    b[25] = 2 if name is None else 0
    b[28:32] = b"\x01\x00\x00\x01"
    b[32] = len(raw)
    b[33:33+len(raw)] = raw
    return bytes(b)


def descriptor(code: int, root_lba: int, root_size: int, blocks: int) -> bytes:
    d = bytearray(2048)
    d[:7] = bytes([code]) + b"CD001\x01"
    d[40:72] = ("WE_06Q4".encode("utf-16-be").ljust(32, b"\x00")
                if code == 2 else b"WE_06Q4".ljust(32, b" "))
    put_mirror4(d, 80, blocks)
    d[128:132] = b"\x00\x08\x08\x00"
    put_mirror4(d, 132, 10)
    d[140:144] = struct.pack("<I", 257)
    d[148:152] = struct.pack(">I", 258)
    d[156:156+34] = record(None, root_lba, root_size, joliet=False)
    if code == 2:
        d[88:91] = b"%/E"
    return bytes(d)


def tag(identifier: int, lba: int) -> bytes:
    s = bytearray(2048)
    struct.pack_into("<HH", s, 0, identifier, 2)
    struct.pack_into("<I", s, 12, lba)
    s[4] = sum(s[i] for i in range(16) if i != 4) & 255
    return bytes(s)


def samples() -> tuple[bytes, bytes]:
    front = bytearray(1 << 20)
    rear = bytearray(1 << 20)
    blocks = 3224081
    for n, code, root_lba in ((16,1,261),(17,2,263)):
        front[n*2048:(n+1)*2048] = descriptor(code,root_lba,4096,blocks)
    front[18*2048:18*2048+7] = b"\xffCD001\x01"
    for n,label in ((19,b"BEA01"),(20,b"NSR02"),(21,b"TEA01")):
        front[n*2048+1:n*2048+6] = label
    for n, identity in enumerate((1,4,5,6,7,8), start=32):
        front[n*2048:(n+1)*2048] = tag(identity,n)
    front[256*2048:257*2048] = tag(2,256)
    rear[-2048:] = tag(2,blocks-1)
    from_repo = {
        "INIT.SDL": (12028, 172032),
        "BENELUX1.SDL": (2430082, 350914560),
        "SWIAUS1.SDL": (2601427, 364488704),
        "DENSWE0.SDL": (1340376, 319488),
        "DENSWE1.SDL": (894268, 912990208),
        "SWIAUS0.SDL": (1340220, 319488),
    }
    for joliet,root_lba in ((False,261),(True,263)):
        recs = [record(None,root_lba,4096,joliet=joliet)]
        for name,(extent,length) in sorted(from_repo.items()):
            recs.append(record(name+";1",extent,length,joliet=joliet))
        body = b"".join(recs)
        front[root_lba*2048:root_lba*2048+len(body)] = body
    return bytes(front), bytes(rear)


class IsoEdgeTests(unittest.TestCase):
    def test_volume_geometry_and_udf_anchors(self):
        p, q = samples()
        r = m.analyze(p,q)
        self.assertEqual(r["volume"]["id"], "WE_06Q4")
        self.assertEqual(r["volume"]["sectors"], 3224081)
        self.assertEqual(r["volume"]["root_file_count"], 6)
        self.assertEqual(r["udf"]["recognition_sequence"], ["BEA01","NSR02","TEA01"])
        self.assertTrue(r["udf"]["end_anchor"]["checksum_ok"])
        self.assertTrue(r["all_iso9660_joliet_names_and_extents_identical"])
        self.assertIn("UDF anchors",m.markdown(r))

    def test_invalid_volume_label(self):
        a,b = samples()
        bad=bytearray(a)
        bad[16*2048+40]=ord("X")
        with self.assertRaisesRegex(m.EvidenceError, "volume label"):
            m.analyze(bytes(bad),b)

    def test_missing_udf_tail_anchor(self):
        a,b=samples()
        with self.assertRaisesRegex(m.EvidenceError, "anchor"):
            m.analyze(a,b[:-2048]+bytes(2048))

    def test_bad_udf_checksum(self):
        a,b=samples()
        broken=bytearray(b)
        broken[-2048+4] ^= 1
        with self.assertRaisesRegex(m.EvidenceError, "anchor"):
            m.analyze(a,bytes(broken))

    def test_joliet_extent_disagreement(self):
        a,b=samples()
        broken=bytearray(a)
        # First actual Joliet entry follows the 34-byte parent record.
        at=263*2048+34+2
        changed=int.from_bytes(broken[at:at+4],"little")+1
        put_mirror4(broken,at,changed)
        with self.assertRaisesRegex(m.EvidenceError, "file entries differ"):
            m.analyze(bytes(broken),b)

    def test_extent_overlap(self):
        a,b=samples()
        broken=bytearray(a)
        # Alter physical extent in both ISO and Joliet roots consistently.
        for root in (261,263):
            base=root*2048
            length=broken[base]
            pos=base+length
            # second record after parent should now overlap the DENSWE0 extent.
            put_mirror4(broken,pos+2,1340376)
        with self.assertRaises(m.EvidenceError):
            m.analyze(bytes(broken),b)

    def test_source_sizes_and_endian(self):
        a,b=samples()
        changed=bytearray(a)
        changed[16*2048+84] ^= 1
        with self.assertRaisesRegex(m.EvidenceError,"endian"):
            m.analyze(bytes(changed),b)

    def test_partial_samples_rejected(self):
        a,b=samples()
        with self.assertRaisesRegex(m.EvidenceError,"exact first and last"):
            m.analyze(a[:-1],b)


if __name__ == "__main__":
    unittest.main()

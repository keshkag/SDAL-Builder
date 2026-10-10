"""Synthetic regressions for paired INIT range evidence, without donor binaries."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'oem_init_pair_tables.py'
spec = importlib.util.spec_from_file_location('oem_init_pair_tables', SCRIPT)
assert spec is not None and spec.loader is not None
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def donor(start: int, identifier: int) -> dict[str, bytes]:
    size = start + 9 * (m.SHORT_BYTES + m.LONG_BYTES) + 0x184
    init = bytearray(size)
    regional = bytearray(0x2000 + 5 * 0x4000)
    carto = bytearray(0x2000 + 5 * 0x4000)
    first_pid = 0x38000020
    for blob in (regional, carto):
        blob[0x2000:0x2004] = first_pid.to_bytes(4, 'big')
    pos = start
    for i, (ap, bp) in enumerate(m.SLOTS):
        m.PAIR.pack_into(init, ap, pos, m.SHORT_BYTES)
        meta = bytearray(m.SHORT_BYTES)
        if i:
            meta[:4] = (0x68000000 + i + identifier).to_bytes(4, 'big')
        init[pos:pos + m.SHORT_BYTES] = meta
        pos += m.SHORT_BYTES
        m.PAIR.pack_into(init, bp, pos, m.LONG_BYTES)
        pool = bytearray(m.LONG_BYTES)
        pid = first_pid if i == 0 else (identifier << 24) | 0xC2
        for n in range(7):
            m.WORD.pack_into(pool, 4*n, pid)
        for n in range(10, 80):
            m.WORD.pack_into(pool, 4*n, (i + 1) * 10000 + n)
        init[pos:pos + m.LONG_BYTES] = pool
        pos += m.LONG_BYTES
    assert pos + 0x184 == size
    return {'INIT.SDL': bytes(init), 'MTOC.SDL': b'',
            'BENELUX0.SDL': bytes(regional), 'CARTOTOP.SDL': bytes(carto)}


class InitPairTablesTests(unittest.TestCase):
    def setUp(self):
        self.releases = {'A': donor(0x1A000, 0x38), 'B': donor(0x1B800, 0x48)}

    def test_groups_and_lengths(self):
        r = m.analyze(self.releases)
        for v in r['releases'].values():
            self.assertTrue(all(v['checks'].values()))
            self.assertEqual([g['first_be32_word_count'] for g in v['groups']], [103]*9)
            self.assertEqual([g['second_be32_word_count'] for g in v['groups']], [1536]*9)
            self.assertEqual(v['groups'][0]['repeated_word_hex'], '0x38000020')
            self.assertEqual(len(v['groups']), 9)

    def test_detects_silent_pair_disconnection(self):
        d = dict(self.releases['A'])
        raw = bytearray(d['INIT.SDL'])
        off = m.SLOTS[3][1]
        raw[off:off+4] = (0x1A100).to_bytes(4, 'big')
        d['INIT.SDL'] = bytes(raw)
        with self.assertRaisesRegex(m.EvidenceError, 'Disconnected'):
            m.analyze_release(d)

    def test_detects_corrupt_repeated_words(self):
        d = dict(self.releases['A'])
        raw = bytearray(d['INIT.SDL'])
        off, _ = m.PAIR.unpack_from(raw, m.SLOTS[4][1])
        raw[off+8] ^= 1
        d['INIT.SDL'] = bytes(raw)
        with self.assertRaisesRegex(m.EvidenceError, 'first seven'):
            m.analyze_release(d)

    def test_source_header_evidence_not_guessed(self):
        d = dict(self.releases['A'])
        raw = bytearray(d['CARTOTOP.SDL'])
        raw[0x2000] ^= 1
        d['CARTOTOP.SDL'] = bytes(raw)
        self.assertTrue(m.analyze_release(d)['checks']['first_pool_word_is_at_least_one_external_file_header'])
        region = bytearray(d['BENELUX0.SDL'])
        region[0x2000] ^= 1
        d['BENELUX0.SDL'] = bytes(region)
        with self.assertRaisesRegex(m.EvidenceError, 'external_file_header'):
            m.analyze_release(d)

    def test_detection_is_read_only_and_order_independent(self):
        before = {k: dict(v) for k, v in self.releases.items()}
        out = m.analyze(self.releases)
        self.assertEqual(out, m.analyze(dict(reversed(list(self.releases.items())))))
        self.assertEqual(before, self.releases)
        self.assertIn('nine paired', m.markdown(out))

    def test_rejects_invalid_release_and_missing_inputs(self):
        with self.assertRaisesRegex(m.EvidenceError, 'Invalid release'):
            m.analyze({'??': self.releases['A'], 'B': self.releases['B']})
        incomplete = dict(self.releases['A'])
        del incomplete['BENELUX0.SDL']
        with self.assertRaisesRegex(m.EvidenceError, 'Missing donor files'):
            m.analyze_release(incomplete)
        with self.assertRaisesRegex(m.EvidenceError, 'At least two'):
            m.analyze({'A': self.releases['A']})


if __name__ == '__main__':
    unittest.main()

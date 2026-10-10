#!/usr/bin/env python3
"""Read-only OEM INIT paired-range inspector: direct bytes, no semantic guesses.

This is not a validator for bootable SDAL media or a writer.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import re
from struct import Struct

PAIR = Struct('>II')
WORD = Struct('>I')
SHORT_BYTES = 0x19C
LONG_BYTES = 0x1800
SLOTS = ((0x40, 0x48),) + tuple((0x1C0 + 16 * i, 0x1C8 + 16 * i)
                                    for i in range(8))
REQUIRED = ('INIT.SDL', 'MTOC.SDL', 'BENELUX0.SDL', 'CARTOTOP.SDL')


class EvidenceError(ValueError):
    pass


def bounded_pair(data: bytes, position: int, required_length: int) -> tuple[int, int]:
    if position < 0 or position + PAIR.size > len(data):
        raise EvidenceError(f'Descriptor at 0x{position:X} is out of bounds')
    offset, length = PAIR.unpack_from(data, position)
    if length != required_length or offset >= len(data) or length > len(data) - offset:
        raise EvidenceError(f'Invalid span at descriptor 0x{position:X}')
    return offset, length


def words_of(fragment: bytes) -> list[int]:
    if len(fragment) % 4:
        raise EvidenceError('Cannot read unaligned BE32 words')
    return [WORD.unpack_from(fragment, i)[0] for i in range(0, len(fragment), 4)]


def analyze_release(files: dict[str, bytes], strict: bool = True) -> dict:
    missing = sorted(set(REQUIRED) - files.keys())
    if missing:
        raise EvidenceError('Missing donor files: ' + ', '.join(missing))
    data = files['INIT.SDL']
    previous_end = None
    groups = []
    for index, (first_pos, second_pos) in enumerate(SLOTS):
        first_at, first_length = bounded_pair(data, first_pos, SHORT_BYTES)
        second_at, second_length = bounded_pair(data, second_pos, LONG_BYTES)
        if first_at + first_length != second_at:
            raise EvidenceError(f'Disconnected pair {index}')
        if previous_end is not None and previous_end != first_at:
            raise EvidenceError(f'Disconnected sequence before pair {index}')
        previous_end = second_at + second_length
        short = data[first_at:first_at + first_length]
        long = data[second_at:previous_end]
        short_words, long_words = words_of(short), words_of(long)
        common = long_words[:7]
        if strict and len(set(common)) != 1:
            raise EvidenceError(f'Inconsistent first seven BE32 words in group {index}')
        sh_counts, lg_counts = Counter(short_words), Counter(long_words)
        raw_head = common[0]
        target = (raw_head & 0xFFFFFF) * 256
        exact_targets = sorted(name for name in ('CARTOTOP.SDL', 'BENELUX0.SDL')
                               if target + 4 <= len(files[name])
                               and files[name][target:target+4] == long[:4])
        groups.append({
            'group': index,
            'descriptors': [first_pos, second_pos],
            'first_start': first_at, 'first_length': first_length,
            'second_start': second_at, 'second_length': second_length,
            'first_sha256': sha256(short).hexdigest(),
            'second_sha256': sha256(long).hexdigest(),
            'first_be32_word_count': len(short_words),
            'second_be32_word_count': len(long_words),
            'first_nonzero_words': sum(bool(w) for w in short_words),
            'second_nonzero_words': sum(bool(w) for w in long_words),
            'second_distinct_nonzero_words': len(lg_counts) - (0 in lg_counts),
            'first_short_word_hex': f'0x{short_words[0]:08X}',
            'first_seven_long_words_identical': len(set(common)) == 1,
            'repeated_word_hex': f'0x{raw_head:08X}',
            'repeated_word_appears': lg_counts[raw_head],
            'low_24_times_256_hypothetical_offset': target,
            'bytes_at_that_offset_equal_word_in': exact_targets,
        })
    checks = {
        '9_contiguous_pairs': len(groups) == 9,
        'all_short_103_words': all(x['first_be32_word_count'] == 103 for x in groups),
        'all_long_1536_words': all(x['second_be32_word_count'] == 1536 for x in groups),
        '7_word_repetition_in_all_groups': all(x['first_seven_long_words_identical'] for x in groups),
        '8_later_groups_start_with_same_word': len(set(x['repeated_word_hex'] for x in groups[1:])) == 1,
        'zero_first_short_word': groups[0]['first_short_word_hex'] == '0x00000000',
        '8_nonfirst_short_words_start_0x68': all(x['first_short_word_hex'].startswith('0x68')
                                                  for x in groups[1:]),
        'last_span_to_eof_0x184': len(data) - previous_end == 0x184,
        'first_pool_word_is_at_least_one_external_file_header': bool(
            groups[0]['bytes_at_that_offset_equal_word_in']),
    }
    if strict and not all(checks.values()):
        raise EvidenceError('Group evidence mismatch: ' + ', '.join(
            key for key, value in checks.items() if not value))
    return {'init_size_bytes': len(data), 'init_sha256': sha256(data).hexdigest(),
            'groups': groups, 'checks': checks}


def analyze(donors: dict[str, dict[str, bytes]], strict: bool = True) -> dict:
    if len(donors) < 2:
        raise EvidenceError('At least two OEM source releases are needed')
    if any(not re.fullmatch('[A-Za-z0-9_-]{1,48}', name) for name in donors):
        raise EvidenceError('Invalid release label')
    versions = {key: analyze_release(donors[key], strict=strict) for key in sorted(donors)}
    comparisons = []
    for a, b in combinations(versions, 2):
        ga, gb = versions[a]['groups'], versions[b]['groups']
        comparisons.append({
            'left': a, 'right': b,
            'identical_first_groups': [i for i in range(9)
                                       if ga[i]['first_sha256'] == gb[i]['first_sha256']],
            'identical_second_groups': [i for i in range(9)
                                        if ga[i]['second_sha256'] == gb[i]['second_sha256']],
        })
    return {'schema': 'oem-init-pair-tables-iter009-v1',
            'proof': 'byte observations; field meanings unknown',
            'releases': versions, 'comparisons': comparisons,
            'limitations': [
                'Four-byte words are not automatically verified Parcel IDs or file pointers.',
                'A candidate 256-byte address is not proof of a parcel header at that offset.',
                'Repeated words and length patterns do not prove functional ownership.',
                'The OEM boot order and ucaParcelSizes have not been reconstructed.',
            ]}


def markdown(report: dict) -> str:
    lines = ['# Iter009: nine paired OEM INIT data ranges', '',
             'Observed byte patterns; no assigned OEM meanings.', '',
             '| Release | Group | Short offset | Long offset | First long BE32 |'
             ' Short nonzero | Long nonzero |',
             '|---|---:|---:|---:|---|---:|---:|']
    for name, entry in report['releases'].items():
        for g in entry['groups']:
            lines.append(f"| {name} | {g['group']} | 0x{g['first_start']:X} | "
                         f"0x{g['second_start']:X} | {g['repeated_word_hex']} | "
                         f"{g['first_nonzero_words']} | {g['second_nonzero_words']} |")
    for name, entry in report['releases'].items():
        lines.extend(['', f'## Checks: {name}', ''])
        lines.extend(f"- {key}: {'PASS' if val else 'FAIL'}"
                     for key, val in entry['checks'].items())
    lines += ['', '## Limits', ''] + ['- ' + q for q in report['limitations']]
    return '\n'.join(lines) + '\n'


def load(path: Path) -> dict[str, bytes]:
    result = {}
    if not path.is_dir():
        raise EvidenceError('OEM directory unavailable: ' + str(path))
    for name in REQUIRED:
        p = path / name
        if p.is_symlink() or not p.is_file():
            raise EvidenceError('Missing original regular OEM file: ' + str(p))
        result[name] = p.read_bytes()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', action='append', required=True, metavar='LABEL=DIR')
    parser.add_argument('--json', type=Path, required=True)
    parser.add_argument('--md', type=Path, required=True)
    args = parser.parse_args()
    try:
        versions = {}
        for item in args.release:
            if '=' not in item:
                raise EvidenceError('Expected LABEL=DIR')
            name, folder = item.split('=', 1)
            if name in versions:
                raise EvidenceError('Duplicate release label: ' + name)
            versions[name] = load(Path(folder))
        report = analyze(versions)
    except (EvidenceError, OSError) as exc:
        parser.exit(2, 'ERROR: ' + str(exc) + '\n')
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf8')
    args.md.write_text(markdown(report), encoding='utf8')
    print('Analyzed', len(report['releases']), 'original INIT files')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

# Iter008 — OEM INIT offset-length reconstruction

Scope: the seven original SDL files from each of the three user-supplied OEM DVDs (OLDER_1, OLDER_2, WE_06Q4). The generated 0.SDL is explicitly excluded. SDAL 1.7 does **not** by itself establish an OEM-specific INIT layout; the structure below is inferred from binary evidence.

## INIT header descriptor table

At INIT byte offsets 0x08..0x48, aligned BE32 pairs behave as (file byte offset, byte length). In all three OEM discs, the pairs point to valid byte ranges within their own INIT file.

| Pair location | OLDER_1 offset + length | OLDER_2 offset + length | WE_06Q4 offset + length |
|---:|---|---|---|
| 0x08 | 0x12000 + 0x94C | 0x12000 + 0x94C | 0x12000 + 0x94C |
| 0x10 | 0x258 + 0x5A8 | 0x258 + 0x5A8 | 0x258 + 0x5A8 |
| 0x18 | 0x800 + 0x1800 | 0x800 + 0x1800 | 0x800 + 0x1800 |
| 0x20 | 0x2000 + 0x4000 | 0x2000 + 0x4000 | 0x2000 + 0x4000 |
| 0x28 | 0x13800 + 0x6800 | 0x13800 + 0x7800 | 0x14000 + 0x7800 |
| 0x30 | 0x13660 + 0xF4 | 0x136D8 + 0x10C | 0x13D50 + 0x118 |
| 0x38 | 0x1294C + 0xD14 | 0x1294C + 0xD8C | 0x1294C + 0x1404 |
| 0x40 | 0x1A000 + 0x19C | 0x1B000 + 0x19C | 0x1B800 + 0x19C |
| 0x48 | 0x1A19C + 0x1800 | 0x1B19C + 0x1800 | 0x1B99C + 0x1800 |

The arithmetic relationships hold on the original binaries, not just synthetic fixtures:

- Pair 0x08 ends at 0x1294C, exactly where pair 0x38 begins; the referenced INIT range is byte-identical to the first 0x94C bytes of OEM MTOC.
- Pair 0x38 ends where pair 0x30 begins.
- Pair 0x10 ends at 0x800, the start of pair 0x18.
- Pair 0x18 ends at 0x2000, the start of pair 0x20.
- Pair 0x20 ends at 0x6000, the start of the first of three region-copy descriptors at INIT 0x240.
- Pair 0x28 ends exactly where pair 0x40 begins, despite differing offsets and lengths across discs.
- Pairs 0x40 and 0x48 are contiguous. Pair 0x48 ends exactly where the first additional descriptor at INIT 0x1C0 begins.

## Sixteen additional descriptors

Sixteen aligned (BE32 offset, BE32 length) records occur at INIT byte offsets 0x1C0, 0x1C8, ..., 0x238. Together with the two records at 0x40 and 0x48 they describe eighteen *contiguous* ranges.

All three OEM releases use lengths alternating 0x19C and 0x1800 nine times. The final range ends exactly 0x184 (388) bytes before file EOF in all three discs.

These observations support a repeatable descriptor/data grouping. They do **not** prove that these are voice files, index records, language tables, or any particular OEM subsystem.

## Additional shared-data relationships

INIT[0x800:0x2000] is exactly identical to INIT[0x2000:0x3800] in all three releases — a full 0x1800-byte internal duplication.

Three further descriptors at INIT 0x240, 0x248 and 0x250 refer to exact 0x4000-byte ranges at INIT 0x6000, 0xA000 and 0xE000. Each is byte-identical to one original BENELUX0 section, with the source ParcelID address preserved. Sources for the third section are 0x12000 on OLDER_1 and OLDER_2 and 0x16000 on WE_06Q4.

This is cross-file **byte provenance**. It is not a proven runtime pointer mechanism or an executable boot loader.

## Implementation

New read-only evidence tool: tools/oem_init_spans.py. New synthetic regression cases: tests/test_oem_init_spans.py. These fail closed on an invalid descriptor, disconnected range chain, mismatched catalog, changed duplicated region, or corrupted original-section copy. Existing map generation, ISO writing and firmware are unchanged.

Reproduce against the extracted originals:

    python3 tools/oem_init_spans.py --release OLDER_1=/path/to/old1 --release OLDER_2=/path/to/old2 --release WE_06Q4=/path/to/we --json verification/iter008-init.json --md verification/iter008-init.md

    python3 -m unittest discover -s tests -p 'test_oem_*.py' -v

GitHub CI uses synthetic fixtures, not copyrighted OEM source binaries. A full execution of the new tool on the original three discs remains an explicit separate acceptance test. The table values above were inspected directly in the original supplied files.

## Unresolved

The meaning of the BE32 word at INIT 0x04; descriptive names and semantics of these variable spans; actual Global Media Header / ucaParcelSizes; CARTOTOP reference resolution; hardware boot/ISO loading order. Do not implement a synthetic OEM writer before these are independently validated.

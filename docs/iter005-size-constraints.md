# Iter005 — provisional OEM parcel-size constraints

## Source and authoritative distinction

Scope: seven user-provided original WE_06Q4 SDL binaries (INIT,
MTOC, REGION, REGIONS, CARTOTOP, BENELUX0, FRANCE0) and the attached
**SDAL PSF 1.7, version 0.4** document.

The specification, section **1.4.0.2 Parcel ID**, describes the
six-bit size index and the 24-bit file offset in units of
`2^usBlockSize`. Sections **1.2.4.5** and **2.1.1.3 Global Media
Header Structure** describe `ucaParcelSizes[]` and `usBlockSize`.
The latter defines `MAX_PARCEL_SIZES = 128` even though the described
ParcelID_t layout allocates only **six** bits for size index (64
addressable values). The implementation does **not** silently resolve
this apparent specification inconsistency.

For the OEM header candidates, 256-byte addressing is independently
corroborated by the 24-bit file address positions. The **start-to-next
candidate or EOF gaps** yield the following provisional indexed length
constraints:

| Index | Inferred units of 256 bytes | Gap bytes | Observations | Sources |
|---:|---:|---:|---:|---|
| 0 | 94 | 24064 | 1 | CARTOTOP |
| 42 | 50 | 12800 | 1 | CARTOTOP |
| 45 | 157 | 40192 | 1 | CARTOTOP |
| 46 | 128 | 32768 | 1 | CARTOTOP |
| 52 | 60 | 15360 | 1 | CARTOTOP |
| 56 | 64 | 16384 | 40 | BENELUX0 (19), FRANCE0 (19), CARTOTOP (2) |
| 59 | 71 | 18176 | 1 | CARTOTOP |

**Total: 46 headers** = 19 regional + 19 regional + **8 CARTOTOP**.

This corrects Iter004's reported count of **42**. Its four omitted
CARTOTOP starts were 0x17E00, 0x21B00, 0x25700, and 0x28900.
The previous strict scanner asserted only four CARTOTOP candidates;
Iter005 changes that to eight, with a synthetic donor regression.

### Reconstructed candidate layout in CARTOTOP

| Start | PID | Size index | End of observed interval | Units |
|---:|---|---:|---:|---:|
| 0x2000 | 0x38000020 | 56 | 0x6000 | 64 |
| 0x6000 | 0x38000060 | 56 | 0xA000 | 64 |
| 0xA000 | 0x2E0000A0 | 46 | 0x12000 | 128 |
| 0x12000 | 0x00000120 | 0 | 0x17E00 | 94 |
| 0x17E00 | 0x2D00017E | 45 | 0x21B00 | 157 |
| 0x21B00 | 0x3400021B | 52 | 0x25700 | 60 |
| 0x25700 | 0x2A000257 | 42 | 0x28900 | 50 |
| 0x28900 | 0x3B000289 | 59 | 0x2D000 (EOF) | 71 |

Exact candidate boundary values were checked directly against the
user-supplied OEM bytes. Observed interval *does not necessarily equal
parcel size*: a header may be missed, and after the last header there
may be file tail padding.

## Table search: negative evidence, not proof of absence

A literal contiguous byte-array scan for all seven size-index/
interval-value pairs in all seven submitted files returned **zero
matches**. This establishes only that this simple plaintext layout was
not observed in this sample. It neither locates nor disproves the real
`ucaParcelSizes[]`, which may be in `0.SDL` or another global file,
may be encoded differently, or may be stored under OEM-specific rules.
The previously submitted `0.SDL` is not currently available as a
mountable binary input for repeat verification.

## Reproduce

```sh
python3 tools/oem_size_constraints.py /path/to/extracted-oem \
  --json verification/oem-size-constraints.json \
  --md verification/oem-size-constraints.md --require-we06q4
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

This tool is **read-only**. The code refuses conflicting observed
lengths for one index, non-sector-aligned spans, lengths that cannot fit
in a uint8 candidate, and strict-donor profile deviations. No default
size table is generated, and no unknown field is set to zero. Until a
real table is decoded and cross-validated, the production writer must
not use these provisional sizes.

## Next bounded step

Read the *original* 12-KiB `0.SDL` (if it belongs to the same OEM
release), locate and parse the actual `GlbMediaHeader_t` and verify
`usBlockSize`, `ucParcelSizeCount` and the table. If `0.SDL` is not
part of the donor's true directory layout, first establish the
OEM-specific source of global media metadata from INIT and references.
Do not invent a `0.SDL` or claim OEM boot compatibility.

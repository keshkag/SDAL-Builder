# Iter006 — first older DVD compared with WE_06Q4

## Sources and scope

This is evidence from the **seven original SDL files uploaded by the user
from each of two physical OEM releases**. This document records the
actual observed values; code and synthetic regression tests are stored in
tools/oem_cross_version.py and tests/test_oem_cross_version.py.

User labels are used: WE_06Q4 for the previously inspected release and
OLDER_1 for the first older DVD. There is no attempt to infer an exact
calendar release year from these bytes.

Generated 0.SDL is **excluded** from the OEM evidentiary corpus. No
proprietary donor binary is checked into GitHub.

## Byte-identical and different files

| File | WE_06Q4 bytes | OLDER_1 bytes | OLDER_1 SHA-256 |
|---|---:|---:|---|
| INIT.SDL | 172032 | 165888 | cb4046b705addccd9bb574b2720cee042151933d4aa39a044c717ae35df67d95 |
| MTOC.SDL | 4096 | 4096 | e8105af91e0b7ecfbdf992dd2b3fc0f37384bf064f55ae978a53bce24db0a941 |
| REGION.SDL | 4096 | 4096 | de49e6283b9df3b3f1f8b7edb8d5b54738f81b6b7e9988ec75a209838d87c227 |
| REGIONS.SDL | 4096 | 4096 | de49e6283b9df3b3f1f8b7edb8d5b54738f81b6b7e9988ec75a209838d87c227 |
| CARTOTOP.SDL | 184320 | 159744 | ea59eda6f3bfd97de5add476be5c5261cc696732767fb46e7c3d53a7b9cb1d92 |
| BENELUX0.SDL | 319488 | 270336 | 15c389a5352b6e6b9afea449888f92b79b09d3f3cb72b1d4635a1d6e90b9be4c |
| FRANCE0.SDL | 319488 | 270336 | bf947e77070be4d8939b16dfe0d25babeb532e4f01972fb9850cdbafe31bd389 |

**MTOC.SDL is byte-identical between the releases** (all 4096 bytes).
Within each release, REGION.SDL is byte-identical to REGIONS.SDL,
although those two files differ between releases.

In both INIT files, the first big-endian 32-bit word equals actual INIT
length (0x2A000 and 0x28800, respectively). Two further words remain
unchanged:

- BE32 at 0x08: 0x12000, location of the MTOC-like catalog in INIT.
- BE32 at 0x0C: 0x94C, matching the identical first 2380 bytes of MTOC.
- MTOC[0:0x94C] equals INIT[0x12000:0x1294C] in **both** OEM releases.
  The rest of MTOC is **not** a verified copy of the corresponding INIT
  range and must not be treated as one.

This is a verified invariant for these two releases; it cannot be assumed
universal for all OEM SDAL discs without additional evidence.

## Regional section organization changes

Both BENELUX0 and FRANCE0 have an observed 8192-byte preamble followed
by consistently self-addressing 16384-byte header-candidate intervals.
The older release has **16** such intervals in each file; WE_06Q4 has
**19**. The repeated ID size index at each start is 56 in both releases.

| Evidence | OLDER_1 | WE_06Q4 |
|---|---:|---:|
| Region *0 file size | 270336 | 319488 |
| Region *0 candidate count per file | 16 | 19 |
| CARTOTOP header-candidate count | 9 | 8 |

The candidate offsets and size-index fields observed in CARTOTOP differ:

| OLDER_1 offset | Size index | Gap to next candidate/EOF (256 B units) |
|---:|---:|---:|
| 0x2000 | 56 | 64 |
| 0x6000 | 36 | 44 |
| 0x8C00 | 48 | 133 |
| 0x11100 | 0 | 117 |
| 0x18600 | 10 | 18 |
| 0x19800 | 38 | 121 |
| 0x21100 | 43 | 51 |
| 0x24400 | 15 | 23 |
| 0x25B00 | 12 | 21 |

| WE_06Q4 offset | Size index | Gap to next candidate/EOF (256 B units) |
|---:|---:|---:|
| 0x2000 | 56 | 64 |
| 0x6000 | 56 | 64 |
| 0xA000 | 46 | 128 |
| 0x12000 | 0 | 94 |
| 0x17E00 | 45 | 157 |
| 0x21B00 | 52 | 60 |
| 0x25700 | 42 | 50 |
| 0x28900 | 59 | 71 |

**Crucial qualification:** index 0 corresponds to a gap of 117 units
in OLDER_1 and 94 in WE_06Q4. This could reflect version-specific
size tables, skipped candidates, or padding. None of these observations
constitutes direct identification of ucaParcelSizes[] or a proof that
the gap equals the actual serialized parcel length.

## Reused sections are relocated (corrected by Iter007)

**Correction after a second independent read of the original OEM bytes:**
the third matching section in OLDER_1 was incorrectly reported as only
12 KiB in an earlier version of this document. In fact all **16 KiB
are byte-for-byte identical**, as they are in WE_06Q4.

- Both releases: INIT 0x6000 ↔ BENELUX0 0x2000, 16 KiB exact.
- Both releases: INIT 0xA000 ↔ BENELUX0 0x6000, 16 KiB exact.
- OLDER_1: INIT 0xE000 ↔ BENELUX0 0x12000, 16 KiB exact.
- WE_06Q4: INIT 0xE000 ↔ BENELUX0 0x16000, 16 KiB exact.

The corresponding source-address field is preserved within the copied
INIT sections. This remains evidence of byte reuse, not proof of
runtime pointers or a boot-loader algorithm.

See `docs/iter007-three-release-evidence.md` for full three-release
verification, including the independently supplied OLDER_2 disc.

## Validation, reproducibility and limits

To run the read-only comparator, place the seven *original* names of
each release into separate folders (no additional preprocessing):

    python3 tools/oem_cross_version.py \
      --release OLDER_1=/path/to/older \
      --release WE_06Q4=/path/to/we06q4 \
      --json verification/iter006-cross-version.json \
      --md verification/iter006-cross-version.md

The repository's GitHub CI executes synthetic regressions without
publishing proprietary OEM binaries. A **full exact-corpus execution of
the new script** requires local access to the original bytes; that
verification is separate from synthetic CI.

The next older donor DVD would allow a three-way comparison of
candidate size-index layouts and media catalogue stability, and could
distinguish release-local coincidences from reproducible rules.

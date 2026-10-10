# Iter003 — OEM 16-KiB region boundaries and ParcelID candidates

## Source authority

Original user-supplied binary files: `INIT.SDL` (172032 bytes),
`BENELUX0.SDL` and `FRANCE0.SDL` (319488 bytes each), and
`CARTOTOP.SDL` (184320 bytes).
This release adds `tools/oem_parcel_boundaries.py` and offline tests.
It makes **no changes** to OSM generation, map packaging, or on-vehicle code.

## Direct byte observations

1. Both `*0.SDL` files comprise exactly 8192 bytes followed by
   **19 x 16384-byte sections** (8192 + 19×16384 = 319488).
   Candidate header starts occur at 0x2000, 0x6000, 0xA000, ...
   0x4A000 in both files.
2. The first four bytes at those section starts are:
   `38 00 00 20`, `38 00 00 60`, `38 00 00 A0`, ...
   `38 00 04 A0` (big-endian parcel-ID candidates).
3. Taking the low 24 bits of each word as an address in
   **256-byte units**, as described by SDAL 1.7 ParcelID_t, yields the
   exact section start byte offset in both regional files. This is a
   cross-file-supported inference for this donor, **not** a confirmation
   of global block-size configuration in every release.
4. For the 19 recurring regional candidates the subsequent bytes
   decode under the SDAL 1.7 20-byte `PclHdr_t` hypothesis as parcel
   type **19** and region **0**. The spec lists type 19 for
   media header/reference/metadata/icon/voice/compression-tree content.
   Further compression/size semantics have **not** been validated.
5. Three entire 16384-byte sections of `INIT.SDL` match BENELUX0
   byte-for-byte. Critically, the *stored* ID field in INIT resolves
   to the **BENELUX0 source offset**, not the copied location:

   | INIT byte offset | BENELUX0 byte offset | Bytes | Match |
   |---:|---:|---:|---|
   | 0x6000 | 0x2000 | 16384 | exact |
   | 0xA000 | 0x6000 | 16384 | exact |
   | 0xE000 | 0x16000 | 16384 | exact |

   This is evidence of relocated common binary sections. It is **not
   yet evidence of runtime pointers into BENELUX0** or of an executable
   boot loader.
6. In CARTOTOP at 0x2000 a superficially related candidate has type
   `0xFF`, not a documented SDAL 1.7 type. It is reported as
   *unclassified* rather than forced into type 19 or 1.

## Correction to previous iteration's response

The actual Iter002 generated block-provenance report confirmed
**17**, not 18, complete same-offset nonuniform 4096-byte blocks
between BENELUX0 and FRANCE0: 13 blocks beginning 0x1A000 and
4 blocks beginning 0x4A000. A prior conversational summary incorrectly
stated 18. The report is authoritative for this comparison.

## Validation and limitations

The new tool checks candidate headers as **hypotheses** against
the SDAL 1.7 `PclHdr_t` and `ParcelID_t` layouts. Its strict mode
rejects missing 16-KiB regional starts, broken inferred address fields
and missing exact 16-KiB INIT-to-BENELUX copy matches. It also includes
seven synthetic regression cases, which should be run by CI.

Run on the original extracted OEM files, without modifying them:

```sh
python3 tools/oem_parcel_boundaries.py /path/to/OEM \
  --json verification/iter003-pcl-candidates.json \
  --md verification/iter003-pcl-candidates.md
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

Do not assume each 16-KiB section is a valid complete parcel until
its length table and compression rules can be interpreted. No content
synthesis or OEM hardware compatibility is claimed.

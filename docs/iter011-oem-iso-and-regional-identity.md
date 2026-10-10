# Iter011 — OEM WE_06Q4 ISO mastering and regional identity

## Original inputs

The user supplied binary samples cut from the original `WE_06Q4.iso`:

- `OEM_ISO_first_1MiB.bin`, exactly 1,048,576 bytes, SHA-256 `2677c49f623688ba30d7382f099abd2b8b3cdad03f85f7b31d261e0810383c0e`
- `OEM_ISO_last_1MiB.bin`, exactly 1,048,576 bytes, SHA-256 `0f46f53465f7949db7f90b368110d93cb337f5b97e54ef457811204394c971c8`

Both were directly parsed with a local byte-level verifier, independently of GitHub's donor-free CI. Also inspected the uploaded genuine `SWIAUS0.SDL` (319,488 bytes), `SWIAUS1.SDL.zip` (one archive member, `SWIAUS1.SDL`, 364,488,704 bytes), earlier `DENSWE0.SDL` (319,488 bytes), and `BENELUX0/1.SDL`. The original binary files are not committed.

## The original is a hybrid ISO9660 / Joliet / UDF DVD

The first 1MiB proves the following volume descriptors and recognition data:

| Byte position / LBA | Observed structure |
|---|---|
| LBA 16 (0x8000) | Primary Volume Descriptor, ISO9660, CD001 |
| LBA 17 | Supplementary Volume Descriptor, Joliet, escape `%/E` |
| LBA 18 | ISO9660 Volume Descriptor Set Terminator |
| LBA 19 | `BEA01` |
| LBA 20 | `NSR02` |
| LBA 21 | `TEA01` |
| LBA 32–37 | UDF descriptors tagged 1, 4, 5, 6, 7, 8 |
| LBA 256 | UDF Anchor Volume Descriptor Pointer (tag 2) |
| LBA 3,224,080 | Terminal UDF anchor (tag 2), found in last sector of supplied final 1MiB |

Both UDF anchors have correct tag checksum and tag location. The root ISO9660 directory is at **LBA 261**, 4,096 bytes; Joliet root is at **LBA 263**, 4,096 bytes. These independent root directories describe exactly the same 42 SDL files with matching start LBAs and lengths.

**Volume ID:** `WE_06Q4`. **Logical block size:** 2,048 bytes. **Volume extent:** 3,224,081 sectors, **6,602,917,888 bytes**.

The terminal UDF anchor occupies the last sector. The last large SDL data extent ends immediately before it: `ITALY1.SDL` starts at LBA 2,779,400, has size 910,704,640 bytes, and its last data sector ends at sector 3,224,079.

The first/last samples confirm the UDF recognition sequence and anchor descriptors; they do *not* prove the entire internal UDF file tree or hardware firmware behavior without the full original ISO.

## Physical placement differs substantially from filename ordering

The original ISO9660 root lists filenames alphabetically, but their actual data extents are not alphabetical:

| File | OEM start sector (LBA) | OEM bytes |
|---|---:|---:|
| FRANCE0.SDL | 318 | 319,488 |
| MTOC.SDL | 942 | 4,096 |
| REGION.SDL | 944 | 4,096 |
| REGIONS.SDL | 946 | 4,096 |
| BENELUX0.SDL | 10,482 | 319,488 |
| CARTOTOP.SDL | 10,638 | 184,320 |
| KDTREE.SDL | 10,728 | 2,662,400 |
| INIT.SDL | 12,028 | 172,032 |
| UK1.SDL | 12,112 | 673,697,792 |
| GERMANY1.SDL | 341,066 | 1,132,957,696 |
| DENSWE1.SDL | 894,268 | 912,990,208 |
| IBERIA0.SDL | 1,340,064 | 319,488 |
| SWIAUS0.SDL | 1,340,220 | 319,488 |
| DENSWE0.SDL | 1,340,376 | 319,488 |
| IBERIA1.SDL | 1,352,076 | 962,105,344 |
| FRANCE1.SDL | 1,821,854 | 1,245,650,944 |
| BENELUX1.SDL | 2,430,082 | 350,914,560 |
| SWIAUS1.SDL | 2,601,427 | 364,488,704 |
| ITALY1.SDL | 2,779,400 | 910,704,640 |

All 42 extents are within the volume and do not overlap. The standalone verifier captures *every* original directory entry and the full observed physical ordering in its JSON output, not just this representative table.

Importantly, physical extent order is **an observed OEM layout**. Whether Denso firmware requires exact placement remains an open test; it must not be asserted as a universal requirement without further evidence.

## DENSWE is Denmark/Sweden, not generic density or Western Europe

The original `DENSWE0.SDL` includes explicit uppercase place labels `DANMARK` and `SVERIGE`, accompanied by regional administrative category names `KOMMUNE`, `KOMMUN` and `MAAKUNTA`. The same original ISO has matching `DENSWE0.SDL` and the **912,990,208-byte `DENSWE1.SDL`**. Thus `DEN`+`SWE` identifies the Denmark/Sweden regional map grouping, not a numeric density overlay. The *whole DVD* is called Western Europe.

The genuine `SWIAUS0.SDL` shows `SCHWEIZ`, `STERREICH`, `LIECHTENSTEIN`, and `ITALIA`, supporting Switzerland/Austria regional grouping with adjacent geography. Its partner `SWIAUS1.SDL` (confirmed by matching ZIP entry size and OEM ISO directory size) is a 364,488,704-byte real map file.

Both `SWIAUS1` and `BENELUX1` have the same PclHdr_t-shaped identifiers at the sampled offsets: `0x49000020` at byte 0x2000 (type 24, region 1) and `0x480000C2` at byte 0xC200 (type 255, region 1). These matching bytes establish a repeatable index/header pattern across two real regional map payloads, but not payload equivalence or device compatibility.

## Producer-side incompatibilities requiring a root-cause fix

`build.sh` is the canonical existing single-command OSM download → transform → SDL generation → ISO pipeline and **must remain functional and complete**.

From the current repo's `src/sdal_builder/iso.py`, `pycdlib.PyCdlib().new(vol_ident=datetime.now().strftime(...), interchange_level=3)` does **not configure** Joliet or UDF, and uses a timestamp-generated volume label. It does not reproduce this confirmed hybrid filesystem fingerprint.

From the current `main.py` generator, `DENS...0.SDL` is constructed as a short count-based parcel and does not represent the genuine `DENSWE0.SDL` regional index. This is not solved by simply renaming the file; the underlying structure and ownership differ.

The existing `encoder.py` also composes ParcelID external/redundancy bits at positions 27/28 rather than the 31/30 bits required by SDAL 1.7 and observed in real `*1.SDL` headers. A production fix requires address-unit and reference-graph reconstruction, not a blind bit patch.

## Changes in this iteration

- New **read-only** `tools/oem_iso_layout.py`: verifies ISO9660/Joliet directory parity, big-/little-endian mirror fields, actual physical sector placement, source map-size contracts, the UDF volume recognition sequence, descriptor records and both UDF anchors. Emits deterministic JSON and Markdown.
- New independent, binary-generated synthetic tests including intentionally corrupted volume labels, UDF checksums, directory parity and inconsistent extents. Tests do not include proprietary donor binary bytes.
- **No production writer or one-command workflow removed, replaced or modified.** This is a bounded evidence slice before choosing an ISO mastering backend that can actually generate ISO9660/Joliet/UDF.

## Reproduce on original image samples

```sh
python3 tools/oem_iso_layout.py \
  --first OEM_ISO_first_1MiB.bin \
  --last OEM_ISO_last_1MiB.bin \
  --json verification/oem-iso-evidence.json \
  --md verification/oem-iso-evidence.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

Next: verify the generated Builder ISO against this independent filesystem fingerprint; select and test a production-grade hybrid mastering path, preserve the single `build.sh` workflow, and validate map parcel pointers on actual `BENELUX1.SDL` / `SWIAUS1.SDL`.

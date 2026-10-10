# Iter012 — OEM cartographic content before ISO mastering

## Engineering decision

The user explicitly prioritized **actual SDAL data correctness and Denso loader expectations** over image mastering. This iteration therefore does **not** change `build.sh`, `iso.py`, the end-to-end OSM download/ETL/publishing chain, or disc-level UDF/Joliet descriptors.

Instead, it implements a reusable parser and byte-preserving low-level serializer for **authentic Global KD-tree Index parcels (type 255)** and surgically corrects a proven SDAL ParcelID bitfield error in the existing encoder.

## Source authority

Original user-provided, unmodified files:

- `WE_06Q4/BENELUX1.SDL` — 350,914,560 bytes
- `WE_06Q4/SWIAUS1.SDL` — 364,488,704 bytes
- `WE_06Q4/INIT.SDL` — 172,032 bytes
- `SDAL_spec.pdf` — SDAL PSF 1.7, section 1.2.4.3 (`PclHdr_t`), section 1.3.0.6 (global KD-tree parcelization and `IDxPclHdr_t`), section 1.4.0.2 (`ParcelID_t` flags and offsets)

These OEM bytes and source documentation were examined directly. Proprietary SDL file payloads have **not** been committed.

## Two types of authentic map parcels at the beginning of each *1.SDL

| Physical position | Parcel ID | Observed type | Size index | Observed next-header spacing |
|---:|---|---:|---:|---:|
| `0x2000` | `0x49000020` | 24 — Map Header | 9 | `0x5100` (20,736 B) |
| `0x7100` | `0x49000071` | 24 — Map Header | 9 | `0x5100` (20,736 B) |
| `0xC200` | `0x480000C2` | 255 — Global KD-tree Index | 8 | `0x5000` (20,480 B) |

All three physical offsets and Parcel IDs occur at the same relative locations in both authentic *1.SDL files. The addresses are consistent with a **256-byte** address unit (`low24bits × 256`), including the SDAL redundancy bit at position **30**. The exact original `ucaParcelSizes[]` has still **not** been located; these parcel lengths are grounded by adjacent authentic headers and independently bounded index arrays.

## IDxPclHdr_t and root-offset table are now confirmed

At `0xC200`, after the 20-byte `PclHdr_t`, the specification defines:

- `usNumRoots` — 2 bytes, big-endian
- `usExtensionOffset` — 2 bytes, big-endian
- An array of `usNumRoots` offsets, each 16-bit big-endian, measured **relative to the start of the index parcel**

The first array entry is **exactly** `24 + (2 × usNumRoots)`, which locates the first tree immediately beyond the root-offset array:

| Measurement | BENELUX1 | SWIAUS1 |
|---|---:|---:|
| `usNumRoots` of index at `0xC200` | 899 | 923 |
| Index extension offset | 0 | 0 |
| Calculated first tree offset | 1822 (`0x71E`) | 1870 (`0x74E`) |
| Actual first U16 root offset | 1822 (`0x71E`) | 1870 (`0x74E`) |
| Final U16 root offset | 20,468 | 20,470 |

All root offsets in these source arrays are strictly increasing and remain within the 20,480-byte extent. Their exact content is release/region-dependent.

## The complete observed sequence of type-255 index parcels

**BENELUX1: ten**, **SWIAUS1: eleven**. The index parcels are spaced by `0x5000` bytes, starting at `0xC200`, and their root counts have been independently extracted from the original byte streams.

| Index parcel offset | BENELUX1 roots | SWIAUS1 roots |
|---:|---:|---:|
| `0xC200` | 899 | 923 |
| `0x11200` | 217 | 168 |
| `0x16200` | 6 | 21 |
| `0x1B200` | 37 | 9 |
| `0x20200` | 706 | 3 |
| `0x25200` | 21 | 6 |
| `0x2A200` | 301 | 619 |
| `0x2F200` | 199 | 246 |
| `0x34200` | 178 | 128 |
| `0x39200` | 39 | 140 |
| `0x3E200` | — | 142 |
| **Total** | **2,603** | **2,405** |

All **21** original index parcels passed the directly executed original-byte checks for coherent root counts, exact first-data boundary, strictly increasing U16 root offsets, and in-bounds last root offset. These are authentic structural observations. **The internal KD-tree node format has not yet been decoded**, so no claim of routing compatibility or complete map serialization follows.

## Source modules

- `src/sdal_builder/oem_index.py`: precise `ParcelID_t` composition; `PclHdr_t` field decoding; `IDxPclHdr_t` parser, root-offset validation, exact reconstruction from offset-delimited tree byte spans; writer that computes U16 root positions for caller-supplied trees.
- `tools/oem_kd_index_evidence.py`: read-only forensic reporter. Validates two map-header positions, walks the type-255 index sequence, attempts parse/rebuild of each index, optionally checks eight repeated `INIT.SDL` index markers against the first authentic map index.
- `src/sdal_builder/encoder.py`: fixes the existing `pid == 0` branch's wrong flag locations (**27/28 → 31/30**), and rejects out-of-range 24-bit reference/address and six-bit size-index values. Existing already-composed nonzero Parcel IDs are deliberately preserved, avoiding a breaking change to current callers.
- Independent tests: `tests/test_oem_kd_index.py`, `tests/test_oem_kd_index_evidence.py`, `tests/test_oem_production_pid.py`; included in the cumulative forensic CI suite.

**Important distinction:** the reusable index writer reconstructs `IDxPclHdr_t` and offset arrays, but expects a caller to provide valid tree-node data. It does **not** generate the tree from OSM or guess unknown tree-node encodings. The existing `encode_bytes` implementation has additional OEM differences beyond the two corrected flag positions; this iteration makes **no unsupported claim** that all production output is now compliant.

## Reproduce the exact-source acceptance check

With original files already uploaded in this conversation:

```sh
python3 tools/oem_kd_index_evidence.py \
  --init /path/to/WE_06Q4/INIT.SDL \
  --map BENELUX1=/path/to/WE_06Q4/BENELUX1.SDL \
  --map SWIAUS1=/path/to/WE_06Q4/SWIAUS1.SDL \
  --json verification/iter012-kd-index.json \
  --md verification/iter012-kd-index.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

The original byte measurements above were independently checked. The **committed reporter's end-to-end original-data execution remains pending**, because the local container stopped accepting commands after the exploratory binary validation; GitHub Actions CI independently verifies the committed code on synthetic data. Do not conflate those two evidence channels.

## Next source-first step

Recover the **tree NODE record format** and its child routing within the verified root blobs; reconstruct actual cartographic parcel type-1 and cross-reference type-2 record ownership, references and compression. Validate node decoding and linked references on BENELUX1 and SWIAUS1 before integrating the writer into the existing one-command OSM→SDL→ISO workflow.

**ISO mastering remains postponed** until generated parcels and reference graph pass their own integrity checks.

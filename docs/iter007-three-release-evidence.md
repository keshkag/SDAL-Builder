# Iter007 — three-release OEM comparison (verified byte evidence)

## Input provenance and limits

Compared the **21 original binary files** uploaded from three physical OEM DVD releases, seven each:

- `OLDER_1` — first older DVD
- `OLDER_2` — second older DVD (newly supplied)
- `WE_06Q4` — previously analysed later DVD

Labels are supplied by the investigator; exact OEM production years are **not** inferred. All comparisons here are based on the actual bytes available in the analysis runtime, not a generated `0.SDL`. Original copyrighted OEM bytes are not committed.

## Sizes

| File | OLDER_1 bytes | OLDER_2 bytes | WE_06Q4 bytes |
|---|---:|---:|---:|
| INIT.SDL | 165888 | 169984 | 172032 |
| MTOC.SDL | 4096 | 4096 | 4096 |
| REGION.SDL | 4096 | 4096 | 4096 |
| REGIONS.SDL | 4096 | 4096 | 4096 |
| CARTOTOP.SDL | 159744 | 225280 | 184320 |
| BENELUX0.SDL | 270336 | 303104 | 319488 |
| FRANCE0.SDL | 270336 | 303104 | 319488 |

## Invariants across all three releases

1. **MTOC.SDL is exactly byte-identical** across all three releases (4096/4096 bytes, SHA-256 `e8105af91e0b7ecfbdf992dd2b3fc0f37384bf064f55ae978a53bce24db0a941`).
2. Within each release, `REGION.SDL` is byte-identical to `REGIONS.SDL`.
3. BE32 at `INIT+0x0` matches the actual INIT file size in all three.
4. BE32 values at `INIT+0x8` and `INIT+0xC` are respectively `0x12000` and `0x94C` in all three. For each release, `INIT[0x12000:0x1294C]` matches `MTOC[0:0x94C]` **byte-for-byte**.
5. The first 0x50 bytes of INIT also have invariant BE32 *values* at offsets:
   - `0x10=0x258`, `0x14=0x5A8`, `0x18=0x800`, `0x1C=0x1800`
   - `0x20=0x2000`, `0x24=0x4000`, `0x38=0x1294C`
   - `0x44=0x19C`, `0x4C=0x1800`
   Their **semantics have not been established**, and do not become universal constants based only on three samples.

## Structural changes

| Observed PclHdr_t candidates | OLDER_1 | OLDER_2 | WE_06Q4 |
|---|---:|---:|---:|
| BENELUX0 | 16 | 18 | 19 |
| FRANCE0 | 16 | 18 | 19 |
| CARTOTOP | 9 | 8 | 8 |

All regional `*0.SDL` files consist of an observed 8192-byte prefix followed by the indicated count of 16384-byte aligned sections. The low 24 bits of the observed parcel ID interpreted in 256-byte units match those candidate addresses. **A matched PclHdr_t-shaped record does not by itself validate its entire parcel or establish ucaParcelSizes[].**

## Very narrow REGION delta

`REGION.SDL` for OLDER_2 and WE_06Q4 differs at exactly **three bytes**:

| File byte offset | OLDER_2 | WE_06Q4 |
|---:|---:|---:|
| `0x05` | `0x03` | `0x02` |
| `0x07` | `0x1F` | `0x11` |
| `0x0B` | `0x05` | `0x06` |

These are observed changing bytes, not assigned firmware- or release-field semantics. OLDER_1's REGION content differs substantially and begins with readable `WESTERN EUROPE`, unlike the other two samples' `EU` label. This may represent an OEM layout revision, but is not proof of one.

## Corrected cross-file provenance — **three full 16KiB copied regions in each release**

Every original donor set has the **following exact 16384-byte matches**:

| INIT destination | OLDER_1 BENELUX0 source | OLDER_2 BENELUX0 source | WE_06Q4 BENELUX0 source |
|---:|---:|---:|---:|
| `0x6000` | `0x2000` | `0x2000` | `0x2000` |
| `0xA000` | `0x6000` | `0x6000` | `0x6000` |
| `0xE000` | `0x12000` | `0x12000` | `0x16000` |

All nine aligned comparisons were independently checked using full 16384-byte equality. **Zero differing byte positions** exist in any of the nine ranges. The embedded parcel-address field at the copied range's start still matches the region *source* position, not the INIT destination.

This corrects Iter006's inaccurate claim that the third OLDER_1 match extended only 12KiB; that claim arose from an overly restrictive/synthetic comparison model. The previous report must not be treated as OEM truth on that point.

## Candidate size-index observations are release-local

The gap after a `CARTOTOP` candidate with size index `0` is **117** units of 256 bytes in OLDER_1, **120** in OLDER_2, and **94** in WE_06Q4. This is evidence that naive next-boundary-to-size rules cannot be universally applied; it **does not prove** differing true `ucaParcelSizes[]` entries for index 0, because boundaries may include undetected records or padding.

## Verification

Use the existing multi-release forensic reader on three extracted OEM directories:

```sh
python3 tools/oem_cross_version.py \
  --release OLDER_1=/path/to/old1 \
  --release OLDER_2=/path/to/old2 \
  --release WE_06Q4=/path/to/we \
  --json verification/three-release.json \
  --md verification/three-release.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

The repository's GitHub Actions suite tests synthetic inputs; the three real OEM datasets are **not present in GitHub CI**. Actual supplied donor bytes were independently compared in the analysis environment for the observations above.

## Next bounded step

Decode the authoritative address/size tables (not inferred gaps) and the relationship between INIT's invariant header words and the catalogue records. Then validate a reader against all three releases before any production serializer or synthesized boot data is introduced.

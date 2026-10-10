# Iter014 — OEM KD-root coverage + production hybrid ISO bridge

## What the user approved

Content correctness and consistency with the genuine Denso SDAL DVD remain the primary development objective. The user **did not request postponement of ISO mastering**: if sufficient evidence exists, implement it now without distracting from the content work. Existing `build.sh` continues to orchestrate OSM download, transform, SDL generation and ISO production. The ISO stage remains the last part of that unchanged overall workflow.

## Real OEM source evidence — 5,008 KD-tree roots

These counts were obtained by reading every 16-bit root table of every Global KD-tree Index parcel in the two genuine WE_06Q4 map files, `BENELUX1.SDL` and `SWIAUS1.SDL`, using their actual 0x5000-byte indexed spans:

| Original map | KD index parcels | Total roots | Exact 2-byte `0x1000` root | Other roots |
|---|---:|---:|---:|---:|
| BENELUX1.SDL | 10 | 2,603 | **1,581** | 1,022 |
| SWIAUS1.SDL | 11 | 2,405 | **1,571** | 834 |
| **Total** | **21** | **5,008** | **3,152** | **1,856** |

A root slice that is **exactly** `10 00` is a two-byte control record with no child-offset or parcel-descriptor flags. The classification is limited to its source-observed structure. No claim about its map coverage or navigation semantics is made.

The **first one** of the 1,856 complex roots in each file was already fully decoded and graph-validated in Iter013 (2,495 BENELUX1 nodes and 2,507 SWIAUS1 nodes, with 3,188 verified external references). The **remaining 1,854 complex roots are not yet fully decoded**; blanket linear parsing was previously shown to produce invalid child offsets for some other roots. These are intentionally called unresolved, not silently reclassified as leaves.

New read-only `tools/oem_kd_root_coverage.py` records all roots, the exact `0x1000` counts, SHA-256 of unclassified root spans, counts by index parcel and the already-proven first-root graph. It does not guess alternate tree encodings or overwrite any original data. Five synthetic regressions detect false leaf classification and source corruption.

## Hybrid ISO mastering — actual production implementation

The existing `src/sdal_builder/iso.py` module has been replaced with a filesystem mastering implementation that preserves its public `build_iso(sdl_files,out_iso)` entrypoint. The one-command `build.sh` OSM→SDL→ISO orchestration is preserved. It now checks for the required UDF mastering executable **before** starting expensive OSM download and ETL, and fails with explicit install instructions instead of failing at the very end.

Actual observed OEM DVD mastering fingerprint:

- ISO9660 Primary Volume Descriptor at sector 16, Joliet Supplementary Volume Descriptor at 17, terminator at 18.
- UDF `BEA01/NSR02/TEA01` recognition sequence at sectors 19–21, and UDF anchors including sector 256 and final volume sector.
- 2048-byte logical sectors, identical physical SDL file LBA/length contracts between ISO9660 and Joliet roots.
- Original OEM label `WE_06Q4`, and exact ISO9660/Joliet physical root-file parity.
- For the original WE_06Q4 image, physical file order was *not* alphabetic. The implementation **does not assert that preserving this historical order is necessary** without firmware evidence.

The new writer uses `genisoimage -udf -J -iso-level 3` on Linux, or equivalent `mkisofs` with UDF capability, and uses `-graft-points` to include existing SDL files **without copying gigabytes of files into a staging directory**. Filename and volume-ID inputs are strictly validated. Volume ID derives deterministically from ISO output filename, and can be overridden through `SDAL_VOLUME_ID`.

**Acceptance gates for every generated ISO:**

1. Mastering exits successfully.
2. PVD, Joliet SVD, descriptor terminator and 2048-byte sector geometry validate.
3. All ISO9660/Joliet catalogue **canonical names**, logical file sizes and physical extents match. Note: `genisoimage` strips the `;1` suffix in Joliet, while retaining it in ISO9660; the OEM source ISO had a different Joliet name representation. This is a known mastering difference that may or may not matter to Denso.
4. No duplicate, missing or unexpected SDL files and no overlapping/out-of-volume SDL extents.
5. UDF VRS and both AVDP anchors are present and consistent.
6. Every byte of each mastered SDL extent has the **same SHA-256 digest** as its original source SDL.
7. Source file lengths and timestamps have not changed while mastering.
8. The resulting ISO is atomically published only after all checks pass. Otherwise temporary ISO is deleted and the build fails with a clear diagnostic. **No pure-ISO9660 fallback**.

These are real-mastering properties, not mere unit-test mocks. GitHub Actions installs `genisoimage`, builds actual synthetic SDL files into an ISO, verifies the filesystem and source payload hashes, and mutates one byte in the mastered image to confirm that SHA-256 comparison fails. A separate macOS GitHub Actions job **passed**, exercising `cdrtools`/`mkisofs` hybrid generation, filesystem checks, byte parity, and deliberate output corruption rejection.

### Deployment dependencies

- Linux (Debian/Ubuntu): `sudo apt-get install genisoimage`
- macOS with Homebrew: `brew install cdrtools` (provides `mkisofs`)
- `build.sh` remains one command; the selected mastering binary must exist on the host. If absent, production now refuses to emit a misleading pure ISO9660 image instead of silently degrading.
- Optional `SDAL_VOLUME_ID=WE_06Q4 ./build.sh ...` configures the label; this is not a claim that every generated disc should impersonate the original release.

`genisoimage` and `cdrtools` are external tools, not distributed binary blobs. No original proprietary map files are distributed.

## Verified versus outstanding

**Verified in this iteration:**
- Original binary root counting: 5,008 roots across 21 type-255 OEM index parcels; 3,152 exact `0x1000` two-byte leaf structures.
- Real Linux `genisoimage` ISO9660/Joliet/UDF mastering on small synthetic SDL sets, including byte-parity validation and corruption rejection.
- Cumulative Python CI tests, including real Linux genisoimage and macOS cdrtools/mkisofs integration on GitHub-hosted runners, passed.

**Still outstanding:**
- Complete node graphs of the 1,854 complex roots other than the two first-root graphs proven in Iter013.
- Actual spatial parcel descriptors, routing geometry, compression format, dictionary semantics and OEM SDAL writer parity.
- Full 6.6-GB end-to-end SDAL Builder production ISO data test (no compatible 6.6-GB generated dataset exists yet).
- UDF *file-tree* parity vs original OEM: the source evidence contained only first/last 1MiB, not the entire original image metadata and directory graph.
- Exact physical file ordering, Joliet filename version suffix representation, and real Denso head-unit acceptance.

This iteration therefore **delivers a working and verified hybrid ISO mastering subsystem**, not a claim of byte-identical OEM ISO metadata or complete navigation compatibility. The next priority remains proving contents of complex roots and the cartographic parcel formats before claiming a bootable map DVD.

## Reproduction

```sh
# OEM read-only coverage:
python3 tools/oem_kd_root_coverage.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --json verification/iter014-kd-coverage.json \
  --md verification/iter014-kd-coverage.md

# Existing one-command build is still the entrypoint:
# prerequisite: genisoimage or mkisofs binary with UDF support
./build.sh europe/cyprus

# Offline test suite:
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

No unsupported new parcel content was substituted into production generation.

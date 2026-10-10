# Iter023 — GlbMediaHeader size authority and deterministic SDAL regional allocator

## Product objective

Produce genuine **OSM PBF → SDAL 1.7 map contents → checked hybrid ISO → Denso navigation disc** using the existing one-command build.sh. The objective is an encoder, not a standalone OEM decoder. This bounded iteration removes individually chosen ParcelID addresses and physical byte capacities from the proposed new type-0/type-1/Global-KD assembly path.

The legacy main.py output is intentionally not switched to the new implementation because complete OEM routing/cartographic payloads, globally authoritative metadata and Denso acceptance are not yet available. The functioning ISO mastering module and build.sh interface remain unchanged.

## Specification reviewed

User-supplied *PSF Specification for SDAL Format 1.7*, Version 0.4:

- **§1.2.4.5:** parcel size granularity belongs to GlbMediaHeader_t, not to each parcel's uncoordinated encoder. Parcels must not overlap; individual data records must stay inside a physical parcel. Uncompressed parcel offsets generally have a 32K bound. The Global KD index is one of the fixed-size-per-type families.
- **§1.4.0.2:** ParcelID_t bit31 denotes external-to-region indirection, bit30 denotes redundancy, bits29–24 provide a **six-bit** size-table index, bits23–0 denote the physical sector offset. External and redundant behavior needs its own authoritative tables.
- **§2.1.1.3, printed pp. 2-5–2-7:** GlbMediaHeader_t is held in the first **2048-byte Global Media Header parcel**, with 128 Uchar entries in ucaParcelSizes and separate ucParcelSizeCount, ucNextParcelLen, usBlockSize, usBlockNbrBits and usBlockSizeBits. **Each ucaParcelSizes entry is a number of logical sectors, not a byte length.** usBlockSize is the exponent giving sector size 2^usBlockSize bytes; documented practical exponents are 8..11.
- The source header definition reserves **128 table cells**, although the **direct ParcelID exposes only 64 different size indexes**. The source has a stale/conflicting MAX_PARCEL_SIZES comment about four size bits. This implementation preserves the 128-cell physical header while enforcing the six-bit 0..63 direct-handle limit. It does not invent an undocumented way to reference the other 64 entries.

### Exact offsets within GlbMediaHeader_t

Calculated by laying out the standard C structure from the specification, with no invented padding:

| Name | Byte position | Width |
|---|---:|---:|
| ucaParcelSizes | 1122 | 128 |
| ucParcelSizeCount | 1250 | 1 |
| ucNextParcelLen | 1251 | 1 |
| usBlockSize (exponent) | 1252 | 2 |
| usBlockNbrBits | 1254 | 2 |
| usBlockSizeBits | 1256 | 2 |

The full 2048-byte header also includes numerous other metadata, locale, category, compressed-data and normalized-attribute fields. **Iter023 edits only the above documented fields** inside a caller-supplied 2048-byte header image; it does not manufacture those unrelated fields.

### Original-corpus qualification

The uploaded original WE_06Q4 **INIT.SDL** (172,032 bytes) has been inspected; its bytes at offset 1250 do not form a valid ucParcelSizeCount under the GlbMediaHeader_t layout. Its name is NOT evidence that its first 2048 bytes are the Global Media Header described by §2.1.1.3. This iteration **does not mislabel INIT.SDL as a genuine source GlbMediaHeader_t** and does not claim to have extracted the OEM parcel-size table from it. The observed index parcel geometry (0x5000 bytes and 256-byte direct addressing, type255 index8) remains empirical data from the original BENELUX1/SWIAUS1 index parcels, not a substitute for source-global table readback.

The generated regression table explicitly declares **index8=80 sectors and index24=16 sectors with sector exponent 8** as a synthetic, caller-owned contract. Index8 is consistent with the observed index extent, but the chosen index24 entry is a test fixture: neither entry is represented here as an independently extracted complete OEM global-media table.

## New production code: src/sdal_builder/oem_media_allocator.py

**MediaSizeTable** stores one immutable media-wide sector exponent and up to 128 nonzero Uchar sector counts. It computes byte capacity as sector count × (1 << usBlockSize), restricts directly selectable indexes to 0..63 and finds the smallest declared capacity sufficient for a payload, without silent truncation. Its size_authority() method converts the same single source of truth into the existing Iter022 SizeAuthority adapter; a physical Cartographic/Route producer cannot use a conflicting capacity when called through this adapter.

**MediaSizeFields** plus parse_media_size_fields and write_media_size_fields read/write **only** the verified GlbMediaHeader fields at their specified physical positions. A readback immediately checks that writing preserved the complete size record. Bytes outside these intervals remain exactly unchanged. The input header is required to have exactly 2048 bytes; the function does NOT synthesize the rest of the Global Media Header.

**ParcelRequest** declares stable content-owner key, physical parcel type, minimum encoded payload length, optional externally proven fixed size index and fixed offset, and redundancy semantics. The current production writer accepts only types **0 (Routing), 1 (Cartographic) and 255 (Global KD)** because only those bounded payload families have implementation and tests. Unsupported parcel families are rejected, not written with synthetic placeholder bytes. The known index profile requires redundant PID, exactly 0x5000 bytes, 256-byte logical sectors and size index 8.

**allocate_region** sorts requests canonically by stable owner key and reserves any fixed physical positions **before** allocating dynamic parcels. It uses sector-aligned deterministic first-fit placement across the remaining free extents, checks a caller-owned prefix occupied by regional metadata, rejects fixed/dynamic collisions, refuses overcapacity requests and 24-bit address overflow, and composes every direct ParcelID from that single plan. All resulting placements have a single source-authoritative start, end, length, size index and ParcelID.

**RegionLayout.render() / verify()** publish and independently reopen the physical binary file; every emitted PclHdr must match the planned direct PID, type and region. Type-0/1 payloads are passed through the Iter022 independent internal block/position/route-graph verifier. The type-255 index goes through the OEM-root-table decoder. Publishing a header whose physical records have broken offsets, even with a valid PID, is refused.

Region prefix bytes are **supplied by the caller**. Zero prefix bytes in synthetic regression fixtures are solely part of the tests and are NOT a production replacement for real regional metadata. Deterministic gap fill is not asserted to be an original OEM packing convention.

## Independently generated binary integration

The new tests create a complete synthetic **physical regional file** using the actual production modules and the one allocation plan:

1. Define an explicit synthetic media-size table (sector exponent 8, index24 16 sectors for the two bounded spatial parcels and index8 80 sectors for Global KD).
2. Reserve 0x2000 bytes for caller-owned test metadata and physically reserve the fixed OEM-profile Global KD index at 0xC200.
3. Let allocate_region choose **different** dynamic physical addresses for Cartographic and Routing. No test manually constructs their final ParcelIDs.
4. Compile actual type-1 Full Polyline + Position arrays at the allocated Cartographic PID with authoritative byte capacity.
5. Compile actual type-0 Node + Segment arrays and reciprocal edges at the allocated Routing PID.
6. Compile the global KD from an independently calculated OSM n/32 partition and the **actual allocated** parcel IDs, after the real target payload bytes exist in the candidate physical image.
7. Publish through RegionLayout.render and independently re-read the complete file: all three PclHdrs, sizes, direct PIDs, type0/1 internal blocks, physical KD roots and typed references.

This is a genuine **encoder → binary regional file → independent decode** path for a supported subset, not merely mock headers. A separate generated 2048-byte media field fixture exercises GlbMediaHeader size-table extraction, direct-address resolution, source read-only auditing and corruption rejection.

### Tests

- tests/test_oem_media_allocator.py: exact byte offsets and preservation of unrelated global header fields; 128 physical vs 64 addressable slots; sector exponent; smallest-fit allocation; fixed-first reservation; byte-identical reproducibility under reversed request order; no overlaps; wrong size indexes, missing payloads, forged PID and tampered Cartographic record table.
- tests/test_oem_media_size_evidence.py: independent read-only source auditor exercised on generated physical global media/region files, including wrong source PclHdr and invalid table count.
- tools/oem_media_size_evidence.py: a tool to apply the **exact published parser** to a separately supplied genuine GlbMediaHeader_t and full regional SDL file. It reports only media metadata, physical offsets and selected parcel IDs, never raw OEM payload bytes. That source audit cannot be claimed on WE_06Q4 without first locating a genuine Global Media File.

The cumulative GitHub Actions suite retains previous forensic regressions plus real Linux and macOS hybrid ISO mastering. Success of this suite is **not** equivalent to on-device Denso compatibility.

## What remains

The global size table and physical regional allocator are now defined within the new encoder components, but full OSM-to-Denso compatibility still requires:

1. Actually serialize all OTHER GlbMediaHeader_t fields, the Global Media Index and the genuine regional metadata into the reserved prefix, using published and checked ownership of every reference.
2. Implement OSM road clipping and cross-boundary ghost nodes, turn restrictions, shape points, normalized attribute tables, display/polygon/text/POI arrays, local/global KD structures and the remaining required interparcel references.
3. Authenticate actual full original Global Media File samples (as distinct from INIT.SDL) and reconcile any OEM-specific size table or region metadata variants without undocumented offset workarounds.
4. Resolve SZIP or prove and validate a complete uncompressed typed-parcel production profile.
5. Replace the older main.py OSM output *only after* a fully consistent generated dataset can pass end-to-end inspection, and finally test real Denso display/search/routing.

No original proprietary binaries committed. The existing build.sh and hybrid ISO mastering remain unchanged.

## Reproduction

    python3 -m unittest discover -s tests -p 'test_oem_*.py' -v

    python3 tools/oem_media_size_evidence.py --media /path/to/actual-global-media-file \
       --region /path/to/actual-region-file --parcel-id 0x18000020 \
       --json verification/iter023-original-size-evidence.json

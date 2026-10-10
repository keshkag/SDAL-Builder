# Iter020 — actual Cartographic/Route fixed headers, variable records and block encoding

## Product purpose

This iteration moves the original `build.sh` OSM → SDAL 1.7 → hybrid ISO product toward real **Cartographic (type 1)** and **Route Calculation (type 0)** payload records. OEM decoding is used to validate the writer, not as an end-user replacement for the encoder.

The code adds actual production serializers, not a new competing command-line pipeline. They are not connected to `main.py` until all mandatory types, cross-references, geometry, routing connectivity and compression can be written coherently. The previously validated hybrid ISO mastering is unchanged.

## Authoritative SDAL Specification consulted

Source: user-supplied **PSF Specification for SDAL Format 1.7, Version 0.4**.

| SDAL section | Requirement implemented |
|---|---|
| §1.4.0.1, pp. 1-16–1-17 | Canonical big-endian Type 1 and Type 4 variable-length unsigned integers |
| §1.4.0.2, pp. 1-20–1-21 | BlkDesc, BlkDesc1, BlkDesc2, BlkDesc3 and BlkDesc4 layouts and exact field order |
| §3.2.2.1, pp. 3-10–3-12 | Distinct RoutingParcelHeader0_t and RoutingParcelHeader1_t fixed fields |
| §3.2.2.6 and §3.2.3.3, pp. 3-13–3-20 | Variable-length block length tables and bottom-layer Route Node basic record encoding |
| §3.5.2.3, pp. 3-47–3-48 | CartoParcelHeader_t, entity start fields, polygon/line/point/position/text/attribute descriptors |
| §3.5.4.3, pp. 3-53 onward | Cartographic Point variable-length entity type, lat/long, subtype and text record offset |
| §3.5.3.4 and §3.5.4 | (N+1) Type 1 record block lengths and first-record offset |

### The fixed-header layouts

The following footprints are used for the examined WE_06Q4 OEM profile and the specification-defined routing variants:

| Structure | Byte length | Typed descriptor variants |
|---|---:|---|
| SptlPclHdr_t common prefix | 92 | PclHdr, XrfPclHdr, three DBRects, KD fields |
| RoutingParcelHeader0_t | **192** | BlkDesc1 ×2, BlkDesc2 ×2, BlkDesc ×1, BlkDesc3 ×2, BlkDesc4 ×3, maxima/reserved |
| RoutingParcelHeader1_t | **164** | BlkDesc2 ×3, BlkDesc ×1, BlkDesc3 ×2, BlkDesc4 ×2, maxima |
| CartoParcelHeader_t (examined WE_06Q4 profile) | **184** | 2 compact initial IDs, BlkDesc ×3, BlkDesc3 ×3, BlkDesc4 ×5, maxima + reserved/zero alignment |

**Source discrepancy and decision:** the generic `EntityID_t` typedef in §1.4.0.2 is `Ulong_t` (32 bits), but the sampled original **uncompressed** WE_06Q4 Cartographic fixed headers have a coherent descriptor sequence only when the two first-ID fields occupy **two bytes each**. The following block descriptors then contain plausible counts and actual offsets. Two final 0x00 alignment bytes produce the 184-byte observed fixed-header footprint. Treat this as a **release-observed compact wire profile**, NOT a universal reinterpretation of `EntityID_t` or proof that all SDAL OEM versions use this layout. The generated writer fails on IDs larger than 65535 in this profile. Expanding other profiles requires independent original-source evidence.

### Sampled authentic OEM measurements (independent exploratory scan)

Using genuine BENELUX1.SDL and SWIAUS1.SDL plus the independent KD Descriptor reference inventory from Iter018:

| Sample cohort | BENELUX1 | SWIAUS1 |
|---|---:|---:|
| Uncompressed type-0 Routing fixed-header candidates | 27 | 13 |
| Uncompressed type-1 Cartographic fixed-header candidates | 10 | 3 |
| **Total uncompressed sample candidates** | **37** | **16** |

All were previously sampled directly from original physical PID addresses, had matching PclHdr types and no declared parcel-body compression. Representative original type-1 metadata include first descriptor arrays interpretable at byte 96 (after two 16-bit initial IDs) rather than at byte 98 or 100. The new exact-version evidence tool is separately provided to reproduce **all fields** and assert byte-exact read/write parity on the authentic files.

**Important verification boundary:** the numbers above describe an independent original-byte sample investigation. Because the local execution environment became unavailable after extraction and exploratory inspection, this document does **not** claim that the newly committed `oem_typed_parcel_evidence.py` was fully rerun against both copyrighted full-size maps. GitHub Actions tests the new implementation on generated fixtures; the exact original-corpus replay remains a separate acceptance gate.

## Production code — new files

### src/sdal_builder/oem_typed_headers.py

Contains the exact standard `BlkDesc` family layouts and reversible typed fixed-header decoders and writers for:

- Cartographic type 1, WE_06Q4 compact-first-ID wire profile
- Route Calculation type 0 at layer 0
- Route Calculation type 0 at routing layers 1–4

They preserve the *actual* ordered block descriptors and maxima arrays. The writer requires type/layer consistency with the already available `oem_spatial_header.py` 92-byte spatial prefix; rejects invalid field widths, incorrect field ordering, trailing/pad anomalies and compressed bodies. This encodes the **fixed prefix of a real parcel**, not all necessary cartography/routing record arrays.

### src/sdal_builder/oem_typed_records.py

Real, deliberately bounded source-to-wire record subset:

- `encode_type1/decode_type1`: 1, 2, 3 or 4 bytes; exact transition values 239/240, 4079/4080 and 65519/65520; maximal legal 1,114,095.
- `encode_type4/decode_type4`: 2 or 3 bytes; exact transition 61439/61440.
- **Printed spec discrepancy:** §1.4.0.1 states Type 4 upper bound **1,110,095**, but the actual 20-bit three-byte encoding with +61,440 can represent at most **1,110,015**. The latter is the executable wire limit; the extra 80 values cannot be serialized without violating the described prefix rules. The writer rejects them rather than truncating or wrapping.
- `encode_carto_point_basic/decode_carto_point_basic`: fully encoded subset of actual Cartographic Point records, with entity type, Type 4 coordinates, no chain or special attributes/population, and a bounded 15-bit text offset. Other variants fail closed.
- `encode_route_node_basic/decode_route_node_basic`: fully encoded subset of actual **regular bottom-layer Routing Node records**: zeroed unsupported option flags, Type 4 coordinates, byte arm count, Type 1 per-arm segment-table indexes, and canonical pairwise name-change bits. Supernodes, cost arrays, Z-level, long haul and named junction records are not silently stripped: unsupported flags fail.

Entity coordinates are converted to parcel-relative NTU deltas and shifted according to the specified scale. The bounded writer requires exact scale representation, refusing accidental coordinate loss.

### src/sdal_builder/oem_record_blocks.py

Implements the real **Type 1 variable-length (N+1) record-length table** common to Cartographic/Routing data blocks. The first value gives the offset from block start to the first record; following values give individual record lengths. The encoder resolves the self-dependent first-offset field correctly even at the 239/240 length-prefix transition. The decoder checks canonical sizes, exact interval coverage, no trailing bytes and 16-bit block capacity.

This is the payload **block** writer, not yet the entire parent parcel's block placement and descriptor address planner. That placement must coordinate additional mandatory record arrays and physical parcel size information.

### tools/oem_typed_parcel_evidence.py

Read-only evidence reader that takes a full original regional SDL file and the independent typed PID reference JSON from Iter018. It traverses genuine sampled type-0/1 PclHdr locations, reports compressed target counts without attempting to decode ciphertext, and for every uncompressed target decodes and re-encodes the entire typed fixed header, requiring exact source-byte parity. Output is metadata-only: source PID, type/layer, descriptor metrics, full-header SHA-256 and results, never OEM payload bytes.

## Verification

The cumulative source-free regression suite includes newly introduced tests under:

- `tests/test_oem_typed_headers.py`: 192/164/184-byte structure lengths, genuine descriptor family field counts, profile restrictions, wrong type/layer, alignment and full codec parity.
- `tests/test_oem_typed_records.py`: byte-exact Type1/Type4 limits and transformations; hundreds of seeded integer roundtrips; basic Route Node and Cartographic Point positive/negative cases.
- `tests/test_oem_record_blocks.py`: actual generated record arrays with first-record offset and record lengths, truncation, wrong offset, overflow and deterministic byte parity.
- `tests/test_oem_typed_parcel_evidence.py`: synthetic **physical SDL bytes** containing placed Routing and Cartographic typed headers, plus deliberate target-PID and compression corruption.

Prior GitHub CI jobs continue to exercise Linux/macOS hybrid ISO creation, source-content SHA-256 matching and corruption detection. Synthetic regression success demonstrates code correctness within the tested profiles, not original DVD hardware compatibility.

## Next OSM → SDAL conversion dependency

A valid complete regional SDL still requires real segment records, shape points, full/short polylines and polygons, additional point/POI variant fields, compression (SZIP), block offset array placement for all record types, routing-condition/date-time arrays, entity-ID and cross-reference allocation, and correct ucaParcelSizes authority.

We must implement and validate those structures in bounded slices against **uncompressed genuine OEM records** wherever possible. Only after both Cartographic and Routing parcels can be internally completed and all global KD and parcel links validate should the new code replace the outdated portions of main.py. Publishing a half-populated type-0 or type-1 parcel as if it were navigable would repeat the original failure mode.

### Reproduction

```sh
python3 tools/oem_typed_parcel_evidence.py \
  --map /path/to/BENELUX1.SDL \
  --reference-report /path/to/BENELUX1-descriptors.json \
  --json verification/iter020-benelux-typed.json

python3 tools/oem_typed_parcel_evidence.py \
  --map /path/to/SWIAUS1.SDL \
  --reference-report /path/to/SWIAUS1-descriptors.json \
  --json verification/iter020-swiaus-typed.json

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

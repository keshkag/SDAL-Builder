# Iter022 — physical type-0/type-1 SDAL parcel assembly

## Goal and acceptance boundary

The actual product is a one-command **OSM PBF → genuine SDAL 1.7 map contents → verified ISO → Denso-readable navigation DVD**. The original-map decoder is only an evidence instrument for the encoder.

This release implements an actual physical producer and verifier for bounded Cartographic/Route Calculation record families, not merely independent record codecs. It deliberately does not substitute incomplete new parcels for the existing main.py output, and it does not alter the proven Linux/macOS hybrid ISO stage or the canonical build.sh interface.

Authority: user-supplied **PSF Specification for SDAL Format 1.7, Version 0.4**. Relevant sections:

- **§1.4.0.2 (printed pp. 1-17–1-21):** ParcelID_t direct file-sector addressing, bit31 external-region, bit30 redundancy, six-bit ucaParcelSizes index, PclHdr_t, BlkDesc_t, BlkDesc1_t and BlkDesc3_t.
- **§2.1:** GlbMediaHeader_t supplies usBlockSize and ucaParcelSizes. Neither can be guessed from individual OSM records.
- **§3.2.2.1 and §3.2.2.6 (pp. 3-10–3-14):** RoutingParcelHeader0_t and node/segment block-offset tables; (2^K)+1 variable record-length values.
- **§3.5.2.3, §3.5.3.2–3.5.3.3 and §3.5.6:** CartoParcelHeader_t, lineDesc, positionDesc, Full Polyline Position Offsets and signed 3-byte Position records.

**Profile qualification:** The Iter020 typed Cartographic fixed-header writer has a compact, observational WE_06Q4 profile with two 16-bit initial entity fields. The general SDAL EntityID_t typedef remains Ulong_t. Do not treat the observed compact footprint as universal for every SDAL release.

## Delivered production code

### src/sdal_builder/oem_parcel_assembly.py

**SizeAuthority** validates an externally supplied, ucaParcelSizes-resolved byte-size table, actual logical sector size, the direct 24-bit ParcelID offset, and physical parcel capacity. It refuses missing indexes, external/redundant handles, misaligned capacities and mismatching start addresses. **It does not yet independently read and authenticate a complete generated GlbMediaHeader_t**, which is a separate integration requirement.

**assemble_cartographic_roads** takes genuine FullPolyline models and each polyline's complete sequence of CartographicPosition vertices, then:

1. Assigns contiguous physical PositionOffset indices and validates position counts.
2. Encodes signed 3-byte positions and exact Full Polyline records at the declared NTU scale, without dropping vertices.
3. Allocates a real U16 block-offset table and canonical Type-1 (N+1) record-length blocks.
4. Writes truthful lineDesc offsets, count, 2^K records/block, maximum record/block byte lengths and usDataOffset.
5. Writes a real positionDesc (record count, three-byte maximum, physical data offset, reserved alignment) and the maximum positions per polyline in the header.
6. Rejects undeclared text records and local normalized attributes if their associated arrays are not present.

**assemble_routing_regular** takes the supported RoutingNodeBasic and RoutingSegmentRegular records plus independently allocated minimum Node/Segment entity IDs, then:

1. Checks node-to-segment and segment-to-node reciprocity, including nonduplicate adjacency.
2. Writes two real BlkDesc1_t block-offset tables and packed node/segment record arrays.
3. Sets independent minimum entity IDs, record counts, physical offsets, block and record maxima, and the actual maximum segments per node.
4. Independently decodes every physical route node and segment; unsupported conditions, ghosts, long-haul, shape, aggregation and local attributes are not silently thrown away.

**verify_bounded_parcel** is an independent physical-byte acceptance path. It decodes the just-produced PclHdr_t and typed fixed header, checks ParcelID and externally supplied size authority, resolves each real 16-bit block pointer and length table from the physical bytes, rejects overlapped fixed headers, offset tables, block extents and Position arrays, and reconstructs all polyline vertices and node/segment links. It checks descriptor maxima, reference counts, declared NTU bounding rectangles and unsupported auxiliary fields. Corrupted physical blocks are rejected.

A produced PhysicalParcel has the explicit status **typed-record-arrays-only**. This means real bytes and checked links in the supported profile, **not** a complete navigable parcel or proven OEM-compatible release.

Unused physical allocation is zero-filled deterministically. This is NOT a claim that all OEM parcels use zero fill; the previously measured FF fill belongs specifically to Global KD type-255 index parcels.

## Generated regional-map integration

New test **tests/test_oem_generated_region_links.py** creates an actual synthetic regional SDL binary containing:

- A complete 4,096-byte physically allocated type-1 record-bearing parcel at byte address 0x2000.
- A similarly allocated type-0 route parcel at 0x4000, with real Node and Segment records.
- A genuine type-255 Global KD index at 0xC200, computed from the existing OSM spatial plan and referencing both actual physical parcel headers, not mocked objects.

The tests re-read and validate the binary produced on each step. They deliberately corrupt a target Parcel ID and an interior block-offset table and ensure generated output is rejected. This demonstrates the **encoder → actual physical SDL bytes → independent decoder** path.

Additional **tests/test_oem_parcel_assembly.py** check record grouping, source geometry, position indexes, minimum routing IDs, forged length tables, wrong PID physical addresses, unresolved size indexes, overcapacity, overlap of descriptor intervals, understated maxima, deterministic input and unsupported auxiliary records. The retained regression suite also masters genuine hybrid ISO images under Linux and macOS.

## Verification provenance

All new implementation tests operate on generated binary fixtures, not historical copyrighted map content. The original corpus observation of seven genuine BENELUX uncompressed polylines in Iter021 remains independent supporting evidence. **The new assembler has not reproduced entire original type-0 or type-1 parcels byte-for-byte**, and such equality must not be inferred from the regression-suite PASS.

The exact generated GlbMediaHeader_t sector-size and parcel-size table is not yet implemented as a single source of truth. The supplied SizeAuthority therefore has an explicit dependency on a separately authenticated allocator. This is a real product blocker, not a migration or compatibility path.

## Remaining producer work before main.py cutover

1. Complete the physical global-media/region parcel allocation and ucaParcelSizes authority, ensuring no overlapping physical parcels and correct parcel-size codes.
2. Implement full OSM geometry clipping with interparcel ghost nodes, true segment/node ID ownership, turn restrictions and conditions, route shape points and attributes.
3. Add real auxiliary Cartographic arrays: points, polygons, text/name, normalized attributes, local/internal spatial KD and required segment↔polyline cross-references.
4. Verify SZIP compression or a fully supported, source-proven uncompressed profile; generate complete metadata and index/catalog relationships.
5. Use the completed writer **inside the existing build.sh pipeline**, validate every generated pointer and check actual Denso map loading, display and route computation.

**Iter022 materially advances binary parcel construction but does not claim a complete OEM-compatible SDAL or a tested head-unit DVD.**

## Run tests

Run the cumulative source-free suite from repository root:

    python3 -m unittest discover -s tests -p 'test_oem_*.py' -v

No original copyrighted donor data is committed.

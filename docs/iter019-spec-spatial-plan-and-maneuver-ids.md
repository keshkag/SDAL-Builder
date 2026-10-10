# Iter019 — SDAL 1.7 specification, OSM spatial partitioning and Maneuver Parcel IDs

## Product objective

The sole product goal is a working end-to-end OSM → SDAL 1.7 encoder that creates real cartographic/routing parcels, correctly indexed regional/global files, and finally an ISO loadable by Denso. Reverse engineering is a validation means, not the product. The existing one-command build.sh pipeline and Iter014 hybrid ISO mastering are preserved. The new source-to-wire modules are not yet connected into a finished type-0/type-1 payload generator.

## Primary source — uploaded SDAL PSF 1.7 v0.4 PDF

The relevant clauses have been checked directly:

- **§1.4.0.2 (printed pages 1-17–1-18):** ParcelID_t bit31 means external region indirection, bit30 means redundant copy information, bits29–24 index the parcel-size table, and low24 specify the direct start offset in logical sectors. External and redundant mechanisms rely on explicit metadata tables, not implied address corrections.
- **§2.1 (2-6–2-7):** GlbMediaHeader_t defines logical block size and ucaParcelSizes. Logical sector sizes can differ by medium; the supplied WE_06Q4 regional files empirically use 256 bytes. An OEM size index is not an arbitrary record-length field.
- **§3.1–3.1.1 (3-3–3-9):** Spatial parcelization is a common refinement across types/layers. Two parcel rectangles may be disjoint, equal or fully nested; partial overlap is forbidden. The Global KD tree encodes cuts at n/32 boundaries, typed Parcel Descriptors and routing segment/node ID minima.
- **§1.4.0.2 (1-19–1-22):** SptlPclHdr_t is 92 bytes: 20-byte common header, 12-byte XrfPclHdr continuation, three 16-byte signed32 NTU DBRect rectangles and 12 bytes of spatial-KD/scale/layer fields.
- **§3.2 and §3.5:** Route Calculation type 0 and Cartographic type 1 require DIFFERENT type-specific headers and real node/segment or polygon/polyline/point/text/attribute records after the fixed spatial prefix. The common header alone does not constitute a valid map parcel.
- **§1.2.4.3 and compression clauses:** A compressed spatial parcel must first be decoded through its declared compression mode. Do not interpret a compressed payload's first bytes as an uncompressed SptlPclHdr_t.

## Ten SWIAUS1 type-3 Maneuver address anomalies

All ten previous OEM exceptions belong to KD index parcel 3 / root 1, type 3, layer 0. We inspected all ten original IDs and their actual physical header candidates across the entire original 364,488,704-byte SWIAUS1.SDL source:

| Finding | Count |
|---|---:|
| External-to-region flag bit31 set | 0 |
| Redundancy flag bit30 set | 0 |
| Matching type-3 region-1 header at nominal address | 0 |
| Matching type-3 region-1 header exactly 0x5000 bytes BEFORE nominal address | 6 |
| Of those six, also matching type-3 region-1 header 0x1000 bytes AFTER nominal address | 2 |
| No aligned matching type-3 region-1 header anywhere in file | 4 |

A direct ParcelID with both flag bits clear must be interpreted by the documented low24 sector offset. Nothing in the checked sections authorizes applying an arbitrary -0x5000 correction. Six alternate source-header occurrences constitute evidence of a localized original-file placement/identifier anomaly; the ultimate root cause is **not yet proven**. Four IDs have no matching type-3/region-1 header in the original. No unsupported compatibility workaround is introduced.

The new read-only tools/oem_maneuver_pid_spec_audit.py enumerates the exact IDs, both flag bits, nominal physical addresses, candidate exact-header locations and deltas. It consumes the prior original-evidence JSON. Synthetic tests ensure the tool does not silently accept a shifted physical header as a valid direct reference. It emits NO copied OEM payload.

The numbers above were independently measured directly on genuine OEM files during this iteration. The exact published tool running against those full files remains a separate release acceptance step: GitHub CI intentionally has only synthetic data.

## Production-side implementation

**src/sdal_builder/osm_spatial_plan.py**: builds a deterministic plan from typed/layered, integer-NTU OSM geometry footprints. Feature bounds use the existing deg_to_ntu conversion (one NTU = 1/100000 degree, defined in the PDF). A KD split must be an exactly representable n/32 geographic cut and partition complete feature envelopes into disjoint cells. The planner rejects duplicate feature keys, out-of-region features, too-small cells, and roads/lines spanning every possible cut: such source geometry needs actual clipping, not a centroid shortcut.

The compiler consumes those planned rectangles AND **already physically serialized type-0/type-1/etc. parcels**. It requires a readable target SDL and checks every direct Parcel ID against its real PclHdr PID, declared spatial type and region. It rejects reused Parcel IDs across disjoint cells, missing type/layer coverage, unresolved external indirection and routing splits without authentic 24-bit segment/node minima. It then uses the Iter018 production KDNode and type-255 index writer to output a real 0x5000-byte index parcel, with child offsets verified by decode/re-encode. No phantom parcel references are permitted. A single-leaf topology lacking an independently proven OEM representation is rejected rather than invented.

**src/sdal_builder/oem_spatial_header.py**: exact reversible 92-byte SptlPclHdr_t common fixed-header writer/reader for types 0..6, with PclHdr, XrfPclHdr, three DBRect structs and trailing KD/scale/layer fields. This module explicitly refuses to treat compressed payload bytes as uncompressed header fields. It is only the common header prefix; the actual type-0/type-1 blocks, spatial geometry and SZIP are separate work.

**tools/oem_spatial_header_evidence.py**: read-only OEM sample verifier which checks PclHdr PID/type/region and performs exact source-byte 92-byte spatial prefix roundtrip **only on uncompressed samples**. Compressed source parcels are recorded as needing a proper decoder. Original binaries are never committed.

## Regression acceptance

New source-free tests cover 1/32 cuts, two-layer KD split compilation, physical target parity on ACTUALLY CREATED synthetic SDL files, duplicate/missing and wrong type PIDs, routing entity minima, nonclippable OSM geometry, deterministic planning, sign-accurate coordinate conversion, exact 92-byte prefix codec, preserved Xref data, explicit compression refusal and the anomalous Maneuver direct-reference behavior. Existing Linux/macOS hybrid ISO integration tests are retained.

**Do not call Iter019 a complete OSM-to-SDAL renderer.** It implements a bounded, spec-constrained partition/index generation stage and common spatial header codec; the current main.py still writes older POI-point and cartography/routing structures. A silent partial cutover would result in internally inconsistent files, so it is intentionally not done.

## Next production dependencies

1. Clip OpenStreetMap roads at the actual n/32 region/parcel boundaries; preserve segment identity, endpoint topology and geometry.
2. Implement genuine type-0 Route Calculation and type-1 Cartographic **additional block descriptors and record arrays** from §3.2 and §3.5, and validate their OEM bytes and compression.
3. Allocate physical parcels and size indexes using GlbMediaHeader_t and ucaParcelSizes, with a single address-authority plan for the whole region.
4. Connect the new spatial partition/KD index to those real parcels; verify leaf rectangles, all typed physical targets and cross-index links.
5. Compose region/global/catalog files, use the already tested hybrid ISO mastering, then test map display, search and route calculation on the head unit.

### Exact-source reproduction

    python3 tools/oem_maneuver_pid_spec_audit.py --map SWIAUS1.SDL --reference-report SWIAUS1-descriptors.json --json maneuver-evidence.json
    python3 tools/oem_spatial_header_evidence.py --map BENELUX1.SDL --reference-report BENELUX1-descriptors.json --json spatial-header-evidence.json
    python3 -m unittest discover -s tests -p 'test_oem_*.py' -v

No legacy/migration logic or undocumented address aliases have been added.

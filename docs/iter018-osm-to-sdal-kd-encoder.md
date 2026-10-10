# Iter018 — Actual OSM-to-SDAL encoder components: spatial parcels and KD-tree

## Objective and nonnegotiable boundary

The decoder serves the **production encoder**. The desired one-command build remains:

**OSM PBF → route/cartographic/POI model → spatial parcelization → genuine SDAL 1.7 parcels and typed KD index → global and region metadata → validated hybrid ISO → Denso hardware acceptance.**

This iteration adds a **real encoder of SDAL spatial KD-tree node records and index parcels**, plus an end-to-end generated-index/target-parcel integrity test. It does **not** claim that the old OSM point-based serialization has already been replaced. The user-facing build.sh and current ISO stage remain unchanged.

## Specification authority

Source: uploaded PSF SDAL Format 1.7 v0.4.

- **§3.1.1.2 (pp. 3-6–3-8)**: 16-bit KD node control field, 1/2/4-byte local/external offsets, common-width physical left/right child slots including absent/pruned child padding, entity IDs, typed five-byte Parcel Descriptor + Parcel ID entries, even-byte node alignment.
- **§3.1.1.3 (pp. 3-8–3-9)**: type-255 index header, U16 root offset table and root identities.
- **§1.2.4.3**: common 20-byte PclHdr_t and spatial types **0 Route Calculation, 1 Cartographic, 2 Cartographic Cross-reference, 3 Maneuver, 4 POI Spatial Index, 5 Abbreviated Segment, 6 Crossroads**.
- **§1.2.4.5**: authentic size indexes depend on ucaParcelSizes[] in the global media header and cannot be freely inferred.

The analyzed WE_06Q4 index parcels occupy 0x5000 bytes, use 256-byte direct address units and end with 0xFF fill. This observed profile is not a universal SDAL constraint.

## Original-byte source findings

Unmodified OEM inputs: BENELUX1.SDL (350,914,560 bytes) and SWIAUS1.SDL (364,488,704 bytes). An independent local pass traversed **every** original KD root and its node and descriptor records, and resolved every direct PID to its physical destination.

| Measurement | BENELUX1 | SWIAUS1 | Combined |
|---|---:|---:|---:|
| KD node records | 11,116 | 11,569 | **22,685** |
| Spatial descriptors | 19,949 | 22,014 | **41,963** |
| Unique PIDs within a map | 19,949 | 22,014 | **41,963** |
| PID exactly matches target PclHdr | 19,949 | 22,004 | **41,953** |
| PID does not match target PclHdr | 0 | 10 | **10** |
| Nonzero node alignment bytes | 0 / 2,565 | 0 / 2,660 | **0 / 5,225** |
| Spatial descriptor reserved bit (0x40) set | 0 | 0 | **0** |

The 41,953 exact direct targets also match the expected type and region 1; the 10 unmatched cases are not asserted to have valid target headers.

| SDAL type | BENELUX1 references | SWIAUS1 references |
|---|---:|---:|
| 0 Route Calculation | 4,814 | 5,374 |
| 1 Cartographic | 3,027 | 4,775 |
| 2 Cartographic Cross-reference | 2,265 | 2,501 |
| 3 Maneuver | 6,777 | 6,657 |
| 4 POI Spatial Index | 247 | 356 |
| 5 Abbreviated Segment | 677 | 724 |
| 6 Crossroads | 2,142 | 1,627 |

**The ten original SWIAUS1 anomalies are all type-3/layer-0 references originating in Global KD Index parcel 3 / tree 1.** Their nominal physical destination does not begin with the required Parcel ID. Some PID bytes also occur as parcel headers at other offsets (for example PID 0x1F0D6318 appears in a type-3 header 0x5000 bytes before its nominal address). The cause is not yet established: the encoder must **not** silently reinterpret, relocate or correct those references.

These counts originate from **independent direct-source analysis**, not yet a replay of the newly committed acceptance CLI on those OEM files. The former is original evidence; the latter is still a separate gate.

## Actual production writer changes

### src/sdal_builder/oem_kd_codec.py — NEW

- Typed SpatialRef: 3-bit parcel type, 3-bit layer and four-byte Parcel ID.
- Reversible five-byte descriptor-list encoder/decoder with a final-entry flag, reserved-bit check and bounded list size.
- Reversible KDNode/KDChild encoder/decoder with bit-accurate 16-bit control, cut position, entity-ID mode, equal-width physical child slots, right-aligned smaller offsets, absent-child zeros, ordered left/right parcel descriptors and zero even-byte alignment.
- A direct-target validator comparing a newly generated PclHdr against its declared typed Parcel ID; external indirect handles **require an explicit validated reference table**, not a guessed lookup.
- encode_index_from_nodes: builds complete SDAL type-255 0x5000-byte index parcels from caller-provided ordered root nodes, checks local child targets point to actual node starts, exactly one parent per nonroot local node, reachability, capacity, index header/root offsets and exact decode/re-encode parity.

The existing src/sdal_builder/oem_index.py producer now uses the OEM-observed 0xFF trailing index-parcel fill rather than unsupported zero fill.

### tools/oem_spatial_encoder_parity.py — NEW

Read-only corpus and generated-output verifier. Walks the established global KD reference graph, **decodes every individual KD node with the new production codec, re-encodes the node, and requires exact byte equality**. Resolves spatial descriptors to the physical 20-byte PclHdr, tabulates type/layer and provides explicit per-PID exception provenance. With --strict-generated-parity, any missing or mismatched typed direct target fails closed. This optional strict gate **is for generated files**; applying it to the historical SWIAUS1 donor correctly fails on its 10 unresolved exceptions.

## Verification in synthetic generated files

- tests/test_oem_kd_codec.py exercises several hundred deterministic writer roundtrips and explicitly malformed control/descriptor inputs.
- tests/test_oem_kd_index_assembly.py builds complete type-255 index parcels, verifies local tree topology, catches missing/multiple parents, invalid offsets, overflow, checks 0xFF fill and decoder byte parity.
- tests/test_oem_spatial_encoder_parity.py **generates its own index and physical type-3 parcel from writer inputs**, validates the entire graph and the target header, and then flips individual target/descriptor bytes to demonstrate hard failure. These are actual written binary files, not mocked API results.
- GitHub Actions retains cumulative Linux/macOS hybrid ISO mastering integration checks.

**Copyrighted original OEM map bytes are not committed.** The exact published decoder/encoder/validator must still be run as-is on both full original files for a separate source-data acceptance claim; independent source scanning alone is not that claim.

## What remains before a useful Denso DVD

The current main.py / spatial.py still serializes SciPy POI-point KD trees as 12-byte records into KDTREE.SDL. **That is not the SDAL §3.1.1.2 typed spatial KD-tree found inside authentic regional 1.SDL files.** The legacy generated short count-based DENS...0.SDL is likewise not the genuine Denmark/Sweden regional index. This architectural mismatch is not repaired by a good codec alone.

Required production sequence:

1. Encode actual SDAL spatial parcel **contents** (types 0,1,2,3,4,5,6) and their cross-reference/geometry/routing structures from OSM.
2. Build one authoritative parcel-placement and size-index plan consistent with GlbMediaHeader_t, sector units, ucaParcelSizes[], original headers and reference index tables.
3. Compute the geographic split plan in NTUs and valid 1/32 spatial cuts; allocate stable SDAL segment/node entity IDs and layers.
4. Call the **production KD node/index writer** delivered here, resolve all local and cross-index root links and all typed Parcel IDs.
5. Reject generated SDL on **any** unresolved or mismatched reference before final ISO mastering.
6. Complete header/catalog correctness and verify map loading, display, search and routes on a real Denso unit.

**Iter018 delivers the writer portion of step 4 plus an integrity gate for step 5, not the missing OSM geometry/parcel generators of steps 1–3.** Integrating it blindly into the old POI-point pipeline would produce invalid maps and is not an acceptable root-cause fix.

## Reproduction

~~~bash
python3 tools/oem_spatial_encoder_parity.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --json verification/iter018-original-evidence.json

# Strict checks only on newly produced, expected-complete SDAL files:
python3 tools/oem_spatial_encoder_parity.py \
  --map GENERATED=/path/to/GENERATED1.SDL \
  --strict-generated-parity \
  --json verification/iter018-generated-evidence.json

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
~~~

**Next content-first slice:** OSM-native typed parcelization and actual type-1 Cartographic / type-0 Routing target parcel serializer with forward and backward reference parity to this KD-tree writer. No speculative OEM migration paths.

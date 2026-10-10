# Iter013 — SDAL 1.7 Global KD-tree node graph integrity

## Scope, source authority and acceptance standard

The user requires data/parcel correctness before revisiting ISO mastering. This slice reconstructs and validates the **complete first root of the first OEM Global KD-tree Index parcel** from two genuine user-supplied map binaries:

- `BENELUX1.SDL` — 350,914,560 bytes, original WE_06Q4 DVD
- `SWIAUS1.SDL` — 364,488,704 bytes, same DVD

The format source is **SDAL PSF 1.7 (version 0.4), sections 3.1.1.2 and 3.1.1.3**. Unlike prior iterations that stopped at `IDxPclHdr_t` and a U16 array of root positions, this release interprets the 16-bit KD-tree control word and its **actual local and inter-parcel child links**. A validated subsection of two authentic OEM maps is not 100% compatibility with a Denso head unit. No unverifiable compatibility claim is made.

## Bit-level decoding grounded in the specification

The node's 16-bit big-endian control word is numbered most-significant bit first by the specification.

| Bit(s) | Verified interpretation |
|---|---|
| 0 | Left Parcel Descriptor List present |
| 1 | Right Parcel Descriptor List present |
| 2 | Vertical (0) or horizontal (1) cut |
| 3–7 | Spatial cut position in 1/32 units |
| 8–9 | Left child: absent (00), external 4-byte (01), local 1-byte (10), local 2-byte (11) |
| 10–11 | Right child: same four modes |
| 12–13 | No explicit entity IDs (00), six explicit bytes (01), implicit zeros (10), implicit 0xFFFFFF (11) |
| 14–15 | Reserved; both zero in the validated initial tree |

When present, six explicit entity-ID bytes precede the child references. Child references precede optional lists of five-byte descriptor/ParcelID pairs. A descriptor with its first (MSB) bit set ends a list; entries are padded to a two-byte node-record boundary.

**Local offset** `delta` targets the node at **current node start + 2 × delta**. **External offset** is two big-endian U16 values: the relative KD-index parcel number and the tree ID in that parcel. We verify these against the real 10 or 11 index parcels and their actual counts of roots.

## Actual OEM binary verification

An independent direct-byte exploratory parser was executed on both authentic map files. The following **fully enumerated graph** results were observed:

| Measurement | BENELUX1 | SWIAUS1 |
|---|---:|---:|
| Global KD index parcels present | 10 | 11 |
| Roots in the first index parcel | 899 | 923 |
| Byte position of first root | `0x071E` | `0x074E` |
| Byte position of second root | 18,674 | 18,628 |
| First tree's exact byte span | 16,852 | 16,758 |
| Fully decoded root-zero nodes | **2,495** | **2,507** |
| Local child edges | **2,494** | **2,506** |
| Four-byte external child references | **1,600** | **1,588** |
| Local edges without a valid node target | **0** | **0** |
| External references without a valid (parcel, tree) target | **0** | **0** |
| Disconnected or unreachable local nodes | **0** | **0** |
| Maximum local tree depth, measured | 11 | 11 |

The locally enumerated start offsets of all node records partition each initial-root byte range without overlap or gaps; each non-root node has **one** incoming local edge, and the root has none. Therefore there are exactly `nodes - 1` local edges and a complete directed tree, not merely a connected multigraph or an accidental sequence of parseable bytes.

External references were checked against the **real U16 root-count arrays of all original index parcels**. Every one of the **3,188** observed external references targets a valid index parcel and a valid root number.

These are **strong structural proofs for this explicitly scoped portion**. They do not establish the routing meaning of an entity ID, a layer's semantic correctness, the correctness of all *other* KD-tree roots, or hardware loading.

## Evidence-limited software

New tool: `tools/oem_kd_graph_integrity.py` — read-only. For each supplied original map:

1. Scans consecutive type-255 global KD index parcels beginning at the known OEM 0xC200 map position; validates their 20-byte PclHdr_t and U16 root-offset arrays.
2. Reads the first root byte span of the first index parcel. Parses nodes according to SDAL 1.7 control flags, local child offsets, external indices/tree IDs, optional entity ID fields and descriptor termination bits.
3. Traverses local child references, forbids backward/cyclic/out-of-root or misaligned offsets, and enforces exact non-overlapping byte-span coverage.
4. Asserts one incoming parent per non-root node and exactly `nodes-1` local edges; validates every external target against the actual available parcel/root inventory.
5. Reports counts, bounds, code distributions, depth and first external targets in deterministic JSON and Markdown, without emitting any copyrighted map content.

Ten synthetic negative/positive regressions test valid trees, physical address/size constraints, invalid local offsets, missing cross-index references, cycles, reserved control bits, descriptor lists, six-byte entity IDs, mutated root tables, reproducibility and truncated inputs. They are run by GitHub Actions with the cumulative source-free forensic suite.

## Known non-validated region

A separate exploratory attempt to extend the same assumption to **all** roots found genuine ambiguous records, particularly in the later type-255 index parcels. Some noninitial roots include additional per-root structures, different record variants or reference conventions not explained by the initial-root decoder.

**Do not claim the full KD-tree has been decoded.** Iter013 deliberately fails closed for a mismatched first-root pattern rather than accepting a misleading node interpretation. It does not rewrite the current OSM KD-tree generator or invent a record schema.

## Reproduction with original OEM files

```sh
python3 tools/oem_kd_graph_integrity.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --json verification/iter013-oem-kd-graph.json \
  --md verification/iter013-oem-kd-graph.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

The numeric observations above were measured from the original bytes by an independent exploratory parser in the analysis runtime. **Execution of the newly committed tool itself against the complete originals must be recorded separately**; current GitHub CI has access only to synthetic inputs. Do not conflate these distinct acceptance levels.

## Next step to approach true compatibility

Continue node-by-node validation into the *remaining* KD-tree roots, determine whether record variants are distinguished by tree type, subtree-level metadata or parsing context; then resolve actual type-1/2/3 parcel references and geometry/compression and compare a fresh OSM-generated sample against the reconstructed reference graph. Only after the content graph and parser contracts are verified should the existing `build.sh` pipeline's production serializer be incrementally switched over and ISO mastering revisited.

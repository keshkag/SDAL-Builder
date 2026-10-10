# Iter017 — SDAL 1.7 spec-first correction of Global KD-tree children

## Root cause, not an undocumented OEM format

The user correctly challenged the implication that we needed to guess the format of 1,101 previously unresolved original KD-tree roots. The authoritative **SDAL PSF Format 1.7 v0.4**, §§3.1.1.2–3.1.1.3 (PDF printed pages **3-6 to 3-9**), explicitly defines node control bits and states:

- Left and right child **offset fields occupy the same byte width**.
- A four-byte field may store a smaller local child offset in its least-significant bytes.
- When one child is absent/pruned but the other has an offset, the source data still contains the absent child's zero-filled field of the common width.
- Local child offsets are relative to the *current node*, counted in 2-byte units.
- Four-byte external offsets encode index-parcel offset and tree ID.
- Explicit segment/node identifiers are 3+3 bytes, and parcel descriptor lists are 1-byte descriptors plus direct 4-byte Parcel IDs.
- All complete index parcels are of equal length and can contain multiple roots described by a U16 root offset table.

**Prior decoder defect:** it consumed each child slot using only that child's own mode. Thus, for the real OEM node bytes \`10 38 00 00 00 03 ...\`, it misread the first \`00 00\` (the pruned left-child slot) as the right-child offset and falsely reported a self-reference of zero. The correct read assigns \`00 00\` to the absent left child and \`00 03\` to the right child, producing the valid target \`node_start + 6\`.

This defect was the **entire explanation of the 1,101 previously unresolved, fully bounded roots**: it was not evidence that OEM used 1,101 special tree variants. The hypothesis experiments in Iter015/016, including "zero means missing child", are historically useful diagnostic records but **must not** be promoted to codec behavior. They are superseded by this spec-backed root-cause fix.

## Exact independently executed original-byte scan (both full OEM map files)

Sources: original user-supplied WE_06Q4 \`BENELUX1.SDL\` (350,914,560 bytes), \`SWIAUS1.SDL\` (364,488,704 bytes), SDAL 1.7 PDF.

| Structural classification | BENELUX1 | SWIAUS1 | Total |
|---|---:|---:|---:|
| Roots in real type-255 index parcels | 2,603 | 2,405 | **5,008** |
| Roots with explicitly bounded data, parse correctly with equal-width slots | 2,593 | 2,394 | **4,987** |
| Previously unresolved bounded roots now correctly parsed | **604** | **497** | **1,101** |
| Terminal roots lacking an explicit end in root_offset[] | 10 | 11 | **21** |
| Terminal roots that also form exact graphs when contiguous final FF fill is excluded | 10/10 | 11/11 | **21/21** |
| All roots passing bounded or FF-inferred structural checks | **2,603** | **2,405** | **5,008** |

The new encoding **did not invalidate a single previously accepted bounded root**. It resolves every one of the old F/G/H/Y "unknown" clusters. Code explicitly distinguishes U16-indexed exact boundaries from FF-inferred terminal boundaries; the latter carry their evidence status rather than silently being treated as independently recorded lengths.

## Independent whole-graph consistency proof

For *every one* of the 5,008 roots, the direct original-data checker validated the local node spans and every 4-byte cross-index pointer. Entire original kd-tree graph measures:

| Proof criterion | BENELUX1 | SWIAUS1 |
|---|---:|---:|
| Type-255 index parcels | 10 | 11 |
| All root records | 2,603 | 2,405 |
| Exact \`0x1000\` leaves (including FF-trimmed terminal leaves) | 1,584 | 1,574 |
| Fully parsed nonleaf root graphs | 1,019 | 831 |
| Parsed node records within nonleaf graphs | **9,532** | **9,995** |
| External child references | **2,602** | **2,404** |
| Distinct addressed nonroot trees | **2,602** | **2,404** |
| Root with no incoming external reference | (0,0) only | (0,0) only |
| Roots with multiple incoming parents | **0** | **0** |
| Missing/invalid external references | **0** | **0** |
| Unreachable roots from global root (0,0) | **0** | **0** |

A directed arborescence proof consists of **N−1 external references, each nonroot having exactly one incoming reference, and graph reachability from the sole root**. This holds for **both complete OEM maps**, completely independently of their differing map contents.

In addition, each local graph uses strict byte partition, forward local children, one incoming parent per nonroot *local node*, and no out-of-bounds child or root reference. Passing these checks on both maps is substantially stronger than recognizing similar control words.

## Delivered changes

- **Corrected** \`tools/oem_kd_graph_integrity.py:parse_node\` to implement equal-width physical slots. Both child descriptors use a common maximum width (1, 2 or 4 bytes); a narrower logical offset uses the least significant bytes, and a pruned child retains an all-zero physical slot. High-order nonzero bytes in padded slots and nonzero absent-child slots fail closed.
- \`tools/oem_kd_all_root_integrity.py:classify_root\` now accepts an explicitly supplied terminal-content bound for evidence-only validation. Without an explicit caller-provided bound, it continues to report terminal-boundary uncertainty and never guesses.
- **New** \`tools/oem_kd_complete_graph.py\`: validates every root, separately audits FF-inferred terminal ends, traverses every proven external child, enforces exactly one incoming external parent per nonroot index tree, verifies the one global root and all-root reachability, emits metadata-only deterministic JSON and Markdown.
- New source-free tests \`tests/test_oem_kd_complete_graph.py\` and added negative cases for zero/nonzero pruned slots and high-byte padding in mixed-width child modes.
- Existing forensic fixtures are changed surgically to contain physically correct same-width child offset slots; earlier invalid fixture bytes must not be mistaken for an OEM example.
- No production OSM serializer, existing \`build.sh\`, ISO mastering, or non-OEM map payload is changed.

## Reproduce against both original map files

\`\`\`sh
python3 tools/oem_kd_complete_graph.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --json verification/iter017-global-kd.json \
  --md verification/iter017-global-kd.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
\`\`\`

**Evidence-channel boundary:** this exact-numeric source census was independently run directly on unmodified original files in the analysis runtime using the spec-correct parser and an independently implemented external-reference walk. GitHub Actions validates the committed code on synthetic, mutated reference graphs, not private OEM data. Execution of the *published CLI itself* on the complete originals remains a separate release-acceptance check unless explicitly re-run and recorded.

## Remaining genuine unknowns

1. The high-level **spatial meaning** of cuts and geographic bounding rectangles across all tree roots, not merely the byte structure and graph.
2. Actual target parcel **type/layer** and physical reference resolution to route/cartographic parcels (types 1/2/3/...).
3. Full cartographic geometry, routing, compression and semantic correctness of OSM-generated content.
4. Precisely specified semantics of the terminal \`0xFF\` padding and whether exact same fill behavior is mandatory for all OEM releases.
5. Final on-device Denso loading, map display, search and route computation tests.

**This iteration establishes complete structural validity of the global index graph for these two original OEM map files. It is NOT proof that the current Builder's generated cartographic data or entire ISO is compatible with a Denso head unit.**

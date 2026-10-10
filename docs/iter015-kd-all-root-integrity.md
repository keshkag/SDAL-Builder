# Iter015 — full-corpus KD-root integrity, without invented node semantics

> **Superseded by Iter017 (SDAL 1.7 §3.1.1.2).** The `1,101 unresolved bounded roots` and their F/G/H/Y classifications below were false negatives caused by the older decoder ignoring equal-width left/right child slots, including the zero-padded field of a pruned child. The spec-correct decoder parses **all 4,987 explicitly bounded roots** in the two genuine maps, and all 21 terminal roots also pass after independently recorded FF-tail inference. See `docs/iter017-sdal17-global-kd-complete.md`. Historical counts are retained below as a record of the superseded experiment, **not current OEM truth**.\n\n
## Source authority and scope

All observations are derived from user-supplied original **WE_06Q4** map payloads:

- \`BENELUX1.SDL\` — 350,914,560 bytes
- \`SWIAUS1.SDL\` — 364,488,704 bytes

The format terminology is from SDAL PSF 1.7 v0.4, §3.1.1.2 (**Global KD Tree Entry Structure**) and §3.1.1.3 (**Global KD Tree Parcelization**). The codec/metadata from Iter012 and node controls from Iter013 remain the basis. No generated \`0.SDL\` and no undocumented OEM byte blobs are admitted as reference evidence.

**This iteration is intentionally content-focused.** It neither modifies the established one-command \`build.sh\` OSM→SDL→ISO workflow nor the verified hybrid ISO mastering of Iter014.

## New cross-map evidence from complete enumeration

Previous development proved only two complex root graphs (one from each original regional map) while classifying 3,152 exactly two-byte leaf records. A new independent, direct-original byte scan used strict traversal and exact interval partition checks for **every root** in all 21 Global KD-tree Index parcels.

| Evidence classification | BENELUX1 | SWIAUS1 | Combined |
|---|---:|---:|---:|
| Root records enumerated from authentic offset tables | 2,603 | 2,405 | **5,008** |
| Exact bounded 2-byte \`0x1000\` leaf | 1,581 | 1,571 | **3,152** |
| Entire bounded interval is a strict valid local tree according to §3.1.1.2 | 408 | 326 | **734** |
| Interior roots failing the current decoder/graph constraints | 604 | 497 | **1,101** |
| Final roots without authenticated byte-length boundary | 10 | 11 | **21** |

**3,886 of 5,008 root records (77.6%) pass the bounded structural profile**, including **732 additional** complete graph structures beyond the two validated first roots in Iter013. These are physical-structure checks, **not** successful navigational query outcomes. The remaining **1,122 records** are explicitly unverified (1,101 malformed/ambiguous under the *current* decoder, plus 21 final-root boundary ambiguities).

The exact bounded two-byte leaf \`0x1000\` has no child-offset nor parcel-descriptor flags in the documented control word. It does **not** establish the geographic purpose or population of that leaf.

### What an accepted multi-node root proves

For a nonterminal root, the beginning and end are both authenticated by **consecutive offsets** in the OEM U16 root-offset array. The strict verifier:

1. Reconstructs each variable-length node from the specified 16-bit control code, six-byte entity-ID mode, child-offset widths and terminating parcel-descriptor lists.
2. Traverses every local child offset from the root entry, using the specified two-byte offset unit from the current node.
3. Rejects zero/backwards child offsets, unaligned addresses, out-of-root jumps and unrecognizable/truncated records.
4. Resolves every four-byte child reference to an **existing index parcel and existing root ID**, using the original root tables.
5. Requires each decoded node's byte range to connect exactly to the next, without overlaps, gaps or trailing silently accepted junk.
6. Requires \`nodes - 1\` local links, no incoming link to the root and exactly one incoming link to every other node.

A complete byte partition and correct graph topology strongly corroborate this scoped encoding interpretation. The routine does **not** infer coordinate transforms, leaf parcel content or the routing meaning of IDs.

### Why 1,122 roots remain unresolved

The independent original scan encountered repeatable failure signatures: local offsets of zero (targeting the current node), apparently discontinuous node spans, and records whose descriptor lists cannot fit their assumed root bounds. These cases show that extending the initial-root parser naively would cause **false-positive acceptance**. The source may use different record variants or reference contexts, but neither is assumed without independent evidence.

The last root of each index parcel is separately classified **terminal_boundary_undetermined**, because the offset array contains its start but does not contain its physical end. Those 21 spans often end with \`0xFF\` bytes, and trimming those bytes until an apparent record fits is not a proof of a correct tree. This explicitly corrects an overly broad interpretation in early explorations where padded final roots could be counted as complete leaves/graphs.

## Delivered implementation

New: \`tools/oem_kd_all_root_integrity.py\`

- Independently inventories **every** source root in each original 0x5000-byte type-255 index parcel.
- Uses the existing documented per-node parser from Iter013 for each nonterminal complex root.
- Distinguishes four mutually exclusive outcomes: \`exact_two_byte_leaf\`, \`exact_graph_under_sdal_control_profile\`, \`unresolved_node_encoding\`, and \`terminal_boundary_undetermined\`.
- Emits root number, parcel number, exact byte-range offsets, SHA-256 of its source bytes, initial control word, and **specific failure reason without serializing proprietary payload bytes**.
- Validates a strict root accounting invariant; streams whole-file SHA-256 so analyzing a 350+ MB original map does not load it all into RAM.
- Produces JSON for future corpus-level comparison and concise Markdown tables and unresolved reasons.

New: \`tests/test_oem_kd_all_root_integrity.py\`

Seven source-free regressions verify complete accounting, valid tree/leaf/last-root classification, error isolation, corrupted topology rejection, deterministic output, absence of input mutation and malformed original index-table rejection.

**Verification separation:** The source-observation counts above are from an independent original-byte scan in this conversation. GitHub Actions runs the committed analyzer on synthetic fixtures. Because the local container intermittently refused later commands, executing this exact committed script on the original full map files is an additional release acceptance check. Do not misrepresent synthetic CI as full-donor verification.

## Reproduce the original-file audit

\`\`\`sh
python3 tools/oem_kd_all_root_integrity.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --json verification/iter015-oem-root-integrity.json \
  --md verification/iter015-oem-root-integrity.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
\`\`\`

## Next bounded investigation

The highest-value problem is the **1,101 bounded roots** that do not pass the current node grammar. Cluster their first failing controls, candidate entity-ID modes, descriptor-list lengths, and local zero-offset cases; test proposed alternate interpretations *against both complete OEM map corpora*. An alternate interpretation is acceptable only if it exactly partitions the bytes, produces a valid rooted graph, has valid inter-parcel references, and does not reduce validation of currently confirmed roots.

After that, validate the parcel-descriptor \`ParcelID_t\` references **against actual map parcels** and build source→generated parity checks for type-1/2/3 cartographic and routing data. Passing graph topology alone cannot certify that OSM output is navigable on Denso hardware.

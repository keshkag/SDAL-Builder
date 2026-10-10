# Iter016 — OEM KD-root similarity clusters and reference relationships

> **Superseded by Iter017 (SDAL 1.7 §3.1.1.2).** The `1,101 unresolved bounded roots` and their F/G/H/Y classifications below were false negatives caused by the older decoder ignoring equal-width left/right child slots, including the zero-padded field of a pruned child. The spec-correct decoder parses **all 4,987 explicitly bounded roots** in the two genuine maps, and all 21 terminal roots also pass after independently recorded FF-tail inference. See `docs/iter017-sdal17-global-kd-complete.md`. Historical counts are retained below as a record of the superseded experiment, **not current OEM truth**.\n\n
## Decision and evidence boundary

The user asked to **find similar undecoded root records, separate them into meaningful groups, identify how groups differ, and trace their connections to verified trees**. This is the scope of Iter016. The existing end-to-end \`build.sh\` OSM→SDL→hybrid ISO workflow and map serializers remain unchanged.

Original byte evidence comes from the **unmodified WE_06Q4** regional map files:

- \`BENELUX1.SDL\` — 350,914,560 bytes
- \`SWIAUS1.SDL\` — 364,488,704 bytes

Reference semantics are constrained by SDAL PSF 1.7 v0.4, §§3.1.1.2–3.1.1.3: MSB-first 16-bit KD control codes; child modes for no child / four-byte cross-index reference / one- or two-byte local offset; explicit 6-byte entity IDs; left/right parcel descriptors; a cross-index reference containing the target index-parcel offset and root identifier.

**Important:** Clusters describe structural evidence, not different established geographic or routing object classes. Until a complete byte partition, valid child tree, and correct cross-index references are demonstrated, no new root record format is accepted as an OEM codec.

## All 5,008 original OEM roots: the refined classification

| Root family | BENELUX1 | SWIAUS1 | Combined | Why classified |
|---|---:|---:|---:|---|
| A — exact two-byte \`0x1000\` | 1,581 | 1,571 | **3,152** | Entire bounded root consists of this control word |
| B — one-node verified records | 356 | 257 | **613** | One node covers the entire bounded interval exactly |
| C — verified multi-node graphs | 52 | 69 | **121** | Exact node partition and correct local/external edge graph |
| F — zero/nonforward local child | 412 | 321 | **733** | Under documented local-offset interpretation, an edge points to its own node (observed delta = 0 in all 733) |
| G — incomplete/overlapping node partition | 150 | 155 | **305** | Decoding may appear plausible but cannot account for every byte |
| H — unterminated/truncated descriptor list | 41 | 21 | **62** | Descriptor series does not terminate before the authenticated root boundary |
| Y — other bounded discrepancy | 1 | 0 | **1** | End of decoded graph does not reach end of bounded root |
| Z — last root of index parcel | 10 | 11 | **21** | Offset array supplies start but no authenticated end before FF padding |
| **Total** | **2,603** | **2,405** | **5,008** | Exact root accounting |

This is a correction in presentation, **not a reversal of earlier raw counts**: Iter015 reported 734 exact graphs, but 613 of those have exactly one node. Only **121** are multi-node graphs. Treating all 734 identically would hide a major difference in how much actual topology has been decoded.

The high-confidence categories A+B+C cover **3,886/5,008 roots**, i.e. approximately 77.6%, **on the structural conditions defined above only**. The 1,122 unverified roots remain explicitly unresolved.

### A control-field clustering with consistent geographic-independent characteristics

A control signature is the tuple:

\`L<left-child-mode> R<right-child-mode> I<entity-ID-mode> D<left-descriptor-flag><right-descriptor-flag>\`

It deliberately omits the cut-axis/position bits, which encode geometry rather than record layout. For example:

- \`0x1000\` → \`L0R0_I0_D00\`: exact two-byte leaf.
- \`0xD004\` → \`L0R0_I1_D11\`: explicit entity ID and both descriptor lists, no local child; prevalent in completely decoded one-node records.
- \`0xD0F4\` → \`L3R3_I1_D11\`: two 2-byte local offsets, explicit entity IDs and both descriptor lists; occurs in **both validated and unresolved** multi-node roots.
- \`0x9034\` → \`L0R3_I1_D10\`: one side has no child, the other uses a 2-byte local offset; this family is repeatedly unresolved and is a high-priority parser-semantics investigation target.

In both OEM maps, every examined first-root signature \`L0R0_I1_D11\` is structurally accepted as a single-node span: **346** in BENELUX1 and **238** in SWIAUS1, 584 total. The remaining 29 accepted single-node spans use different combinations of descriptor flags, entity modes and child modes.

Conversely, at least 422 unresolved roots belong to a few common *one-sided* child/descriptor families, including \`L0R3_I1_D11\`, \`L3R0_I1_D11\`, \`L0R3_I1_D10\` and \`L3R0_I1_D01\`. A code pattern alone is **not** sufficient to declare all records with that signature invalid, because some other signatures occur in both accepted and rejected roots.

### Distinct indexed regions

The unknown groups are very unevenly distributed:

- In BENELUX1, index parcel 0 has **no bounded unresolved roots**. The large concentrations are parcels **4, 6, 7, 8 and 9**.
- In SWIAUS1, index parcel 0 likewise has **no bounded unresolved roots**. The main concentrations are parcels **6, 7, 8, 9 and 10**.

This is evidence of an index-order-dependent data distribution. It is **not** proof that these parcel indices map to the same geographic layers in every OEM map; that meaning requires tracing the original parcel descriptor type/layer fields and actual map extent records.

## Main discovery: graph relationships between root groups

All edges below were independently enumerated by traversing **only those roots with strict complete graph validation**, following SDAL-specified four-byte references to real (index parcel, root ID) locations. Edges from unverified roots are **not** used, to avoid inventing connectivity.

| Verified external link destination | BENELUX1 | SWIAUS1 | Both |
|---|---:|---:|---:|
| A — two-byte \`0x1000\` root | **1,581** | **1,571** | **3,152** |
| B/C — other strictly verified root | 7 | 0 | 7 |
| F/G/H/Y — bounded unresolved root | **9** | **15** | **24** |
| Z — terminal root with unknown byte boundary | **5** | **6** | **11** |
| **All verified external links** | **1,602** | **1,592** | **3,194** |

**Every single one of the 3,152 exact two-byte roots is addressed by exactly one external link from a structurally verified graph.** This is a particularly strong consistency constraint between the apparent top-level index and the simple leaf family. It does not establish each link's spatial meaning, but it makes accidental identification of thousands of \`0x1000\` byte pairs implausible.

The remaining **35 frontier destinations** (24 unresolved bounded roots plus 11 unbounded terminal roots) are high-value targets: each has a proven incoming edge. The new machine-readable report includes their (index, root) IDs, initial control signatures, size, failure reason, SHA-256 and source graph IDs **without shipping any original map bytes**. These are specific inputs for the next constrained decoding experiment.

Seven additional links in BENELUX1 target already verified roots. The known graph consequently has multi-level cross-parcel organization; not all verified reference targets are simple leaves.

### Test of alternative hypothesis: a zero delta means "pruned/absent child"

Every one of the 733 \`nonforward_local_reference\` failures in the OEM corpus occurred at a **zero-valued** local child offset. Such a pattern may indicate a special encoding, but neither the observed pattern nor the retrieved spec explicitly authorizes treating a present local offset of 0 as a missing child.

A *separate experimental interpretation* which suppresses zero-valued local links increased strictly covered graph roots:

| Metric | Baseline spec interpretation | Experimental zero-as-absent |
|---|---:|---:|
| BENELUX1 exact graph roots | 408 | 426 |
| SWIAUS1 exact graph roots | 326 | 333 |
| **Additional apparent graphs** | — | **25** |

The other hundreds of affected roots **still fail exact byte coverage or descriptor constraints**. This does **not** validate the hypothesis. The committed production codec and strict validator **do not make this change**; the experiment is recorded solely as a falsifiable candidate for follow-up testing.

## Implementation and reproducibility

New read-only \`tools/oem_kd_similarity_clusters.py\`:

1. Imports the existing strict \`classify_root\` and \`read_indexes\` forensic readers, so it does **not** duplicate/loosen the validated KD node grammar.
2. Separates accepted one-node roots from multi-node graphs, preserving the original failure taxonomy for unknowns.
3. Aggregates control signatures **independent of cut-coordinate bits**, with counts and ratios by map and index parcel.
4. Traverses **only strictly validated graphs** to recover real external cross-index references; checks each target exists, then aggregates its root family and incoming-link multiplicity.
5. Emits every unresolved target already reached from a verified graph as an explicit investigation frontier; produces deterministic JSON and Markdown.
6. Does not copy map fragments, synthesize KD nodes or write any ISO.

\`tests/test_oem_kd_similarity_clusters.py\` provides offline synthetic regressions for field decoding, target provenance, no-loss root accounting, rejecting zero child offsets instead of inventing sentinel semantics, direct link reassignment, malformed tables, and deterministic/no-mutation operation.

To execute against original OEM payloads:

\`\`\`bash
python3 tools/oem_kd_similarity_clusters.py \
  --map BENELUX1=/path/to/BENELUX1.SDL \
  --map SWIAUS1=/path/to/SWIAUS1.SDL \
  --require-unique-singleton-parent \
  --json verification/iter016-kd-clusters.json \
  --md verification/iter016-kd-clusters.md

python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
\`\`\`

The optional `--require-unique-singleton-parent` mode enforces this particular observed WE_06Q4 cohort's unique-incoming-leaf invariant and fails closed on missing/duplicate links. It is **not** treated as a universal SDAL requirement. A synthetic counterexample is deliberately rejected by the new regression test.

**Verification provenance:** All original-byte counts and relations above were independently computed directly against both user-provided map files in this session. The published tool is covered by synthetic GitHub CI regressions. A separate execution of the *published exact-version* CLI against all original bytes remains a release acceptance item if runtime access is unavailable; green synthetic CI must not be misrepresented as complete original-data verification.

## Next bounded slice

Start with the **35 externally referenced frontier roots**, not 1,101 arbitrary cases. For each:
- Compare original node controls and exact bounded bytes with accepted roots **in the same index parcel**, then across regions, focusing on the entity ID and parcel-descriptor layout.
- Form explicit alternative interpretations of zero offsets and one-sided children **only if** the spec and original bytes permit them.
- Require an exact byte partition and valid parent topology in **both** OEM maps; reject any interpretation that destroys current verified-root proofs.
- Use genuine Parcel Descriptor (type/layer) and physical ParcelID targets to assign each group a function, rather than assuming a function from the control code alone.
- Advance the OSM→SDL serializer only after the source record and its target graph are proven, then exercise real graph/geometry comparisons.

ISO mastering from Iter014 remains unchanged and tested; the primary work continues to be the content placed inside the ISO.

# Iter024 — Global Media Header, Global Media Index and linked regional roots

## Target and scope

The end product remains the existing one-command **OSM PBF → SDAL 1.7 → checked hybrid ISO → Denso navigation disc**. Iter024 implements real source-to-wire production components for the Global Media File's fixed-header core, variable-length bootstrap index and reference parcel links. It does **not** declare a complete OEM-compatible global catalog or replace the current main.py implementation; remaining global reference tables and authentic per-record source writers still need independently verifiable formats.

Primary source: user-supplied **PSF Specification for SDAL Format 1.7 (Version 0.4)**, sections **1.1.2, 2.1, 2.1.1.3, 2.1.1.4 and 2.4.1.2**, rather than inference from original filenames.

## Source-defined bootstrapping contract

- The Global Media File is the special **region-zero file named 0.SDL** in the specification. Its first **2048 bytes** contain GlbMediaHeader_t directly, with **no ordinary PclHdr_t wrapper**. Its second bootstrap parcel begins **exactly at byte 2048** and has length **ucNextParcelLen × (1 << usBlockSize)**. It is the raw variable-length **Global Media Index**, not a type-255 KD parcel and not a collection of records with PclHdr_t at the start.
- Subsequent global reference-data/metadata/icon parcels have ordinary Parcel IDs and PclHdrs in **region 0**; their physical byte addresses derive from the same media-wide size table and sector exponent introduced in Iter023.
- Index array offsets in GlbMediaHeader_t are **relative to the start of the second bootstrap index parcel**. RefDataIndex_t is a **12-byte** structure with an actual ParcelID_t, per-target parcel usIndexOffset and usDescrOffset, a last-index extent, and two reserved bytes.
- MetadataLevel_t has two Ushort fields (**4 bytes**); MetadataModule_t has level/id/length/flags and two ParcelIDs (**16 bytes**); CompressInfo_t uses **8 bytes** and LocaleTable_t begins with a Ushort byte length and 256 Ushort conversion entries. These structures are implemented with explicit field packing and checked readback.
- The fixed Global Media Header contains a **1024-byte** ucaNormalizedAttrs[256][4] global routing dictionary, an **8-byte external index bitmap**, a **4-byte internal index bitmap**, followed by the source-defined table offsets/counts, the 128-entry size table, PSF version/date fields, 32 Ushort permanent node costs and TPD vendor mask. The new core writer preserves all other bytes of its caller-supplied complete 2048-byte header.

### Absolute positions of implemented known fields

| GlbMediaHeader_t field | Byte offset | Bytes |
|---|---:|---:|
| ucaNormalizedAttrs[256][4] | 0 | 1024 |
| ucaExtIdxBitmap | 1024 | 8 |
| ucaIntIdxBitmap | 1032 | 4 |
| metadata-level offset/count | 1036 | 4 |
| metadata-module offset/count | 1040 | 4 |
| usMetadataHashvalue | 1044 | 2 (caller owns algorithm) |
| 8 named reference-data offset/count/max triples | 1046 | 48 |
| shield/POI icon offsets/maxima | 1094 | 8 (not authored yet) |
| voice index offsets/count/max | 1102 | 6 (not authored yet) |
| CompressInfo offset/count | 1108 | 4 |
| Huffman tree offset/count | 1112 | source fields (not authored yet) |
| LocaleTable offset/length | 1118 | 4 |
| ucaParcelSizes | 1122 | 128 |
| ucParcelSizeCount / ucNextParcelLen | 1250 | 2 |
| usBlockSize / usBlockNbrBits / usBlockSizeBits | 1252 | 6 |
| PSF identity / date fields | 1258 | 9 |
| 32 permanent node costs | 1267 | 64 |
| TPD vendor mask | 1335 | 4 |
| firstIconParcelID | 1339 | 4 (not authored yet) |
| Affix reference offset/count/max | 1343 | 6 |
| generic-reference arrays | 1349 onward | **not sized by supplied spec** |

The supplied specification references the constant **MAX_GENERIC_REF_DATA** but does not define its value in the provided text; the associated arrays cannot be safely auto-sized or generated. Their original header bytes are therefore retained as caller-owned state. Shield/POI icons, Huffman tree binaries, metadata module hashing and the remaining generic index structures also require independently validated producer authority.

## New implementation

### src/sdal_builder/oem_global_media_header.py

A concrete, reversible encoder/decoder for all 256 normalized routing attributes, using the actual PSF 32-bit field composition: SpeedCat 3 bits, LaneCat 2 bits, Access 10 bits and Display 17 bits. It also implements explicit PSF version/date, index bitmaps, permanent node costs and vendor-mask fields. No general-purpose dict-to-binary patches and no undocumented body bytes. The writer requires a caller-owned full fixed header and preserves all unknown sections exactly.

This enables the future OSM routing-attribute classifier to produce authoritative global normalized dictionary bytes and 0–255 lookup indexes rather than handing Routing Segment records unverified numeric attribute indexes.

### src/sdal_builder/oem_global_media_index.py

Actual binary producer for:
- Eight named RefDataIndex_t families (Chain ID, Feature Type, Facility Type, Attribute Value, Language Code, Country Info, Time Zone, DST) plus the separately positioned **Affix reference family** at fixed header offset 1343;
- MetadataLevel_t and MetadataModule_t arrays, including declared metadata levels, unique module identifiers, module lengths, both real parcel references and a required externally supplied metadata hash;
- Explicit uncompressed CompressInfo_t records; other compression modes are rejected until authenticated Huffman/LZ metadata can be generated;
- Caller-supplied byte-validated LocaleTable_t with correct declared length, 256 mappings, and negative-string-offset/ligature bounds.

All index sections are placed deterministically at actual even byte offsets inside the index capacity given by ucNextParcelLen. The fixed header's offset/count/max fields are updated. The inverse verifier decodes every declared array, checks all record extents, validates exact byte parity, rejects overlapping intervals and rejects nonzero unowned bytes between sections or after the final section.

Known unsupported icon, voice and Huffman index offsets/counts already present in a source header are **rejected** instead of silently overwritten. Original header bytes outside explicitly owned fields are not modified.

### src/sdal_builder/oem_global_media_file.py

A deterministic, physical Global Media File composer. Its ReferenceSource objects require actual caller-encoded, nonempty reference data bodies and explicit index/description offsets and record-end extents. The composer:
1. Determines index length from the supplied GlbMediaHeader_t and invokes the real index writer.
2. Reserves both exceptional bootstrap parcels first.
3. Assigns the physically smallest fitting size-index from the **same** authoritative ucaParcelSizes table used by Iter023; all subsequent data parcels are region-zero PclHdr_t containers.
4. Generates actual 32-bit direct ParcelIDs and the matching RefDataIndex_t entries, never requiring the caller to invent physical addresses.
5. Publishes the complete binary image and independently re-reads every reference table, PID, physical region, content byte and unused capacity.

This produces **real, self-consistent global file bytes for the supported supplied reference-data set**. It does not fabricate the semantic contents of any missing SDAL source dictionary. A working Denso database requires all relevant dictionaries and internal record-format verification, which is an open dependency.

### Regional index-root relationship

The Global Media Header's external bitmap defines the order and count of root ParcelIDs recorded in the Region Global Data's second parcel (§2.4.1.2). The new verifier converts bits to the documented MSB-first index sequence, requires exact cardinality and checks that spatial index types 0–7 point at the **same physical type-255 Global KD parcel**. When a full region file is supplied, it independently validates real PclHdr PIDs, region number and exact Global KD root-table structure. This now tests a direct binary link **Global Media Header → Regional Global KD**.

## Original-file qualification

The original files supplied include INIT.SDL, BENELUX0.SDL, SWIAUS0.SDL and others, but there is no independently confirmed region-zero file actually named 0.SDL in the currently identified donor set. In particular the original INIT.SDL does **not** have a valid ucParcelSizeCount at the specified byte position 1250 if interpreted as GlbMediaHeader_t. Its filename is not a basis for reinterpreting the bytes with this unrelated structure. The new production codecs therefore deliberately do **not** claim exact original-file global-media byte parity.

The generated-code evidence uses synthetic but complete 2048-byte media-core fixtures, physically indexed region-zero reference parcels, and a real generated type0/type1/type255 regional byte stream from Iter023. The reference bodies in tests are generated test data and demonstrate **physical index consistency only**; they are not presented as legitimate complete feature-type/catalog semantics.

## Acceptance and negative evidence

The new generated-source tests cover:
- Header preservation outside all specifically owned field ranges;
- 256×4-byte normalized attribute exact packing, PSF identity/date, bitmaps, node costs, vendor mask;
- 4/8/12/16-byte index records, physical offset/count fields and authentic 2048-byte bootstrap split;
- Referenced global parcels with region-zero PclHdr_t, the same parcel sizes and physical addresses as the table;
- Metadata level-to-module relationships and caller-authorized metadata hash;
- Locale size and invalid ligature pointers; no invented compression trees;
- Malformed index offsets, overlapping intervals, corrupted PIDs, corrupted payload bytes, missing targets, bad reference ordering, unaddressable indexes and absent index families;
- Global Media bitmap → physically valid generated regional Global KD root; intentional root header corruption;
- Unmodified Linux/macOS hybrid ISO mastering and accumulated earlier OSM-to-SDAL binary tests.

No original copyrighted SDAL parcel content is committed.

## What is still required for a complete OSM → Denso disc

1. Build full Global Media Header semantics, including the as-yet unspecified generic-reference array cardinality from an authoritative source, original-reproducible icon/Huffman/metadata procedures, and complete real reference data catalog record serializers.
2. Implement the actual Region Global Data first/second bootstrap parcel producers, including GlbMapHeader_t and ordered root ParcelID arrays, and all remaining nonspatial indexes.
3. Complete type0/1 cartography and routing payload families, OSM clipping/ghost nodes, turn restrictions, POI/text/catalog links, SZIP compression authority and true normal-attribute dictionaries.
4. Integrate the complete graph into existing main.py and build.sh, run a strict generated-dataset reference audit, master with the existing verified ISO backend, and test load/render/search/routing on the physical Denso device.

These are functional dependencies, not placeholders or compatibility hacks. Iter024's CI green result proves the supported binary encoders and checks on generated sources, **not universal SDAL compatibility or Denso hardware acceptance**.

## Verification

    python3 -m unittest discover -s tests -p 'test_oem_*.py' -v

No private OEM source needs to be checked into GitHub. The untouched original global/region files may be audited separately when their exact catalog roles and headers can be independently identified.

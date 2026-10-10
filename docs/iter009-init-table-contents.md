# Iter009 — internal content of the nine INIT table pairs

## Evidence

This iteration examines original, user-supplied **OLDER_1**, **OLDER_2**, and **WE_06Q4** OEM discs (21 SDL files total). Generated 0.SDL is not included as source evidence.

The read-only tool `tools/oem_init_pair_tables.py` was run successfully against the three original donor directories; the private source files are excluded from this repository. Its evidence outputs are JSON/Markdown, preserving descriptor addresses, SHA-256 hashes, number of nonzero BE32 words, and observed cross-file byte comparisons without publishing proprietary SDL payloads.

## Nine linked groups, each with two different tables

`INIT` contains **nine** contiguous pairs selected by the following descriptor locations:

- Group 0: `INIT+0x40` and `INIT+0x48`.
- Groups 1–8: `INIT+0x1C0+16*i` and `INIT+0x1C8+16*i`, for i=0…7.

Every group consists of:

- One 0x19C-byte segment, **103** big-endian four-byte words.
- One 0x1800-byte segment, **1536** big-endian four-byte words.

The start of each later segment equals the end of its predecessor, and the ninth group's final segment ends 0x184 bytes before the end of INIT in all three discs. These are observed structural facts, not guesses about boot order.

## Repeated word patterns across the three OEM releases

The **first seven BE32 words** of every 0x1800 segment are equal to each other (seven repeated copies). This holds for all 27 original pairs, giving 27 successful individual word-repetition checks.

| Original release | Group 0 repeated word | Groups 1–8 repeated word |
|---|---|---|
| OLDER_1 | `0x38000020` | `0x380000C2` |
| OLDER_2 | `0x38000020` | `0x480000C2` |
| WE_06Q4 | `0x38000020` | `0x480000C2` |

In group 0, the repeated word `0x38000020` is **byte-identical to the 4-byte word at offset 0x2000 in both CARTOTOP.SDL and BENELUX0.SDL** for all three donors.

However, for the eight later groups, interpreting the lower 24 bits as a physical offset gives `0xC200`. The source word at `0xC200` in either CARTOTOP or BENELUX0 **does not match** the group repeated word in any of the three releases. Therefore the later groups are **not** independently validated as direct self-file parcel-header pointers. Applying the usual ParcelID address formula as if all such words had confirmed file/region provenance would be an unsupported assumption.

The initial BE32 word of the group-0 0x19C segment is `0x00000000` in all three releases. Each of groups 1–8 starts with a **0x68xxxxxx** word that varies by group and release. Do not assume a CRC, parcel identity, object count, or location without further evidence.

## Content actually varies despite fixed table extents

No corresponding complete 0x19C or 0x1800 segment has an identical SHA-256 across different OEM releases, based on the pairwise comparison of all three source sets. The extents and initial structural markers are stable, while the full serialized content is release-dependent. A correct writer cannot simply retain one release's 0x1800 payload.

The source tool also reports the number of zero/nonzero BE32 values, per-group SHA-256, descriptor location, and candidate address *without interpreting undecoded payload*.

## Validation and limitations

The full evidence analysis returned PASS for its nine structural assertions on **each** original release. Six independent synthetic regression tests also passed locally, including deliberate mutations in descriptor chaining, repeated marker words, and source-header comparison. The GitHub CI runs this regression file as part of the cumulative suite. Local forensic analysis and GitHub CI are separate evidence channels: CI does not contain OEM binaries.

Re-run against the user's unmodified files:

    python3 tools/oem_init_pair_tables.py \
      --release OLDER_1=/path/to/older1 \
      --release OLDER_2=/path/to/older2 \
      --release WE_06Q4=/path/to/we \
      --json verification/iter009-original-evidence.json \
      --md verification/iter009-original-evidence.md

This work does not assign a functional name to the paired tables or establish their ownership, reference targets, an OEM loader, ucaParcelSizes, or head-unit/ISO acceptance. It makes no changes to the OSM encoder, parcel writer, or physical-media layout.

## Next bounded investigation

Study the relationship between entries of the 0x19C metadata segments and the 1536-word segments by exact in-release correspondence, then compare their observed values against the regional and CARTOTOP records. Infer record formats only when every assigned field has byte-level support on all three releases.

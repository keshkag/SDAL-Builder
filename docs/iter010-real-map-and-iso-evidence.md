# Iter010 — first actual cartographic SDL1 corpus and OEM ISO evidence plan

## Authoritative inputs

For the first time the evidence set includes the **real 350,914,560-byte map payload** `BENELUX1.SDL`, supplied in a ZIP, and a second genuine region-index file `DENSWE0.SDL` (319,488 bytes). Also compared to the previously supplied same-release `BENELUX0.SDL` and `INIT.SDL`.

The ZIP contains exactly one SDL map file. The original BENELUX1 payload has SHA-256 `223ece00295c2befe7ecbe515e6665e6fddfacb7e179617a407afdc8e0b3458f`. DENSWE0 has SHA-256 `5a6062f3a10c045b94ba7f59475acfae3a7cb8827aaecc91c2606259402a5d6d`.

No OEM binaries or downloaded map assets are committed to the Git repository.

## High-confidence byte relationships

- `BENELUX1.SDL` begins with nontrivial records and the ASCII string `benelux_tm` at 0x100.
- At 0x2000, it contains a **PclHdr_t-shaped record** with Parcel ID `0x49000020`, type **24 (Map Header)**, region 1, BE encoding, and its low 24-bit offset referring to 0x2000 when multiplied by 256. The ID has the *redundancy bit* set; a scanner that discards all bit-30-set candidates is incomplete.
- Subsequent aligned data contains many candidates of types **1, 2, 3, 6, 10, 11, 17**, plus numerous other types. Several candidate profiles use nonzero compression type fields. Do not infer the exact number of complete valid parcels from an address-aligned signature scan: payload bytes can cause incidental matches.
- At 0x800 within BENELUX1, seven BE32 words `0x480000C2` appear consecutively.
- The same seven-word signature appears at the beginning of each of the **eight later 0x1800-word-pool regions** in INIT.SDL from WE_06Q4 (previously observed in Iter009).
- **The lower 24 bits of `0x480000C2` identify 0xC200** under the empirically verified 256-byte address unit. At **BENELUX1+0xC200** the actual 20-byte structure begins with that exact Parcel ID, has type **255** and region **1**. This is the first cross-file INIT→real SDL1 **identifier/target-header alignment** demonstrated directly on the OEM bytes. It does not prove how a head unit dereferences it or whether its contents are fully validated.
- The previously provided second older disk has this same word marker in its INIT, but this BENELUX1 is from WE_06Q4; we cannot assert that the second older disc's 1.SDL target is identical.

## DENSWE0 is not established to be a density overlay

The authentic DENSWE0 and BENELUX0 files share the following observed layout:

- File size 319,488 bytes
- 8,192-byte prefix + **19 sections of 16,384 bytes**
- Each aligned section begins with a type-19, region-0, size-index-56 header candidate
- **29 non-uniform 4KiB blocks** are byte-identical at corresponding offsets
- The first byte difference is at offset **1029** (0x405)
- DENSWE0 contains readable labels including `SVERIGE`, which is consistent with the filename's Denmark/Sweden regional grouping

This is **regional global-data/index content**, not proof of a simple numeric density overlay. The exact semantics of its first 8KiB and record tables are still unresolved.

## Gap audit against the existing end-to-end OSM→ISO pipeline

`build.sh` is the existing one-command orchestrator for setting up the Python environment, downloading/processing OSM regions, producing SDL files and assembling a resulting ISO. Iter010 **preserves it unchanged**.

The current implementation has verifiable differences from this OEM corpus:

1. `src/sdal_builder/main.py` generates `DENS...0.SDL` by serializing a count into a short parcel. Genuine DENSWE0 in this sample is a 319,488-byte regional *0 container with 19 structured 16KiB sections. Name collision does **not** establish content compatibility.
2. `src/sdal_builder/encoder.py` sets externally-referenced/redundancy flags using shifts **27/28** in its `pid==0` branch, whereas the supplied SDAL 1.7 specification explicitly uses bits **31/30**. The authentic BENELUX1 first Map Header sets bit 30. Any fix must also account for callers passing an already composed nonzero Parcel ID.
3. The current serializer's main regional writer uses 4,096-byte units (`unit_shift=12`); the observed OEM map and global index headers use address units of **256 bytes** for their validated low24 offsets. A universal 4,096-byte representation cannot reproduce the observed OEM addresses.
4. The current ISO writer uses `pycdlib.new(vol_ident=..., interchange_level=3)`; this establishes ISO creation but does **not** prove physical-file ordering, volume identifiers, directory sectors or other characteristics match the working Denso OEM DVD.
5. The spec describes parcel limitations and actual compression types; simply producing a 20-byte `PclHdr_t` or a nominal 64KB chunk is not sufficient for OEM validation. No compression compatibility or routing correctness is yet established on a head unit.

These are **engineering acceptance blockers**, not a claim that the existing single-command pipeline was removed. Iter010 deliberately does not silently rewrite OSM processing, the map generator, `build.sh`, or the ISO writer before real object semantics are established.

## OEM ISO minimal intake — Mac/Linux

**Do not edit ISO binaries in vi.** Extract unchanged byte ranges:

```bash
dd if="/path/to/original-oem.iso" of="OEM_ISO_first_1MiB.bin" bs=2048 count=512
tail -c 1048576 "/path/to/original-oem.iso" > OEM_ISO_last_1MiB.bin
shasum -a 256 OEM_ISO_first_1MiB.bin OEM_ISO_last_1MiB.bin
zip OEM_ISO_edges.zip OEM_ISO_first_1MiB.bin OEM_ISO_last_1MiB.bin
```

The first fragment covers system-area bytes, ISO9660 descriptors beginning at sector 16 (byte offset 0x8000), and the initial directory/file-system sectors. The final fragment can reveal end-of-volume/UDF or format-specific structures. A whole ISO is not needed at this stage. If the actual ISO's filesystem metadata or critical file extent starts outside these two fragments, a more specifically located sample may be requested after first-pass decoding. An image copied from a physical DVD may include nonstandard session/track details that a filesystem-only file listing cannot reveal.

An ISO generated by SDAL Builder must be inspected **separately**, then compared to the original OEM ISO. A header fragment alone does not certify successful device loading; that ultimately also depends on mastering, disc type and drive behavior.

## Execute the source-evidence tool

```sh
python3 tools/oem_real_map_probe.py \
  --init /path/to/WE_06Q4/INIT.SDL \
  --benelux0 /path/to/WE_06Q4/BENELUX0.SDL \
  --denswe0 /path/to/DENSWE0.SDL \
  --benelux1 /path/to/BENELUX1.SDL \
  --output verification/iter010-original-map.json
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

It records original hashes, candidate types/profiles, full source header fields, shared SDL0 blocks, and the `0x480000C2` aligned target candidate. It does not emit SDL bytes, synthesize parcels, or generate any ISO.

## Next bounded work

Decode specific type-24, type-255 and type-1/3 parcel headers and their internal indices; validate contents and references against actual BENELUX1. Next, compare native ISO9660/UDF/media structure with the current output. Only then surgically correct producer-side parcel ID composition, region metadata ownership, and the ISO master layout while retaining the established one-command `build.sh` workflow.

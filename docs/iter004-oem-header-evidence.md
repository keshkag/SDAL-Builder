# Iter004 — verified header positions versus unknown parcel sizes

## Scope

This iteration adds a **read-only** forensic scanner and tests. It does
not modify the existing OSM encoder, cartography writer, ISO packager,
firmware or vehicle.

The input is the user's original WE_06Q4 sample:
`INIT.SDL`, `BENELUX0.SDL`, `FRANCE0.SDL`, `CARTOTOP.SDL`.

## Format authority and proof level

SDAL 1.7 **section 1.2.4.3** defines the 20-byte `PclHdr_t`
layout. **Sections 1.2.4.5 and 1.4.0.2** define the 32-bit
`ParcelID_t` fields: external-to-region bit, redundancy bit, 6-bit
size index, and 24-bit file offset in `2^usBlockSize` bytes.

On this donor's inspected record candidates a sector unit of
**256 bytes** correctly resolves the low-24-bit offset to its
physical byte position. This is *observed in the donor*, not a
universal constant of the SDAL format.

On the supplied OEM bytes the profile matches:

| Source | Candidate offsets | Type | Region | Size indices |
|---|---|---:|---:|---|
| BENELUX0 | 0x2000 + 0x4000 * i, i=0…18 | 19 | 0 | 56, all 19 |
| FRANCE0 | 0x2000 + 0x4000 * i, i=0…18 | 19 | 0 | 56, all 19 |
| CARTOTOP | 0x2000 | 255 | 1 | 56 |
| CARTOTOP | 0x6000 | 1 | 1 | 56 |
| CARTOTOP | 0xA000 | 1 | 1 | 46 |
| CARTOTOP | 0x12000 | 1 | 1 | 0 |

The scan checks the narrow **observed** combination of type, region,
descriptor, zeroed compression-related fields, big-endian byte layout,
and self-addressing. It is **not** a general-purpose SDAL parser.

There is evidence of different parcel size indexes in `CARTOTOP`
despite known start positions. `ucaParcelSizes[]`, whose meaning is
described by SDAL 1.7 Global Media Header in section 2.1.1, has **not**
yet been decoded and linked to this donor. Accordingly, even a known
distance to the next candidate is not a proven parcel length.

**Important:** the candidate header's `usCmpDataUncompSize` and other
compression-related fields are frequently zero even when the following
16-KiB section contains substantial nonzero bytes. Do not reconstruct
size/compression from those zeros, or consider the 16-KiB spacing a
sufficient explanation of the payload.

## Independent byte-copy verification

Exactly 16,384 source bytes at these locations are equal:

| INIT.SDL destination | BENELUX0.SDL source | Bytes |
|---:|---:|---:|
| 0x6000 | 0x2000 | 16384 |
| 0xA000 | 0x6000 | 16384 |
| 0xE000 | 0x16000 | 16384 |

The parcel-ID address within copied INIT sections still references the
**BENELUX0 source address**, not their INIT destination. Requiring
self-addressing of all INIT bytes would thus reject known OEM input.

These findings demonstrate relocated binary reuse, **not** the semantics
of a boot sequence, nor evidence of an executable loader.

## Reproduce on original OEM corpus

```sh
python3 tools/oem_header_evidence.py /path/to/oem \
  --output-json verification/iter004-evidence.json \
  --output-md verification/iter004-evidence.md
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

CI validates syntax and independent synthetic regressions.
**CI has no access to the real donor bytes.** Exact-OEM profile verification
is a separate action against the user-supplied source data.

Next priority is obtaining or independently decoding the authoritative
global parcel-size table and its header pointer, *then* resolving
content/record sizes. Do not implement a production writer from these
header candidates alone.

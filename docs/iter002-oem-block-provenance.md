# Iter002 — exact non-uniform block provenance (WE_06Q4)

## Evidence and scope

Analysis used the **seven original files supplied by the user** (not generated output):
`INIT.SDL`, `MTOC.SDL`, `REGION.SDL`, `REGIONS.SDL`,
`CARTOTOP.SDL`, `BENELUX0.SDL`, `FRANCE0.SDL`.

Run against the same corpus:

```sh
python3 tools/oem_block_provenance.py \
    OEM/INIT.SDL OEM/MTOC.SDL OEM/REGION.SDL OEM/REGIONS.SDL \
    OEM/CARTOTOP.SDL OEM/BENELUX0.SDL OEM/FRANCE0.SDL \
    --output-json verification/oem-block-provenance.json \
    --output-md verification/oem-block-provenance.md
python3 -m unittest discover -s tests -p 'test_oem_*.py' -v
```

This compares **only complete 4096-byte blocks that contain more than one byte
value**; uniform zero / 0xFF filler and partial blocks do not count. SHA-256
nominates matches, and equality of the actual bytes is required.

## Exact observations

**INIT ↔ BENELUX0:** 13 matching information-bearing blocks (= 53,248 bytes)
at three aligned runs:

| INIT.SDL start | BENELUX0.SDL start | Run |
|---|---|---:|
| 0x1000 | 0x1000 | 1 block / 4,096 bytes |
| 0x6000 | 0x2000 | 8 blocks / 32,768 bytes |
| 0xE000 | 0x16000 | 4 blocks / 16,384 bytes |

**BENELUX0 ↔ FRANCE0:** 18 full nonuniform same-offset blocks
(73,728 bytes), in two runs:

| Start in both files | Run |
|---|---:|
| 0x1A000 | 14 blocks / 57,344 bytes |
| 0x4A000 | 4 blocks / 16,384 bytes |

The regional files also contain two identical **all-zero** 4096-byte blocks at
0x48000 and 0x49000; excluded from information-bearing evidence.
The first byte difference between BENELUX0 and FRANCE0 is at 0x439 (1081).

**REGION ↔ REGIONS:** identical entire file, 4096 bytes, as reported in Iter001.

**CARTOTOP:** no entire *nonuniform* 4096-byte block matches another file in
this seven-file sample. This does not preclude internal links at record level.

The apparent common content (including readable POI/category text in some
regions) is strong evidence of *reuse of binary data*. It does not prove these
blocks are region pointers, boot loader binaries, global media headers, or
replaceable templates.

## Root-cause implication for the writer

Do not generate INIT and regional `*0.SDL` as unrelated buffers. First
reconstruct shared data ownership and the rules that place the same content
at different offsets, then create a single logical source of that content in
the serializer. Do not mechanically splice OEM bytes into unrelated generated
datasets.

## Limits and next step

This method does not detect shared *unaligned* content or shifted individual
records. The next bounded investigation should decode the common chunk
headers/lengths and locate verified indexes/references before synthesizing
any boot or cartographic objects. To follow pointers from index layers to
large map payloads, small byte ranges from an original `*1.SDL` may eventually
be needed. No additional sample is required for this step.

# Iter001 — OEM WE_06Q4 forensic observations

This report is derived from seven binary user-supplied OEM files. It contains observations only, **not** a certification of OEM boot compatibility.

| File | Bytes | SHA-256 prefix |
|---|---:|---|
| INIT.SDL | 172032 | 7615eb71b291 |
| MTOC.SDL | 4096 | e8105af91e0b |
| REGION.SDL | 4096 | 26a30fa32698 |
| REGIONS.SDL | 4096 | 26a30fa32698 |
| CARTOTOP.SDL | 184320 | e9d8493c20d1 |
| BENELUX0.SDL | 319488 | dab51e844742 |
| FRANCE0.SDL | 319488 | f7b4b0feb3b3 |

## Verified byte relationships

- `REGION.SDL` and `REGIONS.SDL` are byte-for-byte identical (4096/4096).
- `MTOC.SDL` contains 34 contiguous observed 68-byte entries. Entry base starts at 0x40; first filename at 0x48; next at 0x8C; 34th at 0x90C.
- Every entry contains a zero-terminated filename in a 16-byte field beginning at base+8. Some unused bytes in this field are **nonzero**, so they must not be assumed to be padding.
- A four-byte word at base+24, read as BE32, is `0x52000001` for BENELUX1.SDL, `0x52000002` for FRANCE1.SDL, etc. Its high byte groups observed entries as 0x52 (8), 0x43 (1), 0x5A (8), 0x4B (1), 0x56 (16); its low 24 bits take sequential values 1 to 34. The *OEM meaning* of these fields has not yet been proven.
- The entire 34-entry record array in `MTOC.SDL` matches the array in `INIT.SDL` at absolute offset 0x12000. The whole first 0x94C bytes match; the first differing byte is at relative 0x94C (absolute INIT offset 0x1294C). There are 616 mismatched byte positions in the compared 4096-byte windows. **Do not treat MTOC as an exact copy of the entire window.**
- `BENELUX0.SDL` and `FRANCE0.SDL` both measure 319488 bytes, but their bytes diverge beginning at offset 1081. This is evidence of shared layout, not proof of what any field means.
- The provided MTOC names refer to 34 files including large cartographic files not contained in this seven-file sample; that does not mean the OEM disc lacks them.
- `REGION.SDL` begins with ASCII `SDAL`; `INIT.SDL` **does not**. Do not fabricate an ASCII SDAL signature for INIT.

## Implementation boundary

Only reconstruct a field after matching it against OEM bytes and cross-references. Maintain observed bytes and undecoded areas distinctly. Initial analysis does not claim to identify the firmware boot loader, ISO physical layout or required media security checks. Do not publish the proprietary donor SDL binary contents into this repository.

## Next evidence needed

An original mapped cartographic data file or a small sample plus `KDTREE.SDL`, after verifying the exact cross-file offsets in INIT and CARTOTOP. A complete OEM ISO is not needed for the current decoder work, but would be needed later to study disc ordering and sector layout.

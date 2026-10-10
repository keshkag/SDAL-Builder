# OEM SDL corpus inventory — Iteration 001

This is a **read-only evidence capture** step toward an OEM-specific SDAL decoder.
It does not attempt to identify binary fields, reconstruct DVD boot order, or certify
that a synthesized SDL is compatible with any head unit. The corpus is never modified.

## Run

Provide an **extracted directory** from a legally obtained original OEM SDAL disc
with its directory structure intact. No user-side parsing or preprocessing is needed.

```sh
python3 tools/oem_inventory.py /path/to/extracted_oem_disc --output oem_inventory.json
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

The deterministic JSON includes SHA-256, size, nonzero byte counts, one 4096-byte
block-density record per block, and occurrences of *printable strings* that look
like `*.SDL` filenames. These filename occurrences are **unverified candidates**,
not decoded OEM table references; the existence check only compares basenames.
All offsets are file byte offsets, not sector addresses or parcel IDs.

## Required evidence for the next phase

A full, untouched OEM source image (ISO, BIN/CUE where applicable), or an extracted
complete corpus. In particular, include INIT.SDL, MTOC.SDL, REGION.SDL,
REGIONS.SDL, 0.SDL, cartographic regional SDLs, and adjacent index/routing files
when present. The exact names may differ between releases. A second OEM release
is useful but not required to start.

A future decoder must establish field widths, endianness, offsets, reference
semantics, and bootstrap ordering independently before generating new records.
Generated outputs cannot be OEM-certified without actual device testing.

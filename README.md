
# SDAL Builder – **Full working prototype**

This repository converts an **OpenStreetMap .osm.pbf** extract into a *fully‑structured* SDAL
Physical Storage Format (PSF) disc image.  The prototype supports:

* Roads (geometry + names) packed into *cartographic* and *navigable* parcel families.
* A two‑level **KD‑tree** spatial index written into its own parcel.
* A sparse **B+‑tree** mapping original OSM way IDs → byte‑offset of the link record.
* Parcel‑level *Huffman + CRC‑32* compression exactly as described in SDAL PSF v1.7.
* ISO‑9660 mastering with `0.SDL` global + `n.SDL` region files.

Quick start builds Cyprus:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python sdal_build.py --region europe/cyprus --out cyprus.iso
```

All heavy work happens inside native‑code extensions already shipped with the Python libraries,
so no separate C/C++ compiler is needed.

See `docs/` for spec notes and record layouts.

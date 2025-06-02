# SDAL Builder

> **⚠️ WARNING: This is a new and experimental solution. The codebase is untested in production environments and under active development. Use at your own risk, and always validate output before deploying or integrating into other systems! Bug reports and test feedback are very welcome.**

**SDAL Builder** is an advanced, modular Python toolchain for building [SDAL Parcel Storage Format (PSF) v1.7](#sdal-parcel-storage-format-psf-v17) map archives from OpenStreetMap (OSM) data extracts.  
It is designed for researchers, navigation developers, and simulation projects needing highly compressed, spatially indexed, verifiable map data—directly from OSM `.pbf` files.

---

## Table of Contents

- [Features](#features)
- [Architecture Overview](#architecture-overview)
- [Data Flow (How it Works)](#data-flow-how-it-works)
- [Installation](#installation)
- [Usage](#usage)
- [Burning SDAL ISO Images](#burning-sdal-iso-images)
- [Cleaning Up](#cleaning-up)
- [File Structure](#file-structure)
- [Frequently Asked Questions](#frequently-asked-questions)
- [SDAL Parcel Storage Format (PSF) v1.7](#sdal-parcel-storage-format-psf-v17)
- [License](#license)
- [Credits](#credits)

---

## Features

- **End-to-end OSM to SDAL pipeline**: Fully automates download, parsing, indexing, compression, and ISO packaging.
- **Parcels & Indexes**: Packs cartographic and navigable data into SDAL parcel "families"; builds spatial (KD-tree) and OSM Way ID (B+-tree) indexes.
- **Parcel-level Huffman compression** and CRC-32 checksums for integrity.
- **Density overlays**: Optional per-region density data for visualization or QA.
- **Modular source code**: Clear separation of ETL, encoding, spatial indexing, ISO writing.
- **CLI-driven with robust logging**: For reproducible, scriptable builds.
- **Format compliance**: All output strictly follows SDAL PSF v1.7 specification.

---

## Architecture Overview

The project is structured as follows:

| Module              | Description                                                                 |
|---------------------|-----------------------------------------------------------------------------|
| `main.py`           | CLI entrypoint. Orchestrates the pipeline: OSM download, extraction, build. |
| `etl.py`            | Extracts, transforms, and loads OSM road and POI data via Pyrosm/Geopandas. |
| `encoder.py`        | Encodes roads, POIs, overlays, and metadata into compact SDAL binary blobs. |
| `spatial.py`        | Builds and serializes spatial (KD-tree) and OSM Way ID (B+-tree) indexes.   |
| `iso.py`            | Assembles all parcels and writes the SDAL-compliant ISO archive.            |
| `constants.py`      | SDAL Parcel IDs, version codes, and related constants.                      |

---

## Data Flow (How it Works)

Below is a high-level walkthrough of what happens when you build an SDAL ISO:

| **Step**      | **What Happens**                                                                                      | **Main Modules**         |
|---------------|------------------------------------------------------------------------------------------------------|--------------------------|
| 1. Download   | OSM `.pbf` for the specified region is fetched from [Geofabrik](https://download.geofabrik.de/)      | `main.py`                |
| 2. ETL        | Roads, POIs, geometry, and attributes are extracted, cleaned, and normalized                         | `etl.py`                 |
| 3. Encoding   | Roads, POIs, overlays are encoded into cartographic & navigational parcel families                   | `encoder.py`, `constants.py` |
| 4. Indexing   | 2-level KD-tree (spatial) and sparse B+-tree (OSM way ID → record offset) are constructed            | `spatial.py`             |
| 5. Compression| Each parcel is compressed using Huffman coding, then CRC-32 checksums are computed                   | `encoder.py`             |
| 6. Packaging  | All data and indexes are packed into a single ISO image per SDAL PSF v1.7                            | `iso.py`                 |

**Visualization:**

```
[OSM .pbf] 
   ↓
[ETL (roads, POIs)]
   ↓
[Parcel Encoding] —→ [KD-tree Index] —→
   ↓                  [B+-tree Index]     → [ISO Packaging + Compression] → [SDAL ISO]
[Cartographic/Navigation Parcels]
```

---

## Installation

**Requirements:**  
- Python **3.9+**
- Basic build tools (for dependencies like numpy, shapely, pyrosm)

**Install Steps:**

```sh
# Clone and enter the project directory
git clone https://github.com/yourname/sdal_builder.git
cd sdal_builder

# Set up a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

You may need system libraries for certain geospatial packages:

- On Ubuntu/Debian:  
  `sudo apt install python3-dev libspatialindex-dev`

---

## Usage

### 1. Building an SDAL ISO

**With the helper script:**
```sh
./build.sh <region> [region2 ...] [output.iso]
```
- Example:
  ```sh
  ./build.sh europe/cyprus
  ./build.sh europe/cyprus europe/spain my_maps.iso
  ```

**Direct Python (advanced/CI use):**
```sh
python sdal_build.py <region> [--out <output.iso>]
```
- Example:
  ```sh
  python sdal_build.py europe/germany --out germany.iso
  ```

- **Region names** use [Geofabrik region naming](https://download.geofabrik.de/).

### 2. Validating an SDAL ISO

After building, you can validate ISO file integrity:
```sh
python validate_sdal_iso.py my_maps.iso
```

---

## Burning SDAL ISO Images

To ensure maximum compatibility, always use a reliable ISO writing tool and avoid using "quick burn" or "multi-session" options.

**Recommended steps:**

1. **On Linux/macOS:**  
   Use `dd` (replace `/dev/sdX` with your USB/SD/DVD device, and double-check your target!):
   ```sh
   sudo dd if=your_output.iso of=/dev/sdX bs=4M status=progress && sync
   ```

2. **On Windows:**  
   Use a trusted tool like [Rufus](https://rufus.ie/) or [balenaEtcher](https://www.balena.io/etcher/) and select the "ISO image mode" (not "ISOHybrid" or other custom formats).  
   Be sure to fully erase/re-format your target media before burning.

3. **General recommendations:**
   - Always safely eject the device after writing.
   - Do not use tools that "modify" the ISO or add extra boot sectors unless specifically required.
   - Test the media on the intended target system before deployment.

> **Compatibility Note:**  
> SDAL ISOs created by this project follow the SDAL PSF v1.7 spec, but downstream system compatibility may depend on SDAL implementation details, media quality, and burn method. If you encounter issues, try a different burning tool or medium.

---

## Cleaning Up

To remove temporary files, caches, and build artifacts:

```sh
./build.sh --clean
```
This will:
- Remove Python bytecode caches
- Remove `.venv` (virtual environment)
- Remove build directories and `.iso` files

---

## File Structure

| Path                      | Purpose                                                 |
|---------------------------|--------------------------------------------------------|
| `sdal_build.py`           | Main entry script for SDAL ISO building (calls CLI)    |
| `build.sh`                | Bash helper for build and clean                        |
| `validate_sdal_iso.py`    | ISO validation/inspection tool                         |
| `src/sdal_builder/`       | All main builder modules (etl, encoder, spatial, etc.) |
| `requirements.txt`        | Python dependencies                                    |
| `pyproject.toml`          | Python build metadata                                  |
| `README.md`               | This file                                              |

---

## Frequently Asked Questions

**Q: Which regions are available?**  
A: Use any region or subregion supported by Geofabrik (see [list here](https://download.geofabrik.de/index-v1.json)). Example: `europe/cyprus`, `europe/germany`.

**Q: Does this generate DENSO* files?**  
A: No, this project outputs SDAL-compliant ISO archives only. (If DENSO compatibility is added later, document here.)

**Q: Can I use my own OSM .pbf file?**  
A: Yes. Place your `.osm.pbf` in `build/tmp` and specify the file via CLI if needed.

**Q: Does this include turn-by-turn routing?**  
A: No. While the navigational topology is included for routing engines, actual routing or navigation is not implemented.

---

## SDAL Parcel Storage Format (PSF) v1.7

This project builds archives strictly according to the [SDAL PSF v1.7 specification](https://example.com/sdal-psf-spec):

- **Cartographic and Navigable Parcels:**  
  Store road geometry, topology, and names in binary "families" for efficient loading.
- **Spatial Indexing:**  
  Two-level KD-tree enables fast spatial lookups for any geometry.
- **OSM Way Indexing:**  
  Sparse B+-tree provides byte-level addressability of any original OSM way.
- **Per-parcel Compression and CRC:**  
  Each parcel is Huffman-compressed and verified with a CRC32 checksum.
- **ISO Image Packaging:**  
  All parcels, indexes, and metadata are written to a single SDAL ISO image.

---

## License

[MIT License](LICENSE)

---

## Credits

- [Pyrosm](https://pyrosm.readthedocs.io/)
- [Geopandas](https://geopandas.org/)
- [Shapely](https://shapely.readthedocs.io/)
- [OpenStreetMap contributors](https://www.openstreetmap.org/)
- SDAL PSF v1.7 community

---

*For bug reports, contributions, or advanced documentation, please open an issue or pull request!*

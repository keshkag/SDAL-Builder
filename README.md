# SDAL Builder

> **⚠️ WARNING: This is a new and experimental solution.**  
> The codebase is **untested on real devices** and under active development.  
> Use at your own risk: the worst case is usually the loss of a blank disc, but please be careful.  
> Bug reports and test feedback are very welcome.

**SDAL Builder** is an advanced, modular Python toolchain for building [SDAL Parcel Storage Format (PSF) v1.7](#sdal-parcel-storage-format-psf-v17) map archives from OpenStreetMap (OSM) data extracts.  
It is designed for researchers, navigation developers, and simulation projects needing highly compressed, spatially indexed, verifiable map data — directly from OSM `.pbf` files.

---

## Table of Contents

- [Features](#features)
- [Supported Vehicle Platforms](#supported-vehicle-platforms)
- [Architecture Overview](#architecture-overview)
- [Data Flow (How It Works)](#data-flow-how-it-works)
- [Installation](#installation)
- [Usage](#usage)
- [Choosing the OSM Processing Engine](#choosing-the-osm-processing-engine)
- [Burning SDAL DVDs (Windows / ImgBurn)](#burning-sdal-dvds-windows--imgburn)
- [Cleaning Up](#cleaning-up)
- [File Structure](#file-structure)
- [Frequently Asked Questions](#frequently-asked-questions)
- [SDAL Parcel Storage Format (PSF) v1.7](#sdal-parcel-storage-format-psf-v17)
- [License](#license)
- [Credits](#credits)

---

## Features

- **End-to-end OSM → SDAL pipeline:** Automates download, parsing, indexing, encoding, and ISO packaging.
- **Verified hybrid ISO filesystem mastering:** The final stage uses `genisoimage` or `mkisofs` with UDF and Joliet, verifies both UDF anchors, ISO directory extents and full SHA-256 parity of each SDL payload. This verifies storage, **not** Denso firmware compatibility. Install `genisoimage` on Debian/Ubuntu or `cdrtools` (`mkisofs`) on macOS before invoking the unchanged one-command `build.sh` workflow.
- **Structural compliance:** Generates structurally complete 512-byte headers (`GlbMediaHeader_t`, `RgnHdr_t`) with correctly populated PID size tables (`ucaParcelSizes`).
- **Configurable format mode:**
  - **OEM mode** (default) — maintains compatibility with custom table files like `REGIONS.SDL`.
  - **SDAL mode** — strict structural compliance, including full `RgnHdr_t` in regional files.
- **Streaming OSM processing:** Handles very large `.osm.pbf` files efficiently using Osmium-based streaming, with live progress reporting and minimal RAM usage.
- **Parcels & indexes:** Packs cartographic and navigational data into SDAL parcel families; builds spatial (KD-tree) and OSM Way ID (B+-tree) indexes.
- **Compression support:** Parcels are encoded using the `NO_COMPRESSION` (`0x01`) flag to ensure structural integrity and compatibility. Implementation of Huffman/SZIP algorithms is currently stubbed or removed.
- **Density overlays:** Optional per-region density data for visualization or QA.
- **Modular codebase:** Clear separation of ETL, encoding, spatial indexing, and ISO writing.
- **CLI-driven with robust logging:** For reproducible, scriptable builds.
- **Format compliance:** Output follows SDAL PSF v1.7 specification, especially in **SDAL mode**.

---

## Supported Vehicle Platforms

The SDAL format was historically used in the following car navigation systems:

| Car-maker            | Typical model/years with SDAL DVD drive                                                                         | Evidence / Reference          |
| -------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------- |
| Mazda                | 2001–2005 Mazda 3, Mazda 6, RX-8 (Kenwood / K303 “touch-screen” system)                                         | SatNaviShop                   |
| Saab                 | 2000–2006 9-3 / 9-5 with the ICM-2/ICM-3 navigation option                                                      | SatNaviShop                   |
| Ford & Lincoln       | Mid-2000s U.S. Ford Edge/Explorer and Lincoln MKX (Pioneer “AVIC-XD” DVD nav unit, aka Ford-Pioneer MFD)        | Ford Edge forum               |
| Toyota (incl. Lexus) | Early-2000s DVD-based nav systems; owners on Digital-Kaos and other forums look for “Toyota SDAL” update discs | Digital-Kaos forum, others    |

These platforms are **not officially supported** by this project. They are listed only as historical SDAL users and potential test targets.

---

## Architecture Overview

The project is structured as follows:

| Module                    | Description                                                                      |
| ------------------------- | -------------------------------------------------------------------------------- |
| `sdal_build.py`           | Main entry script for SDAL ISO building (CLI wrapper around `main.py`).         |
| `build.sh`                | Bash helper script for easy build and cleanup.                                  |
| `validate_sdal_iso.py`    | Utility to validate structural integrity of SDAL ISO images.                    |
| `src/sdal_builder/main.py`| CLI logic and pipeline management; orchestrates the full build.                 |
| `src/sdal_builder/etl.py` | Extracts, transforms, and loads OSM road and POI data via Pyrosm/Geopandas.     |
| `src/sdal_builder/sdal_osmium_stream.py` | Streaming OSM processing with Osmium for large files and efficient memory usage. |
| `src/sdal_builder/encoder.py` | Encodes roads, POIs, overlays, and metadata into compact SDAL binary parcels. |
| `src/sdal_builder/spatial.py` | Builds and serializes spatial (KD-tree) and OSM Way ID (B+-tree) indexes.    |
| `src/sdal_builder/iso.py` | Produces verified hybrid ISO9660/Joliet/UDF images, enforcing input-SDL byte parity. |
| `src/sdal_builder/constants.py` | SDAL Parcel IDs, version codes, and related constants.                     |
| `src/sdal_builder/routing_format.py` | Structures and encoding for routing parcels.                         |
| `src/sdal_builder/translations.py` | Localization tables for country name translation.                      |
| `src/sdal_builder/parcel_merge.py` | Helpers for merging tiles (e.g., for density layers).                 |

---

## Data Flow (How It Works)

High-level walkthrough of what happens when you build an SDAL ISO:

| Step | What Happens                                                                                          | Main Modules                           |
| ---- | ----------------------------------------------------------------------------------------------------- | -------------------------------------- |
| 1    | OSM `.pbf` for the specified region is fetched from [Geofabrik](https://download.geofabrik.de/).      | `sdal_build.py`, `main.py`             |
| 2    | Roads, POIs, geometry, and attributes are extracted, cleaned, and normalized.                         | `etl.py`, `sdal_osmium_stream.py`      |
| 3    | Roads, POIs, overlays are encoded into cartographic & navigational parcel families.                   | `encoder.py`, `constants.py`           |
| 4    | 2-level KD-tree (spatial) and sparse B+-tree (OSM way ID → record offset) are constructed.            | `spatial.py`                           |
| 5    | Each parcel is annotated with `NO_COMPRESSION` flag and validated with a CRC-32 checksum.             | `encoder.py`                           |
| 6    | All parcels and indexes are packed into a single ISO image according to SDAL PSF v1.7.                | `iso.py`                               |

**Visualization:**

```text
[OSM .pbf]
    ↓
[ETL (roads, POIs, geometry, attributes)]
    ↓
[Parcel Encoding (cartographic & navigational)]
    ├─→ [KD-tree Spatial Index]
    └─→ [B+-tree OSM Way Index]
           ↓
[ISO Packaging + Validation]
           ↓
       [SDAL ISO]
```

---

## Installation

### Requirements

- Python **3.9+**
- Basic build tools (for dependencies like `numpy`, `shapely`, `pyrosm`, `pyosmium`, etc.)

### Install Steps

```bash
# Clone and enter the project directory
git clone https://github.com/yourname/sdal_builder.git
cd sdal_builder

# Set up a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

The Osmium library and Python bindings (`pyosmium`) are required for streaming mode.  
You may need to install system packages:

- **Ubuntu / Debian**

  ```bash
  sudo apt install libosmium2-dev
  ```

- **macOS (Homebrew)**

  ```bash
  brew install osmium-tool
  ```

- **Windows**

  See the `pyosmium` documentation for up-to-date installation instructions.

---

## Usage

### 1. Building an SDAL ISO

The helper script `build.sh` provides a simple interface and accepts the format mode flag.

#### Using the helper script

```bash
./build.sh <region> [region2 ...] [output.iso] [--format-mode {OEM|SDAL}]
```

**Example (OEM Mode – default):**  
Uses custom OEM headers for control files (`REGION.SDL`, `MTOC.SDL`) and places map parcels directly at the start of map files (`XXX1.SDL`).

```bash
./build.sh europe/cyprus europe/spain my_maps.iso
```

**Example (SDAL Mode – strict structural compliance):**  
Enforces native SDAL headers for regional map files (`XXX1.SDL`), which will start with a 512-byte Region Header (`RgnHdr_t`) followed by alignment to the unit size.

```bash
./build.sh europe/germany --format-mode SDAL --out germany_sdal.iso
```

#### Direct Python usage (advanced / CI)

```bash
python sdal_build.py <region> [--out <output.iso>] [--format-mode {OEM|SDAL}]
```

Region names use Geofabrik-style naming, for example:

- `europe/cyprus`
- `europe/germany`
- `north-america/us/california`

### 2. Validating an SDAL ISO

After building, you can validate ISO file integrity:

```bash
python validate_sdal_iso.py my_maps.iso
```

This performs structural checks based on the SDAL PSF v1.7 layout.

---

## Choosing the OSM Processing Engine

### Default Behavior

The builder uses **Pyrosm** for small and medium regions, and automatically switches to **Osmium streaming** for large `.osm.pbf` files to reduce memory usage.

### Manual Selection

If your CLI exposes engine selection flags, you can override the default:

- To force **Osmium streaming** (recommended for files over ~2 GB):

  ```bash
  python sdal_build.py <region> --engine osmium
  ```

- To force **Pyrosm**:

  ```bash
  python sdal_build.py <region> --engine pyrosm
  ```

If these flags are not available in your build of the project, engine selection is automatic based on file size.

---

## Burning SDAL DVDs (Windows / ImgBurn)

Most Saab / Mazda SDAL navigation units are extremely picky about media and burn settings.  
Use good discs, correct booktype, and slow speed – otherwise the car will simply say **“NO DISC”**.

Below is the recommended procedure for burning SDAL images (e.g. `WE_06Q4.iso`) using **ImgBurn** on Windows.

### 1. Requirements

- **ImgBurn** 2.5.x or later
- Blank dual-layer DVD:
  - Prefer **Verbatim DVD+R DL**  
    (DVD-R DL can work, but booktype settings don’t apply there)
- A burner that supports changing **Book Type** (bitsetting) for DVD+R DL

### 2. Start ImgBurn and Load the Image

1. Launch ImgBurn.
2. Choose **“Write image file to disc”**.
3. Insert a blank DL disc.
4. Load the correct image:
   - If you have e.g. `WE_06Q4.MDS`, select the **`.MDS`** file, not the `.ISO`.  
     The `.MDS` holds proper layer-break information and is recommended in SDAL guides (especially for Mazda / Saab SDAL images).
   - If there is no `.MDS`, select the `.ISO` directly (e.g. `WE_06Q4.iso`).

### 3. Set BookType to DVD-ROM (for DVD+R DL)

This is critical for many SDAL nav drives – without **DVD-ROM** booktype they often won’t recognise the disc.

1. In ImgBurn, click the small **“book”** icon (Change Book Type) in the lower-right corner.
2. In the dialog:
   - Select your drive’s manufacturer.
   - **Change For** → `DVD+R DL Media`.
   - **New Setting** → `DVD-ROM`.
3. Click **Change**, confirm success, then **OK**.

If you are using **DVD-R DL**, booktype is fixed and this step doesn’t apply – but DVD+R DL with DVD-ROM booktype is strongly preferred.

### 4. Set Write Speed

SDAL nav units (Saab, Mazda, etc.) are known to dislike fast burns.

- **Recommended Write Speed:** `2x` or `2.4x`
  - Mazda SDAL Western Europe instructions explicitly say max `2x`.
  - Saab/Mazda SDAL users report best results with the lowest speed on Verbatim DL media.

In ImgBurn:

1. In the main window, set **Write Speed** to `2x` (or `2.4x` if `2x` isn’t available).
2. If the drive internally bumps it slightly, that’s usually OK.

### 5. Write Mode & Options

Make sure you’re burning a proper single-session disc, not using packet-writing.

- **Write mode:** Disc-At-Once (**DAO**)  
  SDAL guides explicitly state that incremental / packet writing makes discs unreadable in the car.
- **Finalize Disc:** Enabled (close track / session).  
  ImgBurn does this by default – don’t disable it.
- Leave other advanced ImgBurn settings at defaults unless you know exactly why you’re changing them.

### 6. Burn the Disc

1. Click the big **burn** button.
2. Let the burn finish without heavily using the PC (avoid causing buffer underruns).

Optionally allow ImgBurn to **Verify** after writing:  
this adds time but catches bad burns and marginal media.

### 7. Test in the Car

1. Start the car and let voltage stabilise (engine running is best).
2. Insert the disc into the nav drive.
3. Wait:
   - First boot after an update can take longer.
   - Some SDAL discs may perform a small firmware update during first use; **do not interrupt power**.

If the unit doesn’t see the disc at all (immediate “NO DISC” or ejection):

- Re-check:
  - Disc type (DVD+R DL, good brand).
  - Booktype = DVD-ROM (for +R DL).
  - Burn speed (`2x` / `2.4x`).
  - DAO + finalized.
- Try a different blank disc (same good brand), and/or a different burner.
- Confirm the drive still reads a known-good original nav disc – if not, the laser may be weak or dirty.

---

## Cleaning Up

To remove temporary files, caches, and build artifacts:

```bash
./build.sh --clean
```

This will typically:

- Remove Python bytecode caches.
- Optionally remove `.venv` (virtual environment), depending on your script implementation.
- Remove build directories and `.iso` files.

(Check the `build.sh` script to see exactly what it deletes in your version.)

---

## File Structure

| Path                                | Purpose                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------- |
| `sdal_build.py`                     | Main entry script for SDAL ISO building (calls CLI).                                             |
| `build.sh`                          | Bash helper script for easy build and cleanup.                                                    |
| `validate_sdal_iso.py`              | Utility to validate structural integrity of SDAL ISO images.                                     |
| `requirements.txt`                  | Python dependencies.                                                                              |
| `pyproject.toml`                    | Python build metadata.                                                                            |
| `README.md`                         | This file.                                                                                        |
| `src/sdal_builder/main.py`          | Orchestrator: CLI logic and pipeline management.                                                  |
| `src/sdal_builder/etl.py`           | ETL: extraction, transformation, and loading of OSM data.                                         |
| `src/sdal_builder/sdal_osmium_stream.py` | Stream processing helper for memory-efficient OSM parsing (Osmium).                         |
| `src/sdal_builder/encoder.py`       | Encoder: encodes parcel headers (`PclHdr_t`) and data bodies.                                    |
| `src/sdal_builder/spatial.py`       | Indexing: logic for building spatial (KD-tree) and ID (B+-tree) indexes.                         |
| `src/sdal_builder/iso.py`           | Packaging: assembles final ISO images using `pycdlib`.                                           |
| `src/sdal_builder/constants.py`     | Constants: SDAL PIDs, version codes, header structures.                                          |
| `src/sdal_builder/routing_format.py`| Routing: specific structures and encoding for routing parcels.                                   |
| `src/sdal_builder/translations.py`  | L10n: tables for country name localization / translation.                                        |
| `src/sdal_builder/parcel_merge.py`  | Utilities: helper module for merging tiles (e.g., for density layers).                          |

---

## Frequently Asked Questions

**Q: Which regions are available?**  

**A:** Any region or subregion supported by Geofabrik can be used.  
Examples: `europe/cyprus`, `europe/germany`.  
(See the Geofabrik download site for a full list.)

---

**Q: Does this generate DENSO files?**  

**A:** No. This project outputs **SDAL-compliant ISO archives only**.  
If DENSO compatibility is added later, it will be documented here.

---

**Q: Can I use my own OSM `.pbf` file?**  

**A:** Yes. Place your `.osm.pbf` file in `build/tmp` (or your configured working directory) and adjust the CLI arguments accordingly.

---

**Q: Does this include turn-by-turn routing?**  

**A:** No. While the navigational topology is included for routing engines, actual routing or navigation logic is **not** implemented in this project.

---

**Q: My machine runs out of memory on large OSM files!**  

**A:** Use the **Osmium streaming mode** for processing. It minimizes memory usage and provides progress updates.  
See [Choosing the OSM Processing Engine](#choosing-the-osm-processing-engine).

---

## SDAL Parcel Storage Format (PSF) v1.7

This project builds archives according to the **SDAL PSF v1.7** specification (to the extent currently implemented):

- **Full Structural Compliance (goal):**
  - Support generating files with complete, logically populated 512-byte headers:
    - `GlbMediaHeader_t` in `INIT.SDL`
    - `RgnHdr_t` in regional files
  - Correct index parcel layouts (e.g., global KD-tree parcels with properly structured `IDxPclHdr_t`).

- **Header Integrity:**
  - PID size tables (`ucaParcelSizes`) in `GlbMediaHeader_t` are populated with correct size indices (default `0` where appropriate).

- **Compression Note:**
  - Parcels are encoded using the `NO_COMPRESSION` flag to ensure maximum compatibility and structural integrity.
  - Integration of compression algorithms (Huffman, SZIP) is currently a placeholder or removed.

- **Cartographic and Navigable Parcels:**
  - Store road geometry, topology, and names in binary parcel families for efficient loading.

- **Spatial Indexing:**
  - Two-level KD-tree enables fast spatial lookups for geometry.

- **OSM Way Indexing:**
  - Sparse B+-tree provides byte-level addressability of any original OSM way.

- **Per-Parcel Integrity:**
  - Each parcel is verified with a CRC32 checksum.

- **ISO Image Packaging:**
  - All parcels, indexes, and metadata are written to a single SDAL ISO image.

Refer to the official SDAL PSF v1.7 documentation for exact binary layouts and field semantics.

---

## License

This project is licensed under the **MIT License**.  
See the `LICENSE` file for details.

---

## Credits

- **Pyrosm**
- **Pyosmium**
- **GeoPandas**
- **Shapely**
- **OpenStreetMap contributors**
- **SDAL PSF v1.7 community**

For bug reports, contributions, or advanced documentation, please open an **issue** or **pull request** in the repository.

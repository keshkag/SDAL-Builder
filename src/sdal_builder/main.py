# main.py

"""CLI for building SDAL ISO images per region, embedding PID 0 in MTOC.SDL and generating density overlays."""
import argparse
import logging
import pathlib
import sys
import json
import warnings
import os
import struct

import requests
import numpy as np
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, box
from tqdm import tqdm

from .constants import (
    CARTO_PARCEL_ID,
    NAV_PARCEL_ID,
    KDTREE_PARCEL_ID,
    BTREE_PARCEL_ID,
    DENS_PARCEL_ID,
    POI_NAME_PARCEL_ID,
    POI_GEOM_PARCEL_ID,
    POI_INDEX_PARCEL_ID,
)
from .etl import load_road_network, load_poi_data
from .encoder import encode_strings, encode_road_records, encode_bytes
from .spatial import build_kdtree, serialize_kdtree, build_bplustree, dump_bplustree
from .iso import write_iso
from logging.handlers import RotatingFileHandler

def init_logging(verbose: bool, work_dir: pathlib.Path):
    work_dir.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s | %(levelname)s | %(message)s"
    datefmt = "%H:%M:%S"
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    fh = RotatingFileHandler(work_dir / "run.log", maxBytes=5_000_000, backupCount=3)
    fh.setFormatter(logging.Formatter(fmt, datefmt))
    logging.getLogger().addHandler(fh)

def _iter_coords(geom):
    if isinstance(geom, LineString):
        return list(geom.coords)
    if isinstance(geom, MultiLineString):
        coords = []
        for part in geom.geoms:
            coords.extend(part.coords)
        return coords
    return []

def fetch(region: str, dest: pathlib.Path) -> pathlib.Path:
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"
    log = logging.getLogger(__name__)
    if dest.exists():
        log.info("Using cached PBF: %s", dest)
        return dest
    log.info("Downloading %s ...", url)
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
        for chunk in r.iter_content(8192):
            f.write(chunk)
            bar.update(len(chunk))
    log.info("Saved %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest

def build_manifest_payload(regions: list[str], filenames: list[str]) -> bytes:
    """
    Create a simple JSON manifest listing each filename.
    The nav loader expects PID 0 in MTOC.SDL to contain this.
    """
    entries = [{"name": fn} for fn in filenames]
    manifest = {"files": entries}
    return json.dumps(manifest).encode('utf-8')

def build(regions: list[str], out_iso: pathlib.Path, work: pathlib.Path):
    log = logging.getLogger(__name__)

    # Suppress Pyrosm’s chained‐assignment FutureWarning
    warnings.filterwarnings(
        "ignore",
        category=FutureWarning,
        module="pyrosm.networks"
    )
    # Suppress Shapely’s “geographic CRS” centroid warning
    warnings.filterwarnings(
        "ignore",
        message="Geometry is in a geographic CRS.*",
        category=UserWarning
    )

    work.mkdir(parents=True, exist_ok=True)
    try:
        # 1) Fetch & parse
        pbf = fetch(regions[0], work / f"{regions[0].replace('/', '-')}.osm.pbf")
        log.info("Parsing road network with Pyrosm")
        roads = load_road_network(str(pbf))
        log.info("Loaded %d road geometries", len(roads))

        # —————————————————————————————————————————————————————————————————————————
        # 2) Build global KD-tree (exactly as before)
        log.info("Building global KD-tree")
        centroids = [(pt.x, pt.y) for pt in roads["geometry"].centroid]
        kd = build_kdtree(centroids)
        kd_blob = serialize_kdtree(kd)

        # ─── 2.b) Load all POIs from the same PBF ────────────────────────────────
        #     We now call load_poi_data with no extra arguments—our etl.py defaults cover all OSM POI keys.
        pois = load_poi_data(str(pbf), poi_tags=None)
        log.info(f"Loaded {len(pois)} POIs")

        # Prepare a temporary list for POI‐related SDL files.
        poi_files: list[pathlib.Path] = []

        # ─── 2.c) Encode POI names into “POINAMES.SDL”
        poi_name_file = work / "POINAMES.SDL"
        poi_name_bytes = encode_strings(POI_NAME_PARCEL_ID, pois["name"].fillna("").tolist())
        poi_name_file.write_bytes(poi_name_bytes)
        poi_files.append(poi_name_file)

        # ─── 2.d) Build B+ index & data blob for POI geometries ──────────────────
        poi_records: list[tuple[int, bytes]] = []
        poi_offsets: list[tuple[int, int]] = []
        offset_acc = 0

        # If a leftover POI.bpt exists from a previous run, delete it first.
        poi_idx_path = work / "POI.bpt"
        if poi_idx_path.exists():
            os.remove(str(poi_idx_path))

        for pid, geom in zip(pois.index, pois.geometry):
            # Some POI geometries might be polygons; use centroid if no .x/.y directly.
            if hasattr(geom, "x"):
                lon, lat = geom.x, geom.y
            else:
                cent = geom.centroid
                lon, lat = cent.x, cent.y

            payload = struct.pack("<ii", int(lat * 1e6), int(lon * 1e6))
            poi_records.append((int(pid), payload))
            poi_offsets.append((int(pid), offset_acc))
            offset_acc += len(payload) + 6  # leave space for a 6-byte record header

        # Build a fresh B+ tree for POI offsets
        build_bplustree(poi_offsets, str(poi_idx_path))
        poi_index_blob = dump_bplustree(str(poi_idx_path))

        poi_geom_file = work / "POIGEOM.SDL"
        with open(poi_geom_file, "wb") as f:
            # First, write each POI’s geometry under POI_GEOM_PARCEL_ID
            for pid, payload in poi_records:
                f.write(encode_bytes(POI_GEOM_PARCEL_ID, payload))
            # Then append the POI index under POI_INDEX_PARCEL_ID
            f.write(encode_bytes(POI_INDEX_PARCEL_ID, poi_index_blob))
        poi_files.append(poi_geom_file)

        # —————————————————————————————————————————————————————————————————————————
        # 3) Prepare global SDLs (PID 0 → MTOC.SDL)
        filenames = ["MTOC.SDL", "CARTOTOP.SDL", "REGION.SDL", "REGIONS.SDL", "KDTREE.SDL"]
        for region in regions:
            stem = pathlib.Path(region).name
            filenames.extend([f"{stem}F.SDL", f"{stem}M.SDL"])

        mtoc = work / "MTOC.SDL"
        manifest = build_manifest_payload(regions, filenames)
        mtoc.write_bytes(encode_bytes(0, manifest))

        global_files: list[pathlib.Path] = [mtoc]

        # Now merge in our POI SDLs:
        for pf in poi_files:
            global_files.append(pf)

        # Create the rest of the global SDLs exactly as before
        for name, pid, data in [
            ("CARTOTOP.SDL", CARTO_PARCEL_ID, b""),
            ("REGION.SDL", NAV_PARCEL_ID, b""),
            ("REGIONS.SDL", BTREE_PARCEL_ID, b""),
            ("KDTREE.SDL", KDTREE_PARCEL_ID, kd_blob),
        ]:
            path = work / name
            path.write_bytes(encode_bytes(pid, data))
            global_files.append(path)

        # —————————————————————————————————————————————————————————————————————————
        # 4) Generate a multi‐tile 256×256 density grid for each region (unchanged)…
        #
        # Reproject roads into a local UTM CRS so that lengths are in meters.
        bbox = roads.total_bounds  # [minx, miny, maxx, maxy] in EPSG:4326
        minx, miny, maxx, maxy = bbox
        center_x = (minx + maxx) / 2.0
        center_y = (miny + maxy) / 2.0
        utm_zone = int((center_x + 180) / 6) + 1
        utm_crs = f"EPSG:{32600 + utm_zone}"

        roads_proj: gpd.GeoDataFrame = roads.to_crs(utm_crs)
        proj_bounds = roads_proj.total_bounds  # [pminx, pminy, pmaxx, pmaxy] in meters
        pminx, pminy, pmaxx, pmaxy = proj_bounds

        # Explode any MultiLineStrings so we only work with LineString rows
        roads_simple = roads_proj.explode(ignore_index=True)
        roads_simple = roads_simple[roads_simple.geometry.type.isin(["LineString", "MultiLineString"])]

        # For Zoom levels 0..3, build 1, 4, 16, and 64 tiles respectively.
        for Z in range(0, 4):
            num_tiles = 2 ** Z
            tile_width = (pmaxx - pminx) / num_tiles
            tile_height = (pmaxy - pminy) / num_tiles

            for tx in range(num_tiles):
                for ty in range(num_tiles):
                    # Compute sub‐bbox for this tile at zoom Z
                    tminx = pminx + tx * tile_width
                    tmaxx = pminx + (tx + 1) * tile_width
                    tminy = pminy + ty * tile_height
                    tmaxy = pminy + (ty + 1) * tile_height

                    # Build a 256×256 “pixel” grid inside [tminx..tmaxx] × [tminy..tmaxy]
                    grid_size = 256
                    dx = (tmaxx - tminx) / grid_size
                    dy = (tmaxy - tminy) / grid_size

                    # Initialize a floating‐point array for road‐length accumulation
                    density_array = np.zeros((grid_size, grid_size), dtype=np.float64)

                    # Clip roads to this tile’s bounding box
                    tile_box = box(tminx, tminy, tmaxx, tmaxy)
                    roads_clipped = roads_simple.geometry.intersection(tile_box)

                    # Break each clipped geometry into small segments, assign midpoints to cells
                    max_seg_length = min(dx, dy) / 2.0
                    for seg_geom in tqdm(roads_clipped, desc=f"Rasterizing Z{Z} tile ({tx},{ty})", leave=False):
                        if seg_geom.is_empty:
                            continue
                        total_len = seg_geom.length
                        if total_len == 0:
                            continue

                        n_pieces = max(1, int(np.ceil(total_len / max_seg_length)))
                        fractions = np.linspace(0, 1, n_pieces + 1)
                        prev_pt = seg_geom.interpolate(fractions[0], normalized=True)

                        for i in range(1, len(fractions)):
                            curr_pt = seg_geom.interpolate(fractions[i], normalized=True)
                            seg_len = prev_pt.distance(curr_pt)
                            midpoint = LineString([prev_pt, curr_pt]).centroid
                            mx, my = midpoint.x, midpoint.y

                            col = int((mx - tminx) // dx)
                            row = int((my - tminy) // dy)
                            if 0 <= col < grid_size and 0 <= row < grid_size:
                                density_array[row, col] += seg_len

                            prev_pt = curr_pt

                    # Scale to uint16 range
                    max_val = density_array.max()
                    if max_val > 0:
                        scale = 65535.0 / max_val
                    else:
                        scale = 0.0
                    density_scaled = (density_array * scale).clip(0, 65535).astype(np.uint16)

                    # Raw little‐endian uint16 bytes
                    raw_bytes = density_scaled.astype("<u2").tobytes()

                    # Write out one DENS tile per region (same geometry for all regions here)
                    for region in regions:
                        code = pathlib.Path(region).name.upper()[:2]
                        tile_id = ty * num_tiles + tx
                        dens_filename = f"DENS{code}{Z}{tile_id}.SDL"
                        dens_path = work / dens_filename
                        dens_path.write_bytes(encode_bytes(DENS_PARCEL_ID, raw_bytes))
                        global_files.append(dens_path)

        # —————————————————————————————————————————————————————————————————————————
        # 5) Build per-region FAST & MAP SDLs (unchanged)
        region_files: list[pathlib.Path] = []
        for region in regions:
            stem = pathlib.Path(region).name

            # FAST file: NAV (string names) + B+ index
            fast = work / f"{stem}F.SDL"
            # Use fillna("") so that None → empty string
            fast.write_bytes(encode_strings(NAV_PARCEL_ID, roads['name'].fillna("").tolist()))

            records, offsets, off = [], [], 0
            for wid, geom in tqdm(zip(roads['id'], roads.geometry), total=len(roads), unit='road'):
                coords = _iter_coords(geom)
                records.append((wid, coords))
                size = 6 + len(coords) * 16
                offsets.append((wid, off))
                off += size
            idx_path = work / f"{stem}.bpt"
            build_bplustree(offsets, str(idx_path))
            bt_blob = dump_bplustree(str(idx_path))
            fast.write_bytes(encode_bytes(BTREE_PARCEL_ID, bt_blob))
            region_files.append(fast)

            # MAP file: CARTO (road records) + KD-tree
            mapf = work / f"{stem}M.SDL"
            mapf.write_bytes(encode_road_records(CARTO_PARCEL_ID, records))
            mapf.write_bytes(encode_bytes(KDTREE_PARCEL_ID, kd_blob))
            region_files.append(mapf)

        # —————————————————————————————————————————————————————————————————————————
        # 6) Master the ISO
        write_iso(global_files + region_files, out_iso)
        log.info("ISO built: %s", out_iso)

    except Exception:
        log.exception("Build failed")
        raise

def cli():
    parser = argparse.ArgumentParser(description="Build SDAL ISO per region")
    parser.add_argument("regions", nargs='+', help="Geofabrik region slugs")
    parser.add_argument("--out", default="sdal.iso", help="Output ISO path")
    parser.add_argument("--work", default="build/tmp", help="Working directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    init_logging(args.verbose, pathlib.Path(args.work))
    build(args.regions, pathlib.Path(args.out), pathlib.Path(args.work))

if __name__ == "__main__":
    cli()

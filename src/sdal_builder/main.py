#!/usr/bin/env python3
"""
CLI for building SDAL ISO images per region, embedding PID 0 in MTOC.SDL,
generating multi‐tile density overlays, and including all OSM POIs,
all without blowing out memory by holding everything in a single GeoDataFrame.
"""
import argparse
import logging
import pathlib
import sys
import json
import warnings
from logging.handlers import RotatingFileHandler

import requests
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, box, Point
from tqdm import tqdm
import struct

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
    """
    Download (or use cached) {region}-latest.osm.pbf from Geofabrik.
    """
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"
    log = logging.getLogger(__name__)
    if dest.exists():
        log.info("Using cached PBF: %s", dest)
        return dest

    log.info("Downloading %s …", url)
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    total = int(r.headers.get("content-length", 0))
    with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as bar:
        for chunk in r.iter_content(8192):
            f.write(chunk)
            bar.update(len(chunk))

    log.info("Saved %s (%.1f MB)", dest, dest.stat().st_size / 1e6)
    return dest


def region_exists(region: str) -> bool:
    """
    Check if the given region slug has a downloadable PBF on Geofabrik.
    """
    url = f"https://download.geofabrik.de/{region}-latest.osm.pbf"
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def build_manifest_payload(regions: list[str], filenames: list[str]) -> bytes:
    """
    Create a simple JSON manifest listing each filename.
    The nav loader expects PID 0 in MTOC.SDL to contain this.
    """
    entries = [{"name": fn} for fn in filenames]
    manifest = {"files": entries}
    return json.dumps(manifest).encode("utf-8")


def build(regions: list[str], out_iso: pathlib.Path, work: pathlib.Path):
    log = logging.getLogger(__name__)

    # 0) Validate that each region slug exists:
    for region in regions:
        if not region_exists(region):
            log.error(f"Region slug '{region}' not found or not downloadable from Geofabrik.")
            sys.exit(1)

    # Suppress Pyrosm’s chained-assignment FutureWarning
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
        # ────────────────────────────────────────────────────────────────────────
        # 1) STREAM ROAD NETWORKS FROM EACH REGION, ONE-BY-ONE, COLLECT CENTROIDS ONLY
        #    (so we never hold all geometries in one giant GeoDataFrame)

        all_centroids: list[tuple[float, float]] = []
        region_road_counts: dict[str,int] = {}

        for region in regions:
            pbf_path = work / f"{region.replace('/', '-')}.osm.pbf"
            pbf = fetch(region, pbf_path)

            log.info("Parsing road network for %s with Pyrosm", region)
            roads_df = load_road_network(str(pbf))  # this returns a GeoDataFrame of roads
            count = len(roads_df)
            log.info("Loaded %d road geometries from %s", count, region)
            region_road_counts[region] = count

            # Extract centroids (x,y) for KD-tree; drop geometry immediately after
            centroids = [(pt.x, pt.y) for pt in roads_df.geometry.centroid]
            all_centroids.extend(centroids)

            # We need nothing else from `roads_df` right now—drop it to free memory
            del roads_df

        log.info("Total combined road geometries (sum of all regions): %d", sum(region_road_counts.values()))

        # 2) BUILD A SINGLE, GLOBAL KD-TREE OVER ALL CENTROIDS
        log.info("Building global KD-tree")
        kd = build_kdtree(all_centroids)
        kd_blob = serialize_kdtree(kd)

        # ────────────────────────────────────────────────────────────────────────
        # 3) STREAM POIs FROM EACH REGION, ONE-BY-ONE, CONCATENATE NAMES & GEOMETRIES
        all_poi_names: list[str] = []
        poi_records: list[tuple[int, bytes]] = []
        poi_offsets: list[tuple[int,int]] = []
        offset_acc = 0

        poi_index_counter = 0
        for region in regions:
            pbf_path = work / f"{region.replace('/', '-')}.osm.pbf"
            pois_df = load_poi_data(str(pbf_path), poi_tags=None)
            log.info("Loaded %d POIs from %s", len(pois_df), region)

            # 3.a) Collect `name` column into a single list of strings:
            all_poi_names.extend(pois_df["name"].fillna("").tolist())

            # 3.b) Build per-POI geometry payloads (lat/lon in u32) for B+ tree:
            for geom_idx, geom in zip(pois_df.index, pois_df.geometry):
                # If geometry is not a Point, use centroid:
                if not isinstance(geom, Point):
                    geom = geom.centroid
                lon, lat = geom.x, geom.y
                payload = struct.pack("<ii", int(lat * 1e6), int(lon * 1e6))
                poi_records.append((int(poi_index_counter), payload))
                poi_offsets.append((int(poi_index_counter), offset_acc))
                offset_acc += len(payload) + 6  # +6 bytes reserved per-record if needed
                poi_index_counter += 1

            del pois_df

        log.info("Total combined POIs: %d", len(all_poi_names))

        # 3.c) ENCODE POI NAMES → POINAMES.SDL
        global_files: list[pathlib.Path] = []
        poi_name_file = work / "POINAMES.SDL"
        poi_name_bytes = encode_strings(POI_NAME_PARCEL_ID, all_poi_names)
        poi_name_file.write_bytes(poi_name_bytes)
        global_files.append(poi_name_file)

        # 3.d) BUILD B+ INDEX & DATA BLOB FOR POI GEOMETRIES → POIGEOM.SDL
        poi_idx_path = work / "POI.bpt"
        build_bplustree(poi_offsets, str(poi_idx_path))
        poi_index_blob = dump_bplustree(str(poi_idx_path))

        poi_geom_file = work / "POIGEOM.SDL"
        with open(poi_geom_file, "wb") as f:
            for pid, payload in poi_records:
                f.write(encode_bytes(POI_GEOM_PARCEL_ID, payload))
            f.write(encode_bytes(POI_INDEX_PARCEL_ID, poi_index_blob))
        global_files.append(poi_geom_file)

        # ────────────────────────────────────────────────────────────────────────
        # 4) PREPARE GLOBAL SDLs (PID 0 → MTOC.SDL, THEN CARTOTOP.SDL, REGION.SDL, …)
        filenames = [
            "MTOC.SDL",
            "CARTOTOP.SDL",
            "REGION.SDL",
            "REGIONS.SDL",
            "KDTREE.SDL",
        ]
        for region in regions:
            stem = pathlib.Path(region).name.upper().replace("-", "_")
            filenames.extend([f"{stem}F.SDL", f"{stem}M.SDL"])

        mtoc = work / "MTOC.SDL"
        manifest = build_manifest_payload(regions, filenames)
        mtoc.write_bytes(encode_bytes(0, manifest))
        global_files.append(mtoc)

        for name, pid, data in [
            ("CARTOTOP.SDL", CARTO_PARCEL_ID, b""),
            ("REGION.SDL", NAV_PARCEL_ID, b""),
            ("REGIONS.SDL", BTREE_PARCEL_ID, b""),
            ("KDTREE.SDL", KDTREE_PARCEL_ID, kd_blob),
        ]:
            path = work / name
            path.write_bytes(encode_bytes(pid, data))
            global_files.append(path)

        # ────────────────────────────────────────────────────────────────────────
        # 5) MULTI-TILE DENSITY OVERLAY, REGION-BY-REGION (never keep all roads in memory)

        # We already have `all_centroids` so we can drop it now if we want:
        del all_centroids

        # But for density, we need the *geometries* of each region. We re-load, tile, and drop each region’s roads in turn.
        for region in regions:
            pbf_path = work / f"{region.replace('/', '-')}.osm.pbf"
            roads_df = load_road_network(str(pbf_path))  # local GeoDataFrame
            log.info("Loaded %d road geometries for density from %s", len(roads_df), region)

            # Project into a local UTM CRS for accurate length (same as earlier)
            bbox = roads_df.total_bounds  # [minx, miny, maxx, maxy] in EPSG:4326
            minx, miny, maxx, maxy = bbox
            center_x = (minx + maxx) / 2.0
            center_y = (miny + maxy) / 2.0
            utm_zone = int((center_x + 180) / 6) + 1
            utm_crs = f"EPSG:{32600 + utm_zone}"

            roads_proj = roads_df.to_crs(utm_crs)
            proj_bounds = roads_proj.total_bounds  # [pminx, pminy, pmaxx, pmaxy] in meters
            pminx, pminy, pmaxx, pmaxy = proj_bounds

            roads_simple = roads_proj.explode(ignore_index=True)
            roads_simple = roads_simple[
                roads_simple.geometry.type.isin(["LineString", "MultiLineString"])
            ]

            # For zoom levels 0..3, build 1, 4, 16, and 64 tiles respectively for this one region:
            for Z in range(0, 4):
                num_tiles = 2 ** Z
                tile_width = (pmaxx - pminx) / num_tiles
                tile_height = (pmaxy - pminy) / num_tiles

                for tx in range(num_tiles):
                    for ty in range(num_tiles):
                        tminx = pminx + tx * tile_width
                        tmaxx = pminx + (tx + 1) * tile_width
                        tminy = pminy + ty * tile_height
                        tmaxy = pminy + (ty + 1) * tile_height

                        grid_size = 256
                        dx = (tmaxx - tminx) / grid_size
                        dy = (tmaxy - tminy) / grid_size

                        density_array = np.zeros((grid_size, grid_size), dtype=np.float64)
                        tile_box = box(tminx, tminy, tmaxx, tmaxy)
                        clipped = roads_simple.geometry.intersection(tile_box)

                        max_seg_length = min(dx, dy) / 2.0
                        for seg_geom in tqdm(
                            clipped,
                            desc=f"Rasterizing {region} Z{Z} tile ({tx},{ty})",
                            leave=False,
                        ):
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

                        max_val = density_array.max()
                        scale = 65535.0 / max_val if max_val > 0 else 0.0
                        density_scaled = (
                            (density_array * scale).clip(0, 65535).astype(np.uint16)
                        )
                        raw_bytes = density_scaled.astype("<u2").tobytes()

                        code = pathlib.Path(region).name.upper().replace("-", "_")[:2]
                        tile_id = ty * num_tiles + tx
                        dens_filename = f"DENS{code}{Z}{tile_id}.SDL"
                        dens_path = work / dens_filename
                        dens_path.write_bytes(encode_bytes(DENS_PARCEL_ID, raw_bytes))
                        global_files.append(dens_path)

            # Done with this region’s roads for density—drop to free memory
            del roads_df, roads_proj, roads_simple

        # ────────────────────────────────────────────────────────────────────────
        # 6) BUILD PER-REGION FAST & MAP SDLs (roads only, streaming names & coords)

        region_files: list[pathlib.Path] = []
        poi_name_offset = 0  # not strictly needed, but we maintain consistent indexing

        for region in regions:
            # Re-load *just* the road names (and ids) for this region—drop geometry right away.
            pbf_path = work / f"{region.replace('/', '-')}.osm.pbf"
            roads_df = load_road_network(str(pbf_path))[["id", "name", "geometry"]]

            stem = pathlib.Path(region).name.upper().replace("-", "_")

            # 6.a) FAST file: write out all 'name' strings for roads in this region, then B+ index
            fast = work / f"{stem}F.SDL"
            # Fill None → "" to avoid encode errors
            names = roads_df["name"].fillna("").tolist()
            fast.write_bytes(encode_strings(NAV_PARCEL_ID, names))

            records = []
            offsets = []
            off = 0
            for wid, geom in tqdm(zip(roads_df["id"], roads_df.geometry), total=len(roads_df), unit="road"):
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

            # 6.b) MAP file: CARTO (road records) + KD-tree
            mapf = work / f"{stem}M.SDL"
            mapf.write_bytes(encode_road_records(CARTO_PARCEL_ID, records))
            mapf.write_bytes(encode_bytes(KDTREE_PARCEL_ID, kd_blob))
            region_files.append(mapf)

            del roads_df  # drop for memory

        # ────────────────────────────────────────────────────────────────────────
        # 7) MASTER THE ISO
        write_iso(global_files + region_files, out_iso)
        log.info("ISO built: %s", out_iso)

    except Exception:
        log.exception("Build failed")
        raise


def cli():
    parser = argparse.ArgumentParser(description="Build SDAL ISO per region")
    parser.add_argument(
        "regions",
        nargs="+",
        help="Geofabrik region slugs (e.g. europe/cyprus or europe/united-kingdom)",
    )
    parser.add_argument("--out", default="sdal.iso", help="Output ISO path")
    parser.add_argument("--work", default="build/tmp", help="Working directory")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()
    init_logging(args.verbose, pathlib.Path(args.work))
    build(args.regions, pathlib.Path(args.out), pathlib.Path(args.work))


if __name__ == "__main__":
    cli()

"""
Streaming OSM helpers for SDAL builder (single-threaded + progress logging).

Uses SimpleHandler.apply_file(pbf_path, locations=True, idx="flex_mem") to load
node locations properly. Emits INFO logs every 100 000 objects to show progress.

GeoDataFrame schemas exactly match the original Pyrosm outputs.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

import geopandas as gpd
import osmium
import shapely.geometry as sg
from shapely.geometry import Point

LOG = logging.getLogger(__name__)
PROGRESS_EVERY = 100_000  # emit an INFO log every N OSM objects


# --------------------------------------------------------------------------- #
# Base handler with progress counter                                          #
# --------------------------------------------------------------------------- #
class _ProgressHandler(osmium.SimpleHandler):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self._counter = 0
        self._start = time.time()

    def _tick(self):
        self._counter += 1
        if self._counter % PROGRESS_EVERY == 0:
            LOG.info(
                " … %s parsed %d objects in %.1fs",
                self._name,
                self._counter,
                time.time() - self._start,
            )


# --------------------------------------------------------------------------- #
# Road network                                                                #
# --------------------------------------------------------------------------- #
_DRIVABLE = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "motorway_link", "trunk_link",
    "primary_link", "secondary_link", "tertiary_link", "service",
}


class _RoadHandler(_ProgressHandler):
    def __init__(self) -> None:
        super().__init__("_RoadHandler")
        self.rows: List[Dict] = []

    def way(self, w: osmium.osm.Way) -> None:  # type: ignore[attr-defined]
        # Count every way processed for progress
        self._tick()

        # Skip non-drivable or too-short ways
        if w.tags.get("highway") not in _DRIVABLE or len(w.nodes) < 2:
            return

        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium._osmium.InvalidLocationError:
            # If any node lacks a valid location, skip this way entirely
            return

        self.rows.append(
            {
                "id": int(w.id),
                "name": w.tags.get("name", ""),
                "highway": w.tags.get("highway", ""),
                "oneway": w.tags.get("oneway", ""),
                "geometry": sg.LineString(coords),
            }
        )


def extract_driving_roads(pbf_path: str) -> gpd.GeoDataFrame:
    """
    Stream-extract all drivable ways from the .osm.pbf at pbf_path.
    Requires node locations (locations=True, idx='flex_mem').
    Returns a GeoDataFrame with columns: id, name, highway, oneway, geometry.
    """
    handler = _RoadHandler()
    LOG.info("Parsing _RoadHandler (single-threaded, with locations)")
    handler.apply_file(pbf_path, locations=True, idx="flex_mem")
    LOG.info(
        "Road parsing done: %d features, %.1fs total",
        len(handler.rows),
        time.time() - handler._start,
    )
    return gpd.GeoDataFrame(handler.rows, geometry="geometry", crs="EPSG:4326")


# --------------------------------------------------------------------------- #
# Points of Interest (POIs)                                                   #
# --------------------------------------------------------------------------- #
_DEFAULT_POI_TAGS = [
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "historic",
    "natural",
    "man_made",
]


class _POIHandler(_ProgressHandler):
    def __init__(self, wanted_tags: List[str]) -> None:
        super().__init__("_POIHandler")
        self.rows: List[Dict] = []
        self.wanted_tags = set(wanted_tags)

    def node(self, n: osmium.osm.Node) -> None:  # type: ignore[attr-defined]
        self._tick()
        tags_set = {t.k for t in n.tags}
        if not self.wanted_tags.intersection(tags_set):
            return

        # We know the Node has valid location (apply_file forced locations)
        row: Dict = {
            "geometry": Point(n.lon, n.lat),
            "name": n.tags.get("name", ""),
        }
        for k in self.wanted_tags:
            if k in tags_set:
                row[k] = n.tags.get(k)
        self.rows.append(row)

    def way(self, w: osmium.osm.Way) -> None:  # type: ignore[attr-defined]
        self._tick()
        tags_set = {t.k for t in w.tags}
        if not self.wanted_tags.intersection(tags_set):
            return

        # Compute centroid of closed ways or skip if invalid
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
            if len(coords) < 3:
                return
            geom = sg.Polygon(coords) if w.is_closed() else sg.LineString(coords)
            centroid = geom.centroid
        except osmium._osmium.InvalidLocationError:
            return

        row: Dict = {
            "geometry": centroid,
            "name": w.tags.get("name", ""),
        }
        for k in self.wanted_tags:
            if k in tags_set:
                row[k] = w.tags.get(k)
        self.rows.append(row)


def extract_pois(
    pbf_path: str,
    poi_tags: Optional[List[str]] = None,
) -> gpd.GeoDataFrame:
    """
    Stream-extract POI nodes/ways from the .osm.pbf at pbf_path.
    Only top-level keys in poi_tags (or a sensible default) are considered.
    Returns a GeoDataFrame with columns: geometry, name, and one column per tag key.
    """
    tags = poi_tags if poi_tags is not None else _DEFAULT_POI_TAGS
    handler = _POIHandler(tags)
    LOG.info("Parsing _POIHandler (single-threaded, with locations)")
    handler.apply_file(pbf_path, locations=True, idx="flex_mem")
    LOG.info(
        "POI parsing done: %d features, %.1fs total",
        len(handler.rows),
        time.time() - handler._start,
    )

    gdf = gpd.GeoDataFrame(handler.rows, geometry="geometry", crs="EPSG:4326")
    # Ensure every requested tag column (and name) exists
    for t in tags:
        if t not in gdf.columns:
            gdf[t] = None
    if "name" not in gdf.columns:
        gdf["name"] = ""
    return gdf

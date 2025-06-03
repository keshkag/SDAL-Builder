# src/sdal_builder/etl.py
#
# Streaming-friendly implementation.
# ----------------------------------
# The original Pyrosm loading logic has been replaced with two lightweight
# helpers from *sdal_osmium_stream.py*:
#
#     • extract_driving_roads()
#     • extract_pois()
#
# Those helpers parse *.osm.pbf* files with **pyosmium** in true streaming
# mode, so even very large regions (e.g. the full UK extract) no longer
# blow up memory.  All downstream code continues to receive the same
# GeoDataFrame formats as before.
#
from __future__ import annotations

from typing import List, Optional

import geopandas as gpd
from shapely.geometry import Point

from .sdal_osmium_stream import extract_driving_roads, extract_pois


# --------------------------------------------------------------------------- #
# Road network                                                                #
# --------------------------------------------------------------------------- #
def load_road_network(pbf_path: str) -> gpd.GeoDataFrame:
    """
    Return the *driving* road network for ``pbf_path`` as a GeoDataFrame.

    The schema (columns / CRS) matches what the old Pyrosm-based implementation
    produced: ``id``, ``name``, ``highway``, ``oneway``, and ``geometry``
    (EPSG:4326).
    """
    return extract_driving_roads(pbf_path)


# --------------------------------------------------------------------------- #
# Points of Interest (POIs)                                                   #
# --------------------------------------------------------------------------- #
_DEFAULT_POI_TAGS: List[str] = [
    "amenity",
    "shop",
    "tourism",
    "leisure",
    "historic",
    "natural",
    "man_made",
]


def load_poi_data(
    pbf_path: str,
    poi_tags: Optional[List[str]] = None,
) -> gpd.GeoDataFrame:
    """
    Stream-extract POI nodes / ways with the given top-level keys.

    Parameters
    ----------
    pbf_path
        Path to the *.osm.pbf* file.
    poi_tags
        List of tag keys to keep (e.g. ``["amenity", "shop"]``).  If *None*,
        a sensible default set identical to the legacy implementation is used.

    Returns
    -------
    GeoDataFrame
        Columns:
            * ``geometry`` (POINT, EPSG:4326)
            * ``name``     (string)
            * one column per requested tag key (may be entirely null)
    """
    tags = poi_tags if poi_tags is not None else _DEFAULT_POI_TAGS

    poi = extract_pois(pbf_path, tags)

    # Guarantee every requested tag column exists, even if empty
    for key in tags:
        if key not in poi.columns:
            poi[key] = None

    # Ensure 'name' column exists
    if "name" not in poi.columns:
        poi["name"] = ""

    # Build final column order: geometry ➔ name ➔ tag keys
    ordered_cols = ["geometry", "name"] + [k for k in tags if k in poi.columns]
    poi = poi[ordered_cols].copy()

    # Convert any non-point geometries (e.g. polygon centroids) to centroids so
    # the output remains consistent with historical behaviour.
    if not poi.empty and not isinstance(poi.geometry.iloc[0], Point):
        poi["geometry"] = poi.geometry.centroid

    return poi

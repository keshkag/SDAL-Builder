import geopandas as gpd
from pyrosm import OSM
from shapely.geometry import Point
import pandas as pd

def load_road_network(pbf_path: str) -> gpd.GeoDataFrame:
    """
    Use Pyrosm to extract the 'driving' road network as a GeoDataFrame.
    """
    osm = OSM(pbf_path)
    roads = osm.get_network(network_type="driving")
    return roads


def load_poi_data(pbf_path: str, poi_tags: list[str] | None = None) -> gpd.GeoDataFrame:
    """
    Extract POI nodes/ways in the PBF. If poi_tags is provided, only those OSM keys are requested;
    otherwise, defaults to a standard set of POI keys.

    Returns a GeoDataFrame with at least:
      - 'geometry'    (POINT location)
      - 'name'        (string, or NaN if missing)
      - one column per requested POI key, if it actually exists

    If Pyrosm returns None or empty, we still return a GeoDataFrame with 'geometry' and 'name' columns.
    """
    osm = OSM(pbf_path)

    # If user passed a list of tags, use them; else default to common OSM POI keys:
    if poi_tags is None:
        poi_tags = [
            "amenity",
            "shop",
            "tourism",
            "leisure",
            "historic",
            "natural",
            "man_made",
        ]

    # Build a Pyrosm filter dict: {"amenity": True, "shop": True, ...}
    custom_filter = {key: True for key in poi_tags}

    # Ask Pyrosm for POIs that have any of those keys:
    poi = osm.get_pois(custom_filter=custom_filter)

    # If Pyrosm returned nothing, create an empty GeoDataFrame with the right columns:
    if poi is None or poi.empty:
        # Ensure at least 'geometry' and 'name' exist:
        cols = ["geometry", "name"] + [k for k in poi_tags]
        return gpd.GeoDataFrame(columns=cols, geometry="geometry", crs="EPSG:4326")

    # At this point, 'poi' is a GeoDataFrame. Make sure we keep 'geometry', 'name', plus any of the requested tags:
    keep_cols = ["geometry"]
    if "name" in poi.columns:
        keep_cols.append("name")

    for key in poi_tags:
        if key in poi.columns and key not in keep_cols:
            keep_cols.append(key)

    poi = poi[keep_cols].copy()

    # If Pyrosm returned ways (LINESTRING/POLYGON) instead of points, convert to centroid:
    #  (in practice, get_pois() usually yields POINT for node‐POIs and centroid for way‐POIs,
    #   but we guard just in case.)
    if not poi.empty:
        first_geom = poi.geometry.iloc[0]
        if not isinstance(first_geom, Point):
            poi["geometry"] = poi.geometry.centroid

    # Return a clean GeoDataFrame in EPSG:4326 with at least columns ['geometry','name', ...].
    return gpd.GeoDataFrame(poi, geometry="geometry", crs="EPSG:4326")

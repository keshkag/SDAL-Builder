"""OSM road-line geometry -> source-faithful SDAL Cartographic and Routing records.

Inputs are *normalized, fully clipped OSM topology* with explicit physical
routing cost, length, bearings, rank and attribute IDs. These fields cannot
be guessed from a way's centroid or silently defaulted. Output is record
bytes awaiting the authoritative parcel/block/ID placement planner.
"""
from __future__ import annotations
from dataclasses import dataclass
from .oem_typed_records import RecordError
from .oem_line_geometry import (
    FullPolyline,CartographicPosition,encode_full_polyline,
    decode_full_polyline,encode_carto_positions,decode_carto_positions,
)
from .oem_route_segments import (
    RoutingSegmentRegular,encode_route_segment_regular,
    decode_route_segment_regular,
)

@dataclass(frozen=True)
class NormalizedOSMRoad:
    osm_way_id:int
    from_node_index:int
    to_node_index:int
    vertices_ntu:tuple[tuple[int,int],...]       # latitude,longitude in source order
    source_direction:int                         # 1 forward, 2 backward, 3 both
    cost_seconds:int
    length_meters:int
    left_bearing:int                             # already in canonical SDAL orientation
    right_bearing:int
    rank:int
    route_type:int
    highlight_layer:int
    attribute_index:int
    divider_loc:int=0
    divider_legal:bool=False
    detailed_city:bool=False
    multi_digitized:bool=False

@dataclass(frozen=True)
class EncodedRoadRecords:
    polyline:bytes
    cartographic_positions:bytes
    routing_segment:bytes
    left_node_index:int
    right_node_index:int
    source_osm_way_id:int
    reversed_from_osm:bool

def encode_osm_road_records(
    road:NormalizedOSMRoad, *,
    source_nodes:tuple[tuple[int,int],...],
    parcel_min_lat:int,parcel_min_lon:int,
    parcel_max_lat:int,parcel_max_lon:int,
    cartographic_position_offset:int,
    node_count:int,
    scale:int=0,
)->EncodedRoadRecords:
    if not isinstance(road,NormalizedOSMRoad) or road.osm_way_id<=0:
        raise RecordError("Normalized OSM road/identity required")
    if len(road.vertices_ntu)<2 or road.from_node_index==road.to_node_index:
        raise RecordError("Road needs two distinct endpoint vertices and node IDs")
    if not 0<=road.from_node_index<len(source_nodes) or not 0<=road.to_node_index<len(source_nodes):
        raise RecordError("Road endpoint node ID outside local routing index")
    if (road.vertices_ntu[0]!=source_nodes[road.from_node_index] or
        road.vertices_ntu[-1]!=source_nodes[road.to_node_index]):
        raise RecordError("OSM road vertices disagree with routing node coordinates")
    if road.source_direction not in (1,2,3):
        raise RecordError("OSM travel permission must be explicit and nonzero")
    for lat,lon in road.vertices_ntu:
        if not parcel_min_lat<=lat<=parcel_max_lat or not parcel_min_lon<=lon<=parcel_max_lon:
            raise RecordError("Unclipped OSM road extends outside physical SDAL parcel")
    # PSF §3.3.4.1: left endpoint has the lowest longitude (then latitude).
    reversed_way=(road.vertices_ntu[0][1],road.vertices_ntu[0][0]) > (
        road.vertices_ntu[-1][1],road.vertices_ntu[-1][0])
    ordered=tuple(reversed(road.vertices_ntu)) if reversed_way else road.vertices_ntu
    left=road.to_node_index if reversed_way else road.from_node_index
    right=road.from_node_index if reversed_way else road.to_node_index
    direction=(3 if road.source_direction==3 else
               3-road.source_direction if reversed_way else road.source_direction)
    start_lat,start_lon=ordered[0]
    vertices=tuple(CartographicPosition(lat,lon) for lat,lon in ordered[1:])
    positions=encode_carto_positions(start_lat=start_lat,start_lon=start_lon,
                                     points=vertices,scale=scale)
    # The decoder must reconstruct all source vertices without any precision loss.
    if decode_carto_positions(positions,start_lat=start_lat,start_lon=start_lon,
                              scale=scale)!=vertices:
        raise RecordError("OSM geometry changed while encoding Cartographic positions")
    line=FullPolyline(
        position_offset=cartographic_position_offset,entity_type=0,
        start_lat=start_lat,start_lon=start_lon,navigable=True,
        direction=direction,route_type=road.route_type,
        position_count=len(vertices),rank=road.rank,
        divider_loc=road.divider_loc,divider_legal=road.divider_legal,
        multi_digitized=road.multi_digitized,attribute_index=road.attribute_index)
    encoded_line=encode_full_polyline(line,min_lat=parcel_min_lat,
                                      min_lon=parcel_min_lon,scale=scale)
    if decode_full_polyline(encoded_line,min_lat=parcel_min_lat,
                            min_lon=parcel_min_lon,scale=scale)!=line:
        raise RecordError("Polyline does not roundtrip")
    segment=RoutingSegmentRegular(
        left,right,direction,road.left_bearing,road.right_bearing,road.rank,
        road.divider_loc,road.divider_legal,road.detailed_city,
        road.highlight_layer,road.cost_seconds,road.length_meters,
        road.attribute_index)
    encoded_segment=encode_route_segment_regular(segment,node_count=node_count)
    if decode_route_segment_regular(encoded_segment,node_count=node_count)!=segment:
        raise RecordError("Routing segment does not roundtrip")
    return EncodedRoadRecords(encoded_line,positions,encoded_segment,left,right,
                              road.osm_way_id,reversed_way)

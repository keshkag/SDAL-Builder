"""Spec-constrained OSM footprint -> SDAL spatial KD partition and index planner.

This module implements §3.1/§3.1.1 of PSF SDAL 1.7. It does NOT
write cartographic/route parcel payloads: those need their own record
writers and source data clipping before the spatial KD index can point
to them. Fail closed instead of assigning crossing geometry by centroid.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Iterable


class SpatialPlanError(ValueError):
    pass


@dataclass(frozen=True)
class Rect:
    west: int
    south: int
    east: int
    north: int

    def __post_init__(self) -> None:
        coords = (self.west,self.south,self.east,self.north)
        if any(not isinstance(x,int) or isinstance(x,bool)
               or not -(1<<31) <= x < (1<<31) for x in coords):
            raise SpatialPlanError("Coordinates must be signed 32-bit NTUs")
        if self.east <= self.west or self.north <= self.south:
            raise SpatialPlanError("Invalid rectangular extent")

    def contains(self, item: "Footprint") -> bool:
        return (self.west <= item.west <= item.east <= self.east
                and self.south <= item.south <= item.north <= self.north)


@dataclass(frozen=True)
class Footprint:
    source_id: int
    parcel_type: int
    layer: int
    west: int
    south: int
    east: int
    north: int

    def __post_init__(self) -> None:
        if (not isinstance(self.source_id,int) or isinstance(self.source_id,bool)
                or self.source_id < 0):
            raise SpatialPlanError("Source feature ID must be nonnegative")
        if self.parcel_type not in (0,1,2,3,4,5,6) or not 0 <= self.layer <= 4:
            raise SpatialPlanError("Unsupported SDAL spatial parcel type/layer")
        if (self.east < self.west or self.north < self.south
                or any(not -(1<<31) <= a < (1<<31)
                       for a in (self.west,self.south,self.east,self.north))):
            raise SpatialPlanError("Invalid OSM feature bounds")


@dataclass(frozen=True)
class Leaf:
    rect: Rect
    path: str
    features: tuple[Footprint, ...]


@dataclass(frozen=True)
class Split:
    rect: Rect
    path: str
    axis: str
    cut_32nds: int
    coordinate: int
    left: "Leaf | Split"
    right: "Leaf | Split"


def _parts(rect: Rect, axis: str, cut: int) -> tuple[Rect,Rect]:
    if axis == "longitude":
        return (Rect(rect.west,rect.south,cut,rect.north),
                Rect(cut,rect.south,rect.east,rect.north))
    return (Rect(rect.west,rect.south,rect.east,cut),
            Rect(rect.west,cut,rect.east,rect.north))


def plan_spatial_partition(region: Rect, features: Iterable[Footprint], *,
                           max_features_per_leaf: int = 200,
                           max_depth: int = 20,
                           minimum_leaf_span: int = 512) -> Leaf | Split:
    """Create a complete, noncrossing KD partition in 1/32 cut increments.

    Geometry that crosses a candidate cut stays indivisible. If no valid
    cut can meet the requested leaf budget, fail: segment clipping must
    occur upstream. This avoids silently losing OSM road sections.
    """
    if (max_features_per_leaf < 1 or max_depth < 1
            or minimum_leaf_span < 1):
        raise SpatialPlanError("Invalid partition limits")
    source = tuple(sorted(features,key=lambda p:(p.parcel_type,p.layer,p.source_id)))
    if not source or len(source) != len(set((f.parcel_type,f.layer,f.source_id)
                                           for f in source)):
        raise SpatialPlanError("Missing/duplicate OSM source feature keys")
    if any(not region.contains(feature) for feature in source):
        raise SpatialPlanError("OSM geometry extends outside declared SDAL region")

    def build(rect: Rect, group: tuple[Footprint,...], path: str, depth: int):
        if len(group) <= max_features_per_leaf:
            if (rect.east-rect.west < minimum_leaf_span
                    or rect.north-rect.south < minimum_leaf_span):
                raise SpatialPlanError("Parcel rectangle smaller than allowed NTUs")
            return Leaf(rect,path,group)
        if depth >= max_depth:
            raise SpatialPlanError("Spatial depth limit: upstream OSM clipping required")
        candidates=[]
        for axis in ("longitude","latitude"):
            origin = rect.west if axis=="longitude" else rect.south
            extent = ((rect.east-rect.west) if axis=="longitude"
                      else (rect.north-rect.south))
            for fraction in range(1,32):
                numerator=extent*fraction
                if numerator%32:
                    continue
                cut=origin+numerator//32
                one,two=_parts(rect,axis,cut)
                if min(one.east-one.west,one.north-one.south,
                       two.east-two.west,two.north-two.south)<minimum_leaf_span:
                    continue
                left=[];right=[];ambiguous=False
                for f in group:
                    lo,hi=(f.west,f.east) if axis=="longitude" else (f.south,f.north)
                    if hi<=cut:
                        left.append(f)
                    elif lo>=cut:
                        right.append(f)
                    else:
                        ambiguous=True
                        break
                if ambiguous or not left or not right:
                    continue
                # Prefer balanced, near-midpoint cuts, then longitude.
                score=(abs(len(left)-len(right)),abs(fraction-16),
                       0 if axis=="longitude" else 1,fraction)
                candidates.append((score,axis,fraction,cut,one,two,
                                   tuple(left),tuple(right)))
        if not candidates:
            raise SpatialPlanError(
                "No legal n/32 cut without bisecting OSM geometry; "
                "upstream splitting/clipping is required")
        _,axis,fraction,cut,left_rect,right_rect,left_group,right_group = min(
            candidates,key=lambda x:x[0])
        return Split(rect,path,axis,fraction,cut,
                     build(left_rect,left_group,path+"L",depth+1),
                     build(right_rect,right_group,path+"R",depth+1))
    return build(region,source,"",0)


def leaf_inventory(plan: Leaf | Split) -> dict[str,Leaf]:
    """Prove every feature is retained once and rectangles are disjoint."""
    result={}
    def walk(node):
        if isinstance(node,Leaf):
            if node.path in result or not node.features:
                raise SpatialPlanError("Invalid/empty leaf")
            if any(not node.rect.contains(f) for f in node.features):
                raise SpatialPlanError("OSM geometry outside its planned parcel")
            result[node.path]=node
        else:
            a,b=_parts(node.rect,node.axis,node.coordinate)
            if a!=node.left.rect or b!=node.right.rect:
                raise SpatialPlanError("KD child rectangles do not partition parent")
            walk(node.left);walk(node.right)
    walk(plan)
    seen=set()
    for leaf in result.values():
        for f in leaf.features:
            key=(f.parcel_type,f.layer,f.source_id)
            if key in seen:
                raise SpatialPlanError("Feature duplicated between parcels")
            seen.add(key)
    return result


def compile_planned_index(plan: Split, *,
                          parcel_refs: Mapping[str,tuple],
                          entity_id_bounds: Mapping[str,tuple[int,int]],
                          file_offset: int = 0xC200) -> bytes:
    """Compile an independently allocated OSM spatial plan to OEM index bytes.

    The caller must FIRST serialize physical type-0/1/... SDAL parcels
    and supply their *real* direct SpatialRefs by leaf path. No reference
    IDs are fabricated. A leaf without a type/layer match is rejected.
    Explicit segment/node minima are required for any routing subtree.
    """
    from .oem_kd_codec import (KDNode,KDChild,SpatialRef,encode_kd_node,
                               encode_index_from_nodes)
    if not isinstance(plan,Split):
        raise SpatialPlanError("Single-leaf direct descriptor topology unverified")
    leaves=leaf_inventory(plan)
    if set(parcel_refs)!=set(leaves):
        raise SpatialPlanError("Every terminal cell requires typed physical parcels")
    resolved={}
    for path,leaf in leaves.items():
        refs=parcel_refs[path]
        if not refs or not all(isinstance(r,SpatialRef) for r in refs):
            raise SpatialPlanError("Missing physical parcel reference at "+path)
        types=set((f.parcel_type,f.layer) for f in leaf.features)
        if set((r.parcel_type,r.layer) for r in refs)!=types:
            raise SpatialPlanError("Spatial parcel type/layer does not cover OSM leaf")
        if len(set(r.parcel_id for r in refs))!=len(refs):
            raise SpatialPlanError("Duplicate physical Parcel ID")
        if any(r.parcel_id&0x80000000 for r in refs):
            raise SpatialPlanError("External ParcelID requires global indirection")
        resolved[path]=tuple(refs)
    branches=[]
    def collect(node):
        if isinstance(node,Leaf):
            return
        branches.append(node)
        collect(node.left);collect(node.right)
    collect(plan)
    begin={}
    skeleton=[]
    for branch in branches:
        routing=any(f.parcel_type==0 for leaf in leaf_inventory(branch).values()
                    for f in leaf.features)
        if routing and branch.path not in entity_id_bounds:
            raise SpatialPlanError("Routing spatial cut lacks SDAL segment/node ID minima")
        ids=entity_id_bounds.get(branch.path)
        if ids is not None:
            if len(ids)!=2 or any(not 0<=x<=0xffffff for x in ids):
                raise SpatialPlanError("Segment/node bounds must be 24-bit entity IDs")
        branch_left= isinstance(branch.left,Split)
        branch_right= isinstance(branch.right,Split)
        skel=KDNode(
            horizontal_cut=(branch.axis=="latitude"),
            cut_32nds=branch.cut_32nds,
            entity_mode=1 if ids is not None else 0, entity_ids=ids,
            left_child=KDChild(3,1) if branch_left else None,
            right_child=KDChild(3,1) if branch_right else None,
            left_parcels=() if branch_left else resolved[branch.left.path],
            right_parcels=() if branch_right else resolved[branch.right.path])
        skeleton.append(skel)
    pos=0
    for branch,skel in zip(branches,skeleton):
        begin[branch.path]=pos
        pos+=len(encode_kd_node(skel))
    nodes=[]
    for branch,skel in zip(branches,skeleton):
        values=[]
        for child in (branch.left,branch.right):
            if isinstance(child,Split):
                distance=begin[child.path]-begin[branch.path]
                if distance<=0 or distance%2 or distance//2>65535:
                    raise SpatialPlanError("KD local edge cannot fit in two bytes")
                values.append(KDChild(3,distance//2))
            else:
                values.append(None)
        from dataclasses import replace
        nodes.append(replace(skel,left_child=values[0],right_child=values[1]))
    try:
        return encode_index_from_nodes(file_offset=file_offset,roots=(tuple(nodes),))
    except ValueError as exc:
        raise SpatialPlanError("Cannot encode OSM KD plan: "+str(exc)) from exc


def feature_from_osm_bounds(source_id: int, parcel_type: int, layer: int,
                            bounds_degrees: tuple[float,float,float,float]) -> Footprint:
    """Bridge a pre-parsed OSM geometry .bounds to integer SDAL NTUs.

    NTU=1/100000 degree, specified by PSF. This preserves *envelopes*,
    not segment clipping/geometry record content.
    """
    from .routing_format import deg_to_ntu
    west,south,east,north=bounds_degrees
    latmin,lonmin=deg_to_ntu(south,west)
    latmax,lonmax=deg_to_ntu(north,east)
    return Footprint(source_id,parcel_type,layer,lonmin,latmin,lonmax,latmax)

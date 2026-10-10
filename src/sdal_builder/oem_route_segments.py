"""SDAL 1.7 §3.3.4.3: regular bottom-layer routing segment wire records.

Only nonaggregated segments with no optional supernode, POI, sign,
shape-point, condition, TZ/LH/DS or NavID attributes are supported.
Additional flags are rejected: the encoder never discards OSM restrictions.
"""
from __future__ import annotations
from dataclasses import dataclass
from .oem_typed_records import RecordError,encode_type1,decode_type1

def integer(name,n,lo,hi):
    if not isinstance(n,int) or isinstance(n,bool) or not lo<=n<=hi:
        raise RecordError(f"{name} outside {lo}..{hi}")

@dataclass(frozen=True)
class RoutingSegmentRegular:
    left_node_index:int
    right_node_index:int
    direction:int
    left_bearing:int
    right_bearing:int
    rank:int
    divider_loc:int
    divider_legal:bool
    detailed_city:bool
    highlight_layer:int
    cost_seconds:int
    length_meters:int
    attribute_index:int

def encode_route_segment_regular(v:RoutingSegmentRegular,*,node_count:int)->bytes:
    integer("node count",node_count,2,65535)
    integer("left node",v.left_node_index,0,node_count-1)
    integer("right node",v.right_node_index,0,node_count-1)
    if v.left_node_index==v.right_node_index:
        raise RecordError("Coincident routing endpoints")
    integer("direction",v.direction,1,3)
    integer("left bearing",v.left_bearing,0,255)
    integer("right bearing",v.right_bearing,0,255)
    integer("rank",v.rank,0,4)
    integer("divider location",v.divider_loc,0,4)
    integer("highlight layer",v.highlight_layer,0,5)
    integer("cost seconds",v.cost_seconds,0,65519)
    integer("length meters",v.length_meters,0,65519)
    out=bytearray((v.direction<<2,0,v.left_bearing,v.right_bearing,
                   (v.rank<<5)|(v.divider_loc<<2)|
                   (int(v.divider_legal)<<1)|int(v.detailed_city),
                   v.highlight_layer<<5))
    for n in (v.left_node_index,v.right_node_index,v.cost_seconds,
              v.length_meters,v.attribute_index):
        out+=encode_type1(n)
    return bytes(out)

def decode_route_segment_regular(raw:bytes,*,node_count:int)->RoutingSegmentRegular:
    if len(raw)<11:raise RecordError("Truncated routing segment")
    a,b,left_bear,right_bear,flags,highlight=raw[:6]
    if a&0xf3 or b or highlight&31:
        raise RecordError("Unsupported optional/aggregated routing segment flags")
    pos=6
    vals=[]
    for _ in range(5):
        val,pos=decode_type1(raw,pos)
        vals.append(val)
    if pos!=len(raw):raise RecordError("Unexpected segment fields/trailing bytes")
    value=RoutingSegmentRegular(
        vals[0],vals[1],(a>>2)&3,left_bear,right_bear,
        flags>>5,(flags>>2)&7,bool(flags&2),bool(flags&1),
        highlight>>5,vals[2],vals[3],vals[4])
    if encode_route_segment_regular(value,node_count=node_count)!=raw:
        raise RecordError("Regular segment byte mismatch")
    return value

def verify_routing_node_segment_links(nodes:tuple,
                                      segments:tuple[RoutingSegmentRegular,...])->None:
    """Both directions of graph references must be consistent.

    Node instances must be RoutingNodeBasic from oem_typed_records.
    Arbitrary OSM way IDs are not permitted in the segment index arrays.
    """
    if len(nodes)<2 or not segments:raise RecordError("Routing network empty")
    expected=[set() for _ in nodes]
    for i,segment in enumerate(segments):
        encode_route_segment_regular(segment,node_count=len(nodes))
        expected[segment.left_node_index].add(i)
        expected[segment.right_node_index].add(i)
    for actual,required in zip(nodes,expected):
        indexes=tuple(actual.segment_indices)
        if len(set(indexes))!=len(indexes) or set(indexes)!=required:
            raise RecordError("Inconsistent routing node-to-segment backreferences")

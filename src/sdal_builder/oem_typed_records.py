"""SDAL 1.7 variable integers and bounded Route/Carto record encoders.

PSF v0.4 §§1.4.0.1, 3.2.3.3, 3.5.4.3. Implemented records:
* regular layer-0 routing node with no optional supernode/cost/z/name;
* basic cartographic point without a POI chain or population category.
These are strict real record subsets, not placeholders or complete parcels.
Any unimplemented flag combination is rejected, never silently lost.
"""
from __future__ import annotations
from dataclasses import dataclass

class RecordError(ValueError):
    pass

TYPE1_MAX=65520+0xfffff
TYPE4_MAX=61440+0xfffff   # 1,110,015; printed 1,110,095 is 80 too high.


def _check(value: int, maximum: int, field: str):
    if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<=maximum:
        raise RecordError(field+" outside representable range")


def encode_type1(value: int) -> bytes:
    _check(value,TYPE1_MAX,"Type 1 value")
    if value<240:return bytes([value])
    if value<4080:
        n=value-240
        return bytes([0xf0|(n>>8),n&255])
    if value<65520:
        return b"\xff"+(value-4080).to_bytes(2,"big")
    n=value-65520
    return (0xfff00000|n).to_bytes(4,"big")


def decode_type1(raw: bytes, offset: int=0) -> tuple[int,int]:
    if offset<0 or offset>=len(raw):raise RecordError("Truncated Type 1")
    a=raw[offset]
    if a<240:value=a;size=1
    elif a<255:
        size=2
        if len(raw)-offset<2:raise RecordError("Truncated Type 1")
        value=240+(((a&15)<<8)|raw[offset+1])
    else:
        if len(raw)-offset<2:raise RecordError("Truncated Type 1")
        b=raw[offset+1]
        if b<240:
            size=3
            if len(raw)-offset<3:raise RecordError("Truncated Type 1")
            value=4080+int.from_bytes(raw[offset+1:offset+3],"big")
        else:
            size=4
            if len(raw)-offset<4:raise RecordError("Truncated Type 1")
            value=65520+int.from_bytes(raw[offset+1:offset+4],"big")% (1<<20)
    if encode_type1(value)!=raw[offset:offset+size]:
        raise RecordError("Noncanonical Type 1 encoding")
    return value,offset+size


def encode_type4(value: int) -> bytes:
    _check(value,TYPE4_MAX,"Type 4 value")
    if value<61440:return value.to_bytes(2,"big")
    return (0xf00000|(value-61440)).to_bytes(3,"big")


def decode_type4(raw: bytes, offset: int=0) -> tuple[int,int]:
    if offset<0 or offset+2>len(raw):raise RecordError("Truncated Type 4")
    if raw[offset]<0xf0:
        size=2
        value=int.from_bytes(raw[offset:offset+2],"big")
    else:
        size=3
        if offset+3>len(raw):raise RecordError("Truncated Type 4")
        value=61440+(int.from_bytes(raw[offset:offset+3],"big")&0xfffff)
    if encode_type4(value)!=raw[offset:offset+size]:
        raise RecordError("Noncanonical Type 4 encoding")
    return value,offset+size


def _scaled(raw: int, origin: int, scale: int) -> int:
    _check(scale,15,"Spatial scale")
    if not isinstance(raw,int) or not isinstance(origin,int):
        raise RecordError("NTU coordinates must be integers")
    shift=1<<scale
    if raw<origin or (raw-origin)%shift:
        raise RecordError("Coordinate outside cell or not exactly representable by scale")
    encoded=(raw-origin)//shift
    _check(encoded,TYPE4_MAX,"Scaled geographic delta")
    return encoded


@dataclass(frozen=True)
class CartographicPointBasic:
    entity_type: int
    latitude_ntu: int
    longitude_ntu: int
    text_offset: int = 0


def encode_carto_point_basic(point: CartographicPointBasic, *,
                             min_lat_ntu: int, min_long_ntu: int,
                             scale: int=0) -> bytes:
    """Full format for a point without chain, population or special attrs.

    'Attribs' nibble=0 and 'Subtype' nibble=0xF explicitly mean the
    restricted feature profile; there is NO guessed POI chain index.
    """
    _check(point.text_offset,0x7fff,"Carto point text offset")
    raw=(encode_type1(point.entity_type)+
         encode_type4(_scaled(point.latitude_ntu,min_lat_ntu,scale))+
         encode_type4(_scaled(point.longitude_ntu,min_long_ntu,scale))+
         b"\x0f"+point.text_offset.to_bytes(2,"big"))
    return raw


def decode_carto_point_basic(raw:bytes, *, min_lat_ntu:int,
                             min_long_ntu:int, scale:int=0
                             ) -> tuple[CartographicPointBasic,int]:
    et,pos=decode_type1(raw)
    lat,pos=decode_type4(raw,pos)
    lon,pos=decode_type4(raw,pos)
    if len(raw)-pos<3:raise RecordError("Truncated Cartographic point")
    if raw[pos]!=0x0f:
        raise RecordError("Unsupported Cartographic subtype/attributes/chain encoding")
    text=int.from_bytes(raw[pos+1:pos+3],"big")
    if text&0x8000:
        raise RecordError("Population category requires a different point record")
    result=CartographicPointBasic(et,min_lat_ntu+(lat<<scale),
                                  min_long_ntu+(lon<<scale),text)
    consumed=pos+3
    if encode_carto_point_basic(result,min_lat_ntu=min_lat_ntu,
                                min_long_ntu=min_long_ntu,
                                scale=scale)!=raw[:consumed]:
        raise RecordError("Cartographic point encoder byte parity violation")
    return result,consumed


@dataclass(frozen=True)
class RoutingNodeBasic:
    latitude_ntu: int
    longitude_ntu: int
    segment_indices: tuple[int,...]
    name_change_bits: bytes=b""


def encode_route_node_basic(node:RoutingNodeBasic, *,
                            min_lat_ntu:int,min_long_ntu:int,
                            scale:int=0) -> bytes:
    """Regular bottom-layer node, no supernode/long-haul/cost/z/name flags.

    The segment array holds *indices into an already serialized segment
    table*, NOT arbitrary OSM way IDs. The caller must validate them.
    """
    count=len(node.segment_indices)
    if count>255:raise RecordError("More than 255 incident segments")
    mask_bytes=(count*(count-1)//2+7)//8
    if len(node.name_change_bits)!=mask_bytes:
        raise RecordError("Wrong triangular name-change bit mask length")
    if mask_bytes and count*(count-1)//2%8:
        spare=8-(count*(count-1)//2)%8
        if node.name_change_bits[-1]&((1<<spare)-1):
            raise RecordError("Nonzero unused name-change mask bits")
    result=bytearray(b"\x00\x00")
    result+=encode_type4(_scaled(node.latitude_ntu,min_lat_ntu,scale))
    result+=encode_type4(_scaled(node.longitude_ntu,min_long_ntu,scale))
    result.append(count)
    for index in node.segment_indices:
        result+=encode_type1(index)
    result+=node.name_change_bits
    return bytes(result)


def decode_route_node_basic(raw:bytes, *, min_lat_ntu:int,
                            min_long_ntu:int,scale:int=0
                            ) -> tuple[RoutingNodeBasic,int]:
    if len(raw)<2:raise RecordError("Truncated Routing node flags")
    if raw[:2]!=b"\x00\x00":
        raise RecordError("Unsupported routing node type/rank/options")
    lat,pos=decode_type4(raw,2)
    lon,pos=decode_type4(raw,pos)
    if pos>=len(raw):raise RecordError("Truncated routing segment count")
    count=raw[pos];pos+=1
    segs=[]
    for _ in range(count):
        val,pos=decode_type1(raw,pos)
        segs.append(val)
    maskbytes=(count*(count-1)//2+7)//8
    if pos+maskbytes>len(raw):raise RecordError("Truncated name-change bits")
    result=RoutingNodeBasic(min_lat_ntu+(lat<<scale),
                            min_long_ntu+(lon<<scale),
                            tuple(segs),raw[pos:pos+maskbytes])
    end=pos+maskbytes
    if encode_route_node_basic(result,min_lat_ntu=min_lat_ntu,
                               min_long_ntu=min_long_ntu,scale=scale)!=raw[:end]:
        raise RecordError("Routing node writer byte parity violation")
    return result,end

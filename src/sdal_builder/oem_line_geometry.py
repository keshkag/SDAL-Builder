"""SDAL 1.7 Cartographic polylines and 24-bit positions (§§3.5.3, 3.5.6).

Exact integer NTU source geometry; fail closed on lossy scaled deltas,
unsupported short-polylines and inconsistent optional fields.
"""
from __future__ import annotations
from dataclasses import dataclass
from .oem_typed_records import RecordError, encode_type1, decode_type1, encode_type4, decode_type4

def check(name,v,a,b):
    if not isinstance(v,int) or isinstance(v,bool) or not a<=v<=b:
        raise RecordError(f"{name} out of bounds {a}..{b}")

def scale_delta(value,origin,scale):
    check("scale",scale,0,15)
    if not isinstance(value,int) or not isinstance(origin,int):
        raise RecordError("NTU coordinates must be integers")
    d=value-origin
    if d<0 or d%(1<<scale):
        raise RecordError("Coordinate cannot be represented exactly at scale")
    return d>>scale

@dataclass(frozen=True)
class FullPolyline:
    position_offset:int
    entity_type:int
    start_lat:int
    start_lon:int
    navigable:bool
    direction:int
    route_type:int
    position_count:int
    text_offsets:tuple[int,...]=()
    rank:int|None=None
    divider_loc:int=0
    divider_legal:bool=False
    multi_digitized:bool=False
    attribute_index:int|None=None
    in_process:bool=False

def encode_full_polyline(v:FullPolyline,*,min_lat:int,min_lon:int,scale:int=0)->bytes:
    check("position offset",v.position_offset,0,32767)
    check("text record count",len(v.text_offsets),0,255)
    check("travel direction",v.direction,0,3)
    check("route type",v.route_type,0,7)
    if v.navigable:
        if not v.direction or v.rank is None or v.attribute_index is None:
            raise RecordError("Navigable polyline needs direction, rank, attribute index")
        check("rank",v.rank,0,4);check("divider",v.divider_loc,0,4)
    elif (v.direction or v.rank is not None or v.attribute_index is not None
          or v.divider_loc or v.divider_legal or v.multi_digitized):
        raise RecordError("Non-navigable polyline carries navigable-only fields")
    out=bytearray(v.position_offset.to_bytes(2,"big"))
    out.append(len(v.text_offsets))
    out+=encode_type1(v.entity_type)
    out+=encode_type4(scale_delta(v.start_lat,min_lat,scale))
    out+=encode_type4(scale_delta(v.start_lon,min_lon,scale))
    out.append((int(v.navigable)<<7)|(v.direction<<5)
               |(int(v.in_process)<<3)|v.route_type)
    if v.navigable:
        out.append((v.rank<<5)|(v.divider_loc<<2)
                   |(int(v.divider_legal)<<1)|int(v.multi_digitized))
        out+=encode_type1(v.attribute_index)
    out+=encode_type1(v.position_count)
    for off in v.text_offsets:
        check("text offset",off,0,65535)
        out+=off.to_bytes(2,"big")
    return bytes(out)

def decode_full_polyline(raw:bytes,*,min_lat:int,min_lon:int,scale:int=0)->FullPolyline:
    if len(raw)<4 or raw[0]&0x80:raise RecordError("Not a complete full polyline")
    offset=int.from_bytes(raw[:2],"big")
    text_count=raw[2];kind,p=decode_type1(raw,3)
    lat,p=decode_type4(raw,p);lon,p=decode_type4(raw,p)
    if p>=len(raw):raise RecordError("Missing polyline flags")
    flag=raw[p];p+=1
    if flag&0x10:raise RecordError("Reserved polyline flag")
    navigable=bool(flag&0x80)
    rank=attribute=None;divider=0;legal=multi=False
    if navigable:
        if p>=len(raw):raise RecordError("Missing rank/divider")
        a=raw[p];p+=1
        rank=a>>5;divider=(a>>2)&7
        legal=bool(a&2);multi=bool(a&1)
        attribute,p=decode_type1(raw,p)
    count,p=decode_type1(raw,p)
    if len(raw)-p!=text_count*2:
        raise RecordError("Polyline text offset count/record boundary mismatch")
    texts=tuple(int.from_bytes(raw[p+i*2:p+i*2+2],"big") for i in range(text_count))
    value=FullPolyline(offset,kind,min_lat+(lat<<scale),min_lon+(lon<<scale),
                       navigable,(flag>>5)&3,flag&7,count,texts,rank,
                       divider,legal,multi,attribute,bool(flag&8))
    if encode_full_polyline(value,min_lat=min_lat,min_lon=min_lon,scale=scale)!=raw:
        raise RecordError("Full polyline byte mismatch")
    return value

@dataclass(frozen=True)
class CartographicPosition:
    latitude_ntu:int
    longitude_ntu:int
    internal:bool=False
    pen_toggle:bool=False

def encode_carto_position(v:CartographicPosition,*,prev_lat:int,prev_lon:int,scale:int=0)->bytes:
    check("scale",scale,0,15)
    unit=1<<scale;dl=prev_lat-v.latitude_ntu;dn=prev_lon-v.longitude_ntu
    if dl%unit or dn%unit:raise RecordError("Position delta loses OSM precision")
    dl//=unit;dn//=unit
    check("latitude delta",dl,-1024,1023)
    check("longitude delta",dn,-1024,1023)
    return ((int(v.internal)<<23)|(int(v.pen_toggle)<<22)
            |((dl&2047)<<11)|(dn&2047)).to_bytes(3,"big")

def decode_carto_position(raw:bytes,*,prev_lat:int,prev_lon:int,scale:int=0)->CartographicPosition:
    if len(raw)!=3:raise RecordError("Position record must be three bytes")
    check("scale",scale,0,15);w=int.from_bytes(raw,"big")
    dl=(w>>11)&2047;dn=w&2047
    if dl>=1024:dl-=2048
    if dn>=1024:dn-=2048
    v=CartographicPosition(prev_lat-(dl<<scale),prev_lon-(dn<<scale),
                            bool(w&0x800000),bool(w&0x400000))
    if encode_carto_position(v,prev_lat=prev_lat,prev_lon=prev_lon,scale=scale)!=raw:
        raise RecordError("Position byte mismatch")
    return v

def encode_carto_positions(*,start_lat:int,start_lon:int,
                           points:tuple[CartographicPosition,...],scale:int=0)->bytes:
    out=bytearray();lat=start_lat;lon=start_lon
    for v in points:
        out+=encode_carto_position(v,prev_lat=lat,prev_lon=lon,scale=scale)
        lat=v.latitude_ntu;lon=v.longitude_ntu
    return bytes(out)

def decode_carto_positions(raw:bytes,*,start_lat:int,start_lon:int,
                           scale:int=0)->tuple[CartographicPosition,...]:
    if len(raw)%3:raise RecordError("Misaligned position array")
    out=[];lat=start_lat;lon=start_lon
    for i in range(0,len(raw),3):
        v=decode_carto_position(raw[i:i+3],prev_lat=lat,prev_lon=lon,scale=scale)
        out.append(v);lat=v.latitude_ntu;lon=v.longitude_ntu
    return tuple(out)

@dataclass(frozen=True)
class ShortPolylineTwoPoint:
    full_record_index:int
    start_lat:int
    start_lon:int
    end_lat:int
    end_lon:int

def encode_short_polyline_two_point(v:ShortPolylineTwoPoint,*,min_lat:int,min_lon:int,scale:int=0)->bytes:
    check("full record index",v.full_record_index,0,4079)
    check("scale",scale,0,15)
    step=1<<scale;a=v.start_lat-v.end_lat;b=v.start_lon-v.end_lon
    if min(a,b)<0 or a%step or b%step:
        raise RecordError("Short polyline delta is not representable")
    a//=step;b//=step
    check("short latitude",a,0,127);check("short longitude",b,0,127)
    return (bytes((0x80|a,b))+encode_type1(v.full_record_index)
            +encode_type4(scale_delta(v.start_lat,min_lat,scale))
            +encode_type4(scale_delta(v.start_lon,min_lon,scale)))

def decode_short_polyline_two_point(raw:bytes,*,min_lat:int,min_lon:int,
                                    scale:int=0)->ShortPolylineTwoPoint:
    if len(raw)<7 or not (raw[0]&0x80) or raw[1]&0x80:
        raise RecordError("Not a supported short two-point polyline")
    idx,p=decode_type1(raw,2)
    lat,p=decode_type4(raw,p);lon,p=decode_type4(raw,p)
    if p!=len(raw):raise RecordError("Additional short polyline deltas unsupported")
    a=min_lat+(lat<<scale);b=min_lon+(lon<<scale)
    v=ShortPolylineTwoPoint(idx,a,b,a-((raw[0]&127)<<scale),b-(raw[1]<<scale))
    if encode_short_polyline_two_point(v,min_lat=min_lat,min_lon=min_lon,scale=scale)!=raw:
        raise RecordError("Short polyline byte mismatch")
    return v

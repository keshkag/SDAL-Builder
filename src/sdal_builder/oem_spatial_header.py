"""Exact fixed SptlPclHdr_t codec (SDAL PSF 1.7 §1.4.0.2).

This is the COMMON 92-byte prefix of spatial parcel headers (types 0..6).
A complete type-0 routing/type-1 cartographic parcel requires the
additional type-specific BlkDesc structures and actual encoded records.
A compressed OEM parcel's fields beyond PclHdr_t must be decompressed
before being passed to decode_spatial_header().
"""
from __future__ import annotations
from dataclasses import dataclass
import struct

PCL = struct.Struct(">IHBBBBHHHHH")           # PclHdr_t: 20 B
XRF = struct.Struct(">5H2B")                  # 12 B
RECT = struct.Struct(">4i")                   # DBRect_t: 16 B
SPATIAL_FIELDS = struct.Struct(">5H2B")       # 12 B
FIXED_HEADER_BYTES = PCL.size+XRF.size+3*RECT.size+SPATIAL_FIELDS.size


class SpatialHeaderError(ValueError):
    pass


@dataclass(frozen=True)
class DBRect:
    min_long: int
    min_lat: int
    max_long: int
    max_lat: int

    def __post_init__(self):
        if any(not isinstance(v,int) or isinstance(v,bool)
               or not -(1<<31)<=v<(1<<31)
               for v in (self.min_long,self.min_lat,self.max_long,self.max_lat)):
            raise SpatialHeaderError("DBRect coordinate outside signed32 NTU")


@dataclass(frozen=True)
class SpatialFixedHeader:
    pcl_raw: bytes
    xrf_fields: tuple[int,int,int,int,int,int,int]
    bounding_rect: DBRect
    tile_rect: DBRect
    ancestor_rect: DBRect
    kd_fields: tuple[int,int,int,int,int,int,int]

    @property
    def parcel_id(self) -> int:
        return PCL.unpack(self.pcl_raw)[0]

    @property
    def parcel_type(self) -> int:
        return PCL.unpack(self.pcl_raw)[2]


def encode_spatial_header(value: SpatialFixedHeader) -> bytes:
    if not isinstance(value,SpatialFixedHeader) or len(value.pcl_raw)!=20:
        raise SpatialHeaderError("Invalid 20-byte common spatial parcel header")
    pid,desc,kind,region,endian,hi,lo,compression,data,uncomp,ext = PCL.unpack(value.pcl_raw)
    if kind not in range(7) or region!=1 or endian!=0:
        raise SpatialHeaderError("Expected type 0..6, region 1, original byte order")
    try:
        result=bytearray(value.pcl_raw)
        result.extend(XRF.pack(*value.xrf_fields))
        for rectangle in (value.bounding_rect,value.tile_rect,value.ancestor_rect):
            result.extend(RECT.pack(rectangle.min_long,rectangle.min_lat,
                                    rectangle.max_long,rectangle.max_lat))
        result.extend(SPATIAL_FIELDS.pack(*value.kd_fields))
    except (ValueError,TypeError,struct.error) as err:
        raise SpatialHeaderError("Spatial fixed header field outside wire range") from err
    if len(result)!=FIXED_HEADER_BYTES:
        raise SpatialHeaderError("SDAL spatial header must be 92 bytes")
    return bytes(result)


def decode_spatial_header(raw: bytes) -> SpatialFixedHeader:
    if len(raw)<FIXED_HEADER_BYTES:
        raise SpatialHeaderError("Truncated spatial fixed header")
    common=raw[:20]
    if PCL.unpack(common)[7]!=0:
        raise SpatialHeaderError(
            "Compressed parcel body: decode using specified SZIP first")
    xr=XRF.unpack_from(raw,PCL.size)
    start=PCL.size+XRF.size
    rects=tuple(DBRect(*RECT.unpack_from(raw,start+i*RECT.size)) for i in range(3))
    fields=SPATIAL_FIELDS.unpack_from(raw,start+3*RECT.size)
    model=SpatialFixedHeader(common,xr,*rects,fields)
    if encode_spatial_header(model)!=raw[:FIXED_HEADER_BYTES]:
        raise SpatialHeaderError("Spatial common prefix failed byte parity")
    return model


def make_spatial_header(*, parcel_id: int, parcel_type: int, bounds: DBRect,
                        tile: DBRect, ancestor: DBRect,
                        scale: int, layer: int) -> bytes:
    """Generate a real uncompressed fixed header, not a complete map parcel.

    All type-specific block descriptors, compression and source geometry
    must be written after this prefix by their specialized producer.
    """
    if not 0<=parcel_id<=0xffffffff or not 0<=parcel_type<=6:
        raise SpatialHeaderError("Invalid spatial parcel ID or type")
    if not 0<=scale<=255 or not 0<=layer<=4:
        raise SpatialHeaderError("Invalid spatial scale or layer")
    common=PCL.pack(parcel_id,0,parcel_type,1,0,0,0,0,0,0,0)
    model=SpatialFixedHeader(
        common,(0,0,0,0,0,0,0),
        bounds,tile,ancestor,(0,0,0,0,0,scale,layer))
    result=encode_spatial_header(model)
    if decode_spatial_header(result).parcel_id!=parcel_id:
        raise SpatialHeaderError("Generated spatial header failed self-check")
    return result

"""Global Media Header normalized routing attributes and PSF identity codec.

PSF SDAL 1.7 v0.4 §2.1.1.3, printed pages 2-5–2-9:
ucaNormalizedAttrs[256][4] is EXACTLY 1024 bytes starting at byte0.
Each entry encodes SpeedCat (3), LaneCat (2), Access (10) and
Display characteristics (17) in 32-bit big endian wire order.

This is one documented fixed-header family; generic extension table
count and some vendor-specific fields remain external authority.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct

from .oem_global_media_index import (
    GlobalIndexError,ordered_root_index_types,EXTERNAL_BITMAP_AT,
    EXTERNAL_BITMAP_BYTES,INTERNAL_BITMAP_AT,INTERNAL_BITMAP_BYTES
)
from .oem_media_allocator import HEADER_BYTES

ATTRS_LENGTH=1024
ATTRS_COUNT=256
PSF_VERSION_AT=1258
PSF_VERSION_SIZE=9
NODE_COSTS_AT=1267
NODE_COSTS_COUNT=32
VENDOR_MASK_AT=1335
FIRST_ICON_PID_AT=1339
AFFIX_REF_AT=1343


@dataclass(frozen=True)
class NormalizedAttribute:
    speed_category:int
    lane_category:int
    access_mask:int
    display_mask:int

    def __post_init__(self) -> None:
        values=((self.speed_category,7,"SpeedCat"),
                (self.lane_category,3,"LaneCat"),
                (self.access_mask,1023,"Access flags"),
                (self.display_mask,131071,"Display flags"))
        for value,limit,name in values:
            if (not isinstance(value,int) or isinstance(value,bool) or
                    not 0<=value<=limit):
                raise GlobalIndexError(name+" exceeds normalized-attribute bitfield")

    def to_word(self)->int:
        return (self.speed_category<<29)|(self.lane_category<<27)|(
                self.access_mask<<17)|self.display_mask

    @classmethod
    def from_word(cls,word:int)->"NormalizedAttribute":
        if not isinstance(word,int) or not 0<=word<=0xffffffff:
            raise GlobalIndexError("Invalid four-byte normalized-attribute word")
        return cls((word>>29)&7,(word>>27)&3,(word>>17)&1023,
                   word&0x1ffff)


@dataclass(frozen=True)
class PSFIdentity:
    major:int
    minor:int
    issue:int
    point:int
    psf_type:int
    day:int
    month:int
    year:int

    def __post_init__(self) -> None:
        for name,value in (("major",self.major),("minor",self.minor),
                           ("issue",self.issue),("point",self.point),
                           ("type",self.psf_type),("day",self.day),
                           ("month",self.month)):
            if not isinstance(value,int) or not 0<=value<=255:
                raise GlobalIndexError("PSF "+name+" outside Uchar")
        if (not 1<=self.day<=31 or not 1<=self.month<=12 or
                not 1996<=self.year<=65535):
            raise GlobalIndexError("PSF media date outside specification range")

    def encode(self)->bytes:
        return struct.pack(">7BH",self.major,self.minor,self.issue,self.point,
                           self.psf_type,self.day,self.month,self.year)

    @classmethod
    def decode(cls,raw:bytes)->"PSFIdentity":
        if not isinstance(raw,bytes) or len(raw)!=PSF_VERSION_SIZE:
            raise GlobalIndexError("PSFIdentity wire profile requires 9 bytes")
        return cls(*struct.unpack(">7BH",raw))


def decode_normalized_attributes(header:bytes)->tuple[NormalizedAttribute,...]:
    if not isinstance(header,bytes) or len(header)!=HEADER_BYTES:
        raise GlobalIndexError("GlbMediaHeader_t requires 2048 bytes")
    words=struct.unpack_from(">256I",header,0)
    values=tuple(NormalizedAttribute.from_word(n) for n in words)
    if encode_normalized_attributes(values)!=header[:ATTRS_LENGTH]:
        raise GlobalIndexError("Global normalized attributes did not roundtrip")
    return values


def encode_normalized_attributes(attributes:tuple[NormalizedAttribute,...])->bytes:
    if (not isinstance(attributes,tuple) or len(attributes)!=ATTRS_COUNT or
            not all(isinstance(a,NormalizedAttribute) for a in attributes)):
        raise GlobalIndexError("Global normalized attribute array must contain 256 declared entries")
    return struct.pack(">256I",*(a.to_word() for a in attributes))


@dataclass(frozen=True)
class HeaderCoreFields:
    normalized_attributes:tuple[NormalizedAttribute,...]
    external_bitmap:bytes
    internal_bitmap:bytes
    identity:PSFIdentity
    node_costs:tuple[int,...]
    vendor_mask:int

    def __post_init__(self):
        encode_normalized_attributes(self.normalized_attributes)
        ordered_root_index_types(self.external_bitmap)
        if not isinstance(self.internal_bitmap,bytes) or len(self.internal_bitmap)!=4:
            raise GlobalIndexError("Internal index bitmap must contain four bytes")
        if not isinstance(self.identity,PSFIdentity):
            raise GlobalIndexError("PSF version fields are required")
        if not isinstance(self.node_costs,tuple) or len(self.node_costs)!=32:
            raise GlobalIndexError("Exact 32-entry global node cost table required")
        if any(not isinstance(n,int) or isinstance(n,bool) or not 0<=n<=0xffff
               for n in self.node_costs):
            raise GlobalIndexError("Invalid Ushort_t permanent node cost")
        if not isinstance(self.vendor_mask,int) or not 0<=self.vendor_mask<=0xffffffff:
            raise GlobalIndexError("TPD vendor mask outside Ulong_t")


def decode_header_core(header:bytes)->HeaderCoreFields:
    if not isinstance(header,bytes) or len(header)!=HEADER_BYTES:
        raise GlobalIndexError("Missing actual 2048-byte Global Media Header")
    return HeaderCoreFields(
       decode_normalized_attributes(header),
       header[EXTERNAL_BITMAP_AT:EXTERNAL_BITMAP_AT+EXTERNAL_BITMAP_BYTES],
       header[INTERNAL_BITMAP_AT:INTERNAL_BITMAP_AT+INTERNAL_BITMAP_BYTES],
       PSFIdentity.decode(header[PSF_VERSION_AT:PSF_VERSION_AT+PSF_VERSION_SIZE]),
       struct.unpack_from(">32H",header,NODE_COSTS_AT),
       struct.unpack_from(">I",header,VENDOR_MASK_AT)[0],
    )


def write_header_core(header:bytes,fields:HeaderCoreFields)->bytes:
    if not isinstance(header,bytes) or len(header)!=HEADER_BYTES:
        raise GlobalIndexError("Existing Global Media Header must occupy 2048 bytes")
    if not isinstance(fields,HeaderCoreFields):
        raise GlobalIndexError("Complete normalized attribute/PSF core authority required")
    output=bytearray(header)
    output[:ATTRS_LENGTH]=encode_normalized_attributes(fields.normalized_attributes)
    output[EXTERNAL_BITMAP_AT:EXTERNAL_BITMAP_AT+8]=fields.external_bitmap
    output[INTERNAL_BITMAP_AT:INTERNAL_BITMAP_AT+4]=fields.internal_bitmap
    output[PSF_VERSION_AT:PSF_VERSION_AT+9]=fields.identity.encode()
    struct.pack_into(">32H",output,NODE_COSTS_AT,*fields.node_costs)
    struct.pack_into(">I",output,VENDOR_MASK_AT,fields.vendor_mask)
    result=bytes(output)
    if decode_header_core(result)!=fields:
        raise GlobalIndexError("Written global core fields did not roundtrip")
    return result

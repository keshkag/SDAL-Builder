"""SDAL 1.7 global media-size authority and deterministic region allocator.

PSF v0.4 §§1.2.4.5,1.4.0.2,2.1.1.3. GlbMediaHeader_t contains
128 Uchar sector-length entries at byte 1122; direct ParcelIDs address
only indices 0..63. usBlockSize is the sector-size exponent 8..11.
This module does not invent the remaining global header or region catalog.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
import struct
from .oem_spatial_header import PCL
from .oem_index import compose_parcel_id

HEADER_BYTES=2048
SIZES_AT=1122
COUNT_AT=1250
NEXT_AT=1251
SHIFT_AT=1252

class MediaLayoutError(ValueError): pass

def _u(label,value,low,high):
    if not isinstance(value,int) or isinstance(value,bool) or not low<=value<=high:
        raise MediaLayoutError(f"{label} outside {low}..{high}")

@dataclass(frozen=True)
class MediaSizeTable:
    sector_shift:int
    sector_counts:tuple[int,...]
    def __post_init__(self):
        if self.sector_shift not in (8,9,10,11):
            raise MediaLayoutError("usBlockSize must be exponent 8..11")
        if not isinstance(self.sector_counts,tuple) or not 1<=len(self.sector_counts)<=128:
            raise MediaLayoutError("ucParcelSizeCount outside 1..128")
        for count in self.sector_counts:_u("ucaParcelSizes length",count,1,255)
    @property
    def sector_bytes(self):return 1<<self.sector_shift
    def bytes_for(self,index:int)->int:
        _u("direct size index",index,0,63)
        if index>=len(self.sector_counts):
            raise MediaLayoutError("Index beyond ucParcelSizeCount")
        return self.sector_counts[index]*self.sector_bytes
    def best_index(self,needed:int,*,maximum:int=32768)->int:
        _u("required payload bytes",needed,1,0xffffffff)
        choices=[(self.bytes_for(i),i) for i in range(min(len(self.sector_counts),64))
                 if needed<=self.bytes_for(i)<=maximum]
        if not choices:raise MediaLayoutError("No ucaParcelSizes capacity fits payload")
        return min(choices)[1]
    def size_authority(self):
        from .oem_parcel_assembly import SizeAuthority
        return SizeAuthority(self.sector_bytes,
            {i:self.bytes_for(i) for i in range(min(64,len(self.sector_counts)))
             if self.bytes_for(i)<=65535})

@dataclass(frozen=True)
class MediaSizeFields:
    table:MediaSizeTable
    next_index_sectors:int
    block_number_bits:int
    block_size_bits:int
    def __post_init__(self):
        _u("ucNextParcelLen",self.next_index_sectors,1,255)
        _u("usBlockNbrBits",self.block_number_bits,0,65535)
        _u("usBlockSizeBits",self.block_size_bits,0,65535)

def parse_media_size_fields(header:bytes)->MediaSizeFields:
    if not isinstance(header,bytes) or len(header)!=HEADER_BYTES:
        raise MediaLayoutError("GlbMediaHeader_t requires an exact 2048-byte image")
    count=header[COUNT_AT]
    _u("ucParcelSizeCount",count,1,128)
    shift,numbits,indexbits=struct.unpack_from(">HHH",header,SHIFT_AT)
    return MediaSizeFields(MediaSizeTable(shift,tuple(header[SIZES_AT:SIZES_AT+count])),
                           header[NEXT_AT],numbits,indexbits)

def write_media_size_fields(header:bytes,fields:MediaSizeFields)->bytes:
    if not isinstance(header,bytes) or len(header)!=HEADER_BYTES:
        raise MediaLayoutError("Existing exact 2048-byte media header required")
    if not isinstance(fields,MediaSizeFields):
        raise MediaLayoutError("Declared media size fields required")
    data=bytearray(header)
    data[SIZES_AT:COUNT_AT]=bytes(fields.table.sector_counts).ljust(128,b"\0")
    data[COUNT_AT]=len(fields.table.sector_counts)
    data[NEXT_AT]=fields.next_index_sectors
    struct.pack_into(">HHH",data,SHIFT_AT,fields.table.sector_shift,
                     fields.block_number_bits,fields.block_size_bits)
    result=bytes(data)
    if parse_media_size_fields(result)!=fields:
        raise MediaLayoutError("Media-size fields failed readback")
    return result

@dataclass(frozen=True)
class ParcelRequest:
    key:str
    parcel_type:int
    minimum_bytes:int
    size_index:int|None=None
    fixed_offset:int|None=None
    redundant:bool=False
    def __post_init__(self):
        if not isinstance(self.key,str) or not self.key or self.key.strip()!=self.key:
            raise MediaLayoutError("Stable nonblank parcel key required")
        _u("parcel type",self.parcel_type,0,255)
        if self.parcel_type not in (0,1,255):
            raise MediaLayoutError("No verified physical payload producer for requested parcel type")
        _u("payload minimum",self.minimum_bytes,20,0xffffffff)
        if self.size_index is not None:_u("size index",self.size_index,0,63)
        if self.fixed_offset is not None:_u("fixed offset",self.fixed_offset,0,0xffffffff)
        if self.parcel_type==255:
            if not self.redundant or self.minimum_bytes!=0x5000:
                raise MediaLayoutError("Observed global KD index needs redundant 0x5000 profile")
        elif self.redundant:
            raise MediaLayoutError("Nonindex redundancy needs a real redundancy table")

@dataclass(frozen=True)
class Placement:
    key:str
    parcel_type:int
    start:int
    length:int
    size_index:int
    pid:int
    redundant:bool
    @property
    def end(self):return self.start+self.length

@dataclass(frozen=True)
class RegionLayout:
    table:MediaSizeTable
    parcels:tuple[Placement,...]
    prefix_bytes:int
    @property
    def file_bytes(self):return max(p.end for p in self.parcels)
    def get(self,key:str)->Placement:
        found=[p for p in self.parcels if p.key==key]
        if len(found)!=1:raise MediaLayoutError("Unknown or ambiguous parcel key "+key)
        return found[0]
    def render(self,contents:Mapping[str,bytes],*,prefix:bytes)->bytes:
        if not isinstance(prefix,bytes) or len(prefix)!=self.prefix_bytes:
            raise MediaLayoutError("Caller-owned regional metadata prefix required")
        if set(contents)!={p.key for p in self.parcels}:
            raise MediaLayoutError("All planned parcels must be published exactly once")
        image=bytearray(self.file_bytes)
        image[:self.prefix_bytes]=prefix
        for p in self.parcels:
            blob=contents[p.key]
            if not isinstance(blob,bytes) or len(blob)!=p.length:
                raise MediaLayoutError("Payload size differs from media table allocation")
            h=PCL.unpack_from(blob)
            if (h[0],h[2],h[3],h[4])!=(p.pid,p.parcel_type,1,0):
                raise MediaLayoutError("PclHdr PID/type/region contradicts allocation")
            if p.parcel_type==255:
                from .oem_index import decode_index_parcel
                decode_index_parcel(blob,absolute_offset=p.start)
            image[p.start:p.end]=blob
        result=bytes(image)
        self.verify(result)
        return result
    def verify(self,raw:bytes)->None:
        if not isinstance(raw,bytes) or len(raw)!=self.file_bytes:
            raise MediaLayoutError("Regional file physical extent incorrect")
        for p in self.parcels:
            if self.table.bytes_for(p.size_index)!=p.length:
                raise MediaLayoutError("Published parcel length contradicts ucaParcelSizes")
            pid=compose_parcel_id(file_offset=p.start,size_index=p.size_index,
                   redundancy=p.redundant,address_unit=self.table.sector_bytes)
            if pid!=p.pid:raise MediaLayoutError("Noncanonical placed ParcelID")
            h=PCL.unpack_from(raw,p.start)
            if (h[0],h[2],h[3],h[4])!=(p.pid,p.parcel_type,1,0):
                raise MediaLayoutError("Region byte-level PID/type/region mismatch")
            if p.parcel_type in (0,1):
                from .oem_parcel_assembly import verify_bounded_parcel
                try:
                    verify_bounded_parcel(raw[p.start:p.end],
                        authority=self.table.size_authority(),file_offset=p.start)
                except ValueError as exc:
                    raise MediaLayoutError(
                        "Typed spatial parcel physical graph failed verification: "+str(exc)) from exc
            elif p.parcel_type==255:
                from .oem_index import decode_index_parcel
                decode_index_parcel(raw[p.start:p.end],absolute_offset=p.start)

def allocate_region(table:MediaSizeTable,requests:Sequence[ParcelRequest],*,
                    prefix_bytes:int)->RegionLayout:
    if not isinstance(table,MediaSizeTable):raise MediaLayoutError("Media size authority required")
    sector=table.sector_bytes
    _u("region metadata prefix",prefix_bytes,sector,0xffffffff)
    if prefix_bytes%sector:raise MediaLayoutError("Unaligned region prefix")
    if not requests or not all(isinstance(r,ParcelRequest) for r in requests):
        raise MediaLayoutError("Nonempty parcel request set required")
    order=sorted(requests,key=lambda r:r.key)
    if len({r.key for r in order})!=len(order):
        raise MediaLayoutError("Duplicate parcel owner key")
    chosen=[]
    for r in order:
        index=table.best_index(r.minimum_bytes) if r.size_index is None else r.size_index
        length=table.bytes_for(index)
        if length<r.minimum_bytes:raise MediaLayoutError("Parcel does not fit declared size index")
        if r.parcel_type in (0,1) and length>32768:
            raise MediaLayoutError("Uncompressed spatial parcel exceeds 32K")
        if r.parcel_type==255 and (sector!=256 or index!=8 or length!=0x5000):
            raise MediaLayoutError("Unsupported OEM index size/sector profile")
        chosen.append((r,index,length))
    intervals=[(0,prefix_bytes)]
    addresses={}
    for r,index,length in chosen:
        if r.fixed_offset is None:continue
        at=r.fixed_offset
        if at%sector:raise MediaLayoutError("Unaligned fixed parcel position")
        if at//sector>0xffffff:raise MediaLayoutError("ParcelID direct offset overflow")
        if any(at<b and a<at+length for a,b in intervals):
            raise MediaLayoutError("Fixed range overlaps existing/reserved parcel")
        intervals.append((at,at+length));addresses[r.key]=at
    for r,index,length in chosen:
        if r.fixed_offset is not None:continue
        at=prefix_bytes
        while True:
            conflicts=[(a,b) for a,b in intervals if at<b and a<at+length]
            if not conflicts:break
            at=((max(b for _,b in conflicts)+sector-1)//sector)*sector
        if at//sector>0xffffff:raise MediaLayoutError("ParcelID direct offset overflow")
        intervals.append((at,at+length));addresses[r.key]=at
    placements=[]
    for r,index,length in chosen:
        at=addresses[r.key]
        pid=compose_parcel_id(file_offset=at,size_index=index,
               redundancy=r.redundant,address_unit=sector)
        placements.append(Placement(r.key,r.parcel_type,at,length,index,pid,r.redundant))
    placements.sort(key=lambda p:(p.start,p.key))
    if any(a.end>b.start for a,b in zip(placements,placements[1:])):
        raise MediaLayoutError("Overlapping parcel extents")
    return RegionLayout(table,tuple(placements),prefix_bytes)

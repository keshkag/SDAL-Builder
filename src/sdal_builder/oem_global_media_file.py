"""Deterministic SDAL 1.7 Global Media File assembler (bounded reference data).

Bootstrap parcels are the raw 2048-byte GlbMediaHeader_t and
ucNextParcelLen*sector-size Global Media Index. Reference data follows.
Each actual record payload is caller-authored and is NOT created by
inventing a reference-data schema. This compiler never claims that an
incomplete set of global reference families is a finished Denso catalog.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Sequence

from .oem_index import compose_parcel_id
from .oem_spatial_header import PCL
from .oem_media_allocator import parse_media_size_fields
from .oem_global_media_index import (
    GlobalIndexError, RefDataEntry, BuiltGlobalIndex,
    REF_FAMILIES, build_global_media_index,
    verify_global_reference_targets, verify_global_media_index,
)


@dataclass(frozen=True)
class ReferenceSource:
    """Already encoded reference records, not inferred from OSM identifiers."""
    family: str
    owner: str
    parcel_type: int
    payload: bytes
    index_offset: int
    description_offset: int
    last_index: int

    def __post_init__(self) -> None:
        if self.family not in REF_FAMILIES or not isinstance(self.owner,str) or not self.owner:
            raise GlobalIndexError("Unknown reference family or owner")
        if not isinstance(self.payload,bytes) or not self.payload:
            raise GlobalIndexError("Actual nonempty encoded reference data required")
        if not isinstance(self.parcel_type,int) or not 0<=self.parcel_type<=254:
            raise GlobalIndexError("Global reference parcel type outside Uchar")
        for key, value in (("index offset",self.index_offset),
                           ("description offset",self.description_offset)):
            if not isinstance(value,int) or not PCL.size<=value<PCL.size+len(self.payload):
                raise GlobalIndexError(key+" points outside actual reference data")
        if not isinstance(self.last_index,int) or not 0<=self.last_index<=65535:
            raise GlobalIndexError("Reference extent end outside Ushort")


@dataclass(frozen=True)
class ReferencePlacement:
    source: ReferenceSource
    parcel_id: int
    file_offset: int
    capacity_bytes: int

    @property
    def end(self) -> int:
        return self.file_offset+self.capacity_bytes


@dataclass(frozen=True)
class BuiltGlobalMedia:
    image: bytes
    index: BuiltGlobalIndex
    placements: tuple[ReferencePlacement,...]

    def verify(self) -> None:
        verify_global_media_index(self.index)
        verify_global_reference_targets(self.index,self.image,referenced_metadata=False)
        if len(self.image)<self.index.next_data_start or (
            self.image[:self.index.next_data_start] !=
            self.index.media_header+self.index.index_parcel):
            raise GlobalIndexError("Global media bootstrap bytes disagree")
        previous=self.index.next_data_start
        found=[]
        for p in self.placements:
            if p.file_offset<previous:
                raise GlobalIndexError("Global reference parcels overlap")
            if self.image[previous:p.file_offset] != bytes(p.file_offset-previous):
                raise GlobalIndexError("Nonzero bytes in unallocated Global Media gap")
            physical=self.image[p.file_offset:p.end]
            if len(physical)!=p.capacity_bytes:
                raise GlobalIndexError("Truncated global reference parcel")
            fields=PCL.unpack_from(physical)
            if (fields[0],fields[2],fields[3],fields[4])!=(
                    p.parcel_id,p.source.parcel_type,0,0):
                raise GlobalIndexError("Global reference PclHdr differs from plan")
            if physical[PCL.size:PCL.size+len(p.source.payload)]!=p.source.payload:
                raise GlobalIndexError("Physical global reference content modified")
            if physical[PCL.size+len(p.source.payload):] != bytes(
                    p.capacity_bytes-PCL.size-len(p.source.payload)):
                raise GlobalIndexError("Physical global parcel contains unauthored bytes")
            found.append(p.parcel_id)
            previous=p.end
        if previous!=len(self.image):
            raise GlobalIndexError("Global media file has unplanned trailer")
        claimed=tuple(e.parcel_id for _,items in self.index.ref_tables for e in items)
        if set(claimed)!=set(found) or len(claimed)!=len(set(claimed)):
            raise GlobalIndexError("Unreferenced or duplicate global data parcel")


def assemble_global_media(
    source_header: bytes,
    sources: Sequence[ReferenceSource], *,
    locale: bytes | None = None
) -> BuiltGlobalMedia:
    """Allocates all physical global reference parcels AFTER the index.

    PIDs are generated from exactly the media table the header supplies.
    A source may not refer to a second, unprovided data parcel. Authored
    body bytes/semantics are caller-owned and preserved byte-for-byte.
    """
    fields=parse_media_size_fields(source_header)
    table=fields.table
    if not sources or not all(isinstance(s,ReferenceSource) for s in sources):
        raise GlobalIndexError("Nonempty authentic reference-data source set required")
    data=list(sorted(sources,key=lambda s:(REF_FAMILIES.index(s.family),
                                             s.last_index,s.owner)))
    if len({x.owner for x in data})!=len(data):
        raise GlobalIndexError("Duplicate global reference data owner key")
    counts={}
    for s in data:
        if s.family in counts and s.last_index<=counts[s.family]:
            raise GlobalIndexError("Nonascending global reference record extents")
        counts[s.family]=s.last_index

    physical_at=2048+fields.next_index_sectors*table.sector_bytes
    if physical_at%table.sector_bytes:
        raise GlobalIndexError("Global data starts at unaligned sector")
    placements=[]
    grouped={}
    for source in data:
        required=PCL.size+len(source.payload)
        index=table.best_index(required,maximum=32768)
        capacity=table.bytes_for(index)
        parcel_id=compose_parcel_id(file_offset=physical_at,
                    size_index=index,redundancy=False,address_unit=table.sector_bytes)
        p=ReferencePlacement(source,parcel_id,physical_at,capacity)
        placements.append(p)
        grouped.setdefault(source.family,[]).append(
            RefDataEntry(parcel_id,source.index_offset,
                         source.description_offset,source.last_index))
        physical_at=p.end

    index=build_global_media_index(source_header,
          references={k:tuple(v) for k,v in grouped.items()},locale=locale)
    image=bytearray(physical_at)
    image[:index.next_data_start]=index.media_header+index.index_parcel
    for p in placements:
        header=PCL.pack(p.parcel_id,0,p.source.parcel_type,0,0,0,0,0,0,0,0)
        raw=header+p.source.payload
        image[p.file_offset:p.file_offset+len(raw)]=raw
    result=BuiltGlobalMedia(bytes(image),index,tuple(placements))
    result.verify()
    return result

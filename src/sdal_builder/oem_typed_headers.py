"""SDAL 1.7 typed fixed headers: cartographic and route-calculation parcels.

PSF v0.4 §§1.4.0.2, 3.2.2.1, 3.5.2.3.
The WE_06Q4 Cartographic profile has *observed* 2-byte first-ID fields
plus 2-byte end alignment, despite generic EntityID_t being Ulong_t.
This empirical profile is explicit, not silently generalized to all SDAL.
Only UNCOMPRESSED bodies are accepted. These headers do not by
themselves constitute complete route/cartographic record arrays.
"""
from __future__ import annotations
from dataclasses import dataclass
import struct
from .oem_spatial_header import (
    decode_spatial_header, SpatialHeaderError, FIXED_HEADER_BYTES
)

class TypedHeaderError(ValueError):
    pass

DESCRIPTOR_LAYOUTS = {
    "BlkDesc": struct.Struct(">HHBBHHH"),     # 12 B
    "BlkDesc1": struct.Struct(">HHIBBHHH"),   # 16 B
    "BlkDesc2": struct.Struct(">HHHH"),       # 8 B
    "BlkDesc3": struct.Struct(">HHH2s"),      # 8 B
    "BlkDesc4": struct.Struct(">HH"),         # 4 B
}
CARTO_FIELDS = (
    ("polygonDesc", "BlkDesc"), ("lineDesc", "BlkDesc"),
    ("pointDesc", "BlkDesc"), ("positionDesc", "BlkDesc3"),
    ("textDesc", "BlkDesc3"), ("textNameDesc", "BlkDesc3"),
    ("attribArrayDesc", "BlkDesc4"), ("longHaulAttrDesc", "BlkDesc4"),
    ("polygonLHBitmapDesc", "BlkDesc4"), ("polylineLHBitmapDesc", "BlkDesc4"),
    ("pointLHBitmapDesc", "BlkDesc4"),
)
ROUTING0_FIELDS = (
    ("nodeDesc", "BlkDesc1"), ("segmentDesc", "BlkDesc1"),
    ("extSegDesc", "BlkDesc2"), ("conditionDesc", "BlkDesc"),
    ("ghostNodeDesc", "BlkDesc2"), ("deltaShapeDesc", "BlkDesc3"),
    ("dateTimeDesc", "BlkDesc3"), ("attribArrayDesc", "BlkDesc4"),
    ("spatialIndexArrayDesc", "BlkDesc4"), ("aggrSegArrayDesc", "BlkDesc4"),
)
ROUTING1_FIELDS = (
    ("nodeDesc", "BlkDesc2"), ("segmentDesc", "BlkDesc2"),
    ("conditionDesc", "BlkDesc"), ("ghostNodeDesc", "BlkDesc2"),
    ("abbrevSegDesc", "BlkDesc3"), ("dateTimeDesc", "BlkDesc3"),
    ("attribArrayDesc", "BlkDesc4"), ("aggrSegArrayDesc", "BlkDesc4"),
)

def _schema(kind: int, layer: int):
    if kind == 1 and 0 <= layer <= 4:
        return CARTO_FIELDS, struct.Struct(">4B2s"), 184
    if kind == 0 and layer == 0:
        return ROUTING0_FIELDS, struct.Struct(">H8B2s"), 192
    if kind == 0 and 1 <= layer <= 4:
        return ROUTING1_FIELDS, struct.Struct(">HH8B"), 164
    raise TypedHeaderError("Only spatial type 0/1 and layer 0..4 supported")

@dataclass(frozen=True)
class TypedFixedHeader:
    parcel_type: int
    layer: int
    spatial_prefix: bytes
    first_polyline_id: int | None
    first_point_id: int | None
    descriptors: tuple[tuple[str, tuple], ...]
    maxima: tuple[int, ...]
    reserved: bytes
    trailing_alignment: bytes = b""

    @property
    def size(self):
        return _schema(self.parcel_type, self.layer)[2]


def decode_typed_fixed_header(data: bytes) -> TypedFixedHeader:
    try:
        spatial = decode_spatial_header(data)
    except SpatialHeaderError as exc:
        raise TypedHeaderError(str(exc)) from exc
    kind, layer = spatial.parcel_type, spatial.kd_fields[-1]
    schema, maximum, size = _schema(kind,layer)
    if len(data) < size:
        raise TypedHeaderError("Truncated typed spatial header")
    pos = FIXED_HEADER_BYTES
    first_line = first_point = None
    if kind == 1:
        first_line = int.from_bytes(data[pos:pos+2],"big")
        first_point = int.from_bytes(data[pos+2:pos+4],"big")
        pos += 4
    desc=[]
    for name,dtype in schema:
        layout=DESCRIPTOR_LAYOUTS[dtype]
        desc.append((name, layout.unpack_from(data,pos)))
        pos += layout.size
    tail=maximum.unpack_from(data,pos)
    pos += maximum.size
    reserved=tail[-1] if kind==1 or layer==0 else b""
    maxima=tail[:-1] if kind==1 or layer==0 else tail
    trailing=data[pos:size] if kind==1 else b""
    if pos+(2 if kind==1 else 0)!=size:
        raise TypedHeaderError("Unexpected type-specific header layout")
    if kind==1 and trailing!=b"\x00\x00":
        raise TypedHeaderError("Nonzero Cartographic alignment")
    result=TypedFixedHeader(kind,layer,data[:FIXED_HEADER_BYTES],
                            first_line,first_point,tuple(desc),tuple(maxima),
                            reserved,trailing)
    if encode_typed_fixed_header(result)!=data[:size]:
        raise TypedHeaderError("Typed header did not reproduce original bytes")
    return result


def encode_typed_fixed_header(h: TypedFixedHeader) -> bytes:
    if not isinstance(h,TypedFixedHeader):
        raise TypedHeaderError("Expected TypedFixedHeader")
    schema, maxlayout, size = _schema(h.parcel_type,h.layer)
    try:
        spatial=decode_spatial_header(h.spatial_prefix)
    except SpatialHeaderError as exc:
        raise TypedHeaderError(str(exc)) from exc
    if spatial.parcel_type!=h.parcel_type or spatial.kd_fields[-1]!=h.layer:
        raise TypedHeaderError("Spatial prefix type/layer mismatch")
    if len(h.spatial_prefix)!=FIXED_HEADER_BYTES:
        raise TypedHeaderError("Spatial prefix must be exactly 92 bytes")
    if tuple(k for k,_ in h.descriptors)!=tuple(k for k,_ in schema):
        raise TypedHeaderError("Descriptor names/order do not match specification")
    out=bytearray(h.spatial_prefix)
    if h.parcel_type==1:
        for name,number in (("firstPolylineId",h.first_polyline_id),
                            ("firstPointId",h.first_point_id)):
            if not isinstance(number,int) or not 0<=number<=0xFFFF:
                raise TypedHeaderError(name+" outside observed 16-bit OEM profile")
            out+=number.to_bytes(2,"big")
    elif h.first_polyline_id is not None or h.first_point_id is not None:
        raise TypedHeaderError("Routing header cannot encode Cartographic IDs")
    try:
        for (_,fields),(_,kind) in zip(h.descriptors,schema):
            out+=DESCRIPTOR_LAYOUTS[kind].pack(*fields)
        values=tuple(h.maxima)
        if h.parcel_type==1 or h.layer==0:
            if len(h.reserved)!=2:
                raise TypedHeaderError("Missing two reserved alignment bytes")
            values+=(h.reserved,)
        elif h.reserved:
            raise TypedHeaderError("Upper-layer routing has no trailing reserved bytes")
        out+=maxlayout.pack(*values)
    except (struct.error, TypeError, ValueError) as exc:
        raise TypedHeaderError("Descriptor/maximum outside wire range") from exc
    if h.parcel_type==1:
        if h.trailing_alignment!=b"\x00\x00":
            raise TypedHeaderError("Cartographic OEM profile requires 2-byte zero pad")
        out+=h.trailing_alignment
    elif h.trailing_alignment:
        raise TypedHeaderError("Unexpected Routing trailing alignment")
    if len(out)!=size:
        raise TypedHeaderError("Incorrect typed fixed-header byte length")
    return bytes(out)

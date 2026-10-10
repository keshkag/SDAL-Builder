"""SDAL 1.7 compact record block length-table codec.

PSF v0.4 §§3.2.2.6, 3.5.3.4, 3.5.4.3: each point/
polyline/routing variable-length block begins with (N+1)
Type-1 integers. The first gives the byte position of the
first record relative to the block start; the next N values
give each record's exact byte length.

This module DOES NOT invent the enclosing usOffset/usDataOffset
placement, segment/carto referential IDs or missing record formats.
"""
from __future__ import annotations
from dataclasses import dataclass
from .oem_typed_records import (
    encode_type1,decode_type1,RecordError,TYPE1_MAX
)

@dataclass(frozen=True)
class RecordBlock:
    records: tuple[bytes,...]
    raw: bytes
    first_record_offset: int
    record_lengths: tuple[int,...]


def encode_record_block(records:tuple[bytes,...]) -> RecordBlock:
    if not records or len(records)>256:
        raise RecordError("Block must have 1..256 records")
    for record in records:
        if not isinstance(record,bytes) or not 0<len(record)<=TYPE1_MAX:
            raise RecordError("Unencoded/empty or oversized record")
    lengths=tuple(len(record) for record in records)
    encoded_lengths=b"".join(encode_type1(n) for n in lengths)
    offset=0
    for _ in range(5):
        next_value=len(encode_type1(offset))+len(encoded_lengths)
        if next_value==offset:break
        offset=next_value
    else:
        raise RecordError("Block record offset did not converge")
    raw=(encode_type1(offset)+encoded_lengths+b"".join(records))
    if raw[offset:]!=b"".join(records):
        raise RecordError("Block length prefixes did not resolve")
    if len(raw)>65535:
        raise RecordError("Block cannot fit a 16-bit block extent")
    result=RecordBlock(records,raw,offset,lengths)
    if decode_record_block(raw,len(records))!=result:
        raise RecordError("Record block writer failed independent byte parity")
    return result


def decode_record_block(raw:bytes,count:int)->RecordBlock:
    if not isinstance(raw,bytes) or not 1<=count<=256:
        raise RecordError("Invalid record block/count")
    first,p=decode_type1(raw)
    lengths=[]
    for _ in range(count):
        n,p=decode_type1(raw,p)
        if n<=0:raise RecordError("Zero length SDAL record")
        lengths.append(n)
    if first!=p:
        raise RecordError("Block first-record offset disagrees with length table")
    start=first
    records=[]
    for n in lengths:
        if start+n>len(raw):
            raise RecordError("Record extends beyond SDAL block")
        records.append(raw[start:start+n])
        start+=n
    if start!=len(raw):
        raise RecordError("Trailing bytes after SDAL record block")
    if encode_type1(first)+b"".join(encode_type1(n) for n in lengths)+b"".join(records)!=raw:
        raise RecordError("Record block is not canonically encoded")
    return RecordBlock(tuple(records),raw,first,tuple(lengths))

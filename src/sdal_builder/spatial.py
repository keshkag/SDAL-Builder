"""
Spatial helpers for SDAL builder
———————————————
• KD-tree:  nearest-neighbour lookup using scipy.cKDTree  
• B+-tree:  on-disk index way_id (uint32) ➜ file-offset (uint64)

bplustree’s default **IntSerializer** handles *keys* that are Python
ints.  *Values*, however, must already be **bytes** whose length does
not exceed ``value_size`` (8 bytes for a uint64).  Passing a plain int
as the value triggered the earlier ``len(value)`` TypeError.
"""
from __future__ import annotations

import struct
from typing import Iterable, Tuple, List

from scipy.spatial import cKDTree
import bplustree


# --------------------------------------------------------------------------- #
# KD-tree helpers                                                             #
# --------------------------------------------------------------------------- #

def build_kdtree(points: List[Tuple[float, float]]) -> cKDTree:
    """Return a KD-tree built from *points* = [(x, y), …]."""
    return cKDTree(points)


def serialize_kdtree(kd: cKDTree) -> bytes:
    """Serialize KD-tree nodes:  <uint32 idx><int32 x*1e6><int32 y*1e6>."""
    buf = bytearray()
    for idx, (x, y) in enumerate(kd.data):
        buf.extend(struct.pack("<Iii", idx, int(x * 1e6), int(y * 1e6)))
    return bytes(buf)


# --------------------------------------------------------------------------- #
# B+-tree helpers                                                             #
# --------------------------------------------------------------------------- #

_pack_u64 = struct.Struct("<Q").pack          # little-endian uint64


def build_bplustree(offsets: Iterable[Tuple[int, int]], path: str) -> None:
    """
    Build an on-disk B+-tree mapping *way_id* (uint32 int) ➜ *offset* (uint64).

    * bplustree*’s default serializer accepts **int** keys directly.
    * Values **must** be bytes, so we pack the uint64 offset.
    """
    tree = bplustree.BPlusTree(path, key_size=4, value_size=8, order=50)

    for way_id, offs in offsets:
        tree.insert(way_id, _pack_u64(offs))

    tree.close()


def dump_bplustree(path: str) -> bytes:
    """Return the raw bytes of a finished B+-tree file."""
    with open(path, "rb") as f:
        return f.read()

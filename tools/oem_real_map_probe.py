#!/usr/bin/env python3
"""Read-only forensic comparison of OEM regional SDL0 and real map SDL1 bytes.

A self-addressed PclHdr_t-shaped candidate is NOT a validated parcel.
No OSM/ISO writer changes, and no proprietary OEM payloads are emitted.
"""
from __future__ import annotations
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import struct

HEADER = struct.Struct(">IHBBBBHHHHH")
UNIT = 256
SECTION = 16384
KNOWN_TYPES = frozenset((
    0,1,2,3,4,5,6,8,9,10,11,12,13,14,15,16,17,18,19,24,25,26,27,28,29,
    30,31,32,33,34,35,36,37,38,39,40,41,42,45,46,47,48,255,
))


class EvidenceError(ValueError):
    pass


def checked_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("Expected regular OEM source file: " + str(path))
    return path.read_bytes()


def header_at(buf: bytes, offset: int) -> dict:
    if offset < 0 or offset + HEADER.size > len(buf):
        raise EvidenceError("Truncated PclHdr_t at offset " + hex(offset))
    (pid, desc, typ, reg, endian, hi, lo, compress,
     cmp_offset, uncomp, ext) = HEADER.unpack_from(buf, offset)
    return {
        "offset": offset, "raw_header_hex": buf[offset:offset+20].hex(),
        "parcel_id": f"0x{pid:08X}", "size_index": (pid >> 24) & 63,
        "low24_address_units": pid & 0xffffff,
        "self_addressed_at_256_bytes": (pid & 0xffffff)*UNIT == offset,
        "external_bit_31": bool(pid & (1 << 31)),
        "redundancy_bit_30": bool(pid & (1 << 30)),
        "parcel_type": typ, "region": reg, "descriptor": desc,
        "endian": endian, "compressed_bits": (hi << 16) | lo,
        "compression_type": compress,
        "compressed_data_offset": cmp_offset,
        "uncompressed_size_field": uncomp,
        "extension_offset": ext,
    }


def region0_profile(buf: bytes) -> dict:
    if len(buf) < 0x2000 or (len(buf) - 0x2000) % SECTION != 0:
        raise EvidenceError("Regional SDL0 layout does not match sample's 8K+16K sections")
    starts = range(0x2000, len(buf), SECTION)
    headers = [header_at(buf, p) for p in starts]
    good = all(h["self_addressed_at_256_bytes"]
               and h["parcel_type"] == 19 and h["region"] == 0
               and h["size_index"] == 56
               and not h["external_bit_31"] and not h["redundancy_bit_30"]
               for h in headers)
    if not good:
        raise EvidenceError("Regional SDL0 observed header pattern failed")
    return {"file_bytes": len(buf), "prefix_bytes": 0x2000,
            "section_bytes": SECTION, "sections": len(headers),
            "all_header_candidates_conform": good}


def cartographic_candidate_scan(data: bytes) -> dict:
    """Report filtered candidates, not proven parcel count or uncompressed data."""
    count = 0
    types = Counter()
    profiles = Counter()
    flags = Counter()
    samples = []
    for pos in range(UNIT, len(data) - HEADER.size + 1, UNIT):
        (pid, desc, typ, reg, endian, hi, lo, cmp, off, uncomp, ext) = HEADER.unpack_from(data, pos)
        if ((pid & 0xffffff) * UNIT != pos or pid & (1 << 31)
                or endian != 0 or reg != 1 or typ not in KNOWN_TYPES):
            continue
        count += 1
        types[typ] += 1
        profiles[(typ, desc, cmp)] += 1
        flags["redundant" if pid & (1 << 30) else "nonredundant"] += 1
        if len(samples) < 20:
            samples.append(header_at(data, pos))
    return {
        "candidate_count_not_proven_parcels": count,
        "filters": "256-byte aligned; low24*256=current offset; region=1; endian=0; external flag clear; documented type or observed 255",
        "types": [{"type": t, "count": n} for t, n in sorted(types.items())],
        "largest_profiles": [
            {"type": t, "descriptor": d, "compression": c, "count": n}
            for (t,d,c),n in profiles.most_common(24)],
        "redundancy": dict(sorted(flags.items())),
        "first_20_candidates": samples,
    }


def linked_seven_word_markers(init: bytes, map1: bytes) -> list[dict]:
    """Match 28 literal bytes; deliberately do NOT interpret as a cross-file pointer."""
    matches = []
    for i in range(8):
        descriptor = 0x1C8 + i*16
        if descriptor + 8 > len(init):
            raise EvidenceError("INIT descriptor incomplete")
        at, length = struct.unpack_from(">II", init, descriptor)
        if length != 0x1800 or at + 28 > len(init):
            raise EvidenceError("INIT group length/location inconsistent")
        pattern = init[at:at+28]
        if pattern != pattern[:4]*7:
            raise EvidenceError("INIT's seven-word evidence did not match")
        places = []
        search_at = 0
        while len(places) < 20:
            found = map1.find(pattern, search_at)
            if found < 0:
                break
            places.append(found)
            search_at = found + 1
        matches.append({
            "init_group": i+1, "repeated_word": "0x"+pattern[:4].hex().upper(),
            "map1_exact_28_byte_matches": places,
            "interpretation": "literal signature only; pointer semantics unverified",
        })
    return matches


def analyze(init: bytes, benelux0: bytes, denswe0: bytes, benelux1: bytes) -> dict:
    shared = []
    for at in range(0, min(len(benelux0),len(denswe0)), 4096):
        a, b = benelux0[at:at+4096],denswe0[at:at+4096]
        if len(a) == len(b) == 4096 and len(set(a)) > 1 and a == b:
            shared.append(at)
    different_at = next((p for p,(x,y) in enumerate(zip(benelux0,denswe0)) if x != y), None)
    return {
        "schema": "oem-real-map-evidence-iter010-v1",
        "source_hashes": {
            name: {"bytes": len(buf), "sha256": sha256(buf).hexdigest()}
            for name,buf in (("INIT.SDL",init),("BENELUX0.SDL",benelux0),
                             ("DENSWE0.SDL",denswe0),("BENELUX1.SDL",benelux1))},
        "BENELUX1_header_at_0x2000": header_at(benelux1,0x2000),
        "BENELUX1_filtered_candidates": cartographic_candidate_scan(benelux1),
        "BENELUX0_region_index": region0_profile(benelux0),
        "DENSWE0_region_index": region0_profile(denswe0),
        "SDL0_shared_nonuniform_4k_blocks": shared,
        "SDL0_first_difference": different_at,
        "INIT_word_pool_to_BENELUX1_literal_signature": linked_seven_word_markers(init,benelux1),
        "qualifications": [
            "DENSWE0 resembles a full regional SDL0; it cannot be classified as a simple density counter merely from its name.",
            "Aligned PclHdr_t-like signatures can be incidental; do not equate candidate count with valid parcel count.",
            "A repeated 28-byte signature is not an authenticated pointer or navigable index.",
            "OEM disc ISO9660/UDF sector ordering and on-device acceptance require original ISO evidence.",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    for arg in ("init","benelux0","denswe0","benelux1","output"):
        ap.add_argument("--"+arg, required=True, type=Path)
    args = ap.parse_args()
    try:
        result = analyze(checked_file(args.init), checked_file(args.benelux0),
                         checked_file(args.denswe0), checked_file(args.benelux1))
    except (OSError,EvidenceError) as error:
        ap.exit(2, "ERROR: "+str(error)+"\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Filtered SDL1 header candidates:",result["BENELUX1_filtered_candidates"]["candidate_count_not_proven_parcels"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

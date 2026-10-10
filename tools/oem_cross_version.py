#!/usr/bin/env python3
"""Read-only cross-release OEM SDL evidence. No boot/format compliance claim."""
from __future__ import annotations

import argparse
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
import re
import struct

NAMES = ("INIT.SDL", "MTOC.SDL", "REGION.SDL", "REGIONS.SDL",
         "CARTOTOP.SDL", "BENELUX0.SDL", "FRANCE0.SDL")
PCL = struct.Struct(">IHBBBBHHHHH")
CATALOG_POS = 0x12000
CATALOG_LEN = 0x94C
UNIT = 256
SECTION = 0x4000
HEADER_COMBINATIONS = {(19, 0, 0), (255, 1, 0), (1, 1, 0xB8)}


class EvidenceError(ValueError):
    pass


def load(directory: Path) -> dict[str, bytes]:
    if not directory.is_dir():
        raise EvidenceError(f"Not a directory: {directory}")
    output = {}
    for name in NAMES:
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise EvidenceError(f"Missing regular file: {path}")
        output[name] = path.read_bytes()
    return output


def find_headers(data: bytes) -> list[dict]:
    """Candidate only: a matching PclHdr_t shape is not a validated parcel."""
    hits = []
    for offset in range(UNIT, len(data) - PCL.size + 1, UNIT):
        pid, desc, typ, reg, swap, hi, lo, comp, compoff, uncomp, ext = PCL.unpack_from(data, offset)
        if (pid >> 30 != 0 or (pid & 0xFFFFFF) * UNIT != offset or
                (typ, reg, desc) not in HEADER_COMBINATIONS or swap or
                (hi, lo, comp, compoff, ext) != (0, 0, 0, 0, 0)):
            continue
        hits.append({"offset": offset, "pid_be": f"0x{pid:08X}",
                     "type": typ, "region": reg, "descriptor": desc,
                     "size_index": (pid >> 24) & 63, "uncompressed_field": uncomp})
    for index, hit in enumerate(hits):
        end = hits[index + 1]["offset"] if index + 1 < len(hits) else len(data)
        hit["next_candidate_or_eof"] = end
        hit["gap_units_hypothesis"] = (end - hit["offset"]) // UNIT
        hit["ends_at_eof"] = (index + 1 == len(hits))
    return hits


def copied_regions(init: bytes, benelux: bytes) -> list[dict]:
    """Measure exact copied prefixes from aligned OEM regional candidate starts."""
    results = []
    first_block = SECTION // 4
    lookup = {}
    for offset in range(0x2000, len(benelux) - SECTION + 1, SECTION):
        block = benelux[offset:offset + first_block]
        if len(set(block)) > 1:
            lookup.setdefault(sha256(block).digest(), []).append(offset)
    for dest in range(0x2000, len(init) - SECTION + 1, SECTION):
        first = init[dest:dest + first_block]
        for source in lookup.get(sha256(first).digest(), []):
            if first != benelux[source:source + first_block]:
                continue
            left = init[dest:dest + SECTION]
            right = benelux[source:source + SECTION]
            prefix = next((i for i, (a, b) in enumerate(zip(left, right))
                           if a != b), min(len(left), len(right)))
            rawpid = int.from_bytes(first[:4], "big")
            results.append({
                "init_offset": dest, "benelux_offset": source,
                "exact_prefix_bytes": prefix,
                "matching_complete_4k_blocks": prefix // first_block,
                "full_16k_identical": prefix == SECTION,
                "stored_address_points_to_benelux": (rawpid & 0xFFFFFF) * UNIT == source})
    return sorted(results, key=lambda item: (item["init_offset"], item["benelux_offset"]))


def profile(files: dict[str, bytes]) -> dict:
    missing = sorted(set(NAMES) - set(files))
    if missing:
        raise EvidenceError(f"Missing samples: {missing}")
    init, mtoc = files["INIT.SDL"], files["MTOC.SDL"]
    if len(init) < CATALOG_POS + CATALOG_LEN or len(mtoc) < CATALOG_LEN:
        raise EvidenceError("INIT/MTOC too short for known catalogue slice")
    info = {name: {"bytes": len(content), "sha256": sha256(content).hexdigest()}
            for name, content in sorted(files.items())}
    hdrs = {name: find_headers(files[name]) for name in
            ("BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL")}
    region_layout = {}
    for name in ("BENELUX0.SDL", "FRANCE0.SDL"):
        size = len(files[name])
        expected = list(range(0x2000, size, SECTION))
        region_layout[name] = {
            "prefix_bytes": 0x2000, "section_bytes": SECTION,
            "count": len(expected),
            "exact_partition": size >= 0x2000 and (size - 0x2000) % SECTION == 0,
            "candidate_headers_at_every_section": [h["offset"] for h in hdrs[name]] == expected,
        }
    gaps = {}
    for headers in hdrs.values():
        for header in headers:
            key = str(header["size_index"])
            gaps.setdefault(key, set()).add(header["gap_units_hypothesis"])
    return {
        "files": info,
        "region_equals_regions": files["REGION.SDL"] == files["REGIONS.SDL"],
        "init_first_be32_is_file_size": int.from_bytes(init[:4], "big") == len(init),
        "init_catalog_offset_field_be32": int.from_bytes(init[8:12], "big"),
        "init_catalog_length_field_be32": int.from_bytes(init[12:16], "big"),
        "init_mtoc_catalog_slice_identical": (
            init[CATALOG_POS:CATALOG_POS + CATALOG_LEN] == mtoc[:CATALOG_LEN]),
        "headers": hdrs,
        "region_layout": region_layout,
        "gap_units_by_size_index_unverified": {k: sorted(v) for k, v in sorted(gaps.items(), key=lambda x: int(x[0]))},
        "init_benelux_aligned_prefix_matches": copied_regions(init, files["BENELUX0.SDL"]),
    }


def compare(left: dict[str, bytes], right: dict[str, bytes]) -> dict:
    data = {}
    for name in NAMES:
        a, b = left[name], right[name]
        changes = (i for i, (x, y) in enumerate(zip(a, b)) if x != y)
        first = next(changes, None)
        data[name] = {
            "same_bytes": a == b,
            "left_size": len(a), "right_size": len(b),
            "size_delta": len(b) - len(a),
            "first_difference_within_overlap": first,
            "byte_differences_within_overlap": (
                sum(x != y for x, y in zip(a, b))),
        }
        if name in ("REGION.SDL", "REGIONS.SDL"):
            differences = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
            if len(differences) <= 64:
                data[name]["all_changed_byte_offsets"] = differences
                data[name]["changed_byte_values"] = [
                    {"offset": i, "left": a[i], "right": b[i]}
                    for i in differences]
    return {"per_file": data, "mtoc_byte_identical": data["MTOC.SDL"]["same_bytes"]}


def analyze(releases: dict[str, dict[str, bytes]]) -> dict:
    if len(releases) < 2:
        raise EvidenceError("Supply at least two OEM releases")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name) for name in releases):
        raise EvidenceError("Invalid release label")
    names = sorted(releases)
    profiles = {name: profile(releases[name]) for name in names}
    comparisons = [{"left": a, "right": b, **compare(releases[a], releases[b])}
                   for a, b in combinations(names, 2)]
    common_init_words = []
    for offset in range(0, 0x50, 4):
        observed = {int.from_bytes(releases[name]["INIT.SDL"][offset:offset + 4], "big")
                    for name in names}
        if len(observed) == 1:
            common_init_words.append({
                "offset": offset, "be32": next(iter(observed)),
                "interpretation": "unassigned_binary_field"})
    invariants = {
        "sample_release_count": len(names),
        "all_mtoc_byte_identical": (
            len({profiles[name]["files"]["MTOC.SDL"]["sha256"] for name in names}) == 1),
        "all_region_equals_regions": all(
            profiles[name]["region_equals_regions"] for name in names),
        "all_init_catalog_matches_own_mtoc": all(
            profiles[name]["init_mtoc_catalog_slice_identical"] for name in names),
        "common_init_be32_first_0x50": common_init_words,
    }
    return {
        "schema": "oem-cross-version-iter007-v1",
        "evidence_type": "original_bytes_not_generated_0_sdl",
        "releases": profiles, "comparisons": comparisons,
        "cross_release_invariants": invariants,
        "limitations": [
            "Index-to-next-candidate gaps are not an authenticated ucaParcelSizes table",
            "Header candidates do not prove full parcel structure",
            "Cross-release invariants apply only to the supplied sample, not all OEM versions",
            "Exact relocated INIT sections do not establish OEM boot semantics",
        ],
    }


def markdown(report: dict) -> str:
    names = sorted(report["releases"])
    lines = ["# Iter006 — Cross-release OEM byte evidence", "",
             "Observations only. No generator or boot-loader modifications.", "",
             "| File | " + " | ".join(names) + " |",
             "|---|" + "---:|" * len(names)]
    for filename in NAMES:
        sizes = [str(report["releases"][n]["files"][filename]["bytes"]) for n in names]
        lines.append("| " + filename + " | " + " | ".join(sizes) + " |")
    lines += ["", "## Candidate PclHdr_t counts", "",
              "| File | " + " | ".join(names) + " |",
              "|---|" + "---:|" * len(names)]
    for filename in ("BENELUX0.SDL", "FRANCE0.SDL", "CARTOTOP.SDL"):
        vals = [str(len(report["releases"][n]["headers"][filename])) for n in names]
        lines.append("| " + filename + " | " + " | ".join(vals) + " |")
    if "cross_release_invariants" in report:
        inv = report["cross_release_invariants"]
        lines += ["", "## Cross-release observations", "",
                  "- MTOC identical across all samples: " + str(inv["all_mtoc_byte_identical"]),
                  "- REGION matches REGIONS within each sample: " + str(inv["all_region_equals_regions"]),
                  "- INIT catalog slice matches MTOC within each sample: " +
                  str(inv["all_init_catalog_matches_own_mtoc"]),
                  "- Constant BE32 words in INIT first 0x50: " +
                  ", ".join(f"0x{w['offset']:X}=0x{w['be32']:X}"
                            for w in inv["common_init_be32_first_0x50"])]
    for rel in names:
        item = report["releases"][rel]
        lines += ["", "## " + rel, "",
                  "- REGION identical to REGIONS: " + str(item["region_equals_regions"]),
                  "- INIT header size field matches size: " + str(item["init_first_be32_is_file_size"]),
                  "- INIT/MTOC 0x94C-byte catalog equal: " + str(item["init_mtoc_catalog_slice_identical"]),
                  "- INIT catalog fields: offset " + hex(item["init_catalog_offset_field_be32"]) +
                  ", length " + hex(item["init_catalog_length_field_be32"]), "",
                  "### Gap hypotheses, units of 256 B", ""]
        for index, gaps in item["gap_units_by_size_index_unverified"].items():
            lines.append("- size index " + index + ": " + ", ".join(map(str, gaps)))
        lines += ["", "### Identical relocated 16-KiB sections", ""]
        for item2 in item["init_benelux_aligned_prefix_matches"]:
            lines.append(f"- INIT 0x{item2['init_offset']:X} ↔ BENELUX0 "
                         f"0x{item2['benelux_offset']:X} "
                         f"(identical prefix: {item2['exact_prefix_bytes']} bytes; "
                         f"full 16 KiB: {item2['full_16k_identical']}; "
                         f"embedded source address matches: {item2['stored_address_points_to_benelux']})")
    for comp in report["comparisons"]:
        lines += ["", "## Pair " + comp["left"] + " / " + comp["right"], "",
                  "- MTOC exactly identical: " + str(comp["mtoc_byte_identical"])]
    lines += ["", "## Limitations", ""] + ["- " + s for s in report["limitations"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", action="append", required=True, metavar="LABEL=DIR")
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--md", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        releases = {}
        for raw in args.release:
            if "=" not in raw:
                raise EvidenceError("Release argument must be LABEL=DIR")
            label, directory = raw.split("=", 1)
            if label in releases:
                raise EvidenceError(f"Duplicate label: {label}")
            releases[label] = load(Path(directory))
        evidence = analyze(releases)
    except (EvidenceError, OSError) as exc:
        parser.exit(2, "ERROR: " + str(exc) + "\n")
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    args.md.write_text(markdown(evidence), encoding="utf-8")
    print(f"Compared {len(evidence['releases'])} releases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

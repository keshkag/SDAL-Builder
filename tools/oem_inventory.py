#!/usr/bin/env python3
"""Read-only, format-agnostic OEM SDL corpus inventory.

This command deliberately does not interpret the bytes of a file as SDAL
structures. Its output records observations, not OEM format compliance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import BinaryIO

BLOCK_SIZE = 4096
CHUNK_SIZE = 1024 * 1024
# Evidence only: strings ending in .SDL; not decoded OEM reference entries.
SDL_STRING = re.compile(rb"(?<![A-Za-z0-9_])([A-Za-z0-9_-]{1,24}\.SDL)(?![A-Za-z0-9_])", re.IGNORECASE)
MAX_NAME_BYTES = 28


def _scan_stream(stream: BinaryIO, *, size: int, block_size: int) -> dict:
    digest = hashlib.sha256()
    nonzero = 0
    blocks: list[dict] = []
    candidates: list[dict] = []
    tail = b""
    block_tail = b""
    total = 0
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            break
        digest.update(chunk)
        nonzero += sum(b != 0 for b in chunk)
        for_match = tail + chunk
        origin = total - len(tail)
        for match in SDL_STRING.finditer(for_match):
            start = origin + match.start(1)
            if start + len(match.group(1)) <= total:
                continue
            candidates.append({"offset": start, "name": match.group(1).decode("ascii").upper()})
        tail = for_match[-MAX_NAME_BYTES:]
        for_blocks = block_tail + chunk
        block_origin = total - len(block_tail)
        full = len(for_blocks) // block_size
        for i in range(full):
            part = for_blocks[i * block_size:(i + 1) * block_size]
            blocks.append({"offset": block_origin + i * block_size, "bytes": block_size,
                           "nonzero_bytes": sum(b != 0 for b in part)})
        block_tail = for_blocks[full * block_size:]
        total += len(chunk)
    if block_tail:
        blocks.append({"offset": total - len(block_tail), "bytes": len(block_tail),
                       "nonzero_bytes": sum(b != 0 for b in block_tail)})
    if total != size:
        raise ValueError(f"File size changed during scan: initially {size} bytes, read {total}")
    return {"size_bytes": size, "sha256": digest.hexdigest(), "nonzero_bytes": nonzero,
            "zero_bytes": size - nonzero, "blocks": blocks,
            "ascii_sdl_candidates": candidates}


def inventory(directory: Path, *, block_size: int = BLOCK_SIZE) -> dict:
    """Inventory recursively discovered .SDL files without following symlinks."""
    root = directory.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Input must be a directory containing extracted OEM files: {root}")
    if block_size <= 0:
        raise ValueError("block_size must be positive")
    paths = sorted((p for p in root.rglob("*") if not p.is_symlink() and
                    p.is_file() and p.suffix.casefold() == ".sdl"),
                   key=lambda p: p.relative_to(root).as_posix().upper())
    if not paths:
        raise ValueError(f"No SDL files found under {root}")
    names = {p.name.upper() for p in paths}
    results = []
    for path in paths:
        stat = path.stat()
        if os.path.commonpath((str(root), str(path.resolve()))) != str(root):
            raise ValueError(f"Path outside corpus: {path}")
        with path.open("rb") as inp:
            result = _scan_stream(inp, size=stat.st_size, block_size=block_size)
        result["path"] = path.relative_to(root).as_posix()
        for ref in result["ascii_sdl_candidates"]:
            ref["present_in_corpus_by_basename"] = ref["name"] in names
        results.append(result)
    return {"schema_version": 1,
            "method": "byte_examination_only_no_sdal_structures_assumed",
            "block_size": block_size,
            "files": results,
            "total_files": len(results),
            "total_bytes": sum(r["size_bytes"] for r in results)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Extracted original OEM SDL directory")
    parser.add_argument("--output", "-o", type=Path, help="Write deterministic JSON report to this path")
    parser.add_argument("--block-size", type=int, default=BLOCK_SIZE)
    args = parser.parse_args(argv)
    try:
        report = inventory(args.directory, block_size=args.block_size)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Scanned {report['total_files']} SDL files ({report['total_bytes']} bytes); report: {args.output}")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

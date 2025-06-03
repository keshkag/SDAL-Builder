#!/usr/bin/env python
"""Run SDAL builder without installing the package (adds src/ to sys.path)."""

import sys
import pathlib

root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from sdal_builder.main import cli

if __name__ == "__main__":
    try:
        cli()
    except KeyboardInterrupt:
        # Exit silently on Ctrl+C
        sys.exit(0)

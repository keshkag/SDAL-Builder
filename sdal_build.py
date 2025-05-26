
#!/usr/bin/env python
"""Run SDAL builder without installing the package (adds src/ to sys.path)."""
import sys, pathlib
root = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
from sdal_builder.main import cli
if __name__ == "__main__":
    cli()

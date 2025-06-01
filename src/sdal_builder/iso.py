import pycdlib
from datetime import datetime
import pathlib

def write_iso(files: list[pathlib.Path], out_path: pathlib.Path):
    """
    Build an ISO9660 Level 1 image with:
      - VOLID auto‑stamped as YYMMDD_HH (e.g. '250525_11')
      - each file in `files` placed in the root with uppercase filename
    """
    iso = pycdlib.PyCdlib()
    volid = datetime.now().strftime("%y%m%d_%H")
    iso.new(vol_ident=volid, interchange_level=3)

    for fpath in files:
        name = fpath.name.upper()
        iso.add_file(str(fpath), f"/{name};1")

    iso.write(str(out_path))
    iso.close()

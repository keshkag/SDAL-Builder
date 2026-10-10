#!/usr/bin/env bash
set -euo pipefail

# Usage: ./build.sh [--clean] <region1> [region2 ...] [<out_iso>] [optional_flags...]
# Examples:
#   ./build.sh europe/cyprus
#   ./build.sh europe/cyprus europe/spain mymaps.iso
#   ./build.sh europe/cyprus --format-mode SDAL --supp-lang ENG
#   ./build.sh --clean

# Change to the script’s directory (project root)
cd "$(dirname "$0")"

# Define the root of the project for paths
ROOT=$(pwd)

if [[ "${1-}" == "--clean" ]]; then
  echo "Performing cleanup..."
  # Remove Python bytecode caches
  rm -rf src/sdal_builder/__pycache__
  rm -rf src/sdal_builder/__init__.py
  rm -rf src/sdal_builder.egg-info

  # Remove virtual environment
  rm -rf .venv

  # Remove build artifacts
  rm -rf build
  rm -rf work*
  rm -rf *.iso

  echo "Cleanup complete."
  exit 0
fi

# Hybrid ISO9660/Joliet/UDF mastering is a required part of an OEM build.
# Check before expensive OSM download / geospatial processing.
if ! command -v genisoimage >/dev/null 2>&1 && ! command -v mkisofs >/dev/null 2>&1; then
  echo "ERROR: Required hybrid ISO mastering tool not installed." >&2
  echo "  macOS/Homebrew: brew install cdrtools" >&2
  echo "  Debian/Ubuntu: sudo apt-get install genisoimage" >&2
  echo "Pure-ISO9660 fallback is not permitted for OEM output." >&2
  exit 1
fi

# ----------------------------------------------------------------
# Argument parser to reliably separate positional regions and flags + values.
# The ISO output name is always the last positional argument, if present.
# ----------------------------------------------------------------

# Arguments:
# REGIONS: The list of region slugs (positional arguments for the Python script)
# OPTIONS: The list of flags and their values (e.g., --format-mode OEM, --supp-lang ENG)
# OUT: The final ISO filename
REGIONS=()
OPTIONS=()
ISO_ARG=""

# 1. Identify and separate the optional final ISO filename
if [[ "${@: -1}" == *.iso ]]; then
  ISO_ARG="${@: -1}"
  # Process all arguments except the last one (the ISO file)
  args_to_process=("${@:1:$(($#-1))}")
else
  # Process all arguments
  args_to_process=("$@")
fi

# 2. Iterate through the remaining arguments to separate regions from options.
i=0
while [[ $i -lt ${#args_to_process[@]} ]]; do
    arg="${args_to_process[i]}"
    
    if [[ "$arg" == --* ]] || [[ "$arg" == -* ]]; then
        # This is a flag. Add the flag itself.
        OPTIONS+=("$arg")
        i=$((i+1))
        
        # Check if the next argument is the value for this flag (i.e., not another flag)
        if [[ $i -lt ${#args_to_process[@]} ]]; then
            next_arg="${args_to_process[i]}"
            # Value check: If the next argument does NOT start with a hyphen, it's the value.
            if ! [[ "$next_arg" == --* ]] && ! [[ "$next_arg" == -* ]]; then
                OPTIONS+=("$next_arg")
                i=$((i+1))
            fi
        fi
    else
        # This is a positional argument (a region slug)
        REGIONS+=("$arg")
        i=$((i+1))
    fi
done

if [[ ${#REGIONS[@]} -lt 1 ]]; then
  echo "Usage: $0 [--clean] <region1> [region2 ...] [<out_iso>] [optional_flags...]"
  echo "Note: Use --format-mode {OEM,SDAL} to switch file structure. Default is OEM."
  exit 1
fi

# 3. Determine the output ISO filename
if [[ -n "$ISO_ARG" ]]; then
  OUT="$ISO_ARG"
else
  # Derive OUT from the first region slug
  SLUG="${REGIONS[0]##*/}"
  OUT="${SLUG}.iso"
fi

# Define the working directory
WORK_DIR="${ROOT}/build"


# 1) Create & activate venv
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
echo "Venv activated. Python: $(which python)"

# 2) Install/update dependencies
# Note: Assuming 'pip install -e .' is sufficient and requirements.txt is not strictly needed.
.venv/bin/python3 -m pip install -e .

# 3) Execute the builder (passing all flags and arguments safely)
echo "Building regions: ${REGIONS[*]} into $OUT (work_dir: $WORK_DIR)"

# Execute the Python builder, passing positional regions first, then all required and optional flags.
# We use the safe syntax ${OPTIONS[@]+"${OPTIONS[@]}"} for older bash compatibility
python3 "$ROOT/sdal_build.py" "${REGIONS[@]}" --out "$OUT" --work "$WORK_DIR" ${OPTIONS[@]+"${OPTIONS[@]}"}

echo "Success! ISO image is available at $OUT"
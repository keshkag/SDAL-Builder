#!/usr/bin/env bash
set -euo pipefail

# Usage: ./build.sh <region1> [region2 ...] [<out_iso>]
# Examples:
#   ./build.sh europe/cyprus
#   ./build.sh europe/cyprus europe/spain
#   ./build.sh europe/cyprus europe/spain mymaps.iso

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <region1> [region2 ...] [<out_iso>]"
  exit 1
fi

# Determine if last arg is an ISO filename (ends with .iso) or a region slug
if [[ "${@: -1}" == *.iso ]]; then
  OUT="${@: -1}"
  REGIONS=("${@:1:$(($#-1))}")
else
  REGIONS=("$@")
  # Derive OUT from the first region slug
  SLUG="${REGIONS[0]##*/}"
  OUT="${SLUG}.iso"
fi

# 1) Create & activate venv
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate

# 2) Install deps
pip install --upgrade pip
pip install -r requirements.txt

# 3) Build the ISO
python sdal_build.py "${REGIONS[@]}" --out "$OUT"

echo
echo "✅ Built $OUT for regions: ${REGIONS[*]}"

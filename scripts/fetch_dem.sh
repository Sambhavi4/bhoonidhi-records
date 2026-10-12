#!/usr/bin/env bash
# fetch_dem.sh - build data/dem.tif, the raster the two raster processes read.
#
# WHY THIS EXISTS
#   data/dem.tif is 41 MB, so it is gitignored rather than committed. Without
#   it, zonal-statistics and scene-raster-profile cannot run and 18 of the 100
#   compliance tests fail. This script rebuilds it from a public source so a
#   fresh clone is self-sufficient.
#
# WHAT IT FETCHES, AND WHAT IT STANDS IN FOR
#   Copernicus DEM GLO-30 (ESA, via the AWS Open Data registry) - public and
#   unauthenticated. It is a SUBSTITUTE for Bhoonidhi CartoDEM, which requires
#   an authenticated NRSC account. The substitution is recorded in
#   data/PROVENANCE.md and is irrelevant to the gap being demonstrated: the
#   raster processes show raster-vector overlay over an area of interest, and
#   that is the same operation whichever DEM is underneath.
#
#   To serve real CartoDEM instead, drop it in as data/dem.tif, or point
#   RASTER_FILE at it. Nothing else changes.
#
# Usage: ./scripts/fetch_dem.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$ROOT/data/raw"
OUT="$ROOT/data/dem.tif"
BASE="https://copernicus-dem-30m.s3.amazonaws.com"

# AOI 75.1,13.0 -> 76.0,14.1 (Chikkamagaluru / Shivamogga, Western Ghats),
# the window the footprint store also covers. Four 1x1 degree tiles span it.
AOI_W=75.1 AOI_S=13.0 AOI_E=76.0 AOI_N=14.1
TILES=(N13_00_E075_00 N14_00_E075_00 N13_00_E076_00 N14_00_E076_00)

ok(){ printf '   \033[32mok\033[0m    %s\n' "$*"; }
bad(){ printf '   \033[31mfail\033[0m  %s\n' "$*"; }
say(){ printf '\n\033[1m-- %s\033[0m\n' "$*"; }

command -v gdalbuildvrt >/dev/null && command -v gdal_translate >/dev/null \
  || { bad "GDAL not found - sudo apt install gdal-bin"; exit 1; }

if [ -s "$OUT" ]; then
  ok "data/dem.tif already present ($(du -h "$OUT" | cut -f1)) - nothing to do"
  echo "      delete it first if you want to rebuild"
  exit 0
fi

say "fetching ${#TILES[@]} Copernicus DEM GLO-30 tiles"
mkdir -p "$RAW"
for t in "${TILES[@]}"; do
  f="$RAW/Copernicus_DSM_COG_10_${t}_DEM.tif"
  if [ -s "$f" ]; then ok "$t cached"; continue; fi
  url="$BASE/Copernicus_DSM_COG_10_${t}_DEM/Copernicus_DSM_COG_10_${t}_DEM.tif"
  echo "   fetching $t"
  curl -fL --progress-bar -o "$f.part" "$url" \
    || { bad "download failed: $url"; rm -f "$f.part"; exit 1; }
  mv "$f.part" "$f"
  ok "$t  $(du -h "$f" | cut -f1)"
done

say "mosaic -> clip to the AOI -> Cloud-Optimized GeoTIFF"
VRT="$RAW/dem_mosaic.vrt"
gdalbuildvrt -q -overwrite "$VRT" "$RAW"/Copernicus_DSM_COG_10_*_DEM.tif
gdal_translate -q -of COG \
  -projwin "$AOI_W" "$AOI_N" "$AOI_E" "$AOI_S" \
  -a_nodata -9999 \
  -co COMPRESS=DEFLATE -co BLOCKSIZE=512 -co OVERVIEWS=AUTO \
  "$VRT" "$OUT"
ok "data/dem.tif  $(du -h "$OUT" | cut -f1)"

cat > "$ROOT/data/PROVENANCE.md" <<EOF
# Provenance of data/dem.tif

**This is NOT Bhoonidhi CartoDEM.** It is a documented substitute.

| | |
|---|---|
| Source | Copernicus DEM GLO-30 (ESA), via the AWS Open Data registry |
| Access | public, unauthenticated |
| Built by | \`scripts/fetch_dem.sh\` |
| Built on | $(date -u +%Y-%m-%dT%H:%M:%SZ) |
| Extent | $AOI_W, $AOI_S -> $AOI_E, $AOI_N (EPSG:4326) |
| Resolution | 1 arc-second (~30 m) |
| Format | Cloud-Optimized GeoTIFF, 512 px blocks, DEFLATE, with overviews |

## Why a substitute

Bhoonidhi's CartoDEM requires an authenticated NRSC account. So that this
service is demonstrable by anyone who clones the repository with no
credentials, an open DEM stands in.

This substitution does not affect the gap being demonstrated. The raster
processes (\`zonal-statistics\`, \`scene-raster-profile\`) demonstrate
raster-vector overlay over an area of interest, and that is the same operation
whichever elevation model is underneath.

## Serving real CartoDEM instead

Place the CartoDEM product at \`data/dem.tif\`, or point \`RASTER_FILE\` at it.
Nothing else changes: same endpoints, same processes, same tests.
EOF
ok "data/PROVENANCE.md written"

say "done"
echo "   the raster processes can now run:"
echo "     ./scripts/serve_local.sh start && ./scripts/run_tests.sh"

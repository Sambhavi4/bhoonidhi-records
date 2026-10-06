#!/usr/bin/env bash
# demo.sh - the live demo: the catalogue, then the spatial operations.
set -uo pipefail
B="${B:-http://localhost:5003}"
AOI='[75.3,13.2,75.8,13.9]'
BIG='[75.1,13.0,76.0,14.1]'

h(){ printf '\n\033[1m%s\033[0m\n' "$*"; }
d(){ printf '\033[2m  %s\033[0m\n' "$*"; }
py(){ python3 -c "
import json,sys
try: o=json.load(sys.stdin)
except Exception as e: print('   (no JSON:',e,')'); sys.exit(0)
$1"; }

cat <<HDR
===========================================================================
 Bhoonidhi Records + spatial analysis - live demo
 service $B
===========================================================================
HDR

h "1. The gap: Bhoonidhi's catalogue needs a login"
d "GET https://bhoonidhi-api.nrsc.gov.in/data/collections   -> 401 UNAUTHORIZED"
d "(see docs/evidence/ ; ./scripts/probe_gap.sh re-proves it)"

h "2. OGC API - Records: open, searchable discovery"
d "GET $B/collections/bhoonidhi/items?limit=1"
curl -s --max-time 60 "$B/collections/bhoonidhi/items?limit=1&f=json" \
  | py "print('   records in catalogue:', o['numberMatched'])"
for q in scatterometer NDVI SAR elevation; do
  printf '   q=%-14s -> ' "$q"
  curl -s --max-time 60 "$B/collections/bhoonidhi/items?q=$q&limit=1&f=json" \
    | py "print(o['numberMatched'],'records')"
done
for f in "platform_id=EOS-06" "domain=radar" "instrument=AIS"; do
  printf '   %-22s -> ' "$f"
  curl -s --max-time 60 "$B/collections/bhoonidhi/items?$f&limit=1&f=json" \
    | py "print(o['numberMatched'],'records')"
done

h "3. Spatial operation: how much of my AOI is actually covered?"
d "POST $B/processes/aoi-coverage/execution"
curl -s --max-time 300 -X POST "$B/processes/aoi-coverage/execution" \
  -H 'Content-Type: application/json' \
  -d "{\"inputs\":{\"aoi\":$AOI,\"collection\":\"sentinel-2-l2a\"}}" \
  | py "
print(f\"   AOI            {o['aoi_area_km2']} km2\")
print(f\"   covered        {o['covered_area_km2']} km2  = {o['coverage_percent']}%\")
print(f\"   gaps           {o['gap_area_km2']} km2\")
print(f\"   scenes touching AOI: {o['scene_count']}\")
print(f\"   gap polygons returned: {o['gaps'] is not None}\")"

h "4. Spatial operation: which few scenes do I actually need? (set cover)"
d "POST $B/processes/minimal-scene-set/execution"
curl -s --max-time 300 -X POST "$B/processes/minimal-scene-set/execution" \
  -H 'Content-Type: application/json' \
  -d "{\"inputs\":{\"aoi\":$AOI,\"collection\":\"sentinel-2-l2a\",\"target_fraction\":0.99}}" \
  | py "
print(f\"   candidates {o['candidates_considered']}  ->  SELECTED {o['scenes_selected']}  (avoided {o['scenes_avoided']})\")
print(f\"   achieved {o['achieved_percent']}% of the AOI\")
for s in o['selection'][:6]:
    print(f\"     {s['order']}. +{s['new_area_km2']:>9} km2  ->  {s['cumulative_coverage_fraction']*100:5.1f}%  {s['item_id'][:46]}\")"

h "5. Spatial operation: where do optical and radar co-cover?"
d "POST $B/processes/multi-sensor-overlap/execution"
curl -s --max-time 300 -X POST "$B/processes/multi-sensor-overlap/execution" \
  -H 'Content-Type: application/json' \
  -d "{\"inputs\":{\"aoi\":$BIG,\"collection_a\":\"sentinel-2-l2a\",\"collection_b\":\"sentinel-1-grd\"}}" \
  | py "
print(f\"   {o['collection_a']}: {o.get('scenes_a')} scenes, {o.get('coverage_a_km2')} km2\")
print(f\"   {o['collection_b']}: {o.get('scenes_b')} scenes, {o.get('coverage_b_km2')} km2\")
print(f\"   co-covered: {o.get('overlap_area_km2')} km2 = {o.get('overlap_fraction_of_aoi',0)*100:.1f}% of AOI\")"

h "6. Spatial operation: how uneven is revisit? (density grid)"
d "POST $B/processes/revisit-density/execution"
curl -s --max-time 300 -X POST "$B/processes/revisit-density/execution" \
  -H 'Content-Type: application/json' \
  -d "{\"inputs\":{\"aoi\":$AOI,\"collection\":\"sentinel-2-l2a\",\"cell_size_km\":10}}" \
  -o /tmp/density.geojson
py "
s=o['summary']
print(f\"   grid {s['grid']} @ {s['cell_size_km']} km  ->  {s['cells_in_aoi']} cells\")
print(f\"   acquisitions per cell: min {s['min_per_cell']}  mean {s['mean_per_cell']}  max {s['max_per_cell']}\")
print(f\"   never observed: {s['cells_never_observed']} cells\")
print('   saved -> /tmp/density.geojson  (drop into geojson.io to see the heatmap)')" < /tmp/density.geojson

h "7. Asynchronous execution"
loc=$(curl -s -i --max-time 60 -X POST "$B/processes/aoi-coverage/execution" \
  -H 'Content-Type: application/json' -H 'Prefer: respond-async' \
  -d "{\"inputs\":{\"aoi\":$AOI}}" | grep -i '^Location:' | tr -d '\r' | awk '{print $2}')
if [ -n "${loc:-}" ]; then
  printf '   201 Created -> %s\n' "$loc"
  for i in $(seq 1 30); do
    st=$(curl -s --max-time 20 "$loc?f=json" | py "print(o.get('status',''))")
    [ "$st" = "successful" ] && { printf '   job successful after %ss\n' "$i"; break; }
    sleep 1
  done
fi

cat <<'FTR'

===========================================================================
 WHAT TO NOTICE
   Bhoonidhi's search returns a LIST of scenes touching your polygon.
   None of sections 3-6 is answerable from that list without doing the
   spatial algebra yourself. Section 4 is the sharpest: 30 scenes match
   the AOI, and 2 of them cover it.
===========================================================================
FTR

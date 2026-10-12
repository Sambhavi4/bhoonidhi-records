#!/usr/bin/env python3
"""measure_redundancy.py - put a number on the cost of the missing tier.

The gap this repository fills is easy to state and easy to under-sell:
Bhoonidhi's `/data/search` answers *which scenes intersect my area of
interest* and nothing further. That sounds like a missing convenience. It is
not. Because the catalogue will not compute with the footprint geometry it
already stores, a user has no way to learn which of the returned scenes they
actually need - so the rational thing to do, and what people in fact do, is
order every scene the search returned.

This script measures how much of that is wasted, by asking this project's own
`minimal-scene-set` process the question the catalogue cannot answer:

    candidates_considered   what Bhoonidhi's search would hand you
    scenes_selected         what actually covers the same AOI
    scenes_avoided          what you would have downloaded for nothing

and converting scene counts into bytes with published nominal product sizes.

HONESTY ABOUT THE NUMBERS
  * The scene counts are MEASURED, live, against the running service over real
    STAC footprints. They are the part that matters and they are not modelled.
  * The byte figures are PUBLISHED NOMINAL product sizes per scene (see
    PRODUCT_VOLUMES below), multiplied by those counts. They are not measured
    downloads - this script never downloads imagery. A real order varies with
    processing level, tiling and compression.
  * The ResourceSat rows are a PROJECTION onto Bhoonidhi's own holdings: the
    footprint geometry is Sentinel-2/Sentinel-1 (see data/footprints.geojson
    metadata), so the per-scene volume is swapped for the NRSC product's while
    the geometry stays what was actually measured. Labelled as such in output.

Usage:
    ./scripts/measure_redundancy.py                 # default AOI ladder
    ./scripts/measure_redundancy.py --json-only
    BASE=http://host:5003 ./scripts/measure_redundancy.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    sys.exit("requests is not installed - run ./scripts/install.sh")

# RECORDS_BASE is what run_tests.sh and expose_public.sh use; BASE is kept
# as a convenience alias.
BASE = (os.environ.get("RECORDS_BASE") or os.environ.get("BASE")
        or "http://localhost:5003").rstrip("/")
ROOT = pathlib.Path(__file__).resolve().parent.parent
EVIDENCE = ROOT / "docs" / "evidence"

# Published nominal size of ONE delivered scene, in megabytes. These are the
# figures the data providers publish for a whole product as distributed, not
# measurements taken by this script.
#
#   sentinel-2-l2a  ESA L2A SAFE product, 110 x 110 km tile, all bands
#   sentinel-1-grd  Sentinel-1 IW GRD, dual polarisation
#   liss3           ResourceSat-2/2A LISS-III, 141 km swath, 4 bands  (Bhoonidhi)
#   liss4           ResourceSat-2/2A LISS-IV MX, 70 km swath         (Bhoonidhi)
PRODUCT_VOLUMES_MB = {
    "sentinel-2-l2a": 1024.0,
    "sentinel-1-grd": 950.0,
    "liss3": 250.0,
    "liss4": 1536.0,
}

# Which Bhoonidhi product each measured collection is projected onto, so the
# "what this would cost on Bhoonidhi" row is explicit rather than implied.
BHOONIDHI_ANALOGUE = {
    "sentinel-2-l2a": ("liss3", "ResourceSat-2 LISS-III (optical, 141 km swath)"),
    "sentinel-1-grd": ("liss3", "ResourceSat-2 LISS-III (optical, 141 km swath)"),
}

# An AOI ladder, from a taluk-sized window up to the full footprint extent.
# All of these sit inside the harvested footprint store (lon 74.1-77.1,
# lat 12.2-15.6) so every row is a real measurement rather than an empty set.
AOIS = [
    ("taluk",             [75.50, 13.50, 75.70, 13.70]),
    ("district",          [75.30, 13.20, 75.80, 13.90]),
    ("two districts",     [75.10, 13.00, 76.00, 14.10]),
    ("regional transect", [74.50, 12.50, 76.50, 15.00]),
]

COLLECTIONS = ["sentinel-2-l2a", "sentinel-1-grd"]


def run_process(pid: str, inputs: dict, timeout: int = 600) -> dict:
    r = requests.post(f"{BASE}/processes/{pid}/execution",
                      json={"inputs": inputs}, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"{pid} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def gb(mb: float) -> float:
    return mb / 1024.0


def store_depth() -> tuple[str, str]:
    """How deep the footprint store actually is, read from the store itself.

    Reported so the "this is a floor" caveat cites the real store rather than
    a hardcoded guess, and so it stays true if the store is re-harvested.
    """
    try:
        d = json.loads((ROOT / "data" / "footprints.geojson").read_text())
    except (OSError, ValueError):
        return "the harvested", "short window"
    n = len(d.get("features", []))
    win = (d.get("metadata") or {}).get("window") or []
    if len(win) == 2:
        try:
            a, b = (datetime.fromisoformat(w.replace("Z", "+00:00")) for w in win)
            months = max(1, round((b - a).days / 30.4))
            return str(n), f"{months}-month window"
        except ValueError:
            pass
    return str(n), "short window"


def measure() -> dict:
    rows = []
    for label, aoi in AOIS:
        for coll in COLLECTIONS:
            try:
                res = run_process("minimal-scene-set",
                                  {"aoi": aoi, "collection": coll})
            except RuntimeError as e:
                print(f"   skipped {label}/{coll}: {e}", file=sys.stderr)
                continue

            cand = res["candidates_considered"]
            sel = res["scenes_selected"]
            if cand == 0:
                continue

            per_mb = PRODUCT_VOLUMES_MB[coll]
            today_mb = cand * per_mb
            needed_mb = sel * per_mb

            an_key, an_name = BHOONIDHI_ANALOGUE[coll]
            an_mb = PRODUCT_VOLUMES_MB[an_key]

            rows.append({
                "aoi_label": label,
                "aoi_bbox": aoi,
                "aoi_area_km2": round(res["aoi_area_km2"], 1),
                "collection": coll,
                # --- measured, live ---
                "candidates_considered": cand,
                "scenes_selected": sel,
                "scenes_avoided": res["scenes_avoided"],
                "achieved_percent": res["achieved_percent"],
                "redundant_fraction": round(1 - sel / cand, 4),
                # --- modelled from published product sizes ---
                "per_scene_mb": per_mb,
                "download_today_gb": round(gb(today_mb), 2),
                "download_needed_gb": round(gb(needed_mb), 2),
                "wasted_gb": round(gb(today_mb - needed_mb), 2),
                # --- projected onto Bhoonidhi's own product volumes ---
                "bhoonidhi_analogue": an_name,
                "bhoonidhi_today_gb": round(gb(cand * an_mb), 2),
                "bhoonidhi_needed_gb": round(gb(sel * an_mb), 2),
                "bhoonidhi_wasted_gb": round(gb((cand - sel) * an_mb), 2),
            })

    tot_cand = sum(r["candidates_considered"] for r in rows)
    tot_sel = sum(r["scenes_selected"] for r in rows)
    scenes, window = store_depth()
    return {
        "measured_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "service": BASE,
        "store_scenes": scenes,
        "store_window": window,
        "caveat": (
            "scene counts are bounded by the harvested footprint store, so the "
            "measured redundancy is a lower bound: a deeper archive returns more "
            "intersecting scenes for the same AOI while the number needed to "
            "cover it stays roughly constant"
        ),
        "method": (
            "scene counts measured live via POST /processes/minimal-scene-set/"
            "execution over the footprint store; byte figures are published "
            "nominal per-scene product sizes multiplied by those counts, not "
            "measured downloads"
        ),
        "product_volumes_mb": PRODUCT_VOLUMES_MB,
        "rows": rows,
        "totals": {
            "aois_measured": len({r["aoi_label"] for r in rows}),
            "queries": len(rows),
            "candidates_considered": tot_cand,
            "scenes_selected": tot_sel,
            "scenes_avoided": tot_cand - tot_sel,
            "redundant_fraction": round(1 - tot_sel / tot_cand, 4) if tot_cand else 0,
            "download_today_gb": round(sum(r["download_today_gb"] for r in rows), 2),
            "download_needed_gb": round(sum(r["download_needed_gb"] for r in rows), 2),
            "wasted_gb": round(sum(r["wasted_gb"] for r in rows), 2),
            "bhoonidhi_wasted_gb": round(sum(r["bhoonidhi_wasted_gb"] for r in rows), 2),
        },
    }


def report(d: dict) -> None:
    t = d["totals"]
    w = 78
    print("=" * w)
    print(" The cost of the missing computation tier, measured")
    print(f" run (UTC): {d['measured_utc']}    service: {d['service']}")
    print("=" * w)
    print("""
 QUESTION
   Bhoonidhi's /data/search returns every scene whose footprint intersects
   your AOI. It cannot tell you which of them you actually need, because it
   performs no spatial analysis over the footprint geometry it stores. So:
   how many of the scenes it hands back are redundant?
""")

    print(f" {'AOI':<18}{'collection':<16}{'km2':>9}{'found':>7}{'needed':>7}"
          f"{'waste':>7}{'GB today':>10}{'GB needed':>11}")
    print(" " + "-" * (w - 2))
    for r in d["rows"]:
        print(f" {r['aoi_label']:<18}{r['collection']:<16}"
              f"{r['aoi_area_km2']:>9.0f}{r['candidates_considered']:>7}"
              f"{r['scenes_selected']:>7}{r['redundant_fraction']*100:>6.0f}%"
              f"{r['download_today_gb']:>10.1f}{r['download_needed_gb']:>11.1f}")
    print(" " + "-" * (w - 2))
    print(f" {'TOTAL':<34}{t['candidates_considered']:>16}"
          f"{t['scenes_selected']:>7}{t['redundant_fraction']*100:>6.0f}%"
          f"{t['download_today_gb']:>10.1f}{t['download_needed_gb']:>11.1f}")

    print(f"""
 FINDING
   Across {t['queries']} queries over {t['aois_measured']} areas of interest, the catalogue would
   hand back {t['candidates_considered']} scenes. {t['scenes_selected']} of them cover the same ground to the
   same percentage. {t['scenes_avoided']} are redundant - {t['redundant_fraction']*100:.0f}% of everything returned.

   At published product sizes that is {t['download_today_gb']:.0f} GB ordered where
   {t['download_needed_gb']:.0f} GB was required: {t['wasted_gb']:.0f} GB of avoidable transfer, for
   these four areas alone.

   Projected onto Bhoonidhi's own optical products (ResourceSat-2 LISS-III,
   250 MB/scene) the same redundancy is {t['bhoonidhi_wasted_gb']:.0f} GB.

 WHY THIS IS A CAPABILITY GAP AND NOT A USER ERROR
   Nothing in Bhoonidhi's API lets a user discover the {t['redundant_fraction']*100:.0f}% figure. To get
   it they must export every footprint, load them into a desktop GIS or a
   shapely script, union them, difference them against the AOI, and solve a
   set-cover problem - the work this service does in one HTTP request. The
   catalogue holds all the geometry needed to answer it and declines to.

 WHAT THIS SERVICE RETURNS INSTEAD
   POST /processes/minimal-scene-set/execution  -> the scenes to order,
   in order, each with the new area it contributes and the running coverage
   fraction, plus whatever the AOI still lacks as explicit gap polygons.

 THIS MEASUREMENT IS A FLOOR, NOT A CEILING
   The footprint store holds {d['store_scenes']} scenes over a {d['store_window']}, because that is
   what was harvested. Several rows above are capped by the store rather
   than by the AOI - "found" reaches the store's own limit because that is
   all there is to find. A real Bhoonidhi search spans a multi-decade
   archive with many revisits per year, so it returns far more intersecting
   scenes for the same AOI while the number genuinely needed to cover it
   stays roughly constant. Redundancy therefore RISES with archive depth;
   {t['redundant_fraction']*100:.0f}% is the conservative end of this measurement.
""")
    print("=" * w)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-only", action="store_true",
                    help="print only the JSON document")
    args = ap.parse_args()

    try:
        requests.get(f"{BASE}/", timeout=10)
    except requests.RequestException:
        sys.exit(f"{BASE} is not responding - run ./scripts/serve_local.sh start")

    d = measure()
    if not d["rows"]:
        sys.exit("no AOI produced any candidates; is data/footprints.geojson built?")

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    out = EVIDENCE / "redundancy-measurement.json"
    out.write_text(json.dumps(d, indent=2) + "\n")

    if args.json_only:
        print(json.dumps(d, indent=2))
    else:
        report(d)
        print(f" saved -> docs/evidence/{out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

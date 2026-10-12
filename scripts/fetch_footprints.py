#!/usr/bin/env python3
"""
fetch_footprints.py - harvest acquisition FOOTPRINTS into a local store, so the
spatial-analysis processes have real geometry to work on.

Two sources, one code path, because both speak STAC:

  --source bhoonidhi   the real thing. POST /data/search against
                       https://bhoonidhi-api.nrsc.gov.in with a JWT from
                       /auth/token. Needs BHOONIDHI_USER / BHOONIDHI_PASS.

  --source open        Microsoft Planetary Computer's public STAC API. No
                       credentials. Used so the spatial operations are
                       demonstrable by anyone, and clearly LABELLED as a
                       substitute in the output manifest.

Either way what lands on disk is a GeoJSON FeatureCollection of real
acquisition footprints with real timestamps - which is exactly what Bhoonidhi
will give you per item and will not do anything *with*.

Usage:
    ./scripts/fetch_footprints.py --source open
    ./scripts/fetch_footprints.py --source open --collection sentinel-1-grd
    ./scripts/fetch_footprints.py --source bhoonidhi --collection ResourceSat-2_LISS3_L2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests is required:  pip install requests")

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "footprints.geojson"

BHOONIDHI_API = os.environ.get("BHOONIDHI_API", "https://bhoonidhi-api.nrsc.gov.in")
OPEN_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"

# Default AOI: the Western Ghats window in Karnataka. Chosen for a mix of
# optical and radar coverage, and small enough to keep responses quick.
AOI = (75.1, 13.0, 76.0, 14.1)
START, END = "2024-01-01T00:00:00Z", "2024-03-31T23:59:59Z"

UA = "bhoonidhi-records/1.0 (academic coursework)"


def fetch_open(collection: str, bbox, start: str, end: str, limit: int):
    """Planetary Computer STAC search. Pages through rel=next."""
    url, body = f"{OPEN_STAC}/search", {
        "collections": [collection], "bbox": list(bbox),
        "datetime": f"{start}/{end}", "limit": min(limit, 250),
    }
    feats, page = [], 1
    s = requests.Session()
    s.headers["User-Agent"] = UA
    while url and len(feats) < limit:
        r = s.post(url, json=body, timeout=120)
        if r.status_code != 200:
            sys.exit(f"open STAC search failed: HTTP {r.status_code} {r.text[:200]}")
        d = r.json()
        got = d.get("features", [])
        feats.extend(got)
        print(f"  page {page}: {len(got)} footprint(s), {len(feats)} total")
        nxt = next((l for l in d.get("links", []) if l.get("rel") == "next"), None)
        if not nxt or not got:
            break
        url = nxt.get("href", "")
        body = nxt.get("body", body)
        page += 1
    return feats[:limit], "Microsoft Planetary Computer (public STAC)", True


def fetch_bhoonidhi(collection: str, bbox, start: str, end: str, limit: int):
    """Bhoonidhi /data/search. Needs a JWT; this is the real source."""
    user, pw = os.environ.get("BHOONIDHI_USER"), os.environ.get("BHOONIDHI_PASS")
    if not user or not pw:
        sys.exit("BHOONIDHI_USER / BHOONIDHI_PASS not set. Register free at\n"
                 "  https://bhoonidhi.nrsc.gov.in/\n"
                 "or use --source open for the public substitute.")

    s = requests.Session()
    s.headers["User-Agent"] = UA

    # Reuse the cached session rather than opening a new one per harvest.
    # Bhoonidhi limits concurrent sessions, so logging in on every run
    # eventually earns a 403 and locks you out until the old ones expire.
    # bhoonidhi_login.py owns the token, its 0600 cache file and the error
    # messages; this is just a consumer of it.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from bhoonidhi_login import login as _login, verify as _verify
    token = _login()
    if not _verify(token):
        print("  cached token rejected; re-authenticating")
        token = _login(force=True)
        if not _verify(token):
            sys.exit("could not obtain a working Bhoonidhi token - "
                     "run ./scripts/bhoonidhi_login.py for diagnostics")

    minx, miny, maxx, maxy = bbox
    payload = {
        "collections": [collection],
        "intersects": {"type": "Polygon", "coordinates": [[
            [minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]]},
        "datetime": f"{start}/{end}",
        "limit": min(limit, 500),
    }
    url, feats, page = f"{BHOONIDHI_API}/data/search", [], 1
    while url and len(feats) < limit:
        r = s.post(url, json=payload,
                   headers={"Authorization": f"Bearer {token}"}, timeout=180)
        if r.status_code == 503:
            sys.exit("Bhoonidhi STAC backend unavailable (503). Try later.")
        r.raise_for_status()
        d = r.json()
        got = d.get("features", [])
        feats.extend(got)
        print(f"  page {page}: {len(got)} footprint(s), {len(feats)} total")
        nxt = next((l for l in d.get("links", []) if l.get("rel") == "next"), None)
        if not nxt or not got:
            break
        url, payload, page = nxt.get("href", ""), nxt.get("body", payload), page + 1
    return feats[:limit], f"Bhoonidhi {BHOONIDHI_API}/data/search", False


def normalise(feats: list[dict], collection: str) -> list[dict]:
    """Keep only what the spatial operations need, so the store stays small
    and the provenance of every field is obvious."""
    out = []
    for f in feats:
        g = f.get("geometry")
        if not g or g.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        p = f.get("properties", {})
        out.append({
            "type": "Feature",
            "id": f.get("id"),
            "geometry": g,
            "properties": {
                "item_id": f.get("id"),
                "collection": f.get("collection") or collection,
                "datetime": p.get("datetime") or p.get("start_datetime"),
                "platform": p.get("platform") or p.get("Satellite"),
                "instrument": (p.get("instruments") or [p.get("Sensor")] or [None])[0]
                if isinstance(p.get("instruments"), list) else p.get("instruments") or p.get("Sensor"),
                "cloud_cover": p.get("eo:cloud_cover") or p.get("Cloud_Percent"),
            },
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", choices=("open", "bhoonidhi"), default="open")
    ap.add_argument("--collection", default=None,
                    help="STAC collection id (defaults per source)")
    ap.add_argument("--bbox", default=",".join(map(str, AOI)),
                    help="minlon,minlat,maxlon,maxlat")
    ap.add_argument("--start", default=START)
    ap.add_argument("--end", default=END)
    ap.add_argument("--limit", type=int, default=120)
    ap.add_argument("--append", action="store_true",
                    help="add to the existing store instead of replacing it")
    args = ap.parse_args()

    bbox = tuple(float(v) for v in args.bbox.split(","))
    if len(bbox) != 4:
        sys.exit("--bbox needs four numbers")

    collection = args.collection or (
        "sentinel-2-l2a" if args.source == "open" else "ResourceSat-2_LISS3_L2")

    print("=" * 70)
    print(" Harvesting acquisition footprints")
    print("=" * 70)
    print(f"  source     : {args.source}")
    print(f"  collection : {collection}")
    print(f"  AOI        : {bbox}")
    print(f"  window     : {args.start} .. {args.end}")
    print()

    if args.source == "open":
        feats, src_desc, substitute = fetch_open(collection, bbox, args.start, args.end, args.limit)
    else:
        feats, src_desc, substitute = fetch_bhoonidhi(collection, bbox, args.start, args.end, args.limit)

    norm = normalise(feats, collection)
    if not norm:
        sys.exit("\nNo usable footprints returned. Widen the AOI or the window.")

    existing = []
    if args.append and OUT.exists():
        try:
            existing = json.loads(OUT.read_text()).get("features", [])
        except Exception:
            existing = []
    seen, merged = set(), []
    for f in existing + norm:
        key = (f["properties"].get("collection"), f.get("id"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(f)

    collections = sorted({f["properties"]["collection"] for f in merged})
    OUT.write_text(json.dumps({
        "type": "FeatureCollection",
        "metadata": {
            "description": "Acquisition footprints used by the spatial-analysis "
                           "processes. Geometry and timestamps are as returned by "
                           "the source STAC API; nothing is synthesised.",
            "source": src_desc,
            "is_substitute_for_bhoonidhi": substitute,
            "substitute_note": (
                "These footprints are NOT from Bhoonidhi. Bhoonidhi's /data/search "
                "requires a JWT, so an open STAC API stands in so that the spatial "
                "operations are demonstrable without credentials. Re-run with "
                "--source bhoonidhi to use the real thing; the code path and the "
                "processes are identical." if substitute else
                "Footprints harvested from Bhoonidhi's own STAC search."),
            "collections": collections,
            "aoi_bbox": list(bbox),
            "window": [args.start, args.end],
            "harvested_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "count": len(merged),
        },
        "features": merged,
    }, indent=2))

    print(f"\n  footprints stored : {len(merged)}")
    print(f"  collections       : {', '.join(collections)}")
    print(f"  substitute source : {substitute}")
    print(f"  wrote             : {OUT.relative_to(ROOT)}")
    print("\n  Next: ./scripts/serve_local.sh start   then try the spatial processes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

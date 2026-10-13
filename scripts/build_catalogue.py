#!/usr/bin/env python3
"""
build_catalogue.py - build the OGC API - Records catalogue from Bhoonidhi's
published collection list.

WHY THIS EXISTS is the argument of the repository. Bhoonidhi's catalogue is
reachable only with a JWT: every call to /data/collections and /data/search
needs a token, so the holdings cannot be browsed anonymously, crawled, or
harvested into any standard catalogue client. There is no CSW and no
OGC API - Records endpoint. This script therefore builds a catalogue record
per collection from the information Bhoonidhi publishes openly - its API
specification page - and serves it through a conformant Records API.

Provenance rules followed here, because a catalogue that invents metadata is
worse than no catalogue:
  * collection ids come verbatim from Bhoonidhi's published list
  * platform / instrument / product are parsed out of the id itself
  * resolution is recorded only where the id states it (e.g. _30m, _8day_1km)
  * temporal start is the mission LAUNCH date, labelled as indicative - data
    availability cannot begin before launch, and Bhoonidhi does not publish
    per-collection temporal extents without a token
  * spatial extent is labelled indicative and derived from mission type only
  * nothing else is asserted

Usage:
    ./scripts/build_catalogue.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from tinydb import TinyDB
except ImportError:
    sys.exit("tinydb is required:  pip install tinydb")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "bhoonidhi_collections.txt"
OUT_DB = ROOT / "data" / "bhoonidhi-records.tinydb"
OUT_GJ = ROOT / "data" / "bhoonidhi-records.geojson"

PORTAL = "https://bhoonidhi.nrsc.gov.in/"
API_SPEC = "https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/"
API_BASE = "https://bhoonidhi-api.nrsc.gov.in"

# Mission launch dates. Used ONLY as an indicative lower bound on data
# availability, and labelled as such in every record.
LAUNCH = {
    "CartoSat-1":     "2005-05-05",
    "ResourceSat-2":  "2011-04-20",
    "Sentinel-1A":    "2014-04-03",
    "ResourceSat-2A": "2016-12-07",
    "Novasar-1":      "2018-09-16",
    "EOS-04":         "2022-02-14",
    "EOS-06":         "2022-11-26",
    "NISAR":          "2025-07-30",
}

PLATFORM_LONG = {
    "CartoSat-1":     "Cartosat-1 (IRS-P5)",
    "ResourceSat-2":  "ResourceSat-2",
    "ResourceSat-2A": "ResourceSat-2A",
    "EOS-04":         "EOS-04 (RISAT-1A)",
    "EOS-06":         "EOS-06 (Oceansat-3)",
    "Sentinel-1A":    "Sentinel-1A",
    "Novasar-1":      "NovaSAR-1",
    "NISAR":          "NISAR",
}

# Instruments, as the collection ids spell them.
INSTRUMENT = {
    "AWIFS":     ("AWiFS", "optical", "Advanced Wide Field Sensor"),
    "LISS3":     ("LISS-III", "optical", "Linear Imaging Self Scanner III"),
    "LISS4-MX70": ("LISS-IV MX", "optical", "Linear Imaging Self Scanner IV, multispectral mode"),
    "PAN":       ("PAN", "optical", "Panchromatic camera"),
    "SAR-MRS":   ("SAR (MRS)", "radar", "Synthetic Aperture Radar, Medium Resolution Stripmap"),
    "SAR-CRS":   ("SAR (CRS)", "radar", "Synthetic Aperture Radar, Coarse Resolution Stripmap"),
    "SAR-FRS1":  ("SAR (FRS-1)", "radar", "Synthetic Aperture Radar, Fine Resolution Stripmap 1"),
    "SAR-FRS2":  ("SAR (FRS-2)", "radar", "Synthetic Aperture Radar, Fine Resolution Stripmap 2"),
    "SAR-IW":    ("SAR (IW)", "radar", "Synthetic Aperture Radar, Interferometric Wide swath"),
    "OCM-LAC":   ("OCM (LAC)", "optical", "Ocean Colour Monitor, Local Area Coverage"),
    "OCM-GAC":   ("OCM (GAC)", "optical", "Ocean Colour Monitor, Global Area Coverage"),
    "SCAT":      ("SCAT", "radar", "Ku-band scatterometer"),
    "SSAR":      ("S-SAR", "radar", "S-band Synthetic Aperture Radar"),
    "AIS":       ("AIS", "other", "Automatic Identification System receiver"),
}

# Product tokens that appear in the ids.
PRODUCT = {
    "L1C": "Level-1C", "L2": "Level-2", "L2A": "Level-2A", "L2B": "Level-2B",
    "L2C": "Level-2C", "1B": "Level-1B", "2B": "Level-2B", "3SH": "Level-3 (SH)",
    "3SV": "Level-3 (SV)", "3WW": "Level-3 (WW)", "SM": "Soil Moisture",
    "BOA": "Bottom-of-Atmosphere reflectance", "SLC": "Single Look Complex",
    "GRD": "Ground Range Detected", "RSLC": "Range-Doppler Single Look Complex",
    "GSLC": "Geocoded Single Look Complex", "GCOV": "Geocoded Covariance",
    "RUNW": "Range-Doppler Unwrapped Interferogram",
    "GUNW": "Geocoded Unwrapped Interferogram",
    "RIFG": "Range-Doppler Interferogram", "ROFF": "Range-Doppler Offsets",
    "GOFF": "Geocoded Offsets", "AOD": "Aerosol Optical Depth",
    "CHL": "Chlorophyll concentration", "DA": "Diffuse Attenuation",
    "NDVI": "Normalised Difference Vegetation Index",
    "RRS": "Remote Sensing Reflectance",
    "TSM": "Total Suspended Matter", "VF": "Vegetation Fraction",
    "CartoDEM": "Digital Elevation Model", "AIS": "Vessel position reports",
    "mosaic": "Mosaic",
}

# Indicative spatial extents, by mission tasking. Labelled in every record.
INDIA = [68.0, 6.0, 98.0, 38.0]
GLOBAL = [-180.0, -90.0, 180.0, 90.0]
GLOBAL_MISSIONS = {"Sentinel-1A", "NISAR", "Novasar-1"}


def parse(cid: str) -> dict | None:
    """Split a Bhoonidhi collection id into its parts. Returns None if the
    token is not actually a collection (the spec page contains other
    underscore-joined words)."""
    parts = cid.split("_")
    plat = parts[0]
    if plat not in PLATFORM_LONG:
        return None

    rest = parts[1:]
    instr_key = rest[0] if rest else ""
    instr, domain, instr_long = INSTRUMENT.get(
        instr_key, (instr_key or "unknown", "unknown", instr_key))

    tail = rest[1:]
    products, extras, res = [], [], None
    for t in tail:
        if t in PRODUCT:
            products.append(PRODUCT[t])
            continue
        # resolution, only where the id states it
        m = re.fullmatch(r"(\d+)(m|km)", t)
        if m:
            res = int(m.group(1)) * (1000 if m.group(2) == "km" else 1)
            extras.append(t)
            continue
        # composite period, e.g. 8day
        if re.fullmatch(r"\d+day", t):
            extras.append(t)
            continue
        # hyphenated tails such as L2C-NDVI or 1deg-mosaic
        hit = [PRODUCT[p] for p in t.split("-") if p in PRODUCT]
        if hit:
            products.extend(hit)
        else:
            extras.append(t)

    return {
        "platform": plat, "platform_long": PLATFORM_LONG[plat],
        "instrument": instr, "instrument_long": instr_long, "domain": domain,
        "products": products, "extras": extras, "resolution_m": res,
    }


def build_record(cid: str, p: dict, now: str) -> dict:
    prod = ", ".join(p["products"]) if p["products"] else "product"
    extras = " ".join(p["extras"])
    title = f"{p['platform_long']} {p['instrument']} - {prod}".strip()
    if extras:
        title += f" ({extras})"

    bbox = GLOBAL if p["platform"] in GLOBAL_MISSIONS else INDIA
    start = LAUNCH.get(p["platform"])

    desc = (
        f"Bhoonidhi collection '{cid}'. {p['platform_long']}, "
        f"{p['instrument_long']} ({p['domain']} instrument). "
        f"Product: {prod}."
    )
    if p["resolution_m"]:
        desc += f" Nominal resolution {p['resolution_m']} m, as stated in the collection identifier."
    desc += (
        f" Discoverable and downloadable from Bhoonidhi only with an "
        f"authenticated token, via POST {API_BASE}/data/search and "
        f"GET {API_BASE}/download. This catalogue record is derived from "
        f"Bhoonidhi's published collection list; it is metadata about the "
        f"collection, not the data itself."
    )

    keywords = [p["platform_long"], p["instrument"], p["domain"],
                "Bhoonidhi", "ISRO", "NRSC", "earth observation", "India"]
    keywords += p["products"]
    if p["resolution_m"]:
        keywords.append(f"{p['resolution_m']}m")

    return {
        "id": cid,
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]], [bbox[2], bbox[1]],
                [bbox[2], bbox[3]], [bbox[0], bbox[3]], [bbox[0], bbox[1]],
            ]],
        },
        "time": {"interval": [start, None]} if start else None,
        "properties": {
            "type": "dataset",
            "title": title,
            "description": desc,
            "keywords": sorted(set(k for k in keywords if k)),
            "language": "en",
            "created": now,
            "updated": now,
            # Queryables that make the catalogue genuinely searchable.
            "platform": p["platform_long"],
            "platform_id": p["platform"],
            "instrument": p["instrument"],
            "domain": p["domain"],
            "product": prod,
            "resolution_m": p["resolution_m"],
            "collection_id": cid,
            # Temporal start, explicitly labelled.
            "temporal_start": start,
            "temporal_start_basis": (
                "mission launch date - indicative lower bound only; Bhoonidhi "
                "does not publish per-collection temporal extents without a token"),
            "spatial_extent_basis": (
                "indicative, derived from mission tasking "
                f"({'global' if p['platform'] in GLOBAL_MISSIONS else 'India and surrounds'})"
                " - Bhoonidhi does not publish per-collection footprints without a token"),
            "access": "authenticated",
            "access_note": (
                "Bhoonidhi requires a JWT from POST /auth/token for every "
                "catalogue and download call. Register free at " + PORTAL),
            "rights": (
                "Metadata compiled from Bhoonidhi's published collection list for "
                "academic discovery. The underlying data is ISRO/NRSC's and is "
                "subject to Bhoonidhi's terms; attribution required."),
            "providers": [{
                "name": "ISRO / National Remote Sensing Centre (NRSC)",
                "roles": ["producer", "licensor", "host"],
                "url": PORTAL,
            }],
            "themes": [{
                "concepts": [{"id": p["domain"]}, {"id": p["instrument"]},
                             {"id": p["platform_long"]}],
                "scheme": "https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/",
            }],
            "externalIds": [{"scheme": "bhoonidhi-collection", "value": cid}],
            "formats": [{"name": "as distributed by Bhoonidhi /download"}],
            "_metadata-anytext": "",
        },
        "links": [
            {"rel": "canonical", "type": "text/html",
             "title": "Bhoonidhi portal", "href": PORTAL},
            {"rel": "service-desc", "type": "text/html",
             "title": "Bhoonidhi Open Data Access API specification",
             "href": API_SPEC},
            {"rel": "items", "type": "application/json",
             "title": f"STAC items for {cid} (requires a token)",
             "href": f"{API_BASE}/data/collections/{cid}/items"},
            {"rel": "search", "type": "application/json",
             "title": "Bhoonidhi STAC search (requires a token)",
             "href": f"{API_BASE}/data/search"},
        ],
    }


def main() -> int:
    if not SRC.exists():
        sys.exit(f"{SRC} not found. It is produced from Bhoonidhi's published "
                 "collection list; see README.")

    ids = [l.strip() for l in SRC.read_text().splitlines() if l.strip()]

    # Record timestamps come from the SOURCE LIST's mtime, not from "now", so
    # that building the catalogue twice from the same input produces byte
    # identical output.
    #
    # data/bhoonidhi-records.geojson is committed (so the records are readable
    # on GitHub without running anything), and with a wall-clock timestamp
    # every `make data` rewrote all 59 records and left the working tree dirty
    # - which `make verify` then correctly reported as an uncommitted change.
    # A derived file that changes when its input did not is noise, and noise
    # in a diff is how real changes get missed.
    #
    # SOURCE_DATE_EPOCH (the reproducible-builds convention) overrides it.
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    ts = (datetime.fromtimestamp(int(epoch), timezone.utc) if epoch
          else datetime.fromtimestamp(SRC.stat().st_mtime, timezone.utc))
    now = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    records, skipped = [], []
    for cid in ids:
        p = parse(cid)
        if p is None:
            skipped.append(cid)
            continue
        records.append(build_record(cid, p, now))

    # pygeoapi's TinyDB catalogue serves `q=` out of _metadata-anytext, so
    # whatever is NOT in this string is invisible to full-text search.
    #
    # This used to be title + description only, which made the catalogue lie
    # by omission: every record carries "India", "ISRO" and "NRSC" in its
    # keywords, yet q=India and q=ISRO both returned zero results while
    # q=ResourceSat worked - because the former appear only in `keywords` and
    # the latter also appears in the title. A user cannot tell that apart from
    # "this catalogue has nothing about India".
    #
    # The index therefore covers every field a person would plausibly type:
    # the free text, the controlled vocabulary, and the parsed facets.
    ANYTEXT_FIELDS = ("title", "description", "platform", "platform_id",
                      "instrument", "product", "domain", "collection_id")
    for r in records:
        p = r["properties"]
        parts = [str(p.get(f, "")) for f in ANYTEXT_FIELDS]
        parts += [str(k) for k in (p.get("keywords") or [])]
        parts += [str(t.get("id", "")) for t in (p.get("themes") or [])
                  if isinstance(t, dict)]
        p["_metadata-anytext"] = " ".join(x for x in parts if x)

    OUT_DB.unlink(missing_ok=True)
    db = TinyDB(OUT_DB)
    db.insert_multiple(records)
    db.close()

    OUT_GJ.write_text(json.dumps(
        {"type": "FeatureCollection", "features": records}, indent=2))

    print("=" * 70)
    print(" Bhoonidhi Records catalogue built")
    print("=" * 70)
    print(f"  source list   : {SRC.relative_to(ROOT)} ({len(ids)} tokens)")
    print(f"  records built : {len(records)}")
    if skipped:
        print(f"  skipped       : {len(skipped)} non-collection tokens "
              f"({', '.join(skipped)})")
    print(f"  wrote         : {OUT_DB.relative_to(ROOT)}")
    print(f"  wrote         : {OUT_GJ.relative_to(ROOT)}")

    by_plat: dict[str, int] = {}
    by_dom: dict[str, int] = {}
    for r in records:
        by_plat[r["properties"]["platform"]] = by_plat.get(r["properties"]["platform"], 0) + 1
        by_dom[r["properties"]["domain"]] = by_dom.get(r["properties"]["domain"], 0) + 1
    print("\n  by platform:")
    for k, v in sorted(by_plat.items(), key=lambda kv: -kv[1]):
        print(f"    {k:26s} {v}")
    print("  by instrument domain:")
    for k, v in sorted(by_dom.items(), key=lambda kv: -kv[1]):
        print(f"    {k:26s} {v}")
    print("\n  Next: ./scripts/serve_local.sh start")
    return 0


if __name__ == "__main__":
    sys.exit(main())

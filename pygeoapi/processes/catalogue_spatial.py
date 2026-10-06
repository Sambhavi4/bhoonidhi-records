"""
OGC API - Processes: spatial analysis over acquisition footprints.

These are the operations that make a catalogue *useful* rather than merely
listable, and they are exactly what Bhoonidhi cannot do. Bhoonidhi's
/data/search returns a flat list of items that intersect your polygon. It will
not tell you what fraction of your area is actually covered, where the holes
are, which minimal set of scenes to order, or where two sensors overlap in the
same window. Every acquisition-planning question is therefore answered by hand
in a desktop GIS, by every user, every time.

Deliberately distinct from pixel-level processing: nothing here touches a band
or a raster value. The inputs are footprint geometries and timestamps, and the
operations are spatial set algebra (union, intersection, difference), area
measurement and a set-cover optimisation.

All areas are measured in a Lambert Azimuthal Equal-Area projection centred on
the request's own area of interest, so square kilometres mean square
kilometres. Measuring in degrees would make every number here wrong.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape, box
from shapely.ops import transform as shp_transform, unary_union

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
FOOTPRINTS = Path(os.environ.get("FOOTPRINTS_FILE", ROOT / "data" / "footprints.geojson"))

# Guard: a greedy set cover over thousands of footprints is quadratic, and an
# unbounded grid request can exhaust the host.
MAX_FOOTPRINTS = 2000
MAX_GRID_CELLS = 4000


def _fail(msg: str) -> ProcessorExecuteError:
    return ProcessorExecuteError(msg)


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def _equal_area(geom_wgs84) -> tuple[Any, Any]:
    """Return (to_m, from_m) transformers for an equal-area CRS centred on the
    geometry. Areas computed after `to_m` are in square metres."""
    c = geom_wgs84.centroid
    laea = CRS.from_proj4(
        f"+proj=laea +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs")
    wgs = CRS.from_epsg(4326)
    return (Transformer.from_crs(wgs, laea, always_xy=True).transform,
            Transformer.from_crs(laea, wgs, always_xy=True).transform)


def _km2(geom_m) -> float:
    return round(geom_m.area / 1e6, 4)


def _aoi(raw) -> Any:
    """Accept a GeoJSON geometry, Feature, FeatureCollection, or a bbox list."""
    if raw is None:
        raise _fail("'aoi' is required: a GeoJSON Polygon/MultiPolygon, or a "
                    "bbox as [minLon, minLat, maxLon, maxLat]")
    if isinstance(raw, (list, tuple)):
        if len(raw) != 4:
            raise _fail("a bbox 'aoi' must be [minLon, minLat, maxLon, maxLat]")
        minx, miny, maxx, maxy = (float(v) for v in raw)
        if minx >= maxx or miny >= maxy:
            raise _fail("bbox must satisfy minLon<maxLon and minLat<maxLat")
        return box(minx, miny, maxx, maxy)
    if not isinstance(raw, dict):
        raise _fail("'aoi' must be a GeoJSON object or a bbox array")
    t = raw.get("type")
    if t == "FeatureCollection":
        feats = raw.get("features") or []
        if not feats:
            raise _fail("'aoi' FeatureCollection has no features")
        return unary_union([shape(f["geometry"]) for f in feats])
    if t == "Feature":
        return shape(raw["geometry"])
    if t in ("Polygon", "MultiPolygon"):
        return shape(raw)
    raise _fail(f"unsupported 'aoi' geometry type {t!r}")


def _load(collection: str | None, start: str | None, end: str | None,
          aoi_wgs) -> list[dict]:
    """Load footprints, filtered by collection and time window, keeping only
    those that actually intersect the AOI."""
    if not FOOTPRINTS.exists():
        raise _fail(f"no footprint store at {FOOTPRINTS.name}. Run "
                    "scripts/fetch_footprints.py first.")
    try:
        fc = json.loads(FOOTPRINTS.read_text())
    except json.JSONDecodeError as e:
        raise _fail(f"footprint store is not valid JSON: {e}")

    def parse(ts: str | None):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None

    t0, t1 = parse(start), parse(end)
    out = []
    for f in fc.get("features", []):
        p = f.get("properties", {})
        if collection and p.get("collection") != collection:
            continue
        ts = parse(p.get("datetime"))
        if t0 and ts and ts < t0:
            continue
        if t1 and ts and ts > t1:
            continue
        try:
            g = shape(f["geometry"])
        except Exception:
            continue
        if g.is_empty or not g.is_valid:
            g = g.buffer(0)
        if g.is_empty or not g.intersects(aoi_wgs):
            continue
        out.append({"id": f.get("id"), "geom": g, "props": p})

    if len(out) > MAX_FOOTPRINTS:
        raise _fail(f"{len(out)} footprints match, above the {MAX_FOOTPRINTS} "
                    "limit; narrow the AOI, the window or the collection")
    return out


def _store_meta() -> dict:
    try:
        return json.loads(FOOTPRINTS.read_text()).get("metadata", {})
    except Exception:
        return {}


def _provenance(n: int, collection, start, end) -> dict:
    m = _store_meta()
    return {
        "footprints_considered": n,
        "footprint_source": m.get("source"),
        "is_substitute_for_bhoonidhi": m.get("is_substitute_for_bhoonidhi"),
        "substitute_note": m.get("substitute_note"),
        "filters": {"collection": collection, "start": start, "end": end},
        "area_crs": "Lambert Azimuthal Equal-Area centred on the AOI "
                    "(areas in km2, not degrees)",
        "computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------------------
# shared input fragments
# ---------------------------------------------------------------------------
_AOI_IN = {
    "title": "Area of interest",
    "description": "GeoJSON Polygon/MultiPolygon/Feature/FeatureCollection in "
                   "EPSG:4326, or a bbox as [minLon, minLat, maxLon, maxLat].",
    "schema": {"oneOf": [
        {"type": "object"},
        {"type": "array", "minItems": 4, "maxItems": 4,
         "items": {"type": "number"}}]},
    "minOccurs": 1, "maxOccurs": 1,
}
_COLL_IN = {
    "title": "Collection",
    "description": "Restrict to one collection id. Omit to use all footprints.",
    "schema": {"type": "string"}, "minOccurs": 0, "maxOccurs": 1,
}
_START_IN = {"title": "Window start", "description": "RFC 3339 datetime.",
             "schema": {"type": "string"}, "minOccurs": 0, "maxOccurs": 1}
_END_IN = {"title": "Window end", "description": "RFC 3339 datetime.",
           "schema": {"type": "string"}, "minOccurs": 0, "maxOccurs": 1}
_JSON_OUT = {"result": {
    "title": "Result",
    "description": "Analysis result, with geometry where applicable",
    "schema": {"type": "object", "contentMediaType": "application/json"}}}

_EXAMPLE_AOI = [75.3, 13.2, 75.8, 13.9]


def _meta(pid, title, desc, extra=None, keywords=None, example=None):
    inputs = {"aoi": dict(_AOI_IN), "collection": dict(_COLL_IN),
              "start": dict(_START_IN), "end": dict(_END_IN)}
    if extra:
        inputs.update(extra)
    return {
        "version": "1.0.0", "id": pid,
        "title": {"en": title}, "description": {"en": desc},
        "jobControlOptions": ["sync-execute", "async-execute"],
        "keywords": keywords or ["catalogue", "footprints", "spatial analysis"],
        "links": [{"type": "text/html", "rel": "about",
                   "title": "Project repository", "href": "https://github.com/",
                   "hreflang": "en-US"}],
        "inputs": inputs, "outputs": dict(_JSON_OUT),
        "example": example or {"inputs": {"aoi": _EXAMPLE_AOI}},
    }


# ===========================================================================
class AoiCoverageProcessor(BaseProcessor):
    """How much of my area is actually covered, and where are the holes?"""

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "aoi-coverage", "AOI coverage and gap analysis",
            "Unions every acquisition footprint intersecting the area of "
            "interest, measures what fraction of the AOI that union covers, and "
            "returns the UNCOVERED remainder as explicit gap polygons. This is "
            "the question Bhoonidhi's search cannot answer: it returns a list of "
            "scenes that touch your polygon, never how much of it they actually "
            "cover or where they do not.",
            keywords=["coverage", "gap analysis", "union", "difference"]))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        coll = data.get("collection")
        start, end = data.get("start"), data.get("end")
        fps = _load(coll, start, end, aoi)

        to_m, from_m = _equal_area(aoi)
        aoi_m = shp_transform(to_m, aoi)
        aoi_km2 = _km2(aoi_m)
        if aoi_km2 <= 0:
            raise _fail("the AOI has zero area")

        # The empty case must return the SAME keys as the populated one, or a
        # client that works when scenes exist breaks the moment none do.
        if not fps:
            return "application/json", {
                "id": "aoi-coverage",
                "aoi_area_km2": aoi_km2,
                "covered_area_km2": 0.0,
                "coverage_fraction": 0.0,
                "coverage_percent": 0.0,
                "gap_area_km2": aoi_km2,
                "gap_fraction": 1.0,
                "scene_count": 0,
                "fully_covered": False,
                "gap_threshold_km2": 0.01,
                "covered_geometry": None,
                "gaps": mapping(aoi),
                "scenes": [],
                "message": "No footprints match these filters, so none of the "
                           "AOI is covered.",
                "provenance": _provenance(0, coll, start, end),
            }

        clipped_m = [shp_transform(to_m, f["geom"]).intersection(aoi_m) for f in fps]
        union_m = unary_union([g for g in clipped_m if not g.is_empty])
        covered = _km2(union_m)
        gaps_m = aoi_m.difference(union_m)
        frac = min(1.0, covered / aoi_km2)

        # A difference of two near-identical polygons leaves hairline slivers
        # with effectively zero area. Reporting those as "gaps" while also
        # reporting fully_covered=true is contradictory, so collapse anything
        # under 0.01 km2 (1 hectare) to no gap at all.
        GAP_EPS_KM2 = 0.01
        gap_km2 = _km2(gaps_m)
        has_gap = (not gaps_m.is_empty) and gap_km2 >= GAP_EPS_KM2
        if not has_gap:
            gap_km2 = 0.0

        per_scene = sorted((
            {"item_id": f["id"],
             "collection": f["props"].get("collection"),
             "datetime": f["props"].get("datetime"),
             "cloud_cover": f["props"].get("cloud_cover"),
             "aoi_overlap_km2": _km2(g),
             "aoi_overlap_fraction": round(min(1.0, g.area / aoi_m.area), 5)}
            for f, g in zip(fps, clipped_m) if not g.is_empty),
            key=lambda d: -d["aoi_overlap_km2"])

        return "application/json", {
            "id": "aoi-coverage",
            "aoi_area_km2": aoi_km2,
            "covered_area_km2": covered,
            "coverage_fraction": round(frac, 5),
            "coverage_percent": round(frac * 100, 2),
            "gap_area_km2": gap_km2,
            "gap_fraction": round(max(0.0, 1.0 - frac), 5),
            "scene_count": len(per_scene),
            "fully_covered": not has_gap,
            "gap_threshold_km2": GAP_EPS_KM2,
            "covered_geometry": mapping(shp_transform(from_m, union_m)),
            "gaps": mapping(shp_transform(from_m, gaps_m)) if has_gap else None,
            "scenes": per_scene[:200],
            "provenance": _provenance(len(fps), coll, start, end),
        }

    def __repr__(self):
        return "<AoiCoverageProcessor>"


# ===========================================================================
class MinimalSceneSetProcessor(BaseProcessor):
    """Fewest scenes that cover the AOI - a greedy set cover."""

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "minimal-scene-set", "Minimal scene set to cover an AOI",
            "Solves a set-cover problem: starting from every footprint that "
            "touches the area of interest, greedily picks the scene that adds "
            "the most newly-covered area until the AOI is covered or nothing "
            "more can be added. Returns the chosen scenes in order with a "
            "cumulative coverage curve. Ordering every scene a search returns "
            "is how users work today; this says which few are actually needed.",
            extra={"target_fraction": {
                "title": "Target coverage fraction",
                "description": "Stop once this fraction of the AOI is covered "
                               "(0-1). Default 0.99.",
                "schema": {"type": "number", "minimum": 0.01, "maximum": 1.0,
                           "default": 0.99},
                "minOccurs": 0, "maxOccurs": 1},
                "max_scenes": {
                "title": "Maximum scenes",
                "description": "Hard cap on how many scenes to select.",
                "schema": {"type": "integer", "minimum": 1, "maximum": 200,
                           "default": 50},
                "minOccurs": 0, "maxOccurs": 1}},
            keywords=["set cover", "optimisation", "acquisition planning"]))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        coll = data.get("collection")
        start, end = data.get("start"), data.get("end")
        target = float(data.get("target_fraction") or 0.99)
        cap = int(data.get("max_scenes") or 50)
        if not 0.01 <= target <= 1.0:
            raise _fail("target_fraction must be between 0.01 and 1.0")

        fps = _load(coll, start, end, aoi)
        to_m, from_m = _equal_area(aoi)
        aoi_m = shp_transform(to_m, aoi)
        aoi_area = aoi_m.area
        if aoi_area <= 0:
            raise _fail("the AOI has zero area")

        cand = []
        for f in fps:
            g = shp_transform(to_m, f["geom"]).intersection(aoi_m)
            if not g.is_empty:
                cand.append({"f": f, "g": g})

        chosen, covered = [], None
        remaining = list(cand)
        while remaining and len(chosen) < cap:
            frac_now = (covered.area / aoi_area) if covered is not None else 0.0
            if frac_now >= target:
                break
            best, best_gain = None, 0.0
            for c in remaining:
                gain = c["g"].area if covered is None \
                    else c["g"].difference(covered).area
                if gain > best_gain:
                    best, best_gain = c, gain
            # A gain under 1000 m2 is noise, not coverage.
            if best is None or best_gain < 1_000:
                break
            covered = best["g"] if covered is None else unary_union([covered, best["g"]])
            remaining.remove(best)
            chosen.append({
                "order": len(chosen) + 1,
                "item_id": best["f"]["id"],
                "collection": best["f"]["props"].get("collection"),
                "datetime": best["f"]["props"].get("datetime"),
                "cloud_cover": best["f"]["props"].get("cloud_cover"),
                "new_area_km2": round(best_gain / 1e6, 4),
                "cumulative_coverage_fraction": round(min(1.0, covered.area / aoi_area), 5),
            })

        final = (covered.area / aoi_area) if covered is not None else 0.0
        return "application/json", {
            "id": "minimal-scene-set",
            "aoi_area_km2": round(aoi_area / 1e6, 4),
            "candidates_considered": len(cand),
            "scenes_selected": len(chosen),
            "scenes_avoided": max(0, len(cand) - len(chosen)),
            "target_fraction": target,
            "achieved_fraction": round(min(1.0, final), 5),
            "achieved_percent": round(min(1.0, final) * 100, 2),
            "target_met": final >= target,
            "selection": chosen,
            "covered_geometry": mapping(shp_transform(from_m, covered)) if covered is not None else None,
            "algorithm": "greedy set cover; at each step the footprint adding "
                         "the largest previously-uncovered area is taken. Greedy "
                         "set cover is within a ln(n) factor of optimal and is "
                         "not guaranteed minimal.",
            "provenance": _provenance(len(fps), coll, start, end),
        }

    def __repr__(self):
        return "<MinimalSceneSetProcessor>"


# ===========================================================================
class MultiSensorOverlapProcessor(BaseProcessor):
    """Where do two collections co-cover in the same window?"""

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "multi-sensor-overlap", "Multi-sensor co-coverage",
            "Intersects the footprint union of one collection with that of "
            "another over the same area and time window, and returns the "
            "co-covered geometry and its area. Data fusion - optical with "
            "radar, for instance - needs both sensors over the same ground in "
            "the same window, and no catalogue in the stack can answer that: "
            "you would search twice and intersect the results by hand.",
            extra={"collection_a": {
                "title": "First collection",
                "description": "Collection id, e.g. an optical collection.",
                "schema": {"type": "string"}, "minOccurs": 1, "maxOccurs": 1},
                "collection_b": {
                "title": "Second collection",
                "description": "Collection id, e.g. a radar collection.",
                "schema": {"type": "string"}, "minOccurs": 1, "maxOccurs": 1}},
            keywords=["co-coverage", "data fusion", "intersection",
                      "optical", "radar"],
            example={"inputs": {"aoi": _EXAMPLE_AOI,
                                "collection_a": "sentinel-2-l2a",
                                "collection_b": "sentinel-1-grd"}}))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        a, b = data.get("collection_a"), data.get("collection_b")
        if not a or not b:
            raise _fail("both 'collection_a' and 'collection_b' are required")
        if a == b:
            raise _fail("collection_a and collection_b must differ")
        start, end = data.get("start"), data.get("end")

        fa, fb = _load(a, start, end, aoi), _load(b, start, end, aoi)
        to_m, from_m = _equal_area(aoi)
        aoi_m = shp_transform(to_m, aoi)

        def union_of(fps):
            gs = [shp_transform(to_m, f["geom"]).intersection(aoi_m) for f in fps]
            gs = [g for g in gs if not g.is_empty]
            return unary_union(gs) if gs else None

        ua, ub = union_of(fa), union_of(fb)
        if ua is None or ub is None:
            missing = a if ua is None else b
            return "application/json", {
                "id": "multi-sensor-overlap",
                "aoi_area_km2": _km2(aoi_m),
                "collection_a": a, "collection_b": b,
                "overlap_area_km2": 0.0, "overlap_fraction_of_aoi": 0.0,
                "message": f"No footprints for {missing!r} match these filters, "
                           "so there is no co-coverage.",
                "overlap_geometry": None,
                "provenance": _provenance(len(fa) + len(fb), None, start, end),
            }

        inter = ua.intersection(ub)
        return "application/json", {
            "id": "multi-sensor-overlap",
            "aoi_area_km2": _km2(aoi_m),
            "collection_a": a, "collection_b": b,
            "scenes_a": len(fa), "scenes_b": len(fb),
            "coverage_a_km2": _km2(ua), "coverage_b_km2": _km2(ub),
            "overlap_area_km2": _km2(inter),
            "overlap_fraction_of_aoi": round(inter.area / aoi_m.area, 5)
            if aoi_m.area else 0.0,
            "overlap_fraction_of_a": round(inter.area / ua.area, 5) if ua.area else 0.0,
            "overlap_fraction_of_b": round(inter.area / ub.area, 5) if ub.area else 0.0,
            "co_covered": not inter.is_empty,
            "overlap_geometry": mapping(shp_transform(from_m, inter))
            if not inter.is_empty else None,
            "provenance": _provenance(len(fa) + len(fb), None, start, end),
        }

    def __repr__(self):
        return "<MultiSensorOverlapProcessor>"


# ===========================================================================
class RevisitDensityProcessor(BaseProcessor):
    """How often is each part of my AOI observed?"""

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "revisit-density", "Acquisition density grid",
            "Lays a regular grid over the area of interest and counts how many "
            "acquisitions intersect each cell, returning the grid as a GeoJSON "
            "FeatureCollection ready to render as a heatmap. Revisit is uneven "
            "across any AOI because swaths overlap, and nothing in the stack "
            "will show you that: the list a search returns has no spatial "
            "distribution in it.",
            extra={"cell_size_km": {
                "title": "Grid cell size (km)",
                "description": "Side length of each square cell, in kilometres.",
                "schema": {"type": "number", "minimum": 0.5, "maximum": 200,
                           "default": 10},
                "minOccurs": 0, "maxOccurs": 1}},
            keywords=["revisit", "density", "heatmap", "grid"]))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        coll = data.get("collection")
        start, end = data.get("start"), data.get("end")
        cell_km = float(data.get("cell_size_km") or 10)
        if not 0.5 <= cell_km <= 200:
            raise _fail("cell_size_km must be between 0.5 and 200")

        fps = _load(coll, start, end, aoi)
        to_m, from_m = _equal_area(aoi)
        aoi_m = shp_transform(to_m, aoi)
        minx, miny, maxx, maxy = aoi_m.bounds
        step = cell_km * 1000.0

        nx = max(1, int((maxx - minx) // step) + 1)
        ny = max(1, int((maxy - miny) // step) + 1)
        if nx * ny > MAX_GRID_CELLS:
            raise _fail(f"a {cell_km} km grid over this AOI is {nx}x{ny} = "
                        f"{nx*ny} cells, above the {MAX_GRID_CELLS} limit; "
                        "use a larger cell_size_km or a smaller AOI")

        geoms = [shp_transform(to_m, f["geom"]) for f in fps]
        cells, counts = [], []
        for i in range(nx):
            for j in range(ny):
                cell = box(minx + i * step, miny + j * step,
                           min(minx + (i + 1) * step, maxx),
                           min(miny + (j + 1) * step, maxy))
                cell = cell.intersection(aoi_m)
                if cell.is_empty:
                    continue
                n = sum(1 for g in geoms if g.intersects(cell))
                counts.append(n)
                cells.append({
                    "type": "Feature",
                    "geometry": mapping(shp_transform(from_m, cell)),
                    "properties": {"acquisitions": n,
                                   "cell_area_km2": _km2(cell),
                                   "row": j, "col": i},
                })

        if not cells:
            raise _fail("the grid produced no cells inside the AOI")

        nonzero = [c for c in counts if c > 0]
        return "application/json", {
            "type": "FeatureCollection",
            "features": cells,
            "summary": {
                "id": "revisit-density",
                "cell_size_km": cell_km,
                "grid": f"{nx}x{ny}",
                "cells_in_aoi": len(cells),
                "aoi_area_km2": _km2(aoi_m),
                "acquisitions_total": len(fps),
                "min_per_cell": min(counts),
                "max_per_cell": max(counts),
                "mean_per_cell": round(sum(counts) / len(counts), 3),
                "cells_never_observed": sum(1 for c in counts if c == 0),
                "cells_observed": len(nonzero),
                "provenance": _provenance(len(fps), coll, start, end),
            },
        }

    def __repr__(self):
        return "<RevisitDensityProcessor>"

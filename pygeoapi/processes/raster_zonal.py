"""
OGC API - Processes: raster operations over the area of interest.

The footprint processes in catalogue_spatial.py answer "which scenes do I
need". These answer "and what is actually inside them" - they read pixels.

Together they are the point of the service: footprint geometry decides what to
fetch, raster values describe what is there, and the two meet in
scene-raster-profile, which reports the raster statistics underneath each
candidate scene. That join is only possible because the service holds both the
footprints and the pixels, which is exactly what Bhoonidhi's catalogue does not
do with the geometry it already stores.

Operations used here are raster-vector overlay (mask a raster by a polygon),
reclassification into bands, and zonal aggregation.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from pyproj import CRS, Transformer
from rasterio.mask import mask as rio_mask
from shapely.geometry import mapping, shape, box
from shapely.ops import transform as shp_transform

LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent
RASTER = Path(os.environ.get("RASTER_FILE", ROOT / "data" / "dem.tif"))
FOOTPRINTS = Path(os.environ.get("FOOTPRINTS_FILE",
                                 ROOT / "data" / "footprints.geojson"))

# Reading an unbounded window out of a COG will exhaust memory; cap it.
MAX_PIXELS = 40_000_000


def _fail(msg: str) -> ProcessorExecuteError:
    return ProcessorExecuteError(msg)


def _aoi(raw):
    """Accept a GeoJSON geometry, Feature, FeatureCollection, or a bbox."""
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
        return shape(feats[0]["geometry"])
    if t == "Feature":
        return shape(raw["geometry"])
    if t in ("Polygon", "MultiPolygon"):
        return shape(raw)
    raise _fail(f"unsupported 'aoi' geometry type {t!r}")


def _clip(geom):
    """Mask the raster by a polygon. Returns (values, pixel_area_km2, meta).

    This is the raster-vector overlay: everything outside the polygon becomes
    nodata, and only the inside is read.
    """
    if not RASTER.exists():
        raise _fail(f"no raster at {RASTER.name}. See the README for how the "
                    "DEM is staged.")
    with rasterio.open(RASTER) as ds:
        if not shape(mapping(geom)).intersects(box(*ds.bounds)):
            raise _fail(f"the AOI lies outside the raster extent {tuple(round(b,3) for b in ds.bounds)}")
        try:
            arr, _ = rio_mask(ds, [mapping(geom)], crop=True, filled=True,
                              nodata=ds.nodata if ds.nodata is not None else -9999)
        except ValueError as e:
            raise _fail(f"could not clip the raster to the AOI: {e}")
        if arr.size > MAX_PIXELS:
            raise _fail(f"the AOI covers {arr.size} pixels, above the "
                        f"{MAX_PIXELS} limit; request a smaller area")
        nodata = ds.nodata if ds.nodata is not None else -9999
        band = arr[0].astype("float64")
        vals = band[(band != nodata) & np.isfinite(band)]

        # Pixel area in km2, via a local equal-area projection.
        c = geom.centroid
        laea = CRS.from_proj4(
            f"+proj=laea +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs")
        to_m = Transformer.from_crs(CRS.from_epsg(4326), laea, always_xy=True).transform
        # one pixel as a polygon, measured in metres
        px = box(0, 0, abs(ds.transform.a), abs(ds.transform.e))
        px_geo = box(c.x, c.y, c.x + abs(ds.transform.a), c.y + abs(ds.transform.e))
        px_km2 = shp_transform(to_m, px_geo).area / 1e6
        meta = {"crs": str(ds.crs), "nodata": nodata,
                "pixel_size_deg": [abs(ds.transform.a), abs(ds.transform.e)],
                "window_pixels": int(arr[0].size)}
    return vals, px_km2, meta


def _stats(vals: np.ndarray, px_km2: float) -> dict:
    if vals.size == 0:
        raise _fail("the AOI contains no valid raster pixels (all nodata)")
    return {
        "valid_pixels": int(vals.size),
        "area_km2": round(float(vals.size) * px_km2, 4),
        "min": round(float(vals.min()), 3),
        "max": round(float(vals.max()), 3),
        "mean": round(float(vals.mean()), 3),
        "median": round(float(np.median(vals)), 3),
        "stddev": round(float(vals.std()), 3),
        "range": round(float(vals.max() - vals.min()), 3),
        "percentiles": {str(p): round(float(np.percentile(vals, p)), 3)
                        for p in (5, 25, 50, 75, 95)},
    }


def _raster_provenance(meta: dict) -> dict:
    return {
        "raster": RASTER.name,
        "raster_crs": meta.get("crs"),
        "pixel_size_deg": meta.get("pixel_size_deg"),
        "is_substitute_for_cartodem": True,
        "substitute_note": (
            "Elevation is Copernicus DEM GLO-30, used as a labelled stand-in "
            "because CartoDEM download requires an authenticated Bhoonidhi "
            "account. The operations are unchanged by the substitution."),
        "area_crs": "Lambert Azimuthal Equal-Area centred on the AOI "
                    "(areas in km2, not degrees)",
        "computed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


_AOI_IN = {
    "title": "Area of interest",
    "description": "GeoJSON Polygon/MultiPolygon/Feature, or a bbox as "
                   "[minLon, minLat, maxLon, maxLat], in EPSG:4326.",
    "schema": {"oneOf": [{"type": "object"},
                         {"type": "array", "minItems": 4, "maxItems": 4,
                          "items": {"type": "number"}}]},
    "minOccurs": 1, "maxOccurs": 1,
}
_JSON_OUT = {"result": {"title": "Result",
                        "description": "Raster statistics for the area",
                        "schema": {"type": "object",
                                   "contentMediaType": "application/json"}}}
_EXAMPLE = [75.5, 13.5, 75.7, 13.7]


def _meta(pid, title, desc, extra=None, keywords=None, example=None):
    inputs = {"aoi": dict(_AOI_IN)}
    if extra:
        inputs.update(extra)
    return {
        "version": "1.0.0", "id": pid,
        "title": {"en": title}, "description": {"en": desc},
        "jobControlOptions": ["sync-execute", "async-execute"],
        "keywords": keywords or ["raster", "zonal statistics", "overlay"],
        "links": [{"type": "text/html", "rel": "about",
                   "title": "Project repository", "href": "https://github.com/",
                   "hreflang": "en-US"}],
        "inputs": inputs, "outputs": dict(_JSON_OUT),
        "example": example or {"inputs": {"aoi": _EXAMPLE}},
    }


# ===========================================================================
class ZonalStatisticsProcessor(BaseProcessor):
    """Classic raster-vector overlay: polygon in, pixel statistics out."""

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "zonal-statistics", "Zonal statistics over an area",
            "Masks the raster by the supplied polygon and aggregates the pixels "
            "inside it: count, area, min, max, mean, median, standard deviation "
            "and percentiles, plus an optional histogram. This is raster-vector "
            "overlay - the operation that turns 'here is a raster' into 'here "
            "is the answer for my area'. Bhoonidhi will hand over the whole "
            "product; it will not aggregate a single pixel of it.",
            extra={"bins": {
                "title": "Histogram bins",
                "description": "Number of value bands in the returned "
                               "histogram. 0 omits it.",
                "schema": {"type": "integer", "minimum": 0, "maximum": 50,
                           "default": 10},
                "minOccurs": 0, "maxOccurs": 1}},
            keywords=["zonal statistics", "raster", "overlay", "aggregation"]))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        bins = int(data.get("bins") if data.get("bins") is not None else 10)
        if not 0 <= bins <= 50:
            raise _fail("bins must be between 0 and 50")

        vals, px_km2, meta = _clip(aoi)
        out = {"id": "zonal-statistics",
               "statistics": _stats(vals, px_km2)}

        if bins:
            counts, edges = np.histogram(vals, bins=bins)
            cum = 0
            hist = []
            for i in range(len(counts)):
                cum += int(counts[i])
                hist.append({
                    "band": [round(float(edges[i]), 2), round(float(edges[i + 1]), 2)],
                    "pixels": int(counts[i]),
                    "area_km2": round(float(counts[i]) * px_km2, 4),
                    "fraction": round(float(counts[i]) / vals.size, 5),
                    "cumulative_fraction": round(cum / vals.size, 5),
                })
            out["histogram"] = hist

        out["aoi"] = mapping(aoi)
        out["provenance"] = _raster_provenance(meta)
        return "application/json", out

    def __repr__(self):
        return "<ZonalStatisticsProcessor>"


# ===========================================================================
class SceneRasterProfileProcessor(BaseProcessor):
    """The join: raster statistics underneath each candidate scene footprint.

    This is the operation that needs both halves of the service. For every
    scene whose footprint touches the area of interest, it clips the raster to
    that footprint and reports what is underneath. Choosing between candidate
    scenes on what they actually contain - rather than on whether they
    intersect a box - is impossible from a catalogue that only does intersects.
    """

    def __init__(self, processor_def):
        super().__init__(processor_def, _meta(
            "scene-raster-profile", "Raster profile under each scene footprint",
            "For every acquisition footprint intersecting the area of interest, "
            "clips the raster to that footprint and reports the statistics "
            "underneath it, ranked. Joins the footprint geometry to the pixel "
            "values, so scenes can be compared on what they actually cover "
            "rather than merely on whether they intersect a bounding box.",
            extra={"collection": {
                "title": "Collection",
                "description": "Restrict to one collection id.",
                "schema": {"type": "string"}, "minOccurs": 0, "maxOccurs": 1},
                "limit": {
                "title": "Maximum scenes",
                "description": "How many footprints to profile.",
                "schema": {"type": "integer", "minimum": 1, "maximum": 50,
                           "default": 10},
                "minOccurs": 0, "maxOccurs": 1}},
            keywords=["raster", "footprints", "overlay", "scene selection"]))

    def execute(self, data, outputs=None):
        aoi = _aoi(data.get("aoi"))
        coll = data.get("collection")
        limit = int(data.get("limit") or 10)
        if not 1 <= limit <= 50:
            raise _fail("limit must be between 1 and 50")

        if not FOOTPRINTS.exists():
            raise _fail("no footprint store. Run scripts/fetch_footprints.py.")
        fc = json.loads(FOOTPRINTS.read_text())

        profiled, skipped = [], 0
        for f in fc.get("features", []):
            if len(profiled) >= limit:
                break
            p = f.get("properties", {})
            if coll and p.get("collection") != coll:
                continue
            try:
                g = shape(f["geometry"])
            except Exception:
                continue
            if g.is_empty or not g.is_valid:
                g = g.buffer(0)
            clip_geom = g.intersection(aoi)
            if clip_geom.is_empty:
                continue
            try:
                vals, px_km2, meta = _clip(clip_geom)
                st = _stats(vals, px_km2)
            except ProcessorExecuteError:
                skipped += 1
                continue
            profiled.append({
                "item_id": f.get("id"),
                "collection": p.get("collection"),
                "datetime": p.get("datetime"),
                "cloud_cover": p.get("cloud_cover"),
                "overlap_with_aoi_km2": st["area_km2"],
                "raster_statistics": {k: st[k] for k in
                                      ("min", "max", "mean", "median",
                                       "stddev", "range", "valid_pixels")},
            })

        if not profiled:
            raise _fail("no footprints with valid raster data intersect the AOI")

        profiled.sort(key=lambda d: -d["overlap_with_aoi_km2"])
        means = [d["raster_statistics"]["mean"] for d in profiled]
        with rasterio.open(RASTER) as ds:
            meta = {"crs": str(ds.crs),
                    "pixel_size_deg": [abs(ds.transform.a), abs(ds.transform.e)]}

        return "application/json", {
            "id": "scene-raster-profile",
            "scenes_profiled": len(profiled),
            "scenes_skipped_no_data": skipped,
            "across_scenes": {
                "mean_of_means": round(float(np.mean(means)), 3),
                "lowest_mean": round(float(np.min(means)), 3),
                "highest_mean": round(float(np.max(means)), 3),
            },
            "scenes": profiled,
            "provenance": _raster_provenance(meta),
        }

    def __repr__(self):
        return "<SceneRasterProfileProcessor>"

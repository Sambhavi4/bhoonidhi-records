"""
Correctness tests for the raster operations.

These processes read pixels, so the tests check the arithmetic of the
raster-vector overlay: that masking by a polygon actually restricts what is
read, that statistics are internally consistent, that histogram bands account
for every pixel, and that areas come out in square kilometres rather than
square degrees.
"""
from __future__ import annotations

import pytest
import requests

AOI = [75.5, 13.5, 75.7, 13.7]
SMALL = [75.55, 13.55, 75.60, 13.60]
OUTSIDE = [2.2, 48.8, 2.4, 48.9]        # Paris: outside the raster
OPTICAL = "sentinel-2-l2a"


def _run(base, pid, inputs, timeout=600):
    r = requests.post(f"{base}/processes/{pid}/execution",
                      json={"inputs": inputs}, timeout=timeout)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    return r.json()


class TestZonalStatistics:

    def test_returns_statistics(self, base):
        d = _run(base, "zonal-statistics", {"aoi": AOI})
        s = d["statistics"]
        for k in ("valid_pixels", "area_km2", "min", "max", "mean",
                  "median", "stddev", "range", "percentiles"):
            assert k in s, f"missing {k}"
        assert s["valid_pixels"] > 0

    def test_statistics_are_internally_consistent(self, base):
        s = _run(base, "zonal-statistics", {"aoi": AOI})["statistics"]
        assert s["min"] <= s["median"] <= s["max"]
        assert s["min"] <= s["mean"] <= s["max"]
        assert s["range"] == pytest.approx(s["max"] - s["min"], abs=0.01)
        assert s["stddev"] >= 0
        p = s["percentiles"]
        ordered = [p["5"], p["25"], p["50"], p["75"], p["95"]]
        assert ordered == sorted(ordered), f"percentiles not monotonic: {ordered}"
        assert p["50"] == pytest.approx(s["median"], abs=0.01)

    def test_values_are_plausible_elevations(self, base):
        """The AOI is on the Western Ghats; metres, not degrees or nonsense."""
        s = _run(base, "zonal-statistics", {"aoi": AOI})["statistics"]
        assert 0 < s["min"] < 2000, f"min elevation {s['min']}"
        assert 100 < s["max"] < 3000, f"max elevation {s['max']}"

    def test_areas_are_metric(self, base):
        """A 0.2 x 0.2 degree AOI is ~500 km2. In degrees it would be 0.04."""
        s = _run(base, "zonal-statistics", {"aoi": AOI})["statistics"]
        assert 100 < s["area_km2"] < 2000, \
            f"area_km2 is {s['area_km2']} - looks unprojected"

    def test_masking_actually_restricts_what_is_read(self, base):
        """A smaller polygon must read fewer pixels - proof the mask works."""
        big = _run(base, "zonal-statistics", {"aoi": AOI})["statistics"]
        small = _run(base, "zonal-statistics", {"aoi": SMALL})["statistics"]
        assert small["valid_pixels"] < big["valid_pixels"]
        assert small["area_km2"] < big["area_km2"]

    def test_histogram_accounts_for_every_pixel(self, base):
        d = _run(base, "zonal-statistics", {"aoi": AOI, "bins": 8})
        s, h = d["statistics"], d["histogram"]
        assert len(h) == 8
        assert sum(b["pixels"] for b in h) == s["valid_pixels"], \
            "histogram bands do not sum to the pixel count"
        assert sum(b["area_km2"] for b in h) == pytest.approx(s["area_km2"], rel=0.01)
        cum = [b["cumulative_fraction"] for b in h]
        assert cum == sorted(cum), "cumulative fraction not monotonic"
        assert cum[-1] == pytest.approx(1.0, abs=0.001)

    def test_histogram_spans_the_value_range(self, base):
        d = _run(base, "zonal-statistics", {"aoi": AOI, "bins": 5})
        s, h = d["statistics"], d["histogram"]
        assert h[0]["band"][0] == pytest.approx(s["min"], abs=0.02)
        assert h[-1]["band"][1] == pytest.approx(s["max"], abs=0.02)

    def test_bins_zero_omits_histogram(self, base):
        d = _run(base, "zonal-statistics", {"aoi": AOI, "bins": 0})
        assert "histogram" not in d

    def test_geojson_polygon_accepted(self, base):
        poly = {"type": "Polygon", "coordinates": [[
            [75.55, 13.55], [75.65, 13.55], [75.65, 13.65],
            [75.55, 13.65], [75.55, 13.55]]]}
        d = _run(base, "zonal-statistics", {"aoi": poly})
        assert d["statistics"]["valid_pixels"] > 0

    def test_aoi_outside_the_raster_is_rejected(self, base):
        r = requests.post(f"{base}/processes/zonal-statistics/execution",
                          json={"inputs": {"aoi": OUTSIDE}}, timeout=120)
        assert r.status_code >= 400, "an AOI outside the raster was accepted"

    def test_substitution_is_declared(self, base):
        d = _run(base, "zonal-statistics", {"aoi": AOI})
        p = d["provenance"]
        assert p.get("is_substitute_for_cartodem") is True, \
            "the response does not declare that the DEM is a stand-in"
        assert "Equal-Area" in p.get("area_crs", "")

    def test_bad_bins_rejected(self, base):
        r = requests.post(f"{base}/processes/zonal-statistics/execution",
                          json={"inputs": {"aoi": AOI, "bins": 999}}, timeout=120)
        assert r.status_code >= 400


class TestSceneRasterProfile:
    """The join between footprint geometry and pixel values."""

    def test_profiles_scenes(self, base):
        d = _run(base, "scene-raster-profile",
                 {"aoi": [75.4, 13.4, 75.8, 13.8], "collection": OPTICAL,
                  "limit": 5})
        assert d["scenes_profiled"] > 0
        assert len(d["scenes"]) == d["scenes_profiled"]

    def test_each_scene_has_geometry_and_pixels(self, base):
        d = _run(base, "scene-raster-profile",
                 {"aoi": [75.4, 13.4, 75.8, 13.8], "collection": OPTICAL,
                  "limit": 5})
        for s in d["scenes"]:
            assert s["overlap_with_aoi_km2"] > 0, "a scene has no overlap area"
            r = s["raster_statistics"]
            assert r["valid_pixels"] > 0, "a scene profiled zero pixels"
            assert r["min"] <= r["mean"] <= r["max"]

    def test_scenes_ranked_by_overlap(self, base):
        d = _run(base, "scene-raster-profile",
                 {"aoi": [75.4, 13.4, 75.8, 13.8], "collection": OPTICAL,
                  "limit": 8})
        areas = [s["overlap_with_aoi_km2"] for s in d["scenes"]]
        assert areas == sorted(areas, reverse=True), f"not ranked: {areas}"

    def test_across_scenes_summary_is_consistent(self, base):
        d = _run(base, "scene-raster-profile",
                 {"aoi": [75.4, 13.4, 75.8, 13.8], "collection": OPTICAL,
                  "limit": 6})
        means = [s["raster_statistics"]["mean"] for s in d["scenes"]]
        a = d["across_scenes"]
        assert a["lowest_mean"] == pytest.approx(min(means), abs=0.01)
        assert a["highest_mean"] == pytest.approx(max(means), abs=0.01)
        assert min(means) <= a["mean_of_means"] <= max(means)

    def test_limit_is_honoured(self, base):
        d = _run(base, "scene-raster-profile",
                 {"aoi": [75.4, 13.4, 75.8, 13.8], "collection": OPTICAL,
                  "limit": 2})
        assert d["scenes_profiled"] <= 2

    def test_bad_limit_rejected(self, base):
        r = requests.post(f"{base}/processes/scene-raster-profile/execution",
                          json={"inputs": {"aoi": AOI, "limit": 500}}, timeout=120)
        assert r.status_code >= 400

"""
OGC API - Processes Part 1: Core compliance tests, plus correctness tests for
the spatial operations themselves.

Mapped onto OGC 18-062r2. The processes do spatial set algebra over
acquisition footprints - union, intersection, difference, area and a set-cover
optimisation - so these tests check the geometry and the arithmetic, not just
that a response came back.

Run:  ./scripts/run_tests.sh
"""
from __future__ import annotations

import time

import pytest
import requests

AOI = [75.3, 13.2, 75.8, 13.9]
BIG_AOI = [75.1, 13.0, 76.0, 14.1]
OPTICAL = "sentinel-2-l2a"
RADAR = "sentinel-1-grd"

PROCESSES = {"aoi-coverage", "minimal-scene-set",
             "multi-sensor-overlap", "revisit-density"}


def _run(base, pid, inputs, timeout=300):
    r = requests.post(f"{base}/processes/{pid}/execution",
                      json={"inputs": inputs}, timeout=timeout)
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    return r.json()


# ===========================================================================
# Processes Core
# ===========================================================================
class TestProcessesCore:

    def test_conformance_declares_processes_core(self, get):
        d = get("/conformance").json()
        classes = d.get("conformsTo", [])
        assert any("ogcapi-processes-1/1.0/conf/core" in c for c in classes), \
            f"Processes Core not declared; got {classes}"

    def test_process_list(self, get):
        d = get("/processes").json()
        ids = {p["id"] for p in d["processes"]}
        assert PROCESSES <= ids, f"missing {PROCESSES - ids}"

    @pytest.mark.parametrize("pid", sorted(PROCESSES))
    def test_process_description(self, get, pid):
        d = get(f"/processes/{pid}").json()
        assert d["id"] == pid
        assert d.get("inputs"), f"{pid} declares no inputs"
        assert d.get("outputs"), f"{pid} declares no outputs"
        assert "aoi" in d["inputs"], f"{pid} has no aoi input"
        for name, spec in d["inputs"].items():
            assert "schema" in spec, f"{pid} input {name} has no schema"

    @pytest.mark.parametrize("pid", sorted(PROCESSES))
    def test_job_control_options(self, get, pid):
        d = get(f"/processes/{pid}").json()
        opts = d.get("jobControlOptions", [])
        assert "sync-execute" in opts or "async-execute" in opts

    def test_unknown_process_is_404(self, get):
        assert get("/processes/no-such-process").status_code == 404

    def test_async_returns_201_with_location(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          headers={"Prefer": "respond-async"},
                          json={"inputs": {"aoi": AOI}}, timeout=120)
        assert r.status_code == 201, f"HTTP {r.status_code}: {r.text[:200]}"
        assert r.headers.get("Location"), "no Location header"
        assert r.json().get("jobID"), "no jobID"

    def test_job_lifecycle(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          headers={"Prefer": "respond-async"},
                          json={"inputs": {"aoi": AOI}}, timeout=120)
        job = r.json()["jobID"]
        status = None
        for _ in range(60):
            s = requests.get(f"{base}/jobs/{job}", params={"f": "json"},
                             timeout=60).json()
            status = s.get("status")
            assert status in ("accepted", "running", "successful", "failed",
                              "dismissed"), f"invalid status {status!r}"
            if status in ("successful", "failed", "dismissed"):
                break
            time.sleep(1)
        assert status == "successful", f"job ended as {status!r}"
        res = requests.get(f"{base}/jobs/{job}/results",
                           params={"f": "json"}, timeout=120)
        assert res.status_code == 200
        assert res.json(), "job results empty"

    def test_unknown_job_is_404(self, get):
        r = get("/jobs/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404


# ===========================================================================
# aoi-coverage: union, difference, area
# ===========================================================================
class TestAoiCoverage:

    def test_coverage_is_internally_consistent(self, base):
        d = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        assert d["aoi_area_km2"] > 0
        # covered + gap must reconstruct the AOI, within the sliver threshold
        total = d["covered_area_km2"] + d["gap_area_km2"]
        assert total == pytest.approx(d["aoi_area_km2"], rel=0.02), \
            f"covered {d['covered_area_km2']} + gap {d['gap_area_km2']} != AOI {d['aoi_area_km2']}"
        assert 0.0 <= d["coverage_fraction"] <= 1.0
        assert d["coverage_percent"] == pytest.approx(
            d["coverage_fraction"] * 100, abs=0.01)

    def test_gap_reporting_agrees_with_fully_covered(self, base):
        """fully_covered and a non-null gaps geometry must never both be true."""
        d = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        if d["fully_covered"]:
            assert d["gaps"] is None, "fully covered but gaps geometry returned"
            assert d["gap_area_km2"] == 0.0
        else:
            assert d["gaps"] is not None, "not fully covered but no gaps geometry"

    def test_areas_are_metric_not_degrees(self, base):
        """The AOI is ~0.5 x 0.7 degrees. In degrees that is ~0.35; in km2 it is
        a few thousand. A wrong CRS shows up immediately here."""
        d = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        assert 1_000 < d["aoi_area_km2"] < 10_000, \
            f"aoi_area_km2 is {d['aoi_area_km2']} - areas look unprojected"

    def test_empty_result_keeps_the_same_shape(self, base):
        """A client that works with scenes must not break when there are none."""
        full = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        empty = _run(base, "aoi-coverage",
                     {"aoi": AOI, "collection": OPTICAL,
                      "start": "1990-01-01T00:00:00Z",
                      "end": "1990-01-02T00:00:00Z"})
        for k in ("aoi_area_km2", "covered_area_km2", "coverage_fraction",
                  "coverage_percent", "gap_area_km2", "scene_count",
                  "fully_covered", "gaps", "scenes", "provenance"):
            assert k in empty, f"empty result is missing {k}"
            assert k in full, f"populated result is missing {k}"
        assert empty["scene_count"] == 0
        assert empty["coverage_fraction"] == 0.0
        assert empty["gap_area_km2"] == pytest.approx(empty["aoi_area_km2"], rel=0.01)

    def test_per_scene_overlap_never_exceeds_the_aoi(self, base):
        d = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        for s in d["scenes"]:
            assert 0 < s["aoi_overlap_km2"] <= d["aoi_area_km2"] * 1.01
            assert 0 < s["aoi_overlap_fraction"] <= 1.0001

    def test_smaller_aoi_covers_less_absolute_area(self, base):
        big = _run(base, "aoi-coverage", {"aoi": BIG_AOI, "collection": OPTICAL})
        small = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        assert small["aoi_area_km2"] < big["aoi_area_km2"]
        assert small["covered_area_km2"] <= big["covered_area_km2"] * 1.01

    def test_provenance_declares_the_source(self, base):
        d = _run(base, "aoi-coverage", {"aoi": AOI, "collection": OPTICAL})
        p = d["provenance"]
        assert p.get("footprint_source"), "no footprint source recorded"
        assert "is_substitute_for_bhoonidhi" in p, \
            "the result does not say whether the footprints are Bhoonidhi's"
        assert "Equal-Area" in p.get("area_crs", ""), \
            "the result does not declare the area CRS"


# ===========================================================================
# minimal-scene-set: greedy set cover
# ===========================================================================
class TestMinimalSceneSet:

    def test_selects_fewer_than_it_considers(self, base):
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.99})
        assert d["candidates_considered"] > 0
        assert d["scenes_selected"] <= d["candidates_considered"]
        assert d["scenes_avoided"] == d["candidates_considered"] - d["scenes_selected"]

    def test_cumulative_coverage_is_monotonic(self, base):
        """Each greedy step must add area; coverage can never go down."""
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.99})
        cum = [s["cumulative_coverage_fraction"] for s in d["selection"]]
        assert cum == sorted(cum), f"cumulative coverage not monotonic: {cum}"
        for s in d["selection"]:
            assert s["new_area_km2"] > 0, "a selected scene added no new area"

    def test_greedy_takes_the_largest_gain_first(self, base):
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.99})
        gains = [s["new_area_km2"] for s in d["selection"]]
        if len(gains) > 1:
            assert gains[0] == max(gains), \
                f"first pick {gains[0]} is not the largest gain {max(gains)}"

    def test_order_is_sequential(self, base):
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL})
        assert [s["order"] for s in d["selection"]] == \
            list(range(1, len(d["selection"]) + 1))

    def test_target_is_respected(self, base):
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.5})
        if d["target_met"]:
            assert d["achieved_fraction"] >= 0.5

    def test_lower_target_needs_no_more_scenes(self, base):
        lo = _run(base, "minimal-scene-set",
                  {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.5})
        hi = _run(base, "minimal-scene-set",
                  {"aoi": AOI, "collection": OPTICAL, "target_fraction": 0.99})
        assert lo["scenes_selected"] <= hi["scenes_selected"]

    def test_max_scenes_cap(self, base):
        d = _run(base, "minimal-scene-set",
                 {"aoi": AOI, "collection": OPTICAL, "max_scenes": 1})
        assert d["scenes_selected"] <= 1

    def test_algorithm_is_declared(self, base):
        d = _run(base, "minimal-scene-set", {"aoi": AOI, "collection": OPTICAL})
        assert "greedy" in d.get("algorithm", "").lower(), \
            "the result does not say which algorithm produced it"


# ===========================================================================
# multi-sensor-overlap: intersection
# ===========================================================================
class TestMultiSensorOverlap:

    def test_optical_radar_overlap(self, base):
        d = _run(base, "multi-sensor-overlap",
                 {"aoi": BIG_AOI, "collection_a": OPTICAL, "collection_b": RADAR})
        assert d["collection_a"] == OPTICAL
        assert d["collection_b"] == RADAR
        assert d["overlap_area_km2"] >= 0

    def test_overlap_never_exceeds_either_input(self, base):
        """An intersection cannot be larger than either operand."""
        d = _run(base, "multi-sensor-overlap",
                 {"aoi": BIG_AOI, "collection_a": OPTICAL, "collection_b": RADAR})
        if d.get("co_covered"):
            assert d["overlap_area_km2"] <= d["coverage_a_km2"] * 1.01
            assert d["overlap_area_km2"] <= d["coverage_b_km2"] * 1.01
            assert d["overlap_area_km2"] <= d["aoi_area_km2"] * 1.01
            for k in ("overlap_fraction_of_aoi", "overlap_fraction_of_a",
                      "overlap_fraction_of_b"):
                assert 0 <= d[k] <= 1.0001, f"{k} = {d[k]}"

    def test_identical_collections_rejected(self, base):
        r = requests.post(f"{base}/processes/multi-sensor-overlap/execution",
                          json={"inputs": {"aoi": AOI, "collection_a": OPTICAL,
                                           "collection_b": OPTICAL}}, timeout=120)
        assert r.status_code >= 400, "comparing a collection with itself was accepted"

    def test_missing_collection_rejected(self, base):
        r = requests.post(f"{base}/processes/multi-sensor-overlap/execution",
                          json={"inputs": {"aoi": AOI, "collection_a": OPTICAL}},
                          timeout=120)
        assert r.status_code >= 400, "a missing collection_b was accepted"


# ===========================================================================
# revisit-density: gridding
# ===========================================================================
class TestRevisitDensity:

    def test_returns_a_grid(self, base):
        d = _run(base, "revisit-density",
                 {"aoi": AOI, "collection": OPTICAL, "cell_size_km": 10})
        assert d["type"] == "FeatureCollection"
        assert d["features"], "no grid cells returned"
        for f in d["features"]:
            assert f["geometry"]["type"] in ("Polygon", "MultiPolygon")
            assert f["properties"]["acquisitions"] >= 0

    def test_summary_matches_the_cells(self, base):
        d = _run(base, "revisit-density",
                 {"aoi": AOI, "collection": OPTICAL, "cell_size_km": 10})
        s = d["summary"]
        counts = [f["properties"]["acquisitions"] for f in d["features"]]
        assert s["cells_in_aoi"] == len(d["features"])
        assert s["min_per_cell"] == min(counts)
        assert s["max_per_cell"] == max(counts)
        assert s["mean_per_cell"] == pytest.approx(sum(counts) / len(counts), abs=0.01)
        assert s["cells_never_observed"] == sum(1 for c in counts if c == 0)

    def test_cell_areas_sum_to_the_aoi(self, base):
        d = _run(base, "revisit-density",
                 {"aoi": AOI, "collection": OPTICAL, "cell_size_km": 10})
        total = sum(f["properties"]["cell_area_km2"] for f in d["features"])
        assert total == pytest.approx(d["summary"]["aoi_area_km2"], rel=0.02), \
            f"cells sum to {total}, AOI is {d['summary']['aoi_area_km2']}"

    def test_smaller_cells_give_more_cells(self, base):
        coarse = _run(base, "revisit-density",
                      {"aoi": AOI, "collection": OPTICAL, "cell_size_km": 20})
        fine = _run(base, "revisit-density",
                    {"aoi": AOI, "collection": OPTICAL, "cell_size_km": 10})
        assert fine["summary"]["cells_in_aoi"] > coarse["summary"]["cells_in_aoi"]

    def test_oversized_grid_is_rejected(self, base):
        r = requests.post(f"{base}/processes/revisit-density/execution",
                          json={"inputs": {"aoi": BIG_AOI, "cell_size_km": 0.5}},
                          timeout=180)
        assert r.status_code >= 400, "an unbounded grid request was accepted"


# ===========================================================================
# input validation, shared across the processes
# ===========================================================================
class TestInputValidation:

    def test_missing_aoi_rejected(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          json={"inputs": {}}, timeout=120)
        assert r.status_code >= 400

    def test_malformed_bbox_rejected(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          json={"inputs": {"aoi": [1, 2]}}, timeout=120)
        assert r.status_code >= 400

    def test_inverted_bbox_rejected(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          json={"inputs": {"aoi": [76.0, 14.0, 75.0, 13.0]}},
                          timeout=120)
        assert r.status_code >= 400

    def test_bad_geometry_type_rejected(self, base):
        r = requests.post(f"{base}/processes/aoi-coverage/execution",
                          json={"inputs": {"aoi": {"type": "Point",
                                                   "coordinates": [75.5, 13.5]}}},
                          timeout=120)
        assert r.status_code >= 400

    def test_geojson_polygon_aoi_accepted(self, base):
        """A GeoJSON polygon must work, not just a bbox."""
        poly = {"type": "Polygon", "coordinates": [[
            [75.4, 13.3], [75.7, 13.3], [75.7, 13.7], [75.4, 13.7], [75.4, 13.3]]]}
        d = _run(base, "aoi-coverage", {"aoi": poly, "collection": OPTICAL})
        assert d["aoi_area_km2"] > 0

    def test_feature_aoi_accepted(self, base):
        feat = {"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[
                [75.4, 13.3], [75.7, 13.3], [75.7, 13.7], [75.4, 13.7], [75.4, 13.3]]]}}
        d = _run(base, "aoi-coverage", {"aoi": feat, "collection": OPTICAL})
        assert d["aoi_area_km2"] > 0

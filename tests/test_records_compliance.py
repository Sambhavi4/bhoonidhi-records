"""
OGC API - Records Part 1: Core compliance tests.

Mapped onto OGC 20-004 (Records Part 1: Core). Each test names what it
exercises so a reviewer can walk the standard against the suite.

Run:  ./scripts/run_tests.sh      (or: pytest tests/ -v)
"""
from __future__ import annotations

import pytest
import requests


def _json(r):
    assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:300]}"
    assert "json" in r.headers.get("Content-Type", ""), \
        f"Content-Type was {r.headers.get('Content-Type')!r}"
    return r.json()


# ===========================================================================
# Core: landing page, conformance, API definition
# ===========================================================================
class TestCore:

    def test_landing_page(self, get):
        d = _json(get("/"))
        assert d.get("links"), "landing page has no links"
        assert d.get("title"), "landing page has no title"

    def test_landing_page_required_links(self, get):
        d = _json(get("/"))
        rels = {l.get("rel") for l in d["links"]}
        hrefs = " ".join(l.get("href", "") for l in d["links"])
        assert "self" in rels, f"no self link; got {sorted(rels)}"
        assert "/conformance" in hrefs, "no link to /conformance"
        assert "/collections" in hrefs, "no link to /collections"
        assert any(r in rels for r in ("service-desc", "service-doc")), \
            "no API definition link"

    def test_conformance_declares_records_core(self, get):
        """The service shall declare the Records Core conformance class."""
        d = _json(get("/conformance"))
        classes = d.get("conformsTo", [])
        assert any("ogcapi-records-1/1.0/conf/core" in c for c in classes), \
            f"Records Core not declared; got {classes}"

    def test_conformance_declares_json_and_sorting(self, get):
        joined = " ".join(_json(get("/conformance")).get("conformsTo", []))
        assert "records-1/1.0/conf/json" in joined, "Records JSON class not declared"
        assert "records-1/1.0/conf/sorting" in joined, "sorting class not declared"

    def test_openapi_document(self, base):
        r = requests.get(f"{base}/openapi", params={"f": "json"}, timeout=90)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert d.get("openapi", "").startswith("3."), \
            f"openapi version {d.get('openapi')!r}"
        assert "/collections" in d.get("paths", {}), \
            "OpenAPI document does not describe /collections"


# ===========================================================================
# The catalogue collection
# ===========================================================================
class TestCatalogue:

    def test_collections_lists_the_catalogue(self, get, collection):
        d = _json(get("/collections"))
        ids = {c["id"] for c in d["collections"]}
        assert collection in ids, f"{collection} not offered; got {ids}"

    def test_collection_has_required_fields(self, get, collection):
        d = _json(get(f"/collections/{collection}"))
        assert d["id"] == collection
        assert d.get("links"), "collection has no links"
        assert d.get("description"), "collection has no description"
        assert d.get("itemType") == "record", \
            f"itemType was {d.get('itemType')!r}, expected 'record'"

    def test_collection_declares_extents(self, get, collection):
        d = _json(get(f"/collections/{collection}"))
        sp = d.get("extent", {}).get("spatial", {}).get("bbox")
        assert sp, "no spatial extent declared"

    def test_queryables(self, get, collection):
        """Records Core: the catalogue shall advertise its queryables."""
        d = _json(get(f"/collections/{collection}/queryables"))
        props = d.get("properties", {})
        assert props, "no queryables advertised"
        for q in ("platform", "instrument", "domain", "title"):
            assert q in props, f"{q} not queryable; got {sorted(props)[:12]}"

    def test_unknown_collection_is_404(self, get):
        assert get("/collections/not-a-catalogue").status_code == 404


# ===========================================================================
# Records
# ===========================================================================
class TestRecords:

    EXPECTED_TOTAL = 59

    def test_items_is_feature_collection(self, get, collection):
        d = _json(get(f"/collections/{collection}/items", {"limit": 5}))
        assert d["type"] == "FeatureCollection"
        assert len(d["features"]) == 5

    def test_all_collections_are_catalogued(self, get, collection):
        d = _json(get(f"/collections/{collection}/items", {"limit": 1}))
        assert d["numberMatched"] == self.EXPECTED_TOTAL, \
            (f"catalogue holds {d['numberMatched']} records, expected "
             f"{self.EXPECTED_TOTAL} - rebuild with scripts/build_catalogue.py")

    def test_record_shape(self, get, collection):
        d = _json(get(f"/collections/{collection}/items", {"limit": 3}))
        for f in d["features"]:
            assert f["type"] == "Feature"
            assert f.get("id"), "a record has no id"
            p = f.get("properties", {})
            assert p.get("type") == "dataset", f"record type was {p.get('type')!r}"
            for field in ("title", "description", "keywords", "providers"):
                assert p.get(field), f"record {f['id']} has no {field}"

    def test_record_provenance_is_declared(self, get, collection):
        """Every record must say where its extents came from, because they are
        derived rather than published by Bhoonidhi."""
        d = _json(get(f"/collections/{collection}/items", {"limit": 10}))
        for f in d["features"]:
            p = f["properties"]
            assert "indicative" in p.get("spatial_extent_basis", ""), \
                f"{f['id']} does not declare its spatial extent basis"
            assert p.get("temporal_start_basis"), \
                f"{f['id']} does not declare its temporal basis"
            assert p.get("access") == "authenticated", \
                f"{f['id']} does not record that Bhoonidhi access is gated"

    def test_single_record_by_id(self, get, collection):
        rid = "CartoSat-1_PAN_CartoDEM_30m"
        d = _json(get(f"/collections/{collection}/items/{rid}"))
        assert d["id"] == rid
        p = d["properties"]
        assert p["platform_id"] == "CartoSat-1"
        assert p["resolution_m"] == 30, \
            "resolution should be parsed from the collection id"

    def test_unknown_record_is_404(self, get, collection):
        r = get(f"/collections/{collection}/items/Not-A_Collection")
        assert r.status_code == 404, f"HTTP {r.status_code}"

    def test_derived_metadata_is_consistent(self, get, collection):
        """The parsed platform must match the collection id it came from."""
        d = _json(get(f"/collections/{collection}/items", {"limit": 100}))
        for f in d["features"]:
            p = f["properties"]
            assert f["id"].startswith(p["platform_id"]), \
                f"{f['id']} parsed as platform {p['platform_id']!r}"
            assert p["collection_id"] == f["id"]


# ===========================================================================
# Query: the capability Bhoonidhi does not expose openly
# ===========================================================================
class TestQuerying:

    def test_full_text_search_narrows(self, get, collection):
        allr = _json(get(f"/collections/{collection}/items", {"limit": 1}))
        hit = _json(get(f"/collections/{collection}/items",
                        {"limit": 1, "q": "scatterometer"}))
        assert 0 < hit["numberMatched"] < allr["numberMatched"], \
            f"q=scatterometer matched {hit['numberMatched']}"

    @pytest.mark.parametrize("term,expect_min", [
        ("NDVI", 1), ("SAR", 1), ("elevation", 1), ("Oceansat", 1),
    ])
    def test_full_text_search_finds_known_terms(self, get, collection,
                                                term, expect_min):
        d = _json(get(f"/collections/{collection}/items",
                      {"limit": 1, "q": term}))
        assert d["numberMatched"] >= expect_min, \
            f"q={term} matched {d['numberMatched']}"

    def test_full_text_search_results_are_relevant(self, get, collection):
        d = _json(get(f"/collections/{collection}/items",
                      {"limit": 20, "q": "NDVI"}))
        assert d["features"], "q=NDVI returned nothing"
        for f in d["features"]:
            blob = (f["properties"]["title"] + " "
                    + f["properties"]["description"]).lower()
            assert "ndvi" in blob, f"{f['id']} does not mention NDVI"

    @pytest.mark.parametrize("field,value", [
        ("platform_id", "EOS-06"), ("domain", "radar"), ("instrument", "AIS"),
    ])
    def test_queryable_filters(self, get, collection, field, value):
        d = _json(get(f"/collections/{collection}/items",
                      {"limit": 100, field: value}))
        assert d["numberMatched"] > 0, f"{field}={value} matched nothing"
        for f in d["features"]:
            assert f["properties"][field] == value, \
                f"filter leaked a record with {field}={f['properties'][field]!r}"

    def test_queryable_filter_narrows(self, get, collection):
        allr = _json(get(f"/collections/{collection}/items", {"limit": 1}))
        one = _json(get(f"/collections/{collection}/items",
                        {"limit": 1, "domain": "radar"}))
        assert one["numberMatched"] < allr["numberMatched"], \
            "a domain filter did not narrow the catalogue"

    def test_limit_is_honoured(self, get, collection):
        for n in (1, 7, 25):
            d = _json(get(f"/collections/{collection}/items", {"limit": n}))
            assert len(d["features"]) == n, f"limit={n} gave {len(d['features'])}"

    def test_paging_does_not_repeat(self, get, collection):
        seen: list[str] = []
        url = None
        for _ in range(5):
            if url is None:
                d = _json(get(f"/collections/{collection}/items", {"limit": 10}))
            else:
                d = _json(requests.get(url, timeout=90))
            ids = [f["id"] for f in d["features"]]
            assert not (set(ids) & set(seen)), "a page repeated earlier records"
            seen.extend(ids)
            nxt = next((l for l in d.get("links", []) if l.get("rel") == "next"), None)
            if not nxt:
                break
            url = nxt["href"]
        assert len(seen) >= 30, f"paging only yielded {len(seen)} records"
        assert len(seen) == len(set(seen)), "duplicate ids across pages"

    def test_sortby(self, get, collection):
        d = _json(get(f"/collections/{collection}/items",
                      {"limit": 20, "sortby": "title"}))
        titles = [f["properties"]["title"] for f in d["features"]]
        assert titles == sorted(titles), "sortby=title did not sort"

    def test_bbox(self, get, collection):
        """A bbox over India must match the India-tasked collections."""
        d = _json(get(f"/collections/{collection}/items",
                      {"limit": 1, "bbox": "68,6,98,38"}))
        assert d["numberMatched"] > 0, "a bbox over India matched nothing"

    def test_datetime_filter(self, get, collection):
        """Records carry an indicative temporal start, so a window after the
        newest launch must match fewer records than the whole catalogue."""
        allr = _json(get(f"/collections/{collection}/items", {"limit": 1}))
        recent = _json(get(f"/collections/{collection}/items",
                           {"limit": 1, "datetime": "2023-01-01/.."}))
        assert recent["numberMatched"] < allr["numberMatched"], \
            (f"datetime filter did not narrow: {recent['numberMatched']} "
             f"of {allr['numberMatched']}")

    def test_bad_limit_is_rejected(self, get, collection):
        r = get(f"/collections/{collection}/items", {"limit": "-5"})
        assert r.status_code == 400, f"limit=-5 accepted (HTTP {r.status_code})"

    def test_bad_bbox_is_rejected(self, get, collection):
        r = get(f"/collections/{collection}/items", {"bbox": "1,2,3"})
        assert r.status_code == 400, f"3-element bbox accepted (HTTP {r.status_code})"


class TestFullTextIndexCoverage:
    """`q=` must search the whole record, not just title and description.

    Regression guard for a defect found by searching the live service by hand:
    every record carries "India", "ISRO" and "NRSC" in its keywords, yet
    q=India and q=ISRO both returned ZERO while q=ResourceSat returned 10.
    The TinyDB provider serves q= out of _metadata-anytext, and the catalogue
    builder was filling that field from title + description only, so the
    controlled vocabulary and the parsed facets were invisible.

    That is the worst kind of search bug: it does not error, it just quietly
    reports that the catalogue holds nothing on the subject.
    """

    @pytest.mark.parametrize("term", ["India", "ISRO", "NRSC"])
    def test_keywords_are_searchable(self, get, collection, term):
        """Terms present in every record's keywords must match every record."""
        r = get(f"/collections/{collection}/items", {"q": term, "limit": 1})
        assert r.status_code == 200
        n = r.json()["numberMatched"]
        assert n == 59, (
            f"q={term} matched {n} of 59 records. It is in the keywords of "
            "every record, so the full-text index is not covering keywords."
        )

    @pytest.mark.parametrize("term,field", [
        ("optical", "domain"), ("radar", "domain"),
        ("AWiFS", "instrument"), ("ResourceSat-2", "platform"),
    ])
    def test_facet_values_are_searchable(self, get, collection, term, field):
        """A value a user can filter on must also be findable by free text."""
        q = get(f"/collections/{collection}/items", {"q": term, "limit": 1})
        f = get(f"/collections/{collection}/items", {field: term, "limit": 1})
        assert q.status_code == 200 and f.status_code == 200
        nq, nf = q.json()["numberMatched"], f.json()["numberMatched"]
        assert nq >= nf > 0, (
            f"q={term} matched {nq} but {field}={term} matched {nf}; "
            "free-text search should find at least what the facet filter does"
        )

    def test_absent_terms_still_return_nothing(self, get, collection):
        """The fix must not make search match everything.

        This catalogue is collection-level: it describes platforms and
        products, not places. A place name genuinely is not in it, and an
        empty result for one is correct behaviour rather than a bug.
        """
        for term in ["Bhopal", "Karnataka", "pizza"]:
            r = get(f"/collections/{collection}/items", {"q": term, "limit": 1})
            assert r.status_code == 200
            assert r.json()["numberMatched"] == 0, \
                f"q={term} should match nothing in a collection-level catalogue"

    def test_empty_result_is_well_formed(self, get, collection):
        """Zero hits must still be a valid, complete FeatureCollection.

        A browser hitting ?q=Bhopal renders "No items" off this document, so
        it has to be a proper empty result, not a truncated one.
        """
        r = get(f"/collections/{collection}/items", {"q": "Bhopal"})
        assert r.status_code == 200
        d = r.json()
        assert d["type"] == "FeatureCollection"
        assert d["features"] == []
        assert d["numberMatched"] == 0 and d["numberReturned"] == 0
        assert any(l.get("rel") == "self" for l in d.get("links", []))

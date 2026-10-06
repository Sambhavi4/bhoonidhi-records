# Bhoonidhi Catalogue + Spatial Analysis

**Two OGC APIs over ISRO's Bhoonidhi archive: an open, searchable catalogue of
its 59 collections, and spatial operations over acquisition footprints that
answer the planning questions a search result cannot.**

CyberGIS mid-semester practical: *build a missing OGC web service over Bhoonidhi.*

| | |
|---|---|
| Portal | Bhoonidhi (`bhoonidhi.nrsc.gov.in`), ISRO / NRSC |
| Standards | **OGC API – Records** (OGC 20-004) · **OGC API – Processes** (OGC 18-062r2) |
| Framework | pygeoapi 0.24.0 · shapely 2.1 · pyproj 3.8 |
| Compliance | **78/78 tests pass** |
| Catalogue | 59 collection records, full-text + queryable search |
| Spatial ops | 4 processes: coverage/gap, set cover, co-coverage, density grid |

---

## The claim

**Identified Gap :** Bhoonidhi's entire API is `/auth/token`, `/auth/logout`,
`/data/collections`, `/data/search`, `/download`. That leaves two holes.

*1. You cannot find out what it holds without an account.* Every catalogue call
needs a JWT:

```
GET https://bhoonidhi-api.nrsc.gov.in/data/collections      (no token)
  → 401 {"ErrorCode":"401","Description":"UNAUTHORIZED",
         "Action":"Invalid session detected! Please login again."}
```

There is no CSW, no OGC API – Records, no `/conformance` — Bhoonidhi's own spec
page mentions none of them. So the holdings cannot be browsed anonymously,
crawled, harvested into GeoNetwork or pycsw, or included in any federated
search. A researcher comparing Indian data against Copernicus or USGS can see
both of those and not Bhoonidhi.

*2. Even with a token, the catalogue only ever hands back a list.*
`/data/search` returns the scenes whose footprints intersect your polygon — and
nothing more. It cannot tell you:

- **what fraction of your area is actually covered**, or where the holes are
- **which few scenes you actually need** out of the thirty it just returned
- **where two sensors co-cover** in the same window, for data fusion
- **how uneven revisit is** across your area

Every one of those is spatial algebra over footprint geometry, and every user
does it by hand in QGIS after exporting metadata. The catalogue knows the
geometry and refuses to compute with it.

**Proposed Fix :** Two conformant OGC APIs over the same holdings.
**OGC API – Records** makes discovery open and queryable — 59 records, full-text
search, queryables, bbox, datetime, sorting, paging — while the data behind it
stays authenticated, and every record links back to Bhoonidhi's own search and
download. **OGC API – Processes** adds the spatial operations: union,
intersection, difference, area measurement in an equal-area projection, and a
greedy set-cover optimisation over acquisition footprints.

> **Not pixel processing.** Nothing here reads a band or a raster value. The
> inputs are footprint polygons and timestamps; the operations are geometric.
> This is catalogue analytics, deliberately distinct from spectral-index
> computation.

---

## The spatial operations

### `aoi-coverage` — coverage and gap analysis
Unions every footprint intersecting your AOI, measures the covered fraction, and
returns the **uncovered remainder as explicit gap polygons**.

```bash
curl -X POST localhost:5003/processes/aoi-coverage/execution \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"aoi":[75.3,13.2,75.8,13.9],"collection":"sentinel-2-l2a"}}'
```
```
AOI 4191.28 km²  ·  covered 4191.28 km² = 100.0%  ·  gaps 0.0 km²  ·  30 scenes
```

### `minimal-scene-set` — greedy set cover
Repeatedly picks the footprint adding the most **newly**-covered area, until the
AOI is covered. The sharpest result in the project:

```
candidates 30  →  SELECTED 2  (avoided 28)
  1. +2517.58 km²  →   60.1%   S2A_MSIL2A_20240331T051651_R062_T43PER
  2. +1673.70 km²  →  100.0%   S2A_MSIL2A_20240331T051651_R062_T43PEQ
```

Thirty scenes match the AOI. **Two cover it.** Ordering the other 28 is wasted
download, wasted quota and wasted time — and today nothing tells you that.

### `multi-sensor-overlap` — co-coverage for data fusion
Intersects one collection's footprint union with another's over the same AOI and
window. Optical ∩ radar in one call instead of two searches and a manual clip.

### `revisit-density` — acquisition density grid
Lays a metric grid over the AOI and counts intersecting acquisitions per cell,
returning GeoJSON ready to render as a heatmap.

```
grid 6x8 @ 10 km → 48 cells · per cell: min 15, mean 18.75, max 30
```

Revisit is twice as dense in some cells as others. A flat list has no spatial
distribution in it at all.

**All areas are measured in a Lambert Azimuthal Equal-Area projection centred on
each request's own AOI**, so km² means km². Measuring in degrees would make
every number here wrong, and a test asserts the AOI area lands in the thousands
rather than fractions.

---

## Run it

```bash
make install       # Python venv
make data          # build the 59 catalogue records
make footprints    # harvest real acquisition footprints
make up            # start the service on :5003
make test          # 78 compliance tests
make demo          # the whole walkthrough
```

## Try it

```bash
# Records: open discovery
http://localhost:5003/collections/bhoonidhi/items?q=scatterometer
http://localhost:5003/collections/bhoonidhi/queryables
http://localhost:5003/collections/bhoonidhi/items?domain=radar
http://localhost:5003/collections/bhoonidhi/items/CartoSat-1_PAN_CartoDEM_30m

# Processes: spatial operations
http://localhost:5003/processes
```

Verified: `q=scatterometer`→5, `q=NDVI`→4, `q=SAR`→20, `platform_id=EOS-06`→28,
`domain=radar`→24, `instrument=AIS`→1, `datetime=2023-01-01/..`→8 of 59.

---

## Where the data comes from

**Catalogue records** — built by `scripts/build_catalogue.py` from Bhoonidhi's
**published** collection list, under strict provenance rules, because a
catalogue that invents metadata is worse than none:

- ids verbatim from Bhoonidhi's list
- platform, instrument and product **parsed from the id itself**
- resolution recorded **only where the id states it** (`_30m`, `_8day_1km`)
- temporal start is the **mission launch date**, labelled an indicative lower
  bound — data cannot predate launch, and Bhoonidhi publishes no per-collection
  extent without a token
- spatial extent labelled **indicative**, from mission tasking only
- nothing else asserted

Every record carries `spatial_extent_basis`, `temporal_start_basis` and
`access: authenticated`, so a consumer can see how far to trust each field.

**Footprints** — `scripts/fetch_footprints.py` speaks STAC to either source:

| | |
|---|---|
| `--source bhoonidhi` | the real thing: `/auth/token` → `/data/search`. Needs `BHOONIDHI_USER`/`BHOONIDHI_PASS`. |
| `--source open` | Microsoft Planetary Computer's public STAC. No credentials. |

The shipped store uses the open source — **68 real footprints**, 60 optical and
8 radar, with real timestamps and cloud cover; nothing synthesised. It is
flagged `is_substitute_for_bhoonidhi: true` in the store metadata **and in the
provenance block of every process response**, so no result can be mistaken for
Bhoonidhi output. The code path and the processes are identical with
credentials.

## Compliance

```
$ ./scripts/run_tests.sh
============================== 78 passed in 1.76s ==============================
```

| Group | Tests | Covers |
|---|---|---|
| Records core | 5 | landing page, link relations, Records Core/JSON/sorting classes, OpenAPI 3 |
| Records catalogue | 5 | collection listed, `itemType: record`, extents, **queryables**, 404 |
| Records items | 7 | all 59 catalogued, record shape, **provenance fields declared**, retrieval by id, parsed metadata consistent with the id |
| Records querying | 17 | full-text narrows **and is relevant**, 3 queryable filters with no leakage, limit, **paging without repeats**, sortby, bbox, datetime, 400s |
| Processes core | 11 | Processes Core class, process list, per-process input/output schemas, `jobControlOptions`, **201 + Location**, full job lifecycle to `/results`, 404s |
| `aoi-coverage` | 7 | **covered + gap reconstructs the AOI**, fully-covered never contradicts a gap geometry, **areas are metric not degrees**, empty result keeps the same shape, per-scene overlap never exceeds the AOI, provenance declared |
| `minimal-scene-set` | 8 | selects fewer than it considers, **cumulative coverage monotonic**, greedy takes the largest gain first, order sequential, target respected, lower target needs no more scenes, cap honoured, algorithm declared |
| `multi-sensor-overlap` | 4 | optical∩radar, **intersection never exceeds either operand**, identical collections rejected, missing collection rejected |
| `revisit-density` | 5 | returns a grid, **summary matches the cells**, **cell areas sum to the AOI**, finer cells give more cells, oversized grid rejected |
| Input validation | 6 | missing/malformed/inverted bbox, wrong geometry type, GeoJSON Polygon and Feature both accepted |

The suite tests the mathematics, not just the protocol: that covered + gap
reconstructs the AOI, that an intersection is never larger than its operands,
that cell areas sum back to the AOI, that greedy coverage is monotonic, and that
areas are projected. Two real defects were caught this way and fixed — a
hairline sliver being reported as a "gap" while also reporting
`fully_covered: true`, and the zero-footprint branch returning a different JSON
shape from the populated one, which would break any client the first time a
search came back empty.

## Known limitations

1. **Footprints are from an open STAC API, not Bhoonidhi** — Bhoonidhi's search
   needs a JWT. Flagged in the store and in every process response. Supply
   credentials and re-run `fetch_footprints.py --source bhoonidhi`; nothing else
   changes.
2. **Catalogue is collection-level** — 59 collections, not the granules behind
   them. Granule-level records need an authenticated harvest; every record links
   to that endpoint.
3. **Catalogue extents are indicative** and labelled as such. Good to discover
   with, not to cite.
4. **Greedy set cover is not guaranteed minimal** — it is within a ln(n) factor
   of optimal, and the response says so.
5. **Cloud cover is reported, not used.** `aoi-coverage` counts a footprint as
   coverage regardless of cloud. Cloud-aware coverage is the obvious next step.
6. **No CQL2 on the catalogue** — pygeoapi's TinyDB provider gives full-text,
   property equality, bbox, datetime and sorting. PostgreSQL would add the
   Filtering class.
7. **No authentication or quota**, and the service is not a mirror: metadata and
   geometry only, never pixels.
8. **Not an official NRSC product.**

## Reproducing the gap evidence

```bash
./scripts/probe_gap.sh
```

Probes **Bhoonidhi only**, saves responses to `docs/evidence/`, and reports a
timeout as `NO RESPONSE` counted as a failure — never as evidence.

> At the time of writing both NRSC hosts stopped answering from the build host
> (DNS resolves, connections time out, rest of the internet fine), so this is
> NRSC-side. The 401 above is a genuine response captured earlier the same day,
> kept with its capture date in the filename rather than silently regenerated.
> See `docs/evidence/README.md`.

## Attribution

- **Bhoonidhi**, ISRO / National Remote Sensing Centre — the collections this
  catalogue describes and links back to.
  <https://bhoonidhi.nrsc.gov.in/> · <https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/>
- **Microsoft Planetary Computer** — the public STAC API standing in for
  Bhoonidhi's footprints.
- **pygeoapi**, **shapely**, **pyproj** — the OGC APIs and the geometry engine.

Bhoonidhi's STAC API is real, modern engineering and this takes nothing from it.
The argument is narrow: a catalogue you must log in to is a catalogue the world
cannot see, and a catalogue that knows every footprint's geometry but will not
compute with it leaves its hardest work to every user, one at a time.

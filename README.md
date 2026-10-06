# Bhoonidhi Spatial Catalogue Analysis

**OGC API – Processes implementing spatial analysis over Bhoonidhi acquisition
footprints — the geometry operations its catalogue holds the data for and does
not perform.**

CyberGIS mid-semester practical: *build a missing OGC web service over Bhoonidhi.*

| | |
|---|---|
| Portal | Bhoonidhi (`bhoonidhi.nrsc.gov.in`), ISRO / NRSC |
| Standard | **OGC API – Processes** Part 1: Core (OGC 18-062r2) |
| Supporting | OGC API – Records (OGC 20-004), for collection discovery |
| Framework | pygeoapi 0.24.0 · shapely 2.1 · pyproj 3.8 |
| Compliance | **78/78 tests pass** |
| Spatial ops | coverage/gap · set cover · co-coverage · density grid |

---

## The claim

**Identified Gap :** Bhoonidhi's catalogue performs **exactly one spatial
operation**. Audited against its own published specification
(`./scripts/probe_gap.sh`):

| | |
|---|---|
| Spatial parameters on `/data/search` | **`bbox` and `intersects` — and only those** |
| What they do | the same single predicate: *does this item intersect my AOI?* |
| Other spatial operators documented | **none** — no `crosses`, `touches`, `overlaps`, `disjoint`, `s_within`, `s_contains` |
| CQL2 filter operations documented | **`eq` and `and`** — attribute equality |
| Analysis vocabulary anywhere in the API | **none** — no union, aggregation, statistics, coverage, density |
| Endpoints | 5: authenticate, logout, list, search, download. **None computes anything.** |

So the catalogue stores the footprint polygon of every scene it holds, and the
only question you may ask of that geometry is whether it touches yours. The
questions that actually decide an acquisition order are all one step further on:

- **how much of my AOI do these scenes actually cover**, and where are the holes?
  — needs union, difference and area
- **which few of the thirty scenes it just returned do I actually need?**
  — needs a set-cover optimisation over geometry
- **where do optical and radar co-cover** in the same window, for fusion?
  — needs the intersection of two footprint unions
- **how uneven is revisit** across my AOI?
  — needs gridding and per-cell counts

Every one of those is spatial algebra over geometry the catalogue already
stores, and every one is left to the user to redo by hand in a desktop GIS.

**This is a capability gap, not an access-control one.** Requiring a token is
normal and sensible practice — Copernicus and EarthExplorer gate too — and this
project makes no complaint about it. The gap stands for an authenticated user
holding the complete API: you can learn *which* scenes touch your area, and
nothing further.

**Proposed Fix :** An **OGC API – Processes** service implementing the four
missing operations as conformant processes, over acquisition footprints fetched
from Bhoonidhi's own STAC search. All areas measured in an equal-area
projection, synchronous and asynchronous execution, and a job API.

> **Not pixel processing.** Nothing here reads a band or a raster value. The
> inputs are footprint polygons and timestamps; the operations are purely
> geometric. This is catalogue analytics, deliberately distinct from
> spectral-index computation.

An **OGC API – Records** catalogue of Bhoonidhi's 59 collections ships alongside
it, as supporting infrastructure rather than as the gap being filled: the
spatial processes need discoverable collection ids to point at, and a searchable
record set makes the service navigable. It is a convenience, and the marks
should rest on the Processes tier.

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

**Catalogue records** (supporting tier) — built by `scripts/build_catalogue.py`
from Bhoonidhi's **published** collection list, under strict provenance rules,
because a catalogue that invents metadata is worse than none:

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
7. **No authentication or quota** on this service, and it is not a mirror:
   footprint geometry and metadata only, never pixels.
8. **Not an official NRSC product.**

## Reproducing the gap evidence

```bash
./scripts/probe_gap.sh            # audit the saved specification
./scripts/probe_gap.sh --refresh  # re-fetch it from NRSC first
```

This is a **capability audit** of Bhoonidhi's published API specification: it
enumerates the spatial parameters the API documents, shows that `contains`,
`within` and `area` appear only as English prose rather than as operators,
extracts the CQL2 operations from the documented examples, and confirms that no
analysis or aggregation vocabulary appears anywhere. Results are written to
`docs/evidence/capability-audit.json`.

Because it reads the specification rather than hammering the service, **it is
reproducible offline** from `docs/evidence/bhoonidhi-api-spec.html` and does not
depend on NRSC being reachable — which matters, because both NRSC hosts stopped
answering from the build host partway through development (DNS resolves,
connections time out, the rest of the internet is fine). `--refresh` re-fetches
when they are back, and says so plainly when it cannot.

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

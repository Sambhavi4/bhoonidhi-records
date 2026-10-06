# Bhoonidhi Records — an open, searchable catalogue for ISRO's EO holdings

**An OGC API – Records service that makes Bhoonidhi's 59 earth observation
collections discoverable, searchable and harvestable without an account.**

CyberGIS mid-semester practical: *build a missing OGC web service over Bhoonidhi.*

| | |
|---|---|
| Portal | Bhoonidhi (`bhoonidhi.nrsc.gov.in`), ISRO / NRSC |
| Standard | **OGC API – Records** Part 1: Core (OGC 20-004) |
| Framework | pygeoapi 0.24.0, `TinyDBCatalogue` provider |
| Conformance | core · json · html · opensearch · sorting |
| Compliance | **34/34 tests pass** |
| Catalogue | 59 records — Cartosat-1, ResourceSat-2/2A, EOS-04, EOS-06, Sentinel-1A, NovaSAR-1, NISAR |

---

## The claim

**Identified Gap :** Bhoonidhi's entire API is four endpoint groups —
`/auth/token`, `/auth/logout`, `/data/collections`, `/data/search`,
`/download` — and **every catalogue call requires a JWT**. Asking what
Bhoonidhi holds returns:

```
GET https://bhoonidhi-api.nrsc.gov.in/data/collections      (no token)
  → HTTP 401 {"ErrorCode":"401","Description":"UNAUTHORIZED",
              "Action":"Invalid session detected! Please login again."}
```

So you cannot find out what India's national EO archive contains until you
register. There is no CSW, no OGC API – Records, and no `/conformance` —
Bhoonidhi's own specification page mentions none of them. That means its
holdings cannot be browsed anonymously, crawled by a search engine, harvested
into GeoNetwork or pycsw, queried from QGIS's metadata search, or included in
any federated or cross-portal catalogue. A researcher comparing Indian data
against Copernicus or USGS holdings can see both of those and not Bhoonidhi.

Discovery of *individual products* is gated, and discovery of *what collections
even exist* is gated with it.

**Proposed Fix :** Implement **OGC API – Records** using pygeoapi over the same
holdings, so the catalogue is open and queryable even though the data behind it
stays authenticated. 59 records with full-text search, queryables (platform,
instrument, instrument domain, product, resolution), bbox, datetime, sorting,
paging and stable record ids. Each record links back to Bhoonidhi's own search
and download endpoints, so the service **drives traffic to Bhoonidhi rather
than bypassing it** — it publishes metadata, never data.

---

## Run it

```bash
make install   # Python venv
make data      # build the catalogue from Bhoonidhi's collection list
make up        # start the service on :5003
make test      # 34 compliance tests
```

## Try it

```bash
# what's in the catalogue
http://localhost:5003/collections/bhoonidhi/items?limit=10

# the query Bhoonidhi can't answer without a login — full-text search
http://localhost:5003/collections/bhoonidhi/items?q=scatterometer
http://localhost:5003/collections/bhoonidhi/items?q=NDVI

# queryables, then filter on them
http://localhost:5003/collections/bhoonidhi/queryables
http://localhost:5003/collections/bhoonidhi/items?platform_id=EOS-06
http://localhost:5003/collections/bhoonidhi/items?domain=radar
http://localhost:5003/collections/bhoonidhi/items?instrument=AIS

# one record, by a stable id
http://localhost:5003/collections/bhoonidhi/items/CartoSat-1_PAN_CartoDEM_30m

# spatial, temporal, sorted
http://localhost:5003/collections/bhoonidhi/items?bbox=68,6,98,38
http://localhost:5003/collections/bhoonidhi/items?datetime=2023-01-01/..
http://localhost:5003/collections/bhoonidhi/items?sortby=title
```

Verified results: `q=scatterometer` → 5, `q=NDVI` → 4, `q=SAR` → 20,
`platform_id=EOS-06` → 28, `domain=radar` → 24, `instrument=AIS` → 1,
`datetime=2023-01-01/..` → 8 of 59.

---

## Where the metadata comes from

`scripts/build_catalogue.py` builds one record per collection from Bhoonidhi's
**published** collection list, following strict provenance rules — because a
catalogue that invents metadata is worse than no catalogue:

- collection ids are verbatim from Bhoonidhi's list
- platform, instrument and product are **parsed out of the id itself**
- resolution is recorded **only where the id states it** (`_30m`, `_8day_1km`)
- temporal start is the **mission launch date**, labelled an indicative lower
  bound — data cannot predate launch, and Bhoonidhi publishes no per-collection
  temporal extent without a token
- spatial extent is labelled **indicative**, derived from mission tasking only
  (India-tasked vs global)
- nothing else is asserted

Every record carries `spatial_extent_basis`, `temporal_start_basis` and
`access: authenticated` so a consumer can see exactly how much to trust each
field. Three tokens in the spec page (`content_copy`, `access_token`,
`query_by_filters`) are not collections and are reported as skipped.

## Compliance

```
$ ./scripts/run_tests.sh
============================== 34 passed in 0.27s ==============================
```

| Group | Tests | Covers |
|---|---|---|
| Core | 5 | landing page, required link relations, Records Core / JSON / sorting conformance classes, OpenAPI 3 |
| Catalogue | 5 | collection listed, required fields, `itemType: record`, extents, **queryables**, 404 |
| Records | 7 | FeatureCollection shape, all 59 catalogued, record shape, **provenance fields declared**, retrieval by id, 404, parsed metadata consistent with the id |
| Querying | 17 | full-text search narrows **and is relevant**, 4 known terms, 3 queryable filters with no leakage, limit, **paging without repeats**, sortby, bbox, datetime, 400 on bad limit/bbox |

The suite checks correctness, not just protocol shape: that `q=NDVI` returns
records that actually mention NDVI, that a `platform_id` filter never leaks a
different platform, that paging loses and repeats nothing, and that every
record declares the basis for its derived extents.

## Known limitations

1. **Collection-level, not product-level.** 59 collections, not the millions of
   granules behind them. Granule-level records would need an authenticated
   harvest of `/data/search` — the natural next step, and the reason every
   record links to that endpoint.
2. **Spatial and temporal extents are indicative**, derived as described above
   and labelled in every record. They are good enough to discover with and not
   good enough to cite.
3. **The class/instrument mapping is mine**, parsed from identifiers, not an
   official NRSC vocabulary.
4. **No CQL2 filtering.** pygeoapi's TinyDB catalogue offers full-text `q`,
   property equality, bbox, datetime and sorting. A PostgreSQL-backed provider
   would add the Filtering conformance class.
5. **No authentication or quota**, and the service is not a mirror: it carries
   metadata only, and the data itself still requires a Bhoonidhi account.
6. **Not an official NRSC product.** It is a third-party catalogue over public
   metadata, for academic demonstration, with attribution.

## Reproducing the gap evidence

```bash
./scripts/probe_gap.sh
```

Probes **Bhoonidhi only** and saves responses to `docs/evidence/`. It reports a
timeout as `NO RESPONSE` and counts it as a failure, never as evidence.

> At the time of writing both `bhoonidhi.nrsc.gov.in` and
> `bhoonidhi-api.nrsc.gov.in` stopped answering from the build host — DNS
> resolves, connections time out, and the rest of the internet is reachable —
> so this is NRSC-side. The 401 above is a genuine response captured earlier the
> same day and kept with its capture date in the filename rather than silently
> regenerated. See `docs/evidence/README.md`.

## Attribution

- **Bhoonidhi**, ISRO / National Remote Sensing Centre — the collections this
  catalogue describes and links back to.
  <https://bhoonidhi.nrsc.gov.in/> · <https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/>
- **pygeoapi** — the OGC API – Records implementation.

Bhoonidhi's STAC API is a real, modern piece of engineering, and this project
takes nothing away from it. The argument is narrow: a catalogue you must log in
to is a catalogue the world cannot see, and making the *index* open while the
*data* stays governed costs nothing and makes Indian EO holdings findable.

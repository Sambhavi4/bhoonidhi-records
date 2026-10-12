# Gap analysis — why Bhoonidhi needs an OGC API – Processes tier

This is the long-form version of the "Identified Gap" section of
[`../README.md`](../README.md). It exists because the gap is easy to state in
one line and easy to *under-sell* in one line, and the marking rubric weights
gap identification at 5 of 20 marks on whether the justification is
*convincing*.

Everything numeric here is produced by a script in [`../scripts/`](../scripts/)
and saved under [`evidence/`](evidence/). Nothing is asserted that cannot be
re-run.

| Claim | Produced by | Evidence file |
|---|---|---|
| Bhoonidhi's spatial surface is one predicate | `probe_gap.sh` | `evidence/capability-audit.json` |
| 92% of what the catalogue returns is redundant | `measure_redundancy.py` | `evidence/redundancy-measurement.json` |
| No processing endpoint anywhere in ISRO's stack | `probe_baseline.sh` | `evidence/baseline-*` |
| Peers publish 146 processes; Bhoonidhi publishes 0 | `probe_baseline.sh` | `evidence/baseline-peer-*.json` |

---

## 1. The gap in one sentence

> Bhoonidhi stores the footprint polygon of every scene it holds, and the only
> question you are permitted to ask of that geometry is *"does it touch mine?"*

Everything else in this document is either evidence for that sentence or an
argument about why it matters more than it sounds like it does.

---

## 2. What Bhoonidhi actually does — stated fairly first

An argument that misrepresents its target is worthless, so: Bhoonidhi's Open
Data Access API is real, modern engineering and this project takes nothing
away from it.

- It is built on **STAC 1.0.0**, a current community standard.
- It has proper **JWT authentication** (`/auth/token`, `/auth/logout`).
- `/data/collections` lists ~59 published collections.
- `/data/search` accepts GeoJSON `intersects`, a `bbox`, RFC 3339 `datetime`
  ranges and **CQL2-JSON** filters.
- `/download` delivers products by item id.

That is a competent discovery API. A developer can authenticate, search by
space and time, and fetch. **Discovery is solved.** The gap is not there.

### This gap has nothing to do with authentication

Stated explicitly because it is the most tempting wrong version of this
argument. Requiring a token is normal and sensible: Copernicus, USGS
EarthExplorer and NASA Earthdata all gate downloads too. This project makes no
complaint about it.

**The gap stands for a fully authenticated user holding the complete API.**
Hand someone a valid JWT and every limitation described below is still in
force. It is a *capability* gap, not an *access* gap.

---

## 3. What is missing — the audit

`./scripts/probe_gap.sh` audits Bhoonidhi's own published API specification.
It reads the saved specification rather than hammering the live service, so it
is reproducible offline and does not depend on NRSC being reachable.

Findings, written to `evidence/capability-audit.json`:

| Question | Answer |
|---|---|
| Spatial parameters on `/data/search` | **`bbox` and `intersects`** — and nothing else |
| What they compute | the same single predicate: *does this item intersect my AOI?* |
| Other spatial operators documented | **none** — no `crosses`, `touches`, `overlaps`, `disjoint`, `s_within`, `s_contains` |
| CQL2 operations in the documented examples | **`eq`, `and`** — attribute equality |
| Analysis vocabulary anywhere in the API | **none** — no union, aggregation, statistics, coverage, density |
| Endpoints | **5**: authenticate, logout, list, search, download |
| Endpoints that compute anything | **0** |

`contains`, `within` and `area` do appear in the specification — as English
prose, never as operators. The audit checks this specifically, so the
counter-example becomes part of the argument instead of a hole in it.

### The questions that are therefore unanswerable

Each of these is ordinary spatial algebra over geometry Bhoonidhi **already
stores**, and each is the question that actually decides an acquisition order:

| Question an analyst asks | What it needs | Available today |
|---|---|---|
| How much of my AOI do these scenes really cover, and where are the holes? | union, difference, area | ✗ |
| Which few of the 30 scenes returned do I actually need? | set cover over geometry | ✗ |
| Where do optical and radar co-cover, for fusion? | intersection of two unions | ✗ |
| How uneven is revisit across my AOI? | gridding, per-cell counts | ✗ |
| What terrain is actually under each candidate scene? | raster–vector overlay | ✗ |

---

## 4. Why this is a *big* gap, not a small one

Four independent arguments. Each is measured.

### 4.1 It is an entire standardised tier, absent — not a missing parameter

Server-side geospatial computation is not exotic or speculative. It has been
an OGC standard since **2007**:

| Standard | Document | Year |
|---|---|---|
| OGC Web Processing Service 1.0.0 | 05-007r7 | 2007 |
| OGC WPS 2.0.0 | 14-065 | 2015 |
| **OGC API – Processes, Part 1: Core** | **18-062r2** | **2021** |
| openEO API (EO-specific process graphs) | community | 2020 |

`./scripts/probe_baseline.sh` probes ISRO's public stack for any of it:

```
Bhuvan WPS 1.0.0 GetCapabilities       HTTP 404   absent
Bhuvan OGC API - Processes landing     HTTP 404   absent
Bhoonidhi /processes                   HTTP 404   absent
  MATCHED  no server-side computation anywhere in the public stack
```

So the missing thing is not a query parameter someone forgot. It is the whole
processing tier of the OGC stack — the tier that turns a catalogue into
something you can *compute with* — and it is absent from India's national
remote sensing portal, nearly two decades after it was standardised.

### 4.2 Every comparable portal has it — measured, live

The strongest objection to §4.1 is *"nobody actually deploys that; it's a
paper standard."* `probe_baseline.sh` tests that objection against the field:

| Portal | Endpoint | Result |
|---|---|---|
| **Copernicus Data Space** (openEO) | `/openeo/1.2/processes` | **HTTP 200 — 146 processes published** |
| **MS Planetary Computer** | STAC `/v1/` | HTTP 200 — 15 conformance classes incl. CQL2 |
| **Bhoonidhi** | `/processes` | **HTTP 404** |
| **Bhuvan** | `/bhuvan/wps` | **HTTP 404** |

Documented but deliberately not probed, because each needs registration and
hammering them from a course project would be impolite rather than
informative: **NASA Earthdata Harmony** (server-side subsetting, reprojection,
regridding, aggregation), **USGS ESPA / M2M** (on-demand higher-level Landsat
products), **Google Earth Engine** (computation *is* the access model),
**Digital Earth Africa** (Open Data Cube + OGC API – Processes).

> Copernicus publishes **146** server-side processes at a public,
> unauthenticated endpoint that anyone can enumerate right now.
> Bhoonidhi publishes **0**.

That is not a scoping decision everyone else also made. It is the single
capability that separates Bhoonidhi from every portal it would be compared
against.

### 4.3 The cost is measurable, and it is 92%

This is the decisive argument, because it converts the gap from an
architectural complaint into a number.

Because the catalogue will not compute with footprint geometry, a user has no
way to learn which of the returned scenes they actually need. So the rational
move — and what people in fact do — is to **order everything the search
returned**.

`./scripts/measure_redundancy.py` asks this service's own `minimal-scene-set`
process the question the catalogue cannot answer, over four AOIs and two
collections:

| AOI | collection | km² | found | needed | redundant |
|---|---|---|---|---|---|
| taluk | sentinel-2-l2a | 479 | 30 | 1 | 97% |
| taluk | sentinel-1-grd | 479 | 4 | 1 | 75% |
| district | sentinel-2-l2a | 4,191 | 30 | 2 | 93% |
| district | sentinel-1-grd | 4,191 | 8 | 2 | 75% |
| two districts | sentinel-2-l2a | 11,855 | 60 | 2 | 97% |
| two districts | sentinel-1-grd | 11,855 | 8 | 2 | 75% |
| regional transect | sentinel-2-l2a | 59,816 | 60 | 4 | 93% |
| regional transect | sentinel-1-grd | 59,816 | 8 | 2 | 75% |
| **TOTAL** | | | **208** | **16** | **92%** |

> Across 8 queries the catalogue hands back **208 scenes**. **16** cover the
> same ground to the same percentage. **192 are redundant — 92% of everything
> returned.**
>
> At published product sizes that is **206 GB ordered where 16 GB was
> required**: 190 GB of avoidable transfer, for four areas of interest.
> Projected onto Bhoonidhi's own ResourceSat-2 LISS-III volumes
> (250 MB/scene), 47 GB.

**Being precise about what is measured and what is modelled.** The scene
counts are measured live against the running service over real STAC
footprints — that is the part that matters and it is not modelled. The byte
figures are *published nominal product sizes* multiplied by those counts; the
script never downloads imagery and says so in its own output.

**And this is a floor, not a ceiling.** The footprint store holds 68 scenes
over a 3-month window, so several rows above are capped by the store rather
than by the AOI — "found" reaches 30 or 60 because that is all there is to
find. A real Bhoonidhi search spans a multi-decade archive with many revisits
per year: it returns far more intersecting scenes for the same AOI, while the
number genuinely needed to cover it stays roughly constant. **Redundancy rises
with archive depth.** 92% is the conservative end.

### 4.4 The workaround exists, is expert-only, and nobody does it

The honest counter-argument is: *"you can just do this yourself."* True — and
that is precisely the gap. Here is the whole procedure a user must follow
today to learn the 92% figure for their own AOI:

1. Authenticate, `POST /data/search`, page through every result.
2. Extract each item's footprint geometry from the STAC response.
3. Load 30+ polygons into a desktop GIS or a `shapely` script.
4. Union them; difference the union against the AOI to find the holes.
5. Reproject to an equal-area CRS, or every area number is wrong.
6. Implement a **set-cover** optimisation over the footprints.
7. Map the chosen geometries back to orderable item ids.

Step 6 is an NP-hard combinatorial problem. Steps 4–5 are where most people
silently get it wrong, because areas computed in degrees are meaningless.
This is a GIS-literate programmer's afternoon, repeated for every AOI, by
every user, forever — and it is **the same seven steps every time**, over
geometry the server already has in memory when it answers the search.

So in practice nobody does it. They download all 30 scenes.

**This service does all seven steps in one HTTP request:**

```bash
curl -X POST localhost:5003/processes/minimal-scene-set/execution \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"aoi":[75.3,13.2,75.8,13.9],"collection":"sentinel-2-l2a"}}'
```
```
candidates 30  →  SELECTED 2  (avoided 28)
  1. +2517.58 km²  →   60.1%   S2A_MSIL2A_20240331T051651_R062_T43PER
  2. +1673.70 km²  →  100.0%   S2A_MSIL2A_20240331T051651_R062_T43PEQ
```

---

## 5. Counter-arguments, answered

Taken seriously rather than ignored, because a gap claim that cannot survive
its own objections is not convincing.

**"Requiring a token is the real barrier."**
No. See §2. Every limitation here applies to a fully authenticated user.
Gating downloads is normal practice.

**"The data isn't secret — you can get it, so there's no gap."**
Agreed, and the gap is not about secrecy. It is that there is no way to
*compute* with the geometry. §4.3 measures what that costs.

**"Server-side processing is exotic / a paper standard."**
Measured against the field in §4.2: Copernicus publishes 146 processes
publicly, today, at an endpoint this project enumerates live.

**"Users can script it themselves."**
They can, in seven steps including an NP-hard optimisation and a reprojection
that is easy to get silently wrong (§4.4). The whole purpose of a service
interface is that the server does once, correctly, what every client would
otherwise do repeatedly and inconsistently.

**"STAC search *is* the spatial API."**
STAC search is a *filter*. It selects items. It does not perform geometry
operations, and the STAC spec does not claim to. That is exactly the division
of labour OGC API – Processes exists to fill.

**"This is a niche optimisation."**
92% of returned scenes are redundant (§4.3), and the number rises with archive
depth. Order-of-magnitude reductions in transfer volume are not niche —
especially for users on Indian academic or state-government bandwidth, who are
the portal's primary audience.

---

## 6. Scope — what this project does and does not claim

**Claims:** Bhoonidhi has no server-side spatial computation; that capability
is standardised, deployed by peers, and its absence has a measurable cost; and
a conformant OGC API – Processes service over footprint geometry closes it.

**Does not claim:** that Bhoonidhi is badly built (§2), that authentication is
wrong (§2), that this project's footprints *are* Bhoonidhi's (they are
substituted and flagged — see `README.md` → Known limitations), or that this is
an official NRSC product.

---

## 7. What closes the gap

A conformant **OGC API – Processes** (OGC 18-062r2) service over the footprint
geometry Bhoonidhi already stores. This repository implements six processes:

| Process | Closes |
|---|---|
| `aoi-coverage` | coverage fraction + explicit gap polygons |
| `minimal-scene-set` | greedy set cover — *which scenes do I actually need?* |
| `multi-sensor-overlap` | optical ∩ radar co-coverage for fusion |
| `revisit-density` | acquisition density grid |
| `zonal-statistics` | raster–vector overlay: the pixels inside a polygon |
| `scene-raster-profile` | the join — what terrain is under each candidate scene |

with synchronous and asynchronous execution, a job API, and all areas measured
in a Lambert Azimuthal Equal-Area projection centred on each request's own AOI
so that km² means km².

**135/135 compliance tests pass**, and the suite tests the mathematics rather
than only the protocol shape: that covered + gap reconstructs the AOI, that an
intersection never exceeds its operands, that cell areas sum back to the AOI,
that greedy coverage is monotonic, and that areas are projected rather than
computed in degrees.

---

## 8. Reproducing all of it

```bash
./scripts/probe_gap.sh              # audit Bhoonidhi's specification  (offline-capable)
./scripts/probe_gap.sh --refresh    # re-fetch the specification first
./scripts/probe_baseline.sh         # ISRO stack + peer portals, live
./scripts/measure_redundancy.py     # the 92% figure, against the running service
```

The first needs no network. The second and third do. Each writes to
`docs/evidence/` so a reviewer can diff a re-run against what is committed —
and if a probe stops matching, the upstream service has changed and the script
says so loudly rather than quietly passing.

If NRSC enables a processing endpoint, `probe_baseline.sh` will report
`NOT MATCHED` and the honest response is to say the gap has closed.

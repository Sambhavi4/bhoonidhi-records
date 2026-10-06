# Evidence

Backing for section "The claim" in the main README. Regenerate with
`./scripts/probe_gap.sh` (add `--refresh` to re-fetch from NRSC first).

| File | What it shows |
|---|---|
| `bhoonidhi-api-spec.html` | Bhoonidhi's own published API specification page. The primary evidence: it documents exactly five endpoints, exposes `bbox` and `intersects` as its only spatial parameters, uses `eq`/`and` in its CQL2 filter examples, and contains no analysis or aggregation capability anywhere. |
| `capability-audit.json` | Machine-readable summary of the audit: the spatial parameters found, the spatial predicates absent, the CQL2 operations documented, the analysis terms searched for, and the endpoints. |
| `collections-requires-token.CAPTURED-2026-10-06.json` | A genuine live response from `GET /data/collections` with no token (HTTP 401). Kept for completeness, **not** as the gap: requiring a token is normal practice and this project makes no complaint about it. The gap is a capability gap and holds for authenticated users. |

## Why the evidence is a specification audit

The claim is about what Bhoonidhi's API *can do*, not about whether a given
request succeeds. That is settled by reading the published interface, so
`probe_gap.sh` audits the specification rather than hammering the service. It is
therefore reproducible offline and does not depend on NRSC being reachable.

That matters here: partway through development both `bhoonidhi.nrsc.gov.in` and
`bhoonidhi-api.nrsc.gov.in` stopped answering from the build host — DNS resolves,
connections time out, and the rest of the internet is reachable — so the cause
is NRSC-side (an outage, or rate limiting after repeated probing). The saved
specification page was captured before that, and `--refresh` will update it when
they are reachable again, reporting plainly when it cannot.

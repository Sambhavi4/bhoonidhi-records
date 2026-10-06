# Evidence

Responses captured from Bhoonidhi, backing section 1 of the main README.
Regenerate with `./scripts/probe_gap.sh`.

| File | What it shows |
|---|---|
| `bhoonidhi-api-spec.html` | Bhoonidhi's own published API specification page. Documents exactly four endpoint groups — `/auth/token`, `/auth/logout`, `/data/collections`, `/data/search`, `/download` — and contains no mention of `/csw`, `/conformance`, OGC API, or any crawlable catalogue interface. This is the positive half of the gap claim. |
| `collections-requires-token.CAPTURED-2026-10-06.json` | A genuine live response from `GET https://bhoonidhi-api.nrsc.gov.in/data/collections` with no token: HTTP 401, `{"ErrorCode":"401","Description":"UNAUTHORIZED","Action":"Invalid session detected! Please login again."}`. Captured 2026-10-06. |

## Note on reproducibility

At the time of writing, `bhoonidhi.nrsc.gov.in` and `bhoonidhi-api.nrsc.gov.in`
stopped responding from this host — DNS resolves but connections time out,
while the rest of the internet is reachable. That is almost certainly
NRSC-side (an outage, or rate limiting after repeated probing during
development). The 401 above is therefore carried over from an earlier capture
on the same day, with the date in the filename, rather than being silently
regenerated.

`probe_gap.sh` is written so that a timeout is reported as **NO RESPONSE** and
counted as a failure, never as evidence. Re-run it when Bhoonidhi is reachable
and it will capture the responses fresh.

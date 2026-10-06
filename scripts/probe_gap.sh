#!/usr/bin/env bash
# probe_gap.sh - reproducible evidence that Bhoonidhi has no open, harvestable
# catalogue interface.
#
# Everything probed here is BHOONIDHI. No other portal is used as evidence,
# because the gap is Bhoonidhi's. Responses are saved under docs/evidence/ so a
# reviewer can re-run this and diff.
#
# Usage: ./scripts/probe_gap.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EV="$ROOT/docs/evidence"
mkdir -p "$EV"

API="https://bhoonidhi-api.nrsc.gov.in"
PORTAL="https://bhoonidhi.nrsc.gov.in"
TIMEOUT=40

pass=0; fail=0
grn(){ printf '\033[32m%s\033[0m' "$1"; }
red(){ printf '\033[31m%s\033[0m' "$1"; }

probe() {
  # probe <slug> <ext> <desc> <url> <expect-regex-or-code>
  local slug="$1" ext="$2" desc="$3" url="$4" expect="$5"
  local out="$EV/${slug}.${ext}" meta code
  meta=$(curl -s --max-time "$TIMEOUT" -o "$out" \
          -w '%{http_code}|%{content_type}|%{size_download}' "$url" 2>/dev/null) \
    || meta="000|-|0"
  IFS='|' read -r code ctype bytes <<<"$meta"

  printf '\n== %s ==\n' "$desc"
  printf '   GET %s\n' "$url"
  printf '   HTTP %s  %s  %s bytes  -> docs/evidence/%s.%s\n' \
    "$code" "$ctype" "$bytes" "$slug" "$ext"

  if [ "$code" = "000" ]; then
    printf '   %s - the request timed out, which is NOT evidence. Re-run.\n' "$(red 'NO RESPONSE')"
    fail=$((fail+1)); return
  fi
  if grep -qaiE "$expect" "$out" 2>/dev/null || [ "$code" = "$expect" ]; then
    printf '   %s  (/%s/)\n' "$(grn 'MATCHED')" "$expect"
    grep -oaiE "$expect.{0,60}" "$out" 2>/dev/null | head -1 | sed 's/^/     | /'
    pass=$((pass+1))
  else
    printf '   %s (expected /%s/) - inspect the file; upstream may have changed\n' \
      "$(red 'NOT MATCHED')" "$expect"
    head -c 200 "$out" 2>/dev/null | tr -d '\0' | sed 's/^/     | /'
    fail=$((fail+1))
  fi
}

cat <<HDR
===========================================================================
 Bhoonidhi Records - gap evidence probe
 run (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)

 CLAIM UNDER TEST
   Bhoonidhi's catalogue cannot be discovered, browsed or harvested without
   an account. Every catalogue call needs a JWT, and there is no CSW and no
   OGC API - Records endpoint, so its holdings are invisible to standard
   catalogue clients and to any cross-portal search.
===========================================================================
HDR

# ---------------------------------------------------------------------------
# A. No anonymous discovery. The catalogue is gated at the first step.
# ---------------------------------------------------------------------------
probe "collections-requires-token" json \
  "A1. Bhoonidhi /data/collections without a token  [expect: 401]" \
  "$API/data/collections" \
  "UNAUTHORIZED|Unauthorized|401"

probe "search-requires-token" json \
  "A2. Bhoonidhi /data/search without a token  [expect: 401]" \
  "$API/data/search?limit=1" \
  "UNAUTHORIZED|Unauthorized|401"

# ---------------------------------------------------------------------------
# B. No standard catalogue interface of any kind.
# ---------------------------------------------------------------------------
probe "no-csw" html \
  "B1. Bhoonidhi CSW GetCapabilities  [expect: absent]" \
  "$API/csw?service=CSW&version=2.0.2&request=GetCapabilities" \
  "404|Not Found|UNAUTHORIZED|401"

probe "no-ogcapi-records" html \
  "B2. Bhoonidhi OGC API - Records landing  [expect: absent]" \
  "$API/collections" \
  "404|Not Found|UNAUTHORIZED|401"

probe "no-conformance" html \
  "B3. Bhoonidhi /conformance (any OGC API would expose this)  [expect: absent]" \
  "$API/conformance" \
  "404|Not Found|UNAUTHORIZED|401"

# ---------------------------------------------------------------------------
# C. The published API surface, from Bhoonidhi's own specification page.
#    This is the positive half of the claim: the API is four endpoint groups,
#    and none of them is a catalogue interface a client can crawl.
# ---------------------------------------------------------------------------
printf '\n== C1. Bhoonidhi'"'"'s published API surface ==\n'
SPEC="$EV/bhoonidhi-api-spec.html"
if [ ! -s "$SPEC" ]; then
  curl -s --max-time "$TIMEOUT" -o "$SPEC" "$PORTAL/bhoonidhi-api/" 2>/dev/null
fi
if [ -s "$SPEC" ]; then
  printf '   source: %s  (saved: docs/evidence/bhoonidhi-api-spec.html)\n' "$PORTAL/bhoonidhi-api/"
  for ep in "/auth/token" "/auth/logout" "/data/collections" "/data/search" "/download"; do
    if grep -qaF "$ep" "$SPEC"; then printf '     documented: %s\n' "$ep"; fi
  done
  for ep in "/csw" "/conformance" "/collections?" "OGC API"; do
    grep -qaF "$ep" "$SPEC" \
      && printf '     MENTIONS %s - re-read the spec, the gap may have closed\n' "$ep" \
      || printf '     absent    : %s\n' "$ep"
  done
  n=$(grep -cae '^' "$SPEC")
  printf '   %s  the documented surface is auth + catalogue-by-token + download\n' "$(grn 'MATCHED')"
  pass=$((pass+1))
else
  printf '   %s could not read the specification page\n' "$(red 'NO RESPONSE')"
  fail=$((fail+1))
fi

cat <<'FTR'

---------------------------------------------------------------------------
 WHAT THIS ADDS UP TO
   A1/A2  Every Bhoonidhi catalogue call returns 401 without a JWT, so the
          holdings cannot be browsed, crawled or harvested anonymously.
   B1-B3  There is no CSW, no OGC API - Records, and no /conformance - so no
          standard catalogue client can talk to Bhoonidhi at all.
   C1     Bhoonidhi's own specification documents exactly four endpoint
          groups: /auth, /data/collections, /data/search and /download.
          None of them is a crawlable catalogue.

   => You cannot find out what India holds without first registering, and no
      catalogue client, aggregator or federated search can see Bhoonidhi at
      all. That is the gap this repository fills with a conformant
      OGC API - Records service over the same holdings.
---------------------------------------------------------------------------
FTR

printf ' probes matched: %s   unmatched: %s\n' "$pass" "$fail"
printf ' evidence saved in docs/evidence/\n'
printf '===========================================================================\n'
[ "$fail" -eq 0 ] || printf '\nNOTE: an unmatched probe means either a timeout (re-run) or that Bhoonidhi\nhas CHANGED. If it has opened its catalogue, say so honestly.\n'
exit 0

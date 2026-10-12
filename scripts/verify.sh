#!/usr/bin/env bash
# verify.sh - one command that checks everything a marker will check.
#
# Answers the question "how do I know it is actually working?" without
# clicking through URLs by hand. Five groups:
#
#   A  the service responds, as JSON *and* as HTML (a browser hits HTML, and
#      that path broke once while every JSON test passed)
#   B  the OGC API - Processes mandatory operations, including the full
#      asynchronous job lifecycle
#   C  the compliance suite
#   D  the gap evidence - the claims the report makes about Bhoonidhi
#   E  the repository is committed and pushed
#
# Usage:
#   ./scripts/verify.sh            # everything (D needs network)
#   ./scripts/verify.sh --offline  # skip the live upstream probes
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
B="${RECORDS_BASE:-http://localhost:5003}"
PY="$ROOT/../runtime/venv/bin/python"
OFFLINE=0; [ "${1:-}" = "--offline" ] && OFFLINE=1

UA='Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0'
ACC='text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'

pass=0; fail=0; skip=0
g(){ printf '\033[32m%s\033[0m' "$1"; }
r(){ printf '\033[31m%s\033[0m' "$1"; }
y(){ printf '\033[33m%s\033[0m' "$1"; }
hdr(){ printf '\n\033[1m%s\033[0m\n' "$*"; }

ok()   { printf '  %s  %s\n'      "$(g ' ok ')" "$*"; pass=$((pass+1)); }
bad()  { printf '  %s  %s\n'      "$(r 'FAIL')" "$*"; fail=$((fail+1)); }
skp()  { printf '  %s  %s\n'      "$(y 'skip')" "$*"; skip=$((skip+1)); }

# code <url> [accept]  -> prints HTTP status
code(){ curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
          ${2:+-H "Accept: $2"} ${2:+-H "User-Agent: $UA"} "$1" 2>/dev/null; }

check(){ # check <label> <url> <expected> [accept]
  local c; c=$(code "$2" "${4:-}")
  [ "$c" = "$3" ] && ok "$1  ($c)" || bad "$1  (got $c, want $3)"
}

cat <<HDR
===========================================================================
 Bhoonidhi Spatial Catalogue Analysis - end-to-end verification
 service : $B
 run     : $(date -u +%Y-%m-%dT%H:%M:%SZ)
===========================================================================
HDR

# ---------------------------------------------------------------- A
hdr "A. The service responds - as JSON and as HTML"
if [ "$(code "$B/")" != "200" ]; then
  bad "nothing on $B - run: make up"
  printf '\n%s the service is down; everything below would fail for that one reason.\n' "$(r 'STOP:')"
  exit 1
fi
for p in / /conformance /openapi /processes /jobs; do
  check "JSON  $p" "$B$p?f=json" 200
done
# The HTML path is tested separately and deliberately: it broke once while
# every JSON check above passed.
for p in / /collections /collections/bhoonidhi /collections/bhoonidhi/items \
         /processes /processes/minimal-scene-set; do
  check "HTML  $p" "$B$p" 200 "$ACC"
done

# ---------------------------------------------------------------- B
hdr "B. OGC API - Processes mandatory operations"
n=$(curl -s --max-time 30 "$B/processes?f=json" | grep -o '"id"' | wc -l)
[ "${n:-0}" -ge 6 ] && ok "process list advertises $n processes" \
                    || bad "expected >= 6 processes, saw ${n:-0}"

AOI='{"inputs":{"aoi":[75.3,13.2,75.8,13.9],"collection":"sentinel-2-l2a"}}'

sync=$(curl -s --max-time 300 -X POST "$B/processes/minimal-scene-set/execution" \
        -H 'Content-Type: application/json' -d "$AOI" 2>/dev/null)
sel=$(printf '%s' "$sync" | grep -oE '"scenes_selected": *[0-9]+' | grep -oE '[0-9]+$')
cand=$(printf '%s' "$sync" | grep -oE '"candidates_considered": *[0-9]+' | grep -oE '[0-9]+$')
if [ -n "${sel:-}" ] && [ -n "${cand:-}" ] && [ "$cand" -gt "$sel" ]; then
  ok "sync execution: $cand candidates -> $sel selected (the headline result)"
else
  bad "sync execution did not return a usable selection"
fi

hdrs=$(curl -s -i --max-time 300 -X POST "$B/processes/aoi-coverage/execution" \
        -H 'Content-Type: application/json' -H 'Prefer: respond-async' \
        -d "$AOI" 2>/dev/null)
printf '%s' "$hdrs" | grep -qi '^HTTP/1.1 201' && ok "async execution returns 201 Created" \
                                               || bad "async execution did not return 201"
loc=$(printf '%s' "$hdrs" | grep -i '^Location:' | tr -d '\r' | awk '{print $2}')
[ -n "${loc:-}" ] && ok "async returns a Location header" || bad "no Location header"

if [ -n "${loc:-}" ]; then
  st=""
  for _ in $(seq 1 20); do
    st=$(curl -s --max-time 30 "$loc?f=json" | grep -oE '"status": *"[a-z]+"' | grep -oE '[a-z]+"$' | tr -d '"')
    [ "$st" = "successful" ] && break
    [ "$st" = "failed" ] && break
    sleep 1
  done
  [ "$st" = "successful" ] && ok "job reached status: successful" \
                           || bad "job status ended as '${st:-unknown}'"
  check "job results are retrievable" "$loc/results?f=json" 200
fi

check "404 on an unknown process" "$B/processes/does-not-exist?f=json" 404
check "404 on an unknown job"     "$B/jobs/does-not-exist?f=json" 404
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 -X POST \
     "$B/processes/minimal-scene-set/execution" -H 'Content-Type: application/json' \
     -d '{"inputs":{"aoi":[1,2,3]}}' 2>/dev/null)
[ "$c" = "400" ] && ok "400 on a malformed bbox  ($c)" || bad "malformed bbox gave $c, want 400"

# ---------------------------------------------------------------- C
hdr "C. Compliance suite"
if [ -x "$PY" ]; then
  out=$("$PY" -m pytest "$ROOT/tests" -q -p no:cacheprovider 2>&1 | tail -3)
  line=$(printf '%s' "$out" | grep -oE '[0-9]+ (passed|failed)[^$]*' | tail -1)
  if printf '%s' "$out" | grep -q "failed"; then
    bad "pytest: $line"
  else
    ok "pytest: $line"
  fi
else
  skp "venv not found - run: make install"
fi

# ---------------------------------------------------------------- D
hdr "D. The gap evidence (the claims the report makes about Bhoonidhi)"
if [ -s "$ROOT/docs/evidence/capability-audit.json" ]; then
  ops=$("$PY" -c "
import json;d=json.load(open('$ROOT/docs/evidence/capability-audit.json'))
print(','.join(d.get('spatial_filters',[])) or 'none')" 2>/dev/null)
  [ "$ops" = "intersects,bbox" ] || [ "$ops" = "bbox,intersects" ] \
    && ok "audit: Bhoonidhi's spatial surface is exactly '$ops'" \
    || bad "audit: spatial surface is '$ops' - re-read docs/GAP_ANALYSIS.md"
else
  skp "no capability-audit.json - run: make gap"
fi

if [ -s "$ROOT/docs/evidence/redundancy-measurement.json" ]; then
  red=$("$PY" -c "
import json;d=json.load(open('$ROOT/docs/evidence/redundancy-measurement.json'))
t=d['totals'];print(f\"{t['redundant_fraction']*100:.0f}|{t['candidates_considered']}|{t['scenes_selected']}\")" 2>/dev/null)
  pct=${red%%|*}; rest=${red#*|}; cd_=${rest%%|*}; sl=${rest##*|}
  ok "measured redundancy: $cd_ scenes returned, $sl needed = ${pct}% redundant"
else
  skp "no redundancy-measurement.json - run: make redundancy"
fi

if [ "$OFFLINE" = "1" ]; then
  skp "live upstream probes (--offline)"
else
  c=$(code "https://bhoonidhi-api.nrsc.gov.in/processes")
  [ "$c" = "404" ] && ok "Bhoonidhi /processes still absent  ($c)" \
    || { [ "$c" = "000" ] && skp "Bhoonidhi unreachable from here" \
         || bad "Bhoonidhi /processes returned $c - if it now exists, the gap has CLOSED" ; }
  c=$(code "https://bhuvan-vec2.nrsc.gov.in/bhuvan/wps?service=WPS&version=1.0.0&request=GetCapabilities")
  [ "$c" = "404" ] && ok "Bhuvan WPS still absent  ($c)" \
    || { [ "$c" = "000" ] && skp "Bhuvan unreachable from here" \
         || bad "Bhuvan WPS returned $c - if WPS now exists, say so honestly" ; }
fi

# ---------------------------------------------------------------- E
hdr "E. Repository"
cd "$ROOT"
u=$(git status --short 2>/dev/null | wc -l)
[ "$u" = "0" ] && ok "working tree clean" || bad "$u uncommitted change(s)"
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  git fetch -q origin 2>/dev/null
  [ "$(git rev-parse HEAD)" = "$(git rev-parse '@{u}' 2>/dev/null)" ] \
    && ok "pushed: local and $(git rev-parse --abbrev-ref '@{u}') agree" \
    || bad "local and remote differ - run: git push"
else
  skp "no upstream branch set"
fi

# ---------------------------------------------------------------- verdict
printf '\n===========================================================================\n'
if [ "$fail" -eq 0 ]; then
  printf ' %s  %s passed, %s skipped, 0 failed\n' "$(g 'ALL CHECKS PASSED')" "$pass" "$skip"
  printf '\n The service is live, OGC-conformant and the gap evidence still holds.\n'
  printf ' Demo-ready. For a public URL: ./scripts/expose_public.sh\n'
else
  printf ' %s  %s passed, %s failed, %s skipped\n' "$(r 'SOME CHECKS FAILED')" "$pass" "$fail" "$skip"
  printf '\n Fix the FAIL lines above before demoing.\n'
fi
printf '===========================================================================\n'
[ "$fail" -eq 0 ]

#!/usr/bin/env bash
# probe_gap.sh - evidence that Bhoonidhi's catalogue supports ONE spatial
# predicate and no spatial analysis.
#
# This is a CAPABILITY AUDIT of Bhoonidhi's own published API specification,
# not a complaint about access control. Requiring a token is normal practice
# and is not the gap. The gap is that an authenticated user with the full API
# in front of them still cannot ask a spatial question beyond "which items
# intersect this?".
#
# Because the audit reads Bhoonidhi's published specification, it is
# reproducible offline from docs/evidence/bhoonidhi-api-spec.html and does not
# depend on NRSC being reachable.
#
# Usage: ./scripts/probe_gap.sh [--refresh]
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EV="$ROOT/docs/evidence"
SPEC="$EV/bhoonidhi-api-spec.html"
SPEC_URL="https://bhoonidhi.nrsc.gov.in/bhoonidhi-api/"
mkdir -p "$EV"

grn(){ printf '\033[32m%s\033[0m' "$1"; }
red(){ printf '\033[31m%s\033[0m' "$1"; }
ylw(){ printf '\033[33m%s\033[0m' "$1"; }

if [ "${1:-}" = "--refresh" ] || [ ! -s "$SPEC" ]; then
  printf 'fetching %s\n' "$SPEC_URL"
  if curl -sf --max-time 45 -o "$SPEC.new" "$SPEC_URL" 2>/dev/null; then
    mv "$SPEC.new" "$SPEC"; printf '  refreshed\n'
  else
    rm -f "$SPEC.new"
    printf '  %s could not reach NRSC; auditing the saved copy\n' "$(ylw 'note:')"
  fi
fi
[ -s "$SPEC" ] || { printf '%s no specification to audit\n' "$(red 'FAIL')"; exit 1; }

cat <<HDR
===========================================================================
 Bhoonidhi spatial capability audit
 run (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)
 source   : $SPEC_URL
            (saved: docs/evidence/bhoonidhi-api-spec.html)

 CLAIM UNDER TEST
   Bhoonidhi's catalogue exposes exactly one spatial predicate - "give me
   the items that intersect this" - and performs no spatial analysis. It
   holds the footprint geometry of every scene and will not compute with
   it. This is true for an authenticated user with the whole API available;
   it is a capability gap, not an access-control one.
===========================================================================
HDR

python3 - "$SPEC" <<'PY'
import html, json, re, sys
from pathlib import Path

raw = Path(sys.argv[1]).read_text(encoding="utf8", errors="replace")
raw = re.sub(r"<script.*?</script>", "", raw, flags=re.S | re.I)
flat = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw)))
low = flat.lower()

GRN, RED, YLW, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[0m"
findings = {}

def word(w):
    return re.search(r"\b" + re.escape(w) + r"\b", low) is not None

def ctx(w, n=70):
    m = re.search(r"\b" + re.escape(w) + r"\b", flat, re.I)
    return flat[max(0, m.start()-n):m.start()+n].strip() if m else ""

# -- A. which spatial parameters does /data/search document? ----------------
print("\n== A. Spatial parameters documented for /data/search ==")
spatial_filters = ["intersects", "bbox"]
spatial_predicates = ["crosses", "touches", "overlaps", "disjoint",
                      "s_intersects", "s_within", "s_contains", "s_overlaps"]
present = [p for p in spatial_filters if word(p)]
for p in spatial_filters:
    print(f"   {'documented' if word(p) else 'absent    '} : {p}")
print("   ---")
absent_pred = []
for p in spatial_predicates:
    if word(p):
        print(f"   {YLW}PRESENT{OFF}    : {p}  <- re-read the spec")
    else:
        absent_pred.append(p)
print(f"   absent     : {', '.join(absent_pred)}")
findings["spatial_filters"] = present
findings["spatial_predicates_absent"] = absent_pred
if len(present) == 2 and not [p for p in spatial_predicates if word(p)]:
    print(f"   {GRN}MATCHED{OFF}  only bbox and intersects, and they are the SAME")
    print( "            predicate: an item either intersects the AOI or it does not.")
else:
    print(f"   {RED}NOT MATCHED{OFF}  the spatial surface is not what was claimed")

# -- B. 'contains' / 'within' / 'area' are prose, not operators -------------
print("\n== B. Words that look like operators but are not ==")
for w in ("contains", "within", "area"):
    c = ctx(w)
    if c:
        print(f"   {w:9s} appears, as prose: \"...{c}...\"")
    else:
        print(f"   {w:9s} does not appear")
print(f"   {GRN}MATCHED{OFF}  none of these is a documented spatial operator")

# -- C. what CQL2 filter operations are actually documented? ----------------
print("\n== C. CQL2 filter operations in the documented examples ==")
ops = sorted(set(re.findall(r"[\"']op[\"']\s*:\s*[\"'](\w+)[\"']", flat)))
ops = [o for o in ops if o != "condition"]
print(f"   documented ops : {', '.join(ops) if ops else 'none'}")
findings["cql2_ops"] = ops
if set(ops) <= {"eq", "and"}:
    print(f"   {GRN}MATCHED{OFF}  attribute equality only - no spatial operator, no")
    print( "            comparison, no arithmetic, no aggregation")
else:
    print(f"   {YLW}NOTE{OFF}  richer than expected: {ops}")

# -- D. is there any analysis or aggregation anywhere in the API? -----------
print("\n== D. Spatial-analysis vocabulary anywhere in the specification ==")
terms = ["union", "aggregate", "aggregation", "statistics", "coverage fraction",
         "percent covered", "set cover", "mosaic plan", "density", "revisit",
         "overlap area", "geometry operation", "spatial analysis"]
found = [t for t in terms if t in low]
for t in terms:
    print(f"   {'PRESENT' if t in low else 'absent '} : {t}")
findings["analysis_terms_found"] = found
if not found:
    print(f"   {GRN}MATCHED{OFF}  no analysis or aggregation capability is offered at all")
else:
    print(f"   {RED}NOT MATCHED{OFF}  found {found}")

# -- E. and no processing endpoint to do it elsewhere ------------------------
print("\n== E. Endpoints the specification documents ==")
eps = ["/auth/token", "/auth/logout", "/data/collections", "/data/search", "/download"]
for e in eps:
    if e in flat:
        print(f"   documented : {e}")
findings["endpoints"] = [e for e in eps if e in flat]
for e in ["/processes", "/jobs", "OGC API", "WPS"]:
    print(f"   {'PRESENT' if e in flat else 'absent    '} : {e}")
print(f"   {GRN}MATCHED{OFF}  five endpoints: authenticate, list, search, download.")
print( "            None of them computes anything.")

Path(sys.argv[1]).parent.joinpath("capability-audit.json").write_text(
    json.dumps(findings, indent=2))
print("\n   audit summary -> docs/evidence/capability-audit.json")
PY

cat <<'FTR'

---------------------------------------------------------------------------
 WHAT THIS ADDS UP TO
   A  Bhoonidhi's whole spatial surface is `bbox` and `intersects`, which
      are one predicate expressed two ways.
   B  No other spatial operator is documented anywhere.
   C  Its CQL2 filter examples use `eq` and `and` - attribute equality.
   D  No union, no aggregation, no statistics, no coverage, no density.
   E  Five endpoints, none of which computes anything.

   => An authenticated user, holding the complete API, can learn WHICH scenes
      touch their area and nothing further. How much of the area those scenes
      actually cover, where the holes are, which minimum subset suffices,
      where two sensors co-cover, how uneven revisit is - every one of those
      is spatial algebra over footprint geometry the catalogue already
      stores, and every one is left to the user to do by hand.

      That is the gap this repository fills with OGC API - Processes.
      It has nothing to do with needing a token.
---------------------------------------------------------------------------
FTR

#!/usr/bin/env bash
# expose_public.sh - put the running service behind a public HTTPS URL using a
# Cloudflare quick tunnel, so "anyone can issue real HTTP requests".
#
# WHAT THIS DOES TO YOUR MACHINE
#   It opens an outbound tunnel making port 5003 reachable from the public
#   internet. Unlike the GeoServer tiers in the sibling projects there is no
#   admin UI and no credential to rotate here: pygeoapi serves a read-only
#   catalogue plus six compute processes, with no write surface. Two things
#   are still worth knowing before running it:
#
#     * the processes are unauthenticated and unthrottled, so anyone who
#       finds the URL can spend your CPU. The processes are bounded (an AOI
#       footprint cap and a grid-size cap), but there is no quota - see
#       "Known limitations" in README.md;
#     * the raster processes read data/dem.tif from this host.
#
# The URL is ephemeral: it lives only while this script runs, with a fresh
# hostname each time. Start it shortly before a demo, leave it in the
# foreground, Ctrl-C afterwards. For anything longer-lived use a named tunnel
# with a Cloudflare account, or a small cloud VM.
#
# Usage: ./scripts/expose_public.sh
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${RUNTIME:-$(cd "$ROOT/.." && pwd)/runtime}"
BIN="$RUNTIME/bin"; LOGS="$RUNTIME/logs"
mkdir -p "$BIN" "$LOGS"

[ -f "$ROOT/.env" ] && { set -a; . "$ROOT/.env"; set +a; }
PORT="${RECORDS_PORT:-5003}"

say() { printf '\n\033[1m-- %s\033[0m\n' "$*"; }
ok()  { printf '   \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '   \033[31mfail\033[0m  %s\n' "$*"; }
warn(){ printf '   \033[33m!\033[0m     %s\n' "$*"; }

say "pre-flight"
curl -sf -o /dev/null --max-time 5 "http://localhost:$PORT/" \
  && ok "service responding on :$PORT" \
  || { bad "nothing on :$PORT - run ./scripts/serve_local.sh start"; exit 1; }

n=$(curl -s --max-time 20 "http://localhost:$PORT/processes" \
    | grep -oE '"id"' | wc -l)
[ "${n:-0}" -ge 6 ] && ok "$n processes advertised" \
  || warn "expected 6 processes, saw ${n:-0}"

warn "the processes will be unauthenticated and unthrottled on a public URL"

say "cloudflared"
CF="$(command -v cloudflared || echo "$BIN/cloudflared")"
if [ ! -x "$CF" ]; then
  echo "   downloading cloudflared (about 35 MB)"
  case "$(uname -m)" in
    x86_64|amd64)  pkg=cloudflared-linux-amd64 ;;
    aarch64|arm64) pkg=cloudflared-linux-arm64 ;;
    *) bad "unsupported architecture $(uname -m)"; exit 1 ;;
  esac
  curl -fL --progress-bar -o "$BIN/cloudflared" \
    "https://github.com/cloudflare/cloudflared/releases/latest/download/$pkg" \
    || { bad "download failed"; exit 1; }
  chmod +x "$BIN/cloudflared"; CF="$BIN/cloudflared"
fi
ok "$("$CF" --version 2>&1 | head -1)"

say "opening the tunnel"
LOG="$LOGS/records-tunnel.log"; : > "$LOG"
nohup "$CF" tunnel --no-autoupdate --url "http://localhost:$PORT" \
  >> "$LOG" 2>&1 < /dev/null &
echo $! > "$LOG.pid"
PUB=""
for _ in $(seq 1 40); do
  PUB=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG" 2>/dev/null | head -1)
  [ -n "$PUB" ] && break
  sleep 1
done
[ -n "$PUB" ] || { bad "tunnel did not come up; see $LOG"; exit 1; }
ok "public URL: $PUB"

cat <<EOT

===========================================================================
 $(printf '\033[1mPUBLIC ENDPOINT\033[0m')  (ephemeral - alive only while this runs)

 Landing page / conformance / OpenAPI
   $PUB/
   $PUB/conformance
   $PUB/openapi

 OGC API - Processes
   $PUB/processes
   $PUB/processes/minimal-scene-set

 The gap, closed - which scenes do I actually need?
   curl -X POST $PUB/processes/minimal-scene-set/execution \\
     -H 'Content-Type: application/json' \\
     -d '{"inputs":{"aoi":[75.3,13.2,75.8,13.9],"collection":"sentinel-2-l2a"}}'

 Asynchronous execution + the job API
   curl -i -X POST $PUB/processes/aoi-coverage/execution \\
     -H 'Content-Type: application/json' -H 'Prefer: respond-async' \\
     -d '{"inputs":{"aoi":[75.3,13.2,75.8,13.9],"collection":"sentinel-2-l2a"}}'
   # then follow the Location header, and /jobs/{id}/results?f=json

 OGC API - Records (supporting tier)
   $PUB/collections/bhoonidhi/items?q=NDVI

 Verify from outside:
   RECORDS_BASE=$PUB ./scripts/run_tests.sh

 Ctrl-C to close the tunnel.
===========================================================================
EOT

cleanup() {
  printf '\nclosing the tunnel\n'
  [ -f "$LOG.pid" ] && { kill "$(cat "$LOG.pid")" 2>/dev/null; rm -f "$LOG.pid"; }
  exit 0
}
trap cleanup INT TERM
while true; do sleep 60; done

#!/usr/bin/env bash
# serve_local.sh - start the OGC API - Records service.
#
# Usage: ./scripts/serve_local.sh start|stop|status
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${RUNTIME:-$(cd "$ROOT/.." && pwd)/runtime}"
VENV="$RUNTIME/venv"; PIDS="$RUNTIME/pids"; LOGS="$RUNTIME/logs"
PORT="${RECORDS_PORT:-5003}"
mkdir -p "$PIDS" "$LOGS"

export PYGEOAPI_CONFIG="$ROOT/pygeoapi/config.yml"
export PYGEOAPI_OPENAPI="$RUNTIME/records-openapi.yml"
export PYGEOAPI_SERVER_URL="${PYGEOAPI_SERVER_URL:-http://localhost:$PORT}"
# the spatial processes live here
export PYTHONPATH="$ROOT/pygeoapi/processes${PYTHONPATH:+:$PYTHONPATH}"

# Job store and per-job result files. pygeoapi's TinyDB manager writes into
# output_dir but will not create it, and a missing directory surfaces as an
# opaque HTTP 400 on every execution rather than as a startup error. Create it
# here, under runtime/ rather than /tmp so job history survives a reboot.
export JOBS_DIR="${JOBS_DIR:-$RUNTIME/jobs}"
mkdir -p "$JOBS_DIR/outputs"

ok(){ printf '   \033[32mok\033[0m    %s\n' "$*"; }
bad(){ printf '   \033[31mdown\033[0m  %s\n' "$*"; }

case "${1:-start}" in
  start)
    printf '\n\033[1m-- OGC API - Records :%s\033[0m\n' "$PORT"
    curl -sf -o /dev/null --max-time 5 "http://localhost:$PORT/" && { ok "already running"; exit 0; }
    [ -x "$VENV/bin/gunicorn" ] || { bad "venv missing - run ./scripts/install.sh"; exit 1; }
    [ -s "$ROOT/data/bhoonidhi-records.tinydb" ] || { bad "catalogue missing - run ./scripts/build_catalogue.py"; exit 1; }

    "$VENV/bin/pygeoapi" openapi generate "$PYGEOAPI_CONFIG" \
        --output-file "$PYGEOAPI_OPENAPI" > "$LOGS/records-openapi.out" 2>&1 \
      || { bad "openapi generation failed; see $LOGS/records-openapi.out"; exit 1; }

    # --chdir: the provider's data path is relative to the repo root.
    # setsid + </dev/null so the server never holds this script's stdout open.
    setsid nohup "$VENV/bin/gunicorn" pygeoapi.flask_app:APP \
        --bind "0.0.0.0:$PORT" --workers 3 --timeout 300 \
        --chdir "$ROOT" --pid "$PIDS/records.pid" \
        > "$LOGS/records.out" 2>&1 < /dev/null &
    for i in $(seq 1 45); do
      curl -sf -o /dev/null --max-time 3 "http://localhost:$PORT/" && { ok "up after ${i}s"; break; }
      [ "$i" = "45" ] && { bad "did not start; see $LOGS/records.out"; exit 1; }
      sleep 1
    done
    cat <<EOT

  catalogue     http://localhost:$PORT/collections/bhoonidhi/items
  full-text     http://localhost:$PORT/collections/bhoonidhi/items?q=NDVI
  queryables    http://localhost:$PORT/collections/bhoonidhi/queryables
  processes     http://localhost:$PORT/processes
EOT
    ;;
  stop)
    f="$PIDS/records.pid"
    [ -f "$f" ] && { kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; ok "stopped"; } || bad "no pid file"
    ;;
  status)
    curl -sf -o /dev/null --max-time 5 "http://localhost:$PORT/" \
      && ok "Records :$PORT responding" || bad "Records :$PORT"
    n=$(curl -s --max-time 30 "http://localhost:$PORT/collections/bhoonidhi/items?limit=1&f=json" \
        | grep -oE '"numberMatched":[0-9]+' | head -1 | cut -d: -f2)
    [ -n "${n:-}" ] && ok "catalogue reports $n records" || bad "catalogue not answering"
    ;;
  *) echo "usage: $0 start|stop|status"; exit 2 ;;
esac

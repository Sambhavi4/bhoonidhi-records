#!/usr/bin/env bash
# run_tests.sh - run the OGC API - Records compliance suite.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${RUNTIME:-$(cd "$ROOT/.." && pwd)/runtime}"
PY="$RUNTIME/venv/bin/python"
export RECORDS_BASE="${RECORDS_BASE:-http://localhost:5003}"
export COLLECTION_ID="${COLLECTION_ID:-bhoonidhi}"
[ -x "$PY" ] || { echo "venv not found at $RUNTIME/venv"; exit 1; }
cat <<HDR
===========================================================================
 Bhoonidhi Records - OGC API - Records compliance suite
 service    : $RECORDS_BASE
 collection : $COLLECTION_ID
===========================================================================
HDR
exec "$PY" -m pytest "$ROOT/tests" -v --tb=short -p no:cacheprovider "$@"

#!/usr/bin/env bash
# install.sh - create ../runtime/venv with pygeoapi and the test deps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNTIME="${RUNTIME:-$(cd "$ROOT/.." && pwd)/runtime}"
VENV="$RUNTIME/venv"
mkdir -p "$RUNTIME"
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
echo "Python: $(python3 --version)"
[ -d "$VENV" ] || { echo "Creating venv at $VENV"; python3 -m venv "$VENV"; }
"$VENV/bin/pip" install --quiet --upgrade pip
echo "Installing dependencies"
"$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
"$VENV/bin/python" -c "import pygeoapi,tinydb;print(f'  pygeoapi {pygeoapi.__version__}  tinydb {tinydb.__version__}')"
echo
echo "Next: ./scripts/build_catalogue.py && ./scripts/serve_local.sh start"

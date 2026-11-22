#!/usr/bin/env bash
# Run Prism from source as one build flavour, in a sandbox home.
#   devtools/run_flavour.sh <complete|studio|sales|engineering> [main.py args]
# HOME becomes ~/prism-flavour-sandbox/<flavour>, so the real ~/.prism is never
# touched. OFFLINE_DEV means no licence server and no Pulse traffic.
set -eu
f="${1:-}"
case "$f" in complete|studio|sales|engineering) shift ;;
  *) echo "usage: $0 <complete|studio|sales|engineering> [args]" >&2; exit 2 ;;
esac
root="$(cd "$(dirname "$0")/.." && pwd)"
real="$HOME"
sandbox="$HOME/prism-flavour-sandbox/$f"
mkdir -p "$sandbox"
PY="${PRISM_PYTHON:-/home/parth-soni/alphakore/prism+gui/prism_gui/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
cd "$root"
unset GTK_PATH GIO_MODULE_DIR GTK_EXE_PREFIX GTK_IM_MODULE_FILE GSETTINGS_SCHEMA_DIR GTK_MODULES LOCPATH
exec env HOME="$sandbox" PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$real/.cache/ms-playwright}" PRISM_FLAVOUR="$f" PRISM_LICENSE_OFFLINE_DEV=1 \
  PRISM_HOME="$sandbox/.prism-dev" "$PY" main.py "$@"

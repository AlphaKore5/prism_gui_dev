#!/usr/bin/env bash
# Run Prism from source as one build flavour, in a sandbox home.
#   devtools/run_flavour.sh <complete|studio|sales|engineering> [main.py args]
# HOME becomes ~/prism-flavour-sandbox/<flavour>, so the real ~/.prism is never
# touched.
#
# Licence: unless the sandbox already holds a valid one, `mint.py flavour`
# writes a 30-day dev licence for this flavour's features (core plus the
# feature of each add-on in addons/flavours/<flavour>.py), signed with the dev
# key (kid dev2 in licensing/keys.py, trusted from source only, never by a
# frozen build). While that dev licence is in force PRISM_LICENSE_SERVER points
# at a closed local port, so no real licence or AI server is contacted. The key
# is devtools/dev-signing-key.hex here or in the main checkout (gitignored), or
# PRISM_DEV_SIGNING_KEY. Without it the app starts unlicensed, as before.
#
# PRISM_LICENSE_OFFLINE_DEV=1 mints nothing: it only lets a source run treat
# "licence server unreachable" as "allowed" for features the licence on disk
# already has. Pulse sends nothing from source unless PRISM_PULSE=1.
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

key="${PRISM_DEV_SIGNING_KEY:-$root/devtools/dev-signing-key.hex}"
if [ -z "${PRISM_DEV_SIGNING_KEY:-}" ] && [ ! -f "$key" ]; then  # a git worktree: the main checkout's
  common="$(git -C "$root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  [ -n "$common" ] && [ -f "$(dirname "$common")/devtools/dev-signing-key.hex" ] \
    && key="$(dirname "$common")/devtools/dev-signing-key.hex"
fi
srv=""
if [ ! -f "$key" ]; then
  echo "run_flavour: no dev signing key at $key, so no dev licence is minted; Prism will ask for a licence key as before." >&2
else
  lic="$(env HOME="$sandbox" PRISM_HOME="$sandbox/.prism-dev" PRISM_DEV_SIGNING_KEY="$key" \
    "$PY" devtools/mint.py flavour --flavour "$f" --days 30 | tail -n 1)" || lic=""
  case "$lic" in
    minted|dev) srv="http://127.0.0.1:9" ;;
    real) echo "run_flavour: the sandbox holds a production-signed licence; using the real licence server." >&2 ;;
    *) echo "run_flavour: minting a dev licence failed (see above); Prism will ask for a licence key as before." >&2 ;;
  esac
fi

exec env HOME="$sandbox" PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$real/.cache/ms-playwright}" PRISM_FLAVOUR="$f" PRISM_LICENSE_OFFLINE_DEV=1 \
  ${srv:+PRISM_LICENSE_SERVER="$srv"} PRISM_HOME="$sandbox/.prism-dev" "$PY" main.py "$@"

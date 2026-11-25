#!/bin/bash
# Prepares one macOS CI job on our own Mac (docs/MAC_BUILD_RUNNER.md): a fresh
# Python 3.12 environment, and PortAudio for PyAudio. Used by build.yml
# (build-macos) and macos-pins.yml, so both install the same way.
#
# No Homebrew on purpose. A Homebrew library is built for the macOS version of
# the machine it is installed on, so the app would not run on older Macs.
set -euo pipefail

: "${MACOSX_DEPLOYMENT_TARGET:?set it in the workflow}"
: "${RUNNER_TEMP:?}" "${GITHUB_ENV:?}" "${GITHUB_PATH:?}"

fail() { echo "::error::$1 See docs/MAC_BUILD_RUNNER.md, part 2."; exit 1; }

[ "$(uname -m)" = arm64 ] || fail "This is not an Apple Silicon Mac (or the runner runs under Rosetta)."
xcode-select -p >/dev/null 2>&1 || fail "The Xcode Command Line Tools are missing."

PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12
[ -x "$PY" ] || fail "Python 3.12 from python.org is missing ($PY)."

# The machine is kept between runs (a GitHub runner is thrown away), so every
# run gets its own environment: nothing left by the last run can end up in the app.
VENV="$RUNNER_TEMP/prism-venv"
rm -rf "$VENV"
"$PY" -m venv "$VENV"
echo "$VENV/bin" >> "$GITHUB_PATH"

# PyAudio has no ready-made Mac build and needs PortAudio. Built once, kept.
# Same source and checksum as Homebrew's portaudio formula.
PA_URL=https://files.portaudio.com/archives/pa_stable_v190700_20210406.tgz
PA_SHA=47efbf42c77c19a05d22e627d42873e991ec0c1357219c0d74ce6a2948cb2def
PA="$HOME/prism-ci-libs/portaudio-19.7.0-macos$MACOSX_DEPLOYMENT_TARGET"
if [ ! -f "$PA/.done" ]; then
  WORK="$RUNNER_TEMP/portaudio"
  rm -rf "$WORK" "$PA"
  mkdir -p "$WORK"
  curl -fsSL --retry 3 -o "$WORK/pa.tgz" "$PA_URL"
  echo "$PA_SHA  $WORK/pa.tgz" | shasum -a 256 -c -
  tar xzf "$WORK/pa.tgz" -C "$WORK"
  ( cd "$WORK/portaudio"
    ./configure --prefix="$PA" --enable-mac-universal=no
    make install )
  cp "$WORK/portaudio/include/pa_mac_core.h" "$PA/include/"   # PyAudio needs it
  touch "$PA/.done"
fi

{
  echo "CFLAGS=-I$PA/include"
  echo "LDFLAGS=-L$PA/lib"
  echo "ARCHFLAGS=-arch arm64"   # python.org's Python would also build for Intel
} >> "$GITHUB_ENV"
"$VENV/bin/python" -V
sw_vers

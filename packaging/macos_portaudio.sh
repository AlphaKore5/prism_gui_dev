#!/bin/bash
# Builds PortAudio for a macOS CI job; PyAudio has no ready-made Mac build and
# needs it. Used by build.yml (build-macos) and macos-pins.yml.
#
# Not `brew install portaudio`: a Homebrew library is built for the macOS version
# of the machine it is installed on (15 on the runner), and the app promises 14.
set -euo pipefail

: "${MACOSX_DEPLOYMENT_TARGET:?set it in the workflow}"
: "${RUNNER_TEMP:?}" "${GITHUB_ENV:?}"

# Same source and checksum as Homebrew's portaudio formula.
URL=https://files.portaudio.com/archives/pa_stable_v190700_20210406.tgz
SHA=47efbf42c77c19a05d22e627d42873e991ec0c1357219c0d74ce6a2948cb2def
PREFIX="$RUNNER_TEMP/portaudio-installed"
WORK="$RUNNER_TEMP/portaudio-build"
mkdir -p "$WORK"
curl -fsSL --retry 3 -o "$WORK/pa.tgz" "$URL"
echo "$SHA  $WORK/pa.tgz" | shasum -a 256 -c -
tar xzf "$WORK/pa.tgz" -C "$WORK"
( cd "$WORK/portaudio"
  ./configure --prefix="$PREFIX" --enable-mac-universal=no
  make install )
cp "$WORK/portaudio/include/pa_mac_core.h" "$PREFIX/include/"   # PyAudio needs it

{
  echo "CFLAGS=-I$PREFIX/include"
  echo "LDFLAGS=-L$PREFIX/lib"
  echo "ARCHFLAGS=-arch arm64"   # python.org's Python would also build for Intel
} >> "$GITHUB_ENV"

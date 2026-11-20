# constraints/ — exact library versions per platform

`pip install -r requirements.txt -c constraints/<platform>.txt` installs the
versions listed here and nothing newer. CI does this for every build and test
job. A missing file for a platform fails the job, on purpose.

## Why

Until 1.8.9 none of the 31 lines in `requirements.txt` was pinned, so every
release installed whatever was newest that day. Measured on the real update
manifests: updating 1.8.6 -> 1.8.9 meant fetching 207 MB, of which **163 MB was
third-party libraries that changed on their own** (av 64 MB, ctranslate2 61 MB,
PySide6 22 MB, hf_xet, tokenizers, faster-whisper). A code-only release should
fetch about 35-40 MB, and a library should never change without a decision.

## Files

| File | Built from |
|---|---|
| `windows-x64.txt` | the `Successfully installed` lines of the Windows (x64) build job, CI run 44719386793 (the 1.8.9 build) |
| `linux-x64.txt` | the same, Linux (x64) job |
| macOS | none yet: the macOS build is deferred in CI. Create `macos-arm64.txt` the same way, and add `pins:` to the matrix, before turning that leg back on |

## Changing a library on purpose

1. Edit the version in the platform files (both, unless it is platform-only).
2. Say why in the commit, and name the release that carries it. A library
   change makes that release's update large: `devtools/release_all.py` prints the
   download size for a client one version behind; expect it to jump.
3. Run the full suite on Windows CI before releasing.

## What this does not do

Versions are pinned, not hashes: a yanked or replaced PyPI file would still be
a surprise. Hash-pinning (`pip install --require-hashes`) is the next step and
needs per-platform wheel hashes. `PyAudio` is installed separately (optional) and
is not pinned here.

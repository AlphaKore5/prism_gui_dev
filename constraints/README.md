# constraints/ — exact library versions per platform

`pip install -r requirements.txt -c constraints/<platform>.txt` installs the
versions listed here and nothing newer. CI does this for every build and test
job. A missing file for a platform fails the job, on purpose.

## Why

Until 1.8.9 none of the 31 lines in `requirements.txt` was pinned, so every
release installed whatever was newest that day, so a library could change
without anyone choosing it. (An earlier version of this note said the 207 MB
1.8.6 -> 1.8.9 update was mostly libraries drifting. That was wrong: measured on
the real manifests, 179 of the 190 changed Windows files were new, added by the
speech feature, and no existing library changed version. Pinning would not have
made that update smaller; it protects later releases.) A library should never
change without a decision.

## Files

| File | Built from |
|---|---|
| `windows-x64.txt` | the `Successfully installed` lines of the Windows (x64) build job, CI run 44719386793 (the 1.8.9 build) |
| `linux-x64.txt` | the same, Linux (x64) job |
| `macos-arm64.txt` | none yet, and the macOS build job fails until it exists. Recorded on our own Mac by the workflow "Record macOS pin file" (docs/MAC_BUILD_RUNNER.md, part 5); it cannot be written on Linux, the Mac wheels differ |

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

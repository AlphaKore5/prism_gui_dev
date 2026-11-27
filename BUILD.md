# Packaging Prism as a desktop app

Prism ships as a normal double-clickable application on Linux, Windows and
macOS. This file covers how the builds are made and what users have to do with
them. If you only want to *run* Prism from source, see README.md.

---

## What users download

| Platform | Artifact | How they run it |
|---|---|---|
| Linux | `Prism-<version>-linux-x64.tar.gz`, plus `Prism-<version>-x64.AppImage` (`Prism-<flavour>-<version>-x64.AppImage` for Sales, Studio, Engineering) | Extract and run `./install.sh`, or `chmod +x` the AppImage and double-click |
| Windows | `Prism-<version>-windows-x64.zip` | Extract anywhere, run `Prism.exe` |
| macOS | `Prism-<version>-macos-<arch>.dmg` | Open, drag Prism to Applications |

All three are **portable** — no installer, no admin rights, nothing written
outside the folder and `~/.prism`.

### Two things every user still needs

1. **Google Chrome.** Prism drives your real, logged-in Chrome to operate the
   AI tools. It is not bundled (it is a browser, and Google's licence doesn't
   allow redistribution). Prism says so on first run if it can't find it.
2. **PortAudio, only for voice.** Wake word and push-to-talk need PyAudio,
   which needs a system PortAudio library. Every other feature works without
   it; the voice buttons explain what's missing rather than failing silently.

---

## The builds are unsigned

Signing certificates cost money per year (Apple Developer Program, an OV/EV
code-signing cert for Windows), so the artifacts are unsigned. Both OSes will
warn on first launch. This is expected, and it is worth telling your users up
front, because the warnings look like malware alerts:

**macOS** — "Prism can't be opened because Apple cannot check it for malicious
software."
> Right-click (or Control-click) Prism.app → **Open** → **Open**. Once per
> install. **macOS 15 (Sequoia) and newer** removed that Open button: close the
> dialog, then System Settings → Privacy & Security → scroll down → **Open
> Anyway** next to Prism. If macOS instead claims the app "is damaged and
> can't be opened", that is the quarantine flag on a downloaded unsigned app:
> `xattr -dr com.apple.quarantine /Applications/Prism.app`
>
> Also: the build is **Apple Silicon only**. It will not open on an Intel Mac.

The pipeline is ready to sign the moment the credentials exist — every step
(`packaging/codesign.py`: Developer ID + hardened runtime, notarytool,
stapler, and the .dmg itself) runs automatically when the secrets listed in
`.github/workflows/build.yml` under "Import the macOS signing certificate"
are set on the repository. Nothing else to flip.

**Windows** — "Windows protected your PC" (SmartScreen).
> **More info** → **Run anyway**.

**Linux** — no warning; nothing to do.

To sign later, the hooks are already in `packaging/prism.spec`
(`codesign_identity`, `entitlements_file`) and the macOS bundle already carries
the `NSMicrophoneUsageDescription` that notarization requires.

---

## Building it yourself

**PyInstaller cannot cross-compile.** The OS you build on is the OS you get —
a Linux machine cannot produce a `.exe` or a `.dmg`. That is why CI builds all
three targets (Linux, Windows, Apple Silicon Mac) on their own runners. There
is no Intel Mac target — see the matrix comment in
`.github/workflows/build.yml`.

```bash
git clone --recurse-submodules https://github.com/HitarthTrivedi/prism_gui.git
cd prism_gui
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r packaging/requirements-build.txt
python packaging/build.py --clean
```

Output lands in `dist/`. Useful flags:

| Flag | Effect |
|---|---|
| `--clean` | wipe `build/` and `dist/` first (do this after changing the spec) |
| `--no-archive` | stop after `dist/Prism` — faster when iterating |

**Use Python 3.11 or 3.12.** 3.13 removed the stdlib `audioop` module that the
wake word uses (the build still works, voice is just disabled unless you also
install `audioop-lts`), and PySide6 wheels lag new releases.

### Verifying a build

```bash
python packaging/smoke_test.py
```

This runs the **built executable** with `PRISM_SELFTEST=1` and checks that the
stylesheet, fonts, logo, SVG icon engine, engine package, notes files and the
main window all survived bundling — then exits. A build that merely *completes*
proves nothing: one missed hidden import produces a clean build that dies on
double-click, with no console to show the traceback. CI runs this on every
platform and fails the job if it doesn't pass.

---

## CI

`.github/workflows/build.yml` builds on push to main, on pull requests, and on
tags.

**To cut a release:**
```bash
git tag v1.0.0 && git push origin v1.0.0
```
That builds all four targets, smoke-tests each, and publishes a GitHub Release
with the artifacts and the unsigned-app instructions above. Untagged pushes
just attach the artifacts to the run for 14 days.

Note `submodules: recursive` in the checkout step — `prism_terminal` is a
submodule, and without it the engine is an empty directory and the build fails
in `preflight()` with a clear message rather than mysteriously later.

Linux is deliberately built on **ubuntu-22.04**, not `ubuntu-latest`: binaries
link against the build machine's glibc and cannot run on anything older, so the
oldest supported runner gives the widest compatibility.

---

## How the packaging works

```
packaging/
  build.py                 orchestrator: icons → PyInstaller → archive
  prism.spec               the PyInstaller recipe (all three OSes)
  make_icons.py            renders .png/.ico/.icns from assets/prism-logo.svg
  smoke_test.py            runs the built app and checks it starts
  install.sh               Linux: desktop entry + `prism` command
  requirements-build.txt   build-time-only dependencies
  icons/                   generated — safe to delete, rebuilt every build
```

Three decisions worth knowing about before you change anything:

**onedir, not onefile.** undetected-chromedriver downloads and *patches* a
chromedriver binary at runtime. A onefile bundle re-extracts to a fresh temp
directory on every launch, so every run would re-download the driver and throw
the patched copy away. onedir also starts faster and gets scanned by antivirus
once rather than per launch.

**The engine ships as data, not code.** `prism_terminal/` is copied into the
bundle verbatim and put on `sys.path` at runtime by `core_bridge.py` — the same
mechanism as a source checkout. It also keeps `pros_cons.txt` and
`tool_notes.md` readable, which `router._tool_notes()` reads off disk.

**Read-only vs. user state.** Anything bundled is reached through
`paths.resource()`; anything the user owns lives in `~/.prism` via
`paths.user_dir()`. The packaged app and the CLI therefore share one config,
one run history and one Chrome profile — installing the app doesn't orphan an
existing CLI setup.

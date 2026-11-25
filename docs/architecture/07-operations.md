# 7 · Operations

[← Add-ons](06-addons.md) · [Index](README.md) · [Next: State & roadmap →](08-state-and-roadmap.md)

---

Building, releasing, testing, configuring and debugging. `BUILD.md`,
`SHIPPING.md` and `RUNNING.md` are the full procedures; this is the operational
map and the failure modes.

---

## 7.1 Running from source

```bash
git clone --recurse-submodules https://github.com/HitarthTrivedi/prism_gui.git
cd prism_gui
pip install -r requirements.txt
python3 main.py
```

Already cloned without `--recurse-submodules`? Run `git submodule update --init`
once.

> **Without the submodule the engine is an empty directory** and nothing works.
> The CI workflow explains this in its own failure message because the git error
> ("not our ref `<sha>`") cost a debugging session once already.

First launch opens the licence screen, then Setup (API key, profile, one agent
per category, Chrome version) if `~/.prism/config.json` is not already
configured from the CLI.

**You also need Google Chrome installed**, since Prism drives it directly.

---

## 7.2 Dependencies

| Package | Needed for | Optional? |
|---|---|---|
| `PySide6>=6.5.0` | The entire UI | **No** |
| `requests` | Groq, licence server | **No** |
| `cryptography` | Ed25519 verification | **No** |
| `certifi` | TLS roots in a frozen build | **No** |
| `setuptools`, `packaging` | Runtime helpers | **No** |
| `selenium>=4.0.0`, `undetected-chromedriver` | Browser automation | Probed by `automation_available()` |
| `ezdxf` (pulls `numpy`) | BOQ reads DXF geometry | Probed by `boq_available()` |
| `shapely` | Gerber spacing / copper geometry | **Optional** — four of five numbers still work without it, and the missing one says so |
| `pillow` | Reel draws every frame with PIL | Probed by `reel_available()` |
| `imageio-ffmpeg` | Reel encode — **ships inside the build** | Downloaded + SHA-256 verified if missing |
| `openpyxl` | Reading `.xlsx` rate lists | Degrades to CSV only |
| `pypdf`, `python-docx` | Reading purchase orders | Degrades to an honest refusal |
| `pyaudio` | Microphone capture | Voice disabled without it |
| `dnspython` | MX lookup for mail host discovery | Falls back to guessed hosts |
| `keyring` | OS credential store for the licence key | Falls back to the 0600 file |
| `gerbonara` | **Test-only** cross-check of the Gerber parser | Never a runtime dependency |

**Python 3.12, deliberately.** 3.13 removed the stdlib `audioop` that the wake
word uses, and PySide6 wheels lag the newest release.

---

## 7.3 Build and release

`packaging/` — `prism.spec`, `build.py`, `codesign.py`, `make_icons.py`,
`smoke_test.py`, `install.sh`, `entitlements.plist`, two PyInstaller runtime
hooks (`rthook_distutils.py`, `rthook_ssl_certs.py`).

### CI — `.github/workflows/build.yml`

**PyInstaller cannot cross-compile**, so each OS builds on its own runner.

| Runner | Target | Note |
|---|---|---|
| `ubuntu-22.04` | Linux x64 | Oldest supported glibc — binaries built against a newer libc cannot run on older systems |
| `windows-latest` | Windows x64 | |
| `macos-15` | macOS Apple Silicon | Job `build-macos`, not a leg of the matrix: unsigned workflow artifact for testers, never published by CI, oldest macOS 14 |
| ~~`macos-15-intel`~~ | **Dropped** | Built fine but failed its smoke test, and `release` needs the whole matrix — one red leg blocks the publish for every platform. The machines this is going to are Apple Silicon |

> **An arm64 `.dmg` will NOT run on an Intel Mac** — there is no Rosetta path
> for it, the app simply will not open. To support one, add `macos-15-intel`
> back (GitHub offers that image until Aug 2027) and fix the smoke-test failure
> it surfaces.

`fail-fast: false` — a broken macOS build should not hide a good Windows one.

**Triggers:** push to `main`/`master`, any `v*` tag, pull requests, manual
dispatch. **A tag publishes a release; anything else leaves artifacts attached
to the run.**

**`submodules: recursive` is mandatory** in the checkout step.

### The submodule push trap

If `prism_gui` pins `prism_terminal` to a commit that was never pushed, CI
checkout fails. The fix:

```bash
cd prism_terminal && git push origin HEAD:main
```

The workflow prints this as an error annotation on checkout failure.

### Distribution

Portable, no installer — nothing written outside the app folder and `~/.prism`.
Grab the build for your OS from Releases. First launch on macOS needs the
unsigned-app step (`GETTING_STARTED.md` — the doc to hand a non-technical user).

---

## 7.4 Tests

```bash
python3 -m pytest tests/ -q --deselect \
  "tests/test_gates.py::TaskQueue::test_each_task_is_planned_in_turn"

python3 -m devtools.scenarios        # 148 end-to-end scenario checks
python3 devtools/inbox_demo.py       # the inbox pipeline on sample mail
```

**1,203 tests collected** as of commit `20292f4`, plus the 148 scenarios.

> The repo `README.md` says "705 tests" and the file listing at its foot says
> "588" — **both are stale.** Worth correcting when the README is next touched.

**Nothing in either suite touches the network.** IMAP and Groq are both faked,
because a test that needs a mail server is a test nobody runs.

### The one deselect is not decoration

`test_each_task_is_planned_in_turn` builds a real `MainWindow`, which reaches
for the licence server, and it **hangs rather than failing** — so a plain
`pytest tests/` appears to freeze.

It is pre-existing and unrelated to any recent work; it hangs on a clean tree at
older commits too. **Left in place rather than quietly deleted, because a
hanging test is a real problem and deleting it would only hide it.**

### Do NOT export `PRISM_LICENSE_OFFLINE_DEV=1` to run the suite

Full reasoning in [05-licensing.md §5.11](05-licensing.md#511-development-and-testing).
Short version: it changes the *answer*, never the round trip, so it cannot make
a hanging test finish — but it **does** open a production bypass underneath the
revocation test, whose failure was read as known contamination for months.
`tests/conftest.py` now strips it per test.

### Test file map

| Area | Files |
|---|---|
| Email automation | `test_mailflow.py` (1,674), `test_email_automation.py`, `test_inbox_fetch.py`, `test_mail_end_to_end.py`, `test_inquiry_is_never_lost.py`, `test_sorting_precision.py`, `test_document_handoff.py` |
| Inquiry UI | `test_inquiry_ui.py` (1,470), `test_inquiry_screen.py`, `test_register_table.py` |
| Gerber | `test_gerber.py` (974), `test_gerber_dialog.py`, `gerber_samples.json` |
| Licensing | `test_authorization.py` (777), `test_licensing.py`, `test_licensing_endpoint.py`, `test_licence_safe_modules.py`, `test_secrets.py`, `test_gates.py` |
| Reel | `test_reel_capture.py`, `test_reel_dialog.py`, `test_scene_by_scene.py`, `test_ffmpeg.py`, `test_canva.py` |
| Engine / platform | `test_apollo.py`, `test_cuts.py`, `test_intent.py`, `test_failover.py`, `test_resilience.py`, `test_run_timeline.py`, `test_chrome_profile.py` |
| App | `test_ux.py`, `test_roles.py`, `test_i18n.py`, `test_support.py`, `test_dashboard_data.py` |

---

## 7.5 Environment variables

| Variable | Honoured | Effect |
|---|---|---|
| `PRISM_LICENSE_SERVER` | **Source only** | Point at a staging licence server. A frozen build ignores it — an env var that redirected a release build would be the backdoor this design exists not to have |
| `PRISM_LICENSE_OFFLINE_DEV` | **Source only** | Grant offline when the server is *unreachable*. Fires on a connection failure only — a server that answers "no" has not failed |
| `PRISM_SELFTEST` | Always | Run `main._selftest(app)` and exit with its code — proves a packaged build is whole |
| `PRISM_SERVER_URL` | Tests | The fake licence server in the test suite |
| `PRISM_NET_TESTS` | Tests | Opt into tests that would touch the network |
| `PRISM_SLOW_TESTS` | Tests | Opt into slow tests |
| `PRISM_FFMPEG` | Always | Point at a specific FFmpeg binary |
| `PRISM_GOOGLE_CLIENT` | Always | Google Drive client credentials |
| `PRISM_OWN_PROMPT` | Always | Override the engineered prompt (development) |
| `PRISM_EFFECTS`, `PRISM_SHADOWS` | Always | UI effect toggles |
| `PRISM_BUILD_ENGINE` | Build | Which engine to package with |

---

## 7.6 Configuration surface — where a setting actually lives

| Setting | Set in | Stored |
|---|---|---|
| Groq API key | Setup → API key | `cfg["api_key"]` |
| What you do (profile) | Setup → Profile | `cfg["profile"]` |
| One agent per category | Setup → Agents | `cfg["agents"]` |
| Chrome version / profile | Setup → Chrome | `cfg["chrome_version"]`, `cfg["chrome_profile"]` |
| Interface language | Settings → Language | `cfg["language"]` |
| AI output language | Settings → Language | `cfg["output_language"]` — **set separately on purpose**: a Gujarati-speaking owner may well want the output in English |
| Your role | Settings → Your role | designation key → `cfg["designation"]` |
| Workspace root | Settings | `cfg["workspace_root"]` |
| Sending account | Email add-on first run | `cfg["email"]` |
| Mailboxes, register folder, rate list, terms, who's-who | Email automation → Setup | `cfg["inquiry"]` |
| Licence | Rail → Licence | `~/.prism/license.json` + OS credential store |
| Favourites | Star a file | `~/.prism/gui_favorites.json` |

---

## 7.7 Diagnostics and failure modes

### Crash logs

`diagnostics.install()` sends crashes to `~/.prism/logs`, **because a windowed
build has no console to print to**. `problem_dialog.py` offers the diagnostics
file when something goes wrong.

### Check logging

`core/checklog.py` writes one line per email-automation check to
`~/.prism/logs` — start, stop reason, and a done line with counts and elapsed
time. This is the first place to look when a customer says "it didn't pick up my
mail".

### The error contract

`friendly.py` turns every error a customer can see into three things: **what
happened in five words, one or two sentences of plain English, and the numbered
things to try.**

> **Never show someone a problem without showing them the next action.** A
> message with no action is a phone call.

### Failure catalogue

| Symptom | Likely cause | Where to look |
|---|---|---|
| `pytest tests/` appears to freeze | The known hanging test | Add the deselect (§7.4) |
| CI checkout fails, "not our ref" | Submodule pinned to an unpushed commit | `cd prism_terminal && git push origin HEAD:main` |
| `/gerber` says "Unknown command" | Running the **stale sibling** checkout, not the submodule | `docs/AFTER_THE_MERGE.md` §5 — two checkouts of one repo is a trap |
| Edits to `prism_terminal` have no effect | Same cause. `core_bridge` prints a note naming both paths | `core_bridge._warn_about_sibling()` |
| App will not open, licence screen loops | Server unreachable and no lease covers it. **There is no offline fallback by design** | The message names the server address |
| Revocation test fails on `True is not false` | `PRISM_LICENSE_OFFLINE_DEV` leaked into the environment | Unset it |
| "Close it in Excel" on every check | The register is open | Genuine; close Excel |
| One mailbox stops being checked | Repeated auth failure — the timer gives up deliberately, so Prism does not lock the account | `_maybe_stop_timer()`, `_note_failure()` |
| First check returns old newsletters | Pre-`floor_uid` behaviour | Should not recur; `State.floor_uid` fixed it |
| Chrome will not start after a crash | `SingletonLock` left behind | `automation._clear_profile_locks()` handles it; check it ran |
| Nothing is copied from the real Chrome profile | Chrome has no profile called "Default" | `cfg["chrome_profile"]`; `preferred_profile()` |
| A stage returns the prompt back | The tool echoed it | `_is_prompt_echo()` rejects it; failover retries elsewhere |
| Icons missing from the stylesheet | A Windows backslash inside QSS `url()` is read as an escape | `main.py` posix-separates the assets path |
| First widgets on the wrong font | `theme.load_fonts()` ran late | It must be before the first widget |
| Untranslated UI | `i18n.start()` ran after a widget was built | It must patch Qt first |

---

## 7.8 Development tools — `devtools/` (never shipped)

| Tool | Does |
|---|---|
| `mint.py` | Mint licence keys and designation keys locally (`install --features …`) |
| `scenarios.py` | 148 end-to-end scenario checks |
| `inbox_demo.py` | Run the inbox pipeline over sample mail |
| `demo_register.py` | Generate a demo register |
| `extract_strings.py` | Pull translatable strings for `lang/` |
| `dev-signing-key.hex` | The DEVELOPMENT signing key — **trusted from source only** |

---

## 7.9 Localisation

`i18n.py` patches Qt **before the first widget exists**, so nothing is built
untranslated. Language packs live in `lang/`: `hi.json`, `gu.json`, and
`_catalogue.json`.

`i18n.style_for_script(qss)` appends font families that cover Devanagari and
Gujarati to every font stack — Barlow has neither. A no-op for Latin scripts.

**`QFileDialog`'s static methods are deliberately never patched** — doing that
once broke every attachment in the app. Captions are translated at the call
site instead.

**Known gap:** `plans.py` feature names and blurbs are not in the catalogue.

---

## 7.10 The operational rules that are easy to break

Collected in one place, because each one has already cost time.

1. **The submodule always wins.** A sibling `../prism_terminal` checkout is
   ignored. Do not keep two checkouts of one repo.
2. **Push the submodule before pushing the parent**, or CI cannot check out.
3. **Never export `PRISM_LICENSE_OFFLINE_DEV=1` to run tests.**
4. **Keep the one deselect** in the pytest invocation.
5. **One machine writes the register.** Several mailboxes, yes; several writers,
   no.
6. **Gerber files never reach an AI** — asserted by a test that checks a literal
   string. Do not "improve" that test.
7. **Startup order in `main.py` is load-bearing.** Every step's comment says
   what breaks if it moves.
8. **Nothing touches a widget from a worker thread.**
9. **Never show an error without a next action.**

---

[← Add-ons](06-addons.md) · [Index](README.md) · [Next: State & roadmap →](08-state-and-roadmap.md)

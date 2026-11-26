# Release issues — read this before every release, dev build or console change

**Claude: open this file first.** Before you build, tag, publish, push, change the
licence console, or touch how a dev build runs, read the checklist and scan the log.
When something goes wrong, add an entry here in the same session, before you move on.
Every entry says what the owner saw, the real cause (and whether it is *proven* or only
*suspected*), the fix, and the check that now stops it coming back. An entry without a
check is not finished.

The owner's rule (2026-10-27): *"i told you to not make these mistakes."* Repeating a
logged mistake is the failure. If you are about to do something this file warns about,
stop and say so.

---

## Claude's own mistakes: read these as rules

Written 2026-10-27 at the owner's request ("add all of your mistake so you won't repeat"), from a full
review of that day's work. Each is something I actually did. The rule on the right is what I do instead.
If I am about to do the left-hand thing, I stop.

**A. Saying what the state is without checking it now**
| What I did | Rule |
|---|---|
| Said two known failures "now pass" and offered to delete them. They pass on Linux and still fail on the Windows runner. The test runner printed the same "now pass" hint again later. | A pass on Linux says nothing about a Windows-only entry. Never remove a known-failure line on a Linux result. |
| Told the owner the licence-server commits were "only local" after they had pushed them. | Before any sentence about pushed, deployed or live, run the command that shows it (`git status -sb`, `git log origin/main`, a request to the live URL). |
| Called an early snapshot of a half-published release a "FAIL" of the code. | Read what was being read (which release was "latest", how complete) before calling a result good or bad. |
| Reported "357 failures" before reading the first error. They were all "unable to open database file". | Read the first traceback before quoting a count. |
| Said a cause ("missing Groq key" for the mic) with more confidence than the evidence allowed; the owner remembered a local model. | Label every cause PROVEN, LIKELY or A GUESS. Ask what the owner remembers before building a theory on code alone. |
| Said fixes were done when they existed only in my working folder, not in a published build the testers could install. | "Fixed" means: in a build, installed, and checked on the machine that had the problem. Otherwise say "fixed in code, not shipped". |

**B. Design that only worked for the newest client, or hid its caveat**
| What I did | Rule |
|---|---|
| Built a Development version box that older dev builds (1.6.10, 1.6.11) could never use, and put the caveat in small grey text. The owner had to change Production to test dev. (ISS-008, ISS-013) | Design for the oldest, weakest client first. Put every caveat in the control itself. |
| Changed `HOME` and `USERPROFILE` for dev builds to isolate data. Windows lost Downloads, Documents and Desktop in the file picker. (ISS-009) | Never change a global the operating system also reads. Use the narrowest hook, and say which platform I could not test. |
| Computed visible default folders (Desktop, Documents, "Prism ..." folders) from `~`, so on dev builds they pointed into a hidden folder. | A folder a person should open uses the real home. Only Prism's private state uses the isolated one. |
| Left a dev build as a brand-new install (no Groq key, no browser logins, no folders, no History) and let testers read it as bugs. | Whenever a build starts empty, say so and give a way to bring settings across. |
| Labelled a dev build "1.6.10" that held newer code, so it did not behave like the real 1.6.10. | A version number and its behaviour must match, or the label says otherwise. |

**C. Careless edits that cost data or trust**
| What I did | Rule |
|---|---|
| Used `git add -A` and rolled back a teammate's engine update; pushed it. (ISS-017) | Stage files by name. `git diff --cached --stat` before every commit. Update the submodule right after a rebase. |
| Replaced a slice of `admin.py` by index range and deleted two routes. (ISS-015) | Edit by exact anchor. Run that file's tests straight after. |
| Detected my own patch by an attribute a test mock answers for everything. (ISS-014) | Compare identity, not attributes. Run the FULL suite after a cross-cutting change. |
| Pushed the dev repo's `v1.6.10` tag at current code, which made the old-client tests vacuous for weeks. (ISS-003) | Trust a tag by its contents, never its name. |
| Changed a CI workflow (release now waits for tests) without being able to lint it. | Install actionlint before editing a workflow, or say "validated as YAML only". |
| Treated "the folder holding the executable" as Prism's own folder in a feature that deletes it (ISS-018). | For anything destructive, prove the target is ours (expected contents only), and test the shared-folder case. |
| Let a helper process inherit the app's working folder, which Windows will not delete. | Give helper processes an explicit working folder outside anything they delete. |
| Classified the CI workflow and publishing tools as "does not ship" in a gate about what was tested. | Anything that decides how production is built or published counts as shipped. |
| Wrote a changelog line for a feature that was not in the app and not deployed. | Changelogs describe only what the build contains; anything else is labelled as separate and its state given. |

**D. Testing and tools**
| What I did | Rule |
|---|---|
| Shipped a redesigned console with no browser test. The first browser test found a contrast failure within minutes. (ISS-007) | Every UI change ships with a test that runs the real thing. |
| Wrote a new test that mutated shared fixture data (a lease recorded another version), breaking an older test. | A test must leave shared data as it found it, or use its own. |
| Wrote tests asserting the wrong status code (422 instead of 400) and fake objects missing a method the real one has. | Read how the real code answers before asserting. Failures in my own test are my test's fault until proven otherwise. |
| Trusted `gh api rate_limit`, which reported a healthy count while calls were refused; waited on the wrong time. (ISS-005) | The response headers are the truth (`x-ratelimit-reset`). |
| Said "BOQ is tested" after running only the test files a teammate's commit touched; the failing BOQ check lived in another file (ISS-019). | An area is tested only after the FULL suite ran on the combined code. Never choose the test set by the diff alone. |
| Wrote a test that calls `/bin/sh` without a Windows skip, and changed a path's spelling (`/` to `\`) behind a test that compared strings; both only failed on the Windows runner, and I pushed the next commit before reading that run (ISS-020). | Windows first means reading the Windows CI job before the next push, and writing tests that either run on Windows or say why they skip. A green Linux suite proves nothing for customers. |
| Called a running check "stalled" after measuring the wrong process (the parent waits; children do the downloads) and killed it (2026-10-28). | Before stopping a job, find the process doing the work (`pgrep -P`, `/proc/<pid>/io` of the child) and watch it for a minute. A quiet parent proves nothing. |
| Started a Docker container while a browser test was running; Chrome cancelled requests on the network change and the test failed (2026-10-28). | Do not change the machine (containers, networks) during a test run, or rerun what overlapped. |
| Ran full suites while still editing, so a result mixed old and new code. | Run the final suite on the finished commit, on the combined code, with the engine at the recorded commit. |

**E. Release mechanics**
| What I did | Rule |
|---|---|
| Published the signed list before its files. (ISS-004) | Files first, signed list last. |
| Kept work (signed outputs, work folders, databases, the source of a published page) in a scratch folder that a session restart wiped; lost a signed file and had to re-sign. (ISS-010, ISS-011) | Anything that must survive goes in the project folder, not a scratch folder. `mkdir -p` in the same command that uses it. |
| Started long background jobs and did not notice a restart had killed them. | After any restart, list what was running and re-check each before reporting. |
| Did not fetch before pushing to a repo a teammate also uses; the push was rejected. | `git fetch` and look at what is new before every push, and rebase, never force. |
| Ran my earlier test runs without the engine commit the teammate's code needed, so his newest code was never exercised. | After a teammate's push, rerun everything on the combined code. |

**F. Before I say "done" (every time)**
1. Did I run it myself, here, just now? What exactly did I not run (Windows, Mac, a real customer machine)?
2. Is anything staged or pushed that I did not intend (`git diff --cached --stat`, `git status -sb`)?
3. Could this reach a real customer, or the Production number? If yes, is there a confirmation and a test?
4. Is every claim about state (pushed, live, passing, proven) checked now, not remembered?
5. Is the cause I named proven, likely, or a guess, and does my wording say which?
6. Did I write the new mistake into this file before moving on?

---

## The owner's promotion rule (2026-10-27)

Until the owner says **"move to prod"**, everything is built so that the moment they do, customers on
1.6.10 see the download badge and can update. So: never ship anything to dev that a 1.6.10 client could not
take as production; run `python3 devtools/promote_check.py` at the end of every dev release; promote exactly
the commit that was tested. The steps and the reasons are in `docs/PROMOTING-TO-PROD.md`.

## Pre-release checklist

Tick every line for real. If you cannot, say which one and why. Never write "done" for
something you did not run.

**Before building**
- [ ] Stage files by name (never `git add -A`); `git diff --cached --stat` shows no `prism_terminal` line unless the engine
      change is intended; after a rebase run `git submodule update --init prism_terminal` first (ISS-017).
- [ ] `git log v1.6.10..HEAD` read. Know every change that is about to ship, including
      other people's (Hitarth's BOQ work shipped inside the updater release, unannounced).
- [ ] Which channel is this? Dev builds are `PRISM_CHANNEL=dev`, prod are not. Never
      push a dev change toward the prod repo or the reverse (the build refuses; do not argue with it).
- [ ] `python3 devtools/prerelease_check.py` passes. `python3 devtools/extract_strings.py`
      run and its *removals* read.
- [ ] Full app tests and `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 python3 main.py` run against a
      throwaway `PRISM_HOME`, with `~/.prism/config.json` hashed before and after.
- [ ] Accuracy gate: `python devtools/evals/run.py` prints GATE PASS on the exact release commit (replay of recorded answers; live-model run is not built yet); no case that passed before now fails and a lower score blocks. Any override, and any change to `devtools/evals/baseline.json`, is an explicit commit with the reason written in it.

**What a dev build must never do**
- [ ] It must not change `HOME` or `USERPROFILE` for the whole process (ISS-009). Windows
      resolves Downloads, Documents and Desktop through `%USERPROFILE%`. Isolation is the
      `expanduser` hook in `channel.py` only.
- [ ] Any default folder a person is meant to open (Desktop, Documents, "Prism ..." folders, picker
      start folders, Drive/OneDrive discovery) uses `paths.real_home()` / `user_folder()` /
      `desktop_dir()` / `picker_start_dir()`, never a bare `expanduser("~")` (ISS-012).
- [ ] It must not share `update_state.json`, the licence file or `updates/` with a normal install.
- [ ] File pickers must start in the user's real folders, never in the data folder.

**Windows first (then macOS, then Linux; Linux proves nothing for customers)**
- [ ] Attach a file and a folder: Quick access shows Downloads, Documents, Desktop and drives.
- [ ] Microphone records and the words land in the task box.
- [ ] A traced/inquiry folder is picked, remembered and watched after a restart.
- [ ] History and the last brief/research are still there after an update and a restart.
- [ ] Settings > Check for updates, download, restart, version changed, data untouched.
- [ ] Settings > Privacy & data: each "where Prism saves" folder can be chosen and is used; on a spare
      machine only, Uninstall (Prism only / Prism and everything it stored) really removes what it lists and nothing else (ISS-016).

**Publishing**
- [ ] Files first, signed manifest **last** (ISS-004). A manifest with missing files is a customer error.
- [ ] All three platforms: signed manifest, every part complete, verified from outside
      (dev key accepted, prod key rejected for dev; the reverse for prod).
- [ ] `python3 devtools/check_as_old_client.py` (customers on 1.6.10) and
      `--client-tag v1.6.11 ...` (dev users): PASS on every platform, before any banner is raised.
- [ ] GitHub allows about 5,000 API requests an hour. One release uses all of it. Read
      `x-ratelimit-reset` from the response headers, not the `rate_limit` endpoint (ISS-005).
- [ ] Nothing pushes the licence server without the owner saying so in that message: a push deploys production.

**Licence console**
- [ ] `tests/test_console_ui.py` run (real browser: every tab, phone width, contrast, key copy, versions).
- [ ] Anything that reaches real customers asks first and says how many (ISS-008).
- [ ] After a deploy, check the live service from outside. State what was and was not checked.

**Promotion readiness**
- [ ] `python3 devtools/promote_check.py` (add `--dev-proof` once the dev release is published): no FAIL.

**Reporting**
- [ ] Say what is proven, what is simulated, and what no one has run on a real Windows or Mac machine.

---

## Issue log (newest first)

### ISS-037 — A helper's test run wrote reel folders into the real Desktop (2026-11-26) — CAUGHT, cleaned, nothing else touched
- **Found by:** the helper agent reported it, and I checked the folder, `~/.prism/config.json` and the engine clones afterwards.
- **What went wrong:** two early test runs in a helper's shell had no sandbox `HOME` (the `export` did not carry between
  shell calls). A reel test wrote six output folders named `2026-11-26 21-15*` into the real
  `~/Desktop/Prism Artifacts/make an Instagram reel about Tulsi/`. Outputs go to the real home by design (ISS-009), so a
  sandbox `HOME` is the only thing that keeps tests away from them.
- **Fix:** deleted exactly those six folders (the 18 Nov ones were left alone). Confirmed afterwards: no `2026-11-26` folder
  remains, `~/.prism/config.json` is unchanged (20 Nov, 1632 bytes), nothing under `~/.prism` was written.
- **Check:** every test command sets `HOME=$(mktemp -d)` on the SAME line as the command, never in an earlier `export`.
  After a test session, `ls "~/Desktop/Prism Artifacts"` for folders dated today.
- **Lesson:** a safety variable set in one shell call is gone in the next. Put it in the command, or use a wrapper script.

### ISS-033 — A "pull latest" rebase rewrote commits that were already published (2026-11-13) — CAUGHT before pushing
- **Found by:** checking `merge-base --is-ancestor <remote branch> HEAD` before pushing the engine for a PR.
- **What went wrong:** asked to pull, I ran `git rebase --autostash origin/main` on the engine branch. Its first nine commits
  were already on `origin/fix/motion-text-anchor-and-render` (the branch behind an open PR), so the rebase gave them new hashes
  and the branch no longer fast-forwarded the remote. Pushing would have needed a force-push, and the GUI repo's engine
  pointers named the old hashes.
- **Fix:** kept the rebased result on `local/rebased-onto-main-2026-11-13`, went back to the published lineage
  (`backup/pre-pull-2026-11-13`), committed on top of it, and pushed as a fast-forward.
- **Check:** before any rebase of a branch that has a PR, `git merge-base --is-ancestor <remote branch> HEAD` must say YES
  afterwards; if the remote branch is already pushed, do not rebase it, put the new work on top.
- **Lesson:** "rebase, never merge" is for unpublished work. I applied it to published commits because I did not look at what
  was published first.
- **Numbering:** first logged as ISS-023 on `motion/reference-match-part-1`, which clashed with an existing ISS-023; renumbered here.

### ISS-036 — I opened a licence-server PR without running its browser test; CI went red (2026-11-26) — FIXED
- **Seen:** licence-server PR #4 failed `tests/test_console_ui.py::test_pulse_new_badge_only_on_errors_first_seen_in_the_last_day`.
  I had run the whole suite with `--ignore=tests/test_console_ui.py` (it needs Chromium) and added `<b>` tags inside the Pulse error
  rows, so the test's `td b` selector matched several elements.
- **Fix:** the drill-down names the customer with a styled `span`. Ran all 18 browser tests locally, then CI was green.
- **Rule:** when a change edits `app/console.html`, run `tests/test_console_ui.py` before pushing; an ignored test file is a test not run.

### ISS-035 — GitHub blocked asset downloads and workflow dispatches while the quota showed 4,800 of 5,000 left (2026-11-26) — OPEN (wait it out)
- **Seen:** `HTTP 403: API rate limit exceeded` on `gh release download` and `gh workflow run`, for about an hour, while
  `gh api rate_limit` showed ~4,870 core requests left. This is a burst limit on the account, not the hourly quota. Three
  parallel publish runs plus a retry every 90 s kept it alive.
- **Also:** my first waiting loop used `gh api -o`, which does not exist, so its check could never succeed.
- **Rule:** one flavour at a time; after a 403, stop and wait 15+ minutes (retry every 5, not 1.5); test a waiting loop's check
  command once by hand before starting it.

### ISS-034 — Signing the 2.0.0 flavours failed: "this signing key is not the one published as 'udev2'" (2026-11-26) — FIXED
- **Seen:** `sign_manifest.py` refused the key. `prism_gui/devtools/dev-signing-key.hex` (git-ignored) holds a DIFFERENT key
  (public half 4fd56e...) than the one `licensing/keys.py` publishes as `udev2` (0b0591...).
- **Cause (PROVEN):** the real private key is `~/prism-keys/prism-update-dev-udev2.hex`; the stray file was picked up by the old
  default. Nothing was wrong with the builds or with `keys.py`.
- **Fix:** sign with `UPDATE_SIGNING_KEY_HEX="$(tr -d '[:space:]' < ~/prism-keys/prism-update-dev-udev2.hex)"`; the stray file is
  to be deleted once the 2.0.0 publish has succeeded.
- **Rule:** the signing key lives only in `~/prism-keys/`; derive its public half and compare with `keys.py` before a release.

### ISS-032 — Publishing a 2.0.0 flavour from a laptop failed with HTTP 408, and I called it "still uploading" (2026-11-26) — FIXED
- **Seen:** `v2.0.0-studio` existed with only its two small manifests. I told the owner the installers were "still uploading";
  the script had already died: `HTTP 408: Upload body timed out due to inactivity` (`gh release upload` with 4 files of 400-670 MB
  at once). Measured upload line: ~1.1 MB/s (Wi-Fi), so ~5 GB per flavour per platform pair is 1.5 h, three flavours ~5 h.
- **Cause (PROVEN: the log):** `create_flavour_release` sent every installer in ONE `gh release upload`; parallel streams starve
  each other on a slow uplink and GitHub drops the idle one. Second mistake in the same hour: a restart command matched its OWN
  command line with `ps | grep` and killed my shell (the trap in CLAUDE.md).
- **Fix:** `upload_one_by_one` (one file at a time, retry a timed-out file, skip a file already there at the same size);
  `--stage open|sign|finish` and `.github/workflows/publish-flavour.yml` move every big transfer onto GitHub's network; only the
  signing (a few hundred KB) runs on the owner's PC, and the key is never in CI (`finish` refuses to sign).
- **Rule:** never report an upload as running without reading the process or the log first. Big release files are published
  from CI, not from a laptop. Stop a background job by its PID, never by a pattern that appears in your own command.

### ISS-031 — PR #34 went red on a guard test I had not run, and my branch delete closed the PR (2026-11-26) — FIXED
- **Seen:** `Tests · Linux 3/4` red on PR #34: `test_workflow_speed.py::TagRunsAndReleasesAreUntouched::test_tags_still_trigger_the_workflow_and_assets_tags_do_not`
  pins the exact `tags:` list of `build.yml`, and I had added the flavour exclusions. Earlier in the same step, `gh pr merge`
  was refused (branch policy) but the `git push --delete` chained after it still ran, so GitHub closed the PR; I reopened it.
- **Cause (PROVEN):** I ran only the release tests (`test_release_*`, `test_promote_check`), not the suite, before pushing a
  change to `build.yml`. A guard test that pins a workflow value is found by `git grep build.yml -- tests`, which I ran only after the failure.
  The delete was chained to a command whose success I had not read.
- **Fix:** the guard now expects the new list, with the reason in the test (rule 8).
- **Rule:** before pushing a change to `build.yml`, run `git grep -l build.yml -- tests` and every file it lists. Never put a
  branch delete in the same command as a merge: read the merge result first.

### ISS-030 — A UI change passed PR CI and broke three tests in every flavour build (2026-11-26) — FIXED in code
- **Seen:** the first Studio, Sales and Engineering builds from main (runs 45698103739, 45698110820, 45698116808): 5 test
  shards red, no installer built. All 3 failures were chip tests that expect four "Try:" chips on Home
  (`test_ui_port_home_polish.py` x2, `test_ui_port_home_layout.py` x1). Studio draws 2 chips, Sales 2, Engineering 2.
- **Cause (PROVEN: reproduced locally with `PRISM_TEST_FLAVOUR=studio`, red on the old tests, green on the fixed ones):** PR #31
  made Home draw only the chips whose add-on the build has. Pull-request CI runs the Complete flavour only, so all four
  chips were present and every check was green. Only a manual flavour run (`workflow_dispatch`) runs the suite as
  Studio/Sales/Engineering. I had run those test files only as Complete.
- **Fix:** those two test files pin the Complete chip set in `setUp` (they test size and routing).
  `tests/test_home_try_chips_match_build.py` tests the filter itself, per flavour.
- **Check:** the three files pass under `PRISM_TEST_FLAVOUR` = complete, studio, sales, engineering.
- **Rule:** a change to what a screen draws per flavour is not tested until the suite has run as each flavour
  (`PRISM_TEST_FLAVOUR=<flavour>` locally, or a manual flavour run before merging). Local `PRISM_FLAVOUR` does not do
  this inside pytest: a run that passes under it proves nothing.

### ISS-029 — A Studio, Sales or Engineering app would have updated itself into the complete Prism (2026-11-25) — FIXED in code, not yet in a build anyone installed
- **What happened:** nothing yet, no flavour was ever released. Found by reading: `updater.py` built every URL from
  `platform_tag()`, so a flavour asked for `manifest.windows-x64.signed` (complete's) and the quiet `auto_stage` would
  have staged it. `flavour.update_channel()` existed and nothing called it; the tests pinned only the data.
- **Cause (PROVEN by test):** gate G2 landed as data with "not wired yet", and nothing failed because of it. Worse: the
  signed manifest did not say which build it is for, and flavours share `~/.prism/update_state.json` and the staging
  folder, so Complete could also have applied Studio's waiting update.
- **Fix:** own channel in every name, a signed `update_channel` the client checks, own state file, staging name and
  swap script per flavour (docs/UPDATE-SYSTEM.md section 8c). Complete is unchanged.
- **Check:** `tests/test_update_flavours.py` (every build against every other build's manifest, literal URLs) and, in
  the Windows build job, `packaging/windows/update_check.py` (a real install updated, same flavour afterwards).
- **Rule:** a table that "nothing reads yet" needs a test that fails while the thing it describes is live without it.

### ISS-028 — `test_gates.py` hung 480 s on the Windows runner after passing every test (2026-11-23) — FIXED in code, Windows CI rerun pending; cause LIKELY, not proven
- **Seen:** run 45266305406, shard 3/4, windows-latest: `RETRY test_gates.py first attempt: timed out after 480s`; the captured
  output showed `[100%]` and the summary, so all tests had finished and the process then did not exit. The retry took 45 s.
  About 1 run in 3. No stack reached the log.
- **Why no stack — PROVEN (code, and a probe on Linux/Python 3.11):** `run_file` returned on `TimeoutExpired` without reading the
  watchdog's file, and kept output in a pipe. And the watchdog (`faulthandler.dump_traceback_later`) is cancelled when the
  interpreter finalises: a probe that hangs in native exit (`on_exit(pause)`) was NOT ended at 3 s (killed at 20 s, empty dump),
  while a hang in a Python `atexit` or `__del__` was. `conftest` also ends the process with `os._exit` (ISS-026), so a hang there
  is past the watchdog's reach by design.
- **What outlives the tests — PROVEN (Linux, 9 runs):** every `MainWindow` arms `QTimer.singleShot(4000, _warm_heavy_imports)`,
  which imports cadquery (OpenCascade) on a `WarmImportsWorker` QThread. Tests that spin the event loop let it fire: 31 such
  threads per run, 15 OpenCascade pool threads left alive at the end. On Linux every import finished before the end (also under
  CPU starvation, 3x slower), so nothing was in flight at exit and no hang reproduced.
- **Mechanism — LIKELY, NOT PROVEN (cannot run Windows here):** `MainWindow.closeEvent` -> `_retire_workers` waits 10 s on every
  worker in `workers._running`, then `terminate()`s it. A slow Windows import of cadquery still running then is killed inside
  `LoadLibrary` / the import lock; a thread killed while holding the loader lock would make `ExitProcess` (`os._exit`) wait
  forever, with no watchdog left. Confirmed on Linux only that `terminate()` ends a running worker mid-sleep.
- **Fix:** (1) the suite sets `PRISM_NO_WARM_IMPORTS` (conftest autouse) and `_warm_heavy_imports` honours it, so no test
  imports cadquery on a thread; (2) `tests/leakcheck.py` + last test of `test_gates.py` fail if a worker QThread, licensing
  thread, non-daemon thread or (Linux) child process is still running at the end; (3) the runner now writes output to a file,
  kills the process tree on a timeout (`taskkill /T /F` / process group), prints the watchdog stack if any, and otherwise says
  whether the tests had finished (conftest writes two stage markers).
- **Check:** `tests/test_leakcheck.py` (detector, and that the warm-up is off in the suite), `ZNothingOutlivesTheFile` in
  `tests/test_gates.py`, `ATimedOutFileSaysWhereItWasStuck` in `tests/test_workflow_speed.py`; each mutation-checked.
- **Still open:** the same `terminate()` runs when a customer closes Prism within seconds of starting on a slow disk (a warm
  import in flight); not changed here. Verify with several Windows runs without a RETRY line before calling this fixed.

### ISS-027 — `run_flavour.sh` and RUN_A_FLAVOUR.md claimed a "minted licence" that never existed (2026-11-23) — FIXED in code
- **What happened:** the flavour launcher said `PRISM_LICENSE_OFFLINE_DEV=1` gave "minted licence, no licence server". It mints
  nothing: it only changes the answer when the licence server cannot be reached. A fresh sandbox therefore had no licence and
  showed the licence screen. **PROVEN** (licensing/__init__.py `_offline_dev()` / `_unreachable_answer()`).
- **Second cause:** `devtools/mint.py install` could not have helped either. The private key in `devtools/dev-signing-key.hex`
  did not match the `dev1` public key in `licensing/keys.py`, so every minted token failed with `bad_signature`. **PROVEN**.
- **Fix:** new dev key `dev2` (public half in `keys.DEVELOPMENT`, private half only in the gitignored key file; old file kept as
  `dev-signing-key.hex.old-2026-11-23`, also ignored). `mint.py` signs with `dev2` and refuses a key that does not match its
  kid. `run_flavour.sh` runs `mint.py flavour`, which writes a 30-day dev licence for the flavour's features (from
  `addons/flavours/<f>.py`) into the sandbox when it has no valid one, and only then points `PRISM_LICENSE_SERVER` at
  `127.0.0.1:9`. Frozen builds still trust PRODUCTION keys only.
- **Check:** `tests/test_dev_licence.py` (kid/key match, flavour features, nothing tracked) and
  `test_licensing.py::FrozenBuildSafety::test_dev2_and_every_development_key_rejected_when_frozen`. Rule: a comment or doc that
  says what an environment variable does is checked against the code that reads it, before it is written.

### ISS-026 — Dev 1.8.7 and 1.8.8 never published: four different CI failures (2026-11-19) — runner fixed, two flakes UNEXPLAINED
- **1.8.7, `Tests · Windows`:** two new test files did `import pwd` (Unix only) at module level. **PROVEN** (collection error).
  **Fix:** `_real_home()` falls back to `expanduser("~")`. Rule: never import `pwd`/`fcntl`/`termios` at test module level.
- **1.8.8 attempt 1, `Tests · Windows`:** `test_chat_thread.py` died with 0xC0000005 (access violation) on BOTH tries (the runner
  retries once); every other file passed (7630). Same code passed on the 1.8.7 run and 12/12 locally. Cause **UNKNOWN**: the
  runner printed only the last 500 characters, which for a faulthandler dump are pytest's entry point, not the crashing frame.
- **1.8.8 attempt 1, `Tests · Linux`:** stalled after `test_leads_evidence.py` (next file `test_leads_filter_panel.py`, normally
  13 s; 5/5 locally) until cancelled 48 min later. pytest-timeout's default *signal* method cannot fire while a test sits in Qt's
  C++ event loop, so only the 25-min file timeout applied, twice with the retry. Which test hung is **UNKNOWN** for the same reason.
- **1.8.8 attempt 2, `Windows (x64)` build:** packaged-app selftest failed "HTTPS trust store — HTTP 429": Google rate-limited the
  runner. A 429 means TLS verification already succeeded. **Fix:** `main.py` counts any `HTTPError` as a passed TLS check.
- **Runner fix:** `devtools/suite_runner.py` uses `--timeout-method=thread` (a hung test is killed after 300 s with every thread's
  stack) and prints the crash/timeout dump around the failing frame instead of the output's last lines. Verified with a
  deliberately hanging and a deliberately segfaulting test: both now name the test and line. The next recurrence is diagnosable.
- **1.8.8 tag run (attempt 2, 13:07):** `Tests · Linux` hung AGAIN on `test_leads_filter_panel.py` (after `test_leads_evidence.py`,
  12:53:50, 14 min, cancelled). The new per-test limit did not fire, so the hang is OUTSIDE a test (import, class setup, or a
  thread keeping the process from exiting). Attempt 1 of that run died on an Ubuntu mirror outage (apt, not our code).
  **Runner fix 2:** `tests/conftest.py` arms `faulthandler.dump_traceback_later` (set by the runner, file timeout minus 60 s) and
  writes every thread's stack to its own file; the runner reports it even when all tests passed. File timeout 1500 s -> 900 s
  (slowest healthy file 363 s). Verified with probes that hang at import and at exit: both now name the file and line.
- **Windows crash located (branch run 44538341953, 84aed91):** the runner's first-attempt dump showed 0xC0000005 in
  `workers.py:182` (`QThread.__init__`) called from `test_nothing_touches_the_network_on_the_ui_thread`; no worker thread was
  running (workers run inline in that file). A crash inside an allocation = the garbage collector freeing something Qt had already
  deleted. Suspect: `viewer.route_links` (709cf33) connected a lambda holding the browser to the browser's own signal, a cycle
  only the GC frees. Before it: 0 crashes in 3 Windows runs; after: 2 in 7. **Fix:** weak reference; new test proves the browser is
  freed without the GC (fails on the old code). **NOT PROVEN** as the cause until several Windows runs pass without a retry.
- **Pushed the engine to the WRONG repo (19 Nov, ~16:00):** in `wt-engine-int`, `origin` is Hitarth's
  `HitarthTrivedi/prism_terminal`, not AlphaKore's (`alphakore`). `git push origin ai-via-server-int:ai-via-server` created a new
  public branch there with all the server-mode work. Deleted within about a minute; his `main` untouched. **Rule:** name the remote
  by URL before every push (`git remote -v`); in engine worktrees AlphaKore's remote is `alphakore`, in GUI worktrees `alphakore-dev`.
- **Windows test_chat_thread crash, what is now known (19 Nov, flake-hunt branch):** 30 runs of the file per commit on
  windows-latest: 1.8.6 (8706f1a) 9/30 crashed, latest 16/30. So it is OLD, not from the BOQ or viewer merges. Always while
  constructing a QThread (AutomationWorker, once AttachWorker) after an earlier task ran in the same process. Still crashes with the
  GC disabled and with every worker kept alive: NOT the GC, NOT freeing workers. The route_links weakref change (4447350) did not
  fix it (retracted). In this file workers run inline on the GUI thread (start -> run), which the real app never does; whether the
  real app is affected is UNPROVEN. Full page heap + cdb ran 12 times without a crash but the log did not show the tests ran, so
  that proves nothing. Next: a cdb run whose test output is visible.
- **I reported two customer bugs that were only in my test scripts (19 Nov, evening):** my STEP and Email drivers built
  `cfg` by hand. The real app loads it with `config.load()`, which in server mode gives `api_key` and `openrouter_api_key` the
  stand-in `ai_client.AI_KEY` ("prism-ai") so every "is a key set?" check passes. So "STEP Ask/Edit blocked for every customer"
  and "every inbox unsorted" were FALSE; I committed fixes for them and then reverted both (b6a2010, engine 1d6934b). Verified
  after the revert with app-loaded settings: 10 real mails sorted correctly through the server, 3.4 credits. **Rule:** a
  driver that tests a screen takes its cfg from `CB.config.load()` (or the main window), never a hand-built dict; and before
  calling something "broken for every customer", reproduce it through the app's own path.
- **Process (owner's suggestion):** run the workflow on the branch (`workflow_dispatch`, no tag) and tag only a green commit, so
  a red run never burns a version number.

### ISS-025 — Dev 1.8.2 tagged with five new red tests on the Windows runner (2026-11-18) — FIXED in code, Windows CI rerun pending
- **Seen:** `Tests · Windows` of v1.8.2: 7316 passed, 7 failing (2 are the known quotation-PDF entries). The five new ones:
  1. `test_layering` — `widgets/send_to_ai.py` imported `dialogs.base` at module scope. **PROVEN** (the guard names the line; it
     fails on any OS, so Linux was red too). The 1.8.2 STEP consent window was put in a widget file. **Fix:** the window moved to
     `dialogs/send_consent.py`, imported inside `ask_consent`. Guard untouched.
  2. `test_reel_run_transport_with_a_fake_encoder` — "Chromium isn't installed for the web renderer". **PROVEN** from the message
     and code: the run asks `reel_web.available()` before rendering, and the test faked only `render`. Linux passed only because
     Chromium is installed there. **Fix:** the test fakes the browser answer too; it now passes with `PLAYWRIGHT_BROWSERS_PATH`
     pointing nowhere. The real-render test still skips when the browser is absent.
  3. Two structured-file PDF tests (and the two known quotation-PDF failures) — PDF read back as `''`. **Cause LIKELY**: the
     Windows runner's offscreen Qt has no system font, so `QTextDocument.print_` draws no glyphs. Reproduced on Linux by running
     with fontconfig pointed at an empty config: the same four tests fail with the same `''`; registering the bundled fonts
     (`theme.load_fonts()`, which the app does at start-up) fixes all four. Not seen on a real Windows machine. **Fix:** the tests
     register the fonts first. **Open:** nobody has looked at a PDF the real Windows app wrote; the quotation entries in
     `ci_known_failures.txt` stay until the Windows run says they pass.
  4. `test_a_row_that_cannot_wrap_never_pushes_the_window` — `1054 not less than or equal to 1000`. **Cause NOT found**: on Linux
     the screen's minimum is 959 at any font size, so the 95 px extra is Windows-only chrome I could not identify. The typed-in
     1000 was the guess of whoever wrote the test. **Fix:** the limit is measured on the same screen (minimum before the rigid
     row; the row must add nothing, and the whole must fit 1066). A mutation (removing the Ignored policy) fails the new test.
     If Windows still fails, the message now shows the before and after numbers.
- **Check that stops it recurring:** read both `Tests` jobs of a dev tag's run BEFORE telling the owner the build is ready, and
  run the touched test files with `PLAYWRIGHT_BROWSERS_PATH=/nonexistent` and `FONTCONFIG_FILE` pointing at an empty config
  (no browser, no system fonts) to approximate a bare Windows runner. A test must not depend on Chromium or system fonts being there.

### ISS-024 — Fixing the four red tests of 1.8.0 found a real product bug and a gate bug (2026-11-18) — FIXED in code, CI rerun pending
- **Motion rhythm (PROVEN):** `rhythm.probe_video` asked `ffprobe` for the video size. The FFmpeg Prism ships (`imageio-ffmpeg`)
  has no ffprobe beside it and customers have none on PATH, so the check returned None for every customer; this dev machine
  hid it with `/usr/bin/ffprobe`. Reproduced by running the test with an empty PATH (red), fixed in the engine (`ad85769`:
  size read from `ffmpeg -i`), green with and without ffprobe. Rule: a test that shells out must be run once with a bare PATH.
- **STEP (LIKELY cause, Windows CI decides):** the "Also ask ChatGPT for a styled copy" QCheckBox could not wrap, so its one-line text
  set the centre column's minimum width: on Linux 291 of 315 px, on the Windows runner about 340 (column about 372, 2 px past the window).
  It is now a tick box plus a wrapping label; a new test doubles the text and must still fit (red with wrapping off: 1068 > 1066).
- **Inquiry tabs (LIKELY, Windows CI decides):** the test measured titles with the widget font, but the stylesheet paints (and the
  Windows runner sized the tab rect with) the `QTabBar::tab` font; it now reads that font from `style.qss`.
- **Drop test:** Qt hands local files on as `C:/x`, `os.path.join` makes `C:\\x`; compared as normalised paths (not a product bug).
- **Gate bug:** `prerelease_check.py` never honoured whole-file entries in `prerelease_removed_ok.txt`, so the listed removals of
  `ai_directory_dialog.py` etc. stayed red; it now does. The 31 inherited removals (Hitarth 8fb1c2a, Harsh Bhatt 1369936, BOQ
  industries tests) are listed with their source commit but were NOT reviewed by the release session.
- **macOS:** matrix entries commented out with a switch note (owner's decision for dev 1.8.1: Windows + Linux only). Re-enable before any
  build that must reach Mac users; Mac installs get nothing from 1.8.1.
- **Process:** actionlint 1.7.12 (checksum-verified) is in `~/tools/actionlint/`; run it on every workflow edit. Run prerelease_check
  with a sandbox HOME and `PLAYWRIGHT_BROWSERS_PATH` pointing at the real browser cache, or its self-test sees a "!" line.

### ISS-023 — Dev 1.8.0 tagged without CI on the combined code; the gate was red and macOS CI cannot start (2026-11-17) — SUPERSEDED by 1.8.1 (ISS-024); v1.8.0 was never published
- **Seen:** tag v1.8.0 (commit 611a864, reskin + AI through the server) built fine for Windows (runner smoke test passed) and Linux, but
  `Tests · Windows` had 4 new failures and `Tests · Linux` 1; macOS jobs were cancelled at once with "The configuration
  'macos-14-arm64-us-default' is not supported". `release` needs build and tests, so nothing was published. Run 44144776180.
- **Causes:** the branch had never run CI (CI runs on main, PRs and tags only), so the first Windows run of the reskin was the tag run.
  Three failures are Windows-only layout/path checks (tab title 137 px < 143, STEP 2 px overflow, `/` vs `\` in a drop test); one
  (test_motion_rhythm ProbeVideo) fails on both runners, LIKELY ffprobe missing next to the bundled ffmpeg. The macOS error is a
  runner configuration issue (cause not investigated). Also found: the branch commit's engine gitlink was still d0165dd while the tested
  engine (via the symlink) was dce2760, and dce2760 was not on the repository `.gitmodules` pointed at; the pin needed `.gitmodules` ->
  AlphaKore5/prism_terminal.
- **Rule/check:** before tagging a branch that was never in CI, run the workflow on it (workflow_dispatch) and read the Windows tests
  job first. Check `git ls-tree HEAD prism_terminal` against the engine you tested, and that the commit exists at the `.gitmodules` URL.
  The macOS runner label must be fixed before any tag can publish (the release job needs the whole matrix).
- Details: ui-port/stages/18-windows-dev-release.md.

### ISS-022 — Review found Uninstall could delete a person's own folder (2026-10-28) — FIXED before tagging 1.6.13
- **Found by:** the two-axis code review (standards + spec) run on today's diffs, before the dev tag.
- **What was wrong, all confirmed in the code:** "everything" removed any folder named "Prism..." that the person had
  chosen in Settings (their own "Prism Photos" would have gone, with their files); the shared-workspace check compared
  raw strings (case and links on Windows/macOS defeated it); a dev build always refused "everything" (its "~" is its
  data folder) and, once that was fixed, would have removed the normal Prism's folders; the saved licence key in the
  credential store was never removed although the window said "licence"; after 2 minutes the helper deleted even if
  Prism was still running.
- **Fix:** only Prism's own usual folders are candidates (the engine's original default is remembered, so a OneDrive
  Desktop still counts); every folder the person chose is listed as left alone; paths compared after realpath and
  normcase; a workspace inside the data folder stops "everything"; dev builds remove only their own data folder and keep
  the shared key; the key is removed only once the helper has started; still running means nothing is removed (both
  scripts). Six mutations, one per rule, each fail the tests. Tests never touch the real credential store
  (module-wide guard in tests/test_uninstall.py).
- **Lesson:** I wrote the first version and its tests from the same picture of the problem; the tests proved my picture,
  not the owner's rule. A spec review against the owner's own words found what my tests could not.

### ISS-021 — Licence-server tests could reach the live database; the server had no CI (2026-10-28) — FIXED locally, not pushed
- **Found by:** the system review with the installed skills (report: `artifacts/system-review-2026-10-28/report.html`).
- **Live database:** `license_server/.env` holds the live Supabase URL. The tests only *defaulted* `DATABASE_URL`, so a
  shell that had exported it (`source .env`, `run-local.sh`) kept it; one test drops every table, another resets what
  Production offers. Proven with a test that starts Python with a live-looking URL (red on the old code). Now the suite
  always uses a scratch database, `TEST_DATABASE_URL` is the only override, and the table-dropping test refuses anything else.
- **No CI:** Render deployed every licence-server push untested. Added `.github/workflows/tests.yml` (SQLite and
  Postgres 16 like Supabase: migrations, RLS on every table, downgrade/upgrade, whole suite) and
  `autoDeployTrigger: checksPass`. **Owner step:** Render dashboard > Settings > Auto-Deploy > After CI Checks Pass.
- **Also fixed:** `devices.channel` migration gets `lock_timeout` (proven on Postgres: gives up after 6 s instead of
  queuing licence checks); `device_sightings` gets RLS; fleet list order stable on Postgres (a test relied on SQLite's
  order); the two public webhooks no longer block the event loop on a slow prism-wa (proven: loop ran once in 0.5 s
  before, freely after) and stop reading a body past 512 KB (before: read 640 MB, then refused).

### ISS-020 — Three new failures on the Windows test runner only (2026-10-28) — FIXED in code, Windows CI rerun pending
- **Seen:** CI on c9fc339: Linux and macOS green, Windows red with 3 new failures (6029 tests, 5 failing incl. the 2 known PDF ones).
- **1. BOQ Trust dot (Hitarth's test, my diagnosis):** the sampled pixel was the row tint, not the red dot. The dot was the
  text "●"; Qt's offscreen Windows runner has no font with that glyph, so nothing was drawn. *Likely* fine in the real
  Windows app (Segoe UI has it), but not proven, so the dot is now painted as a circle in `_TintDelegate` (no font
  involved). The pixel test was re-checked against a black dot and still fails, as it should.
- **2. Gerber "folder on the Desktop" (my change):** `desktop_dir()` builds `C:\Users\x\Desktop`; the test compared it as a
  string with `expanduser("~/Desktop")` = `C:\Users\x/Desktop`. Same folder on disk. Test now compares normalised paths.
- **3. Uninstall (my test):** a check ran `/bin/sh`, which Windows does not have. Skipped on Windows. Reading the Windows
  helper again turned up two real problems, fixed in the same commit: it was UTF-8 but cmd reads batch files in the
  console code page (a user name like José would be misread, so nothing removed), now `chcp 65001` with a hidden console
  instead of none; and `tasklist`/`find`/`ping` by bare name (a Git/MSYS `find` on PATH breaks the wait), now full paths.
- **New:** `ReallyRunningTheWindowsHelper` runs the real batch file via `start()` on the Windows runner, on folders named
  with a space, `%` and `é`, while a stand-in Prism is still running. This is the first real Windows run of it (ISS-016).

### ISS-019 — CI went red on the combined dev code; I had called BOQ "tested" (2026-10-28) — FIXED
- **Seen:** CI's Linux tests failed on the 1.6.13 candidate: `test_skills.py::...test_the_bill_of_materials_and_quantities_answer_is_checked`.
  The full local run also failed `test_whatsapp_workspace.py::test_the_time_ladder...`.
- **Causes:** (1) Hitarth's BOQ round moved the skills hand-off into `_run_stage(worker_kwargs=...)`; behaviour is the
  same (checked: `_run_stage` unpacks `worker_kwargs` into the worker, which takes `stage_skills`), but the guard test
  matched the old source text. (2) The WhatsApp test expected a clock time for "5 minutes ago", which is "Yesterday"
  in the first five minutes after midnight; my run ended at midnight.
- **Fix:** the guard test checks the new form AND that the kwargs reach the worker (stronger than before); the time
  test expects what the calendar says. Both pass, the midnight case proven at 00:03.
- **My mistake:** I had told the owner "all BOQ-related tests pass (295)", having chosen tests by the files the
  teammate's commit touched. The BOQ check that failed lives in `test_skills.py`. **Rule:** an area is "tested" only
  after the FULL suite has run on the combined code; never pick the test set by the diff alone.
- **Lesson for guard tests:** a test that matches source text breaks on harmless refactors; check behaviour where possible.

### ISS-018 — Review of my own work found three defects before anyone hit them (2026-10-28) — FIXED in code
- **Uninstall could delete a shared folder.** "The program folder" was simply the folder holding the executable. If
  Prism's files had been copied straight onto the Desktop or into Downloads, "Remove the app" would have deleted that
  whole folder. Now it is removed only if it holds nothing but Prism's own entries; otherwise it refuses and names
  the files to delete by hand. The updater's leftovers (`<folder>.old`, `.prism-update-staging`, the pending marker)
  are now removed too. Tests: `tests/test_uninstall.py::TheProgramFolderMustBePrismsAlone` (a deliberate break of the
  check makes it fail).
- **Uninstall would quietly fail on Windows.** The helper inherited Prism's working folder, which for a double-clicked
  Prism is its own program folder, and Windows will not delete a folder that is a process's working folder. It now
  runs from the temp folder. Test: `test_the_helper_never_runs_from_inside_the_program_folder`.
- **The promotion gate treated the CI workflow and the publishing tools as "does not ship".** A change to how
  production is built or published could follow the dev release unnoticed. Now they count. Test:
  `test_how_production_is_built_or_published_counts_as_shipped`.
- **Changelog overclaimed:** 1.6.13 listed a licence-server feature (not deployed) as part of the app, and said
  ordinary builds were unchanged although every picker now opens in Downloads. Corrected.

### ISS-017 — My commit rolled back Hitarth's engine update (2026-10-27) — FIXED, caught within the hour
- **Seen:** after rebasing onto Hitarth's BOQ commit (which moved the `prism_terminal` engine pointer to `4d8ad52`), my
  next commit recorded the OLD engine (`bd8fa50`) and I pushed it to the dev repo. His BOQ code needs the newer engine;
  the dev build and CI would have run it against the wrong one.
- **Cause:** I used `git add -A` while my local engine folder was still at the old commit, so the submodule's
  working-tree state was committed. The rebase had even shown ` M prism_terminal`, and my own gate ignored that line.
- **Fix:** a new commit restored the pointer (no history rewrite); my local engine is updated
  (`git submodule update --init prism_terminal`); `promote_check` now FAILS on a modified engine folder.
- **Rules:** stage files by name, never `git add -A`. Run `git diff --cached --stat` before every commit and expect NO
  `prism_terminal` line unless the engine change is intended. After a rebase or pull, update the submodule before anything else.
- **Also learned:** my full-suite runs before the rebase never exercised his newest BOQ code, because my engine was behind.
  A teammate's push means re-run the suite on the combined code, with the engine at the recorded commit.

### ISS-016 — Uninstall's Windows helper has never run on Windows (2026-10-27) — OPEN, UNVERIFIED
- **What exists:** Settings > Privacy & data > Uninstall (`uninstall.py`, `dialogs/uninstall_dialog.py`). The POSIX helper
  was run for real on throwaway folders; the Windows batch file was only generated and read in tests. From ISS-020 the Windows CI runner runs it for real on
  throwaway folders; that is a server, not a customer's PC, so a spare-machine run is still needed.
- **Risks to check on a spare Windows machine, never the owner's own:** the batch waits for the process to exit, removes
  the install folder (a zip folder, or `C:\Program Files\...` which needs admin and will simply fail), retries, removes
  itself, and leaves `%TEMP%\prism-uninstall.log`. Check both choices: "Uninstall Prism" (program only) and "Uninstall Prism and everything it stored" (program, data
  folder with logs, and the Prism-named folders Prism created).
- **Rules since ISS-022:** a folder the person chose is never removed; dev builds remove only their own data folder;
  nothing is removed while Prism still runs.
- **Safety rules under test:** refuses from source; only names the running program's folder, Prism's data folder
  (`.prism` / `.prism-dev-home`) and folders named "Prism ..."; never a drive root, a home folder or its parent;
  never a folder the user chose that is not Prism-named, and never the shared workspace folder (owner's rule
  2026-10-28: app-only removes Prism only; "everything" removes only what Prism itself stored).
- **Do not announce Uninstall to customers until a Windows run is recorded here.**

### ISS-015 — My own edit deleted two routes; the tests caught it (2026-10-27) — FIXED
- **Seen:** while adding the per-computer channel, `PUT /admin/versions/{channel}` returned 404 and a dozen
  tests failed.
- **Cause:** I replaced a slice of `admin.py` by index range and the slice included the two version-saving routes.
- **Rule:** edit by exact anchor, not by index range; run the file's tests immediately. The tests did their job.

### ISS-014 — A mocked `expanduser` fooled my "is this my hook?" check (2026-10-27) — FIXED
- **Seen:** full-suite run: two Google Drive discovery tests failed after I moved Drive discovery to `real_home()`.
- **Cause:** I looked for a `_prism_original` attribute on `os.path.expanduser`. A test's mock answers every
  attribute lookup, so the check was always "yes".
- **Fix/check:** the hook is recognised by identity (`channel._HOOK`). `tests/test_channel.py`,
  `tests/test_resilience.py::CloudSources`.
- **Rule:** never detect your own patch by attribute; compare identity. Run the FULL suite before calling a
  cross-cutting change done.

### ISS-013 — Dev/prod version change needed the Production box (2026-10-27) — FIXED
- Follow-up to ISS-008. Builds before 1.6.12 cannot say they are dev builds, so an old dev build could only follow
  Production. The licence console can now mark one computer as Development ("Version numbers from" column in
  "Who has updated"); the server then answers that computer on the dev numbers and leaves everyone else alone.
- **Checks:** `tests/test_client_versions.py` (computer choice beats the build's header, other computers
  unaffected, the floor follows it, audited) and `tests/test_console_ui.py` (marking from the table).
- **Needs deploy:** a migration (`devices.channel`), then the console.

### ISS-012 — Dev builds look like a different install (2026-10-27) — FIXED in code, UNVERIFIED on Windows
- **Seen:** on dev builds after 1.6.10: attaching a file or folder does not show Downloads and other
  folders on Windows; a file is sometimes not uploaded; the mic does not work; folder tracing is missing;
  a brief or research discussed earlier is not there; "download version" misbehaves.
- **Evidence:** in the 26 commits since v1.6.10 the only product-module code that changed is Hitarth's BOQ
  commit (`557bbdc`, `addons/boq/*`). Nothing changed in attaching, the mic, folder tracing or history. What
  changed is the updater, packaging and the dev-build home redirect (`channel.py`, `main.py`). So these are
  most likely the environment, not those modules.
- **Probable cause (not yet confirmed on a Windows machine):** ISS-009, plus the fact that a dev build keeps its
  own data folder, so settings, History, speech/ffmpeg tools, traced folders and attachments' default places
  start empty.
- **Why a dev build looks broken (strong lead, not proven):** a dev build is a brand-new install. The mic records
  with PyAudio and then sends the audio to Groq using the key in `config.json` (`core/voice.py`), and a fresh dev
  folder has no key; AI steps that upload files drive a logged-in browser profile in `chrome_profile/`, and a
  fresh folder has none; traced folders live in `config.json`; History lives in `runs/`. One cause, many symptoms.
- **Added:** in a dev build, Settings > Privacy & data > "Bring my settings from my normal Prism" copies the settings
  (including the Groq key), browser logins, History and downloaded tools from the normal install. Read-only on the
  normal one; never copies the licence, device id or update state (`dev_import.py`, `tests/test_dev_import.py`).
- **Evidence from the owner's Windows screenshot (2026-10-27, dev 1.6.12):** the "Attach file(s)" picker opened in
  `C:\Windows\System32` (the working folder the app was started from; no start folder was passed) and its
  sidebar listed only Home, Gallery, OneDrive, This PC and Network, with no Desktop, Downloads, Documents or
  Pictures. The owner says prod does not do this. That is the signature of Windows being unable to resolve the
  user's shell folders, which fits ISS-009 (the published 1.6.12 still redirects `USERPROFILE`). Both causes are
  fixed in code and not yet in a published build.
- **Microphone, open question:** the owner remembers the mic being attached to a local "WhisperFlow"-style model.
  In this repository it is not local: `prism_terminal/core/voice.py` records with PyAudio and sends the audio to
  Groq's hosted `whisper-large-v3`, then a Groq model cleans the text, both with the key in `config.json`.
  Reconcile with whoever built it (Hitarth?) before claiming a cause. If a local model exists on another branch,
  its files live under the data folder too, so a fresh dev folder would lack them; `dev_import` does not copy a
  model folder it does not know about.
- **Browser logins logging out "many times", open:** the engine already keeps logins alive (graceful close,
  session cookies, stale-lock cleanup, `automation.py` lines ~350-730), so this is not a missing feature. Two
  dev-only suspects: a dev build has its own `chrome_profile` that starts empty, and published dev builds
  (env redirect) start Chrome with `USERPROFILE` pointing at the dev folder. Needs a Windows repro on prod AND
  dev: log in, close Prism normally, reopen, repeat three times, note which sites drop.
- **Still unexplained until reproduced on Windows:** "file not uploaded sometimes", "mic not working",
  "download version issue". Do not claim a cause for these. Get the exact steps and the log first.
- **Also found:** the Desktop folder the engine picks for Artifacts is read from the registry with `%USERPROFILE%`
  expanded, and the Gerber, Leads, Email and Inquiries defaults were built from `~`, so on a dev build they pointed
  into the hidden data folder. Fixed with `output_folders.py` and `paths.user_folder()`.
- **Added:** Settings > Privacy & data now lets the person choose where Generated files, STEP files and Gerber
  reports are saved; and an Uninstall button (app only, or everything).
- **Check to add:** a Windows run of the checklist's "Windows first" block on a dev build, and the same on prod 1.6.10.

### ISS-011 — Test database folder wiped, 357 false failures (2026-10-27) — FIXED (process)
- **Seen:** the licence-server suite reported 357 failures.
- **Cause:** the scratch folder holding the throwaway SQLite file was cleared by a session restart, so every
  database test said "unable to open database file". Not a code problem.
- **Rule:** read the first error before reporting a count. Create the folder (`mkdir -p`) in the same command.

### ISS-010 — Linux signing refused after a lost output file (2026-10-27) — FIXED
- **Seen:** `sign_manifest` refused to sign `1.6.12` for linux-x64 because it had "already signed" it.
- **Cause:** a run killed mid-publish had signed and recorded the version, but its signed file was lost.
- **Fix:** `release_all` now reuses an already-signed local file; if it is lost, `--force` re-signs the same
  version (dev). Tests in `tests/test_release_mirror.py`.

### ISS-009 — Redirecting `USERPROFILE` for dev builds (2026-10-25 → 2026-10-27) — FIXED in code, UNVERIFIED on Windows
- **Cause:** `channel.isolate_home()` sets `HOME` and `USERPROFILE` to `~/.prism-dev-home` for dev builds so
  they cannot touch real data. On Windows the shell's per-user folders are defined in terms of `%USERPROFILE%`,
  and Qt/`QDir::homePath()` read it, so the whole process sees the wrong Downloads/Documents/Desktop.
- **Fix (committed, not yet in a published build):** isolate by patching Python's `os.path.expanduser` only,
  leaving the environment alone; every file picker starts in the real Downloads
  (`paths.picker_start_dir()`); visible default folders use the real home.
- **Check:** `tests/test_channel.py` (pure function plus a subprocess run that asserts the environment is
  unchanged), `tests/test_picker_start_dir.py`, `tests/test_output_folders.py`. **Still to do:** run the
  Windows checklist on a dev build that contains this fix. The Windows shell behaviour is inferred, not observed.
- **Lesson:** an isolation trick that changes the OS environment is a global side effect. Prefer the narrowest hook.

### ISS-008 — Dev version change had to be made in the Production box (2026-10-27) — FIXED (console), DESIGN GAP OPEN
- **Seen:** the owner changed the Development version to 1.6.12; the banner on dev builds 1.6.10 and 1.6.11
  appeared and went, and testing dev needed the Production number.
- **Cause:** 1.6.10 and 1.6.11 do not send `X-Prism-Channel` (it exists from 1.6.12), so the server treats
  them as production. The server was right and tested; the console buried the caveat in grey text and let
  Production be changed with one click.
- **Done:** a visible note on each box; a confirmation with a real count before Production's offered version changes.
- **Still open:** an old dev build can only follow Production. Fix: let the console mark individual computers as
  development (a per-device channel the server remembers), so no client change is needed.
- **Rule:** design every dev/prod control for the weakest, oldest client.

### ISS-007 — Console shipped with unreadable text and a phone layout that scrolled sideways (2026-10-27) — FIXED
- **Seen:** white-on-white seat counts, dark cards with dark text, teal initials at contrast 2.76, header and
  number cards overflowing at 400 px.
- **Cause:** the console had no browser test; the redesign was checked by eye.
- **Fix/check:** `license_server/tests/test_console_ui.py` — every tab, no sideways scroll at 1440 and 400 px,
  contrast of every visible text, issued key complete and copied whole, version change flow.

### ISS-006 — Activate button grey with no reason (2026-10-27) — FIXED
- **Seen:** a customer's key copied one character short left Activate disabled and silent.
- **Cause:** correct refusal, no explanation.
- **Fix/check:** the dialog says how many characters the key has, or that it does not look right, or that the
  documents are unread. `tests/test_license_legal.py`. **Rule:** a disabled control says why.

### ISS-005 — GitHub rate limit stopped publishing, and the status endpoint lied (2026-10-25) — KNOWN
- **Cause:** one three-platform publish uses all 5,000 requests per hour; `gh api rate_limit` reported a
  healthy count while calls were refused.
- **Rule:** read `x-ratelimit-reset` from the response headers, wait for it, resume (the script is resumable).

### ISS-004 — Manifest published before its files (2026-10-25) — FIXED
- **Seen:** a check made mid-publish was offered a version whose files were still uploading and failed.
- **Fix/check:** `release_all.do_platform` uploads files, then the signed manifest. Four tests in
  `tests/test_release_mirror.py`, including one that fails if the order reverts.

### ISS-003 — Old-client tests ran against current code (2026-10-23) — FIXED
- **Cause:** the dev repo's own `v1.6.10` tag points at current code, so "the real 1.6.10" was the new updater.
- **Fix/check:** `tests/old_release.py` trusts the tag by content, not by name.

### ISS-002 — Update tests proved only what the author knew (2026-10-23) — FIXED
- **Cause:** unit tests written from the code. **Fix:** an end-to-end harness in real processes against a
  GitHub-shaped local server, plus mutation checks (break the code on purpose, tests must fail).
  **Limit:** Linux/macOS only; Windows still needs real-machine runs.

### ISS-001 — A test overwrote the real `~/.prism/config.json` (2026-10-17) — FIXED
- **Cause:** a test reached `config.save()` against the real home. Groq key, agents and settings lost.
- **Rule:** anything that starts Prism runs with a sandbox home; hash the real config before and after.

---

## Known facts that cost hours — do not rediscover

- The real `v1.6.10` (Hitarth's repo) has **no auto-download**: banner, click Download, restart. Only the bridge
  and later have quiet updates. It reads one address and trusts one key (`u1`).
- Builds before 1.6.12 send no channel: they always follow the **Production** version.
- Signed lists for dev and prod are different keys; a dev list must be rejected by the prod key.
- macOS lists include symlink entries with no `size` and no file on the release; skip them when sampling.
- A push to the licence-server repo deploys production; the assistant's push there needs the owner's explicit word.
- Windows tests in `ci_known_failures.txt` (quotation PDF has no readable text) still fail and are a customer risk.

## 2026-11-23 — Sales/Studio build failed the packaged self-test: `No module named 'shapely'`

- Cause: `flavour.PACKAGE_NEEDS` excluded `shapely` (Gerber) from Sales and Studio, but `rapidocr_onnxruntime` and
  `rapidocr` import it unconditionally, and OCR is in every build. Same class as `av` (faster_whisper). CI run 45068377735.
- Fix: `shapely` moved to `flavour.ALWAYS_BUNDLED`. `tests/test_spec_flavours.py` now holds `RUNTIME_DEPENDENTS`
  (package -> bundled dependents) and fails if an exclusion has a dependent that stays bundled.
- Rule: before adding a package to `PACKAGE_NEEDS`, add its row to `RUNTIME_DEPENDENTS` from the installed metadata
  (`importlib.metadata` requires) plus a grep of site-packages. Unproven until a real CI build passes the packaged-app self-test.

## 2026-11-24 — Frozen builds never found their own bundled `dwg2dxf` (found during the bundle clean-up) — FIXED in code, not yet in a build

- Cause (LIKELY, from code, not run on a customer machine): `packaging/prism.spec` shipped `core/vendor/dwg2dxf/` under
  `prism_terminal/core/vendor/`, but `core/boq.py` looks next to its own `__file__`, which in a frozen build is
  `<bundle>/core/`. The 1.8.9 Windows zip has no `_internal/core/vendor/`, so `_ensure_bundled_dwg2dxf()` would say
  "missing from this copy of Prism" and DWG fell through to ODA / PATH / the install dialog. Every platform's copy also
  shipped in every build (the macOS 22 MB dylib in Windows, both in Linux).
- Fix: the spec ships only this platform's folder, at `core/vendor/dwg2dxf/<tag>` with its README (GPL source offer);
  Linux ships none. Behaviour change for customers: Windows and Apple Silicon builds now convert DWG with the bundled
  copy when ODA is absent.
- Check: `tests/test_spec_slim.py` (per-platform collection) and `main._trimmed_bundle_checks()` in the frozen self-test
  ("DWG converter bundled (<tag>)"), which proves the path inside the real build. Unproven until a CI build passes it.

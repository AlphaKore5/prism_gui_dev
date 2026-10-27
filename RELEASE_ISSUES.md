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
      machine only, Uninstall (app only / everything) really removes what it lists and nothing else (ISS-016).

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
  was run for real on throwaway folders; the Windows batch file was only generated and read in tests.
- **Risks to check on a spare Windows machine, never the owner's own:** the batch waits for the process to exit, removes
  the install folder (a zip folder, or `C:\Program Files\...` which needs admin and will simply fail), retries, removes
  itself, and leaves `%TEMP%\prism-uninstall.log`. Check all three outcomes: app only, everything, everything plus files.
- **Safety rules under test:** refuses from source; only names the running program's folder, Prism's data folder
  (`.prism` / `.prism-dev-home`) and folders named "Prism ..."; never a drive root, a home folder or its parent.
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

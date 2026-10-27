# Working on Prism with Claude

**Read `RELEASE_ISSUES.md` first, every time you build, tag, publish, push, change the
licence console, or change how a dev build runs.** It holds the pre-release checklist and
every release mistake already made. Add an entry there in the same session as any new
incident. Repeating a logged mistake is the failure the owner cares most about.

The owner's standing instruction (8 Sep 2026): every pull, merge, push and
every change to the codebase's structure follows the architecture rules,
so that modules stay independent and are easy to add, edit, update and
delete. Those rules are the repository's, not this file's — read them:

- `CONTRIBUTING.md` — the eight rules and how work lands.
- `docs/architecture/10-adding-an-add-on.md` — the shape of an add-on.
- `docs/architecture/09-boundaries.md` — why each rule exists and which
  test enforces it.

The short form, so nothing is done from memory:

1. An add-on is one folder, `addons/<key>/`, with a stdlib-only `addon.py`
   manifest, `contract.py`, `panel.py`, `dialog.py` and its own workers.
   The only shared file it touches is `addons/registry.py`, one line.
2. No add-on imports another add-on. Ask by intent (`addons/names.py`).
3. Only `core_bridge.py` imports the engine (`prism_terminal/`).
4. Every background thread subclasses `workers._Worker`.
5. Manifest, names and registry stay stdlib-only; registry imports are
   static, never `importlib`.
6. Licence feature keys and agent display names are frozen.
7. The build-contract files at the repo root never move.
8. A guard test is never deleted or skipped to make a change pass; if a
   rule must change, change it and its test in the same commit and say why.

Landing work:

- Pull, merge or push only when the owner asks in that message.
- `git config merge.renameLimit 999999`, `git fetch`, then **rebase** onto
  `origin/main`. Never merge, never force-push a shared branch.
- Push `prism_terminal` before `prism_gui` and bump the gitlink.
- Before every push: the full suite, one process per file as CI runs it,
  `QT_QPA_PLATFORM=offscreen .venv/bin/python devtools/suite_runner.py --timeout 300`
  (summary line `N tests in M files`; a single `pytest` over all ~6,000 tests stalls
  this machine), and `QT_QPA_PLATFORM=offscreen PRISM_SELFTEST=1 .venv/bin/python main.py`
  with `HOME` pointed at a sandbox.
- Windows first: a green Linux run proves nothing for customers. Read the
  `Tests · Windows` job of the last push before pushing again; a test that cannot run
  on Windows says why it skips.
- Write test logs and anything that must survive a session restart to
  `~/prism-test-logs/`, never the session scratch folder (a restart wipes it).
- After adding UI copy: `python3 devtools/extract_strings.py`, and read
  what it removed, not only what it added.
- Update the golden lists in the guard tests (`GOLDEN_RAIL`, `GOLDEN_HOME`,
  `PANELS`, `ADDON_FEATURES`) in the same commit as the add-on.

Testing traps: never call `processEvents()`, `exec()` or a `QEventLoop`
in a test; never write to the real `~/.prism` (conftest fails the run).

## Never do (each one cost the owner real data or trust)

- **Never let a test, script or harness reach the real `~/.prism`.** On
  2026-10-17 a STEP test that called `config.save()` overwrote the owner's real
  `config.json` — Groq key, agent choices, Email-inquiry settings — with its
  fixture (`api_key: "k"`). Nothing flagged it; the next launch said "Groq
  rejected your API key" and there was no backup. Rules that follow:
  - Any script that starts Prism or a dialog runs with `HOME` pointed at a
    sandbox (`make_sandbox.py`); never at the real home, never "just once".
  - A test that can reach `config.save`, `save_run` or `save_artifact` must
    patch it or use the temp `CONFIG_PATH` the conftest provides. When you change
    a guard or a code path that decides whether `_generate`/`save` is reached,
    re-read the tests that exercise it before running them.
  - Before running anything that might write, copy `~/.prism/config.json` aside
    and compare it after. The suite now fails if the real config's hash changes.
  - Never delete a sandbox that was copied from the real config until the real
    one is known good: it may be the only backup.
- **Never run `pkill -f` / `pgrep -f` with a pattern that appears in your own
  command line** — it kills your own shell (use a PID or `[x]yz` on a string not
  typed in the same command).
- **Never push, tag or release without the owner's explicit OK in that message**
  (see Landing work above).

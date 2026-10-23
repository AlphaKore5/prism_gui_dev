# The update system — read this before you touch it

Anyone changing how Prism updates itself reads this file first and ticks the
checklist at the bottom in the pull request. Updating is the one feature that
cannot be fixed by shipping an update: a client whose updater is broken stays
broken. Related: [`RELEASING-UPDATES.md`](../RELEASING-UPDATES.md) (the
release steps), `updater.py`, `update_manifest.py`, `apply_update.py`,
`channel.py`.

Plan and diagrams: `artifacts/update-plan-2026-10-23/` (outside this repo,
in the owner's `prism+gui/` folder): `overview-flow.html`,
`plan-v2-github-gitlab.html`.

## 1. The rule everything follows

**A client can only do what its own installed updater can do.** Whatever
version a customer runs today reads our manifest with that version's code,
for as long as they have not updated. So:

- New manifest fields must be ignorable by old clients (they are: `verify()`
  ignores unknown payload fields).
- An incompatible change gets a **new manifest name**; never reuse an old one
  (see section 4).
- A change to the updater ships alone, tested old-to-new, before anything is
  built on top of it.

## 2. Trust (do not weaken)

| Rule | Where |
|---|---|
| Manifest host is a fixed build constant, never from a server response | `updater.UPDATE_HOST` |
| Manifest is signed with the **update** key, not the licence key | `licensing/keys.py` |
| Nothing is trusted until: signature OK, not expired, newer than running, newer than `highest_seen_version`, every file hash OK | `updater.check_for_update`, `stage_update` |
| The running install is untouched until the staged tree is fully verified | `stage_update` |
| Old build is kept; a new build that does not confirm startup is rolled back | `apply_update.py` |
| The prod signing key is never in CI, never in the repo | `RELEASING-UPDATES.md` |
| The licence server has no say in what gets installed (it only supplies an unsigned banner hint) | `updater.py` docstring |

## 3. Channels: dev and prod

- `channel.CHANNEL` is `"prod"` in the repo. A dev build rewrites that one
  line at build time. It is never read from the environment or a server.
- A dev build keeps its data in `~/.prism-dev-home` (HOME/USERPROFILE are
  redirected by `channel.isolate_home()` before anything imports). This is
  because the engine and `prospector/` hard-code `expanduser("~")/.prism`;
  redirecting HOME covers them without editing the submodule.
- A source run can use `PRISM_HOME=/abs/path`. A frozen prod build **ignores**
  it, so a customer's environment cannot move their licence folder.
- **Keys:** `licensing/keys.py::update_public_keys()` — a frozen prod build
  trusts only `UPDATE_PRODUCTION`; a frozen dev build trusts only
  `UPDATE_DEVELOPMENT`; a source run trusts both. Neither can be updated from
  the other's manifests. The checked-in dev private key is *not* protected, so
  a dev-trusting binary must never reach a customer: `tests/test_channel_keys.py`
  pins `CHANNEL = "prod"` in the repo. Before dev builds go beyond our own
  machines, replace `udev1` with a key whose private half is a CI secret.
- **Building a dev build:** `PRISM_CHANNEL=dev [PRISM_UPDATE_REPO=owner/name]
  python packaging/build.py`. `packaging/build.py` rewrites `CHANNEL` and the
  `UPDATE_REPO` literal for the build and restores them afterwards (same
  pattern as `DEFAULT_SERVER`); it exits if a marker has moved, because an
  unbaked dev build would update from the production repo. The default dev
  repo `AlphaKore5/prism_gui_dev` (created 2026-10-23, empty so far) is where dev builds publish.
  `UPDATE_REPO` stays a plain literal in source, so the guard tests in `tests/test_update_channel.py` still hold.
- **Host failover (built):** `updater.UPDATE_FALLBACK_REPOS` lists repositories
  tried after `UPDATE_REPO`. Empty until the bridge release sets the org repo
  first and keeps the old one second. A repo that is down, stale or serving
  damaged bytes is skipped; each file is verified per host, so nothing the
  update key did not sign is installed. GitLab (a different URL scheme) is not
  built yet.
- Not built yet: GitLab adapter, `-dev.N` version suffix, dev publishing in CI,
  the promote script.

## 4. Changing something big (formats, layout, build engine, hosts)

The safest tool is already in the code: when macOS builds changed layout,
the channel name was retired (`macos-arm64` → `macos-arm64-app`). Old clients
asked for the old manifest, got a 404 and used the download page. Copy that:

1. Incompatible change → **new manifest filename** (and a `gen` number once
   the bridge release carries it). Never reuse an old name.
2. Publish old and new side by side during the transition. Retire the old
   one only when telemetry says few clients still need it.
3. Keep the swap helper (`apply_update.py`) tiny and stable. A bug there
   cannot be fixed by an update.
4. Every client must always be able to reach a full installer from the app.
5. A manifest may declare what it needs (`needs: [...]`); a client lacking a
   capability says "download the installer" instead of attempting it.
6. Ship one big change per release, never mixed with features.

## 5. Big downloads

Check free disk space for the staged copy plus backup before starting; resume
interrupted files; never block the UI; ask before a very large download.
GitHub caps a release at 1000 assets; the per-platform `-assets-<tag>-N` split
exists for that (`updater._assets_release_tag`).

## 6. User data

`~/.prism` outlives every update and every rollback. Migrations are additive
(add keys, never rename or delete in the same release), `config.json` is
backed up before any migration, and old keys are removed only two releases
after nothing reads them. Tests run against a sandbox home; they never touch
the real `~/.prism` (`tests/conftest.py` fails the run if the real config
changes).

## 7. Mirrors (planned, in the bridge release)

Hosts are interchangeable because every file is checked against the signed
manifest: a mirror can fail or go stale but cannot install anything forged.
The bridge adds a fixed ordered host list (GitHub, then GitLab), tried in
turn, and a signed `mirrors` list in the manifest that may only **add**
`static` hosts. A host with a different URL scheme is new code and therefore
a normal release.

## 8. Release policy fields (built) and rollout (partly built)

Three optional, signed fields in the `PRSMUv1` payload; clients built before
the bridge ignore them (proved by `tests/test_update_compat_1_6_10.py`, which
runs the real v1.6.10 updater against them):

| Field | Meaning | Client rule |
|---|---|---|
| `rollout` 0–100 | share of devices offered the release automatically | `check_for_update(honour_rollout=True)` places the device with `rollout_bucket(fingerprint, version)`; widening never removes a device. A customer pressing Download bypasses it. |
| `min_updater` | oldest `updater.UPDATER_LEVEL` that may install it | a lower level raises `UpdaterTooOld`, so the existing download-page fallback runs |
| `revoked` | versions to withdraw | never offered |

Set them with `devtools/sign_manifest.py --rollout N --min-updater N --revoke V`.
`check_policy()` rejects wrong types or ranges at signing time.

Known coupling: 1.6.10 reads no `rollout`, and the licence lease's
`latest_version` banner is unsigned and shown to everyone. While a release is
below 100% the licence server must not advertise it as `latest_version`, or the
banner's manual Download (which bypasses rollout) defeats the staging.

Still to build: the periodic automatic check that passes `honour_rollout=True`,
and the promote step that widens it.

## 8b. Patches (planned)

Dev first (our machines, dev key), then the same files promoted and re-signed
with the prod key at 5%, then 25%, then 100% (`rollout` in the signed manifest;
membership = `hash(device_id + version) mod 100 < rollout`). Patch and hotfix
lanes branch from the released tag. A signed `revoked` list stops a bad
version being offered.

## 9. Checklist for any change to updating

Copy into the PR and tick each line, or write why it does not apply.

- [ ] Old clients: what does the **oldest supported client** do when it meets
      this change? Tested old → new on **Windows and macOS**, not only Linux.
- [ ] No manifest name reused for an incompatible layout.
- [ ] New manifest fields are optional and ignorable by old clients, and
      `tests/test_update_compat_1_6_10.py` passes (it needs the `v1.6.10` tag:
      `git fetch --tags`; a skipped run proves nothing).
- [ ] Trust rules in section 2 unchanged, or the change is justified here.
- [ ] Dev key is not in any prod build's trusted keys.
- [ ] Prod signing key was not placed in CI or the repo.
- [ ] Failure leaves the running install untouched; rollback path tested.
- [ ] `~/.prism` data still readable by the previous version (additive only).
- [ ] A client can still reach a full installer if updating breaks.
- [ ] This file and `RELEASING-UPDATES.md` updated in the same commit.
- [ ] Tests added; no guard test deleted or skipped.
- [ ] Not pushed or released without the owner's explicit OK.

## 10. Known gaps (check before relying on them)

- The Windows and macOS swap paths have never run on real hardware
  (`apply_update.py` header).
- Rollback is self-reported; it cannot catch a build the OS refuses to start.
- macOS in-app updating is held until the Apple Developer ID and a real Mac
  test; manifests are per platform, so Windows/Linux can move first.
- Versions below 1.4.2 cannot self-update (first-launch rollback bug).

## 11. End-to-end tests: what they prove and what they do not

`tests/test_e2e_update.py` (harness: `tests/e2e_update_harness.py`) runs the real
updater, manifest, swap and rollback code in real separate processes against a
local server that copies GitHub's URL shapes and redirects. The "old" client is
the actual `v1.6.10` code extracted from the tag. 18 scenarios: 1.6.10 updating
to a release carrying every new policy field; changed-files-only downloads;
primary host down, corrupt, dropped mid-file, forged manifest, everything
unreachable; killed mid-download; a version that crashes on start being rolled
back and not offered again; rollout, revoked and `min_updater`.

Checked by breaking the code on purpose: removing the per-file hash check,
disabling rollback, and ignoring fallback hosts each make these tests fail.

**Not proved, do not claim:**
- Windows or macOS behaviour (file locks, antivirus, Gatekeeper, the `.bat`
  helper). The harness is Linux-only (`/bin/sh` wrapper).
- The real `main.py`, Qt, or a PyInstaller/Nuitka bundle. The app is a ~60 line
  stand-in; `TheStandInMatchesMain` only checks it makes the same updater calls.
- The real GitHub (redirect on our own repo, rate limits, asset caps).
- A full disk, a laptop sleeping mid-download, a proxy rewriting responses.
Those need the real-hardware runs listed in section 10.

## 12. Quiet updates and outcome reports (core built; UI not wired yet)

- `updater.auto_stage()` checks (honouring `rollout`), downloads and verifies in
  the background, and leaves the result waiting (`ready` in `update_state.json`,
  the signed manifest saved beside the stage as `<stage>.token`). It applies
  nothing. `updater.apply_ready()` is what a "Restart to update" button calls.
- `ready_update()` re-proves the stage every time it is asked: signature and
  expiry of the saved manifest, still newer than what runs, not failed, not
  revoked (including by any manifest seen since), and every staged file against
  the manifest. A stage that fails any of it is deleted, never applied.
- `stage_update()` refuses to start without room for the whole new tree plus a
  margin (`FREE_SPACE_*`), before writing anything.
- Outcomes (`downloaded`, `ok`, `failed`, `rolled_back`, with a fixed reason
  code, never a message) are queued in `update_state.json` and sent by
  `report_async()`. A server that is down keeps them for next time; only our own
  malformed request is dropped; reports older than 14 days are dropped.
  `ok` is reported by the first confirmed start after a swap; `rolled_back` by
  the version it rolled back to.
- Gotcha found by the tests: the pending-update marker holds the version swapped
  IN, not out, whatever `mark_pending_confirm`'s parameter is called. The
  version an update started from is `updater.staged_from()`.
- Known gap: a swap that fails inside the detached helper is only logged
  (`update-apply.log`); it is not reported, because the helper has no access to
  the queue.
- Still to wire: the timer and the "ready" banner in `main_window.py`.

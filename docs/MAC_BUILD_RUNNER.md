# Building the Mac app on our own Mac

GitHub's own Macs refused our builds (RELEASE_ISSUES.md, ISS-023), so the Mac app
is built on our Apple Silicon Mac. GitHub sends it a job, it builds, it sends the
result back. It costs nothing. Set-up takes about an hour, once.

**Nothing here has run on a real Mac yet.** The first build will show what is
missing. Parts 1 and 7 have decisions for the owner.

Two accounts are used below: **your account** (an administrator) and **prism-ci**
(a new, plain account that only builds).

---

## Part 1 — Read this first: the risk, and what limits it

The repository is public, so a stranger can open a pull request. GitHub's advice is
that self-hosted machines "should almost never be used for public repositories",
because a pull request can carry its own copy of the workflow file and ask for our
Mac. The check inside our own workflow file cannot stop that: the stranger edits it.

What does limit it, strongest first:

| Layer | What it does | Where |
|---|---|---|
| A private repository | Strangers cannot open pull requests. The real fix. | owner's decision |
| Approval before outside pull requests run | Nothing from an outsider runs until one of us clicks Approve | step 1 below |
| A script on the Mac that refuses the job | Only `build.yml` on `main` or a `v` tag, and `macos-pins.yml` on `main`, are let through | part 4 |
| A plain account with nothing in it | If something does get through, it finds no files, passwords or keys | part 2 |
| The job gets a read-only token and no secrets | It cannot change the repository | build.yml |
| The workflow's own check | Protects against our mistakes, not against strangers | build.yml |

The script on the Mac is a layer, not a wall. **Do not rely on it without step 1.**

**1. Change the approval setting before connecting the Mac.** On GitHub:
repository → Settings → Actions → General → **Approval for running fork pull
request workflows from contributors** → choose **Require approval for all external
contributors** → Save. (GitHub's weaker choices stop asking once somebody has had one
pull request merged.)

**2. Before clicking Approve on any outside pull request**, open its "Files changed"
tab. If it touches `.github/`, `packaging/` or `devtools/`, do not approve it until
someone has read it.

**3. A safer arrangement, if the repository stays public for long:** connect the Mac
to a small *private* repository that only fetches our public code and builds it. No
outsider can send it a job at all. It is not set up here, because the update
publishing tool expects the Mac build in the same run as Windows and Linux.

GitHub can also limit a machine to chosen workflows ("runner groups"), but only on
its paid Enterprise plan. Our organisation is on the free plan.

---

## Part 2 — Prepare the Mac (your account)

**4. Create the account.** System Settings → Users & Groups → Add User. Type:
**Standard** (not Administrator). Full name and account name: `prism-ci`. Give it a
strong password you do not use elsewhere.

**5. Close your own home folder to it.** In Terminal, in *your* account:

```bash
chmod 700 ~
```

Without this, another account on the same Mac can read some folders in your home.

**6. Install Apple's command line tools** (compiler and friends):

```bash
xcode-select --install
```

Click Install, wait, then check: `xcode-select -p` prints a folder.

**7. Install Python 3.12.10 from python.org.** Go to
<https://www.python.org/downloads/release/python-31210/>, download **macOS 64-bit
universal2 installer**, run it. Then open the folder *Applications → Python 3.12* and
double-click **Install Certificates.command**. Check:

```bash
/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 -V
```

It must print `Python 3.12.10`. Why this one:

- Prism needs 3.12 (build.yml says why). 3.12.10 is the last 3.12 that has a Mac installer.
- It is built for macOS 10.13 and later. Homebrew's Python and libraries are built for
  *your* macOS version, so an app made with them would not run on older Macs.
- GitHub's usual `actions/setup-python` step is not used: on a Mac it only works if the
  machine has a folder `/Users/runner/hostedtoolcache`, which our account does not own.

Homebrew is not needed. PortAudio (for the microphone) is built by the job itself, once.

**8. Disk space:** keep about 30 GB free (an estimate, not measured).

**9. Stop the Mac from sleeping while it is plugged in:**

```bash
sudo pmset -c sleep 0
pmset -g custom      # under "AC Power", sleep must say 0
```

The screen may still turn off; that is fine. A MacBook with its lid closed sleeps
anyway, so leave the lid open.

---

## Part 3 — Connect it to GitHub (prism-ci account)

**10.** Log in as **prism-ci** (use the user menu at the top right, "fast user
switching", so your own account stays open). When macOS offers to sign in with an
Apple Account, choose **Set Up Later / Skip**. Do not sign in to iCloud, Chrome, mail
or GitHub in this account, ever.

**11. Get the download commands.** In *your* browser: repository → Settings → Actions →
Runners → **New self-hosted runner** → macOS → **ARM64**. The page shows the download,
a checksum line and a token. The token works for one hour and for nothing else.

**12.** In **prism-ci's** Terminal, run the page's *Download* commands (they make a
folder `actions-runner`, download, check and unpack). Then, instead of the page's
*Configure* command, run this, with the page's token:

```bash
cd ~/actions-runner
./config.sh --url https://github.com/AlphaKore5/prism_gui_dev \
            --token PASTE_THE_TOKEN \
            --name prism-mac --labels prism-mac --work _work --unattended
```

GitHub adds `self-hosted`, `macOS` and `ARM64` by itself; our workflow asks for all four.
Do not start it yet: do part 4 first.

---

## Part 4 — Install the script that refuses other jobs

**13.** In *your* account (administrator), so that prism-ci cannot change it:

```bash
sudo mkdir -p /usr/local/prism-ci
sudo curl -fsSL -o /usr/local/prism-ci/job-guard.sh \
  https://raw.githubusercontent.com/AlphaKore5/prism_gui_dev/main/devtools/mac_runner_guard.sh
sudo chown -R root:wheel /usr/local/prism-ci
sudo chmod 755 /usr/local/prism-ci /usr/local/prism-ci/job-guard.sh
cat /usr/local/prism-ci/job-guard.sh      # read it: this is what protects the Mac
```

**14.** Check that it refuses:

```bash
GITHUB_EVENT_NAME=pull_request bash /usr/local/prism-ci/job-guard.sh; echo "exit $?"
```

It must print "This Mac refused the job" and `exit 1`.

**15.** In **prism-ci's** Terminal, tell the runner to use it, then start the service:

```bash
cd ~/actions-runner
echo 'ACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/prism-ci/job-guard.sh' >> .env
./svc.sh install && ./svc.sh start
./svc.sh status
```

(No `sudo`: the service belongs to prism-ci.)

**16. Check on GitHub:** Settings → Actions → Runners shows `prism-mac`, **Idle**, with a
green dot and the four labels.

**After every restart of the Mac, log in to prism-ci once** and switch back to your own
account. The service runs only while prism-ci is logged in (it can stay in the
background). With FileVault on, macOS cannot log it in by itself.

---

## Part 5 — Record the library versions (once, and after each deliberate change)

Every build installs exact library versions from a file (constraints/README.md). The Mac
file does not exist yet, and **the Mac build fails until it does**, as on Windows and
Linux: a build with unrecorded versions is not allowed to reach anyone.

**17.** GitHub → Actions → **Record macOS pin file** → Run workflow → branch `main`.

**18.** When it is green, look at the log's step "Set up runner": it must say `Allowed:`
(that is the script from part 4). If it says nothing, the script is not running; stop and
redo step 15.

**19.** Download the artifact `macos-arm64-pins`, unzip it, and commit the file as
`constraints/macos-arm64.txt`. The step "Compare with Linux" lists where the Mac got
different versions; differences there are a choice, not an accident to ignore.

---

## Part 6 — Switch the Mac build on

**20.** Repository → Settings → Secrets and variables → Actions → **Variables** → New
repository variable: name `PRISM_MAC_RUNNER`, value `on`.

Until it says `on`, every Mac job is skipped, so nothing waits for a Mac that is not there.
Delete it, or set it to `off`, when the Mac will be away for a while.

**21.** Try it: Actions → **Build desktop apps** → Run workflow → branch `main`. The job
is called **macOS (Apple Silicon)**.

From then on the Mac builds on: a push to `main`, a `v…` tag, the nightly run, and a manual
run from `main`. Never on a pull request. The tests are not run on the Mac; only the
"does the built app start" check is.

---

## Part 7 — Decision: the oldest macOS the app supports

It is set to **macOS 13 (Ventura)**: `MACOSX_DEPLOYMENT_TARGET` in
`.github/workflows/build.yml`, and the same number in `.github/workflows/macos-pins.yml`.
The app declares it, so an older Mac says "needs macOS 13" instead of crashing.

After each build, `packaging/check_macos_minos.py` reads the minimum out of every
program and library in the app and fails the job if one needs more. The DMG can still be
downloaded for a look (artifact `not-for-release-macos`), but it is never published.

**Expect the first build to fail this check.** These were measured from the real files:

| What | Needs | Who decides |
|---|---|---|
| PySide6 6.12.0 (the whole window system) | macOS 14 | its makers |
| onnxruntime 1.32.0, av 19.0.2 (OCR, speech) | macOS 14 | their makers |
| opencv 4.11, pypdfium2 5.15 | macOS 13 | their makers |
| `dwg2dxf` and `libredwg` inside our engine | **macOS 26** | us: rebuild them |

(The versions are the ones Linux uses; the recorded Mac file may have newer ones.)
The number only controls what the build compiles itself (PyAudio, PortAudio). It cannot
change a library that is downloaded ready-made. Choices:

- **Raise it to 14** (change the number in both files and in `tests/test_workflow_macos.py`).
  Simplest, and what the current libraries need.
- **Keep 13** and put older versions of those libraries in `constraints/macos-arm64.txt`.
  The Mac would then run an older PySide6 than Windows and Linux.

Either way `dwg2dxf` must be rebuilt for the chosen version (on this Mac, with
`MACOSX_DEPLOYMENT_TARGET` set) and committed to the engine. As it is, DWG files most
likely cannot be converted on any Mac older than macOS 26.

---

## Part 8 — Day to day

**If the Mac is off when a release is tagged:** Windows and Linux are published as usual;
they do not wait. The Mac job waits in GitHub's queue and starts by itself when the Mac
comes back. After **24 hours** GitHub cancels it. Then: start the Mac, open the tag's run,
and re-run the job "macOS (Apple Silicon)". When it succeeds, "Publish release (macOS
files)" adds the Mac files to the same release. Re-run within 14 days, while the run's
files still exist.

**The release is not finished until the Mac files are on it.** The signing step
(`devtools/release_all.py`) does Windows, Linux, then macOS, and stops at macOS if its
files are missing. Run it later for the Mac alone with `--only macos-arm64-app`.
Until then Mac customers are simply not offered the new version.

While a Mac job waits, the whole run shows as "in progress". That is all it holds up.

**Safest habit:** stop the service when no build is expected, start it for a release.

## Part 9 — Stop, update, remove

| | In prism-ci's Terminal, in `~/actions-runner` |
|---|---|
| Stop / start | `./svc.sh stop` / `./svc.sh start` |
| Is it running? | `./svc.sh status`; on GitHub: Idle, Active or Offline |
| Its log | `~/Library/Logs/actions.runner.*/` |
| Update the runner | It updates itself |
| Remove | `./svc.sh stop && ./svc.sh uninstall`, then `./config.sh remove --token …` (Settings → Actions → Runners → prism-mac → Remove shows the token) |

To remove everything: also delete `PRISM_MAC_RUNNER`, delete the prism-ci user, and
`sudo rm -r /usr/local/prism-ci`.

If a job ran that should not have: stop the service, remove the runner on GitHub, delete
the prism-ci account with its home folder, and start again from part 2. Do not "clean" it.

When `devtools/mac_runner_guard.sh` changes in the repository, the Mac does not notice:
repeat step 13.

## Part 10 — Signing, later

Builds are **unsigned** for now, so macOS warns on first launch (GETTING_STARTED.md).
Signing needs the Apple Developer Program (99 US dollars a year), which is not confirmed.
When it exists: `packaging/codesign.py` already does the work once it is given a
certificate, but the job gives it none on purpose. Adding it means a separate keychain
that is created and deleted within one run, with the certificate in GitHub's secrets.
Never install the certificate in prism-ci's own keychain, and do it only after the
repository is private.

---

Where the GitHub facts come from (read 25 Nov 2026): docs.github.com "Managing GitHub
Actions settings for a repository" (the approval options), "Actions limits" (24 hours in
the queue), "Secure use reference" (public repositories), "Running scripts before or after
a job" (the guard), "Managing access to self-hosted runners using groups". Not checked on
a real screen: the exact macOS menu wording and the Settings page layout.

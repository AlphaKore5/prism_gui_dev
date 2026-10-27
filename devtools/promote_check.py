"""Is this commit ready to become the production release, right now?

The owner's rule (2026-10-27): until they say "move to prod", every step is built
so that the moment they do, customers on 1.6.10 (who read Hitarth's repository)
see the download badge and can update. This is the gate that proves it, and it is
run at the end of every dev release. It changes nothing: it reads, runs tests,
and prints the exact steps for the day.

    python3 devtools/promote_check.py
    python3 devtools/promote_check.py --dev-proof        # also fetch the dev release as a 1.6.10 client would
    python3 devtools/promote_check.py --skip-tests       # while iterating

Each line is PASS, FAIL (do not promote), WARN (read it, decide) or MANUAL (a human
step this script cannot do). Exit 0 only if nothing FAILED.

What 1.6.10 does, and so what must be true (docs/PROMOTING-TO-PROD.md):
  - it reads ONE address: HitarthTrivedi/prism_gui, GitHub's "latest" release;
  - it trusts ONE key (u1), which only the owner holds;
  - it learns about an update from the licence server's PRODUCTION latest version
    (the banner) or from Settings > Check for updates; it never checks by itself;
  - a click on Download fetches the signed list and every file, then restarts.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

PROD_REPO = "HitarthTrivedi/prism_gui"
DEV_REPO = "AlphaKore5/prism_gui_dev"
LICENCE_SERVER = "https://prism-license-server.onrender.com"
OLDEST_CUSTOMER_VERSION = "1.6.10"
OLD_CLIENT_TESTS = ("tests/test_update_compat_1_6_10.py", "tests/test_e2e_update.py",
                    "tests/test_check_as_old_client.py", "tests/test_update_channel.py")

PASS, FAIL, WARN, MANUAL = "PASS", "FAIL", "WARN", "MANUAL"


@dataclass
class Result:
    status: str
    name: str
    detail: str = ""


def version_tuple(text: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in text.strip().lstrip("v").split("."))
    except ValueError:
        return ()


def _run(*cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True, timeout=timeout)


def current_version() -> str:
    import app_meta
    return app_meta.VERSION


# ── the checks ────────────────────────────────────────────────────────────────
def check_version(version: str, prod_tags: list[str]) -> Result:
    have = version_tuple(version)
    if not have or have <= version_tuple(OLDEST_CUSTOMER_VERSION):
        return Result(FAIL, "version", f"{version} is not newer than {OLDEST_CUSTOMER_VERSION}, so 1.6.10 would never offer it")
    newest = max((version_tuple(t) for t in prod_tags if version_tuple(t)), default=())
    if f"v{version}" in prod_tags:
        return Result(FAIL, "version", f"v{version} already exists on {PROD_REPO}; production versions are never reused")
    if newest and have <= newest:
        return Result(FAIL, "version", f"{version} is not newer than the newest production tag v{'.'.join(map(str, newest))}")
    return Result(PASS, "version", f"{version} is newer than every production tag (newest v{'.'.join(map(str, newest)) or '?'})")


def prod_tags() -> list[str]:
    out = _run("git", "ls-remote", "--tags", "--refs", f"https://github.com/{PROD_REPO}.git", timeout=60)
    if out.returncode != 0:
        return []
    return [line.split("refs/tags/")[-1] for line in out.stdout.splitlines()
            if "assets" not in line and "refs/tags/" in line]


def check_tree_clean() -> Result:
    status = _run("git", "status", "--porcelain", "--untracked-files=no").stdout
    lines = [l for l in status.splitlines() if l.strip()]
    engine = [l for l in lines if l.strip().endswith("prism_terminal")]
    dirty = [l for l in lines if l not in engine]
    if engine:
        # RELEASE_ISSUES.md ISS-017: a checkout of the engine that differs from the commit git records
        # is what let `git add -A` silently roll the engine back and break another person's BOQ work.
        return Result(FAIL, "engine checkout", "your engine folder is not at the commit git records. Run "
                                               "`git submodule update --init prism_terminal`, and stage files by name, never `git add -A`")
    if dirty:
        return Result(FAIL, "clean tree", f"{len(dirty)} uncommitted change(s); promote a commit, not a working folder")
    return Result(PASS, "clean tree", "everything is committed, and the engine folder is at the recorded commit")


#: Paths that are not part of the shipped app. A commit that touches only these after the dev release
#: leaves the tested code unchanged, so it does not break "promote what was tested".
NON_SHIPPING = ("docs/", "devtools/", "tests/", "RELEASE_ISSUES.md", "CLAUDE.md", "CHANGES.md", "BOQ-CHANGES-TODO.md")
#: ...except these, which decide how production is BUILT or PUBLISHED. A change to them after the dev
#: release means the dev release never exercised it (the workflow is outside NON_SHIPPING already).
PUBLISHING = ("devtools/release_all.py", "devtools/sign_manifest.py", "devtools/verify_upload.py")


def shipped_changes(paths: list[str]) -> list[str]:
    return [p for p in paths
            if p in PUBLISHING or not any(p == n or p.startswith(n) for n in NON_SHIPPING)]


def check_dev_tag(version: str) -> Result:
    """The dev release of THIS version was built from THIS commit, or from an earlier one that differs
    only in files that do not ship (docs, tests, tools)."""
    head = _run("git", "rev-parse", "HEAD").stdout.strip()
    out = _run("git", "ls-remote", f"https://github.com/{DEV_REPO}.git", f"refs/tags/v{version}", f"refs/tags/v{version}^{{}}")
    shas = [line.split()[0] for line in out.stdout.splitlines() if line.strip()]
    if not shas:
        return Result(FAIL, "dev release", f"no tag v{version} on the dev repo: this commit has not been through a dev release, and only what was tested is promoted")
    if head in shas:
        return Result(PASS, "dev release", f"v{version} on the dev repo is exactly this commit ({head[:8]})")
    for sha in shas:
        if _run("git", "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
            continue
        changed = _run("git", "diff", "--name-only", sha, "HEAD").stdout.split()
        shipped = shipped_changes(changed)
        if not shipped:
            return Result(PASS, "dev release", f"v{version} was built from {sha[:8]}; since then only docs, tests and tools changed ({len(changed)} files), nothing that ships")
        return Result(FAIL, "dev release", f"code that ships changed since the dev release v{version} ({sha[:8]}): {', '.join(shipped[:4])}. Promote what was tested")
    return Result(FAIL, "dev release", f"the dev tag v{version} is not an ancestor of HEAD ({head[:8]}); promote what was tested")


def check_engine_commit() -> Result:
    """The engine commit this release records must exist where the build fetches it."""
    sha = _run("git", "ls-tree", "HEAD", "prism_terminal").stdout.split()
    if len(sha) < 3:
        return Result(WARN, "engine", "no prism_terminal gitlink found")
    sha = sha[2]
    url = ""
    for line in open(os.path.join(ROOT, ".gitmodules"), encoding="utf-8"):
        if "url" in line and "=" in line:
            url = line.split("=", 1)[1].strip()
    repo = re.sub(r"^https://github.com/|\.git$", "", url)
    out = _run("gh", "api", f"repos/{repo}/commits/{sha}", "--jq", ".sha")
    if out.returncode == 0 and out.stdout.strip().startswith(sha[:10]):
        return Result(PASS, "engine", f"engine commit {sha[:10]} exists on {repo}, where the build fetches it")
    return Result(FAIL, "engine", f"engine commit {sha[:10]} is NOT on {repo}: the production build would fail. "
                                  "Push the engine first (CLAUDE.md: engine before GUI)")


def check_channel_defaults() -> Result:
    import channel
    if channel.CHANNEL != "prod":
        return Result(FAIL, "channel", f"channel.CHANNEL is {channel.CHANNEL!r} in the source; it must ship as 'prod'")
    import updater
    if updater.UPDATE_REPO != "AlphaKore5/prism_gui" or "HitarthTrivedi/prism_gui" not in updater.UPDATE_FALLBACK_REPOS:
        return Result(FAIL, "update hosts", f"unexpected update hosts: {updater.UPDATE_REPO} / {updater.UPDATE_FALLBACK_REPOS}")
    return Result(PASS, "channel", "the source ships as prod; updates ask the organisation first and Hitarth's repo as the fallback")


def check_workflow_gate(text: str | None = None) -> Result:
    if text is None:
        text = open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8").read()
    m = re.search(r"release:\s*\n(?:.*\n){0,6}?\s*needs:\s*(\[[^\]]*\]|\S+)", text)
    needs = m.group(1) if m else ""
    if "tests" not in needs or "build" not in needs:
        return Result(FAIL, "release gate", f"the release job must wait for the builds AND the tests (needs: {needs or 'unknown'})")
    return Result(PASS, "release gate", "the release job waits for the builds and the tests")


def check_old_client_tests() -> Result:
    py = sys.executable
    run = _run(py, "-m", "pytest", "-q", "-p", "no:cacheprovider", *OLD_CLIENT_TESTS, timeout=900)
    tail = " ".join(run.stdout.strip().splitlines()[-1:])[:140]
    if run.returncode == 0:
        return Result(PASS, "real 1.6.10 client", "the released 1.6.10 updater code updates this tree in real processes "
                                                     "(compat, end-to-end, rehearsal tool, channel keys)")
    return Result(FAIL, "real 1.6.10 client", f"a 1.6.10 client would NOT take this tree: {tail}")


def check_dev_proof(version: str) -> Result:
    run = _run(sys.executable, os.path.join("devtools", "check_as_old_client.py"), "--repo", DEV_REPO, "--trust", "dev",
               "--expect-version", version, "--samples", "2", timeout=1200)
    text = run.stdout.strip()
    if run.returncode == 0:
        return Result(PASS, "dev release as a 1.6.10 client", "every platform: offered, signature accepted, files match")
    return Result(FAIL, "dev release as a 1.6.10 client", text.splitlines()[-3:][0] if text else "the rehearsal failed")


def check_licence_server() -> Result:
    try:
        health = urllib.request.urlopen(f"{LICENCE_SERVER}/health", timeout=30).status
    except Exception as error:                              # noqa: BLE001
        return Result(WARN, "licence server", f"could not reach it ({error}); the banner needs it")
    try:
        req = urllib.request.Request(f"{LICENCE_SERVER}/admin/versions")
        urllib.request.urlopen(req, timeout=30)
        code = 200
    except urllib.error.HTTPError as e:                     # 401 = the route exists and wants the token
        code = e.code
    except Exception:                                       # noqa: BLE001
        code = 0
    if health == 200 and code == 401:
        return Result(PASS, "licence server", "up, and it has the version controls the banner depends on")
    return Result(WARN, "licence server", f"health {health}, versions route {code or 'unreachable'} (expected 200 and 401): deploy before promoting")


def open_issues(text: str | None = None) -> list[tuple[str, str]]:
    """(id, heading) of every RELEASE_ISSUES.md entry whose status is OPEN or UNVERIFIED.
    The status is the last part of the heading, after the final " — "."""
    if text is None:
        path = os.path.join(ROOT, "RELEASE_ISSUES.md")
        if not os.path.exists(path):
            return []
        text = open(path, encoding="utf-8").read()
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("### ISS-"):
            continue
        heading = line.lstrip("# ").strip()
        status = heading.rsplit(" — ", 1)[-1]
        if re.search(r"\b(OPEN|UNVERIFIED)\b", status):
            out.append((heading.split()[0], heading))
    return out


def check_open_issues() -> Result:
    issues = open_issues()
    if not issues:
        return Result(PASS, "open issues", "RELEASE_ISSUES.md has nothing open or unverified")
    return Result(WARN, "open issues", f"{len(issues)} you would be accepting: " + "; ".join(i for i, _ in issues))


def manual_steps(version: str) -> list[Result]:
    return [
        Result(MANUAL, "licence server: Production latest version",
               f"must still be {OLDEST_CUSTOMER_VERSION} (or empty) until the production release is published and the 1.6.10 check passes, "
               "or customers are shown a banner for a version that does not exist yet"),
        Result(MANUAL, "your own installs", "update your own real 1.6.10 Windows and Mac installs first, with Settings > Check for updates"),
        Result(MANUAL, "Windows checklist", "RELEASE_ISSUES.md 'Windows first' block, run on the dev build of this same commit"),
    ]


def plan_text(version: str) -> str:
    return f"""
THE DAY YOU SAY "MOVE TO PROD" (each step names who must act; nothing here has been done)
  1. You say so.                                       -> nothing customers can see changes yet
  2. Push this exact commit to {PROD_REPO} and tag v{version}.   [needs your explicit OK in that message]
       CI builds the production installers (no dev settings exist there) and runs the tests first.
  3. Sign the update lists with the production key.    [you: offline, human; never CI, never Claude]
       python3 devtools/release_all.py v{version} <run id>      (publishes to Hitarth's repo, then mirrors to the organisation)
  4. Prove a real 1.6.10 would take it:
       python3 devtools/check_as_old_client.py --expect-version {version}      (must say PASS on every platform)
  5. Update your own machines, then phone the first customers: Settings > Check for updates.
       Anyone who presses it gets the update as soon as step 3 finishes; the banner is not needed.
  6. Raise Production's latest version to {version} in the licence console (Releases tab; it asks first and shows how many
       computers will see the banner). From this moment every 1.6.10 shows "Prism {version} is available" with Download.
  7. Watch the "Who has updated" table. Raise the banner earlier or later as you like; Check for updates always works.
  What a 1.6.10 customer sees: the banner, Download, a progress count, Restart, then {version}. If the new build will not start it
  rolls back to 1.6.10 by itself and the same release is not offered again on that computer.
"""


def run(args) -> int:
    version = current_version()
    results: list[Result] = []
    tags = prod_tags()
    results.append(check_version(version, tags))
    results += [check_tree_clean(), check_dev_tag(version), check_engine_commit(),
                check_channel_defaults(), check_workflow_gate()]
    if not args.skip_tests:
        results.append(check_old_client_tests())
    if args.dev_proof:
        results.append(check_dev_proof(version))
    results += [check_licence_server(), check_open_issues()]
    results += manual_steps(version)

    width = max(len(r.name) for r in results)
    print(f"Promotion readiness for {version} (HEAD {_run('git', 'rev-parse', '--short', 'HEAD').stdout.strip()})\n")
    for r in results:
        print(f"  {r.status:<6} {r.name:<{width}}  {r.detail}")
    failed = [r for r in results if r.status == FAIL]
    print()
    print("NOT READY: " + ", ".join(r.name for r in failed) if failed else "READY: nothing blocks promotion (read the WARN and MANUAL lines).")
    print(plan_text(version))
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dev-proof", action="store_true", help="also rehearse the published dev release as a 1.6.10 client")
    ap.add_argument("--skip-tests", action="store_true", help="skip the real-1.6.10 end-to-end tests (minutes)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

"""Would a real 1.6.10 install accept this release?

Runs the code of the released v1.6.10 tag, unchanged, against a published
release and reports what that client would do: find the signed manifest where
1.6.10 looks for it, accept the signature with the keys 1.6.10 trusts, offer
the version as newer, and fetch the per-file assets from where 1.6.10 looks
for them, with the size and hash checks 1.6.10 applies.

1.6.10 reads ONE address, `releases/latest/download` of HitarthTrivedi/prism_gui,
and trusts ONE key (u1). Anything published only to the organisation repo, any
manifest not signed with u1, a release that is not GitHub's "latest", or a file
named differently, is invisible to every customer still on 1.6.10 -- and
nothing in CI, the signing step or the release script notices.

    python3 devtools/check_as_old_client.py --expect-version 1.6.12
    python3 devtools/check_as_old_client.py --platform windows-x64 --samples 6

Run it after `release_all.py` and BEFORE raising the latest-version banner or
telling anyone to update. Exit 0 only if every platform checked passes.

Rehearsal against the DEV repository (the real 1.6.10 code, dev address, dev key):

    python3 devtools/check_as_old_client.py --repo AlphaKore5/prism_gui_dev \\
        --trust dev --expect-version 1.6.12

It reads public download URLs only, so it uses none of the GitHub API quota and
needs no token. It never touches ~/.prism: the old code runs with a throwaway HOME.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
TAG = "v1.6.10"
PLATFORMS = ("windows-x64", "macos-arm64-app", "linux-x64")
OLD_MODULES = ["app_meta.py", "paths.py", "updater.py", "update_manifest.py",
               "apply_update.py", "licensing"]

#: Runs inside the extracted 1.6.10 tree, in its own interpreter, so the old
#: modules never mix with the current ones.
DRIVER = r'''
import hashlib, json, os, random, sys, urllib.request
tree, platform, repo, samples, github_base, trust_json = sys.argv[1:7]
sys.path.insert(0, tree)
import app_meta, licensing, update_manifest, updater

out = {"running": app_meta.VERSION}
updater.platform_tag = lambda: platform
updater.UPDATE_REPO = repo
updater.UPDATE_HOST = f"https://github.com/{repo}/releases/latest/download"
trust = json.loads(trust_json)
if trust:
    licensing.keys.update_public_keys = lambda: dict(trust)
out["keys_trusted"] = sorted(licensing.keys.update_public_keys())

def fetch(url, timeout=30):
    if github_base:
        url = url.replace("https://github.com", github_base, 1)
    with urllib.request.urlopen(url, timeout=max(timeout, 60)) as r:
        return r.read()

try:
    check = updater.check_for_update(running="1.6.10", fetch=fetch)
except Exception as e:
    out.update(ok=False, stage="manifest", error=f"{type(e).__name__}: {e}")
    print(json.dumps(out)); raise SystemExit(0)
if check is None:
    out.update(ok=False, stage="offer",
               error="the 1.6.10 updater found nothing to offer: no manifest at "
                     f"{updater._manifest_url()}, a signature it does not accept, "
                     "or a version that is not newer than 1.6.10")
    print(json.dumps(out)); raise SystemExit(0)

files = check.manifest.get("files", [])
real = [f for f in files if "symlink" not in f and f.get("size")]
by_part = {}
for f in real:
    by_part.setdefault(update_manifest.part_of(f), []).append(f)
random.seed(1)
bad, ok = [], 0
for part, group in sorted(by_part.items()):
    for f in random.sample(group, min(int(samples), len(group))):
        url = updater._file_url(check.version, f["path"], part)
        try:
            data = updater._get(url, timeout=60, fetch=fetch, max_bytes=f["size"])
            good = len(data) == f["size"] and hashlib.sha256(data).hexdigest() == f["sha256"]
        except Exception as e:
            good = False; bad.append(f"{f['path'][:60]}: {type(e).__name__}")
            continue
        if good: ok += 1
        else: bad.append(f"{f['path'][:60]}: wrong size or hash")
out.update(ok=not bad and ok > 0, stage="files", version=check.version, files=len(files),
           parts=sorted(by_part), sampled_ok=ok, sampled_bad=bad,
           policy={k: check.manifest[k] for k in ("rollout", "min_updater", "revoked") if k in check.manifest})
print(json.dumps(out))
'''


def extract_old_tree(dest: str) -> None:
    import old_release
    why = old_release.skip_reason(TAG)
    if why:
        raise SystemExit(f"cannot rehearse as 1.6.10: {why}")
    data = subprocess.run(["git", "archive", TAG, *OLD_MODULES], cwd=ROOT,
                          capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=data, check=True)


def trusted_keys(mode: str, extra_pub: str) -> dict:
    """{} = leave the 1.6.10 build's own key list alone (the real thing)."""
    if mode == "prod":
        return {}
    sys.path.insert(0, ROOT)
    from licensing import keys
    if mode == "dev":
        return dict(keys.UPDATE_DEVELOPMENT)
    return {"u1": extra_pub}              # the key id the fixtures are signed under


def check_platform(tree: str, platform: str, repo: str, samples: int,
                   github_base: str, trust: dict, expect: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="old-client-home-") as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE="1")
        for k in ("PRISM_HOME", "PRISM_CHANNEL"):
            env.pop(k, None)
        run = subprocess.run(
            [sys.executable, "-I", "-B", "-c", DRIVER, tree, platform, repo, str(samples),
             github_base, json.dumps(trust)],
            capture_output=True, text=True, env=env, cwd=home)
    try:
        result = json.loads(run.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "stage": "driver", "error": (run.stderr or run.stdout)[-400:]}
    if result.get("ok") and expect and result.get("version") != expect:
        result.update(ok=False, stage="version",
                      error=f"1.6.10 would be offered {result.get('version')}, expected {expect}")
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default="HitarthTrivedi/prism_gui",
                    help="the repository to read (default: the one 1.6.10 reads)")
    ap.add_argument("--platform", action="append", choices=PLATFORMS,
                    help="repeatable; default all three")
    ap.add_argument("--expect-version", default="", help="fail unless this is what 1.6.10 is offered")
    ap.add_argument("--samples", type=int, default=3, help="files to fetch per part (default 3)")
    ap.add_argument("--trust", choices=("prod", "dev", "test"), default="prod",
                    help="prod = the keys 1.6.10 ships with; dev = the dev key, for a rehearsal")
    ap.add_argument("--test-pub", default="", help="with --trust test: the public key (hex)")
    ap.add_argument("--github-base", default="",
                    help="replace https://github.com (a local fake, for the tests)")
    args = ap.parse_args(argv)

    if args.repo == "HitarthTrivedi/prism_gui" and args.trust != "prod" and not args.github_base:
        print("refusing: the production repository is read with the production keys only")
        return 2
    platforms = args.platform or list(PLATFORMS)
    trust = trusted_keys(args.trust, args.test_pub)
    failed = 0
    with tempfile.TemporaryDirectory(prefix="old-client-tree-") as tree:
        extract_old_tree(tree)
        print(f"Rehearsing as the released {TAG} against {args.repo} "
              f"(keys: {args.trust}{', ' + args.github_base if args.github_base else ''})")
        for plat in platforms:
            r = check_platform(tree, plat, args.repo, args.samples, args.github_base, trust, args.expect_version)
            if r.get("ok"):
                pol = f"  policy fields it ignores: {r['policy']}" if r.get("policy") else ""
                print(f"  PASS {plat}: would be offered {r['version']} ({r['files']} files, parts {r['parts']}); "
                      f"{r['sampled_ok']} sampled files match size and hash{pol}")
            else:
                failed += 1
                why = r.get("error") or "; ".join(r.get("sampled_bad", []))
                print(f"  FAIL {plat} [{r.get('stage')}]: {why}")
    print("RESULT:", "every platform passes" if not failed else f"{failed} platform(s) would NOT update from 1.6.10")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

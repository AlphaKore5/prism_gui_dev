"""End-to-end harness for the in-app updater.

What is real: the updater, manifest, swap and rollback code (the v1.6.10 tag's
own modules for the "old" client, the working tree's for the "new" one), real
processes, real HTTP through `requests` including GitHub's redirect from
releases/.../download/X to a CDN, real files on disk, real renames.

What is stand-in, on purpose (read before trusting a green run):
  * The app is a ~60 line launcher (LAUNCHER below) that does what main.py does
    around updating: rollback check, startup confirmation, the update flow.
    It is NOT main.py, Qt or the 2 GB bundle. A test in test_e2e_update.py
    compares its calls with main.py's so the two cannot drift silently.
  * github.com is redirected to a local server by a requests adapter; the URLs
    the updater builds are untouched and are what the server routes on.
  * "Frozen" is faked with sys.frozen and a patched sys.executable.
  * Linux only (a /bin/sh wrapper). This proves the logic on a real
    filesystem. It proves nothing about Windows locks, antivirus, Gatekeeper.
"""
from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manifest as UM
import updater
import flatten_update_assets

PRIMARY = "HitarthTrivedi/prism_gui"
FALLBACK = "AlphaKore5/prism_gui"
PROD_UPDATE_PUB = "49f27ccbfba0e52b62f1244ba63c2a54bf81fa3ff13d9d88be802dbc68496d4e"
MODULES = ["app_meta.py", "paths.py", "updater.py", "update_manifest.py",
           "apply_update.py", "licensing"]
OLD_TAG = "v1.6.10"


def keypair() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
    sec = priv.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                             _ser.NoEncryption()).hex()
    return sec, pub


def tag_available(tag: str = OLD_TAG) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", tag + "^{commit}"],
                          cwd=ROOT, capture_output=True).returncode == 0


def extract_tag(dest: str, tag: str = OLD_TAG) -> str:
    os.makedirs(dest, exist_ok=True)
    data = subprocess.run(["git", "archive", tag, *MODULES], cwd=ROOT,
                          capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=data, check=True)
    return dest


# ── the stand-in app ─────────────────────────────────────────────────────────
LAUNCHER = r'''
import json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.frozen = True                                   # paths.is_frozen()
sys.executable = os.path.join(INSTALL, "Prism")     # updater.install_dir()
HOME = os.environ["HOME"]


def log(event, **kw):
    kw.update(event=event, pid=os.getpid(), t=time.time())
    with open(os.path.join(HOME, "events.log"), "a") as f:
        f.write(json.dumps(kw) + "\n")


import app_meta, paths, licensing, updater, apply_update
VERSION = app_meta.VERSION

port = os.environ.get("PRISM_E2E_PORT")
# The frozen build's licence server is the real production one. A test must
# never reach it: aim it at the local server (or a dead port) and give the
# process a stand-in licence and device id.
import licensing.client as _lc
_lc.DEFAULT_SERVER = "http://127.0.0.1:" + (port or "9")
licensing.store.load = lambda _dir: {"license_id": "lic_e2e"}
licensing.device_fingerprint = lambda: "e2e-device-0001"
if port:
    import requests
    from requests.adapters import HTTPAdapter

    class Rewrite(HTTPAdapter):
        def send(self, request, **kw):
            request.url = request.url.replace(
                "https://github.com", "http://127.0.0.1:" + port, 1)
            return super().send(request, **kw)
    _s = requests.Session()
    _s.mount("https://github.com", Rewrite())
    updater._session = _s

args = sys.argv[1:]
if args[:1] == ["--prism-apply-update"]:                    # main.py's helper branch
    code = apply_update.perform_apply_and_relaunch(
        int(args[1]), args[2], args[3], args[4], updater.relaunch_argv())
    log("helper_done", code=code)
    sys.exit(code)

d = updater.install_dir()
if apply_update.check_and_rollback_if_pending(d, d + ".old"):   # main.py, early
    log("rolled_back", version=VERSION)
    updater.note_rollback(VERSION)
    if hasattr(updater, "note_outcome"):
        updater.note_outcome("rolled_back", VERSION, reason="no_confirm")
    apply_update.spawn_detached(updater.relaunch_argv())
    sys.exit(0)

log("start", version=VERSION)
if os.path.exists(os.path.join(HERE, "crash_on_start")):
    log("crash", version=VERSION)
    sys.exit(3)
_updated = apply_update.pending_update_version(d) if hasattr(
    apply_update, "pending_update_version") else ""              # main.py, before confirm
apply_update.confirm_startup_success(d, d + ".old")             # main.py, window up
updater.note_installed(VERSION)
if _updated and hasattr(updater, "note_outcome"):
    updater.note_outcome("ok", VERSION, from_version=updater.staged_from())
log("confirmed", version=VERSION)
if "--flush" in args:                                           # report_async, synchronously
    log("flushed", sent=updater.flush_outbox())
    sys.exit(0)

if "--auto-stage" in args:                                      # the quiet background path
    try:
        staged = updater.auto_stage()
        if staged:
            log("ready", version=staged.version)
        else:
            log("no_update")
    except updater.UpdateError as e:
        log("update_failed", kind=type(e).__name__, msg=str(e)[:300])
    sys.exit(0)

if "--apply-ready" in args:                                     # customer pressed Restart
    try:
        updater.apply_ready()
        log("apply_started")
    except updater.UpdateError as e:
        log("update_failed", kind=type(e).__name__, msg=str(e)[:300])
    sys.exit(0)

if "--update" in args or "--auto" in args:                      # main_window.py flow
    import inspect
    kw = {}
    if "--auto" in args and "honour_rollout" in inspect.signature(
            updater.check_for_update).parameters:
        kw["honour_rollout"] = True
    try:
        check = updater.check_for_update(**kw)
        if check is None:
            log("no_update")
            sys.exit(0)
        log("offered", version=check.version)
        staged = updater.stage_update(check, updater.install_dir())
        log("staged", version=staged.version)
        updater.begin_apply(staged, updater.install_dir())
        log("apply_started")
    except updater.UpdateError as e:
        log("update_failed", kind=type(e).__name__, msg=str(e)[:300])
    sys.exit(0)
'''


def build_tree(dest: str, version: str, src: str, *, test_pub: str,
               repo: str = PRIMARY, fallbacks: tuple[str, ...] = (),
               crash_on_start: bool = False, payload: str = "") -> str:
    """An installed 'Prism' folder: wrapper + _internal/ with real modules."""
    install = os.path.join(dest, "Prism")
    internal = os.path.join(install, "_internal")
    os.makedirs(internal)
    for name in MODULES + (["channel.py"] if os.path.exists(os.path.join(src, "channel.py")) else []):
        s = os.path.join(src, name)
        d = os.path.join(internal, name)
        if os.path.isdir(s):
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(s, d)

    def patch(rel: str, old: str, new: str, *, must: bool = True):
        path = os.path.join(internal, rel)
        text = open(path, encoding="utf-8").read()
        if old not in text:
            if must:
                raise AssertionError(f"{rel}: {old!r} not found -- harness out of date")
            return
        open(path, "w", encoding="utf-8").write(text.replace(old, new, 1))

    import re
    meta = open(os.path.join(internal, "app_meta.py"), encoding="utf-8").read()
    cur = re.search(r'^VERSION = "([^"]+)"', meta, re.M).group(1)
    patch("app_meta.py", f'VERSION = "{cur}"', f'VERSION = "{version}"')
    patch(os.path.join("licensing", "keys.py"), PROD_UPDATE_PUB, test_pub)
    if repo != PRIMARY:
        patch("updater.py", f'UPDATE_REPO = "{PRIMARY}"', f'UPDATE_REPO = "{repo}"')
    if fallbacks:
        patch("updater.py", "UPDATE_FALLBACK_REPOS: tuple[str, ...] = ()",
              f"UPDATE_FALLBACK_REPOS: tuple[str, ...] = {fallbacks!r}", must=False)
    open(os.path.join(internal, "launcher.py"), "w").write(LAUNCHER)
    open(os.path.join(internal, "payload.txt"), "w").write(payload or f"payload of {version}\n")
    if crash_on_start:
        open(os.path.join(internal, "crash_on_start"), "w").write("x")
    wrapper = os.path.join(install, "Prism")
    with open(wrapper, "w") as f:
        f.write('#!/bin/sh\nD="$(cd "$(dirname "$0")" && pwd)"\n'
                f'exec "{sys.executable}" -I -B "$D/_internal/launcher.py" "$@"\n')
    os.chmod(wrapper, 0o755)
    return install


def tree_digest(root: str) -> dict[str, str]:
    out = {}
    for d, _dirs, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            if os.path.islink(p):
                continue
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


# ── a release, as published ──────────────────────────────────────────────────
class Release:
    def __init__(self, work: str, version: str, src: str, *, sec: str, pub: str,
                 policy: dict | None = None, fallbacks=(FALLBACK,), repo=PRIMARY,
                 crash_on_start=False, payload="", label=""):
        self.version = version
        self.tree = build_tree(os.path.join(work, f"release-{version}{label}"), version, src,
                               test_pub=pub, repo=repo, fallbacks=fallbacks,
                               crash_on_start=crash_on_start, payload=payload)
        manifest = UM.build(self.tree, version)
        manifest.update(policy or {})
        self.parts = UM.assign_parts(manifest)
        assert self.parts == 1, "harness releases are small enough for one part"
        self.plat = updater.platform_tag()
        self.manifest_name = f"manifest.{self.plat}.signed"
        self.token = UM.sign(manifest, sec, kid="u1").encode()
        self.assets_dir = os.path.join(work, f"assets-{version}{label}")
        flatten_update_assets.flatten(self.tree, self.assets_dir, self.plat)
        self.tag = updater._assets_release_tag(version, self.plat, 1)
        self.manifest = manifest


# ── GitHub-shaped local server with fault injection ─────────────────────────
class FakeGitHub(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.manifests: dict[str, bytes] = {}            # repo -> latest manifest
        self.assets: dict[tuple[str, str], str] = {}     # (repo, tag) -> dir
        self.faults: dict[str, list[tuple]] = {}         # repo -> [(kind, arg)]
        self.requests: list[tuple[str, str, str]] = []   # (repo, route, name)
        self.reports: list[dict] = []                    # POST /v1/update-report bodies
        self.reports_down = False
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server_address[1]

    def publish(self, release: Release, repos=(PRIMARY, FALLBACK), manifest=True):
        for repo in repos:
            if manifest:
                self.manifests[repo] = release.token
            self.assets[(repo, release.tag)] = release.assets_dir

    def fault(self, repo: str, kind: str, arg=None):
        self.faults.setdefault(repo, []).append((kind, arg))

    def clear_faults(self):
        self.faults.clear()

    def hits(self, route: str, repo: str | None = None) -> list[str]:
        with self.lock:
            return [n for r, rt, n in self.requests if rt == route and (repo is None or r == repo)]

    def stop(self):
        self.shutdown()
        self.server_close()


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", headers=None):
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _record(self, repo, route, name):
        with self.server.lock:
            self.server.requests.append((repo, route, name))

    def do_POST(self):
        srv = self.server
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        if self.path == "/v1/update-report":
            if srv.reports_down:
                return self._send(503, b'{"error":{"code":"DOWN"}}',
                                  {"Content-Type": "application/json"})
            with srv.lock:
                srv.reports.append(json.loads(raw or b"{}"))
            return self._send(200, b'{"recorded":1}', {"Content-Type": "application/json"})
        self._send(404, b"no")

    def do_GET(self):
        srv = self.server
        parts = [p for p in self.path.split("?")[0].split("/") if p]
        if len(parts) >= 6 and parts[2] == "releases" and parts[3] == "latest" and parts[4] == "download":
            repo, name = f"{parts[0]}/{parts[1]}", parts[5]
            self._record(repo, "manifest", name)
            if any(k == "down" for k, _ in srv.faults.get(repo, [])):
                return self._send(503, b"down")
            if name not in (f"manifest.{updater.platform_tag()}.signed",) or repo not in srv.manifests:
                return self._send(404, b"no")
            return self._send(302, b"", {"Location": f"/_cdn/{repo}/latest/{name}"})
        if len(parts) >= 6 and parts[2] == "releases" and parts[3] == "download":
            repo, tag, name = f"{parts[0]}/{parts[1]}", parts[4], parts[5]
            self._record(repo, "asset-redirect", name)
            if any(k == "down" for k, _ in srv.faults.get(repo, [])):
                return self._send(503, b"down")
            d = srv.assets.get((repo, tag))
            if d is None or not os.path.isfile(os.path.join(d, name)):
                return self._send(404, b"no")
            return self._send(302, b"", {"Location": f"/_cdn/{repo}/{tag}/{name}"})
        if len(parts) >= 4 and parts[0] == "_cdn":
            repo = f"{parts[1]}/{parts[2]}"
            tag, name = parts[3], parts[4]
            self._record(repo, "cdn", name)
            if tag == "latest":
                body = srv.manifests.get(repo)
            else:
                d = srv.assets.get((repo, tag))
                body = open(os.path.join(d, name), "rb").read() if d else None
            if body is None:
                return self._send(404, b"no")
            for kind, arg in srv.faults.get(repo, []):
                if kind == "corrupt" and arg in name and tag != "latest":
                    body = bytes(b ^ 0xFF for b in body[:1]) + body[1:]    # same size, wrong hash
                if kind == "forge" and tag == "latest":
                    body = body[:-4] + (b"AAAA" if not body.endswith(b"AAAA") else b"BBBB")
                if kind == "slow" and arg[0] in name:
                    time.sleep(arg[1])
                if kind == "drop_mid" and arg in name and tag != "latest":
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body[: max(1, len(body) // 2)])
                    self.wfile.flush()
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
            return self._send(200, body)
        self._send(404, b"no")


# ── driving an installed app ─────────────────────────────────────────────────
class App:
    def __init__(self, work: str, install: str, server: FakeGitHub | None):
        self.work, self.install, self.server = work, install, server
        self.home = os.path.join(work, "home")
        os.makedirs(self.home, exist_ok=True)
        self.log_path = os.path.join(self.home, "events.log")

    def env(self):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PRISM_", "QT_"))}
        env.update(HOME=self.home, USERPROFILE=self.home, PYTHONDONTWRITEBYTECODE="1")
        if self.server:
            env["PRISM_E2E_PORT"] = str(self.server.port)
        return env

    def run(self, *args, timeout=90) -> subprocess.CompletedProcess:
        return subprocess.run([os.path.join(self.install, "Prism"), *args],
                              env=self.env(), capture_output=True, text=True,
                              timeout=timeout, cwd=self.work)

    def popen(self, *args) -> subprocess.Popen:
        return subprocess.Popen([os.path.join(self.install, "Prism"), *args],
                                env=self.env(), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, cwd=self.work,
                                start_new_session=True)

    def events(self) -> list[dict]:
        try:
            return [json.loads(l) for l in open(self.log_path) if l.strip()]
        except OSError:
            return []

    def names(self) -> list[str]:
        return [e["event"] if "version" not in e else f'{e["event"]}:{e["version"]}'
                for e in self.events()]

    def wait_for(self, name: str, timeout=60.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if name in self.names():
                return True
            time.sleep(0.1)
        return False

    def wait_count(self, name: str, n: int, timeout=60.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.names().count(name) >= n:
                return True
            time.sleep(0.1)
        return False

    def update_state(self) -> dict:
        try:
            return json.load(open(os.path.join(self.home, ".prism", "update_state.json")))
        except OSError:
            return {}

    def leftovers(self) -> list[str]:
        """Update debris next to the install (staging, backup, failed copies)."""
        parent = os.path.dirname(self.install)
        base = os.path.basename(self.install)
        out = []
        for n in sorted(os.listdir(parent)):
            full = os.path.join(parent, n)
            if n == base or not (n.startswith(base + ".") or "staging" in n):
                continue
            # The staging folder itself is created on first use and kept; it
            # is debris only when something is left inside it.
            if "staging" in n and os.path.isdir(full) and not os.listdir(full):
                continue
            out.append(n)
        return out

#!/usr/bin/env python3
"""Update an installed Prism to a higher version the way the in-app updater
does, from a local server with a throwaway signing key. Nothing is published.

Called by installer_check.py in the Windows build job, per flavour. What is
real and what is not (read before trusting a green run):

  * REAL: the installed program folder; the updater, update_manifest,
    apply_update and flavour code, read out of the INSTALLED Prism.exe (so the
    flavour and repository are the baked ones); packaging/manifest.py and
    flatten_update_assets.py; the Windows swap script run by cmd.exe; the
    relaunch of the new Prism.exe, which notes its own first start.
  * NOT DRIVEN: the frozen app itself pressing Update. Its update host and
    public key are baked in and there is no way to override them, on purpose.
    A small Python process stands in for the running app: it runs the code
    above with this job's throwaway public key and a fetch that turns
    https://github.com into the local server, both patched in that process only.
  * The "new version" is the same build with one file changed and one added,
    so it has a higher number in the manifest only.

`run(..., frozen=False)` uses the checkout's modules instead of an .exe's, for
tests/test_windows_update_check.py on a machine without a built bundle.
"""
from __future__ import annotations

import http.server
import importlib.abc
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.dirname(HERE)
GUI = os.path.dirname(PACKAGING)
KID = "u1"
CHANGED = "_internal/style.qss"
ADDED = "_internal/added-by-an-update.txt"
#: Everything the updater is made of; read from the installed executable.
UPDATER_MODULES = ("app_meta", "channel", "flavour", "paths", "licensing", "updater",
                   "update_manifest", "apply_update")


def _fail(message: str) -> None:
    sys.exit(f"update check: {message}")


# ── the modules inside the installed executable ──────────────────────────────
def _pyz(exe: str):
    from PyInstaller.archive.readers import PKG_ITEM_PYZ, CArchiveReader
    archive = CArchiveReader(exe)
    name = next(n for n, entry in archive.toc.items() if entry[-1] == PKG_ITEM_PYZ)
    return archive.open_embedded_archive(name)


def frozen_flavour(exe: str) -> str:
    """The FLAVOUR constant baked into this executable."""
    ns: dict = {"__name__": "flavour"}
    exec(_pyz(exe).extract("flavour"), ns)
    return ns["FLAVOUR"]


class _FromExecutable(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Import UPDATER_MODULES from the executable's own archive."""

    def __init__(self, exe: str):
        self.pyz = _pyz(exe)

    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in UPDATER_MODULES or name not in self.pyz.toc:
            return None
        is_package = self.pyz.toc[name][0] == 1            # PYZ_ITEM_PKG
        return importlib.util.spec_from_loader(name, self, origin="executable",
                                               is_package=is_package)

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = os.path.join(os.path.dirname(sys.executable), "_internal",
                                       *module.__name__.split(".")) + ".py"
        exec(self.pyz.extract(module.__name__), module.__dict__)


# ── the stand-in for the running app (its own process) ───────────────────────
def drive(cfg: dict) -> int:
    """What main_window.py does when the customer presses Update."""
    import socket
    import urllib.request
    import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401  (before sys.executable moves)

    connect = socket.socket.connect

    def only_this_computer(self, address):
        if address[0] != "127.0.0.1":
            raise OSError(f"update check: refused a connection to {address!r}")
        return connect(self, address)
    socket.socket.connect = only_this_computer

    sys.frozen = True
    sys.executable = cfg["exe"]
    if cfg["frozen"]:
        sys.meta_path.insert(0, _FromExecutable(cfg["exe"]))
    else:
        sys.path.insert(0, GUI)
        import flavour
        flavour.FLAVOUR = cfg["flavour"]
    import app_meta
    import flavour
    import licensing
    import updater

    licensing.keys.update_public_keys = lambda: {KID: cfg["pub"]}

    def fetch(url, *, timeout):
        local = url.replace("https://github.com", cfg["base"], 1)
        with urllib.request.urlopen(local, timeout=timeout) as r:
            return r.read()

    install = updater.install_dir()
    out = {"flavour": flavour.FLAVOUR, "channel": updater.update_channel(),
           "asked_first": updater._manifest_url(), "install": install,
           "state": updater.state_path()}
    check = updater.check_for_update(running=app_meta.VERSION, fetch=fetch)
    out["offered"] = check.version if check else None
    if check is not None:
        staged = updater.stage_update(check, install, fetch=fetch)
        out["staged"] = staged.stage_dir
        updater.begin_apply(staged, install)
    print(json.dumps(out))
    return 0


# ── the local release host ───────────────────────────────────────────────────
class _Host(http.server.ThreadingHTTPServer):
    """GitHub's two URL shapes. The first repository asked for the manifest
    serves `wrong` (another build's, genuinely signed); any other, `right`."""
    daemon_threads = True

    def __init__(self, channel: str, version: str, right: bytes, wrong: bytes, assets: str):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.channel, self.version, self.assets = channel, version, assets
        self.right, self.wrong = right, wrong
        self.first_repo = ""
        self.asked: list[str] = []
        self.lock = threading.Lock()
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def answer(self, path: str) -> bytes | None:
        parts = path.strip("/").split("/")
        if len(parts) != 6 or parts[2] != "releases":
            return None
        repo, name = "/".join(parts[:2]), parts[5]
        if parts[3:5] == ["latest", "download"] and name == f"manifest.{self.channel}.signed":
            with self.lock:
                self.first_repo = self.first_repo or repo
            return self.wrong if repo == self.first_repo else self.right
        tag = f"v{self.version}-assets-{self.channel}"
        if parts[3] == "download" and (parts[4] == tag or parts[4][:-1] == tag + "-"):
            full = os.path.join(self.assets, name)
            if os.path.isfile(full):
                with open(full, "rb") as f:
                    return f.read()
        return None


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        body = self.server.answer(self.path)
        with self.server.lock:
            self.server.asked.append(f"{self.path} {200 if body is not None else 404}")
        self.send_response(200 if body is not None else 404)
        self.send_header("Content-Length", str(len(body or b"")))
        self.end_headers()
        self.wfile.write(body or b"")


# ── building the higher version ──────────────────────────────────────────────
def _next_version(version: str, by: int) -> str:
    head, _, last = version.rpartition(".")
    return f"{head}.{int(last) + by}"


def _link(src: str, dst: str) -> None:
    try:
        os.link(src, dst)           # the bundle is over a gigabyte: no second copy
    except OSError:
        shutil.copy2(src, dst)


def _wait_until(done, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done():
            return True
        time.sleep(1)
    return done()


def _running(exe: str) -> bool:
    if sys.platform != "win32":
        return False
    name = os.path.basename(exe)
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}"],
                         capture_output=True, text=True, errors="replace").stdout
    return name.lower() in out.lower()


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def run(install_dir: str, exe: str, *, flavour_name: str, work: str, frozen: bool = True,
        env: dict | None = None) -> list[str]:
    """Update `install_dir`, check it, and leave it as a customer's would be
    after the updated app's window opened. Returns what the server was asked."""
    for path in (GUI, PACKAGING):
        if path not in sys.path:
            sys.path.insert(0, path)
    import app_meta
    import apply_update
    import flatten_update_assets
    import flavour
    import manifest as manifest_tool
    import smoke_test
    import update_manifest as UM
    import updater
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    base = updater.platform_tag()
    channel = flavour.update_channel(base, flavour_name)
    if frozen and frozen_flavour(exe) != flavour_name:
        _fail(f"the installed app is {frozen_flavour(exe)!r}, not {flavour_name!r}")

    # ── the higher version, its manifest and its assets ──
    version, decoy = _next_version(app_meta.VERSION, 1), _next_version(app_meta.VERSION, 2)
    new = os.path.join(work, "new-version")
    shutil.copytree(install_dir, new, symlinks=True, copy_function=_link)
    overlay = os.path.join(work, "changed")
    for rel, text in ((CHANGED, _read(os.path.join(install_dir, *CHANGED.split("/")))
                       + "\n/* changed by the update check */\n"),
                      (ADDED, "a file Setup never installed\n")):
        for root in (new, overlay):
            full = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            if os.path.lexists(full):
                os.remove(full)                 # a hard link to the installed file
            with open(full, "w", encoding="utf-8") as f:
                f.write(text)
    unsigned = os.path.join(work, f"manifest.{channel}.unsigned.json")
    extra = ["--update-channel", channel] if flavour_name != "complete" else []
    manifest_tool.main([new, version, "-o", unsigned, *extra])
    with open(unsigned, encoding="utf-8") as f:
        right = json.load(f)
    assets = os.path.join(work, "update-assets")
    flatten_update_assets.flatten(overlay, assets, channel)

    # Another build's manifest, offering a still higher version, under our name.
    wrong = {k: v for k, v in right.items() if k != "update_channel"}
    wrong["version"] = decoy
    if flavour_name == "complete":
        wrong["update_channel"] = flavour.update_channel(base, "studio")

    key = Ed25519PrivateKey.generate()              # this run's only, never written down
    secret = key.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption()).hex()
    public = key.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw).hex()
    host = _Host(channel, version, UM.sign(right, secret, kid=KID).encode(),
                 UM.sign(wrong, secret, kid=KID).encode(), assets)

    # ── press Update ──
    env = dict(env if env is not None else smoke_test.selftest_env())
    log = os.path.join(work, "update-apply.log")
    env["PRISM_APPLY_LOG"] = log
    cfg = os.path.join(work, "drive.json")
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump({"exe": exe, "frozen": frozen, "flavour": flavour_name, "pub": public,
                   "base": host.base}, f)
    started = time.monotonic()
    done = subprocess.run([sys.executable, os.path.abspath(__file__), "--drive", cfg], cwd=work,
                          env=env, capture_output=True, text=True, errors="replace", timeout=1800)
    host.shutdown()
    host.server_close()
    if done.returncode != 0:
        _fail(f"the update did not stage:\n{done.stdout[-2000:]}\n{done.stderr[-4000:]}")
    got = json.loads(done.stdout.strip().splitlines()[-1])
    print(f"  {got}")
    if (got["flavour"], got["channel"], got["offered"]) != (flavour_name, channel, version):
        _fail(f"expected {flavour_name} on {channel} to be offered {version}, got {got}")
    for line in host.asked:
        name = line.split()[0].rsplit("/", 1)[1]
        if name != f"manifest.{channel}.signed" and not name.startswith(f"{channel}__"):
            _fail(f"the app asked for another build's file: {line}")
    fetched = {line.split()[0].rsplit("/", 1)[1] for line in host.asked if line.endswith(" 200")}
    wanted = {f"manifest.{channel}.signed", UM.flat_name(channel, CHANGED), UM.flat_name(channel, ADDED)}
    if fetched != wanted:
        _fail(f"fetched {sorted(fetched)}, expected {sorted(wanted)}")
    print(f"✓ refused another build's manifest for {decoy}, accepted {version} on {channel}, "
          f"fetched only the {len(wanted) - 1} changed files ({time.monotonic() - started:.0f} s)")

    # ── the swap, and the new version starting ──
    marker = apply_update.confirm_marker_path(install_dir)
    if not _wait_until(lambda: apply_update.LAUNCHED_LINE in _read(marker).split(), 900):
        _fail(f"the new version was not swapped in and started within 15 minutes; "
              f"marker {_read(marker)!r}; log:\n{_read(log)[-4000:]}")
    if _read(marker).split()[0] != version:
        _fail(f"the marker names {_read(marker)!r}, expected {version}")
    if not _wait_until(lambda: not _running(exe), 300):
        _fail("the relaunched Prism did not finish its self-test within 5 minutes")
    print(f"✓ swapped in and started:\n{_read(log).strip()}")
    installed = [e for e in UM.build(install_dir, version)["files"]
                 if e["path"] != os.path.basename(marker)]
    expected = UM.build(new, version)["files"]
    if installed != expected:
        a, b = ({json.dumps(e, sort_keys=True) for e in x} for x in (installed, expected))
        _fail(f"the updated folder is not the new version: {sorted(a ^ b)[:6]}")
    if frozen and frozen_flavour(exe) != flavour_name:
        _fail(f"after the update the app is {frozen_flavour(exe)!r}, not {flavour_name!r}")
    if not os.path.isdir(install_dir + ".old"):
        _fail("the previous version was not kept for a rollback")
    if os.path.exists(got["staged"]):
        _fail(f"the staged copy was left behind: {got['staged']}")
    if not os.path.isfile(got["state"]):
        _fail(f"no update state at {got['state']}")
    print(f"✓ {install_dir} is {version} exactly ({len(installed)} files), still {flavour_name}")

    # What main.py does once the updated window is up.
    apply_update.confirm_startup_success(install_dir, install_dir + ".old")
    return host.asked


if __name__ == "__main__":
    if sys.argv[1:2] != ["--drive"]:
        _fail("run through packaging/windows/installer_check.py")
    with open(sys.argv[2], encoding="utf-8") as _f:
        sys.exit(drive(json.load(_f)))

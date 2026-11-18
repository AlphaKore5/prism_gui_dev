"""The free DWG converter (ODA File Converter): find it, let the person pick it, fetch it.

What the Open Design Alliance (ODA) allows, checked 2026-11-18 (see ui-port/stages/25):
  * https://www.opendesign.com/guestfiles/oda_file_converter lists plain download links, no
    form, login or e-mail gate. The links go through /guestfiles/get?filename=... which answers
    301 to a short-lived signed address on oda-qt.s3.eu-central-1.amazonaws.com.
  * The converter is ODA's, not ours: Prism never bundles it and never hands it on. It only
    fetches ODA's own installer for the person, who first accepts ODA's own terms here.
  * ODA publishes no checksum, so the check is size (against the server's own length) and the
    installer's file signature, nothing stronger.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import Signal

import core_bridge as CB
from workers import _Worker

CONFIG_KEY = "dwg_converter_path"                      # the .exe the person chose
PAGE_URL = "https://www.opendesign.com/guestfiles/oda_file_converter"
TERMS_URL = ("https://www.opendesign.com/files/2025-09/"
             "ODA%20Community%20User%20Agreement%2009-2025.pdf")
GET_URL = "https://www.opendesign.com/guestfiles/get?filename={name}"
# Only these hosts may serve the installer: ODA's site and the bucket it redirects to.
ALLOWED_HOSTS = ("www.opendesign.com", "oda-qt.s3.eu-central-1.amazonaws.com")
# Owner switch: False hides "Install it from Prism" everywhere (ODA's terms have not been
# cleared with ODA in writing; see the stage report).
INSTALL_FROM_PRISM = False   # OFF until ODA confirms in writing that Prism may fetch their installer (ui-port/stages/25)
# The words the engine's "no converter" message starts with (core.boq.NO_CONVERTER_TEXT).
MARKER = "needs a free helper program to open a DWG"

_MSI_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_DEB_MAGIC = b"!<arch>\n"


def is_missing_message(text: str) -> bool:
    return MARKER in (text or "")


def installer_name() -> str | None:
    """ODA's file for this computer, or None when ODA offers none we can use."""
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows":
        return "ODAFileConverter_QT6_vc16_amd64dll.msi" if machine in ("amd64", "x86_64") else None
    if system == "Darwin":
        arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
        return f"ODAFileConverter_QT6_macOsX_{arch}_15.0dll.dmg"
    if system == "Linux":
        return "ODAFileConverter_QT6_lnxX64_11dll.deb" if machine in ("x86_64", "amd64") else None
    return None


def installer_url() -> str | None:
    name = installer_name()
    return GET_URL.format(name=urllib.parse.quote(name)) if name and INSTALL_FROM_PRISM else None


# ── finding it / remembering a hand-picked one ─────────────────────────────

def apply_saved(cfg: dict) -> None:
    """Hand the remembered converter to the engine (its explicit-override slot)."""
    path = (cfg or {}).get(CONFIG_KEY) or ""
    if path and os.path.isfile(path):
        os.environ[CB.get_boq().ENV_CONVERTER] = path


def detect(cfg: dict | None = None) -> str | None:
    if cfg is not None:
        apply_saved(cfg)
    return CB.get_boq().find_dwg_converter()


def remember(cfg: dict, path: str) -> bool:
    """Save a hand-picked converter. False (nothing saved) if it is not a file."""
    if not path or not os.path.isfile(path):
        return False
    cfg[CONFIG_KEY] = path
    try:
        CB.config.save(cfg)
    except Exception:                                   # noqa: BLE001
        pass
    apply_saved(cfg)
    return True


# ── fetching ODA's own installer ───────────────────────────────────────────

class _OnlyOda(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts, schemes):
        self.hosts, self.schemes = hosts, schemes

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urllib.parse.urlparse(newurl)
        if parts.scheme not in self.schemes or parts.hostname not in self.hosts:
            raise urllib.error.URLError(f"redirected somewhere not allowed: {parts.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class DownloadWorker(_Worker):
    """Download ODA's installer to a fresh temp folder, off the UI thread."""
    progress = Signal(int, int)                         # bytes so far, total (0 = unknown)
    done = Signal(str)                                  # path of the saved installer
    failed = Signal(str)

    def __init__(self, url: str, hosts=ALLOWED_HOSTS, schemes=("https",),
                 min_bytes: int = 5_000_000, dest_dir: str | None = None):
        super().__init__()
        self.url, self.hosts, self.schemes = url, tuple(hosts), tuple(schemes)
        self.min_bytes, self.dest_dir = min_bytes, dest_dir
        self.cancelled = False

    def run(self):
        try:
            self.done.emit(self._fetch())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e) or e.__class__.__name__)

    def _fetch(self) -> str:
        parts = urllib.parse.urlparse(self.url)
        if parts.scheme not in self.schemes or parts.hostname not in self.hosts:
            raise ValueError("That address is not one Prism downloads from.")
        opener = urllib.request.build_opener(_OnlyOda(self.hosts, self.schemes))
        name = urllib.parse.parse_qs(parts.query).get("filename", ["oda_installer"])[0]
        folder = self.dest_dir or tempfile.mkdtemp(prefix="prism-oda-")
        path = os.path.join(folder, os.path.basename(name))
        with opener.open(urllib.request.Request(self.url), timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(path, "wb") as out:
                while True:
                    if self.cancelled:
                        raise RuntimeError("Cancelled.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    got += len(chunk)
                    self.progress.emit(got, total)
        if got < self.min_bytes or (total and got != total):
            os.remove(path)
            raise RuntimeError("The download did not finish properly.")
        magic = {".msi": _MSI_MAGIC, ".deb": _DEB_MAGIC}.get(os.path.splitext(path)[1].lower())
        if magic:
            with open(path, "rb") as f:
                if f.read(len(magic)) != magic:
                    os.remove(path)
                    raise RuntimeError("The downloaded file is not an installer.")
        return path


def launch_installer(path: str):
    """Start the installer the normal way (its own window). Returns a Popen to wait on,
    or None when there is nothing to wait for. Linux is never launched: it needs an admin
    password, which Prism does not handle."""
    system = platform.system()
    if system == "Windows":
        return subprocess.Popen(["msiexec", "/i", path])
    if system == "Darwin" and shutil.which("open"):
        return subprocess.Popen(["open", path])
    return None


def linux_command(path: str) -> str:
    return f'sudo apt install "{path}"'

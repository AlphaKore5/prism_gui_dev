"""The parts Prism needs that are not Prism's own code, and how to get them.

Chromium (the web renderer behind Studio, Motion and the exports), FFmpeg
(video), the picture reader, the microphone library and the rest. A packaged
Prism carries almost all of them; a build that lost one (antivirus took the
browser, a half-finished update, a build made on a runner without it) used to
say "pip install ..." at a customer. This module is the one place that knows:

  * what each part is for, in words for someone who has never used AI,
  * how to tell, quickly and with no network, whether it is here,
  * what a feature needs, so the first press can offer the part instead of
    failing,
  * how to fetch the two that can be fetched (Chromium, FFmpeg), into a
    per-user folder, with progress, cancel and a check afterwards.

Plain stdlib, no Qt. The engine is reached through core_bridge only, and only
inside functions. Everything here is safe to call from the UI thread EXCEPT
`install()` and `launch_check()`, which a worker runs.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import dataclass

import paths

READY, MISSING, UPDATE = "ready", "missing", "update"

# Where Playwright's own CDN lives. The driver picks the host and speaks https
# only; Prism never builds a download URL for the browser itself.
CHROMIUM_HOST = "cdn.playwright.dev (Playwright's own download site)"


@dataclass(frozen=True)
class Component:
    key: str
    name: str            # what the customer sees
    purpose: str         # plain words: what it is for
    features: tuple      # feature keys that need it (see FEATURES)
    size_mb: int         # download size; 0 = nothing to download
    install: str         # "chromium" | "ffmpeg" | "" (cannot be fetched from Prism)
    licence: str         # one line
    modules: tuple = ()  # python packages that must be importable (find_spec)


@dataclass(frozen=True)
class Status:
    state: str           # READY | MISSING | UPDATE
    detail: str          # one plain sentence


class DepsError(Exception):
    """Carries a sentence a customer can read."""


COMPONENTS = (
    Component(
        "chromium", "Web renderer (Chromium)",
        "A hidden browser Prism uses to film web pages for reels and motion "
        "graphics and to make PDFs and pictures from pages.",
        ("studio", "motion", "pdf_export", "page_image"), 170, "chromium",
        "Chromium, open source (BSD and others), from Playwright's download "
        "site.", ("playwright",)),
    Component(
        "ffmpeg", "Video encoder (FFmpeg)",
        "A free standard program that turns Prism's frames into a video file.",
        ("reel", "studio", "motion"), 30, "ffmpeg",
        "FFmpeg, GPL/LGPL; Prism runs it as a separate program and keeps its "
        "licence beside it."),
    Component(
        "ocr", "Picture reader",
        "Reads the words printed in a photo or a scanned page, on this "
        "computer, so a brochure crop can be understood.",
        ("pictures",), 0, "", "RapidOCR, Apache 2.0.",
        ("rapidocr_onnxruntime", "onnxruntime")),
    Component(
        "voice", "Microphone (Speak)",
        "Lets you say your request instead of typing it.",
        ("voice",), 0, "", "PyAudio / PortAudio, MIT.", ("pyaudio",)),
    Component(
        "drawings", "Drawing viewer (DXF and DWG)",
        "Draws a CAD drawing as a picture so it can be shown to the AI.",
        ("drawing_picture",), 0, "", "ezdxf, MIT; matplotlib, BSD.",
        ("ezdxf", "numpy", "matplotlib")),
    Component(
        "pdf_drawings", "PDF drawing reader",
        "Reads lines and text inside a PDF drawing for the HVAC takeoff.",
        ("pdf_takeoff",), 0, "", "pdfplumber, pypdfium2, RapidOCR (MIT / "
        "Apache 2.0).", ("pdfplumber", "pypdfium2", "rapidocr")),
    Component(
        "step", "3D model reader (STEP)",
        "Opens STEP 3D models and measures them.",
        ("step",), 0, "", "CadQuery / OpenCascade, LGPL.",
        ("cadquery", "OCP")),
    Component(
        "gerber", "Circuit board reader (Gerber)",
        "Reads and checks circuit-board files.",
        ("gerber",), 0, "", "shapely and gerbonara, BSD / Apache 2.0.",
        ("shapely", "gerbonara")),
    Component(
        "office", "Word, Excel and PDF files",
        "Reads and writes the documents you attach and the sheets Prism makes.",
        ("documents",), 0, "", "python-docx, openpyxl, pypdf (MIT / BSD).",
        ("docx", "openpyxl", "pypdf")),
    Component(
        "pictures", "Picture drawing (Pillow)",
        "Draws the frames of a Reel and prepares pictures.",
        ("reel",), 0, "", "Pillow, HPND.", ("PIL",)),
    Component(
        "drive", "Google Drive picker",
        "Lets you choose files from your Google Drive.",
        ("drive",), 0, "", "Google API client, Apache 2.0.",
        ("googleapiclient", "google_auth_oauthlib")),
    Component(
        "mail", "Mail-server finder",
        "Finds the right mail server from an e-mail address during set-up.",
        ("email_setup",), 0, "", "dnspython, ISC.", ("dns",)),
    Component(
        "keyring", "Secure key storage",
        "Keeps your licence key in the Windows, Mac or Linux password store "
        "instead of a plain file.",
        ("licence",), 0, "", "keyring, MIT.", ("keyring",)),
)

BY_KEY = {c.key: c for c in COMPONENTS}

# A feature the customer presses -> the components it cannot run without.
FEATURES = {
    "studio": ("chromium", "ffmpeg"),
    "motion": ("chromium", "ffmpeg"),
    "reel": ("ffmpeg", "pictures"),
    "pdf_export": ("chromium",),
    "page_image": ("chromium",),
    "voice": ("voice",),
}


def plain_install_reason(c: Component) -> str:
    """Why there is no Install button for a part Prism cannot fetch."""
    return ("This part is built into Prism and can't be downloaded on its "
            "own. Update Prism (Settings > Help & contact) or reinstall it "
            "to get it back.")


# ── where Chromium can be ───────────────────────────────────────────────────

def user_browsers_dir() -> str:
    """~/.prism/browsers (the dev channel's own home on a dev build)."""
    return paths.user_dir("browsers")


def _playwright_dir() -> str:
    spec = importlib.util.find_spec("playwright")
    if spec and spec.submodule_search_locations:
        return list(spec.submodule_search_locations)[0]
    return ""


def expected_revision() -> str:
    """The Chromium revision this Playwright drives, read from its own
    browsers.json: a file read, no Node process, no network."""
    root = _playwright_dir()
    if not root:
        return ""
    try:
        with open(os.path.join(root, "driver", "package", "browsers.json"),
                  encoding="utf-8") as f:
            for entry in json.load(f).get("browsers", []):
                if entry.get("name") == "chromium":
                    return str(entry.get("revision", ""))
    except (OSError, ValueError):
        pass
    return ""


def _default_cache() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.join(
            os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "ms-playwright")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Caches",
                            "ms-playwright")
    return os.path.join(os.path.expanduser("~"), ".cache", "ms-playwright")


def effective_root() -> str:
    """The folder Playwright will look in for this process."""
    setting = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if setting == "0":
        return os.path.join(_playwright_dir(), "driver", "package",
                            ".local-browsers")
    return setting or _default_cache()


_EXE_NAMES = ("chrome.exe", "chrome", "Google Chrome for Testing",
              "Chromium", "chromium")


def _find_exe(folder: str, depth: int = 5) -> str:
    """The browser executable inside one chromium-<rev> folder, or ""."""
    try:
        entries = sorted(os.listdir(folder))
    except OSError:
        return ""
    for name in entries:
        full = os.path.join(folder, name)
        if name in _EXE_NAMES and os.path.isfile(full):
            return full
    if depth <= 0:
        return ""
    for name in entries:
        full = os.path.join(folder, name)
        if os.path.isdir(full) and not name.startswith("locales"):
            found = _find_exe(full, depth - 1)
            if found:
                return found
    return ""


def chromium_in(root: str) -> tuple[str, str]:
    """(state, revision folder) of Chromium inside one browsers folder."""
    rev = expected_revision()
    try:
        names = [n for n in os.listdir(root) if re.fullmatch(r"chromium-\d+", n)]
    except OSError:
        return MISSING, ""
    if rev and f"chromium-{rev}" in names:
        if _find_exe(os.path.join(root, f"chromium-{rev}")):
            return READY, f"chromium-{rev}"
        return MISSING, ""
    if names:
        return UPDATE, names[0]
    return MISSING, ""


def detect_chromium() -> Status:
    if importlib.util.find_spec("playwright") is None:
        return Status(MISSING, "The part that drives the browser is not in "
                               "this copy of Prism.")
    states = [chromium_in(effective_root())[0],
              chromium_in(user_browsers_dir())[0]]
    if READY in states:
        return Status(READY, "Ready.")
    if UPDATE in states:
        return Status(UPDATE, "An older web renderer is on this computer; "
                              "Prism needs a newer one.")
    return Status(MISSING, "Not on this computer yet.")


def ensure_environment() -> bool:
    """Make a Chromium Prism installed itself usable: if the normal place has
    none and the per-user folder has, point Playwright at the per-user folder
    for this process. Returns True when it changed anything. Cheap: file
    listing only. Called at start-up and after an install."""
    if importlib.util.find_spec("playwright") is None:
        return False
    if chromium_in(effective_root())[0] == READY:
        return False
    if chromium_in(user_browsers_dir())[0] != READY:
        return False
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = user_browsers_dir()
    try:
        import core_bridge as CB
        CB.reset_browser_cache()
    except Exception:                                   # noqa: BLE001
        pass
    return True


# ── detection of the rest ───────────────────────────────────────────────────

def _modules_missing(c: Component) -> list[str]:
    out = []
    for name in c.modules:
        try:
            if importlib.util.find_spec(name) is None:
                out.append(name)
        except (ImportError, ValueError):
            out.append(name)
    return out


def detect_ffmpeg() -> Status:
    try:
        import core_bridge as CB
        found = CB.get_ffmpeg().locate()
    except Exception:                                   # noqa: BLE001
        found = None
    return (Status(READY, "Ready.") if found
            else Status(MISSING, "Not on this computer yet."))


def detect(key: str) -> Status:
    c = BY_KEY[key]
    if key == "chromium":
        return detect_chromium()
    if key == "ffmpeg":
        return detect_ffmpeg()
    gone = _modules_missing(c)
    if gone:
        return Status(MISSING, "Missing from this copy of Prism.")
    if key == "voice":
        return Status(READY, "Ready. Prism also needs a microphone.")
    return Status(READY, "Ready.")


def detect_all() -> dict:
    return {c.key: detect(c.key) for c in COMPONENTS}


def missing_for(feature: str) -> list[Component]:
    """The parts a feature needs that are not ready, installable ones first."""
    out = [BY_KEY[k] for k in FEATURES.get(feature, ())
           if detect(k).state != READY]
    return sorted(out, key=lambda c: (not c.install, c.key))


def plain(why: str) -> str:
    """Take pip / playwright / sudo commands out of an engine message."""
    text = (why or "").strip()
    lowered = text.lower()
    if ("pip install" in lowered or "playwright install" in lowered
            or "apt install" in lowered or "brew install" in lowered):
        if "ffmpeg" in lowered:
            return ("Prism needs FFmpeg, a free video program, to make "
                    "videos. Open Settings > Components to get it.")
        if "chromium" in lowered or "playwright" in lowered or "browser" in lowered:
            return ("Prism's web renderer (Chromium) isn't on this computer "
                    "yet. Open Settings > Components to get it.")
        return ("A part Prism needs isn't on this computer. Open Settings > "
                "Components to see what is missing.")
    return text


# ── consent text ────────────────────────────────────────────────────────────

def consent_line(key: str) -> str:
    c = BY_KEY[key]
    if key == "chromium":
        return (f"Prism will download its web renderer, about {c.size_mb} MB, "
                f"from {CHROMIUM_HOST} and keep it only for you, in "
                f"{user_browsers_dir()}. It uses about 400 MB on disk.")
    if key == "ffmpeg":
        return (f"Prism will download FFmpeg, about {c.size_mb} MB, from "
                "pypi.org (the Python package site) and check its checksum "
                "before using it.")
    return ""


# ── voice ───────────────────────────────────────────────────────────────────

def voice_problem(cfg: dict | None = None) -> str:
    """"" when Speak can start, else one plain sentence (never a command)."""
    cfg = cfg or {}
    try:
        import core_bridge as CB
        if CB.ai_client.is_server_key(cfg.get("api_key")):
            return CB.voice.VOICE_UNAVAILABLE
    except Exception:                                   # noqa: BLE001
        pass
    if detect("voice").state != READY:
        return ("Speaking your request isn't set up in this copy of Prism, "
                "so please type it instead. Settings > Components shows "
                "what is missing.")
    return ""


def voice_error(raw: str) -> str:
    """A recording or transcription failure, in words a customer can act on."""
    low = (raw or "").lower()
    if sys.platform.startswith("win"):
        allow = ("Open Windows Settings > Privacy & security > Microphone and "
                 "turn on \"Let desktop apps access your microphone\".")
    elif sys.platform == "darwin":
        allow = ("Open System Settings > Privacy & Security > Microphone and "
                 "switch Prism on.")
    else:
        allow = "Check your system sound settings and allow Prism to record."
    if any(s in low for s in ("permission", "denied", "not allowed", "-9985",
                              "access")):
        return ("Prism needs permission to use the microphone. " + allow)
    if any(s in low for s in ("no default input", "invalid input device",
                              "-9996", "-9998", "no device", "no input",
                              "device unavailable")):
        return ("No microphone found. Plug one in or switch it on, then press "
                "Speak again.")
    if "isn't part of your prism plan" in low:
        return raw
    if any(s in low for s in ("connection", "timed out", "resolve", "network")):
        return ("Prism couldn't reach the speech service. Check your internet "
                "and try again, or type your request.")
    return ("Prism couldn't hear that. Check your microphone and try again, "
            "or type your request.")


# ── installing ──────────────────────────────────────────────────────────────

_PROGRESS = re.compile(r"(\d{1,3})%\s+of\s+([\d.]+)\s*(KiB|MiB|GiB)", re.I)
_UNIT = {"kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3}


def parse_progress(line: str):
    """(done_bytes, total_bytes) from a Playwright progress line, or None."""
    m = _PROGRESS.search(line or "")
    if not m:
        return None
    total = int(float(m.group(2)) * _UNIT[m.group(3).lower()])
    return int(total * min(int(m.group(1)), 100) / 100), total


def chromium_install_command() -> tuple[list, dict]:
    """argv and environment that run Playwright's own installer, from the
    driver that ships inside the playwright package (works in a frozen build,
    where sys.executable is Prism itself and `python -m playwright` is not an
    option). --no-shell matches what CI bundles and Prism launches."""
    try:
        from playwright._impl._driver import (compute_driver_executable,
                                               get_driver_env)
        driver = compute_driver_executable()
        node, cli = (driver if isinstance(driver, tuple)
                     else (str(driver), None))
        argv = [str(node)] + ([str(cli)] if cli else []) + [
            "install", "--no-shell", "chromium"]
        env = dict(get_driver_env())
    except Exception as e:                              # noqa: BLE001
        raise DepsError("This copy of Prism has no installer for the web "
                        "renderer. Update Prism (Settings > Help & contact) "
                        "or reinstall it.") from e
    env["PLAYWRIGHT_BROWSERS_PATH"] = user_browsers_dir()
    return argv, env


def launch_check() -> tuple[bool, str]:
    """Start the browser once and paint a frame (a worker runs this)."""
    import core_bridge as CB
    from core import browser
    return browser.selftest()


def run_command(argv, env, on_progress, cancelled, on_line=None) -> int:
    """Run an installer, feeding progress; kill it when cancelled. Returns the
    exit code, or -1 when cancelled."""
    import queue
    os.makedirs(user_browsers_dir(), exist_ok=True)
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # no console
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env, text=True,
                            encoding="utf-8", errors="replace", bufsize=1,
                            creationflags=flags,
                            cwd=user_browsers_dir())
    lines: "queue.Queue" = queue.Queue()

    def pump():
        for raw in proc.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    try:
        while True:
            if cancelled():
                proc.kill()
                proc.wait(10)
                return -1
            try:
                raw = lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if raw is None:
                break
            hit = parse_progress(raw)
            if hit:
                on_progress(*hit)
            elif on_line and raw.strip():
                on_line(raw.strip())
        return proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()


def install(key: str, consent: bool, on_progress=lambda d, t: None,
            cancelled=lambda: False, on_line=None) -> str:
    """Fetch one part. Raises DepsError (customer words) on any failure;
    returns "cancelled" or "ok". Blocking: run it on a worker, never the UI
    thread. `consent` must be True: nothing is downloaded without it."""
    if not consent:
        raise DepsError("Nothing was downloaded because it was not allowed.")
    c = BY_KEY.get(key)
    if c is None or not c.install:
        raise DepsError(plain_install_reason(c) if c else "Unknown part.")
    if key == "ffmpeg":
        import core_bridge as CB
        try:
            CB.get_ffmpeg().download(on_progress)
        except Exception as e:                          # noqa: BLE001
            raise DepsError(str(e)) from e
        if detect("ffmpeg").state != READY:
            raise DepsError("FFmpeg was downloaded but Prism can't find it. "
                            "Try Repair once more.")
        return "ok"
    argv, env = chromium_install_command()
    try:
        code = run_command(argv, env, on_progress, cancelled, on_line)
    except OSError as e:
        raise DepsError("Prism couldn't start the installer. Check that "
                        "antivirus isn't blocking it and try again.") from e
    if code == -1:
        return "cancelled"
    if code != 0:
        raise DepsError("The download didn't finish. Check your internet "
                        "connection and press Repair to try again; nothing "
                        "else on this computer was changed.")
    ensure_environment()
    if detect_chromium().state != READY:
        raise DepsError("The download finished but the web renderer isn't "
                        "where Prism expects it. Press Repair to try again.")
    ok, why = launch_check()
    if not ok:
        raise DepsError("The web renderer was installed but would not start "
                        f"({why}). On Linux it may need system libraries "
                        "that only an administrator can add.")
    return "ok"

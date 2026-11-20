"""Pulse: Prism telling us how it is doing, so a customer does not have to.

Until now an error stayed in a log file on the customer's machine, and we heard
about it when somebody phoned. Pulse sends a few small, scrubbed facts to the
licence server (/v1/pulse, see license_server app/pulse.py):

  error  the exception TYPE, the top frames of OUR code (file:function), a
         fingerprint of those, and a one-line message with anything quoted or
         numeric blanked out, because an exception message can quote user data
  start  how many milliseconds from launch to a usable window
  slow   an action that took two seconds or more (which screen, how long)
  run    how a run ended: ok, failed or cancelled, in which add-on
  crash  the previous run did not exit cleanly (a marker file was left behind)
  feedback  a thumb (and one of three plain reasons) on a result; never text

NEVER sent: a prompt, an answer, a file name or path, a name, an email, a key, an
attachment. The server scrubs again; this scrubs first.

Rules this module keeps:
  * it NEVER raises and NEVER blocks the app: every public function swallows its
    own failures, sending is on a daemon thread with a short timeout;
  * events wait in ~/.prism/pulse/queue.jsonl, so an error that happened right
    before a crash is still sent on the next start;
  * the queue is capped (300) and old events (7 days) are dropped;
  * it is OFF when the customer turns it off (config `pulse_enabled`, default on)
    and it is a no-op for a source checkout run by a developer (set
    PRISM_PULSE=1 to test it).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid

MAX_QUEUE = 300
MAX_AGE = 7 * 86400
BATCH = 50
SLOW_MS = 2000
MIN_FLUSH_GAP = 60.0                       # seconds between sends

_lock = threading.Lock()
_launch = time.perf_counter()
_enabled = True
_start_sent = False
_last_flush = 0.0
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
_HOME = os.path.expanduser("~")

_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_QUOTED = re.compile(r"""(['"])(?:(?!\1).){1,}?\1""")
_NUMBER = re.compile(r"\d+")
_LONG = re.compile(r"\b[\w\-]{24,}\b")
# A path with no spaces: C:\Work\a.dxf, /mnt/data/x/y.step, \\server\share\f.pdf
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\|/)[^\s'\"<>|]*[\\/][^\s'\"<>|]*")


def configure(cfg: dict | None) -> None:
    """Read the customer's choice. Called at start and when Settings changes."""
    global _enabled
    try:
        _enabled = bool((cfg or {}).get("pulse_enabled", True))
    except Exception:                                    # noqa: BLE001
        _enabled = True


def active() -> bool:
    """On, and not a developer's source checkout (unless PRISM_PULSE=1)."""
    if not _enabled:
        return False
    if os.environ.get("PRISM_PULSE") == "1":
        return True
    try:
        import paths
        return bool(paths.is_frozen())
    except Exception:                                    # noqa: BLE001
        return False


# ── what is allowed to leave ───────────────────────────────────────────────
def scrub_title(text: str) -> str:
    """A one-line message with the parts that could be user data blanked.

    "KeyError: 'Shah Engineering quote'" becomes "KeyError: <str>". The frames
    carry the diagnosis; the message only has to group and be readable.
    """
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = _QUOTED.sub("<str>", t)
    if _HOME and len(_HOME) > 3:
        # Everything after the home folder to the end of the line: folder and
        # file names contain spaces ("Client Drawings"), so there is no safe end.
        t = re.sub(re.escape(_HOME) + r"[^\n]*", "<home>", t)
    t = _PATH.sub("<path>", t)
    t = _EMAIL.sub("<email>", t)
    t = _LONG.sub("<id>", t)
    t = _NUMBER.sub("<n>", t)
    return re.sub(r"\s+", " ", t).strip()[:160]


def _app_frames(tb, limit: int = 3) -> list[str]:
    """The last `limit` frames that are OUR code, as "file.py:function"."""
    frames = []
    for fs in traceback.extract_tb(tb):
        fn = os.path.abspath(fs.filename)
        if fn.startswith(_APP_ROOT) or "prism_terminal" in fn or f"{os.sep}core{os.sep}" in fn:
            if "site-packages" in fn:
                continue
            frames.append(f"{os.path.basename(fn)}:{fs.name}")
    return frames[-limit:]


def fingerprint(exc_type, frames: list[str]) -> str:
    """Same bug, same fingerprint: exception type plus our own top frames."""
    name = getattr(exc_type, "__name__", str(exc_type))
    return hashlib.sha1((name + "|" + "|".join(frames)).encode()).hexdigest()[:16]


# ── recording ──────────────────────────────────────────────────────────────
def _queue_path() -> str:
    import paths
    return paths.user_dir("pulse", "queue.jsonl")


def _context() -> dict:
    import app_meta
    import channel
    try:
        import updater
        plat = updater.platform_tag()
    except Exception:                                    # noqa: BLE001
        plat = sys.platform
    return {"version": app_meta.VERSION, "flavour": "complete", "platform": plat,
            "channel": "dev" if channel.is_dev() else "prod"}


# Server PulseEventIn max_length per string field (wt-server-ai app/schemas.py).
_MAX_LEN = {"version": 20, "flavour": 16, "platform": 24, "addon": 24, "screen": 24,
            "title": 400, "last_screen": 24}


def record(kind: str, **fields) -> None:
    """Add one event to the queue. Never raises."""
    try:
        if not active():
            return
        ev = {**_context(), "kind": kind, "at": int(time.time()), **fields}
        for k, n in _MAX_LEN.items():            # the server refuses the whole batch over one long field
            if isinstance(ev.get(k), str):
                ev[k] = ev[k][:n]
        path = _queue_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _lock:
            lines = []
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    lines = [l for l in f.read().splitlines() if l.strip()]
            lines.append(json.dumps(ev, separators=(",", ":")))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-MAX_QUEUE:]) + "\n")
    except Exception:                                    # noqa: BLE001
        pass


def error(exc_type, exc, tb, *, addon: str = "", screen: str = "") -> None:
    """An exception nobody handled. Called from diagnostics' crash hooks."""
    try:
        frames = _app_frames(tb)
        name = getattr(exc_type, "__name__", "Error")
        record("error", addon=addon, screen=screen,
               fingerprint=fingerprint(exc_type, frames),
               title=scrub_title(f"{name}: {exc}"), detail={"frames": frames})
        flush_async()
    except Exception:                                    # noqa: BLE001
        pass


def run(result: str, *, addon: str = "", title: str = "", ms: int | None = None,
        run_id: str = "") -> None:
    """How a run ended. `title` is blanked like an error message."""
    record("run", result=result, addon=addon, title=scrub_title(title),
           **({"ms": int(ms)} if ms is not None else {}),
           **({"run_id": run_id} if run_id else {}))


def new_run_id() -> str:
    """The AI gateway's id for the run just finished, so feedback joins to the
    model used; a fresh one only when the gateway tagged nothing."""
    try:
        import ai_server
        rid = ai_server.last_run_id()
        if rid:
            return rid
    except Exception:                                    # noqa: BLE001
        pass
    return uuid.uuid4().hex


RATINGS = ("up", "down", "")
REASONS = ("wrong", "incomplete", "slow", "other", "")
OUTCOMES = ("used", "edited", "redone", "none")


def feedback(addon: str, run_id: str, *, rating: str = "", reason: str = "",
             outcome: str = "none", model: str = "") -> None:
    """A thumb, a reason chip, or what the person did next. No free text."""
    rating = rating if rating in RATINGS else ""
    reason = reason if reason in REASONS else ""
    outcome = outcome if outcome in OUTCOMES else "none"
    record("feedback", addon=addon, run_id=run_id, rating=rating, reason=reason,
           outcome=outcome, **({"model": model} if model else {}))


def slow(action: str, ms: float, *, addon: str = "", screen: str = "") -> None:
    if ms >= SLOW_MS:
        record("slow", title=scrub_title(action), ms=int(ms), addon=addon, screen=screen)


def started() -> None:
    """The window is usable: record milliseconds since launch, once."""
    global _start_sent
    if _start_sent:
        return
    _start_sent = True
    record("start", ms=int((time.perf_counter() - _launch) * 1000))
    flush_async(delay=20.0)


# ── crash marker ───────────────────────────────────────────────────────────
# A small file says "Prism is running". A clean exit removes it; if it is still
# there at the next start, the last run died (power cut, kill, native crash) and
# one `crash` event is recorded. The last screen is kept in memory and written
# to the marker when the screen changes: one tiny local write on a click, which
# costs nothing a person could see. faulthandler writes a native crash's stack
# to a second file; only its last lines come back, scrubbed.
_screen = "start"
_trace_file = None
TRACE_LINES = 10


def _marker_path() -> str:
    import paths
    return paths.user_dir("pulse", "running.marker")


def _trace_path() -> str:
    import paths
    return paths.user_dir("pulse", "native-crash.txt")


def _write_marker() -> None:
    import app_meta
    path = _marker_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"version": app_meta.VERSION, "last_screen": _screen}))


def screen(name: str) -> None:
    """The screen the person is on now. Never raises."""
    global _screen
    try:
        if name == _screen:
            return
        _screen = str(name)[:40]
        if os.path.exists(_marker_path()):
            _write_marker()
    except Exception:                                    # noqa: BLE001
        pass


def begin_session() -> None:
    """Report an unclean previous run once, then mark this run as running and
    point faulthandler at a fresh file. Never raises, never blocks."""
    global _trace_file
    try:
        if not active():
            return
        marker = _marker_path()
        if os.path.exists(marker):
            try:
                with open(marker, encoding="utf-8") as f:
                    old = json.load(f)
            except Exception:                            # noqa: BLE001
                old = {}
            version = str(old.get("version", ""))[:20]
            last = str(old.get("last_screen", ""))[:24]
            detail = "previous run did not exit cleanly"
            try:
                with open(_trace_path(), encoding="utf-8", errors="replace") as f:
                    tail = [scrub_title(l) for l in f.read().splitlines()[-TRACE_LINES:] if l.strip()]
                if tail:
                    detail += " | " + " | ".join(tail)
            except OSError:
                pass
            fp = hashlib.sha1(("unclean-exit" + version + last).encode()).hexdigest()[:16]
            record("crash", fingerprint=fp, detail={"note": detail[:900]}, last_screen=last, version=version)
            os.remove(marker)
        _write_marker()
        try:
            import faulthandler
            _trace_file = open(_trace_path(), "w", encoding="utf-8")
            faulthandler.enable(_trace_file)
        except Exception:                                # noqa: BLE001
            pass
    except Exception:                                    # noqa: BLE001
        pass


def clean_exit() -> None:
    """The app is quitting normally: remove the marker. Never raises."""
    global _trace_file
    try:
        if _trace_file is not None:
            import faulthandler
            faulthandler.disable()
            _trace_file.close()
            _trace_file = None
            os.remove(_trace_path())
    except Exception:                                    # noqa: BLE001
        pass
    try:
        os.remove(_marker_path())
    except Exception:                                    # noqa: BLE001
        pass


# ── sending ────────────────────────────────────────────────────────────────
def _read_queue() -> list[dict]:
    path = _queue_path()
    if not os.path.exists(path):
        return []
    out, cutoff = [], time.time() - MAX_AGE
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("at", 0) >= cutoff:
                out.append(ev)
    return out


def flush() -> int:
    """Send what is queued. Returns how many were delivered. A server that cannot
    be reached leaves the queue for next time; a server that says "no" to our
    own malformed batch drops it (retrying a rejection forever helps nobody)."""
    global _last_flush
    try:
        if not active():
            return 0
        import app_meta
        import licensing
        from licensing import client, store
        data = store.load(licensing.user_dir())
        license_id = data.get("license_id") or licensing.state().license_id
        if not license_id:
            return 0
        fp = licensing.device_fingerprint()
    except Exception:                                    # noqa: BLE001
        return 0
    sent = 0
    try:
        with _lock:
            _last_flush = time.time()
            pending = _read_queue()
        while pending:
            batch = pending[:BATCH]
            try:
                client.call("/v1/pulse", {"license_id": license_id, "device_fp": fp, "events": batch},
                            app_version=app_meta.VERSION, timeout=8)
            except client.ServerError as e:
                if e.code != "INVALID_REQUEST":
                    break
            except Exception:                            # noqa: BLE001
                break
            sent += len(batch)
            pending = pending[BATCH:]
        if sent:
            with _lock:
                keep = _read_queue()[sent:]
                with open(_queue_path(), "w", encoding="utf-8") as f:
                    f.write("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in keep))
    except Exception:                                    # noqa: BLE001
        pass
    return sent


def flush_async(delay: float = 0.0) -> None:
    """flush() on a daemon thread, at most once a minute."""
    try:
        if not active() or time.time() - _last_flush < MIN_FLUSH_GAP:
            return

        def go():
            if delay:
                time.sleep(delay)
            flush()

        threading.Thread(target=go, name="prism-pulse", daemon=True).start()
    except Exception:                                    # noqa: BLE001
        pass

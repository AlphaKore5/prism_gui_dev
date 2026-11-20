"""A log, and a button that packages it up.

When a customer says "it didn't work", there is currently nothing to ask them
for. A windowed macOS build has no console at all; the engine's status
messages go to a label that disappears with the window. So a support
conversation is a non-technical person describing a screen from memory.

Two small pieces fix that:

  · every message the engine already emits is mirrored to a rolling file in
    ~/.prism/logs, alongside anything that crashes;
  · Settings → Export diagnostics writes a single .txt the customer can email.

The engine has emitted its whole narrative through one function since the GUI
was built — `core.ui.set_sink()` — so this needs no new instrumentation
anywhere. It just points that sink at a file as well as at the window.

What the export must never contain
──────────────────────────────────
The Groq API key, the SMTP password, and the licence token are all in the
files this sits next to, and a customer emailing a diagnostics bundle has no
way to check what is in it. Everything written here goes through `_scrub()`,
and the export lists config KEYS with values redacted rather than the config
itself. The one identifier kept in full is the device fingerprint, because it
is what you need to release a seat and it is not a secret.
"""
from __future__ import annotations

import os
import platform
import re
import sys
import time
import traceback

import paths

MAX_BYTES = 512_000          # per file — a few days of ordinary use
KEEP = 3                     # prism.log, prism.log.1, prism.log.2

# Anything shaped like a credential, wherever it turns up in a message.
_SECRETS = (
    re.compile(r"gsk_[A-Za-z0-9]{8,}"),                    # Groq key
    re.compile(r"PRSM[-A-Z0-9]{12,}"),                     # licence key
    re.compile(r"PRSD1\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # designation key
    re.compile(r"PRSMv1\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # licence token
    # Authorisation lease. Ordered BEFORE nothing in particular — the regexes
    # are independent — but it must exist: a lease is a bearer credential for
    # protected backend calls, and a support log is exactly the place one
    # would otherwise be pasted.
    re.compile(r"PRSMLv1\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),
    re.compile(r"(?i)(password|passwd|secret|token)[\"'\s:=]+\S+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # addresses
)

_installed = False


def log_dir() -> str:
    path = paths.user_dir("logs")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def log_path() -> str:
    return os.path.join(log_dir(), "prism.log")


def _scrub(text: str) -> str:
    """Redact anything that looks like a credential or an address.

    Deliberately over-eager. A false positive costs a line of the log being
    less readable; a false negative puts a customer's API key in an email.
    """
    out = str(text)
    for pattern in _SECRETS:
        out = pattern.sub("[redacted]", out)
    return out


def _rotate() -> None:
    """Keep the log bounded without a dependency or a background thread."""
    try:
        if os.path.getsize(log_path()) < MAX_BYTES:
            return
    except OSError:
        return
    for index in range(KEEP - 1, 0, -1):
        older = f"{log_path()}.{index}"
        newer = f"{log_path()}.{index - 1}" if index > 1 else log_path()
        try:
            if os.path.exists(newer):
                os.replace(newer, older)
        except OSError:
            pass


def write(level: str, message: str) -> None:
    """One line. Never raises — a broken log must not break a run."""
    try:
        _rotate()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"{stamp}  {level:<5} {_scrub(message)}\n")
    except Exception:                                   # noqa: BLE001
        pass


def _pulse(kind, value, tb) -> None:
    """Tell the server (scrubbed, queued, never blocking). See pulse.py."""
    try:
        import pulse
        pulse.error(kind, value, tb)
    except Exception:                               # noqa: BLE001
        pass


def install() -> None:
    """Mirror the engine's messages into the log, and catch what crashes.

    Chains onto whatever sink the GUI already installed rather than replacing
    it, so the live output panel keeps working exactly as before.
    """
    global _installed
    if _installed:
        return
    _installed = True

    try:
        import core_bridge as CB
        engine_ui = CB.get_ui()
        existing = getattr(engine_ui, "_sink", None)

        def sink(level, text):
            write(level, text)
            if existing:
                try:
                    existing(level, text)
                except Exception:                   # noqa: BLE001
                    pass

        engine_ui.set_sink(sink)
    except Exception:                               # noqa: BLE001
        pass    # no engine yet, or a refactor moved it — logging is optional

    # Anything that escapes a Qt slot or a worker thread. Without this the
    # traceback goes to a stdout a windowed build does not have.
    previous_hook = sys.excepthook

    def hook(kind, value, tb):
        write("CRASH", "".join(traceback.format_exception(kind, value, tb)))
        _pulse(kind, value, tb)
        previous_hook(kind, value, tb)

    sys.excepthook = hook

    try:
        import threading

        def thread_hook(args):
            write("CRASH", "".join(traceback.format_exception(
                args.exc_type, args.exc_value, args.exc_traceback)))
            _pulse(args.exc_type, args.exc_value, args.exc_traceback)

        threading.excepthook = thread_hook
    except Exception:                               # noqa: BLE001
        pass

    write("INFO", f"--- Prism started · {platform.platform()} · "
                  f"python {sys.version.split()[0]} ---")


# ── the export ─────────────────────────────────────────────────────────────
def _safe(fn, default=""):
    try:
        return fn()
    except Exception as e:                          # noqa: BLE001
        return f"(couldn't read: {e})"


def report() -> str:
    """Everything worth knowing about this installation, as plain text.

    Written to be read by a human on a support call, in the order they would
    ask: what version, what licence, what is configured, what happened.
    """
    import app_meta

    lines = [
        "PRISM DIAGNOSTICS",
        f"Generated       {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "── This installation ──",
        f"Version         {app_meta.VERSION}",
        f"Packaged build  {paths.is_frozen()}",
        f"Platform        {platform.platform()}",
        f"Python          {sys.version.split()[0]}",
        f"Config folder   {paths.user_dir()}",
    ]

    lines += ["", "── Licence ──"]
    try:
        import licensing
        state = licensing.state()
        lines += [
            f"Status          {state.status}",
            f"Plan            {state.plan or '—'} ({state.kind or '—'})",
            f"Add-ons         {', '.join(sorted(state.features)) or 'none'}",
            f"Days left       {state.days_left}",
            f"Device id       {licensing.device_fingerprint()}",
            f"Server          {_safe(lambda: licensing.client.server_url())}",
        ]
        # The lease is what protected work is actually checked against, so
        # "my licence looks fine but nothing will start" is answered here and
        # nowhere else. Times and scopes only — never the lease itself, which
        # is a bearer credential and belongs in no support attachment.
        lease_state = _safe(licensing.lease_state)
        lines.append(f"Authorisation   {lease_state}")
        try:
            lease_obj, _ = licensing._read_lease()
        except Exception:                           # noqa: BLE001
            lease_obj = None
        if lease_obj is not None:
            lines += [
                f"  scopes        {', '.join(sorted(lease_obj.scopes)) or 'none'}",
                f"  expires in    {lease_obj.expires_at - int(time.time())}s",
                f"  offline for   {lease_obj.offline_seconds}s after that",
                f"  metered       {lease_obj.metered}",
            ]
        # Where the reusable licence key ended up. "file" is the honest
        # answer on a machine with no OS credential store, and support needs
        # to be able to tell that from "we never stored one".
        lines.append(
            "Key storage     " + _safe(lambda: licensing.secretstore.where(
                bool(licensing.store.load(licensing.user_dir()).get("key")))))
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(couldn't read the licence: {e})")

    lines += ["", "── Role and workspace ──"]
    try:
        import identity
        import workspace as W
        me = identity.current()
        cfg = _cfg()
        lines += [
            f"Role            {me.get('role') or 'personal copy'}",
            f"Member folder   {me.get('mid')}",
            f"Workspace       {W.root(cfg)}",
            f"Shared          {W.is_shared(cfg)}",
            f"Reachable       {os.path.isdir(W.root(cfg))}",
        ]
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(couldn't read the workspace: {e})")

    lines += ["", "── Settings (values hidden) ──"]
    try:
        cfg = _cfg()
        for key in sorted(cfg):
            value = cfg[key]
            if key in ("api_key", "email"):
                shown = "set" if value else "not set"
            elif isinstance(value, dict):
                shown = ", ".join(f"{k}={v}" for k, v in value.items()) or "—"
            elif isinstance(value, list):
                shown = ", ".join(map(str, value)) or "—"
            else:
                shown = str(value) or "—"
            lines.append(f"{key:<15} {_scrub(shown)[:200]}")
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(couldn't read the settings: {e})")

    lines += ["", "── What's available on this machine ──"]
    try:
        import core_bridge as CB
        import cloud
        import wakeword
        for label, probe in (
            ("Browser automation", CB.automation_available),
            ("BOQ (ezdxf)", CB.boq_available),
            ("Reel (Pillow+FFmpeg)", CB.reel_available),
            ("Voice input", wakeword.available),
        ):
            ok, why = _safe(probe, (False, "unknown"))
            lines.append(f"{label:<22} {'yes' if ok else 'no'}"
                         + (f" — {str(why).splitlines()[0][:90]}" if not ok else ""))
        lines.append(f"{'Cloud folders':<22} "
                     + (", ".join(s["label"] for s in cloud.sources()) or "none"))
        # Studio, separately from Reel: "Studio makes artwork on Linux but
        # not on Windows/Mac" is, nine times in ten, Studio not being
        # offered at all on that machine (the dialog then runs the Quick
        # reel, which has no artwork step) -- and this line says why.
        ok, why = _safe(CB.studio_available, (False, "unknown"))
        lines.append(f"{'Prism Studio':<22} {'yes' if ok else 'no'}"
                     + (f" — {str(why).splitlines()[0][:120]}" if not ok else ""))
        lines.append(f"{'Studio browser':<22} "
                     f"{_safe(CB.studio_browser_path, '') or 'not found'}")
        wanted = CB.config.ARTIFACTS_DIR
        actual = _safe(CB.config.artifacts_root, "")
        lines.append(f"{'Artifacts folder':<22} {actual or wanted}"
                     + ("" if actual == wanted else
                        f"  (wanted {wanted}: not writable — Desktop access "
                        "refused, or the Desktop was moved)"))
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(couldn't probe: {e})")

    # The questions a Mac driver failure raises, answered up front: which
    # CPU, is Rosetta there, where is Chrome, which CPU is every driver file
    # built for, and is a Chrome already sitting on Prism's profile. The
    # client's M2 took two releases to diagnose from "errno 86" alone.
    lines += ["", "── Browser driver ──"]
    try:
        import core_bridge as CB
        lines += CB.get_automation().driver_report()
    except Exception as e:                          # noqa: BLE001
        lines.append(f"(couldn't inspect the driver: {e})")

    lines += ["", "── Recent log ──"]
    lines.append(tail(400) or "(the log is empty)")
    return "\n".join(lines)


def _cfg() -> dict:
    import core_bridge as CB
    return CB.config.load()


def tail(lines: int = 400) -> str:
    """The last N lines of the log, oldest file first if it has rotated."""
    chunks = []
    for index in range(KEEP - 1, -1, -1):
        path = log_path() if index == 0 else f"{log_path()}.{index}"
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                chunks.append(f.read())
        except OSError:
            continue
    everything = "".join(chunks).splitlines()
    return "\n".join(everything[-lines:])


def export(target: str) -> str:
    """Write the report to `target`. Returns the path."""
    with open(target, "w", encoding="utf-8") as f:
        f.write(report())
    return target

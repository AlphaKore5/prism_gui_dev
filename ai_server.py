"""
Prism GUI -- who is asking Prism's AI server, and what the credits chip shows
─────────────────────────────────────────────────────────────────────────────
Every model call in Prism (BOQ, STEP, Inquiry, Email, Motion, Studio, pictures,
the planner) goes to the licence server's /v1/ai/* routes, which hold the one
provider key. The engine's seam (prism_terminal/core/ai_client.py) does the
talking; it does not know the licence. This module is the one place that does:

  install()  registers the licence, seat and signed lease with the seam. Called
             once at startup. Nothing here touches the network.
  usage()    the UsageChip's provider: credits left, from the server. It
             answers from a cache and refreshes in the background, so the chip
             never makes the window wait.

PRISM_AI_DIRECT=1 is a TEMPORARY developer switch that puts the old direct keys
back (the seam stays inactive).
"""
from __future__ import annotations

import sys
import threading
import time
from typing import Optional

import app_meta
import channel
import i18n
from widgets.usage_chip import Usage

STALE_AFTER = 120            # seconds before the cache is asked again
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "status": None, "error": ""}
_fetching = False


def _ai():
    from core import ai_client            # the engine is on sys.path via core_bridge
    return ai_client


def _auth() -> dict:
    import licensing
    ai = _ai()
    state = licensing.state()
    if not getattr(state, "license_id", ""):
        raise ai.AiError("NO_LICENCE", i18n.t(
            "Activate Prism with your licence key before using AI."))
    lease = licensing.lease_bearer()
    if not lease:
        # One quick renewal: the lease is free to fetch and a call is waiting.
        try:
            licensing._refresh_lease_once()
        except Exception:                                   # noqa: BLE001
            pass
        lease = licensing.lease_bearer()
    return {"base_url": licensing.client.server_url(),
            "license_id": state.license_id,
            "device_fp": licensing.device_fingerprint(),
            "app_version": app_meta.VERSION,
            "lease": lease,
            "channel": channel.CHANNEL,
            "platform": sys.platform}


def install() -> None:
    """Route the engine's AI calls through Prism's server (unless the dev
    switch is set). Safe to call twice."""
    import core_bridge  # noqa: F401  (puts the engine on sys.path)
    ai = _ai()
    ai.set_auth_provider(_auth)
    ai.set_usage_listener(_heard)
    from widgets import usage_chip
    usage_chip.set_provider(usage)


def active() -> bool:
    return _ai().active()


def _heard(note: dict) -> None:
    """A call just settled: keep the cached balance in step with the server."""
    with _lock:
        st = _cache.get("status")
        if st and st.get("ready") and note.get("balance_mc") is not None:
            st["balance_mc"] = int(note["balance_mc"])
            _cache["at"] = time.time()


def _fetch() -> None:
    global _fetching
    try:
        status = _ai().status()
        err = ""
    except Exception as e:                                  # noqa: BLE001
        status, err = None, str(e)
    with _lock:
        _cache.update({"at": time.time(), "status": status, "error": err})
        _fetching = False


def refresh_async(force: bool = False) -> None:
    """Ask the server for the balance on a daemon thread."""
    global _fetching
    with _lock:
        if _fetching or not active():
            return
        if not force and time.time() - _cache["at"] < STALE_AFTER:
            return
        _fetching = True
    threading.Thread(target=_fetch, daemon=True, name="prism-ai-status").start()


def status_now() -> dict:
    """The cached status dict ({} until the first answer)."""
    with _lock:
        return dict(_cache.get("status") or {})


# What `reason` from /v1/ai/status means to a person.
REASONS = {
    "gateway_off": "AI is paused on Prism's side for the moment.",
    "no_key": "AI isn't set up on Prism's server yet.",
    "not_configured": "AI isn't set up on Prism's server yet.",
    "not_enabled": "AI isn't switched on for your plan yet. Ask Alphakore.",
    "blocked": "AI is switched off for your licence. Ask Alphakore.",
    "scope": "AI isn't switched on for this build of Prism yet.",
    "no_plan": "Your plan has no AI credits to spend yet. Ask Alphakore.",
}


def status_line() -> str:
    """One plain sentence for Settings: what AI is doing for this person."""
    if not active():
        return ""
    st = status_now()
    if st.get("ready"):
        per = int(st.get("mc_per_credit") or 1000) or 1000
        left = int(st.get("balance_mc") or 0) // per
        plan = (st.get("plan") or {}).get("name")
        return (i18n.t("{plan}: {n} AI credits left.").format(plan=plan, n=f"{left:,}")
                if plan else i18n.t("{n} AI credits left.").format(n=f"{left:,}"))
    reason = st.get("reason")
    if reason:
        return i18n.t(REASONS.get(reason, "AI isn't available right now."))
    with _lock:
        err = _cache.get("error") or ""
    return err or i18n.t("Checking your AI plan...")


def usage() -> Optional[Usage]:
    """UsageChip provider. None (chip hidden) until the server has said AI is
    ready for this licence; never blocks."""
    refresh_async()
    st = status_now()
    if not st.get("ready"):
        return None
    per = int(st.get("mc_per_credit") or 1000) or 1000
    left = max(0, int(st.get("balance_mc") or 0) // per)
    total = int(st.get("allowance_mc") or 0) // per or None
    cycle = st.get("cycle") or {}
    renews = ""
    if cycle.get("days_left") is not None:
        n = int(cycle["days_left"])
        renews = (i18n.t("Renews in {n} days").format(n=n) if n != 1
                  else i18n.t("Renews tomorrow"))
    return Usage(credits_left=left, credits_total=total, renews=renews)

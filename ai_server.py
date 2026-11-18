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
    import core_bridge as CB              # the only module that imports the engine
    return CB.ai_client


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


# Sentences elsewhere in the app that talk about Chrome, sign-ins and the
# customer's own keys. They stay as they are for the developer switch; while
# AI runs on Prism's server i18n.t() swaps them (i18n.set_rewording).
_SERVER_WORDS = {
    "Your Chrome opens and the tools are worked as you, in order.":
        "Each step runs in order on your Prism plan, and the answers arrive here.",
    "It drives your own browser": "It runs on your Prism plan",
    "Prism opens your Chrome and works the tools as you, using the accounts you already pay for. Nothing is sent to a Prism server.":
        "Prism's AI runs on Prism's server and is paid from your plan's credits. There is no AI account to sign in to and no browser to leave open. A file is only sent after you say yes.",
    "Signing in to the AI tools": "Your Prism plan and credits",
    "Prism uses your own accounts, in its own browser window. The first time — and occasionally after that — you need to sign in.\n\nClick Login tabs, sign in to each tool in the window that opens, and close it. Prism remembers from then on.":
        "Prism's AI runs through your Prism plan, so there is nothing to sign in to. The credits you have left are shown at the top of the window.",
    "Open Login tabs": "How AI works here",
    "Re-open your tools in Chrome to sign in": "AI runs on your Prism plan: nothing to sign in to",
    "Your Groq key and one tool per kind of step — the router suggests, you decide — plus where each one signs in.":
        "Which helper does each kind of step, and what your Prism plan includes.",
    "Your browser": "Browser used for drawing",
    "Prism drives your own Chrome, signed in as you. It keeps a separate profile so those logins survive between runs — which is also why a login done in your everyday Chrome does not reach it.":
        "Prism uses a Chrome-style browser in the background to draw reels, motion graphics and PDFs. It is never used for AI and you never sign in to anything in it.",
    "Writing it in your browser — this takes a minute or two. Chrome will open by itself; leave it alone until it finishes.":
        "Prism AI is writing it — this takes a few seconds.",
    "The AI tool did not answer. Its tab is still open in Chrome — the reply may have arrived after Prism stopped waiting.":
        "Prism AI did not answer. Nothing was charged for this try — please try again.",
    "AI diagnosis uses your Groq key and a scrubbed recent log.":
        "AI diagnosis runs on your Prism plan and sends only a scrubbed recent log.",
}


def install() -> None:
    """Route the engine's AI calls through Prism's server (unless the dev
    switch is set). Safe to call twice."""
    import core_bridge  # noqa: F401  (puts the engine on sys.path)
    ai = _ai()
    ai.set_auth_provider(_auth)
    ai.set_usage_listener(_heard)
    from widgets import usage_chip
    usage_chip.set_provider(usage)
    if ai.active():
        # Tools Prism's plan does not include are no longer offered anywhere.
        import core_bridge as CB
        CB.agents.prune_for_server()
        i18n.set_rewording(_SERVER_WORDS)


WARM_EVERY = 240             # seconds; Render sleeps after ~15 idle minutes
_warm = {"at": 0.0}


def warm_up() -> None:
    """Wake the server in the background so the first real click is not the
    one that pays for a cold start (tens of seconds on a sleeping host). At
    most one ping per WARM_EVERY seconds, never on the calling thread's
    time. Does nothing unless AI runs through the server."""
    if not active():
        return
    with _lock:
        if time.time() - _warm["at"] < WARM_EVERY:
            return
        _warm["at"] = time.time()

    def work():
        try:
            import requests
            import licensing
            requests.get(licensing.client.server_url().rstrip("/") + "/health",
                         timeout=60)
        except Exception:                                   # noqa: BLE001
            pass
    threading.Thread(target=work, daemon=True, name="prism-warm").start()


def active() -> bool:
    return _ai().active()


PRISM_AI = "Prism AI"


def display_agent(name: str) -> str:
    """What a person sees for a step's tool. In server mode there are no
    websites any more, so every site name (ChatGPT, Claude ...) reads
    "Prism AI"; the old direct path keeps the real names."""
    name = name or ""
    if name and active():
        return PRISM_AI
    return name


# ── this run's cost ──────────────────────────────────────────────────────────
RUN_COST_EVERY = 8           # seconds between run-cost asks while a run goes
_run: dict = {"id": "", "mc": None, "at": 0.0, "fetching": False}


def begin_run(run_id: str) -> None:
    """A pipeline/task run starts on THIS thread: tag its calls with `run_id`
    and start showing its cost. Call from the thread that makes the calls."""
    if not active():
        return
    _ai().set_run_id(run_id)
    with _lock:
        _run.update({"id": run_id, "mc": None, "at": 0.0})


def end_run() -> None:
    """The run finished: stop tagging, take one last cost reading."""
    if not active():
        return
    _ai().set_run_id("")
    with _lock:
        _run["at"] = 0.0
    _fetch_run_cost(force=True)


def _fetch_run_cost(force: bool = False) -> None:
    with _lock:
        rid = _run["id"]
        if (not rid or _run["fetching"]
                or (not force and time.time() - _run["at"] < RUN_COST_EVERY)):
            return
        _run["fetching"] = True
        _run["at"] = time.time()

    def work():
        mc = None
        try:
            got = (_ai().run_cost([rid]).get("runs") or {}).get(rid)
            if got is not None:
                mc = int(got.get("mc") or 0)
        except Exception:                                   # noqa: BLE001
            pass
        with _lock:
            if _run["id"] == rid and mc is not None:
                _run["mc"] = mc
            _run["fetching"] = False
    threading.Thread(target=work, daemon=True, name="prism-ai-runcost").start()


SESSION_KEEP = 200
_session: list[dict] = []        # this run of Prism's own list, newest last


def session_events() -> list[dict]:
    """Calls heard since Prism started, newest first, in the same shape as the
    server's /v1/ai/usage `events`. The fallback when the server has no usage
    route yet."""
    with _lock:
        return [dict(e) for e in reversed(_session)]


def session_usage() -> dict:
    """The /v1/ai/usage shape built from what this session heard, for a server
    that has no usage route. Balance is the cached one; nothing else is known."""
    events = session_events()
    day0 = int(time.time()) - int(time.time()) % 86400
    by_addon: dict = {}
    by_day: dict = {}
    for e in events:
        a = by_addon.setdefault(e["addon"], {"addon": e["addon"], "used_mc": 0, "calls": 0})
        a["used_mc"] += e["used_mc"]
        a["calls"] += 1
        d = time.strftime("%Y-%m-%d", time.gmtime(e["ts"]))
        by_day[d] = by_day.get(d, 0) + e["used_mc"]
    return {"balance_mc": int(status_now().get("balance_mc") or 0),
            "credit_usd_micros": 0,
            "cycle": {"used_mc": sum(e["used_mc"] for e in events),
                      "allowance_mc": None, "resets_at": None},
            "today": {"used_mc": sum(e["used_mc"] for e in events if e["ts"] >= day0)},
            "by_addon": sorted(by_addon.values(), key=lambda r: -r["used_mc"]),
            "by_day": [{"day": d, "used_mc": mc} for d, mc in sorted(by_day.items())],
            "events": events, "next": None}


def fetch_usage(limit: int = 50, before: str = "") -> dict:
    """The server's /v1/ai/usage. BLOCKING: call it from a worker thread."""
    return _ai().usage(limit, before)


def _heard(note: dict) -> None:
    """A call just settled: keep the cached balance in step with the server."""
    with _lock:
        _session.append({
            "ts": int(note.get("ts") or time.time()),
            "addon": str(note.get("addon") or ""),
            "feature": str(note.get("feature") or ""),
            "role": str(note.get("role") or ""),
            "model_label": str(note.get("model_label") or ""),
            "used_mc": int(note.get("charged_mc") or 0),
            "status": "ok", "run_id": str(note.get("run_id") or "")})
        del _session[:-SESSION_KEEP]
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
    _fetch_run_cost()
    with _lock:
        run_mc = _run["mc"] if _run["id"] else None
    run_cost = None if run_mc is None else -(-run_mc // per)   # whole credits, rounded up
    return Usage(credits_left=left, credits_total=total, run_cost=run_cost, renews=renews)

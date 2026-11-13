"""
Prism Sales Automation — the credit gateway
───────────────────────────────────────────
Leads & Outreach no longer runs on the customer's own Exa, Groq and e-mail
verifier keys. Every paid lookup — find people, look up a company, its website,
its recent news, ask the model, check an address, find one — goes to Prism's
licence server (prism-license-server, /v1/leads/*), which holds the provider
keys, charges the customer's pool of credits, makes the call and hands back the
answer. This machine holds no provider secret and never sees one.

How the rest of the engine uses it: it does not change. Each provider call in
source.py / enrich.py / signals.py / verify.py / qualify.py / reach.py already
took an `api_key` (or a `keys` dict); in pooled mode that key is the sentinel
POOL_KEY, and the ONE branch at each call site — `if gateway.is_pool(key)` —
asks this module instead of `requests`. Everything around the call (queries,
parsing, ranking, dedupe, the verify-then-find order) is unchanged and keeps
its tests.

  · `effective_cfg(cfg)` swaps the keys for POOL_KEY and drops every provider
    key the customer might still have in ~/.prism.
  · A run's spend is counted here (`reset()` … `used()`), because the calls that
    make it are threaded and deep inside the engine.
  · When the pool runs dry the server says so with INSUFFICIENT_CREDITS. The
    engine reads a failed lookup as "nothing came back" and would carry on
    asking, so this module remembers the refusal (`exhausted()`) and refuses
    every further paid call at once, without the round trip — a run stops
    within a beat, and the worker says why instead of guessing at a key.

PRISM_LEADS_DIRECT=1 puts the old direct mode back (the developer's own keys
from ~/.prism or the environment). It is a dev switch, not a setting: nothing in
the app offers it.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Callable, Optional

POOL_KEY = "pool"
TIMEOUT = 90
RETRIES = 1

_lock = threading.Lock()
_state = {"used": 0, "balance": None, "exhausted": "", "rates": {}, "ready": {},
          "outdated": False}
_send: Optional[Callable] = None            # tests: fn(path, body) -> dict


# What a customer is told when the licence server they are talking to has no
# /v1/leads routes at all — a server that has not been updated to the credit
# pool yet. Said once, plainly, instead of "the licence server rejected this
# request" on every button.
OUTDATED_MESSAGE = ("Leads credits aren't switched on for your account yet — Prism's "
                    "server needs updating. Ask Alphakore. Nothing was charged.")


class GatewayError(Exception):
    """The licence server refused a lookup, or could not be reached. `message`
    is written as customer-facing copy; `code` is the server's error code."""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class OutOfCredits(GatewayError):
    """The pool cannot cover this lookup. `balance` and `needed` are the
    server's own numbers."""

    @property
    def balance(self) -> int:
        return int(self.detail.get("balance", 0) or 0)

    @property
    def needed(self) -> int:
        return int(self.detail.get("needed", 0) or 0)


# ── mode ─────────────────────────────────────────────────────────────────────

def direct() -> bool:
    """The developer switch: use the provider keys in ~/.prism / the
    environment, as before the pool existed."""
    return os.environ.get("PRISM_LEADS_DIRECT", "").strip().lower() in ("1", "true", "yes", "on")


def pooled() -> bool:
    return not direct()


def is_pool(key) -> bool:
    """True for the sentinel — a provider "key" that means "spend from the
    pool". A dict of keys (verify.collect_keys) counts if it holds it."""
    if isinstance(key, dict):
        return POOL_KEY in key.values()
    return key == POOL_KEY


def effective_cfg(cfg: dict | None) -> dict:
    """The config the engine should run with. Pooled: the Exa key and the
    model key become the sentinel and every provider key a customer may still
    have saved is dropped, so nothing below can reach a provider directly.
    Direct (dev): untouched.

    Pooled means POOLED (owner, 25-Sep-2026: "we need to design this system as
    pooled credits"): no key of the customer's reaches a provider — not the
    finders (Apollo, Hunter, Tomba) either. Every paid lookup, an e-mail
    finder's included, is made by the licence server and charged to credits."""
    cfg = cfg or {}
    if not pooled():
        return cfg
    out = dict(cfg)
    out["exa_api_key"] = POOL_KEY
    out["api_key"] = POOL_KEY
    for key in [k for k in out if k.endswith("_api_key") and k not in ("exa_api_key", "api_key")] + ["tomba_key"]:
        out.pop(key, None)
    out["leads_pool"] = True
    return out


# ── the wire ─────────────────────────────────────────────────────────────────

def set_transport(fn: Optional[Callable]) -> None:
    """Tests only: answer every call with fn(path, body) -> dict (or raise a
    GatewayError). None restores the real licence-server call."""
    global _send
    _send = fn


def _auth_body(**extra) -> dict:
    import app_meta
    import licensing
    body = {"license_id": licensing.state().license_id,
            "device_fp": licensing.device_fingerprint(),
            "app_version": app_meta.VERSION}
    body.update(extra)
    return body


def _raw_call(path: str, body: dict) -> dict:
    if _send is not None:
        return _send(path, body)
    import app_meta
    import licensing
    from licensing.client import ServerError, Unreachable
    try:
        out = licensing.client.call(path, body, app_version=app_meta.VERSION,
                                    timeout=TIMEOUT, retries=RETRIES)
    except ServerError as e:
        if e.code == "INSUFFICIENT_CREDITS":
            raise OutOfCredits(e.code, e.message, e.detail) from e
        if e.code in ("http_404", "http_405", "http_501"):
            # A route this server does not have: not the customer's doing, and
            # not a refusal to retry — the server is older than this app.
            with _lock:
                _state["outdated"] = True
            raise GatewayError("SERVER_OUTDATED", OUTDATED_MESSAGE) from e
        raise GatewayError(e.code, e.message, e.detail) from e
    except Unreachable:
        raise GatewayError(
            "UNREACHABLE", "Couldn't reach Prism's licence server — check this "
            "computer's internet connection and try again.") from None
    with _lock:
        _state["outdated"] = False          # it answered: whatever it is, it is not old
    return out


def _call(op: str, **params) -> dict:
    """One paid lookup: a fresh idempotency key (kept across the transport's own
    retry, so a dropped connection is charged once) and the seat's auth pair."""
    with _lock:
        stopped = _state["exhausted"]
    if stopped:
        raise OutOfCredits("INSUFFICIENT_CREDITS", stopped, {})
    body = _auth_body(idem_key="pc" + uuid.uuid4().hex[:30], **params)
    try:
        out = _raw_call("/v1/leads/" + op, body)
    except OutOfCredits as e:
        _note_exhausted(e)
        raise
    _note(out)
    return out


def _note(out: dict) -> None:
    with _lock:
        _state["used"] += int(out.get("charged", 0) or 0)
        if out.get("balance") is not None:
            _state["balance"] = int(out["balance"])


def _note_exhausted(e: OutOfCredits) -> None:
    """Remember the refusal only when the pool is really empty. A balance of 2
    that cannot buy a 3-credit search can still buy a 1-credit lookup, so one
    refusal must not switch every other lookup off."""
    with _lock:
        _state["balance"] = e.balance
        if e.balance <= 0:
            _state["exhausted"] = e.message



def forget() -> None:
    """Drop everything remembered — the balance, the price list, a refusal, the
    spend and any test transport. For tests, so one run's state never leaks
    into the next."""
    global _send
    with _lock:
        _state.update({"used": 0, "balance": None, "exhausted": "", "rates": {}, "ready": {},
                       "outdated": False})
    _send = None

# ── a run's accounting ───────────────────────────────────────────────────────

def reset() -> None:
    """Start a run: zero the spend and forget an earlier refusal (the balance
    may have been topped up since)."""
    with _lock:
        _state["used"] = 0
        _state["exhausted"] = ""


def used() -> int:
    """Credits this run has been charged so far."""
    with _lock:
        return int(_state["used"])


def exhausted() -> str:
    """'' while the pool can still pay, else the customer-facing reason the run
    stopped."""
    with _lock:
        return _state["exhausted"]


def known_balance() -> Optional[int]:
    with _lock:
        return _state["balance"]


# ── price list, balance, what is switched on ─────────────────────────────────

def status() -> dict:
    """{"balance", "rates", "ready"} from the server — and remembered, so the
    estimates the screens show need no round trip of their own."""
    out = _raw_call("/v1/leads/status", _auth_body())
    with _lock:
        _state["balance"] = int(out.get("balance", 0) or 0)
        _state["rates"] = dict(out.get("rates") or {})
        _state["ready"] = dict(out.get("ready") or {})
        if _state["balance"] > 0:
            _state["exhausted"] = ""
    return out


def rate(action: str, default: int = 1) -> int:
    """What one unit of `action` costs, from the last status() — `default` until
    the server has been asked."""
    with _lock:
        entry = _state["rates"].get(action)
    try:
        return int(entry["credits"]) if entry else default
    except (KeyError, TypeError, ValueError):
        return default


def ready(op: str) -> bool:
    """False only when the server SAID it cannot make this lookup right now — or
    is too old to have the lookup at all (outdated()). Unknown (never asked)
    reads as ready — the lookup itself will say."""
    with _lock:
        flags = _state["ready"]
        old = _state["outdated"]
    if old:
        return False
    return bool(flags.get(op, True)) if flags else True


def outdated() -> bool:
    """True once the licence server answered 404 to a Leads route: it has not
    been updated to the credit pool. Cleared by the next answer that is not."""
    with _lock:
        return bool(_state["outdated"])


# ── the customer's own credit account ────────────────────────────────────────
# What the Credit usage and Upgrade screens read: /v1/credits/*, not a lookup —
# free, no idempotency key, and each raises GatewayError (the screen says why).

def _credits_call(path: str, **params) -> dict:
    out = _raw_call("/v1/credits/" + path,
                    _auth_body(**{k: v for k, v in params.items() if v not in (None, "")}))
    if isinstance(out, dict) and out.get("balance") is not None:
        with _lock:
            _state["balance"] = int(out["balance"])
    return out


def credit_usage(*, min_at=None, max_at=None, device_id=None, action: str = "",
                 limit: int = 200) -> dict:
    """Balance, allowance, renewal date, what was used (by feature and by seat)
    and the activity feed, for one window — the current cycle when no dates."""
    return _credits_call("usage", min_at=min_at, max_at=max_at, device_id=device_id,
                         action=action, limit=limit)


def credit_offers() -> dict:
    """The plans and packs on offer, this licence's plan, and any request it has
    open."""
    return _credits_call("offers")


def request_offer(offer_key: str, note: str = "") -> dict:
    """Ask Alphakore for a plan or a pack. A message, not a purchase — nothing is
    charged or granted until Alphakore does it."""
    return _credits_call("request", offer_key=offer_key, note=note)


# ── the lookups ──────────────────────────────────────────────────────────────
# Each returns what its direct-mode twin returns, so the call site reads the
# same: a list (or "" / a tuple) on success, and None / "" on a failed lookup.

def search_people(query: str, n: int = 50) -> list | None:
    """Exa people rows for one search — a list (maybe empty) when it answered,
    None when the lookup failed. Priced PER SEARCH, and only a search that
    finds people is charged (see the licence server's leads_gateway.people):
    the app can tell the customer how many searches a press makes before it
    runs, which it could never do for "people returned"."""
    n = max(1, min(int(n), 50))
    try:
        out = _call("people", query=query, num_results=n)
    except GatewayError:
        return None
    rows = (out.get("result") or {}).get("results")
    return rows if isinstance(rows, list) else None


def _rows(op: str, **params) -> list | None:
    try:
        out = _call(op, **params)
    except GatewayError:
        return None
    rows = (out.get("result") or {}).get("results")
    return rows if isinstance(rows, list) else None


def company_rows(name: str) -> list | None:
    """Exa's company-index rows for one employer, for the app to match."""
    return _rows("company", name=name)


def website_rows(company: str) -> list | None:
    """[{"url", "title"}] for a company's own website search."""
    return _rows("domain", company=company)


def company_phones(companies: list, why: list | None = None) -> list | None:
    """The phone number each company publishes — [{"name", "domain", "phone",
    "kind", "source_kind", "source_url", "found_at", "evidence"}] for the ones that
    do, a list (maybe empty) when the lookup ran, None when it failed. `companies`
    is [{"name", "domain", "location"}], up to 15 (prospector/phones.py batches).
    Charged per number found; published and format-checked, not called.

    A failure is None like every lookup's, but this one is asked for one reason more
    than the others: when `why` is a list, the server's own sentence (written for the
    customer: server too old, pool empty, provider down) is appended to it."""
    try:
        out = _call("phones", companies=[
            {"name": str(c.get("name") or "")[:160], "domain": str(c.get("domain") or "")[:120],
             "location": str(c.get("location") or "")[:120]} for c in companies[:15]])
    except GatewayError as e:
        if why is not None:
            why.append(e.message)
        return None
    rows = (out.get("result") or {}).get("results")
    if not isinstance(rows, list):
        if why is not None:
            why.append("The server's answer was not one this version of Prism can read.")
        return None
    return rows


def start_mobile(first_name: str, last_name: str, domain: str, why: list | None = None) -> str:
    """Ask for one person's mobile number (Apollo, through the server) and get back
    the lookup's id, or "" when it could not start. It takes minutes, so this only
    starts it and charges nothing; read it with mobile_result(). `why`, when a list,
    gets the server's own sentence for a failure (pool empty, server too old...)."""
    try:
        out = _call("mobile-start", first_name=str(first_name or "")[:60],
                    last_name=str(last_name or "")[:60], domain=str(domain or "")[:120])
    except GatewayError as e:
        if why is not None:
            why.append(e.message)
        return ""
    run_id = out.get("run_id")
    return run_id if isinstance(run_id, str) else ""


def mobile_result(run_id: str, why: list | None = None) -> dict | None:
    """One read of a lookup start_mobile() began: {"state": "pending" | "done",
    "phone": "+91...", "kind": "mobile" | ...} (the phone is "" when Apollo had
    none), or None when the read failed. Charged only when a number comes back,
    and only once: every read of one lookup carries the same idempotency key, so a
    number that arrives on a later read is paid for once however often the app
    asked before it."""
    body = _auth_body(idem_key="mr" + str(run_id), run_id=str(run_id))
    with _lock:
        stopped = _state["exhausted"]
    if stopped:
        if why is not None:
            why.append(stopped)
        return None
    try:
        out = _raw_call("/v1/leads/mobile-result", body)
    except GatewayError as e:
        if isinstance(e, OutOfCredits):
            _note_exhausted(e)
        if why is not None:
            why.append(e.message)
        return None
    _note(out)
    res = out.get("result")
    return res if isinstance(res, dict) and res.get("state") in ("pending", "done") else None


def news_rows(company: str, focus: str = "", exclude_domains=(), num_results: int = 5,
              days: int = 180) -> list | None:
    """Dated news rows about one company, or None when the lookup failed."""
    return _rows("signals", company=company, focus=focus or "", num_results=num_results,
                 days=days, exclude_domains=list(exclude_domains or ())[:60])


def ask(prompt: str, purpose: str, json_mode: bool = False, temperature: float = 0.2) -> str:
    """One model call for `purpose` ('qualify' or 'draft'). Raises GatewayError
    (or OutOfCredits) — the callers already treat any exception as "the model
    could not be reached" and say so on the row."""
    out = _call("llm", purpose=purpose, prompt=prompt, json_mode=bool(json_mode),
                temperature=float(temperature))
    text = (out.get("result") or {}).get("text")
    if not isinstance(text, str) or not text.strip():
        raise GatewayError("PROVIDER_ERROR", "The model returned nothing.")
    return text


def check_email(email: str) -> str:
    """valid / invalid / catch-all / unknown, or '' when no verifier answered
    (in which case nothing was charged)."""
    try:
        out = _call("verify", email=email)
    except GatewayError:
        return ""
    return str((out.get("result") or {}).get("status") or "")


def find_email(first_name: str, last_name: str, domain: str) -> tuple:
    """(email, verification status, finder) — ('', '', '') when none knew. The
    finder's name is kept on the lead so it is not asked again for the address
    it already sold."""
    try:
        out = _call("find-email", first_name=first_name, last_name=last_name, domain=domain)
    except GatewayError:
        return "", "", ""
    res = out.get("result") or {}
    return (str(res.get("email") or ""), str(res.get("status") or ""),
            str(res.get("provider") or ""))


def find_emails(people: list) -> list | None:
    """Real addresses for up to 50 named people in one call — [{"ref","first_name",
    "last_name","domain"}], a domain already known for each. The server tries a
    Hunter Domain Search per company FIRST (one call can resolve several people
    at once) before asking its ordinary finder for whoever that missed — same
    email_find credit either way (verify.find_emails_by_domain). Returns
    [{"ref","email","provider"}] for the ones found, a list (maybe empty) when
    the call answered, None when it failed."""
    try:
        out = _call("find-emails", people=[
            {"ref": str(p.get("ref") or "")[:20], "first_name": str(p.get("first_name") or "")[:60],
             "last_name": str(p.get("last_name") or "")[:60], "domain": str(p.get("domain") or "")[:120]}
            for p in people[:50]])
    except GatewayError:
        return None
    rows = (out.get("result") or {}).get("results")
    return rows if isinstance(rows, list) else None

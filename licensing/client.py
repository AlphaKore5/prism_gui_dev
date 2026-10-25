"""HTTP to the licence server.

Every call here is short, blocking and failure-tolerant, and the caller is
responsible for keeping it off the UI thread. A slow DNS lookup on a corporate
network must never add seconds to Prism's launch, and the licence server being
unreachable must never produce a dialog — the app already holds a token good
for days, which is the entire reason tokens are signed rather than checked
live.

There is no /v1/trial/start. Trials are keys we issue by hand; the client
cannot mint one. See docs/licensing/02-api-and-data.md.
"""
from __future__ import annotations

import os
from typing import Any

import channel
import paths

# Where a shipped build talks to. Baked in at build time and NOT overridable
# at runtime in a frozen app — an env var that could redirect a release build
# to a licence server someone else controls would defeat the whole system.
#
# packaging/build.py writes this from PRISM_SERVER_URL so a test build can be
# pointed at a laptop or a LAN address without editing source. Leave it unset
# for real releases and this default ships.
#
# It must stay the DOMAIN, never the hosting provider's own address. The domain
# is the only thing that lets the licence server move — to another host, to a
# different region, off a free tier — without shipping a new app to everyone
# who already installed one. A build that hard-codes prism-license-server
# .onrender.com is welded to Render for the life of that binary.
#
# This was regressed once, silently, by a one-line change inside a commit about
# something else. Every customer activation in that build would have gone to
# the wrong host. tests/test_licensing_endpoint.py now fails if it drifts again.
DEFAULT_SERVER = "https://prism-license-server.onrender.com"

# Short on purpose. This runs at launch; if the server has not answered in five
# seconds we would rather carry on with the cached token than make the customer
# wait for a timeout they cannot act on.
# Background calls — refresh, deactivate, usage. Failing one of these is
# harmless: the cached token covers it and nothing is shown to the customer.
TIMEOUT = 8

# Authorising a run happens with the customer watching, right after they
# pressed Start the work. They will wait a few seconds for an answer; what
# they will not forgive is being told no because we gave up too early.
#
# Sized for a COLD SERVER, not a warm one. A host that sleeps when idle — which
# is every free and low tier — takes 30-60s to wake, and 15s meant the first
# run of every morning was refused for a server that was merely getting up.
# There is no offline fallback (see licensing.authorize), so this timeout is
# the whole difference between "Prism works" and "Prism doesn't" at 9am.
AUTHORIZE_TIMEOUT = 45

# One retry for a call the customer is watching. A cold start often eats the
# first request entirely — the server wakes, but not before the socket gives
# up — and the second one lands on a warm instance a moment later.
AUTHORIZE_RETRIES = 1

# Renewing the token happens on a background thread that nobody is waiting on,
# so it can afford to wait out a cold server too. At 8s it could not: a host
# waking up ate the only attempt, the token stayed stale, and the customer's
# first click of the morning landed on "Enter a key" for a licence they had
# already paid for.
REFRESH_TIMEOUT = AUTHORIZE_TIMEOUT
REFRESH_RETRIES = AUTHORIZE_RETRIES

# Activation is the most expensive call we make — look up the licence, count
# seats, insert the device, commit — and the one the customer least forgives
# failing, because it is their first impression and they cannot get past it.
#
# Sized for a database that is nowhere near the server: a Supabase project in
# Sydney answers in ~300ms per query, so six queries plus a cold connection
# handshake is comfortably past five seconds. That combination produced a
# "couldn't reach the licence server" on a server that was up and answering.
#
# It is ALSO sized for a sleeping server, which is what the 30s here missed.
# The production host sleeps when idle; a cold /health was measured at 42.6
# seconds — comfortably past a 30-second activation, so the very first thing a
# new customer ever asked Prism to do failed against a server that was up and
# healthy. And activation is the one call they cannot go around: no cached
# token to fall back on, no way into the app, and their first impression is a
# licence they paid for being refused.
#
# 75s is the cold start plus most of it again. A customer who has just typed
# their key will wait; being wrongly told no is what they will not forgive.
ACTIVATE_TIMEOUT = 75

# Deliberately no retry here, unlike authorize().
#
# A timeout on activation is genuinely ambiguous: the request may have reached
# the server, counted a seat and inserted the device before the socket gave
# up. Repeating it can burn a second seat on a two-seat licence — and locking
# a paying customer out of their own second machine is a worse failure than
# the one the retry was meant to fix. The long timeout above is the answer
# instead; it removes the reason to retry rather than papering over it.
ACTIVATE_RETRIES = 0


class ServerError(Exception):
    """The server answered, and said no.

    `message` is the server's own customer-facing wording — it is written as
    copy, not as a log line, so it goes straight to the user.
    """

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


class Unreachable(Exception):
    """Could not talk to the server at all. Almost never worth showing."""


def server_url() -> str:
    """Where to talk to.

    The override exists for staging and is honoured ONLY when running from
    source. An environment variable that redirected a release build would let
    anyone point Prism at a licence server they control, which is precisely the
    backdoor this whole design is meant not to have.
    """
    if not paths.is_frozen():
        override = os.environ.get("PRISM_LICENSE_SERVER")
        if override:
            return override.rstrip("/")
    return DEFAULT_SERVER


def _post(endpoint: str, body: dict[str, Any], *, app_version: str,
          timeout: int | None = None, retries: int = 0) -> dict[str, Any]:
    import requests  # local import: keeps `import licensing` cheap at startup
    import sys
    import time

    url = f"{server_url()}{endpoint}"
    headers = {
        "X-Prism-Version": app_version,
        "X-Prism-Platform": sys.platform,
        # Which release channel this build is, so the licence server can tell a
        # dev build which version to offer without touching production's.
        # A build older than 1.6.12 never sends it and is treated as prod.
        "X-Prism-Channel": channel.CHANNEL,
    }
    response = None
    for attempt in range(retries + 1):
        try:
            response = requests.post(url, json=body, headers=headers,
                                     timeout=timeout or TIMEOUT)
            break
        except Exception as e:                  # noqa: BLE001 — requests raises broadly
            # Only a TRANSPORT failure retries. A server that answered has
            # said something, even if it said no, and repeating the request
            # would double-count a metered run.
            if attempt >= retries:
                raise Unreachable(str(e)) from e
            time.sleep(2)

    try:
        data = response.json()
    except ValueError:
        data = {}

    if response.status_code >= 400:
        error = data.get("error") or {}
        raise ServerError(
            str(error.get("code") or f"http_{response.status_code}"),
            str(error.get("message")
                or "The licence server rejected this request."),
            error.get("detail") if isinstance(error.get("detail"), dict) else {})
    return data


def activate(key: str, device_fp: str, *, app_version: str,
             hostname_label: str = "") -> dict[str, Any]:
    return _post("/v1/activate", {
        "key": key,
        "device_fp": device_fp,
        "app_version": app_version,
        "hostname_label": hostname_label,
    }, app_version=app_version, timeout=ACTIVATE_TIMEOUT,
       retries=ACTIVATE_RETRIES)


def refresh(license_id: str, device_fp: str, *, app_version: str,
            payload_etag: str = "") -> dict[str, Any]:
    return _post("/v1/refresh", {
        "license_id": license_id,
        "device_fp": device_fp,
        "app_version": app_version,
        "payload_etag": payload_etag,
    }, app_version=app_version, timeout=REFRESH_TIMEOUT,
        retries=REFRESH_RETRIES)


def deactivate(license_id: str, device_fp: str, *, app_version: str,
               token: str = "") -> dict[str, Any]:
    """Release this machine's seat.

    `token` is proof we are the machine that holds it. The licence id and the
    fingerprint are not secrets — both sit in ~/.prism and travel in the token
    itself — so without it the server had no way to tell this call apart from a
    stranger releasing someone else's seat.
    """
    return _post("/v1/deactivate", {
        "license_id": license_id,
        "device_fp": device_fp,
        "token": token,
    }, app_version=app_version)


def release_device(key: str, device_id: int, *, app_version: str) -> dict[str, Any]:
    """Free ANOTHER machine's seat, using the key as proof.

    The counterpart to deactivate(): that one releases the seat of the
    machine you are on, this one releases a seat listed in a
    SEAT_LIMIT_REACHED answer — the old, reimaged or traded-in machine —
    from the new one that cannot activate. Same timeout as activate, and
    no retries for the same reason: the request is not idempotent from the
    customer's point of view if it lands twice on different ids.
    """
    return _post("/v1/release", {
        "key": key,
        "device_id": int(device_id),
    }, app_version=app_version, timeout=ACTIVATE_TIMEOUT, retries=0)


def authorize(license_id: str, device_fp: str, *, app_version: str,
              action: str = "run", feature: str = "core",
              scopes: list[str] | None = None) -> dict[str, Any]:
    """Ask permission for one run, or for one add-on being opened.

    This is the METERED call: the server writes a usage row and counts it
    against the daily allowance. Use lease() when all you need is
    authorisation — spending a quota unit to answer "may I open a dialog"
    would bill the customer for the question rather than the work.

    Uses a longer timeout than the launch calls: this one the customer is
    knowingly waiting on, having just pressed a button, so a slow answer beats
    a wrong one.
    """
    return _post("/v1/authorize", {
        "license_id": license_id,
        "device_fp": device_fp,
        "action": action,
        "feature": feature,
        "scopes": scopes or [],
        "app_version": app_version,
    }, app_version=app_version, timeout=AUTHORIZE_TIMEOUT,
       retries=AUTHORIZE_RETRIES)


def lease(license_id: str, device_fp: str, *, app_version: str,
          scopes: list[str] | None = None) -> dict[str, Any]:
    """Fetch a fresh authorisation lease.

    Separate from authorize() because it is FREE: it records no usage event
    and consumes no daily allowance. The server still does the whole check —
    licence status, revocation, seat, device, entitlements, client version —
    it simply is not a billable action.

    Gets the authorise timeout because when the cached lease has gone stale
    this is on the path the customer is watching; the rest of the time it runs
    in the background where the duration does not matter.
    """
    return _post("/v1/lease", {
        "license_id": license_id,
        "device_fp": device_fp,
        "scopes": scopes or [],
        "app_version": app_version,
    }, app_version=app_version, timeout=AUTHORIZE_TIMEOUT,
       retries=AUTHORIZE_RETRIES)


def usage(license_id: str, device_fp: str, *, app_version: str,
          run_id: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return _post("/v1/usage", {
        "license_id": license_id,
        "device_fp": device_fp,
        "run_id": run_id,
        "app_version": app_version,
        "events": events,
    }, app_version=app_version)


def payload(license_id: str, device_fp: str, *, app_version: str) -> dict[str, Any]:
    return _post("/v1/payload", {
        "license_id": license_id,
        "device_fp": device_fp,
        "app_version": app_version,
    }, app_version=app_version)


def call(endpoint: str, body: dict[str, Any], *, app_version: str,
         timeout: int | None = None, retries: int = 0) -> dict[str, Any]:
    """POST to an endpoint on this same server that isn't one of the licence-
    lifecycle calls above — an add-on whose data lives behind this server
    rather than in front of it (WhatsApp, at /v1/whatsapp/…, is the first).

    Just `_post`, named and exported for that caller: the address, headers
    and retry-once-on-transport-failure behaviour are this server's, not a
    second set an add-on would otherwise have to invent and keep in sync.
    """
    return _post(endpoint, body, app_version=app_version, timeout=timeout,
                retries=retries)

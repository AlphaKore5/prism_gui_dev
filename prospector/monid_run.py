"""
Monid, one endpoint at a time
─────────────────────────────
`monid_sources.py` turns four search endpoints into rows for Find my buyers. Everything else Prism
buys through Monid — Apollo's people search and match, the phone sources — needs the same thing: run
ONE endpoint with the owner's own key and hand back the finished run. This is that, and nothing more.

What a finished run looks like (read from real answers, 24-Nov-2026): `status` COMPLETED, the provider's own
HTTP code in `providerResponse.httpStatus` (a no-match is a 404 there, not a failure), the answer in
`output`, and `billedUnits` — 0 for a miss, which is the whole reason the sources are bought this way.

Direct mode only: the owner's key (`monid_api_key` in the config, or MONID_API_KEY). Every run carries
`maxCost`, Monid's own ceiling, so a surprise price is refused before anything is charged. Qt-free.
"""
from __future__ import annotations

import time
import uuid

from . import monid_sources as MS

MonidError = MS.MonidError
api_key = MS.api_key
available = MS.available


def call(provider: str, endpoint: str, *, key: str, body: dict | None = None, query: dict | None = None,
         max_cost: float, post=None, get=None, max_wait: float = 120.0, sleep=time.sleep):
    """Run one endpoint. The finished run (a dict), or None when Monid could not run it — the provider
    was down or too slow, nothing was charged. MonidError, in words for the owner, when the key or the
    wallet is the problem: that stops a whole batch, since every later call would say the same.

    `body` is the endpoint's JSON body, `query` its query string (Apollo's people endpoints take theirs
    there). `post(url, headers, body, timeout)` and `get(url, headers, timeout)` -> (status, json) are
    the test seams, as in monid_sources.run."""
    post, get = post or MS._post, get or MS._get
    headers = {"Authorization": "Bearer " + key, "X-Monid-Client": "prism-desktop",
               "Idempotency-Key": uuid.uuid4().hex}
    payload: dict = {"provider": provider, "endpoint": endpoint, "maxCost": max_cost, "input": {}}
    if query is not None:
        payload["input"]["queryParams"] = query
    if body is not None:
        payload["input"]["body"] = body
    try:
        status, data = post(MS.MONID_URL + "/v1/run", headers, payload, 60)
    except Exception:                                    # noqa: BLE001  (no network: the caller decides)
        return None
    if status in (401, 403):
        raise MonidError("Monid refused the API key. Check MONID_API_KEY.")
    if status == 402 or (isinstance(data, dict) and data.get("errorCode") == "WALLET_INSUFFICIENT_FUNDS"):
        raise MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again.")
    if not isinstance(data, dict):
        return None
    waited = 0.0
    while status == 202 or str(data.get("status") or "").upper() in ("READY", "RUNNING"):
        if waited >= max_wait or not data.get("runId"):
            return None
        sleep(1.5)
        waited += 1.5
        try:
            status, data = get(MS.MONID_URL + "/v1/runs/" + str(data["runId"]), headers, 40)
        except Exception:                                # noqa: BLE001
            return None
        if not isinstance(data, dict):
            return None
    if str(data.get("status") or "").upper() != "COMPLETED":
        return None                                      # failed or blocked: not the same as "nobody found"
    return data


def http_status(run) -> int:
    """The provider's own HTTP code for a finished run (0 when it sent none)."""
    try:
        return int((run.get("providerResponse") or {}).get("httpStatus") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0

"""What the app is allowed to do right now.

Step 8 of verification — the temporal part — plus the shape the rest of the app
reads. Kept separate from token.py because expiry is a normal, expected
condition that the UI has to handle kindly, while a bad signature is an attack.

The six states:

    none      no licence at all            → activation screen, nothing else
    valid     in date, server heard from   → full access to `features`
    grace     past the quoted end date but
              inside grace (paid, late
              payment)                     → full access + renew banner
    stale     in date, but our server has
              not been reached inside the
              licence's offline window     → blocked until it is
    expired   past end date + grace        → read-only: History and Setup only
    tampered  forged, wrong machine,
              or a wound-back clock        → read-only until an online refresh

`stale` and `expired` must never share copy. One means "we couldn't reach
Alphakore"; the other means "your licence is over". Telling a paying customer
the second when the first is true sends them chasing a renewal they do not
need, and costs a support call.

Read-only means the app still opens and the customer can still reach every
piece of work they have already produced. Only new runs and add-ons stop. A
customer locked out of their own past BOQ output does not renew — they file a
complaint, and they are right to.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

NONE = "none"
VALID = "valid"
GRACE = "grace"
STALE = "stale"
EXPIRED = "expired"

# How long a STALE licence — token past its expiry, licence itself in date —
# keeps working before the machine must reach the server. Seven days: the
# offline window the design documents describe, and the tokens the server
# actually issues live one hour, which is not an offline window at all.
STALE_ALLOWANCE = 7 * 24 * 3600
TAMPERED = "tampered"

DAY = 86400

# How far the clock may run backwards before we stop believing it. Generous on
# purpose: timezone changes, DST, a dead CMOS battery on a new site machine and
# a first boot before NTP are all real and innocent. Falsely accusing a paying
# customer of tampering is far worse than missing a rollback — and the rollback
# gains little anyway, because the token's own life is measured in hours.
CLOCK_TOLERANCE = DAY


@dataclass(frozen=True)
class LicenseState:
    status: str = NONE
    plan: str = ""
    customer: str = ""
    kind: str = ""
    features: frozenset[str] = field(default_factory=frozenset)
    seats: int = 0
    license_id: str = ""
    # The date the customer was promised. ALWAYS the one shown in the UI.
    license_ends: int = 0
    # When this particular token dies. Internal — never shown. A customer told
    # "expires in 4 days" on day 3 of a 10-day trial will telephone you.
    token_expires: int = 0
    grace_days: int = 0
    payload_key: str = ""
    payload_etag: str = ""
    message: str = ""
    # What the server last said about versions. NOT claims — they ride along
    # unsigned on every lease and authorize response, so they are advisory by
    # construction: a forged `latest_version` can make the app *suggest* an
    # update, never install one. `min_supported_version` is the floor the
    # server itself enforces on lease issuance; the client only repeats it.
    latest_version: str = ""
    min_supported_version: str = ""
    # Why the state is NONE or TAMPERED, as a stable code ("absent", "empty",
    # "unreadable", "wrong_device", "clock", ...). The activation screen reads
    # it to say WHY it appeared and whether a retry is worth offering.
    reason: str = ""

    @property
    def usable(self) -> bool:
        """May the customer start new work?

        VALID and GRACE, and STALE for up to STALE_ALLOWANCE after the token
        ran out. The server issues one-hour tokens, so "stale" is the normal
        state of every launch more than an hour after the last one — and the
        first click after such a launch used to land on the paywall's "Enter
        a key" while the renewal was still in flight (or had timed out on a
        cold server). Being asked for a key you have already paid for, every
        morning, is not live control; it is a bug. The trade the old rule
        wanted — our availability mattering — still holds, over days: a
        machine that has not reached the server for a week stops. Protected
        work is policed separately by authorize(), which never trusts a token
        alone.
        """
        if self.status in (VALID, GRACE):
            return True
        if self.status == STALE and self.token_expires:
            return time.time() - self.token_expires < STALE_ALLOWANCE
        return False

    @property
    def stale_days_left(self) -> int:
        """Days, rounded up, until a STALE licence stops being usable."""
        if self.status != STALE or not self.token_expires:
            return 0
        return max(math.ceil((self.token_expires + STALE_ALLOWANCE - time.time()) / DAY), 0)

    @property
    def days_left(self) -> int:
        """Days until the licence ends, rounded UP. Negative once it has.

        Rounding up, not down: a 7-day trial is 7 days minus a few seconds the
        instant it is activated, and flooring that shows "6 days left" on a
        licence we just told the customer was seven. Rounding up means the
        count matches the number in our email on day one and still reads
        "1 day left" through the whole final day.
        """
        if not self.license_ends:
            return 0
        return math.ceil((self.license_ends - time.time()) / DAY)

    def has(self, feature: str) -> bool:
        return self.usable and feature in self.features


def resolve(claims: dict[str, Any], *, now: int | None = None) -> LicenseState:
    """Turn verified claims into a state. Assumes token.verify() has passed."""
    now = int(time.time()) if now is None else now

    exp = int(claims.get("exp") or 0)
    grace_days = int(claims.get("grace") or 0)
    # `lend` is the licence end; `exp` is only how long this machine may run
    # without reaching our server. Falling back to exp keeps tokens minted
    # before `lend` existed working.
    lend = int(claims.get("lend") or exp)
    # A trial carries grace 0, so this collapses to a hard stop on the day the
    # customer was told — which is the whole point of the field.
    licence_end = lend + grace_days * DAY

    if now >= licence_end:
        # The licence itself is over. Nothing the network can do about it.
        status = EXPIRED
    elif now >= lend:
        # Past the quoted end date but inside grace — a paid account whose
        # payment is late. Still works; the banner asks them to renew.
        status = GRACE
    elif now < exp:
        status = VALID
    else:
        # In date, but we have not heard from the server inside its offline
        # window. NOT "expired": telling a paying customer their licence ended
        # because our Render instance restarted sends them chasing the wrong
        # thing and costs us a support call.
        status = STALE

    feats = claims.get("feat") or []
    return LicenseState(
        status=status,
        plan=str(claims.get("plan") or ""),
        customer=str(claims.get("cust") or ""),
        kind=str(claims.get("kind") or ""),
        features=frozenset(f for f in feats if isinstance(f, str)),
        seats=int(claims.get("seats") or 0),
        license_id=str(claims.get("sub") or ""),
        # `lend` is the licence end; fall back to the token's own expiry for
        # tokens minted before that claim existed.
        license_ends=int(claims.get("lend") or exp),
        token_expires=exp,
        grace_days=grace_days,
        payload_key=str(claims.get("pk") or ""),
        payload_etag=str(claims.get("petag") or ""),
    )


def none(message: str = "", reason: str = "") -> LicenseState:
    return LicenseState(status=NONE, message=message, reason=reason)


def tampered(message: str, reason: str = "") -> LicenseState:
    return LicenseState(status=TAMPERED, message=message, reason=reason)


def version_tuple(text: str) -> tuple[int, ...]:
    """"1.10.2" → (1, 10, 2). Anything unparseable → ().

    The same parser the licence server uses (license_server/app/config.py),
    kept in step by hand because the two are separate deployables. Hand-rolled
    rather than `packaging.version` because it has to be total: the input is a
    string off the network, and a banner must never be able to crash the
    window. A leading "v" and a "-beta" suffix are tolerated; "1.10" sorts
    above "1.9", which is the whole reason this is not a string compare.
    """
    parts: list[int] = []
    for chunk in (text or "").strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def newer(candidate: str, than: str) -> bool:
    """Is `candidate` a strictly newer version than `than`?

    False whenever either side does not parse. An unreadable server value
    means "no advice", never "update now" — the failure mode of a parser bug
    must be a missing banner, not a permanent one.
    """
    left, right = version_tuple(candidate), version_tuple(than)
    if not left or not right:
        return False
    return left > right


def clock_rolled_back(last_seen: int, now: int | None = None) -> bool:
    """Has the system clock moved backwards past what we have already seen?

    A speed bump, not a control: license.json is user-writable and always will
    be. The real limit on backdating is that a token is only good for seven
    days, so a rollback buys nothing without also blocking the refresh that
    would replace it.
    """
    now = int(time.time()) if now is None else now
    return bool(last_seen) and now < last_seen - CLOCK_TOLERANCE

"""Prism licensing — the whole public surface.

Everything outside this package imports only this module:

    licensing.state()                  what the licence currently allows
    licensing.has("boq")               entitlement check
    licensing.require("boq", self)     check, and show the paywall if not
    licensing.activate(key)            from the activation dialog
    licensing.deactivate()             release this machine's seat
    licensing.refresh()                background token + lease renewal
    licensing.authorize("boq")         may a protected operation go ahead?
    licensing.set_paywall_handler(fn)  wire the UI in, once, at startup

There is deliberately no start_trial(). Trials are keys we issue by hand; the
client cannot mint one.

Two rules run through all of it:

  · Never block the UI. refresh() returns immediately; the network happens on a
    daemon thread and the window builds against the cached token.
  · Fail toward the customer. Any unexpected failure in here resolves to the
    last state we were sure about, never to "expired". A bug in our code must
    not lock out someone who has paid.

════════════════════════════════════════════════════════════════════════════
THE SECURITY BOUNDARY
════════════════════════════════════════════════════════════════════════════
Assume this process is compromised. Everything below runs on the customer's
machine, in a language they can read, from files they can edit; a determined
user can patch out any `if` in this package. Treat every client-side check as
a UX affordance and nothing more.

    LOCAL CLIENT (this package, and the app around it)
      · presentation — which padlocks show, what the banner says
      · workflow editing, local history, local settings
      · Chrome automation against the customer's OWN logged-in sessions
      · verifying — never issuing — backend signatures
      · deciding when to ASK the backend

    BACKEND (license_server/)
      · licence authority: status, expiry, revocation, seats
      · authorisation authority: who gets a lease, with which scopes
      · entitlements: the `feat` list a token and a lease carry
      · quotas and metering
      · every proprietary credential Prism owns
      · the Ed25519 PRIVATE key. It exists there and nowhere else.

The client holds only public verification keys (keys.py). That asymmetry is
the entire design: a modified client can lie to its own user about what it is
allowed to do, but it cannot manufacture a signature, so it cannot obtain
anything the backend actually gates — a lease, a protected response, a
proprietary credential.

The practical rule when adding a feature: if it costs Alphakore money or
exposes something proprietary, it must be gated by a backend check that
independently re-validates. `if licensing.has(...)` is never sufficient for
that class of thing, and is exactly right for deciding whether to grey out a
button.

════════════════════════════════════════════════════════════════════════════
TWO CREDENTIALS, TWO QUESTIONS
════════════════════════════════════════════════════════════════════════════
    licence token   (token.py, ~/.prism/license.json)
        "Is this Prism installation licensed?"
        Hours to days. Read at startup, offline, with no network at all.

    authorisation lease (lease.py, ~/.prism/authorization.json)
        "May this licensed client perform protected operations right now?"
        ~30 minutes, backend-configurable. Names its scopes. Checked before
        anything protected, and re-presented to the backend for anything
        genuinely valuable.

Splitting them is what makes Prism both instant and live. The old design had
only the token, so the only way to get a current answer was a blocking round
trip on every plan — up to 90 seconds against a cold host, with no offline
fallback at all. Now the token opens the app with no network, the lease covers
protected work for half an hour, and the network happens in the background.
"""
from __future__ import annotations

import dataclasses
import os
import threading
import time
from typing import Any, Callable

import app_meta
import channel
import paths

from . import (authorization, client, device, keyformat, keys, lease as _lease_mod,
               meter, payload, secretstore, status as _status, store, token)
from .authorization import Decision, Lease
from .client import ServerError, Unreachable
from .status import (EXPIRED, GRACE, NONE, STALE, TAMPERED,  # noqa: F401
                     VALID, LicenseState)
from .token import TokenError

# NB: the module is status.py, not state.py, because this package also exposes
# a state() function — and a submodule and a function of the same name means
# `from licensing import state` silently hands back whichever won the import,
# which is the sort of thing that is only ever debugged once.

__all__ = [
    "state", "has", "require", "activate", "deactivate", "refresh",
    "authorize", "report_usage", "Authorization", "meter",
    "set_paywall_handler", "device_fingerprint", "reload", "user_dir",
    "LicenseState", "ServerError", "Unreachable", "TokenError", "keyformat",
    "NONE", "VALID", "GRACE", "STALE", "EXPIRED", "TAMPERED",
    "authorization", "lease_state", "lease_bearer", "Decision", "Lease",
    "PROTECTED_ACTIONS", "secretstore", "store",
    "has_saved_key", "reactivate_from_saved_key", "adoptable_licence_folder",
    "adopt_real_licence", "why_activation", "can_retry", "diagnostics_line",
]

# Actions the backend meters and counts against a daily allowance. These go to
# the server when the licence is metered, because a quota can only be counted
# where the counter lives — a lease authorises CAPABILITY, never CONSUMPTION.
#
# Everything not in here (opening an add-on, starting the pipeline against the
# customer's own browser sessions) costs Alphakore nothing per use, so a valid
# lease is a complete answer and no round trip happens at all.
PROTECTED_ACTIONS = frozenset({"plan"})

_lock = threading.Lock()
_cached: LicenseState | None = None
_paywall: Callable[[str, Any, LicenseState], None] | None = None


def _offline_dev() -> bool:
    """PRISM_LICENSE_OFFLINE_DEV — run against a minted token, no server.

    Exists so that working on a dialog does not require uvicorn in another
    terminal. Honoured ONLY when running from source: in a frozen build this
    returns False no matter what the environment says, exactly like the
    PRISM_LICENSE_SERVER override and the DEVELOPMENT keys in keys.py.

    If it were readable in a release build it would be a total bypass of the
    licensing system, settable by any customer with an environment variable.
    That is why the frozen check comes first and there is no way to reorder it.
    """
    if paths.is_frozen():
        return False
    return bool(os.environ.get("PRISM_LICENSE_OFFLINE_DEV"))


def user_dir() -> str:
    return paths.user_dir()


def device_fingerprint() -> str:
    return device.fingerprint(user_dir())[0]


# ── reading the current state ──────────────────────────────────────────────
# How long start-up waits for a licence file that EXISTS but cannot be read
# (antivirus scanning the freshly swapped files, a sync client, a renewal
# thread mid-replace). Only ever spent in that one case: a missing file costs
# nothing. Being asked for the key because a scanner held a file for a second
# is the failure this exists to prevent.
UNREADABLE_WAIT_S = 6.0
_UNREADABLE_STEP_S = 0.5


def _read_licence_file() -> tuple[dict[str, Any], str]:
    """(data, reason-if-no-token). Waits a little if the file is unreadable."""
    data = store.load(user_dir())
    if data.get("token"):
        return data, ""
    problem = store.unreadable(user_dir())
    waited = 0.0
    while problem and waited < UNREADABLE_WAIT_S:
        time.sleep(_UNREADABLE_STEP_S)
        waited += _UNREADABLE_STEP_S
        data = store.load(user_dir())
        if data.get("token"):
            return data, ""
        problem = store.unreadable(user_dir())
    if problem:
        return data, "unreadable"
    exists = os.path.exists(store.path(user_dir()))
    return data, "empty" if exists else "absent"


def _compute() -> LicenseState:
    data, why = _read_licence_file()
    if not data.get("token"):
        return _status.none(reason=why)

    if _status.clock_rolled_back(int(data.get("last_seen_utc") or 0)):
        return _status.tampered(
            "This computer's date and time look wrong — the clock has gone "
            "backwards.\n\nCheck the date and time in your computer's "
            "settings and set them to update automatically, then connect to "
            "the internet so Prism can re-check your licence.",
            reason="clock")

    try:
        claims = token.verify(data["token"],
                              device_fp=device_fingerprint(),
                              public_keys=keys.public_keys())
    except TokenError as e:
        return _status.tampered(str(e), reason=e.code)

    # Version advice rides on the state rather than living in its own cache so
    # the banner is drawn from the same object as everything else — one read,
    # one repaint, no second file to fall out of step. Not claims: see
    # LicenseState for why that is fine.
    return dataclasses.replace(
        _status.resolve(claims),
        latest_version=str(data.get("latest_version") or ""),
        min_supported_version=str(data.get("min_supported_version") or ""))


def state() -> LicenseState:
    """The current licence state. Cached, cheap, safe to call from paint code."""
    global _cached
    with _lock:
        if _cached is None:
            try:
                _cached = _compute()
            except Exception:                       # noqa: BLE001
                # Something we did not anticipate — an unreadable registry, a
                # platform id that vanished mid-session. Send them to the
                # activation screen, which is recoverable, rather than to
                # "expired", which looks like we took their licence away.
                _cached = _status.none(
                    "Prism couldn't read its licence. Please re-enter your key.",
                    reason="error")
        return _cached


def reload() -> LicenseState:
    """Drop the cache and re-read from disk."""
    global _cached
    with _lock:
        _cached = None
    return state()


def has(feature: str) -> bool:
    return state().has(feature)


def set_paywall_handler(fn: Callable[[str, Any, LicenseState], None]) -> None:
    """Register what to show when a locked feature is opened. Called once, from
    main(), so this package never imports Qt."""
    global _paywall
    _paywall = fn


def require(feature: str, parent: Any = None) -> bool:
    """Gate an action. Shows the paywall itself, so call sites stay one line:

        if not licensing.require("boq", self):
            return
    """
    if has(feature):
        return True
    if _paywall is not None:
        try:
            _paywall(feature, parent, state())
        except Exception:                           # noqa: BLE001
            pass    # a broken dialog must not turn into a crash on a click
    return False


# ── the authorisation lease ────────────────────────────────────────────────
def _scopes_wanted() -> list[str]:
    """What to ask the backend to put in a lease.

    Asking for what we hold a token for keeps one lease sufficient for a whole
    session — the point of a lease is one fetch covering many operations, not
    a fetch per feature. The BACKEND decides what it actually grants; this is
    a request, and a lease that comes back narrower is honoured as it came
    back.
    """
    current = state()
    return sorted({authorization.SCOPE_CORE, authorization.SCOPE_WORKFLOW,
                   *current.features})


def _read_lease() -> tuple[Lease | None, str]:
    """The cached lease and its state. Signature checked on every read."""
    return authorization.current(
        user_dir(), device_fp=device_fingerprint(),
        public_keys=keys.public_keys(), license_id=state().license_id)


def lease_state() -> str:
    """authorization.FRESH | GRACE | STALE | NONE | TAMPERED. For the UI."""
    try:
        return _read_lease()[1]
    except Exception:                               # noqa: BLE001
        return authorization.NONE


def lease_bearer() -> str:
    """The raw signed lease, to send as `Authorization: Bearer …` on a call to
    a protected backend endpoint.

    Handing the BACKEND the lease — rather than the client deciding locally
    and then asking for the goods — is what makes a protected operation
    actually protected. The backend re-verifies the signature, the device
    binding, the scope and the revocation list itself, so a patched client
    gains nothing by lying to its own `if`.

    Empty string when there is no usable lease; callers must treat that as
    "not authorised" rather than as "skip the header".

    "Usable" means FRESH. A lease in its offline window still lets an add-on
    open locally, but the backend judges a lease by its own clock and refuses
    one past `exp`; handing it over would fail where an empty answer makes the
    caller renew first (ai_server._auth renews only on an empty bearer).
    """
    try:
        lease_obj, lstate = _read_lease()
    except Exception:                               # noqa: BLE001
        return ""
    if lease_obj is None or lstate != authorization.FRESH:
        return ""
    return lease_obj.raw


def _store_lease(response: dict[str, Any]) -> bool:
    """Cache a lease from a server response, if it verifies.

    Verified BEFORE it is written, never after. Caching something unverified
    would let one bad deploy poison every client's cache with a lease none of
    them can use, and the only cure would be telling customers to delete a
    file.
    """
    raw = (response or {}).get("lease") or ""
    if not raw:
        return False
    try:
        _lease_mod.verify(raw, device_fp=device_fingerprint(),
                          public_keys=keys.public_keys(),
                          license_id=state().license_id)
    except Exception:                               # noqa: BLE001
        # A TokenError means the backend and this build disagree about the
        # lease format or the signing key. Either way the lease is unusable,
        # and dropping it here leaves the previous one in place.
        return False
    authorization.remember(user_dir(), raw)
    return True


# What the server volunteers about versions on every lease and authorize
# response — and inside the `detail` of a CLIENT_TOO_OLD refusal, which is the
# one answer a build that has fallen below the floor will ever get from those
# endpoints. Reading it from the refusal is what lets that build say "update"
# instead of "can't reach the server".
VERSION_FIELDS = ("latest_version", "min_supported_version")


def _versions_in(response: Any) -> dict[str, str]:
    """The version advice in a response or error detail. Only keys that are
    actually present: a server that has stopped sending a field must not
    wipe what we knew, and one that sends it EMPTY must — that is how the
    banner is withdrawn without a client release."""
    found: dict[str, str] = {}
    if not isinstance(response, dict):
        return found
    for name in VERSION_FIELDS:
        if name in response:
            value = response[name]
            found[name] = value.strip() if isinstance(value, str) else ""
    return found


def _store_versions(response: Any) -> bool:
    """Remember the server's version advice. True if anything changed.

    Its own write rather than a ride on _apply(), because the lease refresh —
    the call that runs every ten minutes for as long as the window is open —
    does not go through _apply() at all, and that is the call whose answer a
    customer who has left Prism running all week will actually see.
    """
    wanted = _versions_in(response)
    if not wanted:
        return False
    data = store.load(user_dir())
    if all(data.get(name, "") == value for name, value in wanted.items()):
        return False
    store.update(user_dir(), **wanted)
    reload()
    return True


# ── talking to the server ──────────────────────────────────────────────────
def _apply(response: dict[str, Any], *, key: str = "") -> LicenseState:
    """Persist whatever the server just told us, and re-read."""
    data = store.load(user_dir())
    if response.get("token"):
        data["token"] = response["token"]
    if response.get("license_id"):
        data["license_id"] = response["license_id"]
    # The server's version advice, kept beside the token so updater.py can
    # read it without a round trip: the newest build it knows of, and the
    # oldest it will still lease to. Only what the server actually said —
    # a refresh that says nothing about versions leaves the last advice
    # standing rather than blanking it.
    for field in ("latest_version", "min_supported_version"):
        if response.get(field):
            data[field] = str(response[field])
    data["server"] = client.server_url()
    data.update(_versions_in(response))
    store.save(user_dir(), data)
    store.touch_clock(user_dir())
    if key:
        # Through save_key(), which prefers the OS credential store and clears
        # any plaintext copy a previous version of Prism left behind.
        store.save_key(user_dir(), keyformat.normalise(key))
    result = reload()
    # After reload(), so state().license_id is the new licence — a lease is
    # bound to it and would be rejected against the old one.
    _store_lease(response)
    return result


def activate(key: str) -> LicenseState:
    """Turn a licence key into a token on this machine. Raises ServerError with
    the server's own customer-facing wording, or Unreachable."""
    normalised = keyformat.normalise(key)
    response = client.activate(
        normalised, device_fingerprint(),
        app_version=app_meta.VERSION,
        hostname_label=_hostname())
    return _apply(response, key=normalised)


def release_device(key: str, device_id: int) -> None:
    """Free another machine's seat on the licence `key` belongs to, so THIS
    machine can take it. Raises ServerError / Unreachable like activate();
    nothing local changes — the caller activates afterwards."""
    client.release_device(keyformat.normalise(key), device_id,
                          app_version=app_meta.VERSION)


def deactivate() -> None:
    """Release this machine's seat. Local state is cleared even if the server
    call fails — a customer who has decommissioned a laptop should not be stuck
    with it activated, and a stranded seat is one admin call to release."""
    current = state()
    try:
        if current.license_id:
            client.deactivate(current.license_id, device_fingerprint(),
                              app_version=app_meta.VERSION,
                              # Our own signed token, as proof we hold the seat.
                              token=store.load(user_dir()).get("token") or "")
    except (ServerError, Unreachable):
        pass
    store.clear(user_dir())
    reload()


# ── coming back without asking for the key ───────────────────────────────
def has_saved_key() -> bool:
    """Is a licence key stored on this computer (keyring, then the file)?"""
    try:
        return bool(store.load_key(user_dir()))
    except Exception:                               # noqa: BLE001
        return False


def reactivate_from_saved_key() -> tuple[str, str]:
    """Activate again with the key this computer already holds.

    Returns (outcome, words):
        "ok"          activated; the state is reloaded
        "no_key"      nothing saved
        "refused"     the server answered no (revoked, unknown, seats full);
                      `words` is the server's own wording
        "unreachable" no answer at all (offline, server waking up); a retry is
                      worth offering
        "error"       something unexpected

    Blocking network call: run it on a worker, never on the UI thread.
    """
    try:
        key = store.load_key(user_dir())
    except Exception:                               # noqa: BLE001
        key = ""
    if not key:
        return "no_key", ""
    try:
        activate(key)
    except ServerError as e:
        return "refused", e.message
    except Unreachable:
        return "unreachable", (
            f"Prism couldn't reach its licence server at {client.server_url()}. "
            "Your saved licence is still on this computer.")
    except Exception as e:                          # noqa: BLE001
        return "error", f"{e.__class__.__name__}: {e}"
    return "ok", ""


def _real_licence_folder() -> str:
    """~/.prism of the person, whatever isolation is active."""
    return os.path.join(channel.real_home(), ".prism")


def adoptable_licence_folder() -> str:
    """The normal Prism's data folder, if a dev build could take its licence.

    A dev build keeps its data in its own folder (channel.py), so on a machine
    where the normal Prism is already activated the dev build starts with no
    licence at all. This answers "is there one to offer?": only in a dev build,
    only while this folder has no licence, only if the other folder holds a
    token that verifies for THIS computer. "" otherwise.
    """
    try:
        if not channel.is_dev() or state().status != NONE:
            return ""
        real = _real_licence_folder()
        if os.path.normcase(os.path.abspath(real)) == \
                os.path.normcase(os.path.abspath(user_dir())):
            return ""
        tok = str(store.read_json(store.path(real), {"token": ""}).get("token") or "")
        if not tok:
            return ""
        token.verify(tok, device_fp=device_fingerprint(),
                     public_keys=keys.public_keys())
        return real
    except Exception:                               # noqa: BLE001
        return ""


def adopt_real_licence() -> tuple[bool, str]:
    """Copy the normal Prism's licence into this dev build's folder, once.

    Read-only on the source: files are read from the real folder and written
    to this one, nothing there is touched. Copies the licence, the lease, the
    cached payload and (for machines whose id is a saved random one) the
    device id. If the copy does not give a working licence it is undone.
    """
    real = adoptable_licence_folder()
    if not real:
        return False, "There is no licence to bring over."
    mine = user_dir()
    os.makedirs(mine, exist_ok=True)
    copied: list[str] = []
    try:
        for name in store.STATE_FILES:
            src, dst = os.path.join(real, name), os.path.join(mine, name)
            if not os.path.isfile(src) or os.path.exists(dst):
                continue
            with open(src, "rb") as f:
                blob = f.read()
            tmp = dst + ".adopt.tmp"
            with open(tmp, "wb") as f:
                f.write(blob)
            os.replace(tmp, dst)
            copied.append(dst)
        device.reset_cache()
        result = reload()
    except OSError as e:
        result = None
        error = str(e)
    else:
        error = ""
    if result is None or result.status in (NONE, TAMPERED):
        for dst in copied:
            try:
                os.unlink(dst)
            except OSError:
                pass
        device.reset_cache()
        reload()
        return False, ("Prism couldn't use that licence" +
                       (f" ({error})." if error else " on this build."))
    return True, ""


# ── saying why the key screen is showing ──────────────────────────────────
def can_retry(current: LicenseState) -> bool:
    """Is waiting a moment and trying again a real answer to this state?"""
    return current.reason in ("unreadable", "error")


def why_activation(current: LicenseState) -> str:
    """Plain words for why Prism is asking, and where it looked. No secrets."""
    where = user_dir()
    dev = ("\n\nThis is a development build. It keeps its own licence folder, "
           "separate from the normal Prism on this computer."
           if channel.is_dev() else "")
    reason = current.reason
    if reason == "absent":
        return f"No licence was found in {where}." + dev
    if reason == "empty":
        return (f"The licence file in {where} has no licence in it. That is "
                "what it looks like after this computer was deactivated or the "
                "file was cleared.") + dev
    if reason == "unreadable":
        return (f"Prism found its licence file in {where} but could not read it "
                "just now. Another program (antivirus, a backup or sync tool) "
                "may be holding it. It is still there; try again in a moment.")
    if reason == "wrong_device":
        return ("The licence saved in " + where + " belongs to a different "
                "computer, or this computer's ID has changed since it was "
                "activated.")
    if reason in ("clock", "not_yet_valid"):
        return current.message
    if reason == "error":
        return (f"Prism couldn't read the licence in {where}. "
                "It is still there; try again in a moment.")
    return current.message or f"Prism couldn't use the licence in {where}."


def diagnostics_line(current: LicenseState) -> str:
    """One log line for support: which folder, which files, where the key is.
    Names and yes/no only: never the key, the token or the lease."""
    folder = user_dir()
    data = store.load(folder)
    try:
        keyring_ok = secretstore.available()
        key_in_keyring = bool(secretstore.fetch_key()) if keyring_ok else False
    except Exception:                               # noqa: BLE001
        keyring_ok = key_in_keyring = False
    other = ""
    if channel.is_dev():
        other = (" normal_prism_licence_folder="
                 f"{'has license.json' if os.path.isfile(os.path.join(_real_licence_folder(), store.FILENAME)) else 'no license.json'}")
    return (f"licence screen will show: status={current.status} "
            f"reason={current.reason or '-'} folder={folder} "
            f"files=[{', '.join(store.inventory(folder)) or 'none'}] "
            f"key_location={data.get('key_location') or '-'} "
            f"keyring_available={'yes' if keyring_ok else 'no'} "
            f"key_in_keyring={'yes' if key_in_keyring else 'no'} "
            f"key_in_file={'yes' if data.get('key') else 'no'} "
            f"token_status={'present' if data.get('token') else 'none'} "
            f"channel={channel.CHANNEL}{other}")


def _refresh_once() -> LicenseState:
    data = store.load(user_dir())
    license_id = data.get("license_id") or state().license_id
    if not license_id:
        return state()
    stored_key = store.load_key(user_dir())
    try:
        response = client.refresh(license_id, device_fingerprint(),
                                  app_version=app_meta.VERSION,
                                  payload_etag=data.get("payload_etag") or "")
    except ServerError as e:
        _store_versions(e.detail)
        if e.code == "DEVICE_NOT_ACTIVATED" and stored_key:
            # Someone released this seat, probably by accident. We still hold
            # the key, so re-activate and heal it without troubling anyone.
            try:
                return activate(stored_key)
            except (ServerError, Unreachable):
                return state()
        if e.code in ("LICENSE_REVOKED", "LICENSE_EXPIRED"):
            # The server has definitively withdrawn this licence. The signed
            # token we hold is still valid until it expires and deliberately
            # keeps working — pulling the rug mid-session over a message we
            # cannot verify offline would be its own kind of bug. But the
            # LEASE goes now: it is the thing protected work is checked
            # against, and a revoked licence must stop getting new ones.
            authorization.clear(user_dir())
        # Any other refusal changes nothing right now. The token we already
        # hold is the authority until it runs out.
        return state()
    except Unreachable:
        return state()
    applied = _apply(response)
    if response.get("payload_stale"):
        _fetch_payload(license_id)
    return applied


def _fetch_payload(license_id: str) -> bool:
    """Pull the published configuration, verify it, cache it, apply it.

    Called only when refresh has already said our etag is stale, so the steady
    state costs nothing.

    Every failure path here is a silent no-op that leaves the built-in
    configuration in place. That is the safety property of the whole channel:
    a bad publish, an unreachable server, a signature that does not verify, or
    a payload meant for a newer build all leave the customer exactly as well
    off as the version they installed. Nothing here may ever be able to stop
    Prism working.
    """
    try:
        response = client.payload(license_id, device_fingerprint(),
                                  app_version=app_meta.VERSION)
    except (ServerError, Unreachable):
        return False

    blob = response.get("payload") or ""
    if not blob:
        # Nothing published. Drop any overrides we were holding, so unpublishing
        # is a real undo rather than something that only affects new installs.
        _apply_payload_content({}, [], {})
        store.clear_payload(user_dir())
        store.update(user_dir(), payload_etag="")
        return True
    try:
        claims = payload.verify(blob, public_keys=keys.public_keys(),
                                app_version=app_meta.VERSION)
    except payload.PayloadError:
        return False

    _apply_payload_content(payload.selectors_for(claims),
                           payload.models_for(claims),
                           payload.profiles_for(claims))
    store.save_payload(user_dir(), blob)
    # The etag we record is the SIGNED one, never the envelope's — otherwise a
    # stale payload relabelled in transit would stop us asking for the real fix.
    store.update(user_dir(), payload_etag=str(claims.get("petag") or ""))
    return True


def _apply_payload_content(selectors: dict, models: list | None = None,
                           profiles: dict | None = None) -> None:
    """Hand verified overrides to the engine. Never raises.

    Three independent things, applied separately: which selectors read a
    tool's answer, which Groq models are tried, and how each tool likes to
    be asked. A bad selector costs one tool; a dead model chain costs
    planning entirely; a stale profile costs the quality of one tool's
    answers — which is why all three are published rather than built in.
    """
    try:
        import core_bridge as CB
        CB.agents.apply_overrides(selectors)
    except Exception:
        pass
    try:
        import core_bridge as CB
        CB.router.apply_model_chain(models or [])
    except Exception:
        pass
    try:
        import core_bridge as CB
        CB.agents.apply_profiles(profiles or {})
    except Exception:
        pass


def apply_cached_payload() -> int:
    """Re-apply the last verified payload at startup. Returns agents overridden.

    The cache is re-VERIFIED here rather than trusted, for the same reason
    _store_lease verifies before caching: a signature checked once on the way
    in is not a signature, if the file it landed in is one the customer can
    edit afterwards.
    """
    blob = store.load_payload(user_dir())
    if not blob:
        return 0
    try:
        claims = payload.verify(blob, public_keys=keys.public_keys(),
                                app_version=app_meta.VERSION)
    except payload.PayloadError:
        return 0
    selectors = payload.selectors_for(claims)
    models = payload.models_for(claims)
    profiles = payload.profiles_for(claims)
    _apply_payload_content(selectors, models, profiles)
    return len(selectors) + len(models) + len(profiles)


def _refresh_lease_once(*, clear_if_too_old: bool = False) -> bool:
    """Renew the authorisation lease. True if a fresh one was cached.

    Free — /v1/lease records no usage and consumes no daily allowance — so
    this can run on a timer without billing anybody for the question.
    `clear_if_too_old` is for the background renewal started by authorize()
    only; see the CLIENT_TOO_OLD branch below.
    """
    license_id = store.load(user_dir()).get("license_id") or state().license_id
    if not license_id or state().status in (NONE, TAMPERED):
        return False
    try:
        response = client.lease(license_id, device_fingerprint(),
                                app_version=app_meta.VERSION,
                                scopes=_scopes_wanted())
    except ServerError as e:
        # A CLIENT_TOO_OLD refusal is the only lease answer this build will
        # get once it is below the floor — and it names the floor. Keep it,
        # so the banner can say "update" rather than "can't reach the server".
        _store_versions(e.detail)
        if (e.code in ("LICENSE_REVOKED", "LICENSE_EXPIRED",
                       "DEVICE_NOT_ACTIVATED")
                or (clear_if_too_old and e.code == "CLIENT_TOO_OLD")):
            # A definite withdrawal. Drop the cached lease so protected work
            # stops at the end of this call rather than at the end of the
            # offline window — this is what makes revocation bite.
            # CLIENT_TOO_OLD clears only for the background renewal:
            # authorize() opens an add-on from a lease in its offline window
            # without waiting for this answer, so the floor has to land on
            # the lease for it to refuse the NEXT open. The 10-minute licence
            # timer does not clear: if the floor were raised by mistake,
            # customers on older builds must lose add-ons when their lease
            # ends, not mid-session within 10 minutes.
            authorization.clear(user_dir())
        else:
            authorization.note_attempt(user_dir())
        return False
    except Unreachable:
        authorization.note_attempt(user_dir())
        return False
    _store_versions(response)
    return _store_lease(response)


# One renewal in flight at a time. Taken on the calling thread and released by
# the worker's `finally`, so a second add-on click during a renewal starts no
# second thread and a crash in the worker cannot leave it stuck "in flight".
_renewal_lock = threading.Lock()
_renewal_thread: threading.Thread | None = None


def _renew_in_background() -> None:
    """Start ONE background lease renewal, or do nothing if one is running.

    The thread never touches a widget. Whatever the server answers lands on
    disk (a new lease, or the lease cleared / narrowed), so it is the NEXT
    open that sees it; an add-on that is already open is never closed.
    """
    global _renewal_thread
    if not _renewal_lock.acquire(blocking=False):
        return
    try:
        _renewal_thread = threading.Thread(
            target=_renew_worker, name="prism-lease-renew", daemon=True)
        _renewal_thread.start()
    except Exception:                               # noqa: BLE001
        # No thread, so nothing will release the lock. The open this was
        # called from is already allowed; the next one tries again.
        _renewal_lock.release()


def _renew_worker() -> None:
    try:
        _refresh_lease_once(clear_if_too_old=True)
    except Exception:                               # noqa: BLE001
        pass
    finally:
        _renewal_lock.release()


def _after_renewal(response: dict[str, Any], scope: str) -> Authorization:
    """The answer once a lease or authorize response has been stored.

    The server signs the scopes the licence holds NOW, intersected with what
    was asked for, and refuses nothing on a missing scope. So a plan
    downgrade arrives as a narrower lease, and the old lease that let this
    call through must not be the last word: read what was just stored and
    refuse a scope it does not carry, the same answer a lease already in hand
    gets above.
    """
    lease_obj, lstate = _read_lease()
    decision = authorization.decide(lease_obj, lstate, scope)
    if not decision.allowed and decision.code == "SCOPE_NOT_GRANTED":
        return Authorization(False, code="FEATURE_NOT_LICENSED",
                             message=decision.message, state=lstate)
    return Authorization(True, run_id=response.get("run_id", ""),
                         state=authorization.FRESH)


# False until the first renewal of this session has finished, whatever it
# answered. The window is drawn from the token on disk while that renewal is
# still in flight, and a token past its offline window used to be reported as
# "couldn't reach the licence server" in the seconds before anyone had tried —
# a claim about the network made without asking it.
_refresh_settled = False


def refresh_settled() -> bool:
    """Has this session's first licence renewal finished (success or not)?"""
    return _refresh_settled


def refresh(blocking: bool = False,
            on_done: Callable[[], None] | None = None) -> LicenseState | None:
    """Renew the token and the lease. Returns immediately unless `blocking`.

    Called at launch and periodically. Never surfaces an error: an unreachable
    server is a normal condition that the cached token and lease already cover.

    The lease refresh follows the token refresh on the SAME thread rather than
    on a second one — they are ordered (a lease is bound to the licence id the
    token carries) and neither is urgent, so one background thread doing both
    in sequence is both correct and cheaper than two racing.

    `on_done` is called once both calls have finished, whatever they answered
    — ON THE WORKER THREAD. It exists for "Check for updates", which needs to
    know when the answer has landed and has no other way to find out; a Qt
    caller passes a Signal's emit, which Qt queues back to the UI thread.
    Never touch a widget from it directly.
    """
    store.touch_clock(user_dir())
    if blocking:
        try:
            result = _refresh_once()
            _refresh_lease_once()
        finally:
            _mark_settled()
        _call_quietly(on_done)
        return result
    threading.Thread(target=_safe_refresh, args=(on_done,),
                     name="prism-license-refresh", daemon=True).start()
    return None


def _call_quietly(fn: Callable[[], None] | None) -> None:
    if fn is None:
        return
    try:
        fn()
    except Exception:                               # noqa: BLE001
        pass


def _safe_refresh(on_done: Callable[[], None] | None = None) -> None:
    try:
        _refresh_once()
    except Exception:                               # noqa: BLE001
        pass
    try:
        _refresh_lease_once()
    except Exception:                               # noqa: BLE001
        pass
    _mark_settled()
    _call_quietly(on_done)


def _mark_settled() -> None:
    global _refresh_settled
    _refresh_settled = True


# ── live authorisation & metering ──────────────────────────────────────────
class Authorization:
    """The answer for one run or one add-on.

    `allowed` is the only field a call site should branch on. `state` and
    `offline` exist so the UI can say something useful — "running on cached
    authorisation" reads very differently from "your licence has ended" — and
    neither is a permission.
    """

    def __init__(self, allowed: bool, run_id: str = "", message: str = "",
                 code: str = "", state: str = "", offline: bool = False):
        self.allowed = allowed
        self.run_id = run_id
        self.message = message
        self.code = code
        # authorization.FRESH | GRACE | STALE | NONE | TAMPERED, or "" when
        # the answer came straight from the server.
        self.state = state
        # True when this was answered from cache because the server could not
        # be reached. The caller may want a non-blocking warning; it must not
        # change what runs.
        self.offline = offline

    def __bool__(self) -> bool:
        return self.allowed


def _local_run_id(action: str) -> str:
    """A run id for work the server did not hand one out for.

    The fast path and the offline path both proceed without a round trip, so
    there is no server-issued run_id to group that run's usage events under.
    Without one, everything a customer does offline lands in the reporting as
    a single anonymous blob.

    Deliberately prefixed and deliberately not authoritative: it is a grouping
    key for telemetry the client reports anyway, never an authorisation. The
    `loc_` prefix is what lets the admin console tell a run the server
    authorised from one it merely heard about afterwards.
    """
    import uuid
    if action in PROTECTED_ACTIONS:
        # Recorded here rather than at the call site so that taking the fast
        # path can never quietly cost the admin console its plan counts —
        # which is what happens if metering lives only in the branch that
        # talks to the server.
        meter.record(action, stage=action)
    return f"loc_{uuid.uuid4().hex[:16]}"


def _licence_blocks_protected_work(current: LicenseState) -> Authorization | None:
    """Statuses no lease may override, or None if the licence is no obstacle.

    A lease is normally the FRESHER evidence — the backend caps a lease's
    expiry at the licence's own hard stop, so a valid lease implies a valid
    licence at the moment it was issued, and that is why `stale` (token
    expired, licence fine) is deliberately absent here: a fresh lease is
    exactly the right thing to trust in that case, and refusing it would put
    the round trip back on the path the lease exists to keep clear.

    These three are different. In each of them we cannot establish that the
    licence is alive at all, so a lease that says otherwise is either a clock
    being wound, or a lease that was never ours:

        none      never activated
        expired   past the licence end AND its grace
        tampered  the token does not verify

    Without this the fast path would happily authorise protected work on an
    expired licence for as long as a lease sat on disk — which is precisely
    the hole that "check the cache first" opens if the cache is checked
    *instead of* the licence rather than *as well as*.
    """
    if current.status == NONE:
        return Authorization(False, code="NONE", state=authorization.NONE,
                             message="Prism isn't activated on this computer "
                                     "yet.")
    if current.status == EXPIRED:
        return Authorization(
            False, code=EXPIRED, state=authorization.NONE,
            message="Your licence has ended, so Prism can't start new "
                    "work.\n\nEverything you've already produced is still in "
                    "History. Get in touch and we'll renew it.")
    if current.status == TAMPERED:
        return Authorization(
            False, code=TAMPERED, state=authorization.TAMPERED,
            message=current.message
            or "Prism can't verify this computer's licence, so it can't start "
               "new work. Please re-enter your licence key.")
    return None


def _unreachable_answer(feature: str) -> Authorization:
    """What to say when the server is down and no lease covers this."""
    if _offline_dev():
        # Working on the UI shouldn't require running uvicorn. Source builds
        # only — see _offline_dev().
        if not feature or has(feature):
            return Authorization(True, run_id="dev", state="dev")
        return Authorization(False, code="FEATURE_NOT_LICENSED",
                             message="Not in this dev licence.")
    # Name the address. Without it this message is the same whether the
    # network is down, a firewall is in the way, or the build is simply
    # pointed at a server that does not exist yet — and those need completely
    # different fixes.
    return Authorization(
        False, code="UNREACHABLE", offline=True,
        message=f"Prism couldn't reach the licence server at "
                f"{client.server_url()}, so it can't start new work right "
                "now.\n\nCheck this computer's internet connection and try "
                "again. Everything you've already produced is still in "
                "History.")


def authorize(feature: str = "core", action: str = "run") -> Authorization:
    """May this protected operation go ahead?

    ────────────────────────────────────────────────────────────────────────
    The order, and why it is this order
    ────────────────────────────────────────────────────────────────────────
        1. Local signed lease. Valid and in scope → proceed, no network.
        2. Missing, expired or out of scope → ask the backend.
        3. Backend re-validates licence, device, seat, revocation,
           entitlement, quota and client version, and signs a new lease.
        4. Cache it, and proceed.

    One exception to step 2: an ADD-ON opened while the lease is in its
    offline window (GRACE, signed and in scope) opens at once and the renewal
    runs on a background thread (_renew_in_background). Waiting on a sleeping
    server can take most of a minute and the answer cannot change what this
    open is allowed to do — only the next one. A denial from that renewal
    clears or narrows the lease; it never closes an add-on that is open.

    This replaced a design that went to the server on EVERY plan with no
    offline fallback at all. That was up to 90 seconds against a cold host
    before the customer saw anything, and one flaky connection meant no work.
    The trade it was making — live control in exchange for our availability
    becoming our customers' availability — is now paid for by a signed lease
    instead of by a round trip, which is strictly better on both sides.

    ────────────────────────────────────────────────────────────────────────
    What still always goes to the server
    ────────────────────────────────────────────────────────────────────────
    Metered actions on a metered licence (PROTECTED_ACTIONS, and the lease's
    signed `mtr` flag). A daily allowance can only be counted where the
    counter lives; a lease says what a client MAY do, never how much of it it
    has already done. Prism's own pipeline is browser automation against the
    customer's logged-in sessions and costs Alphakore nothing, so only
    planning — three Groq calls — is in that set.

    ────────────────────────────────────────────────────────────────────────
    The honest limit of the offline window
    ────────────────────────────────────────────────────────────────────────
    Inside GRACE a metered licence can plan without the server counting it.
    That window is the backend-signed `off` claim (the server's
    `offline_hours`, 24 h by default), so the exposure is bounded,
    per-licence, and adjustable without shipping an app.
    A local counter would look like a fix and would not be one — anything this
    process counts, this process can be patched to forget.

    Called at the START of a run or add-on — never during one. A pipeline is
    tens of minutes of browser automation, and failing it part-way would
    discard real work for a reason the customer cannot act on.
    """
    current = state()
    blocked = _licence_blocks_protected_work(current)
    if blocked is not None and current.status != TAMPERED:
        # `none` and `expired` are settled facts the network cannot change.
        # `tampered` falls through: it can be healed by a successful
        # re-activation, and refusing without trying would strand someone
        # whose token was invalidated by a licence reissue.
        return blocked

    scope = feature or authorization.SCOPE_CORE
    lease_obj, lstate = _read_lease()
    decision = authorization.decide(lease_obj, lstate, scope)

    # A lease that is genuinely signed, in date, and simply does not cover
    # this scope is a definite no. Going to the network would produce the same
    # answer more slowly — the backend signs scopes from the same licence.
    if not decision.allowed and decision.code == "SCOPE_NOT_GRANTED":
        return Authorization(False, code="FEATURE_NOT_LICENSED",
                             message=decision.message, state=lstate)

    metered = action in PROTECTED_ACTIONS and (lease_obj is None
                                               or lease_obj.metered)

    # ── the fast path: no network at all ───────────────────────────────────
    # `blocked` is None here for every status that may take it — see
    # _licence_blocks_protected_work. A lease is checked AS WELL AS the
    # licence, never instead of it.
    if (blocked is None and decision.allowed
            and lstate == authorization.FRESH and not metered):
        return Authorization(True, run_id=_local_run_id(action), state=lstate)

    # A lease inside its signed offline window, opening an add-on: decide() has
    # already allowed it, so waiting for the server would only delay a yes.
    # Plans (metered, or counted per run) and runs still ask the server.
    if (blocked is None and decision.allowed
            and lstate == authorization.GRACE
            and action == "addon" and not metered):
        _renew_in_background()
        return Authorization(True, run_id=_local_run_id(action), state=lstate)

    # ── everything else needs the backend ──────────────────────────────────
    data = store.load(user_dir())
    license_id = data.get("license_id") or current.license_id
    if not license_id:
        # No licence id at all — never activated, or the file was cleared.
        return Authorization(False, code=current.status,
                             message="Prism isn't activated on this computer.")

    stored_key = store.load_key(user_dir())
    try:
        if metered:
            response = client.authorize(
                license_id, device_fingerprint(),
                app_version=app_meta.VERSION, action=action, feature=feature,
                scopes=_scopes_wanted())
        else:
            response = client.lease(
                license_id, device_fingerprint(),
                app_version=app_meta.VERSION, scopes=_scopes_wanted())
        _apply(response)
        return _after_renewal(response, scope)
    except ServerError as e:
        _store_versions(e.detail)
        if e.code == "DEVICE_NOT_ACTIVATED" and stored_key:
            # A seat released by mistake. Heal it and try once more.
            try:
                activate(stored_key)
                response = (client.authorize(
                                license_id, device_fingerprint(),
                                app_version=app_meta.VERSION, action=action,
                                feature=feature, scopes=_scopes_wanted())
                            if metered else
                            client.lease(
                                license_id, device_fingerprint(),
                                app_version=app_meta.VERSION,
                                scopes=_scopes_wanted()))
                _apply(response)
                return _after_renewal(response, scope)
            except (ServerError, Unreachable):
                pass
        if e.code in ("LICENSE_REVOKED", "LICENSE_EXPIRED"):
            # Withdrawn. Drop the cached lease so the offline window cannot
            # carry a revoked licence any further.
            authorization.clear(user_dir())
        # A definite no — revoked, expired, add-on not licensed, out of
        # allowance, client too old. The server's wording is customer-facing
        # copy; show it as-is.
        return Authorization(False, message=e.message, code=e.code,
                             state=lstate)
    except Unreachable:
        # The server is down. THIS is where a cached lease earns its keep: an
        # arbitrary network failure must not read as a licence failure.
        authorization.note_attempt(user_dir())
        if blocked is not None:
            # Offline AND unable to establish a live licence. The cached lease
            # does not get to answer this one — that would make "pull the
            # network cable" the way around an expired licence.
            return blocked
        offline = authorization.decide(lease_obj, lstate, scope,
                                       server_reachable=False)
        if offline.allowed:
            return Authorization(True, run_id=_local_run_id(action),
                                 state=lstate, offline=True)
        if offline.code == "LEASE_STALE":
            return Authorization(False, code="LEASE_STALE", offline=True,
                                 message=offline.message, state=lstate)
        return _unreachable_answer(feature)


def report_usage(run_id: str = "") -> None:
    """Send buffered usage. Fire-and-forget; never blocks, never raises.

    Nothing the customer does depends on this arriving, so a failure puts the
    events back on the buffer for the next attempt rather than surfacing.
    """
    threading.Thread(target=_send_usage, args=(run_id,),
                     name="prism-usage", daemon=True).start()


def _send_usage(run_id: str = "") -> None:
    events = meter.drain()
    if not events:
        return
    try:
        data = store.load(user_dir())
        license_id = data.get("license_id") or state().license_id
        if not license_id:
            return
        client.usage(license_id, device_fingerprint(),
                     app_version=app_meta.VERSION, run_id=run_id,
                     events=events)
    except Exception:                               # noqa: BLE001
        meter.restore(events)


def selftest() -> tuple[bool, str]:
    """Verify the committed test vector. Called by main.py's --selftest.

    This has to verify a real signature, not merely import the crypto library.
    `cryptography` loads a native backend dynamically, and freezing breaks
    native extensions in ways that a successful import does not reveal — the
    same class of failure as the SSL trust store and the browser automation
    checks alongside it, both of which are in that self-test because a build
    that imported cleanly still died on a customer's machine.

    Covers BOTH credentials. A build where the token verified and the lease
    did not would open perfectly and then refuse every protected operation —
    which presents exactly like a revoked licence, and would be diagnosed as
    one for as long as it took someone to think of this.
    """
    import json

    path = paths.resource("licensing", "testdata", "vector.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            vector = json.load(f)
    except OSError as e:
        return False, f"test vector missing ({e})"

    pubs = {"vector": vector["public_key"]}
    try:
        claims = token.verify(vector["token"],
                              device_fp=vector["device_fp"],
                              public_keys=pubs,
                              now=int(vector["claims"]["iat"]) + 10)
    except TokenError as e:
        return False, f"vector rejected: {e}"
    except Exception as e:                          # noqa: BLE001
        return False, f"crypto backend unusable: {e}"

    if claims != vector["claims"]:
        return False, "vector claims did not round-trip"

    # The lease half. Absent from vectors generated before leases existed, so
    # a missing key is skipped rather than failed — an old vector should mean
    # "regenerate it", not "this build is broken".
    if vector.get("lease"):
        try:
            leased = _lease_mod.verify(
                vector["lease"], device_fp=vector["device_fp"],
                public_keys=pubs, license_id=vector["lease_claims"]["lid"],
                now=int(vector["lease_claims"]["iat"]) + 10)
        except TokenError as e:
            return False, f"lease vector rejected: {e}"
        except Exception as e:                      # noqa: BLE001
            return False, f"lease crypto unusable: {e}"
        if leased != vector["lease_claims"]:
            return False, "lease vector claims did not round-trip"
    return True, ""


def _hostname() -> str:
    """A human label for the seat list, so a customer asking *which* five
    machines are using their seats gets an answer."""
    import socket
    try:
        return socket.gethostname()[:64]
    except Exception:                               # noqa: BLE001
        return ""

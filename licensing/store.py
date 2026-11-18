"""Where licence state lives on disk: ~/.prism/license.json.

Deliberately NOT in config.json. core/config.py's save() rewrites the whole
dict from whatever the caller is holding, and the GUI keeps `self.cfg` in
memory across dialogs — so any stale copy written back would silently erase the
licence. That would surface as apparently random deactivations, which is about
the worst bug this system could have. A separate file also leaves the
prism_terminal submodule untouched, keeping the CLI a genuinely separate
product.

Every read here is defensive. A truncated or hand-edited file must resolve to
"no licence", never to a crash: the file is user-writable, and the one thing
worse than a customer losing their activation is Prism refusing to launch
because of it.

Nothing in this file is authoritative. It is a cache of things the BACKEND
signed — the licence token, and (in authorization.json, beside it) the
authorisation lease. Every field acted on is read out of a verified payload,
never out of the JSON. Editing this file can turn a working licence into a
rejected one; it cannot turn a rejected one into a working one.

The one exception was the licence key, which sat here in plaintext because it
is a reusable credential the app replays to heal a released seat. It now goes
to the OS credential store when there is one — see secretstore.py and
save_key() below.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

from . import secretstore

FILENAME = "license.json"
PAYLOAD_FILENAME = "payload.enc"

_DEFAULT: dict[str, Any] = {
    "token": "",
    "license_id": "",
    # Plaintext fallback for the reusable licence key, used ONLY when the OS
    # has no usable credential store. Prefer save_key()/load_key(), which try
    # the keychain first and leave this empty when they succeed.
    "key": "",
    # Which of the two places actually holds the key — "keyring", "file" or
    # "absent". Diagnostic only; load_key() checks both regardless, so a stale
    # value here cannot lose anyone their automatic re-activation.
    "key_location": "",
    "last_seen_utc": 0,     # clock high-water mark
    "last_refresh_attempt": 0,
    "payload_etag": "",
    "server": "",
    # The server's last word on versions, copied off the lease/authorize
    # response so the banner can be drawn at launch with no network. Advisory
    # (see status.LicenseState) — a hand-edited value here changes what the
    # banner says and nothing else.
    "latest_version": "",
    "min_supported_version": "",
    # The member's designation key (licensing/designation.py). Beside the
    # licence rather than in config.json for the same reason as the token:
    # config.py rewrites the whole dict from whatever the caller holds, and a
    # stale copy written back would silently demote somebody to no role.
    "designation": "",
}


# ── shared, atomic JSON ────────────────────────────────────────────────────
# license.json and authorization.json have identical durability requirements,
# so they share one implementation. A second hand-rolled copy in
# authorization.py is how one of the two ends up without the fsync.

def read_json(target: str, default: dict[str, Any]) -> dict[str, Any]:
    """Read a state file, resolving every failure to `default`.

    Missing, unreadable, truncated, or not JSON — all the same to the CALLER,
    and none of them may raise: these files are user-writable, and refusing to
    launch over a corrupt cache is a worse outcome than starting fresh.

    They are not the same to SUPPORT, though. A missing file is what "never
    activated" and "deactivated" look like, and that one stays silent on
    purpose — it is the expected, everyday case. Anything else — permission
    denied, a lock held by a scanner or a sync client, a truncated write from
    a crash, a directory where a file should be — means a customer who really
    did activate is being told the same thing as one who never did, with
    nothing anywhere to tell the two apart afterwards. Logging those (and only
    those) does not change what gets returned; it only leaves a trail for the
    one case worth diagnosing.
    """
    last_error = ""
    # A few tries, not one. On Windows a read that lands in the instant the
    # file is being replaced (the renewal thread's os.replace), or while an
    # antivirus scan or sync client holds it, raises PermissionError — and one
    # failed read here used to mean "no licence": the activation screen, for a
    # customer who had activated long ago. It shows up right after an update,
    # when the first launch renews the token while Defender is still scanning
    # the new files. 3 tries, 100 ms apart, cost nothing on the normal path.
    for attempt in range(3):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                _log_read_failure(target, "content is valid JSON but not an object")
                return dict(default)
            return {**default, **data}
        except FileNotFoundError:
            return dict(default)
        except (OSError, ValueError) as e:
            last_error = str(e)
            if attempt < 2:
                time.sleep(0.1)
    _log_read_failure(target, last_error)
    return dict(default)


def _log_read_failure(target: str, reason: str) -> None:
    """Best-effort note that a state file exists but could not be trusted.

    Never raises and never blocks — a broken log must not turn a recoverable
    read failure into a startup failure — and the caller's fallback to
    `default` happens exactly as it would without this.
    """
    try:
        import diagnostics
        diagnostics.write(
            "WARN", f"licence store: could not read {target} ({reason}) — "
                    "treating it as absent for this launch.")
    except Exception:                                   # noqa: BLE001
        pass


def write_json(target: str, data: dict[str, Any]) -> None:
    """Write atomically, 0600.

    A half-written file is indistinguishable from a tampered one and would
    lock the customer out over a power cut. Write a sibling temp file and
    rename — os.replace is atomic on POSIX and on Windows.
    """
    folder = os.path.dirname(target) or "."
    os.makedirs(folder, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".prism-",
                                        suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp_path, 0o600)
        except OSError:
            pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def path(user_dir: str) -> str:
    return os.path.join(user_dir, FILENAME)


def payload_path(user_dir: str) -> str:
    return os.path.join(user_dir, PAYLOAD_FILENAME)


def save_payload(user_dir: str, blob: str) -> None:
    """Cache the signed payload verbatim.

    Kept out of license.json and stored as the raw signed string, because it is
    re-VERIFIED on every load rather than trusted. Storing the parsed content
    would throw away the signature and turn a verified fact into an editable
    one — the same mistake as caching a lease's `allowed` instead of the lease.
    """
    try:
        os.makedirs(user_dir, exist_ok=True)
        tmp = payload_path(user_dir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(blob)
        os.replace(tmp, payload_path(user_dir))
    except OSError:
        pass            # a cache that cannot be written costs one fetch


def load_payload(user_dir: str) -> str:
    try:
        with open(payload_path(user_dir), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def clear_payload(user_dir: str) -> None:
    try:
        os.remove(payload_path(user_dir))
    except OSError:
        pass


def load(user_dir: str) -> dict[str, Any]:
    return read_json(path(user_dir), _DEFAULT)


def unreadable(user_dir: str) -> str:
    """Why license.json exists but cannot be used right now, or "".

    "" for a file that is simply absent (the everyday "never activated") AND
    for one that reads fine. Anything else (locked by a scanner or a sync
    client, truncated by a crash, a folder where the file should be) is the
    difference between "this person never activated" and "Prism could not look
    just now", which the start-up gate must not treat alike.
    """
    target = path(user_dir)
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as e:
        return str(e) or e.__class__.__name__
    return "" if isinstance(data, dict) else "the file is not a JSON object"


# Names only ever reach a log line; never what is inside.
STATE_FILES = (FILENAME, "authorization.json", PAYLOAD_FILENAME, "device_id")


def inventory(user_dir: str) -> list[str]:
    """Which licence-related files exist in `user_dir`, by name and size."""
    found = []
    for name in STATE_FILES:
        try:
            found.append(f"{name}({os.path.getsize(os.path.join(user_dir, name))}B)")
        except OSError:
            continue
    return found


def save(user_dir: str, data: dict[str, Any]) -> None:
    write_json(path(user_dir), {**_DEFAULT, **data})


def update(user_dir: str, **fields: Any) -> dict[str, Any]:
    """Change some fields and leave the rest alone.

    The read-modify-write that save() alone invites callers to do by hand —
    and doing it by hand is how a caller holding a stale dict wipes the token
    while only meaning to set the designation.
    """
    data = load(user_dir)
    data.update(fields)
    save(user_dir, data)
    return data


def touch_clock(user_dir: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Advance the high-water mark to now, if now is later than it.

    Only ever moves forward. That is what makes winding the clock back
    detectable at all — see state.clock_rolled_back().
    """
    data = load(user_dir) if data is None else data
    now = int(time.time())
    if now > int(data.get("last_seen_utc") or 0):
        data["last_seen_utc"] = now
        save(user_dir, data)
    return data


# ── the reusable licence key ───────────────────────────────────────────────
# Kept at all only so _refresh_once() can silently re-activate a seat somebody
# released by mistake. It is the one credential in the system that is neither
# device-bound nor short-lived, so it is the one worth protecting properly.

def save_key(user_dir: str, key: str) -> str:
    """Store the licence key as securely as this machine allows.

    Returns where it went, for diagnostics. On success with a keychain the
    plaintext copy is actively REMOVED from license.json — an upgrade has to
    clean up the key the previous version wrote, or the improvement is only
    theoretical for every existing customer.
    """
    data = load(user_dir)
    if secretstore.store_key(key):
        data["key"] = ""
        data["key_location"] = secretstore.KEYRING
        save(user_dir, data)
        return secretstore.KEYRING
    data["key"] = key
    data["key_location"] = secretstore.FILE
    save(user_dir, data)
    return secretstore.FILE


def load_key(user_dir: str) -> str:
    """The licence key, from wherever it ended up.

    Checks the keychain first but always falls back to the file, so a customer
    upgrading from a build that only knew about the file keeps their automatic
    re-activation. `key_location` is not consulted: it is a label, and a label
    that disagreed with reality must not cost someone a working seat.
    """
    return secretstore.fetch_key() or str(load(user_dir).get("key") or "")


def forget_key(user_dir: str) -> None:
    """Remove it from both places."""
    secretstore.forget_key()
    data = load(user_dir)
    data["key"] = ""
    data["key_location"] = secretstore.ABSENT
    save(user_dir, data)


def clear(user_dir: str) -> None:
    """Forget this machine's activation. Used by Deactivate this device.

    Takes the authorisation lease and the stored key with it. Releasing a seat
    while leaving a valid lease on disk would let protected work carry on for
    the rest of the lease's life on a machine that has just been decommissioned
    — and leaving the key behind means the next launch quietly re-activates and
    takes the seat back.
    """
    secretstore.forget_key()
    from . import authorization
    authorization.clear(user_dir)
    for p in (path(user_dir), payload_path(user_dir)):
        try:
            os.unlink(p)
        except OSError:
            pass

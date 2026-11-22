"""Tests for the licensing package.

Covers the matrix in docs/licensing/03-client-integration.md. Plain unittest so
it runs anywhere with no extra dependency:

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import licensing
from licensing import device, keyformat, keys, status as S, store, token

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "devtools"))
import mint  # noqa: E402

DAY = 86400
DEVICE = "0123456789abcdef"


def _keypair():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
    return private, public


def _claims(**over):
    now = int(time.time())
    base = {
        "kid": "test", "sub": "lic_test", "cust": "Test Ltd", "plan": "business",
        "kind": "paid", "feat": ["core", "boq"], "seats": 3, "dev": DEVICE,
        "iat": now, "nbf": now, "exp": now + 7 * DAY, "lend": now + 30 * DAY,
        "grace": 3,
    }
    base.update(over)
    return base


class TokenVerification(unittest.TestCase):
    def setUp(self):
        self.private, self.public = _keypair()
        self.keys = {"test": self.public}

    def _token(self, **over):
        return mint.sign(_claims(**over), self.private)

    def test_valid_token_round_trips(self):
        claims = token.verify(self._token(), device_fp=DEVICE,
                              public_keys=self.keys)
        self.assertEqual(claims["sub"], "lic_test")
        self.assertEqual(claims["feat"], ["core", "boq"])

    def test_flipped_byte_is_rejected(self):
        tok = self._token()
        head, payload, sig = tok.split(".")
        # Flip one character of the payload segment.
        swapped = ("X" if payload[10] != "X" else "Y")
        tampered = f"{head}.{payload[:10]}{swapped}{payload[11:]}.{sig}"
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(tampered, device_fp=DEVICE, public_keys=self.keys)
        self.assertIn(ctx.exception.code, ("bad_signature", "malformed"))

    def test_signature_from_another_key_is_rejected(self):
        other, _ = _keypair()
        forged = mint.sign(_claims(), other)
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(forged, device_fp=DEVICE, public_keys=self.keys)
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_token_for_another_machine_is_rejected(self):
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(self._token(), device_fp="ffffffffffffffff",
                         public_keys=self.keys)
        self.assertEqual(ctx.exception.code, "wrong_device")

    def test_unknown_kid_is_rejected(self):
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(self._token(kid="nope"), device_fp=DEVICE,
                         public_keys=self.keys)
        self.assertEqual(ctx.exception.code, "unknown_key")

    def test_wrong_version_prefix_is_rejected(self):
        tok = "PRSMv2." + self._token().split(".", 1)[1]
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(tok, device_fp=DEVICE, public_keys=self.keys)
        self.assertEqual(ctx.exception.code, "version")

    def test_garbage_is_rejected_not_crashed(self):
        for junk in ("", "hello", "a.b", "PRSMv1.!!!.!!!", "PRSMv1.e30.zz"):
            with self.assertRaises(token.TokenError):
                token.verify(junk, device_fp=DEVICE, public_keys=self.keys)

    def test_token_from_the_future_is_rejected(self):
        future = int(time.time()) + 10 * DAY
        with self.assertRaises(token.TokenError) as ctx:
            token.verify(self._token(nbf=future), device_fp=DEVICE,
                         public_keys=self.keys)
        self.assertEqual(ctx.exception.code, "not_yet_valid")

    def test_small_clock_skew_is_tolerated(self):
        soon = int(time.time()) + 60
        token.verify(self._token(nbf=soon), device_fp=DEVICE,
                     public_keys=self.keys)   # must not raise

    def test_signature_covers_the_version_prefix(self):
        """A PRSMv1 signature must not verify as any other version."""
        claims = _claims()
        payload_b64 = token.b64u_encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
        # Sign the payload WITHOUT the prefix — the mistake the helper prevents.
        bad_sig = self.private.sign(payload_b64.encode())
        forged = f"PRSMv1.{payload_b64}.{token.b64u_encode(bad_sig)}"
        with self.assertRaises(token.TokenError):
            token.verify(forged, device_fp=DEVICE, public_keys=self.keys)


class CommittedVector(unittest.TestCase):
    """The one artefact proving signer and verifier agree — on every platform,
    and inside a frozen build."""

    def test_vector_verifies(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "licensing", "testdata", "vector.json")
        with open(path, "r", encoding="utf-8") as f:
            vector = json.load(f)
        claims = token.verify(vector["token"],
                              device_fp=vector["device_fp"],
                              public_keys={"vector": vector["public_key"]},
                              now=vector["claims"]["iat"] + 10)
        self.assertEqual(claims, vector["claims"])


class StateResolution(unittest.TestCase):
    def test_in_date_is_valid(self):
        now = int(time.time())
        st = S.resolve(_claims(exp=now + DAY))
        self.assertEqual(st.status, S.VALID)
        self.assertTrue(st.usable)
        self.assertTrue(st.has("boq"))
        self.assertFalse(st.has("reel"))

    def test_inside_grace_is_still_usable(self):
        """Past the quoted end date, inside grace — a paid account whose
        payment is late. Still works, with a renew banner."""
        now = int(time.time())
        st = S.resolve(_claims(exp=now + DAY, lend=now - DAY, grace=3))
        self.assertEqual(st.status, S.GRACE)
        self.assertTrue(st.usable)

    def test_stale_within_a_week_is_still_usable(self):
        """The token the server issues lives ONE HOUR. Every launch more than
        an hour after the last one therefore opens on a stale token, and
        locking the app for that — padlocks on the rail, the paywall's
        "Enter a key" on the first click — was the bug reported as "I have
        to enter the key every time I open Prism". Stale, licence in date,
        less than a week old: usable, with a banner."""
        now = int(time.time())
        st = S.resolve(_claims(exp=now - 3 * 3600, lend=now + 300 * DAY))
        self.assertEqual(st.status, S.STALE)
        self.assertTrue(st.usable)
        self.assertTrue(st.has("boq"))
        self.assertEqual(st.stale_days_left, 7)

    def test_stale_for_over_a_week_stops(self):
        """The trade the old rule wanted still holds, over days: a machine
        that has not reached the server for a week stops until it does."""
        now = int(time.time())
        st = S.resolve(_claims(exp=now - 8 * DAY, lend=now + 300 * DAY))
        self.assertEqual(st.status, S.STALE)
        self.assertFalse(st.usable)
        self.assertFalse(st.has("boq"))
        self.assertEqual(st.stale_days_left, 0)

    def test_past_grace_is_expired(self):
        now = int(time.time())
        st = S.resolve(_claims(exp=now - 5 * DAY, lend=now - 5 * DAY, grace=3))
        self.assertEqual(st.status, S.EXPIRED)
        self.assertFalse(st.usable)
        self.assertFalse(st.has("core"))

    def test_trial_has_no_grace(self):
        """A 10-day trial ends on day 10 — the date in the email we sent."""
        now = int(time.time())
        st = S.resolve(_claims(kind="trial", exp=now - 60, lend=now - 60,
                               grace=0))
        self.assertEqual(st.status, S.EXPIRED)

    def test_ui_shows_licence_end_not_token_expiry(self):
        now = int(time.time())
        st = S.resolve(_claims(exp=now + 7 * DAY, lend=now + 10 * DAY))
        self.assertEqual(st.days_left, 10)         # the licence, not the token
        self.assertNotEqual(st.license_ends, st.token_expires)

    def test_days_left_matches_the_number_we_quoted(self):
        """A 7-day trial must say 7 the moment it is activated, not 6."""
        now = int(time.time())
        st = S.resolve(_claims(exp=now + 7 * DAY, lend=now + 7 * DAY))
        self.assertEqual(st.days_left, 7)

    def test_final_day_still_reads_as_one(self):
        now = int(time.time())
        st = S.resolve(_claims(exp=now + 3600, lend=now + 3600))
        self.assertEqual(st.days_left, 1)

    def test_stale_is_not_expired(self):
        """In date, but we have not reached the server inside its offline
        window. Still STALE, never EXPIRED — and, since the tokens the server
        issues live one hour, a minute past expiry is what every launch looks
        like, so it stays usable (see the two tests below for the week-long
        allowance and its end)."""
        now = int(time.time())
        st = S.resolve(_claims(exp=now - 60, lend=now + 20 * DAY))
        self.assertEqual(st.status, S.STALE)
        self.assertTrue(st.usable)
        self.assertNotEqual(st.status, S.EXPIRED)

    def test_clock_rollback_detected(self):
        now = int(time.time())
        self.assertTrue(S.clock_rolled_back(now + 40 * DAY, now=now))

    def test_small_backward_drift_is_not_tampering(self):
        now = int(time.time())
        self.assertFalse(S.clock_rolled_back(now + 3600, now=now))
        self.assertFalse(S.clock_rolled_back(0, now=now))


class KeyFormat(unittest.TestCase):
    def test_generated_keys_are_well_formed(self):
        for _ in range(200):
            self.assertTrue(keyformat.is_well_formed(keyformat.generate()))

    def test_checksum_catches_a_typo(self):
        key = keyformat.generate()
        body = keyformat.normalise(key)[4:]
        wrong = "2" if body[0] != "2" else "3"
        self.assertFalse(keyformat.is_well_formed("PRSM" + wrong + body[1:]))

    def test_confusable_characters_are_repaired(self):
        key = keyformat.generate()
        canonical = keyformat.normalise(key)
        typed = keyformat.format_display(key).lower().replace("1", "l")
        self.assertEqual(keyformat.normalise(typed), canonical)

    def test_whitespace_and_hyphens_ignored(self):
        key = keyformat.generate()
        messy = "  " + keyformat.format_display(key).replace("-", " ") + "\n"
        self.assertTrue(keyformat.is_well_formed(messy))

    def test_display_format(self):
        shown = keyformat.format_display(keyformat.generate())
        self.assertRegex(shown, r"^PRSM(-[0-9A-Z]{5}){4}$")

    def test_wrong_length_rejected(self):
        self.assertFalse(keyformat.is_well_formed("PRSM-ABC"))
        self.assertFalse(keyformat.is_well_formed(""))


class Store(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-lic-test-")

    def test_missing_file_gives_defaults(self):
        self.assertEqual(store.load(self.tmp)["token"], "")

    def test_round_trip(self):
        store.save(self.tmp, {"token": "abc", "license_id": "lic_1"})
        self.assertEqual(store.load(self.tmp)["license_id"], "lic_1")

    def test_corrupt_file_does_not_raise(self):
        with open(store.path(self.tmp), "w", encoding="utf-8") as f:
            f.write('{"token": "abc"')          # truncated
        self.assertEqual(store.load(self.tmp)["token"], "")

    def test_non_object_json_does_not_raise(self):
        with open(store.path(self.tmp), "w", encoding="utf-8") as f:
            f.write("[1,2,3]")
        self.assertEqual(store.load(self.tmp)["token"], "")

    def test_clock_only_moves_forward(self):
        future = int(time.time()) + 10 * DAY
        store.save(self.tmp, {"last_seen_utc": future})
        store.touch_clock(self.tmp)
        self.assertEqual(store.load(self.tmp)["last_seen_utc"], future)

    def test_permissions_are_owner_only(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions only")
        store.save(self.tmp, {"token": "abc"})
        self.assertEqual(os.stat(store.path(self.tmp)).st_mode & 0o777, 0o600)

    def test_clear_removes_token_and_payload(self):
        store.save(self.tmp, {"token": "abc"})
        with open(store.payload_path(self.tmp), "wb") as f:
            f.write(b"ciphertext")
        store.clear(self.tmp)
        self.assertFalse(os.path.exists(store.path(self.tmp)))
        self.assertFalse(os.path.exists(store.payload_path(self.tmp)))


class Device(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-dev-test-")
        device.reset_cache()

    def tearDown(self):
        device.reset_cache()

    def test_fingerprint_is_stable_and_shaped(self):
        first, tier = device.fingerprint(self.tmp)
        device.reset_cache()
        second, _ = device.fingerprint(self.tmp)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertIn(tier, (device.TIER_PLATFORM, device.TIER_MAC,
                             device.TIER_RANDOM))

    def test_raw_identity_never_leaks_into_the_hash(self):
        raw, _ = device.raw_identity(self.tmp)
        fp, _ = device.fingerprint(self.tmp)
        self.assertNotIn(raw.lower(), fp.lower())

    def test_persisted_fallback_survives(self):
        first = device._persisted_random(self.tmp)
        self.assertEqual(first, device._persisted_random(self.tmp))


class FrozenBuildSafety(unittest.TestCase):
    """The dev signing key and the server override must not exist in a release
    build. Either one shipping would be a universal backdoor."""

    def test_dev_keys_are_rejected_when_frozen(self):
        with mock.patch.object(keys.paths, "is_frozen", return_value=True):
            self.assertNotIn("dev1", keys.public_keys())
        self.assertIn("dev1", keys.public_keys())      # trusted from source

    def test_dev2_and_every_development_key_rejected_when_frozen(self):
        """dev2 is the kid devtools/mint.py signs with (2026-11-23). A frozen
        build must hold the PRODUCTION keys and nothing else."""
        self.assertIn("dev2", keys.DEVELOPMENT)
        with mock.patch.object(keys.paths, "is_frozen", return_value=True):
            frozen = keys.public_keys()
        self.assertNotIn("dev2", frozen)
        self.assertEqual(frozen, keys.PRODUCTION)
        self.assertFalse(set(frozen) & set(keys.DEVELOPMENT))
        self.assertFalse(set(frozen.values()) & set(keys.DEVELOPMENT.values()))
        self.assertIn("dev2", keys.public_keys())      # trusted from source

    def test_server_override_ignored_when_frozen(self):
        from licensing import client
        with mock.patch.dict(os.environ, {"PRISM_LICENSE_SERVER": "http://evil"}):
            with mock.patch.object(client.paths, "is_frozen", return_value=True):
                self.assertEqual(client.server_url(), client.DEFAULT_SERVER)
            with mock.patch.object(client.paths, "is_frozen", return_value=False):
                self.assertEqual(client.server_url(), "http://evil")


class PublicApi(unittest.TestCase):
    """End-to-end through licensing.state(), against a temp ~/.prism."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-api-test-")
        self.private, self.public = _keypair()
        device.reset_cache()
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys", return_value={"test": self.public}),
        ]
        for p in self.patches:
            p.start()
        licensing.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    def _install(self, **over):
        fp = device.fingerprint(self.tmp)[0]
        claims = _claims(dev=fp, **over)
        store.save(self.tmp, {"token": mint.sign(claims, self.private),
                              "license_id": claims["sub"],
                              "last_seen_utc": int(time.time())})
        return licensing.reload()

    def test_no_file_is_none(self):
        self.assertEqual(licensing.state().status, S.NONE)
        self.assertFalse(licensing.has("core"))

    def test_activated_licence_grants_features(self):
        st = self._install()
        self.assertEqual(st.status, S.VALID)
        self.assertTrue(licensing.has("boq"))
        self.assertFalse(licensing.has("reel"))

    def test_hand_edited_features_are_rejected(self):
        """Editing license.json to add an add-on must not work."""
        self._install()
        data = store.load(self.tmp)
        head, payload, sig = data["token"].split(".")
        claims = json.loads(token.b64u_decode(payload))
        claims["feat"].append("reel")
        forged = token.b64u_encode(
            json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
        data["token"] = f"{head}.{forged}.{sig}"
        store.save(self.tmp, data)
        st = licensing.reload()
        self.assertEqual(st.status, S.TAMPERED)
        self.assertFalse(licensing.has("reel"))
        self.assertFalse(licensing.has("core"))

    def test_clock_rollback_blocks(self):
        self._install()
        data = store.load(self.tmp)
        data["last_seen_utc"] = int(time.time()) + 40 * DAY
        store.save(self.tmp, data)
        self.assertEqual(licensing.reload().status, S.TAMPERED)

    def test_deleting_the_file_does_not_grant_a_trial(self):
        self._install()
        store.clear(self.tmp)
        self.assertEqual(licensing.reload().status, S.NONE)
        self.assertFalse(licensing.has("core"))

    def test_expired_trial_blocks_new_work(self):
        now = int(time.time())
        st = self._install(kind="trial", grace=0, exp=now - 60, lend=now - 60)
        self.assertEqual(st.status, S.EXPIRED)
        self.assertFalse(licensing.has("core"))

    def test_require_invokes_the_paywall_once(self):
        self._install()
        seen = []
        licensing.set_paywall_handler(lambda f, p, s: seen.append(f))
        try:
            self.assertTrue(licensing.require("boq"))
            self.assertFalse(licensing.require("reel"))
            self.assertEqual(seen, ["reel"])
        finally:
            licensing.set_paywall_handler(None)

    def test_a_broken_paywall_does_not_crash_the_click(self):
        self._install()

        def boom(*_):
            raise RuntimeError("dialog exploded")

        licensing.set_paywall_handler(boom)
        try:
            self.assertFalse(licensing.require("reel"))
        finally:
            licensing.set_paywall_handler(None)

    def test_unexpected_failure_is_recoverable_not_expired(self):
        """A bug in our code must never look like a revoked licence."""
        self._install()
        with mock.patch.object(licensing, "_compute", side_effect=RuntimeError):
            st = licensing.reload()
        self.assertEqual(st.status, S.NONE)      # recoverable: re-enter the key
        self.assertNotEqual(st.status, S.EXPIRED)


class MintedTokenShape(unittest.TestCase):
    def _args(self, **over):
        base = dict(days=10, ttl=7, features="core", kind="trial", plan="trial",
                    customer="X", license_id="lic_x", seats=1, grace=3,
                    kid="dev1", now=1_700_000_000)
        base.update(over)
        return mock.Mock(**base)

    def test_token_never_outlives_the_licence(self):
        claims = mint.build_claims(self._args(days=10), DEVICE)
        self.assertLessEqual(claims["exp"], claims["lend"])
        self.assertEqual(claims["grace"], 0)              # trials get none

    def test_short_licence_caps_the_token(self):
        """A 3-day trial must not be handed a 7-day token — that would be four
        free days past the date we told the customer."""
        claims = mint.build_claims(self._args(days=3, ttl=7), DEVICE)
        self.assertEqual(claims["exp"], claims["lend"])
        self.assertEqual(claims["exp"], claims["iat"] + 3 * DAY)

    def test_paid_licence_keeps_its_grace_and_ttl(self):
        args = mock.Mock(days=365, ttl=7, features="core", kind="paid",
                         plan="business", customer="X", license_id="lic_x",
                         seats=5, grace=3, kid="dev1", now=1_700_000_000)
        claims = mint.build_claims(args, DEVICE)
        self.assertLess(claims["exp"], claims["lend"])
        self.assertEqual(claims["grace"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

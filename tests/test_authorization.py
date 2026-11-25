"""Does the authorisation lease actually authorise?

test_licensing.py proves the licence TOKEN is verified correctly — is this
installation licensed. This file proves the second half: given a licensed
installation, may it perform a protected operation *right now*, and what
happens when the server is not there to ask.

The distinction is the whole point of the two-credential design, and it is
exactly the sort of thing that passes every state test while the gate itself
is wrong.

Every test here runs against a temp ~/.prism and a throwaway signing key, with
`requests` never imported — client.py is patched at the function boundary, so
nothing in here can touch a network even by accident.

The lettered cases map to the hardening matrix:

    A  valid token                       → startup succeeds locally
    B  modified lease payload            → signature verification fails
    C  modified plan/entitlement         → verification fails / scope denied
    D  wrong device                      → authorisation denied
    E  expired licence                   → protected functionality denied
    F  expired lease                     → refresh required
    G  temporary outage inside grace     → cached lease still usable
    H  revoked licence                   → no new lease, cache dropped
    I  modified plans.py                 → unlocks nothing
    J  modified client-side check        → backend still the authority
    K  server down at startup            → GUI still opens
    L  server down past the lease        → offline policy decides
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "devtools"))

from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey)

import licensing  # noqa: E402
import mint  # noqa: E402
from licensing import (authorization as A, client, device, keys,  # noqa: E402
                       lease as L, store, token as T)

DAY = 86400


def join_licence_threads(timeout: float = 10.0) -> None:
    """Wait for licensing's fire-and-forget daemon threads to finish.

    licensing.refresh() and licensing.report_usage() are deliberately
    unjoinable in the product — nothing the customer does waits on them. A
    test that starts one and does not wait for it has handed the next test a
    thread that re-reads licensing.user_dir() and keys.public_keys() long
    after the patches that set them have been undone. See
    test_k_refresh_returns_immediately_and_never_raises for what that cost.
    """
    for t in threading.enumerate():
        if t.name.startswith("prism-") and t.is_alive():
            t.join(timeout)


class LeaseHarness(unittest.TestCase):
    """A temp ~/.prism, a throwaway signing key, and no network anywhere."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-lease-")
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        device.reset_cache()
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys",
                              return_value={"t": self.public}),
            # No credential store in tests. Otherwise a developer's own
            # keychain would be written to by the suite, and — worse — the
            # plaintext-fallback assertions would pass or fail depending on
            # whose laptop ran them.
            mock.patch.object(licensing.secretstore, "_keyring",
                              return_value=None),
        ]
        for p in self.patches:
            p.start()
        licensing.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    # ── building the two credentials ───────────────────────────────────────
    @property
    def device_fp(self) -> str:
        return device.fingerprint(self.tmp)[0]

    def install_token(self, *, features=("core", "boq"), days=10,
                      license_id="lic_t", kind="paid", dev=None):
        now = int(time.time())
        claims = {
            "kid": "t", "sub": license_id, "cust": "RS Infotech",
            "plan": "works", "kind": kind, "feat": list(features), "seats": 1,
            "dev": dev or self.device_fp,
            "iat": now, "nbf": now, "exp": now + days * DAY,
            "lend": now + days * DAY, "grace": 0,
        }
        store.save(self.tmp, {"token": mint.sign(claims, self.private),
                              "license_id": license_id,
                              "last_seen_utc": now})
        return licensing.reload()

    def make_lease(self, *, scopes=("core", "workflow", "boq"),
                   features=("core", "boq"), ttl=1800, offline=3600,
                   license_id="lic_t", dev=None, metered=False, now=None,
                   kid="t"):
        now = int(time.time()) if now is None else now
        claims = L.build_claims(
            kid=kid, license_id=license_id, device_fp=dev or self.device_fp,
            scope=list(scopes), features=list(features), metered=metered,
            jti="lse_test0001", now=now, ttl=ttl, offline=offline)
        return mint.sign_lease(claims, self.private), claims

    def install_lease(self, **kw):
        raw, claims = self.make_lease(**kw)
        A.remember(self.tmp, raw)
        return raw, claims


# ═══════════════════════════════════════════════════════════════════════════
# The lease format itself
# ═══════════════════════════════════════════════════════════════════════════
class LeaseVerification(LeaseHarness):

    def test_a_valid_lease_round_trips(self):
        raw, claims = self.make_lease()
        got = L.verify(raw, device_fp=self.device_fp,
                       public_keys={"t": self.public}, license_id="lic_t")
        self.assertEqual(got, claims)

    def test_b_a_flipped_byte_is_rejected(self):
        """B — modified lease payload → signature verification fails."""
        raw, _ = self.make_lease()
        head, payload, sig = raw.split(".")
        swapped = "X" if payload[10] != "X" else "Y"
        broken = f"{head}.{payload[:10]}{swapped}{payload[11:]}.{sig}"
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(broken, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertIn(ctx.exception.code, ("bad_signature", "malformed"))

    def test_c_widening_the_scope_breaks_the_signature(self):
        """C — editing the entitlement in the lease invalidates it.

        The obvious attack: keep the signature, add "reel" to the scope list.
        """
        raw, _ = self.make_lease(scopes=("core",))
        head, payload, sig = raw.split(".")
        claims = json.loads(T.b64u_decode(payload))
        claims["scope"] = ["core", "reel", "boq"]
        claims["feat"] = ["core", "reel", "boq"]
        forged = f"{head}.{L.encode_payload(claims)}.{sig}"
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(forged, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_c_clearing_the_metered_flag_breaks_the_signature(self):
        """`mtr` is what sends a quota'd client back to the server. Flipping
        it locally must not be a way to stop paying attention to a quota."""
        raw, _ = self.make_lease(metered=True)
        head, payload, sig = raw.split(".")
        claims = json.loads(T.b64u_decode(payload))
        claims["mtr"] = False
        forged = f"{head}.{L.encode_payload(claims)}.{sig}"
        with self.assertRaises(licensing.TokenError):
            L.verify(forged, device_fp=self.device_fp,
                     public_keys={"t": self.public})

    def test_d_a_lease_for_another_machine_is_rejected(self):
        """D — wrong device → authorisation denied."""
        raw, _ = self.make_lease(dev="ffffffffffffffff")
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(raw, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertEqual(ctx.exception.code, "wrong_device")

    def test_a_lease_for_another_licence_is_rejected(self):
        raw, _ = self.make_lease(license_id="lic_someone_else")
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(raw, device_fp=self.device_fp,
                     public_keys={"t": self.public}, license_id="lic_t")
        self.assertEqual(ctx.exception.code, "wrong_licence")

    def test_signed_by_another_key_is_rejected(self):
        other = Ed25519PrivateKey.generate()
        _, claims = self.make_lease()
        forged = mint.sign_lease(claims, other)
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(forged, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_a_licence_token_cannot_be_replayed_as_a_lease(self):
        """Both are Ed25519 over a base64 payload signed with the SAME key.
        Only the version prefix in the signing input keeps them apart."""
        self.install_token()
        licence_token = store.load(self.tmp)["token"]
        swapped = "PRSMLv1." + licence_token.split(".", 1)[1]
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(swapped, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertEqual(ctx.exception.code, "bad_signature")

    def test_a_lease_cannot_be_replayed_as_a_licence_token(self):
        raw, _ = self.make_lease()
        swapped = "PRSMv1." + raw.split(".", 1)[1]
        with self.assertRaises(licensing.TokenError):
            T.verify(swapped, device_fp=self.device_fp,
                     public_keys={"t": self.public})

    def test_a_future_payload_version_is_refused(self):
        """An old client must not silently ignore a claim it does not know —
        that is how a restricting change becomes a bypass."""
        _, claims = self.make_lease()
        claims["ver"] = L.VERSION + 1
        raw = mint.sign_lease(claims, self.private)
        with self.assertRaises(licensing.TokenError) as ctx:
            L.verify(raw, device_fp=self.device_fp,
                     public_keys={"t": self.public})
        self.assertEqual(ctx.exception.code, "version")

    def test_garbage_is_rejected_not_crashed(self):
        for junk in ("", "hello", "a.b", "PRSMLv1.!!!.!!!", "PRSMLv1.e30.zz",
                     "PRSMLv1..", "x" * 5000):
            with self.assertRaises(licensing.TokenError):
                L.verify(junk, device_fp=self.device_fp,
                         public_keys={"t": self.public})


# ═══════════════════════════════════════════════════════════════════════════
# The cache and the offline policy
# ═══════════════════════════════════════════════════════════════════════════
class LeaseCache(LeaseHarness):

    def test_the_cache_is_a_separate_file(self):
        self.install_token()
        self.install_lease()
        self.assertTrue(os.path.exists(A.path(self.tmp)))
        self.assertTrue(os.path.exists(store.path(self.tmp)))
        self.assertNotEqual(A.path(self.tmp), store.path(self.tmp))

    def test_the_cache_holds_a_signed_lease_not_a_boolean(self):
        """The single most important property of the file on disk."""
        self.install_token()
        self.install_lease()
        with open(A.path(self.tmp), "r", encoding="utf-8") as f:
            raw = f.read()
        self.assertIn("PRSMLv1.", raw)
        blob = json.loads(raw)
        self.assertNotIn("authorized", blob)
        self.assertNotIn("allowed", blob)
        # Nothing in the file is a decision — only the credential and two
        # diagnostic timestamps.
        self.assertEqual(set(blob) - {"lease", "fetched_at", "last_attempt"},
                         set())

    def test_writing_authorized_true_into_the_file_does_nothing(self):
        """J — a user editing the cache by hand must gain nothing."""
        self.install_token()
        store.write_json(A.path(self.tmp),
                         {"lease": "", "authorized": True, "plan": "complete"})
        lease_obj, state = licensing._read_lease()
        self.assertIsNone(lease_obj)
        self.assertEqual(state, A.NONE)
        self.assertFalse(A.decide(lease_obj, state, "core"))

    def test_a_tampered_cache_is_discarded_not_re_read(self):
        self.install_token()
        raw, _ = self.install_lease()
        head, payload, sig = raw.split(".")
        store.write_json(A.path(self.tmp),
                         {"lease": f"{head}.{payload}.{sig[:-4]}AAAA"})
        lease_obj, state = licensing._read_lease()
        self.assertEqual(state, A.TAMPERED)
        # Dropped, so the next call is a clean "no lease" rather than the same
        # failure re-litigated on every click.
        self.assertFalse(os.path.exists(A.path(self.tmp)))

    def test_fresh_grace_and_stale(self):
        self.install_token()
        now = int(time.time())

        _, claims = self.install_lease(ttl=1800, offline=3600)
        lease_obj, state = licensing._read_lease()
        self.assertEqual(state, A.FRESH)

        # Expired 60s ago, one hour of offline grace → GRACE.
        self.install_lease(ttl=-60, offline=3600)
        _, state = licensing._read_lease()
        self.assertEqual(state, A.GRACE)

        # Expired well past the offline window → STALE.
        self.install_lease(ttl=-7200, offline=3600)
        _, state = licensing._read_lease()
        self.assertEqual(state, A.STALE)

    def test_the_offline_window_is_signed_not_local(self):
        """Widening `off` by hand must break the lease, not extend it."""
        self.install_token()
        raw, _ = self.make_lease(ttl=-7200, offline=3600)
        head, payload, sig = raw.split(".")
        claims = json.loads(T.b64u_decode(payload))
        claims["off"] = 400 * DAY
        store.write_json(A.path(self.tmp),
                         {"lease": f"{head}.{L.encode_payload(claims)}.{sig}"})
        _, state = licensing._read_lease()
        self.assertEqual(state, A.TAMPERED)

    def test_deactivating_removes_the_lease(self):
        self.install_token()
        self.install_lease()
        store.clear(self.tmp)
        self.assertFalse(os.path.exists(A.path(self.tmp)))


class OfflinePolicy(LeaseHarness):

    def test_fresh_allows_without_the_server(self):
        self.install_token()
        _, state = self._lease(ttl=1800)
        d = A.decide(self._obj, state, "boq")
        self.assertTrue(d.allowed)
        self.assertFalse(d.needs_server)

    def test_g_grace_allows_while_the_server_is_down(self):
        """G — a temporary outage inside grace keeps a valid cache usable."""
        self.install_token()
        _, state = self._lease(ttl=-60, offline=3600)
        d = A.decide(self._obj, state, "boq", server_reachable=False)
        self.assertTrue(d.allowed)
        self.assertTrue(d.needs_server)     # …and keep trying in the background

    def test_l_stale_refuses_while_the_server_is_down(self):
        """L — past the offline window, protected work stops."""
        self.install_token()
        _, state = self._lease(ttl=-7200, offline=3600)
        d = A.decide(self._obj, state, "boq", server_reachable=False)
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "LEASE_STALE")

    def test_a_scope_not_granted_is_a_definite_no(self):
        """Not a reason to go to the network: the backend signs scopes from
        the same licence, so it would answer identically, slower."""
        self.install_token()
        _, state = self._lease(scopes=("core", "workflow"))
        d = A.decide(self._obj, state, "reel")
        self.assertFalse(d.allowed)
        self.assertEqual(d.code, "SCOPE_NOT_GRANTED")
        self.assertFalse(d.needs_server)

    def test_no_lease_asks_the_server(self):
        self.install_token()
        d = A.decide(None, A.NONE, "core")
        self.assertFalse(d.allowed)
        self.assertTrue(d.needs_server)
        self.assertEqual(d.code, "NO_LEASE")

    def _lease(self, **kw):
        self.install_lease(**kw)
        self._obj, state = licensing._read_lease()
        return self._obj, state


# ═══════════════════════════════════════════════════════════════════════════
# licensing.authorize() — the path every protected operation takes
# ═══════════════════════════════════════════════════════════════════════════
class AuthorizeFlow(LeaseHarness):

    def _no_network(self):
        """Both endpoints raise Unreachable. Patched at the client boundary,
        so a call that slipped past the lease would fail loudly rather than
        quietly hitting the real server."""
        return [
            mock.patch.object(client, "lease",
                              side_effect=client.Unreachable("no network")),
            mock.patch.object(client, "authorize",
                              side_effect=client.Unreachable("no network")),
        ]

    def test_a_fresh_lease_needs_no_network_at_all(self):
        """The headline behaviour: a protected operation with a valid lease
        does not touch HTTP."""
        self.install_token()
        self.install_lease(scopes=("core", "workflow", "boq"))
        with mock.patch.object(client, "lease") as lease_call, \
                mock.patch.object(client, "authorize") as auth_call:
            result = licensing.authorize("boq", "addon")
        self.assertTrue(result.allowed)
        self.assertEqual(result.state, A.FRESH)
        lease_call.assert_not_called()
        auth_call.assert_not_called()

    def test_g_an_outage_inside_grace_still_authorises(self):
        """G, end to end through the public API."""
        self.install_token()
        self.install_lease(ttl=-60, offline=3600)
        with self._no_network()[0], self._no_network()[1]:
            # "run": an add-on in GRACE no longer waits to find the server
            # down (GraceOpensAtOnce); a run still does, and says so.
            result = licensing.authorize("boq", "run")
        self.assertTrue(result.allowed)
        self.assertTrue(result.offline)
        # The add-on opens too; its background renewal is joined inside the
        # patches so it cannot reach the real client afterwards.
        licensing._renewal_thread = None
        with self._no_network()[0], self._no_network()[1]:
            self.assertTrue(licensing.authorize("boq", "addon").allowed)
            licensing._renewal_thread.join(10)

    def test_l_an_outage_past_the_window_refuses(self):
        """L — and says why, in words about the network rather than the
        licence. Telling a paying customer their licence ended because our
        host restarted is the failure this wording exists to prevent."""
        self.install_token()
        self.install_lease(ttl=-7200, offline=3600)
        with self._no_network()[0], self._no_network()[1]:
            result = licensing.authorize("boq", "addon")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "LEASE_STALE")
        self.assertIn("couldn't reach", result.message)
        self.assertNotIn("expired", result.message.lower())

    def test_f_an_expired_lease_triggers_a_refresh(self):
        """F — expired lease → the server is asked for a new one."""
        self.install_token()
        self.install_lease(ttl=-7200, offline=0)
        fresh, _ = self.make_lease(ttl=1800)
        with mock.patch.object(client, "lease",
                               return_value={"lease": fresh}) as lease_call:
            result = licensing.authorize("boq", "addon")
        self.assertTrue(result.allowed)
        lease_call.assert_called_once()
        # …and the new one was cached, so the next call is free.
        _, state = licensing._read_lease()
        self.assertEqual(state, A.FRESH)

    def test_a_metered_plan_always_asks_the_server(self):
        """A quota can only be counted where the counter lives."""
        self.install_token()
        self.install_lease(metered=True)
        fresh, _ = self.make_lease(metered=True)
        with mock.patch.object(
                client, "authorize",
                return_value={"run_id": "run_1", "lease": fresh}) as call:
            result = licensing.authorize("core", "plan")
        self.assertTrue(result.allowed)
        self.assertEqual(result.run_id, "run_1")
        call.assert_called_once()

    def test_an_unmetered_plan_uses_the_lease(self):
        self.install_token()
        self.install_lease(metered=False)
        with mock.patch.object(client, "authorize") as call:
            result = licensing.authorize("core", "plan")
        self.assertTrue(result.allowed)
        call.assert_not_called()
        # Still counted locally, so the admin console keeps its plan numbers.
        self.assertTrue(result.run_id.startswith("loc_"))
        self.assertTrue(any(e["kind"] == "plan"
                            for e in licensing.meter.drain()))

    def test_h_a_revoked_licence_gets_no_lease_and_loses_its_cache(self):
        """H — revoked → no new lease, and the cached one is dropped so the
        offline window cannot carry it any further."""
        self.install_token()
        self.install_lease(ttl=-60, offline=3600)     # would otherwise be GRACE
        refusal = client.ServerError("LICENSE_REVOKED",
                                     "This licence has been cancelled.")
        with mock.patch.object(client, "lease", side_effect=refusal):
            # "run": an add-on in GRACE opens at once and meets the
            # revocation on its NEXT open (GraceOpensAtOnce).
            result = licensing.authorize("boq", "run")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "LICENSE_REVOKED")
        self.assertFalse(os.path.exists(A.path(self.tmp)))
        # And a second attempt, now offline, cannot fall back on it.
        with self._no_network()[0], self._no_network()[1]:
            self.assertFalse(licensing.authorize("boq", "addon").allowed)

    def test_e_an_expired_licence_denies_protected_work(self):
        """E — expired licence → protected functionality denied even though a
        signed lease is sitting there in date."""
        self.install_token(days=-1)
        self.install_lease()
        self.assertEqual(licensing.state().status, licensing.EXPIRED)
        self.assertFalse(licensing.has("boq"))
        refusal = client.ServerError("LICENSE_EXPIRED",
                                     "This licence has ended.")
        with mock.patch.object(client, "lease", side_effect=refusal):
            self.assertFalse(licensing.authorize("boq", "addon").allowed)

    def test_a_client_too_old_refusal_is_surfaced(self):
        """Backend version enforcement reaches the customer as copy, not as a
        code — and does not become a licence problem in their head."""
        self.install_token()
        refusal = client.ServerError(
            "CLIENT_TOO_OLD",
            "This version of Prism is too old to start new work.")
        with mock.patch.object(client, "lease", side_effect=refusal):
            result = licensing.authorize("core", "run")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "CLIENT_TOO_OLD")

    def test_a_lease_the_server_sends_is_verified_before_being_cached(self):
        """A response is not evidence. Only a signature is."""
        self.install_token()
        other = Ed25519PrivateKey.generate()
        _, claims = self.make_lease()
        forged = mint.sign_lease(claims, other)
        with mock.patch.object(client, "lease", return_value={"lease": forged}):
            licensing.authorize("boq", "addon")
        self.assertFalse(A.load(self.tmp).get("lease"))

    def test_never_activated_is_refused_without_a_network_call(self):
        with mock.patch.object(client, "lease") as call:
            result = licensing.authorize("core", "run")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "NONE")
        call.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# An add-on opens at once from a lease in its offline window
# ═══════════════════════════════════════════════════════════════════════════
class GraceOpensAtOnce(LeaseHarness):
    """GRACE with the server ANSWERING. (With it down, G and L above already
    cover the open.) Nothing here waits on a sleep: a stub server blocks on an
    Event the test controls, and the renewal thread is joined."""

    WAIT = 10.0

    def setUp(self):
        super().setUp()
        licensing._renewal_thread = None
        self.install_token()

    def tearDown(self):
        join_licence_threads()
        licensing._renewal_thread = None
        super().tearDown()

    def _join_renewal(self):
        t = licensing._renewal_thread
        self.assertIsNotNone(t, "no background renewal was started")
        t.join(self.WAIT)
        self.assertFalse(t.is_alive(), "the renewal thread did not finish")

    def _blocking_server(self, answer):
        """A client.lease stand-in that records which thread called it, says
        when it was entered, and holds until the test lets it go."""
        calls, entered, release = [], threading.Event(), threading.Event()

        def lease(*_a, **_kw):
            calls.append(threading.current_thread())
            entered.set()
            release.wait(self.WAIT)
            if isinstance(answer, Exception):
                raise answer
            return answer

        return lease, calls, entered, release

    def _down(self):
        return [mock.patch.object(client, "lease",
                                  side_effect=client.Unreachable("down")),
                mock.patch.object(client, "authorize",
                                  side_effect=client.Unreachable("down"))]

    def test_grace_addon_opens_without_waiting_for_the_server(self):
        self.install_lease(ttl=-60, offline=3600)
        fresh, _ = self.make_lease(ttl=1800)
        lease, calls, entered, release = self._blocking_server(
            {"lease": fresh})
        started = time.monotonic()
        with mock.patch.object(client, "lease", side_effect=lease):
            result = licensing.authorize("boq", "addon")
            # The server has not been let go yet: if authorize() had waited
            # for it, it could not have returned before `release` is set.
            returned_while_server_blocked = not release.is_set()
            self.assertTrue(entered.wait(self.WAIT))
            release.set()
            self._join_renewal()
        self.assertTrue(returned_while_server_blocked)
        self.assertLess(time.monotonic() - started, self.WAIT)
        self.assertTrue(result.allowed)
        self.assertEqual(result.state, A.GRACE)
        self.assertTrue(result.run_id.startswith("loc_"))
        self.assertEqual(len(calls), 1)
        self.assertIsNot(calls[0], threading.current_thread())
        self.assertTrue(calls[0].daemon)
        # The renewal landed quietly: the NEXT open is a plain fresh one.
        self.assertEqual(licensing._read_lease()[1], A.FRESH)

    def test_grace_addon_starts_exactly_one_background_renewal(self):
        self.install_lease(ttl=-60, offline=3600)
        fresh, _ = self.make_lease(ttl=1800)
        lease, calls, entered, release = self._blocking_server(
            {"lease": fresh})
        with mock.patch.object(client, "lease", side_effect=lease):
            first = licensing.authorize("boq", "addon")
            self.assertTrue(entered.wait(self.WAIT))
            first_thread = licensing._renewal_thread
            # Two more clicks while the first renewal is still in flight.
            second = licensing.authorize("boq", "addon")
            third = licensing.authorize("boq", "addon")
            self.assertIs(licensing._renewal_thread, first_thread)
            release.set()
            self._join_renewal()
        self.assertTrue(first.allowed and second.allowed and third.allowed)
        self.assertEqual(len(calls), 1)

    def test_a_crashing_renewal_does_not_leave_it_in_flight(self):
        self.install_lease(ttl=-60, offline=3600)
        with mock.patch.object(licensing, "_refresh_lease_once",
                               side_effect=RuntimeError("boom")):
            self.assertTrue(licensing.authorize("boq", "addon").allowed)
            self._join_renewal()
        self.assertTrue(licensing._renewal_lock.acquire(blocking=False))
        licensing._renewal_lock.release()

    def test_grace_plan_still_goes_to_the_server(self):
        self.install_lease(ttl=-60, offline=3600)
        for action in ("plan", "run"):
            fresh, _ = self.make_lease(ttl=1800)
            with mock.patch.object(client, "lease",
                                   return_value={"lease": fresh}) as call:
                result = licensing.authorize("core", action)
            self.assertTrue(result.allowed, action)
            call.assert_called_once()
            self.assertIsNone(licensing._renewal_thread, action)
            self.install_lease(ttl=-60, offline=3600)   # back into GRACE
        # A metered plan asks the server's counter, not the lease.
        self.install_lease(ttl=-60, offline=3600, metered=True)
        fresh, _ = self.make_lease(metered=True)
        with mock.patch.object(
                client, "authorize",
                return_value={"run_id": "run_1", "lease": fresh}) as call:
            result = licensing.authorize("core", "plan")
        call.assert_called_once()
        self.assertEqual(result.run_id, "run_1")
        self.assertIsNone(licensing._renewal_thread)

    def test_grace_with_tampered_or_expired_token_does_not_take_the_fast_path(
            self):
        # Past the signed window: STALE, waits for the server as before.
        self.install_lease(ttl=-7200, offline=3600)
        fresh, _ = self.make_lease(ttl=1800)
        lease, calls, entered, release = self._blocking_server(
            {"lease": fresh})
        release.set()
        with mock.patch.object(client, "lease", side_effect=lease):
            result = licensing.authorize("boq", "addon")
        self.assertTrue(result.allowed)
        self.assertEqual(calls, [threading.current_thread()])
        self.assertIsNone(licensing._renewal_thread)
        # A lease whose signed window was widened by hand is TAMPERED, not
        # GRACE: it is dropped and the server is asked on this thread.
        raw, _ = self.make_lease(ttl=-7200, offline=3600)
        head, payload, sig = raw.split(".")
        claims = json.loads(T.b64u_decode(payload))
        claims["off"] = 400 * DAY
        store.write_json(A.path(self.tmp),
                         {"lease": f"{head}.{L.encode_payload(claims)}.{sig}"})
        calls.clear()
        with mock.patch.object(client, "lease", side_effect=lease):
            licensing.authorize("boq", "addon")
        self.assertEqual(calls, [threading.current_thread()])
        self.assertIsNone(licensing._renewal_thread)

    def test_background_revocation_refuses_the_next_open(self):
        self.install_lease(ttl=-60, offline=3600)
        refusal = client.ServerError("LICENSE_REVOKED", "Cancelled.")
        lease, _calls, _entered, release = self._blocking_server(refusal)
        release.set()
        with mock.patch.object(client, "lease", side_effect=lease):
            self.assertTrue(licensing.authorize("boq", "addon").allowed)
            self._join_renewal()
        self.assertFalse(os.path.exists(A.path(self.tmp)))
        # Cleared, so the offline window cannot carry the next open either.
        with self._down()[0], self._down()[1]:
            self.assertFalse(licensing.authorize("boq", "addon").allowed)

    def test_background_client_too_old_refuses_the_next_open(self):
        self.install_lease(ttl=-60, offline=3600)
        refusal = client.ServerError(
            "CLIENT_TOO_OLD", "Please update Prism.",
            {"min_supported_version": "99.0.0"})
        lease, _calls, _entered, release = self._blocking_server(refusal)
        release.set()
        with mock.patch.object(client, "lease", side_effect=lease):
            self.assertTrue(licensing.authorize("boq", "addon").allowed)
            self._join_renewal()
            self.assertFalse(os.path.exists(A.path(self.tmp)))
            nxt = licensing.authorize("boq", "addon")
        self.assertFalse(nxt.allowed)
        self.assertEqual(nxt.code, "CLIENT_TOO_OLD")
        # The floor is kept for the banner, as the foreground path does.
        self.assertEqual(store.load(self.tmp).get("min_supported_version"),
                         "99.0.0")

    def test_the_timer_path_keeps_the_lease_on_client_too_old(self):
        """Only the background renewal clears on CLIENT_TOO_OLD. The 10-minute
        timer calls _refresh_lease_once() with no argument: a floor raised by
        mistake must not take add-ons away mid-session, only at lease end."""
        self.install_lease(ttl=-60, offline=3600)
        A.save(self.tmp, {**A.load(self.tmp), "last_attempt": 1})
        refusal = client.ServerError(
            "CLIENT_TOO_OLD", "Please update Prism.",
            {"min_supported_version": "99.0.0"})
        with mock.patch.object(client, "lease", side_effect=refusal):
            self.assertFalse(licensing._refresh_lease_once())
        self.assertTrue(os.path.exists(A.path(self.tmp)))
        self.assertGreater(A.load(self.tmp)["last_attempt"], 1)
        self.assertEqual(store.load(self.tmp).get("min_supported_version"),
                         "99.0.0")

    def test_licence_refresh_keeps_the_lease_on_client_too_old(self):
        """The same, through licensing.refresh(): what main_window's
        10-minute licence timer actually calls."""
        self.install_lease(ttl=-60, offline=3600)
        refusal = client.ServerError(
            "CLIENT_TOO_OLD", "Please update Prism.",
            {"min_supported_version": "99.0.0"})
        with mock.patch.object(client, "refresh",
                               side_effect=client.Unreachable("down")), \
                mock.patch.object(client, "lease",
                                  side_effect=refusal) as lease:
            self.assertIsNone(licensing.refresh())
            join_licence_threads()
        lease.assert_called_once()
        self.assertTrue(os.path.exists(A.path(self.tmp)))
        self.assertEqual(licensing._read_lease()[1], A.GRACE)

    def test_renewed_lease_without_the_scope_is_refused(self):
        """A plan downgrade arrives as a narrower lease. The old lease that
        let this call through must not be the last word."""
        self.install_lease(ttl=-7200, offline=0,
                           scopes=("core", "workflow", "boq"))
        narrower, _ = self.make_lease(scopes=("core", "workflow"),
                                      features=("core",))
        with mock.patch.object(client, "lease",
                               return_value={"lease": narrower}):
            result = licensing.authorize("boq", "addon")
        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "FEATURE_NOT_LICENSED")

    def test_background_downgrade_refuses_the_next_open(self):
        self.install_lease(ttl=-60, offline=3600,
                           scopes=("core", "workflow", "boq"))
        narrower, _ = self.make_lease(scopes=("core", "workflow"),
                                      features=("core",))
        lease, _calls, _entered, release = self._blocking_server(
            {"lease": narrower})
        release.set()
        with mock.patch.object(client, "lease", side_effect=lease):
            self.assertTrue(licensing.authorize("boq", "addon").allowed)
            self._join_renewal()
            nxt = licensing.authorize("boq", "addon")
        self.assertFalse(nxt.allowed)
        self.assertEqual(nxt.code, "FEATURE_NOT_LICENSED")

    def test_lease_bearer_is_empty_in_grace(self):
        """The backend refuses a lease past `exp`; an empty bearer is what
        makes ai_server._auth renew before it spends."""
        self.install_lease(ttl=-60, offline=3600)
        self.assertEqual(licensing._read_lease()[1], A.GRACE)
        self.assertEqual(licensing.lease_bearer(), "")


# ═══════════════════════════════════════════════════════════════════════════
# The client is not the authority
# ═══════════════════════════════════════════════════════════════════════════
class ClientIsNotTheAuthority(LeaseHarness):

    def test_i_editing_plans_py_unlocks_nothing(self):
        """I — plans.py is presentation. The entitlement is in the signed
        token, and the scope is in the signed lease."""
        import plans

        self.install_token(features=("core",))
        self.install_lease(scopes=("core", "workflow"), features=("core",))

        original = plans.PLANS["studio"]
        try:
            # The most direct version of the attack: give every plan every
            # feature, locally.
            plans.PLANS["studio"] = plans.Plan(
                "studio", "Prism Studio", "everything",
                includes=tuple(plans.FEATURES))
            self.assertFalse(licensing.has("reel"))
            with mock.patch.object(client, "lease") as call:
                self.assertFalse(licensing.authorize("reel", "addon").allowed)
            # Denied from the signed scope alone — it did not even ask.
            call.assert_not_called()
        finally:
            plans.PLANS["studio"] = original

    def test_i_editing_the_plan_claim_in_the_token_invalidates_it(self):
        """"free" → "enterprise" in license.json must not unlock anything."""
        self.install_token(features=("core",))
        data = store.load(self.tmp)
        head, payload, sig = data["token"].split(".")
        claims = json.loads(T.b64u_decode(payload))
        claims["plan"] = "complete"
        claims["feat"] = list(__import__("plans").FEATURES)
        data["token"] = (f"{head}."
                         f"{T.b64u_encode(json.dumps(claims, separators=(',', ':'), sort_keys=True).encode())}"
                         f".{sig}")
        store.save(self.tmp, data)
        self.assertEqual(licensing.reload().status, licensing.TAMPERED)
        self.assertFalse(licensing.has("reel"))
        self.assertFalse(licensing.has("core"))

    def test_j_a_forged_lease_cannot_be_manufactured_locally(self):
        """J — the client can write anything into the cache; it cannot sign.

        This is the property the whole design rests on: without the private
        key, which exists only on the backend, every locally-made lease is
        rejected before a single field of it is read.
        """
        self.install_token()
        attacker = Ed25519PrivateKey.generate()
        claims = L.build_claims(
            kid="t", license_id="lic_t", device_fp=self.device_fp,
            scope=["core", "workflow", "reel", "grok"],
            features=["core", "reel", "grok"], metered=False,
            jti="lse_forged", now=int(time.time()), ttl=99 * DAY,
            offline=99 * DAY)
        store.write_json(A.path(self.tmp),
                         {"lease": mint.sign_lease(claims, attacker)})
        lease_obj, state = licensing._read_lease()
        self.assertIsNone(lease_obj)
        self.assertEqual(state, A.TAMPERED)

    def test_the_client_holds_no_private_key(self):
        """A public verification key is not a signing key. If this ever fails,
        someone has shipped the ability to mint licences."""
        for name in ("PRODUCTION", "DEVELOPMENT"):
            for kid, hexed in getattr(keys, name).items():
                # Ed25519 public keys are exactly 32 bytes. A 64-byte value
                # would be a private+public pair, and a PEM would be a private
                # key file — either would mean the build can mint licences.
                self.assertEqual(len(bytes.fromhex(hexed)), 32,
                                 f"{name}[{kid}] is not a 32-byte public key")
        # And nothing in the package holds private key material by any other
        # route. This catches a key pasted into a constant rather than a map.
        package = os.path.dirname(os.path.abspath(keys.__file__))
        for folder, _dirs, names in os.walk(package):
            for filename in names:
                if not filename.endswith(".py"):
                    continue
                with open(os.path.join(folder, filename), "r",
                          encoding="utf-8") as f:
                    body = f.read()
                self.assertNotIn("PRIVATE KEY", body,
                                 f"{filename} looks like it holds a private key")
                self.assertNotIn("Ed25519PrivateKey", body,
                                 f"{filename} can construct a signing key")

    def test_lease_bearer_is_empty_when_stale(self):
        """A stale lease must not be presented to a protected endpoint — the
        backend would reject it, but sending it invites a caller to treat
        "we have a string" as "we are authorised"."""
        self.install_token()
        self.install_lease(ttl=-7200, offline=3600)
        self.assertEqual(licensing.lease_bearer(), "")

    def test_lease_bearer_carries_the_raw_signed_lease(self):
        self.install_token()
        raw, _ = self.install_lease()
        self.assertEqual(licensing.lease_bearer(), raw)


# ═══════════════════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════════════════
class LocalFirstStartup(LeaseHarness):

    def test_a_and_k_state_is_computed_with_no_network(self):
        """A and K — a valid cached token resolves locally, and would do so
        with every network call fatal."""
        self.install_token()
        with mock.patch.object(client, "_post",
                               side_effect=AssertionError(
                                   "startup must not make a network call")):
            state = licensing.reload()
        self.assertEqual(state.status, licensing.VALID)
        self.assertTrue(licensing.has("boq"))

    def test_k_refresh_returns_immediately_and_never_raises(self):
        """K — a dead server at launch must cost nothing and surface nothing.

        refresh() hands the work to a daemon thread; the assertion is that the
        CALL returns without waiting on it, so the window is built while the
        request is still in flight.

        The thread is then joined INSIDE the patch, and that is not tidiness.
        Left running it outlived both the patch and this test, and this file's
        promise that "nothing in here can touch a network even by accident"
        was false for exactly one thread: by the time it reached client._post
        the patch had been undone, so it called the real licence server —
        /v1/refresh, then /v1/activate with the developer's own licence key,
        then /v1/lease.

        Worse than the traffic is where the answer lands. The thread re-reads
        licensing.user_dir() and keys.public_keys() at every step, and those
        are mock.patch globals belonging to whichever test is running when it
        gets there — eight modules and several seconds later, in practice
        test_gates.py::WindowGates. A successful refresh takes _apply(), which
        writes the server's real token into that test's temp ~/.prism and then
        reload()s. Verified against test_gates' throwaway public key the real
        token cannot verify, the licence reads TAMPERED, features go empty,
        and every add-on in the rail padlocks.

        That is the whole of the intermittent failure of
        WindowGates::test_sidebar_padlocks_what_is_not_owned and
        WindowGates::test_owned_addon_still_blocked_when_the_server_is_unreachable
        — about twice in ten full runs, never in isolation, and 2-in-10 only
        because the server's own rate limiter ("Too many attempts") turned
        most of those activations away.
        """
        self.install_token()
        started = time.monotonic()
        with mock.patch.object(client, "_post",
                               side_effect=client.Unreachable("down")):
            self.assertIsNone(licensing.refresh())
            elapsed = time.monotonic() - started
            # Inside the patch, so the thread answers from the stub, finishes
            # here, and never sees a socket or another test's user_dir.
            join_licence_threads()
        self.assertLess(elapsed, 0.5)

    def test_startup_survives_a_hostile_cache(self):
        """Every file the customer can edit, edited. The app must still reach
        a defined state rather than an exception."""
        for junk in ("", "{", "null", "[]", '{"token": 12}',
                     '{"token": "PRSMv1.x.y"}'):
            with open(store.path(self.tmp), "w", encoding="utf-8") as f:
                f.write(junk)
            self.assertIn(licensing.reload().status,
                          (licensing.NONE, licensing.TAMPERED))


# ═══════════════════════════════════════════════════════════════════════════
# Where the licence key is kept
# ═══════════════════════════════════════════════════════════════════════════
class KeyStorage(LeaseHarness):

    def test_without_a_keychain_it_falls_back_to_the_file(self):
        """Unchanged behaviour on a machine with no credential store — the
        point is that it still works, not that it is now secret."""
        where = store.save_key(self.tmp, "PRSM-AAAAA-BBBBB-CCCCC-DDDDD")
        self.assertEqual(where, licensing.secretstore.FILE)
        self.assertEqual(store.load_key(self.tmp),
                         "PRSM-AAAAA-BBBBB-CCCCC-DDDDD")

    def test_with_a_keychain_no_plaintext_is_written(self):
        vault: dict = {}

        class _FakeKeyring:
            @staticmethod
            def set_password(service, account, value):
                vault[(service, account)] = value

            @staticmethod
            def get_password(service, account):
                return vault.get((service, account))

            @staticmethod
            def delete_password(service, account):
                vault.pop((service, account), None)

        with mock.patch.object(licensing.secretstore, "_keyring",
                               return_value=_FakeKeyring):
            where = store.save_key(self.tmp, "PRSM-AAAAA-BBBBB-CCCCC-DDDDD")
            self.assertEqual(where, licensing.secretstore.KEYRING)
            # The whole point: nothing readable left on disk.
            self.assertEqual(store.load(self.tmp)["key"], "")
            with open(store.path(self.tmp), "r", encoding="utf-8") as f:
                self.assertNotIn("PRSM-AAAAA", f.read())
            self.assertEqual(store.load_key(self.tmp),
                             "PRSM-AAAAA-BBBBB-CCCCC-DDDDD")

    def test_an_upgrade_clears_the_plaintext_the_old_build_left(self):
        vault: dict = {}

        class _FakeKeyring:
            @staticmethod
            def set_password(s, a, v):
                vault[(s, a)] = v

            @staticmethod
            def get_password(s, a):
                return vault.get((s, a))

            @staticmethod
            def delete_password(s, a):
                vault.pop((s, a), None)

        # As an older Prism would have left it.
        store.save(self.tmp, {"key": "PRSM-OLDER-BUILD-WROTE-THIS"})
        with mock.patch.object(licensing.secretstore, "_keyring",
                               return_value=_FakeKeyring):
            store.save_key(self.tmp, "PRSM-OLDER-BUILD-WROTE-THIS")
        self.assertEqual(store.load(self.tmp)["key"], "")

    def test_deactivating_forgets_the_key(self):
        store.save_key(self.tmp, "PRSM-AAAAA-BBBBB-CCCCC-DDDDD")
        store.clear(self.tmp)
        self.assertEqual(store.load_key(self.tmp), "")


if __name__ == "__main__":
    unittest.main()

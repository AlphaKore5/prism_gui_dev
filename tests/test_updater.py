"""Tests for updater.py and the version advice that feeds it.

Phase 0 of update-plan.md: the licence server's `latest_version` and
`min_supported_version` — sent on every lease and authorize response, and
ignored by every client before 1.3.1 — reach LicenseState, survive a restart
with no network, and turn into advice the UI can draw. The banner itself is
covered in test_gates.py, which already owns a MainWindow harness.

No network anywhere: client._post is patched in every test that would reach
it, and the temp ~/.prism is thrown away. Plain unittest, like the rest.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app_meta
import flavour
import licensing
import updater
from licensing import client, device, keys, store
from licensing.status import LicenseState, newer, version_tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "devtools"))
import mint  # noqa: E402

DAY = 86400


# ═══════════════════════════════════════════════════════════════════════════
# Comparing versions
# ═══════════════════════════════════════════════════════════════════════════
class VersionCompare(unittest.TestCase):
    def test_numeric_not_lexical(self):
        """"1.10" is newer than "1.9". A string compare says the opposite,
        and that is the bug this helper exists to not have."""
        self.assertTrue(newer("1.10.0", "1.9.0"))
        self.assertFalse(newer("1.9.0", "1.10.0"))

    def test_equal_is_not_newer(self):
        self.assertFalse(newer("1.3.1", "1.3.1"))

    def test_prefix_and_suffix_are_tolerated(self):
        self.assertTrue(newer("v1.4.0", "1.3.1"))
        self.assertTrue(newer("1.4.0-beta", "1.3.1"))
        self.assertEqual(version_tuple("v1.10.2"), (1, 10, 2))

    def test_malformed_never_raises_and_never_advises(self):
        """The input is a string off the network. Unreadable means "no
        advice", never "update now" and never an exception in paint code."""
        for junk in ("", None, "latest", "..", "x.y.z", "🙂"):
            self.assertFalse(newer(junk, "1.3.1"), junk)
            self.assertFalse(newer("9.9.9", junk), junk)
        self.assertEqual(version_tuple("1.x"), (1,))
        self.assertEqual(version_tuple(None), ())

    def test_matches_the_server_parser(self):
        """The server's client_too_old() uses the same rule. If these drift,
        a client can think it is fine while the server refuses it."""
        self.assertEqual(version_tuple("1.10.2"), (1, 10, 2))
        self.assertEqual(version_tuple("1.2"), (1, 2))
        self.assertLess(version_tuple("1.2"), version_tuple("1.2.0"))


# ═══════════════════════════════════════════════════════════════════════════
# Shared harness: temp ~/.prism, throwaway key, no keyring, no network
# ═══════════════════════════════════════════════════════════════════════════
class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-updater-")
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        device.reset_cache()
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys",
                              return_value={"t": self.public}),
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

    def install_token(self, *, days=10):
        now = int(time.time())
        claims = {
            "kid": "t", "sub": "lic_t", "cust": "RS Infotech", "plan": "works",
            "kind": "paid", "feat": ["core"], "seats": 1,
            "dev": device.fingerprint(self.tmp)[0],
            "iat": now, "nbf": now, "exp": now + days * DAY,
            "lend": now + days * DAY, "grace": 0,
        }
        store.save(self.tmp, {"token": mint.sign(claims, self.private),
                              "license_id": "lic_t", "last_seen_utc": now})
        return licensing.reload()

    @staticmethod
    def answer(**fields):
        """A _post stub that answers every endpoint with the same dict."""
        return mock.patch.object(client, "_post", return_value=dict(fields))


# ═══════════════════════════════════════════════════════════════════════════
# The server's advice reaches the state, and stays there
# ═══════════════════════════════════════════════════════════════════════════
class ServerAdvice(Harness):
    def test_a_fresh_install_has_no_advice(self):
        state = self.install_token()
        self.assertEqual(state.latest_version, "")
        self.assertEqual(state.min_supported_version, "")
        self.assertEqual(updater.available(state), "")
        self.assertFalse(updater.required(state))

    def test_a_lease_answer_is_remembered(self):
        self.install_token()
        with self.answer(lease="", latest_version="9.9.9",
                         min_supported_version="1.0.0"):
            licensing.refresh(blocking=True)
        state = licensing.state()
        self.assertEqual(state.latest_version, "9.9.9")
        self.assertEqual(state.min_supported_version, "1.0.0")
        # Persisted beside the token, not just cached.
        self.assertEqual(store.load(self.tmp)["latest_version"], "9.9.9")

    def test_the_advice_survives_a_restart_with_no_network(self):
        """The banner is drawn at launch from the cached state. A dead
        server at that moment must not blank it."""
        self.install_token()
        with self.answer(latest_version="9.9.9"):
            licensing.refresh(blocking=True)
        with mock.patch.object(client, "_post", side_effect=AssertionError(
                "launch must not touch the network")):
            self.assertEqual(licensing.reload().latest_version, "9.9.9")

    def test_a_too_old_refusal_still_names_the_floor(self):
        """Once this build is below MIN_CLIENT_VERSION the ONLY thing
        /v1/lease will ever say to it is CLIENT_TOO_OLD. The floor rides in
        that refusal's detail; dropping it would leave the banner saying
        "can't reach the server" about a server that answered."""
        self.install_token()

        def refuse_leases(endpoint, body, **kw):
            if endpoint == "/v1/lease":
                raise client.ServerError(
                    "CLIENT_TOO_OLD", "Please update Prism.",
                    {"min_supported_version": "9.0.0",
                     "latest_version": "9.1.0"})
            return {}

        with mock.patch.object(client, "_post", side_effect=refuse_leases):
            licensing.refresh(blocking=True)
        state = licensing.state()
        self.assertEqual(state.min_supported_version, "9.0.0")
        self.assertTrue(updater.required(state))
        self.assertEqual(updater.target(state), "9.1.0")
        # The licence itself is untouched: the app still opens, History is
        # still there. Only the wording changes.
        self.assertEqual(state.status, licensing.VALID)

    def test_an_empty_value_withdraws_the_advice(self):
        """Clearing LATEST_CLIENT_VERSION on the server takes the banner
        down without a client release. That is how a bad release is pulled."""
        self.install_token()
        with self.answer(latest_version="9.9.9"):
            licensing.refresh(blocking=True)
        with self.answer(latest_version=""):
            licensing.refresh(blocking=True)
        self.assertEqual(licensing.state().latest_version, "")

    def test_a_missing_field_leaves_the_advice_alone(self):
        """An older server (or /v1/refresh, which never carries them) must
        not erase what a lease told us a minute ago."""
        self.install_token()
        with self.answer(latest_version="9.9.9"):
            licensing.refresh(blocking=True)
        with self.answer():
            licensing.refresh(blocking=True)
        self.assertEqual(licensing.state().latest_version, "9.9.9")

    def test_junk_from_the_server_is_harmless(self):
        self.install_token()
        with self.answer(latest_version=12, min_supported_version=None):
            licensing.refresh(blocking=True)          # must not raise
        state = licensing.state()
        self.assertEqual(state.latest_version, "")
        self.assertEqual(state.min_supported_version, "")
        self.assertEqual(updater.available(state), "")

    def test_a_hand_edited_value_can_only_change_wording(self):
        """license.json is user-writable. Writing a version into it makes the
        banner appear — and that is all it can ever do, because nothing here
        fetches or runs anything (see updater.py's docstring)."""
        self.install_token()
        store.update(self.tmp, latest_version="99.0.0")
        state = licensing.reload()
        self.assertEqual(updater.available(state), "99.0.0")
        self.assertTrue(updater.download_url().startswith("https://"))
        self.assertEqual(updater.download_url(), app_meta.DOWNLOAD_URL)

    # ── on_done ─────────────────────────────────────────────────────────────
    def test_on_done_runs_even_when_the_server_is_down(self):
        """"Check for updates" needs to stop saying "Checking…" whatever the
        server did — including not answering at all."""
        self.install_token()
        landed = []
        with mock.patch.object(client, "_post",
                               side_effect=client.Unreachable("down")):
            licensing.refresh(blocking=True, on_done=lambda: landed.append(1))
        self.assertEqual(landed, [1])

    def test_on_done_runs_on_the_worker_thread_and_is_awaited(self):
        self.install_token()
        done = threading.Event()
        with self.answer(latest_version="9.9.9"):
            self.assertIsNone(licensing.refresh(on_done=done.set))
            # Inside the patch, so the thread answers from the stub and never
            # sees a socket or another test's user_dir (see conftest.py).
            self.assertTrue(done.wait(10))
            self._join_refresh_thread()
        self.assertEqual(licensing.state().latest_version, "9.9.9")

    def test_a_broken_on_done_cannot_break_the_refresh(self):
        self.install_token()
        with self.answer(latest_version="9.9.9"):
            licensing.refresh(blocking=True, on_done=lambda: 1 / 0)
        self.assertEqual(licensing.state().latest_version, "9.9.9")

    @staticmethod
    def _join_refresh_thread(timeout: float = 10.0) -> None:
        for t in threading.enumerate():
            if t.name == "prism-license-refresh":
                t.join(timeout)


# ═══════════════════════════════════════════════════════════════════════════
# updater.py — advice against the running version, and "Not now"
# ═══════════════════════════════════════════════════════════════════════════
class Advice(Harness):
    def test_silence_is_not_advice(self):
        self.assertEqual(updater.available(LicenseState(), "1.3.1"), "")
        self.assertFalse(updater.required(LicenseState(), "1.3.1"))
        self.assertEqual(updater.target(LicenseState(), "1.3.1"), "")

    def test_available_only_when_strictly_newer(self):
        self.assertEqual(updater.available(
            LicenseState(latest_version="1.3.1"), "1.3.1"), "")
        self.assertEqual(updater.available(
            LicenseState(latest_version="1.2.9"), "1.3.1"), "")
        self.assertEqual(updater.available(
            LicenseState(latest_version="1.4.0"), "1.3.1"), "1.4.0")
        self.assertEqual(updater.available(
            LicenseState(latest_version=" 1.10.0 "), "1.9.0"), "1.10.0")

    def test_required_follows_the_floor(self):
        self.assertTrue(updater.required(
            LicenseState(min_supported_version="1.4.0"), "1.3.1"))
        self.assertFalse(updater.required(
            LicenseState(min_supported_version="1.3.1"), "1.3.1"))
        self.assertFalse(updater.required(
            LicenseState(min_supported_version="garbage"), "1.3.1"))

    def test_target_prefers_the_latest_then_the_floor(self):
        floor_only = LicenseState(min_supported_version="2.0.0")
        self.assertEqual(updater.target(floor_only, "1.0.0"), "2.0.0")
        both = LicenseState(min_supported_version="2.0.0",
                            latest_version="2.1.0")
        self.assertEqual(updater.target(both, "1.0.0"), "2.1.0")

    def test_defaults_to_the_running_build_and_cached_state(self):
        self.install_token()
        store.update(self.tmp, latest_version="99.0.0")
        licensing.reload()
        self.assertEqual(updater.available(), "99.0.0")
        self.assertEqual(updater.available(running="99.0.0"), "")

    def test_not_now_is_per_version(self):
        self.assertFalse(updater.dismissed("1.4.0"))
        updater.dismiss("1.4.0")
        self.assertTrue(updater.dismissed("1.4.0"))
        # The next release brings the banner back: "not now" meant that one.
        self.assertFalse(updater.dismissed("1.5.0"))
        updater.dismiss("1.5.0")
        self.assertFalse(updater.dismissed("1.4.0"))
        self.assertTrue(updater.dismissed("1.5.0"))

    def test_not_now_postpones_it_does_not_hide_the_update_for_good(self):
        """The banner's Download button used to vanish after "Not now" and
        never return (review finding 6, 2026-10-01)."""
        import time
        updater.dismiss("1.4.0")
        now = time.time()
        self.assertTrue(updater.dismissed("1.4.0", now=now + 60))
        self.assertTrue(updater.dismissed(
            "1.4.0", now=now + updater.DISMISS_FOR_SECONDS - 60))
        self.assertFalse(updater.dismissed(
            "1.4.0", now=now + updater.DISMISS_FOR_SECONDS + 60))

    def test_blank_versions_are_never_dismissed(self):
        updater.dismiss("")
        self.assertFalse(updater.dismissed(""))
        self.assertFalse(os.path.exists(updater.state_path()))

    def test_the_state_file_lives_beside_the_licence(self):
        updater.dismiss("1.4.0")
        self.assertTrue(updater.state_path().startswith(self.tmp))
        # One file per flavour beside the shared licence; "" for complete.
        root, ext = os.path.splitext(updater.STATE_FILENAME)
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp, root + flavour.file_suffix() + ext)))

    def test_a_corrupt_state_file_is_a_fresh_one(self):
        os.makedirs(self.tmp, exist_ok=True)
        for junk in ("", "{", "null", "[]", '{"dismissed": 7}'):
            with open(updater.state_path(), "w", encoding="utf-8") as f:
                f.write(junk)
            self.assertFalse(updater.dismissed("1.4.0"), junk)
        updater.dismiss("1.4.0")
        self.assertTrue(updater.dismissed("1.4.0"))

    def test_not_now_never_raises(self):
        """A full disk must not turn a dismiss click into a crash. The worst
        case is the banner coming back next launch."""
        with mock.patch.object(store, "write_json", side_effect=OSError):
            updater.dismiss("1.4.0")                  # must not raise
        self.assertFalse(updater.dismissed("1.4.0"))

    def test_the_download_address_is_fixed_and_https(self):
        self.assertTrue(updater.download_url().startswith("https://"))
        self.assertEqual(updater.download_url(), app_meta.DOWNLOAD_URL)


if __name__ == "__main__":
    unittest.main()


class PlatformChannel(unittest.TestCase):
    """The channel name is a contract with every binary already shipped.

    macOS moved to `macos-arm64-app` in 1.4.1 because a 1.4.0 Mac that found a
    manifest on the old name would gut its own bundle (updater.platform_tag()
    says why). Pinning the names here means changing one is a deliberate act
    with a failing test to explain, not a side effect of a refactor.
    """

    def _tag(self, sys_platform: str, machine: str) -> str:
        import updater
        with mock.patch.object(updater.sys, "platform", sys_platform), \
                mock.patch.object(updater.platform, "machine", return_value=machine):
            return updater.platform_tag()

    def test_macos_uses_the_bundle_channel(self):
        self.assertEqual(self._tag("darwin", "arm64"), "macos-arm64-app")

    def test_linux_and_windows_channels_are_unchanged(self):
        self.assertEqual(self._tag("linux", "x86_64"), "linux-x64")
        self.assertEqual(self._tag("win32", "AMD64"), "windows-x64")

    def _win_tag(self, built: str, machine: str) -> str:
        import updater
        with mock.patch.object(updater.sys, "platform", "win32"), \
                mock.patch.object(updater.sysconfig, "get_platform", return_value=built), \
                mock.patch.object(updater.platform, "machine", return_value=machine):
            return updater.platform_tag()

    def test_x64_build_on_windows_arm_stays_on_the_x64_channel(self):
        """Python 3.12 reports the HARDWARE (ARM64) to an emulated x64 build.
        The old lookup had no "ARM64" and asked for manifest.windows-ARM64."""
        self.assertEqual(self._win_tag("win-amd64", "ARM64"), "windows-x64")

    def test_native_arm64_build_gets_its_own_channel_in_lower_case(self):
        self.assertEqual(self._win_tag("win-arm64", "ARM64"), "windows-arm64")

    def test_machine_name_case_does_not_matter_off_windows(self):
        self.assertEqual(self._tag("linux", "ARM64"), "linux-arm64")

    def test_build_py_names_the_build_the_same_way(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "packaging"))
        import build
        for built, machine, want in (("win-amd64", "ARM64", "x64"),
                                     ("win-arm64", "ARM64", "arm64"),
                                     ("win-amd64", "AMD64", "x64")):
            with mock.patch.object(build, "IS_WIN", True), \
                    mock.patch.object(build.sysconfig, "get_platform", return_value=built), \
                    mock.patch.object(build.platform, "machine", return_value=machine):
                self.assertEqual(build._arch(), want, (built, machine))

    def test_release_all_publishes_to_the_same_names(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "devtools"))
        import release_all
        # Same three channel names as the updater; the ORDER is the release
        # order (Windows, Linux, macOS), set on purpose in release_all.py.
        self.assertEqual([p for p, _ in release_all.PLATFORMS],
                         ["windows-x64", "linux-x64", "macos-arm64-app"])

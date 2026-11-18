"""A person's activation must survive a reinstall, an update, a server that is
asleep and a dev build, and the screen that asks for a key must say why.

Owner complaint (Windows, dev builds 1.8.x, 2026-11-18): "Why does Prism ask for
my licence key every time? If I uninstall but do not delete .prism, it should
not ask. Whenever I am updating it, this happens."

Everything runs in a sandbox: a temp home, a throwaway signing key and a fake
licence server (client._post). Nothing here touches the real ~/.prism, the real
~/.prism-dev-home or the real OS keyring (conftest closes it).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "devtools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import channel
import licensing
from licensing import client, device, keys, secretstore, store
import mint  # noqa: E402

DAY = 86400
KEY = "PRSM-TZQ57-XJ8VA-9R60N-ZJZCG"


class FakeKeyring:
    vault: dict = {}

    @classmethod
    def set_password(cls, s, a, v):
        cls.vault[(s, a)] = v

    @classmethod
    def get_password(cls, s, a):
        return cls.vault.get((s, a))

    @classmethod
    def delete_password(cls, s, a):
        cls.vault.pop((s, a), None)


class FakeServer:
    """Stands in for client._post. `mode` is what the server is doing."""

    def __init__(self, harness):
        self.h = harness
        self.mode = "ok"
        self.calls: list[str] = []

    def __call__(self, endpoint, body, *, app_version, timeout=None, retries=0):
        self.calls.append(endpoint)
        if self.mode == "down":
            raise client.Unreachable("no route to host")
        if self.mode == "asleep":
            raise client.Unreachable("read timed out")
        if self.mode == "5xx":
            raise client.ServerError("http_503", "The service is starting up.")
        if self.mode == "revoked":
            raise client.ServerError("LICENSE_REVOKED", "This licence was revoked.")
        if endpoint in ("/v1/activate", "/v1/refresh"):
            return {"token": self.h.token_for(body["device_fp"]),
                    "license_id": "lic_t"}
        return {}


class Harness(unittest.TestCase):
    """A temp home, a throwaway key, a fake server, no network, no real keyring."""

    keyring = None            # a test that wants a keyring sets FakeKeyring

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="prism-persist-")
        self.addCleanup(shutil.rmtree, self.home, True)
        self.tmp = os.path.join(self.home, ".prism")
        os.makedirs(self.tmp)
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        FakeKeyring.vault = {}
        device.reset_cache()
        self.server = FakeServer(self)
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys", return_value={"t": self.public}),
            mock.patch.object(client, "_post", self.server),
            mock.patch.object(secretstore, "_keyring",
                              return_value=FakeKeyring if self.keyring else None),
            mock.patch("time.sleep"),           # no real waiting in any retry loop
        ]
        for p in self.patches:
            p.start()
        licensing.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    def token_for(self, device_fp, *, exp_in=3600, lend_in=30 * DAY):
        now = int(time.time())
        claims = {"kid": "t", "sub": "lic_t", "cust": "RS Infotech", "plan": "works",
                  "kind": "paid", "feat": ["core", "boq"], "seats": 1, "dev": device_fp,
                  "iat": now, "nbf": now - 1, "exp": now + exp_in,
                  "lend": now + lend_in, "grace": 0}
        return mint.sign(claims, self.private)

    @property
    def fp(self):
        return device.fingerprint(self.tmp)[0]

    def activate(self):
        return licensing.activate(KEY)

    def snapshot(self, folder=None):
        folder = folder or self.tmp
        out = {}
        for root, _, files in os.walk(folder):
            for n in files:
                p = os.path.join(root, n)
                with open(p, "rb") as f:
                    out[os.path.relpath(p, folder)] = hashlib.sha256(f.read()).hexdigest()
        return out


# ═══════════════════════════════════════════════════════════════════════════
# (a)(b) activate, then reinstall: same home, nothing asked
# ═══════════════════════════════════════════════════════════════════════════
class ReinstallKeepsTheActivation(Harness):
    def test_activation_then_a_new_process_with_the_same_home_is_valid(self):
        self.assertEqual(self.activate().status, licensing.VALID)
        # A different process: no caches, no shared Python state.
        script = (
            "import sys; sys.path.insert(0, %r); import licensing\n"
            "from licensing import keys\n"
            "keys.public_keys = lambda: {'t': %r}\n"
            "print(licensing.state().status)\n") % (ROOT, self.public)
        env = {**os.environ, "HOME": self.home, "USERPROFILE": self.home,
               "QT_QPA_PLATFORM": "offscreen"}
        env.pop("PRISM_HOME", None)
        out = subprocess.run([sys.executable, "-I", "-c", script], env=env,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip().splitlines()[-1:], ["valid"], out.stderr[-400:])

    def test_a_reinstalled_app_folder_changes_nothing_in_the_home(self):
        self.activate()
        before = self.snapshot()
        app = os.path.join(self.home, "apps", "Prism")
        os.makedirs(app)
        shutil.rmtree(app)                       # "uninstall": the program folder goes
        os.makedirs(app)                         # "reinstall": a fresh one
        device.reset_cache()
        self.assertEqual(licensing.reload().status, licensing.VALID)
        self.assertEqual(self.snapshot(), before)


# ═══════════════════════════════════════════════════════════════════════════
# (c) the update swap never reaches ~/.prism
# ═══════════════════════════════════════════════════════════════════════════
class TheUpdateSwapLeavesTheHomeAlone(Harness):
    def test_perform_swap_touches_only_the_install_staging_and_backup_folders(self):
        import apply_update
        self.activate()
        before = self.snapshot(self.home)
        root = tempfile.mkdtemp(prefix="prism-swap-")
        self.addCleanup(shutil.rmtree, root, True)
        install, staged, backup = (os.path.join(root, n) for n in ("Prism", "staged", "Prism.old"))
        for d, marker in ((install, "old"), (staged, "new")):
            os.makedirs(d)
            with open(os.path.join(d, "Prism.exe"), "w") as f:
                f.write(marker)
        apply_update.perform_swap(install, staged, backup, retry_seconds=5.0, retry_interval=0.01)
        with open(os.path.join(install, "Prism.exe")) as f:
            self.assertEqual(f.read(), "new")
        self.assertEqual(self.snapshot(self.home), before)
        self.assertEqual(licensing.reload().status, licensing.VALID)

    def test_the_windows_update_script_deletes_only_its_own_folders(self):
        """Every delete in apply.bat names the backup, the staging folder or the
        version note, never the data folder."""
        import apply_update
        with mock.patch.object(apply_update, "_windows_helper_dir", return_value=self.tmp):
            script = apply_update.write_windows_helper(
                4242, r"C:\Apps\Prism", r"C:\Apps\.prism-update-staging\x",
                r"C:\Apps\Prism.old", r"C:\Apps\Prism\Prism.exe")
        with open(script, encoding="utf-8") as f:
            text = f.read()
        deletes = [ln for ln in text.splitlines()
                   if re.match(r"\s*(if exist .*)?\b(rmdir|rd|del|erase)\b", ln, re.I)]
        self.assertTrue(deletes)
        for ln in deletes:
            self.assertNotRegex(ln, r"\.prism(-dev-home)?\b(?!-update)", ln)
            self.assertNotIn("license", ln.lower())

    def test_app_only_uninstall_never_lists_either_data_folder(self):
        import uninstall as U
        base = tempfile.mkdtemp(prefix="prism-uninst-")
        self.addCleanup(shutil.rmtree, base, True)
        install = os.path.join(base, "Apps", "Prism")
        os.makedirs(install)
        exe = os.path.join(install, "Prism")
        open(exe, "w").close()
        data = os.path.join(base, "home", ".prism")
        dev = os.path.join(base, "home", ".prism-dev-home")
        for d in (data, dev):
            os.makedirs(d)
            open(os.path.join(d, "license.json"), "w").write("{}")
        plan = U.build_plan(U.SCOPE_APP, frozen=True, executable=exe, data_dir=data,
                            home=os.path.join(base, "home"), platform="darwin")
        listed = " ".join(plan.everything())
        self.assertNotIn(".prism", listed.replace(".prism-update", "").replace(".prism_update", ""))
        self.assertFalse(plan.forget_licence)


# ═══════════════════════════════════════════════════════════════════════════
# (d) where the key lives, and silent re-activation
# ═══════════════════════════════════════════════════════════════════════════
class SilentReactivation(Harness):
    keyring = True

    def _lose_the_licence_file(self):
        os.unlink(store.path(self.tmp))
        return licensing.reload()

    def test_key_in_the_keyring_only_brings_the_licence_back_without_typing(self):
        self.activate()
        self.assertEqual(store.load(self.tmp)["key"], "")        # file holds no key
        self.assertEqual(self._lose_the_licence_file().status, licensing.NONE)
        self.assertTrue(licensing.has_saved_key())
        self.assertEqual(licensing.reactivate_from_saved_key(), ("ok", ""))
        self.assertEqual(licensing.state().status, licensing.VALID)

    def test_key_in_the_file_only_brings_the_licence_back(self):
        with mock.patch.object(secretstore, "_keyring", return_value=None):
            self.activate()
            self.assertEqual(store.load(self.tmp)["key_location"], "file")
            store.update(self.tmp, token="", license_id="")      # token lost, key kept
            licensing.reload()
            self.assertEqual(licensing.reactivate_from_saved_key(), ("ok", ""))
        self.assertEqual(licensing.state().status, licensing.VALID)

    def test_no_key_anywhere_asks_and_never_calls_the_server(self):
        with mock.patch.object(secretstore, "_keyring", return_value=None):
            self.assertFalse(licensing.has_saved_key())
            self.assertEqual(licensing.reactivate_from_saved_key()[0], "no_key")
        self.assertEqual(self.server.calls, [])

    def test_a_definitive_no_is_reported_in_the_servers_words(self):
        self.activate()
        self._lose_the_licence_file()
        self.server.mode = "revoked"
        outcome, words = licensing.reactivate_from_saved_key()
        self.assertEqual((outcome, words), ("refused", "This licence was revoked."))

    def test_a_server_that_does_not_answer_is_not_a_no(self):
        self.activate()
        self._lose_the_licence_file()
        for mode in ("down", "asleep"):
            self.server.mode = mode
            outcome, words = licensing.reactivate_from_saved_key()
            self.assertEqual(outcome, "unreachable")
            self.assertIn("still on this computer", words)
        self.assertTrue(licensing.has_saved_key())      # the key is not thrown away

    def test_deactivating_still_forgets_the_key_so_it_does_not_come_back(self):
        self.activate()
        licensing.deactivate()
        self.assertFalse(licensing.has_saved_key())


# ═══════════════════════════════════════════════════════════════════════════
# (e) a dev build with an empty dev home, the normal Prism already activated
# ═══════════════════════════════════════════════════════════════════════════
class DevBuildAdoption(Harness):
    def setUp(self):
        super().setUp()
        # The "normal Prism" folder, activated for this very computer.
        self.real_home = tempfile.mkdtemp(prefix="prism-real-")
        self.addCleanup(shutil.rmtree, self.real_home, True)
        self.real = os.path.join(self.real_home, ".prism")
        os.makedirs(self.real)
        store.save(self.real, {"token": self.token_for(self.fp), "license_id": "lic_t",
                               "key": KEY, "key_location": "file",
                               "last_seen_utc": int(time.time())})
        with open(os.path.join(self.real, "authorization.json"), "w") as f:
            f.write("{}")
        with open(os.path.join(self.real, "config.json"), "w") as f:
            f.write('{"theme": "do not copy"}')
        for p in (mock.patch.object(channel, "CHANNEL", "dev"),
                  mock.patch.dict(os.environ, {"PRISM_REAL_HOME": self.real_home})):
            p.start()
            self.addCleanup(p.stop)
        licensing.reload()

    def test_the_dev_home_starts_empty_and_asks_for_a_key_today(self):
        self.assertEqual(licensing.state().status, licensing.NONE)
        self.assertEqual(licensing.state().reason, "absent")

    def test_it_is_offered_and_adopting_copies_the_licence_read_only(self):
        before = self.snapshot(self.real)
        self.assertEqual(licensing.adoptable_licence_folder(), self.real)
        ok, _ = licensing.adopt_real_licence()
        self.assertTrue(ok)
        self.assertEqual(licensing.state().status, licensing.VALID)
        self.assertEqual(self.snapshot(self.real), before, "the normal Prism must be untouched")
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "authorization.json")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "config.json")),
                         "settings stay separate; only the licence moves")
        self.assertEqual(licensing.adoptable_licence_folder(), "", "offered once")

    def test_it_is_never_offered_to_a_production_build(self):
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertEqual(licensing.adoptable_licence_folder(), "")

    def test_a_licence_for_another_computer_is_not_offered(self):
        store.save(self.real, {"token": self.token_for("ffffffffffffffff"),
                               "license_id": "lic_t"})
        self.assertEqual(licensing.adoptable_licence_folder(), "")
        self.assertFalse(licensing.adopt_real_licence()[0])

    def test_an_existing_dev_licence_is_never_overwritten(self):
        self.activate()
        mine = self.snapshot()
        self.assertEqual(licensing.adoptable_licence_folder(), "")
        self.assertFalse(licensing.adopt_real_licence()[0])
        self.assertEqual(self.snapshot(), mine)

    def test_a_failed_adoption_is_undone(self):
        real_replace = os.replace

        def fail_on_license(src, dst):
            if os.path.basename(dst) == "license.json":
                raise OSError("disk full")
            return real_replace(src, dst)

        with mock.patch("os.replace", fail_on_license):
            ok, words = licensing.adopt_real_licence()
        self.assertFalse(ok)
        self.assertEqual(licensing.state().status, licensing.NONE)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "authorization.json")))


# ═══════════════════════════════════════════════════════════════════════════
# (f) a refresh that fails must never become "enter your key"
# ═══════════════════════════════════════════════════════════════════════════
class ARefreshThatFailsNeverDowngrades(Harness):
    def _fresh(self):
        self.activate()
        return self.snapshot()

    def test_every_non_answer_leaves_the_licence_exactly_as_it_was(self):
        before = self._fresh()
        for mode in ("down", "asleep", "5xx"):
            with self.subTest(mode=mode):
                self.server.mode = mode
                st = licensing._refresh_once()
                licensing._refresh_lease_once()
                self.assertEqual(st.status, licensing.VALID)
                self.assertEqual(licensing.reload().status, licensing.VALID)
        after = self.snapshot()
        before.pop("authorization.json", None)
        after.pop("authorization.json", None)
        self.assertEqual({k: v for k, v in after.items() if k == "license.json"},
                         {k: v for k, v in before.items() if k == "license.json"})

    def test_a_token_past_its_hour_with_the_server_down_is_stale_and_usable(self):
        store.save(self.tmp, {"token": self.token_for(self.fp, exp_in=-3 * 3600),
                              "license_id": "lic_t", "last_seen_utc": int(time.time())})
        self.server.mode = "asleep"
        st = licensing.reload()
        self.assertEqual(st.status, licensing.STALE)
        self.assertTrue(st.usable)
        licensing._refresh_once()
        self.assertEqual(licensing.reload().status, licensing.STALE)
        self.assertTrue(licensing.state().usable)

    def test_a_week_offline_is_stale_not_none_so_no_key_box(self):
        store.save(self.tmp, {"token": self.token_for(self.fp, exp_in=-9 * DAY),
                              "license_id": "lic_t", "last_seen_utc": int(time.time())})
        st = licensing.reload()
        self.assertEqual(st.status, licensing.STALE)
        self.assertFalse(st.usable)

    def _gate(self, state_status):
        """Run main._licence_gate and report which dialogs it built."""
        import main
        built = []

        class Dialog:
            def __init__(self, parent=None, mode="activate"):
                built.append(mode)

            def exec(self):
                return 0

        with mock.patch("dialogs.license_dialog.LicenseDialog", Dialog), \
                mock.patch.object(licensing, "refresh"), \
                mock.patch.object(licensing, "apply_cached_payload", return_value=0):
            result = main._licence_gate()
        return result, built

    def test_the_start_up_gate_shows_no_key_box_for_a_stale_licence(self):
        store.save(self.tmp, {"token": self.token_for(self.fp, exp_in=-9 * DAY),
                              "license_id": "lic_t", "last_seen_utc": int(time.time())})
        licensing.reload()
        result, built = self._gate(licensing.STALE)
        self.assertTrue(result)
        self.assertEqual(built, [])

    def test_the_start_up_gate_shows_no_key_box_for_a_valid_licence(self):
        self.activate()
        result, built = self._gate(licensing.VALID)
        self.assertTrue(result)
        self.assertEqual(built, [])

    def test_a_licence_file_locked_for_a_few_seconds_is_waited_for(self):
        self.activate()
        real_open = open
        state = {"fails": 0}

        def locked_then_free(path, *a, **k):
            if str(path).endswith("license.json") and state["fails"] < 9:
                state["fails"] += 1
                raise PermissionError(13, "held by the scanner")
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", locked_then_free), \
                mock.patch.object(store, "_log_read_failure"):
            st = licensing.reload()
        self.assertEqual(st.status, licensing.VALID)
        self.assertGreaterEqual(state["fails"], 9)

    def test_a_licence_file_that_stays_locked_says_so_and_offers_try_again(self):
        self.activate()
        real_open = open

        def locked(path, *a, **k):
            if str(path).endswith("license.json"):
                raise PermissionError(13, "held by the scanner")
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", locked), \
                mock.patch.object(store, "_log_read_failure"):
            st = licensing.reload()
        self.assertEqual((st.status, st.reason), (licensing.NONE, "unreadable"))
        self.assertTrue(licensing.can_retry(st))
        words = licensing.why_activation(st)
        self.assertIn(self.tmp, words)
        self.assertIn("try again", words.lower())

    def test_only_a_missing_file_skips_the_wait(self):
        os.unlink(store.path(self.tmp)) if os.path.exists(store.path(self.tmp)) else None
        with mock.patch("time.sleep") as nap:
            licensing.reload()
        nap.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# why the screen appears
# ═══════════════════════════════════════════════════════════════════════════
class TheScreenSaysWhy(Harness):
    def test_no_licence_names_the_folder_it_looked_in(self):
        st = licensing.reload()
        self.assertEqual(st.reason, "absent")
        self.assertIn(f"No licence was found in {self.tmp}", licensing.why_activation(st))

    def test_a_dev_build_says_it_keeps_its_own_folder(self):
        with mock.patch.object(channel, "CHANNEL", "dev"):
            words = licensing.why_activation(licensing.reload())
        self.assertIn("development build", words)

    def test_a_deactivated_file_is_described_as_such(self):
        self.activate()
        store.update(self.tmp, token="", license_id="")
        st = licensing.reload()
        self.assertEqual(st.reason, "empty")
        self.assertIn("deactivated", licensing.why_activation(st))

    def test_another_computers_licence_is_named_as_that(self):
        store.save(self.tmp, {"token": self.token_for("ffffffffffffffff"),
                              "license_id": "lic_t"})
        st = licensing.reload()
        self.assertEqual((st.status, st.reason), (licensing.TAMPERED, "wrong_device"))
        self.assertIn("different computer", licensing.why_activation(st))

    def test_a_wrong_clock_keeps_its_own_words(self):
        self.activate()
        store.update(self.tmp, last_seen_utc=int(time.time()) + 40 * DAY)
        st = licensing.reload()
        self.assertEqual(st.reason, "clock")
        self.assertIn("date and time", licensing.why_activation(st))


class TheStartUpLogLine(Harness):
    keyring = True

    def test_it_names_folder_files_and_where_the_key_is_but_holds_no_secret(self):
        self.activate()
        store.update(self.tmp, token="")
        st = licensing.reload()
        line = licensing.diagnostics_line(st)
        for needle in (self.tmp, "license.json(", "key_location=keyring",
                       "keyring_available=yes", "key_in_keyring=yes",
                       "key_in_file=no", "token_status=none"):
            self.assertIn(needle, line)
        data = store.load(self.tmp)
        for secret in (KEY, KEY.replace("-", ""), str(data.get("token") or "x" * 9)):
            self.assertNotIn(secret, line)

    def test_main_writes_it_when_the_screen_will_show(self):
        import main
        st = licensing.reload()
        with mock.patch("diagnostics.write") as write:
            main._log_gate(st)
        write.assert_called_once()
        self.assertIn("licence screen will show", write.call_args[0][1])
        self.assertIn(self.tmp, write.call_args[0][1])

    def test_main_writes_nothing_for_a_working_licence(self):
        import main
        self.activate()
        with mock.patch("diagnostics.write") as write:
            main._log_gate(licensing.reload())
        write.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# the dialog
# ═══════════════════════════════════════════════════════════════════════════
class TheDialog(Harness):
    keyring = True

    def setUp(self):
        super().setUp()
        from PySide6.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([])

    def _dialog(self, mode="activate"):
        from dialogs import license_dialog as LD
        return LD.LicenseDialog(mode=mode)

    def test_it_says_why_and_where_it_looked(self):
        d = self._dialog()
        self.assertIn(self.tmp, d.why_label.text())
        self.assertFalse(d.why_box.isHidden())

    def test_a_saved_key_is_tried_before_anyone_is_asked(self):
        self.activate()
        os.unlink(store.path(self.tmp))
        licensing.reload()
        d = self._dialog()
        d._look_for_saved_licence()
        d._worker.wait(10000)
        d._worker.run() if d._worker.isRunning() else None
        with mock.patch.object(d, "accept") as accept:
            d._on_saved_key(*licensing.reactivate_from_saved_key())
        accept.assert_called_once()
        self.assertEqual(licensing.state().status, licensing.VALID)

    def test_a_server_that_is_asleep_shows_try_again_and_keeps_the_key_box(self):
        self.activate()
        os.unlink(store.path(self.tmp))
        licensing.reload()
        self.server.mode = "asleep"
        d = self._dialog()
        d._on_saved_key(*licensing.reactivate_from_saved_key())
        self.assertFalse(d.retry_btn.isHidden())
        self.assertIn("Try again", d.saved_label.text())
        self.assertTrue(d.key_edit.isEnabled())

    def test_a_revoked_licence_says_so_and_offers_no_retry(self):
        self.activate()
        os.unlink(store.path(self.tmp))
        licensing.reload()
        self.server.mode = "revoked"
        d = self._dialog()
        d._on_saved_key(*licensing.reactivate_from_saved_key())
        self.assertIn("This licence was revoked.", d.saved_label.text())
        self.assertTrue(d.retry_btn.isHidden())

    def test_a_wrong_clock_does_not_try_the_saved_key(self):
        self.activate()
        store.update(self.tmp, last_seen_utc=int(time.time()) + 40 * DAY)
        licensing.reload()
        d = self._dialog(mode="problem")
        with mock.patch.object(licensing, "has_saved_key") as saved:
            d._look_for_saved_licence()
        saved.assert_not_called()

    def test_nothing_secret_is_pre_filled(self):
        self.activate()
        os.unlink(store.path(self.tmp))
        licensing.reload()
        self.assertEqual(self._dialog().key_edit.text(), "")

    def test_the_dev_offer_is_a_button_that_adopts(self):
        real_home = tempfile.mkdtemp(prefix="prism-real-")
        self.addCleanup(shutil.rmtree, real_home, True)
        real = os.path.join(real_home, ".prism")
        os.makedirs(real)
        store.save(real, {"token": self.token_for(self.fp), "license_id": "lic_t"})
        with mock.patch.object(channel, "CHANNEL", "dev"), \
                mock.patch.dict(os.environ, {"PRISM_REAL_HOME": real_home}):
            licensing.reload()
            d = self._dialog()
            self.assertFalse(d.adopt_btn.isHidden())
            with mock.patch.object(d, "accept") as accept:
                d._adopt()
            accept.assert_called_once()
        self.assertEqual(licensing.state().status, licensing.VALID)

    def test_the_stale_banner_offers_try_again_not_a_key(self):
        import inspect
        import main_window
        src = inspect.getsource(main_window.MainWindow.refresh_licence_ui)
        stale = src[src.index("elif state.status == licensing.STALE:"):
                    src.index("elif state.status == licensing.GRACE:")]
        self.assertIn('"Try again"', stale)


# ═══════════════════════════════════════════════════════════════════════════
# (g) the packaged app really can use the OS credential store
# ═══════════════════════════════════════════════════════════════════════════
class ThePackagedKeyring(unittest.TestCase):
    def _spec(self):
        with open(os.path.join(ROOT, "packaging", "prism.spec"), encoding="utf-8") as f:
            return f.read()

    def test_the_spec_bundles_every_keyring_backend(self):
        self.assertIn('collect_submodules("keyring")', self._spec())

    def test_keyring_is_a_real_requirement_so_the_build_has_it(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
            lines = [ln.strip() for ln in f]
        self.assertIn("keyring", lines)

    def test_pyinstallers_own_hook_copies_the_metadata_backends_are_found_by(self):
        try:
            import PyInstaller
        except ImportError:
            self.skipTest("PyInstaller is not installed in this environment")
        hook = os.path.join(os.path.dirname(PyInstaller.__file__), "hooks", "hook-keyring.py")
        with open(hook, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("copy_metadata('keyring')", text)
        self.assertIn("collect_submodules('keyring.backends')", text)

    def test_with_no_backend_the_key_goes_to_the_file_and_still_comes_back(self):
        tmp = tempfile.mkdtemp(prefix="prism-nokr-")
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(secretstore, "_keyring", return_value=None):
            self.assertEqual(store.save_key(tmp, KEY), secretstore.FILE)
            self.assertEqual(store.load_key(tmp), KEY)


if __name__ == "__main__":
    unittest.main()

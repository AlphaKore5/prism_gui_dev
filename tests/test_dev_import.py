"""dev_import.py: a development build is a brand-new install (own data folder),
so testers lose their Groq key, browser logins, folders and History and read it
as bugs (RELEASE_ISSUES.md ISS-012). This copies those across, read-only on the
normal Prism, and never copies the licence or update state."""
import hashlib
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import channel  # noqa: E402
import dev_import as D  # noqa: E402

_app = QApplication.instance() or QApplication([])


def digest(root):
    out = {}
    for d, _dirs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            out[os.path.relpath(p, root)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    return out


class Rooms(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="devimport-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = os.path.join(self.tmp, "real", ".prism")
        self.dst = os.path.join(self.tmp, "real", ".prism-dev-home", ".prism")
        os.makedirs(os.path.join(self.src, "chrome_profile", "Default"))
        os.makedirs(os.path.join(self.src, "runs"))
        os.makedirs(os.path.join(self.src, "tools"))
        files = {
            "config.json": '{"api_key": "gsk_real", "inquiry_folder": "/work"}',
            "gui_favorites.json": "[]", "license.json": "SECRET-LICENCE", "authorization.json": "AUTH",
            "device_id": "device-123", "update_state.json": '{"highest": "1.6.10"}',
            os.path.join("chrome_profile", "Default", "Cookies"): "cookies",
            os.path.join("chrome_profile", "SingletonLock"): "lock",
            os.path.join("runs", "r1.json"): "{}", os.path.join("tools", "ffmpeg"): "bin",
        }
        for name, body in files.items():
            open(os.path.join(self.src, name), "w").write(body)


class Copying(Rooms):
    def test_the_normal_prism_is_never_changed(self):
        before = digest(self.src)
        D.copy(list(D.CHOICES), self.src, self.dst)
        self.assertEqual(digest(self.src), before)
        self.assertEqual(sorted(os.listdir(self.src)), sorted({*os.listdir(self.src)}))

    def test_settings_arrive_and_the_key_is_among_them(self):
        res = D.copy(["settings"], self.src, self.dst)
        self.assertIn("config.json", res["copied"])
        self.assertIn("gsk_real", open(os.path.join(self.dst, "config.json")).read())

    def test_the_licence_device_and_update_state_are_never_copied(self):
        D.copy(list(D.CHOICES), self.src, self.dst)
        for name in ("license.json", "authorization.json", "device_id", "update_state.json"):
            self.assertFalse(os.path.exists(os.path.join(self.dst, name)), name)

    def test_only_what_was_chosen_is_copied(self):
        D.copy(["settings"], self.src, self.dst)
        self.assertEqual(sorted(os.listdir(self.dst)), ["config.json", "gui_favorites.json"])

    def test_browser_logins_come_without_chromes_lock_files(self):
        D.copy(["logins"], self.src, self.dst)
        self.assertTrue(os.path.exists(os.path.join(self.dst, "chrome_profile", "Default", "Cookies")))
        self.assertFalse(os.path.exists(os.path.join(self.dst, "chrome_profile", "SingletonLock")))

    def test_an_existing_file_is_kept_as_a_backup_first(self):
        os.makedirs(self.dst)
        open(os.path.join(self.dst, "config.json"), "w").write('{"api_key": "dev-own"}')
        res = D.copy(["settings"], self.src, self.dst)
        self.assertEqual(res["backed_up"], ["config.json"])
        self.assertIn("dev-own", open(os.path.join(self.dst, "config.json.before-import")).read())

    def test_something_the_normal_prism_does_not_have_is_reported_not_invented(self):
        shutil.rmtree(os.path.join(self.src, "tools"))
        res = D.copy(["tools"], self.src, self.dst)
        self.assertEqual(res["missing"], ["tools"])
        self.assertEqual(res["copied"], [])

    def test_the_same_folder_is_refused_and_so_is_an_unknown_choice(self):
        with self.assertRaises(ValueError):
            D.copy(["settings"], self.src, self.src)
        with self.assertRaises(ValueError):
            D.copy(["everything"], self.src, self.dst)


class WhenItApplies(Rooms):
    def test_never_in_a_normal_build(self):
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertFalse(D.applicable())

    def test_only_in_a_dev_build_with_a_normal_install_to_copy_from(self):
        with mock.patch.object(channel, "CHANNEL", "dev"), \
             mock.patch.object(D, "source_dir", return_value=self.src), \
             mock.patch.object(D, "dest_dir", return_value=self.dst):
            self.assertTrue(D.applicable())
        with mock.patch.object(channel, "CHANNEL", "dev"), \
             mock.patch.object(D, "source_dir", return_value=os.path.join(self.tmp, "none")), \
             mock.patch.object(D, "dest_dir", return_value=self.dst):
            self.assertFalse(D.applicable())

    def test_the_source_is_the_real_homes_prism_folder(self):
        with mock.patch.dict(os.environ, {"PRISM_REAL_HOME": os.path.join(self.tmp, "real")}):
            self.assertEqual(D.source_dir(), self.src)


class TheSettingsButton(Rooms):
    def test_copy_now_copies_what_is_ticked_and_refreshes_the_settings_in_memory(self):
        from widgets import settings_panel as SP
        fake = types.SimpleNamespace(cfg={"api_key": ""}, _after_save=mock.Mock())
        tick = lambda on: types.SimpleNamespace(isChecked=lambda: on)
        boxes = {"settings": tick(True), "logins": tick(False), "history": tick(False), "tools": tick(False)}
        with mock.patch.object(D, "copy", return_value={"copied": ["config.json"], "missing": [], "backed_up": []}) as c, \
             mock.patch.object(SP.CB.config, "load", return_value={"api_key": "gsk_real"}), \
             mock.patch("output_folders.apply"):
            SP.SettingsPanel._run_dev_import(fake, boxes)
        c.assert_called_once_with(["settings"])
        self.assertEqual(fake.cfg["api_key"], "gsk_real", "the open settings must not keep the stale empty key")
        self.assertIn("Restart Prism", fake._after_save.call_args.args[0])

    def test_nothing_ticked_says_so_and_copies_nothing(self):
        from widgets import settings_panel as SP
        fake = types.SimpleNamespace(cfg={}, _after_save=mock.Mock())
        boxes = {"settings": types.SimpleNamespace(isChecked=lambda: False)}
        with mock.patch.object(D, "copy") as c, mock.patch.object(SP.QMessageBox, "information") as info:
            SP.SettingsPanel._run_dev_import(fake, boxes)
        c.assert_not_called()
        info.assert_called_once()


if __name__ == "__main__":
    unittest.main()

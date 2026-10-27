"""File and folder choosers open in the user's real folders (RELEASE_ISSUES.md
ISS-009/ISS-012). A chooser that opens in the install folder or in a dev
build's data folder looks like "Prism cannot see my Downloads"."""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import paths  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TheStartFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.real = os.path.join(self.tmp.name, "real")
        self.data = os.path.join(self.tmp.name, "real", ".prism-dev-home")
        os.makedirs(os.path.join(self.real, "Downloads"))
        os.makedirs(self.data)

    def no_system_folders(self):
        from PySide6.QtCore import QStandardPaths
        return mock.patch.object(QStandardPaths, "writableLocation", return_value="")

    def test_it_is_a_folder_that_exists(self):
        self.assertTrue(os.path.isdir(paths.picker_start_dir()))

    def test_the_real_downloads_folder_is_used_when_the_system_gives_none(self):
        env = {"PRISM_REAL_HOME": self.real, "PRISM_HOME_ISOLATED": self.data}
        with self.no_system_folders(), mock.patch.dict(os.environ, env):
            self.assertEqual(paths.picker_start_dir(), os.path.join(self.real, "Downloads"))

    def test_it_is_never_a_dev_builds_data_folder(self):
        os.rmdir(os.path.join(self.real, "Downloads"))          # nothing to find but the home
        env = {"PRISM_REAL_HOME": self.real, "PRISM_HOME_ISOLATED": self.data}
        with self.no_system_folders(), mock.patch.dict(os.environ, env):
            got = paths.picker_start_dir()
        self.assertEqual(got, self.real)
        self.assertFalse(got.startswith(self.data))

    def test_the_system_downloads_folder_wins_when_it_has_one(self):
        from PySide6.QtCore import QStandardPaths
        moved = os.path.join(self.tmp.name, "moved-downloads")
        os.makedirs(moved)
        with mock.patch.object(QStandardPaths, "writableLocation", return_value=moved):
            self.assertEqual(paths.picker_start_dir(), moved)


class EveryAttachPathPassesIt(unittest.TestCase):
    """The pickers a customer uses to attach things all start in a real folder."""

    def setUp(self):
        self.start = "/real/Downloads"
        patcher = mock.patch.object(paths, "picker_start_dir", return_value=self.start)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_attach_a_folder(self):
        import main_window as MW
        fake = types.SimpleNamespace(_attach_path=mock.Mock())
        with mock.patch.object(MW.QFileDialog, "getExistingDirectory", return_value="") as pick:
            MW.MainWindow._attach_folder_dialog(fake)
        self.assertIn(self.start, pick.call_args.args)

    def test_pick_the_right_folder_then_the_right_file(self):
        import main_window as MW
        fake = types.SimpleNamespace(_attach_path=mock.Mock())
        with mock.patch.object(MW.QFileDialog, "getExistingDirectory", return_value="") as folder, \
             mock.patch.object(MW.QFileDialog, "getOpenFileName", return_value=("", "")) as one:
            MW.MainWindow._change_mention(fake, 0)
        self.assertIn(self.start, folder.call_args.args)
        self.assertIn(self.start, one.call_args.args)

    def test_add_files_in_the_follow_up_window(self):
        from dialogs import followup_dialog as FD
        fake = types.SimpleNamespace(_paths=[], _update_attachments_ui=mock.Mock())
        with mock.patch.object(FD.QFileDialog, "getOpenFileNames", return_value=([], "")) as pick:
            FD.FollowupDialog._add_files(fake)
        self.assertIn(self.start, pick.call_args.args)


if __name__ == "__main__":
    unittest.main()

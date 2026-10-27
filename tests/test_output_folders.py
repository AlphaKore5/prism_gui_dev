"""Where Prism saves the files it makes (output_folders.py), and that the three
places that write them (engine artifacts, STEP, Gerber) honour the choice.

RELEASE_ISSUES.md ISS-012: a dev build's "~" is a hidden data folder, so a
default computed from it hid the person's own files. Defaults a person is meant
to open are now built from the REAL home."""
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
import output_folders as O  # noqa: E402

_app = QApplication.instance() or QApplication([])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="outfolders-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.real = os.path.join(self.tmp, "real")
        self.data = os.path.join(self.real, channel.DEV_HOME_NAME)
        os.makedirs(self.data)
        env = {"PRISM_REAL_HOME": self.real, "PRISM_HOME_ISOLATED": self.data}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)


class Choosing(Base):
    def test_the_usual_places_are_on_the_real_desktop(self):
        for kind, name in (("artifacts", "Prism Artifacts"), ("step", "Prism Step"), ("gerber", "Prism Gerber")):
            self.assertEqual(O.usual_dir(kind), os.path.join(self.real, "Desktop", name))

    def test_a_choice_wins_over_everything(self):
        mine = os.path.join(self.tmp, "work")
        self.assertEqual(O.chosen({"gerber_out_dir": mine}, "gerber", "/engine/default"), mine)

    def test_an_ordinary_build_keeps_the_engines_own_default(self):
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertEqual(O.chosen({}, "artifacts", "/engine/default"), "/engine/default")

    def test_a_dev_build_never_uses_a_default_hidden_in_its_data_folder(self):
        hidden = os.path.join(self.data, "Desktop", "Prism Artifacts")
        with mock.patch.object(channel, "CHANNEL", "dev"):
            got = O.chosen({}, "artifacts", hidden)
        self.assertEqual(got, os.path.join(self.real, "Desktop", "Prism Artifacts"))
        self.assertFalse(got.startswith(self.data))


class Checking(Base):
    def test_empty_means_the_usual_place_and_is_fine(self):
        self.assertEqual(O.check_folder(""), (True, ""))

    def test_a_new_folder_is_created_and_accepted(self):
        target = os.path.join(self.tmp, "a", "b")
        self.assertEqual(O.check_folder(target), (True, ""))
        self.assertTrue(os.path.isdir(target))

    def test_a_folder_that_cannot_be_made_is_refused_with_a_reason(self):
        blocker = os.path.join(self.tmp, "afile")
        open(blocker, "w").write("x")
        ok, why = O.check_folder(os.path.join(blocker, "inside"))
        self.assertFalse(ok)
        self.assertIn("cannot write", why)

    def test_the_top_of_a_drive_is_refused(self):
        ok, why = O.check_folder(os.path.abspath(os.sep))
        self.assertFalse(ok)

    def test_a_folder_inside_the_programs_own_files_is_refused(self):
        bundle = os.path.join(self.tmp, "Prism")
        os.makedirs(bundle)
        with mock.patch("paths.is_frozen", return_value=True), mock.patch("paths.bundle_dir", return_value=bundle):
            ok, why = O.check_folder(os.path.join(bundle, "out"))
        self.assertFalse(ok)
        self.assertIn("program files", why)


class Applying(Base):
    def engine(self, folder):
        return types.SimpleNamespace(ARTIFACTS_DIR=folder, _root_cache={"for": folder, "root": folder})

    def test_a_chosen_folder_reaches_the_engine_and_clears_its_cache(self):
        mine = os.path.join(self.tmp, "mine")
        engine = self.engine("/old")
        O.apply({"artifacts_dir": mine}, engine)
        self.assertEqual(engine.ARTIFACTS_DIR, mine)
        self.assertEqual(engine._root_cache, {"for": None, "root": None})

    def test_nothing_changes_in_an_ordinary_build_with_no_choice(self):
        engine = self.engine("/old")
        with mock.patch.object(channel, "CHANNEL", "prod"):
            O.apply({}, engine)
        self.assertEqual(engine.ARTIFACTS_DIR, "/old")

    def test_a_dev_build_with_no_choice_still_saves_where_the_person_can_see(self):
        engine = self.engine(os.path.join(self.data, "Desktop", "Prism Artifacts"))
        with mock.patch.object(channel, "CHANNEL", "dev"):
            O.apply({}, engine)
        self.assertEqual(engine.ARTIFACTS_DIR, os.path.join(self.real, "Desktop", "Prism Artifacts"))


class TheWritersHonourIt(Base):
    def test_gerber_uses_the_chosen_folder(self):
        from addons.gerber import dialog as G
        mine = os.path.join(self.tmp, "gerber out")
        fake = types.SimpleNamespace(cfg={"gerber_out_dir": mine})
        fake._reports_dir = lambda: G.GerberDialog._reports_dir(fake)
        self.assertEqual(G.GerberDialog._out_dir(fake), mine)

    def test_gerber_falls_back_to_its_usual_folder(self):
        from addons.gerber import dialog as G
        fake = types.SimpleNamespace(cfg={})
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertEqual(G.GerberDialog._reports_dir(fake), G.REPORTS_DIR)

    def test_step_default_is_visible_in_a_dev_build(self):
        from addons.step import dialog as S
        hidden = os.path.join(self.data, "Desktop", "Prism Step")
        fake = types.SimpleNamespace(sf=types.SimpleNamespace(DEFAULT_OUT_ROOT=hidden), cfg={})
        with mock.patch.object(channel, "CHANNEL", "dev"):
            got = S.StepDialog._root_default(fake)
        self.assertEqual(got, os.path.join(self.real, "Desktop", "Prism Step"))


class TheSettingsBox(Base):
    def make(self):
        from widgets import settings_panel as SP
        fake = types.SimpleNamespace(cfg={}, _after_save=mock.Mock())
        return SP, fake

    def test_saving_a_good_folder_stores_it_and_tells_the_engine(self):
        SP, fake = self.make()
        mine = os.path.join(self.tmp, "stepwork")
        field = mock.Mock(); field.text.return_value = mine
        with mock.patch.object(O, "apply") as applied:
            SP.SettingsPanel._save_output_folder(fake, "step", field)
        self.assertEqual(fake.cfg["step_out_dir"], mine)
        applied.assert_called_once()
        fake._after_save.assert_called_once()

    def test_a_bad_folder_is_refused_and_nothing_is_saved(self):
        SP, fake = self.make()
        blocker = os.path.join(self.tmp, "afile"); open(blocker, "w").write("x")
        field = mock.Mock(); field.text.return_value = os.path.join(blocker, "x")
        with mock.patch.object(SP.QMessageBox, "warning") as warned:
            SP.SettingsPanel._save_output_folder(fake, "gerber", field)
        self.assertNotIn("gerber_out_dir", fake.cfg)
        warned.assert_called_once()
        fake._after_save.assert_not_called()

    def test_clearing_the_box_goes_back_to_the_usual_folder(self):
        SP, fake = self.make()
        fake.cfg["artifacts_dir"] = "/something"
        field = mock.Mock(); field.text.return_value = ""
        with mock.patch.object(O, "apply"):
            SP.SettingsPanel._save_output_folder(fake, "artifacts", field)
        self.assertEqual(fake.cfg["artifacts_dir"], "")


if __name__ == "__main__":
    unittest.main()

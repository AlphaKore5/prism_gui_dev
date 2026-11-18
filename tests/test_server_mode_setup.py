"""A task must not be blocked by 'Finish Setup (API key + agents) first' when AI runs on Prism's server.

Owner screenshot 'image copy 6.png': Prism asked for an API key and agents although every AI call goes
through the licence server. The guard checked the old key/agents config; in server mode the licence
is the only requirement (licensing.require has already run). The developer escape hatch keeps the old rule.
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-test-home-")
os.environ["HOME"] = _HOME

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402

_app = QApplication.instance() or QApplication([])


class ReadyToPlan(unittest.TestCase):
    def _window(self):
        import main_window
        with mock.patch.object(main_window.MainWindow, "_first_run"):
            win = main_window.MainWindow()
        win.cfg = {}                      # no key, no agents, not onboarded: a brand-new install
        return win

    def test_server_mode_needs_no_key_agents_or_first_run(self):
        win = self._window()
        with mock.patch.object(CB.ai_client, "active", return_value=True):
            self.assertTrue(win._ready_to_plan())

    def test_direct_mode_still_needs_the_setup(self):
        win = self._window()
        with mock.patch.object(CB.ai_client, "active", return_value=False):
            self.assertFalse(win._ready_to_plan())
            win.cfg = {"api_key": "k", "onboarded": True}
            self.assertTrue(win._ready_to_plan())

    def test_route_one_in_server_mode_never_shows_the_setup_box(self):
        import main_window
        win = self._window()
        shown = []
        with mock.patch.object(CB.ai_client, "active", return_value=True), \
             mock.patch.object(main_window.licensing, "require", return_value=True), \
             mock.patch.object(main_window.QMessageBox, "warning", side_effect=lambda *a, **k: shown.append(a)), \
             mock.patch.object(main_window, "RouterWorker", create=True) as worker:
            worker.return_value.start = lambda: None
            try:
                win._route_one("make a poster")
            except Exception:             # whatever runs after the guard is not this test's business
                pass
        self.assertEqual(shown, [])


if __name__ == "__main__":
    unittest.main()

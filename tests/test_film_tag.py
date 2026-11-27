"""A part of a Reel or Motion run says which film it belongs to, so the server
counts it in that film's share (the engine tags the calls: automation.run(film=)).
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
import workers  # noqa: E402
from addons.reel import dialog as reel_dialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TheWorkerPassesIt(unittest.TestCase):

    def passed(self, **kw):
        seen = {}

        def run(routing, cfg, **kwargs):
            seen.update(kwargs)
            return {}, {}

        engine = SimpleNamespace(run=run, FOLLOWUP_MIN_WAIT=480)
        with mock.patch.object(workers.CB, "automation_available", lambda: (True, "")), \
                mock.patch.object(workers.CB, "get_automation", lambda: engine):
            workers.AutomationWorker({}, {}, [], "q", **kw).run()
        self.assertTrue(seen, "the engine was not reached")
        return seen

    def test_film_reaches_the_engine(self):
        self.assertEqual("reel", self.passed(film="reel")["film"])

    def test_an_ordinary_run_sends_nothing_new(self):
        self.assertNotIn("film", self.passed())

    def test_the_engine_takes_the_argument(self):
        import inspect
        self.assertIn("film", inspect.signature(CB.get_automation().run).parameters)


class TheReelDialogSaysSo(unittest.TestCase):

    def test_the_script_run_is_part_of_a_reel(self):
        dlg = reel_dialog.ReelDialog({"agents": {"content": "ChatGPT"}}, [], None)
        dlg.ask.set_text("a reel about what we sell")
        dlg.reel_btn.setChecked(True)
        with mock.patch.object(reel_dialog, "AutomationWorker") as worker, \
                mock.patch.object(CB, "reel_available", lambda: (True, "")):
            dlg._run()
        self.assertEqual("reel", worker.call_args.kwargs["film"])


if __name__ == "__main__":
    unittest.main()

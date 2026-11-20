"""The Settings switch for Pulse (Privacy & data > Help improve Prism).

Saves under the throwaway CONFIG_PATH the conftest provides (never the real
~/.prism), takes effect at once without a restart, and says plainly what is and
is not sent."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QCheckBox, QLabel      # noqa: E402

_app = QApplication.instance() or QApplication([])

import core_bridge as CB                                           # noqa: E402
import pulse                                                       # noqa: E402
from tests.test_ui_port_settings import _panel                     # noqa: E402


class TheSwitch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-pulse-switch-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        for target, fn in (("paths.user_dir", lambda *p: os.path.join(self.tmp, *p)),):
            m = mock.patch(target, fn)
            m.start()
            self.addCleanup(m.stop)
        m = mock.patch.dict(os.environ, {"PRISM_PULSE": "1"})
        m.start()
        self.addCleanup(m.stop)
        f = mock.patch.object(pulse, "flush_async")
        f.start()
        self.addCleanup(f.stop)
        self.addCleanup(lambda: pulse.configure({}))

    def queued(self):
        path = os.path.join(self.tmp, "pulse", "queue.jsonl")
        return open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []

    def test_it_is_on_by_default_and_on_the_privacy_page(self):
        p = _panel("privacy")
        self.assertTrue(p.pulse_box.isChecked())
        self.assertIsInstance(p.pulse_box, QCheckBox)

    def test_it_reads_a_saved_off(self):
        p = _panel("privacy", {"pulse_enabled": False})
        self.assertFalse(p.pulse_box.isChecked())

    def test_turning_it_off_saves_and_stops_recording_at_once(self):
        p = _panel("privacy")
        pulse.configure(p.cfg)
        pulse.run("ok", addon="task")
        self.assertEqual(1, len(self.queued()))
        p.pulse_box.click()                                  # a person clicking it
        self.assertFalse(p.pulse_box.isChecked())
        self.assertIs(p.cfg["pulse_enabled"], False)
        self.assertFalse(CB.config.load().get("pulse_enabled", True))   # the temp CONFIG_PATH
        pulse.run("ok", addon="task")
        self.assertEqual(1, len(self.queued()), "recorded after being switched off")

    def test_turning_it_back_on_records_again(self):
        p = _panel("privacy", {"pulse_enabled": False})
        pulse.configure(p.cfg)
        pulse.run("ok", addon="task")
        self.assertEqual(0, len(self.queued()))
        p.pulse_box.click()
        self.assertTrue(CB.config.load().get("pulse_enabled"))
        pulse.run("ok", addon="task")
        self.assertEqual(1, len(self.queued()))

    def test_it_says_what_is_sent_and_what_never_is(self):
        p = _panel("privacy")
        text = " ".join(l.text() for l in p.findChildren(QLabel))
        for sent in ("kind of error", "how long Prism took to open", "which screens were slow", "whether a run finished"):
            self.assertIn(sent, text)
        for never in ("never sends your prompts", "answers", "files", "names", "keys"):
            self.assertIn(never, text)


if __name__ == "__main__":
    unittest.main()

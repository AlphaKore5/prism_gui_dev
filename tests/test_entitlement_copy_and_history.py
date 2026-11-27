"""E5 / E5b: an add-on the licence owns but the build lacks (Engineering side).

E5 : the words the download card must use. The card is Studio's R8; this file
     pins the wording and the owner table it reads, with no card needed.
E5b: History is read-only for a saved run whose add-on this build lacks: the
     run is shown with a note, and follow-up / edit-reel are not offered. The
     complete build, which lacks nothing, behaves exactly as before.

Run under any flavour (PRISM_TEST_FLAVOUR=...). No ~/.prism: the dialog is
built from __new__ and fed records directly, as test_history_dialog does.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QListWidget, QListWidgetItem, QPushButton, QTextBrowser  # noqa: E402

_app = QApplication.instance() or QApplication([])

import core_bridge  # noqa: F401,E402
import entitlement_copy as EC  # noqa: E402
import flavour  # noqa: E402
from addons import registry  # noqa: E402
from dialogs import history_dialog as HD  # noqa: E402
from dialogs.history_dialog import HistoryDialog  # noqa: E402

ALL = flavour.ADDONS_BY_FLAVOUR["complete"]


class TheOwnerTable(unittest.TestCase):

    def test_every_add_on_has_one_home_edition(self):
        # Reel and Motion sit in Studio, Sales and Engineering (owner rule
        # 2026-11-26); their home is the first of those, Studio. Every other
        # add-on is in exactly one edition.
        for key in ALL:
            owners = [f for f in EC.EDITION_NAMES
                      if key in flavour.ADDONS_BY_FLAVOUR[f]]
            if key in ("reel", "motion"):
                self.assertEqual(owners, ["studio", "sales", "engineering"], key)
            else:
                self.assertEqual(len(owners), 1, (key, owners))
            self.assertEqual(EC.owner_edition(key), owners[0])

    def test_the_card_names_the_right_edition(self):
        self.assertIn("Prism Sales", EC.absent_message("leads", "Leads"))
        self.assertIn("Prism Sales", EC.absent_message("inquiry", "Email inquiries"))
        self.assertIn("Prism Engineering", EC.absent_message("boq", "BOQ"))
        self.assertIn("Prism Engineering", EC.absent_message("bom", "BOM"))
        self.assertIn("Prism Studio", EC.absent_message("reel", "Reel"))

    def test_the_card_says_you_own_it_and_where_to_open_it(self):
        msg = EC.absent_message("leads", "Leads")
        self.assertTrue(msg.startswith("Leads is part of Prism Sales."))
        self.assertIn("Your licence includes it", msg)
        self.assertIn("Open Prism Sales to use it.", msg)

    def test_an_unknown_key_gets_no_card_text(self):
        self.assertEqual(EC.owner_edition("nonsense"), "")
        self.assertEqual(EC.absent_message("nonsense", "X"), "")
        self.assertEqual(EC.read_only_note("nonsense"), "")


class _Harness(HistoryDialog):
    """A HistoryDialog with just the widgets _show touches."""

    def __init__(self):                       # noqa: skip the heavy real init
        from PySide6.QtWidgets import QDialog
        QDialog.__init__(self)
        self.view = QTextBrowser()
        self.edit_reel_btn = QPushButton()
        self.follow_up_btn = QPushButton()
        self._current_reel = ""
        self._current_record = None


def _show(record):
    d = _Harness()
    item = QListWidgetItem("run")
    item.setData(HD._RECORD_ROLE, dict(record))
    item.setData(HD._PATH_ROLE, "/x/run_1.json")
    d._show(item)
    return d


RECORDS = {
    "boq": {"query": "BOQ - a plant", "boq": {"x": 1}, "responses": {"boq": ["done"]}},
    "gerber": {"query": "Gerber - a board", "gerber": {"x": 1}},
    "step": {"query": "STEP - a part", "step": {"action": "ask", "models": []}},
    "email": {"query": "Email - a reply", "email": {"x": 1}},
    "reel": {"query": "Reel - a film", "reel": {"mp4": "/x/a.mp4"}},
}


class HistoryIsReadOnlyForAbsentKinds(unittest.TestCase):

    def test_one_record_per_kind_follows_the_build(self):
        for kind, record in RECORDS.items():
            absent = registry.is_absent(kind)
            d = _show(record)
            html = d.view.toPlainText()
            # always readable
            self.assertIn(record["query"], html, kind)
            note = EC.read_only_note(kind)
            if absent:
                self.assertIn(note, html, kind)
                self.assertTrue(d.follow_up_btn.isHidden(), kind)
                self.assertIsNone(d._current_record, kind)
            else:
                self.assertNotIn("opens in Prism", html, kind)
                self.assertFalse(d.follow_up_btn.isHidden(), kind)
                self.assertIsNotNone(d._current_record, kind)

    def test_a_run_with_text_only_stays_continuable_in_every_build(self):
        d = _show({"query": "Research", "responses": {"research": ["text"]}})
        self.assertFalse(d.follow_up_btn.isHidden())

    def test_an_absent_kind_never_offers_edit_reel(self):
        d = _show({"query": "Reel - a film", "reel": {"mp4": "/x/a.mp4"},
                   "links": {"a": "https://example.com/a.mp4"}})
        if registry.is_absent("reel"):
            self.assertTrue(d.edit_reel_btn.isHidden())


if __name__ == "__main__":
    unittest.main()

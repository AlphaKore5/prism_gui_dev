"""widgets/stepper.py -- the numbered step tabs and the file card that guided
dialogs (the BOQ steps, the HVAC tender PDF) share."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                         # noqa: E402

_app = QApplication.instance() or QApplication([])

from widgets.stepper import FileCard, StepTabs                     # noqa: E402


class StepTabsMarkDoneActiveAndTodo(unittest.TestCase):
    def test_current_step_splits_the_row_three_ways(self):
        t = StepTabs(["A", "B", "C", "D"])
        t.set_current(2)
        self.assertEqual(t.states(), ["done", "done", "active", "todo"])

    def test_a_done_step_shows_a_tick_not_its_number(self):
        t = StepTabs(["A", "B", "C"])
        t.set_current(2)
        self.assertEqual([x.num.text() for x in t._tabs], ["✓", "✓", "3"])

    def test_the_index_is_clamped_to_the_steps_that_exist(self):
        t = StepTabs(["A", "B"])
        t.set_current(9)
        self.assertEqual(t.current, 1)
        t.set_current(-3)
        self.assertEqual(t.current, 0)

    def test_only_a_finished_step_reports_a_click(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        t = StepTabs(["A", "B", "C"])
        t.show()
        t.set_current(1)
        got = []
        t.step_clicked.connect(got.append)
        QTest.mouseClick(t._tabs[0], Qt.LeftButton)     # done: allowed through
        QTest.mouseClick(t._tabs[2], Qt.LeftButton)     # still to come: nothing
        QTest.mouseClick(t._tabs[1], Qt.LeftButton)     # the one you are on
        self.assertEqual(got, [0])

    def test_every_tab_says_where_it_is_for_a_screen_reader(self):
        t = StepTabs(["Your PDF", "Scale"])
        self.assertIn("Step 1: Your PDF (active)", t._tabs[0].accessibleName())
        self.assertIn("Step 2: Scale (todo)", t._tabs[1].accessibleName())


class FileCardShowsTheFileOnceThereIsOne(unittest.TestCase):
    def _card(self):
        return FileCard("Add your PDF", "A PDF of the drawing.", "PDF added",
                        "Add PDF", "Change PDF")

    def test_empty_prompts_for_a_file(self):
        c = self._card()
        self.assertEqual(c.title.text(), "Add your PDF")
        self.assertEqual(c.button.text(), "Add PDF")
        self.assertFalse(c.property("added"))

    def test_with_a_file_it_names_it_and_offers_a_change(self):
        c = self._card()
        c.set_file("tower-b.pdf")
        self.assertEqual(c.title.text(), "PDF added")
        self.assertEqual(c.hint.text(), "tower-b.pdf")
        self.assertEqual(c.button.text(), "Change PDF")
        self.assertTrue(c.property("added"))

    def test_clearing_the_file_goes_back_to_the_prompt(self):
        c = self._card()
        c.set_file("x.pdf")
        c.set_file("")
        self.assertEqual(c.button.text(), "Add PDF")
        self.assertFalse(c.property("added"))


if __name__ == "__main__":
    unittest.main()

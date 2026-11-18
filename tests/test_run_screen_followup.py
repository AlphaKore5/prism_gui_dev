"""Stage 26 (2): the run screen after a follow-up.

Seen in the owner's capture: two cards both named "Write it up", an 'up to 300s'
chip on a finished card, and a header that showed only the follow-up sentence.
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s26b-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication                         # noqa: E402
_app = QApplication.instance() or QApplication([])

import ai_server                                                   # noqa: E402
import docexport                                                   # noqa: E402
from widgets import output_panel as OP                             # noqa: E402


def _first_run(panel):
    panel.set_plan({"content": "ChatGPT"})
    panel.set_task("write an essay on trees")
    panel.stage_started("content", "ChatGPT")
    panel.stage_done("content", ["The essay."], "")


class FollowupCards(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(ai_server, "active", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def _followup(self, panel, text):
        panel.set_plan({"content": "ChatGPT"}, followup=True,
                       titles={"content": docexport.followup_title("content", text)})
        panel.set_task("write an essay on trees")
        panel.add_followup(text)

    def test_two_cards_are_not_both_write_it_up(self):
        panel = OP.OutputPanel()
        _first_run(panel)
        self._followup(panel, "give me this in a pdf")
        titles = [panel._cards[k]._title for k in panel._order]
        self.assertEqual(len(titles), 2)
        self.assertEqual(len(set(titles)), 2, titles)
        self.assertEqual(titles[1], "Make a PDF")

    def test_a_change_is_called_revise_the_answer(self):
        panel = OP.OutputPanel()
        _first_run(panel)
        self._followup(panel, "make it shorter and friendlier")
        self.assertEqual(panel._cards[panel._order[1]]._title, "Revise the answer")

    def test_each_card_says_which_run_it_belongs_to(self):
        panel = OP.OutputPanel()
        _first_run(panel)
        self._followup(panel, "make it shorter")
        tags = [panel._cards[k].turn() for k in panel._order]
        self.assertEqual(tags, ["First run", "Follow-up 1"])
        self.assertFalse(panel._cards[panel._order[1]].turn_tag.isHidden())

    def test_first_run_has_no_tag(self):
        panel = OP.OutputPanel()
        _first_run(panel)
        self.assertTrue(panel._cards["content"].turn_tag.isHidden())

    def test_header_keeps_the_task_and_lists_followups_beneath(self):
        panel = OP.OutputPanel()
        _first_run(panel)
        self._followup(panel, "make it shorter")
        self.assertEqual(panel.header.task.full_text(), "write an essay on trees")
        self.assertFalse(panel.header.followups.isHidden())
        self.assertIn("make it shorter", panel.header.followups.text())
        panel.clear()
        self.assertTrue(panel.header.followups.isHidden())

    def test_finished_chip_is_the_duration_only(self):
        panel = OP.OutputPanel()
        panel.set_plan({"content": "ChatGPT"})
        panel.stage_started("content", "ChatGPT")
        panel.stage_waiting("content", 300)
        panel.stage_done("content", ["x"], "")
        self.assertNotIn("up to", panel._cards["content"].status_text())


if __name__ == "__main__":
    unittest.main()

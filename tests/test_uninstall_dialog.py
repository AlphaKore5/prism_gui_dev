"""The Uninstall window: what it shows is the plan that will run, the extra
"delete my files" box is off until everything is chosen, and Remove does
nothing irreversible without first starting the plan and quitting. Nothing here
deletes anything: the plan builder, the starter and the quitter are replaced."""
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import uninstall as U  # noqa: E402
from dialogs.uninstall_dialog import UninstallDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


def fake_builder(calls):
    def build(scope, *, include_outputs=False, output_candidates=None):
        calls.append((scope, include_outputs))
        plan = U.Plan(scope, app_dir="/apps/Prism")
        if scope == U.SCOPE_ALL:
            plan.data_dirs = ["/home/x/.prism"]
            if include_outputs:
                plan.output_dirs = ["/home/x/Desktop/Prism Artifacts"]
                plan.skipped = [("/home/x/Documents", "you chose this folder yourself")]
        return plan
    return build


class TheWindow(unittest.TestCase):
    def make(self, **kw):
        self.calls, self.started, self.quit = [], [], []
        return UninstallDialog(["/x"], None, plan_builder=kw.get("builder") or fake_builder(self.calls),
                               starter=lambda plan: self.started.append(plan),
                               quitter=lambda: self.quit.append(1))

    def test_it_opens_on_the_safe_choice_and_lists_only_the_program(self):
        d = self.make()
        self.assertTrue(d.app_only.isChecked())
        self.assertIn("/apps/Prism", d.list_label.text())
        self.assertNotIn(".prism", d.list_label.text())
        self.assertFalse(d.with_files.isEnabled())

    def test_choosing_everything_lists_the_data_folder_and_unlocks_the_files_box(self):
        d = self.make()
        d.everything.setChecked(True)
        self.assertIn("/home/x/.prism", d.list_label.text())
        self.assertTrue(d.with_files.isEnabled())
        self.assertNotIn("Prism Artifacts", d.list_label.text(), "made files stay unless asked")

    def test_asking_for_files_adds_them_and_names_what_is_left_alone(self):
        d = self.make()
        d.everything.setChecked(True)
        d.with_files.setChecked(True)
        text = d.list_label.text()
        self.assertIn("/home/x/Desktop/Prism Artifacts", text)
        self.assertIn("Left alone: /home/x/Documents", text)

    def test_going_back_to_the_app_only_clears_the_files_box(self):
        d = self.make()
        d.everything.setChecked(True)
        d.with_files.setChecked(True)
        d.app_only.setChecked(True)
        self.assertFalse(d.with_files.isChecked())
        self.assertFalse(d.with_files.isEnabled())

    def test_remove_starts_the_plan_the_window_showed_and_then_quits(self):
        d = self.make()
        d.everything.setChecked(True)
        d.remove_btn.click()
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0].scope, U.SCOPE_ALL)
        self.assertEqual(self.quit, [1])

    def test_nothing_starts_until_remove_is_pressed(self):
        d = self.make()
        d.everything.setChecked(True)
        self.assertEqual((self.started, self.quit), ([], []))

    def test_running_from_source_disables_remove_and_says_why(self):
        def refuse(scope, **kw):
            raise U.Refused("Prism is running from its source files, not as an installed app.")
        d = self.make(builder=refuse)
        self.assertFalse(d.remove_btn.isEnabled())
        self.assertIn("source files", d.problem.text())

    def test_a_failure_to_start_is_shown_and_the_app_does_not_quit(self):
        d = self.make()
        d._start = mock.Mock(side_effect=OSError("disk is read-only"))
        d.remove_btn.click()
        self.assertIn("read-only", d.problem.text())
        self.assertEqual(self.quit, [])


if __name__ == "__main__":
    unittest.main()

"""The Uninstall window: what it shows is the plan that will run, the extra
two choices are the only ones, and Remove does
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
    def build(scope, *, output_candidates=None, chosen=None, protect=None):
        calls.append((scope, tuple(output_candidates or []), tuple(chosen or []), tuple(protect or [])))
        plan = U.Plan(scope, app_dir="/apps/Prism")
        if scope == U.SCOPE_ALL:
            plan.data_dirs = ["/home/x/.prism"]
            if output_candidates:
                plan.output_dirs = ["/home/x/Desktop/Prism Artifacts"]
                plan.skipped = [("/home/x/Documents", "you chose this folder yourself")]
        return plan
    return build


class TheWindow(unittest.TestCase):
    def make(self, **kw):
        self.calls, self.started, self.quit = [], [], []
        return UninstallDialog(["/x"], None, chosen=["/mine/Prism Photos"], protect=["/shared"],
                               plan_builder=kw.get("builder") or fake_builder(self.calls),
                               starter=lambda plan: self.started.append(plan),
                               quitter=lambda: self.quit.append(1))

    def test_it_opens_on_uninstall_prism_only_and_lists_only_the_program(self):
        d = self.make()
        self.assertTrue(d.app_only.isChecked())
        self.assertEqual(d.app_only.text(), "Uninstall Prism")
        self.assertIn("/apps/Prism", d.list_label.text())
        self.assertNotIn(".prism", d.list_label.text())
        self.assertNotIn("Prism Artifacts", d.list_label.text())

    def test_there_are_exactly_two_choices_and_no_extra_tick(self):
        from PySide6.QtWidgets import QCheckBox, QRadioButton
        d = self.make()
        self.assertEqual(len(d.findChildren(QRadioButton)), 2)
        self.assertEqual(d.findChildren(QCheckBox), [])
        self.assertEqual(d.everything.text(), "Uninstall Prism and everything it stored")

    def test_everything_lists_the_data_with_logs_the_folders_prism_created_and_what_is_left_alone(self):
        d = self.make()
        d.everything.setChecked(True)
        text = d.list_label.text()
        self.assertIn("/home/x/.prism", text)
        self.assertIn("logs", text)
        self.assertIn("/home/x/Desktop/Prism Artifacts", text)
        self.assertIn("Left alone: /home/x/Documents", text)

    def test_the_window_passes_prisms_folders_the_persons_and_the_workspace_to_the_plan(self):
        d = self.make()
        d.everything.setChecked(True)
        self.assertEqual(self.calls[-1], (U.SCOPE_ALL, ("/x",), ("/mine/Prism Photos",), ("/shared",)))

    def test_the_window_shows_when_the_saved_licence_key_goes_too(self):
        def build(scope, **kw):
            plan = U.Plan(scope, app_dir="/apps/Prism", data_dirs=["/home/x/.prism"])
            plan.forget_licence = scope == U.SCOPE_ALL
            return plan
        d = self.make(builder=build)
        self.assertNotIn("credential store", d.list_label.text())
        d.everything.setChecked(True)
        self.assertIn("credential store", d.list_label.text())

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

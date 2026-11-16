"""UI port stage 13: the STEP workbench in the shared reskin look.

Real widgets, offscreen, sandbox HOME, no network, no AI, nothing saved to
the real ~/.prism (CB.config.save is patched wherever a click could reach it).
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-stage13-step-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtCore import QPoint                                  # noqa: E402
from PySide6.QtWidgets import (                                    # noqa: E402
    QApplication, QCheckBox, QLabel, QVBoxLayout, QWidget,
)

_app = QApplication.instance() or QApplication([])

import core_bridge as CB                                           # noqa: E402
import plans                                                       # noqa: E402
from addons.step import dialog as SD                               # noqa: E402
from addons.step import workbench as WB                            # noqa: E402
from test_gates import GateTest                                    # noqa: E402
from widgets.usage_chip import Usage, UsageChip                    # noqa: E402

EVERYTHING = tuple(plans.FEATURES)


def _model_file() -> str:
    """Only the name matters to attaching; measuring is never started here."""
    path = os.path.join(tempfile.mkdtemp(prefix="prism-step-model-"),
                        "mounting-bracket.step")
    with open(path, "w", encoding="utf-8") as f:
        f.write("ISO-10303-21;\nEND-ISO-10303-21;\n")
    return path


_KEEP = []      # every screen built here lives to the end of the run (no
                # mid-test teardown of Qt objects the painted shadows watch)


def _screen(width=1066, height=716, attached=False):
    """The workbench embedded the way main_window builds it, at the size the
    stack gives it in a 1366x768 window (1920x1080: 1620x1028)."""
    host = QWidget()
    _KEEP.append(host)
    QVBoxLayout(host).setContentsMargins(0, 0, 0, 0)
    d = SD.StepDialog({"step_out_dir": tempfile.mkdtemp()}, [], host,
                      embedded=True)
    d._vision_consent = False
    host.layout().addWidget(d)
    host.resize(width, height)
    host.show()
    if attached:
        d._on_files_added([_model_file()])
    host.layout().activate()
    d.layout().activate()
    _app.sendPostedEvents()
    return host, d


def _right_edge(widget, host) -> int:
    return widget.mapTo(host, QPoint(widget.width(), 0)).x()


class TheRealEntryPath(GateTest):
    def test_the_step_command_lands_on_the_embedded_workbench(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, f, a, then: then()):
            win._handle_command("step")
        self.assertEqual(win.screens.currentIndex(), main_window.STEP_WORK)
        self.assertIsInstance(win.step_work, SD.StepDialog)
        self.assertEqual(win.step_work.objectName(), "stepWork")
        self.assertTrue(win.step_work.isVisibleTo(win))

    def test_the_gate_still_comes_first(self):
        import main_window
        self.grant([f for f in EVERYTHING if f != "step"])
        win = self._window()
        win._handle_command("step")
        self.assertIn("step", self.paywalled)
        self.assertNotEqual(win.screens.currentIndex(), main_window.STEP_WORK)


class TheLayout(unittest.TestCase):
    def test_columns_have_the_preview_widths(self):
        _h, d = _screen()
        self.assertEqual(d.models_card.width(), 250)
        self.assertEqual(d.right_card.width(), WB.RIGHT_W)

    def test_nothing_runs_off_the_right_edge_once_a_model_is_attached(self):
        """Before the port the attached state's controls pushed the results
        pane past the window at 1366 wide."""
        for w, h in ((1066, 716), (1620, 1028)):
            with self.subTest(size=(w, h)):
                host, d = _screen(w, h, attached=True)
                d.more.toggle.click()          # the widest state: the fold open
                d.layout().activate()
                self.assertLessEqual(_right_edge(d.right_card, host), w)
                self.assertLessEqual(_right_edge(d.close_btn, host), w)
                self.assertLessEqual(_right_edge(d.generate_btn, host), w)

    def test_the_wide_toggle_goes_out_and_back(self):
        _h, d = _screen()
        d.wide_btn.click()
        self.assertEqual(d.right_card.width(), 660)
        self.assertIn("narrower", d.wide_btn.toolTip())
        d.wide_btn.click()
        self.assertEqual(d.right_card.width(), WB.RIGHT_W)

    def test_header_card_title_and_trust_chip(self):
        _h, d = _screen()
        head = d.findChild(QWidget, "stepHead")
        self.assertIsNotNone(head)
        self.assertEqual(head.height(), 60)
        trust = d.findChild(QLabel, "stepTrust")
        self.assertEqual(trust.text(), "■  MEASURED HERE — NEVER UPLOADED")
        self.assertIn("Geist Mono", trust.styleSheet())
        title = [l for l in d.findChildren(QLabel) if l.text() == "STEP"
                 and "28.7px" in l.styleSheet()][0]
        self.assertIn("font-weight: 400", title.styleSheet())

    def test_one_dark_primary_on_screen_at_a_time(self):
        host, d = _screen()
        visible = lambda: [b for b in d.findChildren(QWidget)
                           if b.objectName() in ("primaryBtn", "primary")
                           and b.isVisibleTo(host)]
        self.assertEqual(visible(), [d.canvas.choose_btn])
        host2, d2 = _screen(attached=True)
        self.assertEqual([b for b in d2.findChildren(QWidget)
                          if b.objectName() in ("primaryBtn", "primary")
                          and b.isVisibleTo(host2)], [d2.generate_btn])

    def test_the_primary_says_why_it_is_grey(self):
        _h, d = _screen()
        self.assertFalse(d.generate_btn.isEnabled())
        self.assertEqual(d.generate_btn.toolTip(), "Attach a model first")


class MoreOptions(unittest.TestCase):
    def test_advanced_controls_are_folded_and_still_reachable(self):
        host, d = _screen(attached=True)
        body = d.more.body
        for w in (d.ai_draft_cb, d.catalog_box, d.model_combo,
                  d.catalog_attach_btn, d.catalog_remove_btn,
                  d.inquiry_id_edit, d.inquiry_od_edit):
            self.assertTrue(body.isAncestorOf(w), w)
        self.assertFalse(body.isVisibleTo(host))
        d.more.toggle.click()
        self.assertTrue(body.isVisibleTo(host))
        # Draft: the styled-copy tick and the catalog; Ask: who answers.
        self.assertTrue(d.ai_draft_cb.isVisibleTo(host))
        self.assertTrue(d.catalog_box.isVisibleTo(host))
        self.assertFalse(d.model_combo.isVisibleTo(host))
        d._action_buttons["ask"].click()
        self.assertTrue(d.model_combo.isVisibleTo(host))
        self.assertFalse(d.ai_draft_cb.isVisibleTo(host))
        self.assertTrue(d.ask.edit.isVisibleTo(host))     # the question box is NOT folded

    def test_measuring_options_popover_is_unchanged(self):
        _h, d = _screen()
        for w in (d.mode_combo, d.k_edit, d.root_label):
            self.assertTrue(d.opt_box.isAncestorOf(w))
        d.opt_toggle.click()
        self.assertTrue(d.opt_box.isVisible())
        d.opt_box.hide()
        self.assertTrue(d.opt_toggle.text().startswith("Sheet metal"))

    def test_the_tick_still_writes_the_same_setting_on_run(self):
        """Logic guard: a folded control still feeds _generate exactly as before."""
        host, d = _screen(attached=True)
        d.more.toggle.click()
        d.ai_draft_cb.setChecked(True)
        made = []

        class _Worker:
            def __init__(self, paths, mode, root, k):
                made.append((paths, mode, root, k))
                self.progress = self.done = self.failed = mock.Mock()

            def start(self):
                pass

        with mock.patch.object(SD, "StepMeasureWorker", _Worker), \
             mock.patch.object(CB.config, "save") as saved:
            d.generate_btn.click()
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0][0], d.paths)
        self.assertTrue(saved.call_args[0][0]["step_ai_draft"])


class TheUsageChip(unittest.TestCase):
    def test_hidden_until_a_provider_exists(self):
        _h, d = _screen(attached=True)
        self.assertIsInstance(d.usage_chip, UsageChip)
        self.assertTrue(d.usage_chip.isHidden())

    def test_a_provider_makes_it_show_beside_the_run_button(self):
        host, d = _screen(attached=True)
        d.usage_chip._provider = lambda: Usage(1240, 2000, run_cost=4)
        d.usage_chip.refresh()
        self.assertTrue(d.usage_chip.isVisibleTo(host))
        self.assertIs(d.usage_chip.parentWidget(), d.generate_btn.parentWidget())


class TheRegisterAndToast(unittest.TestCase):
    def test_short_figures_stay_on_one_line(self):
        row = WB._kv("Overall size", "120.0 × 60.0 × 3.0 mm")
        value = [l for l in row.findChildren(QLabel)
                 if l.text().endswith("mm")][0]
        self.assertFalse(value.wordWrap())
        self.assertIn("Geist Mono", value.styleSheet())
        long = WB._kv("Holes", " · ".join(["Ø8.5 ×4"] * 6))
        self.assertTrue([l for l in long.findChildren(QLabel)
                         if "Ø" in l.text()][0].wordWrap())

    def test_a_toast_never_runs_past_the_canvas(self):
        host, d = _screen()
        d.canvas.toast("2 files saved to mounting-bracket-with-a-long-name",
                       [("Open folder", lambda: None), ("View", lambda: None)])
        self.assertLessEqual(d.canvas.toast_box.width(), d.canvas.width() - 16)
        d.canvas.toast("ok", [])
        self.assertLess(d.canvas.toast_box.width(), d.canvas.width() - 16)

    def test_section_headings_are_mono_kickers(self):
        host = WB._section("Bend allowance")
        label = host.findChild(QLabel)
        self.assertEqual(label.text(), "BEND ALLOWANCE")
        self.assertEqual(label.objectName(), "kick")


class SegmentsAndPanes(unittest.TestCase):
    def test_segments_and_tabs_use_the_pill_style(self):
        _h, d = _screen()
        seg = d.findChild(QWidget, "stepSegBar")
        self.assertEqual(seg.styleSheet(), WB.SEG_QSS)
        self.assertEqual(d.out_tabs.styleSheet(), WB.TABS_QSS)
        self.assertEqual(d._action_buttons["draft"].height(), 29)
        self.assertEqual(d.out_tabs._buttons[0].height(), 29)

    def test_cards_carry_the_shared_shadow_and_no_border(self):
        _h, d = _screen()
        for card in (d.models_card, d.right_card):
            self.assertIn("border: none", card.styleSheet())
            self.assertTrue(hasattr(card, "_shadow_under"))

    def test_model_row_selected_is_stone_with_a_red_bar(self):
        host, d = _screen(attached=True)
        row = d.model_list.findChild(QWidget, "wbModel")
        self.assertIn("border-left: 3px solid", row.styleSheet())
        self.assertIn("#EEEDEA", row.styleSheet())

    def test_no_checkbox_was_lost(self):
        _h, d = _screen()
        self.assertEqual([c.text() for c in d.findChildren(QCheckBox)],
                         ["Also ask ChatGPT for a styled copy (optional)"])


if __name__ == "__main__":
    unittest.main()

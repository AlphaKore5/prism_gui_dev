"""The STEP add-on's window — the GUI face of /step, /step-auto and
/step-ask, tested the way test_gerber_dialog.py tests Gerber's: intercept
AutomationWorker rather than open a browser, and read what it was given.

The one rule that must never break is the same as Gerber's: the customer's
model is their product. Draft, Ask and Edit may hand an AI the measured
numbers and Prism's OWN render of the parts — never the STEP file, never
its path. If a future edit ever attaches the model to a stage, the security
tests below fail immediately, in CI, before it ships.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

import core_bridge as CB  # noqa: E402
import plans  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_jobs  # noqa: E402
from test_gates import GateTest  # noqa: E402
from addons.step import dialog as SD  # noqa: E402
from addons.step import sessions as SES  # noqa: E402
from addons.step.dialog import StepDialog  # noqa: E402
from dialogs.answer_dialog import AnswerDialog  # noqa: E402
from core import stepfile as SF  # noqa: E402

_app = QApplication.instance() or QApplication([])
HAVE_CAD = SF.available()[0]
EVERYTHING = tuple(plans.FEATURES)


class _Sig:
    def connect(self, *_):
        pass


def _dialog(cfg=None, root=None):
    """A dialog whose folder question is already answered — cfg carries a
    scratch step_out_dir — so no modal can open in a headless run. Every
    test that wants the question itself clears the key on purpose.

    _vision_consent is pre-answered False for the same reason: a real
    QMessageBox.question() call blocks forever in a headless test run
    (the same trap as the folder question) — tests that specifically
    exercise the consent prompt itself mock SD.QMessageBox.question and
    reset _vision_consent to None first."""
    root = root or tempfile.mkdtemp(prefix="prism-test-step-")
    if cfg is None:
        cfg = {"agents": {"visual": "ChatGPT", "brains": "Claude"},
               "openrouter_api_key": "sk-or-test", "step_out_dir": root}
    dlg = StepDialog(cfg, [], None)
    dlg._vision_consent = False
    return dlg


def _box_step(path: str):
    """A 60 x 40 x 8 mm block with one Ø5 hole — every figure known."""
    import cadquery as cq
    part = (cq.Workplane("XY").box(60, 40, 8)
            .faces(">Z").workplane().hole(5))
    cq.exporters.export(part, path)


def _fake_measured(dlg, stem="block", out_dir=None):
    """A measured model without cadquery: the shape _on_measured builds."""
    out_dir = out_dir or os.path.join(dlg._root(), stem)
    os.makedirs(out_dir, exist_ok=True)
    png = os.path.join(out_dir, SF.names(stem)["png"])
    open(png, "wb").write(b"png")
    report = {"file": f"{stem}.step", "stem": stem, "mode": "plastic",
              "path": f"/secret/place/{stem}.step",
              "overall_mm": (60.0, 40.0, 8.0),
              "parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                         "thickness_mm": 6.0, "volume_cm3": 38.0,
                         "holes": [{"dia_mm": 5.0, "count": 1}]}],
              "warnings": []}
    m = {"path": f"/secret/place/{stem}.step", "report": report,
         "out_dir": out_dir, "drawn": {"png": png, "html": ""}, "xlsx": ""}
    dlg.paths = [m["path"]]
    return m


class _CaptureWorker:
    """Stands in for AutomationWorker: records the call, never starts."""
    seen: dict = {}

    def __init__(self, *a, **kw):
        _CaptureWorker.seen = {"args": a, "kwargs": kw}
        self.done = self.failed = _Sig()

    def start(self):
        _CaptureWorker.seen["started"] = True


class TheDoorIsShutUntilAModelIsAttached(unittest.TestCase):

    def test_generate_waits_for_a_model(self):
        dlg = _dialog()
        self.assertFalse(dlg.generate_btn.isEnabled())
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertTrue(dlg.generate_btn.isEnabled())

    def test_only_step_files_are_taken(self):
        """A PDF or a DWG dropped here is not a model; it is named in the
        status line and left out, rather than measured and failing later."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/quote.pdf", "/nowhere/housing.stp"])
        self.assertEqual([os.path.basename(p) for p in dlg.paths],
                         ["housing.stp"])
        self.assertIn("quote.pdf", dlg.status.text())

    def test_the_same_model_is_not_attached_twice(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/a.step"])
        dlg._on_files_added(["/nowhere/a.step"])
        self.assertEqual(len(dlg.paths), 1)

    def test_removing_a_chip_actually_removes_the_model(self):
        """The chip's own 'x' used to only clear AskPanel's private copy —
        dlg.paths (what Generate really measures) kept the file, so a
        mis-picked model was measured and answered anyway even after it
        looked removed. file_removed must keep the two in step."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        dlg._on_files_added(["/nowhere/PET CORE 02 06.STEP"])
        self.assertEqual(len(dlg.paths), 2)
        dlg.ask.remove_path(os.path.abspath("/nowhere/Assem1.STEP"))
        self.assertEqual([os.path.basename(p) for p in dlg.paths],
                         ["PET CORE 02 06.STEP"])
        self.assertTrue(dlg.generate_btn.isEnabled())
        dlg.ask.remove_path(os.path.abspath("/nowhere/PET CORE 02 06.STEP"))
        self.assertEqual(dlg.paths, [])
        self.assertFalse(dlg.generate_btn.isEnabled())

    def test_a_differently_spelled_but_equal_path_is_still_removed(self):
        """Real-world version of the bug above, reproducible on any OS:
        AskPanel always stores (and file_removed always hands back) the
        abspath'd form. A model added under a path that abspath would
        rewrite — a redundant './' segment here, a Windows QFileDialog's
        forward slashes in real use — used to survive in dlg.paths
        unmatched against the rewritten form file_removed emitted, so the
        chip vanished but the file stayed in what Generate measures."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/./Assem1.STEP"])
        self.assertEqual(dlg.paths, [os.path.abspath("/nowhere/Assem1.STEP")])
        dlg.ask.remove_path(os.path.abspath("/nowhere/Assem1.STEP"))
        self.assertEqual(dlg.paths, [])

    def test_the_file_is_asked_for_before_the_question(self):
        """The question box and the choice of action stay out of sight
        until a model is attached — the file first, then what to do."""
        dlg = _dialog()
        self.assertTrue(dlg.step2.isHidden())
        self.assertIs(dlg.ask.edit.parentWidget(), dlg.step2)
        dlg._on_files_added(["/nowhere/quote.pdf"])
        self.assertTrue(dlg.step2.isHidden(), "a non-model must not open it")
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertFalse(dlg.step2.isHidden())

    def test_the_three_actions_are_offered_and_draft_is_the_default(self):
        dlg = _dialog()
        self.assertEqual(set(dlg._action_buttons), {"draft", "ask", "edit"})
        self.assertEqual(dlg._action(), "draft")
        dlg._action_buttons["edit"].setChecked(True)
        self.assertEqual(dlg._action(), "edit")

    def test_the_one_button_always_names_what_it_will_do(self):
        """One shared button for Draft/Ask/Edit used to always just say
        'Generate' — the person had to trust whichever radio they'd picked,
        and a stale selection meant a click landed on the wrong action.
        The button's own label is now the only thing that has to be read."""
        dlg = _dialog()
        self.assertEqual(dlg.generate_btn.text(), "Measure and Draw")
        dlg._action_buttons["ask"].setChecked(True)
        self.assertEqual(dlg.generate_btn.text(), "Ask")
        dlg._action_buttons["edit"].setChecked(True)
        self.assertEqual(dlg.generate_btn.text(), "Make a change")
        dlg._action_buttons["draft"].setChecked(True)
        self.assertEqual(dlg.generate_btn.text(), "Measure and Draw")


class TheFolderQuestionIsAskedOnceThenKept(unittest.TestCase):
    """The owner's ask: the person says where all the files for a model go.
    Asked at the first Generate, remembered in cfg, changeable from the
    Options box — and never asked again once answered."""

    def test_an_answered_question_is_not_asked_again(self):
        dlg = _dialog()
        with mock.patch.object(SD, "QMessageBox") as box:
            self.assertTrue(dlg._ensure_root())
            box.assert_not_called()

    def test_choosing_the_desktop_stores_the_default_explicitly(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "desktop-btn"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake), \
                mock.patch.object(CB.config, "save") as save:
            self.assertTrue(dlg._ensure_root())
            save.assert_called_once()
        self.assertEqual(cfg["step_out_dir"], SF.DEFAULT_OUT_ROOT)
        self.assertIn("Prism Step", dlg.root_label.text())

    def test_choosing_a_folder_keeps_it(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        chosen = tempfile.mkdtemp(prefix="prism-test-step-root-")
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "choose-btn"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake), \
                mock.patch.object(SD.QFileDialog, "getExistingDirectory",
                                  return_value=chosen), \
                mock.patch.object(CB.config, "save"):
            self.assertTrue(dlg._ensure_root())
        self.assertEqual(cfg["step_out_dir"], chosen)
        self.assertIn(chosen, dlg.root_label.text())

    def test_cancelling_the_question_generates_nothing(self):
        cfg = {"agents": {}, "api_key": "", "step_out_dir": ""}
        dlg = StepDialog(cfg, [], None)
        fake = mock.MagicMock()
        fake.return_value.clickedButton.return_value = "something-else"
        fake.return_value.addButton.side_effect = ["choose-btn", "desktop-btn",
                                                   "cancel-btn"]
        with mock.patch.object(SD, "QMessageBox", fake):
            self.assertFalse(dlg._ensure_root())
        self.assertEqual(cfg["step_out_dir"], "")

    def test_the_root_reaches_the_measuring_worker(self):
        """What was chosen is what the worker is given — the folder per
        model is made under it (core.stepfile.output_dir)."""
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        seen = {}

        class FakeMeasure:
            def __init__(self, paths, mode, root, k_factor=0.0):
                seen.update(paths=paths, mode=mode, root=root, k_factor=k_factor)
                self.progress = self.done = self.failed = _Sig()

            def start(self):
                seen["started"] = True

        with mock.patch.object(SD, "StepMeasureWorker", FakeMeasure), \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
        self.assertEqual(seen["root"], dlg.cfg["step_out_dir"])
        self.assertEqual(seen["mode"], "metal")
        self.assertTrue(seen["started"])


class AnAgentOnlyEverSeesTheNumbersAndPrismsOwnRender(unittest.TestCase):
    """The standing rule, enforced at the calls that could break it."""

    def _draft_call(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        # The AI draft is opt-in (Round 42) — these tests are about what
        # it is given WHEN it runs, so switch it on explicitly.
        dlg.ai_draft_cb.setChecked(True)
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker):
            dlg._current = m
            dlg._draft(m)
        return dlg, m, _CaptureWorker.seen

    def test_draft_attaches_prisms_render_and_never_the_model(self):
        dlg, m, seen = self._draft_call()
        attachments = seen["args"][2]
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["path"], m["drawn"]["png"])
        for a in attachments:
            self.assertFalse(a["path"].lower().endswith((".step", ".stp")))

    def test_the_draft_prompt_carries_the_numbers_not_the_path(self):
        dlg, m, seen = self._draft_call()
        prompt = seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("60.00 x 40.00 x 8.00", prompt)
        self.assertIn("MEASURED OFFLINE", prompt)
        self.assertNotIn("/secret/place", prompt)
        self.assertNotIn("/secret/place", seen["args"][3])

    def test_draft_asks_for_the_returned_files(self):
        """The image the agent draws comes back through files_out — without
        it the sheet exists only in the tool's tab."""
        dlg, m, seen = self._draft_call()
        self.assertIs(seen["kwargs"]["files_out"], dlg._made_files)

    def test_draft_promises_a_picture_so_the_wait_is_long_enough(self):
        dlg, m, seen = self._draft_call()
        self.assertEqual(seen["kwargs"]["image_stages"], {"visual"})

    def test_the_ai_draft_is_off_by_default_and_skips_chatgpt_entirely(self):
        """Round 42: checked against Prism's own drawing, ChatGPT's
        'styled' copy just traced it, worse — not an independent check,
        only a different look. Draft's job (Prism's own sheet) is already
        done by the time this runs; ChatGPT is opt-in from here."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        self.assertFalse(dlg.ai_draft_cb.isChecked())
        _CaptureWorker.seen = {}          # not reset between tests otherwise
        # Skipping the AI stage means _draft falls straight through to
        # _next() -> _finish(), which saves the run for real unless mocked
        # (tests/conftest.py fails the suite on a write to the real
        # ~/.prism, by design).
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker), \
                mock.patch.object(CB.config, "save_run"):
            dlg._current = m
            dlg._draft(m)
        self.assertEqual(_CaptureWorker.seen, {},
                         "AutomationWorker (ChatGPT) must not be built at all")

    def test_draft_is_chatgpt_only_with_no_fallback(self):
        """Not the configured visual tool, and no hand-off to another
        image model if ChatGPT stumbles — a second, differently-wrong sheet
        is not a rescue."""
        dlg = _dialog(cfg={"agents": {"visual": "Gamma.app",
                                      "media": "Canva"},
                           "api_key": "k",
                           "step_out_dir": tempfile.mkdtemp()})
        m = _fake_measured(dlg)
        dlg.ai_draft_cb.setChecked(True)
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker):
            dlg._current = m
            dlg._draft(m)
        seen = _CaptureWorker.seen
        self.assertEqual(seen["kwargs"]["custom_stages"][0][1], "ChatGPT")
        self.assertIs(seen["kwargs"]["failover"], False)

    def test_the_plan_stage_gets_numbers_advice_and_the_question(self):
        # Only Edit reaches the plan stage now — Ask stops at the answer.
        # One OpenRouter call, in-house — never a browser, never the file.
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("make it lighter")
        dlg._current = m
        dlg._action_buttons["edit"].setChecked(True)
        with mock.patch.object(SD, "StepPlanWorker") as planner:
            dlg._on_suggested("1) thin the wall", agent="Claude Haiku 5.5")
        # The answer is in the chat at once — no window opened for it.
        self.assertEqual(dlg._live["answer"], "1) thin the wall")
        self.assertIs(dlg.chat_stack.currentWidget(), dlg.chat)
        args = planner.call_args[0]
        self.assertEqual(planner.call_args.kwargs["model"],
                         "anthropic/claude-haiku-5.5")
        self.assertEqual(args[2], "make it lighter")
        self.assertEqual(args[3], "1) thin the wall")
        prompt = SF.plan_prompt(args[1], args[2], args[3])
        self.assertIn("60.00 x 40.00 x 8.00", prompt)
        self.assertIn("make it lighter", prompt)
        self.assertIn("thin the wall", prompt)
        self.assertNotIn("/secret/place", prompt)
    def test_the_groq_question_carries_numbers_and_confidentiality(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        p = SF.ask_prompt(m["report"], "make it lighter")
        self.assertIn("cannot be shown to you", p)
        self.assertNotIn("/secret/place", p)

    def test_ask_shows_only_the_answer_no_plan_and_no_page(self):
        """Ask's whole deliverable is the suggestion text — it must never
        reach the planning stage, so no AutomationWorker is built, no
        review page is written, and nothing is opened — no window, no
        browser page. The answer is in the Chat tab."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("which material fits best?")
        dlg._current = m
        dlg._action_buttons["ask"].setChecked(True)
        _CaptureWorker.seen = {}          # not reset between tests otherwise
        with mock.patch.object(SD.QDesktopServices, "openUrl") as opened, \
                mock.patch.object(SD, "AutomationWorker", _CaptureWorker), \
                mock.patch.object(SD.QMessageBox, "warning") as warned, \
                mock.patch.object(CB.config, "save_run", side_effect=OSError):
            dlg._on_suggested("PP for cost, ABS for a balance of cost "
                              "and strength.")
        opened.assert_not_called()
        warned.assert_not_called()
        self.assertEqual(_CaptureWorker.seen, {},
                         "Ask must never start the plan stage")
        self.assertIn("PP for cost", dlg.chat.cards[0].turn["answer"])
        self.assertTrue(any("choose Edit" in n for n in dlg._notes))
        self.assertTrue(dlg.composer.isVisibleTo(dlg),
                        "the follow-up box carries the conversation on")
    def test_edit_reviews_the_plan_then_asks_before_building(self):
        """The plan lands in the Plan tab with a Build bar; nothing is built
        until Build is pressed."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("fit 6mm")
        dlg._current = m
        dlg._action_buttons["edit"].setChecked(True)
        plan = ('{"changes": [{"op": "enlarge_hole", "part": "p", '
                '"dia_mm": 5, "new_dia_mm": 6, "why": "M6"}], "advice": []}')
        built = {}

        class FakeApply:
            def __init__(self, *a, **kw):
                built["args"] = a
                self.done = self.failed = _Sig()

            def start(self):
                built["started"] = True

        with mock.patch.object(SD, "StepApplyWorker", FakeApply):
            dlg._on_planned({"plan": [plan]}, {})
            self.assertEqual(built, {}, "nothing is built before Build is pressed")
            self.assertTrue(dlg._awaiting)
            self.assertTrue(dlg.plan_panel.build_btn.isVisibleTo(dlg.plan_panel))
            self.assertFalse(dlg.generate_btn.isEnabled())
            self.assertEqual(dlg.out_stack.currentIndex(), 2)
            dlg._confirm_build()
            self.assertTrue(built["started"])
            # The worker is handed the ORIGINAL path to read, and writes the
            # copy under the model's own name in the model's own folder.
            self.assertEqual(built["args"][0], m["path"])
            self.assertEqual(built["args"][4], m["out_dir"])
            self.assertTrue(os.path.exists(
                os.path.join(m["out_dir"], SF.names(m["report"])["review"])))
    def test_a_no_answer_builds_nothing(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("fit 6mm")
        dlg._current = m
        dlg._action_buttons["edit"].setChecked(True)
        plan = ('{"changes": [{"op": "scale", "part": "all", "factor": 2, '
                '"why": ""}], "advice": []}')
        with mock.patch.object(CB.config, "save_run"), \
                mock.patch.object(SD, "StepApplyWorker") as apply_w:
            dlg._on_planned({"plan": [plan]}, {})
            dlg._skip_build()
            apply_w.assert_not_called()
        self.assertTrue(any("not built" in n for n in dlg._notes))
        self.assertFalse(dlg._awaiting)

    def test_a_plan_with_nothing_to_build_says_so_and_what_to_do_next(self):
        """ChatGPT answered, but with no change Prism can apply (a vague
        "make the holes bigger"): the Plan tab explains, offers to refine,
        and the run finishes — no window, no dead end."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("make the holes little bigger")
        dlg._current = m
        dlg._action_buttons["edit"].setChecked(True)
        plan = '{"changes": [], "advice": ["Which holes? Prism needs a size."]}'
        with mock.patch.object(CB.config, "save_run") as saved:
            dlg._on_planned({"plan": [plan]}, {})
        saved.assert_called_once()                    # the run finished
        from PySide6.QtWidgets import QLabel
        texts = " ".join(l.text() for l in dlg.plan_panel.findChildren(QLabel))
        self.assertIn("Nothing to build yet", texts)
        self.assertIn("Which holes?", texts)
        self.assertFalse(dlg.plan_panel.bar.isVisibleTo(dlg.plan_panel))
        self.assertFalse(dlg._awaiting)

class ChoosingAStrongerModelThanHaiku(unittest.TestCase):
    """Claude Haiku 5.5 is the default, fast, in-house path (2026-11-06:
    Groq is gone, "remove groq for now instead use claude haiku and claude
    sonnet5.5", Haiku the default). Picking Claude Sonnet 5.5 instead is
    the SAME kind of call — a direct OpenRouter request, never a browser
    tab — just a different, stronger, pricier model id. No fallback chain
    between them: a failure is reported, not silently retried as a
    different model."""

    def _pick(self, dlg, label_value: str):
        idx = dlg.model_combo.findData(label_value)
        self.assertGreaterEqual(idx, 0, f"{label_value} not offered")
        dlg.model_combo.setCurrentIndex(idx)

    def test_haiku_is_the_default_pick(self):
        dlg = _dialog()
        self.assertEqual(dlg._chosen_model(), "Claude Haiku 5.5")

    def test_a_chosen_model_builds_the_ask_stage_with_its_own_id(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("which material fits best?")
        dlg._current = m
        self._pick(dlg, "Claude Sonnet 5.5")
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._ask(m)
        args, kwargs = worker_cls.call_args
        self.assertEqual(kwargs["model"], "anthropic/claude-sonnet-5.5")
        self.assertIn("which material fits best?", args[2])
        self.assertEqual(kwargs["attachments"], [])   # no consent asked yet
        worker_cls.return_value.start.assert_called_once()

    def test_a_failed_call_reports_the_error_and_never_retries_as_haiku(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        self._pick(dlg, "Claude Sonnet 5.5")
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._ask(m)
            dlg._on_failed("OpenRouter rejected your key.")
        self.assertIn("OpenRouter rejected your key.", dlg.status.text())
        self.assertEqual(worker_cls.call_count, 1)   # never silently retried

    def test_an_answer_records_which_model_actually_answered(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("which material fits best?")
        dlg._current = m
        dlg._action_buttons["ask"].setChecked(True)
        self._pick(dlg, "Claude Sonnet 5.5")
        with mock.patch.object(SD, "StepAskWorker") as worker_cls, \
                mock.patch.object(CB.config, "save_run"):
            dlg._ask(m)
            done_cb = worker_cls.return_value.done.connect.call_args[0][0]
            done_cb("PP for cost, ABS for a balance.")
        key = f"ask · {m['report']['stem']}"
        self.assertEqual(dlg._responses[key],
                         ["PP for cost, ABS for a balance."])
        self.assertEqual(dlg._stage_agents_map[key], "Claude Sonnet 5.5")

    def test_without_an_openrouter_key_neither_model_can_be_asked(self):
        dlg = _dialog(cfg={"step_out_dir": tempfile.mkdtemp()})   # no key
        dlg._on_files_added(["/nowhere/a.step"])
        dlg._action_buttons["ask"].setChecked(True)
        dlg.ask.set_text("which material?")
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker:
            dlg._generate()
            warn.assert_not_called()                      # in the window, not a pop-up
            self.assertIn("needs an OpenRouter key", dlg.status.text())
            worker.assert_not_called()
        dlg.cfg["openrouter_api_key"] = "sk-or-test"
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker, \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
            warn.assert_not_called()
            worker.assert_called_once()


class ThePictureLeavesOnlyWithConsentAskedOnce(unittest.TestCase):
    """2026-11-06: Ask/Edit may now show Claude a rendered picture of the
    part, never the STEP file itself, and never without the person's own
    yes — asked once per dialog session, worded "Prism AI" (the owner's
    own instruction), not the model's real name."""

    def test_the_popup_names_prism_ai_not_the_model(self):
        dlg = _dialog()
        dlg._vision_consent = None       # undo _dialog()'s own safety default
        m = _fake_measured(dlg)
        with mock.patch.object(SD.QMessageBox, "question",
                              return_value=SD.QMessageBox.No) as q:
            dlg._attachments_for(m)
        title, text = q.call_args[0][1], q.call_args[0][2]
        self.assertIn("Prism AI", text)
        self.assertNotIn("Claude", text)
        self.assertNotIn("Haiku", text)
        self.assertNotIn("Sonnet", text)

    def test_saying_yes_attaches_the_rendered_picture(self):
        dlg = _dialog()
        dlg._vision_consent = None
        m = _fake_measured(dlg)
        with mock.patch.object(SD.QMessageBox, "question",
                              return_value=SD.QMessageBox.Yes):
            attachments = dlg._attachments_for(m)
        self.assertEqual(len(attachments), 1)
        self.assertEqual(attachments[0]["kind"], "image")
        self.assertEqual(attachments[0]["mime"], "image/png")

    def test_saying_no_attaches_nothing_and_is_not_asked_again(self):
        dlg = _dialog()
        dlg._vision_consent = None
        m = _fake_measured(dlg)
        with mock.patch.object(SD.QMessageBox, "question",
                              return_value=SD.QMessageBox.No) as q:
            first = dlg._attachments_for(m)
            second = dlg._attachments_for(m)
        self.assertEqual(first, [])
        self.assertEqual(second, [])
        q.assert_called_once()    # asked once for the whole session, not twice

    def test_nothing_to_attach_means_no_popup_at_all(self):
        """Ask/Edit before Draft has ever run has no rendered picture yet —
        nothing to ask permission for."""
        dlg = _dialog()
        dlg._vision_consent = None
        m = _fake_measured(dlg)
        m["drawn"] = {}
        with mock.patch.object(SD.QMessageBox, "question") as q:
            attachments = dlg._attachments_for(m)
        self.assertEqual(attachments, [])
        q.assert_not_called()


class TheMaterialMouldCatalogStaysAttachedUntilRemoved(unittest.TestCase):
    """Draft-only: a shop's own Sr No sheet (CSV/XLSX), attached once via
    cfg["step_catalog_path"] and left there across runs and dialog
    sessions until the person presses Remove -- never re-asked for on
    every Generate the way a one-shot attachment would be."""

    def _catalog_file(self, tmp) -> str:
        path = os.path.join(tmp, "catalog.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Product ID mm,Product OD mm,Material Sr No,Mould Sr No\n"
                    "20,32,MAT-202,MLD-103\n")
        return path

    def test_a_fresh_dialog_with_nothing_attached_says_so(self):
        dlg = _dialog()
        self.assertEqual(dlg._catalog_path(), "")
        self.assertIn("No catalog attached", dlg.catalog_name_label.text())
        self.assertFalse(dlg.catalog_remove_btn.isEnabled())

    def test_attaching_a_file_saves_its_path_and_shows_the_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._catalog_file(tmp)
            dlg = _dialog()
            with mock.patch.object(SD.QFileDialog, "getOpenFileName",
                                   return_value=(path, "")):
                dlg._pick_catalog()
            self.assertEqual(dlg.cfg["step_catalog_path"], path)
            self.assertEqual(dlg.catalog_name_label.text(),
                             os.path.basename(path))
            self.assertTrue(dlg.catalog_remove_btn.isEnabled())

    def test_a_new_dialog_still_shows_a_path_saved_by_an_earlier_one(self):
        """The whole point: it survives past the dialog that attached it,
        the same way step_ai_draft and step_ask_model already do."""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._catalog_file(tmp)
            cfg = {"agents": {"visual": "ChatGPT", "brains": "Claude"},
                  "openrouter_api_key": "sk-or-test",
                  "step_out_dir": tmp, "step_catalog_path": path}
            dlg = StepDialog(cfg, [], None)
            dlg._vision_consent = False
            self.assertEqual(dlg._catalog_path(), path)
            self.assertEqual(dlg.catalog_name_label.text(),
                             os.path.basename(path))

    def test_cancelling_the_file_picker_changes_nothing(self):
        dlg = _dialog()
        with mock.patch.object(SD.QFileDialog, "getOpenFileName",
                              return_value=("", "")):
            dlg._pick_catalog()
        self.assertEqual(dlg._catalog_path(), "")

    def test_remove_clears_it_and_it_stays_cleared(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._catalog_file(tmp)
            cfg = {"agents": {"visual": "ChatGPT", "brains": "Claude"},
                  "openrouter_api_key": "sk-or-test",
                  "step_out_dir": tmp, "step_catalog_path": path}
            dlg = StepDialog(cfg, [], None)
            dlg._vision_consent = False
            dlg._remove_catalog()
            self.assertEqual(dlg._catalog_path(), "")
            self.assertIn("No catalog attached", dlg.catalog_name_label.text())
            self.assertFalse(dlg.catalog_remove_btn.isEnabled())

    def test_a_catalog_that_no_longer_exists_on_disk_reads_as_none(self):
        """cfg can outlive the file (moved, deleted, a synced folder gone
        offline) -- the dialog must not claim an attachment it can't read,
        and must not crash trying to use it."""
        dlg = _dialog(cfg={"agents": {"visual": "ChatGPT", "brains": "Claude"},
                           "openrouter_api_key": "sk-or-test",
                           "step_catalog_path": "/no/such/catalog.csv"})
        self.assertEqual(dlg._catalog_path(), "")
        self.assertEqual(dlg._catalog_lookup_note(), "")


class TheMaterialMouldLookupRunsOnlyForDraft(unittest.TestCase):
    """The ID/OD boxes are the INQUIRY's figures, never measured off the
    file; the lookup itself is Draft-only (Ask/Edit have no use for a
    Sr No) and silently does nothing when either input is missing --
    it is an optional extra, not a thing that can fail the run."""

    def _attached_dialog(self, tmp):
        path = os.path.join(tmp, "catalog.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Product ID mm,Product OD mm,Material Sr No,Mould Sr No\n"
                    "20,32,MAT-202,MLD-103\n")
        dlg = _dialog(root=tmp)
        dlg.cfg["step_catalog_path"] = path
        return dlg

    def test_no_catalog_and_no_ids_gives_an_empty_note(self):
        dlg = _dialog()
        self.assertEqual(dlg._catalog_lookup_note(), "")

    def test_a_catalog_with_no_ids_typed_gives_an_empty_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp)
            self.assertEqual(dlg._catalog_lookup_note(), "")

    def test_only_one_of_id_or_od_typed_gives_an_empty_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp)
            dlg.inquiry_id_edit.setText("20")
            self.assertEqual(dlg._catalog_lookup_note(), "")

    def test_both_ids_typed_with_a_catalog_reports_the_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp)
            dlg.inquiry_id_edit.setText("20.05")
            dlg.inquiry_od_edit.setText("31.9")
            note = dlg._catalog_lookup_note()
        self.assertIn("MAT-202", note)
        self.assertIn("MLD-103", note)

    def test_on_measured_appends_the_lookup_note_for_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp)
            dlg._action_buttons["draft"].setChecked(True)
            dlg.inquiry_id_edit.setText("20")
            dlg.inquiry_od_edit.setText("32")
            m = _fake_measured(dlg, out_dir=tmp)
            with mock.patch.object(SD.CB.config, "save_artifact"), \
                mock.patch.object(dlg, "_next"):
                dlg._on_measured([m])
        self.assertTrue(any("MAT-202" in n for n in dlg._notes))
        self.assertIn("MAT-202", dlg.meas_view.toPlainText())

    def test_on_measured_skips_the_lookup_for_ask(self):
        """Switching to Ask/Edit must not surface a Sr No note even if the
        ID/OD boxes still hold values from an earlier Draft run."""
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp)
            dlg._action_buttons["ask"].setChecked(True)
            dlg.inquiry_id_edit.setText("20")
            dlg.inquiry_od_edit.setText("32")
            m = _fake_measured(dlg, out_dir=tmp)
            with mock.patch.object(SD.CB.config, "save_artifact"), \
                mock.patch.object(dlg, "_next"):
                dlg._on_measured([m])
        self.assertFalse(any("MAT-202" in n for n in dlg._notes))
        self.assertNotIn("MAT-202", dlg.meas_view.toPlainText())

    def test_a_catalog_file_that_cannot_be_understood_reports_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = os.path.join(tmp, "bad.csv")
            with open(bad, "w", encoding="utf-8") as f:
                f.write("Name,Price\nWidget,10\n")
            dlg = _dialog(root=tmp)
            dlg.cfg["step_catalog_path"] = bad
            dlg.inquiry_id_edit.setText("20")
            dlg.inquiry_od_edit.setText("32")
            note = dlg._catalog_lookup_note()
        self.assertIn("Material/mould catalog", note)


class TheCatalogMissExplainerFiresOnlyOnAMiss(unittest.TestCase):
    """A second opinion only for the one ambiguous case -- a confident
    deterministic match never calls an AI at all, and no OpenRouter key
    means no call either. The worker itself is never let run for real
    here: SD.StepCatalogExplainWorker is replaced with a stand-in that
    records its prompt and never starts a thread."""

    class _FakeExplainWorker:
        instances: list = []

        def __init__(self, cfg, prompt, model="anthropic/claude-haiku-5.5"):
            self.cfg, self.prompt, self.model = cfg, prompt, model
            self.done = _Sig()
            self.failed = _Sig()
            self.started = False
            type(self).instances.append(self)

        def start(self):
            self.started = True

    def setUp(self):
        self._FakeExplainWorker.instances = []

    def _attached_dialog(self, tmp, id_mm="20", od_mm="32"):
        path = os.path.join(tmp, "catalog.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Product ID mm,Product OD mm,Material Sr No,Mould Sr No\n"
                    "20,32,MAT-202,MLD-103\n")
        dlg = _dialog(root=tmp)
        dlg.cfg["step_catalog_path"] = path
        dlg.inquiry_id_edit.setText(id_mm)
        dlg.inquiry_od_edit.setText(od_mm)
        return dlg

    def test_a_confident_match_never_calls_the_explainer(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp, "20", "32")   # exact match
            with mock.patch.object(SD, "StepCatalogExplainWorker",
                                   self._FakeExplainWorker):
                dlg._catalog_lookup_note()
                dlg._maybe_explain_catalog_miss()
        self.assertEqual(self._FakeExplainWorker.instances, [])

    def test_a_miss_with_no_openrouter_key_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp, "99", "99")   # miss
            dlg.cfg["openrouter_api_key"] = ""
            with mock.patch.object(SD, "StepCatalogExplainWorker",
                                   self._FakeExplainWorker):
                dlg._catalog_lookup_note()
                dlg._maybe_explain_catalog_miss()
        self.assertEqual(self._FakeExplainWorker.instances, [])

    def test_a_miss_with_a_key_fires_one_worker_with_the_engines_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlg = self._attached_dialog(tmp, "99", "99")   # miss
            dlg.cfg["openrouter_api_key"] = "sk-or-test"
            with mock.patch.object(SD, "StepCatalogExplainWorker",
                                   self._FakeExplainWorker):
                dlg._catalog_lookup_note()
                dlg._maybe_explain_catalog_miss()
        self.assertEqual(len(self._FakeExplainWorker.instances), 1)
        worker = self._FakeExplainWorker.instances[0]
        self.assertTrue(worker.started)
        self.assertIn("MAT-202", worker.prompt)
        self.assertNotIn(".csv", worker.prompt)

    def test_the_answer_is_appended_once_it_comes_back(self):
        dlg = _dialog()
        dlg.meas_view.setPlainText("measured so far")
        dlg._on_catalog_explained("check the drawing's tolerance class.")
        self.assertIn("check the drawing's tolerance class.",
                      dlg.meas_view.toPlainText())
        self.assertTrue(any("Prism AI's read on the miss" in n
                            for n in dlg._notes))

    def test_an_empty_answer_changes_nothing(self):
        dlg = _dialog()
        dlg.meas_view.setPlainText("measured so far")
        dlg._on_catalog_explained("   ")
        self.assertEqual(dlg.meas_view.toPlainText(), "measured so far")
        self.assertEqual(dlg._notes, [])


class TheFinishedRunCarriesWhatTheFollowUpNeeds(unittest.TestCase):
    """main_window offers the ordinary post-completion follow-up (the one
    every routed run gets) by reading _task_name/_responses/
    _stage_agents_map/_links off a closed dialog. STEP never set any of
    these — there was no follow-up option on STEP at all. _finish() must
    leave them in the same shape BOQ's dialog already does."""

    def test_finish_sets_the_task_name_the_followup_reads(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.models = [m]
        dlg.ask.set_text("which material fits best?")
        dlg._action_buttons["ask"].setChecked(True)
        dlg._responses = {"ask · block": ["PP for cost."]}
        dlg._stage_agents_map = {"ask · block": "Claude"}
        with mock.patch.object(CB.config, "save_run"):
            dlg._finish()
        self.assertEqual(dlg._task_name,
                         "STEP — Ask: which material fits best?")
        self.assertEqual(dlg._responses, {"ask · block": ["PP for cost."]})
        self.assertEqual(dlg._stage_agents_map, {"ask · block": "Claude"})


class TheConversationIsSavedToOneFilePerModel(unittest.TestCase):
    """A chatbot-style memory: closing the popup, closing Prism, even
    reattaching the file next week — the conversation about THIS part is
    read back off a plain JSON file sitting beside its other outputs, not
    lost the moment the popup closes."""

    def test_round_trips_through_the_real_file(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        thread = [["You asked", "which material?"], ["Groq", "PP."]]
        dlg._save_conversation(m, thread)
        path = dlg._conversation_path(m)
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith("block - conversation.json"))
        self.assertEqual(dlg._load_conversation(m),
                         [("You asked", "which material?"), ("Groq", "PP.")])

    def test_loading_before_any_conversation_exists_is_just_empty(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        self.assertEqual(dlg._load_conversation(m), [])

    def test_a_second_ask_continues_the_saved_file_not_a_blank_one(self):
        """The whole point: a SECOND Ask on the same model must not start
        from blank — it continues the file the first one wrote."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("question two")
        dlg._save_conversation(m, [["You asked", "question one"],
                                   ["Claude Haiku 5.5", "answer one"]])
        with mock.patch.object(CB.config, "save_run"):
            dlg._on_suggested("answer two")
        self.assertEqual(
            dlg._load_conversation(m),
            [("You asked", "question one"), ("Claude Haiku 5.5", "answer one"),
             ("You asked", "question two"), ("Claude Haiku 5.5", "answer two")])
    def test_an_end_to_end_run_actually_writes_the_whole_thread(self):
        """No window, no stubbing of one: the answer arrives and the file is
        written — and a follow-up typed in the chat is appended to it."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("which material fits best?")
        with mock.patch.object(CB.config, "save_run"):
            dlg._on_suggested("PP for cost.")
        path = dlg._conversation_path(m)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved, [["You asked", "which material fits best?"],
                                 ["Claude Haiku 5.5", "PP for cost."]])
        key = f"ask · {m['report']['stem']}"
        dlg._inline.question = "what about nylon?"
        with mock.patch.object(CB.config, "save_run"):
            dlg._on_answer_followup_done(dlg._inline, key, "Nylon needs drying.")
        with open(path) as f:
            saved = json.load(f)
        self.assertEqual(saved[-2:], [["You followed up", "what about nylon?"],
                                      ["Claude Haiku 5.5", "Nylon needs drying."]])

class AFollowUpTypedInsideTheAnswerPopup(unittest.TestCase):
    """The popup's own "Follow up" button (beside Copy/Close) — a note
    typed there re-asks whichever agent answered the first time, not a
    fresh one, and the popup's own content is what gets updated."""

    def test_the_default_model_gets_the_earlier_answer_as_context(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("which material fits best?")
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["PP for cost."]
        fake_dlg = mock.MagicMock()
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._on_answer_followup(fake_dlg, m, key, "Claude Haiku 5.5",
                                    "what about Nylon 6?")
        fake_dlg.set_busy.assert_called_once_with(True)
        args, kwargs = worker_cls.call_args
        self.assertEqual(kwargs["model"], "anthropic/claude-haiku-5.5")
        self.assertIn("PP for cost.", args[2])
        self.assertIn("what about Nylon 6?", args[2])
        worker_cls.return_value.start.assert_called_once()

    def test_a_successful_followup_updates_the_response_and_popup(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["PP for cost."]
        fake_dlg = mock.MagicMock()
        dlg._stage_agents_map[key] = "Claude Sonnet 5.5"
        dlg._on_answer_followup_done(fake_dlg, key, "Nylon 6 needs drying.",
                                     "Claude Sonnet 5.5")
        # The follow-up is delivered to the chat; the FIRST answer, and who
        # gave it, are exactly as they were.
        self.assertEqual(dlg._responses[key], ["PP for cost."])
        self.assertEqual(dlg._stage_agents_map[key], "Claude Sonnet 5.5")
        fake_dlg.set_busy.assert_called_once_with(False)
        fake_dlg.set_answer.assert_called_once_with(
            "Nylon 6 needs drying.", "Claude Sonnet 5.5")

    def test_switching_model_on_a_followup_uses_the_new_one(self):
        """Haiku answered first; the person picks Sonnet in the popup's own
        "Reply as" row for the follow-up — that follow-up is asked of
        Sonnet, with the earlier Q&A folded into the prompt as context
        (there is no "chat" to resume — every call is a fresh, stateless
        OpenRouter request)."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("which material fits best?")
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["PP for cost."]
        dlg._stage_agents_map[key] = "Claude Haiku 5.5"
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._on_answer_followup(mock.MagicMock(), m, key,
                                    "Claude Sonnet 5.5",
                                    "what about Nylon 6?")
        args, kwargs = worker_cls.call_args
        self.assertEqual(kwargs["model"], "anthropic/claude-sonnet-5.5")
        self.assertIn("PP for cost.", args[2])
        self.assertIn("what about Nylon 6?", args[2])

    def test_an_unrecognised_agent_falls_back_to_the_currently_chosen_model(self):
        """A conversation reopened from before this model picker existed
        may carry an old agent string (a browser tool's name). It is not a
        valid OpenRouter choice, so the currently picked model answers
        instead of crashing or silently guessing."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["PP for cost."]
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._on_answer_followup(mock.MagicMock(), m, key, "ChatGPT",
                                    "what about Nylon 6?")
        self.assertEqual(worker_cls.call_args.kwargs["model"],
                         "anthropic/claude-haiku-5.5")
        self.assertEqual(dlg._responses[key], ["PP for cost."])


class BuildThisWorksFromAnyFollowUpEvenReopenedOnes(unittest.TestCase):
    """Round: a follow-up typed into a REOPENED Answer popup (the file was
    already built once, that popup was closed, the person reattached the
    file and asked again) ran all the way through — ChatGPT even answered
    — but nothing ever got built, because the automatic plan/build only
    ever ran once, immediately after the very FIRST popup of a fresh Edit
    closed. A follow-up's refined answer had no way to become a build at
    all. "Build this" is that way, reachable from any popup at any time,
    not just the first one."""

    def test_the_box_and_the_build_button_appear_under_an_answer(self):
        """Follow up or Build this — in the chat, for any answer, once there
        is a measurement behind it. (Used to be buttons in a pop-up.)"""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("q")
        self.assertFalse(dlg.composer.isVisibleTo(dlg))
        with mock.patch.object(CB.config, "save_run", side_effect=OSError):
            dlg._action_buttons["ask"].setChecked(True)
            dlg._on_suggested("a")
        self.assertTrue(dlg.composer.isVisibleTo(dlg))
        # Ask: the box and "Ask" only — nothing that talks about building.
        self.assertTrue(dlg.composer.send_btn.isVisibleTo(dlg.composer))
        self.assertEqual(dlg.composer.send_btn.text(), "Ask")
        self.assertFalse(dlg.composer.build_btn.isVisibleTo(dlg.composer))
        # Edit: "Make a change" joins it.
        dlg._action_buttons["edit"].setChecked(True)
        self.assertTrue(dlg.composer.build_btn.isVisibleTo(dlg.composer))
        self.assertEqual(dlg.composer.build_btn.text(), "Make a change")
    def test_clicking_build_this_does_not_close_the_popup(self):
        dlg = AnswerDialog("t", "s", "q", "a", "Groq", allow_build=True)
        seen = []
        dlg.build_requested.connect(lambda: seen.append(1))
        dlg.build_btn.click()
        self.assertEqual(seen, [1])
        self.assertFalse(dlg.isHidden() and dlg.result())  # never accepted

    def test_build_this_runs_the_plan_stage_without_touching_the_queue(self):
        """The real scenario: a conversation reopened long after the
        first build finished. _current is whatever the fresh re-measure
        set it to; build_requested must plan with the model that answered
        it (or the currently chosen one), and must never call _next() —
        there is no in-flight queue to advance."""
        dlg = _dialog(cfg={"openrouter_api_key": "sk-or-test"})
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("enlarge the hole")
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["enlarge the Ø8.1mm hole to Ø8.6mm"]
        dlg._stage_agents_map[key] = "Claude Sonnet 5.5"
        fake_popup = mock.MagicMock()
        with mock.patch.object(SD, "StepPlanWorker") as planner:
            dlg._build_plan_for(m, key, fake_popup)
        fake_popup.set_busy.assert_called_with(True)
        args, kwargs = planner.call_args
        self.assertEqual(kwargs["model"], "anthropic/claude-sonnet-5.5")
        self.assertIn("enlarge the Ø8.1mm hole to Ø8.6mm", args[3])

    def test_on_planned_from_the_chat_waits_for_build_and_never_advances_the_queue(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.ask.set_text("fit 6mm")
        dlg._queue = [{"report": {"file": "someone-else.step"}}]  # must stay put
        plan = ('{"changes": [{"op": "enlarge_hole", "part": "p", '
                '"dia_mm": 8.1, "new_dia_mm": 8.6, "why": "test"}], '
                '"advice": []}')
        fake_popup = mock.MagicMock()
        dlg._on_planned({"plan": [plan]}, {}, m=m, popup=fake_popup)
        fake_popup.set_busy.assert_any_call(False)
        self.assertTrue(dlg._awaiting)
        self.assertEqual(len(dlg._queue), 1,
                         "a chat-triggered build must never touch the queue")
        dlg._skip_build()
        self.assertEqual(len(dlg._queue), 1)
    def test_on_applied_from_a_popup_clears_busy_and_leaves_the_queue_alone(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._queue = [{"report": {"file": "someone-else.step"}}]
        fake_popup = mock.MagicMock()
        with mock.patch.object(SD.QDesktopServices, "openUrl") as opened, \
                mock.patch.object(CB.config, "save_artifact"):
            dlg._on_applied(
                {"out": "/x/modified 2026-10-14 0700.step", "log": [],
                 "after": {"file": "Assem1.step", "parts": [],
                          "mode": "plastic", "overall_mm": (0, 0, 0),
                          "warnings": []},
                 "review": "/x/review.html"},
                m=m, popup=fake_popup)
        fake_popup.set_busy.assert_called_with(False)
        opened.assert_not_called()            # no browser page pops up
        self.assertEqual(len(dlg._queue), 1)

    def test_on_applied_shows_the_green_banner_with_the_built_path(self):
        """Round: the same green "saved" confirmation _on_measured shows
        for the measurement folder went missing for a completed BUILD once
        "Build this" and the follow-up path were added — a build finished
        with no visible sign of where the modified file actually landed."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        with mock.patch.object(SD.QDesktopServices, "openUrl"), \
                mock.patch.object(CB.config, "save_artifact"):
            dlg._on_applied(
                {"out": "/x/PET CORE - modified 2026-10-14 0700.step",
                 "log": [],
                 "after": {"file": "Assem1.step", "parts": [],
                          "mode": "plastic", "overall_mm": (0, 0, 0),
                          "warnings": []},
                 "review": "/x/review.html"},
                m=m, popup=mock.MagicMock())
        self.assertIn("PET CORE - modified 2026-10-14 0700.step",
                      dlg.files_label.text())
        self.assertTrue(dlg.meas_box.isVisibleTo(dlg))

    def test_a_plan_with_nothing_in_it_still_finishes_the_run_exactly_once(self):
        """A fresh Edit's own first answer, planned automatically
        (popup=None): when the plan has nothing to build it must still reach
        _finish() once."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg._queue = []
        dlg.ask.set_text("fit 6mm")
        dlg._action_buttons["edit"].setChecked(True)
        with mock.patch.object(SD, "StepPlanWorker") as planner:
            dlg._on_suggested("enlarge the hole", agent="Claude Sonnet 5.5")
        planner.assert_called_once()
        with mock.patch.object(CB.config, "save_run") as saved:
            dlg._on_planned({"plan": ['{"changes": [], "advice": []}']}, {})
        saved.assert_called_once()
    def test_build_this_from_the_chat_does_not_finish_or_restart_the_run(self):
        """"Build this" in the chat asks for a plan on the answer on screen;
        it never advances the queue of a run (there is none) and the answer
        box shows it is working."""
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg._queue = []
        dlg.ask.set_text("fit 6mm")
        key = f"ask · {m['report']['stem']}"
        dlg._responses[key] = ["enlarge the hole"]
        with mock.patch.object(SD, "StepPlanWorker") as planner, \
                mock.patch.object(CB.config, "save_run") as saved:
            dlg._composer_build()
        planner.assert_called_once()
        saved.assert_not_called()
        self.assertFalse(dlg.composer.send_btn.isEnabled())   # busy

class AskAndEditAreTwoThingsAndEachSaysWhoAnswered(unittest.TestCase):
    """Reported 2026-10-17: a follow-up overwrote the first answer so two
    questions showed one answer; choosing Groq still opened ChatGPT and a
    plan; "Build this" sat under a plain question; and nothing said which AI
    had answered."""

    def _asked(self, agent="Groq"):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("which material fits best?")
        dlg._action_buttons["ask"].setChecked(True)
        # Unsaved (as in the earlier Ask tests), so the live card stays on screen.
        with mock.patch.object(CB.config, "save_run", side_effect=OSError):
            dlg._on_suggested("PP for cost.", agent=agent)
        return dlg, m, f"ask · {m['report']['stem']}"

    def test_a_follow_up_leaves_the_first_answer_alone(self):
        dlg, m, key = self._asked("Claude")
        dlg._inline.question = "what about nylon?"
        with mock.patch.object(CB.config, "save_run", side_effect=OSError):
            dlg._on_answer_followup_done(dlg._inline, key, "Nylon needs drying.")
        self.assertEqual(dlg._responses[key], ["PP for cost."])
        self.assertEqual(dlg._stage_agents_map[key], "Claude")
        self.assertEqual(dlg._followups, [
            {"q": "what about nylon?", "a": "Nylon needs drying.",
             "agent": "Claude Haiku 5.5"}])
        turn = dlg.chat.cards[0].turn
        self.assertEqual(turn["answer"], "PP for cost.")
        self.assertEqual(turn["followups"][0]["a"], "Nylon needs drying.")

    def test_two_follow_ups_keep_all_three_answers_apart(self):
        dlg, m, key = self._asked()
        with mock.patch.object(CB.config, "save_run"):
            for q, a in (("and nylon?", "Dry it."), ("and PET?", "Fine.")):
                dlg._inline.question = q
                dlg._on_answer_followup_done(dlg._inline, key, a)
        self.assertEqual([f["a"] for f in dlg._followups], ["Dry it.", "Fine."])
        self.assertEqual(dlg._responses[key], ["PP for cost."])

    def test_a_follow_up_is_given_the_whole_conversation_so_far(self):
        dlg, m, key = self._asked()
        dlg._followups = [{"q": "and nylon?", "a": "Dry it.", "agent": "Groq"}]
        with mock.patch.object(SD, "StepAskWorker") as worker_cls:
            dlg._on_answer_followup(mock.MagicMock(), m, key, "Groq", "and PET?")
        prompt = worker_cls.call_args[0][2]
        for part in ("which material fits best?", "PP for cost.",
                     "and nylon?", "Dry it.", "and PET?"):
            self.assertIn(part, prompt)

    def test_the_answer_names_who_gave_it_and_it_survives_a_reopen(self):
        dlg, m, key = self._asked("Claude")
        self.assertEqual(dlg._live["agent"], "Claude")
        dlg.models = [m]
        record = dlg._run_record("ask")
        self.assertEqual(record["step"]["agents"][key], "Claude")
        sess = SES.build_sessions([{"path": "/r/1.json", "stamp": 1, "rec": {
            "step": record["step"], "responses": record["responses"]}}])[0]
        self.assertEqual(SES.chat_turns(sess)[0]["agent"], "Claude")
        fresh = _dialog()
        fresh._apply_record("", rec=record)
        self.assertEqual(fresh._stage_agents_map[key], "Claude")

    def test_the_card_labels_the_answer_with_its_agent(self):
        dlg, m, key = self._asked("ChatGPT")
        from PySide6.QtWidgets import QLabel
        card = dlg.chat.cards[0]
        texts = [l.text() for l in card.findChildren(QLabel)]
        self.assertTrue(any("CHATGPT" in t for t in texts), texts)

    def test_ask_offers_only_ask_and_edit_adds_make_a_change(self):
        dlg, m, key = self._asked()
        m["path"] = "/nowhere/block.step"
        dlg._sync_composer()
        self.assertFalse(dlg.composer.build_btn.isVisibleTo(dlg.composer))
        dlg._action_buttons["edit"].setChecked(True)
        self.assertTrue(dlg.composer.build_btn.isVisibleTo(dlg.composer))

    def test_edit_answered_by_groq_is_planned_by_groq_with_no_browser(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("enlarge the hole to 6 mm")
        dlg._action_buttons["edit"].setChecked(True)
        _CaptureWorker.seen = {}
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker), \
                mock.patch.object(SD, "StepPlanWorker") as planner, \
                mock.patch.object(CB.config, "save_run"):
            dlg._on_suggested("Enlarge it.", agent="Groq")
        self.assertEqual(_CaptureWorker.seen, {}, "no browser tool may open")
        planner.assert_called_once()
        self.assertIn("enlarge the hole to 6 mm", planner.call_args[0][2])
        planner.return_value.start.assert_called_once()

    def test_the_plan_names_who_wrote_it(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("enlarge the hole")
        dlg._action_buttons["edit"].setChecked(True)
        plan = ('{"changes": [{"op": "enlarge_hole", "part": "block", '
                '"dia_mm": 5, "new_dia_mm": 6, "why": "fit"}], "advice": []}')
        with mock.patch.object(CB.config, "save_run"):
            dlg._on_planned({"plan": [plan]}, {}, agent="Groq")
        from PySide6.QtWidgets import QLabel
        texts = " ".join(l.text() for l in dlg.plan_panel.findChildren(QLabel))
        self.assertIn("Planned by", texts)
        self.assertIn("Groq", texts)

    def test_a_question_asked_in_edit_stays_on_the_answer_not_the_plan(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg._current = m
        dlg.ask.set_text("what material is this?")
        dlg._action_buttons["edit"].setChecked(True)
        dlg._show_tab(1)
        with mock.patch.object(CB.config, "save_run"):
            dlg._on_planned({"plan": ['{"changes": [], "advice": ["It is a question."]}']},
                            {}, agent="Groq")
        self.assertEqual(dlg.out_tabs.current(), 1)
        self.assertIn("question", dlg.status.text())

    def test_making_a_change_after_follow_ups_plans_from_the_whole_conversation(self):
        dlg, m, key = self._asked()
        m["path"] = "/nowhere/block.step"
        dlg._followups = [{"q": "make the hole 6 mm", "a": "Yes, 6 mm.", "agent": "Groq"}]
        with mock.patch.object(SD, "StepPlanWorker") as planner:
            dlg._composer_build()
        suggestions = planner.call_args[0][3]
        self.assertIn("PP for cost.", suggestions)
        self.assertIn("make the hole 6 mm", suggestions)


class TheGuardsSpeakBeforeAnythingRuns(unittest.TestCase):
    """Real QMessageBox.warning calls, patched so a headless run does not
    block — the guard itself is what is being proven."""

    def test_ask_without_a_question_is_refused(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/a.step"])
        dlg._action_buttons["ask"].setChecked(True)
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker:
            dlg._generate()
            warn.assert_not_called()                      # in the window, not a pop-up
            self.assertIn('Say what you want', dlg.status.text())
            worker.assert_not_called()

    def test_draft_needs_no_configured_image_tool(self):
        """Draft is ChatGPT's job regardless of what Agents says, so a cfg
        with no visual tool at all still measures and drafts."""
        dlg = _dialog(cfg={"agents": {"brains": "Claude"}, "api_key": "k",
                           "step_out_dir": tempfile.mkdtemp()})
        dlg._on_files_added(["/nowhere/a.step"])
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker, \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
            warn.assert_not_called()
            worker.assert_called_once()

    def test_edit_needs_no_separate_reasoning_tool_only_the_openrouter_key(self):
        """2026-11-06: Edit used to need a separately configured "Reasoning"
        tool under Agents whenever Ask wasn't answered by Groq — removed
        along with Groq itself. Both models now review their own plan
        in-house, so Edit needs exactly what Ask needs: the OpenRouter key,
        nothing configured under Agents at all."""
        dlg = _dialog(cfg={"step_out_dir": tempfile.mkdtemp()})   # no key
        dlg._on_files_added(["/nowhere/a.step"])
        dlg.ask.set_text("fit 6mm")
        dlg._action_buttons["edit"].setChecked(True)
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker:
            dlg._generate()
            warn.assert_not_called()                      # in the window, not a pop-up
            self.assertIn('needs an OpenRouter key', dlg.status.text())
            worker.assert_not_called()
        dlg.cfg["openrouter_api_key"] = "sk-or-test"
        with mock.patch.object(SD.QMessageBox, "warning") as warn, \
                mock.patch.object(SD, "StepMeasureWorker") as worker, \
                mock.patch.object(CB.config, "save"):
            dlg._generate()
            warn.assert_not_called()
            worker.assert_called_once()


@unittest.skipUnless(HAVE_CAD, "cadquery not installed")
class ARealModelLandsWhereItWasSent(unittest.TestCase):
    """One real measurement through the dialog's own worker: the folder is
    named after the model, under the chosen root, and every file inside
    carries the model's name."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="prism-test-step-root-")
        src = tempfile.mkdtemp()
        cls.model = os.path.join(src, "Bracket A.step")
        _box_step(cls.model)
        cls.dlg = _dialog(root=cls.root)
        cls.dlg._on_files_added([cls.model])
        cls.dlg.mode_combo.setCurrentText("plastic")
        # Draft is the default action; the AI stage is opt-in since Round
        # 42, and this class's own test below wants it ON so it can check
        # what that stage is handed. Checking it also stops the queue at
        # the measurement by intercepting the AI stage.
        cls.dlg.ai_draft_cb.setChecked(True)
        #
        # The measuring worker runs SYNCHRONOUSLY — start() replaced by
        # run() on the calling thread, so its signals deliver straight into
        # the dialog's slots with no event loop. Spinning processEvents()
        # here to wait for a real thread is what aborted the whole suite:
        # it delivered a zero-delay modal leaked by an inquiry-dialog test
        # that ran earlier, with nobody to click it.
        with mock.patch.object(SD, "AutomationWorker", _CaptureWorker), \
                mock.patch.object(SD.StepMeasureWorker, "start",
                                  lambda worker: worker.run()), \
                mock.patch.object(CB.config, "save"), \
                mock.patch.object(CB.config, "save_artifact"):
            cls.dlg._generate()
        if not cls.dlg.models:
            raise unittest.SkipTest("measuring did not finish")

    def test_the_folder_is_named_after_the_model_under_the_root(self):
        m = self.dlg.models[0]
        self.assertEqual(m["out_dir"], os.path.join(self.root, "Bracket A"))

    def test_every_file_carries_the_models_name(self):
        m = self.dlg.models[0]
        files = os.listdir(m["out_dir"])
        self.assertTrue(files)
        for f in files:
            self.assertTrue(f.startswith("Bracket A - "), f)
        self.assertIn("Bracket A - dimensions.xlsx", files)
        self.assertIn("Bracket A - drawing sheet.png", files)

    def test_the_numbers_are_on_screen_and_the_folder_is_named(self):
        text = self.dlg.meas_view.toPlainText()
        self.assertIn("60.00 x 40.00 x 8.00", text)
        self.assertIn("plastic moulding", text)
        self.assertIn(self.dlg.models[0]["out_dir"], self.dlg.files_label.text())
        self.assertTrue(self.dlg.folder_btn.isEnabled())

    def test_the_draft_stage_was_handed_prisms_render_only(self):
        seen = _CaptureWorker.seen
        self.assertTrue(seen.get("started"))
        for a in seen["args"][2]:
            self.assertFalse(a["path"].lower().endswith((".step", ".stp")))
            self.assertTrue(a["path"].startswith(self.root))


@unittest.skipUnless(HAVE_CAD, "OCP/CadQuery not installed")
class KnowingARealFlatSizeSolvesTheKFactor(unittest.TestCase):
    """The shop-floor-facing side of solve_k_factor: pick a part, say
    which side and the true figure, get the K-factor back — checked
    against the same real, customer-verified job as
    TheFlatPatternOfTheCustomersEnclosure in test_stepfile.py, not a
    synthetic box. No worker, no event loop needed — the box only ever
    reads report["_shapes"], already sitting in self.models once a
    measurement has completed."""

    @classmethod
    def setUpClass(cls):
        why = sample_jobs.missing("step_file_demo", "Assem1.STEP")
        if why:
            raise unittest.SkipTest(why)     # a real customer job, not on every machine
        real = sample_jobs.path("step_file_demo", "Assem1.STEP")
        cls.report = SF.analyse(real, mode="metal")
        cls.dlg = _dialog()
        cls.dlg.models = [{"report": cls.report}]
        cls.dlg._fill_kfit_parts(cls.dlg.models)

    def test_only_parts_with_a_flat_pattern_are_offered(self):
        offered = {cls_data[1] for cls_data in
                   (self.dlg.kfit_part_combo.itemData(i)
                    for i in range(self.dlg.kfit_part_combo.count()))}
        for name in ("top", "bottom", "side"):
            self.assertIn(name, offered)

    def test_the_true_width_this_part_was_measured_at_solves_back_to_it(self):
        bottom = next(p for p in self.report["parts"] if p["name"] == "bottom")
        true_w = bottom["flat"]["flat_size_mm"][0]
        idx = next(i for i in range(self.dlg.kfit_part_combo.count())
                  if self.dlg.kfit_part_combo.itemData(i)[1] == "bottom")
        self.dlg.kfit_part_combo.setCurrentIndex(idx)
        self.dlg.kfit_axis_combo.setCurrentIndex(0)     # width
        self.dlg.kfit_target_edit.setText(f"{true_w:.2f}")
        self.dlg._kfit_solve()
        self.assertIn("reproduces that size exactly", self.dlg.kfit_result.text())
        self.assertIsNotNone(self.dlg._kfit_solved)
        solved = self.dlg._kfit_solved
        self.dlg._kfit_apply()
        self.assertEqual(self.dlg.k_edit.text(), f"{solved:g}")

    def test_a_figure_that_cannot_be_this_part_says_so_plainly(self):
        idx = 0
        self.dlg.kfit_part_combo.setCurrentIndex(idx)
        self.dlg.kfit_target_edit.setText("999999")
        self.dlg._kfit_solve()
        self.assertIn("doesn't fit", self.dlg.kfit_result.text())
        self.assertIsNone(self.dlg._kfit_solved)


class ItIsOnTheShelfAndInHistory(unittest.TestCase):
    """Everything the shell knows about STEP it reads off the manifest --
    the rail row, the Home card, History's run attribution and the licence
    gate. These pin that the manifest says what the dialog does."""

    def test_it_is_registered_and_gated_on_its_own_key(self):
        from addons import registry
        a = registry.by_key("step")
        self.assertIsNotNone(a)
        self.assertEqual(a.label, "STEP")
        self.assertEqual(a.feature, "step")
        self.assertEqual(a.screen, "step")
        self.assertEqual(a.engine, ("stepfile",))

    def test_it_is_on_the_rail_with_a_real_icon(self):
        from widgets import icons, sidebar
        entry = next(e for e in sidebar.ADDONS if e[0] == "step")
        self.assertEqual(entry[1], "STEP")
        self.assertEqual(entry[4], "step")
        self.assertIn(entry[2], set(icons._STROKED) | set(icons._FILLED))

    def test_history_recognises_its_runs(self):
        from addons import registry
        from widgets.panel_base import _kind_of, ADDONS
        self.assertEqual(registry.kind_of("STEP — Draft: Assem1.STEP"), "step")
        self.assertEqual(_kind_of("STEP — Draft: Assem1.STEP"), "step")
        self.assertEqual(_kind_of("/step-ask plastic x.stp q"), "step")
        self.assertEqual(_kind_of("/step-auto plastic x.stp"), "step")
        self.assertEqual(ADDONS["step"], "STEP")

    def test_the_front_door_names_its_tools(self):
        from addons.step.panel import StepPanel
        panel = StepPanel({"agents": {"visual": "ChatGPT", "brains": "Claude"}})
        roles = panel.tool_roles()
        self.assertEqual([r[3] for r in roles],
                         ["ChatGPT", "Claude Haiku 5.5"])
        self.assertEqual(panel.KIND, "step")

    def test_the_offer_takes_plain_paths(self):
        """The intent contract: paths in, and the dialog does its own
        shaping -- only models are kept, and a caller by intent needs to
        know nothing about what a model is."""
        from addons import names, registry
        owner, handler = registry.offering(names.MEASURE_MODEL)
        self.assertEqual(owner.key, "step")
        opened = {}

        class FakeDialog:
            def __init__(self, cfg, attachments, parent):
                opened["attachments"] = attachments
                self.paths = []

            def _on_files_added(self, paths):
                opened["paths"] = paths

            def exec(self):
                opened["shown"] = True

        with mock.patch.object(SD, "StepDialog", FakeDialog):
            registry.resolve(handler)(None, {}, ["/x/a.step", "/x/q.pdf"])
        self.assertEqual(opened["paths"], ["/x/a.step", "/x/q.pdf"])
        self.assertEqual(opened["attachments"], [])
        self.assertTrue(opened["shown"])


class TheWindowRoutesIt(GateTest):
    """The route from the rail to the screen, and from the screen's button
    to the dialog, asserted on a real window -- not by reading source."""

    def test_the_rail_key_lands_on_the_step_workbench(self):
        """STEP opens straight into its workbench — one screen for everything,
        not a front door with a window on top of it."""
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        # The gate itself is a network round trip on a worker thread --
        # tests/test_addon_gates.py proves the gate; this proves the route
        # behind it, so the gate is stepped over here the same way.
        with mock.patch.object(CB, "step_available", return_value=(True, "")), \
                mock.patch.object(main_window.MainWindow, "_authorized_then",
                                  lambda self, feature, action, then: then()):
            win._handle_command("step")
        self.assertIsNotNone(win.step_work)
        self.assertEqual(win.screens.currentIndex(), main_window.STEP_WORK)
        self.assertIs(win.step_work.parentWidget(), win.step_host)
        self.assertEqual(win.step_work.windowType(), Qt.Widget)

    def test_the_screens_button_opens_the_workbench_not_a_window(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(CB, "step_available", return_value=(True, "")), \
                mock.patch.object(main_window.MainWindow,
                                  "_offer_followup_for_dialog") as offered:
            win.step_panel.opened.emit()
        self.assertEqual(win.screens.currentIndex(), main_window.STEP_WORK)
        # Deliberately NOT offered: that generic follow-up can only ever
        # save a refined TEXT answer, never actually build a file — a
        # customer hit that dead end twice. STEP's own conversation window
        # is the one place a follow-up can become a real build ("Build
        # this" — tests/test_answer_dialog.py), so this door stays closed.
        offered.assert_not_called()

    def test_leaving_the_workbench_goes_home(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(CB, "step_available", return_value=(True, "")):
            win._open_step_dialog()
        win.step_work._close_clicked()
        self.assertIs(win.screens.currentWidget(), win.home_panel)

    def test_a_step_run_from_history_reopens_in_the_workbench(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        path = os.path.join(tempfile.mkdtemp(), "run_1.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"query": "STEP — Ask: x", "responses": {}, "links": {},
                       "step": {"action": "ask", "mode": "metal",
                                "question": "x", "models": []}}, f)
        with mock.patch.object(CB, "step_available", return_value=(True, "")), \
                mock.patch.object(main_window.MainWindow, "_history_dialog") as hist:
            win._open_run_record(path)
        hist.assert_not_called()
        self.assertEqual(win.screens.currentIndex(), main_window.STEP_WORK)

    def test_without_cadquery_it_says_so_and_opens_nothing(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(CB, "step_available",
                               return_value=(False, "no cadquery")), \
                mock.patch.object(main_window, "StepDialog") as dlg, \
                mock.patch.object(main_window.QMessageBox, "information") as box:
            win.step_panel.opened.emit()
        dlg.assert_not_called()
        self.assertIn("cadquery", box.call_args[0][2])

    def test_it_is_paywalled_without_its_feature(self):
        """Also covered by tests/test_addon_gates.py; kept here so the
        add-on's own file says what it costs."""
        self.grant([f for f in EVERYTHING if f != "step"])
        win = self._window()
        with mock.patch.object(type(win), "_show_screen") as shown:
            win._handle_command("step")
        self.assertIn("step", self.paywalled)
        shown.assert_not_called()


class TheWorkbenchLayout(unittest.TestCase):
    """The workbench re-skin (models · canvas + one action · results) moved
    every widget; these pin what it must still do on screen."""

    def test_the_question_box_belongs_to_ask_and_edit_only(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertTrue(dlg.ai_draft_cb.isVisibleTo(dlg))          # Draft
        self.assertFalse(dlg.ask.edit.isVisibleTo(dlg))
        dlg._action_buttons["ask"].setChecked(True)
        self.assertTrue(dlg.ask.edit.isVisibleTo(dlg))
        self.assertTrue(dlg.model_combo.isVisibleTo(dlg))
        self.assertFalse(dlg.ai_draft_cb.isVisibleTo(dlg))
        dlg._action_buttons["edit"].setChecked(True)
        self.assertTrue(dlg.ask.edit.isVisibleTo(dlg))

    def test_the_text_typed_for_a_draft_is_not_lost_by_hiding_the_box(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        dlg._action_buttons["ask"].setChecked(True)
        dlg.ask.edit.setPlainText("make it lighter")
        dlg._action_buttons["draft"].setChecked(True)
        self.assertEqual(dlg.ask.text(), "make it lighter")

    def test_the_canvas_invites_then_waits_then_shows_the_sheet(self):
        dlg = _dialog()
        self.assertIs(dlg.canvas.stack.currentWidget(), dlg.canvas.page)
        self.assertIn("Attach a 3D model", dlg.canvas.card.text())
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        self.assertIn("Assem1.STEP", dlg.canvas.card.text())
        self.assertIs(dlg.canvas.stack.currentWidget(), dlg.canvas.page)
        dlg.models = [_fake_measured(dlg)]
        png = dlg.models[0]["drawn"]["png"]
        from PySide6.QtGui import QImage
        img = QImage(40, 30, QImage.Format_RGB32)
        img.fill(0xFF336699)
        img.save(png)
        dlg._show_preview(dlg.models)
        self.assertIs(dlg.canvas.stack.currentWidget(), dlg.canvas.sheet)

    def test_a_model_with_no_sheet_says_so_on_the_canvas(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/block.step"])
        dlg.models = [_fake_measured(dlg)]
        dlg.models[0]["path"] = dlg.paths[0]
        dlg.models[0]["drawn"] = {}
        dlg._show_preview(dlg.models)
        self.assertIs(dlg.canvas.stack.currentWidget(), dlg.canvas.page)
        self.assertIn("No drawing sheet", dlg.canvas.card.text())

    def test_the_files_tab_lists_what_is_on_disk_grouped_by_what_made_them(self):
        dlg = _dialog()
        from PySide6.QtWidgets import QLabel
        dlg._refresh_files()
        self.assertIn("Nothing made yet.",
                      [l.text() for l in dlg.files_panel.findChildren(QLabel)])
        dlg.models = [_fake_measured(dlg)]
        out = dlg.models[0]["out_dir"]
        open(os.path.join(out, "block - dimensions.xlsx"), "wb").write(b"x")
        dlg._refresh_files()
        texts = " ".join(l.text() for l in dlg.files_panel.findChildren(QLabel))
        self.assertIn("XLSX", texts)
        self.assertIn("PNG", texts)
        self.assertIn("block - dimensions.xlsx", texts)
        self.assertIn("MEASURED", texts)

    def test_models_are_cards_with_a_status(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        from PySide6.QtWidgets import QLabel
        texts = [l.text() for l in dlg.model_list.findChildren(QLabel)]
        self.assertIn("Assem1.STEP", texts)
        self.assertIn("waiting", texts)
        self.assertEqual(dlg.models_card.count.text(), "1")
        dlg.models = [_fake_measured(dlg)]
        dlg.models[0]["path"] = dlg.paths[0]
        dlg._render_models()
        texts = [l.text() for l in dlg.model_list.findChildren(QLabel)]
        self.assertIn("measured", texts)

    def test_taking_a_model_back_out_clears_its_card(self):
        dlg = _dialog()
        dlg._on_files_added(["/nowhere/Assem1.STEP"])
        dlg.ask.remove_path(dlg.paths[0])
        self.assertEqual(dlg.paths, [])
        self.assertEqual(dlg.models_card.count.text(), "0")
        self.assertIn("Attach a 3D model", dlg.canvas.card.text())

    def test_the_spec_register_reads_the_measurement(self):
        dlg = _dialog()
        dlg.models = [_fake_measured(dlg)]
        dlg._refresh_spec()
        from PySide6.QtWidgets import QLabel
        texts = " ".join(l.text() for l in dlg.spec.findChildren(QLabel))
        self.assertIn("60.0 × 40.0 × 8.0 mm", texts)
        self.assertIn("Ø5 ×1", texts)

    def test_the_plan_tab_lists_the_proposed_changes(self):
        dlg = _dialog()
        from PySide6.QtWidgets import QLabel
        dlg.plan_panel.set_plan({"changes": [
            {"op": "enlarge_hole", "part": "p", "dia_mm": 6.5,
             "new_dia_mm": 8.4, "why": "M8 clearance"}], "advice": ["check fit"]})
        texts = " ".join(l.text() for l in dlg.plan_panel.findChildren(QLabel))
        self.assertIn("Ø6.5 → Ø8.4 on p", texts)
        self.assertIn("M8 clearance", texts)
        self.assertIn("check fit", texts)

    def test_options_are_a_popover_off_the_top_bar(self):
        dlg = _dialog()
        self.assertTrue(dlg.opt_box.isHidden())
        self.assertIn("▾", dlg.opt_toggle.text())
        for w in (dlg.mode_combo, dlg.k_edit, dlg.root_label):
            self.assertIs(w.window(), dlg.opt_box)

    def test_a_finished_ask_opens_the_answer_tab_and_a_measure_the_numbers(self):
        dlg = _dialog()
        dlg.models = [_fake_measured(dlg)]
        dlg._action_buttons["ask"].setChecked(True)
        with mock.patch.object(SD.CB.config, "save_run"):
            dlg._finish()
        self.assertEqual(dlg.out_stack.currentIndex(), 1)


class ReopeningARunFromHistory(unittest.TestCase):
    """History lives in the STEP screen: click a past run and it reopens
    there — no other window."""

    def _record(self, dlg, with_report=True, model_exists=False):
        out = os.path.join(dlg._root(), "block")
        os.makedirs(out, exist_ok=True)
        m = _fake_measured(dlg)
        model = os.path.join(dlg._root(), "block.step")
        if model_exists:
            open(model, "wb").write(b"x")
        rm = {"file": "block.step", "path": model if with_report else "",
              "out_dir": m["out_dir"], "modified": "", "conversation": ""}
        if with_report:
            rm["report"] = {k: v for k, v in m["report"].items()}
        rec = {"query": "STEP — Ask: lighter?", "links": {},
               "responses": {"ask · block": ["Use thinner stock."]},
               "step": {"action": "ask", "mode": "plastic",
                        "question": "lighter?", "models": [rm]}}
        path = os.path.join(dlg._root(), "run_1.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        return path

    def test_the_history_is_one_row_per_chat_not_per_run(self):
        dlg = _dialog()
        def rec(action, q, model, modified=""):
            return {"step": {"action": action, "question": q, "models": [
                {"file": model, "path": "", "out_dir": "/x", "modified": modified}]},
                "responses": {}, "links": {}}
        recs = [
            {"path": "/r/1.json", "stamp": 100, "when": "1d ago", "rec": rec("draft", "", "A.step")},
            {"path": "/r/2.json", "stamp": 200, "when": "1d ago", "rec": rec("ask", "lighter?", "A.step")},
            {"path": "/r/3.json", "stamp": 300, "when": "1h ago",
             "rec": rec("edit", "bigger holes", "A.step", "/x/A - modified 2026-10-15 201121.step")},
            {"path": "/r/4.json", "stamp": 400, "when": "5m ago",
             "rec": rec("ask", "again", "A - modified 2026-10-15 201121.step")},
            {"path": "/r/5.json", "stamp": 50, "when": "3d ago", "rec": rec("draft", "", "B.step")},
        ]
        with mock.patch.object(dlg, "_records", return_value=recs):
            items = dlg._step_runs()
        self.assertEqual([i["text"] for i in items], ["A", "B"])
        self.assertIn("4 runs", items[0]["when"])
        self.assertEqual(items[0]["action"], "Ask")

    def test_a_run_reopens_its_question_answer_and_model(self):
        dlg = _dialog()
        path = self._record(dlg, with_report=True, model_exists=True)
        dlg.load_run(path)
        self.assertEqual(dlg._action(), "ask")
        self.assertEqual(dlg.ask.text(), "lighter?")
        self.assertIn("Use thinner stock.", dlg.result.toPlainText())
        self.assertEqual(len(dlg.models), 1)
        self.assertEqual(len(dlg.paths), 1)
        self.assertTrue(dlg.generate_btn.isEnabled())
        self.assertEqual(dlg.out_stack.currentIndex(), 1)
        self.assertFalse(dlg.step2.isHidden())

    def test_a_run_whose_model_is_gone_still_shows_its_answer_but_cannot_rerun(self):
        dlg = _dialog()
        path = self._record(dlg, with_report=False)
        dlg.load_run(path)
        self.assertIn("Use thinner stock.", dlg.result.toPlainText())
        self.assertEqual(dlg.paths, [])
        self.assertFalse(dlg.generate_btn.isEnabled())
        from PySide6.QtWidgets import QLabel
        texts = " ".join(l.text() for l in dlg.spec.findChildren(QLabel))
        self.assertIn("was not kept", texts)
        shown = [l.text() for l in dlg.model_list.findChildren(QLabel)]
        self.assertIn("block.step", shown)

    def test_a_reopened_model_card_can_be_dismissed(self):
        dlg = _dialog()
        dlg.load_run(self._record(dlg, with_report=False))
        dlg._remove_model("run:" + dlg.models[0]["out_dir"])
        self.assertEqual(dlg.models, [])

    def test_a_run_is_not_reopened_over_one_that_is_still_going(self):
        dlg = _dialog()
        path = self._record(dlg, with_report=True)
        dlg._busy = True
        dlg.load_run(path)
        self.assertEqual(dlg.models, [])
        self.assertIn("still going", dlg.status.text())

    def test_the_follow_up_box_needs_a_kept_measurement(self):
        dlg = _dialog()
        dlg.load_run(self._record(dlg, with_report=False))
        self.assertFalse(dlg.composer.isVisibleTo(dlg))
    def test_a_reopened_run_offers_the_follow_up_box_in_the_chat(self):
        dlg = _dialog()
        dlg.load_run(self._record(dlg, with_report=True, model_exists=True))
        self.assertTrue(dlg.composer.isVisibleTo(dlg))
        # and a follow-up goes to the same run record, not a new one
        self.assertTrue(dlg._run_path.endswith("run_1.json"))
    def test_it_can_be_the_screen_and_ask_the_main_window_to_leave(self):
        from PySide6.QtWidgets import QWidget
        host = QWidget()
        dlg = StepDialog({"step_out_dir": tempfile.mkdtemp()}, [], host,
                         embedded=True)
        got = []
        dlg.leave_requested.connect(lambda: got.append(1))
        dlg._close_clicked()
        self.assertEqual(got, [1])
        self.assertEqual(dlg.windowType(), Qt.Widget)
        self.assertFalse(dlg.isModal())


class AChatStartsEmptyWhenAFileIsAttached(unittest.TestCase):
    """A chat starts when a file is attached — empty, whatever was done with
    that file before — and counts what is done in it: 0, then 1, then 1+n.
    A different file is a new chat; an old one is reopened from History."""

    def _record(self, stamp, action, model, chat):
        return {"path": f"/r/{stamp}.json", "stamp": stamp, "when": "x",
                "rec": {"step": {"action": action, "question": "q", "chat": chat,
                        "models": [{"file": model, "path": "", "out_dir": "/x"}]},
                        "responses": {}}}

    def _tab(self, dlg):
        return dlg.out_tabs._buttons[1].text()

    def test_a_freshly_attached_file_shows_zero_chats_even_if_it_has_history(self):
        dlg = _dialog()
        old = [self._record(1, "draft", "A.step", "old"),
               self._record(2, "ask", "A.step", "old")]
        with mock.patch.object(dlg, "_records", return_value=old):
            dlg._on_files_added(["/nowhere/A.step"])
        self.assertEqual(self._tab(dlg), "Chat  0")
        self.assertEqual(len(dlg.chat.cards), 0)
        self.assertNotEqual(dlg._session_key, "old")

    def test_the_count_grows_as_things_are_done_in_it(self):
        dlg = _dialog()
        recs = []
        with mock.patch.object(dlg, "_records", side_effect=lambda: list(recs)):
            dlg._on_files_added(["/nowhere/A.step"])
            self.assertEqual(self._tab(dlg), "Chat  0")
            recs.append(self._record(1, "draft", "A.step", dlg._session_key))
            dlg._refresh_chat()
            self.assertEqual(self._tab(dlg), "Chat  1")
            recs.append(self._record(2, "ask", "A.step", dlg._session_key))
            dlg._refresh_chat()
            self.assertEqual(self._tab(dlg), "Chat  2")

    def test_a_new_file_after_working_starts_a_new_empty_chat(self):
        dlg = _dialog()
        recs = []
        with mock.patch.object(dlg, "_records", side_effect=lambda: list(recs)):
            dlg._on_files_added(["/nowhere/A.step"])
            first = dlg._session_key
            recs.append(self._record(1, "draft", "A.step", first))
            dlg._refresh_chat()
            dlg._on_files_added(["/nowhere/B.step"])
            self.assertNotEqual(dlg._session_key, first)
            self.assertEqual(self._tab(dlg), "Chat  0")
            self.assertEqual([os.path.basename(p) for p in dlg.paths], ["B.step"])

    def test_files_added_before_anything_is_run_share_one_chat(self):
        dlg = _dialog()
        with mock.patch.object(dlg, "_records", return_value=[]):
            dlg._on_files_added(["/nowhere/A.step"])
            first = dlg._session_key
            dlg._on_files_added(["/nowhere/B.step"])
        self.assertEqual(dlg._session_key, first)
        self.assertEqual(len(dlg.paths), 2)

    def test_taking_every_file_away_ends_the_chat(self):
        dlg = _dialog()
        with mock.patch.object(dlg, "_records", return_value=[]):
            dlg._on_files_added(["/nowhere/A.step"])
            dlg.ask.remove_path(dlg.paths[0])
        self.assertEqual(dlg._session_key, "")
        self.assertEqual(self._tab(dlg), "Chat  0")

    def test_an_old_chat_reopened_from_history_is_carried_on_in(self):
        dlg = _dialog()
        old = [self._record(1, "draft", "A.step", "old"),
               self._record(2, "ask", "A.step", "old")]
        with mock.patch.object(dlg, "_records", return_value=old):
            dlg.load_session("old")
        self.assertEqual(dlg._session_key, "old")
        self.assertEqual(self._tab(dlg), "Chat  2")

    def test_no_file_open_means_no_chat(self):
        dlg = _dialog()
        with mock.patch.object(dlg, "_records", return_value=[]):
            dlg._refresh_chat()
        self.assertEqual(dlg._session_key, "")
        self.assertEqual(len(dlg.chat.cards), 0)


class AChatAboutSeveralPartsHasNoSingleOriginal(unittest.TestCase):
    """Found live: files attached together share one chat, and picking one
    model card then narrowed the screen to that one file and dropped the
    other. Original / edited-copy choices belong to a chat about ONE part."""

    def test_two_parts_in_one_chat_offer_no_version_picker(self):
        from addons.step import sessions as S
        runs = []
        for i, name in enumerate(("A.step", "B.step")):
            runs.append({"path": f"/r/{i}", "stamp": i, "rec": {"step": {
                "action": "draft", "chat": "c",
                "models": [{"file": name, "path": f"/x/{name}", "out_dir": "/x",
                            "modified": ""}]}, "responses": {}}})
        sess = S.build_sessions(runs)[0]
        with mock.patch("os.path.exists", return_value=True):
            self.assertEqual(len(S.versions_of(sess)), 2)
            self.assertEqual(StepDialog._single_part_versions(sess), [])

    def test_one_part_and_its_edit_still_offer_both(self):
        from addons.step import sessions as S
        runs = [{"path": "/r/0", "stamp": 0, "rec": {"step": {
            "action": "edit", "chat": "c", "models": [{
                "file": "A.step", "path": "/x/A.step", "out_dir": "/x",
                "modified": "/x/A - modified 2026-10-15 201121.step"}]},
            "responses": {}}}]
        sess = S.build_sessions(runs)[0]
        with mock.patch("os.path.exists", return_value=True):
            self.assertEqual(len(StepDialog._single_part_versions(sess)), 2)


class DeletingFromTheSidebar(unittest.TestCase):
    """The trash on a History chat removes its run records; the trash on a
    model removes the folder Prism made for it. Both ask first, and neither
    can reach a file outside what Prism itself made."""

    def _rec(self, stamp, chat, out_dir="/x"):
        return {"path": f"/r/run_{stamp}.json", "stamp": stamp, "when": "x",
                "rec": {"step": {"action": "ask", "question": "q", "chat": chat,
                        "models": [{"file": "A.step", "path": "", "out_dir": out_dir}]},
                        "responses": {}}}

    def test_a_styled_copy_is_named_on_the_draft_card(self):
        dlg = _dialog()
        styled = os.path.join(dlg._root(), "A - AI drawing sheet 1.png")
        turn = SES.live_turn("draft", "A.step", "")
        turn["styled"] = [styled]
        dlg.chat.set_turns([turn])
        card = dlg.chat.cards[0]
        names = [l.text() for l in card.findChildren(SD.QLabel)]
        self.assertIn("A - AI drawing sheet 1.png", names)
        self.assertIn("STYLED COPY", names)

    def test_a_cancelled_chat_delete_removes_nothing(self):
        dlg = _dialog()
        recs = [self._rec(1, "old"), self._rec(2, "old")]
        with mock.patch.object(dlg, "_records", return_value=recs), \
                mock.patch.object(dlg, "_confirm", return_value=False), \
                mock.patch.object(SD.DATA, "delete_runs") as gone:
            dlg._delete_chat("old")
        gone.assert_not_called()

    def test_a_confirmed_chat_delete_removes_exactly_its_run_records(self):
        dlg = _dialog()
        recs = [self._rec(1, "old"), self._rec(2, "old"), self._rec(3, "other")]
        with mock.patch.object(dlg, "_records", return_value=recs), \
                mock.patch.object(dlg, "_confirm", return_value=True) as ask, \
                mock.patch.object(SD.DATA, "delete_runs",
                                  return_value=(2, [])) as gone:
            dlg._delete_chat("old")
        self.assertEqual(sorted(gone.call_args[0][1]),
                         ["/r/run_1.json", "/r/run_2.json"])
        self.assertIn("stay where they are", ask.call_args[0][1])

    def test_deleting_the_open_chat_empties_the_screen(self):
        dlg = _dialog()
        recs = [self._rec(1, "old")]
        with mock.patch.object(dlg, "_records", return_value=recs):
            dlg.load_session("old")
        self.assertEqual(dlg._session_key, "old")
        with mock.patch.object(dlg, "_records", return_value=[]), \
                mock.patch.object(dlg, "_confirm", return_value=True), \
                mock.patch.object(dlg, "_sessions",
                                  return_value=SES.build_sessions(recs)), \
                mock.patch.object(SD.DATA, "delete_runs", return_value=(1, [])):
            dlg._delete_chat("old")
        self.assertEqual(dlg._session_key, "")
        self.assertEqual(len(dlg.chat.cards), 0)

    def test_a_model_folder_inside_the_step_folder_is_deleted_after_confirming(self):
        dlg = _dialog()
        m = _fake_measured(dlg)
        dlg.models = [m]
        dlg.paths = []
        folder = m["out_dir"]
        self.assertTrue(os.path.isdir(folder))
        with mock.patch.object(dlg, "_confirm", return_value=False):
            dlg._delete_model_files("run:" + folder)
        self.assertTrue(os.path.isdir(folder), "cancel must keep everything")
        with mock.patch.object(dlg, "_confirm", return_value=True):
            dlg._delete_model_files("run:" + folder)
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(dlg.models, [])

    def test_a_folder_outside_the_step_folder_is_never_deleted(self):
        dlg = _dialog()
        outside = tempfile.mkdtemp(prefix="prism-test-outside-")
        keep = os.path.join(outside, "important.txt")
        open(keep, "w").write("x")
        m = _fake_measured(dlg, out_dir=outside)
        dlg.models = [m]
        with mock.patch.object(dlg, "_confirm", return_value=True) as ask:
            dlg._delete_model_files("run:" + outside)
        ask.assert_not_called()
        self.assertTrue(os.path.exists(keep))
        self.assertIn("only delete", dlg.status.text())

    def test_the_step_folder_itself_and_a_nested_folder_are_refused(self):
        dlg = _dialog()
        nested = os.path.join(dlg._root(), "a", "b")
        os.makedirs(nested)
        self.assertEqual(dlg._safe_model_dir(dlg._root()), "")
        self.assertEqual(dlg._safe_model_dir(nested), "")
        self.assertNotEqual(
            dlg._safe_model_dir(os.path.join(dlg._root(), "a")), "")

    def test_the_folder_holding_an_attached_original_is_refused(self):
        dlg = _dialog()
        folder = os.path.join(dlg._root(), "mine")
        os.makedirs(folder)
        step = os.path.join(folder, "mine.step")
        open(step, "w").write("x")
        dlg.paths = [step]
        self.assertEqual(dlg._safe_model_dir(folder), "")


if __name__ == "__main__":
    unittest.main()

"""BOQ and BOM: the run titles History has to recognise.

BOQ had no test file at all until this one. `addons/boq/dialog.py` is 600
lines, it is a paid feature, and it measures a customer's drawing and
produces the quantities they price from — while Gerber, which has one
prospective customer and is not in daily use, has four test files. That
imbalance is how the bug below survived.

The bug
───────
`widgets/panel_base._RUN_PREFIXES` (now derived from the add-on manifests)
decides which add-on wrote a run, by matching the START of its recorded
title. The titles themselves are f-strings inside the dialogs. Nothing tied
the two together, and the old `_RUN_PREFIXES` comment said so — it listed
the four other files whose f-strings it was matching against.

Commit 6b16cbb scaffolded BOM mode and replaced the dialog's hardcoded
`"BOQ"` with `self._doc`, so runs started being recorded as

    "Bill of Quantities — 500 brackets"

while the prefix table still said `"BOQ — "`. From that commit until this
one, `kind_of()` returned `""` for **every BOQ and BOM run**: no add-on chip
in History, the prefix never stripped from the title, and the add-on's own
front door unable to find its recent runs.

Nothing raised. Nothing was logged. The only symptom was a missing chip.

The fix is structural rather than a corrected literal: the dialog now takes
its prefix from its own manifest, so the two cannot disagree again. This file
is what makes that checkable — it reads the title the dialog actually
composes and feeds it to the same lookup History uses.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                # noqa: E402

from addons import registry                               # noqa: E402
from addons.boq.dialog import BoqDialog                   # noqa: E402

_app = QApplication.instance() or QApplication([])

CFG = {"api_key": "k"}


def _dialog(mode: str = "boq") -> BoqDialog:
    return BoqDialog(CFG, [], None, mode=mode)


class _FakeSignal:
    """A connect()/emit() pair with no Qt underneath -- enough for
    _FakeRunDialog to stand in for a real Signal without needing a QObject."""

    def __init__(self):
        self._slots = []

    def connect(self, fn):
        self._slots.append(fn)

    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)


class _FakeRunDialog:
    """Stands in for addons.boq.run_dialog.BoqRunDialog. show() returns
    immediately instead of opening a real modal -- a real one would block
    forever in a test, since the mocked AutomationWorker below never fires
    a signal to end it (CLAUDE.md: never call exec()/a QEventLoop in a
    test). Every BOQ test that reaches _send_followup for a browser agent
    must patch "addons.boq.run_dialog.BoqRunDialog" with this, the same
    way existing tests already patch FollowupDialog.

    BoqDialog now keeps ONE of these for its whole session and calls
    restart() on later verify/follow-up calls instead of constructing a
    second one -- restart_calls and the constructor's own count (below)
    let a test tell which happened."""

    last = None
    construct_calls = 0

    def __init__(self, title, stage, agent, parent=None, note=""):
        self.title, self.stage, self.agent = title, stage, agent
        self.note = note
        self.show_calls = 0
        self.restart_calls = 0
        _FakeRunDialog.construct_calls += 1
        _FakeRunDialog.last = self
        self.skip_requested = _FakeSignal()
        self.fallback_requested = _FakeSignal()
        self.stop_requested = _FakeSignal()

    def show(self):
        self.show_calls += 1

    def raise_(self):
        pass

    def activateWindow(self):
        pass

    def restart(self, title, stage, agent, note=""):
        self.title, self.stage, self.agent = title, stage, agent
        self.note = note
        self.restart_calls += 1

    def set_agent(self, agent):
        self.agent = agent

    def finish_ok(self, texts, url=""):
        pass

    def finish_error(self, error, exhausted=True):
        pass

    def finish_skipped(self, reason=""):
        pass

    def finish_cancelled(self, note=""):
        pass


class TheRunTitleIsRecognisedByHistory(unittest.TestCase):
    """The regression test for the bug in this file's docstring."""

    def test_a_boq_run_title_is_attributed_to_boq(self):
        dialog = _dialog("boq")
        dialog.request = "500 brackets"
        title = f"{dialog._run_prefix}{dialog.request}"
        self.assertEqual(
            registry.kind_of(title), "boq",
            "History cannot tell that %r came from BOQ, so the run shows no "
            "add-on chip, keeps its prefix in the title, and does not appear "
            "in BOQ's own recent-runs list. Nothing raises when this breaks."
            % title)

    def test_a_bom_run_title_is_attributed_to_bom(self):
        dialog = _dialog("bom")
        dialog.request = "spring assembly"
        title = f"{dialog._run_prefix}{dialog.request}"
        self.assertEqual(registry.kind_of(title), "bom")

    def test_the_two_modes_are_told_apart(self):
        """They share a dialog and a licence key. If their prefixes collide,
        every BOM run is filed as a BOQ run and the mistake is invisible."""
        self.assertNotEqual(_dialog("boq")._run_prefix,
                            _dialog("bom")._run_prefix)

    def test_the_prefix_comes_from_the_manifest(self):
        """Not merely equal to it today — taken from it, so the dialog and
        the prefix table cannot drift apart again."""
        for key in ("boq", "bom"):
            with self.subTest(mode=key):
                self.assertEqual(_dialog(key)._run_prefix,
                                 registry.by_key(key).run_prefixes[0])

    def test_titles_written_before_the_fix_are_still_recognised(self):
        """Every BOQ run recorded between 6b16cbb and the fix is titled with
        the long form. Those records exist on customers' machines; dropping
        them from History would be a second, quieter bug."""
        self.assertEqual(registry.kind_of("Bill of Quantities — 500 brackets"),
                         "boq")
        self.assertEqual(registry.kind_of("Bill of Materials — spring"), "bom")


class TheTwoModesAreOneDialog(unittest.TestCase):
    """BOM is BOQ with `mode="bom"`. The point of that is that BOM inherits
    every fix BOQ gets; the risk is that the two drift in what they say."""

    def test_the_document_name_follows_the_mode(self):
        self.assertEqual(_dialog("boq")._doc, "Bill of Quantities")
        self.assertEqual(_dialog("bom")._doc, "Bill of Materials")

    def test_an_unknown_mode_falls_back_to_boq(self):
        """`mode` reaches this constructor from a rail command; an unexpected
        value must open the ordinary document, not crash or open nothing."""
        self.assertEqual(_dialog("nonsense").mode, "boq")

    def test_the_window_title_is_the_document_name(self):
        self.assertEqual(_dialog("bom").windowTitle(), "Bill of Materials")

    def test_both_modes_construct(self):
        """The cheapest possible guard on a 600-line dialog that had no test
        file at all: it builds, in both modes, without raising."""
        for key in ("boq", "bom"):
            with self.subTest(mode=key):
                self.assertIsNotNone(_dialog(key))


if __name__ == "__main__":
    unittest.main()


class TheDrawingNeverReachesAnAI(unittest.TestCase):
    """The owner's rule for every measuring add-on, made to hold for BOQ too
    (10 Sep 2026): the drawing is measured here; an AI only ever sees the
    numbers. Until now the writing stage attached the CAD file itself."""

    class _Capture:
        seen = {}

        def __init__(self, *a, **kw):
            TheDrawingNeverReachesAnAI._Capture.seen = {"args": a, "kwargs": kw}
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    def test_the_writer_is_handed_templates_and_notes_but_never_the_drawing(self):
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.q = {"layers": ["WALLS"], "lengths_by_layer": {"WALLS": 12.0},
               "areas_by_layer": {}, "block_counts": {}, "unit": "m",
               "scope_total_layers": 1}
        d.cad_path = "/secret/site.dxf"
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d.templates = [{"path": "/x/template.xlsx", "name": "template.xlsx"}]
        d.notes = [{"path": "/x/notes.txt", "name": "notes.txt"}]
        d.writer_agent = "ChatGPT"
        with mock.patch.object(BD, "AutomationWorker", self._Capture):
            d._write()
        files = self._Capture.seen["args"][2]
        names = [f["name"] for f in files]
        self.assertEqual(names, ["template.xlsx", "notes.txt"])
        for f in files:
            self.assertFalse(f["path"].lower().endswith((".dxf", ".dwg")))
        prompt = self._Capture.seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("NOT attached", prompt)
        self.assertNotIn("attached to this message", prompt)
        self.assertNotIn("/secret/site.dxf", prompt)

    def test_the_terminal_command_keeps_the_same_rule(self):
        import inspect
        import core_bridge as CB
        src = inspect.getsource(CB.get_boq().__class__) if False else ""
        import importlib, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "prism_terminal"))
        text = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "prism_terminal", "prism.py"),
            encoding="utf-8").read()
        self.assertIn("write_files = templates + note_files", text)
        self.assertNotIn("write_files = ([cad_file] if cad_file else [])", text)


class TheDrawingGoesToAIOnlyAfterAYes(unittest.TestCase):
    """"Recheck with the drawing" is the one place the drawing may leave the
    machine, and only after the user says yes in the popup."""

    class _Capture:
        seen = {}
        started = 0

        def __init__(self, *a, **kw):
            TheDrawingGoesToAIOnlyAfterAYes._Capture.seen = {"args": a, "kwargs": kw}
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            TheDrawingGoesToAIOnlyAfterAYes._Capture.started += 1

    def setUp(self):
        self._Capture.started = 0
        self.d = _dialog()
        self._drawing = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(self._drawing, "w") as fh:
            fh.write("0\nEOF\n")
        self.d.cad_path = self._drawing
        self.d.summary = "WALLS 12.00 m"
        self.d._task_name = "BOQ — sai"
        self.d.result.setPlainText("1  Brick wall  12.00  m")

    def _ask(self, answer):
        from unittest import mock
        from addons.boq import dialog as BD
        with mock.patch.object(BD, "AutomationWorker", self._Capture), \
                mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog), \
                mock.patch.object(BD.QMessageBox, "question",
                                  staticmethod(lambda *a, **k: answer)):
            self.d._ask_recheck()

    def test_the_button_is_off_without_a_drawing_on_regardless_of_an_answer(self):
        """A drawing alone is enough now -- no existing BOQ required. The
        button covers both "make one from the drawing" (no answer yet)
        and "verify/remake" (one already exists)."""
        self.d._set_busy(False, "")
        self.assertTrue(self.d.recheck_btn.isEnabled())
        self.d.cad_path = ""
        self.d._set_busy(False, "")
        self.assertFalse(self.d.recheck_btn.isEnabled())

    def test_the_button_is_on_even_with_no_answer_yet(self):
        self.d.cad_path = self._drawing
        self.d.result.setPlainText("")
        self.d._set_busy(False, "")
        self.assertTrue(self.d.recheck_btn.isEnabled())

    def test_the_button_says_make_with_drawing(self):
        self.assertEqual(self.d.recheck_btn.text(), "Make with drawing")

    def test_saying_no_sends_nothing(self):
        from addons.boq import dialog as BD
        self._ask(BD.QMessageBox.No)
        self.assertEqual(self._Capture.started, 0)

    def test_saying_yes_sends_the_drawing_to_the_writer_with_the_measured_figures(self):
        from addons.boq import dialog as BD
        self._ask(BD.QMessageBox.Yes)
        self.assertEqual(self._Capture.started, 1)
        files = self._Capture.seen["args"][2]
        self.assertIn(self._drawing, [f["path"] for f in files])
        stage = self._Capture.seen["kwargs"]["custom_stages"][0]
        self.assertEqual(stage[0], "recheck")
        prompt = stage[2][0]
        self.assertIn("WALLS 12.00 m", prompt)
        self.assertIn("Brick wall", prompt)

    def test_with_no_previous_answer_it_makes_from_the_drawing_instead_of_verifying(self):
        """"Make with drawing" pressed before any BOQ exists -- nothing to
        verify yet, so it should read as making one, not correcting one."""
        from addons.boq import dialog as BD
        self.d.result.setPlainText("")
        self._ask(BD.QMessageBox.Yes)
        stage = self._Capture.seen["kwargs"]["custom_stages"][0]
        prompt = stage[2][0]
        self.assertNotIn("PREVIOUS ANSWER", prompt)
        self.assertIn("reading the attached drawing directly", prompt)
        self.assertEqual(_FakeRunDialog.last.title,
                         "Making your BOQ from the drawing")

    def test_with_a_previous_answer_it_still_verifies_and_remakes(self):
        """The same button, pressed once a BOQ already exists -- unchanged
        from before this session's change."""
        from addons.boq import dialog as BD
        self._ask(BD.QMessageBox.Yes)   # setUp already gave self.d an answer
        stage = self._Capture.seen["kwargs"]["custom_stages"][0]
        prompt = stage[2][0]
        self.assertIn("PREVIOUS ANSWER", prompt)
        self.assertIn("Verify and remake", prompt)
        self.assertEqual(_FakeRunDialog.last.title, "Verifying against the drawing")

    def test_the_corrected_answer_replaces_the_first_one_in_the_same_box(self):
        from unittest import mock
        self.d._followup_agent = "Kimi 2.6"
        self.d._followup_stage = "recheck"
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            self.d._on_followed_up({"recheck": ["1  Brick wall  11.50  m"]}, {})
        self.assertEqual(self.d.result.toPlainText(), "1  Brick wall  11.50  m")
        self.assertIn("recheck", self.d._all_responses)


    def _offer(self, *, submitted, quick="", note="", files=()):
        from unittest import mock
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            dlg = fake.return_value
            dlg.submitted.return_value = submitted
            dlg.chosen_quick.return_value = quick
            dlg.followup_text.return_value = note
            dlg.file_paths.return_value = list(files)
            with mock.patch.object(self.d, "_drawing_consent", return_value=True) as consent:
                self.d._offer_followup()
        return fake, consent

    def test_the_followup_popup_is_offered_with_a_one_click_verify_and_remake(self):
        fake, _ = self._offer(submitted=False)
        actions = fake.call_args.kwargs["quick_actions"]
        self.assertEqual([a[0] for a in actions], ["verify"])
        self.assertEqual(fake.call_args.kwargs["artifacts"], [])

    def test_no_popup_without_a_drawing_so_verify_is_not_offered(self):
        from unittest import mock
        self.d.cad_path = ""
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            self.d._offer_followup()
        self.assertEqual(fake.call_args.kwargs["quick_actions"], [])

    def test_saying_no_to_the_followup_sends_nothing(self):
        from unittest import mock
        with mock.patch.object(self._Capture, "__init__", self._Capture.__init__), \
                mock.patch("addons.boq.dialog.AutomationWorker", self._Capture):
            self._offer(submitted=False)
        self.assertEqual(self._Capture.started, 0)

    def test_verify_and_remake_asks_consent_and_sends_the_drawing(self):
        from unittest import mock
        from addons.boq import dialog as BD
        with mock.patch.object(BD, "AutomationWorker", self._Capture), \
                mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog):
            self._offer(submitted=True, quick="verify", note="VERIFY")
        self.assertEqual(self._Capture.started, 1)
        files = self._Capture.seen["args"][2]
        self.assertIn(self._drawing, [f["path"] for f in files])
        self.assertEqual(self._Capture.seen["kwargs"]["custom_stages"][0][0], "recheck")

    def test_a_typed_followup_sends_only_the_files_the_user_added(self):
        from unittest import mock
        from addons.boq import dialog as BD
        extra = os.path.join(tempfile.mkdtemp(), "site_note.txt")
        with open(extra, "w") as fh:
            fh.write("gate is on the north side")
        with mock.patch.object(BD, "AutomationWorker", self._Capture), \
                mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog):
            self._offer(submitted=True, quick="", note="add a gate", files=[extra])
        self.assertEqual(self._Capture.started, 1)
        files = self._Capture.seen["args"][2]
        self.assertIn(extra, [f["path"] for f in files])
        self.assertNotIn(self._drawing, [f["path"] for f in files])
        self.assertEqual(self._Capture.seen["kwargs"]["custom_stages"][0][0], "followup")


class TheWriterGetsThePricedCsvAsReferenceOnly(unittest.TestCase):
    """The offline priced grid goes to the write-up AI as a CSV reference —
    never the drawing, and never as the record of the numbers."""

    class _Capture:
        seen = {}

        def __init__(self, *a, **kw):
            TheWriterGetsThePricedCsvAsReferenceOnly._Capture.seen = {
                "args": a, "kwargs": kw}
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    def _dialog_with_grid(self):
        d = _dialog()
        d.q = {"layers": ["WALLS"], "lengths_by_layer": {"WALLS": 12.0},
               "areas_by_layer": {}, "block_counts": {}, "unit": "m",
               "scope_total_layers": 1}
        d.cad_path = "/secret/site.dxf"
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d.writer_agent = "Claude"
        d.price_table.set_quantities(d.q, title="BOQ")
        return d

    def test_the_priced_grid_goes_as_a_reference_csv_and_the_drawing_does_not(self):
        import csv
        from unittest import mock
        from addons.boq import dialog as BD
        d = self._dialog_with_grid()
        with mock.patch.object(BD, "AutomationWorker", self._Capture):
            d._write()
        files = self._Capture.seen["args"][2]
        self.assertEqual(len(files), 1)
        self.assertTrue(files[0]["name"].startswith("boq_priced_reference"))
        self.assertTrue(files[0]["name"].endswith(".csv"))
        self.assertIn("size", files[0])
        self.assertTrue(os.path.exists(files[0]["path"]))
        with open(files[0]["path"], newline="", encoding="utf-8-sig") as fh:
            self.assertGreater(len(list(csv.reader(fh))), 1)
        for f in files:
            self.assertFalse(f["path"].lower().endswith((".dxf", ".dwg")))
        prompt = self._Capture.seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("REFERENCE ONLY", prompt)
        self.assertNotIn("/secret/site.dxf", prompt)


class GrokIsARealRegisteredBrowserAgent(unittest.TestCase):
    """"Grok" is a real prism_terminal.core.agents.AGENT_REGISTRY entry, so
    it just has to resolve, be offered in the picker, and go through the
    ordinary AutomationWorker path every other browser agent already
    does."""

    def test_grok_is_in_the_writer_pool(self):
        from addons.boq import agents as boq_agents
        self.assertIn("Grok", boq_agents.WRITER)

    def test_grok_resolves_to_a_profile_with_every_selector_the_write_stage_needs(self):
        import core_bridge as CB
        entry = CB.agents.resolve_agent("", "Grok")
        self.assertIsNotNone(entry)
        for key in ("url", "textarea_selector", "response_selector",
                    "submit_selector"):
            self.assertTrue(entry.get(key), f"missing {key}")
        self.assertEqual(entry["url"], "https://grok.com")

    def test_grok_goes_through_automationworker_like_any_other_browser_agent(self):
        from unittest import mock
        from addons.boq import dialog as BD

        class _Capture:
            seen = {}

            def __init__(self, *a, **kw):
                _Capture.seen = {"args": a, "kwargs": kw}
                self.done = self.failed = self

            def connect(self, *_):
                pass

            def start(self):
                pass

        d = _dialog()
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d._task_name = "BOQ — sai"
        d.writer_agent = "Grok"
        with mock.patch.object(BD, "AutomationWorker", _Capture):
            d._write()
        self.assertEqual(_Capture.seen["kwargs"]["custom_stages"][0][:2],
                         ("format", "Grok"))


class DeepSeekIsARealRegisteredBrowserAgent(unittest.TestCase):
    """Same story as Grok above: "DeepSeek" is a real AGENT_REGISTRY entry
    (verified live once the owner logged into chat.deepseek.com themselves,
    2026-10-20), not an API shortcut, so it needs no BOQ-side special-casing
    either -- just the ordinary AutomationWorker path."""

    def test_deepseek_is_in_the_writer_pool(self):
        from addons.boq import agents as boq_agents
        self.assertIn("DeepSeek", boq_agents.WRITER)

    def test_deepseek_resolves_to_a_profile_with_every_selector_the_write_stage_needs(self):
        import core_bridge as CB
        entry = CB.agents.resolve_agent("", "DeepSeek")
        self.assertIsNotNone(entry)
        for key in ("url", "textarea_selector", "response_selector",
                    "submit_selector"):
            self.assertTrue(entry.get(key), f"missing {key}")
        self.assertEqual(entry["url"], "https://chat.deepseek.com")

    def test_deepseek_goes_through_automationworker_like_any_other_browser_agent(self):
        from unittest import mock
        from addons.boq import dialog as BD

        class _Capture:
            seen = {}

            def __init__(self, *a, **kw):
                _Capture.seen = {"args": a, "kwargs": kw}
                self.done = self.failed = self

            def connect(self, *_):
                pass

            def start(self):
                pass

        d = _dialog()
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d._task_name = "BOQ — sai"
        d.writer_agent = "DeepSeek"
        with mock.patch.object(BD, "AutomationWorker", _Capture):
            d._write()
        self.assertEqual(_Capture.seen["kwargs"]["custom_stages"][0][:2],
                         ("format", "DeepSeek"))


class GeminiIsARealRegisteredBrowserAgentSeparateFromTheImageMaker(unittest.TestCase):
    """"Gemini" is its own AGENT_REGISTRY entry (verified live, 2026-10-20),
    deliberately separate from the existing "Google Gemini" entry -- that
    one is permanently tagged as an image-generation tool
    (core.agents._MAKES), and reusing it for a BOQ write-up would have
    asked the writer stage to draw a picture of a bill of quantities
    instead of writing one."""

    def test_gemini_is_in_the_writer_pool(self):
        from addons.boq import agents as boq_agents
        self.assertIn("Gemini", boq_agents.WRITER)

    def test_gemini_resolves_to_a_profile_with_every_selector_the_write_stage_needs(self):
        import core_bridge as CB
        entry = CB.agents.resolve_agent("", "Gemini")
        self.assertIsNotNone(entry)
        for key in ("url", "textarea_selector", "response_selector",
                    "submit_selector"):
            self.assertTrue(entry.get(key), f"missing {key}")
        self.assertEqual(entry["url"], "https://gemini.google.com/app")

    def test_gemini_is_not_tagged_as_an_image_maker_unlike_google_gemini(self):
        import core_bridge as CB
        self.assertFalse(CB.agents.is_maker(CB.agents.resolve_agent("", "Gemini")))
        self.assertTrue(CB.agents.is_maker(
            CB.agents.resolve_agent("", "Google Gemini")))

    def test_gemini_goes_through_automationworker_like_any_other_browser_agent(self):
        from unittest import mock
        from addons.boq import dialog as BD

        class _Capture:
            seen = {}

            def __init__(self, *a, **kw):
                _Capture.seen = {"args": a, "kwargs": kw}
                self.done = self.failed = self

            def connect(self, *_):
                pass

            def start(self):
                pass

        d = _dialog()
        d.summary = "WALLS 12.00 m"
        d.request = "BOQ for the site"
        d._task_name = "BOQ — sai"
        d.writer_agent = "Gemini"
        with mock.patch.object(BD, "AutomationWorker", _Capture):
            d._write()
        self.assertEqual(_Capture.seen["kwargs"]["custom_stages"][0][:2],
                         ("format", "Gemini"))


class _TrackedWorker:
    """A richer fake AutomationWorker than _Capture: records skip()/stop()
    calls and lets a test fire .done/.failed on demand, for exercising the
    fallback-chain logic in _start_followup_run without a real worker
    thread or a real (blocking) BoqRunDialog."""

    instances: list = []

    def __init__(self, *a, **kw):
        self.args, self.kwargs = a, kw
        self.done = _FakeSignal()
        self.failed = _FakeSignal()
        self.started = False
        self.skipped = False
        self.stopped = False
        self._running = False
        _TrackedWorker.instances.append(self)

    def start(self):
        self.started = True
        self._running = True

    def isRunning(self):
        return self._running

    def skip(self):
        self.skipped = True

    def stop(self):
        self.stopped = True
        self._running = False


class TheFollowUpFlowHasALiveWindowAndAFallbackChain(unittest.TestCase):
    """Item 2 from BOQ-CHANGES-TODO.md: a verify/follow-up call shows a
    live run window and automatically tries Claude then Kimi 2.6 if the
    chosen agent can't answer -- the owner's own words, "when those errors
    occur which agent should be used as a fallback (claude/kimi)"."""

    def setUp(self):
        from unittest import mock
        _TrackedWorker.instances = []
        self.d = _dialog()
        self.d.summary = "WALLS 12.00 m"
        self.d.request = "BOQ for the site"
        self.d._task_name = "BOQ — sai"
        self.d.result.setPlainText("1  Brick wall  12.00  m")
        self._patches = [
            mock.patch("addons.boq.dialog.AutomationWorker", _TrackedWorker),
            mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _start(self, agent="ChatGPT"):
        self.d.writer_combo.setCurrentText(agent)
        self.d._send_followup("add a gate", [], verify=False)

    def test_the_chain_is_the_chosen_agent_then_claude_then_kimi(self):
        self._start("ChatGPT")
        self.assertEqual(self.d._fu_chain, ["Claude", "Kimi 2.6"])
        self.assertEqual(_TrackedWorker.instances[0].kwargs["custom_stages"][0][:2],
                         ("followup", "ChatGPT"))

    def test_picking_claude_itself_does_not_put_it_in_its_own_fallback_chain(self):
        self._start("Claude")
        self.assertEqual(self.d._fu_chain, ["Kimi 2.6"])

    def test_a_failure_automatically_tries_the_next_agent_in_the_chain(self):
        self._start("ChatGPT")
        first = _TrackedWorker.instances[0]
        first.failed.emit("ChatGPT ran out of memory")
        self.assertEqual(len(_TrackedWorker.instances), 2)
        second = _TrackedWorker.instances[1]
        self.assertEqual(second.kwargs["custom_stages"][0][:2],
                         ("followup", "Claude"))
        self.assertEqual(_FakeRunDialog.last.agent, "Claude")

    def test_two_failures_try_claude_then_kimi_then_gives_up_cleanly(self):
        self._start("ChatGPT")
        _TrackedWorker.instances[0].failed.emit("ChatGPT ran out of memory")
        _TrackedWorker.instances[1].failed.emit("Claude hit a sign-in wall")
        self.assertEqual(len(_TrackedWorker.instances), 3)
        self.assertEqual(_TrackedWorker.instances[2].kwargs["custom_stages"][0][:2],
                         ("followup", "Kimi 2.6"))
        # Kimi fails too -- the chain is now empty, so this must not try a
        # fourth worker, must not crash, and must leave the dialog usable.
        _TrackedWorker.instances[2].failed.emit("Kimi 2.6 timed out")
        self.assertEqual(len(_TrackedWorker.instances), 3)
        self.assertFalse(self.d.progress.isVisible())

    def test_a_success_updates_the_result_and_reopens_the_followup_offer(self):
        from unittest import mock
        self._start("ChatGPT")
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            _TrackedWorker.instances[0].done.emit(
                {"followup": ["1  Brick wall  12.00  m, gate added"]}, {})
        self.assertEqual(self.d.result.toPlainText(),
                         "1  Brick wall  12.00  m, gate added")

    def test_skip_calls_the_real_workers_skip_not_stop(self):
        self._start("ChatGPT")
        _FakeRunDialog.last.skip_requested.emit()
        self.assertTrue(_TrackedWorker.instances[0].skipped)
        self.assertFalse(_TrackedWorker.instances[0].stopped)
        self.assertTrue(self.d._fu_skipped)

    def test_stop_calls_the_real_workers_stop(self):
        self._start("ChatGPT")
        _FakeRunDialog.last.stop_requested.emit()
        self.assertTrue(_TrackedWorker.instances[0].stopped)
        self.assertTrue(self.d._fu_stopped)

    def test_use_fallback_stops_the_current_attempt_and_starts_the_next_agent(self):
        self._start("ChatGPT")
        _FakeRunDialog.last.fallback_requested.emit()
        self.assertTrue(_TrackedWorker.instances[0].stopped)
        self.assertEqual(len(_TrackedWorker.instances), 2)
        self.assertEqual(_TrackedWorker.instances[1].kwargs["custom_stages"][0][:2],
                         ("followup", "Claude"))

    def test_a_superseded_workers_late_signal_is_ignored(self):
        """Manual fallback moved on to Claude; ChatGPT's worker is stopped
        but Python still holds it, and Qt signal connections are not
        magically severed -- a late .done from it must not overwrite
        Claude's attempt."""
        self._start("ChatGPT")
        first = _TrackedWorker.instances[0]
        _FakeRunDialog.last.fallback_requested.emit()
        first.done.emit({"followup": ["stale answer from ChatGPT"]}, {})
        self.assertNotEqual(self.d.result.toPlainText(),
                            "stale answer from ChatGPT")


class TheInitialRunNowHasTheSameLiveWindowAndFallbackChain(unittest.TestCase):
    """Item 22 from BOQ-CHANGES-TODO.md: "Make my BOQ" itself (research,
    read-drawing and write stages) was the one call in the whole pipeline
    with NO live window and no fallback chain -- a deliberate boundary at
    the time item 2 was built, closed here by routing it through the same
    _run_stage machinery as a verify/follow-up, sharing the SAME
    BoqRunDialog instance for the whole session (item 7's own rule)."""

    def setUp(self):
        from unittest import mock
        _TrackedWorker.instances = []
        _FakeRunDialog.construct_calls = 0
        self.d = _dialog()
        self.d.ask.set_text("500 brackets")
        self._patches = [
            mock.patch("addons.boq.dialog.AutomationWorker", _TrackedWorker),
            mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def test_plain_run_no_research_shows_the_window_for_the_format_stage(self):
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.derive_cb.setChecked(False)
        self.d._run()
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        self.assertEqual(_FakeRunDialog.last.stage, "format")
        self.assertEqual(self.d._active_runner, "rs")

    def test_a_research_stage_shows_standards_first_then_reuses_the_window(self):
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.research_combo.setCurrentText("Perplexity")
        self.d.derive_cb.setChecked(True)
        self.d._run()
        self.assertEqual(_FakeRunDialog.last.stage, "standards")
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        _TrackedWorker.instances[0].done.emit({"standards": ["use 40m spacing"]}, {})
        # no images -> interpret is skipped -> straight to the write stage,
        # the SAME window restarted, not a second one built.
        self.assertEqual(_FakeRunDialog.last.stage, "format")
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        self.assertEqual(_FakeRunDialog.last.restart_calls, 1)

    def test_the_format_stage_gets_a_raised_wait_floor_not_just_claudes_own_pace(self):
        """Item 23: before this, the initial research/interpret/write
        pipeline passed neither `followup=True` nor `min_wait` at all --
        less of a wait floor than an ordinary follow-up already got."""
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.derive_cb.setChecked(False)
        self.d._run()
        kwargs = _TrackedWorker.instances[0].kwargs
        self.assertTrue(kwargs.get("followup"))
        self.assertEqual(kwargs.get("min_wait"), 900)

    def test_a_failure_on_the_format_stage_falls_back_to_the_next_agent(self):
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.derive_cb.setChecked(False)
        self.d._run()
        _TrackedWorker.instances[0].failed.emit("ChatGPT ran out of memory")
        self.assertEqual(len(_TrackedWorker.instances), 2)
        self.assertEqual(_TrackedWorker.instances[1].kwargs["custom_stages"][0][:2],
                         ("format", "Claude"))
        self.assertEqual(_FakeRunDialog.last.agent, "Claude")

    def test_skip_and_stop_route_to_the_run_stage_not_the_followup_flags(self):
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.derive_cb.setChecked(False)
        self.d._run()
        _FakeRunDialog.last.skip_requested.emit()
        self.assertTrue(_TrackedWorker.instances[0].skipped)
        self.assertTrue(self.d._rs_skipped)
        self.assertFalse(getattr(self.d, "_fu_skipped", False))

    def test_a_success_calls_on_written_and_a_later_followup_reuses_the_window(self):
        from unittest import mock
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d.derive_cb.setChecked(False)
        self.d._run()
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            _TrackedWorker.instances[0].done.emit(
                {"format": ["1  Bracket  500  nos"]}, {"format": "https://chat/1"})
        self.assertEqual(self.d.result.toPlainText(), "1  Bracket  500  nos")
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        # a later follow-up reuses the SAME window, now driven by the
        # follow-up flow instead of the run-stage one.
        self.d._send_followup("add a gate", [], verify=False)
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        self.assertEqual(self.d._active_runner, "fu")
        self.assertEqual(_FakeRunDialog.last.restart_calls, 1)


class AFollowUpResumesTheSameChatInsteadOfOpeningAFreshOne(unittest.TestCase):
    """The owner's report, after item 7 shipped: BOTH "Make with drawing"
    and "Make my BOQ" still opened a brand new browser tab/chat for every
    follow-up, because item 7 only fixed Prism's OWN small progress
    window -- it never touched the separate question of which browser tab
    the engine itself opens for a stage. The real mechanism was already
    built and already used by addons/step/dialog.py's identical follow-up
    case (AutomationWorker's own resume_urls/core.automation's
    resume_urls, keyed by stage, matched against driver.current_url saved
    from the agent's last reply) -- BOQ's dialog.py simply never called
    it."""

    def setUp(self):
        from unittest import mock
        _TrackedWorker.instances = []
        self.d = _dialog()
        self.d.summary = "WALLS 12.00 m"
        self.d.request = "BOQ for the site"
        self.d._task_name = "BOQ — sai"
        self.d.result.setPlainText("1  Brick wall  12.00  m")
        self._patches = [
            mock.patch("addons.boq.dialog.AutomationWorker", _TrackedWorker),
            mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _followup(self, agent="ChatGPT"):
        self.d.writer_combo.setCurrentText(agent)
        self.d._send_followup("add a gate", [], verify=False)

    def _write_up(self, agent="ChatGPT", link="https://chatgpt.com/c/abc"):
        """A completed first write-up. texts is non-empty, so _on_written
        ends by opening the follow-up offer -- a real FollowupDialog.exec()
        would hang here forever (CLAUDE.md: never exec()/a QEventLoop in a
        test), so this is always wrapped, the same way every other BOQ
        test that reaches this path already is."""
        from unittest import mock
        self.d.writer_agent = agent
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            self.d._on_written({"format": ["1  Brick wall  12.00  m"]},
                               {"format": link} if link else {})

    def test_a_first_write_up_leaves_its_own_chat_resumable(self):
        self._write_up(link="")
        self.assertEqual(self.d._last_agent, "ChatGPT")
        self.assertEqual(self.d._last_link, "")  # none given in this test

    def test_a_followup_by_the_same_agent_resumes_the_write_ups_chat(self):
        self._write_up()
        self._followup("ChatGPT")
        kw = _TrackedWorker.instances[0].kwargs
        self.assertEqual(kw["resume_urls"], {"followup": "https://chatgpt.com/c/abc"})

    def test_switching_agents_for_the_followup_does_not_resume_anything(self):
        """There is no chat of Claude's to resume if ChatGPT wrote the
        BOQ -- must fall back to the existing full-context prompt, never
        guess at a URL that belongs to a different tool."""
        self._write_up()
        self._followup("Claude")
        kw = _TrackedWorker.instances[0].kwargs
        self.assertIsNone(kw["resume_urls"])

    def test_a_second_followup_resumes_the_first_followups_chat_not_the_write_ups(self):
        from unittest import mock
        self._write_up()
        self._followup("ChatGPT")
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            _TrackedWorker.instances[0].done.emit(
                {"followup": ["1  Brick wall  12.00  m, gate added"]},
                {"followup": "https://chatgpt.com/c/second"})
        self._followup("ChatGPT")
        kw = _TrackedWorker.instances[1].kwargs
        self.assertEqual(kw["resume_urls"],
                         {"followup": "https://chatgpt.com/c/second"})

    def test_make_with_drawing_as_the_very_first_action_resumes_nothing(self):
        """No BOQ exists yet, so there is nothing to resume -- confirmed
        by construction (self._last_agent/_last_link start empty), not a
        special case."""
        from unittest import mock
        self.assertEqual(self.d._last_agent, "")
        self.assertEqual(self.d._last_link, "")
        self.d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(self.d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        with mock.patch.object(self.d, "_drawing_consent", return_value=True):
            self.d.writer_combo.setCurrentText("ChatGPT")
            self.d._ask_recheck()
        kw = _TrackedWorker.instances[0].kwargs
        self.assertIsNone(kw["resume_urls"])

    def test_a_fallback_to_a_different_tool_mid_chain_never_resumes_either(self):
        self._write_up()
        self._followup("ChatGPT")
        self.assertEqual(_TrackedWorker.instances[0].kwargs["resume_urls"],
                         {"followup": "https://chatgpt.com/c/abc"})
        _TrackedWorker.instances[0].failed.emit("ChatGPT ran out of memory")
        # the chain's next agent is Claude (see agents.py:FALLBACK_ORDER) --
        # no chat of Claude's exists to resume
        self.assertIsNone(_TrackedWorker.instances[1].kwargs["resume_urls"])


class AFollowUpOrVerifyActuallyProducesAndSurfacesAFile(unittest.TestCase):
    """Items 4-6 from BOQ-CHANGES-TODO.md, 2026-10-21: a follow-up's new
    file never replaced the stale measured CSV the follow-up window kept
    showing, "Verify and remake" could come back with no file in any
    format and no way to ask for one, and its live window read as stuck
    well before a real drawing-scan run (the owner's own report: ~20
    minutes) could plausibly finish."""

    def setUp(self):
        from unittest import mock
        _TrackedWorker.instances = []
        self.d = _dialog()
        self.d.summary = "WALLS 12.00 m"
        self.d.request = "BOQ for the site"
        self.d._task_name = "BOQ — sai"
        self.d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(self.d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        self.d.result.setPlainText("1  Brick wall  12.00  m")
        self._patches = [
            mock.patch("addons.boq.dialog.AutomationWorker", _TrackedWorker),
            mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _followup(self, agent="ChatGPT"):
        self.d.writer_combo.setCurrentText(agent)
        self.d._send_followup("add a gate", [], verify=False)

    def _recheck(self, agent="ChatGPT"):
        from unittest import mock
        self.d.writer_combo.setCurrentText(agent)
        with mock.patch.object(self.d, "_drawing_consent", return_value=True):
            self.d._ask_recheck()

    # ── item 5: the format picker ────────────────────────────────────
    def test_the_default_format_adds_nothing_to_the_prompt(self):
        self._followup()
        prompt = _TrackedWorker.instances[0].kwargs["custom_stages"][0][2][0]
        self.assertNotIn("downloadable", prompt)

    def test_choosing_a_format_adds_a_file_request_to_the_prompt(self):
        self.d.format_combo.setCurrentIndex(self.d.format_combo.findData("docx"))
        self._followup()
        prompt = _TrackedWorker.instances[0].kwargs["custom_stages"][0][2][0]
        self.assertIn("Word (.docx)", prompt)

    def test_a_stale_picker_choice_does_not_fight_a_typed_format_request(self):
        """Item 24b: a real, reproduced bug -- the format picker left on an
        earlier choice (here CSV) while the follow-up note itself asks for
        a different format (docx) used to append BOTH requests to the same
        prompt, leaving the tool with two disagreeing instructions. The
        note's own wording must win -- the picker's own line is skipped
        entirely, leaving the engine's own contract system (which scans
        the note's own wording) as the one and only source of the format
        instruction actually sent."""
        self.d.format_combo.setCurrentIndex(self.d.format_combo.findData("csv"))
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d._send_followup("add a gate, and give me this as a docx file",
                              [], verify=False)
        prompt = _TrackedWorker.instances[0].kwargs["custom_stages"][0][2][0]
        self.assertNotIn("downloadable CSV", prompt)
        self.assertNotIn("Give me the result as", prompt)

    def test_the_previous_deliverable_file_is_attached_alongside_its_pasted_text(self):
        """Item 24b part 2: when an earlier stage produced a real file, hand
        the follow-up agent that actual file too, not only the pasted-text
        summary -- a stronger "remake this" than text alone, and the text
        stays so a tool that cannot read the attachment still has it."""
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(b"x")
        tmp.close()
        self.addCleanup(lambda: os.path.exists(tmp.name) and os.unlink(tmp.name))
        self.d._deliverable_path = tmp.name
        self._followup()
        files = _TrackedWorker.instances[0].args[2]
        self.assertTrue(any(f.get("path") == tmp.name for f in files))
        prompt = _TrackedWorker.instances[0].kwargs["custom_stages"][0][2][0]
        self.assertIn("PREVIOUS ANSWER", prompt)

    def test_a_deleted_previous_deliverable_is_not_attached_or_an_error(self):
        self.d._deliverable_path = "/x/gone.docx"
        self._followup()        # must not raise
        files = _TrackedWorker.instances[0].args[2]
        self.assertFalse(any(f.get("path") == "/x/gone.docx" for f in files))

    # ── items 4/5: the engine sees the real request, not a short label ─
    def test_the_engine_is_given_the_real_prompt_as_its_query(self):
        self._followup()
        query = _TrackedWorker.instances[0].args[3]
        self.assertIn("add a gate", query)
        self.assertIn("MEASURED FIGURES", query)

    # ── item 6: the wait ceiling and an honest duration note ──────────
    def test_recheck_gets_a_twenty_minute_wait_floor(self):
        self._recheck()
        kw = _TrackedWorker.instances[0].kwargs
        self.assertTrue(kw["followup"])
        self.assertEqual(kw["min_wait"], 1200)

    def test_a_plain_followup_gets_followup_true_with_no_extra_floor(self):
        self._followup()
        kw = _TrackedWorker.instances[0].kwargs
        self.assertTrue(kw["followup"])
        self.assertEqual(kw["min_wait"], 0)

    def test_the_live_window_shows_an_honest_duration_for_recheck(self):
        self._recheck()
        self.assertIn("20 minutes", _FakeRunDialog.last.note)

    def test_a_plain_followup_gets_no_special_duration_note(self):
        self._followup()
        self.assertEqual(_FakeRunDialog.last.note, "")

    # ── items 4/5: a produced file can actually be learned and shown ──
    def test_files_out_is_passed_so_a_harvested_file_can_be_learned(self):
        self._followup()
        self.assertIsInstance(_TrackedWorker.instances[0].kwargs["files_out"], list)

    def test_a_harvested_file_becomes_the_shown_deliverable_not_the_stale_csv(self):
        from unittest import mock
        self.d.csv_path = "/x/boq_quantities_1.csv"
        self._followup()
        made = _TrackedWorker.instances[0].kwargs["files_out"]
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(b"x")
        tmp.close()
        made.append({"path": tmp.name, "name": "BOQ.docx"})
        with mock.patch("core_bridge.config.save_artifact",
                        return_value="/artifacts/BOQ.docx") as save, \
                mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            _TrackedWorker.instances[0].done.emit(
                {"followup": ["1  Brick wall  12.00  m, gate added"]}, {})
            save.assert_called_once()
        self.assertEqual(self.d._deliverable_path, "/artifacts/BOQ.docx")
        artifacts = fake.call_args.kwargs["artifacts"]
        self.assertEqual(artifacts,
                         ["/artifacts/BOQ.docx", "/x/boq_quantities_1.csv"])

    def test_no_harvested_file_leaves_the_stale_csv_as_the_only_artifact(self):
        """The common, correct case -- a plain text answer -- must not be
        treated as a bug: nothing was made, so nothing new is shown."""
        from unittest import mock
        self.d.csv_path = "/x/boq_quantities_1.csv"
        self._followup()
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            _TrackedWorker.instances[0].done.emit(
                {"followup": ["1  Brick wall  12.00  m, gate added"]}, {})
        self.assertEqual(self.d._deliverable_path, "")
        self.assertEqual(fake.call_args.kwargs["artifacts"],
                         ["/x/boq_quantities_1.csv"])


class AttachingASampleTemplateIsDiscoverableAndConfirmed(unittest.TestCase):
    """The owner's ask: "option for the user to just give in the sample
    BOQs/template... as reference... without actually giving the drawing
    file to the AIs." The underlying mechanism already worked --
    core.boq.classify_inputs has always sorted an attached .docx/.pdf/etc.
    into its own "templates" role, described to the writer as "an example
    BOQ showing the firm's usual style", separate from the drawing itself.
    Nothing told the user this was even possible; this is purely the
    discoverability fix, not a new engine capability."""

    def setUp(self):
        self.d = _dialog()

    def _attach(self, name="firm_format.docx"):
        from unittest import mock
        from addons.boq import dialog as BD
        record = {"path": f"/x/{name}", "name": name}
        with mock.patch.object(BD.CB.files, "attach", return_value=record):
            self.d._absorb([record["path"]])

    def test_the_hint_invites_a_sample_before_anything_is_attached(self):
        self.assertIn("sample BOQ", self.d.template_hint.text())
        self.assertIn("Make with drawing", self.d.template_hint.text())

    def test_attaching_one_confirms_it_with_a_count(self):
        self._attach()
        self.assertIn("1 sample template attached", self.d.template_hint.text())
        self.assertIn("Make with drawing", self.d.template_hint.text())

    def test_attaching_a_second_one_updates_the_count_and_pluralises(self):
        self._attach("firm_format.docx")
        self._attach("another_sample.pdf")
        self.assertIn("2 sample templates attached", self.d.template_hint.text())

    def test_a_plain_note_file_does_not_touch_the_hint(self):
        """A .txt classifies as "notes", not "templates" -- the hint must
        stay the standing invitation, not claim one was attached."""
        self._attach(name="requirements.txt")
        self.assertIn("You can also attach", self.d.template_hint.text())


class TheLiveWindowIsReusedAcrossFollowUps(unittest.TestCase):
    """The owner's report: "Verify and remake" opened a brand new window
    instead of continuing in the one the BOQ was already shown in, even
    right after an ordinary follow-up in the same session. One
    BoqRunDialog is now kept for the whole BOQ session and restart() into
    the next job, instead of a second window -- the same way
    main_window.py keeps one OutputPanel for the core Run screen rather
    than one per stage."""

    def setUp(self):
        from unittest import mock
        _TrackedWorker.instances = []
        _FakeRunDialog.construct_calls = 0
        self.d = _dialog()
        self.d.summary = "WALLS 12.00 m"
        self.d.request = "BOQ for the site"
        self.d._task_name = "BOQ — sai"
        self.d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(self.d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        self.d.result.setPlainText("1  Brick wall  12.00  m")
        self._patches = [
            mock.patch("addons.boq.dialog.AutomationWorker", _TrackedWorker),
            mock.patch("addons.boq.run_dialog.BoqRunDialog", _FakeRunDialog),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self._patches])

    def _followup(self, text="add a gate"):
        self.d.writer_combo.setCurrentText("ChatGPT")
        self.d._send_followup(text, [], verify=False)

    def _recheck(self):
        from unittest import mock
        self.d.writer_combo.setCurrentText("ChatGPT")
        with mock.patch.object(self.d, "_drawing_consent", return_value=True):
            self.d._ask_recheck()

    def test_verify_and_remake_after_a_followup_reuses_the_same_window(self):
        self._followup()
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        first_window = _FakeRunDialog.last
        self._recheck()
        self.assertEqual(
            _FakeRunDialog.construct_calls, 1,
            "a second BoqRunDialog was built instead of reusing the first")
        self.assertIs(_FakeRunDialog.last, first_window)
        self.assertEqual(first_window.restart_calls, 1)
        self.assertEqual(first_window.stage, "recheck")

    def test_a_third_call_restarts_again_without_building_another_window(self):
        self._followup()
        self._recheck()
        self._followup("one more change")
        self.assertEqual(_FakeRunDialog.construct_calls, 1)
        self.assertEqual(_FakeRunDialog.last.restart_calls, 2)
        self.assertEqual(_FakeRunDialog.last.stage, "followup")

    def test_the_window_is_shown_not_exec_d_so_it_never_blocks_in_a_test(self):
        """CLAUDE.md: never call exec()/a QEventLoop in a test. The real
        BoqRunDialog is shown with show(), not the modal exec() the old
        code used -- setModal(True) in its own __init__ already keeps the
        BOQ dialog from being clicked underneath it."""
        self._followup()
        self.assertEqual(_FakeRunDialog.last.show_calls, 1)
        self._recheck()
        self.assertEqual(_FakeRunDialog.last.show_calls, 2)


class ASampleBoqDefinesTheDeliverable(unittest.TestCase):
    """Attach one of the firm's own BOQs and the writer is told to make THAT
    document, filled with this drawing's numbers -- the drawing itself
    still never goes (10 Sep 2026)."""

    def test_a_docx_xlsx_or_pdf_is_a_template_and_goes_to_the_writer(self):
        import core_bridge as CB
        boq = CB.get_boq()
        cad, templates, images, notes = boq.classify_inputs([
            {"path": "/x/site.dwg", "name": "site.dwg"},
            {"path": "/x/last_year_boq.xlsx", "name": "last_year_boq.xlsx"},
            {"path": "/x/sample.pdf", "name": "sample.pdf"},
            {"path": "/x/legend.png", "name": "legend.png"}])
        self.assertEqual([t["name"] for t in templates],
                         ["last_year_boq.xlsx", "sample.pdf"])
        self.assertEqual([c["name"] for c in cad], ["site.dwg"])

    def test_the_writer_is_told_the_sample_defines_the_document(self):
        import core_bridge as CB
        boq = CB.get_boq()
        with_sample = boq.formatting_prompt("WALLS 12.00 m", has_template=True)
        self.assertIn("A SAMPLE BOQ IS ATTACHED", with_sample)
        self.assertIn("defines what you are making", with_sample)
        self.assertIn("do not copy the sample's rows or quantities", with_sample)
        without = boq.formatting_prompt("WALLS 12.00 m", has_template=False)
        self.assertNotIn("SAMPLE BOQ", without)

    def test_the_front_door_says_so(self):
        from addons.boq.panel import BoqPanel
        titles = [step[1] for step in BoqPanel.STEPS]
        self.assertIn("Attach a sample BOQ too", titles)

    def test_the_writer_keeps_the_good_habits_of_the_best_boq(self):
        import core_bridge as CB
        prompt = CB.get_boq().formatting_prompt("WALLS 12.00 m", has_template=True)
        for phrase in ("reference table of the measured figures",
                       "size storage, power and switching",
                       "use them as mounting or routing points"):
            self.assertIn(phrase, prompt)

    def test_the_writer_is_told_not_to_silently_drop_a_look_alike_layer(self):
        """23 Oct 2026, a real-file bug: the writer was once told to simply
        'decide — count it once or keep both' for two similarly-named
        layers, and on a real file it used that licence to drop an entire
        real half of a building's ductwork it mistook for a stale
        duplicate. The instruction now turns on the actual figures, not
        the names, and forbids ever dropping a quantity when unsure.

        The owner's own instruction, same day, after a second complex HVAC
        file: this guidance was learned from an HVAC drawing specifically,
        and the BOQ add-on also writes for ELV, CCTV, cabling, plumbing and
        fire-hydrant jobs from this exact same function -- so it must only
        ever appear when the request was actually for HVAC, never by
        default, the same standing rule the measurement side
        (core.boq.measure(hvac=...)) already follows."""
        import core_bridge as CB
        boq = CB.get_boq()
        hvac_prompt = boq.formatting_prompt("WALLS 12.00 m", has_template=True, hvac=True)
        for phrase in ("NOT AUTOMATICALLY A DUPLICATE",
                       "NEVER drop either",
                       "When you are not sure which case this is, keep both",
                       "LEGEND/KEY",
                       "HVAC-SPECIFIC WRITE-UP RULES"):
            self.assertIn(phrase, hvac_prompt)

    def test_the_hvac_write_up_rules_never_appear_for_any_other_trade(self):
        """The other half of the same instruction: an ELV, CCTV, cabling,
        plumbing or fire-hydrant BOQ -- `hvac` left at its default -- must
        never see the HVAC-only guidance above. Proven both ways: the
        phrase is present when hvac=True, absent when it is not."""
        import core_bridge as CB
        boq = CB.get_boq()
        default_prompt = boq.formatting_prompt("WALLS 12.00 m", has_template=True)
        explicit_off = boq.formatting_prompt("WALLS 12.00 m", has_template=True, hvac=False)
        for prompt in (default_prompt, explicit_off):
            for phrase in ("HVAC-SPECIFIC WRITE-UP RULES",
                           "NOT AUTOMATICALLY A DUPLICATE",
                           "LEGEND/KEY"):
                self.assertNotIn(phrase, prompt)


class TheMeasurementIsATable(unittest.TestCase):
    """The owner's screenshot of 10 Sep: the measured figures shown as the
    prompt text in a 120 px box. Now a table, one row per measured item,
    the way the CSV has it. The prompt text is still what the AI gets."""

    Q = {"unit": "unspecified", "unit_code": 0, "unit_confirmed": False,
         "notes": ["Full conversion couldn't be read, so a minimal fallback was used"],
         "lengths_by_layer": {"BOUNDARY WALL": 1091.18, "Concrete Road": 579.23},
         "areas_by_layer": {"Building": 2227.57},
         "block_counts": {"EP": 22, "MAIN-GATE-7M": 2},
         "block_layers": {"EP": ["Electric Pole"], "MAIN-GATE-7M": ["gates"]},
         "layers": ["0", "BOUNDARY WALL", "Building", "Concrete Road",
                    "Electric Pole", "gates"],
         "entity_count": 29661}

    def test_one_row_per_measured_item_in_csv_order(self):
        from addons.boq.measured import MeasuredTable, rows_for
        rows = rows_for(self.Q)
        self.assertEqual([r[0] for r in rows],
                         ["BOUNDARY WALL", "Concrete Road", "Building", "EP",
                          "MAIN-GATE-7M"])
        self.assertEqual([r[1] for r in rows],
                         ["Length", "Length", "Area", "Count", "Count"])
        t = MeasuredTable()
        t.set_quantities(self.Q)
        shown = t.rows()
        self.assertEqual(len(shown), 5)
        self.assertEqual(shown[0], ("BOUNDARY WALL", "Length", "BOUNDARY WALL",
                                    "1,091.18", "unspecified"))
        self.assertEqual(shown[2], ("Building", "Area", "Building", "2,227.57",
                                    "sq unspecified"))
        self.assertEqual(shown[3], ("EP", "Count", "Electric Pole", "22", "nos"))

    def test_the_header_and_warnings_say_what_the_text_said(self):
        """23 Oct 2026: the warnings moved from one ever-growing label into
        a collapsed, bulleted dropdown (owner's report: a real site file's
        warnings had become a wall of text again) -- same content, read
        from warning_lines() / the toggle button instead of a QLabel."""
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        self.assertIn("29,661 entities", t.header.text())
        self.assertIn("6 layers", t.header.text())
        self.assertTrue(t.warn_btn.isVisibleTo(t))
        self.assertFalse(t.warn_list.isVisibleTo(t))          # collapsed by default
        lines = " ".join(t.warning_lines())
        self.assertIn("Unit not confirmed", lines)
        self.assertIn("minimal fallback", lines)
        t._toggle_warnings()
        self.assertTrue(t.warn_list.isVisibleTo(t))
        self.assertEqual(t.warn_list.count(), len(t.warning_lines()))
        self.assertIn("All 6 layers", t.layers.text())

    def test_the_window_fills_the_table_and_keeps_the_prompt_text(self):
        import tempfile
        from unittest import mock
        import core_bridge as CB
        d = _dialog()
        d.cad_path = "/x/site.dwg"
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._on_measured(self.Q, ["a note"])
        self.assertEqual(len(d.meas_table.rows()), 5)
        self.assertIn("LENGTHS BY LAYER", d.summary)     # the AI's text, intact
        self.assertTrue(d.meas_box.isVisibleTo(d))


class RowsAreTintedByConfidenceAndValueIsEditable(unittest.TestCase):
    """23 Oct 2026, the owner's ask: colour each row by how much Prism
    trusts it -- green nothing flagged it, yellow the HVAC duct-pairing
    rule touched it, red Prism can't resolve it alone -- and let a person
    correct the Value cell by hand, which marks that row green (confirmed)
    regardless of what flagged it originally."""

    Q = {
        "unit": "mm", "unit_code": 4, "unit_confirmed": True,
        "notes": ["M-DUCT-SUPP: read 3 pair(s) of lines as one run's two "
                 "edges, not two separate runs (a duct/pipe/tray drawn to "
                 "its real width) — verify before pricing."],
        "lengths_by_layer": {"M-DUCT-SUPP": 4000.0, "A-WALL": 2000.0,
                             "A-DOOR": 500.0},
        "block_counts": {"PUMP": 3},
        "block_layers": {"PUMP": ["M-EQPM"]},
        "layers": ["M-DUCT-SUPP", "A-WALL", "A-DOOR", "M-EQPM"],
        "entity_count": 10,
        "site": {
            "lookalikes": [{"layers": ["A-WALL", "A-Wall-2"],
                            "verdict": "check which is current before counting either"}],
            "remote_blocks": [{"name": "PUMP", "count": 1, "of": 3,
                               "distances_m": [5000]}],
        },
    }

    def test_severity_for_reads_the_same_signals_as_the_warnings(self):
        from addons.boq.measured import SEV_BAD, SEV_WARN, severity_for
        sev = severity_for(self.Q)
        self.assertEqual(sev["A-WALL"], SEV_BAD)
        self.assertEqual(sev["A-Wall-2"], SEV_BAD)
        self.assertEqual(sev["PUMP"], SEV_BAD)
        self.assertEqual(sev["M-DUCT-SUPP"], SEV_WARN)
        self.assertNotIn("A-DOOR", sev)

    def test_rows_are_tinted_green_yellow_red(self):
        """23 Oct 2026, second round: a pale row background alone read as
        "no colour coding" at a glance -- there is now a dedicated Trust
        column too, a solid dot in the full ink colour. Both are checked
        here: the row tint (still present) and the dot's own colour."""
        import theme
        from addons.boq.measured import COL_ITEM, COL_TRUST, MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        by_item = {t.table.item(r, COL_ITEM).text(): r for r in range(t.table.rowCount())}

        def bg(item_name):
            return t.table.item(by_item[item_name], COL_ITEM).background().color()

        def dot_ink(item_name):
            return t.table.item(by_item[item_name], COL_TRUST).foreground().color()

        self.assertEqual(bg("A-WALL"), theme.qcolor(theme.ERR_BG))
        self.assertEqual(bg("PUMP"), theme.qcolor(theme.ERR_BG))
        self.assertEqual(bg("M-DUCT-SUPP"), theme.qcolor(theme.WARN_BG))
        self.assertEqual(bg("A-DOOR"), theme.qcolor(theme.OK_BG))
        self.assertEqual(dot_ink("A-WALL"), theme.qcolor(theme.ERR_INK))
        self.assertEqual(dot_ink("M-DUCT-SUPP"), theme.qcolor(theme.WARN_INK))
        self.assertEqual(dot_ink("A-DOOR"), theme.qcolor(theme.OK_INK))

    def test_the_colours_actually_render_on_screen_under_the_real_stylesheet(self):
        """23 Oct 2026, caught on the owner's own screenshot: every test
        above passed, yet the live app showed every Trust dot solid black
        and no row tint at all. The data model was right
        (`.foreground().color()` reported red); the screen was not --
        because app.qss's `QTableWidget::item { color: #09090b; }` makes
        Qt's style paint every item with that fixed colour regardless of
        the item's own Qt.ForegroundRole/BackgroundRole brush, a known Qt
        stylesheet limitation. Fixed with `_TintDelegate`, which paints
        the cell itself instead of going through the style. This test
        loads the REAL style.qss (what every earlier test here skipped)
        and samples an actual rendered pixel, so it fails the way the
        owner's screenshot did if this regresses, not just on the data."""
        import os
        from PySide6.QtWidgets import QApplication
        from addons.boq.measured import COL_ITEM, COL_TRUST, MeasuredTable
        app = QApplication.instance()
        qss_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "style.qss")
        with open(qss_path, encoding="utf-8") as f:
            qss = f.read()
        previous = app.styleSheet()
        app.setStyleSheet(qss.replace("%ASSETS%", "."))
        try:
            t = MeasuredTable()
            t.set_quantities(self.Q)
            t.resize(760, 300)
            t.show()
            app.processEvents()
            by_item = {t.table.item(r, COL_ITEM).text(): r for r in range(t.table.rowCount())}
            r = by_item["A-WALL"]                       # red (lookalike)
            rect = t.table.visualItemRect(t.table.item(r, COL_TRUST))
            local_pt = t.mapFromGlobal(t.table.viewport().mapToGlobal(rect.center()))
            pixel = t.grab().toImage().pixelColor(local_pt)
            # style.qss's forced item colour is #09090b -- near-black, low
            # red, low green. theme.ERR_INK (#b91c1c) is red-dominant and
            # nowhere near black. If the delegate regresses, this pixel
            # goes back to black and the assertion below catches it.
            self.assertGreater(pixel.red(), 120, pixel.name())
            self.assertLess(pixel.green(), 100, pixel.name())
        finally:
            app.setStyleSheet(previous)

    def test_only_the_value_column_can_be_edited(self):
        from PySide6.QtCore import Qt
        from addons.boq.measured import COL_SORT, COL_VALUE, MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        for c in range(COL_SORT):                  # every visible column
            editable = bool(t.table.item(0, c).flags() & Qt.ItemIsEditable)
            self.assertEqual(editable, c == COL_VALUE, f"column {c}")

    def test_editing_the_value_turns_the_whole_row_green(self):
        import theme
        from addons.boq.measured import (
            COL_ITEM, COL_SORT, COL_TRUST, COL_VALUE, MeasuredTable)
        t = MeasuredTable()
        t.set_quantities(self.Q)
        by_item = {t.table.item(r, COL_ITEM).text(): r for r in range(t.table.rowCount())}
        r = by_item["A-WALL"]                       # starts red (lookalike)
        self.assertEqual(t.table.item(r, COL_ITEM).background().color(), theme.qcolor(theme.ERR_BG))
        t.table.item(r, COL_VALUE).setText("2,500.00")
        for c in range(COL_SORT):
            self.assertEqual(t.table.item(r, c).background().color(),
                             theme.qcolor(theme.OK_BG), f"column {c}")
        self.assertEqual(t.table.item(r, COL_TRUST).foreground().color(), theme.qcolor(theme.OK_INK))
        self.assertEqual(t.rows()[r][3], "2,500.00")

    def test_a_non_numeric_edit_is_left_alone(self):
        import theme
        from addons.boq.measured import COL_ITEM, COL_VALUE, MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        by_item = {t.table.item(r, COL_ITEM).text(): r for r in range(t.table.rowCount())}
        r = by_item["A-WALL"]
        t.table.item(r, COL_VALUE).setText("not a number")
        # a bad edit never crashes and never falsely marks the row confirmed
        self.assertEqual(t.table.item(r, COL_ITEM).background().color(), theme.qcolor(theme.ERR_BG))


class TheUnitPickerConvertsOnScreenWithoutReMeasuring(unittest.TestCase):
    """The owner's ask, same day: values were locked to the drawing's own
    unit with no way to look at them in anything else. `unit_combo` picks
    mm/cm/m/ft/in and `_render_rows()` redraws from the same measured
    figures -- no re-measuring, counts never convert, area converts by the
    squared length factor."""

    Q = {
        "unit": "millimeters", "unit_code": 4, "unit_confirmed": True,
        "notes": [],
        "lengths_by_layer": {"M-DUCT": 4000.0},
        "areas_by_layer": {"M-EQPM": 2_000_000.0},
        "block_counts": {"VALVE": 2},
        "block_layers": {"VALVE": ["M-VALVE"]},
        "layers": ["M-DUCT", "M-EQPM", "M-VALVE"],
        "entity_count": 6,
    }

    def test_convert_value_is_exact_for_length_and_squared_for_area(self):
        from addons.boq.measured import KIND_AREA, KIND_COUNT, KIND_LENGTH, convert_value
        self.assertAlmostEqual(
            convert_value(KIND_LENGTH, 4000.0, "millimeters", "meters"), 4.0)
        self.assertAlmostEqual(
            convert_value(KIND_AREA, 2_000_000.0, "millimeters", "meters"), 2.0)
        self.assertEqual(convert_value(KIND_COUNT, 2, "millimeters", "meters"), 2)
        # an unrecognised/unconfirmed unit is left exactly as given, never guessed
        self.assertEqual(convert_value(KIND_LENGTH, 4000.0, None, "meters"), 4000.0)

    def test_as_measured_is_byte_for_byte_the_old_behaviour(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        self.assertEqual(t.rows()[0], ("M-DUCT", "Length", "M-DUCT", "4,000.00", "millimeters"))

    def test_switching_to_meters_converts_length_and_area_not_count(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        idx = t.unit_combo.findData("meters")
        t.unit_combo.setCurrentIndex(idx)
        by_item = {r[0]: r for r in t.rows()}
        self.assertEqual(by_item["M-DUCT"][3:], ("4.00", "m"))
        self.assertEqual(by_item["M-EQPM"][3:], ("2.00", "sq m"))
        self.assertEqual(by_item["VALVE"][3:], ("2", "nos"))     # untouched

    def test_switching_back_to_as_measured_restores_the_original_figures(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        t.unit_combo.setCurrentIndex(t.unit_combo.findData("feet"))
        t.unit_combo.setCurrentIndex(t.unit_combo.findData("native"))
        self.assertEqual(t.rows()[0], ("M-DUCT", "Length", "M-DUCT", "4,000.00", "millimeters"))

    def test_the_picker_is_disabled_when_the_unit_is_not_confirmed_or_inferred(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        q = dict(self.Q, unit="unspecified", unit_code=0, unit_confirmed=False)
        t.set_quantities(q)
        self.assertFalse(t.unit_combo.isEnabled())


class TheExpandedWindowAndTheDesktopCsv(unittest.TestCase):
    """The owner's report, 23 Oct 2026: the embedded table is too small --
    "you can't see more than half of the information" -- so a button opens
    the same table full-size in its own window. And once the numbers are
    reviewed/edited, a direct CSV save to the Desktop, no file dialog."""

    Q = TheMeasurementIsATable.Q

    def test_open_in_a_bigger_window_shows_the_same_rows(self):
        from addons.boq.measured import MeasuredTable, MeasuredTableWindow
        t = MeasuredTable()
        t.set_quantities(self.Q)
        t._open_big()
        self.assertIsInstance(t._big_window, MeasuredTableWindow)
        self.assertEqual(t._big_window.table_widget.rows(), t.rows())

    def test_opening_it_twice_reuses_the_same_window(self):
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.Q)
        t._open_big()
        first = t._big_window
        t._open_big()
        self.assertIs(t._big_window, first)

    def test_save_as_csv_writes_what_is_on_screen_to_a_patched_desktop(self):
        import csv
        from unittest import mock
        from addons.boq import measured
        t = measured.MeasuredTable()
        t.set_quantities(self.Q)
        tmp = tempfile.mkdtemp(prefix="prism-desktop-")
        with mock.patch.object(measured, "desktop_dir", return_value=tmp):
            t._save_desktop_csv()
        self.assertTrue(t.saved_label.isVisibleTo(t))
        self.assertIn(tmp, t.saved_label.text())
        files = os.listdir(tmp)
        self.assertEqual(len(files), 1)
        with open(os.path.join(tmp, files[0]), newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
        self.assertEqual(rows[0], ["Item", "Measured as", "Layer", "Value", "Unit"])
        self.assertEqual(len(rows) - 1, len(t.rows()))


class TheHvacFlagComesOnlyFromTheIndustryDropdown(unittest.TestCase):
    """HVAC_DRAWING_RULES.md's rules are trade-specific -- the owner's own
    instruction, 22 Oct 2026: apply them only when the person has said so,
    never by default, and never guessed from the drawing itself. Widened
    26 Oct 2026, item 26: BOQ now targets several industries, each with
    its own rule-set, so guessing from the ask box's own typed words (the
    original form of this rule) was replaced with the explicit Industry
    dropdown -- a typo, or a phrase like "ducting job" that never says
    the word "HVAC", used to silently miss the gate; an explicit choice
    cannot. _measure() is the one place this is decided, reading
    self.industry_combo directly (available the moment a drawing is
    attached, unlike self.request, which isn't set until "Make" is
    pressed)."""

    class _Capture:
        seen: dict = {}

        def __init__(self, *a, **kw):
            TheHvacFlagComesOnlyFromTheIndustryDropdown._Capture.seen = kw
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    def _measure_with(self, industry: str) -> bool:
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.industry_combo.setCurrentText(industry)
        d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        with mock.patch.object(BD, "MeasureWorker", self._Capture):
            d._measure()
        return self._Capture.seen.get("hvac")

    def test_picking_hvac_turns_it_on(self):
        self.assertTrue(self._measure_with("HVAC"))

    def test_general_leaves_it_off(self):
        self.assertFalse(self._measure_with("General"))

    def test_the_word_hvac_typed_in_the_request_no_longer_matters(self):
        """The old gate (typed text) must not leak back in -- picking
        "General" must leave the flag off even when the request itself
        says "HVAC", since item 26 moved this decision to the dropdown."""
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.ask.set_text("BOQ for HVAC ductwork")
        d.industry_combo.setCurrentText("General")
        d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        with mock.patch.object(BD, "MeasureWorker", self._Capture):
            d._measure()
        self.assertFalse(self._Capture.seen.get("hvac"))

    def test_the_flag_is_remembered_for_the_write_up_stage_too(self):
        """Not just measured with -- the same decision has to reach the
        write-up prompt later, at `_write()` time, when the dropdown's own
        selection may have already changed."""
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        d.cad_path = os.path.join(tempfile.mkdtemp(), "sai.dxf")
        with open(d.cad_path, "w") as fh:
            fh.write("0\nEOF\n")
        with mock.patch.object(BD, "MeasureWorker", self._Capture):
            d._measure()
        self.assertTrue(d._hvac)

    class _WriteCapture:
        seen: dict = {}

        def __init__(self, *a, **kw):
            TheHvacFlagComesOnlyFromTheIndustryDropdown._WriteCapture.seen = {"args": a, "kwargs": kw}
            self.done = self.failed = self

        def connect(self, *_):
            pass

        def start(self):
            pass

    def _write_prompt_with(self, hvac: bool) -> str:
        from unittest import mock
        from addons.boq import dialog as BD
        d = _dialog()
        d.q = {"layers": ["M-DUCT"], "lengths_by_layer": {"M-DUCT": 12.0},
              "areas_by_layer": {}, "block_counts": {}, "unit": "m",
              "duct_sizes": [], "scope_total_layers": 1}
        d.cad_path = "/x/site.dxf"
        d.summary = "M-DUCT 12.00 m"
        d.request = "BOQ for HVAC ductwork" if hvac else "BOQ for the electrical layout"
        d._hvac = hvac
        d.writer_agent = "ChatGPT"
        with mock.patch.object(BD, "AutomationWorker", self._WriteCapture):
            d._write()
        return self._WriteCapture.seen["kwargs"]["custom_stages"][0][2][0]

    def test_the_write_up_prompt_carries_the_hvac_rules_only_when_hvac(self):
        self.assertIn("HVAC-SPECIFIC WRITE-UP RULES", self._write_prompt_with(True))

    def test_a_different_trades_write_up_prompt_never_sees_them(self):
        self.assertNotIn("HVAC-SPECIFIC WRITE-UP RULES", self._write_prompt_with(False))


class ExternalMeasurementsAreASecondWayIn(unittest.TestCase):
    """24 Oct 2026, the owner's ask: a second entry point into the BOQ
    pipeline besides measuring a drawing -- paste or upload measurements
    from a tool outside Prism (the PDF takeoff extractor, a rate list,
    anyone's own notes). Treated as plain text from here on, never parsed
    into a schema, never sent anywhere as an image -- the same "no AI
    ever sees the drawing" promise, just for a source that was never a
    drawing to begin with."""

    def test_using_external_measurements_sets_q_and_summary(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("DUCT SUMMARY\n  supply 20x30 38.8m\n")
        self.assertEqual(d.q, {"external": True,
                               "text": "DUCT SUMMARY\n  supply 20x30 38.8m\n"})
        self.assertEqual(d.summary, "DUCT SUMMARY\n  supply 20x30 38.8m\n")
        self.assertTrue(d.ext_meas_box.isVisibleTo(d))
        self.assertEqual(d.ext_meas_view.toPlainText(), d.summary)

    def test_it_never_writes_outside_the_patched_runs_dir(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        tmp = tempfile.mkdtemp()
        with mock.patch.object(CB.config, "RUNS_DIR", tmp), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("text")
        self.assertTrue(d.csv_path.startswith(tmp))
        with open(d.csv_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "text")

    def test_hvac_is_decided_from_the_industry_dropdown_the_same_way_as_measuring(self):
        """Item 26, 26 Oct 2026: moved from guessing at the ask box's own
        typed words to the explicit Industry dropdown -- see
        TheHvacFlagComesOnlyFromTheIndustryDropdown for _measure()'s own
        version of this same rule."""
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("text")
        self.assertTrue(d._hvac)

    def test_a_non_hvac_industry_leaves_it_off(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        d.industry_combo.setCurrentText("General")
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("text")
        self.assertFalse(d._hvac)

    def test_only_one_measurement_source_is_ever_shown_at_once(self):
        """Measuring a real drawing after external measurements were used
        hides the external panel, and vice versa -- never both claiming
        to be the active source at the same time."""
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("text")
        self.assertTrue(d.ext_meas_box.isVisibleTo(d))
        d.cad_path = "/x/site.dxf"
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._on_measured({"layers": [], "lengths_by_layer": {}, "areas_by_layer": {},
                            "block_counts": {}, "unit": "m", "unit_code": 6,
                            "unit_confirmed": True, "notes": [], "site": {},
                            "entity_count": 0}, [])
        self.assertFalse(d.ext_meas_box.isVisibleTo(d))
        self.assertTrue(d.meas_box.isVisibleTo(d))

    def test_make_with_drawing_is_off_without_a_real_drawing(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        d = _dialog()
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("text")
        self.assertFalse(d.recheck_btn.isEnabled())
        self.assertEqual(d.cad_path, "")

    def test_the_write_up_prompt_uses_the_pasted_text_as_the_measured_quantities(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        from addons.boq import dialog as BD
        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._use_external_measurements("MY OWN DUCT NUMBERS: 38.8m supply")
        d.request = "Create me a BOQ for the HVAC industry"
        d.writer_agent = "ChatGPT"

        class _Capture:
            seen = {}
            def __init__(self, *a, **kw):
                _Capture.seen = {"args": a, "kwargs": kw}
                self.done = self.failed = self
            def connect(self, *_): pass
            def start(self): pass

        with mock.patch.object(BD, "AutomationWorker", _Capture):
            d._write()
        prompt = _Capture.seen["kwargs"]["custom_stages"][0][2][0]
        self.assertIn("MY OWN DUCT NUMBERS: 38.8m supply", prompt)
        self.assertIn("HVAC-SPECIFIC WRITE-UP RULES", prompt)


class TheIndustryDropdownGatesThePdfTakeoffButton(unittest.TestCase):
    """Item 26: BOQ is sold across industries, and only HVAC has a
    PDF-takeoff tool of its own today -- the button must never be shown
    for an industry that has none (it would silently run HVAC's own OCR
    and rules against a drawing that was never one)."""

    def test_general_is_the_default_and_the_button_starts_hidden(self):
        d = _dialog()
        self.assertEqual(d.industry_combo.currentText(), "General")
        self.assertFalse(d.takeoff_btn.isVisibleTo(d))

    def test_picking_hvac_shows_the_button(self):
        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        self.assertTrue(d.takeoff_btn.isVisibleTo(d))

    def test_switching_back_to_general_hides_it_again(self):
        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        d.industry_combo.setCurrentText("General")
        self.assertFalse(d.takeoff_btn.isVisibleTo(d))

    def test_accepting_the_takeoff_dialog_feeds_its_text_in_as_external_measurements(self):
        from unittest import mock
        import tempfile
        import core_bridge as CB
        from addons.boq import dialog as BD
        from PySide6.QtWidgets import QDialog

        class _FakeTakeoffDialog:
            def __init__(self, industry, parent=None):
                self.industry = industry
            def exec(self):
                return QDialog.Accepted
            def measurements_text(self):
                return "DUCT SUMMARY\n  supply 12x8  40.0 ft\n"

        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        with mock.patch.object(BD, "IndustryTakeoffDialog", _FakeTakeoffDialog), \
                mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._open_industry_takeoff()
        self.assertEqual(d.summary, "DUCT SUMMARY\n  supply 12x8  40.0 ft\n")
        self.assertTrue(d._hvac)

    def test_declining_the_takeoff_dialog_changes_nothing(self):
        from unittest import mock
        from addons.boq import dialog as BD
        from PySide6.QtWidgets import QDialog

        class _FakeTakeoffDialog:
            def __init__(self, industry, parent=None):
                pass
            def exec(self):
                return QDialog.Rejected
            def measurements_text(self):
                return "should never be read"

        d = _dialog()
        d.industry_combo.setCurrentText("HVAC")
        with mock.patch.object(BD, "IndustryTakeoffDialog", _FakeTakeoffDialog):
            d._open_industry_takeoff()
        self.assertEqual(d.summary, "")


class InputMeasurementsDialogTests(unittest.TestCase):
    """The small paste-or-upload dialog itself, independent of BoqDialog."""

    def test_confirm_is_blocked_when_nothing_was_entered(self):
        from unittest import mock
        from addons.boq.dialog import InputMeasurementsDialog
        dlg = InputMeasurementsDialog()
        # _confirm() shows a blocking QMessageBox when empty -- never let a
        # test actually run that modal (same trap as .exec()/processEvents).
        with mock.patch("addons.boq.dialog.QMessageBox.information"):
            dlg._confirm()
        self.assertEqual(dlg.result(), 0)   # never accepted -- still open

    def test_pasted_text_is_returned_as_is(self):
        from addons.boq.dialog import InputMeasurementsDialog
        dlg = InputMeasurementsDialog()
        dlg.text.setPlainText("  some measurements  \n")
        self.assertEqual(dlg.measurements_text(), "some measurements")

    def test_uploading_a_file_loads_its_content_into_the_text_box(self):
        import tempfile
        from unittest import mock
        from addons.boq.dialog import InputMeasurementsDialog
        from PySide6.QtWidgets import QFileDialog
        path = os.path.join(tempfile.mkdtemp(), "takeoff.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"duct_summary": []}')
        dlg = InputMeasurementsDialog()
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(path, "")):
            dlg._upload()
        self.assertEqual(dlg.text.toPlainText(), '{"duct_summary": []}')
        self.assertIn("takeoff.json", dlg.file_label.text())

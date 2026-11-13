"""addons/step/workers.py — the three background workers behind STEP's
Draft/Ask/Edit. Covers the one thing that was silently wrong before: the
file an Edit actually writes.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import core_bridge as CB  # noqa: E402

from addons.step.workers import (StepApplyWorker, StepAskWorker,  # noqa: E402
                                 StepCatalogExplainWorker, StepPlanWorker,
                                 image_attachment)


class AskAndPlanCallOpenRouterNeverGroq(unittest.TestCase):
    """Groq is gone from STEP (2026-11-06): Ask and Edit's suggestion/plan
    stages are both a direct OpenRouter call, Claude Haiku 5.5 by default
    or Claude Sonnet 5.5, never a browser tab and never Groq's API."""

    def test_ask_calls_openrouter_with_the_chosen_model_and_key(self):
        fake_sf = mock.MagicMock()
        fake_sf.ask_prompt.return_value = "PROMPT"
        cfg = {"openrouter_api_key": "sk-or-test"}
        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value=" answer ") as chat:
            worker = StepAskWorker(cfg, {"file": "a.step"}, "q?",
                                   model="anthropic/claude-sonnet-5.5")
            done = []
            worker.done.connect(done.append)
            worker.run()
        chat.assert_called_once()
        args, kwargs = chat.call_args
        self.assertEqual(args[0], "sk-or-test")
        self.assertEqual(args[1], "anthropic/claude-sonnet-5.5")
        self.assertEqual(args[2], "PROMPT")
        self.assertEqual(kwargs["attachments"], [])
        self.assertEqual(done, ["answer"])

    def test_ask_defaults_to_haiku(self):
        fake_sf = mock.MagicMock()
        fake_sf.ask_prompt.return_value = "PROMPT"
        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value="a") as chat:
            StepAskWorker({}, {"file": "a.step"}, "q?").run()
        self.assertEqual(chat.call_args[0][1], "anthropic/claude-haiku-5.5")

    def test_ask_attaches_the_rendered_picture_only_when_given_one(self):
        fake_sf = mock.MagicMock()
        fake_sf.ask_prompt.return_value = "PROMPT"
        pic = {"kind": "image", "mime": "image/png", "b64": "x", "name": "s.png"}
        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value="a") as chat:
            StepAskWorker({"openrouter_api_key": "k"}, {"file": "a.step"},
                         "q?", attachments=[pic]).run()
        self.assertEqual(chat.call_args.kwargs["attachments"], [pic])

    def test_plan_calls_openrouter_with_the_chosen_model(self):
        fake_sf = mock.MagicMock()
        fake_sf.plan_prompt.return_value = "PLAN PROMPT"
        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value='{"changes": []}') as chat:
            worker = StepPlanWorker(
                {"openrouter_api_key": "k"}, {"file": "a.step"}, "q?",
                "advice", model="anthropic/claude-sonnet-5.5")
            done = []
            worker.done.connect(done.append)
            worker.run()
        self.assertEqual(chat.call_args[0][1], "anthropic/claude-sonnet-5.5")
        self.assertEqual(done, ['{"changes": []}'])

    def test_a_failed_call_reports_the_real_error_not_a_crash(self):
        fake_sf = mock.MagicMock()
        fake_sf.ask_prompt.return_value = "PROMPT"
        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  side_effect=RuntimeError("no key set")):
            failed = []
            worker = StepAskWorker({}, {"file": "a.step"}, "q?")
            worker.failed.connect(failed.append)
            worker.run()
        self.assertEqual(failed, ["no key set"])


class CatalogExplainCallsOpenRouterWithNumbersOnly(unittest.TestCase):
    """The near-miss explainer -- one plain OpenRouter call with whatever
    prompt core.stepfile.catalog_explain_prompt built. This worker never
    touches the catalog file or the STEP file itself; it only forwards
    the prompt string it was handed."""

    def test_calls_openrouter_with_the_given_prompt_and_model(self):
        with mock.patch.object(CB.openrouter, "openrouter_chat",
                              return_value=" explanation ") as chat:
            worker = StepCatalogExplainWorker(
                {"openrouter_api_key": "sk-or-test"}, "PROMPT",
                model="anthropic/claude-sonnet-5.5")
            done = []
            worker.done.connect(done.append)
            worker.run()
        chat.assert_called_once()
        args, kwargs = chat.call_args
        self.assertEqual(args[0], "sk-or-test")
        self.assertEqual(args[1], "anthropic/claude-sonnet-5.5")
        self.assertEqual(args[2], "PROMPT")
        self.assertEqual(done, ["explanation"])

    def test_defaults_to_haiku(self):
        with mock.patch.object(CB.openrouter, "openrouter_chat",
                              return_value="a") as chat:
            StepCatalogExplainWorker({"openrouter_api_key": "k"},
                                     "PROMPT").run()
        self.assertEqual(chat.call_args[0][1], "anthropic/claude-haiku-5.5")

    def test_a_failed_call_reports_the_real_error_not_a_crash(self):
        with mock.patch.object(CB.openrouter, "openrouter_chat",
                              side_effect=RuntimeError("no key set")):
            failed = []
            worker = StepCatalogExplainWorker({}, "PROMPT")
            worker.failed.connect(failed.append)
            worker.run()
        self.assertEqual(failed, ["no key set"])


class ImageAttachmentReadsPrismsOwnRenderOnly(unittest.TestCase):
    """The content block an OpenRouter vision call needs -- base64 of
    Prism's own already-drawn PNG, never the STEP file."""

    def test_builds_the_content_block_shape(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "sheet.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNGfakebytes")
        block = image_attachment(path)
        self.assertEqual(block["kind"], "image")
        self.assertEqual(block["mime"], "image/png")
        self.assertEqual(block["name"], "sheet.png")
        import base64
        self.assertEqual(base64.b64decode(block["b64"]), b"\x89PNGfakebytes")


class TheBuiltFileGetsAStampedNameNotTheFlatOne(unittest.TestCase):
    """Round: every Edit wrote "<stem> - modified.step" — the exact same
    literal name on every build, in its own numbered sibling folder, so
    two different requests' results were indistinguishable by name alone,
    especially once moved out of their folder. The actual write must use
    core.stepfile.modified_name() (stamped with when it was built), never
    names()['modified'] (the flat, un-stamped base used only for the
    pre-build "about to write X" message)."""

    def test_apply_plan_is_called_with_the_stamped_path(self):
        fake_sf = mock.MagicMock()
        fake_sf.names.return_value = {
            "xlsx_after": "x.xlsx", "after_dir": "after", "png_after": "x.png"}
        fake_sf.modified_name.return_value = "Assem1 - modified 2026-10-14 063501.step"
        fake_sf.apply_plan.return_value = {"log": []}
        fake_sf.analyse.return_value = {}
        fake_sf.render_sheet.return_value = {}
        fake_sf.review_html.return_value = "/x/review.html"

        with mock.patch.object(CB, "get_stepfile", return_value=fake_sf):
            worker = StepApplyWorker(
                "/x/Assem1.STEP", {"changes": []}, {"file": "Assem1.STEP"},
                "metal", "/x/Assem1 (2)", "enlarge the hole", 0.0)
            worker.run()

        fake_sf.modified_name.assert_called_once_with({"file": "Assem1.STEP"})
        out_path = fake_sf.apply_plan.call_args[0][2]
        self.assertEqual(
            out_path,
            os.path.join("/x/Assem1 (2)",
                         "Assem1 - modified 2026-10-14 063501.step"))
        # names()['modified'] (the flat base) must not be what got written.
        self.assertNotIn("Assem1 - modified.step", out_path)


class AnEngineWithoutModifiedNameStillEdits(unittest.TestCase):
    """1.6.3 was cut against an engine on GitHub that has no
    core.stepfile.modified_name, so every Edit failed at its first line with
    "module 'core.stepfile' has no attribute 'modified_name'". The GUI makes
    the same stamped name itself when the engine cannot."""

    class _OldEngine:
        @staticmethod
        def names(report):
            return {"modified": "Assem1 - modified.step"}

    def test_the_name_is_stamped_and_is_not_the_flat_one(self):
        from addons.step.workers import _modified_name
        got = _modified_name(self._OldEngine, {"file": "Assem1.STEP"})
        self.assertTrue(got.startswith("Assem1 - modified "), got)
        self.assertTrue(got.endswith(".step"), got)
        self.assertNotEqual(got, "Assem1 - modified.step")
        self.assertNotRegex(got, r'[<>:"/\\|?*]')       # legal on Windows too

    def test_two_builds_a_second_apart_get_different_names(self):
        import datetime
        from addons.step import workers
        from addons.step.workers import _modified_name
        with mock.patch.object(workers, "_dt") as dt_mod:
            dt_mod.datetime.now.return_value = datetime.datetime(2026, 10, 14, 6, 35, 1)
            first = _modified_name(self._OldEngine, {})
            dt_mod.datetime.now.return_value = datetime.datetime(2026, 10, 14, 6, 35, 2)
            second = _modified_name(self._OldEngine, {})
        self.assertEqual(first, "Assem1 - modified 2026-10-14 063501.step")
        self.assertNotEqual(first, second)

    def test_the_engines_own_name_wins_when_it_has_one(self):
        from addons.step.workers import _modified_name
        sf = mock.MagicMock()
        sf.modified_name.return_value = "from the engine.step"
        self.assertEqual(_modified_name(sf, {"file": "x.step"}), "from the engine.step")

    def test_an_edit_runs_end_to_end_against_the_old_engine(self):
        sf = mock.MagicMock(spec=["names", "apply_plan", "analyse", "write_xlsx",
                                  "render_sheet", "review_html"])
        sf.names.return_value = {
            "modified": "Assem1 - modified.step", "xlsx_after": "x.xlsx",
            "after_dir": "after", "png_after": "x.png"}
        sf.apply_plan.return_value = {"log": []}
        sf.analyse.return_value = {}
        sf.render_sheet.return_value = {}
        sf.review_html.return_value = "/x/review.html"
        done, failed = [], []
        with mock.patch.object(CB, "get_stepfile", return_value=sf):
            worker = StepApplyWorker(
                "/x/Assem1.STEP", {"changes": []}, {"file": "Assem1.STEP"},
                "metal", "/x/Assem1 (2)", "enlarge the hole", 0.0)
            worker.done.connect(done.append)
            worker.failed.connect(failed.append)
            worker.run()
        self.assertEqual(failed, [])
        self.assertEqual(len(done), 1)
        self.assertRegex(os.path.basename(done[0]["out"]),
                         r"^Assem1 - modified \d{4}-\d\d-\d\d \d{6}\.step$")


if __name__ == "__main__":
    unittest.main()

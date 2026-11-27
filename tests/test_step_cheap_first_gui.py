"""STEP asks go through the engine's cheap-first pipeline (core.step_cheap).

Real workers, the real StepDialog (offscreen) and a real STEP file built with
cadquery, so every answer is a known one. Only the AI itself is fake: a stand
in for ai_client.chat that records which role was called, so nothing is paid
for and no network is used. HOME is a sandbox (the cap file and the answer log
live under ~/.prism), so the real ~/.prism is never touched.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core_bridge as CB  # noqa: E402
import i18n  # noqa: E402

try:
    import cadquery as cq  # noqa: E402
except ImportError:                                     # pragma: no cover
    cq = None

SC = CB.get_step_cheap()
SF = CB.get_stepfile()

from PySide6.QtWidgets import QApplication  # noqa: E402
from addons.step import dialog as SD  # noqa: E402
from addons.step.workers import (StepAskWorker, StepPlanWorker,  # noqa: E402
                                 path_label)

_app = QApplication.instance() or QApplication([])

NEEDS_AI = "how could this be easier to assemble"
GOOD = {"answer": "Enlarge H2 from Ø5 to Ø6 mm; PLATE has 4 holes.",
        "claims": [{"type": "part", "name": "PLATE"},
                   {"type": "hole_count", "part": "PLATE", "value": 4},
                   {"type": "hole_tag", "tag": "H2", "dia_mm": 5}],
        "changes": [{"op": "enlarge_hole", "part": "PLATE", "dia_mm": 5,
                     "new_dia_mm": 6, "hole": "H2", "why": "easier bolt"}],
        "advice": ["Keep Ø8 as is."]}
LIE = dict(GOOD, claims=[{"type": "hole_count", "part": "PLATE", "value": 9}])

# What a customer must never read on this branch: no quality display
# setting exists here, so no model is named.
MODEL_WORDS = ("haiku", "sonnet", "claude", "opus", "step.fast", "reasoner")


def _build_report():
    d = tempfile.mkdtemp(prefix="prism-test-cheap-")
    plate = (cq.Workplane("XY").box(100, 50, 3).faces(">Z").workplane()
             .pushPoints([(-30, 0), (0, 0), (30, 0)]).hole(5)
             .faces(">Z").workplane().pushPoints([(-40, 15)]).hole(8))
    asm = cq.Assembly()
    asm.add(plate, name="PLATE")
    asm.add(cq.Workplane("XY").box(20, 20, 10).translate((0, 0, 20)),
            name="BLOCK")
    path = os.path.join(d, "fx.step")
    asm.export(path)
    return path, SF.analyse(path, "metal")


@unittest.skipIf(cq is None or SC is None, "needs cadquery and the engine's step_cheap")
class _Base(unittest.TestCase):
    """A fake server: `chat` answers from a queue and records the roles."""

    @classmethod
    def setUpClass(cls):
        cls.path, cls.report = _build_report()

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="prism-test-home-")
        self.roles: list = []
        self.replies: list = []
        self.sent: list = []
        patches = [
            mock.patch.dict(os.environ, {"HOME": self.home}),
            mock.patch.object(CB.ai_client, "active", return_value=True),
            mock.patch.object(CB.ai_client, "_auth",
                              return_value={"license_id": "lic-test"}),
            mock.patch.object(CB.ai_client, "chat", side_effect=self._chat),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        # The old direct route must never be taken on the server.
        p = mock.patch.object(CB.openrouter, "openrouter_chat",
                              side_effect=AssertionError("direct call"))
        p.start()
        self.addCleanup(p.stop)

    def _chat(self, role, prompt, **kw):
        self.roles.append(role)
        self.sent.append({"role": role, "prompt": prompt,
                          "model": kw.get("model", ""),
                          "attachments": kw.get("attachments") or []})
        kw["usage_sink"]["credits_mc"] = 2000 if role == SC.ROLE_FAST else 40000
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)

    def run_ask(self, question, **kw):
        w = StepAskWorker({}, self.report, question, **kw)
        out = {"done": [], "answered": [], "failed": []}
        w.done.connect(out["done"].append)
        w.answered.connect(out["answered"].append)
        w.failed.connect(out["failed"].append)
        w.run()
        return out

    def run_plan(self, question, prior=None, **kw):
        w = StepPlanWorker({}, self.report, question, "advice", prior=prior, **kw)
        out = {"done": [], "answered": [], "failed": []}
        w.done.connect(out["done"].append)
        w.answered.connect(out["answered"].append)
        w.failed.connect(out["failed"].append)
        w.run()
        return out


class EachPathAnswersAndIsNamedInPlainWords(_Base):

    def test_a_fact_is_measured_from_the_file_with_no_ai_call(self):
        out = self.run_ask("how many holes are there")
        self.assertEqual(self.roles, [])
        self.assertIn("4 hole(s)", out["done"][0])
        self.assertEqual(path_label(out["answered"][0]), "Measured from the file")
        self.assertEqual(out["answered"][0]["credits"], 0)

    def test_a_plain_edit_is_local_and_carries_a_plan(self):
        out = self.run_ask("enlarge H2 to 6 mm")
        self.assertEqual(self.roles, [])
        res = out["answered"][0]
        self.assertEqual(res["path"], "local")
        self.assertEqual(res["plan"]["changes"][0]["new_dia_mm"], 6.0)

    def test_everything_else_is_a_quick_check_by_the_cheap_role_only(self):
        self.replies = [GOOD]
        out = self.run_ask(NEEDS_AI)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(path_label(out["answered"][0]), "Quick check")
        self.assertEqual(out["done"], [GOOD["answer"]])

    def test_a_failed_check_is_a_full_check_after_one_escalation(self):
        self.replies = [LIE, GOOD]
        out = self.run_ask(NEEDS_AI)
        self.assertEqual(self.roles, [SC.ROLE_FAST, SC.ROLE_ESCALATE])
        self.assertEqual(path_label(out["answered"][0]), "Full check")

    def test_an_answer_that_never_checks_out_says_so_and_proposes_nothing(self):
        self.replies = [LIE, LIE]
        out = self.run_ask(NEEDS_AI)
        self.assertEqual(len(self.roles), 2)
        self.assertEqual(path_label(out["answered"][0]), "Could not be verified")
        self.assertEqual(out["answered"][0]["plan"]["changes"], [])
        self.assertIn("could not verify", out["done"][0])

    def test_no_label_names_a_model(self):
        for text in ("Measured from the file", "Quick check", "Full check",
                     "Could not be verified"):
            for word in MODEL_WORDS:
                self.assertNotIn(word, text.lower())
        self.assertEqual(path_label({"path": "capped"}), "")
        self.assertEqual(path_label(None), "")


class TheCapIsAPlainSentence(_Base):

    def _capped(self, which, value):
        with mock.patch.object(SC, which, value):
            return self.run_ask(NEEDS_AI)

    def test_the_monthly_cap_says_what_it_is_when_it_resets_and_what_still_works(self):
        out = self._capped("STEP_AI_FILES_PER_MONTH", 0)
        self.assertEqual(self.roles, [])
        self.assertEqual(out["done"], [])
        msg = out["failed"][0]
        self.assertIn("this month's limit of AI-assisted STEP files", msg)
        self.assertIn("next month", msg)
        self.assertIn("still work and are free", msg)

    def test_the_daily_cap_says_tomorrow(self):
        out = self._capped("STEP_AI_FILES_PER_DAY", 0)
        self.assertEqual(self.roles, [])
        msg = out["failed"][0]
        self.assertIn("today's limit of AI-assisted STEP files", msg)
        self.assertIn("tomorrow", msg)
        self.assertIn("Measurements", msg)

    def test_the_cap_message_has_no_credits_and_no_model(self):
        msg = self._capped("STEP_AI_FILES_PER_DAY", 0)["failed"][0].lower()
        for word in MODEL_WORDS + ("credit",):
            self.assertNotIn(word, msg)

    def test_local_measuring_still_works_at_the_cap_for_free(self):
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 0), \
                mock.patch.object(SC, "STEP_AI_FILES_PER_MONTH", 0):
            facts = self.run_ask("how many holes are there")
            edit = self.run_plan("enlarge H2 to 6 mm")
        self.assertEqual(self.roles, [])
        self.assertEqual(facts["failed"], [])
        self.assertIn("4 hole(s)", facts["done"][0])
        self.assertEqual(edit["failed"], [])
        self.assertEqual(json.loads(edit["done"][0])["changes"][0]["new_dia_mm"], 6.0)

    def test_the_plan_step_reports_the_cap_too(self):
        out = None
        with mock.patch.object(SC, "STEP_AI_FILES_PER_MONTH", 0):
            out = self.run_plan(NEEDS_AI)
        self.assertEqual(out["done"], [])
        self.assertIn("this month's limit", out["failed"][0])


class ThePlanReusesTheAnswerInsteadOfAskingAgain(_Base):

    def test_a_prior_answer_with_no_change_is_not_paid_for_twice(self):
        self.replies = [dict(GOOD, changes=[])]
        prior = self.run_ask(NEEDS_AI)["answered"][0]
        out = self.run_plan(NEEDS_AI, prior=prior)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(SF.parse_plan(out["done"])[0]["changes"], [])

    def test_a_prior_plan_with_changes_makes_no_second_call(self):
        self.replies = [GOOD]
        prior = self.run_ask(NEEDS_AI)["answered"][0]
        out = self.run_plan(NEEDS_AI, prior=prior)
        self.assertEqual(self.roles, [SC.ROLE_FAST])        # still just one
        plan, why = SF.parse_plan(out["done"])
        self.assertEqual(why, "")
        self.assertEqual(plan["changes"][0]["new_dia_mm"], 6.0)
        self.assertEqual(path_label(out["answered"][0]), "Quick check")

    def test_without_a_prior_the_question_is_asked_once_more(self):
        self.replies = [GOOD]
        out = self.run_plan(NEEDS_AI)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(SF.parse_plan(out["done"])[0]["changes"][0]["hole"], "H2")

    def test_an_unverified_plan_is_empty_and_explains_why(self):
        self.replies = [LIE, LIE]
        out = self.run_plan(NEEDS_AI)
        plan, _ = SF.parse_plan(out["done"])
        self.assertEqual(plan["changes"], [])
        self.assertIn("could not verify", plan["advice"][0])


class AFollowUpIsJudgedOnWhatThePersonJustTyped(_Base):

    def test_earlier_conversation_cannot_trigger_a_local_answer(self):
        composed = ("(This is a follow-up.)\n\nEarlier question: what is the "
                    "volume?\nAnswer: PLATE: 14.67 cm3\n\nNew follow-up: "
                    + NEEDS_AI)
        self.replies = [GOOD]
        out = self.run_ask(composed, plain_question=NEEDS_AI)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(path_label(out["answered"][0]), "Quick check")


class TheOldRouteStaysForOtherSetUps(_Base):

    def test_off_the_server_the_old_way_is_used(self):
        with mock.patch.object(CB.ai_client, "active", return_value=False), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value="old") as chat:
            out = self.run_ask("how many holes are there")
        chat.assert_called_once()
        self.assertEqual(out["done"], ["old"])

    def test_an_engine_without_the_module_uses_the_old_way(self):
        with mock.patch.object(CB, "get_step_cheap", return_value=None), \
                mock.patch.object(CB.openrouter, "openrouter_chat",
                                  return_value="old") as chat:
            out = self.run_ask(NEEDS_AI)
        chat.assert_called_once()
        self.assertEqual(out["done"], ["old"])


class _Dialog(_Base):
    """The StepDialog itself, offscreen, with the workers run in line."""

    def setUp(self):
        super().setUp()
        root = tempfile.mkdtemp(prefix="prism-test-step-")
        cfg = {"agents": {"visual": "ChatGPT", "brains": "Claude"},
               "openrouter_api_key": "sk-or-test", "step_out_dir": root}
        self.dlg = SD.StepDialog(cfg, [], None)
        self.dlg._vision_consent = False
        out_dir = os.path.join(root, "fx")
        os.makedirs(out_dir)
        self.m = {"path": self.path, "report": self.report, "out_dir": out_dir,
                  "drawn": {"png": "", "html": ""}, "xlsx": ""}
        self.dlg.paths = [self.path]
        self.dlg._current = self.m
        self.dlg.models = [self.m]
        self.dlg._queue = []

        def sync_start(worker):
            worker.run()
            _app.processEvents()
        for cls in (StepAskWorker, StepPlanWorker):
            p = mock.patch.object(cls, "start", sync_start)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(CB.config, "save_run")
        p.start()
        self.addCleanup(p.stop)

    def _ask(self, question, action="ask"):
        self.dlg.ask.set_text(question)
        self.dlg._action_buttons[action].setChecked(True)
        self.dlg._ask(self.m)

    def _who(self):
        return self.dlg._thread[-1][0]

    def _screen(self):
        """Every word on a widget of the dialog that is not hidden."""
        from PySide6.QtWidgets import QComboBox, QLabel
        _app.processEvents()
        words = [w.text() for w in self.dlg.findChildren(QLabel)
                 if w.isVisibleTo(self.dlg)]
        words += [w.currentText() for w in self.dlg.findChildren(QComboBox)
                  if w.isVisibleTo(self.dlg)]
        return "\n".join(words)


class InTheRealDialog(_Dialog):
    """The label under each answer, and the cap sentence where the customer
    reads it."""

    def test_ask_shows_each_path_in_words_and_never_a_model(self):
        cases = [("how many holes are there", [], "Measured from the file"),
                 (NEEDS_AI, [GOOD], "Quick check"),
                 (NEEDS_AI, [LIE, GOOD], "Full check")]
        for question, replies, label in cases:
            self.replies = list(replies)
            self._ask(question)
            self.assertEqual(self._who(), label)
            self.assertEqual(self.dlg._stage_agents_map[f"ask · {self.report['stem']}"], label)
            for word in MODEL_WORDS:
                self.assertNotIn(word, self._who().lower())

    def test_a_reached_cap_shows_the_sentence_in_the_window_not_an_answer(self):
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 0):
            self._ask(NEEDS_AI)
        shown = self.dlg.status.text()
        self.assertIn("today's limit of AI-assisted STEP files", shown)
        self.assertIn("tomorrow", shown)
        self.assertIn("still work and are free", shown)
        self.assertEqual(self.roles, [])
        self.assertEqual(self.dlg._responses, {})           # nothing saved as an answer
        from PySide6.QtWidgets import QLabel
        toast = [w.text() for w in self.dlg.canvas.findChildren(QLabel)
                 if "limit of AI-assisted" in w.text()]
        self.assertTrue(any("tomorrow" in t for t in toast), toast)

    def test_local_questions_still_work_at_the_cap_and_cost_nothing(self):
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 0):
            self._ask("how many holes are there")
        self.assertEqual(self.roles, [])
        self.assertEqual(self._who(), "Measured from the file")
        self.assertIn("4 hole(s)", self.dlg._thread[-1][1])

    def test_edit_plans_from_the_first_answer_with_one_call_and_names_the_path(self):
        self.replies = [GOOD]
        with mock.patch.object(self.dlg, "_on_planned",
                               wraps=self.dlg._on_planned) as planned:
            self._ask(NEEDS_AI, action="edit")
        self.assertEqual(self.roles, [SC.ROLE_FAST])        # answer + plan = one call
        planned.assert_called_once()
        self.assertEqual(planned.call_args.kwargs["agent"], "Quick check")
        self.assertEqual(self.dlg._current["plan"]["changes"][0]["new_dia_mm"], 6.0)

    def test_a_plain_edit_is_planned_with_no_ai_at_all(self):
        self._ask("enlarge H2 to 6 mm", action="edit")
        self.assertEqual(self.roles, [])
        self.assertEqual(self.dlg._current["plan"]["changes"][0]["hole"], "H2")

    def test_the_screen_shows_the_path_and_keeps_both_pickers(self):
        self.replies = [GOOD]
        self._ask(NEEDS_AI, action="edit")
        self.dlg._show_tab(1)
        self.assertIn("QUICK CHECK", self._screen())
        self.assertNotIn("HAIKU", "\n".join(
            w for w in self._screen().split("\n") if w.startswith("<span")))
        self.dlg._show_tab(2)
        plan = self._screen()
        self.assertIn("<b>Quick check</b>", plan)
        self.assertNotIn("Planned by", plan)
        for combo in (self.dlg.model_combo, self.dlg.composer.agent):
            self.assertFalse(combo.isHidden())
            self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                             ["Claude Haiku 5.5", "Claude Sonnet 5.5"])

    def test_a_change_agreed_in_a_follow_up_is_planned_without_another_call(self):
        self._ask("how many holes are there")
        key = f"ask · {self.report['stem']}"
        self.replies = [GOOD]
        self.dlg._on_answer_followup(self.dlg._inline, self.m, key, "", NEEDS_AI)
        self.dlg._inline.question = NEEDS_AI
        self.dlg._build_plan_for(self.m, key, None)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(self.dlg._current["plan"]["changes"][0]["new_dia_mm"], 6.0)

    def test_a_follow_up_is_judged_on_its_own_words_and_labelled(self):
        self._ask("how many holes are there")
        key = f"ask · {self.report['stem']}"
        popup = mock.MagicMock()
        self.replies = [GOOD]
        self.dlg._on_answer_followup(popup, self.m, key, "Claude Haiku 5.5",
                                     NEEDS_AI)
        self.assertEqual(self.roles, [SC.ROLE_FAST])
        self.assertEqual(popup.set_answer.call_args[0],
                         (GOOD["answer"], "Quick check"))

HAIKU, SONNET = "Claude Haiku 5.5", "Claude Sonnet 5.5"
PIC = {"kind": "image", "mime": "image/png", "b64": "x", "name": "s.png"}


class _WithDrawing(_Dialog):
    """The dialog with a drawing of the part, and nobody asked about it yet."""

    def setUp(self):
        super().setUp()
        png = os.path.join(self.m["out_dir"], "sheet.png")
        with open(png, "wb") as f:
            f.write(b"png")
        self.m["drawn"] = {"png": png, "html": ""}
        self.dlg._vision_consent = None
        p = mock.patch.object(SD.send_to_ai, "ask_consent", return_value=True)
        self.consent = p.start()
        self.addCleanup(p.stop)
        self.key = f"ask · {self.report['stem']}"

    def _pick(self, name):
        self.dlg.model_combo.setCurrentIndex(self.dlg.model_combo.findData(name))

    def _follow(self, text, agent=HAIKU):
        self.dlg._inline.question = text
        self.dlg._on_answer_followup(self.dlg._inline, self.m, self.key,
                                     agent, text)


class TheModelPickAndThePicture(_WithDrawing):

    def test_haiku_is_the_quick_pass_and_gets_the_picture(self):
        self.replies = [GOOD]
        self._ask(NEEDS_AI)
        self.consent.assert_called_once()
        call, = self.sent
        self.assertEqual((call["role"], call["model"]),
                         (SC.ROLE_FAST, SC.MODEL_FAST))
        self.assertEqual([a["kind"] for a in call["attachments"]], ["image"])
        self.assertEqual(self._who(), "Quick check")

    def test_haiku_escalates_once_to_sonnet_with_the_picture(self):
        self.replies = [LIE, GOOD]
        self._ask(NEEDS_AI)
        self.assertEqual([(c["role"], c["model"], len(c["attachments"]))
                          for c in self.sent],
                         [(SC.ROLE_FAST, SC.MODEL_FAST, 1),
                          (SC.ROLE_PICTURE, SC.MODEL_STRONG, 1)])
        self.assertEqual(self._who(), "Full check")

    def test_sonnet_goes_straight_to_sonnet(self):
        self._pick(SONNET)
        self.replies = [GOOD]
        self._ask(NEEDS_AI)
        self.assertEqual([(c["role"], c["model"]) for c in self.sent],
                         [(SC.ROLE_PICTURE, SC.MODEL_STRONG)])
        self.assertEqual(self._who(), "Full check")

    def test_saying_no_sends_the_numbers_only(self):
        self.consent.return_value = False
        self._pick(SONNET)
        self.replies = [GOOD]
        self._ask(NEEDS_AI)
        self.assertEqual([(c["role"], c["attachments"]) for c in self.sent],
                         [(SC.ROLE_ESCALATE, [])])

    def test_a_local_answer_is_free_and_asks_about_no_picture(self):
        for name in (HAIKU, SONNET):
            self._pick(name)
            self._ask("how many holes are there")
        self.assertEqual(self.roles, [])
        self.consent.assert_not_called()

    def test_the_cap_counts_the_sonnet_pick_too(self):
        self._pick(SONNET)
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 0):
            self._ask(NEEDS_AI)
        self.assertEqual(self.roles, [])
        self.assertIn("today's limit", self.dlg.status.text())

    def test_a_failed_call_leaves_the_allowance_alone(self):
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 1):
            self.replies = [RuntimeError("Prism AI did not answer")]
            self._ask(NEEDS_AI)
            self.assertIn("did not answer", self.dlg.status.text())
            self.assertEqual(SC._load_usage(""), {})
            self.replies = [GOOD]
            self._ask(NEEDS_AI)
        self.assertEqual(self._who(), "Quick check")
        self.assertNotEqual(SC._load_usage(""), {})


class FollowUpsCarryTheEarlierChat(_WithDrawing):

    ANSWER = {"answer": "H3 is the next one along.",
              "claims": [], "changes": [], "advice": []}

    def test_and_the_other_hole(self):
        self.replies = [GOOD, self.ANSWER]
        self._ask(NEEDS_AI)
        self._follow("and the other hole?")
        call = self.sent[-1]
        self.assertIn(GOOD["answer"], call["prompt"])
        self.assertIn("Customer: " + NEEDS_AI, call["prompt"])
        self.assertIn("The customer asks: and the other hole?", call["prompt"])
        self.assertEqual(len(call["attachments"]), 1)     # the picture again
        self.consent.assert_called_once()                 # asked once only

    def test_the_picture_reaches_a_follow_up_after_a_free_first_answer(self):
        self._ask("how many holes are there")
        self.consent.assert_not_called()
        self.replies = [self.ANSWER]
        self._follow("and the other hole?", SONNET)
        call, = self.sent
        self.assertEqual((call["role"], call["model"], len(call["attachments"])),
                         (SC.ROLE_PICTURE, SC.MODEL_STRONG, 1))
        self.assertIn("4 hole(s)", call["prompt"])

    def _long_chat(self):
        marker = {"answer": "The SLOTMARKER bracket stays as it is.",
                  "claims": [], "changes": [], "advice": []}
        filler = {"answer": "Nothing particular to report here. " * 25,
                  "claims": [], "changes": [], "advice": []}
        self.replies = [marker]
        self._ask("how could the bracket be easier to fit")
        for n in range(8):
            self.replies = [filler]
            self._follow(f"could anything else improve, round {'x' * (n + 1)}")

    def test_something_several_turns_back(self):
        self._long_chat()
        self.replies = [self.ANSWER]
        self._follow("could the wording be improved")
        self.assertNotIn("SLOTMARKER", self.sent[-1]["prompt"])   # trimmed
        self.replies = [self.ANSWER]
        self._follow("go back to what you said about the bracket")
        prompt = self.sent[-1]["prompt"]
        self.assertIn("SLOTMARKER", prompt)
        self.assertLess(len(prompt), len(self.sent[0]["prompt"])
                        + SC.HISTORY_CHARS + SC.HISTORY_OLDER_CHARS + 500)

    def test_a_conversation_reopened_from_history_keeps_its_past(self):
        self.replies = [GOOD]
        self._ask(NEEDS_AI)
        self.dlg._thread, self.dlg._followups = [], []   # as load_run leaves it
        for q in ("and the other hole?", "is that one the same"):
            self.replies = [self.ANSWER]
            self._follow(q)
            self.assertIn(GOOD["answer"], self.sent[-1]["prompt"])
        self.assertEqual(len(self.dlg._load_conversation(self.m)), 6)


class InTheAppsLanguage(_Dialog):

    def setUp(self):
        super().setUp()
        self.addCleanup(i18n.load, "en")

    def test_labels_and_limits_are_translated(self):
        for code in ("hi", "gu"):
            i18n.load(code)
            for english in ("Measured from the file", "Quick check",
                            "Full check", "Could not be verified",
                            SC.CAP_MESSAGE_DAY, SC.CAP_MESSAGE_MONTH,
                            SC.UNVERIFIED_MESSAGE):
                self.assertNotEqual(i18n.t(english), english, (code, english))

    def test_the_screen_shows_the_label_and_the_limit_in_hindi(self):
        i18n.load("hi")
        self._ask("enlarge H2 to 6 mm", action="edit")
        self.dlg._show_tab(1)
        self.assertIn(i18n.t("Measured from the file").upper(), self._screen())
        self.assertEqual(self._who(), "Measured from the file")   # stored as is
        with mock.patch.object(SC, "STEP_AI_FILES_PER_DAY", 0):
            self._ask(NEEDS_AI)
        self.assertIn(i18n.t(SC.CAP_MESSAGE_DAY), self.dlg.status.text())



if __name__ == "__main__":
    unittest.main()

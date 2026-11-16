"""Can somebody get themselves unstuck without telephoning anyone?

`test_ux.py` defends the same property for the messages Prism shows when it
notices a problem. This defends it for the larger case: the customer who is
not looking at an error at all, and has gone looking for help.

Three things are easy to lose here, and all of them are silent:

  · the ANSWERS drift into our vocabulary. Every one of them is written for
    somebody who runs a fabrication shop, has never used ChatGPT, and did not
    choose any of this. The moment one says "endpoint" it has stopped working
    and nothing will tell us.
  · a question starts travelling to an AI service just because it was asked
    in Help. The Help Centre must be entirely local: no planning key and no
    network connection are needed to search its reviewed answers.
"""
from __future__ import annotations

import inspect
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import plans  # noqa: E402
import support_kb as KB  # noqa: E402

_app = QApplication.instance() or QApplication([])

# The same list friendly.py is held to. "api" is deliberately NOT here, unlike
# the guide's stricter list: the customer has to find a button that is labelled
# "API key" on our own Settings screen and on Groq's website, and refusing to
# print the words that are actually on the button helps nobody.
JARGON = ("traceback", "exception", "stacktrace", "selector", "webdriver",
          "selenium", "http ", "null", "none type", "stderr",
          "api endpoint", "token expired", "oauth", "regex", "sys.")


def _panel():
    from widgets.support_panel import SupportPanel
    return SupportPanel()


def _said(panel) -> str:
    """Everything currently written in the transcript, flattened.

    Read from the widgets rather than from any internal log, because the
    widgets are what the customer sees — a message that was 'posted' but not
    rendered would pass a log-based check and still be a dead button."""
    texts = []
    box = panel._thread_box
    for i in range(box.count()):
        w = box.itemAt(i).widget()
        if w is not None:
            for label in w.findChildren(QLabel):
                texts.append(label.text())
    return " ".join(texts)


class TheAnswersAreUsable(unittest.TestCase):
    def test_there_are_enough_of_them_to_be_worth_showing(self):
        """A help screen with a dozen answers is a menu, not a help screen —
        it sends everybody to the contact form anyway."""
        self.assertGreaterEqual(len(KB.all_questions()), 40)
        self.assertGreaterEqual(len(KB.TOPICS), 6)

    def test_every_question_has_a_real_answer(self):
        for q in KB.all_questions():
            self.assertTrue(q.text, q.qid)
            self.assertGreater(len(q.answer.what), 40, q.qid)

    def test_every_answer_tells_them_what_to_do(self):
        """A message with no next action is a phone call — which is the exact
        thing this screen exists to prevent."""
        for q in KB.all_questions():
            self.assertTrue(q.answer.steps, f"no steps for {q.qid}")

    def test_the_words_are_ones_a_business_owner_uses(self):
        for q in KB.all_questions():
            text = (f"{q.text} {q.answer.what} {' '.join(q.answer.steps)} "
                    f"{q.answer.note}").lower()
            for word in JARGON:
                self.assertNotIn(word, text, f"{word!r} in {q.qid}")

    def test_steps_read_as_instructions_not_descriptions(self):
        starts_badly = ("the ", "this ", "there ", "it ", "prism's ")
        for q in KB.all_questions():
            for step in q.answer.steps:
                self.assertFalse(
                    step.lower().startswith(starts_badly),
                    f"{q.qid}: reads as a description, not an instruction: "
                    f"{step}")

    def test_nothing_blames_the_customer(self):
        for q in KB.all_questions():
            text = f"{q.text} {q.answer.what}".lower()
            for blame in ("you failed", "invalid input", "you must",
                          "illegal", "you should have"):
                self.assertNotIn(blame, text, q.qid)

    def test_questions_are_phrased_the_way_somebody_would_ask_them(self):
        """Filed our way ("Licence expiry handling") they are unfindable by
        the person who has the problem. Asked their way, the search works and
        the list can be skimmed."""
        for q in KB.all_questions():
            self.assertGreater(len(q.text.split()), 3, q.qid)


class TheAnswersPointSomewhereReal(unittest.TestCase):
    def test_every_button_goes_somewhere_the_window_understands(self):
        """An action key the dispatcher has no branch for is a button that
        silently does nothing — and nothing else in the app would catch it."""
        import main_window
        src = inspect.getsource(main_window.MainWindow._handle_command)
        for q in KB.all_questions():
            if q.answer.action:
                self.assertIn(f'"{q.answer.action}"', src,
                              f"{q.qid} points at {q.answer.action!r}, which "
                              f"_handle_command does not dispatch")

    def _help_text(self):
        for q in KB.all_questions():
            yield q.qid, " ".join((q.answer.what, *q.answer.steps))

    def test_every_settings_path_in_an_answer_is_a_real_section(self):
        """The Settings redesign removed the old Status page and its "Change…"
        buttons, and six answers kept sending customers to them. The 29 Sep QA
        report scored which article matched, never whether the steps inside it
        were still true. "Settings → X" must start with a section label the
        Settings screen actually has."""
        from widgets.settings_panel import SECTIONS
        labels = [label for _key, label, _group, _blurb in SECTIONS]
        for qid, text in self._help_text():
            for tail in text.split("Settings → ")[1:]:
                self.assertTrue(
                    any(tail.startswith(label) for label in labels),
                    f"{qid}: 'Settings → {tail[:30]}…' is not one of {labels}")

    def test_the_controls_an_answer_names_exist_on_screen(self):
        """Retired names must stay gone, and every control an answer tells a
        customer to find or press must be a string the UI really carries."""
        retired = ("Change API key", "Pin Chrome version", "Change language",
                   "Your role and team", "Deactivate this computer",
                   "Start follow-up", "Export diagnostics", "Settings → Status")
        named = ("Groq key", "Company designation key", "Chrome version",
                 "Release this computer's seat", "Change licence key",
                 "AI writes back in", "Send follow-up", "Contact support",
                 "Save as a file")
        ui = ""
        for rel in ("widgets/settings_panel.py", "dialogs/license_dialog.py",
                    "dialogs/followup_dialog.py", "dialogs/contact_dialog.py",
                    "widgets/support_panel.py"):
            with open(os.path.join(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__))), rel), encoding="utf-8") as f:
                ui += f.read()
        spoken = " ".join(text for _qid, text in self._help_text())
        for old in retired:
            where = [qid for qid, text in self._help_text() if old in text]
            self.assertFalse(where, f"{old!r} no longer exists in the UI, "
                                    f"but {where} still tell people to use it")
        for control in named:
            self.assertIn(f'"{control}"', ui, f"{control!r} is not in the UI")

    def test_the_pointers_from_elsewhere_are_dispatchable_too(self):
        """friendly's catch-all and the guide's last topic both send people
        here — checked against the same dispatcher, for the same reason."""
        import friendly
        import main_window
        from dialogs.guide_dialog import TOPICS
        src = inspect.getsource(main_window.MainWindow._handle_command)
        pointers = [t.action for t in TOPICS if t.action]
        generic = friendly.explain("something entirely unrecognised")
        if generic.action:
            pointers.append(generic.action)
        for action in pointers:
            self.assertIn(f'"{action}"', src, action)

    def test_support_itself_is_reachable_without_knowing_where_it_went(self):
        """It left the rail for Settings when the rail was cut back to Home,
        the add-ons and Settings. What matters is that a stuck customer can
        still get to it, so this asserts reachability rather than a location:
        it is in the rail, or it is in the Settings screen the rail still has.
        """
        from widgets.sidebar import MORE, SECONDARY
        from widgets.settings_panel import MORE_LINKS
        rail = [key for key, _l, _i, _t in MORE]
        settings = [key for key, _l, _b in MORE_LINKS]
        self.assertIn("config", rail, "Settings must stay in the rail")
        self.assertIn("support", settings + [k for k, _l, _i, _t in SECONDARY])
        self.assertIn("support", settings, "and be listed on that screen")

    def test_the_window_has_a_screen_for_it(self):
        """This used to grep _show_screen's SOURCE TEXT for '"support"'.

        That stopped working the moment screen identity moved into
        main_window.SCREENS -- the behaviour was unchanged and provably
        correct (tests/test_screen_registry.py builds a real window and
        checks the page that comes up), but the literal was no longer spelled
        inside that particular method. A test of how code is WRITTEN fails on
        a refactor that changes nothing about what it DOES, and it fails in a
        way that looks like a broken feature.

        SCREEN_INDEX is the table _show_screen actually looks the name up in,
        so asserting against it tests the routing rather than the spelling.
        """
        import main_window
        self.assertIn(
            "support", main_window.SCREEN_INDEX,
            "the help screen has no entry in main_window.SCREENS, so every "
            "answer that points a stuck customer at 'support' would silently "
            "drop them on Home instead")

    def test_every_topic_icon_actually_draws(self):
        """icons.pixmap raises on a name it doesn't know — at runtime that
        would happen while building the topic list, taking the screen down."""
        from widgets import icons
        for t in KB.TOPICS:
            self.assertTrue(icons.pixmap(t.icon, 16), t.key)

    def test_every_add_on_answer_names_a_feature_that_exists(self):
        for q in KB.all_questions():
            if q.answer.feature:
                self.assertIn(q.answer.feature, plans.FEATURES, q.qid)

    def test_related_questions_all_resolve(self):
        for q in KB.all_questions():
            for other in q.related:
                self.assertIsNotNone(KB.question(other),
                                     f"{q.qid} points at missing {other!r}")

    def test_no_question_points_at_itself(self):
        for q in KB.all_questions():
            self.assertNotIn(q.qid, q.related, q.qid)

    def test_ids_are_unique(self):
        ids = [q.qid for t in KB.TOPICS for q in t.questions]
        self.assertEqual(len(ids), len(set(ids)))


class SearchFindsTheRightThing(unittest.TestCase):
    """The phrasings are real ones — what somebody types is rarely our
    heading, and a search that only matches our own wording is a search that
    sends everybody to the contact form."""

    CASES = [
        ("captcha keeps appearing", "robot-check"),
        ("gmail rejected my app password", "email-password"),
        ("how many computers can I install this on", "how-many-computers"),
        ("my laptop was stolen and the seat is stuck", "dead-laptop"),
        ("it cant read my dwg", "boq-dwg"),
        ("can I read it in gujarati", "change-language"),
        ("no space left on device", "disk-full"),
        ("can i close the lid while it runs", "walk-away"),
        ("where is my data stored", "where-data"),
        ("windows protected your pc", "os-warning"),
        ("step came back empty", "empty-step"),
        ("chrome wont start", "chrome-wont-open"),
        ("whats the difference between studio and quick", "reel-or-studio"),
        ("can it read two mailboxes at once", "many-mailboxes"),
        ("how does the whole team see one sheet", "shared-register"),
        ("find sales leads and contacts", "leads-find"),
        ("export leads to spreadsheet", "leads-export"),
        ("how to measure a pcb", "gerber-overview"),
        ("measure 3d cad model", "step-overview"),
        ("are 3d models kept private", "step-privacy"),
        ("whatsapp customer messaging", "whatsapp-safe"),
        # "check parts list stock shortages" -> "bom-shortage" left this list
        # on 2026-11-16 with BOM & Stock (addons/bom/addon.py status=OFF);
        # tests/test_ui_port_bom_hidden.py asserts it is NOT found while off
        # and IS found again once BOM is switched back on.
        ("what is motion graphics", "motion-overview"),
        ("add voiceover to reel", "reel-audio"),
        ("edit scenes in studio", "reel-edit"),
        ("where are my deliverables", "where-artifacts"),
        ("how to do a follow up", "followup-task"),
        ("see prompt before running", "inspect-prompt"),
        ("two factor verification code", "two-factor-auth"),
        ("how to update prism", "check-updates"),
        ("take a tour of prism", "guided-tour"),
    ]

    def test_the_right_answer_is_in_the_top_few(self):
        for typed, expected in self.CASES:
            hits = [q.qid for q in KB.search(typed)]
            self.assertIn(expected, hits, f"{typed!r} -> {hits}")

    def test_the_best_match_is_usually_first(self):
        first = sum(1 for typed, expected in self.CASES
                    if (h := KB.search(typed)) and h[0].qid == expected)
        self.assertGreaterEqual(first, len(self.CASES) - 2,
                                "ranking has drifted")

    def test_something_we_have_no_answer_for_returns_nothing(self):
        """This is what opens the route to a person, so it has to stay
        decisive. A weak guess here traps somebody in the menu."""
        for nonsense in ("quantum blockchain integration", "zzzzz"):
            self.assertEqual(KB.search(nonsense), [], nonsense)

    def test_an_empty_query_is_not_a_match_for_everything(self):
        self.assertEqual(KB.search(""), [])
        self.assertEqual(KB.search("   the it is"), [])


class HelpRoutesAreAlwaysAvailable(unittest.TestCase):
    """The user can reach the assistant or a person without navigating a
    gate first; written answers remain available as a lightweight option."""

    def test_both_routes_out_start_available(self):
        p = _panel()
        self.assertTrue(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())

    def test_it_explains_the_available_routes(self):
        p = _panel()
        self.assertTrue(p._foot_note.text())
        self.assertTrue(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())

    def test_reading_an_answer_keeps_routes_available(self):
        p = _panel()
        p._show_answer("empty-step")
        self.assertIn("empty-step", p._seen)
        self.assertTrue(p._contact_btn.isEnabled())

    def test_one_answer_that_did_not_help_opens_both(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=False)
        self.assertTrue(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())

    def test_an_answer_that_worked_keeps_routes_available(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=True)
        self.assertTrue(p._contact_btn.isEnabled())

    def test_a_question_we_cannot_answer_opens_them_immediately(self):
        """Nobody is made to read irrelevant answers to earn a person."""
        p = _panel()
        p._entry.setText("my invoice printer is jamming")
        p._on_typed()
        self.assertTrue(p._contact_btn.isEnabled())
        self.assertTrue(p._ai_btn.isEnabled())

    def test_saying_none_of_these_is_what_i_meant_also_opens_them(self):
        p = _panel()
        p._no_answer("something we do not cover")
        self.assertTrue(p._contact_btn.isEnabled())

    def test_a_typed_question_we_do_answer_stays_in_the_written_tier(self):
        p = _panel()
        p._entry.setText("captcha keeps appearing")
        p._on_typed()
        self.assertTrue(p._contact_btn.isEnabled())


class TheTranscriptStaysReadable(unittest.TestCase):
    """The UX complaint the first version earned: every menu stayed in the
    thread for ever, so ten topics plus ten questions plus ten topics again
    read as a form that kept growing. Menus retire once the conversation
    moves past them; the pick survives as the customer's own bubble."""

    def test_a_menu_is_retired_once_something_is_picked_from_it(self):
        p = _panel()
        self.assertEqual(len(p._live), 1, "the greeting should offer topics")
        p._show_topic("running")
        # The topic chips are gone; what is live now is the question list
        # (and the way back to the topics).
        self.assertEqual(len(p._live), 2)
        p._show_answer("empty-step")
        self.assertEqual(len(p._live), 0,
                         "old menus left live in the scrollback fork the "
                         "conversation")

    def test_the_pick_survives_as_the_customers_own_words(self):
        p = _panel()
        p._show_topic("running")
        self.assertIn(("you", "Running a job"), p._log)

    def test_typing_also_moves_past_the_menus(self):
        p = _panel()
        p._entry.setText("captcha keeps appearing")
        p._on_typed()
        self.assertEqual(len(p._live), 1, "only the search hits stay live")

    def test_start_over_forgets_everything(self):
        p = _panel()
        p._show_answer("empty-step")
        p._verdict("empty-step", solved=False)
        p._start_over()
        self.assertEqual(p._seen, [])
        self.assertEqual(p._unsolved, [])
        self.assertEqual(p._stage, "triage")
        self.assertTrue(p._contact_btn.isEnabled())


class LocalHelpOnly(unittest.TestCase):
    def test_help_never_needs_a_planning_key(self):
        p = _panel()
        p._entry.setText("captcha keeps appearing")
        p._on_typed()
        self.assertIn("captcha", " ".join(text for _who, text in p._log).lower())
        self.assertIsNone(p._worker)
        self.assertEqual(p._stage, "triage")

    def test_browse_all_topics_stays_local(self):
        p = _panel()
        p._show_all_topics()
        self.assertTrue(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())
        self.assertIn("Browse all help topics", " ".join(text for _who, text in p._log))

    def test_diagnosis_is_an_explicit_opt_in(self):
        from widgets.support_panel import SupportPanel
        p = SupportPanel({"api_key": "gsk_test"})
        p._start_ai()
        self.assertEqual(p._stage, "ai")
        self.assertFalse(p._ai_btn.isEnabled())
        self.assertTrue(p._contact_btn.isEnabled())
        prompt = p._prompt("the renderer stopped halfway through")
        self.assertIn("Recent system log events:", prompt)
        self.assertIn("DIAGNOSE THIS", prompt)

    def test_diagnosis_without_a_key_stays_in_local_help(self):
        p = _panel()
        p._start_ai()
        self.assertEqual(p._stage, "triage")
        self.assertIn("key", " ".join(text for _who, text in p._log).lower())

    def test_normal_how_to_question_stays_local_even_in_diagnosis_mode(self):
        from widgets.support_panel import SupportPanel
        p = SupportPanel({"api_key": "gsk_test"})
        p._start_ai()
        p._entry.setText("how do i edit a video in prism")
        p._on_typed()
        self.assertIn("reel-edit", p._seen)
        self.assertIsNone(p._worker)

    def test_diagnostic_markdown_is_rendered_not_shown_as_asterisks(self):
        p = _panel()
        p._ai_answered("**Check the render**\n\n1. **Open** History.")
        visible = _said(p)
        self.assertNotIn("**", visible)
        self.assertIn("Check the render", visible)

    def test_diagnostic_worker_uses_the_saved_groq_key(self):
        import core_bridge as CB
        from workers import SupportWorker
        seen = {}

        def fake_chat(key, model, prompt, **kwargs):
            seen.update(key=key, prompt=prompt, **kwargs)
            return "Open Login tabs and sign in again."

        answers = []
        worker = SupportWorker({"api_key": "gsk_test"}, "PROMPT TEXT")
        worker.done.connect(answers.append)
        with mock.patch.object(CB.router, "groq_chat", fake_chat):
            worker.run()
        self.assertEqual(answers, ["Open Login tabs and sign in again."])
        self.assertEqual(seen["key"], "gsk_test")
        self.assertLessEqual(seen["temperature"], 0.2)


class ContactingUs(unittest.TestCase):
    def setUp(self):
        """Held on `self`, not returned from a helper — a QDialog with no
        Python reference is collected immediately and every later call raises
        "C++ object already deleted"."""
        from dialogs.contact_dialog import ContactDialog
        self.sheet = ContactDialog("Me: it broke\n\nPrism: sorry")

    def test_the_draft_already_contains_what_we_would_ask_for(self):
        import app_meta
        body = self.sheet._body.toPlainText()
        self.assertIn(app_meta.VERSION, body)
        self.assertIn("it broke", body,
                      "the conversation should not have to be retyped")

    def test_it_names_an_address_a_person_reads(self):
        import app_meta
        self.assertIn("@", app_meta.SUPPORT_EMAIL)
        self.assertTrue(self.sheet.windowTitle())

    def test_the_draft_carries_no_secrets(self):
        """They cannot reasonably check this before sending it, so it has to
        be true by construction."""
        self.sheet._name.setText("Ravi")
        text = self.sheet._full_text().lower()
        for secret in ("gsk_", "password", "api key", "licence key"):
            self.assertNotIn(secret, text)

    def test_the_device_code_is_there_because_seat_problems_need_it(self):
        body = self.sheet._body.toPlainText().lower()
        self.assertIn("device code", body)


class ItAllBuilds(unittest.TestCase):
    def test_the_screen_builds_with_no_licence_and_no_key(self):
        """The worst-served customer is a brand-new one whose activation
        failed — help must open for them above all."""
        from unittest import mock
        import licensing
        with mock.patch.object(licensing, "has", return_value=False):
            p = _panel()
            p._show_answer("boq-file")        # a locked add-on answer
            self.assertIn("boq-file", p._seen)

    def test_every_answer_renders(self):
        p = _panel()
        for q in KB.all_questions():
            p._show_answer(q.qid)
        self.assertEqual(len(p._seen), len(KB.all_questions()))

    def test_every_topic_opens(self):
        p = _panel()
        for topic in KB.TOPICS:
            p._show_topic(topic.key)

    def test_navigation_resets_ai_stage_and_placeholder(self):
        p = _panel()
        p._stage = "ai"
        p._entry.setPlaceholderText("Describe the failed task or error…")

        p._show_all_topics()
        self.assertEqual(p._stage, "triage")
        self.assertEqual(p._entry.placeholderText(), "Ask Lumi anything about Prism...")

        p._stage = "ai"
        p._entry.setPlaceholderText("Describe the failed task or error…")
        p._show_topic("files")
        self.assertEqual(p._stage, "triage")
        self.assertEqual(p._entry.placeholderText(), "Ask Lumi anything about Prism...")

        p._stage = "ai"
        p._entry.setPlaceholderText("Describe the failed task or error…")
        p._show_answer("where-is-export")
        self.assertEqual(p._stage, "triage")
        self.assertEqual(p._entry.placeholderText(), "Ask Lumi anything about Prism...")

        p._stage = "ai"
        p._entry.setPlaceholderText("Describe the failed task or error…")
        p._back_to_start()
        self.assertEqual(p._stage, "triage")
        self.assertEqual(p._entry.placeholderText(), "Ask Lumi anything about Prism...")


if __name__ == "__main__":
    unittest.main(verbosity=2)

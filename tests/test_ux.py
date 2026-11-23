"""Does a first-time user get told what to do?

The product goal these defend: a business owner who has never used AI should
be able to resolve an ordinary problem without telephoning anyone. That means
two properties, and both are easy to lose by accident:

  · every failure they can meet is TRANSLATED — no HTTP codes, no exception
    class names, no "selector", "driver" or "token" on screen;
  · every message carries a NEXT ACTION. A message with no action is a phone
    call, so an entry with no steps is a bug in the copy.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import friendly  # noqa: E402
import plans  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Real error text, as the customer's machine would produce it.
REAL_ERRORS = [
    ("run", "Message: session not created: This version of ChromeDriver only "
            "supports Chrome version 131"),
    ("run", "selenium.common.exceptions.WebDriverException: unknown error"),
    ("plan", "Groq API error (HTTP 429): {'error': {'code': "
             "'rate_limit_exceeded'}}"),
    ("plan", "Groq rejected your API key. Re-enter it in Setup."),
    ("plan", "Couldn't reach Groq — check your internet connection."),
    ("run", "Couldn't reach the licence server at https://x.onrender.com"),
    ("run", "You're not signed in to this tool."),
    ("run", "This tool is showing a human-verification check."),
    ("email", "(535, b'5.7.8 Username and Password not accepted')"),
    ("attach", "[Errno 13] Permission denied: '/Users/x/spec.pdf'"),
    ("attach", "[Errno 28] No space left on device"),
    ("attach", "FileNotFoundError: /Users/x/gone.png"),
    ("boq", "ModuleNotFoundError: No module named 'ezdxf'"),
    ("reel", "FFmpeg is not installed"),
    ("voice", "Microphone unavailable: PortAudio not found"),
    ("run", "The agent returned nothing."),
    ("leads", "Apollo returned no rows."),
    ("licence", "Your licence has ended."),
    ("run", "KeyError: 'unexpected'"),
    ("run", ""),
    ("inquiry", "Prism needs either your rate list or your cost sheet "
                "before it can price anything. Add one under Setup → Files."),
    ("send", "[Errno -3] Temporary failure in name resolution"),
    ("send", "The mail server didn't answer on port 587. This usually means "
             "a network is blocking outbound mail — some ISPs and office "
             "firewalls block it entirely. Try port 465 instead in Setup, "
             "or send from a different network (e.g. a phone hotspot) to "
             "check whether it's the network rather than the account."),
]

# Words a business owner should never be shown. Checked against the friendly
# text only — the technical detail is folded away in the dialog on purpose.
JARGON = ("traceback", "exception", "stacktrace", "selector", "webdriver",
          "selenium", "http ", "json", "null", "none type", "stderr",
          "api endpoint", "token expired", "oauth", "regex", "sys.")


class EveryErrorIsAnswerable(unittest.TestCase):
    def test_each_one_gets_a_title_and_an_explanation(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            self.assertTrue(problem.title, error)
            self.assertTrue(problem.what, error)

    def test_each_one_tells_them_what_to_do(self):
        """A message with no next action is a phone call."""
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            self.assertTrue(problem.steps,
                            f"no steps for {context}: {error[:60]}")

    def test_the_words_are_ones_a_business_owner_uses(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            text = f"{problem.title} {problem.what} {' '.join(problem.steps)}"
            for word in JARGON:
                self.assertNotIn(word, text.lower(),
                                 f"{word!r} shown for {context}: {error[:50]}")

    def test_steps_read_as_instructions_not_descriptions(self):
        """Every step should start with a verb — 'Open…', 'Check…', 'Wait…' —
        rather than describing the system's state."""
        starts_badly = ("the ", "this ", "there ", "it ", "prism's ")
        for context, error in REAL_ERRORS:
            for step in friendly.explain(error, context).steps:
                self.assertFalse(
                    step.lower().startswith(starts_badly),
                    f"step reads as a description, not an instruction: {step}")

    def test_the_common_ones_offer_a_button_that_fixes_it(self):
        """Telling somebody to open Settings is worse than taking them."""
        for error, expected in (
                ("session not created: chrome version", "settings:chrome"),
                ("Groq rejected your api key", "settings:key"),
                ("You're not signed in to this tool", "login")):
            self.assertEqual(friendly.explain(error).action, expected, error)

    def test_an_unknown_error_still_helps(self):
        problem = friendly.explain("ZeroDivisionError: division by zero")
        self.assertTrue(problem.steps)
        self.assertTrue(problem.ask_support,
                        "when we don't know, the honest step is 'send it to us'")

    def test_the_no_rate_list_message_keeps_its_own_words_not_the_generic_one(self):
        """addons/inquiry/dialog.py's quotation flow already writes an
        actionable sentence for this; it must not be thrown away for
        "Something went wrong" just because no rule recognised it."""
        problem = friendly.explain(
            "Prism needs either your rate list or your cost sheet before it "
            "can price anything. Add one under Setup → Files.")
        self.assertNotEqual(problem.title, "Something went wrong")
        self.assertFalse(problem.ask_support)

    def test_support_is_offered_only_when_it_is_the_real_next_step(self):
        """Offering it every time trains people to send a file instead of
        reading the fix."""
        self.assertFalse(friendly.explain("rate limit exceeded").ask_support)
        self.assertFalse(friendly.explain("not signed in").ask_support)
        self.assertTrue(friendly.explain("something bizarre").ask_support)

    def test_nothing_blames_the_user(self):
        for context, error in REAL_ERRORS:
            problem = friendly.explain(error, context)
            text = f"{problem.title} {problem.what}".lower()
            for blame in ("you failed", "invalid input", "you must",
                          "illegal", "you should have"):
                self.assertNotIn(blame, text)


class ProblemDialogBuilds(unittest.TestCase):
    def test_it_builds_for_every_real_error(self):
        from dialogs.problem_dialog import ProblemDialog
        for context, error in REAL_ERRORS:
            dialog = ProblemDialog(friendly.explain(error, context),
                                   detail=str(error))
            self.assertTrue(dialog.windowTitle())

    def test_the_technical_detail_starts_hidden(self):
        from dialogs.problem_dialog import ProblemDialog
        dialog = ProblemDialog(friendly.explain("session not created"),
                               detail="WebDriverException: chrome 131")
        self.assertFalse(dialog._detail_label.isVisible())

    def test_pressing_the_fix_button_reports_the_action(self):
        from dialogs.problem_dialog import ProblemDialog
        dialog = ProblemDialog(friendly.explain("not signed in"))
        dialog._take_action()
        self.assertEqual(dialog.chosen_action, "login")


class Guide(unittest.TestCase):
    def test_every_topic_has_a_title_and_body(self):
        from dialogs.guide_dialog import TOPICS
        for topic in TOPICS:
            self.assertTrue(topic.title)
            self.assertGreater(len(topic.body), 40, topic.title)

    def test_the_guide_avoids_jargon_too(self):
        from dialogs.guide_dialog import TOPICS
        banned = ("prompt engineering", "llm", "api", "pipeline stage",
                  "selector", "agent registry", "oauth")
        for topic in TOPICS:
            text = f"{topic.title} {topic.body}".lower()
            for word in banned:
                self.assertNotIn(word, text, f"{word!r} in {topic.title}")

    def test_every_add_on_topic_names_the_feature_that_unlocks_it(self):
        from dialogs.guide_dialog import TOPICS
        for topic in TOPICS:
            if topic.feature:
                self.assertIn(topic.feature, plans.FEATURES, topic.title)

    def test_locked_topics_are_still_listed(self):
        """The guide is the only place a customer can discover what else
        Prism does — a list with holes teaches them nothing."""
        from dialogs.guide_dialog import TOPICS
        self.assertTrue([t for t in TOPICS if t.feature])

    def test_it_builds_and_shows_locked_items_greyed(self):
        from unittest import mock
        import licensing
        from dialogs.guide_dialog import GuideDialog
        core_only = type("S", (), {
            "usable": True, "status": "valid", "features": frozenset(["core"]),
            "message": "", "customer": "X", "plan": "p", "kind": "paid",
            "seats": 1, "license_ends": 0, "days_left": 9, "license_id": "l",
            "grace_days": 0, "has": lambda s, f: f == "core"})()
        with mock.patch.object(licensing, "state", return_value=core_only):
            GuideDialog()          # builds without raising


class Plans(unittest.TestCase):
    def test_the_two_plans_exist_and_are_distinct(self):
        self.assertEqual(set(plans.ORDER), {"studio", "complete"})
        sets = [set(plans.PLANS[k].includes) for k in plans.ORDER]
        self.assertEqual(len(sets), len({frozenset(s) for s in sets}))

    def test_every_plan_includes_the_pipeline(self):
        """A licence that cannot run a task is not a product."""
        for key in plans.ORDER:
            self.assertIn("core", plans.PLANS[key].includes, key)

    def test_studio_is_the_pipeline_plus_reel_and_nothing_else(self):
        """Prism Studio is the base product: core + Reel & Studio. Every
        other capability is an add-on sold on top of it."""
        self.assertEqual(set(plans.PLANS["studio"].includes), {"core", "reel"})

    def test_every_add_on_is_sold_on_top_of_studio(self):
        self.assertEqual(set(plans.PLANS["studio"].addons),
                         {"boq", "email", "inbox", "leads", "gerber", "step",
                          "marketing"})

    def test_every_add_on_is_something_the_app_actually_gates_on(self):
        """A key nothing gates on unlocks nothing — a licence carrying it is a
        sale of nothing. marketing/attendance/dev/bom were exactly that."""
        from addons import registry
        gated = {a.feature for a in registry.REGISTRY if a.feature}
        # A build without an add-on has not got its manifest, so the licence
        # feature it carries is gated by nothing there by design (the licence
        # keys are frozen and still sold). Which add-on carries which feature:
        carrier = {"reel": "reel", "boq": "boq", "gerber": "gerber",
                   "step": "step", "email": "email", "leads": "leads",
                   "inbox": "inquiry", "marketing": "whatsapp"}
        for key in plans.FEATURES:
            if key == "core":
                continue
            self.assertIn(key, carrier, "%s: say which add-on carries it" % key)
            if registry.is_absent(carrier[key]):
                self.assertNotIn(key, gated, key)
            else:
                self.assertIn(key, gated, key)

    def test_complete_really_is_everything(self):
        self.assertEqual(set(plans.PLANS["complete"].includes),
                         set(plans.FEATURES))

    def test_a_plan_and_its_addons_never_overlap(self):
        """Selling somebody something they already have is the worst kind of
        pricing bug."""
        for key in plans.ORDER:
            plan = plans.PLANS[key]
            self.assertFalse(set(plan.includes) & set(plan.addons), key)

    def test_a_plan_plus_its_addons_covers_the_catalogue(self):
        for key in plans.ORDER:
            plan = plans.PLANS[key]
            self.assertEqual(set(plan.includes) | set(plan.addons),
                             set(plans.FEATURES), key)

    def test_every_feature_can_be_sold(self):
        """A feature no plan includes is one nobody can ever buy."""
        sellable = set()
        for key in plans.ORDER:
            sellable |= set(plans.PLANS[key].includes)
        self.assertEqual(sellable, set(plans.FEATURES))

    def test_every_feature_has_words_to_sell_it_with(self):
        for key, feature in plans.FEATURES.items():
            self.assertTrue(feature.label, key)
            self.assertTrue(feature.blurb, key)
            self.assertTrue(plans.pitch(key), key)

    def test_a_broken_licence_still_leaves_a_working_pipeline(self):
        self.assertEqual(plans.features_for("nonsense"), plans.FALLBACK)
        self.assertIn("core", plans.FALLBACK)

    def test_a_bespoke_set_is_reported_as_custom_not_as_a_plan(self):
        self.assertEqual(plans.plan_of({"core", "boq"}), "Custom")
        self.assertEqual(plans.plan_of(plans.features_for("complete")),
                         "Prism Complete")

    def test_the_paywall_can_pitch_every_feature(self):
        from dialogs.paywall import PITCH
        for key in plans.FEATURES:
            self.assertIn(key, PITCH, f"no paywall copy for {key}")
            _name, _icon, text = PITCH[key]
            self.assertTrue(text, key)


class BoqIsLocked(unittest.TestCase):
    """The specific gate that was asked about."""

    def test_boq_is_not_in_the_services_plan(self):
        self.assertNotIn("boq", plans.PLANS["studio"].includes)
        self.assertIn("boq", plans.PLANS["studio"].addons)

    def test_a_core_only_licence_cannot_reach_boq(self):
        from unittest import mock
        import licensing
        core_only = type("S", (), {
            "usable": True, "status": "valid", "features": frozenset(["core"]),
            "message": "", "has": lambda s, f: f == "core"})()
        with mock.patch.object(licensing, "state", return_value=core_only):
            self.assertFalse(licensing.has("boq"))
            self.assertTrue(licensing.has("core"))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AClosedBrowserWindow(unittest.TestCase):
    """The error a customer actually pasted in, with its stack trace.

    Two things were wrong with how Prism met it: the advice was confidently
    incorrect, and the run kept going against a dead session.
    """

    REAL = ("Message: no such window: target window already closed\n"
            "from unknown error: web view not found\n"
            "  (Session info: chrome=151.0.7922.138)\n"
            "Stacktrace:\n"
            "0   undetected_chromedriver  0x0000000102928e84 "
            "undetected_chromedriver + 3427972\n"
            "1   undetected_chromedriver  0x000000010262833c "
            "undetected_chromedriver + 279356")

    def test_it_is_not_diagnosed_as_a_chrome_version_problem(self):
        """Every frame of the stack trace says "undetected_chromedriver",
        which matched the version-mismatch rule — so a closed tab sent the
        customer off to update a browser that was working perfectly. A
        confident wrong answer is worse than the generic one it replaced."""
        import friendly
        p = friendly.explain(self.REAL, "run")
        self.assertNotIn("update", " ".join(p.steps).lower())
        self.assertIn("closed", p.title.lower())

    def test_it_says_the_finished_work_was_kept(self):
        """This arrives mid-run, so the first question is always "did I lose
        everything?"."""
        import friendly
        p = friendly.explain(self.REAL, "run")
        self.assertIn("history", " ".join(p.steps).lower())

    def test_it_does_not_ask_them_to_email_support(self):
        """There is nothing for us to diagnose: they closed a window."""
        import friendly
        self.assertFalse(friendly.explain(self.REAL, "run").ask_support)

    def test_the_engine_knows_the_session_is_dead(self):
        import core_bridge  # noqa: F401  (puts core on sys.path)
        from core import automation as AU
        for wording in ("no such window: target window already closed",
                        "invalid session id",
                        "session deleted because of page crash",
                        "chrome not reachable",
                        "disconnected: not connected to DevTools"):
            self.assertTrue(AU._browser_is_gone(wording), wording)

    def test_blank_native_chromedriver_error_is_recoverable(self):
        """ChromeDriver sometimes returns only Message plus stack addresses."""
        import core_bridge  # noqa: F401  (puts core on sys.path)
        from core import automation as AU
        native = RuntimeError(
            "Message:\nStacktrace:\n#0 0x581cc40b99fa <unknown>\n"
            "#1 0x74d170e9cb84 <unknown>")
        try:
            raise native
        except RuntimeError as cause:
            try:
                raise RuntimeError("ChatGPT: waiting for the message box") from cause
            except RuntimeError as wrapped:
                self.assertTrue(AU._blank_native_webdriver_error(wrapped))
                self.assertTrue(AU._browser_is_gone(wrapped))

    def test_an_ordinary_stage_failure_is_not_mistaken_for_it(self):
        """Stopping the whole run on a normal error would throw away every
        stage after it for no reason."""
        import core_bridge  # noqa: F401  (puts core on sys.path)
        from core import automation as AU
        for wording in ("timed out waiting for the response",
                        "element not interactable",
                        "no response scraped"):
            self.assertFalse(AU._browser_is_gone(wording), wording)

    def test_the_run_stops_instead_of_failing_every_remaining_stage(self):
        """Each later stage would open the same dead session, wait for its own
        timeout and report the same error — so a run broken at step two
        reported five identical failures over several minutes."""
        import ast
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "prism_terminal", "core", "automation.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        called = {n.func.id for n in ast.walk(run)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_browser_is_gone", called)


class WhenTheDesignWillNotParse(unittest.TestCase):
    """"No JSON found in the agent's reply" is unanswerable on its own: the
    customer can see JSON on the ChatGPT page and Prism cannot, and there is
    no way to tell which of them is looking at the truth."""

    def test_the_reply_that_failed_is_kept(self):
        import core_bridge  # noqa: F401
        from core import automation as AU
        path = AU._keep_failed_spec(["this is not json", "neither is this"])
        self.assertTrue(path and os.path.exists(path))
        body = open(path, encoding="utf-8").read()
        self.assertIn("this is not json", body)
        self.assertIn("neither is this", body)
        os.remove(path)

    def test_saving_it_can_never_break_the_run(self):
        """A bad design is already a bad day. A full disk must not turn it
        into a crash on top."""
        import core_bridge  # noqa: F401
        from core import automation as AU
        # A source that cannot be written still returns a string, never raises.
        try:
            AU._keep_failed_spec([None])
        except Exception as e:
            self.fail(f"raised {e}")

    def test_a_linkified_stylesheet_is_repaired(self):
        """Chat UIs turn URLs into links. A stylesheet URL runs straight into
        the CSS after it, so the anchor swallows half the stylesheet — and the
        design then renders with no fonts even when the JSON parses fine."""
        import core_bridge  # noqa: F401
        from core import reel_web as RW
        broken = ("@import url('[https://fonts.googleapis.com/css2?family=DM"
                  "&display=swap');*{margin:0}h1{font-family:'DM]"
                  "(https://fonts.googleapis.com/css2?family=DM%29;*)"
                  " Sans',sans-serif}")
        fixed = RW._unlink_markdown(broken)
        self.assertNotIn("](", fixed)
        self.assertIn("@import url('https://fonts.googleapis.com", fixed)
        self.assertIn("font-family:'DM Sans',sans-serif", fixed)

    def test_ordinary_css_is_untouched(self):
        """CSS is full of brackets and parentheses — attribute selectors,
        url(), rgba(). A looser pattern would eat them."""
        import core_bridge  # noqa: F401
        from core import reel_web as RW
        for css in ("a[href]{color:red}",
                    ".x{background:url(asset:art1)}",
                    ".y{color:rgba(0,0,0,.5)}",
                    "@import url('https://fonts.googleapis.com/css2?x=1');"):
            self.assertEqual(RW._unlink_markdown(css), css, css)


class AReelWithNoPictures(unittest.TestCase):
    """Image generation fails for ordinary reasons — a quota, a content
    refusal, a render that never finished. None of them should cost the
    customer the whole reel."""

    def setUp(self):
        import core_bridge  # noqa: F401
        from core import assets as A
        self.A = A

    def test_the_design_stage_is_told_there_are_none(self):
        """This was the bug. An empty asset list left the prompt simply not
        mentioning pictures, so a model asked for a premium product reel
        assumed the usual ones existed and wrote src='asset:art1'."""
        said = self.A.manifest({})
        self.assertTrue(said.strip(), "an empty manifest says nothing at all")
        self.assertIn("THERE ARE NO IMAGES", said)

    def test_it_forbids_referencing_assets(self):
        said = self.A.manifest({})
        self.assertIn("Do NOT reference asset:", said)

    def test_it_forbids_leaving_gaps_for_them(self):
        """Half the failure: a layout designed around pictures that never
        arrive reads as broken rather than as spare."""
        self.assertIn("Nothing is coming", self.A.manifest({}))

    def test_it_says_what_to_do_instead(self):
        """A prohibition on its own produces a timid design. It has to be
        told that type-led IS the design."""
        said = self.A.manifest({}).lower()
        for tool in ("typography", "negative space", "colour", "css"):
            self.assertIn(tool, said, tool)

    def test_it_frames_this_as_a_real_design_not_a_degraded_one(self):
        self.assertIn("legitimate", self.A.manifest({}))

    def test_a_real_asset_list_is_unchanged(self):
        table = {"logo": {"kind": "logo", "w": 512, "h": 512,
                          "alpha": True, "made": False}}
        said = self.A.manifest(table)
        self.assertIn("asset:logo — 512x512", said)
        self.assertNotIn("THERE ARE NO IMAGES", said)

    def test_the_renderer_still_strips_anything_that_slips_through(self):
        """Belt and braces. The instruction is a prompt, and prompts are
        advice — an unresolved src must never reach the finished video."""
        from core import reel_web as RW
        html = ("<div><img src='asset:art1' alt=''>"
                "<span style='background:url(asset:art2)'>hi</span></div>")
        out = RW._drop_missing(html)
        self.assertNotIn("asset:", out)
        self.assertIn("hi", out)


class TheLogoSlotIsForALogo(unittest.TestCase):
    """Whatever is called `asset:logo` gets placed where a logo belongs — the
    design stage is told so in as many words, "the endcard at least". So the
    slot has to be empty rather than wrong.

    Found while preparing a reel for PCB manufacturers out of screenshots of
    Prism itself: artwork attached, none of it a mark. The imagery stage was
    correctly told "NO logo — make three SUBJECT images", made three, and the
    first of them was named `logo` anyway and landed on the endcard.
    """

    def setUp(self):
        import core_bridge  # noqa: F401
        from core import assets as A
        self.A = A

    def _table(self, prepared):
        """collect()'s slot logic, run against records rather than files —
        the naming is the behaviour under test, not PIL."""
        rest = list(prepared)
        marks = [a for a in rest
                 if not a["made"] and a["alpha"] and a["ink"] < 0.55]
        logo = min(marks, key=lambda a: a["ink"]) if marks else None
        if logo is None and not any(not a["made"] for a in rest):
            made = [a for a in rest if a["made"]]
            logo = made[0] if made else None
        return logo

    def rec(self, made, alpha=False, ink=1.0, tag=""):
        return {"made": made, "alpha": alpha, "ink": ink, "tag": tag}

    def test_generated_art_alongside_the_clients_own_files_is_not_a_logo(self):
        """The imagery stage was told not to make a mark, so there isn't one
        to find — and a product shot on the endcard is worse than none."""
        got = self._table([self.rec(False, tag="screenshot"),
                           self.rec(True, tag="board"),
                           self.rec(True, tag="drill")])
        self.assertIsNone(got)

    def test_with_nothing_attached_the_first_generated_image_is_the_mark(self):
        """The other half. Told nothing exists, the imagery stage IS asked for
        a wordmark first, and the page is harvested in order."""
        got = self._table([self.rec(True, tag="wordmark"),
                           self.rec(True, tag="subject")])
        self.assertEqual(got["tag"], "wordmark")

    def test_the_clients_own_mark_still_wins_outright(self):
        got = self._table([self.rec(False, alpha=True, ink=0.12, tag="theirs"),
                           self.rec(True, tag="generated")])
        self.assertEqual(got["tag"], "theirs")

    def test_screenshots_come_through_as_plain_artwork(self):
        """End to end on the real files, because the records above are only
        as good as collect() agreeing with them."""
        import os
        base = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "..")
        shots = [os.path.join(base, n) for n in ("img_1.png", "img_2.png")]
        if not all(os.path.exists(p) for p in shots):
            self.skipTest("the reference screenshots are not on this machine")
        table = self.A.collect(shots)
        self.assertNotIn("logo", table)
        self.assertEqual(sorted(table), ["art1", "art2"])


class TheChatWindowMangledTheDesign(unittest.TestCase):
    """Diagnosed from a real saved failure. The model wrote valid JSON; the
    page it was rendered on broke it in two different ways."""

    def setUp(self):
        import core_bridge  # noqa: F401
        from core import reel, reel_web
        self.reel, self.web = reel, reel_web

    def test_a_wrapped_url_no_longer_kills_the_design(self):
        """The fatal one. A very long @import URL was soft-wrapped by the chat
        window, and the scrape turned that visual wrap into a real newline
        inside a JSON string — an unescaped control character, so the whole
        design was thrown away over a line break that only existed on screen.
        """
        import json
        broken = ('{"design":{"css":"@import url(\'https://fonts.googleapis.com'
                  '/css2?family=DM+Sans&display=swap\n\');*{margin:0}"},'
                  '"scenes":[{"type":"a","seconds":3,"html":"<p>x</p>"}]}')
        with self.assertRaises(Exception):
            json.loads(broken)
        spec = self.web.parse_spec(broken)
        self.assertEqual(len(spec["scenes"]), 1)
        self.assertIn("@import url(", spec["design"]["css"])

    def test_ordinary_pretty_printed_json_is_untouched(self):
        """Newlines BETWEEN members are perfectly legal and must survive —
        only the ones trapped inside a string value get escaped."""
        pretty = '{\n  "a": 1,\n  "b": "two"\n}'
        self.assertEqual(self.reel._escape_control_chars(pretty), pretty)

    def test_an_escaped_newline_is_not_double_escaped(self):
        already = '{"css":"a\\nb"}'
        self.assertEqual(self.reel._escape_control_chars(already), already)

    def test_tabs_and_returns_are_handled_too(self):
        out = self.reel._escape_control_chars('{"x":"a\tb\rc"}')
        self.assertNotIn("\t", out)
        self.assertNotIn("\r", out)
        self.assertIn("\\t", out)

    def test_the_design_prompt_now_demands_a_code_fence(self):
        """The second corruption, and the cause was our own instruction. Asked
        for BARE json, the reply renders as prose — and prose is markdown, so
        every asterisk in the CSS is eaten as an emphasis marker. The saved
        failure had zero asterisks in 17KB.

        Inside a fence markdown processes nothing. The parser has always
        skipped fences, so forbidding them bought nothing and cost designs.
        """
        for text in (self.web.script_instructions(),
                     self.web.design_instructions()
                     if hasattr(self.web, "design_instructions") else ""):
            if not text:
                continue
            self.assertIn("fenced code block", text)
            self.assertNotIn("no fences", text)



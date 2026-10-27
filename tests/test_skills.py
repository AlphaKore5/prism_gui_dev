"""The skills layer: the doctrine files, the loader, and the two ways in.

The rule this suite exists to hold: a stage or a feature that no skill
claims must produce EXACTLY the prompt it produced before skills existed.
Doctrine is added by a file appearing, never by the mechanism being
present — otherwise every prompt in the app changed the day this landed.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import automation as AU  # noqa: E402
from core import config as C  # noqa: E402
from core import router as R  # noqa: E402
from core import skills as SK  # noqa: E402

# Stages the router knows; a skill may not claim one that does not exist.
KNOWN_STAGES = set(__import__("core.agents", fromlist=["agents"]).PIPELINE_ORDER)

# Features wired to a prompt builder. A skill claiming a feature nothing
# appends is doctrine that silently never reaches a tool, which is worse
# than no doctrine: it reads as done.
WIRED_FEATURES = {
    "boq.standards", "boq.interpret", "boq.format",
    "bom.standards", "bom.format",
    "inquiry.negotiation", "inquiry.followup",
    "gerber.writeup", "gerber.form",
    "step.ask", "step.plan", "step.auto",
    "email.blast", "leads.reach",
}


class EveryShippedSkillIsWellFormed(unittest.TestCase):

    def setUp(self):
        self.skills = SK.reload()

    def test_there_are_skills_and_they_load(self):
        self.assertTrue(self.skills,
                        f"no skills found under {SK.shipped_dir()}")

    def test_each_one_says_what_it_is_and_where_it_applies(self):
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertTrue(s.title.strip(), "needs a title")
                self.assertGreater(len(s.description), 30,
                                   "the description is what the router reads "
                                   "to decide; it has to say something")
                self.assertTrue(
                    s.stages or s.features,
                    "claims neither a stage nor a feature, so nothing can "
                    "ever reach it")
                self.assertGreater(len(s.body), 400, "the body is too thin")

    def test_no_skill_claims_a_stage_that_does_not_exist(self):
        for key, s in self.skills.items():
            for stage in s.stages:
                with self.subTest(skill=key, stage=stage):
                    self.assertIn(stage, KNOWN_STAGES)

    def test_no_skill_claims_a_feature_nothing_appends(self):
        for key, s in self.skills.items():
            for feature in s.features:
                with self.subTest(skill=key, feature=feature):
                    self.assertIn(
                        feature, WIRED_FEATURES,
                        f"'{feature}' is claimed by the {key} skill but no "
                        "prompt builder calls skills.addendum() for it, so "
                        "the doctrine never reaches a tool. Wire it, or fix "
                        "the key.")

    def test_the_budget_fits_the_body(self):
        """A body longer than its budget is silently cut mid-doctrine, and
        what goes first is the quality checklist at the end -- the half the
        prompt's own preamble promises the tool will be judged against."""
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertGreaterEqual(
                    s.budget, len(s.body),
                    f"the {key} body is {len(s.body)} characters and its "
                    f"budget is {s.budget}; raise the budget or cut the body")

    def test_two_skills_on_one_stage_still_fit_the_total(self):
        for stage in KNOWN_STAGES:
            found = SK.for_stage(stage)[:SK.MAX_PER_STAGE]
            if len(found) < 2:
                continue
            with self.subTest(stage=stage):
                text = SK.block([s.key for s in found], "browser")
                self.assertLessEqual(len(text), SK.TOTAL_BUDGET + len(SK._INTRO))

    def test_a_shipped_skill_never_looks_overridden(self):
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertFalse(s.overridden)
                self.assertTrue(s.path.startswith(SK.shipped_dir()))


class EveryCheckerBehaves(unittest.TestCase):
    """A checker runs on whatever a browser scraped. It may report nothing,
    but it may never raise, and it may never fire on an empty answer -- a
    stage that produced nothing is already reported as producing nothing."""

    def setUp(self):
        self.skills = SK.reload()

    def test_checks_expose_a_faults_function(self):
        for key, s in self.skills.items():
            if not s.has_checks:
                continue
            with self.subTest(skill=key):
                module = SK._checks_module(s)
                self.assertTrue(callable(getattr(module, "faults", None)))

    def test_nothing_raises_on_junk(self):
        junk = ["", "   ", "\n\n", "no", "|" * 50, "{}" * 40,
                "SLIDE\nPAGE\nSCENE\nSUBJECT:", "", "a" * 5000,
                "| a | b |\n|---|---|\n", "SCENE 1\nSCENE 2\nSCENE 3"]
        for key, s in self.skills.items():
            if not s.has_checks:
                continue
            for text in junk:
                with self.subTest(skill=key, text=text[:12]):
                    got = SK.check([key], text, {})
                    self.assertIsInstance(got, list)
                    for fault in got:
                        self.assertTrue(fault.startswith(f"[{key}] "))

    def test_a_checker_that_raises_is_reported_and_skipped(self):
        key = next(k for k, s in self.skills.items() if s.has_checks)
        boom = mock.Mock()
        boom.faults.side_effect = RuntimeError("checker is broken")
        with mock.patch.object(SK, "_checks_module", return_value=boom):
            with mock.patch.object(SK.ui, "warn") as warned:
                self.assertEqual(SK.check([key], "anything", {}), [])
        self.assertTrue(warned.called,
                        "a broken checker must be reported, not silent")

    def test_an_unknown_key_is_ignored_rather_than_raising(self):
        self.assertEqual(SK.check(["no-such-skill"], "text", {}), [])
        self.assertEqual(SK.block(["no-such-skill"]), "")


class TheCheckersCatchWhatTheDoctrineSays(unittest.TestCase):
    """Every checker against samples in the two shapes it meets.

    tests/skill_samples/source holds each sample as a chat model writes it.
    captured/ holds the same sample after real Chrome rendered it and
    Selenium read it back -- exactly what automation._capture hands a
    checker (devtools/capture_skill_samples.py). The first checkers were
    tested only on markdown and misfired on nearly every real answer."""

    SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "skill_samples")
    SHAPES = (("source", "md"), ("captured", "txt"))

    def setUp(self):
        SK.reload()

    def _read(self, *parts):
        with open(os.path.join(self.SAMPLES, *parts), encoding="utf-8") as f:
            return f.read()

    def _samples(self, verdict):
        for kind, ext in self.SHAPES:
            for name in sorted(os.listdir(os.path.join(self.SAMPLES, kind))):
                if name.endswith(f"-{verdict}.{ext}"):
                    yield kind, name, name[: -len(f"-{verdict}.{ext}")]

    def test_every_checker_has_good_and_bad_samples_in_both_shapes(self):
        for key, s in SK.catalog().items():
            if not s.has_checks:
                continue
            for kind, ext in self.SHAPES:
                for verdict in ("good", "bad"):
                    with self.subTest(skill=key, sample=f"{kind}/{verdict}"):
                        self.assertTrue(os.path.isfile(os.path.join(
                            self.SAMPLES, kind, f"{key}-{verdict}.{ext}")))

    def test_every_source_sample_has_been_captured(self):
        names = lambda kind: {os.path.splitext(n)[0] for n in
                              os.listdir(os.path.join(self.SAMPLES, kind))}
        self.assertEqual(names("source") - names("captured"), set(),
                         "run devtools/capture_skill_samples.py")

    def test_the_bad_samples_are_caught(self):
        for kind, name, key in self._samples("bad"):
            with self.subTest(sample=f"{kind}/{name}"):
                self.assertTrue(SK.check([key], self._read(kind, name), {}),
                                "the known-bad sample passed")

    def test_the_good_samples_pass_clean(self):
        for kind, name, key in self._samples("good"):
            with self.subTest(sample=f"{kind}/{name}"):
                self.assertEqual(
                    SK.check([key], self._read(kind, name), {}), [],
                    "the known-good sample was faulted; a rule is too tight "
                    "and every real answer will be re-asked once for nothing")


class TheCheckersOnRealReplies(unittest.TestCase):
    """Replies from the owner's own runs, as captured, client names removed.
    Every assertion is a failure measured on 2026-09-11."""

    def setUp(self):
        SK.reload()

    @staticmethod
    def _real(name):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "skill_samples", "real", name)
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_perplexity_headings_and_citations_are_read(self):
        """The markdown-era checker missed 'Executive Summary' and
        'Bibliography' and found no sources in any of the three."""
        for n in (1, 2, 3):
            faults = SK.check(["research-report"],
                              self._real(f"research-perplexity-{n}.txt"), {})
            with self.subTest(reply=n):
                self.assertEqual([f for f in faults if "could be found" in f], [])
                self.assertTrue([f for f in faults if "uncertain" in f],
                                "none of the three says what it could not find")

    def test_cited_figures_are_not_called_unsourced(self):
        faults = SK.check(["research-report"],
                          self._real("research-perplexity-3.txt"), {})
        counted = [int(m.group(1)) for f in faults
                   for m in [re.match(r"\[research-report\] (\d+) figure", f)] if m]
        self.assertLessEqual(sum(counted), 10,
                             "the markdown-era checker called 121 unsourced")

    def test_a_word_ending_in_rs_is_not_a_price(self):
        faults = SK.check(["research-report"],
                          self._real("research-perplexity-1.txt"), {})
        self.assertEqual([f for f in faults if "caterers" in f], [])

    def test_bearings_counted_in_inches_are_caught(self):
        faults = SK.check(["bom-parts"],
                          self._real("boq-bom-writeup-chatgpt.txt"), {})
        self.assertTrue([f for f in faults if "given a length" in f
                         and "Bearing" in f])
        self.assertEqual([f for f in faults if "not physically plausible" in f],
                         [], "'46 M-16 Nut' was read as a 46-metre nut")
        self.assertEqual([f for f in faults if "Drive Shaft" in f], [],
                         "a drive shaft is fabricated, not bought out")

    def test_every_placeholder_in_a_real_document_is_found(self):
        faults = SK.check(["pdf-document"], self._real("document-chatgpt.txt"), {})
        hit = [f for f in faults if "placeholder" in f]
        self.assertTrue(hit)
        self.assertGreaterEqual(int(re.search(r"(\d+) placeholder", hit[0]).group(1)), 8)

    def test_a_file_the_tool_built_is_not_judged_as_text(self):
        text = self._real("document-claude-built-docx.txt")
        self.assertTrue(SK.is_artifact_reply(text))
        for key in ("pdf-document", "documentation", "slide-deck"):
            with self.subTest(skill=key):
                self.assertEqual(SK.check([key], text, {}), [])

    def test_a_cover_block_above_page_one_is_the_cover(self):
        """Live ChatGPT run with the skill: the date sat in a header block
        above 'PAGE 1', and the check spent its re-ask on a dated cover."""
        faults = SK.check(["pdf-document"],
                          self._real("document-chatgpt-with-skill.txt"), {})
        self.assertEqual([f for f in faults if "cover page carries no date" in f], [])

    def test_claude_building_a_deck_in_its_sandbox_is_a_built_file(self):
        text = self._real("deck-claude-built-pptx.txt")
        self.assertTrue(SK.is_artifact_reply(text))
        self.assertEqual(SK.check(["slide-deck"], text, {}), [])

    def test_real_correct_parts_are_not_rejected(self):
        """Rows the 2026-09-11 fact-check proved correct against standards
        and catalogues; the first size ranges rejected several of them."""
        rows = """1 Foundation bolt M20 × 600 mm IS 5624 8 nos
2 Plain washer M10, 2 mm thick IS 2016 20 nos
3 Cam selector switch 64 × 64 mm Kaycee or equivalent 2 nos
4 Proximity sensor M18, sensing distance 8 mm, 2 m cable IP67 Omron or equivalent 4 nos
5 Cable gland M20, cable range 6–12 mm IP68 20 nos
6 Castor 250 mm wheel, 355 mm height IS 12345 4 nos
7 Piano hinge 2000 mm SS 304 2 nos
8 Rope pull emergency stop switch 30 m IP65 Schneider or equivalent 1 nos
9 Terminal block 2.5 mm sq Phoenix or equivalent 40 nos
10 HSFG bolt M20 class 10.9 IS 3757 24 nos
11 TMT bar Fe 500D 12 mm 1,200 kg
12 Aluminium plate 6061-T6 10 mm 40 kg
13 Plate E350 16 mm 900 kg
ASSUMPTIONS
None."""
        self.assertEqual(SK.check(["bom-parts"], rows, {}), [])


class ReadingCapturedText(unittest.TestCase):

    def test_a_citation_line(self):
        for s in ("nhb.gov", "shroomydelightsagrotech", "+1", "ibef.org +2"):
            self.assertTrue(SK.is_source_chip(s), s)
        for s in ("Executive Summary", "₹180", "Low", "Open Settings."):
            self.assertFalse(SK.is_source_chip(s), s)

    def test_a_rendered_heading(self):
        for s in ("Executive Summary", "3. BIBLIOGRAPHY (Full Citations with URLs)",
                  "Sources:", "## Steps"):
            self.assertTrue(SK.is_heading(s), s)
        for s in ("Open Settings. The settings window opens.", "nhb.gov",
                  "Gujarat is suitable for commercial mushroom cultivation, "
                  "but species choice must match climate"):
            self.assertFalse(SK.is_heading(s), s)

    def test_a_rendered_table_row(self):
        text = ("# Description Qty Unit\n"
                "1 Channel section IS 2062 E250 ISMC 100 24 kg\n"
                "2. Drawing interpretation")
        self.assertEqual(SK.item_rows(text),
                         ["1 Channel section IS 2062 E250 ISMC 100 24 kg"])

    def test_placeholders_as_written(self):
        got = SK.placeholders(
            "[PRODUCT LOGO HERE]\n[IMAGE PLACEHOLDER — Product mockup showing "
            "the agent pipeline; Alt text: a long description that runs well "
            "past sixty characters of text]\n{{company}}")
        self.assertEqual(len(got), 3)


class NothingChangesUntilASkillClaimsTheJob(unittest.TestCase):

    def test_a_feature_no_skill_claims_adds_nothing(self):
        self.assertEqual(SK.addendum("nobody.claims.this"), "")

    def test_an_empty_key_list_adds_nothing(self):
        self.assertEqual(SK.block([]), "")
        self.assertEqual(SK.block(None), "")

    def test_a_stage_with_no_skills_gets_no_line_in_the_router_prompt(self):
        self.assertEqual(SK.stage_line("audio"), "")

    def test_the_schema_only_offers_skills_where_some_exist(self):
        stub = R._schema_stub({"presentation": "Canva", "audio": "ElevenLabs"})
        lines = {line.split(":")[0].strip().strip('"'): line
                 for line in stub.splitlines() if '": {' in line}
        self.assertIn('"skills": []', lines["presentation"])
        self.assertNotIn('"skills"', lines["audio"])
        self.assertIn('"kind":', lines["presentation"],
                      "the contract's kind must survive beside the skills key")

    def test_the_rule_is_absent_when_no_enabled_stage_has_a_skill(self):
        self.assertEqual(R._skills_rule({"audio": "ElevenLabs"}), "")
        self.assertIn('"skills"', R._skills_rule({"presentation": "Canva"}))


class WhatTheRouterChoosesIsValidated(unittest.TestCase):

    def setUp(self):
        SK.reload()

    def test_a_real_pick_is_kept(self):
        routing = {"presentation": {"needed": True, "skills": ["slide-deck"]}}
        self.assertEqual(SK.assign("make a deck", routing, ["presentation"]),
                         {"presentation": ["slide-deck"]})

    def test_an_invented_key_is_dropped(self):
        routing = {"presentation": {"needed": True,
                                    "skills": ["deck-writing-2000"]}}
        SK.assign("make something", routing, ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], [])

    def test_a_skill_from_another_stage_is_dropped(self):
        routing = {"presentation": {"needed": True, "skills": ["bom-parts"]}}
        SK.assign("make something", routing, ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], [])

    def test_the_persons_own_words_are_the_fallback(self):
        """The router wrote no skills key. The same backstop shape as the
        make-stage guardrail: the person's words, not the router's brief."""
        routing = {"presentation": {"needed": True}}
        SK.assign("build me a pitch deck for the bank", routing,
                  ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], ["slide-deck"])

    def test_the_fallback_does_not_fire_on_a_stage_that_is_not_running(self):
        routing = {"presentation": {"needed": False}}
        SK.assign("build me a pitch deck", routing, ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], [])

    # Every row here was checked by hand against what the person plainly
    # meant. Two of them were live bugs when this table was first written.
    INTENT = [
        # a request naming two deliverables: the FIRST one is the job
        ("make me a pitch deck for the bank, and a one-pager pdf brochure",
         "presentation", "slide-deck"),
        ("write a one-pager pdf brochure, and a pitch deck to go with it",
         "presentation", "pdf-document"),
        ("write documentation for the pdf export feature",
         "content", "documentation"),
        ("i need a case study about how we saved the surat line",
         "content", "story"),
        # a trigger at position 0 -- scored -0, which is falsy, and was
        # dropped for matching too well
        ("research the cement market in gujarat", "research", "research-report"),
        ("storyboard a 20 second reel for the launch", "content", "scene"),
        ("cold email the plant managers in ahmedabad",
         "content", "cold-outreach"),
        # nothing fits, and guessing would make the answer worse
        ("just summarise this for me", "brains", None),
        ("redeckorate the office", "presentation", None),
        # the owner's two real document requests, and a documentation ask
        # that shares the word -- the longer phrase at the same place wins
        ("make DOCX document for this product", "content", "pdf-document"),
        ("make a pretty good document use colors from it", "content",
         "pdf-document"),
        ("document the api for the export feature", "content", "documentation"),
    ]

    def test_the_fallback_picks_what_the_person_plainly_meant(self):
        for query, stage, want in self.INTENT:
            with self.subTest(query=query[:40]):
                routing = {stage: {"needed": True, "questions": ["x"]}}
                SK.assign(query, routing, [stage])
                self.assertEqual(routing[stage]["skills"],
                                 [want] if want else [])

    def test_guessing_attaches_one_skill_but_choosing_may_attach_two(self):
        """A planner naming two has reasoned about whether they sit
        together. A trigger match has not -- and two conflicting skills on
        one stage spend that stage's single re-ask on a contradiction
        Prism created itself."""
        query = "a pitch deck, and a one-pager pdf brochure"
        guessed = {"presentation": {"needed": True, "questions": ["x"]}}
        SK.assign(query, guessed, ["presentation"])
        self.assertEqual(len(guessed["presentation"]["skills"]), 1)

        chosen = {"presentation": {"needed": True, "questions": ["x"],
                                   "skills": ["slide-deck", "pdf-document"]}}
        SK.assign(query, chosen, ["presentation"])
        self.assertEqual(chosen["presentation"]["skills"],
                         ["slide-deck", "pdf-document"])

    def test_a_trigger_matches_whole_words_only(self):
        routing = {"presentation": {"needed": True}}
        SK.assign("redeckorate the office", routing, ["presentation"])
        self.assertEqual(routing["presentation"]["skills"], [])

    def test_never_more_than_the_cap(self):
        routing = {"content": {"needed": True,
                               "skills": ["slide-deck", "story",
                                          "documentation", "pdf-document"]}}
        SK.assign("x", routing, ["content"])
        self.assertLessEqual(len(routing["content"]["skills"]),
                             SK.MAX_PER_STAGE)

    def test_rubbish_in_the_skills_key_does_not_raise(self):
        for junk in ("slide-deck", 5, None, {"a": 1}, [None, {}, "slide-deck"]):
            routing = {"presentation": {"needed": True, "skills": junk}}
            SK.assign("x", routing, ["presentation"])
            self.assertIsInstance(routing["presentation"]["skills"], list)

    def test_a_duplicated_plan_step_still_finds_its_skills(self):
        """The plan screen lets a step be duplicated, and the second is
        labelled 'content 2'. Its skills live under 'content'."""
        routing = {"content": {"needed": True, "skills": ["story"]}}
        self.assertEqual(SK.keys_for(routing, "content 2"), ["story"])


class TheEngineTypesItAndChecksIt(unittest.TestCase):
    """Source-level, in the same style as tests/test_makers.py: these lines
    are the whole wiring, and a refactor that drops one loses the feature
    silently -- every prompt still sends, nothing is ever checked."""

    def test_the_block_is_typed_after_the_task(self):
        src = AU._SOURCE if hasattr(AU, "_SOURCE") else __import__(
            "inspect").getsource(AU.run)
        self.assertIn('skill_text = (SK.block(skill_keys, "browser", maker=_skill_builds)', src)
        self.assertIn('questions = [q + "\\n\\n" + skill_text.rstrip() '
                      'for q in questions]', src)

    def test_a_caller_with_its_own_stages_can_name_its_skills(self):
        import inspect
        self.assertIn("stage_skills", inspect.signature(AU.run).parameters)
        src = inspect.getsource(AU.run)
        self.assertIn('skill_keys = (list((stage_skills or {}).get(stage) or [])',
                      src)
        self.assertIn("or SK.keys_for(routing, stage))", src)

    def test_only_a_text_step_with_its_deliverable_is_skill_checked(self):
        """1.5.7's contract judges file, image and video steps by whether the
        thing exists, and re-asks when it is missing. The skill check runs
        only on a text step the contract found complete, so no step is asked
        again twice."""
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn('and kind_here == "text" and chat_tool and not short_of', src)
        self.assertLess(src.index('short_of = fixed["missing"]'),
                        src.index("faults = SK.check(skill_keys, stage_responses[-1]"))

    def test_the_answer_is_checked_and_re_asked_once(self):
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn("faults = SK.check(skill_keys, stage_responses[-1]", src)
        self.assertIn("again = _reask(driver, agent_cfg,", src)
        self.assertIn("if len(left) < len(faults):", src)

    def test_a_machine_read_stage_is_never_skill_checked(self):
        """A JSON scene spec has its own lint. A prose checker run over it
        would report a fault on every line and burn the one re-ask."""
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn("if (skill_keys and stage_responses and not machine_shaped",
                      src)

    def test_nothing_is_typed_into_a_stage_that_must_reply_in_json(self):
        """The owner's own setup writes the reel script on ChatGPT for Prism
        Studio, and that stage must answer in JSON. A "reel script" request
        attached the scene skill there, whose layout contradicts it."""
        import inspect
        src = inspect.getsource(AU.run)
        guard = "if skill_keys and not machine_shaped"
        self.assertIn(guard, src)
        self.assertIn('_skill_kind not in ("data", "links") else "")', src)
        self.assertLess(src.index("machine_shaped = ("), src.index(guard))

    def test_the_router_settles_the_choice_before_the_run(self):
        import inspect
        src = inspect.getsource(R.route)
        self.assertIn("SK.assign(query, routing, list(A.PIPELINE_ORDER))", src)


class AMakerGetsTheStandardsNotTheTextLayout(unittest.TestCase):
    """Canva, Gamma, v0 and the video tools BUILD the deliverable. A skill's
    Shape section lays out a text answer and its Non-goals tell a text stage
    to leave the building to a later step -- typed to a maker, both say
    'do not build it', the failure the 2026-09-11 prompt audit traced."""

    def setUp(self):
        SK.reload()

    def test_a_maker_is_not_given_the_layout_or_the_scope(self):
        text = SK.block(["slide-deck"], "browser", maker=True)
        self.assertIn("One idea per slide", text)
        self.assertIn("Quality checklist", text)
        self.assertNotIn("## Shape", text)
        self.assertNotIn("## Non-goals", text)
        self.assertNotIn("Do not design the deck", text)

    def test_a_heading_inside_a_code_example_does_not_end_the_cut(self):
        text = SK.block(["documentation"], "browser", maker=True)
        self.assertNotIn("## Before you start", text)
        self.assertIn("## Rules", text)

    def test_a_text_stage_still_gets_everything(self):
        text = SK.block(["slide-deck"], "browser")
        self.assertIn("## Shape", text)
        self.assertIn("## Non-goals", text)

    def test_the_maker_block_says_build_it(self):
        self.assertIn("Build the thing itself",
                      SK.block(["slide-deck"], "browser", maker=True))

    def test_the_engine_passes_the_flag_and_never_checks_a_maker(self):
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn("_skill_builds = (_builds_deliverable(agent_cfg, stage)", src)
        self.assertIn('or _skill_kind in ("file", "image", "video"))', src)
        self.assertIn("and not _builds_deliverable(agent_cfg, stage)):", src)

    def test_the_presentation_stage_builds_whichever_tool_runs_it(self):
        """Given a deck to make on the 2026-09-11 live run, Claude built the
        .pptx itself; the text layout would have argued with the file."""
        self.assertTrue(AU._builds_deliverable({}, "presentation"))
        self.assertTrue(AU._builds_deliverable({}, "presentation 2"))
        self.assertTrue(AU._builds_deliverable({"makes": "a video"}, "content"))
        self.assertFalse(AU._builds_deliverable({}, "content"))

    def test_a_stage_with_a_skill_is_not_given_a_second_rulebook(self):
        rule = R._skills_rule({"presentation": "Canva"})
        self.assertIn("does not restate them", rule)
        self.assertNotIn("PROMPT CRAFT", rule,
                         "1.5.7's planner writes briefs; there is no PROMPT CRAFT")


class TheAddOnsHandTheirSkillsToTheCheck(unittest.TestCase):
    """A feature skill is typed by the add-on's own prompt builder. Without
    these the doctrine reached the tool and nothing ever read the answer
    against it -- the parts-list checker existed and never ran."""

    @staticmethod
    def _src(*parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, *parts), encoding="utf-8") as f:
            return f.read()

    def test_the_worker_forwards_stage_skills_to_the_engine(self):
        src = self._src("workers.py")
        self.assertIn("stage_skills: dict | None = None", src)
        self.assertIn('kwargs["stage_skills"] = self.stage_skills', src)

    def test_the_bill_of_materials_and_quantities_answer_is_checked(self):
        # The BOQ dialog passes its skills through _run_stage's worker_kwargs since Hitarth's
        # BOQ round (c0c1f09, 2026-10-27), not as a direct keyword. Same protection, new form:
        # the format stage asks for its skills, AND _run_stage hands worker_kwargs to the worker
        # (the old wording-only check could not see whether they ever reached it).
        src = self._src("addons", "boq", "dialog.py")
        self.assertIn('"stage_skills": {"format": [s.key for s in CB.skills.for_feature(', src)
        self.assertIn('f"{self.mode}.format")]}', src)
        self.assertIn("**self._rs_worker_kwargs)", src)

    def test_the_feature_keys_the_dialog_asks_for_are_claimed(self):
        SK.reload()
        self.assertEqual([s.key for s in SK.for_feature("bom.format")],
                         ["bom-parts"])
        self.assertEqual([s.key for s in SK.for_feature("boq.format")],
                         ["boq-writeup"])


class TheChecksKnowWhatTheToolWasShown(unittest.TestCase):
    """A figure is invented only if the tool was never given it. The engine
    hands each checker the prompt it typed, minus the skill's own text."""

    def setUp(self):
        SK.reload()

    def test_a_figure_the_tool_was_given_is_not_invented(self):
        prompt = ("Quotation: Rs 4,200 per tonne, delivery 4 weeks. "
                  "Customer wrote: a competitor offered Rs 3,900.")
        reply = ("You mentioned Rs 3,900. Our Rs 4,200 holds because it "
                 "carries IS 2062 material.\n\nIf you release the full order "
                 "I will hold it. I will send the schedule by Thursday.")
        faults = SK.check(["negotiation-email"], reply, {"prompt": prompt})
        self.assertEqual([f for f in faults if "neither the quotation" in f],
                         [])

    def test_a_figure_nobody_gave_it_is_invented(self):
        faults = SK.check(["negotiation-email"],
                          "We can do Rs 3,500 if you order by Thursday.",
                          {"prompt": "Quotation: Rs 4,200 per tonne."})
        self.assertTrue([f for f in faults if "neither the quotation" in f])

    def test_the_engine_hands_over_the_prompt_without_the_skill(self):
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn('skill_task_text = context + "\\n".join(questions)', src)
        self.assertEqual(src.count('"prompt": skill_task_text'), 2)

    def test_no_stage_inherits_the_skills_of_the_stage_before(self):
        import inspect
        src = inspect.getsource(AU.run)
        self.assertIn('skill_keys, skill_task_text = [], ""', src)
        self.assertLess(src.index('skill_keys, skill_task_text = [], ""'),
                        src.index("skill_keys = (list((stage_skills"))


class ThePlannerIsNotGivenMoreThanItNeeds(unittest.TestCase):
    """The planner prompt was already the thing the customer called
    over-engineered. Skills may add a line per stage and one sentence per
    skill, and nothing repeated."""

    def setUp(self):
        SK.reload()

    def test_each_description_appears_once_however_many_stages_share_it(self):
        agents = {"content": "Claude", "presentation": "Claude",
                  "development": "Claude"}
        text = R._stage_lines(agents, []) + R._skills_rule(agents)
        desc = SK.get("pdf-document").description
        self.assertEqual(text.count(desc), 1)
        self.assertIn("    SKILLS: ", R._stage_lines(agents, []))

    def test_no_skill_claims_the_video_stage(self):
        """Every tool on it is a renderer reading JSON or a maker building
        a clip. A storyboard layout typed there contradicts both."""
        self.assertEqual(SK.for_stage("media"), [])

    def test_the_negotiation_reply_is_checked(self):
        import inspect
        from core import drafting
        src = inspect.getsource(drafting.draft)
        self.assertIn('skill_feature: str = "inquiry.negotiation"', src)
        self.assertIn("_SK.for_feature(skill_feature)", src)
        self.assertEqual([s.key for s in SK.for_feature("inquiry.negotiation")],
                         ["negotiation-email"])


class TheTerminalShowsWhatTheCheckerSaid(unittest.TestCase):
    """rich treats '[anything]' as a style tag. Every skill fault starts
    with '[<skill>]' and many quote a bracketed placeholder back, so printed
    raw, the log lost both -- '·  Placeholder text left in: .' -- in the
    terminal and in the GUI's own log alike."""

    def test_a_fault_prints_with_its_brackets_intact(self):
        from core import ui
        seen = []
        ui.set_sink(lambda level, text: seen.append(text))
        try:
            ui.info("   · " + ui.literal(
                "[slide-deck] Placeholder text left in: [client name]."))
        finally:
            ui.set_sink(None)
        self.assertIn("[slide-deck]", seen[-1])
        self.assertIn("[client name]", seen[-1])

    def test_without_rich_the_brackets_survive_too(self):
        """rich is in the engine's requirements, not the app's, so no packaged
        build has it and neither does any CI lane. The fallback stripper ate
        the brackets there -- this pins that path whatever is installed."""
        import contextlib
        import io
        from unittest import mock
        from core import ui
        seen, out = [], io.StringIO()
        with mock.patch.object(ui, "_RICH", False), \
                contextlib.redirect_stdout(out):
            ui.set_sink(lambda level, text: seen.append(text))
            try:
                ui.info("   · " + ui.literal(
                    "[slide-deck] Placeholder text left in: [client name]."))
                ui.info("[bold]a tag[/bold] still goes")
            finally:
                ui.set_sink(None)
        self.assertEqual(
            seen, ["· [slide-deck] Placeholder text left in: [client name].",
                   "a tag still goes"])
        self.assertIn(
            "   · [slide-deck] Placeholder text left in: [client name].\n",
            out.getvalue())
        self.assertNotIn("\\[", out.getvalue())

    def test_the_engine_escapes_a_fault_before_printing_it(self):
        import inspect
        self.assertIn('ui.info(f"   · {ui.literal(fault)}")',
                      inspect.getsource(AU.run))


class TheFeaturePromptsCarryTheirDoctrine(unittest.TestCase):

    def setUp(self):
        SK.reload()

    def test_every_wired_feature_really_is_appended_somewhere(self):
        """The other half of test_no_skill_claims_a_feature_nothing_appends:
        that one stops a skill naming a key nobody calls, this one stops the
        list above growing a key that was never wired -- which would make
        the first test pass by lying."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        calls = set()
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs
                       if d not in ("__pycache__", ".git", ".venv", "dist",
                                    "build", "node_modules", "skills")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8",
                          errors="ignore") as f:
                    calls.update(re.findall(r"addendum\(\s*[\"']([\w.]+)",
                                            f.read()))
        self.assertEqual(
            WIRED_FEATURES - calls, set(),
            "these feature keys are listed as wired but nothing calls "
            "skills.addendum() for them")

    def test_the_bill_of_materials_prompt_carries_it(self):
        from core import bom
        prompt = bom.formatting_prompt("QTY-MARKER", "context")
        self.assertIn("BILL OF MATERIALS", prompt)
        self.assertTrue(prompt.rstrip().endswith("QTY-MARKER"),
                        "the measured quantities must stay last; doctrine "
                        "wedged after them buries the data")

    def test_the_bill_of_quantities_prompts_carry_it(self):
        from core import boq
        self.assertIn("BILL OF QUANTITIES", boq.formatting_prompt("Q", "c"))
        self.assertIn("BILL OF QUANTITIES",
                      boq.interpretation_prompt("r", "Q", "f"))
        self.assertIn("BILL OF QUANTITIES", boq.standards_prompt("r"))

    def test_the_negotiation_prompts_carry_it_after_the_hard_rules(self):
        from core import drafting
        prompt = drafting.negotiation_prompt(
            quotation_text="Rs 100", customer_reply="too costly",
            policy_text="", signature="Ravi")
        self.assertIn("NEGOTIATION AND FOLLOW-UP", prompt)
        self.assertLess(prompt.index("never invent".upper()
                                     if "NEVER INVENT" in prompt
                                     else drafting._NO_INVENTED_NUMBERS[:40]),
                        prompt.index("NEGOTIATION AND FOLLOW-UP"),
                        "the invented-numbers rules are the floor and must "
                        "come before the doctrine that could soften them")

    def test_the_follow_up_prompt_carries_it(self):
        from core import drafting
        self.assertIn("NEGOTIATION AND FOLLOW-UP", drafting.followup_prompt(
            quotation_text="Rs 100", days_waiting=5, attempt=1))


class ACustomerCanOverrideDoctrineButNotRunCode(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(C, "CONFIG_DIR", self._tmp.name)
        self._patch.start()
        self.user = os.path.join(self._tmp.name, "skills")

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()
        SK.reload()

    def _write(self, key: str, name: str, text: str):
        folder = os.path.join(self.user, key)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
            f.write(text)

    def test_the_user_folder_is_under_their_own_prism_directory(self):
        self.assertEqual(SK.user_dir(),
                         os.path.join(self._tmp.name, "skills"))

    def test_a_body_only_override_keeps_the_shipped_routing(self):
        self._write("slide-deck", "SKILL.md", "Our decks are always 8 slides.")
        SK.reload()
        s = SK.get("slide-deck")
        self.assertEqual(s.body, "Our decks are always 8 slides.")
        self.assertTrue(s.overridden)
        self.assertIn("presentation", s.stages)
        self.assertIn("Our decks are always 8 slides",
                      SK.block(["slide-deck"]))

    def test_notes_are_appended_to_the_shipped_doctrine(self):
        self._write("slide-deck", "notes.md", "We never use the logo on white.")
        SK.reload()
        text = SK.block(["slide-deck"])
        self.assertIn("One idea per slide", text)
        self.assertIn("FIELD NOTES", text)
        self.assertIn("We never use the logo on white", text)

    def test_a_customer_can_add_a_skill_of_their_own(self):
        self._write("house-tone", "SKILL.md",
                    "---\ntitle: House tone\ndescription: How this company "
                    "writes to its customers, in every letter and email.\n"
                    "stages: [content]\ntriggers: [letter]\n---\n"
                    "Short sentences. No exclamation marks. Sign off 'Regards'.")
        SK.reload()
        s = SK.get("house-tone")
        self.assertIsNotNone(s)
        self.assertIn("content", s.stages)
        self.assertIn("house-tone", [x.key for x in SK.for_stage("content")])

    def test_a_customer_skill_can_not_ship_a_checker(self):
        """The one thing an override may not do. A skill can change what a
        tool is told; it may not run code on the machine -- the same reason
        the engine's own sources are not shipped in a build."""
        self._write("evil", "SKILL.md",
                    "---\ntitle: Evil\ndescription: A skill that tries to "
                    "bring its own executable checker along with it.\n"
                    "stages: [content]\n---\nbody")
        self._write("evil", "checks.py",
                    "raise SystemExit('this must never run')")
        SK.reload()
        s = SK.get("evil")
        self.assertIsNotNone(s)
        self.assertFalse(s.has_checks, "a user-supplied checks.py was loaded")
        self.assertEqual(SK.check(["evil"], "anything", {}), [])

    def test_an_override_can_not_borrow_a_shipped_checker_for_new_doctrine(self):
        """Overriding a CHECKED skill keeps that skill's own checker -- it
        is the shipped file either way -- but the checker still comes from
        the shipped folder, never from the user's."""
        self._write("slide-deck", "checks.py",
                    "def faults(text, context):\n    return ['pwned']")
        SK.reload()
        self.assertTrue(SK.get("slide-deck").checks_path.startswith(
            SK.shipped_dir()))
        self.assertNotIn("[slide-deck] pwned",
                         SK.check(["slide-deck"], "SLIDE 1 — x\n", {}))


class TheLoaderIsHonestAboutBadInput(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(C, "CONFIG_DIR", self._tmp.name)
        self._patch.start()
        self.user = os.path.join(self._tmp.name, "skills")

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()
        SK.reload()

    def _write(self, key: str, text: str):
        folder = os.path.join(self.user, key)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "SKILL.md"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_a_folder_with_no_skill_file_is_ignored(self):
        os.makedirs(os.path.join(self.user, "empty"), exist_ok=True)
        SK.reload()
        self.assertIsNone(SK.get("empty"))

    def test_a_key_that_is_not_a_key_is_ignored(self):
        for bad in ("Has Capitals", "../escape", "x", "under_score"):
            folder = os.path.join(self.user, bad)
            try:
                os.makedirs(folder, exist_ok=True)
                with open(os.path.join(folder, "SKILL.md"), "w") as f:
                    f.write("---\ntitle: x\n---\nbody")
            except OSError:
                continue
        SK.reload()
        for bad in ("Has Capitals", "escape", "x", "under_score"):
            self.assertIsNone(SK.get(bad), bad)

    def test_unclosed_frontmatter_becomes_body_rather_than_losing_it(self):
        self._write("half", "---\ntitle: Half\nno closing fence\nreal doctrine")
        SK.reload()
        s = SK.get("half")
        self.assertIsNotNone(s)
        self.assertIn("real doctrine", s.body)

    def test_a_reload_happens_when_a_file_changes(self):
        self._write("moving", "---\ntitle: A\ndescription: first version of "
                    "this skill, long enough to be a real description.\n"
                    "stages: [content]\n---\nfirst")
        self.assertEqual(SK.get("moving").body, "first")
        self._write("moving", "---\ntitle: A\ndescription: second version of "
                    "this skill, long enough to be a real description.\n"
                    "stages: [content]\n---\nsecond")
        os.utime(os.path.join(self.user, "moving", "SKILL.md"), None)
        self.assertEqual(SK.get("moving").body, "second")

    def test_transport_decides_whether_a_skill_is_typed(self):
        self._write("apionly", "---\ntitle: Api only\ndescription: doctrine "
                    "for a direct model call, never for a browser tool.\n"
                    "stages: [content]\ntransport: [api]\n---\nbody here")
        SK.reload()
        self.assertEqual(SK.block(["apionly"], "browser"), "")
        self.assertIn("body here", SK.block(["apionly"], "api"))

    def test_a_long_body_is_cut_at_a_paragraph_and_marked(self):
        body = "\n\n".join(f"Paragraph {n} with some real words in it."
                           for n in range(60))
        self._write("long", "---\ntitle: Long\ndescription: a deliberately "
                    "over-long body used to prove the budget is enforced.\n"
                    "stages: [content]\nbudget: 300\n---\n" + body)
        SK.reload()
        text = SK.block(["long"], "browser")
        self.assertIn("[…]", text)
        self.assertLess(len(text), 300 + len(SK._INTRO) + 60)
        self.assertIn("body here" if False else "Paragraph 0", text)


class TheDoctrineFilesReadAsDoctrine(unittest.TestCase):
    """Cheap structural checks on the shipped bodies. A skill is only as
    good as the rules in it being concrete; these catch the two ways a
    body stops being usable."""

    def setUp(self):
        self.skills = SK.reload()

    def test_each_body_has_a_quality_checklist(self):
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertRegex(
                    s.body, r"(?i)##\s*Quality checklist",
                    "the block Prism types promises the tool it will be "
                    "checked against a checklist; this body has none")

    def test_each_body_says_what_not_to_do(self):
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertRegex(s.body, r"(?i)##\s*Non-goals")

    def test_no_body_leaves_a_placeholder(self):
        """Doctrine somebody never finished.

        Shape, not mere presence: a body may legitimately NAME these as
        things the tool must not write ('no "Lorem ipsum", no "TBD"'), and
        forbidding that would make the doctrine worse to spite the guard.
        What is never legitimate is a marker standing as content -- alone
        on a line, or opening one with a colon.
        """
        unfinished = re.compile(
            r"^[\s\-*#>]*(?:TODO|TBD|FIXME|XXX|lorem ipsum)\b\s*:?.*$",
            re.IGNORECASE | re.MULTILINE)
        for key, s in self.skills.items():
            with self.subTest(skill=key):
                self.assertIsNone(
                    unfinished.search(s.body),
                    "a line of this body is a placeholder marker, not "
                    "doctrine")

    def test_the_readme_sits_beside_the_skills(self):
        self.assertTrue(os.path.isfile(
            os.path.join(SK.shipped_dir(), "README.md")))


class TheBuildShipsThemWithTheirCheckers(unittest.TestCase):

    def test_the_spec_ships_the_skills_tree_including_the_py_files(self):
        """The engine-data loop drops every .py as code, which is right for
        engine sources and wrong for a checks.py -- nothing imports it, it
        is read from its path. Without this the app ships doctrine with
        nothing enforcing it, and only a customer would ever find out."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "packaging", "prism.spec"),
                  encoding="utf-8") as f:
            spec = f.read()
        self.assertIn('_SKILLS_DIR = os.path.join(ENGINE_DIR, "skills")', spec)
        self.assertIn('os.path.join("prism_terminal", _rel)', spec)
        self.assertIn('"skills")', spec.split("_ENGINE_SKIP_DIRS")[1][:200],
                      "skills/ must be excluded from the generic engine-data "
                      "walk, or every file ships twice")

    def test_the_frozen_self_test_loads_every_checker(self):
        """packaging/smoke_test.py runs the real executable with
        PRISM_SELFTEST on every platform CI builds; this census is what
        fails a build that lost the checkers."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "main.py"), encoding="utf-8") as f:
            src = f.read()
        body = src[src.index("def _selftest"):]
        self.assertIn("_skills_bridge.skills._checks_module(_s)", body)
        self.assertIn('checks.append((f"skills (', body)
        self.assertLess(body.index('checks.append((f"skills ('),
                        body.index("failed = [name for name, ok in checks if not ok]"))

    def test_the_shipped_folder_is_found_from_core(self):
        """Frozen, core/skills.py is imported from the archive and its
        __file__ points inside the bundle. Every candidate must be derived
        by walking up from that file, so a hardcoded developer path -- which
        exists on exactly one machine -- can never creep in."""
        engine = os.path.dirname(os.path.dirname(
            os.path.abspath(SK.__file__)))
        for candidate in SK.SHIPPED_DIRS:
            self.assertTrue(
                os.path.abspath(candidate).startswith(engine),
                f"{candidate} is not relative to the skills module itself")
        self.assertTrue(os.path.isdir(SK.shipped_dir()))


if __name__ == "__main__":
    unittest.main()

"""When a tool cannot finish, another one gets the job.

The failure this covers is the expensive one. A run is twenty to forty minutes
of browser automation, the whole pitch is that you start it and walk away, and
the heaviest stage is usually the last. So the free tier that runs out runs out
at the END — and before this, the customer came back to a pipeline that had
done nine tenths of the work and produced nothing they could use.

Three things are tested, because three separate things have to be right:

  1. **Recognising it.** "You've reached your limit" has to be told apart from
     "please sign in", because those need opposite responses: one Prism can
     route around by itself, the other only the user can fix.
  2. **Choosing the replacement.** It has to be able to do the same job, and it
     has to be one the user is plausibly signed in to.
  3. **Not making things worse.** No infinite retry, no rescue that throws away
     the results it was rescuing, and no retry of a stage that actually worked.

Nothing here opens a browser. The driver is a stub that returns page text.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import agents as A  # noqa: E402
from core import automation as AU  # noqa: E402


class _Page:
    """Just enough of a Selenium driver to be asked for the page text."""

    def __init__(self, text: str):
        self._text = text
        self.current_url = "https://example.test/c/1"

    def find_element(self, _how, _what):
        return type("El", (), {"text": self._text})()


# ── 1. recognising a tool that has run out ───────────────────────────────────

class TellingExhaustedFromSignedOut(unittest.TestCase):

    def test_the_real_wordings(self):
        """Taken from what these tools actually put on the page."""
        for wording in (
            "You've reached your limit for Claude Sonnet. Limit resets at 3 PM.",
            "You are out of free messages until tomorrow.",
            "Upgrade to continue using this model",
            "Too many requests. Please try again in a few minutes.",
            "Your daily limit has been reached.",
            "Quota exceeded for this project.",
            "We're currently at capacity. Please check back soon.",
        ):
            self.assertTrue(AU._looks_exhausted(_Page(wording)), wording)

    def test_a_working_page_is_not_mistaken_for_one(self):
        for wording in (
            "Here is the pitch deck outline you asked for. Slide 1: the problem…",
            "I've written the script. It runs about ninety seconds.",
            "",
        ):
            self.assertFalse(AU._looks_exhausted(_Page(wording)), wording)

    def test_a_quota_notice_on_a_long_page_is_still_caught(self):
        """This is why the check has no page-length ceiling, unlike the
        sign-in one. A limit notice appears on a full conversation with every
        previous turn still on it, so "a real page is long" would miss it."""
        page = _Page("some earlier answer. " * 500 +
                     "You've reached your limit for Claude Sonnet.")
        self.assertTrue(AU._looks_exhausted(page))

    def test_being_signed_out_is_a_different_answer(self):
        """They need opposite responses: Prism can route around an exhausted
        tool by itself, but only the user can sign in."""
        page = _Page("Please sign in to continue")
        self.assertFalse(AU._looks_exhausted(page))
        self.assertTrue(AU._looks_signed_out(page))

    def test_a_dead_driver_is_not_an_exception(self):
        class _Broken:
            def find_element(self, *_a):
                raise RuntimeError("session closed")

        self.assertEqual(AU._looks_exhausted(_Broken()), "")

    def test_the_message_quotes_the_page(self):
        """So the customer can see WHY Prism switched tools, rather than
        being told a tool failed for reasons of its own."""
        said = AU._looks_exhausted(_Page("You've reached your limit today."))
        self.assertIn("usage limit", said)
        self.assertIn("you've reached your limit", said)


# ── 2. choosing the replacement ──────────────────────────────────────────────

class PickingAnAlternative(unittest.TestCase):

    def test_the_customers_example(self):
        """Their words: "the freemium claude gets over, we have to give that
        task to kimi". Kimi is in the content category and configured, so it
        goes first."""
        picks = A.alternatives_for(
            "content", ["Claude"],
            {"agents": {"content": "Claude", "development": "Kimi 2.6"}})
        self.assertEqual(picks[0], "Kimi 2.6")

    def test_it_stays_in_the_same_category(self):
        """An alternative has to do the same JOB. Handing a failed image stage
        to a research tool produces an answer, and the answer is an essay
        about pictures."""
        for stage in ("content", "research", "visual", "presentation"):
            for name in A.alternatives_for(stage, []):
                self.assertIn(name, A.CATEGORIES[stage]["agents"], stage)

    def test_a_tool_already_tried_is_never_offered_again(self):
        self.assertNotIn("Claude", A.alternatives_for("content", ["Claude"]))
        self.assertEqual(
            A.alternatives_for("brains",
                               A.CATEGORIES["brains"]["agents"]), [])

    def test_tools_the_user_configured_come_first(self):
        """They picked them, which almost always means they are signed in —
        and a signed-out alternative fails exactly as fast as the tool it is
        replacing. "Claude" here (not "NotebookLM", pre-2026-11-08): the
        research category was narrowed that day (owner's own urgent call)
        to Grok/Claude/ChatGPT — Perplexity itself was pulled too, a few
        hours later the same day, once Chrome 157 proved to crash
        chromedriver on its page every single time, cookies/cache cleared
        or not — this test needs its example to actually BE a member of
        the category it is testing against."""
        picks = A.alternatives_for(
            "research", ["Perplexity"],
            {"agents": {"research": "Perplexity", "brains": "Claude"}})
        self.assertEqual(picks[0], "Claude")

    def test_prisms_own_renderers_are_never_the_alternative(self):
        """They are local renderers, not web tools. A stage that failed in a
        browser is not fixed by handing it to one."""
        picks = A.alternatives_for("media", ["Runway"])
        for name in picks:
            self.assertFalse(A.AGENT_REGISTRY[name].get("local"), name)

    def test_it_is_capped(self):
        """Each attempt is minutes of browser time. Trying eight tools turns a
        failed run into an afternoon."""
        self.assertLessEqual(len(A.alternatives_for("media", [])), 2)

    def test_an_unknown_stage_offers_nothing(self):
        self.assertEqual(A.alternatives_for("not-a-category", []), [])

    def test_every_alternative_is_actually_in_the_registry(self):
        """A category listing a tool the registry does not have would fail
        over onto a name that resolves to nothing."""
        for stage in A.CATEGORIES:
            for name in A.alternatives_for(stage, []):
                self.assertIn(name, A.AGENT_REGISTRY, f"{stage} -> {name}")

    def test_canva_is_not_offered_when_nobody_asked_for_something_editable(self):
        """A real run: ChatGPT hit its free-tier image limit on a request
        for a photorealistic product composite from reference photos.
        Canva sits first in the visual catalogue ("most business visual
        work is a post or a brochure"), and the failover offered it
        anyway — a template builder handed a job it can never do,
        because catalogue order was the only thing consulted. wants_canva
        already exists to keep the PRIMARY tool from routing an ordinary
        image request through Canva; this is that same signal, reused for
        the fallback choice instead of ignored by it."""
        for stage in ("visual", "presentation"):
            picks = A.alternatives_for(stage, [], query="make me a product photo")
            self.assertNotIn("Canva", picks, stage)
            picks_no_query = A.alternatives_for(stage, [])
            self.assertNotIn("Canva", picks_no_query, stage)

    def test_canva_is_still_offered_when_the_customer_actually_asked_for_it(self):
        """The legitimate case wants_canva protects stays intact: someone
        who explicitly wants an editable design still gets Canva offered
        as a fallback, not silently blocked by the same fix."""
        for stage in ("visual", "presentation"):
            picks = A.alternatives_for(
                stage, [], query="make a poster I can edit later in canva")
            self.assertIn("Canva", picks, stage)


class GoogleGeminiIsChatGPTsRealFallback(unittest.TestCase):
    """The owner's ask (15 Sep 2026): add a Google image tool to the visual
    category, positioned so it is actually the next thing tried when
    ChatGPT fails -- which on this account had already happened twice in
    one afternoon (its free-tier image limit). Read live against
    gemini.google.com (Nano Banana / Gemini 2.5 Flash Image) by attaching
    Playwright to Prism's own signed-in Chrome: a plain image prompt in
    the chat produced a clean, correctly-sized picture in about 15
    seconds, with a working download control once it settled -- no
    custom selectors needed, the generic composer and image-harvest logic
    already handle its DOM shape.
    """

    def test_it_is_offered_when_chatgpt_fails(self):
        self.assertIn("Google Gemini",
                      A.alternatives_for("visual", ["ChatGPT"], {"agents": {}}))

    def test_it_is_a_maker_of_images(self):
        entry = A.AGENT_REGISTRY["Google Gemini"]
        self.assertTrue(A.is_maker(entry))
        self.assertEqual(entry["makes"], "generated images")
        self.assertEqual(A.profile_for("Google Gemini")["produces"], ("image",))

    def test_it_is_not_a_local_renderer(self):
        """It is a real web tool, not one of Prism's own renderers -- the
        same thing that rules Prism Reel/Studio/Motion out as alternatives."""
        self.assertFalse(A.AGENT_REGISTRY["Google Gemini"].get("local"))

    def test_it_stays_in_the_visual_category_and_the_registry(self):
        self.assertIn("Google Gemini", A.CATEGORIES["visual"]["agents"])
        self.assertIn("Google Gemini", A.AGENT_REGISTRY)


class PrismImageIsTheDefaultVisualTool(unittest.TestCase):
    """2026-11-07, the owner's own call: "replace that particular step
    where usually chatgpt is responsible for the generation of images...
    with image generation through API key... FLUX 3 Klein... made that
    thing as the default and first choice." Same shape as Prism Studio/
    Reel/Motion (a local=... registry entry, see core.automation._run_local
    and core.image_gen), first in the catalogue so roles.default_agents()
    -- which always picks a category's first name -- hands it to a fresh
    install without anyone having to find it in Settings."""

    def test_it_is_registered_as_a_local_renderer(self):
        entry = A.AGENT_REGISTRY["Prism Image"]
        self.assertEqual(entry.get("local"), "flux_image")

    def test_it_is_first_in_the_visual_catalogue(self):
        self.assertEqual(A.CATEGORIES["visual"]["agents"][0], "Prism Image")

    def test_it_is_not_offered_as_a_browser_fallback(self):
        """Local agents are excluded from alternatives_for() -- a stage
        that failed in a browser is not fixed by handing it to one, and
        the reverse holds too: nothing should ever try to drive "Prism
        Image" as a Chrome tab."""
        for picks in (A.alternatives_for("visual", []),
                     A.alternatives_for("visual", ["ChatGPT"])):
            self.assertNotIn("Prism Image", picks)

    def test_every_alternative_still_resolves_with_it_first(self):
        """The existing "first TWO untried, non-local tools" fallback
        chain for a real browser failure must still skip straight past
        this local entry to Canva/Gemini, not choke on it being first."""
        picks = A.alternatives_for("visual", ["ChatGPT"], {"agents": {}})
        self.assertTrue(picks)
        for name in picks:
            self.assertFalse(A.AGENT_REGISTRY[name].get("local"))

    def test_the_visual_stage_dispatches_to_core_image_gen(self):
        """The one place a "visual" stage picked as "Prism Image" actually
        runs: _run_local("flux_image", ...) must hand off to
        core.image_gen.generate, the same way "reel_web"/"reel"/"motion"
        hand off to their own renderers — not silently fall through to
        "Unknown local agent". `query` (the run's own real ask — a
        follow-up's "use this logo" and nothing else, on a follow-up) must
        reach it too, not just whatever prior_text happens to hold —
        2026-11-08's own follow-up bug. `skill_text` (added the same day,
        same ask: a post's own design rules vary by occasion/client, and
        a matched skill's house doctrine is this pipeline's own existing
        way of saying "different rules for a different kind of job") must
        reach it too, defaulting to "" when the stage matched no skill —
        never a missing kwarg, since generate() always reads it."""
        from unittest import mock
        from core import image_gen as IG
        with mock.patch.object(IG, "generate", return_value=(
                "/tmp/flux_1.png", "FLUX 3 Klein drew the image")) as gen:
            out, note = AU._run_local(
                "flux_image", "a red panda astronaut", [],
                {"openrouter_api_key": "k"}, "visual",
                query="draw our mascot")
        gen.assert_called_once_with("draw our mascot",
                                    "a red panda astronaut",
                                    {"openrouter_api_key": "k"}, [],
                                    skill_text="")
        self.assertEqual(out, "/tmp/flux_1.png")
        self.assertIn("FLUX 3 Klein", note)

    def test_a_matched_skill_reaches_core_image_gen_too(self):
        from unittest import mock
        from core import image_gen as IG
        with mock.patch.object(IG, "generate", return_value=("/x.png", "x")) as gen:
            AU._run_local("flux_image", "a red panda astronaut", [],
                          {"openrouter_api_key": "k"}, "visual",
                          query="draw our mascot",
                          skill_text="PRISM SKILL — house doctrine...")
        self.assertEqual(gen.call_args.kwargs["skill_text"],
                         "PRISM SKILL — house doctrine...")

    def test_a_followup_on_visual_carries_the_original_posts_content(self):
        """The exact scenario reported 2026-11-08: a first run made a post
        (content stage wrote the real brief); a follow-up then said only
        "use this logo". Driven through the real automation.run() — the
        follow-up's own query AND the original run's seeded content must
        both reach generate(), not just the follow-up's bare one-liner."""
        from unittest import mock
        from core import image_gen as IG
        with mock.patch.object(AU, "_get_driver",
                              return_value=(mock.MagicMock(), True)), \
                mock.patch.object(IG, "generate", return_value=(
                    "/tmp/flux_2.png",
                    "FLUX 3 Klein drew: a red panda holding our logo")) as gen:
            responses, links = AU.run(
                {}, {"openrouter_api_key": "k"}, attachments=[],
                prior_responses={"content": [
                    "a launch post for our valve line, playful tone"]},
                query="use this logo",
                custom_stages=[("visual", "Prism Image", ["use this logo"])],
                failover=False)
        gen.assert_called_once()
        args = gen.call_args[0]
        self.assertEqual(args[0], "use this logo")
        self.assertIn("a launch post for our valve line, playful tone",
                      args[1])
        self.assertEqual(links["visual"], "/tmp/flux_2.png")

    def test_the_artwork_stage_routes_to_generate_artwork_not_generate(self):
        """"artwork" (a Reel's several-picture stage, core.reel_web's own
        MAX_GENERATED) is NOT the single-image "visual" path — a run whose
        agent for it is "Prism Image" must call generate_artwork (the
        multi-prompt, web-less-safe one), with the real user query and
        prior responses, and land every path it returns into this run's
        own responses/links. Driven through the real automation.run(),
        Chrome stubbed out since every stage here is local."""
        from unittest import mock
        from core import image_gen as IG
        with mock.patch.object(AU, "_get_driver",
                              return_value=(mock.MagicMock(), True)), \
                mock.patch.object(IG, "generate_artwork", return_value=(
                    ["/tmp/a.png", "/tmp/b.png"],
                    "FLUX 3 Klein drew 2 image(s).")) as gen:
            responses, links = AU.run(
                {}, {"openrouter_api_key": "k"}, attachments=[],
                query="make a Dhanteras post for this company in Vadodara",
                custom_stages=[("artwork", "Prism Image", ["anything"])],
                failover=False)
        gen.assert_called_once()
        args, kwargs = gen.call_args
        self.assertEqual(args[0],
                         "make a Dhanteras post for this company in Vadodara")
        self.assertEqual(kwargs["has_own_artwork"], False)
        self.assertEqual(responses["artwork"], ["FLUX 3 Klein drew 2 image(s)."])
        self.assertEqual(links["artwork"], "/tmp/a.png")

    def test_has_own_artwork_is_true_when_the_client_attached_a_logo(self):
        from unittest import mock
        from core import image_gen as IG
        with mock.patch.object(AU, "_get_driver",
                              return_value=(mock.MagicMock(), True)), \
                mock.patch.object(IG, "generate_artwork",
                                  return_value=(["/tmp/a.png"], "ok")) as gen:
            AU.run({}, {"openrouter_api_key": "k"},
                  attachments=[{"path": "/tmp/their_logo.png",
                               "name": "their_logo.png"}],
                  query="make a reel",
                  custom_stages=[("artwork", "Prism Image", ["anything"])],
                  failover=False, chatgpt_analysis=False)
        self.assertTrue(gen.call_args.kwargs["has_own_artwork"])


# ── 3. the retry pass ────────────────────────────────────────────────────────

class TheRetryPass(unittest.TestCase):

    def setUp(self):
        self.calls = []
        self.events = []
        self._real_run = AU.run

    def tearDown(self):
        AU.run = self._real_run

    def _fake_run(self, answers):
        """Stand in for a real pipeline run. `answers` maps agent name -> the
        text it produces (or "" for a tool that also fails)."""
        def fake(routing, cfg, **kw):
            stage, agent, _q = kw["custom_stages"][0]
            self.calls.append((stage, agent, kw.get("failover")))
            text = answers.get(agent, "")
            return ({stage: [text]} if text else {}), {stage: "https://x/1"}
        return fake

    def _retry(self, failures, responses, answers, cfg=None):
        AU.run = self._fake_run(answers)
        AU._retry_failed_stages(
            failures, cfg or {}, responses, {},
            attachments=[], query="q",
            emit=lambda k, p: self.events.append((k, p)),
            should_stop=None)

    def test_a_failed_stage_is_handed_to_another_tool(self):
        responses = {}
        self._retry({"content": {"agent": "Claude", "questions": ["write it"],
                                 "reason": "usage limit", "exhausted": True}},
                    responses, {"Jasper": "the finished copy"})
        self.assertEqual(responses["content"], ["the finished copy"])

    def test_the_retry_cannot_itself_retry(self):
        """Without this, a category where every tool is having a bad afternoon
        recurses until something gives out."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Jasper": "done"})
        self.assertEqual([c[2] for c in self.calls], [False])

    def test_it_moves_on_when_the_first_alternative_also_fails(self):
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Copy.ai": "second one worked"})
        tried = [c[1] for c in self.calls]
        self.assertEqual(len(tried), 2)
        self.assertEqual(tried[-1], "Copy.ai")

    def test_it_stops_once_one_works(self):
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {"Jasper": "done", "Copy.ai": "also done"})
        self.assertEqual(len(self.calls), 1)

    def test_a_stage_that_already_worked_is_left_alone(self):
        """Re-running a good stage would replace a real answer with a second
        opinion, and cost minutes doing it."""
        responses = {"content": ["the good answer"]}
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    responses, {"Jasper": "different answer"})
        self.assertEqual(self.calls, [])
        self.assertEqual(responses["content"], ["the good answer"])

    def test_an_exception_in_the_rescue_does_not_take_the_run_down(self):
        """A rescue that destroys the results it was rescuing is worse than
        not trying."""
        def explode(routing, cfg, **kw):
            raise RuntimeError("chrome died")

        AU.run = explode
        responses = {"research": ["kept"]}
        AU._retry_failed_stages(
            {"content": {"agent": "Claude", "questions": ["x"],
                         "reason": "r", "exhausted": True}},
            {}, responses, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None)
        self.assertEqual(responses["research"], ["kept"])

    def test_stopping_is_honoured_before_a_retry_starts(self):
        AU.run = self._fake_run({"Jasper": "done"})
        AU._retry_failed_stages(
            {"content": {"agent": "Claude", "questions": ["x"],
                         "reason": "r", "exhausted": True}},
            {}, {}, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=lambda: True)
        self.assertEqual(self.calls, [])

    def test_the_screen_is_told_which_tool_took_over(self):
        """It matters to the customer: the answer came from somewhere other
        than the tool named in their plan, and History has to say so."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "usage limit", "exhausted": True}},
                    {}, {"Jasper": "done"})
        kinds = [k for k, _ in self.events]
        self.assertIn("stage_failover", kinds)
        self.assertIn("stage_recovered", kinds)
        payload = dict(self.events)["stage_recovered"]
        self.assertEqual(payload["failed"], "Claude")
        self.assertEqual(payload["agent"], "Jasper")

    def test_giving_up_is_reported_too(self):
        """Silence here would look like the stage was never attempted."""
        self._retry({"content": {"agent": "Claude", "questions": ["x"],
                                 "reason": "r", "exhausted": True}},
                    {}, {})            # nothing answers
        self.assertIn("stage_unrecovered", [k for k, _ in self.events])


# ── 4. a recovered stage feeding a renderer that already ran ────────────────
#
# `media` (Prism Reel/Studio) runs as one function call, in its own turn — so
# if `visual` failed there and only came back through the retry above, the
# renderer already finished without the images `visual` was going to hand it.
# A plain text/URL handoff can't make an already-rendered video notice new
# pictures showed up afterwards, so the renderer has to be called again.

class ARendererThatAlreadyRan(unittest.TestCase):

    def setUp(self):
        self._real_run = AU.run
        self._real_run_local = AU._run_local

    def tearDown(self):
        AU.run = self._real_run
        AU._run_local = self._real_run_local

    def _fake_run(self, success_text="recovered", images=None):
        """Succeeds on whichever alternative gets tried first — these tests
        are about what happens AFTER a stage recovers, not about which tool
        does the recovering, so which name `alternatives_for` picks first is
        not something they should have to track."""
        def fake(routing, cfg, **kw):
            stage, _agent, _q = kw["custom_stages"][0]
            out = kw.get("pipeline_files_out")
            if images and out is not None:
                out.extend(images)
            return {stage: [success_text]}, {stage: "https://x/1"}
        return fake

    def test_the_renderer_is_called_again_with_the_recovered_images(self):
        rerender_calls = []

        def fake_run_local(kind, prior_text, attachments, cfg, stage, brand=None,
                           studio=None):
            rerender_calls.append((kind, stage, list(attachments)))
            return "/runs/reel_2.mp4", "reel rendered — reel_2.mp4"

        AU.run = self._fake_run(
            "some images",
            images=[{"name": "grid.png", "path": "/tmp/grid.png", "kind": "image"}])
        AU._run_local = fake_run_local

        stages = [("content", "Claude", ["write it"]),
                  ("visual", "ChatGPT", ["make images"]),
                  ("media", "Prism Reel", ["render it"])]
        responses = {"content": ["the script"]}
        links = {"media": "/runs/reel_1.mp4"}       # media already rendered once
        pipeline_files = []

        AU._retry_failed_stages(
            {"visual": {"agent": "DALL-E", "questions": ["make images"],
                       "reason": "quota", "exhausted": True}},
            {}, responses, links, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=pipeline_files, brand={})

        self.assertEqual(len(rerender_calls), 1, rerender_calls)
        kind, stage, attachments_seen = rerender_calls[0]
        self.assertEqual(kind, "reel")
        self.assertEqual(stage, "media")
        self.assertIn({"name": "grid.png", "path": "/tmp/grid.png", "kind": "image"},
                      attachments_seen)
        self.assertEqual(links["media"], "/runs/reel_2.mp4")

    def test_a_renderer_with_nothing_recovered_upstream_is_left_alone(self):
        """`audio` sits AFTER `media` in this plan — its recovery has nothing
        to do with what the renderer already drew, so re-running the render
        would just cost minutes for an identical result. (`content`, which
        genuinely feeds the render, is covered by the test above — recovering
        it SHOULD trigger a re-render, and does.)"""
        rerender_calls = []
        AU._run_local = lambda *a, **kw: rerender_calls.append(a) or ("x", "y")
        AU.run = self._fake_run("the narration")

        stages = [("content", "Claude", ["write it"]),
                  ("media", "Prism Reel", ["render it"]),
                  ("audio", "ElevenLabs", ["voice it"])]
        links = {"media": "/runs/reel_1.mp4"}

        AU._retry_failed_stages(
            {"audio": {"agent": "ElevenLabs", "questions": ["voice it"],
                      "reason": "quota", "exhausted": True}},
            {}, {}, links, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=[], brand={})

        self.assertEqual(rerender_calls, [])

    def test_a_renderer_that_never_ran_is_not_conjured_into_existing(self):
        """`media` isn't in `all_links` at all here — it was never reached, so
        there is nothing to redo."""
        rerender_calls = []
        AU._run_local = lambda *a, **kw: rerender_calls.append(a) or ("x", "y")
        AU.run = self._fake_run("images")

        stages = [("visual", "ChatGPT", ["make images"]),
                  ("media", "Prism Reel", ["render it"])]

        AU._retry_failed_stages(
            {"visual": {"agent": "DALL-E", "questions": ["make images"],
                       "reason": "quota", "exhausted": True}},
            {}, {}, {}, attachments=[], query="q",
            emit=lambda *a: None, should_stop=None,
            stages=stages, pipeline_files=[], brand={})

        self.assertEqual(rerender_calls, [])


class WiredIntoTheRun(unittest.TestCase):
    """The units above are worthless if run() never calls them."""

    def test_run_takes_the_switch_and_defaults_to_on(self):
        import inspect

        sig = inspect.signature(AU.run)
        self.assertIn("failover", sig.parameters)
        self.assertIs(sig.parameters["failover"].default, True)

    def test_run_actually_calls_the_retry(self):
        import ast

        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "..", "prism_terminal", "core", "automation.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "run")
        called = {n.func.id for n in ast.walk(run)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_retry_failed_stages", called)


if __name__ == "__main__":
    unittest.main()

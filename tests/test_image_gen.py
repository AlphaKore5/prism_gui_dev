"""core/image_gen.py -- the "visual" stage's default local renderer:
FLUX 3 Klein, called directly through OpenRouter (2026-11-07, replacing
ChatGPT as the default image-generation step). Nothing here reaches the
real OpenRouter API -- core.openrouter.openrouter_image is mocked.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

from core import image_gen as IG                                   # noqa: E402


class GenerateDrawsFromTheQueryAndEveryPriorStage(unittest.TestCase):
    """generate()'s signature is (query, prior_text, cfg, attachments=None)
    — `query` is the run's own real ask (a follow-up's "use this logo" and
    nothing else, on a follow-up), never just whichever prior stage's text
    happened to be newest. Claude Haiku 5.5 (build_single_prompt) turns
    query + every earlier stage's output into ONE coherent FLUX prompt;
    most tests here stub that step directly so they pin generate()'s OWN
    wiring, not Haiku's wording — a couple of tests right after this class
    cover that synthesis step for real."""

    def test_the_synthesised_prompt_is_what_flux_is_asked_to_draw(self):
        with mock.patch.object(IG, "build_single_prompt",
                              return_value="a red panda astronaut") as brief, \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"\x89PNGfake") as call:
            out, note = IG.generate(
                "draw our mascot", "", {"openrouter_api_key": "sk-or-x"})
        self.assertTrue(out)
        self.assertTrue(os.path.isfile(out))
        self.assertIn("FLUX 3 Klein", note)
        self.assertIn("a red panda astronaut", note)
        self.assertEqual(call.call_args[0][2], "a red panda astronaut")
        brief.assert_called_once()
        self.assertEqual(brief.call_args[0][0], "draw our mascot")
        with open(out, "rb") as f:
            self.assertEqual(f.read(), b"\x89PNGfake")

    def test_haiku_failing_falls_back_to_the_query_itself(self):
        """build_single_prompt degrades to "" on any failure (no key, a
        network error) — generate() must still draw SOMETHING rather than
        fail the whole stage over a synthesis hiccup."""
        with mock.patch.object(IG, "build_single_prompt", return_value=""), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x") as call:
            IG.generate("a mountain at sunrise", "",
                       {"openrouter_api_key": "sk-or-x"})
        self.assertEqual(call.call_args[0][2], "a mountain at sunrise")

    def test_no_query_falls_back_to_prior_text(self):
        """A caller with no real `query` (none currently exists, kept for
        robustness) still has prior_text to fall back to."""
        with mock.patch.object(IG, "build_single_prompt", return_value=""), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x") as call:
            IG.generate("", ["", "  ", "a mountain at sunrise"],
                       {"openrouter_api_key": "sk-or-x"})
        self.assertEqual(call.call_args[0][2], "a mountain at sunrise")

    def test_the_model_id_is_flux_3_klein(self):
        with mock.patch.object(IG, "build_single_prompt", return_value="x"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x") as call:
            IG.generate("x", "", {"openrouter_api_key": "sk-or-x"})
        self.assertEqual(call.call_args[0][1],
                         "black-forest-labs/flux-3-image-klein")
        self.assertEqual(IG.MODEL, "black-forest-labs/flux-3-image-klein")

    def test_nothing_at_all_to_draw_from_fails_without_calling_openrouter(self):
        with mock.patch.object(IG._openrouter, "openrouter_image") as call:
            out, note = IG.generate("   ", "   ",
                                    {"openrouter_api_key": "sk-or-x"})
        self.assertEqual(out, "")
        self.assertIn("Nothing was written", note)
        call.assert_not_called()

    def test_no_openrouter_key_fails_without_calling_openrouter(self):
        with mock.patch.object(IG._openrouter, "openrouter_image") as call:
            out, note = IG.generate("a red panda", "", {})
        self.assertEqual(out, "")
        self.assertIn("needs an OpenRouter key", note)
        call.assert_not_called()

    def test_an_openrouter_image_failure_is_reported_not_raised(self):
        with mock.patch.object(IG, "build_single_prompt",
                              return_value="a red panda"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  side_effect=RuntimeError("rate-limited")):
            out, note = IG.generate("a red panda", "",
                                    {"openrouter_api_key": "k"})
        self.assertEqual(out, "")
        self.assertEqual(note, "rate-limited")

    def test_two_calls_a_second_apart_write_different_files(self):
        with mock.patch.object(IG, "build_single_prompt", return_value="x"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x"), \
                mock.patch.object(IG.time, "time", side_effect=[1000, 1001]):
            first, _ = IG.generate("a", "", {"openrouter_api_key": "k"})
            second, _ = IG.generate("b", "", {"openrouter_api_key": "k"})
        self.assertNotEqual(first, second)


class GenerateCarriesTheFollowUpThroughToHaiku(unittest.TestCase):
    """Reported live, 2026-11-08: filled in real content on a post, then
    followed up with "use this logo" — the new picture was random, because
    the old code only ever grabbed prior_text's single most recent entry
    (the follow-up's own terse ask, or this stage's own earlier one-line
    note) and sent THAT straight to FLUX. query + every prior stage's
    output must both reach the brief-writer."""

    def test_the_query_and_every_prior_stage_reach_build_single_prompt(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="a red panda holding our logo"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x") as img_call:
            IG.generate(
                "use this logo",   # the follow-up's own real ask
                ["FLUX 3 Klein drew: a red panda astronaut, studio light",
                 "content: a launch post for our new valve line, playful "
                 "tone, navy and orange"],
                {"openrouter_api_key": "k"})
        self.assertEqual(img_call.call_args[0][2],
                         "a red panda holding our logo")

    def test_the_meta_prompt_itself_carries_both(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="x") as chat_call, \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x"):
            IG.generate(
                "use this logo",
                ["content: a launch post for our new valve line"],
                {"openrouter_api_key": "k"})
        meta_prompt = chat_call.call_args[0][2]
        self.assertIn("use this logo", meta_prompt)
        self.assertIn("our new valve line", meta_prompt)


class GenerateCarriesAMatchedSkillThroughToHaikuToo(unittest.TestCase):
    """2026-11-08: a post's own design rules vary by occasion and by
    client (a festival post is not a product-launch post), so a matched
    core.skills.py doctrine for this specific job must reach the
    meta-prompt too, ahead of the general design rules — and must not
    appear at all when no skill matched (the common case; most calls
    pass no skill_text)."""

    def test_skill_text_reaches_the_meta_prompt_when_given(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="x") as chat_call, \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x"):
            IG.generate("a post for our product launch", "",
                       {"openrouter_api_key": "k"},
                       skill_text="PRISM SKILL — product-launch doctrine")
        self.assertIn("PRISM SKILL — product-launch doctrine",
                      chat_call.call_args[0][2])

    def test_no_skill_text_means_no_empty_section(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="x") as chat_call, \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=b"x"):
            IG.generate("a plain post", "", {"openrouter_api_key": "k"})
        self.assertNotIn("PRISM SKILL", chat_call.call_args[0][2])


class SingleBriefPromptAdaptsToWhateverTheClientActuallyGave(unittest.TestCase):
    """2026-11-08: the brief must not hand the writer a fixed checklist
    (tagline/offer/phone/website and nothing else) — different clients
    give completely different kinds of information. The instruction
    itself must say to look for whatever is really there, not assume a
    fixed set of fields."""

    def test_asks_for_whatever_is_actually_given_not_a_fixed_list(self):
        text = IG._single_brief_prompt("a post", "")
        self.assertIn("varies by", text)
        self.assertIn("rather than expecting a fixed list", text)

    def test_still_names_the_reserved_corner_and_layout_rules(self):
        text = IG._single_brief_prompt("a post", "")
        self.assertIn("RESERVED CORNER", text)
        self.assertIn("LAYOUT", text)


def _fake_png_bytes(color=(255, 255, 255)) -> bytes:
    """A real, tiny, openable PNG — generate_artwork() runs its output
    through core.assets.prepare()/cutout(), which needs real pixels, not
    an arbitrary byte string."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color).save(buf, "PNG")
    return buf.getvalue()


def _fake_logo_file(path: str) -> str:
    """A real logo-shaped file on disk: a small red mark on a plain white
    card — exactly the "mark on a flat card" case core.assets.cutout()
    already knows how to extract, so _own_logo() exercises the real,
    already-trusted cut-out path, not a mock of it."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (120, 120), (255, 255, 255))
    ImageDraw.Draw(im).rectangle((30, 30, 90, 90), fill=(200, 30, 30))
    im.save(path, "PNG")
    return path


class GenerateNeverLetsFluxDrawTheClientsOwnLogo(unittest.TestCase):
    """Reported live, 2026-11-08: attached a real logo, asked for a post,
    and the logo in the generated picture did not match it. Root cause:
    generate() never looked at `attachments` at all, so the only "logo"
    FLUX could make was its own guess from text. core.assets' own rule
    (never ask an AI to redraw a mark — extract and composite the real
    one) now applies here too."""

    def test_a_real_logo_is_cut_out_and_composited_not_drawn(self):
        logo = _fake_logo_file(
            os.path.join(tempfile.mkdtemp(), "their_logo.png"))
        with mock.patch.object(IG, "build_single_prompt",
                              return_value="a bold product shot"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=_fake_png_bytes()) as call:
            out, note = IG.generate(
                "make an Instagram post with our logo", "",
                {"openrouter_api_key": "k"},
                [{"path": logo, "name": "their_logo.png"}])
        self.assertTrue(out)
        self.assertIn("your own logo placed on top", note)
        # FLUX itself was told NOT to draw one.
        sent_prompt = call.call_args[0][2]
        self.assertIn("Do not draw any logo", sent_prompt)
        # The actual pixels: the generated (white) picture now has the
        # real logo's red mark composited into its bottom-right corner,
        # not whatever FLUX would have invented.
        from PIL import Image
        with Image.open(out) as im:
            px = im.convert("RGB").load()
            w, h = im.size
            corner = px[w - 10, h - 10]
        self.assertGreater(corner[0], 150)   # red channel: the real mark
        self.assertLess(corner[1], 100)      # not white, not FLUX's guess

    def test_no_attachment_means_no_compositing_and_no_instruction(self):
        with mock.patch.object(IG, "build_single_prompt", return_value="x"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=_fake_png_bytes()) as call:
            out, note = IG.generate(
                "make an Instagram post", "", {"openrouter_api_key": "k"}, [])
        self.assertNotIn("logo", note)
        self.assertNotIn("Do not draw any logo", call.call_args[0][2])

    def test_a_plain_photograph_attachment_is_not_treated_as_a_logo(self):
        """core.assets' own rule: a photograph (no flat background to cut,
        no real alpha) is left alone and never mistaken for a mark."""
        import numpy as np
        from PIL import Image
        photo = os.path.join(tempfile.mkdtemp(), "photo.jpg")
        noise = (np.random.default_rng(0).integers(
            0, 255, (120, 120, 3), dtype="uint8"))
        Image.fromarray(noise).save(photo, "JPEG")
        with mock.patch.object(IG, "build_single_prompt", return_value="x"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=_fake_png_bytes()) as call:
            out, note = IG.generate(
                "make a post", "", {"openrouter_api_key": "k"},
                [{"path": photo, "name": "photo.jpg"}])
        self.assertNotIn("logo", note)
        self.assertNotIn("Do not draw any logo", call.call_args[0][2])


class BuildPromptsWritesOneSelfContainedBriefPerAsset(unittest.TestCase):
    """FLUX cannot browse and knows nothing past training — asked for "a
    Dhanteras post for this company in Vadodara" with no other context it
    has no way to complete that itself. A text model writes the real
    briefs first; this is that step, covered without a real OpenRouter
    call (core.openrouter.openrouter_chat is mocked)."""

    def test_a_200_with_n_lines_returns_exactly_those_prompts(self):
        lines = "\n".join(f"prompt {i}" for i in range(1, 7))
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value=lines) as call:
            out = IG.build_prompts("make a Dhanteras post", "",
                                   {"openrouter_api_key": "k"})
        self.assertEqual(out, [f"prompt {i}" for i in range(1, 7)])
        self.assertEqual(call.call_args[0][1], IG.BRIEF_MODEL)

    def test_the_meta_prompt_carries_the_request_and_context(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="a\nb") as call:
            IG.build_prompts(
                "a Dhanteras post for this company in Vadodara",
                "research: they manufacture industrial valves",
                {"openrouter_api_key": "k"})
        meta_prompt = call.call_args[0][2]
        self.assertIn("a Dhanteras post for this company in Vadodara",
                      meta_prompt)
        self.assertIn("industrial valves", meta_prompt)
        self.assertIn("Dhanteras", meta_prompt)      # reused as an example
        self.assertIn("flat solid plain background", meta_prompt)

    def test_todays_date_is_in_the_meta_prompt(self):
        import datetime
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="a\nb") as call:
            IG.build_prompts("x", "", {"openrouter_api_key": "k"})
        today = datetime.date.today().strftime("%d %B %Y")
        self.assertIn(today, call.call_args[0][2])

    def test_no_logo_role_when_the_client_already_has_one(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="a\nb\nc\nd\ne") as call:
            IG.build_prompts("x", "", {"openrouter_api_key": "k"},
                            has_own_artwork=True)
        meta_prompt = call.call_args[0][2]
        self.assertNotIn("wordmark/emblem", meta_prompt)

    def test_no_key_returns_nothing_without_a_network_call(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat") as call:
            out = IG.build_prompts("x", "", {})
        self.assertEqual(out, [])
        call.assert_not_called()

    def test_an_openrouter_failure_returns_nothing_not_a_crash(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              side_effect=RuntimeError("down")):
            out = IG.build_prompts("x", "", {"openrouter_api_key": "k"})
        self.assertEqual(out, [])


class GenerateArtworkDrawsCutsAndKeepsGoingOnOneFailure(unittest.TestCase):
    """The "artwork" stage's own local path: brief, draw, cut the flat
    background out with core.assets (never a new background-remover —
    the one already built and tested for a client's own flat-card logo)."""

    def test_the_brief_sees_every_earlier_stage_not_just_the_last_one(self):
        """Reported live, 2026-11-08: "artwork" usually runs after BOTH
        research (what the company does, their colours) and content (the
        script) -- _prompt_from (single-image 'visual' path) stops at the
        first non-empty entry, which would have silently thrown research's
        own findings away the moment a content stage ran after it. Both
        must reach the brief-writer."""
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="a\nb") as call:
            IG.generate_artwork(
                "make a reel",
                ["the script: a 15-second reel about our valves",
                 "research: Patel Engineering, Vadodara, makes industrial "
                 "valves, brand colours navy and orange"],
                {"openrouter_api_key": "k"})
        meta_prompt = call.call_args[0][2]
        self.assertIn("Patel Engineering", meta_prompt)
        self.assertIn("navy and orange", meta_prompt)
        self.assertIn("15-second reel", meta_prompt)

    def test_six_prompts_become_six_cutout_images(self):
        lines = "\n".join(f"prompt {i}" for i in range(1, 7))
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value=lines), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=_fake_png_bytes()):
            paths, note = IG.generate_artwork(
                "make a Dhanteras post", "", {"openrouter_api_key": "k"})
        self.assertEqual(len(paths), 6)
        for p in paths:
            self.assertTrue(os.path.isfile(p), p)
        self.assertIn("6", note)

    def test_every_image_call_asks_for_a_flat_background(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="one prompt"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  return_value=_fake_png_bytes()) as img_call:
            IG.generate_artwork("x", "", {"openrouter_api_key": "k"})
        sent_prompt = img_call.call_args[0][2]
        self.assertIn("one prompt", sent_prompt)
        self.assertIn("flat solid", sent_prompt)

    def test_one_failed_asset_does_not_sink_the_rest(self):
        lines = "\n".join(f"prompt {i}" for i in range(1, 4))
        calls = {"n": 0}

        def flaky(*_a, **_kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("rate-limited")
            return _fake_png_bytes()

        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value=lines), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  side_effect=flaky):
            paths, note = IG.generate_artwork(
                "x", "", {"openrouter_api_key": "k"})
        self.assertEqual(len(paths), 2)        # 3 asked, 1 failed, 2 made
        self.assertIn("2", note)

    def test_no_prompts_at_all_is_a_clear_failure(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value=""):
            paths, note = IG.generate_artwork(
                "x", "", {"openrouter_api_key": "k"})
        self.assertEqual(paths, [])
        self.assertIn("OpenRouter key", note)

    def test_every_openrouter_call_failing_is_a_clear_failure_not_empty_success(self):
        with mock.patch.object(IG._openrouter, "openrouter_chat",
                              return_value="prompt 1"), \
                mock.patch.object(IG._openrouter, "openrouter_image",
                                  side_effect=RuntimeError("down")):
            paths, note = IG.generate_artwork(
                "x", "", {"openrouter_api_key": "k"})
        self.assertEqual(paths, [])
        self.assertIn("could not draw", note)


if __name__ == "__main__":
    unittest.main()

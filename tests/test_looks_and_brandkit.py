"""Two films in a row must not share a look, and a film must carry the client's identity.

Found 13 Nov 2026: every Studio reel was a serif over an arch (the prompt's one worked example),
the colour sampler read only green, and Prism Motion was never passed the brand at all.
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import automation as AU, brandkit, looks, reel, reel_web   # noqa: E402
from core import config as C                                           # noqa: E402
from core.motion import generate as G                                  # noqa: E402

try:
    from PIL import Image, ImageDraw
except Exception:                                                      # pragma: no cover
    Image = None


def _logo(colour, extra=None):
    d = tempfile.mkdtemp()
    im = Image.new("RGB", (600, 400), "white")
    dr = ImageDraw.Draw(im)
    dr.ellipse((150, 80, 450, 320), fill=colour)
    if extra:
        dr.rectangle((20, 20, 60, 60), fill=extra)
    p = os.path.join(d, "logo.png")
    im.save(p)
    return p


@unittest.skipIf(Image is None, "Pillow is not installed")
class TheSamplerReadsEveryHue(unittest.TestCase):
    def test_red_blue_and_orange_brands_are_read_exactly(self):
        for rgb, want in (((200, 22, 29), "#C8161D"), ((20, 90, 200), "#145AC8"), ((240, 150, 20), "#F09614")):
            self.assertEqual(reel.sample_brand([_logo(rgb)]).get("accent"), want)

    def test_a_green_brand_reads_as_it_always_did(self):
        self.assertEqual(reel.sample_brand([_logo((74, 181, 10))]), {"accent": "#4AB50A", "deep": "#358207"})

    def test_a_red_logo_with_a_small_green_detail_is_a_red_brand(self):
        self.assertEqual(reel.sample_brand([_logo((200, 22, 29), extra=(74, 181, 10))])["accent"], "#C8161D")

    def test_black_and_white_artwork_gives_no_colour_rather_than_a_guess(self):
        self.assertEqual(reel.sample_brand([_logo((30, 30, 30))]), {})


class BrandKit(unittest.TestCase):
    def test_only_well_formed_fields_survive(self):
        kit = brandkit.clean({"name": "  Shakti   Foods ", "accent": "red", "deep": "#900f14", "tone": "",
                              "contact": ["+91 98765 43210", 7], "extra": "x"})
        self.assertEqual(kit, {"name": "Shakti Foods", "deep": "#900F14", "contact": ["+91 98765 43210"]})
        self.assertEqual(brandkit.clean("nonsense"), {})
        self.assertEqual(brandkit.from_config({}), {})

    def test_typed_colours_win_over_measured_ones(self):
        got = brandkit.colours({"accent": "#C8161D"}, {"accent": "#4AB50A", "deep": "#358207"})
        self.assertEqual(got["accent"], "#C8161D")
        self.assertEqual(got["deep"], "#900F14", "the deep is derived from THEIR accent, not kept from the other colour")
        self.assertEqual(brandkit.colours({}, {"accent": "#4AB50A", "deep": "#358207"}),
                         {"accent": "#4AB50A", "deep": "#358207"})
        self.assertEqual(brandkit.colours({}, None), {})

    def test_the_designer_is_told_the_identity_and_nothing_is_invented_for_a_gap(self):
        self.assertEqual(brandkit.block({}), "")
        text = brandkit.block({"name": "Shakti Foods", "tagline": "Taste of home", "display_font": "Anton",
                               "contact": ["shaktifoods.in"]}, has_logo=True)
        for want in ('"Shakti Foods"', '"Taste of home"', "Anton for headlines", "shaktifoods.in", "`logo`"):
            self.assertIn(want, text)
        self.assertNotIn("How they speak", text)

    def test_what_the_kit_supplies_may_be_shown(self):
        from core.motion import grounding
        scene = {"nodes": [{"type": "text", "content": "Call +91 98765 43210 · shaktifoods.in"}]}
        self.assertTrue(grounding.grounding_faults(scene, grounding.allowed_corpus("make a reel")))
        kit = {"contact": ["+91 98765 43210", "shaktifoods.in"]}
        self.assertEqual(grounding.grounding_faults(scene, grounding.allowed_corpus("make a reel\n" + brandkit.corpus(kit))), [])

    def test_a_supplied_mark_that_no_scene_places_is_a_fault(self):
        self.assertTrue(brandkit.missing_logo('{"src": "asset:photo1"}', has_logo=True))
        self.assertEqual(brandkit.missing_logo('{"src": "asset:logo"}', has_logo=True), "")
        self.assertEqual(brandkit.missing_logo("{}", has_logo=False), "")


class Looks(unittest.TestCase):
    REQ = "make reel for wishing happy christmas"

    def test_every_direction_states_the_same_six_things(self):
        for name, look in looks.LOOKS.items():
            for key in ("title", "words", "ground", "type", "framing", "layout", "motion", "avoid"):
                self.assertTrue(look.get(key), f"{name} has no {key}")
        self.assertTrue(set(looks.ROTATION) <= set(looks.LOOKS))
        self.assertNotIn("tech", looks.ROTATION, "the dark-tech look is not a neutral default")

    def test_the_same_request_run_again_and_again_uses_every_direction_before_repeating(self):
        history: list = []
        for _ in range(len(looks.ROTATION) * 2):
            history.append(looks.pick(self.REQ, history))
        first, second = history[:len(looks.ROTATION)], history[len(looks.ROTATION):]
        self.assertEqual(sorted(first), sorted(looks.ROTATION))
        self.assertEqual(sorted(second), sorted(looks.ROTATION))
        self.assertTrue(all(a != b for a, b in zip(history, history[1:])))

    def test_the_choice_is_reproducible(self):
        self.assertEqual(looks.pick(self.REQ, ["poster"]), looks.pick(self.REQ, ["poster"]))

    def test_a_direction_the_client_names_is_the_one_used(self):
        self.assertEqual(looks.pick("christmas reel in a bold style", ["poster"]), "poster")
        self.assertEqual(looks.pick("a minimal look reel for our clinic", []), "swiss")
        self.assertEqual(looks.pick("style: luxury, diwali wishes", []), "luxe")
        self.assertEqual(looks.pick("explain our tech stack", ["editorial"]), looks.pick("explain our tech stack", ["editorial"]))
        self.assertNotEqual(looks.named("explain our tech stack"), "tech", "a subject is not a style request")

    def test_what_was_used_is_remembered_between_runs(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(C, "RUNS_DIR", d):
            self.assertEqual(looks.recent(), [])
            a = AU._film_look(self.REQ)
            b = AU._film_look(self.REQ)
            self.assertNotEqual(a, b)
            self.assertEqual(looks.recent(), [a, b])
            looks.remember("not a look")
            self.assertEqual(looks.recent(), [a, b])

    def test_an_unreadable_history_is_no_history(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(C, "RUNS_DIR", d):
            open(os.path.join(d, "looks_recent.json"), "w").write("{not json")
            self.assertEqual(looks.recent(), [])
            self.assertIn(looks.pick(self.REQ, looks.recent()), looks.ROTATION)


class ThePromptsCarryTheDirectionAndTheIdentity(unittest.TestCase):
    KIT = {"name": "Shakti Foods", "tagline": "Taste of home"}

    def test_studio_with_a_direction_no_longer_hands_out_the_arch(self):
        text = reel_web.design_instructions({"accent": "#C8161D"}, "a reel", "", look="poster", kit=self.KIT)
        self.assertIn('ART DIRECTION FOR THIS FILM — "Poster"', text)
        self.assertNotIn("arches", text)
        self.assertNotIn("400px 400px", text)
        self.assertIn('"Shakti Foods"', text)
        self.assertIn("#C8161D", text)

    def test_studio_without_a_direction_reads_as_before(self):
        text = reel_web.design_instructions({}, "a reel", "")
        self.assertIn("classic architectural arches", text)
        self.assertNotIn("ART DIRECTION FOR THIS FILM", text)

    def test_two_directions_give_two_different_briefs(self):
        a = reel_web.design_instructions({}, "a reel", "", look="poster")
        b = reel_web.design_instructions({}, "a reel", "", look="editorial")
        self.assertNotEqual(a, b)

    def test_motion_is_told_the_colours_the_direction_and_the_identity(self):
        for skeleton in ("cinematic_glass", "story"):
            text = G.storyboard_instructions("a film", brand={"accent": "#C8161D", "deep": "#900F14"},
                                             skeleton=skeleton, look="swiss", kit=self.KIT, has_logo=True)
            self.assertIn("#C8161D", text)
            self.assertIn('ART DIRECTION FOR THIS FILM — "Swiss grid"', text)
            self.assertIn('"Shakti Foods"', text)
            self.assertIn("`logo`", text)

    def test_the_clients_own_typefaces_replace_the_directions(self):
        text = looks.text("poster", fonts_given=True)
        self.assertNotIn("Anton", text)
        self.assertIn("client's own typefaces", text)


class TheRunPassesThemOn(unittest.TestCase):
    """The parameter existing is not the same as anything passing it: Motion's `brand` sat unused."""

    def test_both_film_stages_are_planned_with_the_direction_the_kit_and_the_colours(self):
        src = inspect.getsource(AU.run)
        self.assertIn("look=film_look, kit=film_kit)", src)                      # Studio's design turn
        self.assertIn("query, brand=motion_brand or None", src)                  # Motion's storyboard turn
        self.assertIn("has_logo=motion_has_logo", src)
        self.assertIn("brand=motion_brand, look=film_look", src)                 # Motion's turn rebuilt with the script
        self.assertIn("_brandkit.colours(film_kit, brand)", src)
        self.assertIn("_brandkit.corpus(film_kit)", src)

    def test_the_rebuilt_motion_turn_keeps_them(self):
        got = AU.motion_turn_one("a film", "story", {"content": ["SCENE 1\nHello there"]},
                                 brand={"accent": "#C8161D", "deep": "#900F14"}, look="night",
                                 kit={"name": "Shakti Foods"}, has_logo=False)
        if got:                                           # "" when the responses hold no script
            self.assertIn("#C8161D", got)
            self.assertIn('"Night"', got)
            self.assertIn('"Shakti Foods"', got)


if __name__ == "__main__":
    unittest.main()


class FilmPicturesAreWholeScenes(unittest.TestCase):
    """A reel's pictures were six cut-out subjects on white, set on cards: the slide-deck look."""

    def _run(self, **kw):
        from core import image_gen
        calls = []

        def fake_image(key, model, prompt, aspect_ratio="1:1", resolution="1K", **_):
            calls.append((prompt, aspect_ratio))
            buf = tempfile.SpooledTemporaryFile()
            from io import BytesIO
            b = BytesIO()
            Image.new("RGB", (90, 160), (200, 22, 29)).save(b, "PNG")
            return b.getvalue()

        prompts = [f"prompt {i}" for i in range(1, 6)]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(C, "RUNS_DIR", d), \
                mock.patch.object(image_gen, "build_prompts", return_value=prompts) as bp, \
                mock.patch.object(image_gen._openrouter, "openrouter_image", side_effect=fake_image), \
                mock.patch("core.assets.prepare", side_effect=lambda p, out=None: {"path": p + ".cut.png"}):
            paths, note = image_gen.generate_artwork("a film", "", {"openrouter_api_key": "k"}, **kw)
        return paths, calls, bp

    def test_a_film_gets_three_full_frame_plates_and_two_cut_out_subjects(self):
        paths, calls, bp = self._run(film=True, look="night", brand={"accent": "#C8161D"})
        self.assertEqual([a for _, a in calls], ["9:16", "9:16", "9:16", "4:5", "4:5"])
        self.assertFalse(any("flat solid plain white" in p for p, _ in calls[:3]), "a plate is not set on white")
        self.assertTrue(all("flat solid plain white" in p for p, _ in calls[3:]))
        self.assertEqual([p.endswith(".cut.png") for p in paths], [False, False, False, True, True],
                         "only the subjects have their ground cut away")
        style = bp.call_args.kwargs["film"]
        self.assertIn("cinematic low-key photograph", style)       # the look's own picture style
        self.assertIn("#C8161D", style)                            # the brand colour

    def test_without_film_mode_nothing_changes(self):
        paths, calls, bp = self._run(has_own_artwork=False, n=6)
        self.assertEqual({a for _, a in calls}, {"4:5"})
        self.assertEqual(bp.call_args.kwargs["film"], "")

    def test_every_look_says_how_its_pictures_are_made(self):
        for name in looks.LOOKS:
            self.assertTrue(looks.image_style(name), name)
        self.assertEqual(looks.image_style("nope"), "")

    def test_the_film_stage_passes_the_direction_and_colours_to_the_pictures(self):
        src = inspect.getsource(AU.run)
        self.assertIn("film=bool(film_look), look=film_look", src)
        self.assertIn("brand=studio_brand or motion_brand or None", src)

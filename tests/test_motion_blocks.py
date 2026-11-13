"""The block library: scenes whose layout, scale, timing and hold are fixed in code and tested, so the model writes only words."""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import blocks, generate, rhythm, schema  # noqa: E402


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


PLAN = [
    {"block": "title", "seconds": 3.4, "slots": {"kicker": "Season's greetings", "headline": "Merry Christmas", "line": "Warm wishes for you and yours"}},
    {"block": "statement", "seconds": 3.4, "slots": {"kicker": "This year", "text": "Thank you for being part of our year", "emphasis": "our year"}},
    {"block": "list", "seconds": 4.4, "slots": {"heading": "This Christmas we wish you", "items": ["Time with people you love", "A little rest", "Good food and laughter", "Hope for the year ahead"]}},
    {"block": "number", "seconds": 3.4, "slots": {"figure": "24 Dec", "label": "The night before everything", "line": "Lights on, doors open"}},
    {"block": "close", "seconds": 4.0, "slots": {"name": "Happy Holidays", "done": "Wishes sent", "contact": "+91 98765 43210"}},
]
LONG = " and then some more words that run long"
WORST = [dict(p, slots={k: ([i + LONG for i in v] if isinstance(v, list) else v + LONG) for k, v in p["slots"].items()}) for p in PLAN]
ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}


class Structure(unittest.TestCase):
    def test_every_block_is_in_the_prompt_with_its_slots(self):
        text = blocks.blocks_text()
        for name, b in blocks.BLOCKS.items():
            self.assertIn(f'"{name}"', text)
            for slot in b["slots"]:
                self.assertIn(f'"{slot}"', text)

    def test_the_prompt_forbids_inventing_a_sender_and_names_no_pixel(self):
        t = blocks.plan_instructions("a christmas film")
        self.assertIn("NEVER INVENT WHO IT IS FROM", t)
        self.assertNotIn("1080", t)

    def test_a_default_length_is_stated_when_none_is_given_and_the_ask_wins_when_given(self):
        self.assertIn("15 to 22 seconds", blocks.plan_instructions("x"))
        self.assertIn("30 seconds", blocks.plan_instructions("x", total_seconds=30))

    def test_each_block_has_exactly_one_focus_a_carried_node_and_no_looping_drift(self):
        spec = blocks.compose_plan({}, PLAN)
        for scene in spec["scenes"]:
            nodes = scene["nodes"]
            self.assertEqual(len([n for n in nodes if n.get("focus")]), 1, scene["id"])
            self.assertTrue(any(n.get("continuity_key") == "carry" for n in nodes), scene["id"])
            self.assertFalse(any("secondary_motion" in (n.get("animation") or {}) for n in nodes), "a block ends on a hold")

    def test_the_close_lands_with_a_hit_and_the_film_is_light_and_has_sound(self):
        spec = blocks.compose_plan({}, PLAN)
        self.assertTrue(any(n.get("hit") for n in spec["scenes"][-1]["nodes"]))
        self.assertEqual(spec["project"]["look"], "paper")
        self.assertEqual(spec["project"]["sound"], "ui")
        self.assertAlmostEqual(spec["project"]["duration"], sum(p["seconds"] for p in PLAN), places=1)

    def test_it_validates_at_every_aspect(self):
        for label, (w, h) in ASPECTS.items():
            v = schema.validate_motion_spec(blocks.compose_plan({}, PLAN, w, h))
            self.assertEqual(len(v["scenes"]), 5, label)

    def test_a_long_line_is_wrapped_and_trimmed_to_its_budget(self):
        self.assertEqual(blocks.fit("one two three four five six", 8, 2), "one two\nthree f…")
        self.assertEqual(blocks.fit("", 8), "")


LOGO = {"logo": {"path": "/x/logo.png", "w": 900, "h": 900, "alpha": True, "kind": "logo"}}
BRAND = {"accent": "#C8161D", "deep": "#14412F"}
LOOKS = [k for k in blocks.LOOKS if k]


def _colours(spec):
    return {k: v.upper() for k, v in spec["project"]["palette"].items()}


class Looks(unittest.TestCase):
    def test_every_look_is_one_of_core_looks_directions(self):
        from core import looks
        self.assertEqual(len(LOOKS), 8)
        self.assertEqual(set(LOOKS) - set(looks.LOOKS), set())

    def test_every_look_validates_at_every_aspect_with_a_logo_and_a_brand(self):
        for look in LOOKS:
            for label, (w, h) in ASPECTS.items():
                v = schema.validate_motion_spec(blocks.compose_plan({}, PLAN, w, h, look=look, brand=BRAND, assets=LOGO))
                self.assertEqual(len(v["scenes"]), 5, f"{look} {label}")

    def test_two_looks_differ_in_palette_and_in_fonts(self):
        a, b = (blocks.compose_plan({}, PLAN, look=k) for k in ("editorial", "night"))
        self.assertNotEqual(_colours(a)["bg_a"], _colours(b)["bg_a"])
        self.assertNotEqual(a["project"]["type"]["display_font"], b["project"]["type"]["display_font"])
        self.assertNotEqual(a["project"]["type"]["google_fonts_url"], b["project"]["type"]["google_fonts_url"])

    def test_looks_are_pairwise_distinct_in_ground_and_display_face(self):
        seen = set()
        for look in LOOKS:
            p = blocks.compose_plan({}, PLAN, look=look, brand=BRAND)
            seen.add((p["scenes"][0]["nodes"][0]["fill"], p["project"]["type"]["display_font"]))
        self.assertEqual(len(seen), len(LOOKS))

    def test_an_unknown_look_is_the_librarys_own(self):
        self.assertEqual(blocks.compose_plan({}, PLAN, look="nonsense")["project"]["type"], blocks.compose_plan({}, PLAN)["project"]["type"])

    def test_a_brand_overrides_the_looks_accents(self):
        plain = blocks.compose_plan({}, PLAN, look="swiss")
        branded = blocks.compose_plan({}, PLAN, look="swiss", brand={"accent": "#0A7B3E", "deep": "#123456"})
        self.assertNotEqual(_colours(plain)["accent"], "#0A7B3E")
        self.assertEqual(_colours(branded)["accent"], "#0A7B3E")
        self.assertEqual(_colours(branded)["accent2"], "#123456")

    def test_the_logo_is_in_the_close_only_when_one_is_supplied(self):
        for look in [""] + LOOKS:
            def ids(assets):
                spec = blocks.compose_plan({}, PLAN, look=look, assets=assets)
                return [[n["id"] for n in sc["nodes"] if n.get("type") == "image"] for sc in spec["scenes"]]
            self.assertEqual(ids(None), [[]] * 5, look)
            with_logo = ids(LOGO)
            self.assertEqual(with_logo[-1], ["logo"], look)
            self.assertEqual(with_logo[:-1], [[]] * 4, look)

    def test_the_logo_sits_inside_the_frame_and_keeps_its_proportions(self):
        for look in [""] + LOOKS:
            for label, (w, h) in ASPECTS.items():
                spec = blocks.compose_plan({}, PLAN, w, h, look=look, assets=dict(logo=dict(LOGO["logo"], w=600, h=300)))
                n = next(n for n in spec["scenes"][-1]["nodes"] if n["id"] == "logo")
                self.assertAlmostEqual(n["width"] / n["height"], 2.0, delta=0.02, msg=f"{look} {label}")
                x, y = n["position"]
                self.assertGreaterEqual(x - n["width"] / 2, 0, f"{look} {label}")
                self.assertLessEqual(x + n["width"] / 2, w, f"{look} {label}")
                self.assertGreaterEqual(y - n["height"] / 2, 0, f"{look} {label}")
                self.assertLessEqual(y + n["height"] / 2, h, f"{look} {label}")

    def test_the_logo_and_its_plate_arrive_inside_the_close_scene(self):
        """The plate and the mark once shared one animation dict, which the resolver offsets once per node:
        both arrived a whole scene late (6.4 s into a 3.2-6.8 s scene) and never showed."""
        from core.motion import resolver
        for look in ("night", "poster", "luxe"):
            spec = resolver.resolve_motion_spec(schema.validate_motion_spec(blocks.compose_plan({}, PLAN, look=look, assets=LOGO)))
            scene = spec["scenes"][-1]
            for n in scene["nodes"]:
                if n["id"] in ("logo", "logo_plate"):
                    t = n["animation"]["enter"]["time"]
                    self.assertTrue(scene["start"] <= t < scene["start"] + scene["duration"] / 2, f"{look} {n['id']} at {t}")

    def test_a_logo_never_sits_on_a_ground_it_cannot_be_read_against(self):
        """Dark grounds (night, luxe, poster's red) get a light plate under the mark."""
        spec = blocks.compose_plan({}, PLAN, look="night", assets=LOGO)
        self.assertIn("logo_plate", [n["id"] for n in spec["scenes"][-1]["nodes"]])
        spec = blocks.compose_plan({}, PLAN, look="swiss", assets=LOGO)
        self.assertNotIn("logo_plate", [n["id"] for n in spec["scenes"][-1]["nodes"]])


class Parsing(unittest.TestCase):
    def test_a_plan_is_read_from_a_fenced_reply_and_unknown_blocks_are_dropped(self):
        reply = "```json\n" + json.dumps({"project": {"palette": {"accent": "#123456"}}, "plan": [
            {"block": "title", "seconds": 1, "slots": {"headline": "Hi"}}, {"block": "sparkle", "slots": {}}]}) + "\n```"
        project, plan = blocks.parse_plan(reply)
        self.assertEqual(project["palette"]["accent"], "#123456")
        self.assertEqual([p["block"] for p in plan], ["title"])
        self.assertGreaterEqual(plan[0]["seconds"], blocks.BLOCKS["title"]["min"], "a block is given at least its minimum time")

    def test_nothing_usable_is_an_empty_plan(self):
        self.assertEqual(blocks.parse_plan("sorry"), ({}, []))
        self.assertEqual(blocks.parse_plan("{not json"), ({}, []))

    def test_plan_faults_name_what_is_wrong(self):
        bad = [{"block": "statement", "seconds": 3, "slots": {}}, {"block": "list", "seconds": 4, "slots": {"heading": "h", "items": ["a"]}}]
        f = " | ".join(blocks.plan_faults(bad))
        for needle in ('open with a "title"', 'end with a "close"', 'no "text"', "at least 3 items"):
            self.assertIn(needle, f)
        self.assertEqual(blocks.plan_faults(blocks.parse_plan(json.dumps({"plan": PLAN}))[1]), [])
        three = [{"block": "title", "seconds": 3, "slots": {"headline": "a"}}] + [{"block": "statement", "seconds": 3, "slots": {"text": "x"}}] * 3 \
            + [{"block": "close", "seconds": 3, "slots": {"name": "b"}}]
        self.assertTrue(any("three" in x for x in blocks.plan_faults(three)))


class InTheBuild(unittest.TestCase):
    def _reply(self, plan):
        return "```json\n" + json.dumps({"project": {}, "plan": plan}) + "\n```"

    def test_a_good_plan_is_composed_with_one_turn_and_never_asks_for_a_scene(self):
        asked = []
        spec = generate.build_spec(self._reply(PLAN), lambda p, expect=None: asked.append(p) or "", skeleton="blocks",
                                   request="a christmas film from Happy Holidays, phone +91 98765 43210")
        self.assertEqual(asked, [])
        self.assertEqual(len(spec["scenes"]), 5)
        self.assertEqual(spec["_motion_profile"], "blocks")

    def test_an_invented_sender_sends_the_plan_back_once_and_the_fix_is_used(self):
        bad = [dict(p, slots=dict(p["slots"])) for p in PLAN]
        bad[-1]["slots"]["contact"] = "www.acme.com"
        good = [dict(p, slots=dict(p["slots"])) for p in PLAN]
        good[-1]["slots"].pop("contact")
        asked = []
        spec = generate.build_spec(self._reply(bad), lambda p, expect=None: asked.append(p) or self._reply(good), skeleton="blocks",
                                   request="a christmas film from Happy Holidays, phone +91 98765 43210")
        self.assertEqual(len(asked), 1)
        self.assertIn("acme.com", asked[0])
        texts = json.dumps(spec["scenes"])
        self.assertNotIn("acme", texts)

    def test_a_plan_that_never_parses_is_an_error_not_an_empty_film(self):
        with self.assertRaises(Exception):
            generate.build_spec("nothing useful", lambda p, expect=None: "still nothing", skeleton="blocks")

    def test_the_storyboard_turn_is_the_block_prompt(self):
        self.assertIn("THE BLOCKS", generate.storyboard_instructions("make a christmas film", skeleton="blocks"))


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class RealLayout(unittest.TestCase):
    """The reason blocks exist: laid out in the real runtime, camera applied, at three frame shapes."""

    def test_no_text_runs_off_the_frame_even_with_overlong_words(self):
        from core.motion import measure
        for label, (w, h) in ASPECTS.items():
            for name, plan in (("normal", PLAN), ("overlong", WORST)):
                faults = measure.inspect_all(schema.validate_motion_spec(blocks.compose_plan({}, plan, w, h)))
                self.assertEqual(faults, [], f"{label} {name}: {faults[:2]}")

    def test_every_look_lays_out_cleanly_at_every_aspect_even_with_overlong_words(self):
        from core.motion import measure
        for look in LOOKS:
            for label, (w, h) in ASPECTS.items():
                for name, plan in (("normal", PLAN), ("overlong", WORST)):
                    spec = blocks.compose_plan({}, plan, w, h, look=look, brand=BRAND, assets=LOGO)
                    faults = measure.inspect_all(schema.validate_motion_spec(spec))
                    self.assertEqual(faults, [], f"{look} {label} {name}: {faults[:2]}")

    def test_the_composed_film_breathes(self):
        for label, (w, h) in ASPECTS.items():
            p = rhythm.probe(blocks.compose_plan({}, PLAN, w, h))
            self.assertIsNotNone(p)
            self.assertGreaterEqual(p["static_pct"], 15, label)
            self.assertLessEqual(p["static_pct"], 45, f"{label}: {p['static_pct']}")
            self.assertGreaterEqual(p["holds_ge_1s"], 2, label)


class FontWarmup(unittest.TestCase):
    def test_a_closed_page_never_raises(self):
        from core import browser

        class Dead:
            def evaluate(self, *_a, **_k):
                raise RuntimeError("page closed")

        self.assertEqual(browser.warm_fonts(Dead()), 0)

    @unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
    def test_the_first_settled_frame_of_every_session_has_its_text(self):
        """13 Nov 2026: web fonts load lazily by glyph range, and document.fonts.ready resolves
        before anything has asked for them, so the first frame to use a font was captured with
        the text invisible (30 distinct grey levels, a bare gradient, instead of 80+)."""
        import io
        from PIL import Image
        from core.motion import critic
        spec = blocks.compose_plan({"motif": "none"}, PLAN)
        for session in range(2):
            frames = critic.settled_frames(spec)
            levels = len(set(Image.open(io.BytesIO(frames[0][1])).convert("L").resize((40, 22)).getdata()))
            self.assertGreater(levels, 40, f"session {session}: the title scene came back without its text")


if __name__ == "__main__":
    unittest.main()

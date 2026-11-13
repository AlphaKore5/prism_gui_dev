"""The vision critic: opt-in, never raises, parses defects, costs are tracked, frames are real."""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import critic  # noqa: E402

CFG = {"motion_critic": True, "openrouter_api_key": "sk-or-test"}
FRAMES = [(0, b"\x89PNG-a"), (1, b"\x89PNG-b")]


class Opt_in(unittest.TestCase):
    def test_off_by_default_and_without_a_key_nothing_is_sent(self):
        with mock.patch("core.openrouter.openrouter_chat") as chat:
            for cfg in (None, {}, {"openrouter_api_key": "sk-or-x"}, {"motion_critic": True}, {"motion_critic": True, "openrouter_api_key": "  "}):
                r = critic.critique(FRAMES, cfg)
                self.assertEqual(r["defects"], [])
                self.assertIsNotNone(r["skipped"])
            chat.assert_not_called()
        self.assertFalse(critic.enabled({"motion_critic": False, "openrouter_api_key": "sk-or-x"}))
        self.assertTrue(critic.enabled(CFG))


class Asking(unittest.TestCase):
    def _chat(self, reply, cost=0.0004, boom=None):
        def fake(key, model, prompt, **kw):
            if boom:
                raise boom
            kw["usage_sink"].update({"cost": cost, "prompt_tokens": 900})
            self.seen = dict(model=model, prompt=prompt, n=len(kw["attachments"]), extra=kw["extra"], key=key)
            return reply
        return fake

    def test_frames_go_as_images_with_the_schema_and_the_defects_come_back_with_the_cost(self):
        reply = json.dumps({"defects": [
            {"scene": 1, "type": "text cut off by frame edge", "where": "headline, left", "severity": 3},
            {"scene": 2, "type": "big empty area", "where": "lower half", "severity": 1}]})
        with mock.patch("core.openrouter.openrouter_chat", side_effect=self._chat(reply)):
            r = critic.critique(FRAMES, CFG)
        self.assertEqual(self.seen["n"], 2)
        self.assertEqual(self.seen["model"], critic.MODEL)
        self.assertEqual(self.seen["extra"]["response_format"]["json_schema"]["strict"], True)
        self.assertEqual(self.seen["key"], "sk-or-test")
        self.assertAlmostEqual(r["cost"], 0.0004)
        self.assertIsNone(r["skipped"])
        self.assertEqual([d["severity"] for d in r["defects"]], [3, 1])

    def test_a_provider_error_never_raises_and_says_why(self):
        with mock.patch("core.openrouter.openrouter_chat", side_effect=self._chat("", boom=RuntimeError("OpenRouter rejected your API key."))):
            r = critic.critique(FRAMES, CFG)
        self.assertEqual(r["defects"], [])
        self.assertIn("could not answer", r["skipped"])
        self.assertIn("rejected", r["skipped"])

    def test_a_reply_over_the_cost_cap_is_flagged(self):
        with mock.patch("core.openrouter.openrouter_chat", side_effect=self._chat('{"defects": []}', cost=0.5)):
            r = critic.critique(FRAMES, CFG, max_cost=0.10)
        self.assertIn("cap", r["skipped"])


class Parsing(unittest.TestCase):
    def test_json_wrapped_in_prose_and_garbage_are_handled(self):
        self.assertEqual(len(critic.parse('Here you go: {"defects": [{"scene": 1, "type": "x", "where": "y", "severity": 2}]} done')), 1)
        for bad in ("", "not json", "{}", '{"defects": "nope"}', None):
            self.assertEqual(critic.parse(bad), [])

    def test_severity_is_clamped_and_malformed_entries_dropped(self):
        d = critic.parse(json.dumps({"defects": [{"scene": 1, "type": "a", "where": "", "severity": 9},
                                                 {"scene": "x", "type": "b", "where": "", "severity": 1},
                                                 {"scene": 2, "type": "", "where": "", "severity": 2}]}))
        self.assertEqual([(x["scene"], x["severity"]) for x in d], [(1, 3)])

    def test_faults_are_worst_first_and_drop_minor_ones(self):
        d = [{"scene": 3, "type": "empty card", "where": "centre", "severity": 2},
             {"scene": 1, "type": "text cut off", "where": "left edge", "severity": 3},
             {"scene": 2, "type": "faint", "where": "", "severity": 1}]
        f = critic.faults(d)
        self.assertEqual(f, ["Scene 1: text cut off — left edge", "Scene 3: empty card — centre"])


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class Frames(unittest.TestCase):
    def test_one_real_png_per_scene_at_the_small_size(self):
        from io import BytesIO
        from PIL import Image
        scenes = [{"id": f"s{i}", "duration": 2, "nodes": [{"id": "t", "type": "text", "content": f"Scene {i}",
                                                           "position": [540, 960], "font_size": 120, "fill": "#111111"}]}
                  for i in range(3)]
        spec = {"project": {"duration": 6, "fps": 30, "width": 1080, "height": 1920, "background": "#FAF9F6"}, "scenes": scenes}
        frames = critic.settled_frames(spec)
        self.assertEqual([i for i, _ in frames], [0, 1, 2])
        im = Image.open(BytesIO(frames[0][1]))
        self.assertEqual(im.size, (540, 960))
        self.assertGreater(len(frames[0][1]), 1000)


def _d(scene, sev, what="no focus"):
    return {"scene": scene, "type": what, "where": "centre", "severity": sev}


class Repair(unittest.TestCase):
    """A serious defect sends its scene back once; the fix is kept only if the film has fewer of them."""

    def _run(self, looks):
        scenes = [{"id": f"s{i}", "duration": 3, "v": 0} for i in range(3)]
        asked, it = [], iter(looks)

        def ask(prompt, expect=None):
            asked.append(prompt)
            return "fixed"

        def parse(text):
            return {"id": "?", "duration": 0, "v": 1} if text == "fixed" else None

        def keep(old, new):
            new["id"], new["duration"] = old["id"], old["duration"]

        said = []
        critic.repair(scenes, lambda rows: {"scenes": rows}, ask, parse, keep, said.append, lambda spec: next(it), '"nodes"')
        return scenes, asked, said

    def test_a_clean_film_is_left_alone(self):
        scenes, asked, said = self._run([[_d(1, 1)]])
        self.assertEqual(asked, [])
        self.assertTrue(all(s["v"] == 0 for s in scenes))

    def test_a_serious_defect_goes_back_with_its_words_and_a_real_fix_is_kept(self):
        scenes, asked, said = self._run([[_d(2, 3, "text cut off")], []])
        self.assertEqual(len(asked), 1)
        self.assertIn("scene 2", asked[0]); self.assertIn("text cut off", asked[0])
        self.assertEqual([s["v"] for s in scenes], [0, 1, 0])
        self.assertEqual(scenes[1]["id"], "s1", "the id survives the rewrite")

    def test_a_fix_that_leaves_as_many_defects_is_not_kept(self):
        scenes, asked, said = self._run([[_d(2, 3)], [_d(2, 3)]])
        self.assertEqual([s["v"] for s in scenes], [0, 0, 0])

    def test_a_re_check_that_wipes_every_other_scene_too_is_not_believed(self):
        # Logged 13 Nov 2026: one scene was rewritten and the critic's next reading of the film was "0 defects"
        # (it had said 16 before and said 11 after). Fixing scene 1 cannot clear scenes 2-4.
        before = [_d(1, 3), _d(2, 3), _d(2, 3), _d(3, 3), _d(3, 3)]
        scenes, asked, said = self._run([before, []])
        self.assertEqual([s["v"] for s in scenes], [0, 0, 0])
        self.assertTrue(any("not steady" in m for m in said), said)

    def test_when_the_critic_cannot_re_check_the_fix_is_not_assumed_good(self):
        scenes, asked, said = self._run([[_d(2, 3)], None])
        self.assertEqual([s["v"] for s in scenes], [0, 0, 0])

    def test_when_the_critic_cannot_look_at_all_nothing_is_changed(self):
        scenes, asked, said = self._run([None])
        self.assertEqual(asked, [])

    def test_at_most_three_scenes_go_back_worst_first(self):
        scenes = [{"id": f"s{i}", "duration": 3, "v": 0} for i in range(5)]
        looks = iter([[_d(1, 2), _d(2, 3), _d(3, 3), _d(4, 2), _d(5, 3)],
                      [_d(1, 2), _d(3, 3), _d(4, 2), _d(5, 3)], [_d(1, 2), _d(4, 2), _d(5, 3)], [_d(1, 2), _d(4, 2)]])
        asked = []
        critic.repair(scenes, lambda rows: {"scenes": rows}, lambda p, e=None: asked.append(p) or "fixed",
                      lambda t: {"id": "?", "duration": 0, "v": 1}, lambda o, n: n.update(id=o["id"], duration=o["duration"]),
                      lambda m: None, lambda spec: next(looks), '"nodes"')
        self.assertEqual(len(asked), 3)
        self.assertTrue(all(("scene 2" in a or "scene 3" in a or "scene 5" in a) for a in asked), asked)


class InTheBuilds(unittest.TestCase):
    def test_both_builders_take_a_critic_and_call_it(self):
        import json as _j
        from core import reel_web as RW
        from core.motion import generate as G
        calls = []
        first = _j.dumps({"project": {"width": 1080, "height": 1920, "fps": 30},
                          "storyboard": [{"scene": i + 1, "seconds": 3, "job": "j", "caption": "", "subject": "s",
                                          "look": "l", "motion": "m"} for i in range(2)]})
        ask = lambda p, expect=None: "```json\n" + _j.dumps({"nodes": [{"id": "a", "type": "text", "content": "Hi"}]}) + "\n```"
        G.build_spec(first, ask, check=lambda s: [], critic=lambda spec: calls.append("motion") or [], skeleton=None)
        turn_one = '```json\n{"design": {"name": "n", "css": ""}, "storyboard": [{"scene": 1, "job": "a"}, {"scene": 2, "job": "b"}]}\n```'
        script = _j.dumps({"scenes": [{"role": "hook", "seconds": 3, "headline": "A"}, {"role": "endcard", "seconds": 3, "headline": "B"}]})
        scene = "```json\n" + _j.dumps({"seconds": 3, "cut": "cut", "css": "", "html": "<p>x</p>"}) + "\n```"
        RW.build_spec(turn_one, lambda p, expect=None: scene, script=script, critic=lambda spec: calls.append("studio") or [])
        self.assertEqual(calls, ["motion", "studio"])


if __name__ == "__main__":
    unittest.main()

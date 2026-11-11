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


if __name__ == "__main__":
    unittest.main()

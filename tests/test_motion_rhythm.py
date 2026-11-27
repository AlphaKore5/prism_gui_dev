"""The rhythm of a Motion film is measured, and a film that never rests (or never moves) is named."""
from __future__ import annotations

import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import rhythm  # noqa: E402


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _slide(nid, at, dur, frm=-300, to=0):
    return {"id": nid, "type": "shape_rect", "position": [540, 960], "width": 500, "height": 140, "fill": "#111111",
            "animation": {"enter": {"time": at, "duration": dur, "tweens": [
                {"channel": "x", "from": frm, "to": to, "easing": "none"}]}}}


def _spec(nodes, seconds=8):
    return {"project": {"duration": seconds, "fps": 30, "width": 540, "height": 960, "background": "#FAF9F6", "look": "paper"},
            "scenes": [{"id": "a", "duration": seconds, "nodes": nodes}]}


class Faults(unittest.TestCase):
    def test_no_profile_no_faults(self):
        self.assertEqual(rhythm.faults(None), [])
        self.assertEqual(rhythm.faults({"seconds": 2.0, "static_pct": 0}), [])

    def _p(self, **kw):
        p = {"seconds": 14.0, "static_pct": 30.0, "mean_motion": 2.0, "per_second": [1.0] * 14, "holds": [1.9, 1.7],
             "longest_hold": 1.9, "holds_ge_1s": 2, "top10_share": 38.0, "luminance": [236.0, 250.0]}
        p.update(kw)
        return p

    def test_a_film_like_the_reference_has_nothing_to_fix(self):
        self.assertEqual(rhythm.faults(self._p()), [])

    def test_a_film_that_never_rests_is_named_with_what_to_do(self):
        f = rhythm.faults(self._p(static_pct=5.0, longest_hold=0.7, holds=[0.7], holds_ge_1s=0))
        self.assertTrue(any("never rests" in x and "5%" in x for x in f), f)

    def test_a_film_that_never_moves_names_the_quiet_seconds(self):
        f = rhythm.faults(self._p(static_pct=71.0, per_second=[8, 3, 6, 0.05, 0.03, 0.1, 0.05, 0.4, 0.1, 0.2, 0.1, 0.2, 0.1, 0.1]))
        self.assertTrue(any("mostly still" in x and "stretch is seconds 3-14" in x for x in f), f)

    def test_evenly_spread_motion_asks_for_a_payoff(self):
        f = rhythm.faults(self._p(top10_share=12.0))
        self.assertTrue(any("spread evenly" in x for x in f), f)


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class Probe(unittest.TestCase):
    def test_a_slide_then_a_long_hold_is_mostly_still_with_one_burst(self):
        p = rhythm.probe(_spec([_slide("s", 0.5, 1.5)], seconds=8))
        self.assertGreater(p["static_pct"], 60)
        self.assertGreaterEqual(p["holds_ge_1s"], 1)
        self.assertGreater(p["longest_hold"], 4.0)
        self.assertGreater(p["top10_share"], 30)
        self.assertGreater(p["luminance"][0], 200, "a paper page is bright")

    def test_something_always_moving_never_rests(self):
        node = {"id": "w", "type": "shape_rect", "position": [270, 480], "width": 300, "height": 200, "fill": "#111111",
                "animation": {"secondary_motion": {"property": "x", "freq": 0.6, "amount": 160}}}
        p = rhythm.probe(_spec([node], seconds=8))
        self.assertLess(p["static_pct"], 20)
        self.assertTrue(any("never rests" in f for f in rhythm.faults(p)), p)



class ProbeVideo(unittest.TestCase):
    """The same rhythm numbers, from a finished video file — Studio, Reel, anything."""

    def _write(self, path, frames, fps=10, size=(96, 160)):
        import subprocess
        from core import ffmpeg
        ff = ffmpeg.locate()
        p = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{size[0]}x{size[1]}",
                              "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", path], stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(f.astype("uint8").tobytes())
        p.stdin.close()
        p.wait()

    def test_a_film_that_holds_then_moves_then_holds_is_measured_as_such(self):
        import numpy as np
        import tempfile
        w, h = 96, 160
        still = np.full((h, w), 240.0)
        frames = [still] * 40                                           # a 4 s hold
        for i in range(20):                                             # 2 s of a bar sweeping across
            f = still.copy(); f[:, (i * 4) % w:(i * 4) % w + 20] = 20.0
            frames.append(f)
        frames += [still] * 40                                          # another 4 s hold
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.mp4")
            self._write(path, frames)
            p = rhythm.probe_video(path)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p["seconds"], 9.9, delta=0.3)
        self.assertGreater(p["static_pct"], 70)
        self.assertGreaterEqual(p["holds_ge_1s"], 2)
        self.assertGreater(p["longest_hold"], 3.0)
        self.assertGreater(p["top10_share"], 30, "all the motion is in one burst")
        self.assertGreater(p["luminance"][0], 150)

    def test_a_missing_or_unreadable_file_is_none_not_an_error(self):
        self.assertIsNone(rhythm.probe_video("/nonexistent/film.mp4"))
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4") as t:
            t.write(b"not a video")
            t.flush()
            self.assertIsNone(rhythm.probe_video(t.name))

    def test_a_spec_probe_and_a_video_probe_share_one_set_of_maths(self):
        import numpy as np
        a = rhythm.profile_from_frames([np.full((20, 20), 200.0)] * 30, fps=10)
        self.assertEqual(a["static_pct"], 100.0)
        self.assertEqual(a["holds_ge_1s"], 1)


class Repair(unittest.TestCase):
    """The film-level pass: which scenes go back, and when a fix counts."""

    def _p(self, still, per_second):
        return {"seconds": float(len(per_second)), "static_pct": still, "per_second": per_second,
                "longest_hold": 0.3, "holds_ge_1s": 0, "top10_share": 25.0, "luminance": [200.0, 240.0], "holds": []}

    def test_kind_names_both_failures_and_none_inside_the_band(self):
        self.assertEqual(rhythm.kind(self._p(8, [1] * 12)), "never_rests")
        self.assertEqual(rhythm.kind(self._p(68, [1] * 12)), "mostly_still")
        self.assertIsNone(rhythm.kind(self._p(30, [1] * 12)))
        self.assertIsNone(rhythm.kind(None))
        self.assertIsNone(rhythm.kind(self._p(8, [1, 1])), "too short to judge")

    def test_a_scene_activity_is_the_series_averaged_over_its_own_seconds(self):
        p = self._p(8, [4, 4, 1, 1, 1, 1, 0, 0])
        self.assertEqual(rhythm.scene_activity(p, [2, 4, 2]), [4.0, 1.0, 0.0])

    def test_never_rests_sends_the_busiest_back_but_never_the_payoff(self):
        p = self._p(8, [5, 5, 1, 1, 1, 1, 9, 9])
        self.assertEqual(rhythm.targets(p, [2, 4, 2], "never_rests"), [0, 1])

    def test_mostly_still_sends_the_quietest_back_but_never_the_opening(self):
        p = self._p(70, [0, 0, 1, 1, 1, 1, 0.1, 0.1])
        self.assertEqual(rhythm.targets(p, [2, 4, 2], "mostly_still"), [1, 2])

    def test_a_fix_must_land_clearly_nearer_the_band(self):
        before, near, same = self._p(8, [1] * 12), self._p(13, [1] * 12), self._p(9, [1] * 12)
        self.assertTrue(rhythm.better(before, near))
        self.assertFalse(rhythm.better(before, same), "one point is noise")
        self.assertFalse(rhythm.better(before, None))
        self.assertTrue(rhythm.better(self._p(70, [1] * 12), self._p(50, [1] * 12)))

    def test_the_repair_text_carries_the_measured_numbers_and_the_cure(self):
        t = rhythm.repair_text(2, "never_rests", self._p(8, [1] * 12), 4.2)
        self.assertIn("8%", t); self.assertIn("Scene 2", t); self.assertIn("NOTHING moves", t)
        t = rhythm.repair_text(3, "mostly_still", self._p(68, [1] * 12), 0.1)
        self.assertIn("68%", t); self.assertIn("camera", t)


class RepairInTheBuild(unittest.TestCase):
    """build_spec sends a scene back when the film never rests, keeps the fix only when it helps."""

    def _run(self, profiles):
        import json
        from core.motion import generate
        first = json.dumps({"project": {"width": 1080, "height": 1920, "fps": 30},
                            "storyboard": [{"scene": i + 1, "seconds": 3, "job": "j", "caption": "", "subject": "s",
                                            "look": "l", "motion": "m"} for i in range(3)]})
        asked = []

        def ask(prompt, expect=None):
            asked.append(prompt)
            return "```json\n" + json.dumps({"nodes": [{"id": "a", "type": "text", "content": "Hi", "position": [540, 900]}]}) + "\n```"

        calls = iter(profiles)
        spec = generate.build_spec(first, ask, check=lambda s: [], measure=lambda s: next(calls), skeleton=None)
        return spec, asked

    def _p(self, still):
        return {"seconds": 9.0, "static_pct": still, "per_second": [3.0] * 9, "longest_hold": 0.3,
                "holds_ge_1s": 0, "top10_share": 25.0, "luminance": [200.0, 240.0], "holds": []}

    def test_a_film_that_never_rests_is_sent_back_and_a_real_fix_is_kept(self):
        spec, asked = self._run([self._p(5), self._p(30)])
        rhythm_asks = [a for a in asked if "finished film was measured" in a]
        self.assertEqual(len(rhythm_asks), 1, "fixed on the first scene, band reached, so it stops")
        self.assertIn("5%", rhythm_asks[0])

    def test_a_fix_that_does_not_help_is_not_kept_and_the_pass_tries_the_next_scene(self):
        spec, asked = self._run([self._p(5), self._p(5.5), self._p(5.5)])
        self.assertEqual(len([a for a in asked if "finished film was measured" in a]), 2)

    def test_a_film_inside_the_band_is_left_alone(self):
        spec, asked = self._run([self._p(30)])
        self.assertEqual([a for a in asked if "finished film was measured" in a], [])

    def test_a_measure_that_fails_never_costs_the_film(self):
        import json
        from core.motion import generate
        first = json.dumps({"project": {"width": 1080, "height": 1920, "fps": 30},
                            "storyboard": [{"scene": i + 1, "seconds": 3, "job": "j", "caption": "", "subject": "s",
                                            "look": "l", "motion": "m"} for i in range(2)]})
        ask = lambda p, expect=None: "```json\n" + json.dumps({"nodes": [{"id": "a", "type": "text", "content": "Hi"}]}) + "\n```"

        def boom(spec):
            raise RuntimeError("no browser")

        spec = generate.build_spec(first, ask, check=lambda s: [], measure=boom, skeleton=None)
        self.assertEqual(len(spec["scenes"]), 2)


if __name__ == "__main__":
    unittest.main()

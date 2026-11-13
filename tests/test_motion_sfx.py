"""Sound generated from the timeline: cues read from the spec, synthesised, muxed."""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import numpy as np  # noqa: E402

from core.motion import sfx  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402


def _spec(scenes, camera=None, sound="ui", seconds=None):
    spec = {"project": {"duration": seconds or 3 * len(scenes), "fps": 30, "width": 540, "height": 960,
                        "background": "#FAF9F6", "look": "paper", "sound": sound},
            "scenes": [{"id": f"s{i}", "duration": 3, "nodes": n} for i, n in enumerate(scenes)]}
    if camera:
        spec["camera"] = {"tracks": camera}
    return resolve_motion_spec(validate_motion_spec(spec))


TYPED = {"id": "t", "type": "text", "content": "Hi there", "position": [270, 400], "font_size": 40,
         "type_on": True, "type_rate": 10, "reveal_start": 1.0}


class Cues(unittest.TestCase):
    def test_a_tick_per_typed_character_at_the_rate_and_none_for_spaces(self):
        r = _spec([[TYPED]])
        ticks = [c["t"] for c in sfx.cues(r) if c["kind"] == "tick"]
        self.assertEqual(len(ticks), 7)                       # "Hi there" without its space
        self.assertAlmostEqual(ticks[0], 1.0, places=3)
        self.assertAlmostEqual(ticks[1], 1.1, places=3)
        self.assertAlmostEqual(ticks[2], 1.3, places=3)       # index 3: the space at index 2 is skipped

    def test_the_second_scene_is_shifted_and_gets_a_soft_whoosh_at_its_start(self):
        r = _spec([[{"id": "a", "type": "text", "content": "x", "position": [1, 1]}], [dict(TYPED, id="u")]])
        cs = sfx.cues(r)
        self.assertTrue(any(c["kind"] == "whoosh_soft" and abs(c["t"] - 3.0) < 1e-6 for c in cs))
        self.assertAlmostEqual(min(c["t"] for c in cs if c["kind"] == "tick"), 4.0, places=3)

    def test_clicks_for_a_cursor_landing_and_a_send_and_a_chime_for_done(self):
        r = _spec([[{"id": "cur", "type": "cursor", "position": [10, 10], "label": "A",
                     "path": [{"at": 0.5, "to": [200, 300], "duration": 0.8, "click": True}]},
                    {"id": "in", "type": "ui_input", "position": [270, 500], "text": "ok", "reveal_start": 0.2,
                     "send_at": 2.2},
                    {"id": "done", "type": "ui_pill", "position": [270, 700], "label": "Ready", "check": True,
                     "animation": {"enter": {"time": 2.4, "duration": 0.3, "tweens": [
                         {"channel": "opacity", "from": 0, "to": 1}]}}}]])
        by = {}
        for c in sfx.cues(r):
            by.setdefault(c["kind"], []).append(c["t"])
        self.assertIn(1.3, [round(t, 3) for t in by["click"]])     # 0.5 + 0.8
        self.assertIn(2.2, [round(t, 3) for t in by["click"]])
        self.assertEqual([round(t, 3) for t in by["chime"]], [2.4])

    def test_a_node_marked_hit_gets_a_low_hit_as_it_enters(self):
        r = _spec([[{"id": "d", "type": "ui_pill", "position": [270, 700], "label": "Ready", "check": True, "hit": True,
                     "animation": {"enter": {"time": 1.6, "duration": 0.3, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]}}}]])
        hits = [c["t"] for c in sfx.cues(r) if c["kind"] == "hit"]
        self.assertEqual([round(t, 3) for t in hits], [1.6])
        x = sfx.synthesize([{"t": 1.6, "kind": "hit", "gain": 1.0}], 3.0, bed=False)
        self.assertGreater(float(np.abs(x[int(1.6 * sfx.SR):int(1.633 * sfx.SR)]).max()), 0.05)
        self.assertLess(float(np.abs(x[:int(1.55 * sfx.SR)]).max()), 1e-6)

    def test_a_camera_move_whooshes_and_a_still_camera_does_not(self):
        moving = _spec([[TYPED]], camera=[{"time": 0, "position": [270, 480], "zoom": 1.0},
                                          {"time": 1.0, "position": [270, 480], "zoom": 2.0, "duration": 1.0}])
        self.assertTrue(any(c["kind"] == "whoosh" and abs(c["t"] - 1.0) < 1e-6 for c in sfx.cues(moving)))
        still = _spec([[TYPED]], camera=[{"time": 0, "position": [270, 480], "zoom": 1.0},
                                         {"time": 1.0, "position": [270, 480], "zoom": 1.02, "duration": 1.0}])
        self.assertFalse(any(c["kind"] == "whoosh" for c in sfx.cues(still)))

    def test_a_film_with_nothing_to_play_makes_no_file(self):
        r = _spec([[{"id": "a", "type": "shape_rect", "position": [1, 1], "width": 10, "height": 10}]])
        self.assertEqual(sfx.cues(r), [])
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(sfx.build(r, os.path.join(d, "x.wav")))


class Synthesis(unittest.TestCase):
    def test_the_same_spec_makes_the_same_bytes(self):
        r = _spec([[TYPED]])
        a = sfx.synthesize(sfx.cues(r), 3.0)
        b = sfx.synthesize(sfx.cues(r), 3.0)
        self.assertTrue(np.array_equal(a, b))

    def test_levels_are_safe_and_a_bed_is_quiet(self):
        r = _spec([[TYPED]])
        x = sfx.synthesize(sfx.cues(r), 3.0)
        self.assertLessEqual(float(np.abs(x).max()), 0.9)
        bed_only = sfx.synthesize([], 3.0)
        self.assertLess(float(np.abs(bed_only).max()), 0.05)
        self.assertGreater(float(np.abs(bed_only).max()), 0.001)

    def test_every_cue_starts_within_a_frame_of_its_time(self):
        cue_list = [{"t": 0.5, "kind": "tick", "gain": 1.0}, {"t": 1.2, "kind": "click", "gain": 1.0},
                    {"t": 2.0, "kind": "pop", "gain": 1.0}, {"t": 2.6, "kind": "chime", "gain": 1.0}]
        x = sfx.synthesize(cue_list, 4.0, bed=False)
        win = int(0.005 * sfx.SR)
        env = np.sqrt(np.convolve(x * x, np.ones(win) / win, mode="same"))
        for c in cue_list:
            s = int(c["t"] * sfx.SR)
            before = env[max(0, s - int(0.06 * sfx.SR)):s - int(0.01 * sfx.SR)].max()
            after = env[s:s + int(0.033 * sfx.SR)].max()
            self.assertLess(before, 1e-4, c)
            self.assertGreater(after, 0.01, f"{c}: no onset within 33 ms (one frame at 30 fps)")

    def test_the_wav_is_valid(self):
        import wave
        r = _spec([[TYPED]])
        with tempfile.TemporaryDirectory() as d:
            p = sfx.build(r, os.path.join(d, "s.wav"))
            with wave.open(p) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate()), (1, 2, 44100))
                self.assertGreater(w.getnframes() / 44100, 3.0)


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class RenderedFilmHasTheSound(unittest.TestCase):
    def _probe(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name:format=duration",
                              "-of", "json", path], capture_output=True, text=True).stdout
        j = json.loads(out)
        return [s["codec_type"] for s in j["streams"]], float(j["format"]["duration"])

    def test_sound_ui_adds_an_audio_track_the_length_of_the_film_and_none_means_silent(self):
        # core.motion exports render() the function; the module is reached by name.
        render_fn = importlib.import_module("core.motion.render").render
        spec = _spec([[TYPED]], seconds=3)
        spec["project"].update(width=320, height=320)
        spec["scenes"][0]["nodes"][0]["position"] = [160, 160]
        with tempfile.TemporaryDirectory() as d:
            with_sound = os.path.join(d, "a.mp4")
            render_fn(json.loads(json.dumps(spec)), with_sound)
            kinds, dur = self._probe(with_sound)
            self.assertIn("audio", kinds)
            self.assertAlmostEqual(dur, 3.0, delta=0.2)
            silent = json.loads(json.dumps(spec)); silent["project"]["sound"] = "none"
            plain = os.path.join(d, "b.mp4")
            render_fn(silent, plain)
            self.assertNotIn("audio", self._probe(plain)[0])


if __name__ == "__main__":
    unittest.main()

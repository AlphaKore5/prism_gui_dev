"""Phase 2 of the inspo benchmark: material and camera primitives.

The authored fixture (core.motion.fixtures) is the reference; the model
is only shown a primitive in the catalogue once the fixture proves it.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import camera, continuity  # noqa: E402
from core.motion import inspect as motion_inspect  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402
from core.motion.generate import _NODE_CATALOGUE, parse_scene, scene_instructions  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


def _one_scene(nodes, width=1080, height=1920, **scene_extra):
    return {"project": {"duration": 2, "fps": 30, "width": width, "height": height},
            "scenes": [{"id": "one", "duration": 2, "nodes": nodes, **scene_extra}]}


class MaterialSchemaTests(unittest.TestCase):
    def test_material_props_are_clamped_not_rejected(self):
        spec = _one_scene([
            {"id": "g", "type": "glass_panel", "position": [540, 900],
             "blur": 90, "transmission": 1.4, "border_light": -1,
             "specular": "lots", "inner_shadow": 0.3},
            {"id": "l", "type": "light_field", "position": [540, 900],
             "intensity": 3, "spread": 0.01, "drift": 999},
            {"id": "d", "type": "depth_layer", "depth": 9, "children": []},
            {"id": "d2", "type": "depth_layer", "children": []},
        ])
        nodes = validate_motion_spec(spec)["scenes"][0]["nodes"]
        g, l, d, d2 = nodes
        self.assertEqual(g["blur"], 40.0)
        self.assertEqual(g["transmission"], 1.0)
        self.assertEqual(g["border_light"], 0.0)
        self.assertNotIn("specular", g)
        self.assertEqual(g["inner_shadow"], 0.3)
        self.assertEqual((l["intensity"], l["spread"], l["drift"]), (1.0, 0.2, 200.0))
        self.assertEqual(d["depth"], 2.5)
        self.assertEqual(d2["depth"], 1.0)  # the default the runtime also uses

    def test_shot_is_normalized_or_dropped(self):
        spec = {"project": {"duration": 6, "fps": 30}, "scenes": [
            {"id": "a", "duration": 2, "shot": "push", "nodes": []},
            # 99, not 9: the cap was raised from 3 to 12 (a product film pushes
            # ~8x into one word), so the value must still be out of range.
            {"id": "b", "duration": 2, "shot": {"intent": "Macro ", "target": "hero",
                                                 "zoom": 99, "easing": "nope"}, "nodes": []},
            {"id": "c", "duration": 2, "shot": {"intent": "dolly"}, "nodes": []},
            {"id": "d", "duration": 2, "shot": {"intent": "orbit", "target": [10, "x"],
                                                 "easing": "sine.inOut"}, "nodes": []},
        ]}
        scenes = validate_motion_spec(spec)["scenes"]
        self.assertEqual(scenes[0]["shot"], {"intent": "push"})
        self.assertEqual(scenes[1]["shot"], {"intent": "macro", "target": "hero",
                                             "zoom": camera.ZOOM_MAX})
        self.assertNotIn("shot", scenes[2])
        self.assertEqual(scenes[3]["shot"], {"intent": "orbit", "target": [10.0, 0.0],
                                             "easing": "sine.inOut"})


class CameraCurveTests(unittest.TestCase):
    def test_shots_compile_to_one_continuous_curve(self):
        spec = validate_motion_spec(json.loads(json.dumps(materials_fixture())))
        resolved = resolve_motion_spec(spec)
        tracks = resolved["camera"]["tracks"]
        self.assertEqual([t["_shot"] for t in tracks],
                         ["open", "reveal", "push", "resolve"])
        self.assertTrue(camera.is_continuous(tracks))
        # the opening set is instant, at t=0, at the centre
        self.assertEqual((tracks[0]["time"], tracks[0]["duration"]), (0.0, 0.0))
        self.assertEqual(tracks[0]["position"], [540.0, 960.0])
        # each later track starts at its scene's start and fits inside it
        for track, scene in zip(tracks[1:], resolved["scenes"]):
            self.assertEqual(track["time"], scene["start"])
            self.assertLessEqual(track["duration"], scene["duration"] + 1e-6)
        # node targets resolve to world positions (the panel inside its
        # depth layer), push multiplies zoom, resolve returns to centre/1.0
        panel = resolved["scenes"][1]["nodes"][1]["children"][0]
        self.assertEqual(tracks[2]["position"], [float(panel["position"][0]),
                                                 float(panel["position"][1])])
        self.assertAlmostEqual(tracks[2]["zoom"], 1.18)
        self.assertEqual(tracks[3]["position"], [540.0, 960.0])
        self.assertEqual((tracks[3]["zoom"], tracks[3]["rotation"]), (1.0, 0.0))

    def test_push_and_pull_are_relative_to_where_the_camera_is(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 2, "shot": {"intent": "push"}},
            {"id": "b", "start": 2.0, "duration": 2, "shot": {"intent": "push"}},
            {"id": "c", "start": 4.0, "duration": 2, "shot": {"intent": "pull"}},
            {"id": "d", "start": 6.0, "duration": 2, "shot": {"intent": "hold"}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        zooms = [t["zoom"] for t in tracks]
        self.assertAlmostEqual(zooms[1], 1.15, places=3)
        self.assertAlmostEqual(zooms[2], 1.15 * 1.15, places=3)
        self.assertAlmostEqual(zooms[3], 1.15, places=3)
        self.assertEqual(zooms[4], zooms[3])  # hold keeps the state
        self.assertEqual(tracks[4]["easing"], "none")
        self.assertTrue(camera.is_continuous(tracks))

    def test_a_shot_may_name_how_long_its_move_takes(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 3, "shot": {"intent": "push", "target": [400, 500]}},
            {"id": "b", "start": 3.0, "duration": 4, "shot": {"intent": "reveal", "target": [540, 960],
                                                             "zoom": 1.0, "duration": 0.45}},
            {"id": "c", "start": 7.0, "duration": 2, "shot": {"intent": "hold", "duration": 99}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        self.assertEqual(tracks[1]["duration"], 3.0)          # a push spans its scene
        self.assertEqual(tracks[2]["duration"], 0.45)         # the reveal settles fast
        self.assertEqual(tracks[3]["duration"], 2.0)          # never longer than the scene
        self.assertEqual(camera.normalize_shot({"intent": "push", "duration": "x"}), {"intent": "push"})
        self.assertEqual(camera.normalize_shot({"intent": "push", "duration": 0})["duration"], 0.05)

    def test_orbit_alternates_and_parallax_drifts(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 2, "shot": {"intent": "orbit"}},
            {"id": "b", "start": 2.0, "duration": 2, "shot": {"intent": "orbit"}},
            {"id": "c", "start": 4.0, "duration": 2, "shot": {"intent": "parallax"}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        self.assertEqual(tracks[1]["rotation"], 3.0)
        self.assertEqual(tracks[2]["rotation"], 0.0)
        self.assertNotEqual(tracks[3]["position"][0], tracks[2]["position"][0])
        self.assertEqual(tracks[3]["zoom"], tracks[2]["zoom"])

    def test_an_authored_camera_is_kept_when_no_scene_names_a_shot(self):
        spec = validate_motion_spec({
            "project": {"duration": 2, "fps": 30},
            "camera": {"tracks": [{"time": 0, "position": [540, 960], "zoom": 1.2}]},
            "scenes": [{"id": "a", "duration": 2, "nodes": []}]})
        resolved = resolve_motion_spec(spec)
        self.assertEqual(resolved["camera"]["tracks"][0]["zoom"], 1.2)
        self.assertNotIn("_authored_tracks", resolved["camera"])
        self.assertIsNone(camera.compile_tracks(resolved["scenes"], 1080, 1920, {}))

    def test_an_authored_camera_seeds_the_opening_state_when_shots_exist(self):
        spec = validate_motion_spec({
            "project": {"duration": 2, "fps": 30},
            "camera": {"tracks": [{"time": 0, "position": [400, 800], "zoom": 1.3}]},
            "scenes": [{"id": "a", "duration": 2, "shot": "hold", "nodes": []}]})
        resolved = resolve_motion_spec(spec)
        tracks = resolved["camera"]["tracks"]
        self.assertEqual(tracks[0]["position"], [400.0, 800.0])
        self.assertEqual(tracks[0]["zoom"], 1.3)
        self.assertEqual(tracks[1]["zoom"], 1.3)
        self.assertEqual(len(resolved["camera"]["_authored_tracks"]), 1)

    def test_resolver_is_idempotent_with_shots(self):
        once = resolve_motion_spec(validate_motion_spec(json.loads(json.dumps(materials_fixture()))))
        again = resolve_motion_spec(json.loads(json.dumps(once)))
        self.assertEqual(json.dumps(once["camera"], sort_keys=True),
                         json.dumps(again["camera"], sort_keys=True))


class SafeAreaTests(unittest.TestCase):
    def test_vertical_frames_reserve_platform_bands(self):
        zone = camera.safe_area(1080, 1920)
        self.assertTrue(zone["vertical"])
        self.assertEqual((zone["top"], zone["bottom"]), (211, 1536))
        self.assertLess(zone["title"]["bottom"], zone["action"]["bottom"])
        wide = camera.safe_area(1920, 1080)
        self.assertFalse(wide["vertical"])

    def test_inspect_flags_text_under_platform_chrome_on_9_16_only(self):
        high = _one_scene([{"id": "h", "type": "text", "content": "Hello",
                            "position": [540, 60], "font_size": 48}])
        faults = motion_inspect.inspect(validate_motion_spec(high))
        self.assertTrue(any("top" in f and "platform" in f for f in faults), faults)
        low = _one_scene([{"id": "l", "type": "text", "content": "Hello",
                           "position": [540, 1880], "font_size": 48}])
        faults = motion_inspect.inspect(validate_motion_spec(low))
        self.assertTrue(any("bottom band" in f for f in faults), faults)
        fine = _one_scene([{"id": "f", "type": "text", "content": "Hello",
                            "position": [540, 900], "font_size": 48}])
        self.assertEqual(motion_inspect.inspect(validate_motion_spec(fine)), [])
        wide = _one_scene([{"id": "w", "type": "text", "content": "Hello",
                            "position": [960, 60], "font_size": 48}],
                          width=1920, height=1080)
        self.assertFalse(any("platform" in f for f in
                             motion_inspect.inspect(validate_motion_spec(wide))))

    def test_inspect_walks_into_depth_layers_and_panels(self):
        nested = _one_scene([{"id": "d", "type": "depth_layer", "depth": 1.4,
                              "position": [0, 0], "children": [
                                  {"id": "g", "type": "glass_panel", "position": [540, 200],
                                   "width": 600, "height": 300, "children": [
                                       {"id": "t", "type": "text", "content": "Hi",
                                        "position": [0, -100], "font_size": 48}]}]}])
        faults = motion_inspect.inspect(validate_motion_spec(nested))
        self.assertTrue(any('"t"' in f and "platform" in f for f in faults), faults)

    def test_light_fields_may_bleed_past_the_frame(self):
        spec = _one_scene([{"id": "lf", "type": "light_field", "position": [-400, -400],
                            "width": 1200, "height": 1200}])
        self.assertEqual(motion_inspect.inspect(validate_motion_spec(spec)), [])


class FixtureAndCatalogueTests(unittest.TestCase):
    def test_fixture_validates_compiles_and_passes_every_gate(self):
        spec = validate_motion_spec(json.loads(json.dumps(materials_fixture())))
        for scene in spec["scenes"]:
            self.assertEqual(motion_inspect.inspect(
                {"project": spec["project"], "scenes": [scene]}), [])
        rep = continuity.report(spec)
        self.assertEqual(rep["errors"], [])
        self.assertEqual(rep["warnings"], [])
        self.assertEqual(len(rep["bridges"]), 2)
        resolved = resolve_motion_spec(spec)
        self.assertEqual(resolved["_continuity_compiled"]["errors"], [])
        for scene in resolved["scenes"][1:]:
            self.assertEqual(scene["transition_in"], "morph")

    def test_fixture_scales_with_the_frame(self):
        small = materials_fixture(360, 640)
        panel = small["scenes"][0]["nodes"][1]["children"][0]
        self.assertLess(panel["width"], 360)
        self.assertEqual(validate_motion_spec(json.loads(json.dumps(small)))["project"]["width"], 360)

    def test_runtime_defines_the_primitives_and_applies_parallax(self):
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            prims = fh.read()
        for cls in ("class GlassPanelNode", "class LightFieldNode", "class DepthLayerNode"):
            self.assertIn(cls, prims)
        for mapping in ('type === "glass_panel"', 'type === "light_field"',
                        'type === "depth_layer"'):
            self.assertIn(mapping, prims)
        self.assertIn("backdropFilter", prims)
        self.assertIn("applyParallax(camera, w, h)", prims)
        with open(os.path.join(RUNTIME, "runtime.js"), encoding="utf-8") as fh:
            runtime = fh.read()
        self.assertIn("layer.applyParallax(this.camera, this.width, this.height)", runtime)
        self.assertIn("_collectDepthLayers", runtime)
        with open(os.path.join(RUNTIME, "transitions.js"), encoding="utf-8") as fh:
            self.assertIn("morph:", fh.read())

    def test_catalogue_and_scene_prompt_expose_materials_and_shots(self):
        for name in ("glass_panel", "light_field", "depth_layer", "contrast_guard"):
            self.assertIn(name, _NODE_CATALOGUE)
        for intent in camera.SHOT_INTENTS:
            self.assertIn(f"  {intent}", _NODE_CATALOGUE)
        prompt = scene_instructions(0, 2, {"job": "open", "seconds": 2},
                                    skeleton="cinematic_glass")
        self.assertIn('"shot": {"intent"', prompt)
        self.assertIn("safe area", prompt)

    def test_parse_scene_keeps_the_shot(self):
        got = parse_scene('```json\n{"shot": {"intent": "push", "target": "hero"}, '
                          '"transition_in": "morph", "nodes": [{"id": "hero", '
                          '"type": "shape_rect", "position": [1, 2]}]}\n```')
        self.assertEqual(got["shot"], {"intent": "push", "target": "hero"})
        self.assertEqual(got["transition_in"], "morph")
        self.assertEqual(len(got["nodes"]), 1)


class MaterialsAreTheWritersDefault(unittest.TestCase):
    """A model-written plan tended to build from full-frame rectangles and
    arrows (the first routed Alphakore run did). The catalogue, the scene
    rules, the storyboard turn and inspect() now all say the same thing."""

    def test_the_catalogue_and_rules_name_the_material_for_each_job(self):
        self.assertIn("WRONG primitive for a background or a card", _NODE_CATALOGUE)
        # The scene rules are stated once, in the storyboard turn (see
        # generate._rulebook); a scene prompt only names them.
        from core.motion.generate import storyboard_instructions
        board = storyboard_instructions("a product reveal", skeleton="cinematic_glass")
        self.assertIn("13. Build from the material primitives", board)
        self.assertIn("covering more than half the frame is", board)
        prompt = scene_instructions(0, 3, {"job": "open", "seconds": 2}, skeleton="cinematic_glass")
        self.assertIn("SCENE RULES", prompt)
        self.assertIn("name the material primitives that carry the scene", board)

    def test_inspect_sends_a_flat_full_frame_rect_back_under_the_doctrine(self):
        wash = {"id": "bg", "type": "shape_rect", "position": [540, 960], "width": 1080,
                "height": 1920, "fill": "#101020", "layer": "background",
                "animation": {"secondary_motion": {"property": "x", "freq": 0.1, "amount": 10}}}
        hero = {"id": "h", "type": "text", "content": "Hi", "position": [540, 900],
                "layer": "foreground", "animation": {
                    "enter": {"time": 0, "duration": 0.5, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]},
                    "exit": {"time": 1.2, "duration": 0.4, "tweens": [{"channel": "opacity", "from": 1, "to": 0}]}}}
        faults = motion_inspect.inspect(validate_motion_spec(_one_scene([wash, hero])))
        self.assertEqual(len(faults), 1, faults)
        self.assertIn('"bg" is a flat shape_rect', faults[0])
        self.assertIn("light_field", faults[0])
        # a card-sized flat rect points at glass_panel instead
        card = dict(wash, id="card", layer="midground", width=700, height=1000, fill="#FFFFFF")
        faults = motion_inspect.inspect(validate_motion_spec(_one_scene([wash, card, hero])))
        self.assertTrue(any('"card"' in f and "glass_panel" in f for f in faults), faults)

    def test_gradients_glass_bubbles_and_undoctrined_scenes_are_left_alone(self):
        sky = {"id": "sky", "type": "shape_rect", "position": [540, 960], "width": 1400, "height": 2200,
               "fill": "linear-gradient(215deg, #a8c8ff 0%, #0f1d5c 100%)", "layer": "background",
               "animation": {"secondary_motion": {"property": "x", "freq": 0.1, "amount": 10}}}
        glass = {"id": "g", "type": "shape_rect", "position": [540, 960], "width": 900, "height": 1200,
                 "is_glass": True, "layer": "midground"}
        bubble = {"id": "b", "type": "shape_rect", "position": [470, 785], "width": 1260, "height": 236,
                  "fill": "#FFFFFF", "layer": "foreground",
                  "animation": {"secondary_motion": {"property": "y", "freq": 0.2, "amount": 4},
                                "enter": {"time": 0, "duration": 0.5, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]}}}
        faults = motion_inspect.inspect(validate_motion_spec(_one_scene([sky, glass, bubble])))
        self.assertFalse(any("flat shape_rect" in f for f in faults), faults)
        plain = {"id": "bg", "type": "shape_rect", "position": [540, 960], "width": 1080, "height": 1920,
                 "fill": "#101020"}
        self.assertEqual(motion_inspect.inspect(validate_motion_spec(_one_scene([plain]))), [])
        # the authored recreation carries no flat wash
        from core.motion.fixtures import inspo_fixture
        spec = validate_motion_spec(json.loads(json.dumps(inspo_fixture())))
        for scene in spec["scenes"]:
            faults = motion_inspect.inspect({"project": spec["project"], "scenes": [scene]})
            self.assertFalse(any("flat shape_rect" in f for f in faults), (scene["id"], faults))


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class MaterialsRenderLane(unittest.TestCase):
    """The fixture through the real browser: the glass panel must be a
    visible surface (not the background, not opaque), the light field must
    lift the frame, and the headline on the panel must keep contrast."""

    def test_fixture_frames_show_glass_light_and_readable_copy(self):
        from PIL import Image, ImageStat
        from core import ffmpeg
        render_module = importlib.import_module("core.motion.render")
        spec = materials_fixture(360, 640, fps=12)
        with tempfile.TemporaryDirectory() as folder:
            mp4 = os.path.join(folder, "out.mp4")
            render_module.render(spec, mp4)
            frame = os.path.join(folder, "frame.png")
            subprocess.run([ffmpeg.locate(), "-y", "-loglevel", "error", "-ss", "2.0",
                            "-i", mp4, "-frames:v", "1", frame], check=True)
            img = Image.open(frame).convert("RGB")
            w, h = img.size
            corner = img.crop((0, h - 40, 40, h))
            panel = img.crop((int(w * 0.35), int(h * 0.42), int(w * 0.65), int(h * 0.50)))
            corner_mean = sum(ImageStat.Stat(corner).mean) / 3
            panel_mean = sum(ImageStat.Stat(panel).mean) / 3
            # the panel is a lit surface, brighter than the dark corner but
            # far from a white card
            self.assertGreater(panel_mean, corner_mean + 8, (panel_mean, corner_mean))
            self.assertLess(panel_mean, 200, panel_mean)
            # the headline area has real contrast (bright ink on the panel)
            head = img.crop((int(w * 0.25), int(h * 0.36), int(w * 0.75), int(h * 0.44)))
            self.assertGreater(head.convert("L").getextrema()[1], 180)


if __name__ == "__main__":
    unittest.main()


class WritersNearMissesAreMapped(unittest.TestCase):
    """The Alphakore run (10 Sep 2026) went blank for its last three scenes
    because the writer drifted to x/y, text, source, top-level enter/exit,
    from/to dicts and a shape_group of parts, and the tolerant schema
    dropped every one of them. Now they map to what the runtime reads."""

    def test_aliases_become_the_runtime_keys(self):
        from core.motion.schema import normalize_aliases
        spec = _one_scene([
            {"id": "logo", "type": "image", "source": "asset:logo", "x": 540, "y": 900,
             "width": 700, "height": 418, "layer": "foreground",
             "enter": {"at": 1.05, "duration": 1.15, "ease": "power2.out",
                       "from": {"scale": 0.96, "opacity": 0}, "to": {"scale": 1, "opacity": 1}}},
            {"id": "word", "type": "text", "text": "ALPHAKORE", "x": 540, "y": 1090, "font_size": 80},
            {"id": "line", "type": "shape_arrow", "from": [120, 1060], "to": [960, 1060], "stroke": "#D8FF3E"},
            {"id": "dot", "type": "orb", "position": {"x": 790, "y": 590}, "radius": 16,
             "glow": "rgba(140,120,255,0.9)", "ring": 40},
            {"id": "geom", "type": "shape_group", "stroke": "#fff", "parts": [
                {"type": "shape_arrow", "from": [300, 720], "to": [540, 480]},
                {"type": "shape_arrow", "from": [540, 480], "to": [780, 720]}]},
        ])
        nodes = validate_motion_spec(spec)["scenes"][0]["nodes"]
        logo, word, line, dot, geom = nodes
        self.assertEqual((logo["src"], logo["position"]), ("asset:logo", [540, 900]))
        self.assertNotIn("source", logo)
        enter = logo["animation"]["enter"]
        self.assertEqual(enter["time"], 1.05)
        self.assertEqual({t["channel"]: (t["from"], t["to"]) for t in enter["tweens"]},
                         {"scale": (0.96, 1.0), "opacity": (0.0, 1.0)})
        self.assertEqual(enter["tweens"][0]["easing"], "power2.out")
        self.assertEqual((word["content"], word["position"]), ("ALPHAKORE", [540, 1090]))
        esc = validate_motion_spec(_one_scene([{"id": "u", "type": "text", "position": [540, 900],
                                                "content": "Visit www\\.alphakore\\.com \\- now"}]))
        self.assertEqual(esc["scenes"][0]["nodes"][0]["content"], "Visit www.alphakore.com - now")
        self.assertEqual(line["color"], "#D8FF3E")
        self.assertEqual((dot["position"], dot["glow_color"], dot["ring_radius"]),
                         ([790, 590], "rgba(140,120,255,0.9)", 40))
        self.assertEqual(geom["type"], "group")
        self.assertEqual([c["type"] for c in geom["children"]], ["shape_arrow", "shape_arrow"])
        self.assertEqual(geom["children"][0]["stroke"], "#fff")
        self.assertTrue(all("_no_position" not in n for n in (logo, word, dot)))
        self.assertTrue(line.get("_no_position") is None)  # an arrow has from/to

    def test_inspect_names_nodes_that_render_nothing(self):
        spec = _one_scene([
            {"id": "t", "type": "text", "position": [540, 900]},
            {"id": "i", "type": "image", "position": [540, 700], "width": 300, "height": 300},
            {"id": "r", "type": "shape_rect", "width": 200, "height": 100, "fill": "#fff"},
        ])
        faults = motion_inspect.inspect(validate_motion_spec(spec))
        self.assertTrue(any('"t" is a text node with no "content"' in f for f in faults), faults)
        self.assertTrue(any('"i" is an image with no "src"' in f for f in faults), faults)
        self.assertTrue(any('"r" has no "position"' in f for f in faults), faults)
        field = _one_scene([{"id": "f", "type": "particle_field", "count": 10,
                             "phases": [{"at": 0, "layout": {"kind": "scatter"}}]}])
        self.assertFalse(any('no "position"' in f for f in motion_inspect.inspect(validate_motion_spec(field))))

    def test_a_camera_target_on_an_arrow_uses_its_midpoint_and_a_placeless_node_is_ignored(self):
        spec = validate_motion_spec({
            "project": {"duration": 4, "fps": 30}, "scenes": [
                {"id": "a", "duration": 2, "shot": {"intent": "push", "target": "border"},
                 "nodes": [{"id": "border", "type": "shape_arrow", "from": [-120, 1510], "to": [920, 260]}]},
                {"id": "b", "duration": 2, "shot": {"intent": "push", "target": "ghost"},
                 "nodes": [{"id": "ghost", "type": "shape_rect", "width": 10, "height": 10}]}]})
        tracks = resolve_motion_spec(spec)["camera"]["tracks"]
        self.assertEqual(tracks[1]["position"], [400.0, 885.0])
        self.assertEqual(tracks[2]["position"], [400.0, 885.0])  # held, not the corner


class AShotMayStartLate(unittest.TestCase):
    def test_delay_holds_the_previous_state_then_moves(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 3, "shot": {"intent": "push", "target": [540, 960], "zoom": 1.1}},
            {"id": "b", "start": 3.0, "duration": 3, "shot": {"intent": "parallax", "target": [540, 1480],
                                                             "delay": 1.9, "duration": 0.8}},
            {"id": "c", "start": 6.0, "duration": 1, "shot": {"intent": "hold", "delay": 5}},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        self.assertEqual((tracks[2]["time"], tracks[2]["duration"]), (4.9, 0.8))
        self.assertEqual(tracks[2]["position"], [540.0, 1480.0])
        self.assertLessEqual(tracks[3]["time"] + tracks[3]["duration"], 7.0 + 1e-6)
        self.assertTrue(camera.is_continuous(tracks))
        self.assertEqual(camera.normalize_shot({"intent": "push", "delay": -2})["delay"], 0.0)


class AFieldWrittenLooselyStillPlays(unittest.TestCase):
    """The second Alphakore run crashed the renderer on its first frame:
    a particle_field with phases ["ring", "scatter"] and a palette of
    "project.palette.ink". Both are now the intended values."""

    def test_string_phases_and_palette_references_are_normalised(self):
        spec = {"project": {"duration": 2, "fps": 30, "palette": {"ink": "#11131A", "accent2": "#8D7CFF"}},
                "scenes": [{"id": "a", "duration": 2, "nodes": [
                    {"id": "f", "type": "particle_field", "position": [0, 0], "count": 18,
                     "palette": ["project.palette.ink", "project.palette.accent2", "palette.nope", "#fff"],
                     "phases": ["ring", {"kind": "column", "x": 700}, {"layout": "hidden"}]},
                    {"id": "t", "type": "text", "content": "x", "position": [540, 900], "fill": "$accent2"},
                    {"id": "r", "type": "shape_rect", "position": [540, 900], "fill": "project.palette.missing"}]}]}
        nodes = validate_motion_spec(spec)["scenes"][0]["nodes"]
        field, text, rect = nodes
        self.assertEqual(field["palette"], ["#11131A", "#8D7CFF", "#fff"])
        self.assertEqual([ph["layout"]["kind"] for ph in field["phases"]], ["ring", "column", "hidden"])
        self.assertEqual(field["phases"][1]["layout"]["x"], 700)
        self.assertEqual([ph["at"] for ph in field["phases"]], [0.0, 1.2, 2.4])
        self.assertEqual(text["fill"], "#8D7CFF")
        self.assertNotIn("fill", rect)

    def test_the_runtime_guards_the_same_shapes(self):
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('if (typeof layout === "string") layout = { kind: layout };', src)
        self.assertIn("this.phases = raw.map(", src)

    def test_a_cinematic_scene_without_a_shot_is_sent_back(self):
        from core.motion.generate import shot_faults
        self.assertEqual(shot_faults({"nodes": []}, "brand_launch"), [])
        self.assertEqual(shot_faults({"nodes": [], "shot": {"intent": "push"}}, "cinematic_glass"), [])
        self.assertIn('names no "shot"', shot_faults({"nodes": []}, "cinematic_glass")[0])


class TheCameraNeverParksOnACorner(unittest.TestCase):
    """The second Alphakore run pushed onto a tree at x=790, then wrote no
    shot for five scenes; every caption after 3.5 s was clipped at the
    left edge. Two rules now: a scene without a shot settles back to the
    centre, and text the settled camera would clip is a continuity error."""

    def test_a_scene_without_a_shot_settles_to_centre(self):
        scenes = [
            {"id": "a", "start": 0.0, "duration": 3, "shot": {"intent": "push", "target": [790, 1010], "zoom": 1.15}},
            {"id": "b", "start": 3.0, "duration": 4},
            {"id": "c", "start": 7.0, "duration": 2},
        ]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {})
        self.assertEqual([t["_shot"] for t in tracks], ["open", "push", "settle"])
        self.assertEqual(tracks[2]["position"], [540.0, 960.0])
        self.assertEqual(tracks[2]["zoom"], 1.0)
        self.assertTrue(camera.is_continuous(tracks))
        state = camera.state_at(tracks, 6.9, 1080, 1920)
        self.assertEqual((state["x"], state["y"], state["zoom"]), (540.0, 960.0, 1.0))
        self.assertEqual(camera.visible_rect({"x": 790, "y": 1010, "zoom": 1.15}, 1080, 1920)[0],
                         790 - 1080 / 2.3)

    def test_text_the_settled_camera_clips_is_an_error(self):
        spec = validate_motion_spec({
            "project": {"duration": 7, "fps": 30}, "_motion_profile": "cinematic_glass", "scenes": [
                {"id": "a", "duration": 3, "shot": {"intent": "push", "target": "tree", "zoom": 1.15}, "nodes": [
                    {"id": "tree", "type": "spline_tree", "hub": [790, 1010], "leaves": [[900, 500]],
                     "continuity_key": "k"},
                    {"id": "cap", "type": "text", "content": "Complexity slows progress.", "position": [200, 820],
                     "font_size": 62}]},
                {"id": "b", "duration": 4, "shot": {"intent": "hold"}, "nodes": [
                    {"id": "tree2", "type": "spline_tree", "hub": [790, 1010], "leaves": [[900, 500]],
                     "continuity_key": "k"},
                    {"id": "cap2", "type": "text", "content": "Turn complex workflows", "position": [200, 970],
                     "font_size": 58}]}]})
        rep = continuity.report(spec)
        clipped = [e for e in rep["errors"] if "falls outside it" in e["message"]]
        self.assertEqual(sorted(e["scene_index"] for e in clipped), [0, 1], rep["errors"])
        # the same text under a centred shot is fine
        for sc in spec["scenes"]:
            sc["shot"] = {"intent": "hold", "target": [540, 960], "zoom": 1.0}
        self.assertFalse(any("falls outside" in e["message"] for e in continuity.report(spec)["errors"]))


class EmptyPlaceholderFramesAreSentBack(unittest.TestCase):
    def test_an_empty_glass_panel_under_the_doctrine_is_a_fault(self):
        spec = _one_scene([
            {"id": "bg", "type": "light_field", "position": [540, 960], "layer": "background",
             "animation": {"secondary_motion": {"property": "x", "freq": 0.1, "amount": 10}}},
            {"id": "shot_01", "type": "glass_panel", "position": [540, 900], "width": 600, "height": 900,
             "layer": "midground"},
            {"id": "h", "type": "text", "content": "Hi", "position": [540, 500], "layer": "foreground",
             "animation": {"enter": {"time": 0, "duration": 0.4, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]},
                           "exit": {"time": 1.4, "duration": 0.4, "tweens": [{"channel": "opacity", "from": 1, "to": 0}]}}},
        ])
        faults = motion_inspect.inspect(validate_motion_spec(spec))
        self.assertTrue(any('"shot_01" is an empty glass_panel' in f for f in faults), faults)
        spec["scenes"][0]["nodes"][1]["children"] = [{"id": "c", "type": "text", "content": "copy", "position": [0, 0]}]
        self.assertFalse(any("empty glass_panel" in f for f in motion_inspect.inspect(validate_motion_spec(spec))))
        from core.motion.generate import storyboard_instructions
        board = storyboard_instructions("a product reveal", skeleton="cinematic_glass")
        self.assertIn("must not be drawn as an empty placeholder", board)


class InvisibleMaterialsAreSentBack(unittest.TestCase):
    """Run 3 of the Alphakore reel (10 Sep 2026) wrote 2 px particle tiles
    and light fields the colour of the background: fields and lights that
    render as nothing. Both are checkable facts about one node."""

    def test_dust_fields_and_black_lights_are_faults_under_the_doctrine(self):
        spec = _one_scene([
            {"id": "dust", "type": "particle_field", "count": 40, "size": 2, "layer": "midground",
             "phases": [{"at": 0, "layout": {"kind": "scatter"}}]},
            {"id": "dark", "type": "light_field", "position": [540, 960], "color": "#07091A", "layer": "background",
             "animation": {"secondary_motion": {"property": "x", "freq": 0.1, "amount": 10}}},
            {"id": "h", "type": "text", "content": "Hi", "position": [540, 900], "layer": "foreground",
             "animation": {"enter": {"time": 0, "duration": 0.4, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]},
                           "exit": {"time": 1.4, "duration": 0.4, "tweens": [{"channel": "opacity", "from": 1, "to": 0}]}}},
        ])
        faults = motion_inspect.inspect(validate_motion_spec(spec))
        self.assertTrue(any('"dust" is a particle_field with "size" 2' in f for f in faults), faults)
        self.assertTrue(any('"dark" is a light_field' in f and "nearly black" in f for f in faults), faults)
        spec["scenes"][0]["nodes"][0]["size"] = 30
        spec["scenes"][0]["nodes"][1]["color"] = "rgba(124,156,255,0.6)"
        faults = motion_inspect.inspect(validate_motion_spec(spec))
        self.assertFalse(any("dust" in f or "nearly black" in f for f in faults), faults)

    def test_a_missing_shot_is_not_a_fault_when_the_storyboard_authored_a_camera(self):
        from core.motion.generate import shot_faults
        self.assertEqual(shot_faults({"nodes": []}, "cinematic_glass", has_camera=True), [])
        self.assertTrue(shot_faults({"nodes": []}, "cinematic_glass", has_camera=False))


class SplitSlideTextHasASize(unittest.TestCase):
    """split_slide emptied the line and replaced it with two absolutely
    positioned halves, so the line had no size, the text box collapsed to
    0x0 and its own clipping hid the halves. Every split_slide caption in
    the third Alphakore run vanished. An invisible in-flow copy now keeps
    the line's size."""

    def test_the_mode_keeps_an_in_flow_copy(self):
        with open(os.path.join(RUNTIME, "primitives.js"), encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index('case "split_slide": {'):src.index('case "shimmer_sweep": {')]
        self.assertIn('ghost.style.visibility = "hidden"', block)
        self.assertIn("el.appendChild(ghost)", block)


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class SplitSlideRendersInTheBrowser(unittest.TestCase):
    def test_a_split_slide_caption_has_a_box_and_paints(self):
        import pathlib
        from playwright.sync_api import sync_playwright
        spec = validate_motion_spec(_one_scene([
            {"id": "cap", "type": "text", "content": "Turn complexity into control.", "position": [540, 960],
             "font_size": 60, "fill": "#FFFFFF", "mode": "split_slide"}], width=1080, height=1920))
        resolved = resolve_motion_spec(spec)
        index = pathlib.Path(RUNTIME, "index.html").resolve().as_uri()
        with sync_playwright() as pw:
            b = pw.chromium.launch(); page = b.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(index, wait_until="load"); page.wait_for_function("window.__ready")
            page.evaluate("s => window.__loadSpec(s)", resolved)
            page.evaluate("window.__seek(45)")
            rect = page.evaluate("""() => { const b = document.querySelector('[data-motion-id="cap"]').firstElementChild.getBoundingClientRect(); return [b.width, b.height]; }""")
            b.close()
        self.assertGreater(rect[0], 300, rect)
        self.assertGreater(rect[1], 40, rect)

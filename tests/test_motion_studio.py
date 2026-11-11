"""Phase 3 of the inspo benchmark: the Motion Studio editing surface.

What these defend, mirroring tests/test_reel_edit.py for Studio reels:

  · everything from the browser is sanitised (it is user input);
  · an edit is applied to the SPEC, then validated and resolved by the
    same Python the renderer runs — preview and export cannot differ;
  · the page carries the resolved spec, the saved edits, the safe area
    and the Studio layer; the local server answers /preview, /save,
    /render and /refine on loopback only;
  · the follow-up prompt is scoped to the selected scene, node and
    continuity thread, and a one-scene reply folds back into the spec;
  · in a real browser (render lane): the workspace mounts, threads are
    listed, a scene review point seeks, and a node can be selected.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
import urllib.error
import urllib.request

GUI = os.path.dirname(os.path.dirname(__file__))
ENGINE = os.path.join(GUI, "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import camera, continuity, studio  # noqa: E402
from core.motion.fixtures import materials_fixture  # noqa: E402
from core.motion.schema import MotionValidationError, validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _render_lane() -> bool:
    if not os.environ.get("PRISM_RUN_RENDER_TESTS"):
        return False
    return importlib.import_module("core.motion.render").is_available()[0]


def _spec() -> dict:
    return materials_fixture(1080, 1920, fps=30)


def _settle(ready, seconds: float = 5.0) -> bool:
    """True once `ready()` is truthy, polling briefly — the server's
    callbacks fire after the HTTP response, on the server thread."""
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return bool(ready())


def _post(url: str, path: str, body: dict, origin: str = "") -> tuple[int, dict]:
    req = urllib.request.Request(url + path.lstrip("/"), method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Origin": origin} if origin else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


class WhatTheBrowserSendsIsSanitised(unittest.TestCase):
    def test_a_good_edit_survives_bounded(self):
        got = studio.clean_edits([
            {"scene": 1, "node": "panel_1", "dx": 12.345, "dy": -9000, "scale": 99,
             "rotation": 15, "opacity": 3, "text": "x" * 500,
             "material": {"blur": 100, "transmission": 0.4, "bogus": 1}},
            {"scene": 0, "root": True, "seconds": 99, "shot": {"intent": "push", "zoom": 99},
             "handoff_easing": "power3.inOut"},
        ])
        node, scene = got
        self.assertEqual((node["dx"], node["dy"], node["scale"]), (12.35, -4000.0, 20.0))
        self.assertEqual((node["rotation"], node["opacity"]), (15.0, 1.0))
        self.assertEqual(len(node["text"]), 400)
        self.assertEqual(node["material"], {"blur": 40.0, "transmission": 0.4})
        self.assertEqual(scene["seconds"], 30.0)
        # Bounded by the camera's own cap (raised from 3 to 12; 99 stays out of range).
        self.assertEqual(scene["shot"]["zoom"], camera.ZOOM_MAX)
        self.assertEqual(scene["handoff_easing"], "power3.inOut")

    def test_junk_and_no_op_records_are_dropped_not_raised(self):
        got = studio.clean_edits([
            "nope", None, {"scene": "x", "node": "a", "dx": 5},
            {"scene": -1, "node": "a", "dx": 5},
            {"scene": 0, "node": "a"},                        # nothing changed
            {"scene": 0, "node": "a", "dx": 0, "scale": 1},   # explicit no-op
            {"scene": 0, "root": True, "handoff_easing": "nope"},
            {"scene": 0, "node": "a", "dx": 3}, {"scene": 0, "node": "a", "dx": 4},  # duplicate
        ])
        self.assertEqual(got, [{"scene": 0, "node": "a", "dx": 3.0}])
        self.assertEqual(studio.clean_edits("not a list"), [])


class EditsAreAppliedToTheSpec(unittest.TestCase):
    def test_pose_material_text_and_visibility(self):
        spec = _spec()
        out = studio.apply_edits(spec, [
            {"scene": 0, "node": "panel_0", "dx": 40, "dy": -20, "scale": 1.5,
             "rotation": 10, "opacity": 0.8, "material": {"blur": 30, "specular": 0.1}},
            {"scene": 0, "node": "panel_0_h", "text": "New headline"},
            {"scene": 0, "node": "pill_0", "hidden": True},
        ])
        panel = out["scenes"][0]["nodes"][1]["children"][0]
        original = spec["scenes"][0]["nodes"][1]["children"][0]
        self.assertEqual(panel["position"], [original["position"][0] + 40,
                                             original["position"][1] - 20])
        self.assertEqual(panel["scale"], [1.5, 1.5])
        self.assertEqual((panel["rotation"], panel["opacity"]), (10.0, 0.8))
        self.assertEqual((panel["blur"], panel["specular"]), (30.0, 0.1))
        self.assertEqual(panel["children"][0]["content"], "New headline")
        self.assertFalse(out["scenes"][0]["nodes"][2]["children"][0]["visible"])
        # the original is untouched and the copy carries no edits of its own
        self.assertNotIn("rotation", original)
        self.assertNotIn(studio.EDITS_KEY, out)

    def test_scene_length_shot_and_handoff_easing_reach_the_resolved_spec(self):
        spec = _spec()
        edits = [{"scene": 1, "root": True, "seconds": 4, "shot": {"intent": "macro", "target": "panel_1"},
                  "handoff_easing": "sine.inOut"}]
        out = studio.apply_edits(spec, edits)
        self.assertEqual(out["scenes"][1]["duration"], 4.0)
        self.assertEqual(out["project"]["duration"], 2.5 + 4 + 2.5)
        resolved = studio.resolved_for(spec, edits)
        self.assertEqual(resolved["camera"]["tracks"][2]["_shot"], "macro")
        self.assertEqual(resolved["scenes"][2]["start"], 6.5)
        bridge = [b for b in resolved["_continuity_compiled"]["bridges"] if b["scene_index"] == 1][0]
        self.assertEqual(bridge["easing"], "sine.inOut")
        exit_ = resolved["scenes"][0]["nodes"][1]["children"][0]["animation"]["exit"]
        self.assertEqual({t["easing"] for t in exit_["tweens"]}, {"sine.inOut"})
        self.assertEqual(continuity.bridge_easing({"handoff_easing": "bogus"}), continuity.BRIDGE_EASING)

    def test_no_edits_means_the_same_spec(self):
        spec = _spec()
        self.assertEqual(studio.apply_edits(spec, [])["scenes"], spec["scenes"])
        self.assertEqual(studio.apply_edits(spec, None)["scenes"], spec["scenes"])

    def test_render_applies_the_saved_edits_before_the_continuity_gate(self):
        """An edit that flings the carried subject across the frame in a
        short cut must be refused by render() — which proves the saved
        edits are applied before the gate, not after the film."""
        render_module = importlib.import_module("core.motion.render")
        spec = _spec()
        spec["scenes"][0]["duration"] = 0.6
        spec["scenes"][1]["duration"] = 0.6
        spec["_strict_continuity"] = True
        spec[studio.EDITS_KEY] = [{"scene": 1, "node": "panel_1", "dx": 3000, "dy": 3000}]
        with self.assertRaises(MotionValidationError) as ctx:
            render_module.render(spec, "/nonexistent/out.mp4")
        self.assertIn("continuity broken", str(ctx.exception))

    def test_review_points_and_preview_payload(self):
        pts = studio.review_points({"start": 2.0, "duration": 2.5})
        self.assertEqual(pts, {"start": 2.05, "mid": 3.25, "settled": 4.0, "exit": 4.45})
        payload = studio.preview_payload(_spec(), [])
        self.assertEqual(set(payload), {"resolved", "review", "errors", "warnings", "beats"})
        self.assertEqual(len(payload["review"]), 3)
        self.assertEqual(payload["errors"], [])


class ThePage(unittest.TestCase):
    def test_it_carries_spec_edits_safe_area_and_the_studio_layer(self):
        spec = _spec()
        spec[studio.EDITS_KEY] = [{"scene": 0, "node": "panel_0", "dx": 5}]
        page = studio.editable_html(spec)
        for marker in ("window.__MOTION_SOURCE__", "window.__MOTION_PREVIEW__",
                       "window.__MOTION_EDITS__", "window.__MOTION_SAFE__",
                       "window.__MOTION_SHOTS__", '"dx": 5', '<script src="runtime.js">'):
            self.assertIn(marker, page, marker)
        for name in ("studio.js", "studio.css"):
            with open(os.path.join(RUNTIME, name), encoding="utf-8") as fh:
                self.assertIn(fh.read(), page, name)
        with open(os.path.join(RUNTIME, "runtime.js"), encoding="utf-8") as fh:
            self.assertIn("host.dataset.motionId = this.id", fh.read())


class TheLocalServer(unittest.TestCase):
    def setUp(self):
        self.saved, self.rendered, self.refined = [], [], []
        self.url, self.stop = studio.serve(
            _spec(), on_save=self.saved.append, on_render=self.rendered.append,
            on_refine=lambda change, ctx: self.refined.append((change, ctx)))

    def tearDown(self):
        self.stop()
        self.stop()  # safe twice

    def test_the_page_and_runtime_files_are_served_on_loopback(self):
        self.assertTrue(self.url.startswith("http://127.0.0.1:"))
        with urllib.request.urlopen(self.url, timeout=10) as r:
            self.assertIn("__MOTION_PREVIEW__", r.read().decode())
        with urllib.request.urlopen(self.url + "runtime.js", timeout=10) as r:
            self.assertIn("MotionRuntime", r.read().decode())
        with urllib.request.urlopen(self.url + "domains/charts.js", timeout=10) as r:
            self.assertEqual(r.status, 200)
        for bad in ("secret", "../studio.py", "studio.py"):
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(self.url + bad, timeout=10)

    def test_preview_applies_the_edits_it_is_sent(self):
        status, data = _post(self.url, "/preview",
                             {"edits": [{"scene": 0, "node": "pill_0", "dx": 77}]})
        self.assertEqual(status, 200)
        pill = data["resolved"]["scenes"][0]["nodes"][2]["children"][0]
        original = _spec()["scenes"][0]["nodes"][2]["children"][0]
        self.assertEqual(pill["position"][0], original["position"][0] + 77)
        self.assertEqual(data["errors"], [])
        self.assertEqual(len(data["review"]), 3)

    def test_save_render_and_refine_reach_their_callbacks_cleaned(self):
        status, _ = _post(self.url, "/save", {"edits": [{"scene": 0, "node": "a", "dx": 1.234},
                                                        "junk"]})
        self.assertEqual(status, 200)
        # serve() answers the request and only THEN fires the callback on
        # its own thread — give it a moment rather than racing it.
        self.assertTrue(_settle(lambda: self.saved))
        self.assertEqual(self.saved, [[{"scene": 0, "node": "a", "dx": 1.23}]])
        _post(self.url, "/render", {"edits": []})
        self.assertTrue(_settle(lambda: self.rendered))
        self.assertEqual(self.rendered, [[]])
        status, _ = _post(self.url, "/refine", {"change": "make it warmer",
                                                "context": {"scene_index": "1", "node_id": "panel_1",
                                                            "continuity_key": "panel", "label": "x" * 500}})
        self.assertEqual(status, 200)
        self.assertTrue(_settle(lambda: self.refined))
        change, ctx = self.refined[0]
        self.assertEqual(change, "make it warmer")
        self.assertEqual((ctx["scene_index"], ctx["node_id"], ctx["continuity_key"]), (1, "panel_1", "panel"))
        self.assertEqual(len(ctx["label"]), 160)

    def test_bad_requests(self):
        self.assertEqual(_post(self.url, "/save", {})[0], 400)
        self.assertEqual(_post(self.url, "/refine", {"change": ""})[0], 400)
        self.assertEqual(_post(self.url, "/nothing", {"edits": []})[0], 404)
        self.assertEqual(_post(self.url, "/save", {"edits": []}, origin="http://evil.example")[0], 403)
        self.assertEqual(self.saved, [])


class TheFollowUp(unittest.TestCase):
    def test_the_prompt_is_scoped_to_the_selection_and_its_thread(self):
        prompt = studio.followup_prompt("Make the panel warmer", {
            "scene_index": 1, "node_id": "panel_1", "continuity_key": "panel"}, _spec())
        self.assertIn("Make the panel warmer", prompt)
        self.assertIn("scene 2 of 3", prompt)
        self.assertIn('node "panel_1"', prompt)
        self.assertIn('continuity_key "panel"', prompt)
        self.assertIn('scene 1 node "panel_0" settles at position', prompt)
        self.assertIn('scene 3 node "panel_2" settles at position', prompt)
        self.assertIn("Rewrite ONLY scene 2", prompt)
        # only the selected scene's JSON travels, not the whole spec
        self.assertIn('"panel_1_h"', prompt)
        self.assertNotIn('"panel_0_h"', prompt)

    def test_a_one_scene_reply_folds_back_and_drops_that_scenes_edits(self):
        spec = _spec()
        spec[studio.EDITS_KEY] = [{"scene": 1, "node": "panel_1", "dx": 5},
                                  {"scene": 2, "node": "panel_2", "dx": 6}]
        panel = spec["scenes"][1]["nodes"][1]["children"][0]
        reply = json.dumps({"shot": {"intent": "orbit"}, "nodes": [
            {"id": "far_1", "type": "depth_layer", "depth": 0.55, "children": []},
            {"id": "mid_1", "type": "depth_layer", "children": [panel]},
        ]})
        out, note = studio.apply_followup(spec, 1, "```json\n" + reply + "\n```")
        self.assertIsNotNone(out)
        self.assertEqual(out["scenes"][1]["id"], "scene_1")
        self.assertEqual(out["scenes"][1]["duration"], 2.5)
        self.assertEqual(out["scenes"][1]["shot"], {"intent": "orbit"})
        self.assertEqual(out[studio.EDITS_KEY], [{"scene": 2, "node": "panel_2", "dx": 6.0}])
        self.assertIn("scene 2 rewritten", note)
        self.assertEqual(len(spec["scenes"][1]["nodes"]), 3, "the original is untouched")

    def test_an_unusable_reply_leaves_the_spec_alone_and_says_so(self):
        out, note = studio.apply_followup(_spec(), 1, "Sure! Here is some prose.")
        self.assertIsNone(out)
        self.assertIn("unchanged", note)

    def test_a_reply_that_breaks_continuity_is_kept_but_named(self):
        spec = _spec()
        reply = json.dumps({"nodes": [{"id": "lonely", "type": "text", "content": "hi",
                                       "position": [540, 900]}]})
        out, note = studio.apply_followup(spec, 1, reply)
        self.assertIsNotNone(out)
        self.assertIn("continuity broken", note)


@unittest.skipUnless(_render_lane(), "render lane not enabled")
class InARealBrowser(unittest.TestCase):
    def test_the_workspace_mounts_threads_review_and_selection(self):
        from playwright.sync_api import sync_playwright
        url, stop = studio.serve(_spec())
        errors = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={"width": 1500, "height": 1000})
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url, wait_until="load")
                page.wait_for_function("window.__motionStudio && window.__runtime", timeout=20000)
                self.assertTrue(page.query_selector("#motion-top"))
                self.assertIn("panel", page.inner_text("#ms-threads"))
                page.evaluate("window.__motionStudio.showScene(1, 'settled')")
                state = page.evaluate("window.__motionStudio.state()")
                self.assertEqual(state["current"], 1)
                self.assertGreater(state["time"], 2.5)
                page.evaluate("window.__motionStudio.select('panel_1')")
                self.assertEqual(page.evaluate("window.__motionStudio.state().selected"), "panel_1")
                self.assertTrue(page.query_selector("#stage [data-motion-id='panel_1']"))
                browser.close()
        finally:
            stop()
        self.assertEqual(errors, [])


class TheMotionWindow(unittest.TestCase):
    """The Motion window's Edit button lights when there is a graphic;
    Save keeps the edits on the spec and on disk; Render from the browser
    restarts the render with them; Refine rewrites ONE scene through the
    writing agent. Qt offscreen, no browser, no event loop."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
        if GUI not in sys.path:
            sys.path.insert(0, GUI)
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])
        import core_bridge as CB
        cls.CB = CB

    def _dialog(self, runs_dir: str = ""):
        import tempfile
        from unittest import mock
        from addons.motion.dialog import MotionDialog
        with mock.patch.object(self.CB.config, "RUNS_DIR", runs_dir or tempfile.mkdtemp()):
            return MotionDialog({"agents": {"content": "ChatGPT"}}, [], None)

    def test_the_button_waits_for_a_graphic(self):
        d = self._dialog()
        self.assertFalse(d.edit_btn.isEnabled())
        d.spec = _spec()
        d._refresh_edit_btn()
        self.assertTrue(d.edit_btn.isEnabled())

    def test_the_last_motion_graphic_is_back_on_the_bench(self):
        import tempfile
        runs = tempfile.mkdtemp()
        with open(os.path.join(runs, "motion_200.json"), "w") as f:
            json.dump(_spec(), f)
        with open(os.path.join(runs, "motion_199.json"), "w") as f:
            f.write("{broken")
        d = self._dialog(runs)
        self.assertTrue(d.edit_btn.isEnabled())
        self.assertEqual(len(d.spec["scenes"]), 3)
        self.assertTrue(d.out_path.endswith("motion_200.mp4"))

    def test_edit_opens_the_served_page_in_the_browser(self):
        from unittest import mock
        d = self._dialog()
        d.spec = _spec()
        fake = mock.Mock()
        fake.serve.return_value = ("http://127.0.0.1:1/", mock.Mock())
        import addons.motion.dialog as mod
        with mock.patch.object(self.CB, "get_motion_studio", return_value=fake), \
                mock.patch.object(mod.QDesktopServices, "openUrl") as opened:
            d._edit_layout()
        fake.serve.assert_called_once()
        opened.assert_called_once()
        self.assertIn("browser", d.status.text())

    def test_render_from_the_browser_keeps_the_edits_and_restarts_the_render(self):
        import tempfile
        from unittest import mock
        d = self._dialog()
        d.spec = _spec()
        d.out_path = os.path.join(tempfile.mkdtemp(), "motion_1.mp4")
        stopped = []
        d._edit_stop = lambda: stopped.append(True)
        edits = [{"scene": 0, "node": "pill_0", "dx": 30.0}]
        with mock.patch.object(d, "_start_render") as render:
            d._on_edits_rendered(edits)
        self.assertEqual(d.spec[studio.EDITS_KEY], edits)
        self.assertTrue(stopped, "the editor server must be stopped")
        render.assert_called_once_with(d.spec)
        with open(d.out_path[:-4] + ".json", encoding="utf-8") as f:
            self.assertEqual(json.load(f)[studio.EDITS_KEY], edits)

    def test_a_plain_save_keeps_the_edits_and_says_so(self):
        import tempfile
        d = self._dialog()
        d.spec = _spec()
        d.out_path = os.path.join(tempfile.mkdtemp(), "motion_2.mp4")
        d._on_edits_saved([{"scene": 0, "node": "pill_0", "dx": 5.0}])
        self.assertEqual(len(d.spec[studio.EDITS_KEY]), 1)
        self.assertIn("Render MP4", d.status.text())
        d._on_edits_saved([])
        self.assertNotIn(studio.EDITS_KEY, d.spec)

    def test_refine_rewrites_one_scene_through_the_writing_agent(self):
        from unittest import mock
        d = self._dialog()
        d.spec = _spec()
        d.cfg = {"agents": {"content": "ChatGPT"}, "motion_agent": "ChatGPT"}
        started = {}

        class FakeWorker:
            def __init__(self, *args, **kwargs):
                started["kwargs"] = kwargs
                self.done, self.failed = mock.Mock(), mock.Mock()

            def start(self):
                started["started"] = True

        import addons.motion.dialog as mod
        with mock.patch.object(mod, "AutomationWorker", FakeWorker), \
                mock.patch.object(self.CB.config, "active_agents",
                                  return_value={"content": "ChatGPT"}):
            d._on_editor_refine("shorter headline", {"scene_index": 1, "node_id": "panel_1",
                                                      "continuity_key": "panel"})
        self.assertTrue(started.get("started"))
        stage, agent, prompts = started["kwargs"]["custom_stages"][0]
        self.assertEqual((stage, agent), ("refine", "ChatGPT"))
        self.assertIn("Rewrite ONLY scene 2", prompts[0])
        reply = ('{"nodes": [{"id": "panel_1", "type": "glass_panel", "position": [540, 1000], '
                 '"continuity_key": "panel", "layer": "midground"}]}')
        with mock.patch.object(d, "_start_render") as render:
            d._on_refined({"refine": [reply]}, {})
        render.assert_called_once()
        self.assertEqual(len(d.spec["scenes"][1]["nodes"]), 1)
        self.assertIn("scene 2 rewritten", d.status.text())


if __name__ == "__main__":
    unittest.main()

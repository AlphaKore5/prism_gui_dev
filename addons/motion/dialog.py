"""Motion — say what it's about, get a scene-graph video with a real camera.

Same shape as Reel (addons/reel/dialog.py): one prompt and one button.
Attach a logo or business card and the brand colours are measured off it,
the agent writes a storyboard and then each scene in turn, and the
renderer draws every frame locally from a JSON scene graph — a real
camera, charts, diagrams and UI mockups, not an HTML page filmed.
"""
from __future__ import annotations
import json
import os
import time

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QLabel, QPlainTextEdit

import core_bridge as CB
import i18n
import theme
import deps
from dialogs.base import PrismDialog
from workers import AutomationWorker, RecordWorker, MotionWorker
from widgets.loader import Loader
from widgets.ask_panel import AskPanel


class MotionDialog(PrismDialog):
    # From the Motion Studio server's thread (core.motion.studio.serve) —
    # a signal, never a widget, is what may cross that boundary.
    edits_saved = Signal(list)
    edits_rendered = Signal(list)
    refine_requested = Signal(str, dict)

    def __init__(self, cfg: dict, attachments: list, parent=None):
        super().__init__(
            i18n.t("Make a Motion Graphic"),
            i18n.t("A scene-graph video with a real camera — charts, "
                   "diagrams and UI mockups, drawn frame by frame on this "
                   "machine."),
            icon="video", parent=parent, closable=False)
        self.setWindowTitle("Make a Motion Graphic")
        self.resize(780, 700)
        self.setMinimumSize(620, 620)
        self.cfg = cfg
        self.motion_generate = CB.get_motion_generate()

        self.images: list[dict] = []
        self.brand: dict = {}
        self.spec: dict | None = None
        self.out_path = ""
        # The findable copy — see config.ARTIFACTS_DIR. `out_path` is where
        # the render actually lands (~/.prism/runs, hidden), which is why
        # Play/Show always prefer this one once it exists.
        self.artifact_path = ""
        self._worker = None
        self._render_worker = None
        self._followup_worker = None
        self._rec = None
        self._edit_stop = None
        self.request = ""
        self.edits_saved.connect(self._on_edits_saved)
        self.edits_rendered.connect(self._on_edits_rendered)
        self.refine_requested.connect(self._on_editor_refine)

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        title = QLabel("What should the motion graphic show?")
        title.setObjectName("h4")
        root.addWidget(title)

        self.ask = AskPanel(
            'Just say it — for example:\n'
            '"an animated architecture diagram of our distributed crawler"\n\n'
            "Attach a logo or business card and the brand colours are taken "
            "straight from it.")
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # A measured result ("your brand colours came off this logo"), not a
        # placeholder — same convention as ReelDialog's brand_label.
        self.brand_label = QLabel("", self)
        self.brand_label.setWordWrap(True)
        self.brand_label.setVisible(False)
        self.brand_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        root.addWidget(self.brand_label)

        self.progress = Loader("stages", [i18n.t(n) for n in ['Storyboard', 'Render']])
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.script_view = QPlainTextEdit()
        self.script_view.setReadOnly(True)
        self.script_view.setPlaceholderText(
            "The scenes will be listed here once written.")
        self.script_view.setMinimumHeight(150)
        root.addWidget(self.script_view, stretch=1)

        self.edit_btn = self.button(i18n.t("Edit in Studio"), "secondary",
                                    small=True, on_click=self._edit_layout)
        self.edit_btn.setEnabled(False)
        self.edit_btn.setToolTip(i18n.t(
            "Open the motion graphic in your browser: scenes, continuity "
            "threads, camera shots, glass and handoffs, with start, "
            "midpoint, settled and exit previews of every shot."))
        self.footer.add_utility(self.edit_btn)
        self.play_btn = self.button(i18n.t("Play"), "secondary",
                                    icon_name="play", small=True,
                                    on_click=self._play)
        self.play_btn.setEnabled(False)
        self.footer.add_utility(self.play_btn)
        self.folder_btn = self.button(i18n.t("Show file"), "secondary",
                                      icon_name="folder", small=True,
                                      on_click=self._reveal)
        self.folder_btn.setEnabled(False)
        self.footer.add_utility(self.folder_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.run_btn = self.button(i18n.t("Make my motion graphic"), "primary",
                                   icon_name="video", on_click=self._run)
        self.footer.set_primary(self.run_btn)

        if attachments:
            self._absorb([a["path"] for a in attachments])

        # The newest saved motion graphic is back on the bench, so closing
        # the window after a render does not orphan it — same reason
        # ReelDialog restores the last Studio reel.
        last = self._last_motion_project()
        if last:
            self.spec, self.out_path = last
            self.request = str((self.spec.get("_studio") or {}).get("request", ""))
            if os.path.exists(self.out_path):
                self.play_btn.setEnabled(True)
                self.folder_btn.setEnabled(True)
            self._refresh_edit_btn()

    @staticmethod
    def _last_motion_project():
        """(spec, mp4 path) of the newest saved motion graphic, or None.
        Only the newest twenty records are tried; this runs at every open."""
        folder = CB.config.RUNS_DIR
        if not os.path.isdir(folder):
            return None
        names = sorted((n for n in os.listdir(folder)
                        if n.startswith("motion_") and n.endswith(".json")),
                       reverse=True)
        for name in names[:20]:
            path = os.path.join(folder, name)
            try:
                with open(path, encoding="utf-8") as f:
                    spec = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(spec, dict) and isinstance(spec.get("scenes"), list) \
                    and spec["scenes"]:
                return spec, path[:-5] + ".mp4"
        return None

    # ── inputs ──────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        self._absorb(paths)

    def _absorb(self, paths: list):
        """Only images matter here — they carry the brand and become
        `image` nodes the AI can place by name. Anything else is ignored
        rather than refused."""
        for p in paths:
            if not p.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
                continue
            try:
                att = CB.files.attach(p)
            except Exception:
                continue
            if att["path"] not in [i["path"] for i in self.images]:
                self.images.append(att)
        if not self.images:
            return
        # Same pixel-level measurement Reel/Studio use — no Motion-specific
        # brand sampling exists or needs to.
        self.brand = CB.get_reel().sample_brand(
            [i["path"] for i in self.images]) or {}
        if self.brand:
            self.brand_label.setText(
                f"Brand colours read from {', '.join(i['name'] for i in self.images)} — "
                f"accent {self.brand.get('accent')}, deep {self.brand.get('deep')}. "
                "Measured from the artwork, not guessed.")
            self.brand_label.setVisible(True)

    def _toggle_record(self):
        if self._rec:
            self._rec.stop()
            self.ask.set_recording(False)
            return
        problem = deps.voice_problem(self.cfg)
        if problem:
            QMessageBox.information(self, "Speak", problem)
            return
        self.ask.set_recording(True)
        self._rec = RecordWorker(self.cfg)
        self._rec.done.connect(self._on_spoken)
        self._rec.failed.connect(lambda e: self._on_spoken("", ""))
        self._rec.start()

    def _on_spoken(self, text: str, lang: str):
        self._rec = None
        self.ask.set_recording(False)
        if text:
            self.ask.append_text(text)

    # ── the run ─────────────────────────────────────────────────────────
    # One turn names the storyboard; every scene's nodes are then asked for
    # on their own turn, in the same tab, checked before the next is asked
    # for. See core.motion.generate.build_spec() — same shape as Studio's
    # design conversation, for the same reason: a whole motion graphic
    # asked for in one reply starves every scene of room to have real
    # motion in it.

    def _run(self):
        request = self.ask.text()
        if not request:
            QMessageBox.information(self, "Motion Graphics",
                                    "Tell me what the motion graphic is about.")
            return

        active = CB.config.active_agents(self.cfg)
        # "media" is deliberately excluded — that category holds the local
        # Reel/Studio renderers, which render video and cannot hold a text
        # conversation. Same precedent as /motion's own CLI agent choice.
        writer = (self.cfg.get("motion_agent") or active.get("brains")
                 or active.get("content"))
        if not writer:
            QMessageBox.warning(self, "Motion Graphics",
                                "No writing agent set up yet — open Agents first.")
            return
        self.request = request

        self.progress.set_stage(0)
        self._busy(True, f"{writer} is planning the storyboard…")
        prompt = self.motion_generate.storyboard_instructions(
            request, self.brand, skeleton="cinematic_glass")
        self._worker = AutomationWorker(
            {}, self.cfg, self.images, f"motion graphic — {request}",
            custom_stages=[("storyboard", writer, [prompt])],
            chatgpt_analysis=False,
            motion_design_stage="storyboard",
            motion_skeleton="cinematic_glass")
        self._worker.stage_event.connect(self._on_motion_event)
        self._worker.done.connect(self._on_storyboard)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_motion_event(self, kind: str, payload: dict):
        if kind == "motion_scene":
            n, total = payload.get("index", 0) + 1, payload.get("total", 0)
            self.progress.set_stage(0)
            self._busy(True, f"Writing scene {n} of {total} — "
                             "each one is written and checked on its own.")
            if total:
                self.progress.setRange(0, total)
                self.progress.setValue(n - 1)

    def _on_storyboard(self, responses: dict, links: dict):
        # By the time this fires, automation.run()'s motion_feeder block has
        # already run the whole per-scene conversation and left the fully
        # assembled, validated spec — as JSON text — in responses["storyboard"].
        texts = [t for t in (responses.get("storyboard") or []) if t.strip()]
        if not texts:
            self._busy(False, "")
            QMessageBox.warning(self, "Motion Graphics",
                                "The agent returned nothing.")
            return
        try:
            spec = json.loads(texts[-1])
        except (ValueError, json.JSONDecodeError) as e:
            self._busy(False, "")
            QMessageBox.warning(
                self, "Motion Graphics",
                f"Could not parse the assembled motion graphic: {e}"
                + ("\n\nIts tab: " + links["storyboard"]
                   if links.get("storyboard") else ""))
            return
        self.spec = spec
        spec.setdefault("_studio", {})["request"] = self.request
        self._start_render(spec)

    def _start_render(self, spec: dict):
        scenes = spec.get("scenes", [])
        lines = [f"{i + 1}. scene  ·  {sc.get('duration', 0):.1f}s   "
                 f"{len(sc.get('nodes', []))} node(s)"
                 for i, sc in enumerate(scenes)]
        self.script_view.setPlainText("\n".join(lines))

        dur = float((spec.get("project") or {}).get("duration", 8.0))
        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        stamp = int(time.time())
        self.out_path = os.path.join(CB.config.RUNS_DIR, f"motion_{stamp}.mp4")
        # Saved beside the video and complete in itself — assets inlined —
        # so it re-renders identically next year without an AI in the loop.
        json.dump(spec, open(
            os.path.join(CB.config.RUNS_DIR, f"motion_{stamp}.json"), "w"),
            indent=2)

        self.progress.setRange(0, 100)
        self.progress.set_stage(1)
        self._busy(True, f"Rendering {len(scenes)} scenes, {dur:.0f}s, "
                         "1080x1920…")
        self._render_worker = MotionWorker(spec, self.out_path)
        self._render_worker.progress.connect(self._on_frames)
        self._render_worker.done.connect(self._on_rendered)
        self._render_worker.failed.connect(self._on_failed)
        self._render_worker.start()

    def _on_frames(self, done: int, total: int):
        self.progress.setValue(int(done / max(1, total) * 100))

    # ── the Studio editing surface ──────────────────────────────────────

    def _refresh_edit_btn(self):
        self.edit_btn.setEnabled(bool(self.spec))

    def _edit_layout(self):
        """Open the motion graphic in the browser with the edit layer on.

        The page plays the SAME runtime the renderer films, fed by the
        same edit records the renderer applies — fix a pose or a handoff
        by eye there, press Render MP4, and the film cannot differ.
        """
        if not self.spec:
            return
        self._stop_editor()
        studio = CB.get_motion_studio()
        try:
            url, self._edit_stop = studio.serve(
                self.spec,
                on_save=self.edits_saved.emit,
                on_render=self.edits_rendered.emit,
                on_refine=self.refine_requested.emit)
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, "Motion Graphics", i18n.t(
                "Could not open the editor: {error}").format(error=e))
            return
        QDesktopServices.openUrl(QUrl(url))
        self.status.setText(i18n.t(
            "The motion graphic is open in your browser. Select a layer or "
            "a thread, adjust it, then press Render MP4 there — the new "
            "video renders here."))

    def _keep_edits(self, edits: list):
        """The edits onto the spec and the spec back onto disk, so the saved
        copy re-renders with them even next year."""
        if not self.spec:
            return
        if edits:
            self.spec["_motion_edits"] = edits
        else:
            self.spec.pop("_motion_edits", None)
        if self.out_path.endswith(".mp4"):
            try:
                with open(self.out_path[:-4] + ".json", "w", encoding="utf-8") as f:
                    json.dump(self.spec, f, indent=2)
            except OSError:
                pass    # the render still carries the edits in memory

    def _on_edits_saved(self, edits: list):
        self._keep_edits(edits)
        self.status.setText(i18n.t(
            "Layout saved — {n} change(s). Press Render MP4 in the browser "
            "when you are happy with it.").format(n=len(edits)))

    def _on_edits_rendered(self, edits: list):
        self._keep_edits(edits)
        self._stop_editor()
        self._start_render(self.spec)

    def _on_editor_refine(self, change: str, selection: dict):
        """A prompt from the Studio, scoped to the selected scene, layer
        and continuity thread — one scene is rewritten, not the piece."""
        if not self.spec:
            return
        active = CB.config.active_agents(self.cfg)
        writer = (self.cfg.get("motion_agent") or active.get("brains")
                  or active.get("content"))
        if not writer:
            self.status.setText(i18n.t(
                "No writing agent set up yet — open Agents first."))
            return
        studio = CB.get_motion_studio()
        prompt = studio.followup_prompt(change, selection, self.spec)
        self._refine_scene = int(selection.get("scene_index", 0) or 0)
        self._stop_editor()
        self.progress.set_stage(0)
        self._busy(True, i18n.t("{agent} is rewriting scene {n}…").format(
            agent=writer, n=self._refine_scene + 1))
        self._followup_worker = AutomationWorker(
            {}, self.cfg, self.images, f"motion refinement — {change}",
            custom_stages=[("refine", writer, [prompt])],
            chatgpt_analysis=False)
        self._followup_worker.done.connect(self._on_refined)
        self._followup_worker.failed.connect(self._on_failed)
        self._followup_worker.start()

    def _on_refined(self, responses: dict, links: dict):
        texts = [t for t in (responses.get("refine") or []) if t.strip()]
        studio = CB.get_motion_studio()
        new_spec, note = studio.apply_followup(
            self.spec, getattr(self, "_refine_scene", 0), texts[-1] if texts else "")
        if new_spec is None:
            self._busy(False, "")
            QMessageBox.warning(self, "Motion Graphics", note)
            return
        self.spec = new_spec
        self.status.setText(note)
        self._start_render(self.spec)

    def _stop_editor(self):
        if self._edit_stop is not None:
            try:
                self._edit_stop()
            except Exception:                           # noqa: BLE001
                pass
            self._edit_stop = None

    def _on_rendered(self, path: str):
        self.play_btn.setEnabled(True)
        self.folder_btn.setEnabled(True)
        self._refresh_edit_btn()
        try:
            self.artifact_path = CB.config.save_artifact(
                path, self.request, kind="motion", task=self.request)
        except Exception:                               # noqa: BLE001
            self.artifact_path = ""
        if self.artifact_path:
            self._busy(False, i18n.t(
                "Done — saved to Desktop/Prism Artifacts/{name}").replace(
                "{name}", os.path.basename(self.artifact_path)))
        else:
            self._busy(False, f"Done — {os.path.basename(path)}")
        CB.config.save_run({
            "query": f"motion — {self.request}",
            "motion": {"mp4": path, "brand": self.brand,
                      "artifact": self.artifact_path},
        })

    def closeEvent(self, event):
        """Wind up any worker before this dialog is destroyed.

        A QThread destroyed while still running aborts the whole process —
        see ReelDialog.closeEvent() for the same fix, applied there first.
        """
        self._stop_editor()
        for worker in (getattr(self, "_worker", None),
                       getattr(self, "_render_worker", None),
                       getattr(self, "_followup_worker", None),
                       getattr(self, "_rec", None)):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    def _on_failed(self, error: str):
        self._busy(False, "")
        QMessageBox.warning(self, "Motion Graphics", error)

    def _busy(self, busy: bool, message: str):
        if busy:
            self.progress.set_message(message)
        self.progress.setVisible(busy)
        if busy and self.progress.maximum() == 0:
            self.progress.setRange(0, 0)
        self.run_btn.setEnabled(not busy)
        self.status.setText("" if busy else message)   # the loader carries it while busy

    # ── output ──────────────────────────────────────────────────────────

    def _play(self):
        path = self.artifact_path or self.out_path
        if not path:
            return
        import paths
        paths.open_file(path, self)

    def _reveal(self):
        path = self.artifact_path or self.out_path
        if not path:
            return
        import paths
        paths.reveal_result(path)

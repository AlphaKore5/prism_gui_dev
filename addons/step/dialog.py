"""STEP add-on — measure a 3D model, then draft, ask or edit. No AI sees it.

The GUI face of the terminal's /step, /step-auto and /step-ask, on the same
rule as Gerber: the customer's STEP file is their product, and it never
leaves this machine. core.stepfile measures it here; the only things that
ever reach an AI are the measured NUMBERS and Prism's own plain render of
the parts (a PNG Prism drew, not the model). The three actions:

    Draft  — measure, then the image tool draws a dimensioned drawing sheet
             FROM THE NUMBERS (auto_brief) — the model stays here.
    Ask    — measure, then Groq suggests improvements from the numbers and
             the question. That answer IS the deliverable — nothing is
             planned, nothing is built, no page opens.
    Edit   — measure, get Groq's suggestions, then a reviewing agent turns
             them into an exact change plan shown on a review page; after
             the person confirms against that page, the plan is applied to
             a COPY of the model, locally, and the copy is re-measured so
             the After column is real, not predicted.

Several models can be attached at once; each is measured into its own
folder, named after it, under the folder the person chose (asked once, the
first time, and kept in cfg["step_out_dir"]). Every file inside carries the
model's own name — see core.stepfile.names().
"""
from __future__ import annotations

import json
import os
import shutil
import time
import uuid

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QStackedWidget, QTextBrowser,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import dashboard_data as DATA
import i18n
import paths as appfiles
import theme
from dialogs.base import PrismDialog
from workers import AutomationWorker
from addons.step.workers import (StepApplyWorker, StepAskWorker,
                                 StepMeasureWorker, StepPlanWorker)
from addons.step import sessions as SES
from addons.step import workbench as WB
from widgets.loader import Loader
from widgets import controls as C
from widgets import icons
from widgets.ask_panel import AskPanel

MODEL_EXTS = (".step", ".stp")

# (key, label, what it does) — the order they are offered in.
ACTIONS = (
    ("draft", "Draft",
     "Measure and draw the dimensioned sheet here — flat pattern, "
     "isometric, every hole sized and placed on the drawing itself — no "
     "AI. ChatGPT drawing a second, styled copy is optional (below); "
     "compared against Prism's own sheet it turned out to just trace the "
     "picture it was shown, text and all, worse — it is not an "
     "independent check on the numbers, only a different look."),
    ("ask", "Ask",
     "Measure, then get suggestions for the part from the numbers and your "
     "question. Just the answer — nothing is planned, built or opened."),
    ("edit", "Edit",
     "Measure, get suggestions, then review an exact change plan and — "
     "once you confirm — apply it to a COPY of the model, here, and "
     "re-measure it. The original is never touched."),
)

ACTIONS_BY_KEY = {key: label for key, label, _blurb in ACTIONS}

# What the footer's one button says and does, per selected action — so the
# single button a person must press always names the actual result ("Make
# the Changes", not a generic "Generate") instead of making them trust a
# separate radio choice they might not remember making.
ACTION_BUTTON = {
    "draft": ("Measure and Draw", "grid"),
    "ask": ("Ask", "chat"),
    "edit": ("Make a change", "pencil"),
}

# (cfg value, label) — who answers Ask/Edit's question. Groq is a direct,
# near-instant API call; the other three are the SAME background-Chrome
# automation Draft and Edit's plan stage already use to reach a tool —
# slower (roughly 10-60s), but a stronger model than the small one Groq
# runs here.
MODEL_CHOICES = (
    ("Groq", "Groq (fast, in-house)"),
    ("ChatGPT", "ChatGPT"),
    ("Claude", "Claude"),
)

# Deliberately no Gemini. "Google Gemini" is registered in agents._MAKES as
# an image generator — core.automation._maker_brief() wraps EVERY stage
# routed to that name with "what I need from you is generated images...
# build it here", regardless of what the stage's own prompt says, by
# design (it exists specifically to override a text-shaped ask). A plain
# Q&A prompt sent to it comes back as a refused image request, not an
# answer — confirmed live. Fixable only by giving Gemini a second,
# non-maker agent identity in the engine; out of scope here, so it is left
# out rather than shipped broken.
#
# If the chosen model can't answer, retry in this fixed, quality-ordered
# chain — never silently back to Groq, which is the thing being upgraded
# away from. Whichever was already tried as the primary pick is skipped.
FALLBACK_ORDER = ("ChatGPT", "Claude")


# Short, per-action lines for the workbench's action block — the long text
# stays on ACTIONS (and as each button's tooltip).
ACTION_SHORT = {
    "draft": "Draws the dimensioned sheet here — flat pattern, isometric, "
             "every hole sized. No AI needed.",
    "ask": "Measures, then answers your question from the numbers. Nothing "
           "is built or opened.",
    "edit": "Measures, plans, and — once you confirm — applies the change to "
            "a copy of the model and re-measures it. The original is never "
            "touched.",
}

class _InlineAnswer:
    """What the follow-up and build logic talks to. It used to be the answer
    pop-up (set_busy / set_answer); now it is the composer under the chat, so
    nothing opens over the window."""

    def __init__(self, dlg):
        self.dlg = dlg
        self.question = ""

    def set_busy(self, busy: bool):
        self.dlg.composer.set_busy(
            busy, self.dlg.tr_busy if busy else "")

    def set_answer(self, text: str, agent: str = ""):
        self.dlg._followup_answered(self.question, text, agent)


# What a run goes through, per action — the stages the loader shows.
def _stages(action: str) -> list:
    return {
        "draft": [i18n.t("Measure"), i18n.t("Draw"), i18n.t("Save")],
        "ask": [i18n.t("Measure"), i18n.t("Ask"), i18n.t("Answer")],
        "edit": [i18n.t("Measure"), i18n.t("Plan"), i18n.t("Build"), i18n.t("Check")],
    }.get(action, [])


class StepDialog(PrismDialog):
    # Asked of the main window when this is the screen (not a popup) and the
    # person closes it.
    leave_requested = Signal()

    def __init__(self, cfg: dict, attachments: list, parent=None,
                 embedded: bool = False):
        super().__init__(
            i18n.t("STEP"),
            i18n.t("Attach a 3D model. It is measured here, on this machine "
                   "— no AI ever sees the STEP file."),
            icon="grid", parent=parent, closable=False, scrollable=False)
        self.setWindowTitle("STEP — 3D model measurement")
        self._embedded = embedded
        if embedded:
            # The screen, not a window: it sits in the main window's stack
            # like every other screen, so Ask, Edit and History all happen in
            # the one place.
            self.setWindowFlags(Qt.Widget)
            self.setModal(False)
        self.resize(1240, 800)
        self.setMinimumSize(1000, 640)
        self.cfg = cfg
        self.sf = CB.get_stepfile()

        self.paths: list[str] = []
        # Once measured: [{"path", "report", "out_dir", "drawn", "xlsx"}]
        self.models: list[dict] = []
        self._queue: list[dict] = []      # models still waiting for the action
        self._current: dict | None = None
        self._worker = None
        self._agent_worker = None
        self._ask_worker = None
        self._apply_worker = None
        self._followup_ask_worker = None
        self._followup_agent_worker = None
        self._built_from_popup = False
        self._live: dict | None = None
        self._followups: list = []
        self._thread: list = []
        self._run_path = ""
        self._last_action = ""
        self._pending: dict | None = None
        self._awaiting = False
        self._stay_on_plan = False
        self._review_path = ""
        self.tr_busy = i18n.t("Working on it…")
        self._inline = _InlineAnswer(self)
        self._links: dict = {}
        self._responses: dict = {}
        self._stage_agents_map: dict = {}
        self._model_chain: list[str] = []
        self._made_files: list = []
        self._notes: list[str] = []
        self._preview_ok = False
        self._busy = False
        self._session_key = ""
        self._versions: list[dict] = []
        self._sel = ""
        self._loaded_run = ""
        self._measure_lines: list[str] = []

        # ── the workbench (preview/step-redesign/a2-workbench.html) ───────
        # models · canvas with one action at a time · results in tabs. Every
        # widget the logic below reads keeps its name; only where it sits has
        # changed. The dialog's own header and footer are replaced by the
        # top bar and the run row.
        self.header.setVisible(False)
        self.footer.setVisible(False)
        root = self.body
        root.setSpacing(theme.SPACE_3)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4,
                                theme.SPACE_4)
        self.setAcceptDrops(True)

        # ── top bar: STEP · the promise · output folder · options · close ──
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_3)
        title = QLabel("STEP")
        title.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 28px;"
            " font-weight: 600; letter-spacing: 1px;")
        top.addWidget(title)
        lock = WB.chip("●  " + i18n.t("Measured here — never uploaded"), "ok")
        lock.setToolTip(
            "The STEP file never leaves this machine. Draft, Ask and Edit "
            "show an AI only the measured NUMBERS and Prism's own plain "
            "render of the parts — never the model, never a path. Edits are "
            "made here, on a copy.")
        lock.setStyleSheet(lock.styleSheet().replace("font-size: 10.5px",
                                                     "font-size: 12px")
                           + " padding: 4px 10px;")
        top.addWidget(lock)
        top.addStretch(1)
        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.open_btn.setVisible(False)
        top.addWidget(self.open_btn)
        self.folder_btn = self.button(i18n.t("Output folder"), "secondary",
                                      icon_name="folder", small=True,
                                      on_click=self._open_folder)
        self.folder_btn.setEnabled(False)
        top.addWidget(self.folder_btn)
        self.opt_toggle = self.button("", "secondary", small=True,
                                      on_click=self._toggle_options)
        top.addWidget(self.opt_toggle)
        top.addWidget(self.button("✕", "secondary", small=True,
                                  on_click=self._close_clicked,
                                  tooltip=i18n.t("Close")))
        root.addLayout(top)

        # The options live in a popover under the top bar's button.
        opt_box = QFrame(self, Qt.Popup)
        self.opt_box = opt_box
        opt_box.setAttribute(Qt.WA_StyledBackground, True)
        opt_box.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid "
            f"{theme.NEUTRAL[300]}; border-radius: 12px; }}"
            "QLabel, QComboBox, QLineEdit { border-radius: 6px; }")
        opt_box.setFixedWidth(330)
        opt_v = QVBoxLayout(opt_box)
        opt_v.setContentsMargins(14, 12, 14, 12)
        opt_v.setSpacing(theme.SPACE_2)
        opt_v.addWidget(WB.heading(i18n.t("Measuring options")))
        mat_row = QHBoxLayout()
        mat_row.addWidget(QLabel(i18n.t("Material")))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(self.sf.MODES))
        self.mode_combo.setCurrentText(self.cfg.get("step_mode") or "metal")
        mat_row.addWidget(self.mode_combo, stretch=1)
        opt_v.addLayout(mat_row)
        mat_note = QLabel(i18n.t("Sheet metal reads thickness and weight in "
                                 "steel; plastic reads wall and ABS/PP/PC."))
        mat_note.setWordWrap(True)
        mat_note.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 12px;"
                               " border: none;")
        opt_v.addWidget(mat_note)

        # The bend-allowance K-factor a flat pattern is unfolded with —
        # theirs if they know it, Prism's own default if they don't. Never
        # asked before every model; kept in cfg like everything else here,
        # and the drawing sheet always states which one was actually used
        # (core.stepfile.analyse's own warning), so a blank box quietly
        # becoming the default is never mistaken for a confirmed shop value.
        k_row = QHBoxLayout()
        k_row.addWidget(QLabel(i18n.t("Bend K-factor")))
        self.k_edit = QLineEdit()
        self.k_edit.setPlaceholderText(f"default {self.sf._DEFAULT_K_FACTOR:g}")
        self.k_edit.setMaximumWidth(110)
        self.k_edit.setText(str(self.cfg.get("step_k_factor") or ""))
        k_row.addWidget(self.k_edit)
        k_row.addStretch(1)
        opt_v.addLayout(k_row)
        k_note = QLabel(i18n.t("Only for a metal flat pattern; leave blank "
                               "unless your shop gives you one."))
        k_note.setWordWrap(True)
        k_note.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 12px;"
                             " border: none;")
        opt_v.addWidget(k_note)

        # Where everything for a model goes. Asked ONCE, the first time
        # Generate is pressed (see _ensure_root), and shown here so the
        # answer is never a mystery and can be changed at any time.
        self.root_label = QLabel(self._root_caption())
        self.root_label.setWordWrap(True)
        self.root_label.setStyleSheet("font-size: 12px; border: none;")
        opt_v.addWidget(self.root_label)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.button(i18n.t("Change folder…"), "secondary",
                                      small=True, on_click=self._pick_root))
        self.root_default_btn = self.button(i18n.t("Use the Desktop"),
                                            "secondary", small=True,
                                            on_click=self._use_default_root)
        self.root_default_btn.setVisible(bool(self.cfg.get("step_out_dir")))
        dir_row.addWidget(self.root_default_btn)
        dir_row.addStretch(1)
        opt_v.addLayout(dir_row)
        opt_v.addWidget(QLabel(i18n.t("Changing these re-measures the model.")))
        self.mode_combo.currentTextChanged.connect(lambda _t: self._sync_opt_label())

        cols = QHBoxLayout()
        cols.setSpacing(theme.SPACE_3)
        root.addLayout(cols, stretch=1)

        # The AskPanel is kept — it holds the question box, Speak, and the
        # attached-file list the logic reads — but its own file row is not
        # shown: models are added from the drop zone on the left.
        self.ask = AskPanel(
            "For Ask and Edit, say what you want — e.g. \"how do I make "
            "this lighter?\" or \"fit M8 bolts instead of M6\". Draft needs "
            "no text.")
        self.ask.files_added.connect(self._on_files_added)
        self.ask.file_removed.connect(self._on_file_removed)
        self.ask.setVisible(False)

        # ── left · models, their history, the drop zone ──────────────────
        self.models_card = WB.Card(i18n.t("Models"), counter=True)
        self.models_card.setFixedWidth(280)
        cols.addWidget(self.models_card)
        self.model_list = WB.ModelList()
        self.model_list.selected.connect(self._select_model)
        self.model_list.removed.connect(self._remove_model)
        self.model_list.trashed.connect(self._delete_model_files)
        self.models_card.lay.addWidget(self.model_list)
        self.hist_head = WB.heading(i18n.t("History"))
        self.hist_head.setContentsMargins(16, 10, 16, 0)
        self.models_card.lay.addWidget(self.hist_head)
        self.history = WB.RunList()
        self.history.chosen.connect(self.load_session)
        self.history.delete_requested.connect(self._delete_chat)
        hist_scroll = QScrollArea()
        hist_scroll.setWidgetResizable(True)
        hist_scroll.setFrameShape(QFrame.NoFrame)
        hist_scroll.setStyleSheet("background: transparent;")
        hist_scroll.setWidget(self.history)
        self.models_card.lay.addWidget(hist_scroll, stretch=1)
        drop_host = QWidget()
        dl = QVBoxLayout(drop_host)
        dl.setContentsMargins(10, 6, 10, 10)
        self.drop = WB.DropZone()
        self.drop.browse.connect(self.ask._pick_file)
        self.drop.favourites.connect(self.ask._show_favourites)
        self.drop.dropped.connect(self._on_files_added)
        dl.addWidget(self.drop)
        self.models_card.lay.addWidget(drop_host)

        # ── centre · one action at a time, over the canvas ───────────────
        centre_card = WB.Card()
        cols.addWidget(centre_card, stretch=1)
        bar = QFrame()
        bar.setStyleSheet(f"border: none; border-bottom: 1px solid {WB._HAIR};")
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(14, 10, 14, 10)
        seg = QFrame()
        seg.setObjectName("stepSegBar")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"#stepSegBar {{ background: {theme.NEUTRAL[200]};"
            f" border: none; border-radius: {theme.R_CONTROL + 2}px; }}"
            "QPushButton#stepSeg { padding: 7px 22px; font-weight: 700;"
            " border: 1px solid transparent; background: transparent;"
            f" border-radius: {theme.R_CONTROL}px; color: {theme.NEUTRAL[700]}; }}"
            f"QPushButton#stepSeg:checked {{ background: #ffffff;"
            f" color: {theme.TEXT}; border: 1px solid {theme.NEUTRAL[300]}; }}")
        seg_row = QHBoxLayout(seg)
        seg_row.setContentsMargins(3, 3, 3, 3)
        seg_row.setSpacing(2)
        self._action_group = QButtonGroup(self)
        self._action_buttons: dict[str, QPushButton] = {}
        for key, label, blurb in ACTIONS:
            radio = QPushButton(i18n.t(label))
            radio.setObjectName("stepSeg")
            radio.setCheckable(True)
            radio.setCursor(Qt.PointingHandCursor)
            radio.setProperty("action", key)
            radio.setToolTip(i18n.t(blurb))
            self._action_group.addButton(radio)
            self._action_buttons[key] = radio
            seg_row.addWidget(radio)
        self._action_buttons["draft"].setChecked(True)
        bar_l.addWidget(seg)
        bar_l.addStretch(1)
        centre_card.lay.addWidget(bar)

        self.canvas = WB.Canvas()
        self.canvas.choose.connect(self.ask._pick_file)
        self.canvas.dropped.connect(self._on_files_added)
        centre_card.lay.addWidget(self.canvas, stretch=1)

        # A staged pipeline: the bar shows which stage the work is in.
        self.progress = Loader("stages", _stages("draft"))
        self.progress.setVisible(False)
        centre_card.lay.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            f"color: {theme.NEUTRAL[700]}; font-size: 12.5px;"
            " padding: 6px 16px; border: none;")
        centre_card.lay.addWidget(self.status)

        # Hidden until a model is attached. The question box and the Speak
        # button are the AskPanel's own, reparented down here so the action
        # reads as one block: what to say, who answers, the button.
        self.step2 = QFrame()
        self.step2.setStyleSheet(f"border: none; border-top: 1px solid {WB._HAIR};")
        step2_v = QVBoxLayout(self.step2)
        step2_v.setContentsMargins(16, 12, 16, 12)
        step2_v.setSpacing(theme.SPACE_2)
        self.action_blurb = QLabel("")
        self.action_blurb.setWordWrap(True)
        self.action_blurb.setStyleSheet(
            f"color: {theme.NEUTRAL[700]}; font-size: 12.5px; border: none;")
        step2_v.addWidget(self.action_blurb)
        # The question box sits directly in step2 (its own parent, as before);
        # the Speak row and the "answer with" row are small hosts so a whole
        # row can be shown or hidden with the action.
        step2_v.addWidget(self.ask.edit)
        mic_host = QWidget()
        mic_row = QHBoxLayout(mic_host)
        mic_row.setContentsMargins(0, 0, 0, 0)
        mic_row.addWidget(self.ask.mic_btn)
        mic_row.addStretch(1)
        step2_v.addWidget(mic_host)
        # Who answers Ask/Edit's question — only matters once a question is
        # actually asked, but shown alongside the action so the choice is
        # made before pressing the button, not discovered after.
        model_host = QWidget()
        model_row = QHBoxLayout(model_host)
        model_row.setContentsMargins(0, 0, 0, 0)
        self.model_label = QLabel(i18n.t("Answer with:"))
        model_row.addWidget(self.model_label)
        self.model_combo = QComboBox()
        for key, label in MODEL_CHOICES:
            self.model_combo.addItem(i18n.t(label), key)
        saved_model = self.cfg.get("step_ask_model", "Groq")
        idx = self.model_combo.findData(saved_model)
        self.model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        model_row.addWidget(self.model_combo)
        model_row.addStretch(1)
        step2_v.addWidget(model_host)
        model_hint = QLabel(i18n.t(
            "Groq answers in seconds. ChatGPT and Claude are stronger but "
            "slower — driven in a background Chrome window. If the one "
            "you pick can't answer, Prism tries the other one."))
        model_hint.setWordWrap(True)
        model_hint.setStyleSheet(
            f"color: {theme.NEUTRAL[600]}; font-size: 12px; border: none;")
        step2_v.addWidget(model_hint)
        self._ask_only = (self.ask.edit, mic_host, model_host, model_hint)

        # Off by default: checked against Prism's own drawing, ChatGPT's
        # "styled" copy just traced it, worse — same numbers, garbled
        # text (see ACTIONS' own note above). Not deleted, because a
        # differently-styled picture for sending to someone outside the
        # shop is still a real, if occasional, reason to want one; it is
        # just no longer something Draft spends a minute on unasked.
        self.ai_draft_cb = QCheckBox(i18n.t(
            "Also ask ChatGPT for a styled copy (optional)"))
        self.ai_draft_cb.setToolTip(i18n.t(
            "Not an independent check of the numbers — only a different "
            "look."))
        self.ai_draft_cb.setChecked(bool(self.cfg.get("step_ai_draft")))
        step2_v.addWidget(self.ai_draft_cb)

        run_row = QHBoxLayout()
        run_row.addStretch(1)
        draft_label, draft_icon = ACTION_BUTTON["draft"]
        self.generate_btn = self.button(i18n.t(draft_label), "primary",
                                        icon_name=draft_icon,
                                        on_click=self._generate)
        self.generate_btn.setEnabled(False)
        self.generate_btn.setToolTip(i18n.t("Attach a model first"))
        run_row.addWidget(self.generate_btn)
        step2_v.addLayout(run_row)
        self.step2.setVisible(False)
        centre_card.lay.addWidget(self.step2)

        # ── right · Measured · Answer · Plan · Files ─────────────────────
        right = WB.Card()
        self.right_card = right
        right.setFixedWidth(420)
        cols.addWidget(right)
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(8, 8, 8, 4)
        self.out_tabs = C.Tabs([i18n.t("Measured"), i18n.t("Chat"),
                                i18n.t("Plan"), i18n.t("Files")])
        tabs_row.addWidget(self.out_tabs)
        tabs_row.addStretch(1)
        self.wide_btn = self.button("⤢", "secondary", small=True,
                                    on_click=self._toggle_wide,
                                    tooltip=i18n.t("Make this panel wider"))
        tabs_row.addWidget(self.wide_btn)
        right.lay.addLayout(tabs_row)
        self.out_stack = QStackedWidget()
        right.lay.addWidget(self.out_stack, stretch=1)
        self.out_tabs.changed.connect(self.out_stack.setCurrentIndex)

        # Measured — the register, then the back-solve, then the full text.
        measured_page = QWidget()
        mp = QVBoxLayout(measured_page)
        mp.setContentsMargins(0, 0, 0, 0)
        mp.setSpacing(0)
        self.measured_empty = QLabel(i18n.t(
            "Nothing measured yet — attach a model and press the button."))
        self.measured_empty.setWordWrap(True)
        self.measured_empty.setStyleSheet(
            f"color: {theme.NEUTRAL[500]}; padding: {theme.SPACE_4}px;"
            " border: none;")
        mp.addWidget(self.measured_empty)
        self.spec = WB.SpecPanel()
        mp.addWidget(self.spec, stretch=1)
        # The full text report (and where it was saved) — one click away.
        self.meas_box = QWidget()
        meas_l = QVBoxLayout(self.meas_box)
        meas_l.setContentsMargins(12, 4, 12, 8)
        meas_l.setSpacing(theme.SPACE_1)
        self.full_toggle = self.button(i18n.t("Full report  ▸"), "secondary",
                                       small=True, on_click=self._toggle_full)
        meas_l.addWidget(self.full_toggle)
        self.full_box = QWidget()
        fb = QVBoxLayout(self.full_box)
        fb.setContentsMargins(0, 0, 0, 0)
        self.meas_view = QPlainTextEdit()
        self.meas_view.setReadOnly(True)
        self.meas_view.setMinimumHeight(180)
        fb.addWidget(self.meas_view)
        self.files_label = QLabel("")
        self.files_label.setWordWrap(True)
        self.files_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 12.5px; border: none;")
        fb.addWidget(self.files_label)
        self.full_box.setVisible(False)
        meas_l.addWidget(self.full_box)
        self.meas_box.setVisible(False)
        mp.addWidget(self.meas_box)

        # Back-solve the K-factor: the shop already knows the true flat
        # size of a part they've cut before (from a past job, or a
        # fabricator's own reference sheet) — this turns that one known
        # number into the K-factor that reproduces it, instead of asking
        # them to guess-and-check against Prism's default. Only appears
        # once something has actually been measured and unfolded.
        self.kfit_box = QGroupBox(i18n.t(
            "Know a part's real flat size? Back-solve the K-factor"))
        kfit_v = QVBoxLayout(self.kfit_box)
        kfit_v.setSpacing(theme.SPACE_2)
        kfit_note = QLabel(i18n.t(
            "Pick the part, say which side you know (from a past job or "
            "the fabricator's own sheet) and its true length — Prism works "
            "out the K-factor that would have produced exactly that."))
        kfit_note.setWordWrap(True)
        kfit_note.setStyleSheet(f"color: {theme.NEUTRAL[700]}; font-size: 12px;")
        kfit_v.addWidget(kfit_note)
        kfit_row = QHBoxLayout()
        self.kfit_part_combo = QComboBox()
        kfit_row.addWidget(self.kfit_part_combo, stretch=1)
        self.kfit_axis_combo = QComboBox()
        self.kfit_axis_combo.addItem(i18n.t("Width"), "w")
        self.kfit_axis_combo.addItem(i18n.t("Height"), "h")
        kfit_row.addWidget(self.kfit_axis_combo)
        self.kfit_target_edit = QLineEdit()
        self.kfit_target_edit.setPlaceholderText(i18n.t("true size, mm"))
        self.kfit_target_edit.setMaximumWidth(100)
        kfit_row.addWidget(self.kfit_target_edit)
        kfit_row.addWidget(self.button(i18n.t("Solve"), "secondary",
                                       small=True, on_click=self._kfit_solve))
        kfit_v.addLayout(kfit_row)
        result_row = QHBoxLayout()
        self.kfit_result = QLabel("")
        self.kfit_result.setWordWrap(True)
        result_row.addWidget(self.kfit_result, stretch=1)
        self.kfit_use_btn = self.button(i18n.t("Use this K-factor"),
                                        "secondary", small=True,
                                        on_click=self._kfit_apply)
        self.kfit_use_btn.setVisible(False)
        result_row.addWidget(self.kfit_use_btn)
        kfit_v.addLayout(result_row)
        self._kfit_solved: float | None = None
        self.kfit_box.setVisible(False)
        mp.addWidget(self.kfit_box)
        self.out_stack.addWidget(measured_page)

        # Answer — what the AI drew, suggested or planned.
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setFrameShape(QFrame.NoFrame)
        self.result.setPlaceholderText(
            i18n.t("Everything done with this part — drafts, questions, edits — "
                   "builds up here as one chat."))
        answer_page = QWidget()
        ap = QVBoxLayout(answer_page)
        ap.setContentsMargins(0, 0, 0, 0)
        ap.setSpacing(0)
        # The finished chat is a page of cards; the plain box is for the live
        # text a run writes while it is still going.
        self.chat = WB.ChatView()
        self.chat_stack = QStackedWidget()
        self.chat_stack.addWidget(self.chat)
        self.chat_stack.addWidget(self.result)
        self.chat_stack.setCurrentWidget(self.result)
        ap.addWidget(self.chat_stack, stretch=1)
        # Carry on in the window: a follow-up, or "Build this".
        self.composer = WB.Composer(MODEL_CHOICES)
        self.composer.set_agent(self.cfg.get("step_ask_model", "Groq"))
        self.composer.send.connect(self._composer_send)
        self.composer.build.connect(self._composer_build)
        self.composer.hide()
        ap.addWidget(self.composer)
        self.out_stack.addWidget(answer_page)

        # Plan — the steps Edit proposed, for reading.
        self.plan_panel = WB.PlanPanel()
        self.plan_panel.set_plan(None)
        self.plan_panel.build_clicked.connect(self._confirm_build)
        self.plan_panel.skip_clicked.connect(self._skip_build)
        self.plan_panel.refine_clicked.connect(self._refine_request)
        self.plan_panel.open_review.connect(self._open_review_page)
        self.out_stack.addWidget(self.plan_panel)

        # Files — everything written for these models, named after them.
        self.files_panel = WB.FilesPanel()
        self.files_panel.open_folder.connect(self._open_folder)
        self.files_panel.change_folder.connect(self._pick_root)
        self.out_stack.addWidget(self.files_panel)

        # The one button a person must press always names the action it is
        # about to take — never a generic "Generate" they have to trust a
        # radio choice above it to interpret correctly.
        for radio in self._action_buttons.values():
            radio.toggled.connect(
                lambda checked: self._sync_generate_label() if checked
                else None)
            radio.toggled.connect(
                lambda checked: self._sync_action_ui() if checked else None)
        self._sync_opt_label()
        self._sync_action_ui()
        self._refresh_runs()
        self._render_models()
        self._set_canvas()
        self._refresh_files()

        if attachments:
            self._on_files_added([a["path"] for a in attachments])

    # ── the workbench's own small pieces ─────────────────────────────────

    def _toggle_options(self):
        """The options popover, under the top bar's button."""
        if self.opt_box.isVisible():
            self.opt_box.hide()
            return
        pos = self.opt_toggle.mapToGlobal(
            self.opt_toggle.rect().bottomRight())
        self.opt_box.adjustSize()
        self.opt_box.move(pos.x() - self.opt_box.width(), pos.y() + 6)
        self.opt_box.show()

    def _sync_opt_label(self):
        names = {"metal": i18n.t("Sheet metal"), "plastic": i18n.t("Plastic")}
        self.opt_toggle.setText(names.get(self._mode(), self._mode()) + "  ▾")

    def _toggle_wide(self):
        """Give the results panel the room to read a chat in."""
        wide = self.right_card.width() < 500
        self.right_card.setFixedWidth(660 if wide else 420)
        self.wide_btn.setToolTip(i18n.t("Make this panel narrower") if wide
                                 else i18n.t("Make this panel wider"))

    def _toggle_full(self):
        on = self.full_box.isHidden()
        self.full_box.setVisible(on)
        self.full_toggle.setText(i18n.t("Full report  ▾") if on
                                 else i18n.t("Full report  ▸"))

    def _sync_action_ui(self):
        """Only what the chosen action needs: the question box and who
        answers it for Ask and Edit; the styled-copy tick for Draft."""
        action = self._action()
        self.action_blurb.setText(i18n.t(ACTION_SHORT[action]))
        for w in self._ask_only:
            w.setVisible(action in ("ask", "edit"))
        self.model_label.setText(i18n.t("Suggest the change with:")
                                 if action == "edit" else i18n.t("Answer with:"))
        self.ai_draft_cb.setVisible(action == "draft")
        if hasattr(self, "composer"):
            self._sync_composer()
        lay = self.step2.layout()
        if lay is not None:
            lay.invalidate()
            lay.activate()

    # models ---------------------------------------------------------------

    def _model_for(self, path: str):
        if path.startswith("run:"):
            return next((m for m in self.models
                         if m["out_dir"] == path[4:]), None)
        key = os.path.normcase(path)
        return next((m for m in self.models
                     if m["path"] and os.path.normcase(m["path"]) == key), None)

    def _current_path(self) -> str:
        if self._sel and any(os.path.normcase(p) == os.path.normcase(self._sel)
                             for p in self.paths):
            return self._sel
        if self.paths:
            return self.paths[0]
        if self.models:
            return "run:" + self.models[0]["out_dir"]
        return ""

    def _remove_model(self, path: str):
        """The ✕ on a model card: take an attached file back out, or let go
        of a model that came back with a reopened run."""
        if any(os.path.normcase(v["path"]) == os.path.normcase(path)
               for v in self._versions):
            # Taking a version off this screen — the file itself is untouched.
            self._versions = [v for v in self._versions
                              if os.path.normcase(v["path"]) != os.path.normcase(path)]
            if any(os.path.normcase(p) == os.path.normcase(path) for p in self.paths):
                self.ask.remove_path(path)
            self._render_models()
            return
        if path.startswith("run:"):
            self.models = [m for m in self.models if m["out_dir"] != path[4:]]
            if not self.paths and not self.models:
                self._session_key = ""
            self._refresh_chat()
            self._render_models()
            self._refresh_files()
            self._set_canvas()
            return
        self.ask.remove_path(path)

    # deleting: a chat from History, or the files Prism made for a model ------

    def _confirm(self, text: str, info: str, ok: str) -> bool:
        """Ask before anything is deleted. Cancel is the default."""
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("STEP"))
        box.setIcon(QMessageBox.Warning)
        box.setText(text)
        box.setInformativeText(info)
        yes = box.addButton(ok, QMessageBox.DestructiveRole)
        cancel = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        box.exec()
        return box.clickedButton() is yes

    def _folder_for(self, path: str, session: dict | None = None) -> str:
        """The folder Prism made for the model on this card — or ''. Only a
        folder that is safe to delete is ever offered."""
        folder = ""
        m = self._model_for(path) if path else None
        if m is not None:
            folder = m.get("out_dir") or ""
        elif path:
            want = os.path.normcase(os.path.abspath(path))
            for item in (session or self._current_session() or {}).get("runs", []):
                for rm in ((item["rec"].get("step") or {}).get("models") or []):
                    for field in ("path", "modified"):
                        if rm.get(field) and os.path.normcase(
                                os.path.abspath(rm[field])) == want:
                            folder = rm.get("out_dir") or ""
        return self._safe_model_dir(folder)

    def _safe_model_dir(self, folder: str) -> str:
        """`folder` if it is a real folder exactly one level inside the
        Prism Step folder and holds none of the files attached here — else ''.
        Nothing outside what Prism itself made can be deleted through this."""
        if not folder or os.path.islink(folder) or not os.path.isdir(folder):
            return ""
        try:
            root = os.path.realpath(self._root())
            real = os.path.realpath(folder)
        except OSError:
            return ""
        if os.path.dirname(real) != root:
            return ""
        for p in self.paths:
            if os.path.realpath(p).startswith(real + os.sep):
                return ""
        return real

    def _delete_model_files(self, path: str):
        if self._busy:
            self.status.setText(i18n.t(
                "A run is still going — delete files once it finishes."))
            return
        folder = self._folder_for(path)
        if not folder:
            self._notify_error(i18n.t(
                "Prism will only delete the folder it made inside your STEP "
                "folder — this one is somewhere else."))
            return
        count = sum(len(f) for _r, _d, f in os.walk(folder))
        name = os.path.basename(folder)
        if not self._confirm(
                i18n.t("Delete the files Prism made for {name}?")
                .replace("{name}", name),
                i18n.t("This deletes the folder “{folder}” and the {n} files "
                       "in it — the drawing sheet, the Excel sheet and any "
                       "edited copies. Your original STEP file is not "
                       "touched. This cannot be undone.")
                .replace("{folder}", folder).replace("{n}", str(count)),
                i18n.t("Delete these files")):
            return
        try:
            shutil.rmtree(folder)
        except OSError as exc:
            self._notify_error(i18n.t("Could not delete {folder}: {why}")
                               .replace("{folder}", folder).replace("{why}", str(exc)))
            return
        self.models = [m for m in self.models
                       if os.path.realpath(m.get("out_dir") or "") != folder]
        self._versions = [v for v in self._versions if os.path.exists(v["path"])]
        if not self.paths and not self.models:
            self._session_key = ""
        self._refresh_chat()
        self._render_models()
        self._refresh_files()
        self._set_canvas()
        self.status.setText(i18n.t("Deleted {n} files in {name}.")
                            .replace("{n}", str(count)).replace("{name}", name))

    def _delete_chat(self, key: str):
        if self._busy:
            self.status.setText(i18n.t(
                "A run is still going — delete a chat once it finishes."))
            return
        session = next((x for x in self._sessions() if x["key"] == key), None)
        if session is None:
            return
        n = len(session["runs"])
        if not self._confirm(
                i18n.t("Delete the chat about {name}?").replace("{name}", session["name"]),
                i18n.t("This removes the chat and its {n} from History. "
                       "The files Prism made — sheets, Excel, edited copies — "
                       "stay where they are.").replace(
                    "{n}", i18n.t("1 run") if n == 1
                    else i18n.t("{n} runs").replace("{n}", str(n))),
                i18n.t("Delete this chat")):
            return
        gone, refused = DATA.delete_runs(
            self.cfg, [r["path"] for r in session["runs"]])
        if key == self._session_key:
            self._session_key, self._live, self._versions = "", None, []
            self.models, self._pending, self._awaiting = [], None, False
            self.paths = []
            self.ask.clear_files()
            self.plan_panel.set_plan(None)
            self._refresh_chat()
            self._render_models()
            self._refresh_files()
            self._set_canvas()
        else:
            self._refresh_runs()
        if refused:
            self._notify_error(i18n.t("{n} runs could not be deleted.")
                               .replace("{n}", str(len(refused))))
        else:
            self.status.setText(i18n.t("Deleted the chat about {name}.")
                                .replace("{name}", session["name"]))

    def _select_model(self, path: str):
        if any(os.path.normcase(v["path"]) == os.path.normcase(path)
               for v in self._versions):
            self._choose_version(path)
            return
        self._sel = path
        self._render_models()
        self._set_canvas()

    def _render_models(self):
        items = []
        shown = set()
        cur = self._current_path()
        if self._versions:
            # A chat about one part: the original and each edited copy, to
            # carry on from. The one being worked on is marked.
            known = set()
            sess = self._current_session()
            for v in self._versions:
                known.add(os.path.normcase(v["path"]))
                here = os.path.normcase(v["path"]) == os.path.normcase(cur)
                edited = v["kind"] == "edited"
                when = time.strftime("%d %b %H:%M", time.localtime(v["stamp"])) \
                    if v.get("stamp") else ""
                items.append({
                    "path": v["path"], "name": v["label"],
                    "sub": (i18n.t("edited copy") if edited
                            else i18n.t("original")) + (f" · {when}" if when else ""),
                    "status": i18n.t("working on this") if here
                    else i18n.t("carry on from this"),
                    "tone": "ok" if here else ("warn" if edited else "info"),
                    "folder": self._folder_for(v["path"], sess)})
            for p in self.paths:
                if os.path.normcase(p) not in known:
                    items.append(self._model_item(p, self._model_for(p)))
            self.model_list.set_items(items, cur)
            self.models_card.set_count(len(items))
            return
        for p in self.paths:
            m = self._model_for(p)
            if m is not None:
                shown.add(id(m))
            items.append(self._model_item(p, m))
        # Models that came back with a reopened run have no file attached to
        # them (yet) — they are still listed, so the run reads as it did.
        for m in self.models:
            if id(m) in shown or any(
                    os.path.normcase(m["path"] or "?") == os.path.normcase(p)
                    for p in self.paths):
                continue
            items.append(self._model_item("", m))
        self.model_list.set_items(items, cur)
        self.models_card.set_count(len(items))

    def _model_item(self, p: str, m) -> dict:
        if m is not None:
            rep = m["report"]
            if rep.get("_stub"):
                sub, status, tone = i18n.t("from a past run"), i18n.t("opened"), "info"
            else:
                ox, oy, oz = rep["overall_mm"]
                sub = (f"{len(rep['parts'])} {i18n.t('parts')} · "
                       f"{ox:g}×{oy:g}×{oz:g}")
                status, tone = i18n.t("measured"), "ok"
            name = os.path.basename(p) if p else rep["file"]
            path = p or ("run:" + m["out_dir"])
        else:
            try:
                sub = f"{os.path.getsize(p) / 1024:,.0f} KB"
            except OSError:
                sub = ""
            busy = self._busy and self._worker is not None
            status, tone = ((i18n.t("measuring…"), "info") if busy
                            else (i18n.t("waiting"), "warn"))
            name, path = os.path.basename(p), p
        return {"path": path, "name": name, "sub": sub, "status": status,
                "tone": tone, "folder": self._folder_for(path)}

    # history: every past STEP run, one click to reopen -----------------------

    def _records(self) -> list:
        """Every STEP run on this machine, as {"path", "stamp", "rec"}."""
        try:
            runs = DATA.recent_runs(self.cfg, 200) or []
        except Exception:                               # noqa: BLE001
            return []
        out = []
        for run in runs:
            if not str(run.get("title", "")).startswith("STEP"):
                continue
            path = run.get("path", "")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    rec = json.load(f) or {}
            except (OSError, ValueError):
                continue
            if rec.get("step"):
                out.append({"path": path, "stamp": run.get("stamp", 0),
                            "rec": rec, "when": run.get("when", "")})
        return out

    def _sessions(self) -> list:
        return SES.build_sessions(self._records())

    def _step_runs(self) -> list:
        """One row per CHAT (a part and its edited versions), newest first."""
        items = []
        for sess in self._sessions()[:40]:
            last = sess["runs"][-1]
            n = len(sess["runs"])
            action = (sess["actions"][-1] or "").capitalize()
            items.append({
                "path": sess["key"],
                "action": action if action in ("Draft", "Ask", "Edit") else "STEP",
                "text": sess["name"],
                "when": (i18n.t("{n} runs").replace("{n}", str(n)) if n > 1
                         else i18n.t("1 run")) + " · " + last.get("when", ""),
                "tip": sess["name"] + " — " + ", ".join(
                    dict.fromkeys(a.capitalize() for a in sess["actions"] if a))})
        return items

    def _refresh_runs(self):
        self.history.set_items(self._step_runs(), self._session_key)

    def load_run(self, path: str):
        """Open the chat a run belongs to (Prism's History and the Home
        screen's recent activity hand over a run's own path)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                rec = json.load(f) or {}
        except (OSError, ValueError):
            self.status.setText(i18n.t("That run could not be read."))
            return
        info = rec.get("step") or {}
        key = str(info.get("chat") or "")
        if not key:
            # A run saved before chats had ids: the chat it sits in is found
            # by the run itself.
            key = next((x["key"] for x in self._sessions()
                        if any(r["path"] == path for r in x["runs"])), "")
        self.load_session(key, focus=path)

    def load_session(self, key: str, focus: str = ""):
        """Reopen a chat: everything done to one part and its edited copies,
        as one thread — with the original and each edited file offered to
        carry on from. No other window opens."""
        if self._busy:
            self.status.setText(i18n.t(
                "A run is still going — open another once it finishes."))
            return
        session = next((x for x in self._sessions() if x["key"] == key), None)
        if session is None and focus:
            self._apply_record(focus)
            return
        if session is None:
            return
        runs = session["runs"]
        latest = next((r for r in runs if r["path"] == focus), runs[-1])
        self._session_key = key
        self._apply_record(latest["path"], rec=latest["rec"])
        self._versions = self._single_part_versions(session)
        self._set_chat(session)
        if self._versions:
            self._choose_version(self._versions[-1]["path"], quiet=True)
        self._refresh_runs()
        self._render_models()
        self._show_tab(1)
        n = len(self._versions)
        self.status.setText(
            i18n.t("Opened the chat about {name}.").replace("{name}", session["name"])
            + (" " + i18n.t("Choose which file to carry on from on the left.")
               if n > 1 else ""))

    def _set_chat(self, session: dict | None, keep_live: bool = False):
        text = SES.chat_text(session) if session else ""
        if session or not keep_live:
            self.result.setPlainText(text)
        turns = SES.chat_turns(session) if session else []
        if self._live:
            turns = turns + [self._live]
        if turns:
            self.chat.set_turns(turns)
            self.chat_stack.setCurrentWidget(self.chat)
        else:
            self.chat.set_turns([])
            self.chat_stack.setCurrentWidget(self.result)
        self._tab_label(1, i18n.t("Chat"), len(turns), zero=True)
        self._sync_composer()

    def _show_live(self):
        self._set_chat(self._current_session(), keep_live=True)

    def _sync_composer(self):
        """The follow-up box is there when there is an answer to follow up on
        and the measurement behind it."""
        m = self._current or (self.models[0] if self.models else None)
        key = f"ask · {m['report']['stem']}" if m and m.get("report") else ""
        ok = bool(m and not m["report"].get("_stub") and key
                  and self._responses.get(key))
        self.composer.setVisible(ok)
        if ok:
            # Ask: the one button is "Ask". Only when the person is changing
            # the model does a second one — "Make a change" — appear.
            edit_mode = self._action() == "edit"
            self.composer.set_mode(edit_mode and bool(m.get("path")))
            self.composer.set_agent(self._stage_agents_map.get(key)
                                    or self.cfg.get("step_ask_model", "Groq"))

    def _refresh_chat(self, keep_live: bool = False):
        """Show the chat this screen is in. It starts empty when a file is
        attached — no matter what was done with that file before — and gains
        a card for each thing done here. Take every file away and it goes;
        reopen a chat from History to carry on in an old one."""
        session = next((x for x in self._sessions()
                        if x["key"] == self._session_key), None) \
            if self._session_key else None
        if session is None:
            self._versions = []
            self._set_chat(None, keep_live=keep_live)
            self._refresh_runs()
            return
        self._versions = self._single_part_versions(session)
        self._set_chat(session)
        self._refresh_runs()

    @staticmethod
    def _single_part_versions(session: dict) -> list:
        """The original and edited copies to carry on from — only when the
        chat is about ONE part. A chat that holds several parts (files attached
        together) has no single "original" to pick."""
        versions = SES.versions_of(session)
        if len({SES.lineage(v["path"]) for v in versions}) > 1:
            return []
        return versions

    def _choose_version(self, path: str, quiet: bool = False):
        """Carry on from this file — the original, or an edited copy."""
        path = os.path.abspath(path)
        self.ask.clear_files()
        self.paths = [path]
        self.ask.add_paths([path], emit=False)
        self._sel = path
        stored = None
        for item in reversed((self._current_session() or {}).get("runs", [])):
            for rm in ((item["rec"].get("step") or {}).get("models") or []):
                if rm.get("path") and os.path.abspath(rm["path"]) == path \
                        and rm.get("report"):
                    stored = self._model_from_record(rm, item["rec"].get("step") or {})
                    break
            if stored:
                break
        self.models = [stored] if stored else []
        self._current = stored
        self.step2.setVisible(True)
        self.generate_btn.setEnabled(True)
        self.generate_btn.setToolTip("")
        self._sync_generate_label()
        if stored:
            self.meas_box.setVisible(True)
            self.measured_empty.setVisible(False)
            self._refresh_spec()
            self._fill_kfit_parts(self.models)
        else:
            self.spec.set_reports([])
            self.meas_box.setVisible(False)
            self.measured_empty.setVisible(True)
            self.kfit_box.setVisible(False)
        self._refresh_files()
        self._render_models()
        self._set_canvas()
        if not quiet:
            self.status.setText(i18n.t("Carrying on from {name}.").replace(
                "{name}", os.path.basename(path)))

    def _chat_has_runs(self) -> bool:
        return bool(self._session_key and self._current_session())

    def _current_session(self):
        return next((x for x in self._sessions()
                     if x["key"] == self._session_key), None)

    def _apply_record(self, path: str, rec: dict | None = None):
        """Put one run's question, answer, plan, model and files on screen."""
        if not path and rec is None:
            return
        if self._busy:
            self.status.setText(i18n.t(
                "A run is still going — open another once it finishes."))
            return
        if rec is None:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    rec = json.load(f) or {}
            except (OSError, ValueError):
                self.status.setText(i18n.t("That run could not be read."))
                return
        info = rec.get("step") or {}
        if not info:
            return
        self._loaded_run = path
        self._run_path = path
        self._last_action = info.get("action") or ""
        self._followups = list(info.get("followups") or [])
        self._stage_agents_map = dict(info.get("agents") or {})
        self._live, self._pending, self._awaiting = None, None, False
        action = info.get("action") if info.get("action") in ACTIONS_BY_KEY else "draft"
        self._action_buttons[action].setChecked(True)
        self.ask.set_text(info.get("question", ""))
        if info.get("mode") in list(self.sf.MODES):
            self.mode_combo.setCurrentText(info["mode"])
        self._responses = {k: list(v) for k, v in (rec.get("responses") or {}).items()}
        self._links = dict(rec.get("links") or {})
        self._notes = []
        self.result.clear()
        self.plan_panel.set_plan(None)
        self._tab_label(1, i18n.t("Chat"), 0, zero=True)
        self._tab_label(2, i18n.t("Plan"))
        self.meas_view.clear()
        # The models: attached again only if their file is still where it was.
        self.ask.clear_files()
        self.paths = []
        self.models = []
        wanted = []
        for rm in info.get("models") or []:
            mp = rm.get("path") or ""
            if mp and os.path.exists(mp):
                wanted.append(os.path.abspath(mp))
            self.models.append(self._model_from_record(rm, info))
        if wanted:
            self.paths = list(wanted)
            self.ask.add_paths(wanted, emit=False)
            for m in self.models:
                if m["path"]:
                    m["path"] = os.path.abspath(m["path"])
        self._sel = wanted[0] if wanted else ""
        self.step2.setVisible(True)
        self.generate_btn.setEnabled(bool(self.paths))
        self.generate_btn.setToolTip(
            "" if self.paths else i18n.t(
                "The model file is not stored with this run — attach it "
                "again to run something new."))
        self._sync_generate_label()
        self._current = self.models[0] if self.models else None
        # What the run produced.
        if self.models:
            self.meas_box.setVisible(True)
            self.measured_empty.setVisible(False)
            self.folder_btn.setEnabled(True)
            self._refresh_spec()
            self._fill_kfit_parts(self.models)
        stem = self.models[0]["report"]["stem"] if self.models else ""
        thread = self._load_conversation(self.models[0]) if self.models else []
        text = self._answer_text(rec, stem, thread)
        if text:
            self.result.setPlainText(text)
            self._tab_label(1, i18n.t("Chat"), 0, zero=True)
        plan_texts = (self._responses.get(f"plan · {stem}") or []) if stem else []
        if plan_texts:
            plan, _why = self.sf.parse_plan(plan_texts)
            if plan:
                self.plan_panel.set_plan(plan, self._stage_agents_map.get(f"plan · {stem}", ""))
                self._tab_label(2, i18n.t("Plan"),
                                len(plan["changes"]) + len(plan["advice"]))
        self.open_btn.setVisible(bool(self._links))
        self.open_btn.setEnabled(bool(self._links))
        self._refresh_files()
        self._render_models()
        self._set_canvas()
        self._refresh_runs()
        self._show_tab(1 if text else 0)
        self._sync_composer()
        self.status.setText(i18n.t("Opened a past run.") + (
            "" if self.paths else " " + i18n.t(
                "The model itself is not stored with it — the answer, "
                "sheet and files are.")))

    def _model_from_record(self, rm: dict, info: dict) -> dict:
        """A model as a past run left it: its folder, its sheet, its files
        and — for runs saved since the screen was rebuilt — its measurement."""
        file = rm.get("file") or ""
        stem = os.path.splitext(file)[0]
        out_dir = rm.get("out_dir") or ""
        names = self.sf.names(stem)
        png = os.path.join(out_dir, names["png"])
        if not os.path.exists(png) and os.path.isdir(out_dir):
            png = next((os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
                        if n.lower().endswith(".png") and "drawing sheet" in n.lower()
                        and "after" not in n.lower()), "")
        xlsx = os.path.join(out_dir, names["xlsx"])
        report = rm.get("report")
        if not report:
            report = {"file": file, "stem": stem, "mode": info.get("mode", ""),
                      "overall_mm": (0, 0, 0), "parts": [], "warnings": [],
                      "_stub": True}
        else:
            report = dict(report)
            report["overall_mm"] = tuple(report.get("overall_mm") or (0, 0, 0))
            for part in report.get("parts", []):
                if "size_mm" in part:
                    part["size_mm"] = tuple(part["size_mm"])
        return {"path": rm.get("path") or "", "report": report,
                "out_dir": out_dir,
                "drawn": {"png": png if png and os.path.exists(png) else ""},
                "xlsx": xlsx if os.path.exists(xlsx) else "",
                "modified": rm.get("modified", "")}

    @staticmethod
    def _answer_text(rec: dict, stem: str, thread: list) -> str:
        """The question and the answer(s), as one readable block."""
        if thread:
            return "\n\n".join(f"{who.upper()}\n{what}" for who, what in thread)
        texts = (rec.get("responses") or {}).get(f"ask · {stem}") or []
        question = ((rec.get("step") or {}).get("question") or "").strip()
        body = "\n\n".join(t for t in texts if t and t.strip())
        if not body:
            return ""
        return (f"YOU\n{question}\n\n" if question else "") + body

    def enter(self):
        """The screen was opened from the rail: pick up the latest config and
        runs, and keep whatever the person had on it."""
        self._refresh_runs()

    def shutdown(self):
        """Stop and join every worker — the same wind-down closeEvent does,
        for when this is a screen and no window is closing."""
        for worker in (self._worker, self._agent_worker, self._ask_worker,
                       self._apply_worker, self._followup_ask_worker,
                       self._followup_agent_worker):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)

    def _close_clicked(self):
        if self._embedded:
            self.leave_requested.emit()
        else:
            self.reject()

    # canvas ---------------------------------------------------------------

    def _set_canvas(self):
        """What the big area shows: the invitation to attach, the models
        that are waiting, the measuring progress, or — once measured —
        Prism's own drawing sheet for the model picked on the left."""
        if not self.paths and not self.models:
            self.canvas.show_empty()
            return
        if self._busy and self._worker is not None and not self.models:
            name = os.path.basename(self._current_path())
            self.canvas.show_measuring(name, self._measure_lines)
            return
        m = self._model_for(self._current_path()) if self.models else None
        if m is not None:
            png = (m.get("drawn") or {}).get("png")
            if png and os.path.exists(png) and self.canvas.show_sheet(
                    png, i18n.t("Drawing sheet") + " · " + m["report"]["stem"]):
                self._preview_ok = True
                return
            self._preview_ok = False
            self.canvas.show_note(
                i18n.t("Measured"),
                i18n.t("No drawing sheet was made for this model — the "
                       "numbers are on the right."))
            return
        names = ", ".join(os.path.basename(p) for p in self.paths[:3])
        more = len(self.paths) - 3
        self.canvas.show_waiting(names + (f" +{more}" if more > 0 else ""))

    def _show_preview(self, results: list):
        self._preview_ok = False
        self._set_canvas()

    # right-hand panes --------------------------------------------------------

    def _show_tab(self, index: int):
        self.out_tabs.set_current(index)
        self.out_stack.setCurrentIndex(index)

    def _tab_label(self, index: int, text: str, count: int = 0,
                   zero: bool = False):
        try:
            self.out_tabs._buttons[index].setText(
                f"{text}  {count}" if (count or zero) else text)
        except (AttributeError, IndexError):
            pass

    def _k_note(self) -> str:
        return i18n.t("yours") if self._k_factor() else i18n.t("default")

    def _refresh_spec(self):
        self.spec.set_reports([m["report"] for m in self.models], self._k_note())

    def _refresh_files(self):
        """Everything written for these models — the files are real; this
        only lists what is on disk."""
        files = []
        for m in self.models:
            folder = m["out_dir"]
            for base, _dirs, names in os.walk(folder):
                if os.path.relpath(base, folder).count(os.sep) > 1:
                    continue
                files += [os.path.join(base, n) for n in sorted(names)]
            try:
                conv = self._conversation_path(m)
            except Exception:                           # noqa: BLE001
                conv = ""
            if conv and os.path.exists(conv):
                files.append(conv)
        self.files_panel.set_files(self._root(), files, bool(self.models))
        self._tab_label(3, i18n.t("Files"), len(files))
        return files

    def _toast_saved(self, count: int):
        self.canvas.toast(
            i18n.t("✓ {n} files saved to {folder}")
            .replace("{n}", str(count))
            .replace("{folder}", os.path.basename(self.models[0]["out_dir"])
                     if self.models else ""),
            [(i18n.t("Open folder"), self._open_folder),
             (i18n.t("View files"), lambda: self._show_tab(3))])

    # dropping a model anywhere on the window ---------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self._on_files_added(paths)
            event.acceptProposedAction()

    # ── where the files go ───────────────────────────────────────────────

    def _root_default(self) -> str:
        """Where STEP work goes when nobody chose: the engine's own default,
        except in a dev build, whose "~" is a hidden data folder."""
        import output_folders
        return output_folders.chosen({}, "step", self.sf.DEFAULT_OUT_ROOT)

    def _root(self) -> str:
        return self.cfg.get("step_out_dir") or self._root_default()

    def _root_caption(self) -> str:
        return (i18n.t("Files go to {folder} — a folder per model, every "
                       "file named after the model.")
                .replace("{folder}", self._root()))

    def _pick_root(self) -> bool:
        path = QFileDialog.getExistingDirectory(
            self, i18n.t("Where should Prism keep the files for your STEP "
                         "models?"), self._root())
        if not path:
            return False
        self.cfg["step_out_dir"] = path
        CB.config.save(self.cfg)
        self.root_label.setText(self._root_caption())
        self.root_default_btn.setVisible(True)
        return True

    def _use_default_root(self):
        self.cfg["step_out_dir"] = ""
        CB.config.save(self.cfg)
        self.root_label.setText(self._root_caption())
        self.root_default_btn.setVisible(False)

    def _ensure_root(self) -> bool:
        """The question the owner asked for: where do all the files for a
        model go? Asked once — the answer is kept in cfg — and only at the
        moment it matters, the first Generate. Choosing the Desktop stores
        the default explicitly, so the question is not asked again."""
        if self.cfg.get("step_out_dir"):
            return True
        box = QMessageBox(self)
        box.setWindowTitle(i18n.t("STEP"))
        box.setIcon(QMessageBox.Question)
        box.setText(i18n.t("Where should Prism keep the files for your STEP "
                           "models?"))
        box.setInformativeText(i18n.t(
            "Prism makes a folder named after each model inside it, and every "
            "file in that folder carries the model's name. You can change "
            "this any time from the Options box."))
        choose = box.addButton(i18n.t("Choose a folder…"),
                               QMessageBox.AcceptRole)
        desktop = box.addButton(i18n.t("Use the Desktop"),
                                QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(choose)
        box.exec()
        clicked = box.clickedButton()
        if clicked is choose:
            return self._pick_root()
        if clicked is desktop:
            self.cfg["step_out_dir"] = self._root_default()
            CB.config.save(self.cfg)
            self.root_label.setText(self._root_caption())
            self.root_default_btn.setVisible(True)
            return True
        return False

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        # Stored as AskPanel itself stores them — abspath'd — so this
        # dialog's own list (what Generate actually measures) and the
        # chip's path (what file_removed hands back on removal) are always
        # the same string. A raw, un-normalised compare let a Windows
        # QFileDialog's forward-slash path survive here unmatched against
        # the backslashed, abspath'd one file_removed later emits — the
        # chip vanished but the file stayed in self.paths and was measured
        # and billed anyway.
        have = {os.path.normcase(sp) for sp in self.paths}
        models, other = [], []
        for p in paths:
            if p and p.lower().endswith(MODEL_EXTS):
                ap = os.path.abspath(os.path.expanduser(p))
                if os.path.normcase(ap) not in have:
                    have.add(os.path.normcase(ap))
                    models.append(ap)
            elif p:
                other.append(os.path.basename(p))
        skipped = (i18n.t("Only .step / .stp models are measured — skipped: ")
                   + ", ".join(other)) if other else ""
        if not models:
            if skipped:
                self.status.setText(skipped)
            return
        if self._chat_has_runs():
            # This chat has been worked in; a new file is a new part, so it
            # gets a new, empty chat — the old one stays in History.
            self.ask.clear_files()
            self.paths = []
            self.models = []
            self._versions = []
            self._session_key = ""
        self.paths += models
        self.ask.add_paths(models, emit=False)
        self.step2.setVisible(True)      # the file is in; now the ask
        self.generate_btn.setEnabled(True)
        self.generate_btn.setToolTip("")
        self._sel = models[0]
        if not self._session_key:
            # A file with no chat open starts a new one — empty, whatever was
            # done with this file before.
            self._session_key = uuid.uuid4().hex[:10]
        self._refresh_chat()
        self._render_models()
        self._set_canvas()
        n = len(self.paths)
        self.status.setText(
            (i18n.t("{n} models attached. ").format(n=n) if n > 1
             else i18n.t("Model attached. "))
            + i18n.t("Now say what you want done with it, then press "
                     "Generate.")
            + (f"  {skipped}" if skipped else ""))

    def _on_file_removed(self, path: str):
        """The chip's own 'x' only ever touched AskPanel's private list —
        this keeps the dialog's real one (what Generate actually measures)
        in step with what the person sees attached. Matched by normcase,
        not exact string equality — AskPanel already abspath's everything
        it stores, but a case-only difference (Windows' filesystem is
        case-insensitive) would otherwise still slip past."""
        key = os.path.normcase(path)
        self.paths = [p for p in self.paths if os.path.normcase(p) != key]
        self.step2.setVisible(bool(self.paths))
        self.generate_btn.setEnabled(bool(self.paths))
        if not self.paths and not self.models:
            self._session_key = ""
        self._refresh_chat()
        self._render_models()
        self._set_canvas()
        n = len(self.paths)
        self.status.setText(
            i18n.t("{n} models attached.").format(n=n) if n else
            i18n.t("No model attached yet."))

    def _action(self) -> str:
        for key, radio in self._action_buttons.items():
            if radio.isChecked():
                return key
        return "draft"

    def _sync_generate_label(self):
        label, icon = ACTION_BUTTON[self._action()]
        self.generate_btn.setText(i18n.t(label))
        icons.button_icon(self.generate_btn, icon, 15, theme.CARD)

    def _mode(self) -> str:
        return self.mode_combo.currentText().strip() or "metal"

    def _chosen_model(self) -> str:
        return self.model_combo.currentData() or "Groq"

    def _k_factor(self) -> float:
        """0.0 means "use Prism's default" — a blank box, or anything
        that doesn't parse as a plausible K-factor (0 to 1; it is a
        fraction of the sheet's thickness, never more than one whole
        thickness), falls back to that rather than silently unfolding
        with whatever a typo left in the box."""
        text = self.k_edit.text().strip()
        if not text:
            return 0.0
        try:
            k = float(text)
        except ValueError:
            return 0.0
        return k if 0.0 < k < 1.0 else 0.0

    # ── generate: measure, then the chosen action per model ────────────

    def _agents(self) -> dict:
        return CB.config.active_agents(self.cfg) or {}

    # Draft is ChatGPT's job, full stop. Not "the configured visual tool",
    # not a fallback to whichever image model answers: its image model is
    # the one that draws a dimension sheet well from a numbers-only brief,
    # and a second, differently-wrong sheet from another tool is not a
    # rescue. The stage runs with failover off for the same reason.
    ARTIST = "ChatGPT"

    def _artist(self) -> str:
        return self.ARTIST

    def _planner(self) -> str:
        agents = self._agents()
        return next((agents[s] for s in ("brains", "content", "research")
                     if agents.get(s)), "")

    def _generate(self):
        if not self.paths:
            return
        action = self._action()
        question = self.ask.text().strip()
        if action in ("ask", "edit"):
            if not question:
                self._notify_error(i18n.t(
                    "Say what you want to know or change — type the "
                    "question in the box above."))
                self.ask.setFocus()
                return
            if self._chosen_model() == "Groq" and not self.cfg.get("api_key"):
                self._notify_error(i18n.t(
                    "Groq needs your key — add it in Settings, or pick "
                    "ChatGPT or Claude above instead."))
                return
        if (action == "edit" and self._chosen_model() != "Groq"
                and not self._planner()):
            self._notify_error(i18n.t(
                "Edit needs a reasoning tool to review the plan — open "
                "Agents and pick one for Reasoning first."))
            return
        if not self._ensure_root():
            return

        if not self._session_key:
            self._session_key = uuid.uuid4().hex[:10]
        self.cfg["step_mode"] = self._mode()
        self.cfg["step_k_factor"] = self.k_edit.text().strip()
        self.cfg["step_ai_draft"] = self.ai_draft_cb.isChecked()
        self.cfg["step_ask_model"] = self._chosen_model()
        try:
            CB.config.save(self.cfg)
        except Exception:                               # noqa: BLE001
            pass
        self.models = []
        self._responses, self._links, self._notes = {}, {}, []
        self._stage_agents_map = {}
        self.meas_view.clear()
        self.result.clear()
        self._measure_lines = []
        self._live, self._followups, self._thread = None, [], []
        self._pending, self._awaiting, self._run_path = None, False, ""
        self.chat_stack.setCurrentWidget(self.result)
        self.plan_panel.set_plan(None)
        self._tab_label(1, i18n.t("Chat"), 0, zero=True)
        self._tab_label(2, i18n.t("Plan"))
        self.progress.set_stages(_stages(action))
        self._set_busy(True, i18n.t(
            "Measuring — the model never leaves this machine…"), 0)
        self._worker = StepMeasureWorker(list(self.paths), self._mode(),
                                         self._root(), self._k_factor())
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_measured)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
        self._render_models()
        self._set_canvas()

    def _on_progress(self, line: str):
        self.meas_view.appendPlainText(f"   {line}")
        self._measure_lines.append(line.strip())
        self._set_canvas()

    def _on_measured(self, results: list):
        self.models = results
        blocks, files = [], []
        for m in results:
            report = m["report"]
            heading = (f"═══ {report['file']} ═══\n" if len(results) > 1
                       else "")
            blocks.append(heading + self.sf.report_text(report))
            files.append(m["out_dir"])
            drawn = m.get("drawn") or {}
            deliverables = [m.get("xlsx"), drawn.get("png"),
                            *drawn.get("flats", {}).values()]
            for path in deliverables:
                if path and os.path.exists(path):
                    try:
                        CB.config.save_artifact(path, os.path.basename(path),
                                                kind="step",
                                                task=report["file"])
                    except Exception:                   # noqa: BLE001
                        pass
        self.meas_view.setPlainText("\n\n".join(blocks))
        self.files_label.setText(
            i18n.t("Saved so every number can be checked → ")
            + "; ".join(files))
        self.meas_box.setVisible(True)
        self.measured_empty.setVisible(False)
        self._refresh_spec()
        self._show_tab(0)
        self.folder_btn.setEnabled(True)
        self._show_preview(results)
        files = self._refresh_files()
        self._toast_saved(len(files))
        self._fill_kfit_parts(results)
        self._queue = list(results)
        self._next()

    def _fill_kfit_parts(self, results: list):
        """Only the parts that actually unfolded to a flat pattern can
        have their K-factor back-solved — nothing to invert for a part
        with no flat size in the first place."""
        self.kfit_part_combo.clear()
        self.kfit_result.setText("")
        multi = len(results) > 1
        for i, m in enumerate(results):
            report = m["report"]
            for p in report["parts"]:
                if not p.get("flat"):
                    continue
                label = (f"{report['file']} — {p['name']}" if multi
                         else p["name"])
                self.kfit_part_combo.addItem(label, (i, p["name"]))
        self.kfit_box.setVisible(self.kfit_part_combo.count() > 0)

    def _kfit_solve(self):
        self.kfit_use_btn.setVisible(False)
        self._kfit_solved = None
        if self.kfit_part_combo.count() == 0:
            return
        idx = self.kfit_part_combo.currentIndex()
        model_i, part_name = self.kfit_part_combo.itemData(idx)
        axis = self.kfit_axis_combo.currentData()
        text = self.kfit_target_edit.text().strip()
        try:
            target = float(text)
        except ValueError:
            self.kfit_result.setText(i18n.t(
                "Enter the true size in millimetres first."))
            return
        report = self.models[model_i]["report"]
        k = self.sf.solve_k_factor(report, part_name, target, axis=axis)
        if k is None:
            self.kfit_result.setText(i18n.t(
                "That figure doesn't fit this part's own geometry — check "
                "the part, the side (width/height) and the number."))
            return
        self._kfit_solved = k
        self.kfit_result.setText(i18n.t(
            "K-factor {k} reproduces that size exactly.").replace(
            "{k}", f"{k:g}"))
        self.kfit_use_btn.setVisible(True)

    def _kfit_apply(self):
        if self._kfit_solved is None:
            return
        self.k_edit.setText(f"{self._kfit_solved:g}")
        self.kfit_result.setText(self.kfit_result.text() + "  " + i18n.t(
            "— now set as the Bend K-factor above; press Generate again to "
            "re-draw with it."))
        self.kfit_use_btn.setVisible(False)

    def _next(self):
        """The chosen action, one model at a time — an AI stage per model,
        in order, then the run is saved once."""
        if not self._queue:
            self._finish()
            return
        self._current = self._queue.pop(0)
        {"draft": self._draft, "ask": self._ask,
         "edit": self._ask}[self._action()](self._current)

    # ── draft ───────────────────────────────────────────────────────────

    def _draft(self, m: dict):
        report = m["report"]
        if not self.ai_draft_cb.isChecked():
            # Prism's own drawing sheet was already made in _on_measured —
            # that IS the deliverable now (Round 42: flat pattern + hole
            # positions marked on the drawing itself). Nothing left for an
            # AI to add unless the person actually asked for its copy.
            self._notes.append(f"{report['file']}: Prism's own drawing "
                               "sheet stands — ChatGPT's copy wasn't asked "
                               "for")
            self._next()
            return
        artist = self._artist()
        # Only Prism's OWN render travels — never the model. With no PNG
        # (no browser engine) the numbers in the brief carry it alone.
        files = []
        png = (m.get("drawn") or {}).get("png")
        if png and os.path.exists(png):
            try:
                files.append(CB.files.attach(png))
            except Exception:                           # noqa: BLE001
                pass
        self._made_files = []
        self._set_busy(True, i18n.t(
            "{agent} is drawing the dimensioned sheet for {file} — from "
            "the measured numbers only; the model stays here…")
            .replace("{agent}", artist).replace("{file}", report["file"]), 1)
        self._agent_worker = AutomationWorker(
            {}, self.cfg, files, f"STEP — draft sheet for {report['file']}",
            custom_stages=[("visual", artist, [self.sf.auto_brief(report)])],
            chatgpt_analysis=False, files_out=self._made_files,
            # A picture is the point: the engine's full image budget — and
            # ChatGPT only, no hand-off to another tool if it stumbles.
            image_stages={"visual"}, failover=False)
        self._agent_worker.done.connect(self._on_drafted)
        self._agent_worker.failed.connect(self._on_failed)
        self._agent_worker.start()

    def _on_drafted(self, responses: dict, links: dict):
        m = self._current
        report, out_dir = m["report"], m["out_dir"]
        self._links.update({f"{k} · {report['stem']}": v
                            for k, v in links.items()})
        kept = []
        for rec in self._made_files:
            src = rec.get("path", "") if isinstance(rec, dict) else str(rec)
            if not src or not os.path.exists(src):
                continue
            dest = os.path.join(out_dir, self.sf.ai_sheet_name(
                report["stem"], len(kept) + 1, os.path.splitext(src)[1]))
            try:
                shutil.copyfile(src, dest)
                kept.append(dest)
                CB.config.save_artifact(dest, os.path.basename(dest),
                                        kind="step", task=report["file"])
            except Exception:                           # noqa: BLE001
                pass
        texts = [t for t in (responses.get("visual") or []) if t.strip()]
        self._responses[f"draft · {report['stem']}"] = texts
        self._stage_agents_map[f"draft · {report['stem']}"] = self._artist()
        if kept:
            self._notes.append(f"{report['file']}: AI drawing sheet → "
                               + "; ".join(kept))
            self.result.appendPlainText(
                f"{report['file']} — AI drawing sheet saved:\n  "
                + "\n  ".join(kept))
        elif texts:
            self._notes.append(f"{report['file']}: no image came back — "
                               "the agent's words are saved with the run")
            self.result.appendPlainText(f"{report['file']} — {texts[0]}")
        else:
            self._notes.append(f"{report['file']}: the agent returned "
                               "nothing; Prism's own measured sheet stands")
        self._next()

    # ── ask / edit ──────────────────────────────────────────────────────

    def _ask(self, m: dict):
        report = m["report"]
        model = self._chosen_model()
        if model != "Groq":
            # Chosen over Groq's fast in-house call. If it can't answer,
            # retry the rest of FALLBACK_ORDER — never silently fall back
            # TO Groq, which is the thing being upgraded away from.
            self._model_chain = [model] + [t for t in FALLBACK_ORDER
                                           if t != model]
            self._ask_via_chain(m)
            return
        self._set_busy(True, i18n.t(
            "Asking Groq about {file} — the measured numbers and your "
            "question only; the model stays here…")
            .replace("{file}", report["file"]), 1)
        self._ask_worker = StepAskWorker(self.cfg, report,
                                         self.ask.text().strip())
        self._ask_worker.done.connect(self._on_suggested)
        self._ask_worker.failed.connect(self._on_failed)
        self._ask_worker.start()

    def _ask_via_chain(self, m: dict):
        report = m["report"]
        if not self._model_chain:
            self._on_failed(i18n.t(
                "Neither ChatGPT nor Claude could answer for "
                "{file}.").replace("{file}", report["file"]))
            return
        tool = self._model_chain.pop(0)
        self._set_busy(True, i18n.t(
            "Asking {tool} about {file} — the measured numbers and your "
            "question only; the model stays here…")
            .replace("{tool}", tool).replace("{file}", report["file"]), 1)
        self._agent_worker = AutomationWorker(
            {}, self.cfg, [], f"STEP — ask {tool} about {report['file']}",
            custom_stages=[("ask", tool, [self.sf.ask_prompt(
                report, self.ask.text().strip())])],
            chatgpt_analysis=False, failover=False)
        self._agent_worker.done.connect(
            lambda responses, links, m=m, tool=tool:
                self._on_asked_by_tool(m, tool, responses, links))
        self._agent_worker.failed.connect(lambda _e, m=m: self._ask_via_chain(m))
        self._agent_worker.start()

    def _on_asked_by_tool(self, m: dict, tool: str, responses: dict,
                          links: dict):
        texts = [t for t in (responses.get("ask") or []) if t.strip()]
        if not texts:
            self._ask_via_chain(m)
            return
        if links.get("ask"):
            self._links[f"ask · {m['report']['stem']}"] = links["ask"]
        self._model_chain = []
        self._on_suggested(texts[0], agent=tool)

    # ── the conversation, saved to one file per model ──────────────────────
    # "ask · stem" is already scoped to the model, not the exact question —
    # every Ask/Edit on the same attached model, and every follow-up inside
    # each one, is one running conversation about THAT PART, the same way a
    # chatbot thread would be. Saved as plain JSON reads back as a list of
    # [speaker, text] pairs with nothing else to parse.
    #
    # Deliberately NOT inside m["out_dir"]: core.stepfile.output_dir() gives
    # every fresh measurement of the same model its own numbered sibling
    # folder ("PET CORE (2)", "(3)", …) so a re-measure never overwrites the
    # last one's sheet — which means that folder is a NEW path on every
    # single run, never the same twice. A conversation file written there
    # would never be found again; caught live, by actually simulating a
    # second session rather than trusting the first one's save. The stable
    # thing is the root the person chose (_root()) plus the model's own
    # stem, so it sits beside every numbered run folder rather than inside
    # any one of them.
    def _conversation_path(self, m: dict) -> str:
        stem = m["report"]["stem"]
        # The engine names it; one that predates the key (the one on GitHub
        # did when 1.6.3 was cut) raised KeyError on every open and every save
        # of a model's conversation, so the same name is made here as a floor.
        name = self.sf.names(stem).get("conversation") or f"{stem} - conversation.json"
        return os.path.join(self._root(), name)

    def _load_conversation(self, m: dict) -> list:
        path = self._conversation_path(m)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [(s, t) for s, t in data] if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_conversation(self, m: dict, thread: list):
        try:
            with open(self._conversation_path(m), "w", encoding="utf-8") as f:
                json.dump(thread, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _on_suggested(self, suggestions: str, agent: str = "Groq"):
        """The answer arrives — in the Chat tab, not a window. Ask is done
        (the answer is the deliverable, the box below it carries on the
        conversation). Edit goes straight on to plan the changes."""
        m = self._current
        report = m["report"]
        key = f"ask · {report['stem']}"
        self._responses[key] = [suggestions]
        self._stage_agents_map[key] = agent
        is_edit = self._action() == "edit"
        question = self.ask.text().strip()
        self._followups = []
        self._thread = self._load_conversation(m) + [
            (i18n.t("You asked"), question), (agent, suggestions)]
        self._save_conversation(m, self._thread)
        self._live = SES.live_turn(self._action(), report["file"], question,
                                   suggestions, agent=agent)
        self._show_live()
        self._show_tab(1)
        if not is_edit:
            # Ask's whole deliverable is the answer — no plan, no review
            # page, nothing opened. Only Edit builds, and only on request.
            self._notes.append(f"{report['file']}: suggestions only — "
                               "choose Edit to turn this into a change "
                               "plan")
            self._next()
            return
        self._build_plan_for(m, key, None)

    # ── carrying on in the chat: a follow-up, or "Build this" ─────────────

    def _composer_send(self, text: str, agent: str):
        m = self._current or (self.models[0] if self.models else None)
        if m is None or m["report"].get("_stub"):
            return
        key = f"ask · {m['report']['stem']}"
        if not self._responses.get(key):
            return
        self._inline.question = text
        self._on_answer_followup(self._inline, m, key, agent, text)

    def _composer_build(self):
        m = self._current or (self.models[0] if self.models else None)
        if m is None or m["report"].get("_stub"):
            return
        key = f"ask · {m['report']['stem']}"
        if not self._responses.get(key):
            return
        self._build_plan_for(m, key, self._inline)

    def _followup_answered(self, question: str, answer: str, agent: str):
        """A follow-up came back: it joins the chat, is saved with the run,
        and is kept in the conversation file."""
        m = self._current or (self.models[0] if self.models else None)
        self._followups.append({"q": question, "a": answer, "agent": agent})
        if m is not None:
            self._thread += [(i18n.t("You followed up"), question),
                             (agent, answer)]
            self._save_conversation(m, self._thread)
        self.composer.clear()
        if self._live is not None:
            self._live["followups"] = list(self._followups)
            self._show_live()
        else:
            self._persist_run()
            self._refresh_chat()
        self._show_tab(1)

    def _conversation_text(self, key: str) -> str:
        """The whole conversation so far — the question, the first answer and
        every follow-up with who answered it — as plain text a tool can be
        handed, so a later step sees all of it and not only the last reply."""
        first = (self._responses.get(key) or [""])[0]
        who = self._stage_agents_map.get(key) or i18n.t("the first answer")
        parts = [f"Earlier question: {self.ask.text().strip()}",
                 f"Answer ({who}):\n{first}"]
        for f in self._followups:
            parts += [f"Follow-up: {f.get('q', '')}",
                      f"Answer ({f.get('agent') or '?'}):\n{f.get('a', '')}"]
        return "\n\n".join(parts)

    def _plan_via_groq(self, m: dict, key: str, popup, suggestions: str):
        """Groq answered, so Groq plans: one in-house call, no browser."""
        report = m["report"]
        if not self.cfg.get("api_key"):
            self._notify_error(i18n.t(
                "Groq needs your key — add it in Settings, or pick "
                "ChatGPT or Claude above instead."))
            if popup is not None:
                popup.set_busy(False)
            return
        if popup is not None:
            popup.set_busy(True)
        else:
            self._set_busy(True, i18n.t(
                "Groq is turning the answer into an exact change plan for "
                "{file}…").replace("{file}", report["file"]), 1)
        self._plan_worker = StepPlanWorker(
            self.cfg, report, self.ask.text().strip(), suggestions)
        self._plan_worker.done.connect(
            lambda text, m=m, popup=popup: self._on_planned(
                {"plan": [text]}, {}, m=m, popup=popup, agent="Groq"))
        self._plan_worker.failed.connect(
            lambda err, popup=popup: self._on_build_failed(err, popup))
        self._plan_worker.start()

    def _build_plan_for(self, m: dict, key: str, popup):
        """Turn whatever is CURRENTLY saved at `key` into a plan, then (if
        confirmed) a build — the same pipeline a fresh Edit's own first
        answer already ran automatically, now reachable on demand from
        any follow-up too, including one on a conversation reopened long
        after the original build finished and its popup closed."""
        report = m["report"]
        suggestions = (self._conversation_text(key) if self._followups
                       else self._responses[key][0])
        if self._stage_agents_map.get(key) == "Groq":
            self._plan_via_groq(m, key, popup, suggestions)
            return
        if popup is not None:
            popup.set_busy(True)
        planner = self._planner()
        if not planner:
            msg = i18n.t("Edit needs a reasoning tool to review the plan "
                         "— open Agents and pick one for Reasoning first.")
            if popup is not None:
                popup.set_busy(False)
                self._notify_error(msg)
            else:
                self._notes.append(f"{report['file']}: suggestions only — "
                                   "no reasoning tool set up to plan "
                                   "changes")
            return
        files = []
        png = (m.get("drawn") or {}).get("png")
        if png and os.path.exists(png):
            try:
                files.append(CB.files.attach(png))
            except Exception:                           # noqa: BLE001
                pass
        if popup is not None:
            popup.set_busy(True)
        else:
            self._set_busy(True, i18n.t(
                "{agent} is reviewing the suggestions into an exact change "
                "plan for {file}…")
                .replace("{agent}", planner).replace("{file}", report["file"]), 1)
        self._agent_worker = AutomationWorker(
            {}, self.cfg, files,
            f"STEP — review and plan CAD changes for {report['file']}",
            custom_stages=[("plan", planner, [self.sf.plan_prompt(
                report, self.ask.text().strip(), suggestions)])],
            chatgpt_analysis=False)
        self._agent_worker.done.connect(
            lambda responses, links, m=m, popup=popup:
                self._on_planned(responses, links, m=m, popup=popup))
        self._agent_worker.failed.connect(
            lambda err, popup=popup: self._on_build_failed(err, popup))
        self._agent_worker.start()

    def _on_build_failed(self, error: str, popup):
        self._awaiting = False
        self.plan_panel.hide_bar()
        if popup is not None:
            popup.set_busy(False)
            self._set_busy(False, "")
            self._notify_error(error)
        else:
            self._on_failed(error)

    # ── a follow-up typed inside the answer popup ─────────────────────────

    def _on_answer_followup(self, dlg, m: dict, key: str,
                            agent: str, text: str):
        """`agent` is whatever was selected in the popup's own "Reply as"
        picker when Send was pressed — the same one that answered first,
        by default, but the person may have switched it."""
        report = m["report"]
        dlg.set_busy(True)
        if agent == "Groq":
            composed = (
                "(This is a follow-up to a conversation already under way.)\n\n"
                f"{self._conversation_text(key)}\n\nNew follow-up: {text}")
            self._followup_ask_worker = StepAskWorker(
                self.cfg, report, composed)
            self._followup_ask_worker.done.connect(
                lambda answer, dlg=dlg, key=key:
                    self._on_answer_followup_done(dlg, key, answer))
            self._followup_ask_worker.failed.connect(
                lambda err, dlg=dlg: self._on_answer_followup_failed(
                    dlg, err))
            self._followup_ask_worker.start()
            return
        # A real chat already exists for THIS agent — resume IT rather than
        # starting a fresh one, so it answers with the earlier turn as
        # context instead of being re-sent the whole job from scratch. If
        # the person switched to a DIFFERENT agent than the one that
        # answered before, there is no chat of theirs to resume — give it
        # the same context Groq's follow-up gets instead, in the prompt.
        same_agent = self._stage_agents_map.get(key) == agent
        resume = ({"ask": self._links[key]}
                 if same_agent and self._links.get(key) else None)
        prompt = text if resume else (
            "(This is a follow-up to a conversation another tool already "
            f"had.)\n\n{self._conversation_text(key)}\n\n"
            f"New follow-up: {text}")
        self._followup_agent_worker = AutomationWorker(
            {}, self.cfg, [],
            f"STEP — follow-up with {agent} on {report['file']}",
            custom_stages=[("ask", agent, [prompt])], chatgpt_analysis=False,
            failover=False, resume_urls=resume, followup=True)
        self._followup_agent_worker.done.connect(
            lambda responses, links, dlg=dlg, key=key, agent=agent:
                self._on_answer_followup_agent_done(
                    dlg, key, agent, responses, links))
        self._followup_agent_worker.failed.connect(
            lambda err, dlg=dlg: self._on_answer_followup_failed(dlg, err))
        self._followup_agent_worker.start()

    def _on_answer_followup_done(self, dlg, key: str,
                                 answer: str):
        # The first answer stays where it is (self._responses[key]); a
        # follow-up is its own entry, kept with who gave it.
        dlg.set_busy(False)
        dlg.set_answer(answer, "Groq")

    def _on_answer_followup_agent_done(self, dlg, key: str,
                                       agent: str, responses: dict,
                                       links: dict):
        texts = [t for t in (responses.get("ask") or []) if t.strip()]
        if not texts:
            self._on_answer_followup_failed(
                dlg, i18n.t("{agent} didn't answer the follow-up.")
                .replace("{agent}", agent))
            return
        if links.get("ask") and not self._links.get(key):
            self._links[key] = links["ask"]
        dlg.set_busy(False)
        dlg.set_answer(texts[0], agent)

    def _on_answer_followup_failed(self, dlg, error: str):
        dlg.set_busy(False)
        self._notify_error(error)

    def _on_planned(self, responses: dict, links: dict, m: dict = None,
                    popup=None, agent: str = ""):
        """The plan came back — in the Plan tab, not a window. With changes
        in it, a Build bar waits for you; nothing is built until you press it.
        With none, it says so and says what to do next.

        `popup` is the inline answer box when this was asked for by "Build
        this" (then the queue is not touched); None for an Edit's own run."""
        m = m or self._current
        report, out_dir = m["report"], m["out_dir"]
        self._links.update({f"{k} · {report['stem']}": v
                            for k, v in links.items()})
        texts = [t for t in (responses.get("plan") or []) if t.strip()]
        self._responses[f"plan · {report['stem']}"] = texts
        self._stage_agents_map[f"plan · {report['stem']}"] = agent or self._planner()
        plan, why = self.sf.parse_plan(texts)
        if plan is None:
            self.status.setText(why)
            if popup is not None:
                popup.set_busy(False)
                return
            self._notes.append(f"{report['file']}: {why}")
            self._next()
            return
        m["plan"] = plan
        self.plan_panel.set_plan(plan, agent or self._planner())
        self._tab_label(2, i18n.t("Plan"), len(plan["changes"]) + len(plan["advice"]))
        question = self.ask.text().strip()
        review = self.sf.review_html(report, plan, out_dir, question=question)
        self._review_path = review
        if popup is not None:
            popup.set_busy(False)
        if not plan["changes"]:
            # Nothing to change — most often the question was a question.
            # Stay on the answer; the Plan tab holds the explanation for
            # anyone who wants it, but it does not take over the screen.
            self._show_tab(1)
            self._notes.append(f"{report['file']}: nothing to change — a "
                               "question is answered with Ask")
            note = i18n.t(
                "Nothing was changed — that reads as a question. Use Ask for "
                "questions, or say exactly what to change (which holes, what "
                "size, or a scale).")
            self.status.setText(note)
            self.canvas.toast(note, [], seconds=12)
            if popup is None:
                self._next()
            return
        self._show_tab(2)
        # Something to build: wait for the person.
        self._pending = {"m": m, "plan": plan, "question": question,
                         "popup": popup, "out_dir": out_dir}
        self._awaiting = True
        self._set_busy(False, i18n.t(
            "Review the plan on the right, then press “Build the modified model”."))
        self.plan_panel.ask_to_build(len(plan["changes"]), report["file"])

    def _confirm_build(self):
        pend = self._pending
        if not pend:
            return
        self._pending = None
        self._awaiting = False
        m, plan, popup = pend["m"], pend["plan"], pend["popup"]
        report = m["report"]
        self.plan_panel.building()
        if popup is not None:
            popup.set_busy(True)
        self.progress.set_stages(_stages("edit"))
        self._set_busy(True, i18n.t("Building a copy and re-measuring it…"), 2)
        self._apply_worker = StepApplyWorker(
            m["path"], plan, report, self._mode(), pend["out_dir"],
            pend["question"], self._k_factor())
        self._apply_worker.done.connect(
            lambda result, m=m, popup=popup: self._on_applied(result, m, popup))
        self._apply_worker.failed.connect(
            lambda err, popup=popup: self._on_build_failed(err, popup))
        self._apply_worker.start()

    def _skip_build(self):
        pend = self._pending
        if not pend:
            return
        self._pending = None
        self._awaiting = False
        report = pend["m"]["report"]
        self.plan_panel.hide_bar()
        self._notes.append(f"{report['file']}: not built — the plan stays in "
                           "the Plan tab and the review page")
        self._set_busy(False, "")
        if pend["popup"] is None:
            self._next()

    def _refine_request(self):
        """The plan had nothing to build: back to the question box."""
        self._show_tab(1)
        self.ask.edit.setFocus()
        self.ask.edit.selectAll()
        self.status.setText(i18n.t(
            "Say exactly which holes and to what size (or a scale factor), "
            "then press the button again."))

    def _open_review_page(self):
        if self._review_path and os.path.exists(self._review_path):
            appfiles.open_file(self._review_path)

    def _on_applied(self, result: dict, m: dict = None, popup=None):
        m = m or self._current
        report = m["report"]
        m["modified"] = result["out"]
        self._review_path = result.get("review") or self._review_path
        self.result.appendPlainText(
            f"{report['file']} — built {os.path.basename(result['out'])}:\n  "
            + "\n  ".join(result["log"]) + "\n\n"
            + self.sf.report_text(result["after"]) + "\n")
        self._notes.append(f"{report['file']}: modified model → "
                           f"{result['out']}")
        try:
            CB.config.save_artifact(result["out"],
                                    os.path.basename(result["out"]),
                                    kind="step", task=report["file"])
        except Exception:                               # noqa: BLE001
            pass
        self.files_label.setText(
            i18n.t("Saved — the modified file is at ") + result["out"])
        self.meas_box.setVisible(True)
        self.measured_empty.setVisible(False)
        self.plan_panel.built(os.path.basename(result["out"]))
        self._refresh_files()
        if self._live is not None:
            self._live["built"] = [result["out"]]
            self._show_live()
        if popup is not None:
            popup.set_busy(False)
            self._persist_run()
            self._refresh_chat()
            self._render_models()
        else:
            self._next()
        self._set_busy(False, i18n.t(
            "Built {name}. It is in the Models list — carry on from it there.")
            .replace("{name}", os.path.basename(result["out"])))

    # ── finishing ───────────────────────────────────────────────────────

    def _run_record(self, action: str) -> dict:
        label = {"draft": "Draft", "ask": "Ask", "edit": "Edit"}[action]
        names = ", ".join(m["report"]["file"] for m in self.models)
        question = self.ask.text().strip()
        self._task_name = f"STEP — {label}: {question or names}"
        return {
            "query": self._task_name,
            "responses": self._responses, "links": self._links,
            "step": {
                "action": action, "mode": self._mode(),
                "question": question,
                "chat": self._session_key,
                "followups": list(self._followups),
                "agents": dict(self._stage_agents_map),
                "models": [{"file": m["report"]["file"],
                            "path": m.get("path", ""),
                            "report": self._storable(m["report"]),
                            "out_dir": m["out_dir"],
                            "modified": m.get("modified", ""),
                            "conversation": self._conversation_path(m)}
                           for m in self.models],
            },
        }

    def _persist_run(self):
        """Save what happened after the run finished — a follow-up, a build —
        into the same run record."""
        if not (self._run_path and self.models and self._last_action):
            return
        try:
            CB.config.save_run(self._run_record(self._last_action),
                               path=self._run_path)
        except Exception:                               # noqa: BLE001
            pass

    def _finish(self):
        action = self._action()
        self._set_busy(False, i18n.t("Done. ") + (
            " ".join(self._notes) if self._notes
            else i18n.t("Measured from the geometry itself — not by an AI.")))
        self.open_btn.setEnabled(bool(self._links))
        self.open_btn.setVisible(bool(self._links))
        self._refresh_files()
        self._render_models()
        try:
            self._run_path = CB.config.save_run(self._run_record(action))
            self._loaded_run = self._run_path
            self._last_action = action
        except Exception:                               # noqa: BLE001
            pass
        if self._run_path:
            self._live = None            # saved: the chat reads it from the record
        self._refresh_runs()
        self._refresh_chat(keep_live=True)
        self._render_models()             # an edit's copy joins the list now
        if self._stay_on_plan:
            self._stay_on_plan = False
        elif action in ("ask", "edit"):
            self._show_tab(1)

    @staticmethod
    def _storable(report: dict) -> dict:
        """The measurement without its CAD shapes, as plain JSON — so a run
        reopened from History still has its numbers."""
        plain = {k: v for k, v in report.items() if not str(k).startswith("_")}
        try:
            return json.loads(json.dumps(plain, default=str))
        except (TypeError, ValueError):
            return {}

    def _notify_error(self, error: str):
        """A problem, shown in the window — the status line and a notice on
        the canvas — not a pop-up that takes the screen and says nothing about
        what to do next."""
        text = str(error or "").strip() or i18n.t("Something went wrong.")
        self.status.setText("⚠  " + text)
        self.canvas.toast("⚠  " + (text if len(text) < 140 else text[:137] + "…"),
                          [], seconds=10)

    def _on_failed(self, error: str):
        self._set_busy(False, "")
        self._render_models()
        self._set_canvas()
        self._notify_error(error)
        # A failure on one model must not strand the rest of the queue.
        if self._queue:
            self._next()

    def _set_busy(self, busy: bool, message: str, stage: int | None = None):
        self._busy = busy
        if busy:
            self.progress.set_message(message)
            if stage is not None:
                self.progress.set_stage(stage)
        self.progress.setVisible(busy)
        message_line = "" if busy else message   # the loader carries it while busy
        self.generate_btn.setEnabled(
            not busy and bool(self.paths) and not self._awaiting)
        self.status.setText(message_line)

    def _open_folder(self):
        for m in self.models[:1]:
            appfiles.open_file(m["out_dir"])

    def _open_link(self):
        import webbrowser
        for url in self._links.values():
            if url:
                webbrowser.open(url)
                break

    def closeEvent(self, event):
        """Same reasoning as Gerber: a QThread destroyed mid-run aborts the
        whole process, so ask each worker to stop and wait for it."""
        for worker in (self._worker, self._agent_worker, self._ask_worker,
                       self._apply_worker, self._followup_ask_worker,
                       self._followup_agent_worker):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

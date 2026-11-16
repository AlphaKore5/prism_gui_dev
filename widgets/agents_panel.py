"""The plan — what Prism is going to do, as a list of steps you can edit.

This is the workbench's centre of gravity and, before this pass, its emptiest
surface. One row per stage, each carrying the five things the design asks a
step to communicate:

    [number] [action] [description] [AI tool] [status]

and — this is the part that was missing — each row is genuinely editable.
The audit found the plan editor supported two of seven capabilities
(enable/disable, change tool). All seven are here now: reorder, edit the
engineered prompt, duplicate, delete and inspect as well.

None of that needed an engine change. `automation.run(custom_stages=…)` has
always taken an ordered list of `(stage_label, agent_name, questions)` tuples
and explicitly allows the same category more than once; the blocker was purely
that this panel handed back a `{stage: tool}` dict, in which order cannot be
expressed and a duplicate cannot survive. `selected_steps()` is the ordered
list; `selected_agents()` stays as the dict shim the licence gate still wants.

The other thing this file is careful about is *provenance*. Four different
things can put a step in front of you, and the design asks that they never
look alike:

    you asked for it      the tool was named in your own sentence
    Prism planned it      the router chose it
    Prism suggests        the router would rather use a different tool — and
                          it wrote a sentence saying why, which used to be
                          parsed, shipped across the thread boundary and then
                          thrown away
    you changed it        you have since edited, moved or re-pointed the step

The stage keys are the engine's own (research / brains / content / …); the
titles here are the human translation — a step is named after what it does for
you, not after the category it came from."""
from __future__ import annotations
import re

from PySide6.QtCore import Qt, Signal, QSize, QTimer
from PySide6.QtGui import QIcon, QTransform
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton, QTextEdit,
    QSizePolicy, QMenu,
)

import core_bridge as CB
import i18n
import theme
from widgets import icons
from widgets import controls as C
from widgets.controls import StepMark, ToolChip, heading, meta

# stage -> (icon, plain title, plain one-liner)
# Read by widgets/output_panel.py as well — keep the three-tuple shape.
STAGE_COPY = {
    "research":     ("search",  "Look things up",   "Find the facts and sources this needs"),
    "leads":        ("user",    "Find the people",  "Companies to approach, with verified emails"),
    "brains":       ("bulb",    "Think it through", "Work out the angle and the argument"),
    "content":      ("pencil",  "Write it up",      "Turn the thinking into clear words"),
    "visual":       ("image",   "Make the images",  "Generate the artwork to go with it"),
    "media":        ("video",   "Make the video",   "Produce the video or audio piece"),
    "audio":        ("video",   "Record the voice", "Voice-over, music or narration"),
    "development":  ("code",    "Build the tool",   "Stand up the app or page itself"),
    "presentation": ("present", "Build the slides", "A clean deck, ready to present"),
    "summary":      ("list",    "Pull it together", "Fold every step into one answer"),
    "analysis":     ("file",    "Read your files",  "Go through the attachments first"),
    # BOQ's own stage keys (addons/boq/dialog.py, addons/boq/run_dialog.py) --
    # not PIPELINE_ORDER categories, but STAGE_COPY is keyed by any stage a
    # StageCard is asked to show, and "analysis" above is already a
    # non-pipeline custom key, so three more read fine here.
    "format":       ("pencil",  "Write it up",       "Turn the measured figures into the document"),
    "recheck":      ("eye",     "Verify and remake", "Check the answer against the drawing itself"),
    "followup":     ("chat",    "Make the change",   "Carry the conversation on from the last answer"),
}

# How a step got here. Four provenances, four looks — see the module docstring.
ORIGIN_YOURS = "yours"          # you named the tool in your own words
ORIGIN_PLANNED = "planned"      # the router chose it
ORIGIN_SUGGESTED = "suggested"  # the router would rather use something else
ORIGIN_EDITED = "edited"        # you have changed it since

# The tag style each provenance wears. The WORDS are built in _origin_copy()
# rather than sitting in this table, because devtools/extract_strings.py reads
# the source: a literal inside an i18n.t() call is always found, whereas a
# module-level table is only scanned if its name happens to be in the tool's
# COPY_TABLES set — and a label that reaches a screen without reaching a
# translator is exactly what the catalogue exists to prevent.
_ORIGIN_STYLE = {
    ORIGIN_YOURS: "tagOutline",
    ORIGIN_SUGGESTED: "tagAccent",
    ORIGIN_EDITED: "tagOutline",
}


def _origin_copy(origin: str) -> tuple[str, str]:
    """(label, tag style) for how a step got into the plan."""
    words = {
        ORIGIN_YOURS: i18n.t("You picked this"),
        ORIGIN_SUGGESTED: i18n.t("Prism suggests"),
        ORIGIN_EDITED: i18n.t("You changed this"),
    }
    return words.get(origin, ""), _ORIGIN_STYLE.get(origin, "tagNeutral")


# How far the description, the reason line and the row's own actions are inset
# so they line up under the step's NAME rather than under its number. Derived
# rather than typed, so it cannot drift out of step with the marker's size.
_LEAD = StepMark.SIZE + 22 + 18 + theme.SPACE_3 * 3


def _arrow_icon(down: bool, size: int = 15, colour: str = "") -> QIcon:
    """Move-up / move-down glyphs. The icon set has `arrow-up` and no
    `arrow-down`, and adding one would mean editing widgets/icons.py — so the
    down arrow is the up arrow turned over, which is what it is anyway."""
    px = icons.pixmap("arrow-up", size, colour or theme.NEUTRAL[700])
    if not down:
        return QIcon(px)
    flipped = px.transformed(QTransform().rotate(180), Qt.SmoothTransformation)
    flipped.setDevicePixelRatio(px.devicePixelRatio())
    return QIcon(flipped)


def _tiny(icon_name: str, tip: str, on_click=None, down: bool = None) -> QPushButton:
    """A 30px square glyph button for the per-row actions.

    Slightly tighter than controls.icon_button's 34px because a plan row
    carries five of them, and still clear of the 28px minimum target."""
    btn = QPushButton()
    btn.setObjectName("iconBtn")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(30, 30)
    if down is None:
        icons.button_icon(btn, icon_name, 15, theme.NEUTRAL[700])
    else:
        btn.setIcon(_arrow_icon(down))
        btn.setIconSize(QSize(15, 15))
    btn.setToolTip(tip)
    btn.setAccessibleName(tip)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def _first_sentence(text: str, limit: int = 150) -> str:
    """The opening of an engineered prompt, as one readable line.

    The prompts the router writes are 120-250 words. The row shows the first
    sentence of the real thing rather than a hardcoded blurb about the
    category — the whole product is what Prism decided to ask, and until now
    that was reachable only through two collapsed containers."""
    flat = " ".join((text or "").split())
    if not flat:
        return ""
    cut = re.split(r"(?<=[.?!])\s", flat, maxsplit=1)[0]
    if len(cut) > limit:
        cut = cut[:limit - 1].rstrip() + "…"
    return cut


def _minutes(seconds: int) -> str:
    if seconds >= 3600:
        return i18n.t("{n}h {m}m").format(n=seconds // 3600,
                                          m=(seconds % 3600) // 60)
    return i18n.t("{n}m").format(n=max(1, round(seconds / 60)))


class PlanToolChip(ToolChip):
    """The tool picker, as a choice of execution engine rather than a combo box.

    Same painted chip as controls.ToolChip — this only replaces the menu it
    opens, because the shared one is a flat alphabetical list of names and the
    registry already knows far more than that. Tools are grouped Recommended
    above Other, each line carries the tool's real cost band and typical reply
    time from AGENT_REGISTRY, and where the router wrote a sentence explaining
    why it prefers a different tool, that sentence is the item's tooltip.
    """

    def __init__(self, tools, current="", suggested="", named="", reason="",
                 parent=None):
        self._named = named or ""
        self._reason = reason or ""
        super().__init__(tools, current, suggested, parent)

    def set_reason(self, reason: str):
        self._reason = reason or ""

    def _recommended(self) -> list:
        """Groq's pick, your own pick, and the category's own first choice.

        All three are real signals: `_suggestions` is what the router decided
        for *this* task, `_named_tools` is what you literally asked for, and
        the head of CATEGORIES[stage]["agents"] is the registry's default for
        the job. Everything else is Other."""
        picks = []
        for name in (self._suggested, self._named,
                     self._tools[0] if self._tools else ""):
            if name and name in self._tools and name not in picks:
                picks.append(name)
        return picks

    def _open_menu(self):
        if not self._tools:
            return
        A = CB.agents
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        top = self._recommended()
        rest = [t for t in self._tools if t not in top]

        for group, names in ((i18n.t("Recommended"), top),
                             (i18n.t("Other tools"), rest)):
            if not names:
                continue
            menu.addSection(group)
            for name in names:
                entry = A.resolve_agent("", name) or {}
                bits = [b for b in (entry.get("cost"), entry.get("avg")) if b]
                text = name if not bits else f"{name}\t{'  ·  '.join(bits)}"
                if name == self._suggested:
                    text = i18n.t("{tool}  ★ suggested").format(tool=text)
                action = menu.addAction(text)
                action.setCheckable(True)
                action.setChecked(name == self._current)
                tip = entry.get("specialty") or ""
                if name == self._suggested and self._reason:
                    tip = f"{self._reason}\n\n{tip}" if tip else self._reason
                if tip:
                    action.setToolTip(tip)
                action.triggered.connect(lambda _=False, n=name: self._pick(n))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


def _makes_copy(kind: str) -> str:
    """What a step will hand back, as its row says it (core/contract.py).

    One literal i18n.t call per phrase so devtools/extract_strings.py can
    find each of them; a dict looked up at run time would be invisible to
    it. A written answer is every step's default, so it says nothing —
    printing "writes an answer" on every row would be noise.
    """
    if kind == "file":
        return i18n.t("makes a file to download")
    if kind == "image":
        return i18n.t("makes pictures")
    if kind == "video":
        return i18n.t("makes a video")
    if kind == "links":
        return i18n.t("finds companies and contacts")
    if kind == "data":
        return i18n.t("writes a spec for the renderer")
    return ""


def default_prompt_for_stage(stage: str, query: str = "") -> str:
    """Generate a sensible, stage-tailored prompt from the user's task request."""
    q = query.strip() if query else "the task"
    if stage == "research":
        return f"Research and gather facts, sources, data, and background on: {q}"
    if stage == "brains":
        return f"Think through, analyze, and outline a detailed plan and solution for: {q}"
    if stage == "leads":
        return f"Find relevant contacts, companies, leads, and sources for: {q}"
    if stage == "content":
        return f"Write comprehensive, high-quality content and documentation for: {q}"
    if stage == "visual":
        return f"Create visual concepts, image prompts, or diagrams for: {q}"
    if stage == "presentation":
        return f"Create an outline and slide-by-slide structure for a presentation on: {q}"
    if stage == "development":
        return f"Write clean, complete code and technical implementation for: {q}"
    if stage == "media":
        return f"Create a structured video reel script and visual scenes for: {q}"
    if stage == "audio":
        return f"Write a voiceover script and narration for: {q}"
    return f"Complete the {stage} stage for: {q}"


class PlanRow(QFrame):
    """One step: number, marker, icon, name, the real prompt, tool, status —
    and the six controls that make the plan an editable object rather than a
    read-only receipt."""

    toggled = Signal()
    changed = Signal()                      # anything that alters what runs
    move_requested = Signal(object, int)    # (row, -1 | +1)
    remove_requested = Signal(object)
    duplicate_requested = Signal(object)

    def __init__(self, stage: str, meta_data: dict, current: str, included: bool,
                 suggested: str | None = None, forced: str | None = None,
                 questions: list | None = None, reason: str = "",
                 parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("listRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        icon_name, title, blurb = STAGE_COPY.get(
            stage, ("grid", meta_data.get("label", stage), meta_data.get("desc", "")))
        self._icon_name = icon_name
        self._title = title
        self._fallback_blurb = blurb
        self._questions = [q for q in (questions or []) if q and q.strip()]
        self._reason = (reason or "").strip()
        self._suggested = suggested or ""
        self._forced = forced or ""
        self._included = included
        # What the PLAN said, kept separate from what the row shows now. The
        # difference is the whole point: a row the planner never turned on
        # and the person never touched is not the same thing as a row the
        # person deliberately switched off, and treating them alike is how a
        # planner omission became an instruction to the engine — "visual was
        # not planned" reaching automation.run() as skip_stages, which
        # switches off Studio's own artwork step (2026-09-10 reel runs).
        self._planned = included
        # What this step owes as the planner declared it, and the request it
        # was planned from. Together with the tool they decide the row's
        # "makes …" line (_refresh_engine, core/contract.py). Set after
        # construction by AgentsPanel.set_content, which has both.
        self._planner_kind = ""
        self._query = ""
        # Whether the person switched this step on or off themselves, and
        # whether it is the ONE step the request's file falls to (set by
        # AgentsPanel._apply_file_promotion, the same choice the engine makes).
        self._touched = False
        self._promoted = False
        self._origin = (ORIGIN_YOURS if forced else
                        ORIGIN_SUGGESTED if (suggested and suggested != current)
                        else ORIGIN_PLANNED)

        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3 + 2, theme.SPACE_3,
                                theme.SPACE_3, theme.SPACE_3)
        root.setSpacing(theme.SPACE_2)

        # ── line 1: what this step is, who runs it, where it stands ────────
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_3)

        self.number = QLabel("01")
        self.number.setFixedWidth(22)
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 15px;"
            f" font-weight: 600; color: {theme.NEUTRAL_350};")
        top.addWidget(self.number, alignment=Qt.AlignVCenter)

        self.mark = StepMark(included)
        self.mark.setToolTip(i18n.t("Click to leave this step out of the run"))
        top.addWidget(self.mark, alignment=Qt.AlignVCenter)

        self.glyph = QLabel()
        self.glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        top.addWidget(self.glyph, alignment=Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.name = QLabel(title)
        self.name.setObjectName("h5")
        head.addWidget(self.name)
        self.origin_tag = self._tag("", "tagAccent")
        head.addWidget(self.origin_tag)
        self.prompts_tag = self._tag("", "tagNeutral")
        head.addWidget(self.prompts_tag)
        head.addStretch(1)
        text.addLayout(head)

        # The description is the FIRST SENTENCE OF THE REAL PROMPT when the
        # router wrote one, not the category blurb. The blurb is the fallback.
        self.blurb = QLabel()
        self.blurb.setObjectName("meta")
        self.blurb.setWordWrap(True)
        self.blurb.setMinimumWidth(180)
        text.addWidget(self.blurb)
        top.addLayout(text, stretch=1)

        tools = meta_data.get("agents", []) or ([current] if current else [])
        self.chip = PlanToolChip(tools, forced or current, suggested or "",
                                 named=forced or "", reason=self._reason)
        self.chip.setToolTip(i18n.t("Click to run this step with a different tool"))
        # controls.ToolChip has always emitted `changed` and nothing has ever
        # connected it — so until Start was pressed, swapping a tool updated
        # no count, no estimate and no licence check. It does now.
        self.chip.changed.connect(self._on_tool_changed)

        engine = QVBoxLayout()
        engine.setContentsMargins(0, 0, 0, 0)
        engine.setSpacing(2)
        engine.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        engine.addWidget(self.chip, alignment=Qt.AlignRight)
        # What choosing this engine actually costs you: the tool's price band,
        # how long it usually takes to answer, and the timeout Prism will
        # honour before giving up on it. All three are in the registry already
        # and the chip has only ever shown the name.
        self.engine_meta = QLabel("")
        self.engine_meta.setObjectName("meta")
        self.engine_meta.setAlignment(Qt.AlignRight)
        engine.addWidget(self.engine_meta)
        top.addLayout(engine)

        self.badge = C.StatusBadge("queued" if included else "skipped",
                                   focusable=False)
        top.addWidget(self.badge, alignment=Qt.AlignVCenter)
        root.addLayout(top)

        # ── line 2: why Prism suggests a different tool ────────────────────
        # Groq writes one sentence per suggestion. It was fetched, validated,
        # shipped across the thread boundary and then dropped on the floor.
        self.why = QLabel(self)
        self.why.setObjectName("meta")
        self.why.setWordWrap(True)
        self.why.setContentsMargins(_LEAD, 0, 0, 0)
        self.why.setVisible(False)
        root.addWidget(self.why)

        # ── line 3: the six edits ─────────────────────────────────────────
        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_2 - 2)
        actions.setContentsMargins(_LEAD, 0, 0, 0)
        self.inspect_btn = QPushButton(i18n.t("Prompt"))
        self.inspect_btn.setObjectName("ghostBtn")
        self.inspect_btn.setCheckable(True)
        self.inspect_btn.setCursor(Qt.PointingHandCursor)
        self.inspect_btn.setMinimumHeight(C.MIN_TARGET)
        self.inspect_btn.setToolTip(i18n.t(
            "See and edit the exact words Prism will send this tool"))
        icons.button_icon(self.inspect_btn, "chevron-right", 14,
                          theme.ACCENT_RAMP[700])
        self.inspect_btn.toggled.connect(self._on_inspect)
        actions.addWidget(self.inspect_btn)

        self.dup_btn = QPushButton(i18n.t("Duplicate"))
        self.dup_btn.setObjectName("ghostBtn")
        self.dup_btn.setCursor(Qt.PointingHandCursor)
        self.dup_btn.setMinimumHeight(C.MIN_TARGET)
        self.dup_btn.setToolTip(i18n.t(
            "Run this step twice — a second pass at the same job, which you "
            "can then point at a different tool."))
        icons.button_icon(self.dup_btn, "copy", 14, theme.NEUTRAL[700])
        self.dup_btn.clicked.connect(
            lambda: self.duplicate_requested.emit(self))
        actions.addWidget(self.dup_btn)

        self.del_btn = QPushButton(i18n.t("Remove"))
        self.del_btn.setObjectName("ghostBtn")
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setMinimumHeight(C.MIN_TARGET)
        self.del_btn.setToolTip(i18n.t("Take this step out of the plan"))
        icons.button_icon(self.del_btn, "trash", 14, theme.NEUTRAL[700])
        self.del_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        actions.addWidget(self.del_btn)
        actions.addStretch(1)

        self.up_btn = _tiny("", i18n.t("Move this step earlier"),
                            lambda: self.move_requested.emit(self, -1),
                            down=False)
        actions.addWidget(self.up_btn)
        self.down_btn = _tiny("", i18n.t("Move this step later"),
                              lambda: self.move_requested.emit(self, 1),
                              down=True)
        actions.addWidget(self.down_btn)
        root.addLayout(actions)

        # ── the drawer: the engineered prompt itself, editable ────────────
        self.drawer = QWidget(self)
        drawer = QVBoxLayout(self.drawer)
        drawer.setContentsMargins(_LEAD, 0, 0, 0)
        drawer.setSpacing(theme.SPACE_2)
        self.prompt_hint = QLabel()
        self.prompt_hint.setObjectName("meta")
        self.prompt_hint.setWordWrap(True)
        drawer.addWidget(self.prompt_hint)
        self._editors: list[QTextEdit] = []
        self._editor_box = QVBoxLayout()
        self._editor_box.setContentsMargins(0, 0, 0, 0)
        self._editor_box.setSpacing(theme.SPACE_2)
        drawer.addLayout(self._editor_box)
        self.drawer.setVisible(False)
        root.addWidget(self.drawer)

        self._refresh_text()
        self._refresh_origin()
        self._refresh_engine()
        self.set_included(included)

    # ── small builders ────────────────────────────────────────────────────
    @staticmethod
    def _tag(text: str, style: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName(style)
        # Only ever HIDE here (empty text). Calling setVisible(True) on this
        # still-parentless label would flash it as a top-level OS window — the
        # ghost-window flash; it shows on its own once added to a live parent.
        if not text:
            lbl.setVisible(False)
        return lbl

    # ── the prompt ────────────────────────────────────────────────────────
    def questions(self) -> list:
        """The prompts as they will be sent — the edited text if the drawer
        has been opened and typed in, otherwise what the router wrote."""
        if self._editors:
            live = [e.toPlainText().strip() for e in self._editors]
            return [q for q in live if q]
        return list(self._questions)

    def set_questions(self, questions: list):
        self._questions = [q for q in (questions or []) if q and q.strip()]
        self._editors = []
        while self._editor_box.count():
            item = self._editor_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._refresh_text()

    def _refresh_text(self):
        first = self._questions[0] if self._questions else ""
        self.blurb.setText(_first_sentence(first) or self._fallback_blurb)
        if self._questions:
            self.blurb.setToolTip("\n\n".join(self._questions))
        count = len(self._questions)
        self.prompts_tag.setText(
            "" if count <= 1 else i18n.t("{n} prompts").format(n=count))
        self.prompts_tag.setVisible(count > 1)
        self.prompts_tag.setToolTip(i18n.t(
            "Prism sends this tool more than one prompt in the same "
            "conversation, in order."))
        self.prompt_hint.setText(
            i18n.t("This is what Prism will type into the tool. Edit it and "
                   "your words are what gets sent.") if self._questions else
            i18n.t("Prism didn't engineer a prompt for this step, so it will "
                   "pass your task through as written."))

    def _build_editors(self):
        if self._editors or not self._questions:
            return
        for text in self._questions:
            edit = C.PlainPasteTextEdit()
            edit.setObjectName("promptEdit")
            edit.setPlainText(text)
            edit.setMinimumHeight(96)
            edit.setMaximumHeight(190)
            edit.setStyleSheet(
                f"background: {theme.WELL}; border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.R_CONTROL}px; padding: 10px;"
                + theme.type_css("SUPPORT", theme.NEUTRAL[800]))
            edit.textChanged.connect(self._on_prompt_edited)
            self._editor_box.addWidget(edit)
            self._editors.append(edit)

    def _on_inspect(self, open_: bool):
        icons.button_icon(self.inspect_btn,
                          "chevron-down" if open_ else "chevron-right", 14,
                          theme.ACCENT_RAMP[700])
        if open_:
            self._build_editors()
        self.drawer.setVisible(open_)

    def _on_prompt_edited(self):
        live = [e.toPlainText().strip() for e in self._editors]
        if live != self._questions:
            self.mark_edited()
        self.blurb.setText(_first_sentence(live[0] if live else "")
                           or self._fallback_blurb)

    # ── provenance ────────────────────────────────────────────────────────
    def origin(self) -> str:
        return self._origin

    def mark_edited(self):
        if self._origin != ORIGIN_EDITED:
            self._origin = ORIGIN_EDITED
            self._refresh_origin()
            self._apply_skin()
        self.changed.emit()

    def _refresh_origin(self):
        text, style = _origin_copy(self._origin)
        self.origin_tag.setText(text)
        self.origin_tag.setObjectName(style)
        self.origin_tag.setVisible(bool(text))
        self.origin_tag.style().unpolish(self.origin_tag)
        self.origin_tag.style().polish(self.origin_tag)
        tips = {
            ORIGIN_YOURS: i18n.t("You named this tool in your own words, so "
                                 "Prism kept it."),
            ORIGIN_SUGGESTED: i18n.t("Prism proposed a different tool for "
                                     "this step. You are in control — leave "
                                     "it, or pick another."),
            ORIGIN_EDITED: i18n.t("You have changed this step since Prism "
                                  "planned it."),
        }
        self.origin_tag.setToolTip(tips.get(self._origin, ""))

        show_why = self._origin == ORIGIN_SUGGESTED and bool(self._reason)
        if show_why:
            self.why.setText(i18n.t("Prism suggests {tool} — {why}").format(
                tool=self._suggested, why=self._reason))
        self.why.setVisible(show_why)

    # ── include / exclude ─────────────────────────────────────────────────
    def mousePressEvent(self, event):
        """The row is still the switch — clicking anywhere that is not a
        control includes or drops the step."""
        if event.button() == Qt.LeftButton:
            self.toggle()
            self.changed.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.toggle()
            self.changed.emit()
            return
        super().keyPressEvent(event)

    def set_included(self, included: bool):
        self._included = included
        self.mark.set_included(included)
        self.badge.set_state("queued" if included else "skipped")
        self.name.setStyleSheet("" if included else f"color: {theme.NEUTRAL[500]};")
        self.chip.setEnabled(included)
        self.blurb.setStyleSheet("" if included else f"color: {theme.NEUTRAL[400]};")
        self.glyph.setPixmap(icons.pixmap(
            self._icon_name, 18,
            theme.ACCENT if included else theme.NEUTRAL[400]))
        for btn in (self.inspect_btn, self.dup_btn):
            btn.setEnabled(included)
        if not included and self.inspect_btn.isChecked():
            self.inspect_btn.setChecked(False)
        self._apply_skin()
        self.setAccessibleName(
            f"{self.number.text()}. {self._title}. "
            f"{self.chip.current()}. {self.badge.accessibleName()}")

    def _apply_skin(self):
        """The row keeps its card shape when dropped and loses its colour
        instead — swapping it for an outlined box changed the shape of the
        list every time a step was switched off, which made the plan feel like
        it was being rebuilt rather than edited.

        The left rule is the provenance cue: a solid accent edge means a human
        decided this (you named the tool, or you have since changed it), a
        pale edge means Prism is proposing something, and no edge means the
        router simply planned it.
        """
        if not self._included:
            self.setStyleSheet(
                f"#listRow {{ background: {theme.NEUTRAL[100]};"
                f" border: 1px solid {theme.HAIRLINE};"
                f" border-radius: {theme.R_CONTROL}px; }}")
            return
        edge = {ORIGIN_YOURS: theme.ACCENT,
                ORIGIN_EDITED: theme.ACCENT,
                ORIGIN_SUGGESTED: theme.ACCENT_RAMP[300]}.get(self._origin, "")
        left = (f"border-left: 3px solid {edge};" if edge
                else f"border-left: 1px solid {theme.HAIRLINE};")
        self.setStyleSheet(
            f"#listRow {{ background: {theme.CARD};"
            f" border: 1px solid {theme.HAIRLINE}; {left}"
            f" border-radius: {theme.R_CONTROL}px; }}")

    # ── tool ──────────────────────────────────────────────────────────────
    def _refresh_engine(self):
        entry = CB.agents.resolve_agent(self.stage, self.chip.current()) or {}
        wait = int(entry.get("wait_time") or 0)
        bits = []
        # What the step will hand back, first — so a reel plan with no step
        # that makes pictures, or a document request whose writing step can
        # only produce chat text, is visible BEFORE the run, not after it.
        # Recomputed when the tool changes: a tool that cannot make a file
        # changes this line, which is the point.
        kind = CB.contract.for_stage(self.stage, self._planner_kind, entry)
        if self._promoted and kind == "text":
            kind = "file"
        makes = _makes_copy(kind)
        if makes:
            bits.append(makes)
        bits += [b for b in (entry.get("cost"), entry.get("avg")) if b]
        if wait:
            bits.append(i18n.t("waits up to {t}").format(t=_minutes(wait)))
        self.engine_meta.setText("  ·  ".join(bits))
        self.engine_meta.setVisible(bool(bits))
        self.engine_meta.setToolTip(entry.get("specialty") or "")

    def _on_tool_changed(self, _name: str):
        self._refresh_engine()
        self.mark_edited()

    def selected_agent(self) -> str | None:
        return self.chip.current()

    def is_checked(self) -> bool:
        return self._included

    def was_planned(self) -> bool:
        """Was this step on when the plan arrived? See left_out_stages()."""
        return self._planned

    def set_kind(self, kind: str, query: str = "") -> None:
        """The planner's declared deliverable for this step, and the request
        it was planned from. Refreshes the "makes …" line."""
        self._planner_kind = kind or ""
        self._query = query or ""
        self._refresh_engine()

    def kind_and_tool(self) -> tuple:
        """(this step's kind before the request is applied, its tool entry)."""
        entry = CB.agents.resolve_agent(self.stage, self.chip.current()) or {}
        return CB.contract.for_stage(self.stage, self._planner_kind, entry), entry

    def set_promoted(self, promoted: bool) -> None:
        if promoted != self._promoted:
            self._promoted = promoted
            self._refresh_engine()

    def was_touched(self) -> bool:
        return self._touched

    def toggle(self) -> None:
        """The person switched this step on or off — see left_out_stages()."""
        self._touched = True
        new_state = not self._included
        if new_state and not self._questions:
            prompt = default_prompt_for_stage(self.stage, self._query)
            self.set_questions([prompt])
            self._origin = ORIGIN_YOURS
            self._apply_skin()
        self.set_included(new_state)
        self.toggled.emit()

    def title(self) -> str:
        """The step's name as the plan shows it — "Find the people", not
        "leads" — so a refusal can point at the row the owner is looking at."""
        return self._title

    def wait_seconds(self) -> int:
        entry = CB.agents.resolve_agent(self.stage, self.chip.current()) or {}
        return int(entry.get("wait_time") or 0)

    # ── position ──────────────────────────────────────────────────────────
    def set_index(self, index: int, last: bool):
        self.number.setText(f"{index:02d}")
        self.up_btn.setEnabled(index > 1)
        self.down_btn.setEnabled(not last)


class AgentsPanel(QWidget):
    run_requested = Signal()
    discard_requested = Signal()
    plan_changed = Signal()          # any edit — reorder, drop, swap, rewrite

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[PlanRow] = []
        self._query = ""
        self._brief = ""
        self._extras: list[tuple[str, str]] = []
        self._attached = 0
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        self.header = C.SectionHeader(
            i18n.t("Your plan"),
            i18n.t("Prism drafted this. Reorder it, rewrite any prompt, change a "
                   "tool, or drop a step — nothing runs until you say so.")
        )
        self.subtitle = self.header.subtitle
        self.count = C.Pill("", "neutral")
        self.count.setVisible(False)
        self.header.add_action(self.count)
        self.budget = C.Pill("", "quiet")
        self.budget.setVisible(False)
        self.header.add_action(self.budget)
        root.addWidget(self.header)

        # Prism's own restatement of the job, sitting between your words (the
        # composer recap, immediately above) and the steps it produced.
        # `routing["_brief"]` is the whole first pass of the router and the
        # thing every prompt below was written from; it has only ever been
        # readable inside a closed disclosure inside a 44px collapsed rail.
        # Reading it back is how you catch a misunderstanding BEFORE forty
        # minutes of browser automation, not after.
        self.intent = QFrame(self)
        self.intent.setObjectName("well")
        self.intent.setAttribute(Qt.WA_StyledBackground, True)
        intent = QVBoxLayout(self.intent)
        intent.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                  theme.SPACE_4, theme.SPACE_3)
        intent.setSpacing(2)
        self.intent_kicker = C.kicker(i18n.t("How Prism read it"), muted=True)
        intent.addWidget(self.intent_kicker)
        self.intent_text = QLabel("")
        self.intent_text.setWordWrap(True)
        self.intent_text.setStyleSheet(
            theme.type_css("SUPPORT", theme.NEUTRAL[800]) + " font-style: italic;")
        intent.addWidget(self.intent_text)
        self.intent.setVisible(False)
        root.addWidget(self.intent)

        rows_wrap = QWidget()
        # Maximum, not Preferred: the rows column hugs its rows exactly. With
        # a Preferred policy the leftover window height was handed to it and
        # then had nowhere to go inside it, which put the grey band back —
        # only this time hidden inside the plan. The slack goes to exactly one
        # deliberate place instead: `_tail` when there is a plan, the centring
        # EmptyState when there is not.
        rows_wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.rows_box = QVBoxLayout(rows_wrap)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(theme.SPACE_2 + 2)
        root.addWidget(rows_wrap)

        # Steps the engine will run that are not rows: the final synthesis the
        # router asks for, and the file-reading pass ChatGPT does first when
        # something is attached. Both were entirely invisible, so the plan
        # under-reported the run.
        self.extras = QLabel("", self)
        self.extras.setObjectName("note")
        self.extras.setWordWrap(True)
        self.extras.setVisible(False)
        root.addWidget(self.extras)

        # Kept for compatibility with anything that poked at the old dashed
        # label; the real empty state is the centring one below it.
        self.empty = QLabel("", self)
        self.empty.setVisible(False)
        root.addWidget(self.empty)

        self.empty_state = C.EmptyState(
            "list", i18n.t("No plan yet"),
            i18n.t("Describe the job above and press Make a plan. Prism "
                   "works out the steps, picks a tool for each, and writes "
                   "the exact prompt it will send — then hands all of it to "
                   "you to change."))
        # EmptyState hands its body a max width and two stretches, and a
        # word-wrapped QLabel between two stretches collapses to its minimum.
        # A floor here keeps the sentence a paragraph rather than a column.
        self.empty_state.body.setMinimumWidth(460)
        # Its own 20px inset on top of the column's spacing pushed the toolkit
        # below the fold on a 900px window.
        self.empty_state.layout().setContentsMargins(0, theme.SPACE_3, 0,
                                                     theme.SPACE_3)
        root.addWidget(self.empty_state, stretch=1)

        # An empty bench is the right place to answer "what would a plan even
        # look like?" — with the categories this copy of Prism is actually
        # configured for and the tool assigned to each. Every card is read
        # from the user's own config; a category with no tool assigned is not
        # drawn, because the router will not plan one either.
        self.toolkit = QWidget(self)
        kit = QVBoxLayout(self.toolkit)
        kit.setContentsMargins(0, 0, 0, 0)
        kit.setSpacing(theme.SPACE_3)
        kit_head = QHBoxLayout()
        kit_head.setSpacing(theme.SPACE_2)
        kit_head.addWidget(C.kicker(i18n.t("Steps Prism can run for you"),
                                    muted=True), stretch=1)
        self.toolkit_note = meta("")
        kit_head.addWidget(self.toolkit_note)
        kit.addLayout(kit_head)
        self.toolkit_grid = C.CardGrid(min_col_width=210, max_columns=5)
        kit.addWidget(self.toolkit_grid)
        self.toolkit.setVisible(False)
        root.addWidget(self.toolkit)

        # Exactly one of `empty_state` and `_tail` is ever visible, and both
        # carry stretch 1 — so whichever is on screen is the single item that
        # absorbs the leftover window height. Without a named home the surplus
        # is distributed across whatever the layout thinks can grow, which is
        # how a 70%-empty screen happens by accident rather than by choice.
        self._tail = QWidget(self)
        self._tail.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self._tail.setVisible(False)
        root.addWidget(self._tail, stretch=1)

        self.run_btn = QPushButton(i18n.t('Start the work'))
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setIcon(C.brand_dot_icon(24))
        self.run_btn.setIconSize(QSize(24, 24))
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.setMinimumHeight(44)
        self.run_btn.setEnabled(False)
        self.run_btn.setToolTip(i18n.t(
            "Make a plan first — this fills in once Prism picks the steps."))
        self.run_btn.clicked.connect(self.run_requested.emit)

        # "Start the work" is the commitment; this is the way back out of it.
        # Without it a plan you did not want could only be escaped by editing
        # the task and re-planning over the top, which is not obviously
        # possible and leaves the old plan armed in the meantime.
        # A widget, not a bare layout, so the window can lift it out of the
        # scrolling column and pin it — see main_window._work_column.
        self.cta = QWidget()
        cta = QHBoxLayout(self.cta)
        cta.setContentsMargins(0, 0, 0, 0)
        cta.setSpacing(theme.SPACE_2 + 1)
        cta.addWidget(self.run_btn, stretch=1)
        self.discard_btn = QPushButton(i18n.t('Discard'), self)
        self.discard_btn.setCursor(Qt.PointingHandCursor)
        self.discard_btn.setMinimumHeight(44)
        self.discard_btn.setToolTip(i18n.t(
            "Throws these steps away and clears the task, ready for a new "
            "one. Your attached files stay."))
        icons.button_icon(self.discard_btn, "trash", 15, theme.NEUTRAL[600])
        self.discard_btn.clicked.connect(self.discard_requested.emit)
        self.discard_btn.setVisible(False)
        cta.addWidget(self.discard_btn)
        root.addWidget(self.cta)

        # The bug this line fixes: set_run_enabled(False) hides the whole CTA
        # and clear() calls it, but __init__ never did — it only disabled the
        # button. The guard in main_window hangs off work_stack.currentChanged,
        # which does not fire on first show, so the very first thing a new user
        # saw was a full-width dead "Start the work" bar pinned to the foot of
        # an empty bench.
        self.set_run_enabled(False)
        self._refresh_shell()
        # Deferred one turn of the event loop so building the window never
        # waits on the config file.
        QTimer.singleShot(0, self.refresh_toolkit)

    # ── state ─────────────────────────────────────────────────────────────
    def set_run_enabled(self, enabled: bool):
        self.run_btn.setEnabled(enabled)
        self.run_btn.setToolTip(
            i18n.t("Runs every step still switched on.") + " "
            + i18n.t("Press Enter to start.") if enabled else
            i18n.t("Make a plan first — this fills in once Prism picks the "
                   "steps."))
        # Discard only exists while there are steps to discard.
        self.discard_btn.setVisible(enabled)
        # The whole bar goes with it: pinned to the foot of the column, an
        # always-present Start button on an empty bench is a dead control
        # occupying the most valuable strip on the screen.
        self.cta.setVisible(enabled)

    def clear(self):
        self._rows = []
        self._extras = []
        self._brief = ""
        self.intent_text.setText("")
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.extras.setVisible(False)
        self._refresh_shell()
        # With no rows there is nothing to run — leaving the CTA armed after a
        # wipe is exactly the stale-plan trap this clear() exists to avoid.
        # set_content re-enables it once the new rows are in.
        self.set_run_enabled(False)

    def _refresh_shell(self):
        """Show the plan furniture, or the centring empty state — never both.

        `_tail` and `empty_state` are the only two stretch-1 items in the
        column, so this is also what decides where the leftover window height
        lands."""
        has = bool(self._rows)
        self.subtitle.setVisible(has)
        self.count.setVisible(has)
        self.budget.setVisible(has and bool(self.budget.text()))
        self.intent.setVisible(False)
        self.empty_state.setVisible(not has)
        self.toolkit.setVisible(False)
        self._tail.setVisible(has)

    # ── the toolkit shown on an empty bench ───────────────────────────────
    def refresh_toolkit(self, agents_cfg: dict = None):
        """Draw one card per category this copy of Prism has a tool for.

        Loads the config itself when it is not handed one, so the empty
        Describe surface is never a lone sentence over a grey field on a
        machine that is fully set up. Guarded end to end — an unreadable
        config costs the region, not the screen."""
        A = CB.agents
        if agents_cfg is None:
            try:
                agents_cfg = CB.config.active_agents(CB.config.load() or {}) or {}
            except Exception:
                agents_cfg = {}
        self.toolkit_grid.clear()
        drawn = 0
        for stage in A.PIPELINE_ORDER:
            if stage == "summary":
                continue
            tool = (agents_cfg or {}).get(stage)
            if not tool:
                continue
            self.toolkit_grid.add(self._toolkit_card(stage, tool))
            drawn += 1
        self.toolkit_note.setText(
            i18n.t("{n} configured — Prism picks the ones your task needs")
            .format(n=drawn) if drawn else "")
        self._refresh_shell()

    def _toolkit_card(self, stage: str, tool: str) -> QWidget:
        A = CB.agents
        icon_name, title, blurb = STAGE_COPY.get(
            stage, ("grid", A.CATEGORIES.get(stage, {}).get("label", stage), ""))
        card = C.Card()
        col = card.body((theme.SPACE_3, theme.SPACE_3, theme.SPACE_3,
                         theme.SPACE_3), theme.SPACE_2 - 2)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2 + 2)
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(C.IconPad(icon_name, theme.ACCENT, 28, theme.R_CONTROL, 14))
        name = QLabel(title)
        name.setObjectName("h6")
        name.setWordWrap(True)
        top.addWidget(name, stretch=1)
        col.addLayout(top)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_2)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(C.ToolBadge(tool, 20, theme.R_MICRO))
        who = QLabel(tool)
        who.setObjectName("meta")
        line.addWidget(who, stretch=1)
        col.addLayout(line)
        card.setToolTip(blurb or tool)
        return card

    def set_query(self, query: str):
        """The sentence this plan came from.

        A fallback only: when the router produced a `_brief`, that is the
        better thing to show here, because the composer's own recap is already
        printing the user's words two inches higher up and a screen that says
        the same sentence twice is saying it once."""
        self._query = " ".join((query or "").split())
        if not self._brief:
            self.intent_kicker.setText(i18n.t("What you asked for").upper())
            self.intent_text.setText(self._query)
        self._refresh_shell()

    def set_content(self, routing: dict, agents_cfg: dict, query: str = ""):
        self.clear()
        A = CB.agents
        suggestions = {s.get("stage"): s
                       for s in (routing.get("_suggestions") or [])
                       if isinstance(s, dict) and s.get("stage")}
        forced = routing.get("_named_tools") or {}
        self._plan_query = query or ""
        for stage in A.PIPELINE_ORDER:
            if stage == "summary":
                continue
            data = routing.get(stage) or {}
            current = agents_cfg.get(stage)
            if not current:
                continue   # user never assigned a tool to this category at all
            questions = [q for q in (data.get("questions") or []) if q and q.strip()]
            needed = bool(data.get("needed") and questions)
            hint = suggestions.get(stage) or {}
            plan_row = PlanRow(
                stage, A.CATEGORIES.get(stage, {}), current, needed,
                hint.get("suggested"), forced.get(stage), questions,
                (hint.get("reason") or ""))
            plan_row.set_kind(data.get("kind") or "", query)
            self._add_row(plan_row)
        self._collect_extras(routing, agents_cfg)
        self._apply_file_promotion()
        # `_brief` is on the routing dict already — no wiring needed for the
        # single most useful sentence the router produces.
        self._brief = " ".join((routing.get("_brief") or "").split())
        if self._brief:
            self.intent_kicker.setText(i18n.t("How Prism read it").upper())
            self.intent_text.setText(self._brief)
        if query:
            self.set_query(query)
        self.set_run_enabled(bool(self._rows))
        self._refresh_count()
        self._refresh_shell()

    def set_attachment_count(self, count: int):
        """How many files ride along. Whenever there are any, the engine
        inserts a ChatGPT pass that reads them before the plan starts
        (automation.run's `chatgpt_analysis`) — a real step that has never
        appeared anywhere in the plan."""
        count = max(0, int(count or 0))
        if count != self._attached:
            self._attached = count
            self._refresh_extras()

    def _collect_extras(self, routing: dict, agents_cfg: dict):
        """The stages that run without ever appearing as a row.

        The plan has always under-reported the run: the router's final
        synthesis is skipped by the row loop, and the file-reading pass is
        inserted by the engine itself. Both happen, both cost time, and
        neither was visible anywhere."""
        A = CB.agents
        self._extras = []
        summary = routing.get("summary") or {}
        questions = [q for q in (summary.get("questions") or []) if q and q.strip()]
        if summary.get("needed") and questions:
            tool = A.summary_agent_name(agents_cfg) or ""
            if tool:
                self._extras.append(("summary", tool, questions))
        self._refresh_extras()

    def _refresh_extras(self):
        lines = []
        if self._attached:
            lines.append(
                (i18n.t("Prism reads your {n} attached file with ChatGPT "
                        "first, before step 1.") if self._attached == 1 else
                 i18n.t("Prism reads your {n} attached files with ChatGPT "
                        "first, before step 1.")).format(n=self._attached))
        for _stage, tool, _qs in self._extras:
            lines.append(i18n.t(
                "After the last step, {tool} folds every answer into one "
                "final summary.").format(tool=tool))
        self.extras.setText("\n".join(lines))
        self.extras.setVisible(bool(lines) and bool(self._rows))

    # ── editing ───────────────────────────────────────────────────────────
    def _add_row(self, row: PlanRow, at: int = -1):
        row.toggled.connect(self._refresh_count)
        row.changed.connect(self._on_edit)
        row.toggled.connect(self._apply_file_promotion)
        row.changed.connect(self._apply_file_promotion)
        row.move_requested.connect(self._move)
        row.remove_requested.connect(self._remove)
        row.duplicate_requested.connect(self._duplicate)
        if at < 0 or at >= len(self._rows):
            self.rows_box.addWidget(row)
            self._rows.append(row)
        else:
            self.rows_box.insertWidget(at, row)
            self._rows.insert(at, row)
        return row

    def _apply_file_promotion(self, *_args) -> None:
        """Mark the one step that will hand back a file the person asked for.

        The same choice the engine makes (contract.file_step_index), so the
        plan and the run agree on which step owes it. A writing step that
        comes before a renderer Prism drives itself is writing that
        renderer's script, which a program reads, so it is not a candidate.
        """
        rows = [r for r in self._rows if r.is_checked()]
        entries = [(r.stage,) + r.kind_and_tool() for r in rows]
        renderer_at = max((i for i, e in enumerate(entries)
                           if (e[2] or {}).get("local")), default=-1)
        entries = [(st, "data" if i < renderer_at and kind == "text" else kind, cfg)
                   for i, (st, kind, cfg) in enumerate(entries)]
        at = CB.contract.file_step_index(entries, getattr(self, "_plan_query", ""))
        for i, row in enumerate(rows):
            row.set_promoted(i == at)
        for row in self._rows:
            if not row.is_checked():
                row.set_promoted(False)

    def _move(self, row: PlanRow, delta: int):
        try:
            index = self._rows.index(row)
        except ValueError:
            return
        target = index + delta
        if not 0 <= target < len(self._rows):
            return
        self._rows.pop(index)
        self.rows_box.removeWidget(row)
        self._rows.insert(target, row)
        self.rows_box.insertWidget(target, row)
        row.mark_edited()
        self._refresh_count()
        row.setFocus()

    def _remove(self, row: PlanRow):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self.rows_box.removeWidget(row)
        row.hide()   # before setParent(None): avoids ghost-window flash
        row.setParent(None)
        row.deleteLater()
        self._refresh_count()
        self._refresh_shell()
        self.plan_changed.emit()

    def _duplicate(self, row: PlanRow):
        """A second pass at the same job.

        The engine has always supported this — custom_stages "can name any
        agent any number of times in any order" — and the only thing standing
        in the way was this panel returning a dict keyed by stage, in which
        the second copy overwrote the first."""
        if row not in self._rows:
            return
        A = CB.agents
        clone = PlanRow(row.stage, A.CATEGORIES.get(row.stage, {}),
                        row.selected_agent(), True, "", "",
                        row.questions(), "")
        clone.mark_edited()
        self._add_row(clone, at=self._rows.index(row) + 1)
        self._refresh_count()
        self.plan_changed.emit()

    def _on_edit(self):
        self._refresh_count()
        self.plan_changed.emit()

    def _refresh_count(self):
        for i, row in enumerate(self._rows, start=1):
            row.set_index(i, last=i == len(self._rows))
        on = sum(1 for r in self._rows if r.is_checked())
        if not self._rows:
            self.count.setText("")
            self.budget.setText("")
        else:
            # Assembled through t() rather than as an f-string: by the time an
            # f-string reaches setText the sentence is already built and
            # matches nothing in the catalogue. Two forms because the singular
            # and plural are different sentences in most languages, and the
            # placeholders are named so a translator can reorder them.
            # Both literals sit inside a t() call rather than being chosen
            # into a variable first: devtools/extract_strings.py reads the
            # source, so a key it cannot see never reaches a translator.
            self.count.setText(
                (i18n.t("{n} step of {total}") if on == 1
                 else i18n.t("{n} steps of {total}")
                 ).format(n=on, total=len(self._rows)))
            # Not an estimate of how long the work takes — it is the sum of
            # the per-tool timeouts Prism will actually honour, which is a
            # real number the registry already carries. Labelled "waits up
            # to" so it cannot be read as a prediction.
            seconds = sum(r.wait_seconds() for r in self._rows if r.is_checked())
            self.budget.setText(
                i18n.t("waits up to {t}").format(t=_minutes(seconds))
                if seconds else "")
            self.budget.setVisible(bool(seconds))
        self.set_run_enabled(on > 0)

    # ── what the run gets ─────────────────────────────────────────────────
    def selected_steps(self) -> list:
        """The plan as the engine wants it: an ordered list of
        `(stage_label, agent_name, questions)` tuples, ready to hand to
        `automation.run(custom_stages=…)`.

        This is the channel that makes the other five editing capabilities
        real. `selected_agents()` — a dict keyed by stage — can express only
        *which stages run* and *which tool runs each*; order, a rewritten
        prompt and a duplicated step are all inexpressible through it, which
        is why the plan editor could not offer them.

        Labels are unique within the list, which is all the engine requires
        (`automation.run`'s docstring: "Stage labels only need to be unique
        WITHIN this list"). A duplicated step gets " 2", " 3" appended.

        The final `summary` step is appended here even though it is not a row.
        That is load-bearing rather than tidy: passing `custom_stages` bypasses
        `automation._needed_stages`, which is the only thing that was adding
        the router's synthesis pass to a run. Leaving it out would silently
        drop the last step of every plan the day this list starts being used.
        """
        out, seen = [], {}
        for row in self._rows:
            if not row.is_checked():
                continue
            agent = row.selected_agent()
            if not agent:
                continue
            seen[row.stage] = seen.get(row.stage, 0) + 1
            label = row.stage if seen[row.stage] == 1 else \
                f"{row.stage} {seen[row.stage]}"
            out.append((label, agent, row.questions()))
        if out:
            for stage, tool, questions in self._extras:
                out.append((stage, tool, list(questions)))
        return out

    def apply_prompts(self, steps: list):
        """Put rewritten prompts back on the rows, in the order
        selected_steps() handed them out -- the ticked rows first, then the
        extras (the summary pass) that are not rows."""
        rows = [r for r in self._rows if r.is_checked() and r.selected_agent()]
        for row, step in zip(rows, steps):
            row.set_questions(list(step[2]) if len(step) > 2 else [])
        rest = steps[len(rows):]
        self._extras = [(stage, tool, list(step[2]) if len(step) > 2 else list(qs))
                        for (stage, tool, qs), step in zip(self._extras, rest)] \
            + list(self._extras[len(rest):])

    def ensure_prompts(self) -> None:
        """Ensure every checked row has a prompt before execution."""
        for row in self._rows:
            if row.is_checked() and row.selected_agent() and not row.questions():
                prompt = default_prompt_for_stage(row.stage, self._query)
                row.set_questions([prompt])
                row._origin = ORIGIN_YOURS
                row._apply_skin()

    def unprompted_steps(self) -> list:
        """Titles of the steps that are ticked to run but carry no prompt.

        The router writes prompts only for the steps it planned; a step the
        owner ticks on by hand starts with none, and selected_steps() hands
        it to the engine exactly like that — a stage that uploads the files,
        asks nothing, and waits the whole cap. Asked before the run starts so
        the refusal can name the step rather than the engine discovering it
        five minutes in.
        """
        return [row.title() for row in self._rows
                if row.is_checked() and row.selected_agent()
                and not row.questions()]

    def left_out_stages(self) -> list:
        """Stage keys of the rows the owner actually TURNED OFF.

        Handed to the engine as `skip_stages`: a few stages are inserted by
        the engine rather than planned here (Studio's image maker), and
        unticking their row has to reach them or the run puts them straight
        back.

        Only a row the person actually switched off counts. A row the
        planner never turned on, and nobody touched, is not a decision, and
        sending it here reads to the engine as one — which is how a reel
        whose plan happened to omit "Make the images" came out with no
        pictures and nothing on screen saying why.
        """
        return [row.stage for row in self._rows
                if not row.is_checked()
                and (row.was_planned() or row.was_touched())]

    def unprompted_stages(self) -> list:
        """The same rows by stage key — what selected_agents() is keyed by,
        so a run can drop exactly these and nothing else."""
        return [row.stage for row in self._rows
                if row.is_checked() and row.selected_agent()
                and not row.questions()]

    def selected_agents(self) -> dict:
        """{stage: agent_name} for every step still switched on.

        The compatibility shim. `_run_pipeline`'s add-on entitlement check and
        the CTA visibility guard both only ever ask "which tools are in this
        plan", and a dict answers that fine. The run itself should go through
        `selected_steps()`, which can also express order and duplicates.
        """
        return {r.stage: r.selected_agent()
                for r in self._rows if r.is_checked()}

    def rows(self) -> list:
        return list(self._rows)

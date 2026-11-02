"""The task card — step 1 of the workbench, and the front door to the product.

An orchestration command centre, not a chat box. Everything an operator needs
to hand Prism a job is on this one card:

    the task itself, as an obvious input rather than a line of grey placeholder
    the things it should work from  — files, folders, spoken words
    the things it could be          — the tasks you have run before
    the things it can be            — a few worked examples
    one, and exactly one, primary action

The three regions below the composer (attached context, recent tasks,
examples) are the answer to the screen being 69.5% empty grey: they are all
real, they are all one click from starting work, and they disappear the moment
a plan exists — at which point the composer collapses to a one-line recap and
the plan takes the screen.

The blueprint frame this used to sit in is gone — see style.qss's header for
why the registration marks were retired in favour of the stripe.
"""
from __future__ import annotations
import os

from PySide6.QtCore import QSize, Signal, QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFrame, QLabel, QTextEdit, QPushButton,
    QSizePolicy,
)

import i18n
from widgets.loader import Loader
import theme
from widgets import icons
from widgets import controls as C
from widgets.controls import Card, Pill, kicker
from widgets.files_panel import kind_label, size_label

# state key -> (pill text, tone)
# Named STATES, not _STATES: devtools/extract_strings.py scans module-level
# copy tables by exact name, and the underscored version was invisible to it —
# so "Waiting on you" and "Ready to plan", the two words on this card a
# first-time user reads first, have never reached a translator.
STATES = {
    "empty":   ("Waiting on you", "neutral"),
    "ready":   ("Ready to plan",  "accent"),
    "routing": ("Planning…",      "warn"),
    "planned": ("Ready to run",   "accent"),
    "running": ("Working…",       "warn"),
    "done":    ("Finished",       "ok"),
}

def examples() -> list[tuple[str, str]]:
    """Worked examples. UI copy, not data.

    They are on the card as suggestions of the SHAPE a good task takes — a
    deliverable, an audience, a source — which is the single thing a
    first-time user gets wrong. Clicking one fills the composer so it can be
    edited rather than run blind.

    A function with the literals inside t() rather than a module-level table:
    devtools/extract_strings.py scans tables only by exact name, and a
    sentence that reaches the screen without reaching a translator is what the
    catalogue exists to prevent. It also means these follow a language change
    mid-session, which a table read once at import does not.
    """
    return [
        (i18n.t("Research and write"),
         i18n.t("Research the top five competitors in our region, work out "
                "where we win, and draft a one-page positioning note.")),
        (i18n.t("Find and reach out"),
         i18n.t("Find ten manufacturing companies near Ahmedabad, get the "
                "name and email of whoever runs purchasing, and draft an "
                "introduction email to each.")),
        (i18n.t("Turn a file into a deck"),
         i18n.t("Read the attached specification and build a ten-slide deck "
                "a customer could sit through.")),
        (i18n.t("Make the campaign"),
         i18n.t("Write three social posts for our new product and generate "
                "an image to go with each one.")),
    ]


def _action(label: str, icon_name: str, tip: str = "") -> QPushButton:
    btn = QPushButton(label)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setMinimumHeight(C.MIN_TARGET + 4)
    icons.button_icon(btn, icon_name, 15, theme.NEUTRAL[600])
    if tip:
        btn.setToolTip(tip)
    return btn


class _QueuedTaskRow(QFrame):
    """One task waiting its turn, with the number it will run in."""

    def __init__(self, index: int, text: str, on_remove, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        row.setSpacing(9)

        num = QLabel(str(index))
        num.setObjectName("tagNeutral")
        num.setAlignment(Qt.AlignCenter)
        num.setFixedWidth(22)
        row.addWidget(num)

        # Elide in the label rather than truncating the stored text: the queue
        # holds the real task, this only has to be recognisable at a glance.
        one_line = " ".join(text.split())
        label = QLabel(one_line if len(one_line) <= 78 else one_line[:77] + "…")
        label.setToolTip(text)
        row.addWidget(label, stretch=1)

        drop = QPushButton()
        drop.setObjectName("smallBtn")
        drop.setCursor(Qt.PointingHandCursor)
        drop.setToolTip(i18n.t("Remove this task"))
        drop.setFixedWidth(28)
        icons.button_icon(drop, "x", 13, theme.TEXT)
        drop.clicked.connect(on_remove)
        row.addWidget(drop)


class _StarterRow(QFrame):
    """A task you have run before, offered back as a starting point.

    Real, and only real: title, the tools that ran it and when, straight out
    of the saved run records under the member's runs folder. If the folder is
    empty the whole region is not drawn — there is no placeholder version of
    this."""

    chosen = Signal(str)

    def __init__(self, record: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("listRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._text = (record.get("title") or "").strip()

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_2 + 1,
                               theme.SPACE_3, theme.SPACE_2 + 1)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("clock", theme.ACCENT, 28, theme.R_CONTROL, 14))

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        one_line = " ".join(self._text.split())
        title = QLabel(one_line if len(one_line) <= 62 else one_line[:61] + "…")
        title.setStyleSheet(theme.type_css("SUPPORT", theme.TEXT))
        title.setToolTip(self._text)
        col.addWidget(title)
        detail = " · ".join([b for b in (
            ", ".join(record.get("tools") or []), record.get("when") or "") if b])
        sub = QLabel(detail, self)
        sub.setObjectName("meta")
        sub.setVisible(bool(detail))
        col.addWidget(sub)
        row.addLayout(col, stretch=1)

        use = QPushButton(i18n.t("Use again"))
        use.setObjectName("ghostBtn")
        use.setCursor(Qt.PointingHandCursor)
        use.setMinimumHeight(C.MIN_TARGET)
        use.clicked.connect(self._emit)
        row.addWidget(use)
        self.setAccessibleName(f"{one_line}. {detail}")

    def _emit(self):
        self.chosen.emit(self._text)

    def mousePressEvent(self, event):
        self._emit()
        super().mousePressEvent(event)


class _AttachmentChip(QFrame):
    removed = Signal(str)
    activated = Signal(str)

    def __init__(self, att: dict, parent=None):
        super().__init__(parent)
        self.att = att
        self.path = att.get("path") or ""
        name = att.get("name") or os.path.basename(self.path)
        kind = att.get("kind") or "file"
        size = size_label(self.path)

        self.setObjectName("attachmentChip")
        self.setStyleSheet(f"""
            QFrame#attachmentChip {{
                background-color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.14);
                border-radius: 8px;
            }}
            QFrame#attachmentChip:hover {{
                border-color: rgba(0, 0, 0, 0.35);
                background-color: #fafafa;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("folder" if kind == "folder" else "file", 14, theme.ACCENT))
        row.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-weight: 500; font-size: 12px; color: #18181b;")
        row.addWidget(name_lbl)

        if size:
            size_lbl = QLabel(f"· {size}")
            size_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
            row.addWidget(size_lbl)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip(i18n.t("Remove this file"))
        close_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                color: #71717a;
                font-size: 15px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                color: #dc2626;
            }
        """)
        close_btn.clicked.connect(lambda *_: self.removed.emit(self.path))
        row.addWidget(close_btn)

        self.setToolTip(self.path or name)

    def mouseDoubleClickEvent(self, event):
        if self.path:
            self.activated.emit(self.path)
        super().mouseDoubleClickEvent(event)


class _FolderAttachmentChip(QFrame):
    removed = Signal(str)
    activated = Signal(str)

    def __init__(self, folder_path: str, files: list, parent=None):
        super().__init__(parent)
        self.folder_path = folder_path
        name = os.path.basename(folder_path.rstrip("/\\")) or folder_path
        count = len(files)

        self.setObjectName("attachmentChip")
        self.setStyleSheet(f"""
            QFrame#attachmentChip {{
                background-color: #ffffff;
                border: 1px solid rgba(0, 0, 0, 0.14);
                border-radius: 8px;
            }}
            QFrame#attachmentChip:hover {{
                border-color: rgba(0, 0, 0, 0.35);
                background-color: #fafafa;
            }}
        """)

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("folder", 14, theme.ACCENT))
        row.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("font-weight: 500; font-size: 12px; color: #18181b;")
        row.addWidget(name_lbl)

        count_lbl = QLabel(f"· {count} files" if count != 1 else "· 1 file")
        count_lbl.setStyleSheet("font-size: 11px; color: #71717a;")
        row.addWidget(count_lbl)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setToolTip(i18n.t("Remove this folder"))
        close_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                color: #71717a;
                font-size: 15px;
                font-weight: bold;
                padding: 0;
            }
            QPushButton:hover {
                color: #dc2626;
            }
        """)
        close_btn.clicked.connect(lambda *_: self.removed.emit(self.folder_path))
        row.addWidget(close_btn)

        self.setToolTip(f"{folder_path}\n({count} files attached — double-click to open folder)")

    def mouseDoubleClickEvent(self, event):
        if self.folder_path:
            self.activated.emit(self.folder_path)
        super().mouseDoubleClickEvent(event)


class InputPanel(Card):
    route_clicked = Signal(str)
    cancel_route_clicked = Signal()
    mic_toggle_clicked = Signal()
    attach_file_clicked = Signal()
    attach_folder_clicked = Signal()
    detach_requested = Signal(str)
    detach_folder_requested = Signal(str)
    queue_changed = Signal(int)     # how many tasks are queued behind this one
    attachment_activated = Signal(str)   # a path the user asked to open

    _MIN_H, _MAX_H = 108, 240

    # style.qss draws #taskEdit as a transparent, borderless box with a 2px
    # underline. That is precisely the complaint the redesign starts from —
    # the most important input in the product does not look like an input.
    # The stylesheet belongs to the design system agent, so the composer
    # carries its own drawn well here instead: an inset field with a real
    # border that lifts to white and an accent edge on focus.
    @staticmethod
    def _EDITOR_QSS() -> str:
        return (f"#taskEdit {{ background: {theme.WELL};"
                f" border: 1px solid {theme.BORDER};"
                f" border-radius: {theme.R_CONTROL}px;"
                f" padding: {theme.SPACE_3}px; }}"
                f"#taskEdit:focus {{ background: {theme.CARD};"
                f" border: 1px solid {theme.ACCENT}; }}")

    @staticmethod
    def _RECAP_QSS() -> str:
        """Settled text, not a field: no border, no fill, nothing to type into."""
        return (f"#taskEdit {{ background: transparent; border: none;"
                f" padding: 0; "
                + theme.type_css("BODY", theme.NEUTRAL[800]) + " }")

    def __init__(self, parent=None):
        super().__init__(stripe=True, radius=theme.R_HERO, raised=True,
                         parent=parent)
        self._busy = False
        self.content = self.body((theme.CARD_PAD, theme.CARD_PAD,
                                  theme.CARD_PAD, theme.CARD_PAD), spacing=0)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        head.addWidget(kicker(i18n.t("Your task")), stretch=1)
        self.state_pill = Pill()
        head.addWidget(self.state_pill)
        self.content.addLayout(head)
        self.content.addSpacing(theme.SPACE_3 - 2)

        # ── the composer ─────────────────────────────────────────────────
        # A drawn, focusable well rather than a line of placeholder text on a
        # white card. The complaint the redesign starts from is that the most
        # important input in the product did not look like an input at all.
        self.text = C.SubmitTextEdit()
        self.text.setObjectName("taskEdit")
        self.text.submitted.connect(self._submit_from_keyboard)
        self.text.setFrameShape(QTextEdit.NoFrame)
        self.text.setPlaceholderText(i18n.t(
            "Describe the job in your own words — what you want, who it is "
            "for, and anything Prism should work from."))
        self.text.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text.textChanged.connect(self._on_text_changed)
        # Grow with the task instead of reserving a fixed block: a one-line
        # task shouldn't leave a hole between it and the buttons.
        self.text.document().documentLayout().documentSizeChanged.connect(
            self._autosize)
        self.text.setStyleSheet(self._EDITOR_QSS())
        self.text.setFixedHeight(self._MIN_H)
        self.content.addWidget(self.text)

        # Naming a file out loud is Prism's least discoverable feature and one
        # of its best — the router resolves the description against the disk
        # and offers the match for confirmation. Saying so under the field is
        # the whole of the teaching.
        self.hint = C.icon_label(
            "paperclip",
            i18n.t("Name a file or folder in plain English — “the tender in "
                   "my Documents folder” — and Prism will go and find it."),
            14, theme.NEUTRAL[500])
        self.hint.layout().itemAt(1).widget().setObjectName("meta")
        self.hint.layout().itemAt(1).widget().setWordWrap(True)
        self.content.addWidget(self.hint)
        self.content.addSpacing(theme.SPACE_2)

        # ── attached files bar (stuck right under the message bar) ────────────
        self.attachments_bar = QWidget(self)
        self._attachments_flow = C.FlowLayout(self.attachments_bar, margin=0, h_space=6, v_space=6)
        self.attachments_bar.setVisible(False)
        self.content.addWidget(self.attachments_bar)
        self.content.addSpacing(theme.SPACE_2)

        # ── the queue ────────────────────────────────────────────────────────
        # Tasks the user lined up before starting. Prism plans and runs them in
        # order, so this list IS the running order — hence the numbers.
        self._queue: list[str] = []
        self.queue_box = QWidget(self)
        qv = QVBoxLayout(self.queue_box)
        qv.setContentsMargins(0, 0, 0, 0)
        qv.setSpacing(5)
        self.queue_head = QLabel("")
        self.queue_head.setObjectName("meta")
        qv.addWidget(self.queue_head)
        self.queue_rows = QWidget()
        self._queue_layout = QVBoxLayout(self.queue_rows)
        self._queue_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_layout.setSpacing(4)
        qv.addWidget(self.queue_rows)
        self.queue_box.setVisible(False)
        self.content.addWidget(self.queue_box)

        self.actions_row = QWidget()
        row = QHBoxLayout(self.actions_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.mic_btn = C.VoiceInputButton(i18n.t("Speak"), self)
        self.mic_btn.setToolTip(i18n.t("Dictate the task instead of typing"))
        self.mic_btn.clicked.connect(self.mic_toggle_clicked.emit)
        row.addWidget(self.mic_btn)

        self.attach_file_btn = _action(i18n.t("Add file"), "paperclip",
                                       i18n.t("Attach a file from your computer"))
        self.attach_file_btn.clicked.connect(self.attach_file_clicked.emit)
        row.addWidget(self.attach_file_btn)

        self.attach_folder_btn = _action(i18n.t("Add folder"), "folder",
                                         i18n.t("Attach a whole folder"))
        self.attach_folder_btn.clicked.connect(self.attach_folder_clicked.emit)
        row.addWidget(self.attach_folder_btn)

        self.add_task_btn = _action(
            i18n.t("Add task"), "plus",
            i18n.t("Queue this one and type another — Prism runs them in order"))
        self.add_task_btn.clicked.connect(self._queue_current)
        row.addWidget(self.add_task_btn)
        row.addStretch(1)

        self.route_btn = QPushButton(i18n.t("Make a plan"))
        self.route_btn.setObjectName("primaryBtn")
        self.route_btn.setIcon(C.brand_dot_icon(22))
        self.route_btn.setIconSize(QSize(22, 22))
        self.route_btn.setCursor(Qt.PointingHandCursor)
        self.route_btn.setToolTip(i18n.t(
            "Press Enter to make the plan. Shift+Enter starts a new line."))
        self.route_btn.setMinimumHeight(C.MIN_TARGET + 10)
        self.route_btn.clicked.connect(self._on_route_btn_clicked)
        row.addWidget(self.route_btn)
        self.content.addWidget(self.actions_row)

        # Voice feedback ("heard: …") — hidden until there's something to say,
        # so the card keeps its shape in the common case.
        self.status = QLabel("", self)
        self.status.setObjectName("meta")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        self.status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.content.addWidget(self.status)

        # Planning is a licence check and an AI call: Prism's orb, with the
        # words, until the plan arrives.
        self.thinking = Loader("orb")
        self.thinking.setVisible(False)
        self.content.addWidget(self.thinking)

        # ── context: what Prism is holding for this task ─────────────────
        self.context_box = QWidget(self)
        ctx = QVBoxLayout(self.context_box)
        ctx.setContentsMargins(0, theme.SPACE_4, 0, 0)
        ctx.setSpacing(theme.SPACE_2)
        ctx.addWidget(C.hairline())
        ctx_head = QHBoxLayout()
        ctx_head.setSpacing(theme.SPACE_2)
        ctx_head.addWidget(kicker(i18n.t("Working from"), muted=True), stretch=1)
        self.context_count = C.Pill("", "quiet")
        ctx_head.addWidget(self.context_count)
        ctx.addLayout(ctx_head)
        self.context_rows = QWidget()
        self._context_layout = QVBoxLayout(self.context_rows)
        self._context_layout.setContentsMargins(0, 0, 0, 0)
        self._context_layout.setSpacing(theme.SPACE_1 + 2)
        ctx.addWidget(self.context_rows)
        self.context_box.setVisible(False)
        self.content.addWidget(self.context_box)

        # ── starters: real recent tasks, and worked examples ─────────────
        self.starters = QWidget()
        st = QVBoxLayout(self.starters)
        st.setContentsMargins(0, theme.SPACE_4, 0, 0)
        st.setSpacing(theme.SPACE_3)
        st.addWidget(C.hairline())

        cols = QHBoxLayout()
        cols.setSpacing(theme.SPACE_6)

        self.recent_box = QWidget(self)
        rc = QVBoxLayout(self.recent_box)
        rc.setContentsMargins(0, 0, 0, 0)
        rc.setSpacing(theme.SPACE_2)
        rc.addWidget(kicker(i18n.t("Pick up where you left off"), muted=True))
        self.recent_rows = QWidget()
        self._recent_layout = QVBoxLayout(self.recent_rows)
        self._recent_layout.setContentsMargins(0, 0, 0, 0)
        self._recent_layout.setSpacing(theme.SPACE_1 + 2)
        rc.addWidget(self.recent_rows)
        rc.addStretch(1)
        self.recent_box.setVisible(False)
        cols.addWidget(self.recent_box, stretch=3)

        example_box = QWidget()
        ex = QVBoxLayout(example_box)
        ex.setContentsMargins(0, 0, 0, 0)
        ex.setSpacing(theme.SPACE_2)
        ex.addWidget(kicker(i18n.t("Or start from one of these"), muted=True))
        for title, body in examples():
            ex.addWidget(self._example(title, body))
        ex.addStretch(1)
        cols.addWidget(example_box, stretch=2)
        st.addLayout(cols)
        self.content.addWidget(self.starters)

        self._blink = QTimer(self)
        self._blink.setInterval(600)
        self._blink.timeout.connect(self._pulse_mic)
        self._blink_on = False
        self._state = "empty"
        self._compact = False
        self.set_state("empty")
        # Deferred one event loop turn so building the window never waits on
        # the disk. A workspace with no runs simply draws nothing here.
        QTimer.singleShot(0, self.refresh_recent)

    # ── starters ──────────────────────────────────────────────────────────
    def refresh_recent(self):
        """Re-read the member's own saved runs.

        Called once on construction and again by the window after a run
        finishes, so "pick up where you left off" is never stale. Guarded
        end-to-end: an unreadable runs folder must cost the region, not the
        screen."""
        try:
            import core_bridge as CB
            import dashboard_data
            # Ask for more than we show, then drop the runs that never got a
            # task out of the user. `recent_runs` titles those "Untitled task",
            # and this workspace has 86 of them in a row (all one Chrome
            # failure), so unfiltered this region offered three identical
            # "Untitled task — Use again" rows. Pressing one would have put
            # nothing in the box, because there is no text to bring back.
            # History still lists them; they are just not something to resume.
            runs = dashboard_data.recent_runs(CB.config.load() or {}, 30)
            resumable = [r for r in runs if (r.get("title") or "").strip()
                         and r.get("title") != "Untitled task"]
            self.set_recent(resumable[:3])
        except Exception:
            self.set_recent([])

    def _example(self, title: str, body: str) -> QPushButton:
        btn = QPushButton(title)
        btn.setObjectName("linkBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setMinimumHeight(C.MIN_TARGET)
        btn.setToolTip(body)
        icons.button_icon(btn, "arrow-right", 14, theme.ACCENT_RAMP[700])
        btn.clicked.connect(lambda _=False, b=body: self._use_starter(b))
        return btn

    def _use_starter(self, text: str):
        self.text.setPlainText(text)
        self.text.setFocus()
        cursor = self.text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.text.setTextCursor(cursor)

    def set_recent(self, records: list):
        """The last few saved runs, offered as starting points.

        Fed from dashboard_data.recent_runs(), which reads the member's own
        run folder. An empty folder draws nothing at all — there is no
        placeholder recent task, because a fabricated one is the first thing
        a customer would spot."""
        while self._recent_layout.count():
            item = self._recent_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        rows = [r for r in (records or []) if (r.get("title") or "").strip()][:3]
        for record in rows:
            row = _StarterRow(record)
            row.chosen.connect(self._use_starter)
            self._recent_layout.addWidget(row)
        self.recent_box.setVisible(bool(rows))

    # ── attached context ──────────────────────────────────────────────────
    def set_context(self, attachments: list):
        """The files this task will be run against, on the Describe surface
        itself rather than only inside a 44px collapsed rail."""
        items = list(attachments or [])

        # 1. Update the attachment chips bar (stuck right near the message bar)
        while self._attachments_flow.count():
            item = self._attachments_flow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        folders = {}
        loose = []
        for att in items:
            folder = att.get("from_dir")
            if folder:
                folders.setdefault(folder, []).append(att)
            else:
                loose.append(att)

        for folder_path, files in folders.items():
            chip = _FolderAttachmentChip(folder_path, files)
            chip.removed.connect(self.detach_folder_requested.emit)
            chip.activated.connect(self.attachment_activated.emit)
            self._attachments_flow.addWidget(chip)

        for att in loose:
            chip = _AttachmentChip(att)
            chip.removed.connect(self.detach_requested.emit)
            chip.activated.connect(self.attachment_activated.emit)
            self._attachments_flow.addWidget(chip)

        self.attachments_bar.setVisible(bool(items) and not self._compact)

        # 2. Also keep context_box updated for full context details
        while self._context_layout.count():
            item = self._context_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for att in items[:4]:
            name = att.get("name") or os.path.basename(att.get("path") or "")
            bits = [b for b in (kind_label(att), size_label(att.get("path"))) if b]
            if att.get("truncated"):
                bits.append(i18n.t("first part only"))
            p = att.get("path") or ""
            drop = C.icon_button("x", i18n.t("Remove this file"),
                                 lambda *_, path=p: self.detach_requested.emit(path))
            drop.setFixedSize(26, 26)
            row = C.FileItem(name, " · ".join(bits),
                             "folder" if att.get("kind") == "folder" else "file",
                             actions=[drop])
            row.setToolTip(p or name)
            row.activated.connect(
                lambda *_, path=p: self.attachment_activated.emit(path))
            self._context_layout.addWidget(row)
        extra = len(items) - 4
        if extra > 0:
            more = QLabel(i18n.t("and {n} more").format(n=extra))
            more.setObjectName("meta")
            self._context_layout.addWidget(more)
        self.context_count.setText(
            (i18n.t("{n} file") if len(items) == 1
             else i18n.t("{n} files")).format(n=len(items)))
        self.context_box.setVisible(bool(items) and not self._compact)

    # ── the task queue ────────────────────────────────────────────────────
    def _queue_current(self):
        """Move whatever is in the box onto the queue and clear it for the
        next one. Deliberately not allowed while a run is going: the queue is
        read once when the run starts, so appending mid-run would silently do
        nothing."""
        text = self.text.toPlainText().strip()
        if not text:
            self.append_status(i18n.t("Type the task first, then Add task."))
            return
        if self._state in ("routing", "running"):
            return
        self._queue.append(text)
        self.text.clear()
        self.append_status("")
        self._render_queue()
        self.set_state("empty")
        self.queue_changed.emit(len(self._queue))

    def _render_queue(self):
        while self._queue_layout.count():
            item = self._queue_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for i, task in enumerate(self._queue):
            self._queue_layout.addWidget(
                _QueuedTaskRow(i + 1, task,
                               lambda _=False, n=i: self._remove_task(n)))
        n = len(self._queue)
        self.queue_head.setText(
            "" if not n else
            (i18n.t("{n} task queued — it runs first, and the box below is "
                    "the last one.") if n == 1 else
             i18n.t("{n} tasks queued — they run in this order, and the box "
                    "below is the last one.")).format(n=n))
        self.queue_box.setVisible(bool(n))

    def _remove_task(self, index: int):
        if 0 <= index < len(self._queue):
            self._queue.pop(index)
            self._render_queue()
            self.queue_changed.emit(len(self._queue))
            # Dropping the last queued task while the box is empty leaves
            # nothing to plan — put the chip back to match.
            if not self._queue and not self.text.toPlainText().strip():
                self.set_state("empty")
            elif self._state == "empty" and self._queue:
                self.set_state("ready")

    def tasks(self) -> list[str]:
        """Everything to run, in order: the queue, then whatever is still in
        the box. The box counts as the final task so the user never has to
        press Add task before Show steps."""
        tail = self.text.toPlainText().strip()
        return self._queue + ([tail] if tail else [])

    def clear_queue(self):
        self._queue = []
        self._render_queue()
        self.queue_changed.emit(0)

    # ── state ─────────────────────────────────────────────────────────────
    def set_compact(self, on: bool):
        """Shrink to a read-only recap of the task, or open back up.

        Once a plan exists the composer has done its job, and leaving it at
        full height pushed nine plan rows and the Start button below the fold —
        with "Make a plan" still sitting there as the most prominent control on
        a screen whose actual next step is "Start the work". The design replaces
        the composer with a one-line recap at this point; this is that.
        """
        if on == getattr(self, "_compact", None):
            return
        self._compact = on
        self.actions_row.setVisible(not on)
        self.hint.setVisible(not on)
        self._sync_starters()
        self.text.setReadOnly(on)
        self.text.setFixedHeight(
            self._recap_height() if on else max(self._MIN_H, self.text.height()))
        self.text.setStyleSheet(self._RECAP_QSS() if on else self._EDITOR_QSS())
        # With the button row hidden, the composer's generous bottom padding
        # became a band of empty card under a single line of text.
        left, top, right, _bottom = self.content.getContentsMargins()
        self.content.setContentsMargins(left, top, right,
                                        theme.SPACE_4 if on else theme.CARD_PAD)
        if on:
            self.queue_box.setVisible(False)
            self.status.setVisible(False)
            self.attachments_bar.setVisible(False)
            self.context_box.setVisible(False)
        else:
            # Visibility only. Calling _render_queue() here tore down and
            # rebuilt every queued-task row — and since _on_text_changed drives
            # set_state on each keystroke, that meant deleteLater() churn on the
            # whole queue for every character typed.
            self.queue_box.setVisible(bool(self._queue))
            self.attachments_bar.setVisible(self._attachments_flow.count() > 0)
            self.context_box.setVisible(self._context_layout.count() > 0)
            self._autosize()

    def _recap_height(self) -> int:
        return max(24, int(self.text.document().size().height()) + 4)

    def set_state(self, key: str):
        """Drive the chip. Also gates the CTA: there's nothing to plan until
        the box has words in it."""
        if key not in STATES:
            return
        self._state = key
        label, tone = STATES[key]
        self.state_pill.setText(i18n.t(label))
        self.state_pill.set_tone(tone)
        # "planned" is the only state where the composer is on screen with a
        # plan already made. routing/running/done either show a spinner here or
        # switch the stack to the output panel entirely.
        self.set_compact(key == "planned")
        # A queued task is enough to plan with even when the box is empty —
        # otherwise "Add task" would disable the very button it leads to.
        self.route_btn.setEnabled(
            key in ("ready", "planned", "done")
            or (key == "empty" and bool(self._queue)))
        self.add_task_btn.setEnabled(key not in ("routing", "running"))

    def _autosize(self):
        height = int(self.text.document().size().height()) + 4
        if getattr(self, "_compact", False):
            # Hug the text exactly while it is a recap — the composer's floor
            # exists to give you somewhere to type, and there is nowhere to
            # type here.
            self.text.setFixedHeight(self._recap_height())
            return
        self.text.setFixedHeight(max(self._MIN_H, min(self._MAX_H, height)))

    def _on_text_changed(self):
        if self._state in ("empty", "ready"):
            self.set_state("ready" if self.text.toPlainText().strip() else "empty")
        self._sync_starters()

    def _sync_starters(self):
        """Recent tasks and examples are for an EMPTY box.

        They exist to answer "what do I even type here"; the moment there are
        words in the field that question is answered, and leaving 200px of
        suggestions between the task and its plan pushes the plan below the
        fold. So they retire as soon as you start writing, and come back if
        you clear it."""
        self.starters.setVisible(
            not self._compact and not self.text.toPlainText().strip())

    def reset(self):
        """Empty the card for a fresh task. set_state comes last: clear()
        fires textChanged, and _on_text_changed ignores it while the state is
        still 'done'."""
        self.text.clear()
        self.append_status("")
        self.clear_queue()
        self.set_state("empty")

    def set_query_text(self, text: str):
        self.text.setPlainText(text)

    def append_status(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_recording(self, on: bool):
        self.mic_btn.set_recording(on)

    def _pulse_mic(self):
        pass

    def _submit_from_keyboard(self):
        """Enter in the composer: the same as pressing Make a plan, and only
        when that button would work. While busy the button reads Cancel, and a
        stray Enter must never mean that."""
        if not self._busy and self.route_btn.isEnabled():
            self.route_btn.click()

    def _on_route_btn_clicked(self):
        """The same button does both jobs, like mic_btn's Speak/Stop — while
        busy it reads "Cancel" and means that instead of "Make a plan"."""
        if self._busy:
            self.cancel_route_clicked.emit()
        else:
            self.route_clicked.emit(self.text.toPlainText())

    def set_busy_message(self, text: str):
        """What the wait is on right now ("Checking your licence…")."""
        self.thinking.set_message(text)

    def set_busy(self, busy: bool):
        self._busy = busy
        if busy and not self.thinking.isVisibleTo(self):
            self.thinking.set_message(i18n.t("Making a plan for your task…"))
        self.thinking.setVisible(busy)
        self.route_btn.setText(
            i18n.t('Cancel') if busy else i18n.t('Make a plan'))
        # The Enter hint is about making the plan; while the button reads
        # Cancel it would be wrong.
        self.route_btn.setToolTip("" if busy else i18n.t(
            "Press Enter to make the plan. Shift+Enter starts a new line."))
        if busy:
            self.set_state("routing")
        # Enabled either way: "routing" disables it in set_state (nothing to
        # route to yet), but busy needs it clickable as Cancel instead. When
        # not busy, the caller always follows with its own set_state() right
        # after, which re-settles this correctly for that state.
        self.route_btn.setEnabled(True)

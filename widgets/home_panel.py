"""Home — the command centre Prism opens on.

Prism used to open straight onto an empty composer. That is the right screen
for someone who already knows what they want to type, and the wrong one for
everybody else: it answers "what do I do now" with a blank box, and says
nothing about what the app has already done for you.

So Home is a report, and it answers six questions in order:

    what can I do      the hero, with the one primary action on the screen
    what is running    the active-run section, pushed in live by the window
    how did it go      four figures over the runs this workspace actually has
    what happened      recent activity, then the add-ons you own
    what is connected  which tool each pipeline stage is set up to drive
    how do I start     "Describe a task", and three quick-starts beside it

Every figure comes out of dashboard_data, which reads the real run records and
the real inquiry register. Where a store is empty the card says so plainly
instead of showing a zero that looks like data.

Two things this file is deliberately careful about, because both have bitten:

**Nothing here may report its full text width as its minimum.** A plain QLabel
does, and one 143-character run title (there is a real one in the shipped
data) dragged Home's inner widget out to 1391px inside a 1200px viewport — so
the third figure and the whole add-ons column were clipped off the right edge
of the window, with the horizontal scrollbar switched off to hide it. Worse,
it came and went with whatever happened to be in the runs folder that hour, so
it looked like an intermittent fault rather than a missing `elidedText` call.
Anything that renders user data on this screen goes through `_Elided`.

**A "failed" run and a run that never started are different events.** 86 of the
102 records in the shipped workspace have no query, no tools and
`"error": "Chrome would not launch"` — they are the same environment fault
recorded 86 times, not 86 failed jobs. Rendering four of them as "Untitled task
· Failed" makes the product look broken and buries the one run that did work.
They are counted and named separately here, never hidden. See `_split()`.
"""
from __future__ import annotations
from datetime import datetime
import os

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QCursor, QFontMetrics, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

import dashboard_data as DATA
import festivals
import i18n
import identity
import paths
import theme
from addons import manifest, registry
from widgets import controls as C
from widgets import icons

# How many run records Home reads per refresh. The figures are honest about
# their own scope ("of your last 102 runs") rather than pretending to be a
# lifetime total, and the bound is what keeps a workspace with five thousand
# runs on a shared drive from costing five thousand file opens.
#
# 120 and not 40, which was the first guess: the shipped workspace opens with
# 87 consecutive records that never reached a tool, so a 40-record window sat
# entirely inside them and reported "0 completed" to somebody with 15
# successful runs. A window has to be wide enough to clear the longest run of
# one outcome or it is not measuring anything. 102 records costs ~32ms here,
# and this is read on refresh() only — never on set_active(), which is the
# call that runs nine times per job.
RUN_WINDOW = 120

# The number of recent runs listed. Five is what fits beside the two narrower
# columns without either of them stretching to fill.
RECENT_SHOWN = 6

# Stages shown in an active run's tool chain before it collapses to a count.
# A nine-stage plan drawn in full is 800px of badges, which is wider than the
# card at 1280 — and the last four are not the ones you are waiting on.
CHAIN_SHOWN = 6

# The add-on shelf, in the rail's order. A module-level copy table so
# The Home shelf, DERIVED from addons/registry.py -- the one place an add-on
# is declared. The comment that used to sit here said this list "must never
# drift from" widgets/sidebar.ADDONS. It had drifted, three ways at once:
#
#   membership  Home carried reel and motion; the rail did not.
#   icons       Gerber was "grid" here and "file" on the rail.
#   copy        BOM said "Coming soon" in grey, months after BOM shipped.
#
# The last one reached customers. BOM is routed, gated, has its own screen
# and opens a real dialog in BOM mode; the rail draws it in the accent
# colour. Anyone working from this screen was told it did not exist yet, and
# `_addon_row` below would not let them click it either.
#
# The tuple layout is unchanged -- key, label, blurb, icon, tone -- so
# devtools/extract_strings.py still finds the labels by the assignment
# target name `ADDONS`. The 5th field is now a TONE TOKEN rather than a
# colour or None; see theme.tone() for why that had to stop being frozen at
# import time.
ADDONS = [
    (a.key, a.label, a.blurb, a.icon, a.tone)
    for a in registry.shelf(manifest.HOME)
]


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return i18n.t("Good morning")
    if hour < 17:
        return i18n.t("Good afternoon")
    return i18n.t("Good evening")


def _never_started(run: dict) -> bool:
    """True for a record that has no query AND no tools.

    Such a run never reached a tool. In the shipped workspace every one of
    them carries "Chrome would not launch" — they are one environment fault
    recorded 86 times, not 86 jobs that ran and went wrong. Counting them as
    failures turns a working install into a 96%-failure dashboard, and listing
    four of them as "Untitled task · Failed" pushes the runs that did work off
    the bottom of the card.

    Nothing is discarded on the strength of this: the count is shown, named for
    what it is, and History still lists every record in full.

    "Untitled task" is the literal dashboard_data.recent_runs() substitutes for
    an empty query — a plain Python string, never passed through i18n — so this
    compares against data and never against a translated label.
    """
    return (not run.get("ok", True)
            and not run.get("tools")
            and (run.get("title") or "").strip() in ("", "Untitled task"))


def _split(runs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """(finished, failed, never-started) out of one window of run records."""
    done, failed, stalled = [], [], []
    for run in runs:
        if run.get("ok", True):
            done.append(run)
        elif _never_started(run):
            stalled.append(run)
        else:
            failed.append(run)
    return done, failed, stalled


class _Elided(QLabel):
    """A one-line label that shrinks to nothing rather than widening the page.

    This is the fix for Home's horizontal overflow. A QLabel reports the full
    width of its text as its minimum size, and a QScrollArea with
    `widgetResizable` honours that minimum even with the horizontal scrollbar
    switched off — so a single long run title silently pushed 191px of the
    dashboard past the right edge of the window, where there was no way to
    scroll to it and no clue it was there.

    Two changes make that impossible: an `Ignored` horizontal size policy, so
    the label asks the layout for nothing at all, and an elide on resize, so
    what it can no longer fit ends in an ellipsis instead of being clipped.
    The full text stays in the tooltip.

    Whitespace is collapsed first — a run title can contain newlines (there is
    a real "hello\\nwassup" in the shipped data), and a two-line row in a list
    of one-line rows reads as a rendering fault.
    """

    def __init__(self, text: str, level: str = "BODY", colour: str = "",
                 weight: int = 0, parent=None):
        super().__init__(parent)
        self._full = " ".join((text or "").split())
        css = theme.type_css(level, colour) + " background: transparent;"
        if weight:
            css += f" font-weight: {weight};"
        self.setStyleSheet(css)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(self._full)
        # Read the text back rather than trusting what was passed in. i18n
        # patches QLabel.setText, so a catalogue string handed here in English
        # is on screen in Hindi a moment later — and elidedText() run against
        # the English original would then quietly put English back the first
        # time the row resized. Whatever actually landed is what gets elided.
        self._full = self.text()
        if self._full:
            self.setToolTip(self._full)

    def text_value(self) -> str:
        """The untruncated string, for an accessible name."""
        return self._full

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = QFontMetrics(self.font())
        # The width is fixed by the layout (the policy is Ignored), so setting
        # a shorter text here cannot feed back into another resize.
        self.setText(metrics.elidedText(self._full, Qt.ElideRight,
                                        max(16, self.width())))


class _Row(QFrame):
    """A flat, hoverable row inside a card that can be activated.

    Home had two of these and neither was reachable from the keyboard — the
    add-on rows worked by reassigning `mousePressEvent` on a bare QFrame, which
    gives a mouse user a click target and everyone else nothing. This one is a
    tab stop, takes Return and Space, and draws a focus ring.
    """

    clicked = Signal()

    def __init__(self, enabled: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._live = enabled
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.TabFocus)
            # The app stylesheet gives #rowFlat no border and no focus state.
            # A transparent border in the resting rule keeps the row from
            # jumping by a pixel when the ring appears.
            self.setStyleSheet(
                f"#rowFlat {{ border: 1px solid transparent; }}"
                f"#rowFlat:focus {{ border-color: {theme.ACCENT};"
                f" background: {theme.WELL}; }}")
        # Ten clear of the 28px floor, not sixteen: three columns of these rows
        # is what sets Home's total height, and four pixels a row was the
        # difference between the page fitting a 900px window and scrolling.
        self.setMinimumHeight(C.MIN_TARGET + 10)

    def mousePressEvent(self, event):
        if self._live:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self._live and event.key() in (Qt.Key_Return, Qt.Key_Enter,
                                          Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class TimelineNode(QWidget):
    """Paints vertical timeline connector track with centered node dot."""

    def __init__(self, is_first: bool = False, is_last: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedWidth(20)
        self._is_first = is_first
        self._is_last = is_last

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cx = w / 2.0
        cy = h / 2.0

        pen = QPen(theme.qcolor(theme.HAIRLINE))
        pen.setWidth(2)
        painter.setPen(pen)
        top_y = cy if self._is_first else 0.0
        bot_y = cy if self._is_last else float(h)
        painter.drawLine(QPointF(cx, top_y), QPointF(cx, bot_y))

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(theme.qcolor(theme.ACCENT)))
        painter.drawEllipse(QPointF(cx, cy), 3.5, 3.5)


class ShowcaseTourCard(QFrame):
    """Featured demo video card on the right side of the hero section:
    'Ideas to outcomes.'
    'Prism combines AI, tools and automation — so you can focus on what matters.'
    '▶ Watch demo video'
    '“Less work. More possibilities.”'
    """

    tour_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tourCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(250)
        C.elevate(self, theme.SHADOW_RAISED)

        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                               theme.SPACE_4, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        demo_badge = QLabel("DEMO")
        demo_badge.setStyleSheet(
            "background: rgba(255, 255, 255, 0.22); color: #ffffff; "
            "border: 1px solid rgba(255, 255, 255, 0.35); "
            "border-radius: 4px; padding: 2px 7px; font-size: 10px; "
            "font-weight: 700; letter-spacing: 0.5px;"
        )
        top_row.addWidget(demo_badge)
        top_row.addStretch(1)
        time_lbl = QLabel("01:03 >")
        time_lbl.setStyleSheet(
            "background: rgba(0, 0, 0, 0.55); color: #ffffff; "
            "border: 1px solid rgba(255, 255, 255, 0.2); "
            "border-radius: 10px; padding: 2px 8px; font-size: 11px; "
            "font-weight: 600;"
        )
        top_row.addWidget(time_lbl)
        col.addLayout(top_row)

        title = QLabel(i18n.t("Ideas to outcomes."))
        title.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 22px; "
            "font-weight: 700; color: #ffffff;"
        )
        col.addWidget(title)

        desc = QLabel(i18n.t("Prism combines AI, tools and automation — so you can focus on what matters."))
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 13px; "
            "color: rgba(255, 255, 255, 0.90); line-height: 1.4;"
        )
        col.addWidget(desc)
        col.addSpacing(theme.SPACE_2)

        tour_btn = QPushButton(i18n.t('Watch demo video'))
        tour_btn.setObjectName("tourPlayBtn")
        tour_btn.setIcon(icons.icon("play", 13, "#09090b"))
        tour_btn.setCursor(Qt.PointingHandCursor)
        tour_btn.clicked.connect(self._play_demo)
        tour_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        col.addWidget(tour_btn)

        col.addStretch(1)

        quote = QLabel(i18n.t("“Less work. More possibilities.”"))
        quote.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 12px; "
            "font-style: italic; color: rgba(255, 255, 255, 0.85);"
        )
        quote.setAlignment(Qt.AlignRight)
        col.addWidget(quote)

        prog = QFrame()
        prog.setFixedHeight(2)
        prog.setStyleSheet("background: rgba(255, 255, 255, 0.25); border-radius: 1px;")
        col.addWidget(prog)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        radius = 18.0

        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        painter.setClipPath(clip)

        # 1. Dark foundation base
        painter.fillRect(r, QBrush(QColor(11, 17, 32)))

        # 2. Draw scenic mountain landscape if available
        bg_path = paths.resource("assets", "demo_card_bg.jpg")
        if not os.path.exists(bg_path):
            bg_path = os.path.join(os.path.dirname(__file__), "..", "assets", "demo_card_bg.jpg")

        if os.path.exists(bg_path):
            pix = QPixmap(bg_path)
            if not pix.isNull():
                target_w = max(1, int(r.width()))
                target_h = max(1, int(r.height()))
                scaled = pix.scaled(target_w, target_h,
                                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                sx = max(0, int((scaled.width() - target_w) * 0.75))
                sy = max(0, (scaled.height() - target_h) // 2)
                painter.drawPixmap(0, 0, scaled, sx, sy, target_w, target_h)

        # 3. Horizontal gradient: dark on left for text readability, clear on right for mountain
        grad = QLinearGradient(0.0, 0.0, float(r.width()), 0.0)
        grad.setColorAt(0.00, QColor(8, 14, 26, 205))
        grad.setColorAt(0.40, QColor(8, 14, 26, 155))
        grad.setColorAt(0.70, QColor(8, 14, 26, 45))
        grad.setColorAt(1.00, QColor(8, 14, 26, 15))
        painter.fillRect(r, QBrush(grad))

        # Bottom subtle gradient for quote
        bot_grad = QLinearGradient(0.0, float(r.height() * 0.65), 0.0, float(r.height()))
        bot_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1.0, QColor(0, 0, 0, 95))
        painter.fillRect(QRectF(0.0, float(r.height() * 0.65), float(r.width()), float(r.height() * 0.35)), QBrush(bot_grad))

        # 4. Subtle border
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.end()

    def mousePressEvent(self, event):
        self._play_demo()
        super().mousePressEvent(event)

    def _play_demo(self):
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "inspo.mp4"),
            os.path.join(os.path.dirname(__file__), "..", "videos", "prism-creator-promo",
                         "renders", "prism-creator-promo_2026-08-16_05-15-18.mp4"),
            os.path.join(os.path.dirname(__file__), "..", "..", "inspo-final", "alphakore-run2-1080.mp4"),
        ]
        video_path = next((p for p in candidates if os.path.exists(p)), "")
        if video_path:
            from dialogs.preview_dialog import open_preview
            open_preview(video_path, self, demo_mode=True)
        else:
            self.tour_clicked.emit()


class ActiveRunCard(C.Card):
    """One in-flight task: its state, the tools it will pass through, how far
    along it is, and what is happening right now.

    Kept as a local Card subclass rather than folded into controls.py: nothing
    there composes a tool chain, and the chain is the point of this card. A
    progress bar alone says "wait"; the row of badges says *what is being
    waited on*, which is the difference between a customer trusting the run and
    killing it at 40%.

    The hand-rolled status dot it used to lead with is gone — the head row
    carries a real `StatusBadge`, so a run in flight says "RUNNING" here in the
    same words, colour and dot it uses on the run screen and in History.
    """

    opened = Signal()

    def __init__(self, title: str, stages: list[tuple[str, str]],
                 fraction: float, note: str, started: str,
                 hue: str = None, parent=None):
        super().__init__(parent=parent)
        hue = hue or theme.WARN
        col = self.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.StatusBadge("running", focusable=False))
        head.addWidget(_Elided(title, "CARD_TITLE"), stretch=1)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_3)

        col.addLayout(self._chain(stages))
        col.addSpacing(theme.SPACE_3)

        col.addWidget(C.ProgressBar(fraction, hue))
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(note, level="META", wrap=True))
        col.addSpacing(theme.SPACE_3)

        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE_2)
        foot.addWidget(C.label(started, role="faint"), stretch=1)
        open_btn = C.button(i18n.t("Open"), "secondary", "arrow-right",
                            small=True, on_click=self.opened.emit)
        foot.addWidget(open_btn)
        col.addLayout(foot)

    def _chain(self, stages: list[tuple[str, str]]) -> QHBoxLayout:
        """Badge over caption, chevrons between — capped so it cannot widen
        the page. Every caption cell is a fixed width and elides inside it, so
        a long stage name costs an ellipsis and never a clipped column."""
        chain = QHBoxLayout()
        chain.setSpacing(theme.SPACE_1 + 1)
        chain.setAlignment(Qt.AlignLeft)
        shown = list(stages)[:CHAIN_SHOWN]
        for i, (tool, caption) in enumerate(shown):
            if i:
                sep = QLabel()
                sep.setPixmap(icons.pixmap("chevron-right", 10,
                                           theme.NEUTRAL[300], stroke=3))
                sep.setAlignment(Qt.AlignTop)
                sep.setContentsMargins(0, 11, 0, 0)
                chain.addWidget(sep)
            cell = QVBoxLayout()
            cell.setSpacing(theme.SPACE_1)
            cell.setAlignment(Qt.AlignHCenter)
            badge = C.ToolBadge(tool, 34, radius=theme.R_CONTROL)
            # On this card the badge is a soft tinted pad rather than a solid
            # fill — three saturated squares in a row out-shouted the task
            # name, which is the thing you are actually scanning for.
            badge.setStyleSheet(
                f"background: {theme.tint(theme.badge_color(tool))};"
                f" color: {theme.badge_color(tool)};"
                f" border: 1px solid {theme.tint(theme.badge_color(tool), '40')};"
                f" border-radius: {theme.R_CONTROL}px;"
                f" font-family: '{theme.FONT_HEADING}';"
                f" font-weight: 700; font-size: 13px;")
            badge.setToolTip(f"{tool} — {caption}")
            cell.addWidget(badge, alignment=Qt.AlignHCenter)
            cap = _Elided(caption, "LABEL", theme.NEUTRAL[500])
            cap.setFixedWidth(74)
            cap.setAlignment(Qt.AlignHCenter)
            cell.addWidget(cap, alignment=Qt.AlignHCenter)
            chain.addLayout(cell)
        if len(stages) > CHAIN_SHOWN:
            more = C.Pill(i18n.t("+{n} more").format(n=len(stages) - CHAIN_SHOWN),
                          "quiet")
            more.setToolTip(" · ".join(t for t, _c in stages[CHAIN_SHOWN:]))
            chain.addWidget(more, alignment=Qt.AlignVCenter)
        chain.addStretch(1)
        return chain


class HomePanel(QWidget):
    """The dashboard. Rebuilt wholesale by refresh() rather than mutated — it
    is a read-only report over two stores, and a rebuild is far easier to keep
    correct than a dozen setText() paths that each have to remember the empty
    case.

    With ONE exception, and it is the reason the run section has its own host
    widget. refresh() costs a read of the register CSV plus a walk of the runs
    folder, and on a company install both live on a shared drive. set_active()
    is called from the window on every `stage_started`, so a nine-stage run was
    paying that whole cost nine times — synchronously, on the UI thread. That
    is the "it freezes for a few seconds every time it moves to the next step"
    report, and it is worst over VPN or a Drive-for-Desktop mount where a
    blocked stat is not interruptible. A run in flight changes one card, so
    set_active() repaints one card and touches neither store.

    The screen is a fixed PageHeader over a scrolling body, which is the
    standard page scaffold: the greeting and the way out to History stay put
    while the report scrolls under them.
    """

    describe_task = Signal()
    task_submitted = Signal(str, list)  # (prompt_text, [file_or_folder_paths])
    open_addon = Signal(str)        # any command the window's router accepts
    open_history = Signal()
    open_run = Signal()
    open_run_record = Signal(str)   # path of a saved run record — NEEDS WIRING
    lumi_open_requested = Signal()
    lumi_close_requested = Signal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._active: list[dict] = []
        self._rows: list[dict] = []
        self._home_attachments: list[str] = []
        # (festival name, "post"/"reel") already answered (Yes or No) this
        # session -- refresh() rebuilds the whole screen from scratch, so
        # without remembering this here a dismissed tip would just come
        # straight back on the next refresh (every stage_started repaint
        # included, by way of set_active -> nothing, but also History/Home
        # navigation, which does call refresh()).
        self._festival_dismissed: set[tuple[str, str]] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Scrollable Body ─────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.verticalScrollBar().valueChanged.connect(lambda _: self._scroll.viewport().update())
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._scroll.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        root.addWidget(self._scroll, stretch=1)

        # Lumi is not built here. Her launcher is the window-wide edge button
        # (widgets/lumi_card.LumiEdgeButton, owned by LumiOverlay), the same
        # on Home as on every other screen; Home's own copy was a hidden 66 px
        # button and a popover that nothing opened.

        # Active run host slot
        self._active_host = QWidget()
        _slot = QVBoxLayout(self._active_host)
        _slot.setContentsMargins(0, 0, 0, 0)

        self.refresh()

    # ── live run state, pushed in by the window ──────────────────────────
    def set_active(self, runs: list[dict]):
        self._active = list(runs or [])
        self._fill_active()

    def _fill_active(self):
        slot = self._active_host.layout()
        while slot.count():
            item = slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())
        if self._active:
            slot.addLayout(self._active_runs())
        self._active_host.setVisible(bool(self._active))

    def _active_runs(self) -> QVBoxLayout:
        wrap = QVBoxLayout()
        wrap.setSpacing(theme.SPACE_3)
        wrap.addWidget(C.SectionHeader(
            i18n.t("Active runs"), "",
            [C.button(i18n.t("View all"), "link",
                      on_click=self.open_history.emit)]))

        row = QHBoxLayout()
        row.setSpacing(theme.CARD_GAP)
        for run in self._active:
            card = ActiveRunCard(
                run.get("title", ""), run.get("stages", []),
                run.get("fraction", 0.0), run.get("note", ""),
                run.get("started", ""), run.get("hue"))
            card.opened.connect(self.open_run.emit)
            row.addWidget(card)
        if len(self._active) == 1:
            row.addStretch(1)
        wrap.addLayout(row)
        return wrap

    # ── refresh ──────────────────────────────────────────────────────────
    def _refresh_identity(self):
        if hasattr(self, "_avatar") and self._avatar:
            whole = identity.describe()
            initial = (whole or "?").strip()[:1].upper()
            self._avatar.setText(initial)
            self._avatar.setToolTip(whole)

    def refresh(self):
        self._refresh_identity()
        while self._col.count():
            item = self._col.takeAt(0)
            widget = item.widget()
            if widget is self._active_host:
                widget.hide()
                widget.setParent(None)
            elif widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

        self._rows = DATA.register_rows(self.cfg)
        runs = DATA.recent_runs(self.cfg, RUN_WINDOW)
        done, failed, stalled = _split(runs)

        # 1. Hero row (Left: Greeting + Composer + Try chips; Right: Lumi)
        self._col.addLayout(self._hero_section())

        # 2. Active runs (if any)
        self._col.addWidget(self._active_host)
        self._fill_active()

        # 3. Bottom section (Left: Recent activity; Right: Add-ons)
        self._col.addLayout(self._bottom_section(runs, stalled))
        self._col.addStretch(1)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── Section 1: Hero Section (Two Columns) ─────────────────────────────
    def _hero_section(self) -> QHBoxLayout:
        hero = QHBoxLayout()
        hero.setSpacing(theme.CARD_GAP)

        # Left Column (~62%)
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(theme.SPACE_3)

        # Greeting row with script motto on the right
        greet_row = QHBoxLayout()
        greet_row.setContentsMargins(0, 0, 0, 0)
        greet_row.setSpacing(theme.SPACE_2)

        greet_stack = QVBoxLayout()
        greet_stack.setContentsMargins(0, 0, 0, 0)
        greet_stack.setSpacing(2)

        salutation = QLabel(f"{_greeting()},")
        salutation.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 22px; "
            f"font-weight: 700; color: #09090b;"
        )
        greet_stack.addWidget(salutation)

        who = (identity.display_name(self.cfg) or "").split(" ")[0]
        if not who:
            who = "there"
        name_lbl = QLabel(f"{who},")
        name_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 44px; "
            f"font-weight: 800; color: #000000; line-height: 1.1;"
        )
        C.track(name_lbl, -0.02)
        greet_stack.addWidget(name_lbl)

        sub_lbl = QLabel(i18n.t("Let's turn ideas into outcomes."))
        sub_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 18px; "
            f"font-weight: 600; color: #09090b;"
        )
        greet_stack.addWidget(sub_lbl)
        greet_row.addLayout(greet_stack, stretch=1)

        motto = QLabel(i18n.t("Less work. More possibilities."))
        motto.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 13.5px; "
            f"font-weight: 600; color: #09090b; "
            f"background: rgba(255, 255, 255, 0.85); "
            f"border: 1px solid rgba(0, 0, 0, 0.12); border-radius: 999px; "
            f"padding: 6px 14px;"
        )
        motto.setAlignment(Qt.AlignCenter)
        greet_row.addWidget(motto, alignment=Qt.AlignRight | Qt.AlignVCenter)
        left_col.addLayout(greet_row)

        tips = self._festival_tips()
        if tips:
            left_col.addLayout(tips)
        left_col.addWidget(self._prompt_card())
        left_col.addLayout(self._try_chips_row())

        hero.addLayout(left_col, stretch=62)

        # Right Column (~38%)
        tour_card = ShowcaseTourCard()
        tour_card.tour_clicked.connect(lambda: self.open_addon.emit("guide"))
        hero.addWidget(tour_card, stretch=38)

        return hero

    # ── festival tip (27 Oct 2026) ─────────────────────────────────────────
    def _festival_tips(self, today=None) -> QVBoxLayout | None:
        """Up to two yellow tip rows -- "make a post" and "make a reel" --
        for the single NEAREST upcoming festival (festivals.upcoming()
        can return several at once in a busy week; showing all of them
        would turn this into a second feed above the composer, so only
        the closest one gets a tip, same as the owner's own "a small tip"
        framing implies). Each kind is independently dismissable and
        independently answerable -- saying yes to the post must not also
        answer the reel question, since they are two different asks.

        `today` is a plain pass-through to festivals.upcoming() -- tests
        use it directly rather than mocking datetime.date.today(), which
        CPython refuses to patch at all ("cannot set 'today' attribute of
        immutable type 'datetime.date'")."""
        upcoming = festivals.upcoming(3, today=today)
        if not upcoming:
            return None
        f = upcoming[0]
        rows = [self._festival_tip_row(f, kind) for kind in ("post", "reel")
                if (f["name"], kind) not in self._festival_dismissed]
        if not rows:
            return None
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        for row in rows:
            col.addWidget(row)
        return col

    def _festival_tip_row(self, f: dict, kind: str) -> QFrame:
        bar = QFrame()
        bar.setObjectName("festivalTip")
        bar.setStyleSheet(
            f"QFrame#festivalTip {{ background: {theme.WARN_BG}; "
            f"border-radius: {theme.R_CONTROL}px; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                               theme.SPACE_3, theme.SPACE_2)
        row.setSpacing(theme.SPACE_2)

        prompt = festivals.post_prompt(f) if kind == "post" else festivals.reel_prompt(f)
        question = (i18n.t("{name} is coming up {when} — want to make a "
                           "{kind} about it?").format(
            name=f["name"], when=festivals.when_phrase(f),
            kind=i18n.t("post") if kind == "post" else i18n.t("reel")))
        label = QLabel(question)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.WARN_INK}; font-weight: 600;")
        row.addWidget(label, stretch=1)

        yes_btn = C.button(i18n.t("Yes"), "secondary", small=True,
                           on_click=lambda *_, f=f, k=kind, p=prompt:
                               self._on_festival_answer(f, k, True, p))
        row.addWidget(yes_btn)
        no_btn = C.button(i18n.t("No"), "tertiary", small=True,
                          on_click=lambda *_, f=f, k=kind:
                              self._on_festival_answer(f, k, False, ""))
        row.addWidget(no_btn)
        return bar

    def _on_festival_answer(self, f: dict, kind: str, yes: bool, prompt: str):
        self._festival_dismissed.add((f["name"], kind))
        # refresh() rebuilds the whole screen wholesale -- including a
        # brand new self._prompt_input -- so the prefill has to happen
        # AFTER it, on the box that actually ends up on screen, not the
        # one about to be torn down.
        self.refresh()
        if yes:
            self._prompt_input.setText(prompt)
            self._prompt_input.setFocus()
            self._prompt_input.selectAll()

    def _prompt_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("heroPromptCard")
        card.setMinimumHeight(220)
        col = QVBoxLayout(card)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                               theme.SPACE_4, theme.SPACE_3)
        col.setSpacing(theme.SPACE_3)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(theme.SPACE_2)

        cursor_bar = QFrame()
        cursor_bar.setFixedWidth(2)
        cursor_bar.setFixedHeight(20)
        cursor_bar.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 1px;")
        input_row.addWidget(cursor_bar)

        self._prompt_input = QLineEdit()
        self._prompt_input.setObjectName("heroPromptInput")
        self._prompt_input.setPlaceholderText(i18n.t("What can I take care of today?"))
        self._prompt_input.returnPressed.connect(self._submit_home_task)
        input_row.addWidget(self._prompt_input, stretch=1)
        col.addLayout(input_row)

        # Attachment chips bar for files/folders attached right from the dashboard
        self._home_attachments_bar = QWidget()
        self._home_attachments_flow = C.FlowLayout(self._home_attachments_bar, margin=0, h_space=6, v_space=6)
        self._home_attachments_bar.setVisible(False)
        col.addWidget(self._home_attachments_bar)

        # Spacer to give the card visual height like a multi-line composer
        col.addStretch(1)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(theme.SPACE_2)

        attach_btn = QPushButton(i18n.t('Attach'))
        attach_btn.setObjectName("promptChipBtn")
        attach_btn.setIcon(icons.icon("paperclip", 13, theme.TEXT))
        attach_btn.setCursor(Qt.PointingHandCursor)
        attach_btn.clicked.connect(self._on_attach_clicked)
        bar.addWidget(attach_btn)

        cmds_btn = QPushButton(i18n.t('Commands'))
        cmds_btn.setObjectName("promptChipBtn")
        cmds_btn.setIcon(icons.icon("command", 13, theme.TEXT))
        cmds_btn.setCursor(Qt.PointingHandCursor)
        cmds_btn.clicked.connect(self.open_history.emit)
        bar.addWidget(cmds_btn)

        tools_btn = QPushButton(i18n.t('Tools'))
        tools_btn.setObjectName("promptChipBtn")
        tools_btn.setIcon(icons.icon("grid", 13, theme.TEXT))
        tools_btn.setCursor(Qt.PointingHandCursor)
        tools_btn.clicked.connect(lambda: self.open_addon.emit("catalog"))
        bar.addWidget(tools_btn)

        bar.addStretch(1)

        send_btn = QPushButton()
        send_btn.setObjectName("promptSendBtn")
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setIcon(icons.icon("arrow-right", 16, "#ffffff"))
        send_btn.setToolTip(i18n.t("Start task"))
        send_btn.clicked.connect(self._submit_home_task)
        bar.addWidget(send_btn)

        col.addLayout(bar)
        return card

    def _on_attach_clicked(self):
        menu = QMenu(self)
        add_file = menu.addAction(i18n.t("Attach file(s)…"))
        add_folder = menu.addAction(i18n.t("Attach folder…"))
        chosen = menu.exec(QCursor.pos())
        if chosen == add_file:
            paths, _ = QFileDialog.getOpenFileNames(self, i18n.t("Attach file(s)"))
            if paths:
                for p in paths:
                    if p not in self._home_attachments:
                        self._home_attachments.append(p)
                self._render_home_attachments()
        elif chosen == add_folder:
            path = QFileDialog.getExistingDirectory(self, i18n.t("Attach folder"))
            if path:
                if path not in self._home_attachments:
                    self._home_attachments.append(path)
                self._render_home_attachments()

    def _render_home_attachments(self):
        while self._home_attachments_flow.count():
            item = self._home_attachments_flow.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for path in self._home_attachments:
            is_dir = os.path.isdir(path)
            chip = QFrame()
            chip.setObjectName("attachmentChip")
            chip.setStyleSheet("""
                QFrame#attachmentChip {
                    background-color: #ffffff;
                    border: 1px solid rgba(0, 0, 0, 0.14);
                    border-radius: 8px;
                }
                QFrame#attachmentChip:hover {
                    border-color: rgba(0, 0, 0, 0.35);
                    background-color: #fafafa;
                }
            """)
            crow = QHBoxLayout(chip)
            crow.setContentsMargins(8, 4, 8, 4)
            crow.setSpacing(6)
            icon = QLabel()
            icon.setPixmap(icons.pixmap("folder" if is_dir else "file", 14, theme.ACCENT))
            crow.addWidget(icon)
            lbl = QLabel(os.path.basename(path.rstrip("/\\")) or path)
            lbl.setStyleSheet("font-weight: 500; font-size: 12px; color: #18181b;")
            crow.addWidget(lbl)
            x_btn = QPushButton("×")
            x_btn.setFixedSize(18, 18)
            x_btn.setCursor(Qt.PointingHandCursor)
            x_btn.setToolTip(i18n.t("Remove"))
            x_btn.setStyleSheet("""
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
            x_btn.clicked.connect(lambda *_, p=path: self._remove_home_attachment(p))
            crow.addWidget(x_btn)
            self._home_attachments_flow.addWidget(chip)
        self._home_attachments_bar.setVisible(bool(self._home_attachments))

    def _remove_home_attachment(self, path: str):
        if path in self._home_attachments:
            self._home_attachments.remove(path)
            self._render_home_attachments()

    def _submit_home_task(self):
        text = self._prompt_input.text().strip()
        paths = list(self._home_attachments)
        self._prompt_input.clear()
        self._home_attachments.clear()
        self._render_home_attachments()
        self.task_submitted.emit(text, paths)
        self.describe_task.emit()

    def get_prompt_text(self) -> str:
        return self._prompt_input.text().strip()

    def clear_prompt(self):
        self._prompt_input.clear()

    def get_attachments(self) -> list[str]:
        return list(self._home_attachments)

    def clear_attachments(self):
        self._home_attachments.clear()
        self._render_home_attachments()

    def _try_chips_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)

        prefix = QLabel(i18n.t("Try:"))
        prefix.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 12px; "
            f"font-weight: 500; color: {theme.NEUTRAL[500]};"
        )
        row.addWidget(prefix)

        chips_data = [
            ("inquiry", i18n.t("Summarize a PDF"), "file"),
            ("reel", i18n.t("Create a reel"), "film"),
            ("boq", i18n.t("Analyze this BOQ"), "chart"),
            ("artifacts", i18n.t("Clean up artifacts"), "sparkles"),
        ]

        for key, label, icon_name in chips_data:
            chip = QPushButton(label)
            chip.setObjectName("tryChip")
            chip.setIcon(icons.icon(icon_name, 12, theme.NEUTRAL[600]))
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self.open_addon.emit(k))
            row.addWidget(chip)

        row.addStretch(1)
        return row

    # ── Section 2: Bottom Section (Two Columns) ───────────────────────────
    def _bottom_section(self, runs, stalled) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(theme.CARD_GAP)
        row.addWidget(self._recent_activity_card(runs, stalled), stretch=60)
        row.addWidget(self._addons_card(), stretch=40)
        return row

    def _recent_activity_card(self, runs, stalled) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = C.heading(i18n.t("Recent activity"), 4)
        head.addWidget(title, stretch=1)

        see_all = C.button(f"{i18n.t('See all')} →", "link",
                           on_click=self.open_history.emit)
        head.addWidget(see_all)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_3)

        if not runs:
            empty = C.EmptyState(
                "inbox", i18n.t("No runs yet"),
                i18n.t("Every task you start is saved here, with the tools it "
                       "used and what it produced."),
                i18n.t("Describe a task"))
            empty.clicked.connect(self.describe_task.emit)
            col.addWidget(empty, stretch=1)
            return card

        listed = [r for r in runs if not _never_started(r)][:RECENT_SHOWN]
        if not listed:
            empty = C.EmptyState(
                "alert", i18n.t("Nothing has finished yet"),
                i18n.t("Every recent run stopped before a tool was reached. "
                       "Open History to see what each one recorded."),
                i18n.t("Open History"))
            empty.clicked.connect(self.open_history.emit)
            col.addWidget(empty, stretch=1)
            return card

        for i, run in enumerate(listed):
            is_first = (i == 0)
            is_last = (i == len(listed) - 1 and not stalled)
            col.addWidget(self._timeline_row(run, is_first, is_last))

        if stalled:
            col.addSpacing(theme.SPACE_1)
            col.addWidget(self._stalled_row(stalled))

        col.addStretch(1)
        return card

    def _timeline_row(self, run: dict, is_first: bool, is_last: bool) -> QWidget:
        wrap = _Row()
        wrap.clicked.connect(
            lambda p=run.get("path", ""): p and self.open_run_record.emit(p))

        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)

        track = TimelineNode(is_first=is_first, is_last=is_last)
        row.addWidget(track)

        tools = run.get("tools") or []
        primary = tools[0] if tools else "Task"
        badge = C.ToolBadge(primary, 34, theme.R_CONTROL) if tools else \
            C.IconPad("file", theme.NEUTRAL[400], 34, theme.R_CONTROL, 16)
        row.addWidget(badge)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        title = _Elided(run.get("title", ""), "BODY", weight=500)
        text_col.addWidget(title)

        source = tools[0] if tools else "Prism"
        when = run.get("when", "")
        detail_text = f"{source} · {when}" if when else source
        subtitle = _Elided(detail_text, "META")
        text_col.addWidget(subtitle)
        row.addLayout(text_col, stretch=1)

        is_ok = run.get("ok", True)
        status_badge = C.StatusBadge("completed" if is_ok else "failed", focusable=False)
        row.addWidget(status_badge)

        menu_btn = QPushButton()
        menu_btn.setObjectName("recentMenuBtn")
        menu_btn.setIcon(icons.icon("more-horizontal", 16, theme.NEUTRAL[400]))
        menu_btn.setFixedSize(28, 28)
        menu_btn.clicked.connect(
            lambda: self.open_run_record.emit(run.get("path", "")))
        row.addWidget(menu_btn)

        wrap.setAccessibleName(title.text_value())
        return wrap

    def _stalled_row(self, stalled: list[dict]) -> QWidget:
        wrap = _Row()
        wrap.clicked.connect(self.open_history.emit)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("alert", theme.WARN, 32, theme.R_CONTROL, 16))

        stack = QVBoxLayout()
        stack.setSpacing(1)
        stack.addWidget(_Elided(i18n.t("Stopped before any tool ran"),
                                "BODY", weight=500))
        reason = ""
        for run in stalled:
            reason = (run.get("error") or "").strip()
            if reason:
                break
        stack.addWidget(_Elided(
            reason or i18n.t("These runs never reached a tool. Open History to see them."),
            "META"))
        row.addLayout(stack, stretch=1)
        row.addWidget(C.Pill(str(len(stalled)), "warn"))
        return wrap

    def _addons_card(self) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = C.heading(i18n.t("Add-ons"), 3)
        head.addWidget(title, stretch=1)

        manage_btn = C.button(i18n.t("Manage"), "secondary", small=False,
                              on_click=lambda: self.open_addon.emit("catalog"))
        head.addWidget(manage_btn)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_3)

        grid = QGridLayout()
        grid.setSpacing(theme.SPACE_2)

        addon_specs = [
            ("Email Inquiry", "inquiry", "inquiry"),
            ("BOQ", "boq", "boq"),
            ("Gerber", "gerber", "gerber"),
            ("STEP", "step", "step"),
            ("BOM & Stock", "bom", "bom"),
            ("Email", "email", "email"),
            ("Leads", "leads", "leads"),
            ("Reel", "reel", "reel"),
            ("Motion", "motion", "motion"),
        ]

        for i, (name, logo_key, nav_key) in enumerate(addon_specs):
            tile = self._make_addon_tile(name, logo_key, nav_key)
            row_idx = i // 3
            col_idx = i % 3
            grid.addWidget(tile, row_idx, col_idx)

        col.addLayout(grid)
        col.addSpacing(theme.SPACE_3)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        browse_btn = QPushButton(f"+ {i18n.t('Browse Add-ons')}")
        browse_btn.setObjectName("chipBtn")
        browse_btn.setCursor(Qt.PointingHandCursor)
        browse_btn.setStyleSheet("font-size: 14px; font-weight: 600; padding: 6px 14px;")
        browse_btn.clicked.connect(lambda: self.open_addon.emit("catalog"))
        foot.addWidget(browse_btn)

        foot.addStretch(1)

        guide_link = C.button(f"{i18n.t('Explore all add-ons')} →", "link",
                              on_click=lambda: self.open_addon.emit("catalog"))
        guide_link.setStyleSheet("font-size: 14px; font-weight: 600;")
        foot.addWidget(guide_link)
        col.addLayout(foot)

        return card

    @staticmethod
    def _make_tool_tile(host, name: str, glyph: str, builtin: bool, route: str) -> QWidget:
        return _ToolTile(host, name, glyph, builtin, route)

    def _make_addon_tile(self, name: str, logo_key: str, nav_key: str) -> QWidget:
        return self._make_tool_tile(self, name, logo_key, True, nav_key)


class _ToolTile(QFrame):
    """Tool launcher tile with full keyboard navigation and accessible state."""

    def __init__(self, host, name: str, glyph: str, builtin: bool, route: str, parent=None):
        super().__init__(parent)
        self.host = host
        self.route = route
        self.setObjectName("toolTile")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)
        status_text = "Built-in" if builtin else "Not connected"
        self.setAccessibleName(f"{name} ({status_text})")

        tile_col = QVBoxLayout(self)
        tile_col.setContentsMargins(6, 10, 6, 8)
        tile_col.setSpacing(theme.SPACE_1)
        tile_col.setAlignment(Qt.AlignCenter)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.tool_logo(glyph, 28))
        icon_lbl.setAlignment(Qt.AlignCenter)
        tile_col.addWidget(icon_lbl)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 13.5px; "
            f"font-weight: 600; color: {theme.TEXT};"
        )
        name_lbl.setAlignment(Qt.AlignCenter)
        tile_col.addWidget(name_lbl)

        dot = QLabel("●")
        dot.setStyleSheet(f"font-size: 10px; color: {theme.OK if builtin else theme.NEUTRAL[400]};")
        dot.setAlignment(Qt.AlignCenter)
        tile_col.addWidget(dot)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.host.open_addon.emit(self.route)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.host.open_addon.emit(self.route)
            event.accept()
            return
        super().keyPressEvent(event)

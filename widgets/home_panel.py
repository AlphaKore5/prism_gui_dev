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
    QBrush, QColor, QCursor, QFont, QFontMetrics, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
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
RECENT_SHOWN = 3

# Width of the one centred column Home is built in.
STAGE_W = 700

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


# The add-on word a task starts with (how every task a user types is routed) and
# the preview's line icon for it. Anything else is a plain document.
_RUN_ICON = {
    "boq": "sheet", "step": "cube", "gerber": "chip", "bom": "box",
    "/reel": "film-box", "reel": "film-box", "/motion": "video", "motion": "video",
    "email": "mail", "leads": "user", "inquiry": "inbox",
}


def _run_icon(run: dict) -> str:
    """The line icon for a Home run row, by the add-on the task named first
    (display only: the row opens the same record as before)."""
    words = (run.get("title") or run.get("query") or "").strip().lower().split()
    first = words[0].strip("—-:,.") if words else ""
    if first in _RUN_ICON:
        return _RUN_ICON[first]
    if any("studio" in (t or "").lower() for t in (run.get("tools") or [])):
        return "film-box"
    return "file"


def _hl_pen(w: float, h: float, top_alpha: int) -> QPen:
    """A 1px pen that is `top_alpha` white at the top of a w x h shape and gone
    by 45% down: the preview's `inset 0 1px 0 rgba(255,255,255,a)`."""
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0.0, QColor(255, 255, 255, top_alpha))
    g.setColorAt(0.45, QColor(255, 255, 255, 0))
    g.setColorAt(1.0, QColor(255, 255, 255, 0))
    return QPen(QBrush(g), 1)


def _glow_gradient(cx: float, cy: float, r: float, blur: float, rgb, alpha: float) -> QRadialGradient:
    """`0 0 <blur> rgba(rgb, alpha)` around a circle of radius r: a radial gradient
    whose alpha follows the gaussian edge profile (sigma = blur / 2)."""
    import math
    sigma = blur / 2.0
    reach = 2.5 * sigma
    g = QRadialGradient(QPointF(cx, cy), r + reach)
    for i in range(0, 13):
        d = reach * i / 12.0
        a = alpha * 0.5 * math.erfc(d / (sigma * math.sqrt(2)))
        g.setColorAt((r + d) / (r + reach), QColor(rgb[0], rgb[1], rgb[2], int(round(a * 255))))
    g.setColorAt(0.0, QColor(rgb[0], rgb[1], rgb[2], int(round(alpha * 0.5 * 255))))
    return g


def _pixel_glyph(p: QPainter, cx: float, cy: float, size: float, cells, colour="#FFFFFF"):
    """The preview's 18-unit pixel glyphs (parrow / pplay): 2x2 squares."""
    u = size / 18.0
    ox, oy = cx - 9 * u, cy - 9 * u
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colour))
    for x, y in cells:
        p.drawRect(QRectF(ox + x * u, oy + y * u, 2 * u, 2 * u))


PIXEL_ARROW = ((2, 8), (5, 8), (8, 8), (11, 8), (11, 5), (11, 11), (14, 8))
PIXEL_PLAY = ((5, 3), (5, 6), (5, 9), (5, 12), (8, 5), (8, 8), (8, 11), (11, 7))


class _SendButton(QPushButton):
    """The preview's `.send`: a 53x43 dark gradient pill carrying a 32px red dot
    with the pixel ARROW, a red glow and a soft shadow under the pill. Painted;
    clicked, tooltip, cursor and the objectName are the plain button's."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("promptSendBtn")
        # the app sheet's QPushButton min-height/padding would override a fixed size
        self.setStyleSheet("min-height: 43px; max-height: 43px; padding: 0px; border: none;")
        self.setFixedSize(53, 43)
        self.setCursor(Qt.PointingHandCursor)
        C.attach_shadow(self, C.SH_SEND)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        body = QRectF(0, 0, w, h)
        if self.isDown():
            top = bot = "#0c0c0b"
        elif self.underMouse():
            top, bot = "#4a4a48", "#1c1c1b"
        else:
            top, bot = "#3a3a38", "#0c0c0b"
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor(top))
        g.setColorAt(1, QColor(bot))
        p.setPen(QPen(QColor(0, 0, 0, 89), 1))          # 0 0 0 1px rgba(0,0,0,.35)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(body.adjusted(.5, .5, -.5, -.5), h / 2, h / 2)
        p.setPen(_hl_pen(w, h, 41))                      # inset 0 1px 0 .16
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body.adjusted(1.5, 1.5, -1.5, -1.5), h / 2 - 1, h / 2 - 1)
        d = 32.0
        cx, cy = w / 2, h / 2
        clip = QPainterPath()
        clip.addRoundedRect(body, h / 2, h / 2)
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_glow_gradient(cx, cy, d / 2, 14.7, (222, 48, 36), .4)))
        p.drawEllipse(QPointF(cx, cy), d / 2 + 18.4, d / 2 + 18.4)
        p.setClipping(False)
        dot = QRectF(cx - d / 2, cy - d / 2, d, d)
        rg = QLinearGradient(0, dot.top(), 0, dot.bottom())
        rg.setColorAt(0, QColor("#F4523A"))
        rg.setColorAt(1, QColor("#C81A1C"))
        p.setBrush(QBrush(rg))
        p.drawEllipse(dot)
        p.setPen(QPen(QBrush(self._dot_highlight(dot)), 1))   # inset 0 1px 0 .5
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(dot.adjusted(1.5, 1.5, -1.5, -1.5))
        _pixel_glyph(p, cx, cy, 17.0, PIXEL_ARROW)

    @staticmethod
    def _dot_highlight(dot: QRectF) -> QLinearGradient:
        g = QLinearGradient(0, dot.top(), 0, dot.bottom())
        g.setColorAt(0.0, QColor(255, 255, 255, 128))
        g.setColorAt(0.45, QColor(255, 255, 255, 0))
        g.setColorAt(1.0, QColor(255, 255, 255, 0))
        return g


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


class _RunCard(C.Card):
    """One recent run as a small card: line-icon tile and status pill on top,
    the title on one line, then mono "ADDON · time". Opens the saved record."""

    clicked = Signal()

    def __init__(self, run: dict, parent=None):
        super().__init__(radius=14, parent=parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        col = self.body((12, 12, 12, 12 + C.CARD_LIP), spacing=theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        tile = C.IconPad(_run_icon(run), theme.INK, 30, 9, 14)
        tile.setStyleSheet("background: #EFEEEA; border-radius: 9px;")
        top.addWidget(tile)
        top.addStretch(1)
        is_ok = run.get("ok", True)
        state = "completed" if is_ok else "failed"
        pill = C.Pill(theme.status(state)[0], "st_ok" if is_ok else "st_err")
        pill.setAccessibleName(theme.status(state)[0].title())
        top.addWidget(pill)
        col.addLayout(top)
        title = _Elided(run.get("title", ""), "BODY", weight=400)
        title.setStyleSheet(title.styleSheet() + " font-size: 13px; color: #111110;")
        col.addWidget(title)
        tools = run.get("tools") or []
        source = tools[0] if tools else "Prism"
        when = run.get("when", "")
        meta = _Elided(f"{source} · {when}" if when else source, "META")
        meta.setStyleSheet(meta.styleSheet()
                           + f" font-family: '{theme.FONT_MONO}'; font-size: 10px;")
        C.track(meta, 0.03)
        col.addWidget(meta)
        self.setAccessibleName(title.text_value())

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


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
        # The run slot lives inside the page column; take it out before the
        # old column is deleted, or it goes with it.
        self._active_host.hide()
        self._active_host.setParent(None)
        while self._col.count():
            item = self._col.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

        self._rows = DATA.register_rows(self.cfg)
        runs = DATA.recent_runs(self.cfg, RUN_WINDOW)
        done, failed, stalled = _split(runs)

        # One centred column, vertically centred when the window is taller
        # than it: headline, [festival notice], composer, quiet meta row,
        # [active runs], [Recent activity].
        stage = QWidget()
        stage.setMaximumWidth(STAGE_W)
        col = QVBoxLayout(stage)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        self._hero_section(col)
        col.addWidget(self._active_host)
        self._fill_active()
        self._recent_section(col, runs, stalled)

        wrap = QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        wrap.addWidget(stage, 1000)
        wrap.addStretch(1)
        self._col.addStretch(1)
        self._col.addLayout(wrap)
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

    # ── Headline, notice, composer, meta row ──────────────────────────────
    def _hero_section(self, col: QVBoxLayout):
        head = QVBoxLayout()
        head.setContentsMargins(0, 0, 0, theme.SPACE_2)
        head.setSpacing(2)

        salutation = QLabel(f"{_greeting()},")
        salutation.setAlignment(Qt.AlignCenter)
        salutation.setStyleSheet(
            f"font-family: 'Geist Light', '{theme.FONT_BODY}'; font-size: 21px; "
            f"font-weight: 300; color: {theme.TEXT};"
        )
        head.addWidget(salutation)

        who = (identity.display_name(self.cfg) or "").split(" ")[0]
        if not who:
            who = "there"
        name_lbl = QLabel(f"{who.upper()},")
        name_lbl.setAlignment(Qt.AlignCenter)
        name_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_DISPLAY}'; font-size: 52px; "
            f"font-weight: 700; color: {theme.INK};"
        )
        C.track(name_lbl, 0.02)
        head.addWidget(name_lbl)

        sub_lbl = QLabel(i18n.t("Let's turn ideas into outcomes."))
        sub_lbl.setAlignment(Qt.AlignCenter)
        _lead, _tail = "Let's turn ideas ", "into outcomes."
        if sub_lbl.text() == _lead + _tail:          # English: the tail is the faint clause
            sub_lbl.setTextFormat(Qt.RichText)
            sub_lbl.setText(f'{_lead}<span style="color: {theme.FAINT};">{_tail}</span>')
        sub_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 18px; "
            f"font-weight: 400; color: {theme.INK};"
        )
        head.addWidget(sub_lbl)
        col.addLayout(head)

        tips = self._festival_tips()
        if tips:
            col.addWidget(tips)
        col.addWidget(self._prompt_card())
        col.addLayout(self._try_chips_row())
        col.addLayout(self._meta_links_row())

    def _meta_links_row(self) -> QHBoxLayout:
        """Two quiet links under the chips: the demo video and the add-on
        catalogue (Home no longer carries either as a card)."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_3)
        demo = C.button(f"▶ {i18n.t('Watch demo video')} · 01:03", "link",
                        on_click=self._play_demo)
        row.addWidget(demo)
        row.addStretch(1)
        manage = C.button(f"{i18n.t('Manage add-ons')} →", "link",
                          on_click=lambda: self.open_addon.emit("catalog"))
        row.addWidget(manage)
        return row

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
            self.open_addon.emit("guide")

    # ── festival tip (27 Oct 2026) ─────────────────────────────────────────
    def _festival_tips(self, today=None) -> QFrame | None:
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
        banner = QFrame()
        banner.setObjectName("festivalBanner")
        banner.setStyleSheet(
            f"QFrame#festivalBanner {{ background: #FFFFFF; "
            f"border: 1px solid {theme.HAIRLINE}; border-radius: 14px; }}")
        col = QVBoxLayout(banner)
        col.setContentsMargins(0, 4, 0, 4)
        col.setSpacing(0)
        for row in rows:
            col.addWidget(row)
        return banner

    def _festival_tip_row(self, f: dict, kind: str) -> QFrame:
        bar = QFrame()
        bar.setObjectName("festivalTip")
        bar.setStyleSheet("QFrame#festivalTip { background: transparent; border: none; }")
        row = QHBoxLayout(bar)
        row.setContentsMargins(theme.SPACE_3, 2, theme.SPACE_3, 2)
        row.setSpacing(theme.SPACE_2)

        prompt = festivals.post_prompt(f) if kind == "post" else festivals.reel_prompt(f)
        question = (i18n.t("{name} is coming up {when} — want to make a "
                           "{kind} about it?").format(
            name=f["name"], when=festivals.when_phrase(f),
            kind=i18n.t("post") if kind == "post" else i18n.t("reel")))
        label = QLabel(question)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {theme.INK}; font-size: 13px; background: transparent; border: none;")
        row.addWidget(label, stretch=1)

        yes_btn = C.button(i18n.t("Yes"), "secondary", small=True,
                           on_click=lambda *_, f=f, k=kind, p=prompt:
                               self._on_festival_answer(f, k, True, p))
        C.attach_shadow(yes_btn, C.SH_LIGHT_BTN)
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
        card = C.Card()
        card.setMinimumHeight(140 + C.CARD_LIP)
        col = QVBoxLayout(card)
        col.setContentsMargins(17, 15, 15, 13 + C.CARD_LIP)
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
        self._chip_icon(attach_btn, "paperclip")
        attach_btn.setCursor(Qt.PointingHandCursor)
        attach_btn.clicked.connect(self._on_attach_clicked)
        bar.addWidget(attach_btn)

        cmds_btn = QPushButton(i18n.t('Commands'))
        cmds_btn.setObjectName("promptChipBtn")
        self._chip_icon(cmds_btn, "cmd")
        cmds_btn.setCursor(Qt.PointingHandCursor)
        cmds_btn.clicked.connect(self.open_history.emit)
        bar.addWidget(cmds_btn)

        tools_btn = QPushButton(i18n.t('Tools'))
        tools_btn.setObjectName("promptChipBtn")
        self._chip_icon(tools_btn, "grid")
        tools_btn.setCursor(Qt.PointingHandCursor)
        tools_btn.clicked.connect(lambda: self.open_addon.emit("catalog"))
        bar.addWidget(tools_btn)

        bar.addStretch(1)

        send_btn = _SendButton()
        send_btn.setToolTip(i18n.t("Start task"))
        send_btn.clicked.connect(self._submit_home_task)
        bar.addWidget(send_btn)

        col.addLayout(bar)
        return card

    @staticmethod
    def _chip_icon(btn: QPushButton, name: str):
        """The preview's chip glyph (14px, 1.7 stroke) and its ~7px gap to the
        label, and the preview's hover shadow."""
        btn.setIcon(icons.icon_gapped(name, 14, theme.INK))
        btn.setIconSize(QSize(17, 14))
        C.attach_shadow(btn, C.SH_CHIP_HOVER, hover_only=True)

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

        prefix = QLabel(i18n.t("Try:").upper())
        prefix.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-size: 10px; "
            f"font-weight: 400; color: {theme.MUTE};"
        )
        row.addWidget(prefix)

        chips_data = [
            ("inquiry", i18n.t("Summarize a PDF"), "file"),
            ("reel", i18n.t("Create a reel"), "film-box"),
            ("boq", i18n.t("Analyze this BOQ"), "bars"),
            ("artifacts", i18n.t("Clean up artifacts"), "spark"),
        ]

        for key, label, icon_name in chips_data:
            chip = QPushButton(label)
            chip.setObjectName("tryChip")
            self._chip_icon(chip, icon_name)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, k=key: self.open_addon.emit(k))
            row.addWidget(chip)

        row.addStretch(1)
        return row

    # ── Section 2: Bottom Section (Two Columns) ───────────────────────────
    # ── Section 2: Today (insights) and demo videos ───────────────────────
    def _section_head(self, label: str, note: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(C.kicker(label))
        row.addStretch(1)
        if note:
            hint = QLabel(note)
            hint.setStyleSheet(theme.type_css("MONO", theme.MUTE) + " font-size: 11px;")
            row.addWidget(hint)
        return row

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

    # ── Recent activity: the latest runs as a row of small cards ──────────
    def _recent_section(self, col: QVBoxLayout, runs, stalled):
        if not runs:
            return
        listed = [r for r in runs if not _never_started(r)][:RECENT_SHOWN]
        col.addSpacing(theme.SPACE_3)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel(i18n.t("Recent activity"))
        title.setStyleSheet(f"font-family: '{theme.FONT_BODY}'; font-size: 13px; color: {theme.MUTE};")
        head.addWidget(title, stretch=1)
        head.addWidget(C.button(f"{i18n.t('See all')} →", "link",
                                on_click=self.open_history.emit))
        col.addLayout(head)
        if listed:
            cards = QHBoxLayout()
            cards.setSpacing(theme.CARD_GAP)
            for run in listed:
                card = _RunCard(run)
                card.clicked.connect(
                    lambda p=run.get("path", ""): p and self.open_run_record.emit(p))
                cards.addWidget(card, 1)
            for _ in range(RECENT_SHOWN - len(listed)):
                cards.addStretch(1)
            col.addLayout(cards)
        if stalled:
            col.addWidget(self._stalled_row(stalled))

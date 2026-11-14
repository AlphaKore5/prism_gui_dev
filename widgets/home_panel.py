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


class _TimelineRow(_Row):
    """A Recent activity row. No border (a 1px one would leave a gap in the
    timeline wire at every row); keyboard focus paints its ring instead."""

    def __init__(self, parent=None):
        super().__init__(True, parent)
        self.setStyleSheet(f"#rowFlat {{ border: none; }}"
                           f"#rowFlat:focus {{ background: {theme.WELL}; }}")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus():
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
            p.end()


class TimelineNode(QWidget):
    """The preview's `.acts li::before/::after`: a 1.2px #CBCAC4 wire at the left
    of the row (from the row's middle on the first row, full height otherwise)
    and a 7.4px ink dot centred on the row."""

    WIRE = "#CBCAC4"

    def __init__(self, is_first: bool = False, is_last: bool = False, parent=None):
        super().__init__(parent)
        self.setFixedWidth(8)
        self._is_first = is_first
        self._is_last = is_last

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        h = float(self.height())
        cy = h / 2.0
        top_y = cy if self._is_first else 0.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.WIRE))
        painter.drawRect(QRectF(3.8, top_y, 1.2, h - top_y))
        painter.setBrush(QColor(theme.INK))
        painter.drawEllipse(QPointF(4.0, cy), 3.7, 3.7)


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


class _Motto(QLabel):
    """The mono-caps pill with the AlphaKore red square (.motto)."""

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(14, (self.height() - 6) // 2, 6, 6, QColor(theme.BRAND_RED))
        p.end()


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


def _pixel_play(size: int) -> QPixmap:
    """The preview's pixel play glyph on a transparent pixmap (a demo tile's picture)."""
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    _pixel_glyph(p, size / 2, size / 2, size, PIXEL_PLAY)
    p.end()
    return pm


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


class _WatchDemoButton(QPushButton):
    """The preview's `.btn.light.sm` with a dark `.ic` chip: white gradient pill,
    25px near-black round chip carrying the pixel play glyph, then the label."""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("tourPlayBtn")
        self.setStyleSheet("min-height: 33px; max-height: 33px; padding: 0px; border: none;")
        self.setFixedHeight(33)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        C.attach_shadow(self, C.SH_LIGHT_BTN)

    def _font(self) -> QFont:
        f = QFont(theme.FONT_BODY)
        f.setPixelSize(13)
        f.setWeight(QFont.Medium)
        return f

    def sizeHint(self) -> QSize:
        tw = QFontMetrics(self._font()).horizontalAdvance(self.text())
        return QSize(int(4.4 + 25 + 8.8 + tw + 17 + .5), 33)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        body = QRectF(0, 0, w, h)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#FFFFFF"))
        g.setColorAt(1, QColor("#F8F7F4"))
        if self.isDown():
            g = QColor("#EFEEEA")
        p.setPen(QPen(QColor(20, 20, 18, 56 if self.underMouse() else 20), 1))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(body.adjusted(.5, .5, -.5, -.5), h / 2, h / 2)
        d = 25.0
        cx, cy = 4.4 + d / 2, h / 2
        dot = QRectF(cx - d / 2, cy - d / 2, d, d)
        rg = QLinearGradient(0, dot.top(), 0, dot.bottom())
        rg.setColorAt(0, QColor("#3a3a38"))
        rg.setColorAt(1, QColor("#111110"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(rg))
        p.drawEllipse(dot)
        hp = QPen(QBrush(_SendButton._dot_highlight(dot)), 1)
        p.setPen(hp)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(dot.adjusted(.5, .5, -.5, -.5))
        _pixel_glyph(p, cx, cy, 15.0, PIXEL_PLAY)
        p.setFont(self._font())
        p.setPen(QColor(theme.INK))
        x0 = 4.4 + d + 8.8
        p.drawText(QRectF(x0, 0, w - x0, h), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class _DemoPill(QLabel):
    """`.demo .pill`: mono 10px caps in a 6px-radius chip, white 10% fill and a
    22% ring; `live` adds the red square before the word."""

    def __init__(self, text: str, live: bool = False, parent=None):
        super().__init__(text, parent)
        self._live = live
        self.setFixedHeight(32)
        pad_l = 8 + (11 if live else 0)
        self.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-size: 10px; font-weight: 500; "
            "color: #ffffff; background: transparent; border: none; "
            f"padding: 0px 8px 0px {pad_l}px;")
        C.track(self, 0.08)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        p.setPen(QPen(QColor(255, 255, 255, 56), 1))
        p.setBrush(QColor(255, 255, 255, 26))
        p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 6, 6)
        if self._live:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.BRAND_RED))
            p.drawRect(QRectF(8, (r.height() - 5) / 2, 5, 5))
        p.end()
        super().paintEvent(event)


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
        C.attach_shadow(self, C.SH_DEMO, 17)

        col = QVBoxLayout(self)
        col.setContentsMargins(18, 16, 18, 15)
        col.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(_DemoPill("DEMO", live=True))
        top_row.addStretch(1)
        top_row.addWidget(_DemoPill("01:03 ›"))
        col.addLayout(top_row)

        col.addSpacing(14)
        title = QLabel(i18n.t("Ideas to outcomes."))
        tf = QFont(theme.FONT_HEADING)              # -0.035em, as .demo h2
        tf.setPixelSize(26)
        tf.setWeight(QFont.Normal)
        tf.setLetterSpacing(QFont.AbsoluteSpacing, -0.9)
        title.setFont(tf)
        title.setStyleSheet("color: #ffffff; background: transparent;")
        col.addWidget(title)

        col.addSpacing(7)
        desc = QLabel(i18n.t("Prism combines AI, tools and automation — so you can focus on what matters."))
        desc.setWordWrap(True)
        desc.setMaximumWidth(265)
        desc.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 13px; "
            "color: rgba(255, 255, 255, 0.78); background: transparent;"
        )
        col.addWidget(desc)
        col.addSpacing(15)

        tour_btn = _WatchDemoButton(i18n.t('Watch demo video'))
        tour_btn.clicked.connect(self._play_demo)
        col.addWidget(tour_btn)

        col.addStretch(1)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet("background: rgba(255, 255, 255, 0.22);")
        col.addWidget(rule)
        col.addSpacing(9)
        quote = QLabel(i18n.t("“Less work. More possibilities.”"))
        quote.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-size: 11px; "
            "color: rgba(255, 255, 255, 0.82); background: transparent;"
        )
        C.track(quote, 0.05)
        quote.setAlignment(Qt.AlignRight)
        col.addWidget(quote)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        if not painter.isActive():
            return
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())
        radius = 17.0

        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        painter.setClipPath(clip)

        # The preview's `.demo`: #0a0a09 under the brand painting (cover, 50% 22%),
        # then a dark wash that is solid behind the text and clear over the colour.
        painter.fillRect(r, QBrush(QColor(10, 10, 9)))
        pix = QPixmap(paths.resource("assets", "prism-spectrum.jpg"))
        if pix.isNull():
            pix = QPixmap(os.path.join(os.path.dirname(__file__), "..", "assets", "prism-spectrum.jpg"))
        if not pix.isNull():
            tw, th = max(1, int(r.width())), max(1, int(r.height()))
            scaled = pix.scaled(tw, th, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            sx = int((scaled.width() - tw) * 0.5)
            sy = int((scaled.height() - th) * 0.22)
            painter.drawPixmap(0, 0, scaled, sx, sy, tw, th)

        wash = QLinearGradient(0.0, 0.0, 0.0, float(r.height()))
        wash.setColorAt(0.00, QColor(10, 10, 9, 245))
        wash.setColorAt(0.40, QColor(10, 10, 9, 214))
        wash.setColorAt(0.68, QColor(10, 10, 9, 0))
        wash.setColorAt(1.00, QColor(10, 10, 9, 140))
        painter.fillRect(r, QBrush(wash))

        painter.setPen(QPen(QColor(0, 0, 0, 102), 1.0))      # 0 0 0 1px rgba(0,0,0,.4)
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


# One short demo video per main feature, shown under the composer so a new
# person can see what Prism does without leaving the app. A tile plays
# assets/demos/<key>.mp4 when that file exists. Until it is recorded the tile
# stays off and says so; dropping the file in turns it on, no code change.
DEMOS = (
    ("reel", "Make a reel", "A 9:16 video from one sentence", "reel"),
    ("boq", "Bill of Quantities", "From a drawing to a priced sheet", "boq"),
    ("inquiry", "Email inquiries", "Quote, remind, record the order", "inquiry"),
    ("leads", "Leads & Outreach", "Find people, draft, send", "leads"),
)


def demo_path(key: str) -> str:
    """The recorded demo for a feature, or "" when it has not been made yet."""
    p = paths.resource("assets", "demos", f"{key}.mp4")
    return p if os.path.isfile(p) else ""


class _StatTile(C.Card):
    """One number that matters today. Opens the screen where it is acted on."""

    clicked = Signal()

    def __init__(self, number: str, title: str, caption: str, parent=None):
        super().__init__(radius=14, parent=parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        col = self.body((theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4),
                        spacing=2)
        num = QLabel(number)
        num.setStyleSheet(f"font-family: '{theme.FONT_DISPLAY}'; font-size: 34px; "
                          f"font-weight: 700; color: {theme.INK}; background: transparent;")
        col.addWidget(num)
        col.addWidget(_Elided(title, "CARD_TITLE"))
        col.addWidget(_Elided(caption, "META", theme.MUTE))

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class _DemoTile(C.Card):
    """A demo-video tile. Off, with the reason, until its video exists."""

    clicked = Signal()

    def __init__(self, title: str, caption: str, icon_name: str, video: str, parent=None):
        super().__init__(radius=14, parent=parent)
        self._video = video
        col = self.body((theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_3),
                        spacing=theme.SPACE_1)
        thumb = QLabel()
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setFixedHeight(76)
        thumb.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3a3a38, stop:1 #111110);"
            " border-radius: 10px;")
        thumb.setPixmap(_pixel_play(26) if video else icons.icon(icon_name, 26, "#FFFFFF").pixmap(26, 26))
        col.addWidget(thumb)
        col.addWidget(_Elided(title, "CARD_TITLE"))
        col.addWidget(_Elided(caption if video else i18n.t("Not recorded yet"), "META", theme.MUTE))
        if video:
            self.setCursor(Qt.PointingHandCursor)
            self.setFocusPolicy(Qt.TabFocus)
        else:
            self.setEnabled(False)
            self.setToolTip(i18n.t("This demo hasn't been recorded yet."))

    def mousePressEvent(self, event):
        if self._video:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self._video and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
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

        # 3. Today (insights) and demo videos
        self._col.addLayout(self._insights_section())
        self._col.addLayout(self._demos_section())

        # 4. Bottom section (Left: Recent activity; Right: Add-ons)
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
            f"font-family: 'Geist Light', '{theme.FONT_BODY}'; font-size: 21px; "
            f"font-weight: 300; color: {theme.TEXT};"
        )
        greet_stack.addWidget(salutation)

        who = (identity.display_name(self.cfg) or "").split(" ")[0]
        if not who:
            who = "there"
        name_lbl = QLabel(f"{who.upper()},")
        name_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_DISPLAY}'; font-size: 52px; "
            f"font-weight: 700; color: {theme.INK};"
        )
        C.track(name_lbl, 0.02)
        greet_stack.addWidget(name_lbl)

        sub_lbl = QLabel(i18n.t("Let's turn ideas into outcomes."))
        _lead, _tail = "Let's turn ideas ", "into outcomes."
        if sub_lbl.text() == _lead + _tail:          # English: the tail is the faint clause
            sub_lbl.setTextFormat(Qt.RichText)
            sub_lbl.setText(f'{_lead}<span style="color: {theme.FAINT};">{_tail}</span>')
        sub_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 18px; "
            f"font-weight: 400; color: {theme.INK};"
        )
        greet_stack.addWidget(sub_lbl)
        greet_row.addLayout(greet_stack, stretch=1)

        motto = _Motto(i18n.t("Less work. More possibilities.").upper())
        motto.setStyleSheet(
            f"font-family: '{theme.FONT_MONO}'; font-size: 11px; "
            f"font-weight: 400; color: {theme.INK}; "
            f"background: #ffffff; "
            f"border: 1px solid {theme.HAIRLINE}; border-radius: 16px; "
            f"padding: 8px 14px 8px 28px;"
        )
        C.track(motto, 0.05)
        C.attach_shadow(motto, C.SH_MOTTO)
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
        card.setMinimumHeight(205)          # preview: 13.6rem (200px) + the 5px lip
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

    def _insights_section(self) -> QVBoxLayout:
        """The numbers the owner opens Prism for, every one read from the
        register and the run records. Nothing is invented: a store that is not
        set up shows a dash, never a plausible figure."""
        needs = DATA.needs_you(self.cfg, self._rows)
        month = DATA.month_summary(self.cfg, self._rows)
        done, failed = DATA.run_counts(self.cfg, 7)
        have = bool(self._rows)
        dash = "–"
        tiles = (
            (str(needs["to_quote"]) if have else dash, i18n.t("Inquiries to quote"),
             i18n.t("Waiting for your price") if needs["to_quote"] else
             (i18n.t("Nothing waiting") if have else i18n.t("No inquiry register yet")),
             lambda: self.open_addon.emit("inquiry")),
            (str(needs["waiting"]) if have else dash, i18n.t("Quotations, no answer"),
             (i18n.t("{n} need a reminder today").format(n=needs["due"]) if needs["due"] else
              (i18n.t("Nobody to chase") if have else i18n.t("No inquiry register yet"))),
             lambda: self.open_addon.emit("inquiry")),
            (str(month["converted"]) if month else dash, i18n.t("Orders this month"),
             month["month"] if month else i18n.t("No inquiry register yet"),
             lambda: self.open_addon.emit("inquiry")),
            (str(done + failed), i18n.t("Tasks run this week"),
             (i18n.t("{n} did not finish").format(n=failed) if failed else
              i18n.t("All saved in History")),
             self.open_history.emit),
        )
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2)
        box.addLayout(self._section_head(i18n.t("Today")))
        grid = QHBoxLayout()
        grid.setSpacing(theme.CARD_GAP)
        for number, title, caption, go in tiles:
            tile = _StatTile(number, title, caption)
            tile.clicked.connect(go)
            grid.addWidget(tile, stretch=1)
        box.addLayout(grid)
        return box

    def _demos_section(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2)
        box.addLayout(self._section_head(i18n.t("See Prism work"),
                                         i18n.t("Short demos, about a minute each")))
        grid = QHBoxLayout()
        grid.setSpacing(theme.CARD_GAP)
        for key, title, caption, icon_name in DEMOS:
            video = demo_path(key)
            tile = _DemoTile(i18n.t(title), i18n.t(caption), icon_name, video)
            if video:
                tile.clicked.connect(lambda _p=video: self._open_demo(_p))
            grid.addWidget(tile, stretch=1)
        box.addLayout(grid)
        return box

    def _open_demo(self, path: str):
        from dialogs.preview_dialog import open_preview
        open_preview(path, self, demo_mode=True)

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
        wrap = _TimelineRow()
        wrap.clicked.connect(
            lambda p=run.get("path", ""): p and self.open_run_record.emit(p))

        outer = QHBoxLayout(wrap)
        outer.setContentsMargins(0, 0, 0, 0)     # the wire runs the row's full height
        outer.setSpacing(12)

        track = TimelineNode(is_first=is_first, is_last=is_last)
        outer.addWidget(track)
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(12)
        outer.addLayout(row, 1)

        tools = run.get("tools") or []
        tile = C.IconPad(_run_icon(run), theme.INK, 34, 10, 14)
        tile.setStyleSheet("background: #EFEEEA; border-radius: 10px;")
        row.addWidget(tile)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)

        title = _Elided(run.get("title", ""), "BODY", weight=400)
        title.setStyleSheet(title.styleSheet() + " font-size: 14px; color: #111110;")
        text_col.addWidget(title)

        source = tools[0] if tools else "Prism"
        when = run.get("when", "")
        detail_text = f"{source} · {when}" if when else source
        subtitle = _Elided(detail_text, "META")
        subtitle.setStyleSheet(subtitle.styleSheet()
                               + f" font-family: '{theme.FONT_MONO}'; font-size: 11px;")
        C.track(subtitle, 0.03)
        text_col.addWidget(subtitle)
        row.addLayout(text_col, stretch=1)

        is_ok = run.get("ok", True)
        state = "completed" if is_ok else "failed"
        status_badge = C.Pill(theme.status(state)[0], "st_ok" if is_ok else "st_err")
        status_badge.setAccessibleName(theme.status(state)[0].title())
        row.addWidget(status_badge)

        menu_btn = QPushButton()
        menu_btn.setObjectName("recentMenuBtn")
        menu_btn.setIcon(icons.icon("more-dots", 18, theme.MUTE))
        menu_btn.setIconSize(QSize(18, 18))
        menu_btn.setFixedSize(30, 30)
        menu_btn.setCursor(Qt.PointingHandCursor)
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
        C.attach_shadow(manage_btn, C.SH_LIGHT_BTN)
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
        browse_btn.setStyleSheet("font-size: 13px; font-weight: 500; padding: 6px 14px;")
        C.attach_shadow(browse_btn, C.SH_LIGHT_BTN)
        browse_btn.clicked.connect(lambda: self.open_addon.emit("catalog"))
        foot.addWidget(browse_btn)

        foot.addStretch(1)

        guide_link = C.button(f"{i18n.t('Explore all add-ons')} →", "link",
                              on_click=lambda: self.open_addon.emit("catalog"))
        foot.addWidget(guide_link)
        col.addLayout(foot)

        return card

    @staticmethod
    def _make_tool_tile(host, name: str, glyph: str, builtin: bool, route: str) -> QWidget:
        return _ToolTile(host, name, glyph, builtin, route)

    def _make_addon_tile(self, name: str, logo_key: str, nav_key: str) -> QWidget:
        return self._make_tool_tile(self, name, logo_key, True, nav_key)


class _TileState(QLabel):
    """Mono caps state under an add-on tile: a small square, then READY."""

    def __init__(self, text: str, colour: str, parent=None):
        super().__init__(text.upper(), parent)
        self._colour = colour
        self.setStyleSheet(f"font-family: '{theme.FONT_MONO}'; font-size: 10px; "
                           f"color: {colour}; background: transparent; padding-left: 10px;")
        C.track(self, 0.08)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(0, (self.height() - 5) // 2, 5, 5, QColor(self._colour))
        p.end()


# The line icon of each Home add-on tile: the rail's glyph for the add-on (so the
# two agree) and the preview's own for the two the rail does not list.
_TILE_ICON = {"reel": "film-box", "motion": "video"}


def _tile_icon(glyph: str) -> str:
    from widgets.sidebar import _RAIL_ICON
    return _TILE_ICON.get(glyph) or _RAIL_ICON.get(glyph) or glyph


class _AddonHolder(QWidget):
    """`.ad .tile`: a 37px near-black squircle (gradient #3a3a38 to #111110, 12px
    radius, inset top highlight, soft drop shadow) with a white 1.6px line icon."""

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(37, 37)
        self._pm = icons.pixmap(icon_name, 17, "#FFFFFF", 1.6)
        C.attach_shadow(self, ((0, 5.9, 11.8, -5.9, (0, 0, 0, .5)),), 12)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        g = QLinearGradient(0, 0, 0, r.height())
        g.setColorAt(0, QColor("#3a3a38"))
        g.setColorAt(1, QColor("#111110"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 12, 12)
        p.setPen(_hl_pen(r.width(), r.height(), 56))     # inset 0 1px 0 .22
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(.5, 1.5, -.5, -.5), 11, 11)
        x = (r.width() - 17) / 2
        p.drawPixmap(int(round(x)), int(round(x)), self._pm)


class _ToolTile(QFrame):
    """Tool launcher tile with full keyboard navigation and accessible state.
    Painted as the preview's `.ad`: soft #F6F5F2 tile, 14px radius, ring, white
    and a soft shadow on hover."""

    def __init__(self, host, name: str, glyph: str, builtin: bool, route: str, parent=None):
        super().__init__(parent)
        self.host = host
        self.route = route
        self.setObjectName("toolTile")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(106)
        status_text = "Built-in" if builtin else "Not connected"
        self.setAccessibleName(f"{name} ({status_text})")
        C.attach_shadow(self, C.SH_TILE_HOVER, 14, hover_only=True)

        tile_col = QVBoxLayout(self)
        tile_col.setContentsMargins(7, 12, 7, 10)
        tile_col.setSpacing(7)
        tile_col.setAlignment(Qt.AlignCenter)

        tile_col.addWidget(_AddonHolder(_tile_icon(glyph)), alignment=Qt.AlignHCenter)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"font-family: '{theme.FONT_BODY}'; font-size: 14px; "
            f"font-weight: 500; color: {theme.INK}; background: transparent;"
        )
        name_lbl.setAlignment(Qt.AlignCenter)
        tile_col.addWidget(name_lbl)

        state = _TileState(i18n.t("Ready") if builtin else i18n.t("Not connected"),
                           theme.BRAND_OK if builtin else theme.NEUTRAL[400])
        tile_col.addWidget(state, alignment=Qt.AlignCenter)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(self.rect())
        hot = self.underMouse()
        p.setPen(QPen(QColor("#D8D7D2" if hot else "#E6E5E1"), 1))
        p.setBrush(QColor("#FFFFFF" if hot else "#F6F5F2"))
        p.drawRoundedRect(r.adjusted(.5, .5, -.5, -.5), 14, 14)
        if self.hasFocus():
            p.setPen(QPen(QColor(theme.INK), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1.5, 1.5, -1.5, -1.5), 13, 13)
        p.end()

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

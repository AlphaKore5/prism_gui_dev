"""The shared component module. Everything a screen is built out of lives here.

Two jobs, and the second one is now the bigger of the two.

The first is the original: three shapes in the design have no Qt equivalent to
style — the sliding switch, the tool chip with its filled initial-badge, and
the small filled check-square used as a step marker — so they are painted here
against the same tokens style.qss uses.

The second is consolidation. The component census found six recipes for a white
rounded panel, four mechanisms for a status tag, six empty states and the same
`_label` helper defined identically in four separate panels. None of that was
anyone reinventing things for fun: the shared version either did not exist, or
existed somewhere a panel could not reach it. So the rule for this module is
that if two screens need the same thing, the thing belongs here — and if you
are about to write a fifth `_label`, use `label()` below instead.

A component here is expected to earn its place by being obviously easier than
hand-rolling one. That means: a docstring saying what it is for and which
screen needs it, sane defaults, every interactive part keyboard-reachable with
a visible focus ring, and a minimum target height of 28px. COMPONENTS.md in the
redesign scratchpad is the index.

Tokens come from theme.py — never a literal hex, never a bare pixel size. The
accent rotation is a blunt string replace over eleven fixed hexes, so an
off-palette blue written here will not rotate and will strand one permanently
blue element in an otherwise green copy."""
from __future__ import annotations
import math
import os

from PySide6.QtCore import (
    Qt, Signal, QSize, QRect, QRectF, QPropertyAnimation, QEasingCurve, Property,
    QTimer, QPoint, QPointF, QEvent,
)
from PySide6.QtGui import (
    QAction, QPainter, QPen, QFont, QFontMetrics, QBrush, QColor, QPainterPath,
    QLinearGradient, QRadialGradient, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QMenu, QProgressBar,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

import theme
from widgets import icons

# The smallest a thing you can click is allowed to be. Every interactive
# component in this module asserts it, because a 24px row is reachable with a
# mouse on a desk and is not reachable with a trackpad on a train.
MIN_TARGET = theme.BTN_HEIGHT_SM   # 28px — from theme spacing scale


def add_password_visibility(edit: QLineEdit):
    """Add a trailing eye action that reveals a secret only while requested."""
    import i18n

    action = QAction(icons.icon("eye", 16, theme.NEUTRAL[500]), "", edit)
    action.setCheckable(True)
    action.setText(i18n.t("Show password"))
    action.setToolTip(i18n.t("Show password"))

    def toggle(visible: bool):
        edit.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        action.setIcon(icons.icon(
            "eye-off" if visible else "eye", 16, theme.NEUTRAL[600]))
        label = i18n.t("Hide password") if visible else i18n.t("Show password")
        action.setText(label)
        action.setToolTip(label)

    action.toggled.connect(toggle)
    edit.addAction(action, QLineEdit.TrailingPosition)
    return action


# ── text helpers ────────────────────────────────────────────────────────────
def track(widget, em: float):
    """Apply letter-spacing. QSS has no letter-spacing property, and this
    system leans on tracked uppercase condensed labels everywhere, so the
    spacing has to be set on the QFont directly."""
    font = widget.font()
    font.setLetterSpacing(QFont.PercentageSpacing, 100 + em * 100)
    widget.setFont(font)
    return widget


def has_wallpaper(widget) -> bool:
    """Whether the person picked a wallpaper (Settings > Appearance). Only then
    do cards stay frosted glass over it; by default they are flat AlphaKore
    cards: solid white, one hairline."""
    central = widget.window().findChild(QWidget, "central")
    pix = getattr(central, "_bg_orig", None)
    return bool(pix is not None and not pix.isNull())


def paint_flat_card(widget, painter, rect: QRectF, radius: float) -> bool:
    """Paint the flat card and return True, or return False when a wallpaper is
    set and the caller should paint its glass instead."""
    if has_wallpaper(widget):
        return False
    painter.setPen(QPen(QColor(theme.HAIRLINE), 1))
    painter.setBrush(QColor(theme.CARD))
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    return True


class _Kicker(QLabel):
    """Uppercase mono label led by the AlphaKore red square (.kick)."""

    _SQ = 6                     # square edge
    _GAP = 6                    # square to text

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setContentsMargins(self._SQ + self._GAP, 0, 0, 0)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.fillRect(0, (self.height() - self._SQ) // 2, self._SQ, self._SQ,
                   QColor(theme.BRAND_RED))
        p.end()


def kicker(text: str, muted: bool = False) -> QLabel:
    """Mono, tracked, uppercase section label with a red square (.kick)."""
    lbl = _Kicker(text.upper())
    lbl.setObjectName("kickMuted" if muted else "kick")
    return track(lbl, 0.12)


def heading(text: str, level: int = 4) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(f"h{level}")
    return track(lbl, -0.015)


def meta(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("meta")
    return lbl


# The eight levels, smallest first, for snapping a legacy `size=` argument onto
# the scale. See label() — this is how twenty shipped font sizes are absorbed
# without hunting down every call site by hand.
_LEVELS_BY_PX = (
    (11, "LABEL"), (12, "META"), (13, "SUPPORT"), (14, "BODY"),
    (15, "CARD_TITLE"), (18, "SECTION"), (24, "PAGE_TITLE"),
)


def _level_for_px(px: float) -> str:
    """The scale level nearest a raw pixel size."""
    return min(_LEVELS_BY_PX, key=lambda pair: abs(pair[0] - px))[1]


def label(text: str, role: str = "", level: str = "", colour: str = "",
          weight: int = 0, wrap: bool = False, size: float = 0,
          tooltip: str = "") -> QLabel:
    """One text label, on the type scale. The single label helper.

    This function is the shared version of the `_label` that four panels
    (simple_panels, home_panel, settings_panel, inquiry_panel) each defined
    byte-for-byte identically, and it exists because that duplication is what
    produced the sprawl: twenty distinct font sizes, nine of them inside one
    4px band, almost all introduced by an ad-hoc `size=` argument rather than
    by any named role. Half a pixel is not a decision anyone can see.

    So `size=` is still accepted — a call site that passes 12.5 keeps working —
    but it is SNAPPED to the nearest of the eight levels rather than honoured
    literally. That is deliberate: it lets a panel be converted by search and
    replace and still come out on the scale.

    Prefer, in this order:
        label("Runs this week", level="SECTION")   the scale, by name
        label("3 minutes ago", role="meta")        an existing qss type role
        label(text, colour=theme.OK_INK)           an override, when the
                                                   colour carries meaning

    `role` sets the object name, so every type role style.qss already defines
    (h1-h6, kick, meta, dim, faint, body, lead, stat, statSm, mono, emptyState)
    keeps working untouched.
    """
    lbl = QLabel(text)
    if role:
        lbl.setObjectName(role)
    if not level and size:
        level = _level_for_px(size)
    if level or colour or weight:
        family, px, css_weight, ink = theme.TYPE.get(level or "BODY",
                                                     theme.T_BODY)
        stack = (theme.FONT_MONO_STACK if (level or "") == "MONO"
                 else f"'{family}'")
        # An explicit colour beats the level's own ink; a level with no colour
        # override keeps the ink the scale assigns it, which is what makes
        # SUPPORT reliably muted and BODY reliably not.
        parts = [f"font-weight: {weight or css_weight};",
                 f"color: {colour or ink};"]
        if level:
            parts.insert(0, f"font-family: {stack}; font-size: {px}px;")
        lbl.setStyleSheet(" ".join(parts))
    if wrap:
        lbl.setWordWrap(True)
    if tooltip:
        lbl.setToolTip(tooltip)
    return lbl


def hairline(vertical: bool = False) -> QFrame:
    """The 1px rule between two rows, or between two columns.

    Defined three times across the panels with three slightly different
    recipes; this is the one. It carries the `cardLine` object name, so its
    colour comes from style.qss and moves with the palette rather than being
    baked into whichever panel drew it.
    """
    line = QFrame()
    line.setObjectName("cardLine")
    if vertical:
        line.setObjectName("railLine")
        line.setFixedWidth(1)
    else:
        line.setFixedHeight(1)
    return line


def icon_label(icon_name: str, text: str, size: int = 16,
               color: str = None) -> QFrame:
    """A line icon next to a caption — the system's replacement for the
    emoji-prefixed labels the app used to carry."""
    wrap = QFrame()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    glyph = QLabel()
    glyph.setPixmap(icons.pixmap(icon_name, size, color or theme.ACCENT))
    row.addWidget(glyph)
    row.addWidget(QLabel(text), stretch=1)
    return wrap


# ── elevation ───────────────────────────────────────────────────────────────
def shadows_enabled() -> bool:
    """Whether to hang a QGraphicsDropShadowEffect off every card. OFF by
    default, and that default is the fix for the blank-panels bug.

    A widget carrying a QGraphicsEffect is painted through a separate pipeline
    — and that pipeline draws the WHOLE widget, background and children
    included, not just the shadow. On some setups (software rasterisers,
    virtual machines, remote desktop, older drivers) it produces nothing at
    all. The card then reserves its space in the layout and never paints, so
    the screen shows correctly-sized gaps where the content should be, while
    everything WITHOUT an effect — headings, the timeline dots — draws
    normally. It reads as the app having lost your work rather than as a
    graphics fault, which is what made it so hard to report.

    A soft shadow is not worth that. Cards now read as cards from their white
    fill and hairline border, which are ordinary QSS and paint everywhere,
    and the design's own predecessor used hairline borders anyway.

    Opt back in per machine if you want the lift and know it works there:

        PRISM_SHADOWS=1           one run
        ~/.prism/config.json      "shadows": true, to make it stick
    """
    if os.environ.get("PRISM_SHADOWS"):
        return True
    try:
        import core_bridge as CB
        if (CB.config.load() or {}).get("shadows"):
            return True
    except Exception:
        pass                    # unreadable config must not turn them back on
    return False


def effects_enabled() -> bool:
    """Whether an entrance animation may run through a QGraphicsEffect. OFF by
    default, for the same reason shadows_enabled() is — and this one is worse.

    A widget carrying a QGraphicsEffect is painted through a separate pipeline
    that draws the whole widget, background and children included. On software
    rasterisers, virtual machines, remote desktop and older drivers that
    pipeline produces nothing at all.

    A drop shadow that fails to render costs you a shadow. A
    QGraphicsOpacityEffect that fails to render costs you the widget: the
    animation starts at opacity 0.0 and drives it to 1.0, so if the effect
    never paints, the card is present, correctly sized, laid out, and
    completely invisible — permanently. That is live in the app today. Every
    StageCard on the run screen fades in from a QGraphicsOpacityEffect, so on
    such a machine a customer watching a nine-stage run sees nine
    correctly-sized blank gaps and concludes the app lost their work.

    Use this to gate the animation, not to gate the widget:

        if controls.effects_enabled():
            card.setGraphicsEffect(fade)
            anim.start()
        # …and nothing else. The card is already visible and already correct.

    The important half is that the else branch is empty. An entrance animation
    is a nicety; the content is the product. Never make the final state depend
    on the animation having run.

    Opt back in per machine if you want the motion and know it works there:

        PRISM_EFFECTS=1           one run
        ~/.prism/config.json      "effects": true, to make it stick
    """
    if os.environ.get("PRISM_NO_EFFECTS"):
        return False
    return True


def elevate(widget: QWidget, spec=None, hue: str = None) -> QWidget:
    """Give a widget the design's soft drop shadow.

    QSS has no box-shadow, so every card in the Soft Industry direction gets
    its lift from a QGraphicsDropShadowEffect instead. The design's shadows are
    all large-blur, low-alpha and offset downward — `0 20px 44px -18px
    rgba(20,30,40,0.16)` and friends. Qt has no spread, so the negative spread
    is absorbed by using the blur radius the design's spread implies rather
    than its literal value; the visual weight matches.

    Note the caller must leave margin around the widget for the shadow to fall
    into, or the parent layout clips it. Cards are laid out with that in mind.

    Returns the widget either way, so callers never have to care whether the
    shadow was actually applied — see shadows_enabled().
    """
    if not shadows_enabled():
        return widget
    blur, dy, alpha = spec or theme.SHADOW_CARD
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(theme.c(hue or theme.SHADOW_INK, alpha))
    widget.setGraphicsEffect(effect)
    return widget


class Card(QFrame):
    """The one surface this redesign is built out of: a water-glass
    glassmorphism panel floating over the canvas.

    Paints multiple layers of glass optics in paintEvent:
      - A vertical gradient fill that fades from bright-white at the top
        to a faintly blue-tinted translucent base — simulating water depth.
      - A bright specular sheen along the top inner edge (the "wet rim").
      - A fainter secondary sheen along the left inner edge (side catch-light).
      - A soft inner shadow at the bottom (light absorption in deep glass).
      - A crisp outer border composed of a bright top-left arm and a faint
        bottom-right arm, which together read as directional studio light.

    `stripe` paints the 3px accent bar across the top that replaces the
    blueprint registration marks the old design cornered its panels with.
    """

    def __init__(self, stripe: bool = False, radius: int = 18,
                 raised: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._radius = radius
        self._stripe = stripe
        self.setAttribute(Qt.WA_StyledBackground, True)
        # QSS provides the base fill; paintEvent layers the glass optics on top.
        self.setStyleSheet(
            f"#card {{ background: transparent; border-radius: {radius}px; "
            f"border: none; }}"
        )
        elevate(self, theme.SHADOW_RAISED if raised else theme.SHADOW_CARD)

    def body(self, margins=None, spacing: int = 0) -> QVBoxLayout:
        """The card's own column, inset past the stripe."""
        if margins is None:
            margins = (theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD)
        col = QVBoxLayout(self)
        top = margins[1] + (3 if self._stripe else 0)
        col.setContentsMargins(margins[0], top, margins[2], margins[3])
        col.setSpacing(spacing)
        return col

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = QRectF(self.rect())
        radius = float(self._radius)
        if paint_flat_card(self, painter, r, radius):
            if self._stripe:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(theme.INK))
                painter.drawRect(QRectF(r.left() + radius, r.top(), r.width() - 2 * radius, 3))
            return

        # ── Clip all painting to the rounded rect ──────────────────────────
        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        painter.setClipPath(clip)

        # ── Layer 1: True Gaussian Backdrop Blur ──────────────────────────
        central = self.window().findChild(QWidget, "central")
        if central and hasattr(central, "get_blurred_pixmap"):
            blurred = central.get_blurred_pixmap()
            if blurred and not blurred.isNull():
                pos = central.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
                src_rect = QRect(pos.x(), pos.y(), int(r.width()), int(r.height()))
                painter.drawPixmap(r.toRect(), blurred, src_rect)

        # ── Layer 2: Frosted light glass sheen ────────────────────────────
        glass_grad = QLinearGradient(QPointF(r.left(), r.top()),
                                     QPointF(r.left(), r.bottom()))
        glass_grad.setColorAt(0.00, QColor(255, 255, 255, 215))  # ~84% frosted white at top rim
        glass_grad.setColorAt(0.40, QColor(255, 255, 255, 175))  # ~68% frosted white in middle
        glass_grad.setColorAt(1.00, QColor(255, 255, 255, 155))  # ~60% frosted white at bottom
        painter.setBrush(QBrush(glass_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(r, radius, radius)

        # ── Layer 3: Diagonal bright-light catch sheen ─────────────────────
        sheen = QRadialGradient(QPointF(r.left() + r.width() * 0.2,
                                        r.top() + r.height() * 0.1),
                                r.width() * 0.65)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 100))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen))
        painter.drawRoundedRect(r, radius, radius)

        # ── Layer 4: Outer glass specular and contact border ──────────────
        border_grad = QLinearGradient(
            QPointF(r.left(), r.top()), QPointF(r.right(), r.bottom()))
        border_grad.setColorAt(0.0, QColor(255, 255, 255, 230))
        border_grad.setColorAt(0.5, QColor(255, 255, 255, 130))
        border_grad.setColorAt(1.0, QColor(0, 0, 0, 24))
        border_pen = QPen(QBrush(border_grad), 1.2)
        painter.setPen(border_pen)
        painter.setBrush(Qt.NoBrush)
        inset = r.adjusted(0.6, 0.6, -0.6, -0.6)
        painter.drawRoundedRect(inset, radius - 0.6, radius - 0.6)

        # ── Stripe accent bar (optional) ───────────────────────────────────
        if self._stripe:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
            painter.drawRect(QRectF(r.left(), r.top(), r.width(), 3))
        # painter is implicitly ended when it goes out of scope.
        # We do NOT call super().paintEvent(event) here — QFrame would overdraw
        # our glass layers with a solid background. Children are painted by Qt
        # through their own paint events, not through this frame's paintEvent.


class Pill(QLabel):
    """The rounded status tag the design uses everywhere — "Done", "Quoted",
    "3 waiting". Tone names map to the semantic roles, not the accent, so a
    "Won" pill stays green in every role.

    Every tone below clears WCAG AA (4.5:1) against its own tint. Two did not
    before this pass: `neutral` was NEUTRAL[700] on NEUTRAL[100] at 3.9:1 and
    `quiet` was NEUTRAL[500] on the same at 2.6:1 — the pill that says "Queued"
    was the least readable thing on the run screen. Both inks moved one step
    down the ramp; the tints are unchanged, and the two tones are still a
    visible three steps apart.
    """

    # The shipped defaults, kept as a class attribute because callers read it.
    # _tones() below is what set_tone actually uses — see why there.
    TONES = {
        "accent": (theme.ACCENT_RAMP[100], theme.ACCENT_RAMP[800]),
        "info": (theme.INFO_BG, theme.INFO_INK),
        # NEUTRAL[200], not [100]: step 100 is one unit off the canvas, so a
        # neutral pill on the page rather than on a card had no fill at all.
        "neutral": (theme.NEUTRAL[200], theme.NEUTRAL[800]),
        "ok": (theme.OK_BG, theme.OK_INK),
        "warn": (theme.WARN_BG, theme.WARN_INK),
        "err": (theme.ERR_BG, theme.ERR_INK),
        "quiet": (theme.NEUTRAL[100], theme.NEUTRAL[700]),
    }

    @classmethod
    def _tones(cls) -> dict:
        """The tone table, rebuilt against theme's *current* accent.

        TONES is evaluated when this module is imported, and this module is
        imported before theme.apply_role() runs. So the two accent tones in the
        frozen copy are always Prism blue — in a green profile every other
        surface rotates and the accent pill does not. Reading them live is the
        fix, and it costs one dict build per pill.
        """
        live = dict(cls.TONES)
        live["accent"] = (theme.ACCENT_RAMP[100], theme.ACCENT_RAMP[800])
        live["info"] = (theme.INFO_BG, theme.INFO_INK)
        return live

    def __init__(self, text: str = "", tone: str = "neutral", parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.set_tone(tone)

    def set_tone(self, tone: str):
        tones = self._tones()
        bg, ink = tones.get(tone, tones["neutral"])
        family, px, weight, _ink = theme.T_LABEL
        self.setStyleSheet(
            f"background: {bg}; color: {ink}; border-radius: {theme.R_PILL}px;"
            f" font-size: {px}px; font-weight: {weight};"
            f" padding: 3px {theme.SPACE_3 - 1}px;")


class ToolBadge(QLabel):
    """The rounded square carrying a tool's initial in its own brand colour."""

    def __init__(self, tool: str, size: int = 28, radius: int = theme.R_CHIP,
                 parent=None):
        super().__init__(theme.badge_initial(tool), parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: {theme.badge_color(tool)}; color: #ffffff;"
            f" border-radius: {radius}px; font-family: '{theme.FONT_HEADING}';"
            f" font-weight: 700; font-size: {max(9, int(size * 0.43))}px;")


class IconPad(QLabel):
    """A line icon on a soft tinted pad — the design's standard leading glyph
    for a stat card, an add-on row or a timeline dot."""

    def __init__(self, icon_name: str, hue: str = None, size: int = 30,
                 radius: int = theme.R_CONTROL, glyph: int = 15, parent=None):
        super().__init__(parent)
        hue = hue or theme.ACCENT
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setPixmap(icons.pixmap(icon_name, glyph, hue))
        self.setStyleSheet(
            f"background: {theme.tint(hue)}; border-radius: {radius}px;")


class Avatar(QLabel):
    """Circular initial. The rail, the profile row and every register line use
    the same one so a customer reads the same in all three."""

    def __init__(self, name: str, size: int = 28, hue: str = None, parent=None):
        super().__init__((name or "?").strip()[:1].upper() or "?", parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: {hue or theme.ACCENT}; color: #ffffff;"
            f" border-radius: {size // 2}px;"
            f" font-family: '{theme.FONT_HEADING}'; font-weight: 700;"
            f" font-size: {max(10, int(size * 0.42))}px;")


class Sparkline(QWidget):
    """The seven-bar mini chart on the dashboard stat cards.

    Painted rather than charted on purpose: it carries no axis, no scale and no
    tooltip, and is not meant to be read as data — it is there to say "this
    number has a direction". The last three bars take full colour and the
    earlier ones fade back, which is what gives the shape its read.
    """

    def __init__(self, values: list[float], hue: str = None, parent=None):
        super().__init__(parent)
        self._values = list(values) or [0]
        self._hue = hue or theme.ACCENT
        self.setFixedHeight(22)
        self.setMinimumWidth(len(self._values) * 6)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        top = max(self._values) or 1
        count = len(self._values)
        bar, gap = 4, 2
        span = count * bar + (count - 1) * gap
        x = self.width() - span                 # right-aligned, per the design
        for i, value in enumerate(self._values):
            height = max(2, round(self.height() * (value / top)))
            # Recent bars at full strength, older ones stepped back — two
            # tints, not a gradient, so it reads at 22px tall.
            fade = 1.0 if i >= count - 3 else (0.45 if i >= count - 5 else 0.22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(theme.c(self._hue, fade)))
            painter.drawRoundedRect(
                QRectF(x + i * (bar + gap), self.height() - height, bar, height),
                2, 2)


class ProgressBar(QWidget):
    """The 5px rounded run-progress bar on an active-run card."""

    def __init__(self, fraction: float = 0.0, hue: str = None, parent=None):
        super().__init__(parent)
        self._fraction = max(0.0, min(1.0, fraction))
        self._hue = hue or theme.ACCENT
        self.setFixedHeight(5)

    def set_fraction(self, fraction: float):
        self._fraction = max(0.0, min(1.0, fraction))
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(theme.CARD_LINE))
        painter.drawRoundedRect(QRectF(self.rect()), 3, 3)
        if self._fraction <= 0:
            return
        painter.setBrush(theme.c(self._hue))
        painter.drawRoundedRect(
            QRectF(0, 0, self.width() * self._fraction, self.height()), 3, 3)


class Chip(QFrame):
    """A small status tag with a leading line icon. A QLabel can show a pixmap
    or text but never both, so the pair needs its own two-label box.

    The ink comes from theme.TAG_TONES, which is the same table style.qss uses
    for the #tagXxx rules this class also applies. That is the fix for a real
    bug: the two used to be separate, and they disagreed for two of the five
    tones. A `tagWarn` chip painted its text NEUTRAL[600] grey while the
    stylesheet gave the frame an amber fill, and a `tagOk` chip painted its
    text accent blue on a green fill — so the one class built specifically to
    show a status rendered the wrong ink for its own tone, while the plain
    QLabel it duplicates got the right one. One table now, read at paint time,
    so it cannot drift again.
    """

    def __init__(self, text: str = "", icon_name: str = "", style: str = "tagOk",
                 parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(9, 3, 9, 3)
        row.setSpacing(theme.SPACE_1 + 1)
        self._icon = QLabel()
        row.addWidget(self._icon)
        self._text = QLabel()
        row.addWidget(self._text)
        self.set(text, icon_name, style)

    def set(self, text: str, icon_name: str = "", style: str = "tagOk"):
        _bg, color = theme.TAG_TONES.get(
            style, theme.TAG_TONES["tagNeutral"])
        _family, px, weight, _ink = theme.T_LABEL
        self._text.setText(text)
        self._text.setStyleSheet(
            f"font-size: {px}px; font-weight: {weight}; color: {color};")
        if icon_name:
            self._icon.setPixmap(icons.pixmap(icon_name, 13, color))
        self._icon.setVisible(bool(icon_name))
        self.setObjectName(style)
        self.style().unpolish(self)
        self.style().polish(self)


# ── switch ──────────────────────────────────────────────────────────────────
class ToggleSwitch(QAbstractButton):
    """The modern high-contrast pill switch.
    Off: clearly visible neutral track with white knob.
    On: deep sleek black track with white knob on the right.
    """

    W, H = 38, 20
    KNOB = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(self.W, self.H)
        self._pos = 3.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(float(self.W - self.KNOB - 3 if on else 3))
        self._anim.start()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float):
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self) -> QSize:
        return QSize(self.W, self.H)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        on = self.isChecked()
        radius = self.H / 2.0
        rect = QRectF(0, 0, self.W, self.H)

        if on:
            # Active state: deep sleek black track with subtle border
            painter.setPen(QPen(QColor(0, 0, 0, 70), 1.0))
            painter.setBrush(QColor("#18181b"))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

            # White knob with soft shadow
            inset = (self.H - self.KNOB) / 2.0
            knob_rect = QRectF(self._pos, inset, self.KNOB, self.KNOB)
            painter.setPen(QPen(QColor(0, 0, 0, 40), 1.0))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(knob_rect)
        else:
            # Inactive state: clearly visible modern light-grey track with crisp outline
            painter.setPen(QPen(QColor(0, 0, 0, 40), 1.0))
            painter.setBrush(QColor("#d1d5db"))
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius - 0.5, radius - 0.5)

            # White knob with clean subtle boundary
            inset = (self.H - self.KNOB) / 2.0
            knob_rect = QRectF(self._pos, inset, self.KNOB, self.KNOB)
            painter.setPen(QPen(QColor(0, 0, 0, 45), 1.0))
            painter.setBrush(QColor("#ffffff"))
            painter.drawEllipse(knob_rect)


# ── step marker ─────────────────────────────────────────────────────────────
class StepMark(QLabel):
    """The rounded square that leads a plan row: filled accent + white tick
    when the step is in the run, flat neutral-200 when it's been switched off.

    The off state drops its tick entirely rather than showing a grey one. A
    faint tick still reads as "ticked" at a glance, which is exactly backwards
    for the one control on the screen whose whole job is to say this step will
    not run."""

    SIZE = 22

    def __init__(self, included: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._included = included
        self._refresh()

    def set_included(self, included: bool):
        if included != self._included:
            self._included = included
            self._refresh()

    def _refresh(self):
        if self._included:
            self.setPixmap(icons.pixmap("check", 13, "#ffffff"))
        else:
            self.clear()
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("on", self._included)
        self.setObjectName("stepMark")
        self.style().unpolish(self)
        self.style().polish(self)


# ── tool chip ───────────────────────────────────────────────────────────────
class ToolChip(QAbstractButton):
    """`.tool` — a hairline chip carrying a filled square badge with the
    tool's initial, its name, and a chevron. Clicking opens the list of every
    tool available for that stage, so the chip *is* the agent picker."""

    changed = Signal(str)
    BADGE = 19
    _PAD_L, _PAD_R, _GAP = 4, 9, 8

    def __init__(self, tools: list[str], current: str = "", suggested: str = "",
                 parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._tools = list(tools)
        self._suggested = suggested
        self._current = current or (self._tools[0] if self._tools else "")
        self._font = QFont(theme.FONT_BODY, 11)
        self._badge_font = QFont(theme.FONT_HEADING, 10)
        self._badge_font.setWeight(QFont.DemiBold)
        self.clicked.connect(self._open_menu)
        self._resize_to_text()

    # -- state ------------------------------------------------------------
    def current(self) -> str:
        return self._current

    def set_current(self, tool: str):
        if tool and tool != self._current:
            self._current = tool
            self._resize_to_text()
            self.update()

    def _resize_to_text(self):
        width = (self._PAD_L + self.BADGE + self._GAP
                 + QFontMetrics(self._font).horizontalAdvance(self._current)
                 + 6 + 15 + self._PAD_R)
        self.setFixedSize(width, 29)

    def _open_menu(self):
        if not self._tools:
            return
        menu = QMenu(self)
        for name in self._tools:
            label = f"{name}  ★ suggested" if name == self._suggested else name
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(name == self._current)
            action.triggered.connect(lambda _=False, n=name: self._pick(n))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _pick(self, name: str):
        if name != self._current:
            self.set_current(name)
            self.changed.emit(name)

    # -- paint ------------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect()
        if not self.isEnabled():
            painter.setOpacity(0.4)
            fill_color = theme.NEUTRAL[200]
            text_color = theme.NEUTRAL[600]
            chev_color = theme.NEUTRAL[400]
        else:
            hovered = self.underMouse()
            fill_color = "#27272a" if hovered else "#18181b"
            text_color = "#ffffff"
            chev_color = "#a1a1aa"

        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c(fill_color))
        painter.drawRoundedRect(QRectF(rect), theme.R_CONTROL,
                                theme.R_CONTROL)

        badge = QRectF(self._PAD_L, (rect.height() - self.BADGE) / 2,
                       self.BADGE, self.BADGE)
        painter.setBrush(theme.c(theme.badge_color(self._current)))
        painter.drawRoundedRect(badge, theme.R_MICRO, theme.R_MICRO)
        painter.setPen(theme.c("#ffffff"))
        painter.setFont(self._badge_font)
        painter.drawText(badge, Qt.AlignCenter,
                         theme.badge_initial(self._current))

        painter.setPen(theme.c(text_color))
        painter.setFont(self._font)
        text_x = int(badge.right()) + self._GAP
        painter.drawText(QRect(text_x, 0, rect.width() - text_x - self._PAD_R - 15,
                               rect.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self._current)

        chevron = icons.pixmap("chevron-down", 15, chev_color)
        painter.drawPixmap(rect.width() - self._PAD_R - 15,
                           (rect.height() - 15) // 2, chevron)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)


# ── buttons ─────────────────────────────────────────────────────────────────
# Four variants and no more. style.qss carries the colour model for each; these
# two factories exist so a panel picks a variant by name instead of guessing an
# object name, which is how the app ended up with eleven of them — including
# `primary`, which had no rule at all, so three add-on "run" buttons rendered
# as plain hairline boxes.
_VARIANTS = {
    "primary": "primaryBtn",        # solid accent — exactly one per surface
    "secondary": "secondaryBtn",    # outlined neutral — the default, the workhorse
    "tertiary": "ghostBtn",         # text/ghost — in-place actions
    "destructive": "dangerBtn",     # outlined red — irreversible only
    "link": "linkBtn",              # tertiary, left-aligned, for a column of them
}


def button(text: str, variant: str = "secondary", icon_name: str = "",
           small: bool = False, on_click=None) -> QPushButton:
    """One button, in one of the four variants.

    Which to reach for:
        primary      the single thing this surface is for. One per screen.
        secondary    everything else with a box. The default, and correct
                     far more often than primary is.
        tertiary     an action inside a row or card that must not compete
                     with the surface's primary.
        destructive  delete, discard, revoke. Nothing that can be undone.

    `small` is a size modifier on the secondary variant, not a fifth variant.
    Qt style sheets have one object name per widget, so a small primary is not
    expressible without a second rule — and a primary action that wants to be
    small is usually a secondary action that has not admitted it yet.
    """
    btn = QPushButton(text)
    name = _VARIANTS.get(variant, "")
    if small and variant == "secondary":
        name = "smallBtn"
    if name:
        btn.setObjectName(name)
    btn.setCursor(Qt.PointingHandCursor)
    # Even the small step clears the minimum target: 28px is the floor for
    # anything you can click, not a suggestion that shrinks with the label.
    btn.setMinimumHeight(MIN_TARGET)
    if icon_name:
        ink = {"primary": theme.CARD, "destructive": theme.ERR_INK}.get(
            variant, theme.ACCENT_RAMP[700] if variant in ("tertiary", "link")
            else theme.NEUTRAL[800])
        icons.button_icon(btn, icon_name, 15, ink)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


def icon_button(icon_name: str, tooltip: str = "", on_click=None,
                colour: str = "") -> QPushButton:
    """A square glyph-only button. 34px, so it clears the 28px minimum target
    with room for its focus ring.

    Always give it a tooltip: a button whose only label is a picture is
    unlabelled to a screen reader and ambiguous to everyone else, and the
    tooltip is what fills both gaps.
    """
    btn = QPushButton()
    btn.setObjectName("iconBtn")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFixedSize(34, 34)
    icons.button_icon(btn, icon_name, 17, colour or theme.NEUTRAL[700])
    if tooltip:
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


# ── status ──────────────────────────────────────────────────────────────────
class _StatusDot(QWidget):
    """The glyph half of a StatusBadge. Painted, because a dot that pulses and
    a dot that spins are two frames of the same 12px circle and neither is
    something QSS can draw.

    Motion here is a QTimer repaint, deliberately NOT a QGraphicsEffect. An
    effect-driven fade can render the whole widget as nothing on a software
    rasteriser (see effects_enabled()); a repaint cannot, so the worst case for
    this dot on a bad renderer is that it holds still.
    """

    SIZE = 12

    def __init__(self, state: str = "idle", parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)
        self.set_state(state)

    def set_state(self, state: str):
        self._label, self._ink, self._bg, self._dot = theme.status(state)
        self._sync_timer()
        self.update()

    def _sync_timer(self):
        wants = self._dot in ("pulse", "spinner") and self.isVisible()
        if wants and not self._timer.isActive():
            self._timer.start()
        elif not wants and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.08) % 1.0
        self.update()

    # A timer running behind a hidden widget is a repaint nobody sees and a
    # wakeup the machine pays for anyway — a nine-stage run leaves nine of them
    # behind when you navigate away.
    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        ink = theme.c(self._ink)
        box = QRectF(1, 1, self.SIZE - 2, self.SIZE - 2)
        kind = self._dot

        if kind == "hollow":
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(self._ink, 0.55), 1.6))
            painter.drawEllipse(box)
        elif kind == "dashed":
            pen = QPen(theme.c(self._ink, 0.75), 1.6, Qt.DashLine)
            pen.setDashPattern([2.0, 1.6])
            painter.setBrush(Qt.NoBrush)
            painter.setPen(pen)
            painter.drawEllipse(box)
        elif kind == "solid":
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(box)
        elif kind == "pulse":
            # A ring expanding out of a solid core. This is the one cue on the
            # run screen that says "Prism is here now, this is the live step" —
            # the previous static ring was a 45% accent on a near-white fill,
            # which the design's own notes admitted was the worst contrast in
            # the system.
            grow = self._phase
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(self._ink, max(0.0, 0.5 * (1 - grow))),
                                1.6))
            spread = box.adjusted(-2.5 * grow, -2.5 * grow, 2.5 * grow,
                                  2.5 * grow)
            painter.drawEllipse(spread)
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(box.adjusted(2, 2, -2, -2))
        elif kind == "spinner":
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(self._ink, 0.22), 1.8))
            painter.drawEllipse(box)
            painter.setPen(QPen(ink, 1.8, Qt.SolidLine, Qt.RoundCap))
            start = int(-self._phase * 360 * 16) + 90 * 16
            painter.drawArc(box, start, -100 * 16)
        elif kind == "square":
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 2, 2)
        elif kind == "dash":
            painter.setPen(QPen(ink, 2.0, Qt.SolidLine, Qt.RoundCap))
            mid = self.SIZE / 2
            painter.drawLine(QRectF(2, mid, 0, 0).topLeft(),
                             QRectF(self.SIZE - 2, mid, 0, 0).topLeft())
        else:                                   # check / cross
            painter.setPen(Qt.NoPen)
            painter.setBrush(ink)
            painter.drawEllipse(box)
            painter.setPen(QPen(theme.c(self._bg), 1.7, Qt.SolidLine,
                                Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath()
            if kind == "check":
                path.moveTo(3.4, 6.2)
                path.lineTo(5.2, 8.0)
                path.lineTo(8.8, 4.2)
            else:                               # cross
                path.moveTo(4.0, 4.0)
                path.lineTo(8.0, 8.0)
                path.moveTo(8.0, 4.0)
                path.lineTo(4.0, 8.0)
            painter.drawPath(path)


class StatusBadge(QFrame):
    """Dot + LABEL + optional detail. The single status implementation.

    Used by: the run screen (every StageCard), Home's active-run card, History,
    the plan rows, and anywhere else a thing has a state. Before this there
    were four separate mechanisms and no two of them agreed on what "done"
    looked like.

    Everything it renders comes from theme.STATUS, so a state has one label,
    one ink, one tint and one dot everywhere it appears. The state name is
    forgiving — "Done", "done" and "completed" are the same row (theme.status)
    — because the engine, the run screen and History each grew their own
    spelling and no call site should have to know which.

    Two states you might expect are deliberately absent: `paused` and
    `waiting-for-user`. The engine cannot produce either — there is no pause
    primitive and no mid-run callback that can block on a human — so there is
    no badge for them. See theme.STATUS.

        StatusBadge("running", "Perplexity · 12s")
        badge.set_state("completed", "1m 40s")
    """

    def __init__(self, state: str = "idle", detail: str = "",
                 focusable: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("statusBadge")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setMinimumHeight(MIN_TARGET)
        # Reachable by keyboard and named for assistive tech. A timeline with
        # nine of these should pass focusable=False on all but the live one —
        # nine extra tab stops between the Back button and Stop is worse for a
        # keyboard user than no stop at all.
        self.setFocusPolicy(Qt.TabFocus if focusable else Qt.NoFocus)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_2 + 2, theme.SPACE_1,
                               theme.SPACE_3 - 1, theme.SPACE_1)
        row.setSpacing(theme.SPACE_2 - 1)
        self._dot = _StatusDot(state)
        row.addWidget(self._dot)
        self._label = QLabel()
        track(self._label, 0.06)
        row.addWidget(self._label)
        self._detail = QLabel()
        row.addWidget(self._detail)

        self._state = "idle"
        self.set_state(state, detail)

    def state(self) -> str:
        """The canonical STATUS key currently shown."""
        return self._state

    def set_state(self, state: str, detail: str = None):
        self._state = theme.status_key(state)
        text, ink, bg, _dot = theme.status(state)
        self._dot.set_state(state)
        family, px, weight, _ink = theme.T_LABEL
        self._label.setText(text)
        self._label.setStyleSheet(
            f"font-family: '{family}'; font-size: {px}px;"
            f" font-weight: {weight}; color: {ink}; background: transparent;")
        if detail is not None:
            self._detail.setText(detail)
        self._detail.setVisible(bool(self._detail.text()))
        self._detail.setStyleSheet(theme.type_css("META", theme.c(ink).name())
                                   + " background: transparent;")
        self.setStyleSheet(
            f"#statusBadge {{ background: {bg}; border: 2px solid {bg};"
            f" border-radius: {theme.R_PILL}px; }}"
            f"#statusBadge:focus {{ border-color: {ink}; }}")
        # What a screen reader says. The visual is a coloured dot; without
        # this, that is all it is.
        spoken = f"{text.title()}. {self._detail.text()}".strip()
        self.setAccessibleName(spoken)
        self.setToolTip(spoken)


# ── page scaffold ───────────────────────────────────────────────────────────
class PageHeader(QFrame):
    """The fixed band at the top of every screen: title, optional subtitle,
    optional actions on the right. Never scrolls.

    Used by: every screen. This is the top half of the page scaffold the
    redesign is built on — a header that stays put, then a scrolling content
    region with 28px padding underneath it. The screens that read as "a small
    card floating over a grey field" are the ones with no fixed header at all,
    so the whole page slides as one lump.

    `actions` is a list of already-built widgets, usually one primary button
    and one or two secondary ones. Exactly one primary per surface.
    """

    def __init__(self, title: str, subtitle: str = "", actions: list = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.PAGE_PAD, theme.SPACE_4,
                               theme.PAGE_PAD, theme.SPACE_4)
        row.setSpacing(theme.SPACE_4)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        self.title.setTextFormat(Qt.RichText)
        track(self.title, -0.015)
        col.addWidget(self.title)
        # Parented at creation: setVisible below runs before col.addWidget, and
        # setVisible(True) on a parentless widget flashes it as a top-level OS
        # window — the ghost-window flash. See SectionHeader for the full note.
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setTextFormat(Qt.RichText)
        # Wrapping, as in SectionHeader (see the note there). Without it the
        # label insists on its whole sentence as its minimum width, so at the
        # app's default width the subtitle was cut mid-word ("...not gue") and
        # the buttons beside it were squeezed ("Export shee"), on Inquiry,
        # Email, Gerber, STEP, BOM and Leads (seen in the real window).
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        row.addLayout(col, stretch=1)

        self.actions_row = QHBoxLayout()
        self.actions_row.setContentsMargins(0, 0, 0, 0)
        self.actions_row.setSpacing(theme.SPACE_2)
        row.addLayout(self.actions_row)
        for widget in actions or []:
            self.actions_row.addWidget(widget)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(self.rect())

        if not has_wallpaper(self):
            painter.setPen(QPen(QColor(theme.HAIRLINE), 1))
            painter.drawLine(QPointF(r.left(), r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
            return

        central = self.window().findChild(QWidget, "central")
        if central and hasattr(central, "get_blurred_pixmap"):
            blurred = central.get_blurred_pixmap()
            if blurred and not blurred.isNull():
                pos = central.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
                src_rect = QRect(pos.x(), pos.y(), int(r.width()), int(r.height()))
                painter.drawPixmap(r.toRect(), blurred, src_rect)

        # Translucent frosted white glass fill
        glass_grad = QLinearGradient(QPointF(r.left(), r.top()),
                                     QPointF(r.left(), r.bottom()))
        glass_grad.setColorAt(0.00, QColor(255, 255, 255, 215))
        glass_grad.setColorAt(1.00, QColor(255, 255, 255, 175))
        painter.setBrush(QBrush(glass_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRect(r)

        # Bottom subtle hairline divider & specular edge
        painter.setPen(QPen(QColor(0, 0, 0, 22), 1))
        painter.drawLine(QPointF(r.left(), r.bottom() - 0.5), QPointF(r.right(), r.bottom() - 0.5))
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawLine(QPointF(r.left(), r.bottom() - 1.5), QPointF(r.right(), r.bottom() - 1.5))

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget: QWidget):
        self.actions_row.addWidget(widget)


class SectionHeader(QWidget):
    """The standard band above a group of cards, inside the scrolling region.

    Used by: Home (each dashboard group), Settings (each section), AI tools
    (each category), History (each date group). One step down from PageHeader
    in every way — smaller type, no bottom rule, no page padding of its own,
    because it sits inside content that already has some.
    """

    def __init__(self, title: str, subtitle: str = "", actions: list = None,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("sectionHeader")
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(4, theme.SPACE_3, 4, theme.SPACE_1)
        row.setSpacing(theme.SPACE_3)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.title = QLabel(title)
        self.title.setObjectName("sectionTitle")
        track(self.title, -0.015)
        col.addWidget(self.title)
        # Parented to self at creation, NOT left parentless until col.addWidget
        # below: setVisible(True) a few lines down runs before that add, and
        # setVisible on a parentless widget promotes it to a top-level OS window
        # for an instant — the ghost-window flash (Windows even draws its native
        # shadow on it). A widget that already has a parent can never flash.
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("sectionSubtitle")
        # Wrapping, and not as a nicety. A non-wrapping QLabel reports its
        # whole sentence as its minimum width, so a two-clause subtitle pushes
        # the page wider than the viewport — and with the horizontal scrollbar
        # off, that silently clips whatever sits at the right edge of every row
        # below it (status pills, in the case that found this). Two screens had
        # already worked around it locally before it was fixed here.
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        row.addLayout(col, stretch=1)

        self.actions_row = QHBoxLayout()
        self.actions_row.setContentsMargins(0, 0, 0, 0)
        self.actions_row.setSpacing(theme.SPACE_2)
        row.addLayout(self.actions_row)
        for widget in actions or []:
            self.actions_row.addWidget(widget)

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget: QWidget):
        self.actions_row.addWidget(widget)


class Toolbar(QFrame):
    """A strip of search / filter / actions above a long list.

    Used by: History, AI tools, the inquiry register. A bare list with no
    toolbar is the thing that makes a hundred rows unusable — there is nowhere
    to put "find one" and nowhere to put "show me only the failed ones", so
    both end up not existing.

    Built as a card-shaped frame so it can be pinned above a scroll area and
    still read as part of the content rather than as chrome.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("toolbar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._rows = QVBoxLayout(self)
        self._rows.setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                                      theme.SPACE_3, theme.SPACE_2)
        self._rows.setSpacing(theme.SPACE_2)
        self._row = QHBoxLayout()
        self._row.setSpacing(theme.SPACE_2)
        self._rows.addLayout(self._row)

    def new_row(self):
        """Start a second line in the same strip: everything add()ed from
        here on goes under the first line. For a toolbar whose controls do
        not fit one line at the app's default width (the inquiry register:
        range, search, four chips and two buttons) — squeezing them into one
        line cut the search box to "Fin…"."""
        self._row = QHBoxLayout()
        self._row.setSpacing(theme.SPACE_2)
        self._rows.addLayout(self._row)

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        self._row.addWidget(widget, stretch)
        return widget

    def add_stretch(self, factor: int = 1):
        self._row.addStretch(factor)

    def add_separator(self):
        rule = QFrame()
        rule.setObjectName("cardLine")
        rule.setFixedWidth(1)
        rule.setFixedHeight(MIN_TARGET - 8)
        rule.setStyleSheet(f"background: {theme.HAIRLINE};")
        self._row.addWidget(rule)


class FlowLayout(QLayout):
    """A row of widgets that wraps onto the next line when it runs out of
    width, instead of clipping the ones on the right.

    Qt's own canonical example, kept because a QHBoxLayout has exactly one
    failure mode and it is the one the owner photographed: seven buttons in
    a row on a window narrower than seven buttons, and the last two simply
    gone. A flow layout has no such width; whatever does not fit steps down
    a line. Used for every action row in the Email inquiry automation window.
    """

    def __init__(self, parent=None, margin: int = 0,
                 h_space: int = theme.SPACE_2, v_space: int = theme.SPACE_2):
        super().__init__(parent)
        self._items: list = []
        self._h, self._v = h_space, v_space
        self.setContentsMargins(margin, margin, margin, margin)

    # -- QLayout contract --------------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), dry_run=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._arrange(rect, dry_run=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        left, top, right, bottom = self.getContentsMargins()
        return size + QSize(left + right, top + bottom)

    # -- the wrap --------------------------------------------------------
    def _arrange(self, rect: QRect, *, dry_run: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        inner = rect.adjusted(left, top, -right, -bottom)
        x, y = inner.x(), inner.y()
        line_height = 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisibleTo(widget.parentWidget()):
                continue                    # hidden buttons take no room
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h
            if next_x - self._h > inner.right() + 1 and line_height > 0:
                x = inner.x()
                y = y + line_height + self._v
                next_x = x + hint.width() + self._h
                line_height = 0
            if not dry_run:
                item.setGeometry(QRect(x, y, hint.width(), hint.height()))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + bottom


class PlainPasteTextEdit(QTextEdit):
    """A QTextEdit that pastes as plain text, always.

    Qt's default paste inserts the richest format the clipboard offers, and a
    terminal window — or any other dark, monospace editor — commonly puts an
    HTML copy on the clipboard next to the plain one, carrying its own font,
    background colour and whatever ANSI colour codes became inline styles.
    Pasted into one of Prism's free-text boxes that showed up as a font
    change mid-sentence, a coloured block, or a line break landing somewhere
    it never was in the source. Every box someone composes a task or a brief
    into should get back exactly the characters they copied, nothing else.
    """

    def insertFromMimeData(self, source):
        if source.hasText():
            self.insertPlainText(source.text())


class SubmitTextEdit(PlainPasteTextEdit):
    """The task composer: Enter sends it, like the button beside it does.

    A multi-line box swallows Enter as a new line, so the only way to go on
    was the mouse. Here Enter (the keypad one too, and Ctrl+Enter) emits
    `submitted`; Shift+Enter still breaks the line. An input method that is
    composing (Gujarati, Hindi) keeps its own Enter — Qt hands that to the
    method, not to keyPressEvent — so confirming a word never sends the task.
    """

    submitted = Signal()

    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not self.isReadOnly()      # the plan's recap lets Enter bubble
                and not (event.modifiers() & (Qt.ShiftModifier | Qt.AltModifier))):
            event.accept()
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class SearchField(QLineEdit):
    """The one search box. A capsule QLineEdit with a leading glyph and a
    clear button.

    Used by: History, AI tools, the inquiry register — everywhere a list can
    get long enough that scanning it stops working.

    Emits `changed` on every keystroke. It is a real QLineEdit, so it inherits
    the stylesheet's hover, focus and disabled states rather than reinventing
    them, and Escape clears it the way every search box on the machine does.
    """

    changed = Signal(str)

    def __init__(self, placeholder: str = "Search", parent=None):
        super().__init__(parent)
        self.setObjectName("searchField")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumHeight(MIN_TARGET + 4)
        self.setAccessibleName(placeholder)
        self.addAction(icons.icon("search", 16, theme.NEUTRAL[500]),
                       QLineEdit.LeadingPosition)
        self.textChanged.connect(self.changed.emit)
        self._name_the_clear_button()

    def _name_the_clear_button(self):
        """Give Qt's built-in clear button a name and a tab stop.

        setClearButtonEnabled() quietly inserts an 18px QToolButton with no
        accessible name and NoFocus. It was the last thing left in the app's
        click-target and unnamed-control audit, on three screens at once, and
        it is not ours to redraw — but it is ours to label. Named and
        focusable it stops being a mystery to a screen reader; the 18px hit
        area stays Qt's, which is why Escape also clears (see keyPressEvent)
        and is the route we actually document.

        There are TWO QToolButtons in here, not one: setClearButtonEnabled()
        makes the trailing X, and the leading search glyph is a QAction with a
        button of its own. Qt tags the real clear button's action
        `_q_qlineeditclearaction`, which is the only reliable way to tell them
        apart — naming by position or by order labelled the decorative glyph
        "Clear the search" too, so a screen reader announced a non-functional
        icon as an action.

        Bare literals rather than i18n.t(): this module deliberately does not
        import i18n (i18n patches Qt's own text methods, so importing it here
        would invert the dependency), and setToolTip is both patched at
        runtime and scanned by extract_strings — so the string is translated
        and catalogued anyway.
        """
        from PySide6.QtWidgets import QToolButton
        for btn in self.findChildren(QToolButton):
            action = btn.defaultAction()
            is_clear = (action is not None
                        and action.objectName() == "_q_qlineeditclearaction")
            if is_clear:
                btn.setToolTip("Clear the search")
                btn.setAccessibleName("Clear the search")
                btn.setFocusPolicy(Qt.TabFocus)
            else:
                # Decorative. Named honestly so it is not an anonymous button
                # to a screen reader, and kept out of the tab order because
                # there is nothing behind the click — a tab stop that does
                # nothing is worse than no tab stop.
                #
                # The property says that out loud. An accessibility sweep
                # cannot otherwise tell a deliberately inert glyph from a
                # control someone forgot to make reachable, and those two want
                # opposite fixes.
                btn.setAccessibleName("Search")
                btn.setFocusPolicy(Qt.NoFocus)
                btn.setProperty("decorative", True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        super().keyPressEvent(event)


class FilterChips(QWidget):
    """A row of exclusive filter chips — "All · Completed · Failed".

    Used by: History (filter runs by outcome), AI tools (filter by category).
    A chip row rather than a combo box on purpose: with six or fewer options
    the whole choice is visible at once and costs one click, and the current
    selection is readable without opening anything.

    `options` takes either plain strings, or (value, label) pairs when the
    value the code wants is not the words the user should read, or
    (value, label, count) when there is a real number to show. Never invent
    the count — pass None and it is simply not drawn.
    """

    changed = Signal(str)

    def __init__(self, options: list, current: str = "", parent=None):
        super().__init__(parent)
        # A FlowLayout, not a QHBoxLayout: AI tools feeds this eleven
        # categories, and a one-line row reports their whole width (742 px) as
        # its minimum, which forced the page's scroll content wider than the
        # viewport and clipped the right-hand column of cards at the app's
        # default width (seen in the real window, 1 Oct 2026). Chips now step
        # down a line instead.
        row = FlowLayout(self, margin=0, h_space=theme.SPACE_2 - 2,
                         v_space=theme.SPACE_2 - 2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        for option in options:
            if isinstance(option, (tuple, list)):
                value, text = option[0], option[1]
                count = option[2] if len(option) > 2 else None
            else:
                value = text = option
                count = None
            btn = QPushButton(f"{text}  {count}" if count is not None else text)
            btn.setObjectName("chipBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(MIN_TARGET)
            btn.setAccessibleName(text)
            btn.clicked.connect(lambda _=False, v=value: self._pick(v))
            self._group.addButton(btn)
            row.addWidget(btn)
            self._buttons[value] = btn

        self._current = ""
        first = current or (next(iter(self._buttons), ""))
        if first:
            self.set_current(first)

    def current(self) -> str:
        return self._current

    def set_current(self, value: str):
        btn = self._buttons.get(value)
        if btn is None:
            return
        self._current = value
        btn.setChecked(True)

    def _pick(self, value: str):
        if value != self._current:
            self._current = value
            self.changed.emit(value)


class EmptyState(QWidget):
    """Icon pad, title, one line of body, optional primary button — CENTRED in
    the full height it is given.

    Used by: Settings, the BOQ / Gerber / Email front doors, AI tools, History,
    the plan stub on the workbench. Six screens, and the centring is the point
    of all six.

    Those screens measured 45-70% empty grey. The mechanical cause was always
    the same: a small card top-anchored inside a scroll area with a trailing
    addStretch(), so every pixel of leftover window height piled up in one
    contiguous band underneath it. This widget has an expanding size policy and
    a stretch above AND below its content, so handed that same slack it sits in
    the middle of it instead of on top of it — which is the difference between
    a screen that is quiet and a screen that looks broken.

    Put it in the layout with a stretch factor and nothing after it:

        layout.addWidget(EmptyState("inbox", "No runs yet",
                                    "Runs you start will be listed here.",
                                    "Start a task"), stretch=1)

    Never pad the body out to look fuller. If a surface is thin the answer is
    more of what is real, not more words.
    """

    clicked = Signal()

    def __init__(self, icon: str = "inbox", title: str = "",
                 body: str = "", action_text: str = None, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.card = Card(radius=18)
        self.card.setMinimumHeight(160)
        outer = self.card.body((theme.SPACE_5, theme.SPACE_5,
                                theme.SPACE_5, theme.SPACE_5), spacing=0)
        outer.addStretch(1)

        self.content_layout = col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.setAlignment(Qt.AlignHCenter)

        self.pad = IconPad(icon, theme.ACCENT, 56, theme.R_CARD, 26)
        pad_row = QHBoxLayout()
        pad_row.setContentsMargins(0, 0, 0, 0)
        pad_row.addStretch(1)
        pad_row.addWidget(self.pad)
        pad_row.addStretch(1)
        col.addLayout(pad_row)

        self.title = QLabel(title)
        self.title.setObjectName("emptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        track(self.title, -0.015)
        col.addWidget(self.title)

        # Parented at creation: setVisible(bool(body)) below runs before this
        # label is put in a layout, and setVisible on a parentless widget flashes
        # it as a top-level OS window (the ghost-window flash). See SectionHeader.
        self.body = QLabel(body, self)
        self.body.setObjectName("emptyBody")
        self.body.setAlignment(Qt.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setMaximumWidth(460)
        self.body.setVisible(bool(body))
        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.addStretch(1)
        body_row.addWidget(self.body)
        body_row.addStretch(1)
        col.addLayout(body_row)

        self.action = None
        if action_text:
            self.action = button(action_text, "primary")
            self.action.clicked.connect(self.clicked.emit)
            act_row = QHBoxLayout()
            act_row.setContentsMargins(0, theme.SPACE_1, 0, 0)
            act_row.addStretch(1)
            act_row.addWidget(self.action)
            act_row.addStretch(1)
            col.addLayout(act_row)

        outer.addLayout(col)
        outer.addStretch(1)
        root.addWidget(self.card)

    def set_text(self, title: str = None, body: str = None):
        if title is not None:
            self.title.setText(title)
        if body is not None:
            self.body.setText(body)
            self.body.setVisible(bool(body))


# ── list and grid items ─────────────────────────────────────────────────────
class MetricCard(Card):
    """A number with a name under it, and optionally a trend and an icon.

    Used by: Home's dashboard row, the inquiry register summary, the run
    summary strip. A Card subclass rather than a seventh card recipe.

    `value` is a string on purpose — the caller has already formatted it as
    "₹8.4L" or "58%" or "12", and this must not guess. Pass `trend` only when
    a real series exists; a sparkline drawn from invented numbers is worse than
    no sparkline, because it looks like data.
    """

    def __init__(self, label_text: str, value: str, detail: str = "",
                 icon: str = "", trend: list = None, hue: str = None,
                 parent=None):
        super().__init__(parent=parent)
        hue = hue or theme.ACCENT
        col = self.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        self.kicker = kicker(label_text)
        top.addWidget(self.kicker, stretch=1)
        if icon:
            top.addWidget(IconPad(icon, hue, 30, theme.R_CONTROL, 15))
        col.addLayout(top)

        self.value = QLabel(value)
        self.value.setObjectName("stat")
        track(self.value, -0.02)
        col.addWidget(self.value)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(theme.SPACE_2)
        self.detail = QLabel(detail, self)
        self.detail.setObjectName("meta")
        self.detail.setVisible(bool(detail))
        bottom.addWidget(self.detail, stretch=1)
        self.spark = None
        if trend:
            self.spark = Sparkline(trend, hue)
            bottom.addWidget(self.spark)
        col.addLayout(bottom)

    def set_value(self, value: str, detail: str = None):
        self.value.setText(value)
        if detail is not None:
            self.detail.setText(detail)
            self.detail.setVisible(bool(detail))


class FileItem(QFrame):
    """One attachment or one produced file: glyph, name, size/kind, actions.

    Used by: the context rail's attachment list, the run screen's local-result
    cards, BOQ and Gerber output. Every one of those grew its own row; this is
    the shared one.

    The name elides from the middle rather than the end, because a path's last
    twenty characters are the part that identifies it and a run of files from
    the same folder is identical for the first forty.
    """

    activated = Signal()

    def __init__(self, name: str, detail: str = "", icon: str = "file",
                 actions: list = None, parent=None, leading: QWidget = None):
        super().__init__(parent)
        self.setObjectName("listRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(MIN_TARGET + 14)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_2,
                               theme.SPACE_2, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)
        # `leading` lets a caller show the file's own content (e.g. a real
        # image thumbnail) instead of a generic glyph — everything else about
        # the row stays identical, so Artifacts can look like a gallery
        # without becoming a second, divergent row implementation.
        row.addWidget(leading or IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15))

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._name = name
        self.name = QLabel(name)
        self.name.setStyleSheet(theme.type_css("SUPPORT", theme.TEXT))
        self.name.setToolTip(name)
        col.addWidget(self.name)
        self.detail = QLabel(detail, self)
        self.detail.setObjectName("meta")
        self.detail.setVisible(bool(detail))
        col.addWidget(self.detail)
        row.addLayout(col, stretch=1)

        for widget in actions or []:
            row.addWidget(widget)

        self.setAccessibleName(f"{name}. {detail}".strip())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        metrics = QFontMetrics(self.name.font())
        self.name.setText(metrics.elidedText(
            self._name, Qt.ElideMiddle, max(60, self.name.width())))

    def mouseDoubleClickEvent(self, event):
        self.activated.emit()
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class StepRow(QFrame):
    """One step in a plan or a run: marker, title, support line, status.

    Used by: the plan screen (one per stage), the run screen's queued steps,
    the guide's checklist. The status half is a StatusBadge, so a step and its
    card and its History entry all say "running" the same way.

    `trailing` takes an already-built widget — a ToolChip on the plan screen, a
    duration on the run screen — because what belongs at the end of the row is
    the one thing that genuinely differs between the three uses.
    """

    clicked = Signal()

    def __init__(self, index: int, title: str, subtitle: str = "",
                 state: str = "idle", trailing: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("listRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumHeight(MIN_TARGET + 20)
        self.setFocusPolicy(Qt.TabFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_3, theme.SPACE_3,
                               theme.SPACE_3, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)

        self.number = QLabel(f"{index:02d}")
        self.number.setFixedWidth(24)
        self.number.setAlignment(Qt.AlignCenter)
        self.number.setStyleSheet(
            f"font-family: '{theme.FONT_HEADING}'; font-size: 15px;"
            f" font-weight: 600; color: {theme.NEUTRAL_350};")
        row.addWidget(self.number)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        self.title = QLabel(title)
        self.title.setStyleSheet(theme.type_css("CARD_TITLE"))
        col.addWidget(self.title)
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("meta")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        row.addLayout(col, stretch=1)

        if trailing is not None:
            row.addWidget(trailing)
        self.badge = StatusBadge(state, focusable=False)
        row.addWidget(self.badge)
        self.setAccessibleName(f"Step {index}. {title}")

    def set_state(self, state: str, detail: str = None):
        self.badge.set_state(state, detail)
        self.setAccessibleName(
            f"Step {self.number.text()}. {self.title.text()}. "
            f"{self.badge.accessibleName()}")

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class Tabs(QFrame):
    """The segmented strip: two to five mutually exclusive views of one thing.

    Used by: the inquiry register, Settings' sections, the guide. Tabs, not a
    combo box, because the alternatives are worth seeing; a combo box hides
    them and costs a click to remember they exist.

    Emits `changed(index)`. Left/Right arrows move between tabs, which is what
    a keyboard user expects of a segmented control and what a plain row of
    buttons does not do.
    """

    changed = Signal(int)

    def __init__(self, options: list, current: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("tabStrip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_1, theme.SPACE_1,
                               theme.SPACE_1, theme.SPACE_1)
        row.setSpacing(theme.SPACE_1)
        self._buttons: list[QPushButton] = []
        for i, text in enumerate(options):
            btn = QPushButton(text)
            btn.setObjectName("tabBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(MIN_TARGET)
            btn.clicked.connect(lambda _=False, n=i: self.set_current(n))
            row.addWidget(btn)
            self._buttons.append(btn)
        self._current = -1
        self.set_current(current)

    def current(self) -> int:
        return self._current

    def set_current(self, index: int):
        if not self._buttons:
            return
        index = max(0, min(index, len(self._buttons) - 1))
        for i, btn in enumerate(self._buttons):
            on = i == index
            btn.setChecked(on)
            btn.setProperty("cur", "true" if on else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index != self._current:
            self._current = index
            self.changed.emit(index)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Left:
            self.set_current(self._current - 1)
            self._buttons[self._current].setFocus()
            return
        if event.key() == Qt.Key_Right:
            self.set_current(self._current + 1)
            self._buttons[self._current].setFocus()
            return
        super().keyPressEvent(event)


class CardGrid(QWidget):
    """A responsive card grid. Reflows by COLUMN COUNT and fills the width.

    Used by: Home, AI tools, Settings, the add-on front doors, History's
    grouped view — six screens, all of which currently lay cards out at a fixed
    width and leave a 400px dead gutter down the right-hand side at 1440px.

    That gutter is half the wasted-space problem. A fixed-width card in a
    variable-width window can only ever be right at one window size; this
    computes how many columns of at least `min_col_width` fit, gives every one
    of them an equal stretch, and lets the cards take the remainder. So the
    content reaches both edges at any width, and reflows to fewer, wider
    columns as the window narrows rather than clipping or scrolling sideways.

        grid = CardGrid(min_col_width=280)
        for tool in tools:
            grid.add(ToolCard(tool))

    Items keep their insertion order across a reflow, which matters because a
    grid that reshuffles when you resize the window looks like a bug.
    """

    def __init__(self, min_col_width: int = 280, gap: int = theme.CARD_GAP,
                 max_columns: int = 0, parent=None):
        super().__init__(parent)
        self._min = max(80, int(min_col_width))
        self._gap = int(gap)
        self._max_columns = int(max_columns)
        self._items: list[QWidget] = []
        self._cols = 0
        self._laying = False
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(self._gap)
        self._grid.setVerticalSpacing(self._gap)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    # -- contents ---------------------------------------------------------
    def add(self, widget: QWidget) -> QWidget:
        self._items.append(widget)
        widget.setParent(self)
        self._relayout(force=True)
        return widget

    def add_all(self, widgets: list):
        for widget in widgets:
            self._items.append(widget)
            widget.setParent(self)
        self._relayout(force=True)

    def count(self) -> int:
        return len(self._items)

    def clear(self):
        for widget in self._items:
            self._grid.removeWidget(widget)
            widget.hide()   # before setParent(None): avoids ghost-window flash
            widget.setParent(None)
            widget.deleteLater()
        self._items = []
        self._cols = 0

    # -- layout -----------------------------------------------------------
    def columns(self) -> int:
        """How many columns fit right now. Public so a caller can decide to
        render four compact cards instead of two wide ones."""
        return max(1, self._cols)

    def _columns_for(self, width: int) -> int:
        if width <= 0:
            return 1
        fit = (width + self._gap) // (self._min + self._gap)
        fit = max(1, min(int(fit), len(self._items) or 1))
        if self._max_columns:
            fit = min(fit, self._max_columns)
        return fit

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self, force: bool = False):
        # Re-entrancy guard: adding to a QGridLayout triggers a relayout, which
        # can trigger a resizeEvent, which lands back here.
        if self._laying:
            return
        cols = self._columns_for(self.width())
        if cols == self._cols and not force:
            return
        self._laying = True
        try:
            for widget in self._items:
                self._grid.removeWidget(widget)
            for index, widget in enumerate(self._items):
                self._grid.addWidget(widget, index // cols, index % cols)
            # Equal stretch on the live columns and none on any column left
            # over from a wider layout, which is what makes the row fill the
            # width instead of hugging the left edge.
            for column in range(max(cols, self._grid.columnCount())):
                self._grid.setColumnStretch(column, 1 if column < cols else 0)
            self._cols = cols
        finally:
            self._laying = False


# ── Toast notifications ──────────────────────────────────────────────────
class Toast(QFrame):
    """A floating, high-contrast notification pill/card that floats above a window.

    Dismisses automatically after `duration` ms (default 4000ms), or when the user
    clicks the close button or the toast itself.
    """

    def __init__(self, parent: QWidget | None, title: str, body: str = "",
                 tone: str = "ok", duration: int = 4000, position: str = "bottom",
                 on_click=None):
        top = parent.window() if (parent and hasattr(parent, "window")) else parent
        self._top = top
        self._position = position
        self._on_click = on_click
        super().__init__(top)
        self.setObjectName("toastNotification")
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 85))
        shadow.setOffset(0, 6)
        self.setGraphicsEffect(shadow)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 16, 12)
        layout.setSpacing(14)

        # Icon badge
        badge = QLabel()
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignCenter)
        if tone == "ok":
            badge.setStyleSheet("background: #186b53; border-radius: 14px;")
            badge.setPixmap(icons.pixmap("check", 15, "#ffffff", stroke=2.0))
        elif tone in ("err", "error"):
            badge.setStyleSheet("background: #8a2f2f; border-radius: 14px;")
            badge.setPixmap(icons.pixmap("x", 13, "#ffffff", stroke=2.0))
        elif tone in ("warn", "warning"):
            badge.setStyleSheet("background: #755a14; border-radius: 14px;")
            badge.setPixmap(icons.pixmap("alert", 15, "#ffffff", stroke=2.0))
        else:
            badge.setStyleSheet("background: #27272a; border-radius: 14px;")
            badge.setPixmap(icons.pixmap("help", 15, "#ffffff", stroke=2.0))
        layout.addWidget(badge)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet(
            "color: #ffffff; font-family: 'Barlow', 'Inter', sans-serif; "
            "font-size: 14px; font-weight: 600; background: transparent;")
        text_col.addWidget(self.title_lbl)

        if body:
            self.body_lbl = QLabel(body)
            self.body_lbl.setStyleSheet(
                "color: #a1a1aa; font-family: 'Barlow', 'Inter', sans-serif; "
                "font-size: 12px; font-weight: 400; background: transparent;")
            text_col.addWidget(self.body_lbl)

        layout.addLayout(text_col, stretch=1)

        close_btn = QPushButton()
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setFixedSize(24, 24)
        icons.button_icon(close_btn, "x", 12, "#71717a")
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 12px; min-height: 24px; min-width: 24px; padding: 0; } "
            "QPushButton:hover { background: rgba(255, 255, 255, 0.15); }")
        close_btn.clicked.connect(self.dismiss)
        layout.addWidget(close_btn)

        self.setStyleSheet(
            "QFrame#toastNotification { "
            "background: #09090b; "
            "border: 1px solid rgba(255, 255, 255, 0.16); "
            "border-radius: 12px; "
            "}")

        self.setMinimumWidth(380)
        self.adjustSize()
        self._reposition(animate=False)

        if self._top:
            self._top.installEventFilter(self)

        self._dismissed = False
        self._timer = None
        if duration > 0:
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.dismiss)
            self._timer.start(duration)

    def mousePressEvent(self, event):
        if self._on_click:
            self._on_click()
        super().mousePressEvent(event)

    def closeEvent(self, event):
        self._dismissed = True
        if self._timer:
            try:
                self._timer.stop()
            except Exception:
                pass
        top = getattr(self, "_top", None)
        if top:
            try:
                import shiboken6
                if shiboken6.isValid(top):
                    top.removeEventFilter(self)
            except Exception:
                pass
        super().closeEvent(event)

    def eventFilter(self, watched, event):
        try:
            import shiboken6
            if not shiboken6.isValid(self):
                return False
            top = getattr(self, "_top", None)
            if top and shiboken6.isValid(top) and watched == top and event.type() in (QEvent.Resize, QEvent.Move):
                self._reposition(animate=False)
        except Exception:
            return False
        return super().eventFilter(watched, event)

    def _reposition(self, animate: bool = True):
        try:
            import shiboken6
            if not shiboken6.isValid(self):
                return
            top = getattr(self, "_top", None)
            if not top or not shiboken6.isValid(top):
                return
            top_w = top.width()
            top_h = top.height()
            w = max(self.width(), self.sizeHint().width(), 380)
            h = max(self.height(), self.sizeHint().height())
            x = (top_w - w) // 2
            if self._position == "top":
                y = 28
            else:
                y = top_h - h - 32

            if animate:
                start_y = y + 16 if self._position == "bottom" else y - 16
                self.setGeometry(x, start_y, w, h)
                self._anim = QPropertyAnimation(self, b"pos", self)
                self._anim.setDuration(220)
                self._anim.setStartValue(QPoint(x, start_y))
                self._anim.setEndValue(QPoint(x, y))
                self._anim.setEasingCurve(QEasingCurve.OutCubic)
                self._anim.start()
            else:
                self.setGeometry(x, y, w, h)
            self.raise_()
        except Exception:
            pass

    def dismiss(self):
        try:
            import shiboken6
            if not shiboken6.isValid(self):
                return
        except Exception:
            pass
        if getattr(self, "_dismissed", False):
            return
        self._dismissed = True
        if getattr(self, "_timer", None):
            try:
                self._timer.stop()
            except Exception:
                pass
        try:
            top = getattr(self, "_top", None)
            if top:
                try:
                    import shiboken6
                    if shiboken6.isValid(top):
                        top.removeEventFilter(self)
                except Exception:
                    pass
            if hasattr(self, "_anim") and self._anim:
                try:
                    self._anim.stop()
                except Exception:
                    pass
            self._anim_out = QPropertyAnimation(self, b"pos", self)
            self._anim_out.setDuration(160)
            self._anim_out.setStartValue(self.pos())
            out_y = self.y() + 16 if self._position == "bottom" else self.y() - 16
            self._anim_out.setEndValue(QPoint(self.x(), out_y))
            self._anim_out.setEasingCurve(QEasingCurve.InCubic)
            self._anim_out.finished.connect(self.close)
            self._anim_out.start()
        except Exception:
            try:
                self.close()
            except Exception:
                pass


def show_toast(parent: QWidget | None, title: str, body: str = "",
               tone: str = "ok", duration: int = 4000, position: str = "bottom",
               on_click=None) -> Toast | None:
    """Show a modern, floating toast notification on `parent` (or active window)."""
    try:
        top = None
        if parent is not None:
            try:
                import shiboken6
                if not shiboken6.isValid(parent):
                    return None
            except Exception:
                pass
            top = parent.window() if hasattr(parent, "window") else parent
        if top is None:
            from PySide6.QtWidgets import QApplication
            top = QApplication.activeWindow()
        if not top:
            return None
        toast = Toast(top, title=title, body=body, tone=tone, duration=duration,
                      position=position, on_click=on_click)
        toast.show()
        return toast
    except Exception:
        return None


# ── Animated Wave Dots Loader ─────────────────────────────────────────────
class WaveDots(QWidget):
    """Animated waving dots loader matching Framer Motion's WaveDots.

    5 circular dots that oscillate up and down with a sinusoidal wave and
    phase offset (delay = i * 0.15s, cycle = 1.0s, amplitude = ±3.5px).
    Automatically pauses animation when hidden to consume 0% idle CPU.
    """

    def __init__(self, parent: QWidget | None = None, dot_size: int = 6,
                 dot_count: int = 5, spacing: int = 5, color: str | None = None):
        super().__init__(parent)
        self._dot_size = dot_size
        self._dot_count = dot_count
        self._spacing = spacing
        self._custom_color = color
        self._amplitude = 3.5
        self._duration = 1.0
        self._delay_step = 0.15
        self._time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._on_tick)

        total_w = dot_count * dot_size + (dot_count - 1) * spacing
        total_h = 22
        self.setFixedSize(total_w, total_h)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:
        total_w = self._dot_count * self._dot_size + (self._dot_count - 1) * self._spacing
        return QSize(total_w, 22)

    def showEvent(self, event):
        super().showEvent(event)
        self._time = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()

    def start(self):
        self._time = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self.hide()

    def _on_tick(self):
        self._time += 0.016
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        c = QColor(self._custom_color) if self._custom_color else theme.c(theme.NEUTRAL[800])
        painter.setBrush(QBrush(c))

        center_y = self.height() / 2.0
        r = self._dot_size / 2.0

        for i in range(self._dot_count):
            t = (self._time - i * self._delay_step) % self._duration
            phase = (2.0 * math.pi * t) / self._duration
            y_off = -self._amplitude * math.cos(phase)
            cx = i * (self._dot_size + self._spacing) + r
            painter.drawEllipse(QRectF(cx - r, center_y + y_off - r, self._dot_size, self._dot_size))
        painter.end()


class WaveDotsProgress(QProgressBar):
    """QProgressBar drop-in replacement that paints animated WaveDots.

    Compatible with existing progress bar API (setVisible, isVisible, setRange,
    setValue, etc.) while rendering a modern, sleek 5-dot wave animation
    instead of an obsolete rectangular bar.
    """

    def __init__(self, parent: QWidget | None = None, dot_size: int = 6,
                 dot_count: int = 5, spacing: int = 5, color: str | None = None):
        super().__init__(parent)
        self._dot_size = dot_size
        self._dot_count = dot_count
        self._spacing = spacing
        self._custom_color = color
        self._amplitude = 3.5
        self._duration = 1.0
        self._delay_step = 0.15
        self._time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

        total_w = dot_count * dot_size + (dot_count - 1) * spacing
        total_h = 22
        self.setFixedSize(total_w, total_h)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setTextVisible(False)
        self.setStyleSheet("background: transparent; border: none;")

    def sizeHint(self) -> QSize:
        total_w = self._dot_count * self._dot_size + (self._dot_count - 1) * self._spacing
        return QSize(total_w, 22)

    def showEvent(self, event):
        super().showEvent(event)
        self._time = 0.0
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._timer.isActive():
            self._timer.stop()

    def _on_tick(self):
        self._time += 0.016
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        c = QColor(self._custom_color) if self._custom_color else theme.c(theme.NEUTRAL[800])
        painter.setBrush(QBrush(c))

        center_y = self.height() / 2.0
        r = self._dot_size / 2.0

        for i in range(self._dot_count):
            t = (self._time - i * self._delay_step) % self._duration
            phase = (2.0 * math.pi * t) / self._duration
            y_off = -self._amplitude * math.cos(phase)
            cx = i * (self._dot_size + self._spacing) + r
            painter.drawEllipse(QRectF(cx - r, center_y + y_off - r, self._dot_size, self._dot_size))
        painter.end()


# ── Animated Voice Input Component ─────────────────────────────────────────

class VoiceFrequencyBars(QWidget):
    """12 animated frequency bars matching Framer Motion's VoiceInput frequency visualizer.

    When listening but not speaking:
      - Renders a clean, sleek, plain horizontal baseline line across the visualizer width.
      - Zero frantic jitter or unwanted bouncing.
    When speaking:
      - Dynamically animates the 12 rounded frequency bars oscillating up to 16px with speech harmonics.
    When speech pauses or ends:
      - Smoothly eases down back to the flat plain resting line.

    Supports:
      - set_speaking(bool)
      - set_audio_level(float 0.0..1.0)
      - Automatic conversational speech cadence when running in default demonstration mode.
      - Consumes 0% idle CPU when stopped.
    """

    def __init__(self, parent: QWidget | None = None, bar_count: int = 12,
                 bar_width: float = 2.5, spacing: float = 2.5, color: str | None = None):
        super().__init__(parent)
        self._bar_count = bar_count
        self._bar_width = bar_width
        self._spacing = spacing
        self._color = color or "#8a2f2f"
        self._time = 0.0

        self._is_speaking = False
        self._speech_level = 0.0          # 0.0 = completely flat plain line, 1.0 = full wave
        self._target_speech_level = 0.0
        self._cadence_mode = True         # Natural conversational cadence when active
        self._cadence_timer = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._on_tick)

        self._total_w = int(bar_count * bar_width + (bar_count - 1) * spacing)
        self.setFixedSize(self._total_w, 20)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def sizeHint(self) -> QSize:
        return QSize(self._total_w, 20)

    def start(self):
        self._time = 0.0
        self._cadence_timer = 0.0
        self._is_speaking = False
        self._speech_level = 0.0
        self._target_speech_level = 0.0
        if not self._timer.isActive():
            self._timer.start()
        self.show()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self._is_speaking = False
        self._speech_level = 0.0
        self._target_speech_level = 0.0
        self.hide()

    def set_speaking(self, speaking: bool):
        self._cadence_mode = False
        self._is_speaking = bool(speaking)
        self._target_speech_level = 1.0 if speaking else 0.0

    def set_audio_level(self, level: float):
        self._cadence_mode = False
        level = max(0.0, min(1.0, float(level)))
        self._is_speaking = level > 0.05
        self._target_speech_level = level

    def is_speaking(self) -> bool:
        return self._is_speaking

    def speech_level(self) -> float:
        return self._speech_level

    def _on_tick(self):
        self._time += 0.05

        # In automatic cadence mode, simulate natural conversational speech bursts and pauses
        if self._cadence_mode:
            self._cadence_timer += 0.016
            cycle = self._cadence_timer % 4.5
            # 0.0 - 0.8s: Initial silence/pause -> plain resting line
            # 0.8 - 3.2s: Speaking -> wave effect with natural phrasing modulation
            # 3.2 - 4.5s: Pause between sentences -> plain resting line
            if 0.8 <= cycle <= 3.2:
                self._is_speaking = True
                sub_cycle = math.sin((cycle - 0.8) * 4.0)
                self._target_speech_level = max(0.35, min(1.0, 0.75 + 0.25 * sub_cycle))
            else:
                self._is_speaking = False
                self._target_speech_level = 0.0

        # Natural attack and decay easing
        if self._target_speech_level > self._speech_level:
            # Fast attack (0.22) when speech begins
            self._speech_level += (self._target_speech_level - self._speech_level) * 0.22
        else:
            # Smooth analog decay (0.12) when pausing / stopping speech
            self._speech_level += (self._target_speech_level - self._speech_level) * 0.12

        if abs(self._speech_level - self._target_speech_level) < 0.005:
            self._speech_level = self._target_speech_level

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        mid_y = self.height() / 2.0
        r = self._bar_width / 2.0

        # 1. Plain listening line (when silent / not speaking)
        # Fades smoothly as speech level rises
        plain_opacity = max(0.0, 1.0 - self._speech_level * 1.6)
        if plain_opacity > 0.01:
            line_color = QColor(self._color)
            line_color.setAlphaF(plain_opacity)
            painter.setBrush(QBrush(line_color))
            painter.drawRoundedRect(QRectF(0, mid_y - 1.0, self._total_w, 2.0), 1.0, 1.0)

        # 2. Dynamic frequency wave effect (emerges and animates when speaking)
        if self._speech_level > 0.01:
            bars_opacity = min(1.0, self._speech_level * 1.8)
            bar_color = QColor(self._color)
            bar_color.setAlphaF(bars_opacity)
            painter.setBrush(QBrush(bar_color))

            for i in range(self._bar_count):
                phase = self._time * 3.5 + i * 0.48
                wave = 3.0 + 5.0 * math.sin(phase) + 3.0 * math.sin(phase * 1.8 + 1.2) + 2.5 * math.cos(phase * 0.6)
                wave = max(0.0, min(14.0, abs(wave)))

                h = 2.0 + wave * self._speech_level
                h = max(2.0, min(16.0, h))

                x = i * (self._bar_width + self._spacing)
                y = mid_y - h / 2.0
                painter.drawRoundedRect(QRectF(x, y, self._bar_width, h), r, r)

        painter.end()


class VoiceInputButton(QPushButton):
    """Interactive Voice Input Button matching shadcn / Framer Motion VoiceInput.

    In idle state:
      - Standard secondary pill with mic glyph and "Speak" label (matching Add File/Folder).
    In active (listening) state:
      - Smooth horizontal expansion.
      - Displays animated rotating/pulsing recording glyph.
      - Displays plain listening line while silent, transitioning to animated 12 frequency wave bars while speaking.
      - Displays live running timer in MM:SS format.
      - Armed recording red tint.
    """

    def __init__(self, text: str = "Speak", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("micBtn")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(40)
        self.setMaximumHeight(40)

        self._listening = False
        self._time_sec = 0

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(14, 0, 14, 0)
        self._row.setSpacing(7)
        self._row.setAlignment(Qt.AlignCenter)

        # 1. Leading icon label
        self._icon_lbl = QLabel(self)
        self._icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._icon_lbl.setPixmap(icons.pixmap("mic", 15, theme.NEUTRAL[700]))
        self._row.addWidget(self._icon_lbl)

        # 2. Text label (for idle "Speak")
        self._text_lbl = QLabel(text, self)
        self._text_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._text_lbl.setStyleSheet(
            "font-family: 'Barlow'; font-size: 14px; font-weight: 600; color: #09090b;")
        self._row.addWidget(self._text_lbl)

        # 3. Frequency bars (12 wave bars with plain resting line)
        self._bars = VoiceFrequencyBars(self, bar_count=12, bar_width=2.5, spacing=2.5, color="#8a2f2f")
        self._bars.setVisible(False)
        self._row.addWidget(self._bars)

        # 4. Timer label (MM:SS)
        self._timer_lbl = QLabel("00:00", self)
        self._timer_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._timer_lbl.setStyleSheet(
            "font-family: 'Barlow'; font-size: 13px; font-weight: 600; color: #8a2f2f; min-width: 38px;")
        self._timer_lbl.setVisible(False)
        self._row.addWidget(self._timer_lbl)

        # Rotation/pulse timer for listening indicator
        self._rot_angle = 0
        self._rot_timer = QTimer(self)
        self._rot_timer.setInterval(40)
        self._rot_timer.timeout.connect(self._on_rot_tick)

        # 1-second elapsed timer
        self._second_timer = QTimer(self)
        self._second_timer.setInterval(1000)
        self._second_timer.timeout.connect(self._on_second_tick)

    def sizeHint(self) -> QSize:
        if self._listening:
            return QSize(162, 40)
        return QSize(96, 40)

    def text(self) -> str:
        return "Stop" if self._listening else self._text_lbl.text()

    def setText(self, text: str):
        self._text_lbl.setText(text)

    def isChecked(self) -> bool:
        return self._listening

    def setChecked(self, on: bool):
        self.set_recording(on)

    def set_speaking(self, speaking: bool):
        self._bars.set_speaking(speaking)

    def set_audio_level(self, level: float):
        self._bars.set_audio_level(level)

    def is_speaking(self) -> bool:
        return self._bars.is_speaking()

    def set_recording(self, on: bool):
        if self._listening == on:
            return
        self._listening = on
        super().setChecked(on)

        if on:
            self._time_sec = 0
            self._timer_lbl.setText("00:00")
            self._text_lbl.setVisible(False)
            self._bars.start()
            self._timer_lbl.setVisible(True)
            self._second_timer.start()
            self._rot_angle = 0
            self._rot_timer.start()
            self._update_recording_icon()
            self.setStyleSheet("""
                #micBtn {
                    background: #fdeeee;
                    border: 1px solid #eecccc;
                    border-radius: 8px;
                    min-height: 28px;
                }
                #micBtn:hover {
                    background: #fbdada;
                    border-color: #e4b8b8;
                }
            """)
        else:
            self._rot_timer.stop()
            self._second_timer.stop()
            self._bars.stop()
            self._timer_lbl.setVisible(False)
            self._text_lbl.setVisible(True)
            self._icon_lbl.setPixmap(icons.pixmap("mic", 15, theme.NEUTRAL[700]))
            self.setStyleSheet("")

        self.updateGeometry()
        if self.parentWidget() and self.parentWidget().layout():
            self.parentWidget().layout().activate()

    def _on_rot_tick(self):
        self._rot_angle = (self._rot_angle + 12) % 360
        self._update_recording_icon()

    def _update_recording_icon(self):
        size = 16
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.translate(size / 2.0, size / 2.0)
        p.rotate(self._rot_angle)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#8a2f2f")))
        p.drawRoundedRect(QRectF(-4.5, -4.5, 9, 9), 2, 2)
        p.end()
        self._icon_lbl.setPixmap(pix)

    def _on_second_tick(self):
        self._time_sec += 1
        mins = self._time_sec // 60
        secs = self._time_sec % 60
        self._timer_lbl.setText(f"{mins:02d}:{secs:02d}")




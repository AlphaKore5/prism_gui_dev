"""Industry design-system tokens, in Python.

style.qss is the source of truth for anything QSS can express. This module
mirrors the same tokens for the parts Qt stylesheets *can't* reach — the
custom-painted widgets (blueprint registration marks, the toggle switch, the
tool chip badges) all need real QColor values, and they must land on exactly
the same palette as the stylesheet or the seams show.

Keep the two in sync: every constant here has a twin in style.qss.

Four scales live here, and between them they are meant to be the whole
vocabulary — a screen that reaches outside them is what makes an app stop
looking like one product:

    colour    the NEUTRAL and ACCENT ramps, six surface roles, four semantics
    type      eight levels (TYPE / T_*), nothing else
    spacing   SPACE_1..SPACE_7 on a 4px base, plus four page-layout constants
    radius    R_CHIP / R_CONTROL / R_CARD, plus the R_PILL special case

Nothing is ever removed from this module. Nine other files import from it, so
a retired token is aliased onto its replacement rather than deleted — see
R_HERO and R_MODAL, which are now both R_CARD."""
from __future__ import annotations
import os
from PySide6.QtGui import QColor, QFont, QFontDatabase

import paths

# ── tonal ramps (one shared lightness scale, so step N of any role matches) ──
# Declared first because nearly every surface and semantic token below is a
# step of one of these rather than a hand-picked hex. That is the whole reason
# the two ramps exist: a value that is "a step" can be reasoned about, and a
# value that is a one-off cannot.
NEUTRAL = {
    100: "#f5f5f7", 200: "#e5e5ea", 300: "#d1d1d6", 400: "#a1a1aa",
    500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
    900: "#111110",
}
ACCENT_RAMP = {
    100: "rgba(0, 0, 0, 0.04)", 200: "rgba(0, 0, 0, 0.07)", 300: "rgba(0, 0, 0, 0.12)", 400: "#a1a1aa",
    500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
    900: "#111110",
}

# ── core roles ──────────────────────────────────────────────────────────────
# AlphaKore brand (alphakore.org): the one source for the family look. Ink is
# the text and primary-button colour. Red is for brand marks only (the small
# label squares, the dot on a primary button) and is never a status colour.
STONE = "#EEEDEA"                    # warm canvas
INK = "#111110"
MUTE = "#6B6A65"                     # 4.5:1 on STONE and on white (the site's #8C8B86 fails)
BRAND_RED = "#C8161D"
BRAND_OK, BRAND_OK_BG = "#1F6B43", "#E4EFE7"
BRAND_ERR, BRAND_ERR_BG = "#A3141A", "#F7E3E1"

TEXT = INK
ACCENT = INK
ACCENT_2 = "#2A2A28"

# ── the six surfaces, one value each ────────────────────────────────────────
CANVAS = STONE                       # warm stone page
CARD = "#FFFFFF"                     # solid white card
WELL = "#F6F5F2"                     # inset well inside a card
HAIRLINE = "#E6E5E1"                 # hairline: card borders, row separators
DIVIDER = "#D8D7D2"                  # divider: the heavier rule between regions
BORDER = "#D8D7D2"                   # border: the drawn edge of a control
RAIL = "#FFFFFF"                     # sidebar card

# Retired duplicates, kept as names because other files import them.
BG = CANVAS
SURFACE = NEUTRAL[200]
CARD_LINE = HAIRLINE
NEUTRAL_350 = "#9ca3af"

import re


def apply_palette(app) -> None:
    """Make the whole application light, whatever the desktop is set to.

    Prism is light-only. main.py used to pin seven roles on a fresh QPalette and
    leave every other role to the platform, and Qt 6 follows the OS colour
    scheme. Measured on a GNOME desktop in dark mode (2 Oct 2026 review): the
    selection colour was the OS accent, placeholder text and the bevel roles
    (Mid/Dark/Light, which paint progress tracks and pill tints) came out dark,
    and the Disabled group was identical to the enabled one. Under a light OS
    theme the placeholder was pure black, indistinguishable from typed text.

    So: ask Qt for its light scheme first (Qt >= 6.8; a build without the call
    keeps the explicit roles below), then set every role the widgets read.
    Disabled text is the same grey the stylesheet gives disabled buttons.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPalette

    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)

    pal = QPalette()
    ink, paper, subtle = QColor(TEXT), QColor("#ffffff"), QColor(NEUTRAL[500])
    muted = QColor("#b7b7ba")
    roles = {
        QPalette.Window: paper, QPalette.WindowText: ink,
        QPalette.Base: paper, QPalette.AlternateBase: QColor("#f4f5f6"),
        QPalette.Text: ink, QPalette.Button: paper, QPalette.ButtonText: ink,
        QPalette.BrightText: paper, QPalette.PlaceholderText: subtle,
        QPalette.Highlight: QColor(ACCENT), QPalette.HighlightedText: paper,
        QPalette.Link: QColor(NEUTRAL[700]), QPalette.LinkVisited: QColor(NEUTRAL[600]),
        # the bevel roles: light ramp, darkest last
        QPalette.Light: paper, QPalette.Midlight: QColor("#ececee"),
        QPalette.Mid: QColor("#d4d4d8"), QPalette.Dark: QColor(NEUTRAL[400]),
        QPalette.Shadow: QColor(NEUTRAL[500]),
    }
    for role, colour in roles.items():
        pal.setColor(role, colour)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, muted)
    app.setPalette(pal)


def qcolor(val: str | QColor | tuple | list) -> QColor:
    """Safe conversion from CSS rgba/rgb/hex strings, tuples, or QColor to a valid QColor."""
    if isinstance(val, QColor):
        return val
    if not val:
        return QColor(0, 0, 0, 0)
    if isinstance(val, (tuple, list)):
        return QColor(*val)
    val_str = str(val).strip()
    m = re.match(r"rgba\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d\.]+)\s*\)", val_str)
    if m:
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = float(m.group(4))
        alpha = int(a * 255) if a <= 1.0 else int(a)
        return QColor(r, g, b, alpha)
    m = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", val_str)
    if m:
        return QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    c = QColor(val_str)
    if not c.isValid():
        return QColor(0, 0, 0, 0)
    return c


# ── semantic roles ──────────────────────────────────────────────────────────
OK = "#16a34a"
OK_INK = "#15803d"
OK_BG = "rgba(22, 163, 74, 0.14)"
WARN = "#ca8a04"
WARN_INK = "#a16207"
WARN_BG = "rgba(202, 138, 4, 0.14)"
ERR = "#dc2626"
ERR_INK = "#b91c1c"
ERR_BG = "rgba(220, 38, 38, 0.14)"
ERR_LINE = "rgba(220, 38, 38, 0.30)"

INFO = "#0284c7"
INFO_INK = "#0369a1"
INFO_BG = "rgba(2, 132, 199, 0.14)"

# ── the inquiry register's states ([12][15][17], owner's decision 13 Oct 2026)
# One colour per state, the same on every register tab, in the Excel copy
# and in its legend: yet to quote blue, quoted grey, no reply amber,
# negotiating orange, won green, lost red. Solid hexes, not rgba: the tint
# has to be the same colour on screen and in an .xlsx, and an rgba over a
# frosted card is not. None of these is an _ACCENT_HEXES entry, so a role's
# accent rotation never turns "yet to quote" into its own hue.
# Each state has a light and a dark pair (background, ink). The light set
# is a soft wash with the state's own dark ink, the look the register had
# before (13 Oct, round 3): the round-2 blue (#a9cdfc) was strong enough
# that every New row read as a picked row. A picked row is now a charcoal
# fill (_TintedCellDelegate), never a tint. Measured in
# tests/test_register_colours.py: in light every ink is at least 7:1 on its
# background, in dark at least 4.5:1 (white on a saturated orange tops out
# near 5:1); every two backgrounds are at least 10 apart in CIEDE2000 in
# light (pale washes; the inks differ too) and 15 in dark, where 2 to 3 is
# the "just noticeable" step. The grey is a warm grey so it stays clear of
# the pale blue.
REGISTER_STATES = ("new", "quoted", "no_reply", "negotiating", "won", "lost")
REGISTER_TONES = {
    "light": {
        "new":         ("#d9e8fe", "#1e3a8a"),   # blue
        "quoted":      ("#e7e5e4", "#44403c"),   # grey
        "no_reply":    ("#fdf0b5", "#713f12"),   # amber
        "negotiating": ("#ffdcbc", "#7c2d12"),   # orange
        "won":         ("#cff3da", "#14532d"),   # green
        "lost":        ("#fdd4d4", "#7f1d1d"),   # red
    },
    "dark": {
        "new":         ("#1e40af", "#eff6ff"),
        "quoted":      ("#52525b", "#fafafa"),
        "no_reply":    ("#7c5800", "#fefce8"),
        "negotiating": ("#c2410c", "#ffffff"),
        "won":         ("#166534", "#f0fdf4"),
        "lost":        ("#7f1d1d", "#fef2f2"),
    },
}


def is_dark_palette() -> bool:
    """Whether the running app paints dark. apply_palette() pins light today,
    so this is False in practice; it is here so the register's colours follow
    if that ever changes, instead of putting dark ink on a dark row."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        return bool(app) and app.palette().window().color().lightness() < 128
    except Exception:                                   # noqa: BLE001
        return False


def register_tones(dark: bool | None = None) -> dict:
    """{state: (background, ink)} for the light or the dark palette."""
    if dark is None:
        dark = is_dark_palette()
    return REGISTER_TONES["dark" if dark else "light"]


TAG_TONES = {
    "tagAccent": ("rgba(0, 0, 0, 0.06)", "#111110"),
    "tagOutline": ("rgba(255, 255, 255, 0.85)", "#111110"),
    "tagNeutral": ("rgba(0, 0, 0, 0.05)", "#27272a"),
    "tagOk": (OK_BG, OK_INK),
    "tagWarn": (WARN_BG, WARN_INK),
    "tagErr": (ERR_BG, ERR_INK),
}

# ── execution states ────────────────────────────────────────────────────────
STATUS = {
    "idle":         ("IDLE",         "#52525b", "rgba(0, 0, 0, 0.05)", "hollow"),
    "queued":       ("QUEUED",       "#52525b", "rgba(0, 0, 0, 0.05)", "hollow"),
    "planning":     ("PLANNING",     INFO_INK,  INFO_BG,               "pulse"),
    "running":      ("RUNNING",      INFO_INK,  INFO_BG,               "pulse"),
    "streaming":    ("STREAMING",    INFO_INK,  INFO_BG,               "pulse"),
    "waiting":      ("WAITING",      "#3f3f46", "rgba(0, 0, 0, 0.05)", "dashed"),
    "needs_review": ("NEEDS REVIEW", WARN_INK,  WARN_BG,               "solid"),
    "retrying":     ("RETRYING",     WARN_INK,  WARN_BG,               "spinner"),
    "completed":    ("COMPLETED",    OK_INK,    OK_BG,                 "check"),
    "failed":       ("FAILED",       ERR_INK,   ERR_BG,                "cross"),
    "cancelled":    ("CANCELLED",    "#71717a", "rgba(0, 0, 0, 0.05)", "square"),
    "skipped":      ("SKIPPED",      "#71717a", "rgba(0, 0, 0, 0.05)", "dash"),
}

# The words the engine and the existing panels already use for these states.
# Call sites should not have to translate: status("Done") and status("done")
# and status("completed") are the same row.
_STATUS_ALIASES = {
    "done": "completed", "complete": "completed", "ok": "completed",
    "success": "completed", "finished": "completed",
    "error": "failed", "failure": "failed", "err": "failed",
    "stopped": "cancelled", "aborted": "cancelled", "stopping": "cancelled",
    "pending": "queued", "not_started": "idle", "new": "idle",
    "routing": "planning", "thinking": "planning",
    "working": "running", "in_progress": "running", "active": "running",
    "blocked": "needs_review", "exhausted": "needs_review",
    "timed_out": "needs_review", "no_response": "needs_review",
    "review": "needs_review", "partial": "needs_review",
    "retry": "retrying", "failover": "retrying",
    "waiting_for_tool": "waiting",
}


def status(name: str) -> tuple[str, str, str, str]:
    """One STATUS row, tolerant of however the caller spells the state.

    The engine, the run screen and History each grew their own spelling of the
    same handful of states ("Done", "done", "completed"), which is how the app
    ended up with two different-looking success pills. Everything normalises
    through here instead: case, spaces and hyphens are all the same, unknown
    names fall back to idle rather than raising, and the caller never has to
    know which vocabulary produced the string.
    """
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _STATUS_ALIASES.get(key, key)
    return STATUS.get(key, STATUS["idle"])


def status_key(name: str) -> str:
    """The canonical STATUS key for a state name — see status()."""
    key = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = _STATUS_ALIASES.get(key, key)
    return key if key in STATUS else "idle"


# ── elevation ───────────────────────────────────────────────────────────────
# QSS has no box-shadow, so these are consumed by QGraphicsDropShadowEffect
# (see widgets.controls.elevate) rather than by the stylesheet. Kept as tokens
# anyway so the two cards that need a deeper shadow ask for it by name.
# (blur, y-offset, alpha) against ink #141e28.
#
# A hairline border is the default separator in this system and shadow is
# reserved for things that genuinely float — modals, dropdowns, a dragged row.
# A resting card in a grid gets no shadow: shadow on everything is what makes
# every element look like it is hovering, and it is also the reason
# shadows_enabled() defaults off.
SHADOW_INK = "#111110"
SHADOW_CARD = (26, 8, 0.08)     # resting card
SHADOW_RAISED = (48, 16, 0.12)  # hero card, modals
SHADOW_HOVER = (32, 10, 0.14)   # stat card under the cursor
SHADOW_ACCENT = (20, 8, 0.25)   # primary button glow, in monochrome tone

# ── radii ───────────────────────────────────────────────────────────────────
# Three values, not six. The census counted thirteen distinct radii painting
# against six declared tokens — R_MODAL was used nowhere at all, R_CHIP had
# zero Python call sites, and 10px was the second most common radius in the
# stylesheet with no name whatsoever. Three steps is enough to say "chip",
# "control" and "card", and a fourth step is indistinguishable at these sizes.
#
# R_HERO and R_MODAL are aliases rather than deletions: four files import them
# and this module never removes a name.
R_CHIP = 6                      # pills, chips, badges, step marks, menu items
R_CONTROL = 8                   # buttons, inputs, rows, small cards
R_CARD = 12                     # panels, cards, modals, dialogs
R_HERO = R_CARD                 # was 14 — a hero card is a card
R_MODAL = R_CARD                # was 16 — a modal is a card
R_PILL = 999                    # the special case: a true pill, any height
# Not a scale step: half the width of a 4-8px bar, i.e. the radius that makes a
# progress bar or a scrollbar handle a capsule. Reach for R_CHIP for anything
# with content inside it.
R_MICRO = 4

# ── spacing ─────────────────────────────────────────────────────────────────
# A 4px base, seven steps, nothing between them. The census found 37 distinct
# content-margin tuples and 20 distinct layout spacings across the panels —
# 8, 9, 10 and 11 all shipping side by side, which no eye can distinguish and
# no reader can justify.
SPACE_1 = 4                     # inside a chip; icon to its own label
SPACE_2 = 8                     # between two controls in a row
SPACE_3 = 12                    # between rows inside a card
SPACE_4 = 16                    # between cards
SPACE_5 = 20                    # inside a card, edge to content
SPACE_6 = 28                    # page padding
SPACE_7 = 40                    # between major regions of a page

# Golden Ratio (phi ≈ 1.618) & 8pt-Grid Spacing Matrix Tokens
SPACE_XXS = SPACE_1             # 4px - micro-spacing, badges, icon gaps
SPACE_XS = SPACE_2              # 8px - base unit, compact paddings
SPACE_SM = SPACE_3              # 12px - field vertical padding, tight gaps
SPACE_MD = SPACE_4              # 16px - standard card inner padding, dialog padding
SPACE_LG = 24                   # 24px - section gap (~16 * 1.5)
SPACE_XL = SPACE_7              # 40px - major container separation (~24 * 1.618)
SPACE_2XL = 64                  # 64px - page lateral gutters and top breathing margins

# Component Sizing Matrix Tokens
BTN_HEIGHT_SM = 28              # Small utility button
BTN_HEIGHT_MD = 34              # Standard / Secondary button
BTN_HEIGHT_LG = 40              # Primary / Hero button

RADIUS_SM = R_CHIP              # 6px - chips, pills, tags
RADIUS_MD = R_CONTROL           # 8px - buttons, inputs
RADIUS_LG = 10                  # 10px - standard cards
RADIUS_XL = R_CARD              # 12px - dialogs, modal panels

# The four page-layout constants every screen uses, named so a panel does not
# have to remember which SPACE step the scaffold called for.
PAGE_PAD = SPACE_6              # 28 — page edge to content, every screen
# Lumi's launcher is a small round button docked to the window's right edge,
# like Android's floating accessibility button (LumiEdgeButton in
# widgets/lumi_card.py). Its diameter comes from the font's line height, kept
# between these two, so it reads the same at 100 %, 150 % and on a retina Mac.
LUMI_BUTTON_MIN = 40
LUMI_BUTTON_MAX = 46
# Gap between the button and the window's right edge. With PAGE_PAD of 28 the
# button reaches at most LUMI_BUTTON_MAX + LUMI_EDGE_GAP - PAGE_PAD = 22 px into
# a page's content column, and only in its own short band; screens no longer
# reserve room for it.
LUMI_EDGE_GAP = SPACE_1
# Where it rests by default, measured from the window's bottom edge to the
# button's bottom: above a footer row (PAGE_PAD + a tall button + a gap), so
# Next, "Start the work" and the Leads bulk bar are never under it.
LUMI_REST_FROM_BOTTOM = PAGE_PAD + BTN_HEIGHT_LG + SPACE_4   # 84
LUMI_IDLE_OPACITY = 0.6         # resting; full opacity under the cursor or focus
# Width of the slim tab left on screen when the button is tucked away.
LUMI_TAB_W = 14
CARD_PAD = SPACE_5              # 20 — card edge to content
CARD_GAP = SPACE_4              # 16 — gutter between cards in a grid
ROW_GAP = SPACE_3               # 12 — between rows inside one card

# ── type ────────────────────────────────────────────────────────────────────
# AlphaKore family: Geist for text and headings, Geist Mono for labels and
# numbers, Doto (dot-matrix) for the display greeting and big numbers.
FONT_BODY = "Geist"
FONT_HEADING = "Geist"
FONT_DISPLAY = "Doto"
FONT_MONO = "Geist Mono"
FONT_MONO_STACK = '"Geist Mono", "JetBrains Mono", "DejaVu Sans Mono", "Menlo", "Consolas", monospace'
_FONT_DIR = paths.resource("assets", "fonts")

# Eight levels and nothing else.
#
# Twenty distinct font sizes shipped before this pass, nine of them inside a
# single 4px band — 11, 11.5, 12, 12.5, 13, 13.5, 14, 14.5, 15 — almost all
# introduced by ad hoc size= arguments rather than by any named role. Half a
# pixel of difference is not a decision anyone can see; it is only noise that
# stops the app reading as one system.
#
# Headings take their weight from condensation, not from size: Barlow
# Condensed at 600 reads as a heading at 15px, so nothing here is oversized.
# The old #h1 was 30px, which on a 900px-tall window was a sixth of the
# vertical budget spent on a greeting.
#
# Each entry is (family, pixel size, CSS weight, colour). Pixels, not points,
# because style.qss speaks pixels and the painted widgets have to land on the
# same metric — see font() below, which sets a pixel size on the QFont for
# exactly that reason. PT_ values are provided for the handful of call sites
# that already construct QFont(family, points).
TYPE = {
    # level          family         px  weight  colour
    "PAGE_TITLE": (FONT_HEADING,    26,   600,  "#111110"),
    "SECTION":    (FONT_HEADING,    20,   600,  "#111110"),
    "CARD_TITLE": (FONT_HEADING,    16,   600,  "#111110"),
    "BODY":       (FONT_BODY,       15,   400,  "#18181b"),
    "SUPPORT":    (FONT_BODY,       14,   400,  "#18181b"),
    "META":       (FONT_BODY,       13,   500,  "#3f3f46"),
    "LABEL":      (FONT_HEADING,    12,   600,  "#27272a"),
    "MONO":       (FONT_MONO,       13,   500,  "#18181b"),
}

# The same eight as flat constants, for `from theme import T_BODY`.
T_PAGE_TITLE = TYPE["PAGE_TITLE"]
T_SECTION = TYPE["SECTION"]
T_CARD_TITLE = TYPE["CARD_TITLE"]
T_BODY = TYPE["BODY"]
T_SUPPORT = TYPE["SUPPORT"]
T_META = TYPE["META"]
T_LABEL = TYPE["LABEL"]
T_MONO = TYPE["MONO"]

# Which qss object name each level owns. The stylesheet keeps every one of the
# old names working — six heading levels collapse onto three real sizes — so
# no panel has to be edited for the scale to take effect.
TYPE_ROLE = {
    "PAGE_TITLE": "h2",         # also h1, #stat
    "SECTION": "h4",            # also h3, #statSm
    "CARD_TITLE": "h6",         # also h5
    "BODY": "",                 # the global default
    "SUPPORT": "body",          # also #lead
    "META": "meta",             # also #dim, #faint
    "LABEL": "kick",            # also #colHead
    "MONO": "mono",
}

_WEIGHT_TO_QT = {300: QFont.Light, 400: QFont.Normal, 500: QFont.Medium,
                 600: QFont.DemiBold, 700: QFont.Bold}


def type_pt(level: str) -> float:
    """A level's size in points, for QFont(family, points) call sites.

    Qt's point size is resolved against the screen's DPI and the stylesheet's
    is not, so the two agree only at 96dpi. Prefer font() below, which sets a
    pixel size and therefore matches style.qss on every display.
    """
    return TYPE.get(level, T_BODY)[1] * 0.75


def font(level: str = "BODY", weight: int = 0) -> QFont:
    """The QFont for one type level, sized in pixels.

    Pixels rather than points on purpose. A painted widget that asked for
    "10pt" and a stylesheet rule that asked for "13px" agree on one machine and
    diverge on the next, and the seam shows as a heading one step off the label
    beside it — which is the whole failure this module exists to prevent.
    """
    family, px, css_weight, _colour = TYPE.get(level, T_BODY)
    out = QFont(family)
    out.setPixelSize(px)
    out.setWeight(_WEIGHT_TO_QT.get(weight or css_weight, QFont.Normal))
    return out


def type_css(level: str = "BODY", colour: str = "") -> str:
    """One type level as a QSS fragment, for the widgets that set their own
    stylesheet. Always use this rather than retyping a size — a bare
    `font-size: 12.5px` is how the twenty-size sprawl happened."""
    family, px, weight, ink = TYPE.get(level, T_BODY)
    stack = FONT_MONO_STACK if level == "MONO" else f"'{family}'"
    return (f"font-family: {stack}; font-size: {px}px; "
            f"font-weight: {weight}; color: {colour or ink};")


def load_fonts() -> None:
    """Register the vendored Geist, Geist Mono and Doto faces (plus the older
    Barlow files, still used by a few painted widgets). The system is built on the
    AlphaKore pairing — without it Qt silently falls back to a
    default sans and every heading loses its condensed proportions, so the
    fonts ship with the app rather than being assumed present on the box."""
    if not os.path.isdir(_FONT_DIR):
        return
    for name in sorted(os.listdir(_FONT_DIR)):
        if name.lower().endswith((".ttf", ".otf")):
            QFontDatabase.addApplicationFont(os.path.join(_FONT_DIR, name))


# ── per-role accent ─────────────────────────────────────────────────────────
# A company running Prism has one copy per person, and the fastest way to know
# whose copy you are looking at — or which profile a manager has switched into
# — is that the whole app is a different colour.
#
# Only the HUE moves. Every swatch keeps the lightness and saturation of the
# blue it replaces, so contrast against text and canvas is identical in every
# role and nothing has to be re-checked for legibility. That is why this
# generates the ramp instead of listing nine hand-picked palettes: nine
# palettes drift, and one of them ends up with grey-on-grey somewhere.
_BASE_ACCENT = dict(ACCENT_RAMP)
_BASE_ACCENT_KEYS = ("ACCENT", "ACCENT_2")

# Everything the stylesheet says in the accent hue. Rewritten at load time by
# role_stylesheet(); the keys are the shipped blues, the values are what they
# become. Kept as a list so a hex that appears in more than one role of the
# design (ACCENT and ramp 600 are close but distinct) each map correctly.
#
# THIS TUPLE IS THE CONTRACT. Any accent-coloured hex written into style.qss
# must be one of these eleven or it will not rotate, and one permanently blue
# button in an otherwise green copy is worse than no rotation at all. Equally,
# any hex that must NOT rotate — every neutral, every semantic, every tool
# brand colour — has to be distinct from all eleven. The INFO role added above
# is composed entirely of ramp steps for exactly this reason: it rotates and it
# needed no new entry here.
_ACCENT_HEXES = ("#4480bb", "#628fbb", "#eff6fe", "#d8ebfd", "#b6d9fc",
                 "#7ebcf9", "#5e9eda", "#457eb7", "#306191", "#1f456a",
                 "#142d46")


def _hex_to_hls(value: str) -> tuple[float, float, float]:
    import colorsys
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)


def _hls_to_hex(h: float, l: float, s: float) -> str:
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def recolour(value: str, hue: int) -> str:
    """One accent swatch, rotated to `hue`, keeping its lightness exactly."""
    _h, lightness, saturation = _hex_to_hls(value)
    return _hls_to_hex((hue % 360) / 360.0, lightness, saturation)


def role_palette(hue: int) -> dict[str, str]:
    """{shipped blue -> the role's version of it}, for every accent swatch."""
    return {value: recolour(value, hue) for value in _ACCENT_HEXES}


def apply_role(hue: int) -> None:
    """Keep theme monochrome and consistent across all roles."""
    global ACCENT, ACCENT_2, ACCENT_RAMP, RAIL
    global INFO, INFO_INK, INFO_BG, TAG_TONES, STATUS, _BADGE_CYCLE
    ACCENT = "#111110"
    ACCENT_2 = "#27272a"
    ACCENT_RAMP = {
        100: "rgba(0, 0, 0, 0.04)", 200: "rgba(0, 0, 0, 0.07)", 300: "rgba(0, 0, 0, 0.12)", 400: "#a1a1aa",
        500: "#71717a", 600: "#52525b", 700: "#3f3f46", 800: "#27272a",
        900: "#111110",
    }
    RAIL = "#ffffff"
    INFO = "#27272a"
    INFO_INK = "#111110"
    INFO_BG = "rgba(0, 0, 0, 0.04)"
    TAG_TONES = dict(TAG_TONES)
    TAG_TONES["tagAccent"] = ("rgba(0, 0, 0, 0.05)", "#111110")
    TAG_TONES["tagOutline"] = (CARD, "#111110")
    STATUS = dict(STATUS)
    for key in ("planning", "running", "streaming"):
        label, _ink, _bg, dot = STATUS[key]
        STATUS[key] = (label, INFO_INK, INFO_BG, dot)
    _BADGE_CYCLE = ["#18181b", "#27272a", "#3f3f46", "#52525b", "#71717a"]


def tone(name: str) -> str:
    """Resolve tone tokens in monochrome palette."""
    return {"accent": ACCENT, "ok": "#18181b", "warn": "#27272a",
            "muted": "#71717a"}.get(name, ACCENT)


def role_stylesheet(qss: str, hue: int) -> str:
    """Rewrite any blue or colored accent hexes in the stylesheet to monochrome water glass tokens."""
    if hue != 210:
        new_accent = recolour(ACCENT, hue)
        if new_accent != ACCENT:
            qss = qss.replace(ACCENT, new_accent)
    swaps = {
        "#4480bb": "#111110",
        "#628fbb": "#27272a",
        "#eff6fe": "rgba(0, 0, 0, 0.04)",
        "#d8ebfd": "rgba(0, 0, 0, 0.08)",
        "#b6d9fc": "rgba(0, 0, 0, 0.14)",
        "#7ebcf9": "#a1a1aa",
        "#5e9eda": "#71717a",
        "#457eb7": "#52525b",
        "#306191": "#27272a",
        "#1f456a": "#18181b",
        "#142d46": "#ffffff",
        "#f4f5f6": "#ffffff",
    }
    for original, replacement in swaps.items():
        qss = qss.replace(original, replacement)
        qss = qss.replace(original.upper(), replacement)
    return qss


def c(hex_or_role: str, alpha: float = 1.0) -> QColor:
    """QColor from a token, optionally at partial alpha."""
    col = qcolor(hex_or_role)
    if alpha < 1.0:
        col.setAlphaF(col.alphaF() * alpha)
    return col


def contrast(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two opaque hexes."""
    def channel(value: str) -> float:
        value = value.lstrip("#")
        out = []
        for i in (0, 2, 4):
            v = int(value[i:i + 2], 16) / 255
            out.append(v / 12.92 if v <= 0.03928
                       else ((v + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]

    a, b = channel(fg), channel(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


_TOOL_BADGES = {
    "perplexity": "#18181b",
    "chatgpt": "#18181b",
    "openai": "#18181b",
    "claude": "#27272a",
    "anthropic": "#27272a",
    "gamma": "#27272a",
    "apollo": "#18181b",
    "notebooklm": "#18181b",
    "gemini": "#18181b",
}
_BADGE_CYCLE = ["#18181b", "#27272a", "#3f3f46", "#52525b", "#71717a"]


def badge_color(tool: str) -> str:
    key = (tool or "?").strip().lower()
    if key in _TOOL_BADGES:
        return _TOOL_BADGES[key]
    return _BADGE_CYCLE[sum(map(ord, key)) % len(_BADGE_CYCLE)]


def badge_initial(tool: str) -> str:
    """The single letter on a tool badge. NotebookLM is 'N', not 'No'."""
    return (tool or "?").strip()[:1].upper() or "?"


def over(alpha: float, fg: str = "#111110", bg: str = None) -> str:
    """`fg` at `alpha` composited onto `bg`, as a solid hex."""
    base = bg or "#f4f4f5"
    fv, bv = fg.lstrip("#"), base.lstrip("#")
    out = []
    for i in (0, 2, 4):
        f, b = int(fv[i:i + 2], 16), int(bv[i:i + 2], 16)
        out.append(round(f * alpha + b * (1 - alpha)))
    return "#%02x%02x%02x" % tuple(out)


def tint(hex_colour: str, alpha_hex: str = "1f") -> str:
    """A brand colour at low opacity, for the pad behind its own icon.

    The design writes these as 8-digit hexes (#1DA487 + '1f'). Qt's stylesheet
    parser does not accept #RRGGBBAA, so this returns the rgba() form it does.
    """
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{int(alpha_hex, 16) / 255:.3f})"


def html_bg(colour: str, bg: str = "#ffffff") -> str:
    """Return a solid 6-digit hex safe for use in Qt HTML `bgcolor="..."` attrs.

    Qt's QTextHtmlParser **cannot** parse `rgba(...)` strings inside a
    `bgcolor` attribute — it silently falls back to `#000000` (pitch black).
    CSS `style='background:rgba(...)'` works fine, but `bgcolor='rgba(...)'`
    does not. Pass any theme color (hex or rgba) through this function when
    you need it as a `bgcolor` value; transparent colors are composited onto
    `bg` (default white).
    """
    c = qcolor(colour)
    if not c.isValid() or c.alpha() == 0:
        return bg
    if c.alpha() < 255:
        # Composite the semi-transparent colour onto the background
        bv = bg.lstrip("#")
        br, bg_r, bb = (int(bv[i:i + 2], 16) for i in (0, 2, 4))
        a = c.alpha() / 255.0
        nr = round(c.red() * a + br * (1 - a))
        ng = round(c.green() * a + bg_r * (1 - a))
        nb = round(c.blue() * a + bb * (1 - a))
        return "#%02x%02x%02x" % (nr, ng, nb)
    return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())


# ── solid-hex aliases for Qt HTML bgcolor="" attributes ─────────────────────
# Qt's QTextHtmlParser cannot parse rgba() in bgcolor="…" — it silently falls
# back to #000000. Use these pre-composited solids wherever setHtml()/
# QTextBrowser is involved. The rgba() originals remain for QPainter / QSS.
HTML_ERR_BG   = "#fef2f2"   # ERR_BG  composited on white  (rgba 220,38,38,0.14)
HTML_WARN_BG  = "#fefce8"   # WARN_BG composited on white  (rgba 202,138,4,0.14)
HTML_OK_BG    = "#f0fdf4"   # OK_BG   composited on white  (rgba 22,163,74,0.14)
HTML_INFO_BG  = "#f0f9ff"   # INFO_BG composited on white  (rgba 2,132,199,0.14)
HTML_ACCENT_100 = "#f5f5f7"  # ACCENT_RAMP[100] composited on white
HTML_ACCENT_200 = "#ebebed"  # ACCENT_RAMP[200] composited on white
HTML_WELL     = "#f7f7f7"   # WELL    composited on white  (rgba 0,0,0,0.03)


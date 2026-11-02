"""Left rail: brand, the two named nav groups, the add-on shelf, favourites,
and the pinned foot (wake word + profile).

The rail is a *shelf*, and it is grouped by what the user is doing rather than
by what the code calls it:

    WORK       the thing you came to start, and the two places that answer
               "where do things stand" and "what happened"
    ADD-ONS    the purpose-built runners — a product line, colour-coded
    (a rule)   Settings, which owns everything that configures Prism
    (the foot) the wake word and whose copy this is

Three constraints shape it and none of them may be traded away:

* **The budget is twelve controls and two headings, fitting at 768px with no
  scroll.** The rail had grown to twenty-odd controls across six headed groups
  — more choices than the screen it navigates to — and was cut back
  deliberately. It is at twelve here: New task, Home, History, Artifacts,
  four live add-ons, Settings, Favourites, the wake row, the profile row.
  Anything new has to displace something.
* **`theme.over()` for every white-at-alpha.** The rail's glyphs are rendered
  by handing a colour string to QSvgRenderer, and `rgba()` there is not
  dependable across Qt's SVG backends — a nav icon that silently renders black
  on navy is invisible. `over()` flattens the same pixel against the RAIL with
  no renderer to trust, and follows the role hue like everything else.
* **Everything is reachable from the keyboard.** Up/Down walks the rail,
  Home/End jump to its ends, Enter and Space activate, and every row shows the
  white focus ring `style.qss` gives `#navItem/#navSub/#railPrimary`.

Two things here are Prism's and not the design's, and both are kept:

* **Favourites** — the design has no equivalent. It is the only way to
  re-attach a folder you use every day without walking a file dialog, so it
  stays, at the foot of the nav where it does not compete with the add-ons.
* **The direct-jump settings** (`DIRECT`, below). They are also reachable as
  sections of the Settings screen, which is where the rail sends you.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QSize, QEvent, QPoint, QTimer, QRect, QRectF, QPointF
from PySide6.QtGui import (
    QFontMetrics, QPainter, QPainterPath, QLinearGradient, QBrush, QPen,
    QColor,
)
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QHBoxLayout, QFileDialog, QSizePolicy, QWidget, QScrollArea,
)

import favorites as FAV
import i18n
import identity
import theme
from addons import manifest, registry
from widgets import icons
from widgets import controls as C
from widgets.controls import Avatar, ToggleSwitch, elevate, kicker, track

_PATH_ROLE = 1000

# (key, label, icon, tip) — the WORK group: the destinations that bracket a
# run. Home answers "where do things stand", History answers "what happened",
# Artifacts answers "what did it actually make".
#
# History came back into the rail in this pass. It is the fifth step of the
# app's own mental model (describe → plan → review → execute → RESULTS), and
# with it in Settings → More the rail had no way at all to say "review your
# work" — one of the five things the grouping has to make legible. It is paid
# for by BOM & Stock, which stopped being a button (see ADDONS).
#
# Artifacts is paid for by the slot Reel/Studio's own row freed when it was
# pulled from ADDONS — the budget is back to twelve of twelve. A generated
# file used to exist only as a path a dialog held in memory (gone once it
# closed) or a link into a tool's own hosted session (gone once that session
# ended); this is where it actually lives once Prism has saved a findable
# copy, and it needed a way in that survives every dialog that ever produced
# one — not just Reel's.
PRIMARY = [
    ("home", "Home", "home",
     "Where things stand — recent runs, and what is waiting on you"),
    ("runs", "History", "clock", "Every past run, re-rendered from its record"),
    ("artifacts", "Artifacts", "folder",
     "Every file Prism has generated for you — reels, images, documents — "
     "kept here even after you close it"),
]

# The add-on shelf, DERIVED. The hand-written table that used to live here
# is gone; addons/registry.py is the one place an add-on is declared.
#
# It was one of three lists of the same add-ons, and the three had already
# drifted apart -- different memberships, and where they overlapped,
# different icons and different copy. widgets/home_panel.py still carries the
# comment saying it is the list that "must never drift from" this one.
#
# The tuple layout is unchanged on purpose -- key, label, icon, tip, feature,
# tone -- because four test files index it positionally and because
# devtools/extract_strings.py matches COPY_TABLES on the assignment target
# name, so the labels and tips stay translatable exactly as before.
#
# ONE THING DID CHANGE: the 6th field is now a TONE TOKEN, not a colour.
# Holding theme.ACCENT here froze it at import time, before theme.apply_role()
# runs -- and since apply_role rebinds ACCENT but not OK or WARN, a stale
# accent affected only some rows and was correspondingly hard to see. It is
# resolved by theme.tone() at the point of use below, which happens when the
# rail is built rather than when this module is imported.
ADDONS = [
    (a.key, a.label, a.icon, a.tip, a.feature, a.tone)
    for a in registry.shelf(manifest.RAIL)
]

# Kept for the one caller that still asks. Nothing sets it any more: "not
# built yet" is now manifest.SOON in an add-on's `status`, which is a fact
# about the add-on rather than a sentinel smuggled through the licence
# column. BOM outgrew it -- it ships, it is routed and gated, and only Home
# had not been told.
SOON = "__soon__"


# Everything that is neither WORK nor an add-on.
#
# No section header over it: one row does not need a group label, and the
# hairline above it already says "this is a different kind of thing".
MORE = [
    ("config", "Settings", "sliders",
     "Licence, agents, profile, language and workspace"),
]

# Lifted OUT of the rail and into the Settings screen's "More" section.
# Lumi's working help surface is on Home, where it can be found when a customer
# needs it without spending a permanent navigation slot.
#
# AI tools stays here rather than coming back to the rail with History, and the
# reason is the budget: the rail is at twelve of twelve. Of the two, History is
# the one the rail cannot do without — it is a *stage of the work*, and nothing
# else in the rail reports on finished runs. AI tools is a catalogue of what
# Prism can drive and whether you are signed in to each: setup, consulted when
# something will not log in, which is exactly what Settings is for.
SECONDARY = [
    ("catalog", "AI tools", "grid", "Every tool Prism can drive, and whether "
     "you're signed in to it"),
    ("guide", "How to use Prism", "help",
     "What Prism can do and what to type"),
]

# Behind the disclosure under MORE. Every one of these is also a section of the
# Settings screen; these are the shortcuts for people who know where they are
# going. None are licence-gated, so unlike ADDONS there is no lock to track.
DIRECT = [
    ("status", "Status", "chart", "Current profile, key & agents"),
    # Not "lock": that glyph means "you don't own this" everywhere else in the
    # rail, and Login tabs is always available — reusing it would teach the
    # wrong lesson.
    ("login", "Login tabs", "external",
     "Re-open your tools in Chrome to sign in"),
    ("licence", "Licence", "archive",
     "Your plan, what's included, seats and expiry"),
    ("agents", "Agents", "grid", "Re-pick one agent per category"),
    ("language", "Language", "globe",
     "Prism's own language, and what the AI tools answer in"),
    ("team", "Your role", "user",
     "Which job this copy is set up for, and the team workspace"),
    ("profile", "Profile", "user", "Change what-you-do"),
    ("key", "API key", "key", "Change your Groq API key"),
    ("chrome", "Chrome", "globe", "Pin or auto-detect your Chrome version"),
]

# Screens under direct settings mapping
OWNED_BY = {}

# How bright each rail ink is, as a fraction of white flattened onto the RAIL
# by theme.over(). Named rather than sprinkled, because the contrast ratios
# below are the reason for the exact values and they are easy to nudge apart by
# accident. Against ACCENT_RAMP[900]:
#   1.00 -> 14.5:1   0.82 -> 9.5:1   0.55 -> 5.3:1   0.50 -> 4.7:1
# 0.50 is the floor for anything that has to be read: the group headings sit on
# it, and it is why locked add-ons are no longer dimmed to 0.32 (2.8:1, which
# fails AA outright — see AddonRow.set_locked).
INK_CURRENT = 1.00
INK_PRIMARY = 0.88      # a live add-on's name, the current row's glyph
INK_ITEM = 0.70         # a resting nav row's glyph
INK_HEADING = 0.55      # a group heading
INK_QUIET = 0.45        # the coming-soon row: an inactive component
INK_CHROME = 0.60       # chevrons, the favourites +/- glyphs


def _amp(text: str) -> str:
    """Escape an ampersand for a button label.

    Qt reads `&` in button text as an accelerator marker, so "BOM & Stock"
    rendered as "BOM_Stock" with the S underlined. Every label that reaches a
    QPushButton goes through here.
    """
    return text.replace("&", "&&")


class _Elided(QLabel):
    """A label that elides rather than clipping.

    The rail is a fixed 240px and Hindi and Gujarati run about a third longer
    than English, so a name that fits in English will not fit translated.
    Clipped it loses its last glyphs silently and looks like a rendering fault;
    elided it says plainly that there is more, and the full string is on the
    row's tooltip either way.

    `setText` is deliberately NOT overridden — `i18n.install()` patches
    `QLabel.setText` at class level and a subclass in that path is a trap.
    Callers use `set_full_text()`, which is also the only place that knows what
    the untruncated string was.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(40)
        # Ignored, so a long name cannot widen the rail or push the lock glyph
        # off the end of the row — it takes what the layout gives it.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if text:
            self.setText(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._apply()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full, Qt.ElideRight,
                                        max(0, self.width())))


def nav_button(label: str, icon_name: str, small: bool = False,
               tip: str = "") -> QPushButton:
    btn = QPushButton(f"  {_amp(label)}")
    btn.setObjectName("navSub" if small else "navItem")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFlat(True)
    btn.setFocusPolicy(Qt.StrongFocus)
    size = 15 if small else 17
    icons.button_icon(btn, icon_name, size, "#27272a")
    btn.setIconSize(QSize(size, size))
    btn.setProperty("cur", False)
    btn.setMinimumHeight(C.MIN_TARGET + 4)
    # The accessible name is the label without its two-space icon gutter; the
    # description is why you would go there. A screen reader reads both.
    btn.setAccessibleName(label)
    if tip:
        btn.setToolTip(tip)
        btn.setAccessibleDescription(tip)
    btn._raw_label = label
    btn._raw_icon = icon_name
    btn._raw_tip = tip
    btn._is_small = small
    return btn


class AddonRow(QPushButton):
    """A shelf item: a colour-tinted chip carrying the add-on's glyph, then its
    name, then — when the licence does not cover it — a padlock.

    The chip is what separates this group from the flat rows above and below
    it: an add-on is a product, and it gets to look like one.
    """

    CHIP = 24

    def __init__(self, label: str, icon_name: str, hue: str, parent=None):
        # No _amp() here, deliberately, even though this IS a QPushButton:
        # the name is drawn by the _Elided QLabel below rather than by the
        # button's own text, and QLabel does not read "&" as an accelerator.
        # Escaping it would put a literal "&&" on the shelf.
        super().__init__(parent)
        self.setObjectName("navSub")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self._hue = hue
        self._icon_name = icon_name
        self._locked = False
        self._current = False
        self._raw_label = label
        display_label = "Email Inquiries" if label == "Email inquiry automation" else label

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 0, 6, 0)
        row.setSpacing(theme.SPACE_2 + 2)
        self._row_layout = row
        self._chip = QLabel()
        self._chip.setFixedSize(self.CHIP, self.CHIP)
        self._chip.setAlignment(Qt.AlignCenter)
        self._chip.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self._chip)
        self._label = _Elided(display_label)
        row.addWidget(self._label, stretch=1)
        # Drawn only when locked. It keeps its 14px of width either way so the
        # names in the shelf stay on one left edge whatever the licence says.
        self._lock = QLabel()
        self._lock.setFixedWidth(14)
        self._lock.setAlignment(Qt.AlignCenter)
        self._lock.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self._lock)
        self.setMinimumHeight(34)
        self.setAccessibleName(label)
        self._repaint()

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        if collapsed:
            self._label.setVisible(False)
            self._lock.setVisible(False)
            self._row_layout.setContentsMargins(0, 0, 0, 0)
            self._row_layout.setAlignment(Qt.AlignCenter)
            self.setFixedSize(48, 38)
        else:
            self._label.setVisible(True)
            self._lock.setVisible(self._locked)
            self._row_layout.setContentsMargins(6, 0, 6, 0)
            self._row_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.setMinimumHeight(34)
            self.setMaximumWidth(16777215)
            self.setMinimumWidth(0)
            self.setMaximumHeight(16777215)
        self._repaint()          # tile and glyph size differ between the two rails

    # ── state ─────────────────────────────────────────────────────────────
    def set_locked(self, locked: bool) -> None:
        """An add-on the licence does not cover.

        The old treatment dimmed the whole row to 32% white — 2.8:1 on the
        rail, which fails AA — and swapped the chip glyph for a padlock. Both
        were wrong. Dim reads as *disabled or broken*, not as "not on your
        plan", and losing the product's own glyph meant you could no longer
        tell which add-on the row was.

        So: the name stays at a readable weight, the chip keeps the add-on's
        glyph and only loses its colour (so live and locked are still
        scannable apart at a glance), and a padlock appears at the end of the
        row. The row stays **enabled** — clicking one opens the pitch for it,
        which is the most useful thing that click can do, because the customer
        has just told us exactly what they want.
        """
        self._locked = locked
        self._repaint()

    def set_current(self, current: bool) -> None:
        self._current = current
        self._repaint()

    def is_locked(self) -> bool:
        return self._locked

    def _repaint(self) -> None:
        live = not self._locked
        hue = self._hue if live else theme.NEUTRAL[400]
        if getattr(self, "_collapsed", False):
            # On the collapsed rail the glyph stands alone. A tinted tile behind
            # every add-on turned a slim strip of icons into a column of grey
            # blocks, which is what made it look full. The open rail keeps its
            # tiles: there they set the shelf apart from the flat rows around it.
            # Same ink as the Home / History / Artifacts glyphs above, so the
            # add-ons do not sit on the rail as a heavier, blacker group.
            glyph = (theme.over(INK_CURRENT if self._current else INK_ITEM)
                     if live else hue)
            self._chip.setPixmap(icons.pixmap(self._icon_name, 18, glyph))
            self._chip.setStyleSheet("background: transparent;")
            return
        chip_bg = (theme.tint(self._hue, "2e") if live
                   else theme.tint("#ffffff", "16"))
        self._chip.setPixmap(icons.pixmap(self._icon_name, 14, hue))
        self._chip.setStyleSheet(
            f"background: {chip_bg}; border-radius: {theme.R_CHIP + 1}px;")
        ink = theme.over(INK_CURRENT if self._current
                         else INK_PRIMARY if live else INK_ITEM)
        self._label.setStyleSheet(
            theme.type_css("SUPPORT", ink)
            + " font-weight: 500; background: transparent;")
        if self._locked:
            self._lock.setPixmap(icons.pixmap("lock", 13,
                                              theme.over(INK_HEADING)))
        else:
            self._lock.clear()


class SoonRow(QFrame):
    """The next add-on, shown but not offered.

    Not a QPushButton: there is nothing behind the click, and a disabled button
    is a control that fails every audit for click target, focus and name while
    doing nothing a caption would not do. As a caption it costs no slot in the
    rail's control budget, which is what pays for History.
    """

    def __init__(self, label: str, icon_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName("navSoon")
        row = QHBoxLayout(self)
        row.setContentsMargins(6 + 2, 0, 6 + 2, 0)
        row.setSpacing(theme.SPACE_2 + 2)
        self._row_layout = row
        self.chip = QLabel()
        self.chip.setFixedSize(AddonRow.CHIP, AddonRow.CHIP)
        self.chip.setAlignment(Qt.AlignCenter)
        self.chip.setPixmap(icons.pixmap(icon_name, 14, theme.over(INK_QUIET)))
        self.chip.setStyleSheet(f"background: {theme.tint('#ffffff', '0f')};"
                           f" border-radius: {theme.R_CHIP + 1}px;")
        row.addWidget(self.chip)
        name = _Elided(label)
        name.setStyleSheet(theme.type_css("SUPPORT", theme.over(INK_QUIET))
                           + " font-weight: 500; background: transparent;")
        row.addWidget(name, stretch=1)
        self.name = name
        self.setMinimumHeight(30)

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed:
            self.name.setVisible(False)
            self._row_layout.setContentsMargins(0, 0, 0, 0)
            self._row_layout.setAlignment(Qt.AlignCenter)
            self.setFixedSize(48, 38)
        else:
            self.name.setVisible(True)
            self._row_layout.setContentsMargins(6 + 2, 0, 6 + 2, 0)
            self._row_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.setMinimumHeight(30)
            self.setMaximumWidth(16777215)
            self.setMinimumWidth(0)
            self.setMaximumHeight(16777215)


class Sidebar(QFrame):
    command_triggered = Signal(str)
    favorite_chosen = Signal(str)
    wakeword_toggled = Signal(bool)
    tour_requested = Signal()
    collapsed_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(260)
        self._collapsed = False
        self.setAttribute(Qt.WA_StyledBackground, False)

        # The rail fits inside 768px without scrolling — that is the budget the
        # twelve-control limit exists to hold. The scroll area stays as a floor
        # for anything smaller (a 640px window is allowed by the shell), because
        # a rail you can reach by scrolling is worth more than one Qt has
        # squeezed below its sizeHint and clipped.
        shell = QVBoxLayout(self)
        shell.setContentsMargins(4, 4, 4, 4)
        shell.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent;
                width: 4px;
                margin: 0px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 0, 0, 0.20);
                min-height: 20px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 0, 0, 0.40);
            }
            QScrollBar::sub-line:vertical, QScrollBar::add-line:vertical {
                height: 0px;
                width: 0px;
                background: transparent;
                border: none;
            }
            QScrollBar::up-arrow:vertical, QScrollBar::down-arrow:vertical {
                width: 0px;
                height: 0px;
                background: transparent;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: transparent;
            }
        """)
        inner = QWidget()
        inner.setObjectName("sidebarInner")
        scroll.setWidget(inner)
        shell.addWidget(scroll)
        self._scroll = scroll
        self._inner = inner

        root = QVBoxLayout(inner)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_5,
                                theme.SPACE_3, theme.SPACE_3)
        root.setSpacing(theme.SPACE_1)
        self._root_layout = root

        self._brand_widget = self._brand()
        root.addWidget(self._brand_widget)
        root.addSpacing(theme.SPACE_3)

        # ── WORK ─────────────────────────────────────────────────────────────
        # One heading over the three things a run is made of: start it, see
        # where it stands, read what happened.
        self._nav: dict[str, QWidget] = {}
        self._nav_glyph: dict[str, tuple[str, int, float]] = {}
        self._chain: list[QWidget] = []

        self._work_lbl = self._section("WORK")
        root.addWidget(self._work_lbl)
        self._work_collapsed_rule = self._rule()
        self._work_collapsed_rule.setVisible(False)
        root.addWidget(self._work_collapsed_rule)

        # The rail's one emphasised control. A soft tinted button rather than a
        # solid black one: the black slab was the heaviest thing on the screen.
        self.new_task_btn = QPushButton(i18n.t('New task'))
        self.new_task_btn.setObjectName("railPrimary")
        self.new_task_btn.setCursor(Qt.PointingHandCursor)
        self.new_task_btn.setFocusPolicy(Qt.StrongFocus)
        self.new_task_btn.setMinimumHeight(C.MIN_TARGET + 6)
        self.new_task_btn.setAccessibleName(i18n.t("New task"))
        self.new_task_btn.setToolTip(i18n.t("Describe something you want done"))
        self.new_task_btn.setIcon(C.brand_dot_icon(24, "plus"))
        self.new_task_btn.setIconSize(QSize(24, 24))
        self.new_task_btn.clicked.connect(
            lambda: self.command_triggered.emit("workbench"))
        elevate(self.new_task_btn, theme.SHADOW_ACCENT, theme.ACCENT)
        root.addWidget(self.new_task_btn)
        # "workbench" is a destination even though its control is a button: on
        # the workbench the rail must say so, or the screen the app is *for* is
        # the one screen with nothing lit.
        self._register("workbench", self.new_task_btn)

        for key, label, icon_name, tip in PRIMARY:
            small = key != "home"
            btn = nav_button(i18n.t(label), icon_name, small=small,
                             tip=i18n.t(tip))
            btn.clicked.connect(lambda _=False, k=key: self._go(k))
            self._nav_glyph[key] = (icon_name, 15 if small else 17,
                                    INK_ITEM if small else INK_PRIMARY)
            self._register(key, btn)
            root.addWidget(btn)
        self._current = "home"

        # ── the add-on shelf: collapsible with dropdown arrow ─────────────
        root.addSpacing(theme.SPACE_2)

        addons_head = QWidget()
        addons_head.setObjectName("addonsHead")
        addons_head.setCursor(Qt.PointingHandCursor)
        addons_hlayout = QHBoxLayout(addons_head)
        addons_hlayout.setContentsMargins(4, 2, 4, 2)
        addons_hlayout.setSpacing(theme.SPACE_1)

        addons_lbl = self._section("ADD-ONS")
        addons_hlayout.addWidget(addons_lbl, stretch=1)

        self._addons_toggle_btn = QPushButton()
        self._addons_toggle_btn.setObjectName("addonsChevron")
        self._addons_toggle_btn.setFlat(True)
        self._addons_toggle_btn.setFixedSize(22, 22)
        self._addons_toggle_btn.setCursor(Qt.PointingHandCursor)
        self._addons_toggle_btn.setToolTip(i18n.t("Collapse / expand Add-ons"))
        self._addons_open = True
        icons.button_icon(self._addons_toggle_btn, "chevron-down", 11, theme.over(INK_CHROME))
        addons_hlayout.addWidget(self._addons_toggle_btn)

        addons_head.mousePressEvent = lambda e: self._toggle_addons()
        self._addons_toggle_btn.clicked.connect(lambda: self._toggle_addons())

        root.addWidget(addons_head)
        self._addons_head = addons_head
        self._addons_collapsed_rule = self._rule()
        self._addons_collapsed_rule.setVisible(False)
        root.addWidget(self._addons_collapsed_rule)

        self._addon_rows: list[QWidget] = []
        self._gated: dict[str, tuple[AddonRow, str, str, str]] = {}
        # Straight off the registry rather than off ADDONS above, because the
        # manifest carries `status` -- which ADDONS' six positional fields
        # cannot, and which used to be smuggled through the licence column as
        # a SOON sentinel. This loop runs when the rail is BUILT, so
        # theme.tone() below resolves after apply_role() rather than at import.
        for addon in registry.shelf(manifest.RAIL):
            if addon.status == manifest.SOON:
                # A caption, not a control. A disabled thing that cannot be
                # clicked, focused or activated is not a button, and drawing
                # it as one is dishonest; rendering it as a caption also hands
                # its slot in the twelve-control budget back to History.
                text = i18n.t("{addon}  (soon)").format(
                    addon=i18n.t(addon.label))
                row = SoonRow(text, addon.icon)
                row.setToolTip(i18n.t(addon.tip))
                self._addon_rows.append(row)
                root.addWidget(row)
                continue
            row = AddonRow(i18n.t(addon.label), addon.icon,
                           theme.tone(addon.tone))
            row.setToolTip(i18n.t(addon.tip))
            row.setAccessibleDescription(i18n.t(addon.tip))
            row.clicked.connect(
                lambda _=False, k=addon.key: self.command_triggered.emit(k))
            if addon.feature:
                self._gated[addon.key] = (row, addon.label, addon.icon,
                                          addon.feature)
            self._register(addon.key, row)
            self._addon_rows.append(row)
            root.addWidget(row)

        # -- Settings ---------------------------------------------------------
        # Under a hairline rather than under a third heading: it is the one
        # configuring surface, and the rule says "different kind of thing" for
        # nothing but a pixel.
        root.addSpacing(theme.SPACE_2)
        root.addWidget(self._rule())
        root.addSpacing(theme.SPACE_1)
        for key, label, icon_name, tip in MORE:
            btn = nav_button(i18n.t(label), icon_name, small=True,
                             tip=i18n.t(tip))
            btn.clicked.connect(lambda _=False, k=key: self._go(k))
            self._nav_glyph[key] = (icon_name, 15, INK_ITEM)
            self._register(key, btn)
            root.addWidget(btn)

        # -- favorites -------------------------------------------------------
        # Folded shut by default, and pushed to the *bottom* of the nav by the
        # stretch above it. Favourites are a working shortcut used while
        # composing a task, not a destination, so they sit beside the profile
        # row rather than in the middle of the list — and the slack the rail
        # used to leave as a navy void now separates "where you go" from "your
        # own things", which is a distinction worth drawing.
        root.addStretch(1)
        fav_wrap = QWidget()
        fav_col = QVBoxLayout(fav_wrap)
        fav_col.setContentsMargins(0, 0, 0, 0)
        fav_col.setSpacing(theme.SPACE_1 // 2)

        fav_head = QHBoxLayout()
        fav_head.setSpacing(theme.SPACE_1 // 2)
        self.fav_toggle = QPushButton(i18n.t("Favourites"))
        self.fav_toggle.setObjectName("navSub")
        self.fav_toggle.setFlat(True)
        self.fav_toggle.setCheckable(True)
        self.fav_toggle.setCursor(Qt.PointingHandCursor)
        self.fav_toggle.setFocusPolicy(Qt.StrongFocus)
        self.fav_toggle.setMinimumHeight(C.MIN_TARGET)
        self.fav_toggle.setAccessibleName(i18n.t("Favourites"))
        self.fav_toggle.setToolTip(i18n.t("Files and folders you attach often"))
        icons.button_icon(self.fav_toggle, "chevron-right", 13,
                          theme.over(INK_CHROME))
        self.fav_toggle.toggled.connect(self._toggle_favorites)
        fav_head.addWidget(self.fav_toggle, stretch=1)
        self._fav_add = self._mini("plus", "Favorite a file or folder",
                                   self._add_favorite)
        self._fav_del = self._mini("trash", "Remove the selected favorite",
                                   self._remove_favorite)
        fav_head.addWidget(self._fav_add)
        fav_head.addWidget(self._fav_del)
        fav_col.addLayout(fav_head)
        self._chain.append(self.fav_toggle)
        self._chain.append(self._fav_add)
        self._chain.append(self._fav_del)

        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favList")
        self.fav_list.setFrameShape(QListWidget.NoFrame)
        self.fav_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.fav_list.setAccessibleName(i18n.t("Favourite files and folders"))
        # On the dark rail the shared QListWidget rules would paint a white
        # box; the favourites list is part of the rail, not a control on it.
        self.fav_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; padding: 0;"
            f" {theme.type_css('META', theme.over(INK_ITEM))} }}"
            "QListWidget::item { padding: 6px 6px;"
            f" border-radius: {theme.R_CHIP + 1}px; }}"
            f"QListWidget::item:hover {{ background: rgba(0, 0, 0, 0.04);"
            f" color: {theme.over(1.0)}; }}"
            f"QListWidget::item:selected {{ background: rgba(0, 0, 0, 0.07);"
            f" color: {theme.over(1.0)}; }}")
        self.fav_list.setToolTip(i18n.t("Double-click to attach"))
        self.fav_list.setIconSize(QSize(15, 15))
        self.fav_list.itemDoubleClicked.connect(self._favorite_clicked)
        # Sized to its contents by reload_favorites(), not stretched. Inside
        # the rail's scroll area a stretching list has no slack to take — the
        # content is already taller than the viewport — so Qt collapsed it to
        # its minimum and the favourites vanished entirely.
        self.fav_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        fav_col.addWidget(self.fav_list)
        root.addWidget(fav_wrap)
        self._fav_wrap = fav_wrap

        # -- foot -------------------------------------------------------------
        # Pinned below the scroll area rather than inside it. The design keeps
        # these at the bottom of the rail with a flex spacer, which works
        # because a browser page is as tall as it needs to be. Here the rail is
        # a fixed 100%-height column, so anything left inside would be pushed
        # off the bottom on a short window — and "which plan am I on" and
        # "whose copy is this" are exactly the two things that must never
        # require a scroll to answer.
        foot = QWidget()
        foot.setObjectName("sidebarInner")
        foot_col = QVBoxLayout(foot)
        foot_col.setContentsMargins(theme.SPACE_3, 0,
                                    theme.SPACE_3, theme.SPACE_3)
        foot_col.setSpacing(theme.SPACE_1)
        foot_col.addWidget(self._rule())
        foot_col.addSpacing(theme.SPACE_1)
        self._foot_col = foot_col

        # The wake word lives down here rather than above the add-on shelf: it
        # is a standing preference, not a destination, and it was occupying the
        # most valuable strip in the rail. Removed from visible nav bar per user request.
        self._wake_row()
        self.wake_row.setVisible(False)
        # The licence card folded into the profile row: two lines instead of a
        # card plus a row, and "what am I paying for" is still answered without
        # a scroll or a click.
        foot_col.addWidget(self._profile_row())
        shell.addWidget(foot)

        # The "you are here" marker. The `cur` wash carries the state on its
        # own; this is the second, faster read — a 3px bar on the rail's own
        # edge, in the one place the eye already goes to find its place in a
        # list. It is a child of `inner` because `inner` paints an opaque
        # background over anything the QFrame itself would draw.
        self._pip = QFrame(inner)
        self._pip.setObjectName("railPip")
        self._pip.setStyleSheet("background: #09090b; border-radius: 2px;")
        self._pip.hide()
        inner.installEventFilter(self)

        for widget in self._chain:
            widget.installEventFilter(self)

        self.reload_favorites()
        self._toggle_favorites(False)
        self._refresh_nav()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        r = QRectF(self.rect())
        radius = 20.0
        if C.paint_flat_card(self, painter, r, radius):
            return

        clip = QPainterPath()
        clip.addRoundedRect(r, radius, radius)
        painter.setClipPath(clip)

        central = self.window().findChild(QWidget, "central")
        if central and hasattr(central, "get_blurred_pixmap"):
            blurred = central.get_blurred_pixmap()
            if blurred and not blurred.isNull():
                pos = central.mapFromGlobal(self.mapToGlobal(QPoint(0, 0)))
                src_rect = QRect(pos.x(), pos.y(), int(r.width()), int(r.height()))
                painter.drawPixmap(r.toRect(), blurred, src_rect)

        # Frosted light glass sheen
        glass_grad = QLinearGradient(QPointF(r.left(), r.top()),
                                     QPointF(r.left(), r.bottom()))
        glass_grad.setColorAt(0.00, QColor(255, 255, 255, 185))
        glass_grad.setColorAt(0.50, QColor(255, 255, 255, 150))
        glass_grad.setColorAt(1.00, QColor(255, 255, 255, 130))
        painter.setBrush(QBrush(glass_grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(r, radius, radius)

        # Crisp glass outer border
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

    # ── registration ──────────────────────────────────────────────────────
    def _register(self, key: str, widget: QWidget) -> None:
        """One rail destination: highlightable by key, and one stop on the
        keyboard walk. Registering both in one call is what keeps the arrow
        order and the visual order from drifting apart."""
        self._nav[key] = widget
        self._chain.append(widget)

    # Tab order is deliberately left to Qt's default, which is creation order —
    # and every row here is created in the order it is drawn, so the two already
    # agree. An explicit setTabOrder() pass re-links the *window's* whole focus
    # chain, which moved the initial focus onto the rail's New-task button and
    # away from the workbench's input.

    # ── chrome ────────────────────────────────────────────────────────────
    def _brand(self) -> QWidget:
        wrap = QWidget()
        wrap.setObjectName("brandWrap")
        main_layout = QVBoxLayout(wrap)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 1. Expanded brand row ─────────────────────────────────────────────
        expanded_w = QWidget()
        expanded_row = QHBoxLayout(expanded_w)
        expanded_row.setContentsMargins(2, 0, 0, 0)
        expanded_row.setSpacing(theme.SPACE_2)
        mark = QLabel()
        mark.setPixmap(icons.logo_pixmap(26))
        mark.setAccessibleName("Prism")
        expanded_row.addWidget(mark)
        name = QLabel("PRISM")
        name.setObjectName("brand")
        # Stacked under the wordmark when this copy belongs to a company
        # member: on a shared workspace several people run Prism side by side
        # and the accent colour alone does not say WHICH sales person.
        who = identity.describe()
        if who:
            stack = QVBoxLayout()
            stack.setContentsMargins(0, 0, 0, 0)
            stack.setSpacing(0)
            stack.addWidget(track(name, 0.14))
            member = _Elided(who)
            member.setObjectName("railMuted")
            member.setStyleSheet(theme.type_css("LABEL",
                                                theme.over(INK_HEADING))
                                 + " background: transparent;")
            member.setToolTip("This copy of Prism is set up for this person. "
                              "Change it in Settings → Your role.")
            stack.addWidget(member)
            expanded_row.addLayout(stack, stretch=1)
        else:
            expanded_row.addWidget(track(name, 0.14), stretch=1)

        self._collapse_btn = QPushButton()
        self._collapse_btn.setObjectName("railCollapseBtn")
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setCursor(Qt.PointingHandCursor)
        self._collapse_btn.setToolTip(i18n.t("Collapse navigation"))
        icons.button_icon(self._collapse_btn, "chevron-left", 14, theme.over(INK_CHROME))
        self._collapse_btn.clicked.connect(lambda: self.toggle_collapsed(True))
        expanded_row.addWidget(self._collapse_btn)

        main_layout.addWidget(expanded_w)
        self._brand_expanded = expanded_w

        # ── 2. Collapsed brand row ────────────────────────────────────────────
        collapsed_w = QWidget()
        collapsed_col = QVBoxLayout(collapsed_w)
        collapsed_col.setContentsMargins(0, 0, 0, 0)
        collapsed_col.setSpacing(6)
        collapsed_col.setAlignment(Qt.AlignCenter)

        mark_c = QLabel()
        mark_c.setPixmap(icons.logo_pixmap(26))
        mark_c.setAccessibleName("Prism")
        mark_c.setCursor(Qt.PointingHandCursor)
        mark_c.setToolTip(i18n.t("Expand navigation"))
        mark_c.mousePressEvent = lambda e: self.toggle_collapsed(False)
        collapsed_col.addWidget(mark_c, alignment=Qt.AlignCenter)

        self._expand_btn = QPushButton()
        self._expand_btn.setObjectName("railCollapseBtn")
        self._expand_btn.setFixedSize(28, 28)
        self._expand_btn.setCursor(Qt.PointingHandCursor)
        self._expand_btn.setToolTip(i18n.t("Expand navigation"))
        icons.button_icon(self._expand_btn, "chevron-right", 14, theme.over(INK_CHROME))
        self._expand_btn.clicked.connect(lambda: self.toggle_collapsed(False))
        collapsed_col.addWidget(self._expand_btn, alignment=Qt.AlignCenter)

        collapsed_w.setVisible(False)
        main_layout.addWidget(collapsed_w)
        self._brand_collapsed = collapsed_w

        return wrap

    @staticmethod
    def _section(text: str, faint: bool = False) -> QLabel:
        """A rail group heading, on the LABEL level of the type scale.

        `#colHead` is the light-mode LABEL role and inks itself
        ACCENT_RAMP[700], which is 1.3:1 on the rail — unreadable. So the rail
        keeps its own `#navSection`, which carries the identical Barlow
        Condensed 11/600 metrics with an ink that survives navy, and the
        colour is set here from the same INK_ scale everything else uses.
        """
        lbl = kicker(text, muted=True)
        lbl.setObjectName("navSection")
        lbl.setStyleSheet(
            theme.type_css("LABEL",
                           theme.over(INK_QUIET if faint else INK_HEADING))
            + f" background: transparent; padding: {theme.SPACE_2}px 4px 2px;")
        return lbl

    @staticmethod
    def _rule() -> QFrame:
        line = QFrame()
        line.setObjectName("railRule")
        line.setFixedHeight(1)
        line.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        return line

    def _wake_row(self) -> QWidget:
        """The wake-word switch, with the whole row as its hit target.

        `ToggleSwitch` is 32x18 by design and it is correct at that size — but
        18px is well under the 28px floor, and a 32px-wide target is a miss
        waiting to happen on a trackpad. So the row is the control: it is a
        button, it takes focus and shows the rail's white focus ring, Space and
        Enter activate it, and the label is clickable, which is what everyone
        expects of a switch with words beside it.

        The switch itself is disabled *as a control* and kept as the row's
        indicator. It still animates and still reports its state — a disabled
        QAbstractButton emits `toggled` from `setChecked()` exactly as before —
        and `paintEvent` sets its own brushes, so it draws identically.
        """
        row_btn = QPushButton()
        row_btn.setObjectName("navSub")
        row_btn.setFlat(True)
        row_btn.setCursor(Qt.PointingHandCursor)
        row_btn.setFocusPolicy(Qt.StrongFocus)
        row_btn.setMinimumHeight(C.MIN_TARGET + 6)
        row_btn.setStyleSheet("""
            QPushButton#navSub {
                background: transparent;
                border: none;
                border-radius: 8px;
                padding: 4px 8px;
            }
            QPushButton#navSub:hover {
                background: rgba(0, 0, 0, 0.04);
            }
        """)
        wake_row = QHBoxLayout(row_btn)
        wake_row.setContentsMargins(theme.SPACE_2 + 2, 4, theme.SPACE_2 + 2, 4)
        wake_row.setSpacing(theme.SPACE_3)
        self._wake_row_layout = wake_row

        self.wake_switch = ToggleSwitch()
        self.wake_switch.setEnabled(False)
        self.wake_switch.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.wake_switch.setFocusPolicy(Qt.NoFocus)
        self.wake_switch.toggled.connect(self.wakeword_toggled.emit)
        wake_row.addWidget(self.wake_switch)

        wake_label = QLabel(i18n.t('Listen for "Prism"'))
        wake_label.setObjectName("railMuted")
        wake_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        wake_label.setStyleSheet("color: #27272a; font-size: 13px; font-weight: 500; background: transparent;")
        wake_row.addWidget(wake_label, stretch=1)
        self._wake_label = wake_label

        self._wake_symbol = QLabel()
        self._wake_symbol.setFixedSize(22, 22)
        self._wake_symbol.setAlignment(Qt.AlignCenter)
        self._wake_symbol.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._wake_symbol.setVisible(False)
        wake_row.addWidget(self._wake_symbol)
        self.wake_switch.toggled.connect(lambda on: self._update_wake_symbol(on))
        self._update_wake_symbol(self.wake_switch.isChecked())

        # The literal stays inside the setToolTip call: devtools/
        # extract_strings.py reads the source, and a sentence assembled into a
        # variable first is one a translator never sees.
        row_btn.setToolTip(
            "Best-effort wake word: polls the mic every ~2s and checks Groq "
            "Whisper for the word 'Prism'. Not instant like a real wake-word "
            "engine — see wakeword.py for details.")
        row_btn.setAccessibleName(i18n.t('Listen for "Prism"'))
        row_btn.setAccessibleDescription(row_btn.toolTip())
        row_btn.clicked.connect(
            lambda: self.wake_switch.setChecked(not self.wake_switch.isChecked()))
        self.wake_row = row_btn
        self._chain.append(row_btn)
        return row_btn

    def _profile_row(self) -> QWidget:
        """Who this copy belongs to, and what it is licensed for — one row.

        These were a card and a row: four lines and a button to say a plan name
        and a person. The two questions ("whose copy is this", "what am I
        paying for") are asked together and answered together, and folding them
        halves the rail's footer without losing either.
        """
        btn = QPushButton()
        btn.setObjectName("railProfile")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.StrongFocus)
        btn.setToolTip(i18n.t("Your profile, licence and workspace"))
        btn.setAccessibleName(i18n.t("Your profile, licence and workspace"))
        btn.clicked.connect(lambda: self.command_triggered.emit("config"))
        # A QPushButton does not grow its sizeHint for a layout put inside it,
        # so the second line was being clipped by the button's own text height.
        btn.setMinimumHeight(48)
        row = QHBoxLayout(btn)
        row.setContentsMargins(6, 6, 6, 6)
        row.setSpacing(theme.SPACE_2 + 1)
        self._profile_btn_layout = row

        self._avatar_slot = QHBoxLayout()
        self._avatar_slot.setContentsMargins(0, 0, 0, 0)
        row.addLayout(self._avatar_slot)

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        self._profile_name = _Elided(i18n.t("This computer"))
        self._profile_name.setObjectName("railProfileName")
        stack.addWidget(self._profile_name)
        self._profile_sub = _Elided(i18n.t("Checking licence…"))
        self._profile_sub.setObjectName("railProfileRole")
        # `#railProfileRole` inks itself white-at-45%, 4.1:1 on the rail. The
        # plan name is the answer to "what am I paying for" and has to clear
        # AA, so the ink comes from the INK_ scale instead — 5.3:1.
        self._profile_sub.setStyleSheet(
            theme.type_css("META", theme.over(INK_ITEM))
            + " background: transparent;")
        stack.addWidget(self._profile_sub)
        row.addLayout(stack, stretch=1)

        chevron = QLabel()
        chevron.setPixmap(icons.pixmap("chevron-right", 13,
                                       theme.over(INK_CHROME)))
        chevron.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(chevron)
        self._profile_chevron = chevron
        self._profile_btn = btn
        self._chain.append(btn)
        self.set_profile("")
        return btn

    def set_profile(self, name: str) -> None:
        """Name the person, or say plainly that nobody has been named.

        A solo install has no designation key and therefore no name, so this
        used to read "This computer" forever. It still does when nothing is
        set — that is honest — but the name is now settable in Settings, and
        once set it is what the rail shows.
        """
        shown = (name or "").strip()
        self._profile_name.set_full_text(shown or i18n.t("This computer"))
        while self._avatar_slot.count():
            item = self._avatar_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._avatar_slot.addWidget(Avatar(shown or "?", 28))

    def _build_direct_group(self) -> QWidget:
        """The settings shortcuts, collapsed behind one disclosure row.

        Not currently mounted in the rail — every one of DIRECT is a section of
        the Settings screen, and mounting this would put ten more controls into
        a twelve-control budget. Kept because the shortcut route is a real
        design position and this is its implementation, not because anything
        calls it today.
        """
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1 // 2)

        toggle = QPushButton(i18n.t('More settings'))
        toggle.setObjectName("navSub")
        toggle.setCursor(Qt.PointingHandCursor)
        toggle.setFlat(True)
        toggle.setCheckable(True)
        toggle.setLayoutDirection(Qt.RightToLeft)   # chevron on the right
        icons.button_icon(toggle, "chevron-right", 15, theme.over(INK_CHROME))
        col.addWidget(toggle)

        body = QWidget(self)
        body_col = QVBoxLayout(body)
        body_col.setContentsMargins(0, 0, 0, 0)
        body_col.setSpacing(theme.SPACE_1 // 2)
        for key, label, icon_name, tip in DIRECT:
            btn = nav_button(i18n.t(label), icon_name, small=True,
                             tip=i18n.t(tip))
            btn.clicked.connect(
                lambda _=False, k=key: self.command_triggered.emit(k))
            body_col.addWidget(btn)
        body.setVisible(False)
        col.addWidget(body)

        def _on_toggled(open_: bool):
            icons.button_icon(toggle,
                              "chevron-down" if open_ else "chevron-right",
                              15, theme.over(INK_CHROME))
            body.setVisible(open_)
        toggle.toggled.connect(_on_toggled)
        self._configure_toggle = toggle
        return wrap

    def _mini(self, icon_name: str, tip: str, slot) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip(i18n.t(tip))
        btn.setAccessibleName(i18n.t(tip))
        btn.setFocusPolicy(Qt.StrongFocus)
        # 24px was under the 28px floor: reachable with a mouse on a desk, not
        # with a trackpad on a train.
        btn.setFixedSize(C.MIN_TARGET, C.MIN_TARGET)
        btn.setStyleSheet(
            "QPushButton { background: transparent;"
            " border: 2px solid transparent;"
            f" border-radius: {theme.R_CHIP}px; padding: 0; }}"
            f"QPushButton:hover {{ background: rgba(0, 0, 0, 0.05); }}"
            f"QPushButton:focus {{ border-color: {theme.over(0.85)}; }}")
        icons.button_icon(btn, icon_name, 14, theme.over(INK_CHROME))
        btn.clicked.connect(slot)
        return btn

    # ── nav ───────────────────────────────────────────────────────────────
    def _go(self, key: str):
        # Safe to light optimistically: `_go` is only wired to PRIMARY and
        # MORE, and none of those three is licence-gated, so the window cannot
        # refuse the jump. The add-ons deliberately do NOT come through here —
        # they emit straight to the window and wait to be told where they
        # landed, because an add-on the licence refuses never opens its screen
        # and a rail that had already lit it would be lying.
        self.set_current(key)
        self.command_triggered.emit(key)

    def set_current(self, key: str):
        """Light the rail row for the screen the window actually switched to.

        Accepts every screen key, not just the rail's own: the three surfaces
        behind Settings → More (AI tools, the guide, help) map onto Settings
        via OWNED_BY, so being on one of them lights the branch you are in
        rather than leaving the whole rail dark. Anything genuinely unmapped
        clears the highlight — an honest "nowhere in this list" beats a stale
        row claiming you are still on Home.
        """
        self._current = OWNED_BY.get(key, key if key in self._nav else "")
        self._refresh_nav()

    def current(self) -> str:
        return self._current

    def _refresh_nav(self):
        c = getattr(self, "_collapsed", False)
        for key, widget in self._nav.items():
            cur = key == self._current
            widget.setProperty("cur", cur)
            glyph = self._nav_glyph.get(key)
            if glyph:
                name, size, ink = glyph
                actual_size = 18 if c else size
                icons.button_icon(widget, name, actual_size,
                                  theme.over(INK_CURRENT if cur else ink))
            if isinstance(widget, AddonRow):
                widget.set_current(cur)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._place_pip()

    # ── the "you are here" marker ─────────────────────────────────────────
    def _place_pip(self):
        widget = self._nav.get(self._current)
        if widget is None or not widget.isVisibleTo(self):
            self._pip.hide()
            return
        # mapTo() assumes widget is a descendant of self._inner in the same
        # window; that stopped holding once the sidebar could be reparented,
        # so go through global coordinates instead (see 4f65dfd).
        origin = self._inner.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        top = origin.y()
        height = max(14, min(22, widget.height() - 10))
        c = getattr(self, "_collapsed", False)
        self._pip.setGeometry(2 if c else 0,
                              top + (widget.height() - height) // 2,
                              3 if c else 4, height)
        self._pip.show()
        self._pip.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._place_pip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_favorites()
        self._place_pip()

    # ── keyboard ──────────────────────────────────────────────────────────
    def _focus_chain(self) -> list[QWidget]:
        return [w for w in self._chain
                if w is not None and w.isVisibleTo(self) and w.isEnabled()]

    def eventFilter(self, obj, event):
        if obj is self._inner and event.type() in (
                QEvent.LayoutRequest, QEvent.Resize):
            self._place_pip()
            return False
        if event.type() == QEvent.KeyPress:
            chain = self._focus_chain()
            if obj in chain:
                key = event.key()
                index = chain.index(obj)
                target = None
                if key == Qt.Key_Down:
                    target = chain[(index + 1) % len(chain)]
                elif key == Qt.Key_Up:
                    target = chain[(index - 1) % len(chain)]
                elif key == Qt.Key_Home:
                    target = chain[0]
                elif key == Qt.Key_End:
                    target = chain[-1]
                if target is not None:
                    target.setFocus(Qt.TabFocusReason)
                    return True
                # QPushButton only answers Space unless it is a dialog's
                # default button; on a nav list Enter has to work too.
                if (key in (Qt.Key_Return, Qt.Key_Enter)
                        and isinstance(obj, QAbstractButton)):
                    obj.click()
                    return True
        return super().eventFilter(obj, event)

    # ── licence ───────────────────────────────────────────────────────────
    def set_entitlements(self, features, usable: bool = True):
        """Mark add-ons the licence doesn't cover.

        A padlock means one thing only: **you don't own this**. It must not
        also mean "we can't reach the server" — those need different actions
        from the customer, and padlocking a feature they have paid for tells
        them they've lost it. Availability is the banner's job; ownership is
        this. `usable` is accepted and ignored so callers need not care.

        Locked items stay **enabled**. Clicking one opens the pitch for it,
        which is the most useful thing that click can do — the customer has
        just told us exactly what they want. A greyed-out row sells nothing,
        and is indistinguishable from something broken.
        """
        for _, (row, label, icon_name, feature) in self._gated.items():
            unlocked = feature in features
            row.set_locked(not unlocked)
            row.setProperty("locked", not unlocked)
            if unlocked:
                row.setAccessibleName(i18n.t(label))
            else:
                # Said in words, not only in dimming: a screen reader gets the
                # state, and so does anyone who hovers.
                row.setToolTip(i18n.t(
                    "{addon} isn't in your licence — click to find out "
                    "about it").format(addon=i18n.t(label)))
                row.setAccessibleName(i18n.t(
                    "{addon} — not in your plan").format(addon=i18n.t(label)))
            row.style().unpolish(row)
            row.style().polish(row)

    def set_plan(self, title: str, detail: str, ok: bool = True):
        """The licence, on the profile row's second line.

        `detail` is the sentence — "Your licence is active", "Ended — renew to
        start new work". At 240px the plan NAME is what fits, so the sentence
        becomes the tooltip; but when something is actually wrong the sentence
        is the only part worth reading, so that case shows it instead.
        """
        self._profile_sub.set_full_text(title if ok else detail)
        self._profile_sub.setToolTip(f"{title} — {detail}" if ok else detail)
        self._profile_sub.setStyleSheet(
            theme.type_css("META", theme.over(INK_ITEM) if ok else theme.WARN)
            + " background: transparent;")

    def set_listening(self, on: bool):
        """Reflect wake-word state pushed back from the window (e.g. it
        refused to start because no API key is set)."""
        if self.wake_switch.isChecked() != on:
            self.wake_switch.blockSignals(True)
            self.wake_switch.setChecked(on)
            self.wake_switch.blockSignals(False)
        self._update_wake_symbol(on)

    def _update_wake_symbol(self, on: bool = False) -> None:
        if hasattr(self, "_wake_symbol"):
            hue = theme.ACCENT if on else theme.over(INK_CHROME)
            self._wake_symbol.setPixmap(icons.pixmap("mic", 18, hue))

    def is_collapsed(self) -> bool:
        return getattr(self, "_collapsed", False)

    def toggle_collapsed(self, collapsed: bool | None = None) -> None:
        """Toggle sidebar between expanded (240px) and collapsed rail (68px) symbols mode."""
        if collapsed is None:
            self._collapsed = not getattr(self, "_collapsed", False)
        else:
            self._collapsed = collapsed

        c = self._collapsed
        self.setFixedWidth(72 if c else 260)
        self.setProperty("collapsed", c)
        self.style().unpolish(self)
        self.style().polish(self)

        # Inner margins
        if hasattr(self, "_root_layout"):
            self._root_layout.setContentsMargins(
                8 if c else theme.SPACE_3,
                theme.SPACE_5,
                8 if c else theme.SPACE_3,
                theme.SPACE_3,
            )
        if hasattr(self, "_foot_col"):
            self._foot_col.setContentsMargins(
                8 if c else theme.SPACE_3,
                0,
                8 if c else theme.SPACE_3,
                theme.SPACE_3,
            )

        # Brand header
        if hasattr(self, "_brand_expanded"):
            self._brand_expanded.setVisible(not c)
        if hasattr(self, "_brand_collapsed"):
            self._brand_collapsed.setVisible(c)

        # Section WORK
        if hasattr(self, "_work_lbl"):
            self._work_lbl.setVisible(not c)
        if hasattr(self, "_work_collapsed_rule"):
            self._work_collapsed_rule.setVisible(c)

        # New task button
        if c:
            self.new_task_btn.setText("")
            self.new_task_btn.setFixedSize(48, 38)
            self.new_task_btn.setToolTip(i18n.t("New task"))
            self.new_task_btn.setIcon(C.brand_dot_icon(24, "plus"))
        else:
            self.new_task_btn.setText(i18n.t('New task'))
            self.new_task_btn.setMinimumHeight(C.MIN_TARGET + 6)
            self.new_task_btn.setMaximumWidth(16777215)
            self.new_task_btn.setMinimumWidth(0)
            self.new_task_btn.setMaximumHeight(16777215)
            self.new_task_btn.setToolTip(i18n.t("Describe something you want done"))
            icons.button_icon(self.new_task_btn, "plus", 15, "#ffffff")

        # Primary nav buttons
        for key, label, icon_name, tip in PRIMARY:
            btn = self._nav.get(key)
            if btn:
                if c:
                    btn.setText("")
                    btn.setFixedSize(48, 38)
                    btn.setToolTip(i18n.t(label))
                else:
                    btn.setText(f"  {_amp(i18n.t(label))}")
                    btn.setMinimumHeight(C.MIN_TARGET + 4)
                    btn.setMaximumWidth(16777215)
                    btn.setMinimumWidth(0)
                    btn.setMaximumHeight(16777215)
                    btn.setToolTip(i18n.t(tip))

        # ADD-ONS
        if hasattr(self, "_addons_head"):
            self._addons_head.setVisible(not c)
        if hasattr(self, "_addons_collapsed_rule"):
            self._addons_collapsed_rule.setVisible(c)
        for row in getattr(self, "_addon_rows", []):
            if hasattr(row, "set_collapsed"):
                row.set_collapsed(c)
            if c:
                row.setVisible(True)
            else:
                row.setVisible(getattr(self, "_addons_open", True))

        # Settings (MORE)
        for key, label, icon_name, tip in MORE:
            btn = self._nav.get(key)
            if btn:
                if c:
                    btn.setText("")
                    btn.setFixedSize(48, 38)
                    btn.setToolTip(i18n.t(label))
                else:
                    btn.setText(f"  {_amp(i18n.t(label))}")
                    btn.setMinimumHeight(C.MIN_TARGET + 4)
                    btn.setMaximumWidth(16777215)
                    btn.setMinimumWidth(0)
                    btn.setMaximumHeight(16777215)
                    btn.setToolTip(i18n.t(tip))

        # Favourites
        if hasattr(self, "_fav_wrap"):
            self._fav_wrap.setVisible(not c)
        if c:
            self.fav_list.setVisible(False)
        else:
            self.fav_list.setVisible(self.fav_toggle.isChecked())

        # Foot: Wake row (hidden per user requirement)
        if hasattr(self, "wake_row"):
            self.wake_row.setVisible(False)

        # Foot: Profile row
        if hasattr(self, "_profile_btn"):
            if c:
                self._profile_name.setVisible(False)
                self._profile_sub.setVisible(False)
                self._profile_chevron.setVisible(False)
                self._profile_btn.setFixedSize(48, 48)
                self._profile_btn_layout.setContentsMargins(0, 0, 0, 0)
                self._profile_btn_layout.setAlignment(Qt.AlignCenter)
                self._profile_btn.setToolTip(
                    f"{self._profile_name.full_text()} — {self._profile_sub.full_text()}")
            else:
                self._profile_name.setVisible(True)
                self._profile_sub.setVisible(True)
                self._profile_chevron.setVisible(True)
                self._profile_btn.setMinimumHeight(48)
                self._profile_btn.setMaximumWidth(16777215)
                self._profile_btn.setMinimumWidth(0)
                self._profile_btn.setMaximumHeight(16777215)
                self._profile_btn_layout.setContentsMargins(6, 6, 6, 6)
                self._profile_btn_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self._profile_btn.setToolTip(i18n.t("Your profile, licence and workspace"))

        self._refresh_nav()
        self._place_pip()
        self.collapsed_toggled.emit(c)

    def _toggle_addons(self, open_: bool | None = None) -> None:
        """Collapse or expand the add-on shelf."""
        if open_ is None:
            self._addons_open = not getattr(self, "_addons_open", True)
        else:
            self._addons_open = open_

        icons.button_icon(self._addons_toggle_btn,
                          "chevron-down" if self._addons_open else "chevron-right",
                          11, theme.over(INK_CHROME))
        if not getattr(self, "_collapsed", False):
            for row in getattr(self, "_addon_rows", []):
                row.setVisible(self._addons_open)
        self._place_pip()

    # ── favorites ─────────────────────────────────────────────────────────
    _FAV_ROW = 30
    _FAV_MAX = 5

    def _toggle_favorites(self, open_: bool) -> None:
        icons.button_icon(self.fav_toggle,
                          "chevron-down" if open_ else "chevron-right", 13,
                          theme.over(INK_CHROME))
        self.fav_list.setVisible(open_)
        self._fav_add.setVisible(open_)
        self._fav_del.setVisible(open_)
        self._fit_favorites()
        self._place_pip()

    def _size_favorites(self, count: int):
        """Pin the list to exactly the rows it holds, up to five. Past that it
        scrolls itself rather than pushing the rest of the rail down."""
        self._fav_count = count
        rows = max(1, min(count, self._FAV_MAX))
        self.fav_list.setFixedHeight(rows * self._FAV_ROW + 6)
        self._fit_favorites()

    def _fit_favorites(self):
        """…and never past the room the rail actually has.

        Five rows plus the nav plus the pinned foot is more than a 768px laptop
        has, so opening favourites there used to put the whole rail into a
        scroll — which is the one thing the twelve-control budget exists to
        prevent. The list is the only elastic thing in the column, so it is the
        thing that gives: it keeps its own internal scrollbar and shows as many
        rows as fit, down to one.
        """
        if not self.fav_list.isVisible():
            return
        rows = max(1, min(getattr(self, "_fav_count", 0), self._FAV_MAX))
        want = rows * self._FAV_ROW + 6
        # Everything in the column except the list itself.
        other = self._inner.sizeHint().height() - self.fav_list.height()
        room = self._scroll.viewport().height() - other
        self.fav_list.setFixedHeight(
            max(self._FAV_ROW + 6, min(want, room)))

    def reload_favorites(self):
        self.fav_list.clear()
        items = FAV.load()
        self._size_favorites(len(items))
        if not items:
            placeholder = QListWidgetItem(i18n.t("No favorites yet"))
            placeholder.setFlags(Qt.NoItemFlags)
            placeholder.setToolTip("Click + above to favorite a file or folder")
            self.fav_list.addItem(placeholder)
            return
        for item in items:
            name = "folder" if item["kind"] == "folder" else "file"
            li = QListWidgetItem(
                icons.icon(name, 15, theme.over(INK_CHROME)), item["label"])
            li.setData(_PATH_ROLE, item["path"])
            li.setToolTip(item["path"])
            self.fav_list.addItem(li)

    def _add_favorite(self):
        path = QFileDialog.getExistingDirectory(self, i18n.t("Favorite a folder…"))
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, i18n.t("…or favorite a file"))
        if not path:
            return
        FAV.add(path)
        self.reload_favorites()

    def _remove_favorite(self):
        it = self.fav_list.currentItem()
        if not it or not it.data(_PATH_ROLE):
            return
        FAV.remove(it.data(_PATH_ROLE))
        self.reload_favorites()

    def _favorite_clicked(self, item: QListWidgetItem):
        path = item.data(_PATH_ROLE)
        if path:
            self.favorite_chosen.emit(path)

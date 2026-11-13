"""What every screen in this folder is built out of.

Split out of widgets/simple_panels.py, which was six screens and their
shared furniture in one 1,581-line file. Three of those screens are core
(Guide, Catalog, History) and three are add-on front doors (BOQ, BOM,
Gerber), so the file could not move into addons/ and could not stay where it
was either.

Three names lost their leading underscore on the way out, because a private
name imported from four other modules is a public name nobody renamed:

    _Page            -> Page
    _bucket          -> bucket_for
    _AddonFrontDoor  -> AddonFrontDoor

_AddonFrontDoor is the interesting one. It is already a declarative manifest
in all but name -- ICON, HUE, HEADLINE, DETAIL, ACTION, STEPS, PLACEHOLDERS,
KIND, LAZY, RELOAD_ON_SHOW, SCAN as class attributes, plus opened/open_run/
navigate signals -- which is why the add-on manifest borrows its shape rather
than inventing a second idiom.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import core_bridge as CB
import dashboard_data as DATA
import i18n
import theme
from addons import registry
from widgets import controls as C
from widgets import icons


LABELS = {
    "research": "Research",
    "leads": "Leads",
    "brains": "Reasoning",
    "content": "Writing",
    "visual": "Images",
    "media": "Video",
    "audio": "Audio",
    "development": "Apps",
    "presentation": "Decks",
}

# Which add-on wrote a run record, in the word a History row wears.
# DERIVED from addons/registry.py. This was the third list of the same
# add-ons and it had its own membership again -- no inquiry, unlike the other
# two -- which is now simply "the ones that write run records", i.e. the ones
# with a kind. The short names come from the manifest's `chip` field: the
# pill has room for "Reel", not "Reel / Studio".
ADDONS = {a.kind or a.key: a.chip_label()
          for a in registry.REGISTRY if a.run_prefixes}

# History's date groups, coarsest last. Returned by bucket_for() and translated
# at render time — the literals are here so the extractor can see them.
SECTIONS = ("Today", "Yesterday", "Earlier this week", "Last week",
            "Two weeks ago", "Three weeks ago", "Earlier this month", "Older")

# A leading line icon per category, for the pipeline cards. Icon names, not
# copy — every one is lowercase and alphanumeric so the string extractor's
# identifier test rejects it. Do NOT put a hyphenated icon name in here; it
# would read as prose and land in front of a translator.
_CATEGORY_ICONS = {
    "research": "book", "leads": "user", "brains": "bulb", "content": "pencil",
    "visual": "image", "media": "video", "audio": "mic", "development": "code",
    "presentation": "present", "summary": "list",
}

# How each add-on stamps the run record it saves, so a History row and an
# add-on's own "recent runs" list can both recognise its work. Matched with
# str.startswith against stored data and never shown to anyone, which is why
# this table is deliberately NOT named after one of the extractor's copy
# tables — a translated match prefix would match nothing.
#   boq_dialog.py:351     f"BOQ — {self.request}"
#   gerber_dialog.py:247  f"Gerber — {…}"
#   email_dialog.py:604   f"/email {goal}"
#   prism.py (the CLI)    "/boq …", "/email …", "/reel …"
# DERIVED. The hand-written version carried a comment listing the four OTHER
# files whose f-strings it was matching against -- boq_dialog, gerber_dialog,
# email_dialog and the CLI's prism.py -- with nothing tying them together and
# no test that would notice if one changed. Change a title f-string and
# History silently stopped recognising that add-on's runs.
#
# They still have to agree with those f-strings; what has changed is that
# there is now one place to look, and tests/test_addon_contract.py asserts
# these are unique and never translatable.
_RUN_PREFIXES = tuple((a.kind or a.key, a.run_prefixes)
                      for a in registry.REGISTRY if a.run_prefixes)

# dashboard_data.recent_runs() substitutes this when a record carries no query
# at all. Matching the sentinel is the only way, from the shaped row, to tell
# "the user never typed anything" from "the user typed something and it broke"
# — see ## WIRING NEEDED, which asks for an explicit flag instead.
_NO_QUERY = "Untitled task"


# ── small shared helpers ────────────────────────────────────────────────────
def _tip(text: str) -> str:
    """A tooltip that keeps its own colours. A tooltip inherits the style
    sheet of the widget it hangs off, so a label styled with dark text put
    dark text on the tooltip's black background (seen on the STEP recent-runs
    list, 15 Oct 2026). Rich text carries its colour with it."""
    import html
    return ("<div style='color:#ffffff'>"
            + html.escape(text or "").replace("\n", "<br>") + "</div>")


class _Elided(QLabel):
    """A single-line label that is allowed to shrink.

    This exists because of a measured defect, not for tidiness. A plain QLabel
    reports its full text width as its layout minimum, so ONE long run title
    drags the whole page wider than the window and the user gets a horizontal
    scrollbar on a list screen — audit_ui.py caught History overflowing by
    74px at 1366x768 and 160px at 1280x800 while looking perfectly fine at
    1440x900 with that hour's data.

    So: a small minimum width, a size policy that lets the layout squeeze it,
    and the text elided to whatever width it actually got. The full string
    stays in the tooltip, so nothing is lost.

    The font is set as a real QFont as well as in the stylesheet. Both come
    from theme, so they agree — but the QFont is what QFontMetrics measures,
    and style.qss's `* { font-size: 14px }` would otherwise make every
    elision computation wrong by a couple of characters.
    """

    MIN_W = 64

    def __init__(self, text: str = "", level: str = "BODY", colour: str = "",
                 weight: int = 0, grow: bool = True, min_w: int = 0,
                 max_w: int = 0, mode=Qt.ElideRight, parent=None,
                 px: int = 0):
        super().__init__(parent)
        self._full = text or ""
        self._mode = mode
        font = theme.font(level, weight)
        if px:
            font.setPixelSize(px)
        self.setFont(font)
        family, size, css_weight, ink = theme.TYPE.get(level, theme.T_BODY)
        px = px or size
        stack = (theme.FONT_MONO_STACK if level == "MONO" else f"'{family}'")
        self.setStyleSheet(
            f"font-family: {stack}; font-size: {px}px;"
            f" font-weight: {weight or css_weight}; color: {colour or ink};"
            f" background: transparent;")
        # Ignored, not Preferred: Ignored drops the sizeHint entirely, which is
        # what lets a long title give its width back to the row instead of
        # taking it from everything else.
        self.setSizePolicy(QSizePolicy.Ignored if grow else QSizePolicy.Preferred,
                           QSizePolicy.Fixed)
        self.setMinimumWidth(min_w or self.MIN_W)
        if max_w:
            self.setMaximumWidth(max_w)
        if self._full:
            self.setToolTip(_tip(self._full))
        self._apply()

    def set_full_text(self, text: str):
        self._full = text or ""
        self.setToolTip(_tip(self._full))
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self):
        metrics = QFontMetrics(self.font())
        width = max(self.minimumWidth(), self.width())
        QLabel.setText(self, metrics.elidedText(self._full, self._mode, width))


class _ActionCard(C.Card):
    """A card that is a link. Icon, name, one line, and it goes somewhere.

    Used by the guide's "Where things are" section. A Card subclass rather
    than a sixth card recipe, and keyboard-reachable because a card that only
    a mouse can activate is a control that half the audit does not see.
    """

    clicked = Signal()

    def __init__(self, icon: str, title: str, body: str, parent=None):
        super().__init__(parent=parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        # Card sets a plain "#card { … }" rule with no interactive states, so
        # a focused card would be indistinguishable from a resting one. The
        # resting half is re-declared identically rather than added to,
        # because a widget stylesheet REPLACES the app rule for this widget.
        self.setStyleSheet(
            f"#card {{ background: {theme.CARD};"
            f" border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.HAIRLINE}; }}"
            f"#card:hover {{ border-color: {theme.NEUTRAL[300]}; }}"
            f"#card:focus {{ border-color: {theme.ACCENT}; }}")
        col = self.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15))
        top.addWidget(_Elided(title, "CARD_TITLE"), stretch=1)
        arrow = QLabel()
        arrow.setPixmap(icons.pixmap("chevron-right", 15, theme.NEUTRAL[500]))
        top.addWidget(arrow)
        col.addLayout(top)
        col.addWidget(_wrapped(body, "META"))
        self.setAccessibleName(f"{title}. {body}")

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


def _wrapped(text: str, level: str = "SUPPORT", colour: str = "") -> QLabel:
    """A wrapping paragraph that is also allowed to shrink.

    Same reasoning as _Elided: an explicit minimumWidth replaces whatever the
    layout would otherwise compute from the text, which is what keeps a card
    grid from forcing the page wider than the window.
    """
    lbl = C.label(text, level=level, colour=colour, wrap=True)
    lbl.setMinimumWidth(80)
    return lbl


def _clip(text: str, limit: int = 104) -> str:
    """The opening of a registry `specialty`, cut on a word boundary.

    The registry writes some of these as whole paragraphs (ChatGPT's runs to
    nine lines). A card grid needs every card to be roughly one height, and
    the full text is one tooltip away, so the card shows the claim and not the
    essay. Truncating what is displayed is not the same as inventing it.
    """
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(" ,;.:—-") + "…"


def _kind_of(title: str) -> str:
    """Which add-on wrote this run record, or "" for a workbench task."""
    title = title or ""
    for kind, prefixes in _RUN_PREFIXES:
        for prefix in prefixes:
            if title.startswith(prefix):
                return kind
    return ""


def _plain_title(title: str) -> str:
    """A run's title with the add-on's own prefix taken off, so a BOQ row
    reads "Quantities for the shed" and not "BOQ — Quantities for the shed"
    next to a chip that already says BOQ."""
    title = title or ""
    for _kind, prefixes in _RUN_PREFIXES:
        for prefix in prefixes:
            if title.startswith(prefix):
                return title[len(prefix):].strip() or title
    return title


def _state_of(run: dict) -> str:
    """One run as a theme.STATUS state: completed, failed, or cancelled.

    The third one is the whole point, and it is a DISPLAY decision — nothing
    is deleted, hidden from the counts, or made unopenable.

    Real user data on this machine holds 86 records out of 103 with no query
    text, no tool and the error "Chrome would not launch". Nothing was ever
    attempted in any of them. Rendering those in red as FAILED, six in a row,
    makes Prism look like a product that does not work — when what actually
    happened is that it never started. `cancelled` is the state the system
    already has for that: neutral tone, square dot, outside the error colour.

    They are still listed, still counted on their own filter chip, and still
    open their record when clicked. Suppressing them was the alternative and
    it is worse: 86 identical aborts is the single most useful diagnostic
    signal in this History, and a user who cannot see them cannot report it.
    """
    if run.get("ok"):
        return "completed"
    if not run.get("tools") and (run.get("title") or "").strip() == _NO_QUERY:
        return "cancelled"
    return "failed"


def bucket_for(when: str, stamp: float = 0.0) -> str:
    """Which date group a run belongs to.

    Driven by the raw mtime `recent_runs` now returns. It used to read
    `_ago()`'s English instead, and that had one bad consequence: every
    phrasing containing "week" — one week or four — landed in a single
    bucket. A workspace with a month of history therefore rendered as one
    undated heap headed "Earlier this month · 78 runs", which is not an
    ordering a person can read even though the rows inside it were in
    perfect order.

    The English is still accepted as a fallback so a caller that has no
    stamp (an older record, a test fixture) keeps working.
    """
    if stamp:
        import time
        days = max(0.0, (time.time() - stamp) / 86400.0)
        if days < 1:
            return SECTIONS[0]          # Today
        if days < 2:
            return SECTIONS[1]          # Yesterday
        if days < 7:
            return SECTIONS[2]          # Earlier this week
        if days < 14:
            return SECTIONS[3]          # Last week
        if days < 21:
            return SECTIONS[4]          # Two weeks ago
        if days < 28:
            return SECTIONS[5]          # Three weeks ago
        if days < 60:
            return SECTIONS[6]          # Earlier this month
        return SECTIONS[7]              # Older

    text = (when or "").strip().lower()
    if text == "yesterday":
        return SECTIONS[1]
    if text == "just now" or text.endswith("m ago") or "hour" in text:
        return SECTIONS[0]
    if "day" in text:
        return SECTIONS[2]
    if "week" in text:
        return SECTIONS[6]
    return SECTIONS[7]


def _focusable_row(widget: QFrame):
    """Give a clickable list row its hover and focus states.

    style.qss defines #rowFlat and #rowFlat:hover but no :focus, so a row
    reached by keyboard looked exactly like a row that was not — which makes
    tabbing through History indistinguishable from doing nothing. The border
    is always there and only changes colour, so gaining focus never reflows
    the row underneath the cursor.
    """
    widget.setStyleSheet(
        f"#rowFlat {{ background: transparent;"
        f" border: 1px solid transparent;"
        f" border-radius: {theme.R_CONTROL}px; }}"
        f"#rowFlat:hover {{ background: {theme.WELL}; }}"
        f"#rowFlat:focus {{ background: {theme.WELL};"
        f" border-color: {theme.ACCENT}; }}")
    return widget


def _tool_line(tool: str | None) -> QWidget:
    """A tool's badge and name, or the fact that no tool is set.

    Shared by the AI tools pipeline cards and the add-on screens, so "which
    tool runs this" reads identically wherever the question comes up.
    """
    wrap = QFrame()
    row = QHBoxLayout(wrap)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(theme.SPACE_2)
    if tool:
        row.addWidget(C.ToolBadge(tool, 22, theme.R_MICRO))
        row.addWidget(_Elided(tool, "SUPPORT", theme.TEXT, weight=600),
                      stretch=1)
    else:
        row.addWidget(C.Pill(i18n.t("Not picked"), "quiet"))
        row.addStretch(1)
    return wrap


def _categories_of(tool: str) -> list[str]:
    """Every category that offers this tool, in pipeline order.

    A tool appearing more than once is deliberate and documented in the
    registry — LAZYCOOK is offered under four categories, Claude under four —
    so the card states all of them rather than picking one and looking like a
    duplicate.
    """
    out = []
    for stage in CB.agents.PIPELINE_ORDER:
        meta = CB.agents.CATEGORIES.get(stage)
        if meta and tool in meta.get("agents", ()):
            out.append(stage)
    return out


# ── the page scaffold every screen here uses ────────────────────────────────
class Page(QWidget):
    """A fixed PageHeader, then a scrolling column with page padding.

    The header never scrolls; the column is rebuilt by refresh(). Subclasses
    implement build() and add to self._col.

    build() owns what happens to the leftover height, and that is the whole
    fix for these screens. Finish with self._col.addStretch(1) only when there
    is real content above it; otherwise hand the slack to a C.EmptyState added
    with stretch=1, which centres in it. The one thing build() must never do
    is top-anchor a small card and leave a grey field beneath.

    LAZY defers the first build until the screen is actually shown, so a panel
    that reads run records off a (possibly shared, possibly slow) folder costs
    nothing at startup — MainWindow constructs all eleven screens in its own
    __init__.
    """

    TITLE = ""
    BLURB = ""
    MAX_W = 0                   # 0 = fill the width
    LAZY = False                # don't touch the disk until shown
    RELOAD_ON_SHOW = False      # re-read every time the screen is opened

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._built = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = C.PageHeader(i18n.t(self.TITLE),
                                   i18n.t(self.BLURB) if self.BLURB else "",
                                   self.header_actions())
        root.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._scroll.setWidget(host)
        frame = QHBoxLayout(host)
        frame.setContentsMargins(theme.PAGE_PAD, theme.PAGE_PAD, theme.PAGE_PAD,
                                 theme.PAGE_PAD)
        frame.setSpacing(0)
        holder = QWidget()
        if self.MAX_W:
            holder.setMaximumWidth(self.MAX_W)
        self._col = QVBoxLayout(holder)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(theme.CARD_GAP)
        frame.addWidget(holder, stretch=1)
        root.addWidget(self._scroll, stretch=1)

        self.refresh()

    # -- overridable ------------------------------------------------------
    def header_actions(self) -> list:
        """Already-built widgets for the header's right-hand side. Exactly one
        primary per surface."""
        return []

    def build(self):
        raise NotImplementedError

    # -- lifecycle --------------------------------------------------------
    def refresh(self):
        self.header.title.setText(i18n.t(self.TITLE))
        self.header.set_subtitle(i18n.t(self.BLURB) if self.BLURB else "")
        self._drop(self._col)
        if self.LAZY and not self.isVisible():
            self._built = False
            return
        self._built = True
        self.build()

    def showEvent(self, event):
        super().showEvent(event)
        if self.LAZY and (not self._built or self.RELOAD_ON_SHOW):
            self.refresh()

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            # Held in a local, deliberately. `item.widget().setParent(None)`
            # hands ownership back to Python, and with no reference kept the
            # widget is collected on the spot — so a second `item.widget()`
            # on the next line returns None and the reparenting crashes the
            # rebuild.
            widget = item.widget()
            if widget is not None:
                # Hidden first: setParent(None) on a visible widget makes it a
                # top-level OS window for a frame — the ghost-window flash.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._drop(child)


# ── Guide ───────────────────────────────────────────────────────────────────

# Shared furniture, not History's alone: AddonFrontDoor below renders
# the same row for an add-on's own recent runs. Keeping it here is what
# stopped panel_base having to import a panel, which the split made
# visible -- the base referencing HistoryPanel's private row widget was
# a dependency pointing the wrong way the whole time.
class _RunRow(QFrame):
    """One run: what was asked, which tools ran it, when, and how it ended.

    Keyboard reachable, which the old row was not — it was a bare QFrame with
    mousePressEvent monkey-patched onto the instance, so the entire History
    screen was unreachable without a mouse.
    """

    activated = Signal()
    # Opt-in, both off unless the screen asks. This row is shared -- the
    # add-on front doors draw it too -- and none of them wants a checkbox.
    picked = Signal(bool)                       # tick state changed
    removed = Signal()                          # the row's own delete

    def __init__(self, run: dict, state: str, parent=None, *,
                 selectable: bool = False, deletable: bool = False):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        _focusable_row(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(C.MIN_TARGET + 22)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_4, 10, theme.SPACE_4, 10)
        row.setSpacing(theme.SPACE_3)

        self.tick = None
        if selectable:
            self.tick = QCheckBox()
            self.tick.setFixedWidth(20)
            self.tick.setAccessibleName(i18n.t("Select this run"))
            # The box is its own control: clicking it must tick, not open
            # the run, so it swallows the press rather than letting the
            # row's mousePressEvent see it.
            self.tick.toggled.connect(self.picked.emit)
            row.addWidget(self.tick)

        kind = _kind_of(run.get("title", ""))
        title = _plain_title(run.get("title", ""))

        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(_Elided(title, "SUPPORT", theme.TEXT, weight=400,
                                px=14))

        under = QHBoxLayout()
        under.setContentsMargins(0, 0, 0, 0)
        under.setSpacing(theme.SPACE_1)
        tools = run.get("tools") or []
        # Three badges at most. Six of them is 130px of fixed width fighting
        # the title for the row, and the names are spelled out beside them.
        for tool in tools[:3]:
            under.addWidget(C.ToolBadge(tool, 18, theme.R_MICRO))
        if tools:
            under.addSpacing(theme.SPACE_1)
        under.addWidget(_Elided(" · ".join(tools) or i18n.t("No tool recorded"),
                                "META", theme.MUTE, weight=400, px=12),
                        stretch=1)
        stack.addLayout(under)
        row.addLayout(stack, stretch=1)

        if kind:
            row.addWidget(C.Pill(i18n.t(ADDONS[kind]).upper(), "tag"))
        row.addWidget(_Elided(run.get("when", ""), "LABEL", grow=False,
                              min_w=76, max_w=118, px=11))
        detail = i18n.t("never ran") if state == "cancelled" else ""
        row.addWidget(C.StatusBadge(state, detail, focusable=False))

        if deletable:
            binw = C.icon_button("trash", i18n.t("Delete this run"),
                                 self.removed.emit, colour=theme.MUTE)
            row.addWidget(binw)

        self.setAccessibleName(f"{title}. {run.get('when', '')}")
        self.setToolTip(_tip(run.get("title", "") or title))

    def mousePressEvent(self, event):
        # A press that landed on the tick box or the bin belongs to them.
        # Without this, ticking a row also opened it.
        child = self.childAt(event.position().toPoint())
        while child is not None and child is not self:
            if isinstance(child, (QCheckBox, QPushButton)):
                return super().mousePressEvent(event)
            child = child.parentWidget()
        self.activated.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class AddonFrontDoor(Page):
    """One add-on as a product module: what it does, what it has produced on
    this machine, and the way in.

    Built to be subclassed — set the class attributes, and override
    status_block() if the add-on knows something real about its own
    configuration (EmailPanel does; it knows the sending address). Every
    add-on screen should come through here rather than copying the layout: the
    inquiry screen has its own hand-copied version of the old one-card shape
    and that is exactly how six screens drifted apart in the first place.

    Recent activity is read, not invented. Add-on dialogs stamp the run record
    they save with their own prefix, so an add-on can recognise its own work
    in the same store History reads.
    """

    ICON = "file"
    HUE = None
    HEADLINE = ""
    DETAIL = ""
    ACTION = ""
    ACTION_ICON = "paperclip"
    STEPS = []                  # [(icon, title, body)] — what it actually does
    # [(example ask, the note beside it)]. Lifted verbatim from the add-on
    # dialog's own AskPanel placeholder, so the front door and the dialog
    # cannot end up teaching two different things — "what do I actually type"
    # is the first question every one of these gets, and the answer used to
    # only exist inside a modal you had to open to read it.
    PLACEHOLDERS = []
    KIND = ""                   # the run-record prefix key in _RUN_PREFIXES

    LAZY = True
    RELOAD_ON_SHOW = True       # a run finished in the dialog must show here
    # How far back to look for this add-on's own work. The same depth History
    # reads, because an add-on used twice a month is otherwise buried under a
    # month of workbench runs and its screen says "nothing yet" while its
    # output sits in History two screens away. Paid for only when the screen
    # is actually opened — see Page.LAZY.
    SCAN = 200

    opened = Signal()
    open_run = Signal(str)      # path of a run record, same as History's
    navigate = Signal(str)      # a key for MainWindow._handle_command

    def header_actions(self):
        if not self.ACTION:
            return []
        return [
            C.button(i18n.t(self.ACTION), "secondary",
                     icon_name=self.ACTION_ICON,
                     on_click=self.opened.emit),
        ]

    # -- overridable ------------------------------------------------------
    def status_block(self) -> QWidget | None:
        """Something the add-on genuinely knows about its own setup, shown on
        the right of the banner. None if it knows nothing."""
        return None

    def tool_roles(self) -> list:
        """[(icon, what it does, why that one, the tool)] — which of the
        user's own configured tools this add-on will actually reach for.

        Not a guess. Every add-on dialog picks its agent by a fixed rule off
        CB.config.active_agents(cfg) and refuses to run if the rule finds
        nothing, so the answer is knowable before you open the dialog — and
        "No writing agent set up yet" arriving as a modal AFTER you attached
        a drawing is the wrong moment to learn it.

        It is also the join the owner asked for: the add-ons stop being
        separate products the moment the screen says which of your tools runs
        them, in the same badge the AI tools screen uses.
        """
        return []

    def _agents(self) -> dict:
        """The user's configured tools, by category — the same call the
        add-on dialogs make when they choose one."""
        try:
            return CB.config.active_agents(self.cfg) or {}
        except Exception:                                   # noqa: BLE001
            return {stage: tool
                    for stage, tool in (self.cfg.get("agents") or {}).items()
                    if tool}

    # -- build ------------------------------------------------------------
    def build(self):
        runs = self._recent()
        if runs:
            self._col.addWidget(C.SectionHeader(
                i18n.t("Recent runs"),
                i18n.t("Read back out of the stored records, same as History.")))
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)
            for i, run in enumerate(runs):
                if i:
                    col.addWidget(C.hairline())
                row = _RunRow(run, _state_of(run))
                row.activated.connect(
                    lambda p=run.get("path", ""): p and self.open_run.emit(p))
                col.addWidget(row)
            self._col.addWidget(card)

        if self.STEPS:
            self._col.addWidget(C.SectionHeader(
                i18n.t("How it works"),
                i18n.t("Fast, automated workflow from drawing to finished document.")))
            self._col.addWidget(self._steps_card(self.STEPS))

        if self.PLACEHOLDERS:
            self._col.addWidget(C.SectionHeader(
                i18n.t("What you can ask for"),
                i18n.t("Click an example or type your own prompt in the dialog.")))
            self._col.addWidget(self._examples_card(self.PLACEHOLDERS))
        self._col.addStretch(1)

    def _steps_card(self, steps: list) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), spacing=0)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_4)
        for i, (icon, title, body) in enumerate(steps):
            if i:
                row.addWidget(C.hairline(vertical=True))
            step_box = QVBoxLayout()
            step_box.setContentsMargins(theme.SPACE_2, 0, theme.SPACE_2, 0)
            step_box.setSpacing(theme.SPACE_2)

            top = QHBoxLayout()
            top.setSpacing(theme.SPACE_2)
            top.addWidget(C.IconPad(icon, self.HUE or theme.ACCENT, 26,
                                    theme.R_CONTROL, 13))
            top.addWidget(C.kicker(f"{i + 1:02d}"), stretch=1)
            step_box.addLayout(top)

            step_box.addWidget(C.label(i18n.t(title), level="CARD_TITLE", size=14, weight=600, wrap=True))
            step_box.addWidget(C.label(i18n.t(body), level="META", size=12, colour=theme.NEUTRAL[600], wrap=True))
            step_box.addStretch(1)

            row.addLayout(step_box, stretch=1)
        col.addLayout(row)
        return card

    def _examples_card(self, placeholders: list) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (text, note) in enumerate(placeholders):
            if i:
                col.addWidget(C.hairline())
            row = QHBoxLayout()
            row.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
            row.setSpacing(theme.SPACE_3)

            icon = C.IconPad("mic", self.HUE or theme.ACCENT, 28,
                            theme.R_CONTROL, 14)
            row.addWidget(icon, alignment=Qt.AlignTop)

            stack = QVBoxLayout()
            stack.setSpacing(2)
            stack.addWidget(C.label(f"“{i18n.t(text)}”", level="CARD_TITLE", size=14, weight=600, wrap=True))
            if note:
                stack.addWidget(C.label(i18n.t(note), level="META", size=13, colour=theme.NEUTRAL[600], wrap=True))
            row.addLayout(stack, stretch=1)

            btn = C.button(i18n.t("Try this"), "secondary", small=True,
                           on_click=self.opened.emit)
            row.addWidget(btn, alignment=Qt.AlignVCenter)

            col.addLayout(row)
        return card

    def _role_card(self, icon: str, title: str, note: str,
                   tool: str) -> QWidget:
        card = C.Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, self.HUE or theme.ACCENT, 30,
                                theme.R_CONTROL, 15), alignment=Qt.AlignTop)
        top.addWidget(_wrapped(i18n.t(title), "CARD_TITLE"), stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(note), "META"))
        col.addWidget(C.hairline())
        col.addWidget(_tool_line(tool))
        return card

    def _example_card(self, text: str, note: str) -> QWidget:
        card = C.Card()
        card.setMinimumHeight(120)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad("mic", self.HUE or theme.ACCENT, 26,
                                theme.R_CHIP, 14), alignment=Qt.AlignTop)
        top.addWidget(_wrapped("“" + i18n.t(text) + "”", "SUPPORT", theme.TEXT),
                      stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(note), "META"))
        return card

    def _recent(self, limit: int = 8) -> list:
        try:
            runs = DATA.recent_runs(self.cfg, self.SCAN) or []
        except Exception:                                   # noqa: BLE001
            return []
        return [run for run in runs
                if _kind_of(run.get("title", "")) == self.KIND][:limit]

    def _banner(self, runs: list) -> QWidget:
        hue = self.HUE or theme.ACCENT
        card = C.Card()
        row = QHBoxLayout(card)
        row.setContentsMargins(theme.CARD_PAD, theme.CARD_PAD,
                               theme.CARD_PAD, theme.CARD_PAD)
        row.setSpacing(theme.SPACE_5)
        row.addWidget(C.IconPad(self.ICON, hue, 52, theme.R_CARD, 24),
                      alignment=Qt.AlignTop)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        col.addWidget(_wrapped(i18n.t(self.HEADLINE), "SECTION"))
        col.addWidget(_wrapped(i18n.t(self.DETAIL), "SUPPORT"))
        row.addLayout(col, stretch=1)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(theme.SPACE_2)
        side.setAlignment(Qt.AlignTop | Qt.AlignRight)
        extra = self.status_block()
        if extra is not None:
            side.addWidget(extra, alignment=Qt.AlignRight)
        if runs:
            side.addWidget(C.Pill(
                i18n.t("1 run here") if len(runs) == 1
                else i18n.t("{n} runs here").format(n=len(runs)), "neutral"),
                alignment=Qt.AlignRight)
        row.addLayout(side)
        return card

    def _step_card(self, index: int, icon: str, title: str, body: str):
        card = C.Card()
        card.setMinimumHeight(120)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(icon, self.HUE or theme.ACCENT, 30,
                                theme.R_CONTROL, 15))
        top.addWidget(C.kicker(f"{index:02d}"), stretch=1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(title), "CARD_TITLE"))
        col.addWidget(_wrapped(i18n.t(body), "META"))
        return card



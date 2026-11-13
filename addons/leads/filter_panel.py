"""
Leads & Outreach — lead filters, the Apollo / Sales Navigator column
─────────────────────────────────────────────────────────────────────
Who a list is for, as filters. Every facet holds values to INCLUDE and values
to EXCLUDE — "Location: anywhere, except India" — shown as chips under the
facet's name: the info tint for in, the error tint with a leading minus for
out. A click on a chip flips its side; its small x removes it. Seniority and
Function pick from fixed lists, company headcount, annual revenue and years in
the role are multi-select bands, and "changed jobs in the last 90 days" is a
switch.

The panel only EDITS a `prospector.filters.SearchSpec`. What a filter means —
which includes steer the Exa search and which are enforced on every person who
comes back — lives beside the engine, not here. Inside the panel the spec is
the single source of truth: an edit changes the spec, then every widget is
redrawn from it, so a chip can never say something a run will not ask.

No scroll area of its own. The cockpit's rail (addons/leads/cockpit.py)
scrolls it at ~280px of content width, so nothing in here may ask for more:
long values elide instead of widening the rail, and rows of chips and bands
wrap (widgets.controls.FlowLayout) instead of clipping.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStyle,
    QStyleOption, QToolButton, QVBoxLayout, QWidget,
)

import i18n
import theme
from widgets import controls as C
from widgets import icons
from prospector.filters import (
    BAND_FACETS, CLOSED_FACETS, EMAIL_STATUS, FACET_LABELS, GUIDES_ONLY,
    HEADCOUNT, IMPORT_FACETS, INDUSTRY_SUGGESTIONS, LOCAL_FACETS,
    LOCATION_SUGGESTIONS, RECORD_GROUPS, REVENUE, TITLE_SUGGESTIONS,
    YEARS_IN_ROLE, SearchSpec, custom_key, label_of, parse_location_text,
    read_place_text, split_custom_key,
)

# Apollo's rail, top to bottom (23-Sep-2026: "copy the entire architecture and
# interface of apollo"). The facets a search nearly always starts from are
# always there — Apollo pins Job Titles, Company, Location, Industry — with the
# two CSV imports beside them, because a sheet the owner brought is where half
# of his searches start. The rest wait under "More filters" (Apollo's "View
# 60+ Filters") unless one of them is SET: an active filter is pinned into the
# rail, the way Apollo shows "Contact CSV Import ×1" once it is applied.
# "changed_jobs_90d" is the one switch, not a facet.
_PINNED = ("job_titles", "seniority", "companies", "locations", "industries",
           "contact_imports", "account_imports")
_MORE = ("lists", "stages", "functions", "keywords", "headcount", "revenue",
         "company_hq", "years_in_role", "changed_jobs_90d", "email_status", "scores",
         "custom_fields")
# Stage and Lists: ONE filter each with Apollo's switch between the contact's
# and the account's side ("Stage > Contact or Account"; "Lists > People or
# Company"). (facet, switch label, what a chip says before an account value).
_RECORD_SIDES = {
    "stages": (("contact_stages", "Contact", ""), ("account_stages", "Account", "Account")),
    "lists": (("contact_lists", "People", ""), ("account_lists", "Company", "Company")),
}
_CUSTOM_SIDES = (("contact", "Contact"), ("account", "Account"))
# The Companies page's rail is this same panel over the company-level facets
# (kind="company"). Apollo's Companies page pins # of employees, Company,
# Industry and Location and keeps the rest behind More filters; stage, lists
# and custom fields there are the ACCOUNT's, so each has the one side.
_COMPANY_PINNED = ("companies", "company_hq", "industries", "headcount")
_COMPANY_MORE = ("stages", "lists", "keywords", "revenue", "account_imports",
                 "custom_fields")
_COMPANY_LABELS = {"companies": "Company", "company_hq": "Location",
                   "industries": "Industry", "headcount": "# of employees",
                   "revenue": "Annual revenue", "stages": "Stage", "lists": "Lists",
                   "keywords": "Keywords", "account_imports": "Account CSV import",
                   "custom_fields": "Custom fields"}
_COMPANY_SIDES = {"stages": (("account_stages", "Account", ""),),
                  "lists": (("account_lists", "Company", ""),)}
_COMPANY_CUSTOM_SIDES = (("account", "Account"),)
_COMPANY_CATEGORIES = (("company", "Company"), ("records", "Your records"))
_COMPANY_OPEN_AT_START = frozenset({"companies", "company_hq"})
# What a record facet says when there is nothing to pick yet.
_RECORD_EMPTY = {
    "contact_stages": "",
    "account_stages": "",
    "contact_lists": "No lists yet — tick people and use Add to list.",
    "account_lists": "No company lists yet — an accounts import can add its "
                     "companies to one.",
}
# The All filters window's groups (addons/leads/all_filters.py), and which
# group each filter sits in.
CATEGORIES = (("person", "Person"), ("company", "Company"),
              ("records", "Your records"), ("scores", "Scores"))
CATEGORY_OF = {
    "job_titles": "person", "seniority": "person", "functions": "person",
    "locations": "person", "years_in_role": "person", "changed_jobs_90d": "person",
    "email_status": "person",
    "companies": "company", "industries": "company", "keywords": "company",
    "headcount": "company", "revenue": "company", "company_hq": "company",
    "contact_imports": "records", "account_imports": "records", "lists": "records",
    "stages": "records", "custom_fields": "records",
    "scores": "scores",
}
_CUSTOM_EMPTY = ("No custom fields yet — the columns an imported sheet brings that "
                 "Prism has no field for show up here.")
_MAX_CUSTOM_VALUES = 24      # a custom field's most-used values offered
_SEP = "\x1f"               # a record chip's value: facet, then the value
_IMPORT_KIND = {"contact_imports": "contacts", "account_imports": "accounts"}
# Where nearly every search starts, so these two open with the panel.
_OPEN_AT_START = frozenset({"locations", "job_titles"})
_BANDS = {"headcount": HEADCOUNT, "revenue": REVENUE, "years_in_role": YEARS_IN_ROLE,
          "email_status": EMAIL_STATUS}
# Facets whose editor SHOWS its choices when open (a checked band, a ticked
# import, the score controls) — their chips hide then (_Section._sync_chips).
_SHOWS_CHOSEN = frozenset(BAND_FACETS) | frozenset(IMPORT_FACETS) \
    | frozenset(LOCAL_FACETS) | {"scores"}
# Bands checked on the company's record (filters.match_company). A company
# whose size is not on record is let through and counted unverified, and the
# editor says so — a band reads like a promise otherwise.
_ON_RECORD = frozenset({"headcount", "revenue"})
_PLACEHOLDERS = {
    "locations": "Add a country, region or city",
    "job_titles": "Add a job title",
    "seniority": "Find a seniority level",
    "functions": "Find a function",
    "industries": "Add an industry",
    "companies": "Add a company",
    "company_hq": "Add a country, region or city",
    "keywords": "Add a keyword",
    "stages": "Find a stage",
    "lists": "Find a list",
}
_STATIC = {
    "locations": LOCATION_SUGGESTIONS, "company_hq": LOCATION_SUGGESTIONS,
    "job_titles": TITLE_SUGGESTIONS, "industries": INDUSTRY_SUGGESTIONS,
}
# Facets whose values are places. What is typed there is READ, never pasted:
# "Global except india" + Enter is a − India chip, "ger" is Germany, and text
# no gazetteer can place makes no chip — it would go to Exa word for word and
# match nobody's location.
_PLACE_FACETS = frozenset({"locations", "company_hq"})
_MAX_ROWS = 6
_MAX_LEN = 120           # filters.py keeps a value to this; so does the input
# What the "?" walkthrough calls each facet (addons/leads/help.py). A key, not
# the facet name, because the tour's script must survive a facet being renamed
# in prospector.filters — and because "facet_years" reads better in a script
# than "years_in_role".
_HELP_FACETS = {
    "facet_locations": "locations",
    "facet_job_titles": "job_titles",
    "facet_seniority": "seniority",
    "facet_functions": "functions",
    "facet_industries": "industries",
    "facet_headcount": "headcount",
    "facet_revenue": "revenue",
    "facet_companies": "companies",
    "facet_company_hq": "company_hq",
    "facet_years": "years_in_role",
    "facet_keywords": "keywords",
    "facet_contact_imports": "contact_imports",
    "facet_account_imports": "account_imports",
    "facet_email_status": "email_status",
    "facet_scores": "scores",
    "facet_lists": "lists",
    "facet_stages": "stages",
    "facet_custom_fields": "custom_fields",
}
# Every key help_targets() can answer. Public because the rail these live in is
# not this panel's to unfold — the workbench does that for them (help_reveal).
# ("save_search" left the panel with its button: the page toolbar answers it.)
HELP_KEYS = frozenset(_HELP_FACETS) | {
    "filters_head", "count_badge", "clear_all", "more_filters",
    "similar_titles", "facet_changed_jobs",
}
_REVEAL_PAD = 24         # a revealed target is scrolled this clear of the edge
# The width a chip elides against before it has been laid out: the rail's
# content width with its scrollbar showing (cockpit._RAIL_W 320 - 9 - 2 x 16).
_RAIL_CONTENT = 279
_CHIP_X = 16              # the remove button on a chip
_MINUS = 12               # the leading minus on an excluded chip
_TEXT_INSET = 12          # where an input's text starts: 2px border + 10px padding


def _clean(text) -> str:
    """A typed value the way filters.py will keep it: inner spaces collapsed,
    trimmed, capped."""
    return " ".join(str(text or "").split())[:_MAX_LEN].strip()


def static_suggest(facet: str, text: str) -> list:
    """The typeahead before the richer lookups are wired in: the starter lists
    in prospector.filters, prefix matches first, then anything that contains
    the text (casefold). Facets with no list — companies, keywords — offer
    nothing but what was typed."""
    pool = _STATIC.get(facet, ())
    fold = _clean(text).casefold()
    if not fold:
        return list(pool)
    first = [s for s in pool if s.casefold().startswith(fold)]
    then = [s for s in pool if fold in s.casefold() and not s.casefold().startswith(fold)]
    return first + then


def reveal_in_scroll(widget) -> None:
    """Scroll whatever scroll area a widget sits in until it can be seen.

    Neither this panel nor the workbench owns the rail that scrolls them — the
    cockpit does — so a target is found by walking up from the widget instead
    of by holding a reference to somebody else's scroll area."""
    parent = widget.parentWidget() if widget is not None else None
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(widget, 0, _REVEAL_PAD)
            return
        parent = parent.parentWidget()


def _on_screen(target, root) -> bool:
    """Whether a help target is really there to point at: nothing in the chain
    up to `root` is hidden, and a region target has a box. A target that is not
    on screen is left out of help_targets() — the tour then skips that step
    rather than ringing a stale rectangle."""
    widget, rect = target if isinstance(target, tuple) else (target, None)
    if widget is None:
        return False
    # `root` answering for a region of ITSELF is on screen by definition — the
    # tour is asking this widget where its own parts are, and whoever hosts it
    # decides whether it is showing. (No widget is its own ancestor, so
    # isVisibleTo would walk past it to a window that is hidden until shown.)
    if widget is not root and not widget.isVisibleTo(root):
        return False
    return rect is None or not rect.isEmpty()


def _sheet() -> str:
    """Every rule the panel's parts wear, scoped by object name and set once on
    the panel. Scoped because the app stylesheet makes a QPushButton or a
    QLineEdit 34-36px tall with its own 2px border — a parent's sheet outranks
    the app's, so these win — and because an unscoped rule here would restyle
    whatever the rail hosts beside the panel. Built when the panel is, so the
    accent follows the member's role like every other surface."""
    t = theme
    heading = f"font-family:'{t.FONT_HEADING}';letter-spacing:1px;font-weight:600;"
    # 20px content + 3px padding + 1px border: a 28px target, not the app's 34.
    small = (f"border-radius:{t.R_CHIP}px;padding:3px 6px;min-height:20px;"
             f"font-size:12px;font-weight:600;")
    badge = "border-radius:8px;padding:0px 5px;font-size:11px;font-weight:700;"
    return "".join((
        f"QLabel#fkick{{color:{t.NEUTRAL[600]};{heading}font-size:11px;}}",
        f"QLabel#fgroup{{color:{t.NEUTRAL[500]};{heading}font-size:10px;}}",
        f"QLabel#fcount{{background:{t.ACCENT};color:#ffffff;{badge}}}",
        f"QLabel#ffacetCount{{background:{t.INFO_BG};color:{t.INFO_INK};{badge}}}",
        f"QLabel#fheadText{{color:{t.TEXT};font-size:13px;font-weight:600;}}",
        f"QLabel#fchipText{{font-size:12px;font-weight:600;}}",
        f"QLabel#fsugText{{color:{t.TEXT};font-size:13px;font-weight:400;}}",
        f"QLabel#fhint{{color:{t.NEUTRAL[600]};font-size:12px;font-weight:500;}}",
        # header actions
        f"QPushButton#fclearAll{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ACCENT_RAMP[700]};}}",
        f"QPushButton#fclearAll:hover{{background:{t.INFO_BG};color:{t.INFO_INK};}}",
        f"QPushButton#fclearAll:focus{{border-color:{t.ACCENT};}}",
        # "More filters (n)" — Apollo's "View 60+ Filters", a quiet outline
        f"QPushButton#fmore{{background:{t.CARD};border:1px solid {t.NEUTRAL[300]};"
        f"{small}padding:3px 10px;color:{t.NEUTRAL[800]};}}",
        f"QPushButton#fmore:hover{{background:{t.WELL};border-color:{t.NEUTRAL[400]};}}",
        f"QPushButton#fmore:focus{{border-color:{t.ACCENT};}}",
        # a CSV import's row: box, file name, what it held
        f"QLabel#fimportName{{color:{t.TEXT};font-size:13px;font-weight:500;}}",
        f"QLabel#fimportMeta{{color:{t.NEUTRAL[600]};font-size:11px;}}",
        f"QCheckBox#fimportBox{{border:none;background:transparent;}}",
        f"QPushButton#fsave{{background:{t.CARD};border:1px solid {t.NEUTRAL[300]};"
        f"{small}padding:3px 10px;color:{t.NEUTRAL[800]};}}",
        f"QPushButton#fsave:hover{{background:{t.WELL};border-color:{t.NEUTRAL[400]};}}",
        f"QPushButton#fsave:pressed{{background:{t.NEUTRAL[200]};}}",
        f"QPushButton#fsave:focus{{border-color:{t.ACCENT};}}",
        # an include/exclude facet's input and its suggestions
        f"QLineEdit#finput{{padding:4px 10px;min-height:20px;font-size:13px;}}",
        f"QFrame#fsugRow{{background:transparent;border:none;border-radius:{t.R_CHIP}px;}}",
        f"QFrame#fsugRow:hover{{background:{t.WELL};}}",
        f"QPushButton#fsugInc{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ACCENT_RAMP[700]};}}",
        f"QPushButton#fsugInc:hover{{background:{t.INFO_BG};color:{t.INFO_INK};}}",
        f"QPushButton#fsugInc:pressed{{background:{t.ACCENT_RAMP[200]};}}",
        f"QPushButton#fsugInc:focus{{border-color:{t.ACCENT};}}",
        f"QPushButton#fsugExc{{background:transparent;border:1px solid transparent;"
        f"{small}color:{t.ERR_INK};}}",
        f"QPushButton#fsugExc:hover{{background:{t.ERR_BG};}}",
        f"QPushButton#fsugExc:pressed{{background:{t.ERR_LINE};}}",
        f"QPushButton#fsugExc:focus{{border-color:{t.ERR_INK};}}",
        f"QCheckBox#fsimilar{{border:none;background:transparent;font-size:13px;"
        f"color:{t.NEUTRAL[800]};}}",
        # bands
        f"QPushButton#fband{{background:{t.WELL};border:1px solid {t.HAIRLINE};"
        f"border-radius:{t.R_CHIP}px;padding:3px 10px;min-height:20px;"
        f"font-size:12px;font-weight:500;color:{t.NEUTRAL[800]};}}",
        f"QPushButton#fband:hover{{border-color:{t.NEUTRAL[300]};}}",
        f"QPushButton#fband:checked{{background:{t.INFO_BG};color:{t.INFO_INK};"
        f"border-color:{t.ACCENT};}}",
        f"QPushButton#fband:focus{{border-color:{t.ACCENT};}}",
        # Stage / Lists / Custom fields: Apollo's Contact | Account switch
        f"QFrame#fseg{{background:{t.WELL};border:1px solid {t.HAIRLINE};"
        f"border-radius:{t.R_CONTROL}px;}}",
        f"QFrame#fseg QPushButton{{background:transparent;border:none;"
        f"border-radius:{t.R_CHIP}px;padding:3px 10px;min-height:18px;font-size:12px;"
        f"font-weight:600;color:{t.NEUTRAL[600]};}}",
        f"QFrame#fseg QPushButton:hover{{color:{t.TEXT};}}",
        f"QFrame#fseg QPushButton:checked{{background:{t.CARD};color:{t.TEXT};}}",
        f"QComboBox#fcustomField{{padding:4px 10px;min-height:20px;font-size:13px;}}",
        f"QToolButton#fpin{{background:transparent;border:1px solid transparent;"
        f"border-radius:{t.R_CHIP}px;padding:3px;}}",
        f"QToolButton#fpin:hover{{background:{t.WELL};}}",
        f"QToolButton#fpin:checked{{background:{t.INFO_BG};border-color:{t.ACCENT};}}",
        # chips
        f"#fchipInc{{background:{t.INFO_BG};border:1px solid {t.INFO_BG};"
        f"border-radius:{t.R_CHIP}px;}}",
        f"#fchipInc:hover{{border-color:{t.ACCENT_RAMP[300]};}}",
        f"#fchipInc:focus{{border-color:{t.INFO_INK};}}",
        f"#fchipExc{{background:{t.ERR_BG};border:1px solid {t.ERR_BG};"
        f"border-radius:{t.R_CHIP}px;}}",
        f"#fchipExc:hover{{border-color:{t.ERR_LINE};}}",
        f"#fchipExc:focus{{border-color:{t.ERR_INK};}}",
        f"QToolButton#fchipX{{background:transparent;border:none;padding:0px;"
        f"margin:0px;border-radius:{t.R_MICRO}px;}}",
        f"#fchipInc QToolButton#fchipX:hover{{background:{t.tint(t.INFO_INK, '29')};}}",
        f"#fchipExc QToolButton#fchipX:hover{{background:{t.tint(t.ERR_INK, '29')};}}",
    ))


def _through(*widgets) -> None:
    """Let the mouse fall through to the button a part sits inside."""
    for widget in widgets:
        widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)


def _count_badge(name: str, parent) -> QLabel:
    badge = QLabel("0", parent)
    badge.setObjectName(name)
    badge.setAlignment(Qt.AlignCenter)
    badge.setFixedHeight(16)
    badge.setMinimumWidth(16)
    badge.hide()
    return badge


class _Elided(QLabel):
    """One line that elides to the width it is given instead of asking for its
    whole length — a sixty-character job title must not widen a 320px rail.

    Painted, and never handed to setText: i18n routes every QLabel.setText
    through the catalogue, and a value someone typed is content, not copy.
    Copy shown through this is translated by the caller."""

    def __init__(self, name: str, ink: str = theme.TEXT, parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._full = ""
        self._ink = ink
        self._cap = 0                   # the widest it may ask to be; 0 = none

    def full(self) -> str:
        return self._full

    def set_full(self, text: str, ink: str = "") -> None:
        text = text or ""
        if text != self._full:
            self._full = text
            self.setAccessibleName(text)
            self.updateGeometry()
        self._ink = ink or self._ink
        self.update()

    def set_cap(self, px: int) -> None:
        if px != self._cap:
            self._cap = px
            self.updateGeometry()

    def natural(self) -> int:
        self.ensurePolished()
        return self.fontMetrics().horizontalAdvance(self._full) + 2

    def elides(self) -> bool:
        return bool(self._cap) and self.natural() > self._cap

    def sizeHint(self) -> QSize:
        width = self.natural()
        if self._cap:
            width = min(width, self._cap)
        return QSize(width, self.fontMetrics().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(min(self.sizeHint().width(), 24), self.fontMetrics().height())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(theme.c(self._ink))
        rect = self.contentsRect()
        text = self.fontMetrics().elidedText(self._full, Qt.ElideRight, rect.width())
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class _Pressable(QAbstractButton):
    """A button laid out like a row — label, badge, chevron — instead of
    painting its own text, so a facet header or a chip is one focusable thing
    with `clicked`, Space and click() for free. What sits inside lets the
    mouse through (`_through`). Tab-focus only: a mouse click must not leave a
    focus ring on a header it just opened."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setAttribute(Qt.WA_StyledBackground, True)

    def sizeHint(self) -> QSize:
        lay = self.layout()
        return lay.sizeHint() if lay is not None else QSize(0, 0)

    def minimumSizeHint(self) -> QSize:
        lay = self.layout()
        return lay.minimumSize() if lay is not None else QSize(0, 0)

    def paintEvent(self, _event):
        # QSS backgrounds and borders reach a custom widget only through
        # PE_Widget; QAbstractButton itself paints nothing.
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.end()


class _Head(_Pressable):
    """A facet's header: its name, how many values it holds, and a chevron
    that says whether its editor is open."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setAccessibleName(title)
        self.setMinimumHeight(C.MIN_TARGET + 4)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 2, 6)
        row.setSpacing(theme.SPACE_2 - 2)
        self._title = QLabel(title, self)
        self._title.setObjectName("fheadText")
        self.badge = _count_badge("ffacetCount", self)
        self._chevron = QLabel(self)
        self._chevron.setFixedSize(14, 14)
        row.addWidget(self._title, 0, Qt.AlignVCenter)
        row.addWidget(self.badge, 0, Qt.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._chevron, 0, Qt.AlignVCenter)
        _through(self._title, self.badge, self._chevron)
        self._open = False
        self._hover = False
        self._paint_chevron()

    def set_open(self, open_: bool) -> None:
        self._open = bool(open_)
        self._paint_chevron()

    def set_count(self, n: int) -> None:
        self.badge.setText(str(n))
        self.badge.setVisible(n > 0)

    def _paint_chevron(self):
        ink = theme.NEUTRAL[800] if self._hover else theme.NEUTRAL[500]
        name = "chevron-down" if self._open else "chevron-right"
        self._chevron.setPixmap(icons.pixmap(name, 14, ink))

    def enterEvent(self, event):
        self._hover = True
        self._paint_chevron()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self._paint_chevron()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.hasFocus():
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setPen(QPen(theme.c(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1),
                                    theme.R_CHIP, theme.R_CHIP)


class _Chip(_Pressable):
    """One chosen value. The side reads without colour too: an excluded chip
    leads with a minus. A click on the body flips the side (when the facet has
    two), the x — or Delete — removes it."""

    removeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.value = ""
        self.side = ""
        self.flippable = True
        self._width = _RAIL_CONTENT
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 4, 4)
        row.setSpacing(theme.SPACE_1)
        self._minus = QLabel(self)
        self._minus.setFixedSize(_MINUS, _MINUS)
        self._minus.hide()
        self._text = _Elided("fchipText", theme.INFO_INK, self)
        self._x = QToolButton(self)
        self._x.setObjectName("fchipX")
        self._x.setFixedSize(_CHIP_X, _CHIP_X)
        self._x.setCursor(Qt.PointingHandCursor)
        self._x.setFocusPolicy(Qt.NoFocus)          # Delete on the chip does it
        self._x.setToolTip(i18n.t("Remove"))
        self._x.setAccessibleName(i18n.t("Remove"))
        self._x.clicked.connect(lambda _=False: self.removeRequested.emit())
        row.addWidget(self._minus, 0, Qt.AlignVCenter)
        row.addWidget(self._text, 1, Qt.AlignVCenter)
        row.addWidget(self._x, 0, Qt.AlignVCenter)
        _through(self._minus, self._text)

    def label(self) -> str:
        """What the chip shows (an option's label for seniority, function and
        the bands; the value itself otherwise)."""
        return self._text.full()

    def set_state(self, value: str, text: str, side: str, flippable: bool = True):
        self.value, self.flippable = value, flippable
        exclude = side == "exclude"
        ink = theme.ERR_INK if exclude else theme.INFO_INK
        if side != self.side:
            self.side = side
            self.setObjectName("fchipExc" if exclude else "fchipInc")
            # The sheet keys on the object name, and a renamed widget keeps its
            # old look until re-polished — so does the x, whose hover tint
            # hangs off the chip's name.
            for widget in (self, self._x):
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            icons.button_icon(self._x, "x", 10, ink, stroke=2.0)
            if exclude:
                self._minus.setPixmap(icons.pixmap("minus", _MINUS, ink, stroke=2.2))
            self._minus.setVisible(exclude)
        self._text.set_full(text, ink)
        self.setCursor(Qt.PointingHandCursor if flippable else Qt.ArrowCursor)
        self.set_max_width(self._width)
        self.update()

    def set_max_width(self, width: int) -> None:
        """Elide the value so the whole chip fits `width` — the chip row's."""
        self._width = max(60, int(width))
        lay = self.layout()
        margins = lay.contentsMargins()
        chrome = margins.left() + margins.right() + _CHIP_X + lay.spacing()
        if self.side == "exclude":
            chrome += _MINUS + lay.spacing()
        self._text.set_cap(max(24, self._width - chrome))
        self._sync_tip()

    def _sync_tip(self):
        if not self.flippable:
            tip = ""
        elif self.side == "exclude":
            tip = i18n.t("Excluded — click to include")
        else:
            tip = i18n.t("Included — click to exclude")
        if self._text.elides():
            tip = f"{self._text.full()}\n{tip}".strip()
        self.setToolTip(tip)

    def minimumSizeHint(self) -> QSize:
        # Small on purpose: FlowLayout's minimum width is its widest item's
        # minimum, and that minimum becomes the rail's.
        hint = self.sizeHint()
        return QSize(min(hint.width(), 64), hint.height())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.removeRequested.emit()
            return
        super().keyPressEvent(event)


class _ChipBox(QWidget):
    """A facet's chosen values, wrapping onto new lines as they run out of
    width. Chips are pooled and restyled in place, never rebuilt: a chip's own
    x is mid-click when the redraw that hides it runs, and deleting a widget
    from inside its own signal is a crash."""

    def __init__(self, on_flip, on_remove, parent=None):
        super().__init__(parent)
        self._flow = C.FlowLayout(self, margin=0, h_space=6, v_space=6)
        self._flow.setContentsMargins(0, 0, 0, theme.SPACE_2 + 2)
        self._on_flip, self._on_remove = on_flip, on_remove
        self.chips: list = []

    def active(self) -> list:
        return [chip for chip in self.chips if not chip.isHidden()]

    def set_items(self, items) -> None:
        """items: (value, label, side, flippable), in the order to show."""
        width = self.width() if self.isVisible() else _RAIL_CONTENT
        while len(self.chips) < len(items):
            chip = _Chip(self)
            chip.clicked.connect(lambda _=False, c=chip: self._on_flip(c))
            chip.removeRequested.connect(lambda c=chip: self._on_remove(c))
            self._flow.addWidget(chip)
            self.chips.append(chip)
        for chip, (value, label, side, flippable) in zip(self.chips, items):
            chip.set_state(value, label, side, flippable)
            chip.set_max_width(width)
            chip.show()
        for chip in self.chips[len(items):]:
            chip.value = ""
            chip.hide()
        self._flow.invalidate()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for chip in self.chips:
            chip.set_max_width(self.width())


class _Input(QLineEdit):
    """A facet's input. Escape empties it, the way every typeahead does.

    setMaxLength (120, _MAX_LEN) is right for typing one value, and wrong
    for pasting a list -- 193 company names from a customer's own sheet
    (the case this exists for) is thousands of characters, silently cut to
    120 by Qt before any code here ever sees it. A paste that carries a
    comma is a list, not a value someone is about to keep typing, so it
    never touches the length-capped buffer at all: `pasted` carries the
    whole clipboard text straight to the panel. A paste with no comma is
    one value and behaves exactly as it always has."""
    pasted = Signal(str)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        super().keyPressEvent(event)

    def paste(self):
        text = QApplication.clipboard().text()
        if "," in text:
            self.pasted.emit(text)
            return
        super().paste()


class _Row(QFrame):
    """One suggestion under a facet's input: the value, then Include and
    Exclude. A click on the row itself includes, the way a typeahead picks."""

    includeRequested = Signal()
    excludeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fsugRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.value = ""
        self.label = ""
        row = QHBoxLayout(self)
        # 12px: the input's own text inset (2px border + 10px padding), so a
        # suggestion lines up under what was typed.
        row.setContentsMargins(_TEXT_INSET, 0, 0, 0)
        row.setSpacing(2)
        self._text = _Elided("fsugText", theme.TEXT, self)
        row.addWidget(self._text, 1, Qt.AlignVCenter)
        self.include_btn = QPushButton(i18n.t("Include"), self)
        self.include_btn.setObjectName("fsugInc")
        self.exclude_btn = QPushButton(i18n.t("Exclude"), self)
        self.exclude_btn.setObjectName("fsugExc")
        for btn, signal in ((self.include_btn, self.includeRequested),
                            (self.exclude_btn, self.excludeRequested)):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda _=False, s=signal: s.emit())
            row.addWidget(btn, 0, Qt.AlignVCenter)

    def set_value(self, value: str, label: str) -> None:
        self.value, self.label = value, label
        self._text.set_full(label)
        self.setToolTip(label)
        self.include_btn.setAccessibleName(i18n.t("Include {value}").format(value=label))
        self.exclude_btn.setAccessibleName(i18n.t("Exclude {value}").format(value=label))

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.includeRequested.emit()
            return
        super().mouseReleaseEvent(event)


class _ChipEditor(QWidget):
    """The editor under an include/exclude facet: an input, up to six
    suggestions under it, and whatever the facet adds below (the similar-
    titles box, the guides-only note)."""

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        self.values: list = []          # what each shown row would add, in order
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, theme.SPACE_3)
        self._col.setSpacing(theme.SPACE_1 + 2)
        self.input = _Input(self)
        self.input.setObjectName("finput")
        self.input.setPlaceholderText(placeholder)
        self.input.setAccessibleName(placeholder)
        self.input.setMaxLength(_MAX_LEN)
        self._col.addWidget(self.input)
        self._rows_box = QWidget(self)
        rows = QVBoxLayout(self._rows_box)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        self.rows: list = []
        for _ in range(_MAX_ROWS):
            row = _Row(self._rows_box)
            row.hide()
            rows.addWidget(row)
            self.rows.append(row)
        self._rows_box.hide()
        self._col.addWidget(self._rows_box)
        self.hint = QLabel(self)
        self.hint.setObjectName("fhint")
        # Wraps: a place hint repeats what was typed ("Press Enter for: United
        # Arab Emirates, Saudi Arabia … except India"), and an unwrapped label
        # would widen the rail past its 320px.
        self.hint.setWordWrap(True)
        self.hint.setContentsMargins(_TEXT_INSET, 0, 0, 0)      # under the rows' text
        self.hint.hide()
        self._col.addWidget(self.hint)

    def add_extra(self, widget: QWidget) -> None:
        self._col.addWidget(widget)

    def show_rows(self, rows, hint: str = "") -> None:
        """rows: (value, label) pairs, at most six. Rows are pooled for the
        same reason chips are — the Include pressed is inside the redraw."""
        self.values = [value for value, _label in rows]
        for row, (value, label) in zip(self.rows, rows):
            row.set_value(value, label)
            row.show()
        for row in self.rows[len(rows):]:
            row.value = row.label = ""
            row.hide()
        self._rows_box.setVisible(bool(rows))
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


class _BandEditor(QWidget):
    """A band facet's editor: every band as a small toggle, wrapping, and a
    note under them when the facet has one."""

    def __init__(self, options, on_click, note: str = "", parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, theme.SPACE_3)
        col.setSpacing(theme.SPACE_1 + 2)
        # The bands sit in a box of their own: a FlowLayout lays a wrapping
        # note out as one more item at its whole sentence's width.
        bands = QWidget(self)
        flow = C.FlowLayout(bands, margin=0, h_space=6, v_space=6)
        self.buttons: dict = {}
        for key, label in options:
            btn = QPushButton(i18n.t(label), bands)
            btn.setObjectName("fband")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda on=False, k=key: on_click(k, on))
            flow.addWidget(btn)
            self.buttons[key] = btn
        col.addWidget(bands)
        self.note = None
        if note:
            self.note = C.label(note, level="META", wrap=True)
            col.addWidget(self.note)

    def set_chosen(self, keys) -> None:
        for key, btn in self.buttons.items():
            btn.setChecked(key in keys)


class _ScoreEditor(QWidget):
    """Apollo's "Scores", Prism's way: the lowest triage fit to keep (the FIT
    column's number) and "Qualified by Prism only" — the two refine controls
    the results rail used to carry on its own, now a facet like the rest."""

    def __init__(self, on_floor, on_qualified, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, theme.SPACE_3)
        col.setSpacing(theme.SPACE_1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        caption = QLabel(i18n.t("Minimum fit"), self)
        caption.setObjectName("fsugText")
        row.addWidget(caption, 1, Qt.AlignVCenter)
        self.floor = QSpinBox(self)
        self.floor.setObjectName("ffloor")
        self.floor.setRange(0, 100)
        self.floor.setSuffix(" / 100")
        self.floor.setMinimumWidth(104)
        self.floor.valueChanged.connect(on_floor)
        row.addWidget(self.floor, 0, Qt.AlignVCenter)
        col.addLayout(row)
        self.qualified = _ToggleRow(
            i18n.t("Qualified by Prism only"),
            i18n.t("Only people Prism has researched and scored"), self)
        self.qualified.switch.clicked.connect(on_qualified)
        col.addWidget(self.qualified)

    def set_values(self, floor: int, qualified: bool) -> None:
        self.floor.blockSignals(True)
        self.floor.setValue(int(floor))
        self.floor.blockSignals(False)
        self.qualified.switch.setChecked(bool(qualified))


class _ImportRow(_Pressable):
    """One past import as a tickable row: a box, the file's name (elided — a
    long export name must not widen the rail) and what it held under it. The
    whole row answers a click, like a band."""

    toggled = Signal(bool)

    def __init__(self, import_id: str, name: str, meta: str, parent=None):
        super().__init__(parent)
        self.import_id = import_id
        self.setMinimumHeight(C.MIN_TARGET)
        self.setToolTip(name)
        self.setAccessibleName(name)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 2, 3)
        row.setSpacing(theme.SPACE_2)
        self.box = QCheckBox(self)
        self.box.setObjectName("fimportBox")
        self.box.setFocusPolicy(Qt.NoFocus)          # the row is the tab stop
        row.addWidget(self.box, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        self.name = _Elided("fimportName", theme.TEXT, self)
        self.name.set_full(name)
        self.meta = _Elided("fimportMeta", theme.NEUTRAL[600], self)
        self.meta.set_full(meta)
        text.addWidget(self.name)
        text.addWidget(self.meta)
        row.addLayout(text, 1)
        _through(self.box, self.name, self.meta)
        self.clicked.connect(lambda _=False: self._flip())

    def _flip(self):
        self.box.setChecked(not self.box.isChecked())
        self.toggled.emit(self.box.isChecked())

    def set_checked(self, on: bool) -> None:
        self.box.setChecked(bool(on))

    def is_checked(self) -> bool:
        return self.box.isChecked()


class _ImportEditor(QWidget):
    """Apollo's "Contact CSV import" / "Account CSV import": every past import
    of one kind, newest first, each a tick — Apollo's own words, "check one or
    more CSV import file names". With none yet, a line saying where imports
    come from: the Import menu at the top of the page, never this rail."""

    def __init__(self, kind: str, on_toggle, parent=None):
        super().__init__(parent)
        self.kind = kind
        self._on_toggle = on_toggle
        self.rows: dict = {}                            # import id → _ImportRow
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, theme.SPACE_3)
        col.setSpacing(2)
        self._list = QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(2)
        col.addLayout(self._list)
        what = (i18n.t("No contact imports yet — use Import ▸ Contacts at the top "
                       "of the page.") if kind == "contacts" else
                i18n.t("No account imports yet — use Import ▸ Accounts at the top "
                       "of the page."))
        self.empty = C.label(what, level="META", wrap=True)
        col.addWidget(self.empty)

    def set_imports(self, headers, label) -> None:
        """Rebuild the rows from import headers (imports.list_imports);
        `label(header)` says what each held ("3 contacts · 22 Sep")."""
        chosen = {i for i, r in self.rows.items() if r.is_checked()}
        for row in self.rows.values():
            row.setParent(None)
            row.deleteLater()
        self.rows = {}
        for header in headers or ():
            row = _ImportRow(header["id"], header.get("name", ""), label(header), self)
            row.toggled.connect(lambda on, i=header["id"]: self._on_toggle(i, on))
            row.set_checked(header["id"] in chosen)
            self._list.addWidget(row)
            self.rows[header["id"]] = row
        self.empty.setVisible(not self.rows)

    def set_chosen(self, ids) -> None:
        ids = set(ids or ())
        for import_id, row in self.rows.items():
            row.set_checked(import_id in ids)


def _side_switch(sides, on_pick, parent) -> tuple:
    """Apollo's small Contact | Account (People | Company) switch over a
    record filter: (frame, {key: button}). `on_pick(key)` on a click."""
    frame = QFrame(parent)
    frame.setObjectName("fseg")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    row = QHBoxLayout(frame)
    row.setContentsMargins(2, 2, 2, 2)
    row.setSpacing(2)
    buttons = {}
    for key, label in sides:
        btn = QPushButton(i18n.t(label), frame)
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.TabFocus)
        btn.clicked.connect(lambda _=False, k=key: on_pick(k))
        row.addWidget(btn, 1)
        buttons[key] = btn
    return frame, buttons


class _RecordEditor(_ChipEditor):
    """Stage or Lists — Apollo's "Stage > Contact or Account", "Lists >
    People or Company": the switch, then the names there are (stages, list
    names) under a box that narrows them, each with Include and Exclude. Only
    names that exist are offered — a stage or a list nobody has matches
    nobody."""

    def __init__(self, group: str, placeholder: str, parent=None, sides=None):
        super().__init__(placeholder, parent)
        self.group = group
        self.sides = sides or _RECORD_SIDES[group]
        self.facet = self.sides[0][0]               # the side being edited
        frame, self.side_btns = _side_switch([(f, label) for f, label, _p in self.sides],
                                             self.set_facet, self)
        self._col.insertWidget(0, frame)
        frame.setVisible(len(self.sides) > 1)       # one side: nothing to switch
        self.on_side = None                         # set by the panel: redraw rows
        self._sync_side()

    def set_facet(self, facet: str) -> None:
        if facet in self.side_btns:
            self.facet = facet
            self._sync_side()
            if self.on_side is not None:
                self.on_side()

    def _sync_side(self) -> None:
        for facet, btn in self.side_btns.items():
            btn.setChecked(facet == self.facet)


class _CustomEditor(QWidget):
    """Apollo's "Custom fields": "select a custom field. Select a value to
    filter by." The Contact | Account switch, a field picker holding the
    columns imported sheets brought in, then that column's values, most used
    first, each a toggle — a value checked is kept, OR within the field."""

    def __init__(self, on_value, parent=None, sides=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox
        self._on_value = on_value                   # (custom key, value, on)
        self._sides = sides or _CUSTOM_SIDES
        self.scope = self._sides[0][0]
        self.options: dict = {"contact": {}, "account": {}}
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 2, 0, theme.SPACE_3)
        col.setSpacing(theme.SPACE_1 + 2)
        frame, self.side_btns = _side_switch(self._sides, self.set_scope, self)
        frame.setVisible(len(self._sides) > 1)
        col.addWidget(frame)
        self.field = QComboBox(self)
        self.field.setObjectName("fcustomField")
        self.field.setAccessibleName(i18n.t("Select a custom field"))
        self.field.currentIndexChanged.connect(lambda _i: self._fill_values())
        col.addWidget(self.field)
        self._values_box = QWidget(self)
        self._flow = C.FlowLayout(self._values_box, margin=0, h_space=6, v_space=6)
        col.addWidget(self._values_box)
        self.empty = C.label(i18n.t(_CUSTOM_EMPTY), level="META", wrap=True)
        col.addWidget(self.empty)
        self.buttons: dict = {}                     # value → its toggle
        self._chosen: dict = {}                     # custom key → [values]
        self._sync()

    def column(self) -> str:
        return self.field.currentData() or ""

    def key(self) -> str:
        return custom_key(self.scope, self.column()) if self.column() else ""

    def set_options(self, options) -> None:
        """{"contact" | "account": {column: [values, most used first]}}."""
        options = options if isinstance(options, dict) else {}
        self.options = {scope: dict(options.get(scope) or {}) for scope, _l in self._sides}
        self._sync()

    def set_scope(self, scope: str) -> None:
        self.scope = scope
        self._sync()

    def set_chosen(self, custom: dict) -> None:
        self._chosen = {k: list(v) for k, v in (custom or {}).items()}
        self._fill_values()

    def _sync(self) -> None:
        for scope, btn in self.side_btns.items():
            btn.setChecked(scope == self.scope)
        keep = self.column()
        columns = list(self.options.get(self.scope, {}))
        self.field.blockSignals(True)
        self.field.clear()
        self.field.addItem(i18n.t("Select a custom field"), "")
        for column in columns:
            self.field.addItem(column, column)
        at = self.field.findData(keep) if keep else -1
        self.field.setCurrentIndex(at if at > 0 else (1 if len(columns) == 1 else 0))
        self.field.blockSignals(False)
        self.field.setVisible(bool(columns))
        self.empty.setVisible(not columns)
        self._fill_values()

    def _fill_values(self) -> None:
        for btn in self.buttons.values():
            self._flow.removeWidget(btn)
            btn.setParent(None)
            btn.deleteLater()
        self.buttons = {}
        column = self.column()
        values = list(self.options.get(self.scope, {}).get(column, ()))[:_MAX_CUSTOM_VALUES]
        key = self.key()
        chosen = {v.casefold() for v in self._chosen.get(key, ())}
        # A value chosen earlier that no record carries any more stays offered,
        # so it can be unticked.
        values += [v for v in self._chosen.get(key, ())
                   if v.casefold() not in {x.casefold() for x in values}]
        for value in values:
            btn = QPushButton(value, self._values_box)
            btn.setObjectName("fband")
            btn.setCheckable(True)
            btn.setChecked(value.casefold() in chosen)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
            btn.clicked.connect(lambda on=False, v=value, k=key: self._on_value(k, v, on))
            self._flow.addWidget(btn)
            self.buttons[value] = btn
        self._values_box.setVisible(bool(values))


class _Section(QWidget):
    """One facet: header, its chips (always visible, Sales-Nav style), and the
    editor that opening the header reveals, over a hairline."""

    def __init__(self, facet: str, title: str, editor: QWidget, open_: bool,
                 on_flip, on_remove, parent=None):
        super().__init__(parent)
        self.facet = facet
        # Bands, import lists and the score controls SHOW what is chosen when
        # open, so their chips hide then — see _sync_chips.
        self._band = facet in _SHOWS_CHOSEN
        self._open = False
        self._has_chips = False
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.head = _Head(title, self)
        self.head.clicked.connect(lambda _=False: self._toggle())
        self._head_row = QHBoxLayout()
        self._head_row.setContentsMargins(0, 0, 0, 0)
        self._head_row.setSpacing(theme.SPACE_1)
        self._head_row.addWidget(self.head, 1)
        col.addLayout(self._head_row)
        self.chips = _ChipBox(lambda chip: on_flip(facet, chip),
                              lambda chip: on_remove(facet, chip), self)
        self.chips.hide()
        col.addWidget(self.chips)
        self.editor = editor
        col.addWidget(editor)
        col.addWidget(C.hairline())
        self.set_open(open_)

    def is_open(self) -> bool:
        return self._open

    def add_pin(self, pin: QWidget) -> None:
        """The All filters window's pin, beside the header."""
        self._head_row.addWidget(pin, 0, Qt.AlignVCenter)

    def set_open(self, open_: bool) -> None:
        self._open = bool(open_)
        self.editor.setVisible(self._open)
        self.head.set_open(self._open)
        self._sync_chips()

    def set_chips(self, items) -> None:
        self.chips.set_items(items)
        self._has_chips = bool(items)
        self._sync_chips()

    def _toggle(self):
        self.set_open(not self._open)
        field = getattr(self.editor, "input", None)
        if self._open and field is not None and self.isVisible():
            field.setFocus(Qt.OtherFocusReason)

    def _sync_chips(self):
        # An open band's checked buttons ARE its chosen values; chips above
        # them would say the same thing twice.
        self.chips.setVisible(self._has_chips and not (self._band and self._open))


class _Switch(C.ToggleSwitch):
    """The shared switch, with an off track that shows on a white rail.

    C.ToggleSwitch paints its off track white at 18% because it was drawn for
    the dark nav rail; on the white filter rail that track — and the white
    knob on it — is simply not there. The knob also sits where the state says
    whenever no animation is running, so a spec applied in code never leaves
    an "on" switch drawn off."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.TabFocus)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        on = self.isChecked()
        radius = self.H / 2
        painter.setPen(QPen(theme.c(theme.ACCENT_RAMP[800]), 1.5) if self.hasFocus()
                       else Qt.NoPen)
        painter.setBrush(theme.c(theme.ACCENT if on else theme.NEUTRAL[300]))
        painter.drawRoundedRect(QRectF(0.75, 0.75, self.W - 1.5, self.H - 1.5),
                                radius, radius)
        moving = self._anim.state() == QAbstractAnimation.State.Running
        knob = self.get_knob() if moving else float(self.W - self.KNOB - 2 if on else 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.c("#ffffff"))
        inset = (self.H - self.KNOB) / 2
        painter.drawEllipse(QRectF(knob, inset, self.KNOB, self.KNOB))


class _ToggleRow(_Pressable):
    """A switch with its sentence. The row answers a click as well as the
    switch does — a 32px switch alone is a small thing to hit."""

    def __init__(self, text: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)             # the switch is the tab stop
        self.setMinimumHeight(C.MIN_TARGET + 4)
        self.setToolTip(tooltip)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 6, 2, 6)
        row.setSpacing(theme.SPACE_2)
        self.text = _Elided("fheadText", theme.TEXT, self)
        self.text.set_full(text)
        self.switch = _Switch(self)
        self.switch.setAccessibleName(text)
        row.addWidget(self.text, 1, Qt.AlignVCenter)
        row.addWidget(self.switch, 0, Qt.AlignVCenter)
        _through(self.text)
        self.clicked.connect(lambda _=False: self.switch.click())


class FilterPanel(QWidget):
    """The "Lead filters" column. Edits one SearchSpec (module docstring).

        panel = FilterPanel(suggest=lookup)     # lookup(facet, text) -> [str]
        panel.changed.connect(on_filters)       # once per edit
        panel.set_spec(SearchSpec.from_params(session_params))
        panel.spec().to_dict()

    `suggest` feeds the typeahead of the open facets (locations, job_titles,
    industries, companies, company_hq, keywords). Seniority and Function offer
    their own fixed options and never ask it."""

    changed = Signal()
    saveRequested = Signal()
    pinnedChanged = Signal(list)            # the filters kept in the rail, in its order

    def __init__(self, suggest=None, parent=None, catalog: bool = False,
                 kind: str = "person"):
        super().__init__(parent)
        # "person": Find People's rail. "company": the Companies page's — the
        # same chips, bands and record filters over the company-level facets.
        self._kind = "company" if kind == "company" else "person"
        company = self._kind == "company"
        self._pinned_names = _COMPANY_PINNED if company else _PINNED
        self._more_names = _COMPANY_MORE if company else _MORE
        self._order = self._pinned_names + self._more_names
        self._open_at_start = _COMPANY_OPEN_AT_START if company else _OPEN_AT_START
        self._similar = self._jobs = self._jobs_box = None   # a person rail only
        self._spec = SearchSpec()
        self._suggest = suggest or static_suggest
        self._sections: dict = {}
        # The rail keeps its PINNED filters in view — Apollo's own few until
        # the owner pins others in the All filters window — and any filter
        # that holds a value. `catalog` is that window's copy of this panel:
        # every filter, narrowed by its search and group, each with a pin.
        self._catalog = bool(catalog)
        self._pinned = set(self._pinned_names)
        self._pin_btns: dict = {}
        self._query = ""
        self._category = ""
        # What the two CSV-import facets offer: import headers, newest first
        # (addons/leads/imports.py). The workbench hands them over.
        self._imports = {name: [] for name in IMPORT_FACETS}
        # What Stage, Lists and Custom fields offer (pool.record_options):
        # the names on the owner's own records. Apollo's stages until told.
        from addons.leads.accounts import STAGES as ACCOUNT_STAGES
        from addons.leads.contacts import STAGES as CONTACT_STAGES
        self._records = {"contact_stages": list(CONTACT_STAGES),
                         "account_stages": list(ACCOUNT_STAGES),
                         "contact_lists": [], "account_lists": [],
                         "custom": {"contact": {}, "account": {}}}
        self._more_open = False
        self.setStyleSheet(_sheet())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._build_hidden()
        for name in self._order:
            if name == "changed_jobs_90d":
                root.addWidget(self._build_jobs())
            else:
                root.addWidget(self._build_section(name))
        root.addSpacing(theme.SPACE_3)
        root.addLayout(self._build_footer())
        if self._catalog:
            self._build_pins()
        self._render()

    # ── the public surface ────────────────────────────────────────────────────
    def spec(self) -> SearchSpec:
        """The filters as set — a copy; editing it changes nothing here."""
        return self._spec.copy()

    def set_spec(self, spec) -> None:
        """Show a SearchSpec (or its dict), read through SearchSpec.from_dict so
        a hand-edited or older file is forgiven. Clears anything half-typed;
        leaves which facets are open alone. Emits `changed` once."""
        raw = spec.to_dict() if isinstance(spec, SearchSpec) else spec
        self._spec = SearchSpec.from_dict(raw if isinstance(raw, dict) else {})
        for section in self._sections.values():
            field = getattr(section.editor, "input", None)
            if field is not None:
                field.blockSignals(True)
                field.clear()
                field.blockSignals(False)
        self._render()
        self.changed.emit()

    def clear(self) -> None:
        """"Clear all": every facet emptied, the switches back to default."""
        self.set_spec(SearchSpec())

    def active_count(self) -> int:
        return self._spec.active_count()

    def set_suggest(self, suggest) -> None:
        """Swap the typeahead lookup (None: the static starter lists)."""
        self._suggest = suggest or static_suggest
        for name in self._sections:
            self._refresh_rows(name)

    def set_imports(self, contacts=(), accounts=()) -> None:
        """What "Contact CSV import" and "Account CSV import" offer: import
        headers (addons/leads/imports.list_imports), newest first. A chosen id
        whose import has since been deleted stays chosen — shown as a deleted
        import — until the owner removes it: a filter never changes itself."""
        from addons.leads.imports import label
        self._imports = {"contact_imports": list(contacts or ()),
                         "account_imports": list(accounts or ())}
        for name in IMPORT_FACETS:
            self._sections[name].editor.set_imports(self._imports[name], label)
        self._render()

    def set_record_options(self, options) -> None:
        """What Stage, Lists and Custom fields offer — pool.record_options():
        the stages, list names and imported columns the owner's own contacts
        and accounts carry. A chosen value no record carries any more stays
        chosen until the owner removes it: a filter never changes itself."""
        options = options if isinstance(options, dict) else {}
        for name in ("contact_stages", "account_stages", "contact_lists", "account_lists"):
            if isinstance(options.get(name), (list, tuple)):
                self._records[name] = [str(v) for v in options[name] if str(v).strip()]
        if isinstance(options.get("custom"), dict):
            self._records["custom"] = options["custom"]
            self._sections["custom_fields"].editor.set_options(options["custom"])
        self._render()

    def import_name(self, name: str, import_id: str) -> str:
        """The file name an import facet shows for an id ("" when unknown)."""
        for header in self._imports.get(name, ()):
            if header.get("id") == import_id:
                return header.get("name", "")
        return ""

    def pinned(self) -> list:
        """The filters kept in the rail, in the rail's order."""
        return [n for n in self._order if n in self._pinned]

    def set_pinned(self, names) -> None:
        """Which filters the rail keeps in view (an unknown name is ignored;
        None or nothing known: Apollo's defaults). Emits nothing."""
        known = [n for n in (names or ()) if n in self._order]
        self._pinned = set(known) if known else set(self._pinned_names)
        for name, btn in self._pin_btns.items():
            btn.setChecked(name in self._pinned)
        self._sync_more()

    def set_catalog_filter(self, text: str = "", category: str = "") -> None:
        """The All filters window: show the filters whose name holds `text`
        in the chosen group ("" is every group)."""
        self._query = _clean(text).casefold()
        self._category = category if category in dict(CATEGORIES) else ""
        self._sync_more()

    def catalog_names(self) -> list:
        """The filters the window shows now, in order."""
        return [n for n in self._order if self._matches(n)]

    def open_all_filters(self) -> None:
        """"More filters": the window of every filter (addons/leads/
        all_filters.py) over a copy of these; Apply brings its filters and
        pins back here, Cancel leaves everything as it was."""
        from addons.leads.all_filters import AllFiltersDialog
        dlg = AllFiltersDialog(self, parent=self.window())
        if not self._ask(dlg):
            return
        spec, pinned = dlg.result()
        if pinned != self.pinned():
            self.set_pinned(pinned)
            self.pinnedChanged.emit(self.pinned())
        if spec.to_dict() != self._spec.to_dict():
            self.set_spec(spec)

    def _ask(self, dlg) -> bool:
        """Show the window and wait. A test seam: no modal in a test."""
        from PySide6.QtWidgets import QDialog
        # Off the CLASS: PySide 6.11 has no instance attribute for it, so
        # dlg.Accepted raised after every close (live crash, 24-Sep-2026).
        return dlg.exec() == QDialog.Accepted

    def more_open(self) -> bool:
        return self._more_open

    def set_more_open(self, open_: bool) -> None:
        """Show or fold the facets under "More filters" (an active one always
        shows, open or not)."""
        self._more_open = bool(open_)
        self._sync_more()

    # ── the guided walkthrough points at these ────────────────────────────────
    def help_targets(self) -> dict:
        """The parts the "?" tour can ring, by the key it asks for: a real
        widget already on screen, or (widget, QRect) where the target is a
        region of one. Nothing is built here — a step is drawn around the
        control the owner is looking at, not a copy of it.

        Only the People rail is walked: the Companies page's rail answers the
        same facet keys, and from a tab that is not showing it would win a key
        its sibling should answer — the step is then skipped as not drawn."""
        if self._kind != "person":
            return {}
        out = {
            # The whole column: Apollo's rail has no title over its facets.
            "filters_head": self,
            "count_badge": self._badge,
            "clear_all": self._clear_btn,
            "more_filters": self._more_btn,
            "similar_titles": self._similar,
            "facet_changed_jobs": self._jobs,
        }
        for key, facet in _HELP_FACETS.items():
            if facet in self._sections:
                out[key] = self._sections[facet]
        # The badge and Clear all appear only once a filter is set, and the
        # similar-titles box only while Job titles is open.
        return {k: t for k, t in out.items() if _on_screen(t, self)}

    def help_reveal(self, key: str) -> None:
        """Make one target reachable: open the facet the step is about and
        scroll the rail to it. Opening a section shows what is already chosen —
        it never edits the spec, and the section is left open afterwards, the
        way it would be if the owner had clicked the header themselves."""
        if self._kind != "person":
            return
        facet = _HELP_FACETS.get(key)
        if key == "similar_titles":
            facet = "job_titles"            # the box lives in that facet's editor
        if facet in self._more_names or key == "facet_changed_jobs":
            self.set_more_open(True)        # a folded facet can't be pointed at
        section = self._sections.get(facet)
        if section is not None and not section.is_open():
            section.set_open(True)
        # Asked for the whole panel, a scroll area centres it and its top ends
        # up above the rail's edge — so the first facet is what gets scrolled to.
        target = (self._sections[self._order[0]] if key == "filters_head"
                  else self.help_targets().get(key))
        if isinstance(target, QWidget):
            reveal_in_scroll(target)

    def help_snapshot(self) -> tuple:
        """The facets that are open, and whether "More filters" is. A walk
        opens every facet, one step at a time, and an owner who kept two open
        should get two back."""
        return (frozenset(name for name, section in self._sections.items()
                          if section.is_open()), self._more_open)

    def help_restore(self, snapshot) -> None:
        if snapshot is None:
            return
        if isinstance(snapshot, tuple):
            open_names, more = snapshot
            self.set_more_open(more)
        else:
            open_names = snapshot
        for name, section in self._sections.items():
            want = name in open_names
            if section.is_open() != want:
                section.set_open(want)

    # ── building ──────────────────────────────────────────────────────────────
    def _build_hidden(self) -> None:
        """Save lives in the page toolbar now — Apollo's "Save as new search"
        — which clicks this button, so `saveRequested` keeps one source and a
        caller that clicks it in code still works. Never shown."""
        self._save_btn = QPushButton(i18n.t("Save search"), self)
        self._save_btn.setObjectName("fsave")
        self._save_btn.clicked.connect(lambda _=False: self.saveRequested.emit())
        self._save_btn.hide()

    def _build_footer(self) -> QHBoxLayout:
        """Apollo's foot of the rail: "Clear all (n)", then "View 60+ Filters"
        — here "More filters (n)", which unfolds the facets under it."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2 - 2)
        self._clear_btn = QPushButton(i18n.t("Clear all"), self)
        self._clear_btn.setObjectName("fclearAll")
        self._clear_btn.clicked.connect(lambda _=False: self.clear())
        self._badge = _count_badge("fcount", self)
        self._more_btn = QPushButton(self)
        self._more_btn.setObjectName("fmore")
        self._more_btn.clicked.connect(lambda _=False: self.open_all_filters())
        for btn in (self._clear_btn, self._more_btn):
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.TabFocus)
        row.addWidget(self._clear_btn, 0, Qt.AlignVCenter)
        row.addWidget(self._badge, 0, Qt.AlignVCenter)
        row.addStretch(1)
        row.addWidget(self._more_btn, 0, Qt.AlignVCenter)
        return row

    @property
    def kind(self) -> str:
        return self._kind

    def categories(self) -> tuple:
        """The All filters window's groups for this rail."""
        return _COMPANY_CATEGORIES if self._kind == "company" else CATEGORIES

    def _title(self, name: str) -> str:
        """What a facet is called on this rail."""
        if self._kind == "company" and name in _COMPANY_LABELS:
            return i18n.t(_COMPANY_LABELS[name])
        return i18n.t(FACET_LABELS.get(name, "Changed jobs in the last 90 days"))

    def _sides(self) -> dict:
        return _COMPANY_SIDES if self._kind == "company" else _RECORD_SIDES

    def _more_widget(self, name: str):
        return self._jobs_box if name == "changed_jobs_90d" else self._sections[name]

    def _sync_more(self) -> None:
        """Which filters show. In the rail: the pinned ones, any that holds a
        value (an applied filter is never hidden) and, while the tour has the
        rail unfolded, all of them. In the All filters window: every filter
        its search and group let through."""
        folded = 0
        for name in self._order:
            if self._catalog:
                show = self._matches(name)
            else:
                on = (self._spec.changed_jobs_90d if name == "changed_jobs_90d"
                      else self._spec.count(name) > 0)
                show = self._more_open or on or name in self._pinned
                folded += 0 if show else 1
            self._more_widget(name).setVisible(show)
        self._more_btn.setText(i18n.t("More filters ({n})").format(n=folded) if folded
                               else i18n.t("More filters"))
        self._more_btn.setVisible(not self._catalog)

    def _matches(self, name: str) -> bool:
        if self._category and CATEGORY_OF.get(name) != self._category:
            return False
        if not self._query:
            return True
        title = (i18n.t("Changed jobs in the last 90 days") if name == "changed_jobs_90d"
                 else self._title(name))
        return self._query in title.casefold() or self._query in name.replace("_", " ")

    def _build_pins(self) -> None:
        """The All filters window's pins: one beside every filter's header."""
        for name in self._order:
            pin = QToolButton(self)
            pin.setObjectName("fpin")
            pin.setCheckable(True)
            pin.setCursor(Qt.PointingHandCursor)
            pin.setFocusPolicy(Qt.TabFocus)
            pin.setIcon(icons.icon("pin", 14, theme.NEUTRAL[600]))
            pin.setToolTip(i18n.t("Keep this filter in the rail"))
            pin.setAccessibleName(i18n.t("Pin {filter}").format(
                filter=self._title(name)))
            pin.setChecked(name in self._pinned)
            pin.toggled.connect(lambda on, n=name: self._toggle_pin(n, on))
            if name == "changed_jobs_90d":
                self._jobs_row.addWidget(pin, 0, Qt.AlignVCenter)
            else:
                self._sections[name].add_pin(pin)
            self._pin_btns[name] = pin

    def _toggle_pin(self, name: str, on: bool) -> None:
        if on:
            self._pinned.add(name)
        else:
            self._pinned.discard(name)
        self.pinnedChanged.emit(self.pinned())

    def _build_section(self, name: str) -> _Section:
        if name == "custom_fields":
            editor = _CustomEditor(self._custom_value, self,
                                   _COMPANY_CUSTOM_SIDES if self._kind == "company" else None)
            editor.set_options(self._records["custom"])
            section = _Section(name, self._title(name), editor, False,
                               self._flip, self._remove, self)
            self._sections[name] = section
            return section
        if name in RECORD_GROUPS:
            editor = _RecordEditor(name, i18n.t(_PLACEHOLDERS[name]), self,
                                   self._sides()[name])
            editor.on_side = lambda n=name: self._refresh_rows(n)
            editor.input.textChanged.connect(lambda _t, n=name: self._refresh_rows(n))
            editor.input.returnPressed.connect(lambda n=name: self._enter(n))
            for row in editor.rows:
                row.includeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "include"))
                row.excludeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "exclude"))
            section = _Section(name, self._title(name), editor, False,
                               self._flip, self._remove, self)
            self._sections[name] = section
            return section
        if name in IMPORT_FACETS or name == "scores":
            if name == "scores":
                editor = _ScoreEditor(
                    lambda value: self._edit(lambda s: setattr(s, "min_fit", int(value))),
                    lambda on=False: self._set_flag("qualified_only", on), self)
            else:
                editor = _ImportEditor(_IMPORT_KIND[name],
                                       lambda i, on, n=name: self._toggle_import(n, i, on),
                                       self)
            section = _Section(name, self._title(name), editor, False,
                               self._flip, self._remove, self)
            self._sections[name] = section
            return section
        if name in BAND_FACETS or name in LOCAL_FACETS:
            note = (i18n.t("Checked against the company's record · unknown sizes "
                           "aren't dropped") if name in _ON_RECORD else "")
            editor = _BandEditor(_BANDS[name],
                                 lambda key, on, n=name: self._band(n, key, on),
                                 note, self)
        else:
            editor = _ChipEditor(i18n.t(_PLACEHOLDERS[name]), self)
            editor.input.textChanged.connect(lambda _t, n=name: self._refresh_rows(n))
            editor.input.returnPressed.connect(lambda n=name: self._enter(n))
            editor.input.pasted.connect(lambda text, n=name: self._bulk_paste(n, text))
            for row in editor.rows:
                row.includeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "include"))
                row.excludeRequested.connect(
                    lambda n=name, r=row: self._pick(n, r, "exclude"))
            if name == "job_titles":
                self._similar = QCheckBox(i18n.t("Include similar titles"), editor)
                self._similar.setObjectName("fsimilar")
                self._similar.setToolTip(i18n.t(
                    "On: titles guide the search. Off: a person's title must "
                    "contain one of them."))
                self._similar.clicked.connect(
                    lambda on=False: self._set_flag("similar_titles", on))
                editor.add_extra(self._similar)
            if name in GUIDES_ONLY and self._kind == "person":
                # A person row carries no industry and no keywords, so an
                # include can only steer Exa; an exclude is checked (filters.py).
                editor.add_extra(C.label(
                    i18n.t("Include guides the search · Exclude is enforced"),
                    level="META", wrap=True))
        section = _Section(name, self._title(name), editor,
                           name in self._open_at_start, self._flip, self._remove, self)
        self._sections[name] = section
        return section

    def _build_jobs(self) -> QWidget:
        box = QWidget(self)
        self._jobs_box = box            # folds under "More filters" (_sync_more)
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._jobs = _ToggleRow(
            i18n.t("Changed jobs in the last 90 days"),
            i18n.t("Only people whose current role started in the last 90 days"), box)
        self._jobs.switch.clicked.connect(
            lambda on=False: self._set_flag("changed_jobs_90d", on))
        self._jobs_row = QHBoxLayout()
        self._jobs_row.setContentsMargins(0, 0, 0, 0)
        self._jobs_row.setSpacing(theme.SPACE_1)
        self._jobs_row.addWidget(self._jobs, 1)
        col.addLayout(self._jobs_row)
        col.addWidget(C.hairline())
        return box

    # ── edits: change the spec, redraw from it, say so once ──────────────────
    def _edit(self, change) -> None:
        before = self._spec.to_dict()
        draft = self._spec.copy()
        change(draft)
        # Through from_dict, so the panel keeps exactly what a file would:
        # trimmed, de-duplicated, capped, never on both sides.
        after = SearchSpec.from_dict(draft.to_dict())
        edited = after.to_dict() != before
        if edited:
            self._spec = after
        self._render()                  # a refused edit still redraws the truth
        if edited:
            self.changed.emit()

    def _set_flag(self, attr: str, on) -> None:
        self._edit(lambda spec: setattr(spec, attr, bool(on)))

    def _add(self, name: str, value: str, side: str) -> None:
        self._add_many(name, [(value, side)])

    def _add_many(self, name: str, pairs) -> None:
        """(value, side) pairs onto one facet as ONE edit — "Global except
        india" is a single change, not two."""
        pairs = [(_clean(v), side) for v, side in pairs if _clean(v)]
        if not pairs:
            return
        self._clear_input(name)         # the redraw below refreshes the rows once
        into = self._target(name)

        def change(spec):
            facet = spec.facet(into)
            for value, side in pairs:
                fold = value.casefold()
                target = facet.exclude if side == "exclude" else facet.include
                if any(v.casefold() == fold for v in target):
                    continue
                facet.include = [v for v in facet.include if v.casefold() != fold]
                facet.exclude = [v for v in facet.exclude if v.casefold() != fold]
                (facet.exclude if side == "exclude" else facet.include).append(value)
        self._edit(change)

    def _target(self, name: str) -> str:
        """The spec facet an edit in a section lands on: a Stage or Lists
        section edits the side its switch is on."""
        if name in RECORD_GROUPS:
            return self._sections[name].editor.facet
        return name

    @staticmethod
    def _decode(name: str, value: str) -> tuple:
        """(facet, value) from a chip: a Stage, Lists or Custom fields chip
        carries which facet (or custom field) it belongs to (_SEP)."""
        if (name in RECORD_GROUPS or name == "custom_fields") and _SEP in value:
            facet, _sep, raw = value.partition(_SEP)
            return facet, raw
        return name, value

    def _custom_value(self, key: str, value: str, on) -> None:
        """A custom field's value ticked on or off."""
        if not key:
            return

        def change(spec):
            values = [v for v in spec.custom_fields.get(key, []) if v.casefold() != value.casefold()]
            if on:
                values.append(value)
            if values:
                spec.custom_fields[key] = values
            else:
                spec.custom_fields.pop(key, None)
        self._edit(change)

    def _clear_input(self, name: str) -> None:
        field = self._sections[name].editor.input
        field.blockSignals(True)
        field.clear()
        field.blockSignals(False)

    def _pick(self, name: str, row: _Row, side: str) -> None:
        if row.value:
            self._add(name, row.value, side)

    def _enter(self, name: str) -> None:
        editor = self._sections[name].editor
        typed = _clean(editor.input.text())
        if not typed:
            return
        if name in RECORD_GROUPS:
            # Only a stage or a list that exists: the first one offered.
            if editor.values:
                self._add(name, editor.values[0], "include")
            return
        if name in _PLACE_FACETS:
            self._enter_place(name, typed)
            return
        if name not in CLOSED_FACETS and "," in typed:
            # Typed (not pasted -- see _Input.pasted for that) but still a
            # list: "Acme, Beta, Gamma" then Enter. Same rule either way.
            if self._add_list(name, typed):
                return
        if not editor.values:
            return
        if name not in CLOSED_FACETS:
            facet = self._spec.facet(name)
            if typed.casefold() in {v.casefold() for v in facet.include + facet.exclude}:
                return      # already chosen: never quietly add the next suggestion
        self._add(name, editor.values[0], "include")

    def _bulk_paste(self, name: str, text: str) -> None:
        """A paste that carried a comma, straight from the clipboard, never
        length-capped by the input it landed in (see _Input.pasted)."""
        if name in _PLACE_FACETS:
            self._enter_place(name, text)
            return
        if name in CLOSED_FACETS:
            return          # picked from a fixed list; a pasted list isn't
        self._add_list(name, text)

    def _add_list(self, name: str, text: str) -> bool:
        """"Acme Ltd, Beta Corp, …" -> every name its own chip, one edit.
        Company, job-title, industry and keyword facets only (locations and
        company_hq read commas their own way, via read_place_text; seniority
        and functions pick from a fixed list, so a typed comma there is
        punctuation someone is still typing past, not a separator).
        True if it added anything, so a caller can fall back to the
        single-value path on a comma that was not really a list of names."""
        values = [v for v in (_clean(p) for p in text.split(",")) if v]
        if len(values) < 2:
            return False
        self._add_many(name, [(v, "include") for v in values])
        return True

    def _enter_place(self, name: str, typed: str) -> None:
        """Enter in Location / Company HQ: the text is read as places. A known
        place is included; "Global except india" adds its chips on both sides;
        a half-typed name ("ger") takes the first suggestion; "Anywhere" clears
        the box (no filter IS anywhere); anything else unplaceable stays typed
        under its hint and adds nothing."""
        include, exclude, unknown = read_place_text(typed)
        facet = self._spec.facet(name)
        chosen = {v.casefold() for v in facet.include + facet.exclude}
        if unknown:
            words, out = parse_location_text(typed)
            editor = self._sections[name].editor
            if len(words) == 1 and not out and not include and editor.values:
                self._add(name, editor.values[0], "include")
            return
        if not include and not exclude:
            self._clear_input(name)
            self._refresh_rows(name)
            return
        if len(include) == 1 and not exclude:
            if include[0].casefold() in chosen:
                return      # already chosen: never quietly flip it or add another
        self._add_many(name, [(v, "include") for v in include]
                       + [(v, "exclude") for v in exclude])

    def _flip(self, name: str, chip: _Chip) -> None:
        if not chip.flippable or not chip.value:
            return
        target, value = self._decode(name, chip.value)

        def change(spec):
            facet = spec.facet(target)
            if value in facet.include:
                facet.include.remove(value)
                facet.exclude.append(value)
            elif value in facet.exclude:
                facet.exclude.remove(value)
                facet.include.append(value)
        self._edit(change)

    def _remove(self, name: str, chip: _Chip) -> None:
        if not chip.value:
            return
        target, value = self._decode(name, chip.value)

        def change(spec):
            if name == "scores":
                if value == "min_fit":
                    spec.min_fit = 0
                elif value == "qualified_only":
                    spec.qualified_only = False
            elif name == "custom_fields":
                left = [v for v in spec.custom_fields.get(target, []) if v != value]
                if left:
                    spec.custom_fields[target] = left
                else:
                    spec.custom_fields.pop(target, None)
            elif name in BAND_FACETS or name in IMPORT_FACETS or name in LOCAL_FACETS:
                setattr(spec, name, [k for k in getattr(spec, name) if k != value])
            else:
                facet = spec.facet(target)
                facet.include = [v for v in facet.include if v != value]
                facet.exclude = [v for v in facet.exclude if v != value]
        self._edit(change)

    def _toggle_import(self, name: str, import_id: str, on) -> None:
        def change(spec):
            chosen = [i for i in getattr(spec, name) if i != import_id]
            if on:
                chosen.append(import_id)
            setattr(spec, name, chosen)
        self._edit(change)

    def _band(self, name: str, key: str, on) -> None:
        def change(spec):
            chosen = set(getattr(spec, name))
            if on:
                chosen.add(key)
            else:
                chosen.discard(key)
            setattr(spec, name, [k for k, _label in _BANDS[name] if k in chosen])
        self._edit(change)

    # ── drawing the spec ──────────────────────────────────────────────────────
    def _render(self) -> None:
        spec = self._spec
        for name, section in self._sections.items():
            if name in RECORD_GROUPS:
                chips = []
                for facet, _label, prefix in self._sides()[name]:
                    lead = f"{i18n.t(prefix)}: " if prefix else ""
                    f = spec.facet(facet)
                    chips += [(facet + _SEP + v, lead + v, "include", True) for v in f.include]
                    chips += [(facet + _SEP + v, lead + v, "exclude", True) for v in f.exclude]
                section.set_chips(chips)
                self._refresh_rows(name)
            elif name == "custom_fields":
                chips = []
                for key, values in spec.custom_fields.items():
                    scope, column = split_custom_key(key)
                    shown = column if scope == "contact" else \
                        i18n.t("{field} (account)").format(field=column)
                    chips += [(key + _SEP + v, f"{shown}: {v}", "include", False)
                              for v in values]
                section.set_chips(chips)
                section.editor.set_chosen(spec.custom_fields)
            elif name == "scores":
                chips = []
                if spec.min_fit:
                    chips.append(("min_fit", i18n.t("Fit {n}+").format(n=spec.min_fit),
                                  "include", False))
                if spec.qualified_only:
                    chips.append(("qualified_only", i18n.t("Qualified only"),
                                  "include", False))
                section.set_chips(chips)
                section.editor.set_values(spec.min_fit, spec.qualified_only)
            elif name in IMPORT_FACETS:
                chosen = getattr(spec, name)
                section.set_chips([(i, self.import_name(name, i) or i18n.t("Deleted import"),
                                    "include", False) for i in chosen])
                section.editor.set_chosen(chosen)
            elif name in BAND_FACETS or name in LOCAL_FACETS:
                chosen = getattr(spec, name)
                section.set_chips([(k, i18n.t(label_of(_BANDS[name], k)), "include", False)
                                   for k in chosen])
                section.editor.set_chosen(chosen)
            else:
                facet = spec.facet(name)
                options = CLOSED_FACETS.get(name)

                def shown(value, options=options):
                    return i18n.t(label_of(options, value)) if options else value
                section.set_chips([(v, shown(v), "include", True) for v in facet.include]
                                  + [(v, shown(v), "exclude", True) for v in facet.exclude])
                self._refresh_rows(name)
            section.head.set_count(spec.count(name))
        if self._similar is not None:
            self._similar.setChecked(spec.similar_titles)
        if self._jobs is not None:
            self._jobs.switch.setChecked(spec.changed_jobs_90d)
        total = spec.active_count()
        self._badge.setText(str(total))
        self._badge.setVisible(total > 0)
        self._clear_btn.setVisible(total > 0)
        self._sync_more()

    def _refresh_rows(self, name: str) -> None:
        section = self._sections.get(name)
        if section is None or name in _SHOWS_CHOSEN or name == "custom_fields":
            return
        rows, hint = self._suggestions(name, section.editor.input.text())
        section.editor.show_rows(rows, hint)

    def _record_rows(self, name: str, typed: str):
        """(rows, hint) for Stage or Lists: the names on the switch's side
        that exist and are not chosen yet, narrowed by what is typed."""
        target = self._target(name)
        facet = self._spec.facet(target)
        chosen = {v.casefold() for v in facet.include + facet.exclude}
        names = [v for v in self._records.get(target, ()) if v.casefold() not in chosen]
        if not self._records.get(target):
            return [], i18n.t(_RECORD_EMPTY.get(target, "")) if _RECORD_EMPTY.get(target) else ""
        fold = typed.casefold()
        if fold:
            first = [v for v in names if v.casefold().startswith(fold)]
            names = first + [v for v in names if fold in v.casefold() and v not in first]
            return [(v, v) for v in names[:_MAX_ROWS]], ("" if names else i18n.t("No match"))
        more = len(names) > _MAX_ROWS
        return [(v, v) for v in names[:_MAX_ROWS]], (i18n.t("Type to filter") if more else "")

    def _suggestions(self, name: str, text: str):
        """(rows, hint) for a facet's input. Rows are (value, label). A value
        already chosen, on either side and in any case, is never offered."""
        typed = _clean(text)
        if name in RECORD_GROUPS:
            return self._record_rows(name, typed)
        fold = typed.casefold()
        facet = self._spec.facet(name)
        chosen = {v.casefold() for v in facet.include + facet.exclude}
        options = CLOSED_FACETS.get(name)
        if options:
            left = [(key, i18n.t(label)) for key, label in options
                    if key.casefold() not in chosen]
            if not fold:
                more = len(left) > _MAX_ROWS
                return left[:_MAX_ROWS], (i18n.t("Type to filter") if more else "")
            first = [o for o in left if o[1].casefold().startswith(fold)]
            then = [o for o in left if fold in o[1].casefold() and o not in first]
            found = (first + then)[:_MAX_ROWS]
            return found, ("" if found else i18n.t("No match"))
        if not fold:
            return [], ""
        try:
            offered = [_clean(s) for s in (self._suggest(name, typed) or [])
                       if isinstance(s, str)]
        except Exception:                                   # noqa: BLE001
            offered = []                # a failing lookup must not stop typing
        offered = [s for s in offered if s]
        if name in _PLACE_FACETS:
            return self._place_rows(typed, offered, chosen)
        rows, seen = [], set(chosen)
        if fold not in seen:
            # The typed text leads — in the list's spelling when it names a
            # listed value ("india" offers "India").
            spelled = next((s for s in offered if s.casefold() == fold), typed)
            rows.append((spelled, spelled))
            seen.add(fold)
        for value in offered:
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            rows.append((value, value))
            if len(rows) >= _MAX_ROWS:
                break
        return rows, ""

    def _place_rows(self, typed: str, offered: list, chosen: set):
        """(rows, hint) for a place facet. The typed text leads only when it IS
        a known place, in the gazetteer's spelling ("bombay" offers Mumbai);
        otherwise the suggestions stand alone and the hint says what Enter
        will do — or that nothing here is a place."""
        include, exclude, unknown = read_place_text(typed)
        rows, seen = [], set(chosen)
        single = len(include) == 1 and not exclude and not unknown
        if single and include[0].casefold() not in seen:
            rows.append((include[0], include[0]))
            seen.add(include[0].casefold())
        for value in offered:
            if value.casefold() in seen:
                continue
            seen.add(value.casefold())
            rows.append((value, value))
            if len(rows) >= _MAX_ROWS:
                break
        words, out = parse_location_text(typed)
        one_word = len(words) == 1 and not out and not include
        if unknown and not (one_word and rows):
            hint = i18n.t("Not a place Prism knows") + ": " + (
                typed if one_word else ", ".join(unknown))
        elif exclude or len(include) > 1:
            said = SearchSpec.from_dict({"locations": {"include": include,
                                                       "exclude": exclude}})
            hint = i18n.t("Press Enter for") + ": " + said.location_label(limit=3)
        elif not include and not unknown and not rows:
            hint = i18n.t("Anywhere is the default: no filter needed")
        else:
            hint = ""
        return rows, hint

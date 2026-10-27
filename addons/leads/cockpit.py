"""
Leads & Outreach — the workspace (the "A" direction)
────────────────────────────────────────────────────
`LeadsWorkspace` is the whole surface: a tab strip over six screens —

    Leads · Sessions · Lists · Saved searches · Sequences · Analytics

• Leads is the dense cockpit (`LeadsCockpit`): a multi-select lead TABLE with a
  left rail (the workbench mounts its lead filters there, above the refine
  controls), a Net-new / avg-fit counter strip, a bulk-actions bar that rises
  once a row is ticked, and an on-demand right DRAWER carrying the dossier plus
  a stop-on-reply sequence preview. Rail, results and a docked drawer share a
  splitter the user drags; columns resize. Scan-dense list; depth one click away.
• Sessions is real — every finished run (addons/leads/sessions.py), reopenable.
• Lists is real — the CSV/xlsx sheets Prism has already written to
  ~/Documents/Prism Leads, as open-able cards.
• Saved searches is real — the filters the owner kept to run again
  (addons/leads/saved_searches.py), each a card with its last run, "Use
  search" and "Delete".
• Analytics is real — this run's funnel, deliverability and verdict mix drawn
  from the dossiers in hand, plus the count of addresses already reached (the
  suppression ledger) and the outreach guardrails.
• Sequences is an honest, designed shell: it shows the exact model it will
  hold, and says plainly that the scheduler lands next.

The cockpit is pure presentation + selection: it takes the qualified dossiers
the pipeline produced and emits a signal when the user asks to verify, export,
save or sequence the checked rows, open a session, or use or delete a saved
search. The workbench wires those to the real workers and stores, so the whole
surface is testable with no pipeline and no network — Analytics off the
dossiers passed in, Lists, Sessions and Saved searches off folders the test
controls.
"""
from __future__ import annotations

import datetime
import os

import i18n
import paths
import theme
from addons.leads import evidence
from widgets import controls as C
from widgets import icons
from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QPoint, QPointF, QPropertyAnimation,
    QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter,
    QPainterPath, QPen, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QScrollArea,
    QSizePolicy,
    QSplitter, QSplitterHandle, QStackedWidget, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

_COLS = ("", "Lead", "Focus", "Fit", "Status", "Signal")
# The deliverability statuses a lead can carry, each with its (ink, tint) tone.
_TONE = {
    "Verified":  (theme.OK_INK,   theme.OK_BG),
    "Unverified": (theme.WARN_INK, theme.WARN_BG),
    "Catch-all": (theme.WARN_INK, theme.WARN_BG),
    "Unknown":   (theme.WARN_INK, theme.WARN_BG),
    "Invalid":   (theme.ERR_INK,  theme.ERR_BG),
    "No email":  (theme.WARN_INK, theme.WARN_BG),
    "Mailed":    (theme.NEUTRAL[700], theme.NEUTRAL[200]),
    "Not qualified": (theme.NEUTRAL[700], theme.NEUTRAL[200]),
}
# Dossier.status of a display-only row: someone a search sourced whom the
# qualify pass never reached (a leads-sheet-only run, or past the Qualify count)
# — and the rows "Qualify & draft" can (re)run. One value with the pool's own
# placeholder rows (pool.Person.row).
from addons.leads.pool import RETRYABLE, UNQUALIFIED                # noqa: E402
_MONO = theme.FONT_MONO_STACK.split(",")[0].strip().strip('"')


def status_of(dos, draft=None) -> str:
    """The deliverability label for a dossier — the one thing a bulk sender
    must see per row. A lead already sent to reads 'Mailed'; otherwise the free
    verify verdict (or 'Unverified' for an address no verifier has ruled on
    — nothing is guessed since 24-Sep-2026). One rule
    with the "Email status" filter: addons/leads/pool.py decides, this names."""
    from addons.leads.pool import EMAIL_STATUS_LABEL, email_status_of
    return EMAIL_STATUS_LABEL[email_status_of(dos.lead, draft)]


def needs_email(dos) -> bool:
    """True while "Find e-mails" still has something to do for this lead: no
    address at all, or one nobody has confirmed (a guess, a catch-all, an
    invalid). A verified address is done — asking again only spends credits."""
    return ((dos.lead.extra or {}).get("email_check") or "") != "valid"


def needs_phone(dos) -> bool:
    """True while "Find phones" still has something to do for this lead: they have
    no phone of any kind and work somewhere a company's number can be looked up.
    A lead that came with a number, or has one already, is left as it is."""
    from prospector import phones
    return phones.needs_phone(getattr(dos, "lead", None))


def unqualified_rows(dossiers, all_leads) -> list:
    """Everyone a run sourced whom the qualify pass didn't reach, as display-only
    rows. The table used to list qualified dossiers alone, so a leads-sheet-only
    run — 100 people sourced, none qualified — opened to an empty screen, and a
    full run hid everyone past the Qualify count. Apollo lists every person a
    search found, and so does this.

    The rows live only here: never saved into a session, exported as dossiers
    or counted by Analytics. A qualified lead keeps its real dossier — matched
    by object, since a run's dossiers and its all_leads share Lead objects (a
    restored session rebuilds them that way too)."""
    from prospector.models import Dossier
    have = {id(d.lead) for d in dossiers or []}
    return [Dossier(lead=lead, verdict="", generated_at="", status=UNQUALIFIED,
                    score=int(getattr(lead, "fit_score", 0) or 0))
            for lead in all_leads or [] if id(lead) not in have]


class _FitItem(QTableWidgetItem):
    """Sorts by the numeric fit score, not the string — so 100 beats 88. The
    score is painted as a chip by _FitDelegate, which reads _FIT_ROLE."""
    def __init__(self, value: float):
        super().__init__(f"{value:g}")
        self._v = float(value)
        self.setData(_FIT_ROLE, self._v)

    def __lt__(self, other):
        return self._v < getattr(other, "_v", 0.0)


class _LeadCard(QFrame):
    """One lead as a card in the gallery view — clickable (opens the drawer),
    with an accent-lit hover. Carries its dossier index so a click and a tick
    both name the same lead."""

    clicked = Signal(int)

    def __init__(self, idx: int, parent=None):
        super().__init__(parent)
        self._idx = idx
        self.setObjectName("leadcard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"QFrame#leadcard{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}"
            f"QFrame#leadcard:hover{{border-color:{theme.ACCENT};}}")

    def mousePressEvent(self, event):
        self.clicked.emit(self._idx)
        super().mousePressEvent(event)


# ── faces and painted cells ─────────────────────────────────────────────────
# One quiet disc for every lead. The avatar colour used to be picked from a ring
# that held the OK green and the WARN amber -- the same two colours the Status and
# Fit chips use for a verdict, so a lead's initials could read as one -- next to
# near-black entries that were the heaviest thing in a row of light chips. Colour
# in this table now means something (a status, a fit band) or nothing at all.
_AVATAR_FILL = theme.NEUTRAL[200]
_AVATAR_TEXT = theme.NEUTRAL[700]
_RAIL_W = 340          # the rail's default width
_RAIL_MIN = 280        # a drag on the rail's edge stays between these
_RAIL_MAX = 520
_DRAWER_W = 760        # the person panel: its default width, and its width floating —
_DRAWER_MIN = 420      # wide enough for Apollo's two columns (person._WIDE)
_DRAWER_MAX = 1000
_DOCK_MIN = 1180       # floor for docking; _dock_room also measures the centre
_TABLE_MIN = 560       # a docked drawer never leaves the results less than this
_HANDLE_W = 6          # a splitter handle's grab area — it draws a 1px rule
_SHADOW = 12           # the soft edge a floating drawer paints over the table
_ROW_H = 52
_HEAD_H = 36
_PAD = 12              # a cell's edge to its text; the header labels share it
_BOX = 16              # the painted checkbox
_TICK_BOX = 40         # the tick column's box, centred in its first 40px; the
                       # header's caret for Apollo's Bulk Selection takes the rest
_STEP = 20             # one scroll step, in px — the table scrolls per pixel
_SLIDE_MS = 160        # the bulk bar's slide
_DRAWER_MS = 180       # the drawer's
_QMAX = 16777215       # QWIDGETSIZE_MAX: "no maximum"
_COMPANY_ROLE = Qt.UserRole + 1     # Lead cell: the company under the name
_WHERE_ROLE = Qt.UserRole + 1       # Focus cell: the location under the title
_FIT_ROLE = Qt.UserRole + 2         # Fit cell: the score as a number
_C_TICK, _C_LEAD, _C_FOCUS, _C_FIT, _C_STATUS, _C_SIGNAL = range(len(_COLS))
# Default widths, and the least a drag may leave. Focus has neither: it takes
# whatever the others leave, and _fit_columns keeps that at _FOCUS_MIN or more.
_COL_WIDTH = {_C_TICK: 58, _C_LEAD: 300, _C_FIT: 76, _C_STATUS: 124, _C_SIGNAL: 136}
_COL_MIN = {_C_LEAD: 180, _C_FIT: 60, _C_STATUS: 100, _C_SIGNAL: 112}
_FOCUS_MIN = 150
# Every column at its minimum, and a scrollbar's width to spare: what a docked
# drawer must leave the table (_dock_room).
_TABLE_FLOOR = max(_TABLE_MIN, _COL_WIDTH[_C_TICK] + sum(_COL_MIN.values())
                   + _FOCUS_MIN + 12)
# Pills that name a state rather than a finding, drawn as a quiet outline.
_OUTLINE = frozenset({"Not qualified"})
_EMPTY_TITLE = "No people yet"
_EMPTY_BODY = ("Import a sheet with Import at the top right, or set filters on the "
               "left and press Find new people. Everyone Prism has ever found or "
               "imported shows here, and filters narrow it at once.")
# When filters (or a tab) leave nobody out of people Prism DOES hold.
_NO_MATCH_TITLE = "Nobody here matches these filters"
_NO_MATCH_BODY = ("Remove a filter on the left, look under another tab, or press "
                  "Find new people to search for people who match.")
# Apollo's three tabs over every result (pool.split), in its order.
_PEOPLE_TABS = (("total", "Total"), ("net_new", "Net New"), ("saved", "Saved"))
# Apollo's sort choices, Prism's way (pool.sort_people); legacy local sorting
# (a cockpit fed set_dossiers, not a pool) knows the first two.
_SORTS = (("relevance", "Relevance"), ("name", "Name A–Z"),
          ("newest", "Newest"), ("company", "Company A–Z"))
# What the "?" walkthrough calls the parts of this screen (addons/leads/help.py).
# A column has no widget of its own — the header paints all of them — so those
# keys answer with a region of the header instead (_section_rect).
_HELP_COLS = {"col_lead": _C_LEAD, "col_focus": _C_FOCUS, "col_fit": _C_FIT,
              "col_status": _C_STATUS, "col_signal": _C_SIGNAL}
_HELP_BULK = ("bulk_save", "bulk_remove", "bulk_verify", "bulk_emails", "bulk_phones",
              "bulk_list", "bulk_export", "bulk_stage", "bulk_qualify", "bulk_sequence")
_HELP_KEYS = frozenset({"import_menu", "views_menu", "hide_filters", "people_search",
                        "research_menu", "save_as_search", "sort", "search_settings",
                        "view_toggle", "people_tabs", "pager",
                        "table", "select_all", "bulk_bar", "drawer"}
                       | set(_HELP_COLS) | set(_HELP_BULK))
# The tab strip's own keys, in the order the tabs are built (_TABS).
_HELP_TABS = ("tab_people", "tab_sessions", "tab_lists", "tab_saved",
              "tab_sequences", "tab_analytics")
_REVEAL_PAD = 24       # a revealed target is scrolled this clear of the edge


def _initials(name: str) -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p[:1].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def _avatar_ink(name: str) -> str:
    """The avatar disc's fill. The same for everyone -- see _AVATAR_FILL."""
    return _AVATAR_FILL


def _avatar(name: str, size: int = 32) -> QLabel:
    lab = QLabel(_initials(name))
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(
        f"QLabel{{color:{_AVATAR_TEXT};background:{_avatar_ink(name)};"
        f"border-radius:{size // 2}px;font-weight:700;font-size:{max(11, size // 3)}px;}}")
    return lab


def _motion_ok(widget: QWidget) -> bool:
    """Whether a slide may play: only where someone can watch it — on screen,
    on a real display. These slides animate a height or a width, never a
    QGraphicsEffect, so they carry none of the blank-paint risk that
    controls.effects_enabled() guards against, and they run by default (the
    owner asked for a smoother screen; PRISM_NO_MOTION=1 turns them off).
    Anywhere else — a test, the offscreen renderer, a tab that isn't showing —
    the change lands at its end state at once. Every slide below sets that
    same end state when it finishes, so skipping one never changes where
    things end up."""
    if os.environ.get("PRISM_NO_MOTION") or not widget.isVisible():
        return False
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    return app is not None and app.platformName() != "offscreen"


def _on_screen(target, root) -> bool:
    """Whether a help target is really there to point at: nothing in the chain
    up to `root` is hidden, and a region target has a box. A target that is not
    on screen is left out of help_targets(), so the tour skips that step
    instead of ringing a stale rectangle."""
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


def _asset(name: str) -> str:
    """A shipped asset as a stylesheet url() path (forward slashes on Windows)."""
    return paths.resource("assets", name).replace(os.sep, "/")


def _combo_sheet() -> str:
    """The Leads combos' own look — the sort menu's and the page picker's. The
    app sheet's combo is 36px tall with no arrow, which read as a text box and
    stood 8px taller than the buttons beside the page picker."""
    return (
        f"QComboBox#leadsSort{{background:{theme.CARD};color:{theme.TEXT};"
        f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
        f"padding:5px 10px;min-height:20px;font-size:13px;}}"
        f"QComboBox#leadsSort:hover{{border-color:{theme.NEUTRAL[300]};}}"
        f"QComboBox#leadsSort::drop-down{{border:none;width:22px;}}"
        f"QComboBox#leadsSort::down-arrow{{image:url({_asset('caret-down.svg')});"
        f"width:12px;height:12px;}}")


def _font(px: int, weight=QFont.Normal, family: str = "") -> QFont:
    f = QFont(family or theme.FONT_BODY)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def _ticked(value) -> bool:
    """A CheckStateRole value read as ticked. PySide hands back an int or a
    Qt.CheckState depending on who set it, and the two don't compare equal."""
    try:
        return int(getattr(value, "value", value)) == Qt.Checked.value
    except (TypeError, ValueError):
        return False


def _mix(base: str, ink: str, amount: float) -> QColor:
    """`base` moved `amount` of the way towards `ink` — an opaque tint, so a
    row ground never lets the hairline beneath it show through."""
    a, b = theme.qcolor(base), theme.qcolor(ink)
    return QColor(round(a.red() + (b.red() - a.red()) * amount),
                  round(a.green() + (b.green() - a.green()) * amount),
                  round(a.blue() + (b.blue() - a.blue()) * amount))


def _paint_check(painter: QPainter, rect, state, hot: bool = False) -> None:
    """The table's own checkbox, for the rows and the header alike: a rounded
    16px box, white with a grey edge unticked, accent-filled with a white mark
    when ticked (a bar when only some are). Painted rather than left to the
    platform: under the native Windows style an unticked item-view indicator
    drew nothing at all, so nobody could see the rows were selectable."""
    area = QRectF(rect)
    box = QRectF(area.center().x() - _BOX / 2, area.center().y() - _BOX / 2, _BOX, _BOX)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    if state in (Qt.Checked, Qt.PartiallyChecked):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT_RAMP[600] if hot else theme.ACCENT))
        painter.drawRoundedRect(box, 4, 4)
        pen = QPen(QColor("#ffffff"), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if state == Qt.PartiallyChecked:
            y = box.center().y()
            painter.drawLine(QPointF(box.left() + 4.5, y), QPointF(box.right() - 4.5, y))
        else:
            mark = QPainterPath()
            mark.moveTo(box.left() + 4.2, box.top() + 8.3)
            mark.lineTo(box.left() + 6.9, box.top() + 11.0)
            mark.lineTo(box.left() + 11.9, box.top() + 5.4)
            painter.drawPath(mark)
    else:
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if hot else theme.NEUTRAL[400]), 1.2))
        painter.setBrush(theme.qcolor(theme.CARD))
        painter.drawRoundedRect(box.adjusted(0.6, 0.6, -0.6, -0.6), 4, 4)
    painter.restore()


def _paint_row(painter: QPainter, option, index) -> None:
    """A row's ground, painted by every cell so the row reads as one: white; a
    faint accent once ticked; a stronger one with an accent edge on the row
    open in the drawer; a shade darker under the mouse. The hairline under it
    is the only rule — the grid is off."""
    view = option.widget
    rect = option.rect
    row = index.row()
    is_open = bool(option.state & QStyle.State_Selected)
    ticked = _ticked(index.sibling(row, _C_TICK).data(Qt.CheckStateRole))
    hover = getattr(view, "hover_row", -1) == row
    if is_open or ticked:
        ground = _mix(theme.CARD, theme.ACCENT,
                      (0.10 if is_open else 0.06) + (0.03 if hover else 0.0))
    else:
        ground = theme.qcolor(theme.NEUTRAL[100] if hover else theme.CARD)
    painter.fillRect(rect, ground)
    painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1),
                     theme.qcolor(theme.HAIRLINE))
    if is_open and index.column() == _C_TICK:
        painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()),
                         QColor(theme.ACCENT))


def _two_lines(painter: QPainter, x: int, rect: QRect, first: str, second: str,
               font1: QFont, ink1: str, font2: QFont, ink2: str) -> None:
    """One or two lines centred as a block in the row. The line boxes are the
    Lead cell's (a 14px name over a 12px company) whatever the fonts, so the
    Lead and Focus cells' second lines sit on the same baseline."""
    width = max(0, rect.right() - _PAD - x)
    h1 = QFontMetrics(_font(14, QFont.DemiBold)).height()
    h2 = QFontMetrics(_font(12)).height()
    top = rect.top() + (rect.height() - h1 - (h2 + 1 if second else 0)) // 2
    painter.setFont(font1)
    painter.setPen(QColor(ink1))
    painter.drawText(QRect(x, top, width, h1), Qt.AlignLeft | Qt.AlignVCenter,
                     QFontMetrics(font1).elidedText(first, Qt.ElideRight, width))
    if second:
        painter.setFont(font2)
        painter.setPen(QColor(ink2))
        painter.drawText(QRect(x, top + h1 + 1, width, h2), Qt.AlignLeft | Qt.AlignVCenter,
                         QFontMetrics(font2).elidedText(second, Qt.ElideRight, width))


class _CellDelegate(QStyledItemDelegate):
    """Base for every column: the row's ground first, then `cell`. The view's
    own item painting is skipped on purpose — under the native Windows style
    it added a dotted focus rectangle, and the tick column's indicator was
    invisible until ticked."""

    def paint(self, painter, option, index):
        painter.save()
        _paint_row(painter, option, index)
        self.cell(painter, QRect(option.rect), index, option)
        painter.restore()

    def cell(self, painter, rect, index, option):
        """Draw the cell's content inside `rect`."""


class _TickDelegate(_CellDelegate):
    """The tick column: the painted checkbox, edged in the accent under the
    mouse. The item's CheckStateRole stays the one source of truth."""

    def cell(self, painter, rect, index, option):
        view = option.widget
        hot = (getattr(view, "hover_row", -1) == index.row()
               and getattr(view, "hover_col", -1) == _C_TICK)
        state = Qt.Checked if _ticked(index.data(Qt.CheckStateRole)) else Qt.Unchecked
        # In the header's box's column, not the cell's middle: the header
        # keeps the rest of the width for its Bulk Selection caret.
        _paint_check(painter, QRect(rect.left(), rect.top(), _TICK_BOX, rect.height()),
                     state, hot)


class _LeadDelegate(_CellDelegate):
    """The 'Lead' column: an initials avatar, the name, and the company beneath."""

    def cell(self, painter, rect, index, option):
        name = index.data(Qt.DisplayRole) or ""
        company = index.data(_COMPANY_ROLE) or ""
        d = 32
        x = rect.left() + theme.SPACE_2
        ay = rect.top() + (rect.height() - d) // 2
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(_avatar_ink(name)))
        painter.drawEllipse(QRectF(x, ay, d, d))
        painter.setFont(_font(11, QFont.Bold))
        painter.setPen(QColor(_AVATAR_TEXT))
        painter.drawText(QRect(x, ay, d, d), Qt.AlignCenter, _initials(name))
        _two_lines(painter, x + d + theme.SPACE_3, rect, name, company,
                   _font(14, QFont.DemiBold), theme.TEXT, _font(12), theme.NEUTRAL[600])


class _FocusDelegate(_CellDelegate):
    """The 'Focus' column: the title, and beneath it where they are — the owner
    filters by location, so a row says it without opening the drawer."""

    def cell(self, painter, rect, index, option):
        _two_lines(painter, rect.left() + _PAD, rect, index.data(Qt.DisplayRole) or "",
                   index.data(_WHERE_ROLE) or "", _font(13), theme.NEUTRAL[800],
                   _font(12), theme.NEUTRAL[600])


def _fit_tone(fit: float) -> tuple:
    """(ink, tint) for a fit score — the bands the gallery badge uses."""
    if fit >= 75:
        return theme.OK_INK, theme.OK_BG
    if fit >= 50:
        return theme.WARN_INK, theme.WARN_BG
    return theme.NEUTRAL[700], theme.NEUTRAL[100]


class _FitDelegate(_CellDelegate):
    """The 'Fit' column: the score as a compact tinted chip, right-aligned. The
    band's tone says good or weak; a big bold number shouted it on every row."""

    def cell(self, painter, rect, index, option):
        fit, text = index.data(_FIT_ROLE), index.data(Qt.DisplayRole) or ""
        if fit is None or not text:
            return
        ink, bg = _fit_tone(float(fit))
        f = _font(12, QFont.DemiBold, _MONO)
        w, h = max(36, QFontMetrics(f).horizontalAdvance(text) + 16), 22
        x = rect.right() + 1 - _PAD - w
        y = rect.top() + (rect.height() - h) // 2
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(bg))
        painter.drawRoundedRect(QRectF(x, y, w, h), theme.R_CHIP, theme.R_CHIP)
        painter.setFont(f)
        painter.setPen(theme.qcolor(ink))
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter, text)


class _PillDelegate(_CellDelegate):
    """Status / Signal columns: the value as a tinted pill — the card tones.
    "Not qualified" is a state rather than a finding, so it takes a quiet
    outline instead of a fill. Every pill is 22px, centred on the row."""

    def cell(self, painter, rect, index, option):
        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return
        f = _font(11, QFont.DemiBold)
        fm = QFontMetrics(f)
        h = 22
        w = min(fm.horizontalAdvance(text) + 20, max(0, rect.width() - 2 * _PAD))
        x = rect.left() + _PAD
        y = rect.top() + (rect.height() - h) // 2
        box = QRectF(x, y, w, h)
        painter.setRenderHint(QPainter.Antialiasing)
        if text in _OUTLINE:
            ink = theme.NEUTRAL[600]
            painter.setPen(QPen(QColor(theme.NEUTRAL[300]), 1))
            painter.setBrush(Qt.NoBrush)
            box = box.adjusted(0.5, 0.5, -0.5, -0.5)
        else:
            ink, bg = _TONE.get(text, (theme.INFO_INK, theme.INFO_BG))
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(bg))
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        painter.setFont(f)
        painter.setPen(theme.qcolor(ink))
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter,
                         fm.elidedText(text, Qt.ElideRight, max(0, w - 12)))


class _LeadHeader(QHeaderView):
    """The table's header, painted whole: 11px uppercase labels lined up with
    the cell content, a hairline beneath, a quiet rule on each edge you can
    drag (accent while hovered), and over the tick column Apollo's "Bulk
    Selection" — the box ticks or clears this page, the caret beside it opens
    the choices (select this page, all, a number of people). Painted rather
    than styled so no platform style can float a sort arrow or a grid line
    into it."""

    toggleAll = Signal()
    bulkMenuRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self._state = Qt.Unchecked
        self._hot_edge = -1                 # the column whose right edge is under the mouse
        self._hot_box = False               # the mouse is on the select-all box
        self._hot_caret = False             # …or on the Bulk Selection caret
        self.setSectionsClickable(False)    # the Sort combo is the one sort control
        self.setHighlightSections(False)
        self.setSortIndicatorShown(False)
        self.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.setFixedHeight(_HEAD_H)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def check_state(self):
        return self._state

    def set_check_state(self, state) -> None:
        if state != self._state:
            self._state = state
            self.viewport().update()

    def _edge_at(self, x: int) -> int:
        """The resizable column whose right edge — its drag grip — is under x."""
        for col in range(self.count()):
            if (self.isSectionHidden(col)
                    or self.sectionResizeMode(col) != QHeaderView.Interactive):
                continue
            if abs(x - self.sectionViewportPosition(col) - self.sectionSize(col)) <= 4:
                return col
        return -1

    def paintSection(self, painter, rect, logical):
        painter.save()
        painter.fillRect(rect, theme.qcolor(theme.CARD))
        painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1),
                         theme.qcolor(theme.HAIRLINE))
        if logical == _C_TICK:
            _paint_check(painter, QRect(rect.left(), rect.top(), _TICK_BOX, rect.height()),
                         self._state, self._hot_box)
            self._paint_caret(painter, self._caret_rect(rect))
        else:
            label = str(self.model().headerData(logical, Qt.Horizontal, Qt.DisplayRole) or "")
            f = _font(11, QFont.DemiBold, theme.FONT_HEADING)
            f.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
            painter.setFont(f)
            painter.setPen(QColor(theme.NEUTRAL[600]))
            inset = theme.SPACE_2 if logical == _C_LEAD else _PAD     # over the avatar
            align = Qt.AlignRight if logical == _C_FIT else Qt.AlignLeft
            painter.drawText(rect.adjusted(inset, 0, -_PAD, 0), align | Qt.AlignVCenter,
                             label.upper())
        # A faint rule between the labelled columns keeps their rhythm even; the
        # one under the mouse lights up only where a drag would resize (the
        # cursor tells the same truth).
        if logical not in (_C_TICK, self.logicalIndex(self.count() - 1)):
            hot = logical == self._hot_edge
            painter.fillRect(QRect(rect.right() - (1 if hot else 0), rect.top() + 10,
                                   2 if hot else 1, rect.height() - 20),
                             QColor(theme.ACCENT if hot else theme.NEUTRAL[200]))
        painter.restore()

    def _tick_section(self) -> QRect:
        """The tick column's heading, in the viewport's coordinates."""
        return QRect(self.sectionViewportPosition(_C_TICK), 0,
                     self.sectionSize(_C_TICK), self.viewport().height())

    @staticmethod
    def _caret_rect(section: QRect) -> QRect:
        """The Bulk Selection caret: what the tick column has right of its box."""
        return QRect(section.left() + _TICK_BOX - 8, section.top(),
                     max(0, section.width() - _TICK_BOX + 8), section.height())

    def caret_rect(self) -> QRect:
        """The caret in the header's own coordinates — what the tour rings and
        where the Bulk Selection popup opens under."""
        vp = self.viewport()
        box = self._caret_rect(self._tick_section())
        at = self.mapFromGlobal(vp.mapToGlobal(box.topLeft()))
        return QRect(at, box.size())

    def _paint_caret(self, painter, rect: QRect) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(theme.qcolor(theme.ACCENT if self._hot_caret else theme.NEUTRAL[500]), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        cx, cy = rect.center().x() - 2, rect.center().y() + 1
        path = QPainterPath()
        path.moveTo(cx - 4, cy - 2)
        path.lineTo(cx, cy + 2)
        path.lineTo(cx + 4, cy - 2)
        painter.drawPath(path)
        painter.restore()

    def _hover(self, edge: int, box: bool, caret: bool = False) -> None:
        if (edge, box, caret) != (self._hot_edge, self._hot_box, self._hot_caret):
            self._hot_edge, self._hot_box, self._hot_caret = edge, box, caret
            self.viewport().update()

    def _part_at(self, x: int) -> str:
        """"box", "caret" or "" — what of the tick column's heading is at x."""
        if self._edge_at(x) >= 0 or self.logicalIndexAt(x) != _C_TICK:
            return ""
        return "caret" if x >= self._caret_rect(self._tick_section()).left() else "box"

    def mouseMoveEvent(self, event):
        x = event.position().toPoint().x()
        if event.buttons():
            self._hover(self._hot_edge, False)          # mid-drag: keep the grip lit
        else:
            part = self._part_at(x)
            self._hover(self._edge_at(x), part == "box", part == "caret")
        super().mouseMoveEvent(event)

    def _press(self, event) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        part = self._part_at(event.position().toPoint().x())
        if part == "box":
            self.toggleAll.emit()
        elif part == "caret":
            self.bulkMenuRequested.emit()
        else:
            return False
        event.accept()
        return True

    def mousePressEvent(self, event):
        if not self._press(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # The second press of a double click is a click too, as on any checkbox.
        if not self._press(event):
            super().mouseDoubleClickEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover(-1, False)
        return super().viewportEvent(event)


class _LeadTable(QTableWidget):
    """The lead table, with what a list you work through needs: a click
    anywhere in the tick column ticks that row without opening the drawer,
    Space ticks the current row, Esc asks for the drawer to close, and the
    cell under the mouse is tracked so the delegates can light its row."""

    tickRequested = Signal(int)             # a row
    escapePressed = Signal()

    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self.hover_row = -1
        self.hover_col = -1
        self._ticking = False               # a press in the tick column owns this click
        self.viewport().setMouseTracking(True)
        # Rows slide under a still mouse while scrolling: re-read what's under it.
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._hover_at_cursor())

    def _hover(self, row: int, col: int) -> None:
        if (row, col) == (self.hover_row, self.hover_col):
            return
        rows = {self.hover_row, row}
        self.hover_row, self.hover_col = row, col
        vp = self.viewport()
        for r in rows:
            if r >= 0:
                vp.update(QRect(0, self.rowViewportPosition(r), vp.width(), self.rowHeight(r)))

    def _hover_at_cursor(self) -> None:
        if not self.viewport().underMouse():
            self._hover(-1, -1)
            return
        p = self.viewport().mapFromGlobal(QCursor.pos())
        row = self.rowAt(p.y())
        self._hover(row, self.columnAt(p.x()) if row >= 0 else -1)

    def _cell_at(self, event) -> tuple:
        p = event.position().toPoint()
        return self.rowAt(p.y()), self.columnAt(p.x())

    def mouseMoveEvent(self, event):
        row, col = self._cell_at(event)
        self._hover(row, col if row >= 0 else -1)
        if self._ticking:
            return                          # no drag-select out of a tick
        super().mouseMoveEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Leave, QEvent.HoverLeave):
            self._hover(-1, -1)
        return super().viewportEvent(event)

    def _tick_press(self, event) -> bool:
        row, col = self._cell_at(event)
        if event.button() != Qt.LeftButton or row < 0 or col != _C_TICK:
            return False
        self._ticking = True
        self.setFocus(Qt.MouseFocusReason)
        self.tickRequested.emit(row)
        event.accept()
        return True

    def mousePressEvent(self, event):
        if not self._tick_press(event):
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        # The second press of a double click ticks again, as on any checkbox.
        if not self._tick_press(event):
            super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event):
        if self._ticking:
            self._ticking = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space and self.currentRow() >= 0:
            self.tickRequested.emit(self.currentRow())
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.escapePressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _BulkSelect(QFrame):
    """Apollo's Bulk Selection, under the header's caret (knowledge.apollo.io
    "Search for People": "Select number of people lets you specify how many
    people to select from your search results. Max people per company limits
    how many people Apollo selects from any single company. Select this page
    selects everyone on the current page. Select all selects all available
    people from the search results.") — and Clear selection. A popup: it
    closes on any pick, or on a click anywhere else."""

    pageRequested = Signal()
    allRequested = Signal()
    numberRequested = Signal(int, int)      # how many, at most this many per company (0: any)
    clearRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("bulkSelect")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#bulkSelect{{background:{theme.CARD};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#bulkSelect QPushButton#bulkPick{{background:transparent;border:none;"
            f"text-align:left;padding:6px 8px;border-radius:{theme.R_CHIP}px;"
            f"color:{theme.TEXT};font-size:13px;font-weight:500;}}"
            f"QFrame#bulkSelect QPushButton#bulkPick:hover{{background:{theme.WELL};}}"
            f"QFrame#bulkSelect QLabel{{color:{theme.NEUTRAL[700]};font-size:12px;"
            f"font-weight:600;background:transparent;}}"
            f"QFrame#bulkSelect QSpinBox{{padding:4px 8px;min-height:20px;font-size:13px;}}")
        from PySide6.QtWidgets import QSpinBox
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
        col.setSpacing(2)
        self.page_btn = self._pick(self.pageRequested)
        self.all_btn = self._pick(self.allRequested)
        col.addWidget(self.page_btn)
        col.addWidget(self.all_btn)
        col.addWidget(self._rule())
        form = QVBoxLayout()
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        form.addWidget(QLabel(i18n.t("Select number of people")))
        self.number = QSpinBox()
        self.number.setRange(1, 100000)
        self.number.setValue(25)
        self.number.setAccessibleName(i18n.t("Select number of people"))
        form.addWidget(self.number)
        form.addSpacing(4)
        form.addWidget(QLabel(i18n.t("Max people per company")))
        self.per_company = QSpinBox()
        self.per_company.setRange(0, 1000)
        self.per_company.setSpecialValueText(i18n.t("No limit"))
        self.per_company.setAccessibleName(i18n.t("Max people per company"))
        form.addWidget(self.per_company)
        form.addSpacing(4)
        self.apply_btn = C.button(i18n.t("Select"), "primary", on_click=self._apply)
        form.addWidget(self.apply_btn, 0, Qt.AlignRight)
        col.addLayout(form)
        col.addWidget(self._rule())
        self.clear_btn = self._pick(self.clearRequested)
        self.clear_btn.setText(i18n.t("Clear selection"))
        col.addWidget(self.clear_btn)
        self.setMinimumWidth(248)

    def _pick(self, signal) -> QPushButton:
        b = QPushButton()
        b.setObjectName("bulkPick")
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(lambda _=False: (self.hide(), signal.emit()))
        return b

    @staticmethod
    def _rule() -> QFrame:
        rule = QFrame()
        rule.setObjectName("bulkRule")
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame#bulkRule{{background:{theme.HAIRLINE};border:none;}}")
        return rule

    def set_counts(self, page: int, total: int, selected: int) -> None:
        """What each choice would take: this page's people, and all of them."""
        self.page_btn.setText(i18n.t("Select this page ({n})").format(n=f"{page:,}"))
        self.all_btn.setText(i18n.t("Select all ({n})").format(n=f"{total:,}"))
        self.number.setMaximum(max(1, total))
        self.clear_btn.setEnabled(selected > 0)
        self.apply_btn.setEnabled(total > 0)

    def _apply(self) -> None:
        self.hide()
        self.numberRequested.emit(int(self.number.value()), int(self.per_company.value()))


class _SplitHandle(QSplitterHandle):
    """A handle you can find without seeing a fat bar: a 6px grab area that
    draws one 1px rule, lit in the accent while hovered or dragged."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hot = False
        self._held = False
        self.setCursor(Qt.SplitHCursor if orientation == Qt.Horizontal else Qt.SplitVCursor)

    def _light(self, on: bool) -> None:
        if on != self._hot:
            self._hot = on
            self.update()

    def enterEvent(self, event):
        self._light(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._light(self._held)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._held = True
        self._light(True)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._held = False
        self._light(self.underMouse())
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), theme.qcolor(theme.CARD))
        mid = self.width() // 2
        if self._hot:
            p.fillRect(QRect(mid - 1, 0, 2, self.height()), theme.qcolor(theme.ACCENT))
        else:
            p.fillRect(QRect(mid, 0, 1, self.height()), theme.qcolor(theme.HAIRLINE))


class _Splitter(QSplitter):
    def createHandle(self):
        return _SplitHandle(self.orientation(), self)


class _Reveal(QWidget):
    """A box that shows as much of one widget as its own size allows, keeping
    the widget at full size inside it. Animating the box's height (the bulk
    bar) or width (the drawer) then slides the content in whole, instead of
    squashing its layout for a few frames. At rest `extent` is 0 and the
    content simply fills the box. A horizontal box can also paint a soft
    shadow down its left edge, for a drawer floating over the table."""

    def __init__(self, child: QWidget, orientation=Qt.Vertical, parent=None):
        super().__init__(parent)
        self._child = child
        self._vertical = orientation == Qt.Vertical
        self._shadow = 0
        self.extent = 0                     # the content's length while a slide runs
        child.setParent(self)
        if self._vertical:
            self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def shadow(self) -> int:
        return self._shadow

    def set_shadow(self, px: int) -> None:
        """A painted gradient, not a QGraphicsEffect — see controls.shadows_enabled
        for why this app never trusts those to render."""
        self._shadow = max(0, int(px))
        self._fit()
        self.update()

    def paintEvent(self, event):
        if self._shadow and not self._vertical:
            p = QPainter(self)
            fade = QLinearGradient(0, 0, self._shadow, 0)
            fade.setColorAt(0.0, theme.c(theme.SHADOW_INK, 0.0))
            fade.setColorAt(1.0, theme.c(theme.SHADOW_INK, 0.10))
            p.fillRect(QRect(0, 0, self._shadow, self.height()), fade)
        super().paintEvent(event)

    def sizeHint(self) -> QSize:
        return self._child.sizeHint()

    def minimumSizeHint(self) -> QSize:
        # Claims no width: what it holds sheds its own extras when narrow
        # (_fit_bulk), and a claimed minimum pushed the bar past the results.
        m = self._child.minimumSizeHint()
        return QSize(0, 0) if self._vertical else QSize(0, m.height())

    def event(self, event):
        if event.type() == QEvent.LayoutRequest:
            self.updateGeometry()           # the content's hint moved: tell our parent
            self._fit()
        return super().event(event)

    def resizeEvent(self, event):
        self._fit()
        super().resizeEvent(event)

    def _fit(self) -> None:
        if self._vertical:
            self._child.setGeometry(0, 0, self.width(), max(self.height(), self.extent))
        else:
            s = self._shadow
            self._child.setGeometry(s, 0, max(self.width() - s, self.extent), self.height())


class LeadsCockpit(QWidget):
    """Find People — Apollo's page (23-Sep-2026: "copy the entire architecture
    and interface of apollo"):

        Find people                                              [Import ▾]
        [Default view ▾] [Hide filters] [Search people] [Research with AI ▾]
          [Save as new search]              [Table|Cards] [Sort ▾] [⚙]
        ┌ Total · Net New · Saved ┐ ┌ NAME … the table …                  ┐
        │ the filter facets        │ │                                     │
        │ [Find new people]        │ │ ‹ [1] ›  1 – 25 of 312              │
        └──────────────────────────┘ └ the action bar, once rows are ticked┘

    It is a VIEW. The workbench owns the pool (addons/leads/pool.py), filters,
    splits, sorts and pages it, and hands one page here (`set_people`); every
    control on this page says what the owner asked by a signal. `set_dossiers`
    still fills it straight from one run's dossiers (Analytics, tests) — then
    the table sorts itself, as it always did. The *Requested signals carry the
    ticked rows out to the workbench's workers."""

    verifyRequested = Signal(list)
    emailsRequested = Signal(list)
    phonesRequested = Signal(list)          # Find phones: each company's published number
    exportRequested = Signal(list)
    saveListRequested = Signal(list)
    sequenceRequested = Signal(list)
    qualifyRequested = Signal(list)
    saveContactsRequested = Signal(list)    # Apollo's "Save": make them contacts
    stageRequested = Signal(list, str)      # Apollo's Edit > Set stage: rows, stage
    # Remove: take the rows off the list (removed.py) — the owner's "Clear",
    # 23-Sep-2026. removedRequested: the rail's "N removed", to restore.
    removeRequested = Signal(list)
    removedRequested = Signal()
    importRequested = Signal(str)           # "contacts" | "accounts"
    tabChanged = Signal(str)                # "total" | "net_new" | "saved"
    pageRequested = Signal(int)             # 0-based
    sortChanged = Signal(str)               # a _SORTS key
    queryChanged = Signal(str)              # the Search people box
    settingsRequested = Signal()
    saveSearchRequested = Signal()
    savedSearchPicked = Signal(str)         # a saved search's id
    starterPicked = Signal(str)             # a starter search's key (set_starters)
    manageSearchesRequested = Signal()
    findPrepareRequested = Signal()         # Research with AI ▸ find and qualify

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dossiers: list = []
        self._people: list = []             # the page's pool.Person rows, when pooled
        self._pooled = False                # fed by set_people (else set_dossiers)
        self._tab = "total"
        self._draft_by: dict = {}
        self._checked: set = set()          # dossier indices ticked (shared view)
        # A pooled page's selection outlives the page (Apollo's: tick people
        # on page 1, go on to page 2, the count keeps them): everyone in the
        # result, in its order, and the identity keys of everyone selected.
        self._universe: list = []
        self._sel_keys: set = set()
        self._hidden: set = set()           # dossier indices hidden by the filters
        self._card_cbs: dict = {}           # idx → the gallery card's checkbox
        self._view = "table"                # "table" (dense) or "cards" (gallery)
        self._rail_pref = _RAIL_W           # the rail's width, to come back to after a fold
        self._drawer_pref = _DRAWER_W       # the docked drawer's width, as last dragged
        self._col_pref = dict(_COL_WIDTH)   # column widths as the user last left them
        self._fitting = False               # _fit_columns is resizing, not the user
        self._drawer_docked = False         # the drawer is in the splitter (else floats)
        self._drawer_t = 0.0                # 0 shut … 1 open: what its geometry shows now
        self._drawer_opening = False        # where the drawer's slide is headed
        self._bulk_open = False             # where the bulk bar is headed
        self._drawer_anim = QVariantAnimation(self)
        self._drawer_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._drawer_anim.valueChanged.connect(self._drawer_step)
        self._drawer_anim.finished.connect(self._drawer_landed)
        self._placing = False               # _move_drawer is mid-move: don't re-enter
        # Resizes place the drawer on the next turn of the event loop, never
        # inside the resize: docking resizes the results, and placing again
        # from within that left their layout finishing with a stale width.
        self._place_timer = QTimer(self)
        self._place_timer.setSingleShot(True)
        self._place_timer.setInterval(0)
        self._place_timer.timeout.connect(self._place_drawer)
        self._build()

    # ── construction ──────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # Apollo's two rows over the whole page — the title with Import, then
        # the toolbar — both full width, above the rail as well as the table.
        root.addWidget(self._title_row())
        root.addWidget(self._toolbar_row())
        # rail | results | drawer, in a splitter the user can drag. The drawer is
        # in the splitter only while there's room to dock it; on a narrow window
        # it floats over the results instead — see _place_drawer.
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._split = _Splitter(Qt.Horizontal)
        self._split.setHandleWidth(_HANDLE_W)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._filter_rail())
        self._center_w = self._center()
        self._split.addWidget(self._center_w)
        # A wider window widens the results; the rail and drawer keep their width.
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([_RAIL_W, 4 * _RAIL_W])
        self._split.splitterMoved.connect(self._on_split_moved)
        body.addWidget(self._split)
        self._drawer()
        self._body.installEventFilter(self)
        root.addWidget(self._body, 1)
        self._show_empty(True)
        self._refresh_bulk()

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Resize and obj in (getattr(self, "_body", None),
                                             getattr(self, "_view_stack", None)):
            # The body resizing moves the dock threshold; the results column
            # resizing (the bulk bar sliding) moves a floating drawer's foot.
            self._place_timer.start()
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_table_vp", None):
            self._fit_columns()
        # Show as well as Resize: off screen the toolbar and the bulk bar keep
        # everything (a tab away, or the bar hidden between ticks), and coming
        # back at the same width sends no Resize — so without Show they stayed
        # unfolded and Qt crushed their labels to stubs.
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_toolbar", None):
            self._fit_toolbar()
        elif kind in (QEvent.Resize, QEvent.Show) and obj is getattr(self, "_bulk_bar_w", None):
            self._fit_bulk()
        return super().eventFilter(obj, event)

    def _filter_rail(self) -> QWidget:
        """Apollo's left column: Total · Net New · Saved, then the filters (the
        workbench mounts its FilterPanel — set_search_panel), then the one paid
        action (Find new people — set_find_panel). Every filter is a facet now:
        the "refine" controls this rail used to carry (deliverability, minimum
        fit, qualified only, a search box) filtered ONE page of a run; they are
        facets and the toolbar's Search people, applied to the whole pool
        before it is paged. The rail scrolls on its own, so a short window
        never crushes a control; its edge drags between _RAIL_MIN and _RAIL_MAX."""
        self._rail = QScrollArea()
        self._rail.setObjectName("leadsRail")
        self._rail.setMinimumWidth(_RAIL_MIN)
        self._rail.setMaximumWidth(_RAIL_MAX)
        self._rail.setWidgetResizable(True)
        self._rail.setFrameShape(QFrame.NoFrame)
        self._rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rail.verticalScrollBar().setSingleStep(_STEP)
        # No border-right: the splitter handle beside it draws the rule.
        self._rail.setStyleSheet(
            f"QScrollArea#leadsRail{{background:{theme.CARD};border:none;}}")
        inner = QWidget()
        inner.setObjectName("leadsRailInner")
        inner.setAttribute(Qt.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget#leadsRailInner{{background:{theme.CARD};}}")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        lay.setSpacing(theme.SPACE_3)

        lay.addWidget(self._tabs_bar())
        # Whoever was taken off the list (Remove), one click from coming back.
        # Only there while somebody is: an empty "0 removed" is noise.
        self._removed_link = QPushButton()
        self._removed_link.setObjectName("removedLink")
        self._removed_link.setCursor(Qt.PointingHandCursor)
        self._removed_link.setToolTip(i18n.t("People you took off the list. Open "
                                             "to put any of them back."))
        self._removed_link.setStyleSheet(
            f"QPushButton#removedLink{{background:transparent;border:none;"
            f"color:{theme.NEUTRAL[600]};padding:0px 2px;font-size:12px;"
            f"font-weight:600;text-align:right;}}"
            f"QPushButton#removedLink:hover{{color:{theme.TEXT};"
            f"text-decoration:underline;}}")
        self._removed_link.clicked.connect(lambda _=False: self.removedRequested.emit())
        self._removed_link.hide()
        lay.addWidget(self._removed_link, 0, Qt.AlignRight)

        self._search_slot = QVBoxLayout()
        self._search_slot.setContentsMargins(0, 0, 0, 0)
        self._search_slot.setSpacing(0)
        lay.addLayout(self._search_slot)

        self._find_slot = QVBoxLayout()
        self._find_slot.setContentsMargins(0, 0, 0, 0)
        self._find_slot.setSpacing(theme.SPACE_1)
        lay.addLayout(self._find_slot)
        lay.addStretch(1)
        lay.addWidget(_muted("Manual, 1:1 — Prism drafts and paces the touches; you "
                             "send from your own inbox. No auto-DMs.", 11))
        self._rail.setWidget(inner)
        return self._rail

    def _tabs_bar(self) -> QWidget:
        """Total · Net New · Saved, each with its count under its name — the
        way Apollo stacks them over its filters."""
        seg = QFrame()
        seg.setObjectName("peopleTabs")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"QFrame#peopleTabs{{background:{theme.WELL};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#peopleTabs QPushButton{{background:transparent;border:none;"
            f"border-radius:{theme.R_CHIP}px;color:{theme.NEUTRAL[600]};"
            f"padding:5px 4px;font-size:12px;font-weight:600;text-align:center;}}"
            f"QFrame#peopleTabs QPushButton:hover{{color:{theme.TEXT};}}"
            f"QFrame#peopleTabs QPushButton:checked{{background:{theme.CARD};"
            f"color:{theme.TEXT};}}")
        lay = QHBoxLayout(seg)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._tab_btns: dict = {}
        self._tab_counts: dict = {key: 0 for key, _ in _PEOPLE_TABS}
        for key, name in _PEOPLE_TABS:
            b = QPushButton()
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, k=key: self._pick_tab(k))
            lay.addWidget(b, 1)
            self._tab_btns[key] = b
        self._tabs_frame = seg
        self._paint_tabs()
        return seg

    def _paint_tabs(self) -> None:
        for key, name in _PEOPLE_TABS:
            b = self._tab_btns[key]
            # The name through the catalogue by hand: with its count under
            # it, the whole text matches no entry (i18n.py, Templates).
            b.setText(f"{i18n.t(name)}\n{self._tab_counts.get(key, 0):,}")
            b.setChecked(key == self._tab)

    def _pick_tab(self, key: str) -> None:
        self._tab = key
        self._paint_tabs()
        self.tabChanged.emit(key)

    def tab(self) -> str:
        return self._tab

    def set_tab(self, key: str) -> None:
        """Select a tab without emitting — the workbench restoring one."""
        if key in self._tab_btns:
            self._tab = key
            self._paint_tabs()

    def set_removed_count(self, n: int) -> None:
        """How many people are off the list — the rail's "N removed" link,
        hidden while nobody is."""
        n = max(0, int(n or 0))
        self._removed_link.setText(i18n.t("{n} removed · Restore").format(n=f"{n:,}"))
        self._removed_link.setVisible(n > 0)

    def set_counts(self, counts: dict) -> None:
        """The three tabs' counts, {"total", "net_new", "saved"}."""
        for key, _name in _PEOPLE_TABS:
            self._tab_counts[key] = int((counts or {}).get(key, 0) or 0)
        self._paint_tabs()

    def set_search_panel(self, widget: QWidget) -> None:
        """Mount the filter column (the workbench's FilterPanel) under the
        tabs — Apollo's facets."""
        _clear(self._search_slot)
        self._search_slot.addWidget(widget)

    def set_find_panel(self, widget: QWidget) -> None:
        """Mount the paid search — Find new people and its estimate — under
        the filters, with a rule between: the one thing on this page that
        spends, set apart from everything that is free."""
        _clear(self._find_slot)
        rule = QFrame()
        rule.setObjectName("railRule")
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame#railRule{{background:{theme.HAIRLINE};border:none;}}")
        self._find_slot.addSpacing(theme.SPACE_2)
        self._find_slot.addWidget(rule)
        self._find_slot.addSpacing(theme.SPACE_2)
        self._find_slot.addWidget(widget)

    # ── the page's own two rows (Apollo's) ───────────────────────────────────
    def _title_row(self) -> QWidget:
        """"Find people" and, at the far right, Import ▾ — Apollo's People >
        Import > CSV. Importing is its own action here, never a mode of the
        search: the file becomes a "Contact CSV import" / "Account CSV import"
        filter value, and nothing is searched."""
        bar = QFrame()
        bar.setObjectName("peopleTitle")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(f"QFrame#peopleTitle{{background:{theme.CARD};border:none;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_3)
        title = QLabel("Find people")
        title.setObjectName("peopleTitleText")
        title.setStyleSheet(theme.type_css("SECTION", theme.TEXT))
        lay.addWidget(title, 0, Qt.AlignVCenter)
        lay.addStretch(1)
        self._import_btn = self._menu_button("Import", "importBtn")
        menu = self._import_btn.menu()
        a = menu.addAction(i18n.t("Contacts — people from a CSV or Excel file…"))
        a.triggered.connect(lambda: self.importRequested.emit("contacts"))
        a = menu.addAction(i18n.t("Accounts — companies from a CSV or Excel file…"))
        a.triggered.connect(lambda: self.importRequested.emit("accounts"))
        lay.addWidget(self._import_btn, 0, Qt.AlignVCenter)
        return bar

    def _menu_button(self, text: str, name: str, icon_name: str = ""):
        """A toolbar button that opens a menu — Apollo's "Default view ▾",
        "Research with AI ▾", "Import ▾" — outlined like Apollo's, with the
        caret the Sort box wears."""
        from PySide6.QtWidgets import QToolButton
        b = QToolButton()
        b.setObjectName(name)
        b.setText(text)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if icon_name
                             else Qt.ToolButtonTextOnly)
        if icon_name:
            b.setIcon(icons.icon(icon_name, 15, theme.NEUTRAL[700]))
        b.setCursor(Qt.PointingHandCursor)
        b.setMenu(QMenu(b))
        b.setStyleSheet(
            f"QToolButton#{name}{{background:{theme.CARD};color:{theme.NEUTRAL[800]};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 26px 5px 10px;min-height:20px;font-size:12px;"
            f"font-weight:600;}}"
            f"QToolButton#{name}:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}"
            f"QToolButton#{name}::menu-indicator{{image:url({_asset('caret-down.svg')});"
            f"subcontrol-position:right center;subcontrol-origin:padding;"
            f"right:8px;width:12px;height:12px;}}")
        return b

    def _toolbar_row(self) -> QWidget:
        """Apollo's toolbar, full width over the rail and the table:
        Default view ▾ · Hide filters · Search people · Research with AI ▾ ·
        Save as new search … Table|Cards · Sort ▾ · Search settings."""
        self._toolbar = QFrame()
        self._toolbar.setObjectName("resultsBar")
        self._toolbar.setAttribute(Qt.WA_StyledBackground, True)
        # Its full dress is wider than a 1366 window's page, and a layout
        # passes a child's minimum up to the window — so, Ignored: the bar
        # takes the width it is given and _fit_toolbar drops labels to fit,
        # instead of the bar forcing the whole window wider.
        self._toolbar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._toolbar.setStyleSheet(
            f"QFrame#resultsBar{{background:{theme.CARD};border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QFrame#resultsBar QPushButton#tbBtn{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[800]};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;padding:5px 12px;min-height:20px;"
            f"font-size:12px;font-weight:600;}}"
            f"QFrame#resultsBar QPushButton#tbBtn:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}")
        tlay = QHBoxLayout(self._toolbar)
        tlay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        tlay.setSpacing(theme.SPACE_2)

        # Default view ▾ — the saved searches (Apollo keeps its views there),
        # and the two layouts this page draws.
        self._views_btn = self._menu_button("Default view", "viewsBtn", "grid")
        self._views_menu = self._views_btn.menu()
        self._saved_searches: list = []
        self._starters: list = []           # (key, name) — set_starters
        self._fill_views_menu()
        tlay.addWidget(self._views_btn)
        tlay.addWidget(self._filters_toggle())

        self._search = QLineEdit()
        self._search.setObjectName("peopleSearch")
        self._search.setPlaceholderText("Search people")
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(150)
        self._search.setMaximumWidth(260)
        self._search.addAction(icons.icon("search", 15, theme.NEUTRAL[500]),
                               QLineEdit.LeadingPosition)
        # Debounced: every keystroke would otherwise re-filter the whole pool.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(
            lambda: self.queryChanged.emit(self._search.text().strip()))
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        tlay.addWidget(self._search)

        self._research_btn = self._menu_button("Research with AI", "researchBtn",
                                               "sparkles")
        menu = self._research_btn.menu()
        # Armed the moment it opens, with the reason on a disarmed item: a
        # pick that silently did nothing was 22-Sep's "Nothing changes at all".
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(self._sync_research_menu)
        self._find_prepare_ready = lambda: (True, "")
        self._act_qualify = menu.addAction(i18n.t("Qualify and draft for the people ticked"))
        self._act_qualify.triggered.connect(
            lambda: self.qualifyRequested.emit(self.selected()))
        self._act_find_prepare = menu.addAction(
            i18n.t("Find new people and qualify them — the whole pipeline"))
        self._act_find_prepare.triggered.connect(self.findPrepareRequested.emit)
        tlay.addWidget(self._research_btn)

        self._save_search_btn = QPushButton("Save as new search")
        self._save_search_btn.setObjectName("tbBtn")
        self._save_search_btn.setCursor(Qt.PointingHandCursor)
        self._save_search_btn.setToolTip("Keep these filters to run again later")
        self._save_search_btn.clicked.connect(lambda _=False: self.saveSearchRequested.emit())
        tlay.addWidget(self._save_search_btn)
        tlay.addStretch(1)

        self._seg = self._view_toggle()
        tlay.addWidget(self._seg)
        self._sort = QComboBox()
        self._sort.setObjectName("leadsSort")
        for key, label in _SORTS:
            self._sort.addItem(label, key)
        self._sort.setMinimumWidth(124)
        self._sort.setCursor(Qt.PointingHandCursor)
        self._sort.setToolTip("Sort")
        # One height with the toggle and the view switch (32px), and a caret:
        # the app sheet's combo is 36px with no arrow, so it read as a text box.
        self._sort.setStyleSheet(_combo_sheet())
        self._sort.currentIndexChanged.connect(self._on_sort_changed)
        tlay.addWidget(self._sort)
        self._settings_btn = QPushButton("Search settings")
        self._settings_btn.setObjectName("tbBtn")
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        self._settings_btn.setToolTip(
            "Which database to search, how far a search goes, what you sell, "
            "your keys — the settings every search here runs with")
        icons.button_icon(self._settings_btn, "sliders", 15, theme.NEUTRAL[700])
        self._settings_btn.clicked.connect(lambda _=False: self.settingsRequested.emit())
        tlay.addWidget(self._settings_btn)
        self._toolbar.installEventFilter(self)          # narrow → _fit_toolbar
        return self._toolbar

    def _fill_views_menu(self) -> None:
        menu = self._views_menu
        # Not menu.clear(): that deletes each action at once, and this runs
        # from inside one of them (a pick that refreshes the list) — Qt would
        # still be emitting the action it had just freed.
        for act in menu.actions():
            menu.removeAction(act)
            act.deleteLater()
        head = menu.addAction(i18n.t("Saved searches"))
        head.setEnabled(False)
        if not self._saved_searches:
            none = menu.addAction(i18n.t("None yet — use Save as new search"))
            none.setEnabled(False)
        for record in self._saved_searches[:20]:
            # The owner's own name for it: data, never looked up.
            act = menu.addAction(record.get("name") or i18n.t("Untitled search"))
            act.triggered.connect(lambda _=False, i=record.get("id", ""):
                                  self.savedSearchPicked.emit(i))
        if self._starters:
            menu.addSeparator()
            head = menu.addAction(i18n.t("Starter searches"))
            head.setEnabled(False)
            for key, name in self._starters:
                act = menu.addAction(name)
                act.triggered.connect(lambda _=False, k=key: self.starterPicked.emit(k))
        menu.addSeparator()
        manage = menu.addAction(i18n.t("Manage saved searches…"))
        manage.triggered.connect(self.manageSearchesRequested.emit)
        menu.addSeparator()
        layout = menu.addAction(i18n.t("Layout"))
        layout.setEnabled(False)
        self._layout_acts = {}
        for view, name in (("table", i18n.t("Table")), ("cards", i18n.t("Cards"))):
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(self._view == view)
            act.triggered.connect(lambda _=False, v=view: self._set_view(v))
            self._layout_acts[view] = act

    def set_find_prepare_ready(self, check) -> None:
        """How Research with AI ▸ "Find new people and qualify them" knows it
        can run: check() -> (ok, why) — the workbench's own Find new people,
        asked each time the menu opens."""
        self._find_prepare_ready = check

    def _sync_research_menu(self) -> None:
        """Arm Research with AI's two items exactly as their buttons are."""
        ok = self._qualify_wanted and self._b_qualify.isEnabled()
        self._act_qualify.setEnabled(ok)
        self._act_qualify.setToolTip("" if ok else i18n.t(
            "Tick people who are not qualified yet."))
        try:
            ok, why = self._find_prepare_ready()
        except Exception:                                   # noqa: BLE001
            ok, why = False, ""
        self._act_find_prepare.setEnabled(bool(ok))
        self._act_find_prepare.setToolTip("" if ok else (why or ""))

    def set_saved_searches(self, records) -> None:
        """What Default view ▾ lists (saved_searches.list_searches)."""
        self._saved_searches = list(records or ())
        self._fill_views_menu()

    def set_starters(self, starters) -> None:
        """Default view ▾'s starter searches — [(key, name)], the workbench's
        ready-made filter sets; picking one emits starterPicked(key)."""
        self._starters = [(str(k), str(n)) for k, n in (starters or ())]
        self._fill_views_menu()

    def _pager_bar(self) -> QWidget:
        """Apollo's foot of the results: ‹ [page ▾] ›  "1 - 25 of 312". Only a
        pooled page has pages; a run shown straight from its dossiers hides it."""
        self._pager = QFrame()
        self._pager.setObjectName("peoplePager")
        self._pager.setAttribute(Qt.WA_StyledBackground, True)
        self._pager.setStyleSheet(
            f"QFrame#peoplePager{{background:{theme.CARD};border:none;"
            f"border-top:1px solid {theme.HAIRLINE};}}"
            f"QFrame#peoplePager QPushButton{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[800]};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;padding:5px 10px;min-height:20px;"
            f"min-width:12px;font-size:13px;font-weight:600;}}"
            f"QFrame#peoplePager QPushButton:disabled{{color:{theme.NEUTRAL[300]};"
            f"border-color:{theme.HAIRLINE};}}")
        lay = QHBoxLayout(self._pager)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setToolTip("Previous page")
        self._next_btn = QPushButton("›")
        self._next_btn.setToolTip("Next page")
        self._page_box = QComboBox()
        self._page_box.setObjectName("leadsSort")
        self._page_box.setStyleSheet(_combo_sheet())
        self._page_box.setFixedWidth(72)
        for b in (self._prev_btn, self._next_btn):
            b.setCursor(Qt.PointingHandCursor)
        self._prev_btn.clicked.connect(lambda: self.pageRequested.emit(self._page_index - 1))
        self._next_btn.clicked.connect(lambda: self.pageRequested.emit(self._page_index + 1))
        self._page_box.activated.connect(lambda i: self.pageRequested.emit(i))
        self._range_lbl = QLabel("")
        self._range_lbl.setStyleSheet(f"color:{theme.TEXT};font-size:13px;font-weight:600;")
        lay.addWidget(self._prev_btn)
        lay.addWidget(self._page_box)
        lay.addWidget(self._next_btn)
        lay.addSpacing(theme.SPACE_2)
        lay.addWidget(self._range_lbl)
        lay.addStretch(1)
        self._page_index = 0
        self._pager.hide()
        return self._pager

    def set_page(self, info: dict) -> None:
        """Show which page is on screen — pool.page()'s dict."""
        info = info or {}
        pages = max(1, int(info.get("pages", 1) or 1))
        self._page_index = int(info.get("page", 0) or 0)
        total = int(info.get("total", 0) or 0)
        self._page_box.blockSignals(True)
        if self._page_box.count() != pages:
            self._page_box.clear()
            self._page_box.addItems([str(i + 1) for i in range(pages)])
        self._page_box.setCurrentIndex(min(self._page_index, pages - 1))
        self._page_box.blockSignals(False)
        self._prev_btn.setEnabled(self._page_index > 0)
        self._next_btn.setEnabled(self._page_index < pages - 1)
        self._range_lbl.setText(i18n.t("{a} - {b} of {n}").format(
            a=f"{info.get('start', 0):,}", b=f"{info.get('end', 0):,}", n=f"{total:,}"))
        self._pager.setVisible(self._pooled and total > 0)

    def _center(self) -> QWidget:
        wrap = QWidget()
        # On a narrow window the rail gives way (down to its minimum) before
        # the results do.
        wrap.setMinimumWidth(_TABLE_MIN)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self._table = self._build_table()

        # Nothing loaded yet → a centred empty state, not an empty grid.
        self._empty = C.EmptyState("user", _EMPTY_TITLE, _EMPTY_BODY)

        # Two ways to read the same filtered leads: the dense table (scan power)
        # and a card gallery (the visual, Pinterest-style view). One selection
        # model feeds both, so ticking a card and ticking a row are the same act.
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._table)             # 0 — table
        self._view_stack.addWidget(self._build_gallery())   # 1 — cards
        self._view_stack.addWidget(self._empty)             # 2 — nothing loaded
        self._view_stack.installEventFilter(self)
        col.addWidget(self._view_stack, 1)
        col.addWidget(self._pager_bar())

        self._bulk = self._bulk_bar()
        col.addWidget(self._bulk)
        return wrap

    def _build_table(self) -> QTableWidget:
        t = _LeadTable(0, len(_COLS))
        t.setObjectName("leadsTable")
        self._head = _LeadHeader(t)
        t.setHorizontalHeader(self._head)
        t.setHorizontalHeaderLabels(list(_COLS))
        t.horizontalHeaderItem(_C_TICK).setToolTip("Select all")
        rows = t.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.Fixed)
        rows.setDefaultSectionSize(_ROW_H)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        t.setWordWrap(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        # Per pixel, in 20px steps: per item, one wheel notch jumped three rows.
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.verticalScrollBar().setSingleStep(_STEP)
        t.horizontalScrollBar().setSingleStep(_STEP)
        t.setItemDelegateForColumn(_C_TICK, _TickDelegate(t))
        t.setItemDelegateForColumn(_C_LEAD, _LeadDelegate(t))
        t.setItemDelegateForColumn(_C_FOCUS, _FocusDelegate(t))
        t.setItemDelegateForColumn(_C_FIT, _FitDelegate(t))
        pills = _PillDelegate(t)
        t.setItemDelegateForColumn(_C_STATUS, pills)
        t.setItemDelegateForColumn(_C_SIGNAL, pills)
        head = self._head
        head.setStretchLastSection(False)
        head.setMinimumSectionSize(40)
        # Focus is Fixed rather than Stretch, and _fit_columns hands it the
        # rest of the width: a Stretch column can't be held to a minimum, so a
        # wide Lead squeezed it to a 40px sliver instead of scrolling.
        for c in range(len(_COLS)):
            head.setSectionResizeMode(c, QHeaderView.Interactive if c in _COL_MIN else
                                      QHeaderView.Fixed)
            if c in _COL_WIDTH:
                head.resizeSection(c, _COL_WIDTH[c])
        head.sectionResized.connect(self._on_section_resized)
        head.toggleAll.connect(self._toggle_all_visible)
        head.bulkMenuRequested.connect(self._open_bulk_select)
        self._bulk_select = _BulkSelect(self)
        self._bulk_select.hide()
        self._bulk_select.pageRequested.connect(lambda: self._set_many(self._visible(), True))
        self._bulk_select.allRequested.connect(self._select_all)
        self._bulk_select.numberRequested.connect(self._select_number)
        self._bulk_select.clearRequested.connect(self._clear_ticks)
        t.tickRequested.connect(self._tick_row)
        t.escapePressed.connect(self._dismiss_drawer)
        t.itemChanged.connect(self._on_item_changed)
        t.currentCellChanged.connect(lambda *_: self._show_selected())
        self._table_vp = t.viewport()
        self._table_vp.installEventFilter(self)
        # The app sheet hides every horizontal scrollbar (height 0); this table
        # can overflow sideways once columns are dragged wide, so it gets a thin one.
        t.setStyleSheet(
            f"QTableWidget#leadsTable{{background:{theme.CARD};border:none;"
            f"border-radius:0px;outline:0;}}"
            f"QTableWidget#leadsTable QHeaderView{{background:{theme.CARD};border:none;}}"
            f"QTableWidget#leadsTable QScrollBar:horizontal{{height:9px;"
            f"background:transparent;margin:0px;}}"
            f"QTableWidget#leadsTable QScrollBar::handle:horizontal{{"
            f"background:{theme.NEUTRAL[300]};border-radius:4px;min-width:30px;}}"
            f"QTableWidget#leadsTable QScrollBar::handle:horizontal:hover{{"
            f"background:{theme.NEUTRAL[400]};}}"
            f"QTableWidget#leadsTable QScrollBar::add-line:horizontal,"
            f"QTableWidget#leadsTable QScrollBar::sub-line:horizontal{{width:0px;}}")
        return t

    def _filters_toggle(self) -> QPushButton:
        """Hide filters / Show filters — Apollo's switch: fold the rail away for
        a wider table, and bring it back at the width it had. Apollo puts the
        number of filters on beside the words ("Hide Filters 1") — so the owner
        can see filters are on even with the rail folded away."""
        self._filters_label = i18n.t("Hide filters")
        self._filter_count = 0
        b = QPushButton(self._filters_label)
        b.setObjectName("filtersToggle")
        b.setToolTip(self._filters_label)
        b.setCursor(Qt.PointingHandCursor)
        icons.button_icon(b, "list", 15, theme.NEUTRAL[700])
        b.setStyleSheet(
            f"QPushButton#filtersToggle{{background:{theme.CARD};color:{theme.NEUTRAL[800]};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 12px 5px 10px;min-height:20px;font-size:12px;font-weight:600;}}"
            f"QPushButton#filtersToggle:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}")
        b.clicked.connect(lambda: self.set_filters_shown(self._rail.isHidden()))
        self._filters_btn = b
        return b

    def set_filters_shown(self, show: bool) -> None:
        """Fold the rail away, or bring it back at the width it had when folded."""
        rail = self._rail
        if show != rail.isHidden():
            return                          # already that way
        if show:
            rail.show()
            self._split_sizes(rail=self._rail_pref)
        else:
            if rail.isVisible() and rail.width() >= _RAIL_MIN:
                self._rail_pref = min(_RAIL_MAX, rail.width())
            rail.hide()
        # Looked up here, not stored in English: the label is sent to the
        # button with the count beside it, which no catalogue entry matches.
        self._filters_label = i18n.t("Hide filters") if show else i18n.t("Show filters")
        self._filters_btn.setToolTip(self._filters_label)
        self._fit_toolbar()                 # puts the new label on, unless icon-only
        self._split.refresh()
        self._place_drawer()

    def set_filter_count(self, n: int) -> None:
        """How many filters are on — shown on Hide filters, Apollo's way."""
        self._filter_count = max(0, int(n or 0))
        self._fit_toolbar()

    def _filters_text(self) -> str:
        return (f"{self._filters_label}  {self._filter_count}" if self._filter_count
                else self._filters_label)

    def _view_toggle(self) -> QWidget:
        seg = QFrame()
        seg.setObjectName("viewSeg")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"QFrame#viewSeg{{background:{theme.WELL};border:1px solid {theme.HAIRLINE};"
            f"border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#viewSeg QPushButton{{background:transparent;border:none;"
            f"color:{theme.NEUTRAL[600]};padding:3px 14px;min-height:20px;"
            f"font-size:12px;font-weight:600;border-radius:{theme.R_CHIP}px;}}"
            f"QFrame#viewSeg QPushButton:hover{{color:{theme.TEXT};}}"
            f"QFrame#viewSeg QPushButton:checked{{background:{theme.CARD};"
            f"color:{theme.TEXT};}}")
        lay = QHBoxLayout(seg)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._view_table_btn = QPushButton("Table")
        self._view_cards_btn = QPushButton("Cards")
        for b, v in ((self._view_table_btn, "table"), (self._view_cards_btn, "cards")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, view=v: self._set_view(view))
            lay.addWidget(b)
        self._view_table_btn.setChecked(True)
        return seg

    def _set_view(self, view: str) -> None:
        self._view = view
        self._view_table_btn.setChecked(view == "table")
        self._view_cards_btn.setChecked(view == "cards")
        for key, act in getattr(self, "_layout_acts", {}).items():
            act.setChecked(key == view)     # Default view's Layout ticks follow
        if not self._dossiers:
            self._show_empty(True)
            return
        self._view_stack.setCurrentIndex(0 if view == "table" else 1)
        if view == "cards":
            self._fill_gallery()

    def _show_empty(self, empty: bool) -> None:
        """Nobody to show: a centred empty state instead of an empty grid, and
        no bulk bar offering to act on nobody. The toolbar STAYS — it holds
        Import, Search people and the filters' switch, which is exactly how
        someone gets from nobody to somebody."""
        if empty:
            self._land_bulk(False)
            self._view_stack.setCurrentIndex(2)
            self._close_drawer()
        else:
            self._view_stack.setCurrentIndex(0 if self._view == "table" else 1)

    def set_empty_text(self, title: str = "", body: str = "") -> None:
        """What the empty state says. After a leads-only run there ARE leads —
        just none qualified to show here — so the default "No leads yet" would
        tell the user to redo what they just did. Blank restores the default."""
        self._empty.set_text(title or _EMPTY_TITLE, body or _EMPTY_BODY)

    def _build_gallery(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        scroll.verticalScrollBar().setSingleStep(_STEP)
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        hl.setSpacing(0)
        self._grid = C.CardGrid(min_col_width=228)
        hl.addWidget(self._grid)
        hl.addStretch(1)
        scroll.setWidget(host)
        self._gallery = scroll
        return scroll

    def _link(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("bulkLink")
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _bulk_bar(self) -> QWidget:
        """The bulk actions. Hidden until a row is ticked, then it rises from
        the foot of the results with the count, "Select all N" while only some
        are ticked, "Clear", and the actions."""
        bar = QFrame()
        bar.setObjectName("bulkBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#bulkBar{{background:{theme.CARD};border:none;"
            f"border-top:1px solid {theme.DIVIDER};}}"
            f"QFrame#bulkBar QLabel{{color:{theme.TEXT};font-size:13px;font-weight:600;"
            f"background:transparent;border:none;}}"
            f"QFrame#bulkBar QPushButton{{color:{theme.NEUTRAL[800]};background:{theme.CARD};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 14px;min-height:20px;font-family:'{theme.FONT_BODY}';"
            f"font-size:12px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}"
            f"QFrame#bulkBar QPushButton:disabled{{color:{theme.NEUTRAL[400]};"
            f"border-color:{theme.HAIRLINE};background:{theme.CARD};}}"
            f"QFrame#bulkBar QPushButton#primary{{background:{theme.ACCENT};"
            f"border-color:{theme.ACCENT};color:#fff;}}"
            f"QFrame#bulkBar QPushButton#primary:hover{{background:{theme.ACCENT_RAMP[600]};"
            f"border-color:{theme.ACCENT_RAMP[600]};}}"
            f"QFrame#bulkBar QPushButton#primary:disabled{{background:{theme.NEUTRAL[200]};"
            f"border-color:{theme.NEUTRAL[200]};color:{theme.NEUTRAL[500]};}}"
            f"QFrame#bulkBar QPushButton#bulkLink{{background:transparent;border:none;"
            f"color:{theme.ACCENT};padding:5px 6px;font-size:13px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton#bulkLink:hover{{color:{theme.ACCENT_RAMP[700]};"
            f"text-decoration:underline;}}"
            # "Clear" and "Select all" are #bulkLink, a more specific selector
            # than the plain QPushButton:disabled rule above, so without this
            # they kept their normal accent-blue "still clickable" colour while
            # _set_running(True) had genuinely disabled the whole bar under
            # them (live report, 22-Sep-2026: a customer pressed "Clear"
            # while a background search was running, saw nothing happen, and
            # had no way to tell it wasn't just broken).
            f"QFrame#bulkBar QPushButton#bulkLink:disabled{{color:{theme.NEUTRAL[400]};"
            f"text-decoration:none;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 10, theme.SPACE_4, 10)
        lay.setSpacing(theme.SPACE_2)
        self._sel_lbl = QLabel("0 selected")
        lay.addWidget(self._sel_lbl)
        lay.addSpacing(theme.SPACE_2)
        self._sel_all = self._link("Select all")
        self._sel_all.clicked.connect(self._select_all)
        lay.addWidget(self._sel_all)
        # "Clear selection", not "Clear": it only unticks. The owner read a
        # bare "Clear" as taking the people away (23-Sep-2026) — that is
        # Remove's job, beside Save.
        self._bulk_clear = self._link("Clear selection")
        self._bulk_clear.clicked.connect(self._clear_ticks)
        lay.addWidget(self._bulk_clear)
        lay.addStretch(1)
        # Apollo's "Save": the ticked people become saved contacts — the Saved
        # tab, and what every later search counts as not net new.
        self._b_contact = QPushButton("Save")
        self._b_contact.setToolTip("Save the selected people as contacts — they "
                                   "move from Net New to Saved.")
        # Remove: off the list — out of Total, Net New and Saved, and out of
        # every new search — until restored from the rail's "N removed".
        # Nothing is deleted (removed.py); the workbench asks first.
        self._b_remove = QPushButton("Remove")
        self._b_remove.setToolTip("Take the selected people off the list. They leave "
                                  "People and new searches skip them. Restore them "
                                  "any time from Removed, under Total · Net New · Saved.")
        # A Find-people run brings back nobody's address (finding people is
        # free; finding addresses is not) — this is where that is spent, on the
        # rows the owner ticked.
        self._b_emails = QPushButton("Find e-mails")
        from prospector import gateway
        if gateway.pooled():
            # Every check is one credit, taken only when a verifier answers.
            self._b_verify = QPushButton("Verify")
            self._b_verify.setToolTip("Check the selected people's e-mails. A "
                                      "credit is used for each address a "
                                      "verifier answers for.")
            self._b_emails.setToolTip("Find each selected person's real e-mail "
                                      "and check it. A credit is used only when "
                                      "a finder knows the person. Nothing is "
                                      "guessed.")
        else:
            self._b_verify = QPushButton("Verify free")
            self._b_emails.setToolTip("Find each selected person's real e-mail "
                                      "with Hunter, then Apollo, and check it with "
                                      "the free verifiers. A credit is used only "
                                      "when a finder knows the person. Nothing is "
                                      "guessed.")
        # The phone each selected person's COMPANY publishes (its website, or a
        # directory), one lookup per company. Published, not called or verified.
        self._b_phones = QPushButton("Find phones")
        self._b_phones.setToolTip(
            "Look up the phone number each selected person's company publishes on "
            "its own website or a business directory. It is the company's number, "
            "not a direct dial, and Prism has not called it."
            + (" A credit is used only for a number found." if gateway.pooled() else ""))
        self._b_save = QPushButton("Add to list")
        self._b_export = QPushButton("Export")
        # Apollo's Edit > Set stage: where the selected contacts stand with
        # you. Someone not saved yet is saved first — only a contact has one.
        self._b_stage = QPushButton("Set stage")
        self._b_stage.setToolTip("Move the selected people to a stage — Cold, "
                                 "Approaching, Interested… Anyone not saved yet "
                                 "is saved as a contact first.")
        self._stage_menu = QMenu(self._b_stage)
        from addons.leads.contacts import STAGES
        for stage in STAGES:
            # A stage is a record's value, like a list's name — shown as kept.
            act = self._stage_menu.addAction(stage)
            act.triggered.connect(lambda _=False, s=stage: self.stageRequested.emit(
                self.selected(), s))
        self._b_stage.setMenu(self._stage_menu)
        # Runs the qualify pass on the ticked people a run sourced but never
        # qualified. "&&": a lone & in a button label is eaten as a mnemonic.
        self._b_qualify = QPushButton("Qualify && draft")
        self._b_qualify.setToolTip("Research, qualify and draft an email for the "
                                   "selected leads that aren't qualified yet.")
        self._b_seq = QPushButton("Add to sequence")   # Barlow has no →
        self._b_seq.setObjectName("primary")
        self._b_contact.clicked.connect(
            lambda: self.saveContactsRequested.emit(self.selected()))
        self._b_remove.clicked.connect(lambda: self.removeRequested.emit(self.selected()))
        self._b_verify.clicked.connect(lambda: self.verifyRequested.emit(self.selected()))
        self._b_emails.clicked.connect(lambda: self.emailsRequested.emit(self.selected()))
        self._b_phones.clicked.connect(lambda: self.phonesRequested.emit(self.selected()))
        self._b_save.clicked.connect(lambda: self.saveListRequested.emit(self.selected()))
        self._b_export.clicked.connect(lambda: self.exportRequested.emit(self.selected()))
        self._b_qualify.clicked.connect(lambda: self.qualifyRequested.emit(self.selected()))
        self._b_seq.clicked.connect(lambda: self.sequenceRequested.emit(self.selected()))
        # On a narrow window the less-used actions fold into More (_fit_bulk).
        self._b_more = QPushButton("More")
        self._b_more.setToolTip("More actions for the selected leads")
        self._b_more.clicked.connect(self._show_more)
        self._b_more.hide()
        self._qualify_wanted = False        # the run holds someone Qualify can reach
        self._emails_wanted = False         # …and someone without a verified address
        self._phones_wanted = False         # …and someone with no phone at all
        self._sel_all_wanted = False        # only some of the visible rows are ticked
        self._bulk_folded: list = []
        for b in (self._b_contact, self._b_remove, self._b_verify, self._b_emails,
                  self._b_phones, self._b_save, self._b_export, self._b_stage,
                  self._b_qualify, self._b_more, self._b_seq):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        self._bulk_bar_w = bar
        bar.installEventFilter(self)
        slot = _Reveal(bar, Qt.Vertical)
        slot.setObjectName("bulkSlot")
        self._bulk_anim = QPropertyAnimation(slot, b"maximumHeight", self)
        self._bulk_anim.setDuration(_SLIDE_MS)
        self._bulk_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._bulk_anim.finished.connect(lambda: self._land_bulk(self._bulk_open))
        return slot

    def _slide_bulk(self, show: bool) -> None:
        """Bring the bulk bar up when the first row is ticked and take it away
        when the last is cleared: a slide on screen, the end state elsewhere."""
        slot, anim = self._bulk, self._bulk_anim
        running = anim.state() == QAbstractAnimation.Running
        if show == self._bulk_open and (running or slot.isHidden() != show):
            return                          # already there, or on its way
        if not _motion_ok(self):
            self._land_bulk(show)
            return
        self._bulk_open = show
        anim.stop()
        start = 0 if slot.isHidden() else slot.height()
        slot.extent = slot.sizeHint().height()
        slot.setMaximumHeight(start)
        slot.show()
        anim.setStartValue(start)
        anim.setEndValue(slot.extent if show else 0)
        anim.start()

    def _land_bulk(self, show: bool) -> None:
        """The bulk bar's end state, with no slide."""
        self._bulk_anim.stop()
        self._bulk_open = show
        self._bulk.extent = 0
        self._bulk.setMaximumHeight(_QMAX)
        self._bulk.setVisible(show)

    # ── narrow windows: the toolbar and the bulk bar shed extras, not letters ──
    # Apollo's toolbar, compacted least-needed first. Each level keeps what the
    # one before it kept and gives up one more thing.
    _TOOLBAR_LEVELS = 6

    def _apply_toolbar_level(self, level: int) -> None:
        """0 is everything, with words. 1: "Save as new search" says "Save
        search". 2: Table|Cards leaves the bar (Default view ▾ holds Layout).
        3: Search settings shows its icon alone. 4: Hide filters and Research
        with AI shrink to their icons. 5: Default view shrinks to its icon."""
        def text(widget, value: str) -> None:
            if widget.text() != value:
                widget.setText(value)
        text(self._save_search_btn, "Save search" if level >= 1 else "Save as new search")
        self._seg.setVisible(level < 2)
        text(self._settings_btn, "" if level >= 3 else "Search settings")
        text(self._filters_btn, "" if level >= 4 else self._filters_text())
        for btn, words, at in ((self._research_btn, "Research with AI", 4),
                               (self._views_btn, "Default view", 5)):
            small = level >= at
            text(btn, "" if small else words)
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly if small
                                   else Qt.ToolButtonTextBesideIcon)
            btn.setToolTip(words if small else "")

    def _toolbar_need(self, level: int) -> int:
        """The width the toolbar asks for at one step of compaction."""
        self._apply_toolbar_level(level)
        return self._toolbar.layout().sizeHint().width()

    def _fit_toolbar(self) -> None:
        """Take the toolbar's extras away, least needed first, until what's left
        fits — instead of Qt crushing every label to a stub. Off screen (a
        test) it keeps everything."""
        bar = self._toolbar
        level = 0
        if bar.isVisible():
            while (level < self._TOOLBAR_LEVELS - 1
                   and self._toolbar_need(level) > bar.width()):
                level += 1
        self._apply_toolbar_level(level)
        self._toolbar_level = level

    def _bulk_actions(self) -> tuple:
        """In _HELP_BULK's order: Save, Remove, Verify, Find e-mails, Find phones,
        Add to list, Export, Set stage, Qualify & draft, Add to sequence."""
        return (self._b_contact, self._b_remove, self._b_verify, self._b_emails,
                self._b_phones, self._b_save, self._b_export, self._b_stage,
                self._b_qualify, self._b_seq)

    def _wanted(self, button: QPushButton) -> bool:
        """An action the run can still use. Qualify, Find e-mails and Find phones
        are about work not yet done, so they leave the bar once it is."""
        if button is self._b_qualify:
            return self._qualify_wanted
        if button is self._b_emails:
            return self._emails_wanted
        if button is self._b_phones:
            return self._phones_wanted
        return True

    @staticmethod
    def _fold_set(level: int, actions: tuple) -> tuple:
        """Which actions sit in More at a compaction level: from 2 the four
        least used (Find phones among them — an occasional action, folded before
        the rest), from 3 all but Save, the primary and Find e-mails (a list
        with no addresses is unusable, so that stays on the bar as long as it
        fits). Save never folds: it is Apollo's first action, and the one that
        moves people from Net New to Saved. Nor does Remove — the owner asked
        for it by name — until the bar is narrower than anything else can
        absorb (5): the old floating Ask-Lumi pill took the right 300px of the bar
        (_launcher_inset), and on a 1366px window that left less than Save,
        Remove, More and the primary need, so their labels were crushed to
        stubs ("emov", "i seq"). Folded, Remove is still in More, by name. From
        6 "Clear selection" goes too (_fit_bulk): the header tick clears as well."""
        (_contact, remove, verify, emails, phones, add_list, export, stage, qualify,
         _seq) = actions
        every_extra = (verify, phones, add_list, stage, export, qualify, emails)
        return {2: (verify, phones, add_list, stage),
                3: (verify, phones, add_list, stage, export, qualify),
                4: every_extra,
                5: every_extra + (remove,),
                6: every_extra + (remove,)}.get(level, ())

    def _bulk_need(self, level: int) -> int:
        """The width the bulk bar needs at a compaction level: 0 is all of it;
        1 drops "Select all N"; 2 to 5 fold actions into More; 6 folds
        "Clear selection" there too."""
        lay = self._bulk_bar_w.layout()
        m = lay.contentsMargins()
        items = [self._sel_lbl.sizeHint().width() + theme.SPACE_2]
        if level < 6:
            items.append(self._bulk_clear.sizeHint().width())
        if level < 1 and self._sel_all_wanted:
            items.append(self._sel_all.sizeHint().width())
        folded = self._fold_set(level, self._bulk_actions())
        items += [b.sizeHint().width() for b in self._bulk_actions()
                  if self._wanted(b) and b not in folded]
        if level >= 6 or any(self._wanted(b) for b in folded):
            items.append(self._b_more.sizeHint().width())
        return m.left() + m.right() + sum(items) + lay.spacing() * len(items)

    @staticmethod
    def _inset_past_launcher(room: int, reach: int) -> int:
        """How much of the bar's right edge Lumi's button covers, given `room`
        px between the bar and the window's right edge and the button's
        `reach` in from that edge, plus a gap."""
        return max(0, reach + theme.SPACE_2 - room)

    def _launcher_inset(self) -> int:
        """How far the bulk bar's contents stop short of its right edge so
        Lumi's edge button does not sit on top of them. The button used to be
        a 285 px pill floating exactly where this bar is pinned, and it covered
        Find e-mails, More and Add to sequence at every window size (12-Oct-
        2026). It is now a ~44 px round button that rests above a footer row
        (theme.LUMI_REST_FROM_BOTTOM), so this is 0 unless the owner has
        dragged it down into the bar's band — then the bar gives way by the
        button's real width, read off the button itself. 0 outside the real
        window and while the bar is not showing."""
        win = self.window()
        bar = self._bulk_bar_w
        if not isinstance(win, QMainWindow) or not self._bulk.isVisible():
            return 0
        central = win.centralWidget() or win
        button = central.findChild(QWidget, "lumiEdgeButton")
        if button is None or button.isHidden():
            return 0
        g = button.geometry()
        top = bar.mapTo(central, QPoint(0, 0)).y()
        if g.bottom() < top or g.top() > top + bar.height() - 1:
            return 0                        # the button is above or below the bar
        room = central.width() - (bar.mapTo(central, bar.rect().topRight()).x() + 1)
        return self._inset_past_launcher(room, central.width() - g.x())

    def _fit_bulk(self) -> None:
        """Show the bulk actions that fit; fold the rest into More. Off screen
        every wanted action shows, as on a wide window."""
        lay = self._bulk_bar_w.layout()
        m = lay.contentsMargins()
        right = theme.SPACE_4 + self._launcher_inset()
        if m.right() != right:
            lay.setContentsMargins(m.left(), m.top(), right, m.bottom())
        level = 0
        if self._bulk.isVisible():
            width = self._bulk_bar_w.width()
            while level < 6 and self._bulk_need(level) > width:
                level += 1
        folded = self._fold_set(level, self._bulk_actions())
        for b in self._bulk_actions():
            b.setVisible(self._wanted(b) and b not in folded)
        self._sel_all.setVisible(self._sel_all_wanted and level < 1)
        self._bulk_clear.setVisible(level < 6)
        self._bulk_folded = ([self._bulk_clear] if level >= 6 else []) + [
            b for b in folded if self._wanted(b)]
        self._b_more.setVisible(bool(self._bulk_folded))

    def _show_more(self) -> None:
        """More's menu: the folded actions, armed exactly as their buttons are.
        It opens upwards — the bar sits at the foot of the window."""
        menu = QMenu(self)
        for b in self._bulk_folded:
            if b is self._b_stage:
                # Its stages, not a click that would open the button's own
                # menu over a folded-away button.
                sub = menu.addMenu(b.text())
                sub.setEnabled(b.isEnabled())
                for act in self._stage_menu.actions():
                    sub.addAction(act)
                continue
            act = menu.addAction(b.text())
            act.setEnabled(b.isEnabled())
            act.triggered.connect(b.click)
        if menu.isEmpty():
            return
        at = self._b_more.mapToGlobal(QPoint(0, -menu.sizeHint().height() - theme.SPACE_1))
        menu.popup(at)
        self._more_menu = menu              # alive while it shows

    def _drawer(self) -> QWidget:
        """The person panel's drawer — Apollo's contact profile (addons/leads/
        person.py). Hidden until a person is picked; docks beside the results
        on a wide window and floats over them on a narrow one — full height,
        from the top of the page (_float_rect) — so opening it never squeezes
        the table into a sliver; Expand spreads it over the whole page.
        Floating, it is the COCKPIT's child, not the body's: the body starts
        under the title row and the toolbar, and a drawer confined to it was
        left too short to read a person in."""
        from addons.leads.person import PersonPanel
        panel = QFrame()
        panel.setObjectName("leadDrawer")
        panel.setAttribute(Qt.WA_StyledBackground, True)
        col = QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.person_panel = PersonPanel()
        self.person_panel.closeRequested.connect(self._dismiss_drawer)
        self.person_panel.expandToggled.connect(self._set_expanded)
        self.person_panel.personPicked.connect(self._open_person)
        col.addWidget(self.person_panel, 1)
        # The Prospect tab's column, where the qualification leads — what the
        # dossier drawer used to be.
        self._drawer_lay = self.person_panel.prospect_lay
        self._drawer_expanded = False
        self._person_provider = None        # (dos, person) -> PersonView, the workbench's
        self._drawer_dos = None             # the row the panel shows
        self._drawer_person = None
        self._drawer_panel = panel
        self._drawer_w = _Reveal(panel, Qt.Horizontal, self)
        self._drawer_w.setObjectName("leadDrawerSlot")
        self._style_drawer(floating=True)
        close = QShortcut(QKeySequence(Qt.Key_Escape), self._drawer_w)
        close.setContext(Qt.WidgetWithChildrenShortcut)
        close.activated.connect(self._dismiss_drawer)
        self._drawer_w.hide()
        return self._drawer_w

    def _style_drawer(self, floating: bool) -> None:
        # Docked, the splitter handle is its edge; floating over the table it
        # needs one of its own, and a soft shadow to lift it off the rows.
        edge = f"border-left:1px solid {theme.DIVIDER};" if floating else ""
        # Floating, it sits ON the rows, so it must be opaque: the glass CARD
        # tint is 65% white and let the table's Fit/Status pills show straight
        # through the drawer's text. Docked beside the table there is nothing
        # behind it, so the glass stays.
        surface = "#ffffff" if floating else theme.CARD
        self._drawer_panel.setStyleSheet(
            f"QFrame#leadDrawer{{background:{surface};border:none;{edge}}}")
        self._drawer_w.set_shadow(_SHADOW if floating else 0)

    # ── the splitter, and where the drawer lives ──────────────────────────────
    def _split_sizes(self, rail: int | None = None, drawer: int | None = None) -> None:
        """Set the rail's and/or the drawer's width and give the results the
        rest. A hidden pane gets 0; a width left as None stays as it is."""
        sp = self._split
        sizes = sp.sizes()
        out = [0 if self._rail.isHidden() else (sizes[0] if rail is None else rail), 0]
        if sp.count() > 2:
            out.append(0 if self._drawer_w.isHidden()
                       else (sizes[2] if drawer is None else drawer))
        out[1] = max(1, sum(sizes) - out[0] - sum(out[2:]))
        sp.setSizes(out)

    def _on_split_moved(self, _pos: int, _index: int) -> None:
        """A handle was dragged: keep the widths it left, so a folded rail or a
        reopened drawer comes back as the user set it."""
        sizes = self._split.sizes()
        if not self._rail.isHidden() and sizes and sizes[0] >= _RAIL_MIN:
            self._rail_pref = min(_RAIL_MAX, sizes[0])
        if (self._drawer_docked and len(sizes) > 2 and not self._drawer_w.isHidden()
                and not self._drawer_sliding()):
            self._drawer_pref = max(_DRAWER_MIN, min(_DRAWER_MAX, sizes[2]))

    def _dock_room(self) -> bool:
        """Whether the drawer can dock: the table keeps room for every column
        at its minimum (_TABLE_FLOOR) beside the rail and the drawer. The
        toolbar spans the whole page above all three (Apollo's), so docking
        never squeezes it — and nothing here changes with the drawer, so this
        can't flip-flop. Expanded, it never docks: it covers the page."""
        if getattr(self, "_drawer_expanded", False):
            return False
        rail = 0 if self._rail.isHidden() else self._rail_pref + _HANDLE_W
        need = max(_DOCK_MIN, rail + _TABLE_FLOOR + _HANDLE_W + self._drawer_pref)
        return self._body.width() >= need

    def _float_rect(self) -> QRect:
        """Floating, the drawer is Apollo's side panel: it runs the cockpit's
        whole height on the right — over the title row and the toolbar's right
        half, whose left half (Default view, Hide filters, Search) stays clear —
        and stops at the foot of the results, so the pager and the bulk actions
        stay reachable while it is open. It used to start UNDER the toolbar:
        the rows above the results had already taken ~340px of a 1080p window,
        which left the person's details a 190px strip (57px on a 768p laptop).
        In the cockpit's own coordinates — the drawer is its child, not the
        body's. Expanded, it is the whole cockpit."""
        if getattr(self, "_drawer_expanded", False):
            return QRect(0, 0, self.width(), self.height())
        bottom = self.mapFromGlobal(
            self._view_stack.mapToGlobal(QPoint(0, self._view_stack.height()))).y()
        width = min(_DRAWER_W + _SHADOW, self.width())
        return QRect(self.width() - width, 0, width, max(0, bottom))

    def _set_expanded(self, on: bool) -> None:
        """Expand (or back to the list): the panel spreads over the whole page
        — floating, never docked — and comes back to its place."""
        self._drawer_expanded = bool(on)
        self.person_panel.set_expanded(on)
        if not self._drawer_w.isHidden():
            if on and self._drawer_docked:
                self._move_drawer(False)
            self._place_drawer()
            self._settle_drawer()

    def _move_drawer(self, dock: bool, sized: bool = True) -> None:
        """Put the drawer in the splitter (dock) or back over the page (float)."""
        w = self._drawer_w
        shown = not w.isHidden()
        self._placing = True
        self._drawer_docked = dock          # first: the moves below re-enter via resizes
        try:
            if dock:
                self._split.addWidget(w)
                self._split.setCollapsible(self._split.indexOf(w), False)
                w.setMinimumWidth(_DRAWER_MIN)
                w.setMaximumWidth(_DRAWER_MAX)
            else:
                w.setParent(self)
                w.setMinimumWidth(0)
                w.setMaximumWidth(_QMAX)
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            self._style_drawer(floating=not dock)
            w.setVisible(shown)             # a reparent hides a widget
            if dock and shown and sized:
                self._split_sizes(drawer=self._drawer_pref)
                self._split.refresh()
        finally:
            self._placing = False

    def _place_drawer(self) -> None:
        w = getattr(self, "_drawer_w", None)
        if w is None or w.isHidden() or self._placing or self._drawer_sliding():
            return                          # a move or a slide owns the geometry for now
        dock = self._dock_room()
        if dock != self._drawer_docked:
            self._move_drawer(dock)
        if not self._drawer_docked:
            w.setGeometry(self._float_rect())
            w.raise_()

    # ── the drawer's open and close ───────────────────────────────────────────
    def _drawer_sliding(self) -> bool:
        return self._drawer_anim.state() == QAbstractAnimation.Running

    def _open_drawer(self, dos) -> None:
        self._render_drawer(dos)
        w = self._drawer_w
        if not w.isHidden() and not (self._drawer_sliding() and not self._drawer_opening):
            self._place_drawer()            # already open: it just shows the new lead
            return
        if w.isHidden():
            self._drawer_t = 0.0
            w.show()
        if _motion_ok(self):
            self._slide_drawer(True)
        else:
            self._drawer_anim.stop()
            self._drawer_opening, self._drawer_t = True, 1.0
            self._settle_drawer()

    def _close_drawer(self) -> None:
        if self._drawer_expanded:
            # Shut, it comes back at its own size next time.
            self._drawer_expanded = False
            self.person_panel.set_expanded(False)
        w = self._drawer_w
        if w.isHidden() or (self._drawer_sliding() and not self._drawer_opening):
            return                          # shut, or already on its way
        if _motion_ok(self):
            self._slide_drawer(False)
        else:
            self._shut_drawer_now()

    def _shut_drawer_now(self) -> None:
        """Shut without the slide — for when something else needs the space
        this very moment (a tour step aimed at a control the drawer covers)."""
        self._drawer_anim.stop()
        self._drawer_opening, self._drawer_t = False, 0.0
        self._drawer_w.hide()
        self._settle_drawer()

    def _slide_drawer(self, opening: bool) -> None:
        """Slide the drawer in from the right edge, or back out. Docked, it
        grows its splitter pane while its content keeps full width and moves
        with the pane's edge; floating, it moves over the table."""
        anim = self._drawer_anim
        anim.stop()
        self._drawer_opening = opening
        if opening and self._dock_room() != self._drawer_docked:
            self._move_drawer(not self._drawer_docked, sized=False)
        w = self._drawer_w
        w.extent = (self._drawer_pref if self._drawer_docked
                    else self._float_rect().width() - w.shadow())
        if self._drawer_docked:
            # Let the pane go under its real minimum for the length of the slide.
            w.setMinimumWidth(0)
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        start, end = self._drawer_t, (1.0 if opening else 0.0)
        self._drawer_step(start)
        anim.setDuration(max(1, round(_DRAWER_MS * abs(end - start))))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _drawer_step(self, t) -> None:
        self._drawer_t = float(t)
        w = self._drawer_w
        if self._drawer_docked:
            self._split_sizes(drawer=round(self._drawer_pref * self._drawer_t))
        else:
            r = self._float_rect()
            w.setGeometry(self.width() - round(r.width() * self._drawer_t),
                          r.top(), r.width(), r.height())
            w.raise_()

    def _drawer_landed(self) -> None:
        if not self._drawer_opening:
            self._drawer_w.hide()
        self._settle_drawer()

    def _settle_drawer(self) -> None:
        """The end of an open or a close: a docked drawer gets its real minimum
        and maximum and its width back; a floating one is placed."""
        w = self._drawer_w
        w.extent = 0
        if self._drawer_docked:
            w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            w.setMinimumWidth(_DRAWER_MIN)
            w.setMaximumWidth(_DRAWER_MAX)
            if not w.isHidden():
                self._split_sizes(drawer=self._drawer_pref)
            self._split.refresh()
        self._place_drawer()

    def _dismiss_drawer(self) -> None:
        """The ✕ or Esc: close it and drop the row highlight, so it doesn't reopen."""
        self._table.blockSignals(True)
        self._table.setCurrentCell(-1, -1)
        self._table.clearSelection()
        self._table.blockSignals(False)
        self._close_drawer()

    # ── data ──────────────────────────────────────────────────────────────────
    def set_dossiers(self, dossiers: list, drafts=None, all_leads=None) -> None:
        """One run, straight from its dossiers — qualified first, then
        everyone else it sourced — sorted here by the Sort box, as the
        cockpit always did. No pool, no pages."""
        self._pooled = False
        self._people = []
        self._universe, self._sel_keys = [], set()
        self._load_rows(list(dossiers or []) + unqualified_rows(dossiers, all_leads),
                        drafts)
        self._pager.hide()

    def set_people(self, people, page=None, counts=None, empty_text=None,
                   universe=None) -> None:
        """One page of the pool — pool.Person rows the workbench has already
        filtered, split into Total / Net New / Saved, sorted and paged — shown
        in exactly that order. `page` is pool.page()'s dict, `counts` the three
        tabs', `empty_text` (title, body) what to say when the page is empty,
        `universe` everyone in the result on every page, in order — what
        Select all and Select number of people choose from (the page alone
        when not given). Whoever was selected stays selected."""
        self._pooled = True
        self._people = list(people or ())
        self._universe = list(universe) if universe is not None else list(self._people)
        rows, drafts = [], []
        for person in self._people:
            rows.append(person.row())
            if person.draft is not None:
                drafts.append(person.draft)
        if empty_text:
            self.set_empty_text(*empty_text)
        self._load_rows(rows, drafts)
        if counts is not None:
            self.set_counts(counts)
        self.set_page(page or {})

    def person_for(self, dos):
        """The pool.Person a row stands for (pooled pages only), else None."""
        for i, d in enumerate(self._dossiers):
            if d is dos and i < len(self._people):
                return self._people[i]
        return None

    def _load_rows(self, dossiers: list, drafts) -> None:
        # A pooled page rebuilt under an open person (a stage set in their
        # panel, a page turned) keeps them open, as Apollo's profile stays.
        keep = (self._pooled and self._drawer_person is not None
                and not self._drawer_w.isHidden())
        self._dossiers = list(dossiers)
        self._draft_by = {id(d.dossier): d for d in (drafts or [])}
        # A run's rows start with nothing ticked; a pooled page ticks whoever
        # the selection holds, however they got into it (another page).
        self._checked = ({i for i, p in enumerate(self._people) if self._is_sel(p)}
                         if self._pooled else set())
        self._hidden = set()
        self._card_cbs = {}
        self._show_empty(not self._dossiers)
        # Emptying the table moves its current cell, which would shut the
        # panel before it can be kept open.
        self._keeping = keep and bool(self._dossiers)
        try:
            self._fill_table()              # _apply_filters() fills the gallery too
        finally:
            self._keeping = False
        if keep and self._dossiers and self._keep_person_open():
            return
        self._show_selected()               # nothing picked → the drawer stays shut

    def _keep_person_open(self) -> bool:
        """The open person again, on the rebuilt page: their row highlighted
        when they are on it, and their panel drawn from the records as they
        now stand either way."""
        person = self._drawer_person
        keys = getattr(person, "keys", None) or frozenset()
        for idx, p in enumerate(self._people):
            if keys and not keys.isdisjoint(p.keys):
                for row in range(self._table.rowCount()):
                    item = self._table.item(row, _C_TICK)
                    if item is not None and item.data(Qt.UserRole) == idx:
                        self._table.blockSignals(True)
                        self._table.setCurrentCell(row, _C_LEAD)
                        self._table.blockSignals(False)
                        break
                self._render_drawer(p.row(), p)
                return True
        if self._drawer_dos is None:
            return False
        self._render_drawer(self._drawer_dos, None)
        return True

    def _fill_table(self):
        t = self._table
        # Never live-sorted: the Sort combo sorts once (_resort). Live sorting
        # also re-showed the header's sort arrow on every fill.
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.blockSignals(True)
        for idx, dos in enumerate(self._dossiers):
            lead = dos.lead
            row = t.rowCount()
            t.insertRow(row)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if idx in self._checked else Qt.Unchecked)
            chk.setData(Qt.UserRole, idx)          # sort-safe dossier pointer
            t.setItem(row, _C_TICK, chk)

            # Name is the item text (sorts A–Z); the company rides along for the
            # painted two-line cell (_LeadDelegate).
            name_it = QTableWidgetItem(lead.name or "(no name)")
            name_it.setData(_COMPANY_ROLE, lead.company or "")
            name_it.setToolTip(" — ".join(p for p in (lead.name, lead.company) if p))
            t.setItem(row, _C_LEAD, name_it)
            focus_it = QTableWidgetItem(lead.title or lead.industry or "")
            where = str((lead.extra or {}).get("location") or "")
            focus_it.setData(_WHERE_ROLE, where)
            focus_it.setToolTip(" — ".join(p for p in (focus_it.text(), where) if p))
            t.setItem(row, _C_FOCUS, focus_it)

            t.setItem(row, _C_FIT, _FitItem(getattr(lead, "fit_score", 0) or 0))

            # Status and signal are painted as pills by _PillDelegate.
            t.setItem(row, _C_STATUS, QTableWidgetItem(
                status_of(dos, self._draft_by.get(id(dos)))))
            if getattr(dos, "status", "") == UNQUALIFIED:
                signal = "Not qualified"
            else:
                signal = "why-now" if getattr(dos, "signal_status", "") == "found" else ""
            t.setItem(row, _C_SIGNAL, QTableWidgetItem(signal))
        t.blockSignals(False)
        if not self._pooled:
            self._resort()                  # a pooled page arrives already sorted
        self._apply_filters()
        self._refresh_bulk()

    def _dossier_at(self, row: int):
        it = self._table.item(row, _C_TICK)
        return self._dossiers[it.data(Qt.UserRole)] if it is not None else None

    # ── columns ───────────────────────────────────────────────────────────────
    def _resize_col(self, col: int, width: int) -> None:
        self._fitting = True
        try:
            self._head.resizeSection(col, width)
        finally:
            self._fitting = False

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        """A column dragged: hold it to its minimum and remember the width, so
        a narrow spell that squeezed it hands it back later."""
        if self._fitting or col not in _COL_MIN:
            return
        if new < _COL_MIN[col]:
            new = _COL_MIN[col]
            self._resize_col(col, new)
        self._col_pref[col] = new
        self._fit_columns(grown=col)

    def _fit_columns(self, grown: int = -1) -> None:
        """Lay the columns into the table's width. Focus takes what the others
        leave, never less than _FOCUS_MIN. When the table narrows the others
        give way — Lead first, then Signal, Status and Fit, each down to its
        minimum — and grow back to the widths the user left once there's room;
        past that the table scrolls sideways. A column being dragged (`grown`)
        takes nothing from the others: it stops when Focus is at its minimum."""
        t = self._table
        if not t.isVisible():
            return                          # nothing laid out yet; showing resizes it
        head = self._head
        room = t.viewport().width() - head.sectionSize(_C_TICK) - _FOCUS_MIN
        if grown in _COL_MIN:
            others = sum(head.sectionSize(c) for c in _COL_MIN if c != grown)
            cap = max(_COL_MIN[grown], room - others)
            if head.sectionSize(grown) > cap:
                self._resize_col(grown, cap)
                self._col_pref[grown] = cap
        else:
            width = {c: self._col_pref[c] for c in _COL_MIN}
            over = sum(width.values()) - room
            for c in (_C_LEAD, _C_SIGNAL, _C_STATUS, _C_FIT):
                give = max(0, min(over, width[c] - _COL_MIN[c]))
                width[c] -= give
                over -= give
            for c, w in width.items():
                if head.sectionSize(c) != w:
                    self._resize_col(c, w)
        rest = t.viewport().width() - sum(head.sectionSize(c) for c in range(head.count())
                                          if c != _C_FOCUS)
        if head.sectionSize(_C_FOCUS) != max(_FOCUS_MIN, rest):
            self._resize_col(_C_FOCUS, max(_FOCUS_MIN, rest))

    # ── interaction ───────────────────────────────────────────────────────────
    def sort_key(self) -> str:
        return self._sort.currentData() or "relevance"

    def set_sort(self, key: str) -> None:
        """Select a sort without emitting — the workbench restoring one."""
        i = self._sort.findData(key)
        if i >= 0 and i != self._sort.currentIndex():
            self._sort.blockSignals(True)
            self._sort.setCurrentIndex(i)
            self._sort.blockSignals(False)

    def _resort(self):
        """A run shown straight from its dossiers sorts itself: Relevance is
        best fit first, Name is A–Z (the two a single run can answer)."""
        col, order = ((_C_LEAD, Qt.AscendingOrder) if self.sort_key() == "name"
                      else (_C_FIT, Qt.DescendingOrder))
        self._table.sortItems(col, order)

    def _on_sort_changed(self):
        if self._pooled:
            # The whole pool re-sorts, then pages — not just this page.
            self.sortChanged.emit(self.sort_key())
            return
        # Not inside _resort: _fill_table calls _resort right before
        # _apply_filters, which already refills the gallery.
        self._resort()
        if self._view == "cards":
            self._fill_gallery()

    def _apply_filters(self):
        """Every row shows — filters are the pool's now (the workbench's), not
        this table's; what is on the page is what passed. Still the one pass
        that re-lays everything a new set of rows touches."""
        self._hidden = set()
        for row in range(self._table.rowCount()):
            self._table.setRowHidden(row, False)
        self._fit_toolbar()
        if self._view == "cards":
            self._fill_gallery()
        self._refresh_bulk()                # selection may have lost visible rows
        self._place_drawer()

    def _visible(self) -> list:
        """Dossier indices the filters show."""
        return [i for i in range(len(self._dossiers)) if i not in self._hidden]

    def _tick_row(self, row: int) -> None:
        """A click in the tick column, or Space: flip that row's tick through its
        item, so itemChanged → _set_checked does the rest as for any tick."""
        it = self._table.item(row, _C_TICK)
        if it is not None and not self._table.isRowHidden(row):
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _toggle_all_visible(self) -> None:
        """The header checkbox: tick every row the filters show — or, when all
        of those are ticked already, clear them. Rows the filters hide keep
        whatever tick they had (selected() leaves them out regardless)."""
        shown = self._visible()
        self._set_many(shown, not all(i in self._checked for i in shown))

    def _clear_ticks(self) -> None:
        """Clear — everyone selected, on every page."""
        self._sel_keys = set()
        self._set_many(list(self._checked), False)

    # ── a pooled page's selection, across its pages ─────────────────────────
    def _is_sel(self, person) -> bool:
        keys = getattr(person, "keys", None)
        return bool(keys) and not keys.isdisjoint(self._sel_keys)

    def _mark(self, people, on: bool) -> None:
        """Select or unselect people by their identity keys (pool.Person.keys):
        the handle that survives a page change and a pool rebuild."""
        for person in people or ():
            keys = getattr(person, "keys", None) or frozenset()
            if on:
                self._sel_keys |= keys
            else:
                self._sel_keys -= keys

    def _resync_ticks(self) -> None:
        """This page's ticks from the selection, after it changed off the page."""
        if self._pooled:
            want = {i for i, p in enumerate(self._people) if self._is_sel(p)}
            self._set_many(set(self._checked) - want, False, mark=False)
            self._set_many(want - self._checked, True, mark=False)
            self._refresh_bulk()

    def _select_all(self) -> None:
        """Select all — everyone in the result, on every page."""
        if self._pooled:
            self._mark(self._universe, True)
            self._resync_ticks()
        else:
            self._set_many(self._visible(), True)

    def _select_number(self, n: int, per_company: int = 0) -> None:
        """Select number of people: the first `n` of the result in its order,
        at most `per_company` from any one company (pool.pick). It replaces
        the selection, as Apollo's does."""
        from addons.leads.pool import pick
        if self._pooled:
            self._sel_keys = set()
            self._mark(pick(self._universe, n, per_company), True)
            self._resync_ticks()
            return
        order = [self._table.item(r, _C_TICK).data(Qt.UserRole)
                 for r in range(self._table.rowCount())
                 if self._table.item(r, _C_TICK) is not None
                 and not self._table.isRowHidden(r)]
        chosen = pick([self._dossiers[i] for i in order], n, per_company)
        ids = {id(d) for d in chosen}
        self._set_many(list(self._checked), False)
        self._set_many([i for i in order if id(self._dossiers[i]) in ids], True)

    def clear_selection(self) -> None:
        """Forget who is selected — the workbench asks when the filters, the
        tab or the search box change what the result IS (Apollo starts a new
        search with nothing selected); a new page or a new sort keeps it."""
        self._sel_keys = set()
        if self._checked:
            self._set_many(list(self._checked), False, mark=False)

    def _open_bulk_select(self) -> None:
        """The header caret: Bulk Selection, opening under the tick column."""
        pop = self._bulk_select
        total = len(self._universe) if self._pooled else len(self._visible())
        pop.set_counts(len(self._visible()), total, len(self.selected()))
        pop.adjustSize()
        at = self._head.mapToGlobal(self._head.caret_rect().bottomLeft())
        pop.move(at.x() - _TICK_BOX // 2, at.y() + 2)
        pop.show()
        pop.raise_()

    def _on_item_changed(self, item):
        if item.column() == _C_TICK:
            self._set_checked(item.data(Qt.UserRole),
                              item.checkState() == Qt.Checked)

    def _set_checked(self, idx: int, on: bool) -> None:
        """The one place a lead's ticked state changes — from a table row or a
        gallery card. Mirrors it into the other view and re-arms the bulk bar."""
        if idx is None:
            return
        if on:
            self._checked.add(idx)
        else:
            self._checked.discard(idx)
        if self._pooled and 0 <= idx < len(self._people):
            self._mark([self._people[idx]], on)
        self._sync_check(idx)
        self._refresh_bulk()

    def _set_many(self, idxs, on: bool, mark: bool = True) -> None:
        """Tick or clear many leads at once — select all, clear — in one pass
        over the rows and one bulk-bar refresh, not one per lead. `mark` False
        only redraws ticks the selection already says."""
        idxs = set(idxs)
        if on:
            self._checked |= idxs
        else:
            self._checked -= idxs
        if self._pooled and mark:
            self._mark([self._people[i] for i in idxs if 0 <= i < len(self._people)], on)
        state = Qt.Checked if on else Qt.Unchecked
        self._table.blockSignals(True)
        for row in range(self._table.rowCount()):
            it = self._table.item(row, _C_TICK)
            if it is not None and it.data(Qt.UserRole) in idxs and it.checkState() != state:
                it.setCheckState(state)
        self._table.blockSignals(False)
        for idx in idxs:
            cb = self._card_cbs.get(idx)
            if cb is not None and cb.isChecked() != on:
                cb.blockSignals(True)
                cb.setChecked(on)
                cb.blockSignals(False)
        self._refresh_bulk()

    def _sync_check(self, idx: int) -> None:
        on = idx in self._checked
        for row in range(self._table.rowCount()):
            it = self._table.item(row, _C_TICK)
            if it is not None and it.data(Qt.UserRole) == idx:
                if (it.checkState() == Qt.Checked) != on:
                    self._table.blockSignals(True)
                    it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                    self._table.blockSignals(False)
                break
        cb = self._card_cbs.get(idx)
        if cb is not None and cb.isChecked() != on:
            cb.blockSignals(True)
            cb.setChecked(on)
            cb.blockSignals(False)

    def _refresh_bulk(self):
        picked = self.selected()
        n = len(picked)
        on_page = len(self._dossiers) - len(self._hidden)
        # Select all is everyone in the result, every page — Apollo's.
        shown = len(self._universe) if self._pooled else on_page
        self._sel_lbl.setText(i18n.t("{n} selected").format(n=f"{n:,}"))
        self._sel_all.setText(i18n.t("Select all {n}").format(n=f"{shown:,}"))
        self._sel_all_wanted = 0 < n < shown
        for b in (self._b_contact, self._b_remove, self._b_verify, self._b_save,
                  self._b_export, self._b_seq, self._b_stage):
            b.setEnabled(n > 0)
        # Qualify only means something while the run holds people to qualify
        # (never qualified, or a failed pass), and arms when one of them is ticked.
        self._qualify_wanted = any(getattr(d, "status", "") in RETRYABLE
                                   for d in self._dossiers + picked)
        self._b_qualify.setEnabled(any(getattr(d, "status", "") in RETRYABLE
                                       for d in picked))
        # The same rule for addresses: a confirmed one has nothing left to find,
        # so the button is for the rows that are blank, guessed or unconfirmed.
        self._emails_wanted = any(needs_email(d) for d in self._dossiers + picked)
        self._b_emails.setEnabled(any(needs_email(d) for d in picked))
        # And for phones: someone with a number already (their sheet's, or one
        # Find phones found) has nothing left to look up.
        self._phones_wanted = any(needs_phone(d) for d in self._dossiers + picked)
        self._b_phones.setEnabled(any(needs_phone(d) for d in picked))
        # The header's box speaks for THIS page, as Apollo's does.
        ticked = len([i for i in self._checked if i not in self._hidden])
        self._head.set_check_state(Qt.Unchecked if ticked == 0 else
                                   Qt.Checked if ticked >= on_page else Qt.PartiallyChecked)
        self._table.viewport().update()     # a tick tints its whole row, not one cell
        self._slide_bulk(n > 0)
        # Fold after the slide has put the bar up: measured while it was still
        # hidden, the fold came out as "everything", and a bar returning at
        # the same width gets no Resize to correct it.
        self._fit_bulk()

    def selected(self) -> list:
        """The rows the bulk actions act on: on a pooled page everyone
        selected on ANY page of the result, in its order; else the ticked
        rows of this one."""
        if self._pooled:
            return [p.row() for p in self._universe if self._is_sel(p)]
        return [self._dossiers[i] for i in sorted(self._checked)
                if i not in self._hidden and 0 <= i < len(self._dossiers)]

    # ── the guided walkthrough points at these ────────────────────────────────
    def help_targets(self) -> dict:
        """The parts of this screen the "?" tour can ring, by the key it asks
        for: a real widget already on screen, or (widget, QRect) where the
        target is a region of one — a column heading is painted by the header,
        not a widget of its own. Nothing is built here.

        A key whose part is not on screen right now is left out and the tour
        skips it: the table before anyone is in it, the pager before there is
        a page, the bulk bar between ticks, the drawer before a lead is opened."""
        out = {
            "import_menu": self._import_btn,
            "views_menu": self._views_btn,
            "hide_filters": self._filters_btn,
            "people_search": self._search,
            "research_menu": self._research_btn,
            "save_as_search": self._save_search_btn,
            "view_toggle": self._seg,
            "sort": self._sort,
            "search_settings": self._settings_btn,
            "people_tabs": self._tabs_frame,
            "pager": self._pager,
            "table": self._table,
            "select_all": (self._head, self._section_rect(_C_TICK)),
            "bulk_bar": self._bulk_bar_w,
            "drawer": self._drawer_panel,
        }
        for key, col in _HELP_COLS.items():
            out[key] = (self._head, self._section_rect(col))
        for key, button in zip(_HELP_BULK, self._bulk_actions()):
            # On a narrow window the least-used actions live in More (_fit_bulk),
            # so a step about one points at the button that opens that menu.
            out[key] = self._b_more if button in self._bulk_folded else button
        return {k: t for k, t in out.items() if _on_screen(t, self)}

    def help_reveal(self, key: str) -> None:
        """Make one target reachable: unfold the rail and scroll to it, bring a
        column's heading on screen, open the dossier drawer.

        It ticks no row, changes no filter value and starts nothing. The bulk
        bar only exists while rows are ticked, so a step about it is skipped
        while it is down rather than ticked into being."""
        if key not in _HELP_KEYS:
            return
        if key != "drawer" and self._drawer_covers(key):
            # A step back from the drawer step can land on Import or the view
            # toggle, which the full-height drawer sits over: shut it first.
            self._shut_drawer_now()
        if key == "people_tabs":
            self.set_filters_shown(True)        # the rail may be folded away
            self._rail.ensureWidgetVisible(self._tabs_frame, 0, _REVEAL_PAD)
        elif key in _HELP_COLS or key == "select_all":
            self._scroll_to_column(_HELP_COLS.get(key, _C_TICK))
        elif key == "drawer":
            self._help_open_drawer()

    def _drawer_covers(self, key: str) -> bool:
        """Whether the open, floating drawer is over a help target. It runs the
        page's full height, so Import, the view toggle and the like sit under it."""
        w = self._drawer_w
        if w.isHidden() or self._drawer_docked:
            return False
        target = self.help_targets().get(key)
        widget = target[0] if isinstance(target, tuple) else target
        if widget is None:
            return False
        at = self.mapFromGlobal(widget.mapToGlobal(QPoint(0, 0)))
        return w.geometry().intersects(QRect(at, widget.size()))

    def _section_rect(self, col: int) -> QRect:
        """One column's heading as a box in the header's own coordinates,
        measured from the section — the header paints every label itself, so
        there is no widget to ask."""
        head = self._head
        if head.isSectionHidden(col) or head.sectionSize(col) <= 0:
            return QRect()
        vp = head.viewport()
        at = head.mapFromGlobal(vp.mapToGlobal(QPoint(head.sectionViewportPosition(col), 0)))
        return QRect(at.x(), at.y(), head.sectionSize(col), vp.height())

    def _scroll_to_column(self, col: int) -> None:
        """Scroll the table sideways until a column's heading is on screen:
        dragged wide enough, the columns run past the results' right edge."""
        head, bar = self._head, self._table.horizontalScrollBar()
        left = head.sectionPosition(col)
        right = left + head.sectionSize(col)
        width = self._table.viewport().width()
        if left < bar.value():
            bar.setValue(left)
        elif right > bar.value() + width:
            bar.setValue(min(left, right - width))

    def _help_open_drawer(self) -> None:
        """A step about the dossier drawer needs a dossier in it. The drawer
        follows the highlighted lead, so this highlights the first row on
        screen — the same act as clicking that lead, and no tick, so nothing
        the bulk bar would act on changes."""
        if not self._drawer_w.isHidden():
            return                              # already open on someone
        for row in range(self._table.rowCount()):
            if self._table.isRowHidden(row):
                continue
            if self._table.currentRow() == row:
                self._show_selected()           # already highlighted, just shut
            else:
                self._table.setCurrentCell(row, _C_LEAD)
            return

    def help_snapshot(self) -> dict:
        """What this screen's reveals move — the rail's fold, the highlighted
        lead and its drawer, the scroll of the rail and the table — for the
        walk to put back when it closes (help_restore)."""
        table, rail = self._table, self._rail
        return {
            "rail_hidden": rail.isHidden(),
            "row": table.currentRow(),
            "column": table.currentColumn(),
            "drawer_hidden": self._drawer_w.isHidden(),
            "rail_scroll": rail.verticalScrollBar().value(),
            "table_scroll": (table.horizontalScrollBar().value(),
                             table.verticalScrollBar().value()),
        }

    def help_restore(self, snap: dict) -> None:
        """Back to a help_snapshot(), touching only what differs — the walk
        restores twice around a layout pass, and a second pass that re-set the
        row would reopen a drawer the first one had just shut."""
        if not isinstance(snap, dict):
            return
        self.set_filters_shown(not snap.get("rail_hidden", False))
        table = self._table
        row = snap.get("row", -1)
        if table.currentRow() != row:
            if row < 0 or row >= table.rowCount():
                # The way the drawer's own x forgets a lead: no highlight left
                # for the drawer to reopen on.
                table.blockSignals(True)
                table.setCurrentCell(-1, -1)
                table.clearSelection()
                table.blockSignals(False)
            else:
                table.setCurrentCell(row, max(0, snap.get("column", _C_LEAD)))
        if snap.get("drawer_hidden", True):
            self._close_drawer()
        elif self._drawer_w.isHidden():
            self._show_selected()
        self._rail.verticalScrollBar().setValue(snap.get("rail_scroll", 0))
        across, down = snap.get("table_scroll", (0, 0))
        table.horizontalScrollBar().setValue(across)
        table.verticalScrollBar().setValue(down)

    # ── gallery (the card view) ────────────────────────────────────────────────
    def _fill_gallery(self):
        self._grid.clear()
        self._card_cbs = {}
        # Cards follow the table's row order, so Sort means the same thing in
        # both views.
        order = [self._table.item(r, _C_TICK).data(Qt.UserRole)
                 for r in range(self._table.rowCount())
                 if self._table.item(r, _C_TICK) is not None]
        self._grid.add_all([self._card_for(i, self._dossiers[i])
                            for i in order if i not in self._hidden])

    def _card_for(self, idx: int, dos) -> QWidget:
        lead = dos.lead
        draft = self._draft_by.get(id(dos))
        card = _LeadCard(idx)
        card.clicked.connect(self._card_clicked)
        v = QVBoxLayout(card)
        v.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        v.setSpacing(theme.SPACE_2)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        cb = QCheckBox()
        cb.setChecked(idx in self._checked)
        cb.setStyleSheet("QCheckBox{border:none;background:transparent;}")  # see rail
        cb.toggled.connect(lambda on, i=idx: self._set_checked(i, on))
        self._card_cbs[idx] = cb
        top.addWidget(cb, alignment=Qt.AlignTop)
        top.addWidget(_avatar(lead.name, 38))
        top.addStretch(1)
        top.addWidget(self._fit_badge(getattr(lead, "fit_score", 0) or 0),
                      alignment=Qt.AlignTop)
        v.addLayout(top)

        name = QLabel(lead.name or "(no name)")
        name.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        name.setWordWrap(True)
        v.addWidget(name)
        if lead.company:
            v.addWidget(_muted(lead.company, 12))
        focus = lead.title or lead.industry or ""
        if focus:
            v.addWidget(_muted(focus, 11))

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(theme.SPACE_1)
        status = status_of(dos, draft)
        ink, bg = _TONE.get(status, (theme.NEUTRAL[700], theme.WELL))
        chips.addWidget(_pill(status, ink, bg))
        if getattr(dos, "status", "") == UNQUALIFIED:
            # The table's quiet outline, so the two views say it the same way.
            chips.addWidget(_outline_pill("Not qualified"))
        elif getattr(dos, "signal_status", "") == "found":
            chips.addWidget(_pill("why-now", theme.INFO_INK, theme.INFO_BG))
        chips.addStretch(1)
        v.addLayout(chips)
        return card

    def _fit_badge(self, fit) -> QLabel:
        ink = theme.OK if fit >= 75 else (theme.WARN if fit >= 50 else theme.NEUTRAL[500])
        lab = QLabel(f"{fit:g}")
        lab.setFixedSize(30, 30)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet(
            f"QLabel{{color:#fff;background:{ink};border-radius:15px;"
            f"font-family:'{_MONO}';font-weight:700;font-size:12px;}}")
        return lab

    def _card_clicked(self, idx: int) -> None:
        if 0 <= idx < len(self._dossiers):
            self._open_drawer(self._dossiers[idx])

    # ── drawer ────────────────────────────────────────────────────────────────
    def _show_selected(self):
        if getattr(self, "_keeping", False):
            return                          # a rebuild keeping the open person
        row = self._table.currentRow()
        dos = self._dossier_at(row) if row >= 0 else None
        if dos is None:
            self._close_drawer()
        else:
            self._open_drawer(dos)

    def _render_drawer(self, dos, person=None):
        """Show one person in the panel: their PersonView from the workbench's
        provider (set_person_provider) — contact, account, colleagues and
        the rest — or, with no provider (a run shown on its own), what this
        page holds: the row, its draft, its pool person."""
        self._drawer_dos = dos
        if dos is None:
            self._drawer_person = None
            self.person_panel.show_person(None)
            return
        if person is None:
            person = self.person_for(dos)
        self._drawer_person = person
        self.person_panel.show_person(self._person_view(dos, person))

    def _person_view(self, dos, person):
        from addons.leads.person import PersonView
        if self._person_provider is not None:
            try:
                view = self._person_provider(dos, person)
            except Exception:                                   # noqa: BLE001
                view = None
            if view is not None:
                return view
        draft = self._draft_by.get(id(dos))
        if draft is None and person is not None:
            draft = person.draft
        return PersonView(row=dos, draft=draft, person=person)

    def set_person_provider(self, provider) -> None:
        """How the panel learns everything about someone: provider(dos,
        person) -> person.PersonView (the workbench's, which reads the stores)."""
        self._person_provider = provider

    def refresh_person(self) -> None:
        """Draw the open person again from the records as they now stand —
        after an act on them. Their row on the page may be a new object once
        the pool was rebuilt, so they are found again by who they are."""
        dos = self._drawer_dos
        if dos is None or self._drawer_w.isHidden():
            return
        person = self._drawer_person
        if self._pooled and person is not None:
            keys = getattr(person, "keys", None) or frozenset()
            again = next((p for p in self._people if keys and not keys.isdisjoint(p.keys)),
                         None)
            if again is not None:
                person, dos = again, again.row()
        self._render_drawer(dos, person)

    def _open_person(self, person) -> None:
        """A colleague picked in the panel: their profile, in the same drawer."""
        if person is not None:
            self._render_drawer(person.row(), person)


# ════════════════════════════════════════════════════════════════════════════
#  Shared building blocks for the non-Leads tabs
# ════════════════════════════════════════════════════════════════════════════
def _page_title(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{theme.TEXT};font-family:'{theme.FONT_HEADING}';"
        f"font-size:20px;font-weight:600;")
    return lab


def _section_head(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:11px;letter-spacing:1px;font-weight:600;")
    return lab


def _muted(text: str, size: int = 12) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:{size}px;")
    return lab


def _card(title: str = ""):
    """A bordered card surface → (frame, body-layout). Title optional.

    The selector is scoped to the frame by object name on purpose: QLabel is a
    QFrame subclass, so a bare `QFrame{border}` would cascade a box onto every
    label inside the card. `#leadcard` keeps the border on the card alone."""
    f = QFrame()
    f.setObjectName("leadcard")
    f.setAttribute(Qt.WA_StyledBackground, True)   # paint the fill in any container
    f.setStyleSheet(
        f"QFrame#leadcard{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};"
        f"border-radius:{theme.R_CARD}px;}}")
    v = QVBoxLayout(f)
    v.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
    v.setSpacing(theme.SPACE_3)
    if title:
        v.addWidget(_section_head(title))
    return f, v


def _pill(text: str, ink: str, bg: str) -> QLabel:
    # R_CHIP, not R_PILL: Qt drops a border-radius larger than half the height
    # and draws square corners, so 999px rendered every pill as a box.
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
        f"padding:3px 10px;font-size:11px;font-weight:600;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def _outline_pill(text: str) -> QLabel:
    """A pill for a state rather than a finding ("Not qualified"): an outline,
    no fill, the same size as _pill."""
    lab = QLabel(text)
    lab.setStyleSheet(
        f"QLabel{{color:{theme.NEUTRAL[600]};background:transparent;"
        f"border:1px solid {theme.NEUTRAL[300]};border-radius:{theme.R_CHIP}px;"
        f"padding:2px 9px;font-size:11px;font-weight:600;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def _clear(layout) -> None:
    while layout.count():
        it = layout.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)      # leave the paint tree now, not on the next tick
            w.deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())


def _bar_row(label: str, value: int, total: int, ink: str) -> QWidget:
    """One labelled proportion bar — label · filled track · count. The fill is a
    stretch ratio so the bar stays right when the panel is resized."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.SPACE_3)
    lab = QLabel(label)
    lab.setFixedWidth(104)
    lab.setStyleSheet(f"color:{theme.TEXT};font-size:12px;")
    h.addWidget(lab)
    track = QFrame()
    track.setFixedHeight(16)
    track.setStyleSheet(
        f"QFrame{{background:{theme.WELL};border-radius:{theme.R_CHIP}px;}}")
    th = QHBoxLayout(track)
    th.setContentsMargins(0, 0, 0, 0)
    th.setSpacing(0)
    fill = QFrame()
    fill.setStyleSheet(
        f"QFrame{{background:{ink};border-radius:{theme.R_CHIP}px;}}")
    th.addWidget(fill, max(int(value), 0))
    th.addWidget(QWidget(), max(int(total) - int(value), 0) if total else 1)
    h.addWidget(track, 1)
    num = QLabel(f"{value:g}")
    num.setFixedWidth(34)
    num.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    num.setStyleSheet(
        f"color:{theme.NEUTRAL[700]};font-family:'{_MONO}';font-size:12px;")
    h.addWidget(num)
    return row


def _stat_card(label: str, value: str, sub: str = "", accent: bool = False) -> QWidget:
    f, v = _card()
    v.setSpacing(2)
    lab = QLabel(label.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:10px;letter-spacing:1px;font-weight:600;")
    v.addWidget(lab)
    num = QLabel(value)
    ink = theme.ACCENT if accent else theme.TEXT
    num.setStyleSheet(f"color:{ink};font-family:'{_MONO}';font-size:26px;font-weight:600;")
    v.addWidget(num)
    if sub:
        v.addWidget(_muted(sub, 11))
    v.addStretch(1)         # top-aligned: a tile with a caption must not move its siblings' numbers
    f._num = num
    return f


# ════════════════════════════════════════════════════════════════════════════
#  Lists — the real sheets Prism has written to ~/Documents/Prism Leads
# ════════════════════════════════════════════════════════════════════════════
def _human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _csv_rows(path: str):
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            n = sum(1 for _ in f)
        return max(n - 1, 0)
    except Exception:                                       # noqa: BLE001
        return None


class _ListsTab(QWidget):
    """The real files Prism has already written — every run's sheets and every
    saved list, in ~/Documents/Prism Leads. Each is a card you can open; the
    folder is one click away. Rescans on `refresh()`, and when the tab is shown."""

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self._folder = folder
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)

        head = QHBoxLayout()
        head.addWidget(_page_title("Saved lists"))
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        open_dir = QPushButton("Open folder")
        for b in (refresh, open_dir):
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton{{color:{theme.TEXT};background:{theme.CARD};"
                f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
                f"padding:7px 13px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:{theme.WELL};}}")
        refresh.clicked.connect(self.refresh)
        open_dir.clicked.connect(self._open_folder)
        head.addWidget(refresh)
        head.addWidget(open_dir)
        root.addLayout(head)
        root.addWidget(_muted(i18n.t(
            "Every search's sheets and every list you save land here "
            "automatically — the leads sheet, the hot list and any shortlist. "
            "Open one to work it in Excel, or bring it back with Import on the "
            "People tab.")))

        # The empty state sits in the page, not the grid (as on Saved searches):
        # EmptyState centres itself in the height it is given.
        self._empty = C.EmptyState(
            "file", "No lists yet",
            "Find new people, or tick people on the People tab and press Add "
            "to list — the files will appear here.")
        root.addWidget(self._empty, 1)

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)
        self.refresh()

    def _scan(self) -> list:
        try:
            names = os.listdir(self._folder)
        except Exception:                                   # noqa: BLE001
            return []
        out = []
        for nm in names:
            if os.path.splitext(nm)[1].lower() not in (".csv", ".xlsx", ".xlsm"):
                continue
            p = os.path.join(self._folder, nm)
            try:
                st = os.stat(p)
            except Exception:                               # noqa: BLE001
                continue
            out.append((p, nm, st.st_size, st.st_mtime))
        out.sort(key=lambda r: r[3], reverse=True)
        return out

    def refresh(self) -> None:
        _clear(self._grid)
        files = self._scan()
        self._empty.setVisible(not files)
        self._scroll.setVisible(bool(files))
        if not files:
            return
        for i, (path, name, size, mtime) in enumerate(files):
            self._grid.addWidget(self._file_card(path, name, size, mtime),
                                 i // 2, i % 2)

    def _file_card(self, path: str, name: str, size: int, mtime: float) -> QWidget:
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        f, v = _card()
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2)
        tag = _pill(ext.upper(), theme.INFO_INK, theme.INFO_BG)
        top.addWidget(tag)
        top.addStretch(1)
        when = datetime.datetime.fromtimestamp(mtime).strftime("%d %b %Y")
        top.addWidget(_muted(when, 11))
        v.addLayout(top)

        title = QLabel(os.path.splitext(name)[0])
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)

        rows = _csv_rows(path) if ext == "csv" else None
        meta = _human_size(size) if rows is None else f"{rows} rows · {_human_size(size)}"
        v.addWidget(_muted(meta, 11))

        btn = QPushButton("Open")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}")
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        btn.clicked.connect(lambda _=False, p=path: self._open(p))
        v.addWidget(btn)
        return f

    def _open(self, path: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_folder(self) -> None:
        try:
            os.makedirs(self._folder, exist_ok=True)
        except Exception:                                   # noqa: BLE001
            pass
        self._open(self._folder)


# ════════════════════════════════════════════════════════════════════════════
#  Sessions — every run Prism has kept, reopenable exactly as it was
# ════════════════════════════════════════════════════════════════════════════
_SESSION_MODES = {"sheet": "Sheet", "icp": "Find people", "icp_leads_only": "Leads sheet"}


class _SessionsTab(QWidget):
    """Every finished run is kept as a session (addons/leads/sessions.py) —
    newest first. Open one to put its leads, drafts and send status back on the
    Leads tab. People a session pulled are what the next search skips."""

    openRequested = Signal(str)

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self._folder = folder or ""
        self._current = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)

        head = QHBoxLayout()
        head.addWidget(_page_title("Sessions"))
        head.addStretch(1)
        refresh = QPushButton("Refresh")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.setStyleSheet(
            f"QPushButton{{color:{theme.TEXT};background:{theme.CARD};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:7px 13px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.WELL};}}")
        refresh.clicked.connect(self.refresh)
        head.addWidget(refresh)
        root.addLayout(head)
        root.addWidget(_muted(
            "Every run is kept here with its leads, drafts and who was mailed. "
            "A new search skips everyone these sessions already pulled — turn "
            "that off in the search panel to go through them again."))

        self._empty = C.EmptyState(
            "clock", "No sessions yet",
            "Every run you prepare is kept here — its leads, drafts and send "
            "status — so you can come back to it.")
        root.addWidget(self._empty, 1)

        scroll = QScrollArea()
        self._scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        scroll.setWidget(self._host)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def set_current(self, session_id: str) -> None:
        self._current = session_id or ""
        self.refresh()

    def _headers(self) -> list:
        if not self._folder:
            return []
        try:
            from addons.leads import sessions
            return sessions.list_sessions(self._folder)
        except Exception:                                   # noqa: BLE001
            return []

    def refresh(self) -> None:
        _clear(self._grid)
        heads = self._headers()
        self._empty.setVisible(not heads)
        self._scroll.setVisible(bool(heads))
        if not heads:
            return
        for i, head in enumerate(heads):
            self._grid.addWidget(self._session_card(head), i // 2, i % 2)
        self._grid.setRowStretch((len(heads) + 1) // 2, 1)

    def _session_card(self, head: dict) -> QWidget:
        f, v = _card()
        sid = head.get("id", "")
        on_screen = bool(sid) and sid == self._current
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2)
        top.addWidget(_pill(_SESSION_MODES.get(head.get("mode"), "Session"),
                            theme.INFO_INK, theme.INFO_BG))
        if on_screen:
            top.addWidget(_pill("On screen", theme.OK_INK, theme.OK_BG))
        top.addStretch(1)
        try:
            when = datetime.datetime.fromisoformat(
                head.get("created_at", "")).strftime("%d %b %Y, %H:%M")
        except (TypeError, ValueError):
            when = head.get("created_at", "")
        top.addWidget(_muted(when, 11))
        v.addLayout(top)

        title = QLabel(head.get("label") or "Session")
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)
        c = head.get("counts") or {}
        v.addWidget(_muted(
            f"{c.get('leads', 0)} leads · {c.get('qualified', 0)} qualified · "
            f"{c.get('hot', 0)} hot · {c.get('drafted', 0)} drafted · "
            f"{c.get('sent', 0)} mailed", 12))
        if head.get("skipped_seen"):
            v.addWidget(_muted(f"{head['skipped_seen']} already pulled, skipped", 11))

        btn = QPushButton("On screen" if on_screen else "Open")
        btn.setEnabled(not on_screen)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}"
            f"QPushButton:disabled{{background:{theme.NEUTRAL[200]};"
            f"color:{theme.NEUTRAL[600]};}}")
        btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        btn.clicked.connect(lambda _=False, s=sid: self.openRequested.emit(s))
        v.addWidget(btn)
        return f


# ════════════════════════════════════════════════════════════════════════════
#  Analytics — this run's funnel + mix, the reached-to-date ledger, guardrails
# ════════════════════════════════════════════════════════════════════════════
class _AnalyticsTab(QWidget):
    """Real numbers, honestly sourced. The funnel, deliverability mix and verdict
    mix are computed from the dossiers in hand; “reached to date” is the real
    suppression ledger (who Prism won't re-contact); the guardrails are the
    operating targets. Live reply/open/bounce tracking needs the inbox watcher
    that lands with the sequence engine — it is named as such, not faked."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dossiers: list = []
        self._draft_by: dict = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        col.setSpacing(theme.SPACE_4)
        col.addWidget(_page_title("Analytics"))
        col.addWidget(_muted(
            "This run, measured. Sending metrics (opens, replies, bounces) become "
            "live meters when the inbox watcher lands with the sequence engine."))

        self._stats = QHBoxLayout()
        self._stats.setSpacing(theme.SPACE_4)
        col.addLayout(self._stats)

        self._funnel_card, self._funnel = _card("Funnel — this run")
        col.addWidget(self._funnel_card)
        self._mix_card, self._mix = _card(i18n.t("Deliverability"))
        col.addWidget(self._mix_card)
        self._verdict_card, self._verdict = _card("Fit & verdict")
        col.addWidget(self._verdict_card)

        guard_card, guard = _card("Outreach guardrails")
        guard.addWidget(_bar_row("Reply target", 4, 100, theme.OK))
        guard.addWidget(_muted(
            "Aim for a 2–4% reply rate on cold 1:1 mail. Below ~1% says the list "
            "or the opener is off — re-qualify before sending more.", 11))
        guard.addWidget(_bar_row("Bounce ceiling", 2, 100, theme.WARN))
        guard.addWidget(_muted(
            "Keep hard bounces under 2%. Prism verifies before it sends and "
            "suppresses every bounce so a re-run never retries it; the sequence "
            "engine auto-pauses a send if bounces cross the line.", 11))
        guard.addWidget(_muted(
            "Re-verify addresses older than 60 days. One send per person, from "
            "your own inbox — never a blast.", 11))
        col.addWidget(guard_card)
        col.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_data(self, dossiers: list, draft_by: dict) -> None:
        self._dossiers = list(dossiers or [])
        self._draft_by = dict(draft_by or {})
        self.refresh()

    def _reached_to_date(self):
        try:
            from prospector import reach
            return len(reach.load_suppression())
        except Exception:                                   # noqa: BLE001
            return None

    def refresh(self) -> None:
        dos = self._dossiers
        n = len(dos)
        drafted = sum(1 for d in dos if id(d) in self._draft_by)
        mailed = sum(1 for d in dos
                     if status_of(d, self._draft_by.get(id(d))) == "Mailed")
        reached = self._reached_to_date()

        _clear(self._stats)
        self._stats.addWidget(_stat_card("Qualified", str(n)))
        self._stats.addWidget(_stat_card("Drafted", str(drafted)))
        self._stats.addWidget(_stat_card("Mailed", str(mailed), accent=True))
        self._stats.addWidget(_stat_card(
            "Reached to date", "—" if reached is None else str(reached),
            "won't be re-contacted"))

        # Funnel — Sourced→Qualified→Drafted→Mailed off this run.
        _clear(self._funnel)
        self._funnel.addWidget(_section_head("Funnel — this run"))
        if n:
            for label, val in (("Qualified", n), ("Drafted", drafted),
                               ("Mailed", mailed)):
                self._funnel.addWidget(_bar_row(label, val, n, theme.ACCENT))
        else:
            self._funnel.addWidget(_muted(
                "Run a list to see its funnel — qualified, drafted, mailed."))

        # Deliverability mix.
        _clear(self._mix)
        self._mix.addWidget(_section_head(i18n.t("Deliverability")))
        if n:
            counts: dict = {}
            for d in dos:
                s = status_of(d, self._draft_by.get(id(d)))
                counts[s] = counts.get(s, 0) + 1
            order = ("Verified", "Unverified", "Catch-all", "Unknown", "Invalid",
                     "No email", "Mailed")
            for s in order:
                if counts.get(s):
                    ink = _TONE.get(s, (theme.NEUTRAL[700], theme.WELL))[0]
                    self._mix.addWidget(_bar_row(s, counts[s], n, ink))
        else:
            self._mix.addWidget(_muted(
                "Verify statuses appear here once a list is prepared."))

        # Fit & verdict.
        _clear(self._verdict)
        self._verdict.addWidget(_section_head("Fit & verdict"))
        if n:
            fits = [getattr(d.lead, "fit_score", 0) or 0 for d in dos]
            avg = round(sum(fits) / len(fits)) if fits else 0
            self._verdict.addWidget(_muted(f"Average fit  ·  {avg} / 100", 12))
            vcount = {"hot": 0, "warm": 0, "cold": 0}
            for d in dos:
                v = getattr(d, "verdict", "")
                if v in vcount:
                    vcount[v] += 1
            for label, key, ink in (("Hot", "hot", theme.OK),
                                    ("Warm", "warm", theme.WARN),
                                    ("Cold", "cold", theme.NEUTRAL[500])):
                self._verdict.addWidget(_bar_row(label, vcount[key], n, ink))
        else:
            self._verdict.addWidget(_muted(
                "Fit scores and hot/warm/cold split appear here after a run."))


# ════════════════════════════════════════════════════════════════════════════
#  Saved searches — filters kept to run again (addons/leads/saved_searches.py)
# ════════════════════════════════════════════════════════════════════════════
def _saved_when(iso: str) -> str:
    """"11 Sep, 14:02" — how a card says when a search last ran."""
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return ""


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _small_button(text: str, primary: bool) -> QPushButton:
    """The card buttons, sized like the Sessions card's Open: the app sheet
    makes a bare QPushButton 34-36px with its own border, so both carry their
    whole look. Primary is the accent fill; the other is a quiet text button
    that must not compete with it."""
    btn = QPushButton(text)
    btn.setCursor(Qt.PointingHandCursor)
    if primary:
        btn.setStyleSheet(
            f"QPushButton{{color:#fff;background:{theme.ACCENT};border:none;"
            f"border-radius:{theme.R_CONTROL}px;padding:7px 16px;font-size:12px;"
            f"font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_RAMP[600]};}}"
            f"QPushButton:disabled{{background:{theme.NEUTRAL[200]};"
            f"color:{theme.NEUTRAL[600]};}}")
    else:
        btn.setStyleSheet(
            f"QPushButton{{color:{theme.NEUTRAL[700]};background:transparent;"
            f"border:1px solid transparent;border-radius:{theme.R_CONTROL}px;"
            f"padding:6px 12px;font-size:12px;font-weight:600;}}"
            f"QPushButton:hover{{background:{theme.ERR_BG};color:{theme.ERR_INK};}}")
    btn.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return btn


class _SavedSearchesTab(QWidget):
    """The searches the owner saved from the lead filters — most recently used
    first. "Use search" puts one back in the Leads rail, ready to run; a run
    of it is recorded on its card. Pure presentation: the workbench loads,
    runs and deletes (useRequested / deleteRequested)."""

    useRequested = Signal(str)
    deleteRequested = Signal(str)

    def __init__(self, folder: str = "", parent=None):
        super().__init__(parent)
        self._folder = folder or ""
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)
        root.addWidget(_page_title("Saved searches"))
        root.addWidget(_muted(
            "Filters you kept to run again. A re-run skips everyone an earlier "
            "session already pulled, so each one brings new people."))

        # The empty state sits in the page, not the grid: EmptyState centres
        # itself in the height it is given, and the grid's cells give it none.
        self._empty = C.EmptyState(
            "search", "No saved searches yet",
            "Set your filters on the People tab and press Save as new search.")
        root.addWidget(self._empty, 1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._host = QWidget()
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(theme.SPACE_4)
        self._grid.setVerticalSpacing(theme.SPACE_4)
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, 1)
        self.refresh()

    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def _records(self) -> list:
        if not self._folder:
            return []
        try:
            from addons.leads import saved_searches
            return saved_searches.list_searches(self._folder)
        except Exception:                                   # noqa: BLE001
            return []

    def cards(self) -> int:
        """How many search cards are showing — what a test counts."""
        return sum(1 for i in range(self._grid.count())
                   if self._grid.itemAt(i).widget() is not None)

    def refresh(self) -> None:
        _clear(self._grid)
        records = self._records()
        self._empty.setVisible(not records)
        self._scroll.setVisible(bool(records))
        for i, record in enumerate(records):
            self._grid.addWidget(self._search_card(record), i // 2, i % 2)
        # Rows keep their natural height; the leftover goes below the last row.
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)
        self._grid.setRowStretch((len(records) + 1) // 2, 1)

    def _chips(self, spec) -> list:
        """Up to four small chips: where, how many titles, how many industries,
        then what is excluded — in the error tone, so an exclusion reads as a
        rule at a glance."""
        where = (", ".join(spec.locations.include[:2])
                 + (f" +{len(spec.locations.include) - 2}"
                    if len(spec.locations.include) > 2 else "")
                 ) if spec.locations.include else "Anywhere"
        chips = [_pill(where, theme.INFO_INK, theme.INFO_BG)]
        n_titles, n_ind = len(spec.job_titles.include), len(spec.industries.include)
        if n_titles:
            chips.append(_pill(_plural(n_titles, "title", "titles"),
                               theme.NEUTRAL[700], theme.WELL))
        if n_ind:
            chips.append(_pill(_plural(n_ind, "industry", "industries"),
                               theme.NEUTRAL[700], theme.WELL))
        from prospector.filters import CHIP_FACETS, CLOSED_FACETS, label_of
        excluded = []
        for name in CHIP_FACETS:
            options = CLOSED_FACETS.get(name)
            excluded += [label_of(options, v) if options else v
                         for v in spec.facet(name).exclude]
        room = 4 - len(chips)
        for value in excluded[:room]:
            chip = _pill(f"\u2212 {value}", theme.ERR_INK, theme.ERR_BG)
            chip.setToolTip(f"Excluded: {value}")
            chips.append(chip)
        return chips

    def _search_card(self, record: dict) -> QWidget:
        from prospector.filters import SearchSpec
        from addons.leads import saved_searches
        f, v = _card()
        sid = record.get("id", "")
        name = record.get("name") or "Saved search"
        spec = SearchSpec.from_dict(record.get("filters"))

        title = QLabel(name)
        title.setWordWrap(True)
        title.setStyleSheet(f"color:{theme.TEXT};font-size:14px;font-weight:600;")
        v.addWidget(title)
        v.addWidget(_muted(saved_searches.summary(record), 12))

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(theme.SPACE_1 + 2)
        for chip in self._chips(spec):
            chips.addWidget(chip)
        chips.addStretch(1)
        v.addLayout(chips)

        runs = int(record.get("runs") or 0)
        when = _saved_when(record.get("last_run_at") or "")
        if runs and when:
            meta = (f"Last run {when} · {_plural(runs, 'run', 'runs')} · "
                    f"{int(record.get('last_new') or 0)} new last time")
        else:
            meta = "Never run"
        v.addWidget(_muted(meta, 11))

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        use = _small_button("Use search", primary=True)
        use.clicked.connect(lambda _=False, i=sid: self.useRequested.emit(i))
        delete = _small_button("Delete", primary=False)
        delete.clicked.connect(lambda _=False, i=sid: self.deleteRequested.emit(i))
        actions.addWidget(use)
        actions.addWidget(delete)
        actions.addStretch(1)
        v.addLayout(actions)
        f._use, f._delete = use, delete         # what a test presses
        return f


# ════════════════════════════════════════════════════════════════════════════
#  Sequences — honest shell: the real 3-touch stop-on-reply model
# ════════════════════════════════════════════════════════════════════════════
class _SequencesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        root.setSpacing(theme.SPACE_4)
        root.addWidget(_page_title("Sequences"))
        root.addWidget(_muted(
            "A stop-on-reply sequence: a short run of touches that halts the "
            "moment someone replies. Every message goes one-to-one from your own "
            "inbox — Prism drafts and paces; it never blasts and never auto-DMs."))

        card, v = _card("Your sequence")
        for i, (t, when, what) in enumerate((
                ("First touch", "today",
                 "the reviewed opener, grounded in the company's own why-now"),
                ("Follow-up", "+3 days", "a short nudge if there's no reply"),
                ("Last touch", "+7 days", "a final, easy-to-decline close")), 1):
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_3)
            mark = QLabel(str(i))
            mark.setFixedSize(24, 24)
            mark.setAlignment(Qt.AlignCenter)
            mark.setStyleSheet(
                f"color:#fff;background:{theme.ACCENT};border-radius:12px;"
                f"font-weight:700;font-size:12px;")
            row.addWidget(mark)
            txt = QLabel(f"<b>{t}</b> · <span style='color:{theme.NEUTRAL[600]}'>"
                         f"{when}</span><br><span style='color:{theme.NEUTRAL[600]};"
                         f"font-size:11px'>{what}</span>")
            txt.setTextFormat(Qt.RichText)
            txt.setWordWrap(True)
            row.addWidget(txt, 1)
            v.addLayout(row)
        stop = QLabel("Stops automatically the moment they reply · "
                      "pauses if bounces cross 2%")
        stop.setWordWrap(True)
        stop.setStyleSheet(
            f"color:{theme.OK_INK};background:{theme.OK_BG};"
            f"border-radius:{theme.R_CONTROL}px;padding:8px 12px;font-size:11px;")
        v.addWidget(stop)
        root.addWidget(card)

        status = QHBoxLayout()
        status.setSpacing(theme.SPACE_2)
        status.addWidget(_pill("Touch 1 live", theme.OK_INK, theme.OK_BG))
        status.addWidget(_muted(
            "Today: select leads and “Add to sequence” sends the first touch now, "
            "from your inbox. The scheduler that fires the follow-ups and watches "
            "for replies is the next build.", 12), 1)
        root.addLayout(status)
        root.addStretch(1)


# ════════════════════════════════════════════════════════════════════════════
#  The workspace — the tab strip over the five screens
# ════════════════════════════════════════════════════════════════════════════
_TABS = ("People", "Sessions", "Lists", "Saved searches", "Sequences", "Analytics")


class LeadsWorkspace(QWidget):
    """The whole Leads & Outreach surface. Re-exposes the cockpit's bulk
    signals and its `set_dossiers`, so the dialog wires to it exactly as it did
    to the bare cockpit — plus it keeps Analytics, Lists, Sessions and Saved
    searches in step."""

    verifyRequested = Signal(list)
    emailsRequested = Signal(list)
    phonesRequested = Signal(list)
    exportRequested = Signal(list)
    saveListRequested = Signal(list)
    sequenceRequested = Signal(list)
    qualifyRequested = Signal(list)
    saveContactsRequested = Signal(list)
    stageRequested = Signal(list, str)
    removeRequested = Signal(list)
    removedRequested = Signal()
    openSessionRequested = Signal(str)
    useSavedSearchRequested = Signal(str)
    deleteSavedSearchRequested = Signal(str)
    # Find People's own (LeadsCockpit), passed straight through.
    importRequested = Signal(str)
    tabChanged = Signal(str)
    pageRequested = Signal(int)
    sortChanged = Signal(str)
    queryChanged = Signal(str)
    settingsRequested = Signal()
    saveSearchRequested = Signal()
    findPrepareRequested = Signal()
    starterPicked = Signal(str)

    def __init__(self, leads_folder: str | None = None, sessions_folder: str = "",
                 searches_folder: str = "", parent=None):
        super().__init__(parent)
        import paths
        self._folder = leads_folder or paths.user_folder("Documents", "Prism Leads")
        self.leads = LeadsCockpit()
        for name in ("verifyRequested", "emailsRequested", "phonesRequested",
                     "exportRequested", "saveListRequested", "sequenceRequested",
                     "qualifyRequested",
                     "saveContactsRequested", "stageRequested", "removeRequested",
                     "removedRequested", "importRequested", "tabChanged",
                     "pageRequested", "sortChanged", "queryChanged",
                     "settingsRequested", "saveSearchRequested",
                     "findPrepareRequested", "starterPicked"):
            getattr(self.leads, name).connect(getattr(self, name))
        # Default view ▾ picks a saved search the way the Saved searches tab's
        # "Use search" does; "Manage…" is that tab.
        self.leads.savedSearchPicked.connect(self.useSavedSearchRequested)
        self.leads.manageSearchesRequested.connect(
            lambda: self._select(_TABS.index("Saved searches")))
        # No folder → the tab shows its empty state and never touches disk.
        self._sessions = _SessionsTab(sessions_folder)
        self._sessions.openRequested.connect(self.openSessionRequested)
        self._lists = _ListsTab(self._folder)
        self._saved = _SavedSearchesTab(searches_folder)
        self._saved.useRequested.connect(self.useSavedSearchRequested)
        self._saved.deleteRequested.connect(self.deleteSavedSearchRequested)
        self.leads.set_saved_searches(self._saved._records())
        self._sequences = _SequencesTab()
        self._analytics = _AnalyticsTab()
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._tabstrip())
        self._stack = QStackedWidget()
        self._stack.setStyleSheet(f"QStackedWidget{{background:{theme.CANVAS};}}")
        for w in (self.leads, self._sessions, self._lists, self._saved,
                  self._sequences, self._analytics):
            self._stack.addWidget(w)
        root.addWidget(self._stack, 1)
        self._select(0)

    def _tabstrip(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("wsTabs")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#wsTabs{{background:{theme.CARD};border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_5)
        self._tabs = []
        for i, name in enumerate(_TABS):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, k=i: self._select(k))
            self._tabs.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        from prospector import gateway
        if gateway.pooled():
            badge = _pill("Your credits · your inbox", theme.INFO_INK, theme.INFO_BG)
            badge.setToolTip("Finding and qualifying people is charged to your Prism "
                             "credits — you hold no API keys; every message leaves "
                             "from your own mailbox.")
        else:
            badge = _pill("Local · BYO-key · your inbox", theme.INFO_INK, theme.INFO_BG)
            badge.setToolTip("Runs on this computer with your own API keys; every "
                             "message leaves from your own mailbox.")
        lay.addWidget(badge)
        return bar

    def _style_tab(self, b: QPushButton, active: bool) -> None:
        # border-radius:0 on purpose: the app-wide QPushButton radius would curl
        # the ends of the 2px underline up into a bracket.
        if active:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid {theme.ACCENT};color:{theme.TEXT};"
                f"padding:12px 4px;margin-bottom:-1px;font-size:13px;font-weight:600;}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid transparent;color:{theme.NEUTRAL[600]};"
                f"padding:12px 4px;font-size:13px;font-weight:500;}}"
                f"QPushButton:hover{{color:{theme.TEXT};}}")

    def _select(self, i: int) -> None:
        self._stack.setCurrentIndex(i)
        for k, b in enumerate(self._tabs):
            self._style_tab(b, k == i)
        w = self._stack.widget(i)
        if w is self._lists:
            self._lists.refresh()
        elif w is self._sessions:
            self._sessions.refresh()
        elif w is self._saved:
            self._saved.refresh()
        elif w is self._analytics:
            self._analytics.refresh()

    # ── the guided walkthrough points at these ────────────────────────────────
    def help_targets(self) -> dict:
        """The tab strip's own keys, over everything the Leads tab offers. Its
        own win: a tab is this widget's, whatever the cockpit inside it calls
        the same name."""
        out = dict(self.leads.help_targets())
        out.update(zip(_HELP_TABS, self._tabs))
        return out

    def help_reveal(self, key: str) -> None:
        """Show the tab a step is on, then let the Leads tab reveal its own —
        every key but the tabs' is inside it, and a rail cannot be scrolled to
        while another screen is showing."""
        if key in _HELP_TABS:
            self._select(_HELP_TABS.index(key))
        elif key in _HELP_KEYS:
            self._select(0)
            self.leads.help_reveal(key)

    def help_snapshot(self) -> int:
        """The tab on screen. Only the tab: the Leads tab's own state is the
        cockpit's to record, and the walk asks it separately."""
        return self._stack.currentIndex()

    def help_restore(self, index) -> None:
        # Only on a change: _select re-reads Sessions, Lists and Saved searches
        # from disk, and the walk restores twice.
        if isinstance(index, int) and 0 <= index < self._stack.count() \
                and index != self._stack.currentIndex():
            self._select(index)

    # ── forwarded from the dialog ──────────────────────────────────────────────
    def set_run(self, dossiers: list, drafts=None) -> None:
        """The CURRENT run — what Analytics counts. The People tab shows the
        pool (set_people), not one run."""
        draft_by = {id(d.dossier): d for d in (drafts or [])}
        self._analytics.set_data(list(dossiers or []), draft_by)

    def set_dossiers(self, dossiers: list, drafts=None, all_leads=None) -> None:
        # The table lists everyone sourced; Analytics counts only the qualified.
        self.leads.set_dossiers(dossiers, drafts, all_leads)
        draft_by = {id(d.dossier): d for d in (drafts or [])}
        self._analytics.set_data(list(dossiers or []), draft_by)

    def refresh_lists(self) -> None:
        self._lists.refresh()

    def set_search_panel(self, widget: QWidget) -> None:
        """Mount the workbench's filter column in the People rail."""
        self.leads.set_search_panel(widget)

    def set_find_panel(self, widget: QWidget) -> None:
        """Mount the workbench's Find new people under the filters."""
        self.leads.set_find_panel(widget)

    def set_people(self, people, page=None, counts=None, empty_text=None,
                   universe=None) -> None:
        self.leads.set_people(people, page, counts, empty_text, universe)

    def show_people_tab(self) -> None:
        self._select(0)

    def set_empty_text(self, title: str = "", body: str = "") -> None:
        self.leads.set_empty_text(title, body)

    def set_sessions_folder(self, folder: str) -> None:
        self._sessions.set_folder(folder)

    def refresh_sessions(self, current_id: str = "") -> None:
        """Re-read the Sessions tab and mark which session is on screen."""
        self._sessions.set_current(current_id)

    def set_searches_folder(self, folder: str) -> None:
        self._saved.set_folder(folder)
        self.leads.set_saved_searches(self._saved._records())

    def refresh_searches(self) -> None:
        """Re-read the Saved searches tab — after a save, a delete or a run —
        and the list People's Default view ▾ offers."""
        self._saved.refresh()
        self.leads.set_saved_searches(self._saved._records())

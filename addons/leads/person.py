"""
Leads & Outreach — the person panel (Apollo's contact profile)
──────────────────────────────────────────────────────────────
Apollo opens a person from the list into their profile (knowledge.apollo.io,
"View and Edit Contacts", read 23-Sep-2026), and so does Prism:

    header       the face, the name (LinkedIn beside it), "Title at Company ·
                 Location"; e-mail, call, Add to list, Add to sequence, and
                 "…" — Edit contact info, Flag as inaccurate, Delete contact
    on the left  Contact information · Record details · Tasks · Account · Notes
    tabs         Prospect · Activities · Sequences · Enrichment · All Fields

Apollo's own widgets and tabs that Prism has nothing real behind are left out,
never drawn empty: Deals (Prism keeps no deals yet), Conversations (it records
no calls or meetings — they can be LOGGED, under Activities), Files, the owner
and the meeting assistant.

Everything shown is a record Prism holds — the person (the page's Lead, as live
as the workers keep it), their saved contact as the file has it (stage, lists,
notes, tasks, Activities), the account they work at, the searches that found
them, the run that qualified them and the e-mail drafted for them — gathered by
the workbench into a PersonView. The panel changes nothing itself: every act is
a signal the workbench carries out on the stores, and the panel is then handed
the record as it now stands. Acting on someone not saved yet saves them first,
Apollo's rule ("Save a person … This unlocks key actions like enrichment,
ownership, and timeline tracking").

Anything that came off the web or out of a sheet is drawn as plain text.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QDate, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QComboBox, QDateEdit, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

import i18n
import theme
from addons.leads import evidence
from addons.leads.pool import RETRYABLE, UNQUALIFIED
from widgets import controls as C
from widgets import icons

_WIDE = 640            # at least this wide: the widgets beside the tabs
_LEFT_W = 264          # the widgets' column when it sits beside the tabs
_STICKY_H = 440        # at least this tall: the header stays pinned above the scroll.
                       # Shorter, it scrolls away with the rest — pinned, it took ~150px
                       # of a 340px drawer and left the person a 190px strip (a laptop's
                       # was 57px), which is why "I can't see the contact's details".
_COLLEAGUES = 6        # "People at …" shown before "and N more"
_LIST_MAX = 8          # notes / tasks shown before "Show all"
# The tabs, Apollo's order, left to right.
TABS = (("prospect", "Prospect"), ("activities", "Activities"),
        ("sequences", "Sequences"), ("enrichment", "Enrichment"),
        ("fields", "All Fields"))
# Activities' filter, Apollo's "Click Emails or Calls to filter by activity type".
_ACTIVITY_FILTERS = (("all", "All"), ("emails", "Emails"), ("calls", "Calls"),
                     ("meetings", "Meetings"))
_EMAILS = frozenset({"sent", "email", "message"})
# The round icon in front of each line of the timeline (the mockup's "dot"), by what the line says happened.
_TIMELINE_ICON = {"saved": "user", "stage": "arrow-right", "list": "list-plus", "sent": "send", "email": "mail", "message": "mail",
                  "edited": "pencil", "note": "file-text", "task": "check-square", "found": "search", "qualified": "check",
                  "call": "phone", "meeting": "calendar"}
# What can be logged by hand (contacts.LOGGED), as the Log activity menu says it.
_LOG_KINDS = (("call", "Call"), ("meeting", "Meeting"), ("email", "E-mail"),
              ("message", "Message"), ("other", "Other"))
# How the saved-via keys read in Activities (contacts.VIA).
_VIA_WORDS = {"import": "Imported from a CSV", "save": "Saved as a contact",
              "export": "Exported — saved as a contact",
              "sequence": "Added to a sequence — saved as a contact",
              "list": "Added to a list — saved as a contact",
              "email": "E-mail looked up — saved as a contact",
              "phone": "Phone number looked up — saved as a contact"}
_EDIT_FIELDS = (("name", "Name"), ("title", "Title"), ("company", "Company"),
                ("email", "E-mail"), ("phone", "Phone"), ("industry", "Industry"),
                ("location", "Location"), ("linkedin", "LinkedIn"),
                ("website", "Company website"))
_PHONE_NOTE = "No phone yet"


@dataclass
class PersonView:
    """Everything the panel shows about one person — plain data, gathered by
    the workbench (LeadsWorkbench._person_view)."""
    row: object                                    # the Dossier the table shows
    draft: object = None                           # the e-mail drafted for them
    person: object = None                          # pool.Person, on a pooled page
    contact: object = None                         # contacts.Contact, as saved
    account: object = None                         # accounts.Account they work at
    company: dict = field(default_factory=dict)    # their Account CSV import company
    colleagues: list = field(default_factory=list)  # pool.Person at their company
    more_colleagues: int = 0                       # beyond those
    found_by: list = field(default_factory=list)   # [(when, what the search asked)]
    deals: list = field(default_factory=list)      # deals.Deal linked to them, newest first

    @property
    def lead(self):
        return self.row.lead

    @property
    def status(self) -> str:
        return getattr(self.row, "status", "") or ""

    @property
    def qualified(self) -> bool:
        return self.status not in RETRYABLE


def _text(value) -> str:
    return " ".join(str(value or "").split())


def _extra(lead, key: str) -> str:
    return _text((getattr(lead, "extra", None) or {}).get(key, ""))


def activities(view: PersonView) -> list:
    """The Activities tab — every line Prism can stand behind, newest first:
    [{"at", "kind", "text"}]. The contact's own history (saves, stage moves,
    lists, sends, edits, what the owner logged), their notes and tasks, the
    searches that found them, the qualify pass, and a send older than the
    history. A line with no date sorts last."""
    out = []
    contact = view.contact
    history = list(getattr(contact, "history", None) or ())
    for h in history:
        kind, text = h.get("kind", ""), h.get("text", "")
        if kind == "saved":
            line = i18n.t(_VIA_WORDS.get(text, "Saved as a contact"))
        elif kind == "stage":
            old, _sep, new = text.partition(" → ")
            line = (i18n.t("Stage changed from {old} to {new}").format(old=old, new=new)
                    if new else i18n.t("Stage set to {new}").format(new=text))
        elif kind == "list":
            line = i18n.t("Added to the list {name}").format(name=text)
        elif kind == "sent":
            line = i18n.t("E-mail sent: {subject}").format(subject=text or "—")
        elif kind == "edited":
            line = i18n.t("Contact info edited: {fields}").format(fields=text)
        elif kind == "flagged":
            line = i18n.t("Flagged as inaccurate") + (f": {text}" if text else "")
        else:
            said = dict(_LOG_KINDS).get(kind, "Other")
            line = i18n.t("{kind} logged").format(kind=i18n.t(said)) + (
                f": {text}" if text else "")
        out.append({"at": h.get("at", ""), "kind": kind, "text": line})
    for note in getattr(contact, "notes", None) or ():
        out.append({"at": note.get("at", ""), "kind": "note",
                    "text": i18n.t("Note: {text}").format(text=note.get("text", ""))})
    for task in getattr(contact, "tasks", None) or ():
        done = i18n.t(" (done)") if task.get("done") else ""
        out.append({"at": task.get("at", ""), "kind": "task",
                    "text": i18n.t("Task: {text}").format(text=task.get("text", "")) + done})
    for at, what in view.found_by:
        out.append({"at": at, "kind": "found",
                    "text": i18n.t("Found by a search: {what}").format(what=what)})
    if view.qualified and getattr(view.row, "generated_at", ""):
        verdict = str(getattr(view.row, "verdict", "") or "").upper()
        out.append({"at": view.row.generated_at, "kind": "qualified",
                    "text": i18n.t("Qualified: {verdict} · {score} / 100").format(
                        verdict=verdict, score=getattr(view.row, "score", 0))})
    draft = view.draft
    if (draft is not None and getattr(draft, "status", "") == "sent"
            and not any(h.get("kind") == "sent" for h in history)):
        out.append({"at": "", "kind": "sent", "text": i18n.t("E-mail sent: {subject}").format(
            subject=getattr(draft, "subject", "") or "—")})
    dated = [a for a in out if _moment(a["at"]) is not None]
    dated.sort(key=lambda a: _moment(a["at"]), reverse=True)
    return dated + [a for a in out if _moment(a["at"]) is None]


def _moment(stamp: str):
    """An ISO time as a comparable instant — a qualify pass stamps UTC, a
    save the local time, and as text they sort wrong. None when unreadable."""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(stamp or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()                    # a bare time is local time
    return dt.timestamp()


def _matches(kind: str, which: str) -> bool:
    if which == "emails":
        return kind in _EMAILS
    if which == "calls":
        return kind == "call"
    if which == "meetings":
        return kind == "meeting"
    return True


def all_fields(view: PersonView, side: str = "people") -> list:
    """All Fields: (field, value) for the person ("people") or their company
    ("company") — every field Prism holds, the sheet's own columns included."""
    lead = view.lead
    rows = []
    if side == "people":
        extra = dict(getattr(lead, "extra", None) or {})
        custom = extra.pop("custom", None)
        for key, label in (("name", "Name"), ("title", "Title"), ("company", "Company"),
                           ("email", "E-mail"), ("phone", "Phone"),
                           ("industry", "Industry")):
            rows.append((i18n.t(label), _text(getattr(lead, key, ""))))
        rows.append((i18n.t("Fit"), f"{getattr(lead, 'fit_score', 0) or 0:g} / 100"))
        rows.append((i18n.t("Why that fit"), _text(getattr(lead, "fit_reason", ""))))
        contact = view.contact
        if contact is not None:
            rows.append((i18n.t("Stage"), contact.stage))
            rows.append((i18n.t("Lists"), ", ".join(contact.lists)))
            rows.append((i18n.t("Saved"), evidence.when(contact.saved_at)))
        for key in sorted(extra, key=str.casefold):
            value = extra[key]
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                rows.append((key.replace("_", " ").capitalize(), _text(value)))
        if isinstance(custom, dict):
            for key in sorted(custom, key=lambda k: str(k).casefold()):
                rows.append((_text(key), _text(custom[key])))
    else:
        account, company = view.account, view.company or {}
        names = (("name", "Company"), ("website", "Website"), ("domain", "Domain"),
                 ("industry", "Industry"), ("headcount", "Employees"),
                 ("revenue", "Revenue"), ("location", "Headquarters"),
                 ("phone", "Phone"), ("linkedin", "LinkedIn"),
                 ("description", "Description"))
        # What the person's own row says about the company fills what neither
        # the account nor the import holds.
        own = {"name": _text(getattr(lead, "company", "")),
               "website": _extra(lead, "website"),
               "industry": _text(getattr(lead, "industry", "")),
               "headcount": _extra(lead, "headcount")}
        for key, label in names:
            value = _text(getattr(account, key, "") if account is not None else "") \
                or _text(company.get(key, "")) or own.get(key, "")
            rows.append((i18n.t(label), value))
        if account is not None:
            rows.append((i18n.t("Account stage"), account.stage))
            rows.append((i18n.t("Company lists"), ", ".join(account.lists)))
        custom = dict(company.get("custom") or {}) if isinstance(company.get("custom"), dict) else {}
        if account is not None:
            custom.update(account.custom)
        for key in sorted(custom, key=lambda k: str(k).casefold()):
            rows.append((_text(key), _text(custom[key])))
    return [(k, v) for k, v in rows if k]


# ── building blocks ───────────────────────────────────────────────────────────

def _sheet() -> str:
    t = theme
    return "".join((
        f"QWidget#personPanel{{background:{t.CARD};}}",
        f"QLabel#pName{{color:{t.TEXT};font-size:17px;font-weight:600;}}",
        f"QLabel#pRole{{color:{t.NEUTRAL[700]};font-size:12px;}}",
        f"QLabel#pHead{{color:{t.NEUTRAL[600]};font-family:'{t.FONT_HEADING}';"
        f"font-size:10px;letter-spacing:1px;font-weight:600;}}",
        f"QLabel#pKey{{color:{t.NEUTRAL[600]};font-size:12px;}}",
        f"QLabel#pVal{{color:{t.TEXT};font-size:12px;}}",
        f"QLabel#pMuted{{color:{t.NEUTRAL[600]};font-size:12px;}}",
        f"QFrame#pWidget{{background:{t.CARD};border:1px solid {t.HAIRLINE};"
        f"border-radius:{t.R_CONTROL}px;}}",
        f"QFrame#pBanner{{background:{t.INFO_BG};border:none;"
        f"border-radius:{t.R_CONTROL}px;}}",
        f"QLabel#pBannerText{{color:{t.INFO_INK};font-size:12px;font-weight:600;}}",
        f"QPushButton#pTab{{background:transparent;border:none;border-bottom:2px solid "
        f"transparent;border-radius:0px;padding:6px 8px;min-height:20px;"
        f"color:{t.NEUTRAL[600]};font-size:13px;font-weight:600;}}",
        f"QPushButton#pTab:hover{{color:{t.TEXT};}}",
        f"QPushButton#pTab:checked{{color:{t.TEXT};border-bottom-color:{t.ACCENT};}}",
        f"QPushButton#pLink{{background:transparent;border:none;padding:2px 0px;"
        f"min-height:18px;color:{t.ACCENT_RAMP[700]};font-size:12px;font-weight:600;"
        f"text-align:left;}}",
        f"QPushButton#pLink:hover{{text-decoration:underline;}}",
        f"QPushButton#pLink:disabled{{color:{t.NEUTRAL[400]};}}",
        f"QPushButton#pSeg{{background:transparent;border:1px solid {t.HAIRLINE};"
        f"border-radius:{t.R_CHIP}px;padding:3px 10px;min-height:18px;font-size:12px;"
        f"font-weight:600;color:{t.NEUTRAL[600]};}}",
        f"QPushButton#pSeg:checked{{background:{t.INFO_BG};color:{t.INFO_INK};"
        f"border-color:{t.ACCENT};}}",
        f"QToolButton#pMore{{background:{t.CARD};border:1px solid {t.BORDER};"
        f"border-radius:{t.R_CONTROL}px;padding:4px;}}",
        f"QToolButton#pMore::menu-indicator{{image:none;width:0px;}}",
        f"QPlainTextEdit#pNote{{font-size:13px;}}",
    ))


def _label(text: str, name: str = "pVal", wrap: bool = True, select: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName(name)
    lab.setTextFormat(Qt.PlainText)            # sheets and the web: never markup
    lab.setWordWrap(wrap)
    if select:
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def _link(text: str, on_click=None) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("pLink")
    b.setCursor(Qt.PointingHandCursor)
    b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    if on_click is not None:
        b.clicked.connect(lambda _=False: on_click())
    return b


def _widget(title: str, action=None) -> tuple:
    """One of the left column's widgets: a titled card. `action` is a
    (tooltip, callable) for the "+" in its corner."""
    box = QFrame()
    box.setObjectName("pWidget")
    col = QVBoxLayout(box)
    col.setContentsMargins(theme.SPACE_3, theme.SPACE_2 + 2, theme.SPACE_3, theme.SPACE_3)
    col.setSpacing(theme.SPACE_2)
    head = QHBoxLayout()
    head.setContentsMargins(0, 0, 0, 0)
    head.addWidget(_label(title.upper(), "pHead", wrap=False), 1)
    if action is not None:
        tip, fn = action
        plus = C.icon_button("plus", tip, on_click=fn)
        plus.setFixedSize(26, 26)
        head.addWidget(plus, 0, Qt.AlignRight)
    col.addLayout(head)
    return box, col


class _ClickLabel(QLabel):
    """A check row's words: a click on them ticks the box, as on any checkbox."""
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def _check_row(text: str) -> tuple:
    """(row, box, words): a checkbox beside words that WRAP. A QCheckBox's own
    text never wraps, and one long line forces the whole column wider than
    the panel — everything right of it was cut off."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(theme.SPACE_2)
    box = QCheckBox()
    words = _ClickLabel(text)
    words.setObjectName("pVal")
    words.setTextFormat(Qt.PlainText)
    words.setWordWrap(True)
    words.setCursor(Qt.PointingHandCursor)
    words.clicked.connect(lambda: box.isEnabled() and box.toggle())
    lay.addWidget(box, 0, Qt.AlignTop)
    lay.addWidget(words, 1)
    return row, box, words


def _pill(text: str, ink: str, bg: str) -> QLabel:
    lab = QLabel(text)
    lab.setTextFormat(Qt.PlainText)
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    lab.setStyleSheet(f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
                      f"padding:2px 8px;font-size:11px;font-weight:600;}}")
    return lab


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _email_tone(lead, draft) -> tuple:
    from addons.leads.pool import EMAIL_STATUS_LABEL, email_status_of
    key = email_status_of(lead, draft)
    tone = {"verified": (theme.OK_INK, theme.OK_BG), "invalid": (theme.ERR_INK, theme.ERR_BG),
            "mailed": (theme.NEUTRAL[700], theme.NEUTRAL[200])}
    ink, bg = tone.get(key, (theme.WARN_INK, theme.WARN_BG))
    return i18n.t(EMAIL_STATUS_LABEL[key]), ink, bg, key


# ── the panel ─────────────────────────────────────────────────────────────────

class PersonPanel(QWidget):
    """Apollo's contact profile for one person — see the module docstring.

        panel.show_person(view)            # a PersonView
        panel.stageRequested.connect(...)  # the workbench does the rest

    Test seams (no modal box in a test): ask_edit, confirm_delete, open_url."""

    closeRequested = Signal()
    expandToggled = Signal(bool)
    saveRequested = Signal(object)                 # lead — save them as a contact
    stageRequested = Signal(object, str)           # lead, contact stage
    accountStageRequested = Signal(object, str)    # accounts.Account, stage
    accountSaveRequested = Signal(object)          # lead — save their company
    noteRequested = Signal(object, str)            # lead, text
    taskRequested = Signal(object, str, str)       # lead, text, due (ISO date or "")
    taskDoneRequested = Signal(object, str, bool)  # lead, task id, done
    logRequested = Signal(object, str, str)        # lead, kind (contacts.LOGGED), text
    editRequested = Signal(object, dict)           # lead, {field: value}
    flagRequested = Signal(object)                 # lead
    deleteRequested = Signal(object)               # lead
    listRequested = Signal(object)                 # the row — Add to list
    sequenceRequested = Signal(object)             # the row — Add to sequence
    dealRequested = Signal(object)                 # the lead — Create deal
    enrichRequested = Signal(object, list)         # the row, ["email", "company", "qualify"]
    personPicked = Signal(object)                  # a pool.Person at their company

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("personPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_sheet())
        self.view: PersonView | None = None
        self._tab = "prospect"
        self._activity = "all"
        self._fields_side = "people"
        self._expanded = False
        self._wide = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root = root
        # The header and the rule under it travel as one: pinned above the scroll
        # while the panel is tall enough to spare the room, and the first thing IN
        # the scroll — so it scrolls away and the whole panel is left for the
        # person — when it is not (_dock_header).
        self._head_group = QWidget()
        group = QVBoxLayout(self._head_group)
        group.setContentsMargins(0, 0, 0, 0)
        group.setSpacing(0)
        group.addWidget(self._header())
        rule = QFrame()
        rule.setObjectName("pRule")
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame#pRule{{background:{theme.HAIRLINE};border:none;}}")
        group.addWidget(rule)
        self._head_sticky = True
        root.addWidget(self._head_group)
        scroll = QScrollArea()
        scroll.setObjectName("pScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setSingleStep(20)
        scroll.setStyleSheet("QScrollArea#pScroll{background:transparent;border:none;}")
        body = QWidget()
        body.setObjectName("pBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        body.setStyleSheet(f"QWidget#pBody{{background:{theme.CARD};}}")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._head_slot = QVBoxLayout()             # where a scrolling header sits
        self._head_slot.setContentsMargins(0, 0, 0, 0)
        outer.addLayout(self._head_slot)
        cols = QWidget()
        outer.addWidget(cols, 1)
        self._body_lay = QBoxLayout(QBoxLayout.LeftToRight, cols)
        self._body_lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4,
                                          theme.SPACE_4)
        self._body_lay.setSpacing(theme.SPACE_4)
        self._left = QWidget()
        self.left_lay = QVBoxLayout(self._left)
        self.left_lay.setContentsMargins(0, 0, 0, 0)
        self.left_lay.setSpacing(theme.SPACE_3)
        self._body_lay.addWidget(self._left, 0, Qt.AlignTop)
        self._body_lay.addWidget(self._right(), 1)
        scroll.setWidget(body)
        self._scroll = scroll
        root.addWidget(scroll, 1)
        self._lay_out(False)

    # ── the parts that never change ──────────────────────────────────────────
    def _header(self) -> QWidget:
        head = QWidget()
        col = QVBoxLayout(head)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        self._avatar = QLabel()
        self._avatar.setFixedSize(44, 44)
        self._avatar.setAlignment(Qt.AlignCenter)
        self._avatar.setStyleSheet(
            f"QLabel{{color:{theme.NEUTRAL[700]};background:{theme.NEUTRAL[200]};"
            f"border-radius:22px;font-weight:700;font-size:15px;}}")
        top.addWidget(self._avatar, 0, Qt.AlignTop)
        who = QVBoxLayout()
        who.setContentsMargins(0, 0, 0, 0)
        who.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(theme.SPACE_1)
        self.name = _label("", "pName", wrap=True, select=True)
        name_row.addWidget(self.name, 0)
        self._linkedin = C.icon_button("linkedin", i18n.t("Open their LinkedIn profile"),
                                       on_click=lambda: self._open_extra("linkedin"))
        self._linkedin.setFixedSize(26, 26)
        name_row.addWidget(self._linkedin, 0, Qt.AlignVCenter)
        name_row.addStretch(1)
        self._stage_pill = _pill("", theme.NEUTRAL[700], theme.NEUTRAL[200])
        name_row.addWidget(self._stage_pill, 0, Qt.AlignVCenter)
        who.addLayout(name_row)
        self.role = _label("", "pRole", wrap=True, select=True)
        who.addWidget(self.role)
        self.reach = _label("", "pMuted", wrap=True, select=True)       # their e-mail and phone, so no tab is needed to see how to reach them
        who.addWidget(self.reach)
        top.addLayout(who, 1)
        self._expand_btn = C.icon_button("maximize", i18n.t("Expand"),
                                         on_click=self._toggle_expand)
        top.addWidget(self._expand_btn, 0, Qt.AlignTop)
        top.addWidget(C.icon_button("x", i18n.t("Close"), on_click=self.closeRequested.emit),
                      0, Qt.AlignTop)
        col.addLayout(top)
        acts = QHBoxLayout()
        acts.setContentsMargins(0, 0, 0, 0)
        acts.setSpacing(theme.SPACE_2)
        self._mail_btn = C.icon_button("mail", i18n.t("E-mail them from your own mail app"),
                                       on_click=self._mail)
        self._call_btn = C.icon_button("phone", i18n.t("Call them"), on_click=self._call)
        self._task_btn = C.icon_button("check-square", i18n.t("Add a task"),
                                       on_click=lambda: self._task_form(True))
        for b in (self._mail_btn, self._call_btn, self._task_btn):
            acts.addWidget(b)
        acts.addStretch(1)
        self._save_btn = C.button(i18n.t("Save"), on_click=self._save)
        self._list_btn = C.button(i18n.t("Add to list"), icon_name="list-plus",
                                  on_click=lambda: self.listRequested.emit(self.view.row))
        self._seq_btn = C.button(i18n.t("Add to sequence"), "primary", icon_name="send",
                                 on_click=lambda: self.sequenceRequested.emit(self.view.row))
        acts.addWidget(self._save_btn)
        acts.addWidget(self._list_btn)
        acts.addWidget(self._seq_btn)
        self._more = QToolButton()
        self._more.setObjectName("pMore")
        self._more.setIcon(icons.icon("more-horizontal", 17, theme.NEUTRAL[700]))
        self._more.setIconSize(QSize(17, 17))
        self._more.setFixedSize(34, 34)
        self._more.setToolTip(i18n.t("More"))
        self._more.setPopupMode(QToolButton.InstantPopup)
        self._more.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self._more)
        self._act_edit = menu.addAction(i18n.t("Edit contact info"))
        self._act_edit.triggered.connect(self._edit)
        self._act_flag = menu.addAction(i18n.t("Flag as inaccurate"))
        self._act_flag.setToolTip(i18n.t("Their details are wrong: the stage becomes Bad Data"))
        self._act_flag.triggered.connect(lambda: self.flagRequested.emit(self.view.lead))
        menu.addSeparator()
        self._act_delete = menu.addAction(i18n.t("Delete contact"))
        self._act_delete.triggered.connect(self._delete)
        menu.setToolTipsVisible(True)
        self._more.setMenu(menu)
        acts.addWidget(self._more)
        col.addLayout(acts)
        return head

    def _right(self) -> QWidget:
        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        strip_w = QWidget()
        # Ignored: the strip takes the width it is given and never widens the
        # column past the panel, which cut off everything to its right.
        strip_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        strip = QHBoxLayout(strip_w)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        self.tab_btns: dict = {}
        self._pages: dict = {}
        self._stack = QStackedWidget()
        for key, name in TABS:
            b = QPushButton(i18n.t(name))
            b.setObjectName("pTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            strip.addWidget(b)
            self.tab_btns[key] = b
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(theme.SPACE_3)
            self._pages[key] = lay
            self._stack.addWidget(page)
        strip.addStretch(1)
        col.addWidget(strip_w)
        col.addWidget(C.hairline())
        col.addWidget(self._stack, 0, Qt.AlignTop)
        col.addStretch(1)
        # The Prospect tab's column: the qualification leads it (what the
        # rest is the proof of) — what the old dossier drawer showed.
        self.prospect_lay = self._pages["prospect"]
        return right

    # ── layout: two columns when there is room, one when not ────────────────
    def _lay_out(self, wide: bool) -> None:
        if wide == self._wide:
            return
        self._wide = wide
        self._body_lay.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        if wide:
            self._left.setFixedWidth(_LEFT_W)
        else:
            self._left.setMinimumWidth(0)
            self._left.setMaximumWidth(16777215)

    def _dock_header(self, sticky: bool) -> None:
        """Pin the header above the scroll (sticky), or make it the first thing
        in it. Depends only on the panel's own height, which moving the header
        does not change, so it cannot flip back and forth."""
        if sticky == self._head_sticky:
            return
        self._head_sticky = sticky
        if sticky:
            self._head_slot.removeWidget(self._head_group)
            self._root.insertWidget(0, self._head_group)
        else:
            self._root.removeWidget(self._head_group)
            self._head_slot.addWidget(self._head_group)
        self._head_group.show()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lay_out(self.width() >= _WIDE)
        self._dock_header(self.height() >= _STICKY_H)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._expand_btn.setToolTip(i18n.t("Back to the list") if self._expanded
                                    else i18n.t("Expand"))
        self.expandToggled.emit(self._expanded)

    def set_expanded(self, on: bool) -> None:
        """Say whether the host shows the panel expanded, without emitting."""
        self._expanded = bool(on)
        self._expand_btn.setToolTip(i18n.t("Back to the list") if on else i18n.t("Expand"))

    def set_tab(self, key: str) -> None:
        if key not in self.tab_btns:
            return
        self._tab = key
        for k, b in self.tab_btns.items():
            b.setChecked(k == key)
        self._stack.setCurrentIndex([k for k, _n in TABS].index(key))

    def tab(self) -> str:
        return self._tab

    # ── showing someone ───────────────────────────────────────────────────────
    def show_person(self, view: PersonView | None) -> None:
        """Draw one person's profile, or nothing for None. The tab the owner
        was on stays."""
        self.view = view
        for lay in list(self._pages.values()) + [self.left_lay]:
            _clear(lay)
        if view is None:
            return
        lead = view.lead
        from addons.leads.cockpit import _initials
        self._avatar.setText(_initials(lead.name))
        self.name.setText(lead.name or i18n.t("(no name)"))
        where = _extra(lead, "location")
        at = (i18n.t("{title} at {company}").format(title=lead.title, company=lead.company)
              if lead.title and lead.company else lead.title or lead.company or "")
        self.role.setText(" · ".join(p for p in (at, where) if p))
        self._linkedin.setVisible(bool(evidence.safe_url(self._url(_extra(lead, "linkedin")))))
        saved = view.contact is not None
        stage = str(getattr(view.contact, "stage", "") or "") if saved else ""
        ink, bg = (theme.OK_INK, theme.OK_BG) if stage else (theme.NEUTRAL[700], theme.NEUTRAL[200])
        self._stage_pill.setText(stage or (i18n.t("Saved") if saved else i18n.t("Not saved")))
        self._stage_pill.setStyleSheet(f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
                                       f"padding:2px 8px;font-size:11px;font-weight:600;}}")
        reach = " · ".join(p for p in (_text(lead.email), _text(lead.phone)) if p)
        self.reach.setText(reach)
        self.reach.setVisible(bool(reach))
        self._mail_btn.setEnabled(bool(_text(lead.email)))
        self._call_btn.setEnabled(bool(_text(lead.phone)))
        self._save_btn.setVisible(not saved)
        self._act_delete.setEnabled(saved)
        self._fill_left(view)
        self._fill_prospect(view)
        self._fill_activities()
        self._fill_sequences(view)
        self._fill_enrichment(view)
        self._fill_fields()
        self.set_tab(self._tab)

    # left: Contact information, Record details, Tasks, Account, Notes
    def _fill_left(self, view: PersonView) -> None:
        lay, lead = self.left_lay, view.lead
        if view.contact is None:
            banner = QFrame()
            banner.setObjectName("pBanner")
            row = QHBoxLayout(banner)
            row.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
            row.addWidget(_label(i18n.t("Not saved yet — save them to keep a stage, "
                                        "notes, tasks and their activity."),
                                 "pBannerText"), 1)
            lay.addWidget(banner)

        box, col = _widget(i18n.t("Contact information"))
        tone = _email_tone(lead, view.draft)
        email_row = QHBoxLayout()
        email_row.setSpacing(theme.SPACE_2)
        email_row.addWidget(self._icon("mail"))
        email_row.addWidget(_label(_text(lead.email) or i18n.t("No e-mail yet"),
                                   "pVal" if lead.email else "pMuted", select=True), 1)
        email_row.addWidget(_pill(tone[0], tone[1], tone[2]), 0, Qt.AlignVCenter)
        col.addLayout(email_row)
        if lead.email:
            # Where it came from — Hunter, Apollo, their sheet, you. Nothing is
            # guessed since 24-Sep-2026, so every address has an answer.
            from prospector.exports import email_source_of
            self.email_source = _label(i18n.t("Source: {src}").format(
                src=i18n.t(email_source_of(lead))), "pMuted")
            col.addWidget(self.email_source)
        if tone[3] != "verified":
            self.find_email = _link(i18n.t("Find their e-mail…"),
                                    lambda: self.enrichRequested.emit(self.view.row, ["email"]))
            col.addWidget(self.find_email)
        from prospector import mobiles, phones
        found = phones.entry_for(lead)      # a number Find phones found, with where it came from
        phone_row = QHBoxLayout()
        phone_row.setSpacing(theme.SPACE_2)
        phone_row.addWidget(self._icon("phone"))
        kind = (found or {}).get("kind") or "unknown"
        shown = phones.display(lead.phone, kind) if found else _text(lead.phone)
        phone_row.addWidget(_label(shown or i18n.t(_PHONE_NOTE),
                                   "pVal" if lead.phone else "pMuted", select=True), 1)
        if found:
            kind_words = phones.KIND_LABEL.get(kind, phones.KIND_LABEL["unknown"])
            phone_row.addWidget(_pill(i18n.t(kind_words), theme.NEUTRAL[700], theme.NEUTRAL[200]),
                                0, Qt.AlignVCenter)
        col.addLayout(phone_row)
        if found:
            # What the number IS, said every time it is shown: the company's own
            # published number, never rung, never checked against a do-not-call list.
            line = (phones.PERSON_LINE if found.get("scope") == "person"
                    else phones.SOURCE_LINE.get(found.get("source"), phones.SOURCE_LINE["other"]))
            self.phone_source = _label(
                i18n.t(line).format(when=evidence.when(found.get("found_at") or "")
                                    or i18n.t("recently")), "pMuted")
            col.addWidget(self.phone_source)
            if evidence.safe_url(found.get("source_url") or ""):
                col.addWidget(_link(i18n.t("Open the page it came from"),
                                    lambda: self.open_url(found.get("source_url") or "")))
        elif phones.needs_phone(lead):
            self.find_phone = _link(i18n.t("Find their phone…"),
                                    lambda: self.enrichRequested.emit(self.view.row, ["phone"]))
            col.addWidget(self.find_phone)
        # Their OWN mobile (Apollo, through Prism's credits). When it could not become the
        # lead's phone — a number they came with stays — it is shown here, never hidden.
        mobile = mobiles.entry_of(lead)
        if mobile:
            if mobile.get("number") != _text(lead.phone):
                mobile_row = QHBoxLayout()
                mobile_row.setSpacing(theme.SPACE_2)
                mobile_row.addWidget(self._icon("phone"))
                mobile_row.addWidget(_label(phones.display(mobile.get("number") or "", "mobile"),
                                            "pVal", select=True), 1)
                mobile_row.addWidget(_pill(i18n.t(phones.KIND_LABEL["mobile"]),
                                           theme.NEUTRAL[700], theme.NEUTRAL[200]),
                                     0, Qt.AlignVCenter)
                col.addLayout(mobile_row)
                self.mobile_source = _label(
                    i18n.t(phones.PERSON_LINE).format(
                        when=evidence.when(mobile.get("found_at") or "") or i18n.t("recently")),
                    "pMuted")
                col.addWidget(self.mobile_source)
        elif mobiles.needs_mobile(lead):
            self.find_mobile = _link(i18n.t("Find their mobile…"),
                                     lambda: self.enrichRequested.emit(self.view.row, ["mobile"]))
            col.addWidget(self.find_mobile)
        # LinkedIn only when it is LinkedIn; the page a search found them on
        # (an Exa people page) is its own link (identity.move_profile_link).
        for key, icon_name, text in (("linkedin", "linkedin", "LinkedIn profile"),
                                     ("profile_url", "external", "Profile page (Exa)"),
                                     ("website", "globe", "Company website")):
            url = evidence.safe_url(self._url(_extra(lead, key)))
            if url:
                row = QHBoxLayout()
                row.setSpacing(theme.SPACE_2)
                row.addWidget(self._icon(icon_name))
                row.addWidget(_link(i18n.t(text), lambda k=key: self._open_extra(k)))
                row.addStretch(1)
                col.addLayout(row)
        lay.addWidget(box)

        box, col = _widget(i18n.t("Record details"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        r = 0
        from addons.leads.contacts import STAGES
        self.stage = QComboBox()
        self.stage.setObjectName("pStage")
        stages = list(STAGES)
        current = view.contact.stage if view.contact is not None else ""
        if current and current not in stages:
            stages.append(current)
        if not current:
            self.stage.addItem(i18n.t("No stage yet"), "")
        for s in stages:
            self.stage.addItem(s, s)
        self.stage.setCurrentIndex(max(0, self.stage.findData(current)))
        self.stage.activated.connect(self._stage_picked)
        grid.addWidget(_label(i18n.t("Stage"), "pKey", wrap=False), r, 0)
        grid.addWidget(self.stage, r, 1)
        r += 1
        lists = list(view.contact.lists) if view.contact is not None else []
        grid.addWidget(_label(i18n.t("Lists"), "pKey", wrap=False), r, 0, Qt.AlignTop)
        grid.addWidget(_label(", ".join(lists) or i18n.t("None"),
                              "pVal" if lists else "pMuted"), r, 1)
        r += 1
        fit = getattr(lead, "fit_score", 0) or 0
        grid.addWidget(_label(i18n.t("Fit"), "pKey", wrap=False), r, 0, Qt.AlignTop)
        grid.addWidget(_label(f"{fit:g} / 100" + (f" · {lead.fit_reason}" if lead.fit_reason
                                                  else "")), r, 1)
        r += 1
        latest = next((a["at"] for a in activities(view) if a["at"]), "")
        grid.addWidget(_label(i18n.t("Last activity"), "pKey", wrap=False), r, 0)
        grid.addWidget(_label(evidence.when(latest) or i18n.t("None yet"),
                              "pVal" if latest else "pMuted"), r, 1)
        r += 1
        if view.contact is not None:
            grid.addWidget(_label(i18n.t("Saved"), "pKey", wrap=False), r, 0)
            grid.addWidget(_label(evidence.when(view.contact.saved_at)), r, 1)
            r += 1
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        col.addWidget(_link(i18n.t("See all fields"), lambda: self.set_tab("fields")))
        lay.addWidget(box)

        box, col = _widget(i18n.t("Deal"))
        self.deal_lines: list = []
        for deal in view.deals[:_LIST_MAX]:
            value = self._deal_value(deal)
            line = _label(f"{deal.title} · {deal.stage}" + (f" · {value}" if value else ""), "pVal")
            self.deal_lines.append(line)
            col.addWidget(line)
            if deal.next_step:
                col.addWidget(_label(deal.next_step, "pMuted"))
        if not view.deals:
            col.addWidget(_label(i18n.t("None yet"), "pMuted"))
        self.deal_btn = C.button(i18n.t("Create deal"), small=True,
                                 on_click=lambda: self.dealRequested.emit(self.view.lead))
        col.addWidget(self.deal_btn, 0, Qt.AlignLeft)
        lay.addWidget(box)

        box, col = _widget(i18n.t("Tasks"), (i18n.t("Add a task"),
                                             lambda: self._task_form(True)))
        self._task_box = col
        self._task_editor = self._task_form_widget()
        self._task_editor.hide()
        col.addWidget(self._task_editor)
        tasks = list(getattr(view.contact, "tasks", None) or ())
        open_first = sorted(tasks, key=lambda t: (t["done"], t.get("due") or "9999",
                                                  t.get("at", "")))
        self.task_boxes: dict = {}
        self.task_labels: dict = {}
        for task in open_first[:_LIST_MAX]:
            row, cb, words = _check_row(
                task["text"] + (f"  · {i18n.t('due')} {evidence.when(task['due'])}"
                                if task.get("due") else ""))
            cb.setChecked(task["done"])
            cb.toggled.connect(lambda on, tid=task["id"]: self.taskDoneRequested.emit(
                self.view.lead, tid, bool(on)))
            col.addWidget(row)
            self.task_boxes[task["id"]] = cb
            self.task_labels[task["id"]] = words
        if not tasks:
            col.addWidget(_label(i18n.t("No tasks."), "pMuted"))
        elif len(tasks) > _LIST_MAX:
            col.addWidget(_label(i18n.t("and {n} more — under Activities").format(
                n=len(tasks) - _LIST_MAX), "pMuted"))
        lay.addWidget(box)

        box, col = _widget(i18n.t("Account"))
        account, company = view.account, view.company or {}
        name = (account.name if account is not None else "") or _text(company.get("name")) \
            or _text(lead.company)
        col.addWidget(_label(name or i18n.t("No company"), "pVal" if name else "pMuted"))
        site = evidence.safe_url(self._url(
            (account.website or account.domain) if account is not None
            else company.get("website") or _extra(lead, "website")))
        if site:
            col.addWidget(_link(site.split("://", 1)[-1].rstrip("/"),
                                lambda u=site: self.open_url(u)))
        facts = [x for x in (
            (account.industry if account is not None else "") or _text(company.get("industry")),
            (i18n.t("{n} employees").format(n=account.headcount)
             if account is not None and account.headcount else ""),
            (account.location if account is not None else "") or _text(company.get("location")),
        ) if x]
        if facts:
            col.addWidget(_label(" · ".join(facts), "pMuted"))
        if account is not None:
            from addons.leads.accounts import STAGES as ACCOUNT_STAGES
            row = QHBoxLayout()
            row.addWidget(_label(i18n.t("Account stage"), "pKey", wrap=False))
            self.account_stage = QComboBox()
            self.account_stage.setObjectName("pAccountStage")
            names = list(ACCOUNT_STAGES)
            if account.stage and account.stage not in names:
                names.append(account.stage)
            for s in names:
                self.account_stage.addItem(s, s)
            self.account_stage.setCurrentIndex(max(0, self.account_stage.findData(account.stage)))
            self.account_stage.activated.connect(
                lambda _i: self.accountStageRequested.emit(
                    self.view.account, self.account_stage.currentData() or ""))
            row.addWidget(self.account_stage, 1)
            col.addLayout(row)
        elif name:
            col.addWidget(_link(i18n.t("Save the company as an account"),
                                lambda: self.accountSaveRequested.emit(self.view.lead)))
        lay.addWidget(box)

        box, col = _widget(i18n.t("Notes"))
        self.note_edit = QPlainTextEdit()
        self.note_edit.setObjectName("pNote")
        self.note_edit.setPlaceholderText(i18n.t("Add a note"))
        self.note_edit.setFixedHeight(64)
        col.addWidget(self.note_edit)
        self.note_btn = C.button(i18n.t("Add note"), small=True, on_click=self._add_note)
        col.addWidget(self.note_btn, 0, Qt.AlignRight)
        notes = list(getattr(view.contact, "notes", None) or ())
        for note in reversed(notes[-_LIST_MAX:]):
            col.addWidget(_label(evidence.when(note.get("at", "")), "pKey", wrap=False))
            col.addWidget(_label(note.get("text", ""), select=True))
        lay.addWidget(box)
        lay.addStretch(1)

    @staticmethod
    def _deal_value(deal) -> str:
        from addons.leads import deals as DL
        return DL.inr(deal.value) if deal.value else ""

    def _icon(self, name: str) -> QLabel:
        lab = QLabel()
        lab.setPixmap(icons.pixmap(name, 15, theme.NEUTRAL[600]))
        lab.setFixedSize(18, 18)
        return lab

    def _task_form_widget(self) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        self.task_text = QLineEdit()
        self.task_text.setPlaceholderText(i18n.t("What needs doing"))
        self.task_text.returnPressed.connect(self._add_task)
        col.addWidget(self.task_text)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.task_due_on = QCheckBox(i18n.t("Due"))
        self.task_due = QDateEdit(QDate.currentDate().addDays(1))
        self.task_due.setCalendarPopup(True)
        self.task_due.setDisplayFormat("d MMM yyyy")
        self.task_due.setEnabled(False)
        self.task_due_on.toggled.connect(self.task_due.setEnabled)
        row.addWidget(self.task_due_on)
        row.addWidget(self.task_due, 1)
        self.task_add = C.button(i18n.t("Add task"), small=True, on_click=self._add_task)
        row.addWidget(self.task_add)
        col.addLayout(row)
        return box

    def _task_form(self, show: bool) -> None:
        if self.view is None:
            return
        editor = getattr(self, "_task_editor", None)
        if editor is not None:
            editor.setVisible(show)
            if show:
                self.task_text.setFocus(Qt.OtherFocusReason)

    # right: the tabs
    def _fill_prospect(self, view: PersonView) -> None:
        lay = self.prospect_lay
        head = evidence.headline(view.row)
        for part in head:
            lay.addWidget(part)
        if view.qualified and not head:
            # Qualified, with no evidence kept: the verdict and score it earned.
            box, col = _widget(i18n.t("Qualification"))
            verdict = str(getattr(view.row, "verdict", "") or "").upper()
            col.addWidget(_label(i18n.t("{verdict} · {score} / 100").format(
                verdict=verdict, score=getattr(view.row, "score", 0))))
            why = _text(getattr(view.row, "summary", "")) or _text(view.lead.fit_reason)
            if why:
                col.addWidget(_label(why, "pMuted"))
            lay.addWidget(box)
        if view.status == UNQUALIFIED:
            box, col = _widget(i18n.t("Qualification"))
            col.addWidget(_label(i18n.t("Not qualified yet. Prism found this person but "
                                        "hasn't researched them or drafted an e-mail.")))
            col.addWidget(_link(i18n.t("Qualify contact…"),
                                lambda: self.enrichRequested.emit(self.view.row, ["qualify"])))
            lay.addWidget(box)
        elif view.status in RETRYABLE:
            why = _text(getattr(view.row, "note", "")) or i18n.t("The qualify pass failed.")
            box, col = _widget(i18n.t("Qualification"))
            col.addWidget(_label(i18n.t("Couldn't be qualified: {why}").format(why=why)))
            col.addWidget(_link(i18n.t("Try again…"),
                                lambda: self.enrichRequested.emit(self.view.row, ["qualify"])))
            lay.addWidget(box)
        # Apollo's Company insights: the why-now news with its source, and the
        # six dimensions with their evidence.
        for part in evidence.detail(view.row):
            lay.addWidget(part)
        # Account overview.
        rows = [(k, v) for k, v in all_fields(view, "company") if v]
        if rows:
            box, col = _widget(i18n.t("Account overview"))
            for key, value in rows[:9]:
                line = QHBoxLayout()
                line.addWidget(_label(key, "pKey", wrap=False), 0, Qt.AlignTop)
                line.addWidget(_label(value, select=True), 1)
                col.addLayout(line)
            lay.addWidget(box)
        # People at the company — saved first, then new prospects.
        if view.colleagues:
            company = _text(view.lead.company) or i18n.t("the company")
            box, col = _widget(i18n.t("People at {company}").format(company=company))
            for p in view.colleagues[:_COLLEAGUES]:
                line = QHBoxLayout()
                who = _link(p.lead.name or i18n.t("(no name)"),
                            lambda person=p: self.personPicked.emit(person))
                line.addWidget(who)
                line.addWidget(_label(_text(p.lead.title), "pMuted", wrap=False), 1)
                line.addWidget(_pill(i18n.t("Saved") if p.saved else i18n.t("Net New"),
                                     theme.NEUTRAL[700], theme.NEUTRAL[200]))
                col.addLayout(line)
            more = len(view.colleagues) - _COLLEAGUES + view.more_colleagues
            if more > 0:
                col.addWidget(_label(i18n.t("and {n} more").format(n=more), "pMuted"))
            lay.addWidget(box)
        lay.addStretch(1)

    def _fill_activities(self) -> None:
        lay, view = self._pages["activities"], self.view
        bar = QWidget()
        row = C.FlowLayout(bar, margin=0, h_space=4, v_space=4)
        self.activity_btns = {}
        for key, name in _ACTIVITY_FILTERS:
            b = QPushButton(i18n.t(name))
            b.setObjectName("pSeg")
            b.setCheckable(True)
            b.setChecked(key == self._activity)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._filter_activities(k))
            row.addWidget(b)
            self.activity_btns[key] = b
        self.log_btn = C.button(i18n.t("Log activity"), small=True)
        log_menu = QMenu(self.log_btn)
        for kind, name in _LOG_KINDS:
            act = log_menu.addAction(i18n.t(name))
            act.triggered.connect(lambda _=False, k=kind: self._log_form(k))
        self.log_btn.setMenu(log_menu)
        row.addWidget(self.log_btn)
        lay.addWidget(bar)
        self.log_box = QWidget()
        form = QVBoxLayout(self.log_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.SPACE_1)
        self.log_title = _label("", "pKey", wrap=False)
        form.addWidget(self.log_title)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("pNote")
        self.log_text.setFixedHeight(56)
        self.log_text.setPlaceholderText(i18n.t("What happened"))
        form.addWidget(self.log_text)
        self.log_save = C.button(i18n.t("Log it"), small=True, on_click=self._log_it)
        form.addWidget(self.log_save, 0, Qt.AlignRight)
        self.log_box.hide()
        self._log_kind = "call"
        lay.addWidget(self.log_box)
        self.activity_list = QVBoxLayout()
        self.activity_list.setContentsMargins(0, 0, 0, 0)
        self.activity_list.setSpacing(theme.SPACE_2)
        lay.addLayout(self.activity_list)
        self._draw_activities()
        lay.addStretch(1)

    def _draw_activities(self) -> None:
        _clear(self.activity_list)
        shown = [a for a in activities(self.view) if _matches(a["kind"], self._activity)]
        if not shown:
            self.activity_list.addWidget(_label(i18n.t("Nothing here yet."), "pMuted"))
        for a in shown:
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_3)
            dot = QLabel()
            dot.setFixedSize(28, 28)
            dot.setAlignment(Qt.AlignCenter)
            dot.setPixmap(icons.pixmap(_TIMELINE_ICON.get(a["kind"], "clock"), 15, theme.NEUTRAL[700]))
            dot.setStyleSheet(f"QLabel{{background:{theme.NEUTRAL[200]};border-radius:14px;}}")
            line.addWidget(dot, 0, Qt.AlignTop)
            words = QVBoxLayout()
            words.setContentsMargins(0, 0, 0, 0)
            words.setSpacing(0)
            words.addWidget(_label(a["text"], select=True))
            words.addWidget(_label(evidence.when(a["at"]) or "—", "pKey", wrap=False))
            line.addLayout(words, 1)
            self.activity_list.addLayout(line)

    def _filter_activities(self, key: str) -> None:
        self._activity = key
        for k, b in self.activity_btns.items():
            b.setChecked(k == key)
        self._draw_activities()

    def _log_form(self, kind: str) -> None:
        self._log_kind = kind
        self.log_title.setText(i18n.t("Log a {kind}").format(
            kind=i18n.t(dict(_LOG_KINDS)[kind]).lower()))
        self.log_box.show()
        self.log_text.setFocus(Qt.OtherFocusReason)

    def _log_it(self) -> None:
        text = self.log_text.toPlainText().strip()
        if self.view is None:
            return
        self.logRequested.emit(self.view.lead, self._log_kind, text)

    def _fill_sequences(self, view: PersonView) -> None:
        lay, draft = self._pages["sequences"], view.draft
        opener = (getattr(draft, "body", "") if draft is not None else "") or \
            getattr(view.row, "opener", "") or ""
        if not opener:
            lay.addWidget(_label(i18n.t("Not in a sequence. Qualify them to draft an "
                                        "e-mail, or add them to a sequence."), "pMuted"))
            lay.addWidget(_link(i18n.t("Add to sequence…"),
                                lambda: self.sequenceRequested.emit(self.view.row)))
            lay.addStretch(1)
            return
        status = getattr(draft, "status", "draft") if draft is not None else "draft"
        words = {"draft": i18n.t("Not sent yet"), "sent": i18n.t("Sent"),
                 "failed": i18n.t("Failed"), "skipped": i18n.t("Skipped")}
        box, col = _widget(i18n.t("First touch"))
        head = QHBoxLayout()
        subject = getattr(draft, "subject", "") if draft is not None else ""
        head.addWidget(_label(subject or i18n.t("(no subject yet)"), "pVal"), 1)
        head.addWidget(_pill(words.get(status, status), theme.NEUTRAL[700], theme.NEUTRAL[200]))
        col.addLayout(head)
        col.addWidget(_label(opener, select=True))
        if draft is not None and getattr(draft, "error", ""):
            col.addWidget(_label(draft.error, "pMuted"))
        lay.addWidget(box)
        box, col = _widget(i18n.t("Stop-on-reply sequence · 3 touches"))
        for i, (step, when) in enumerate((("First touch", "today"), ("Follow-up", "+3 days"),
                                           ("Last touch", "+7 days")), 1):
            col.addWidget(_label(f"{i}  {i18n.t(step)} · {i18n.t(when)}"))
        col.addWidget(_label(i18n.t("Stops the moment they reply."), "pMuted"))
        lay.addWidget(box)
        lay.addStretch(1)

    def _fill_enrichment(self, view: PersonView) -> None:
        """Apollo's Enrichment tab: "displays any enrichable fields for the
        contact. Select one or fields, then click Enrich fields." What each
        spends is said beside it, and each still asks before it spends."""
        lay, lead = self._pages["enrichment"], view.lead
        lay.addWidget(_label(i18n.t("Pick what to fill in, then Enrich fields. Anything "
                                    "that costs a credit asks first."), "pMuted"))
        from addons.leads.cockpit import needs_email
        self.enrich_boxes = {}
        from prospector import mobiles, phones
        choices = (
            ("email", i18n.t("E-mail — look it up and check it (free verifiers first, "
                             "then a finder credit)"), needs_email(view.row)),
            ("phone", i18n.t("Phone — the number their company publishes (one Exa "
                             "lookup; a credit only for a number found)"),
             phones.needs_phone(lead)),
            ("mobile", i18n.t("Mobile — their own mobile number (Apollo; takes a few minutes; "
                              "a credit only for a number found)"), mobiles.needs_mobile(lead)),
            ("company", i18n.t("Company — website, size, revenue and HQ (one Exa search)"),
             bool(_text(lead.company) or _extra(lead, "website"))),
            ("qualify", i18n.t("Qualify — research, score and draft an opener (Groq and "
                               "one news search)"), view.status in RETRYABLE),
        )
        for key, text, can in choices:
            row, cb, words = _check_row(text)
            cb.setEnabled(bool(can))
            words.setObjectName("pVal" if can else "pMuted")
            lay.addWidget(row)
            self.enrich_boxes[key] = cb
        self.enrich_btn = C.button(i18n.t("Enrich fields"), on_click=self._enrich)
        lay.addWidget(self.enrich_btn, 0, Qt.AlignLeft)
        lay.addStretch(1)

    def _enrich(self) -> None:
        picked = [k for k, cb in self.enrich_boxes.items() if cb.isEnabled() and cb.isChecked()]
        if picked and self.view is not None:
            self.enrichRequested.emit(self.view.row, picked)

    def _fill_fields(self) -> None:
        lay = self._pages["fields"]
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText(i18n.t("Search fields"))
        self.field_search.setClearButtonEnabled(True)
        self.field_search.textChanged.connect(lambda _t: self._draw_fields())
        top.addWidget(self.field_search, 1)
        self.field_side_btns = {}
        for key, name in (("people", "People"), ("company", "Company")):
            b = QPushButton(i18n.t(name))
            b.setObjectName("pSeg")
            b.setCheckable(True)
            b.setChecked(key == self._fields_side)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._fields_to(k))
            top.addWidget(b)
            self.field_side_btns[key] = b
        lay.addLayout(top)
        self.field_grid = QGridLayout()
        self.field_grid.setHorizontalSpacing(theme.SPACE_3)
        self.field_grid.setVerticalSpacing(theme.SPACE_2)
        self.field_grid.setColumnStretch(1, 1)
        lay.addLayout(self.field_grid)
        self._draw_fields()
        lay.addStretch(1)

    def _fields_to(self, side: str) -> None:
        self._fields_side = side
        for k, b in self.field_side_btns.items():
            b.setChecked(k == side)
        self._draw_fields()

    def _draw_fields(self) -> None:
        _clear(self.field_grid)
        want = self.field_search.text().strip().casefold()
        rows = [(k, v) for k, v in all_fields(self.view, self._fields_side)
                if not want or want in k.casefold() or want in v.casefold()]
        self.field_rows = rows
        for r, (key, value) in enumerate(rows):
            self.field_grid.addWidget(_label(key, "pKey"), r, 0, Qt.AlignTop)
            self.field_grid.addWidget(_label(value or "—", "pVal" if value else "pMuted",
                                             select=True), r, 1)

    # ── acting ────────────────────────────────────────────────────────────────
    @staticmethod
    def _url(value: str) -> str:
        value = _text(value)
        if value and "://" not in value:
            value = "https://" + value
        return value

    def open_url(self, url: str) -> None:
        """Open an http(s) link in the browser. A test seam."""
        safe = evidence.safe_url(url)
        if safe:
            QDesktopServices.openUrl(QUrl(safe))

    def _open_extra(self, key: str) -> None:
        if self.view is not None:
            self.open_url(self._url(_extra(self.view.lead, key)))

    def _mail(self) -> None:
        email = _text(self.view.lead.email) if self.view is not None else ""
        if email:
            QDesktopServices.openUrl(QUrl(f"mailto:{email}"))

    def _call(self) -> None:
        phone = _text(self.view.lead.phone) if self.view is not None else ""
        if phone:
            QDesktopServices.openUrl(QUrl("tel:" + "".join(ch for ch in phone
                                                           if ch.isdigit() or ch == "+")))

    def _save(self) -> None:
        if self.view is not None:
            self.saveRequested.emit(self.view.lead)

    def _stage_picked(self, _index: int) -> None:
        stage = self.stage.currentData() or ""
        if stage and self.view is not None:
            self.stageRequested.emit(self.view.lead, stage)

    def _add_note(self) -> None:
        text = self.note_edit.toPlainText().strip()
        if text and self.view is not None:
            self.noteRequested.emit(self.view.lead, text)

    def _add_task(self) -> None:
        text = self.task_text.text().strip()
        if not text or self.view is None:
            return
        due = self.task_due.date().toString(Qt.ISODate) if self.task_due_on.isChecked() else ""
        self.taskRequested.emit(self.view.lead, text, due)

    def ask_edit(self, values: dict):
        """Edit contact info: a small form over the fields Prism keeps; the
        changed values, or None on Cancel. A test seam."""
        from dialogs.base import PrismDialog
        dlg = PrismDialog(i18n.t("Edit contact info"), parent=self)
        form = QGridLayout()
        edits = {}
        for r, (key, name) in enumerate(_EDIT_FIELDS):
            form.addWidget(_label(i18n.t(name), "pKey", wrap=False), r, 0)
            edit = QLineEdit(values.get(key, ""))
            form.addWidget(edit, r, 1)
            edits[key] = edit
        dlg.body.addLayout(form)
        dlg.footer.add_secondary(dlg.button(i18n.t("Cancel"), on_click=dlg.reject))
        dlg.footer.set_primary(dlg.button(i18n.t("Save contact"), "primary",
                                          on_click=dlg.accept))
        if dlg.exec() != PrismDialog.Accepted:
            return None
        return {k: e.text() for k, e in edits.items() if e.text().strip() != values.get(k, "")}

    def _edit(self) -> None:
        if self.view is None:
            return
        lead = self.view.lead
        values = {k: (_text(getattr(lead, k, "")) if hasattr(lead, k) else _extra(lead, k))
                  for k, _n in _EDIT_FIELDS}
        changes = self.ask_edit(values)
        if changes:
            self.editRequested.emit(lead, changes)

    def confirm_delete(self, name: str) -> bool:
        """Apollo's warning, in Prism's words. A test seam."""
        # Built rather than QMessageBox.question(...): the static helpers give no
        # way to set a text format and default to AutoText, and `name` comes from
        # an imported sheet or a provider, so markup in it would render as
        # markup in the box that confirms who is about to be deleted.
        box = QMessageBox(
            QMessageBox.Icon.Question, i18n.t("Delete contact"),
            i18n.t("Delete {name} from your contacts? Their stage, lists, notes, tasks "
                   "and activity go with them. Someone a search found stays on the "
                   "page as net new.").format(name=name or i18n.t("this person")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _delete(self) -> None:
        if self.view is not None and self.view.contact is not None \
                and self.confirm_delete(self.view.lead.name):
            self.deleteRequested.emit(self.view.lead)

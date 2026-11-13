"""Due today — the screen to open each morning (drafted in "Prism CRM: interface mockups", 3 Nov 2026).

What needs the owner, in one list, and nothing in it sends by itself:

  · a task that is due today or late         → "Today" / "Late"            [Open] [Done]
  · someone marked Replied, nothing since    → "Replied"                   [Open]
  · an active contact who has gone quiet     → "Quiet 9d"                  [Open]
  · an open deal that has not moved for 7 days → "Stalled 9d"                [Open deal]
  · a sequence touch that has fallen due     → "Late 3 days" / "Today"      [Open] [Copy touch]

Everything is read from the saved contacts (contacts.Contact) and the deals (deals.Deal), so every line can be stood behind. The mockup also shows a
WhatsApp hand-over; Prism does not record one yet, so it is not here.

`due_items` is a plain function; `DueTodayPage` only draws what it is handed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

import i18n
import theme
from addons.leads import deals as DL
from addons.leads import result_rows as RR
from widgets import controls as C

QUIET_DAYS = 7                                  # an active contact with nothing for this long has gone quiet
ACTIVE_STAGES = ("Approaching", "Interested")   # the stages where silence is a problem


@dataclass
class DueItem:
    kind: str                # "task" | "replied" | "quiet" | "deal" | "touch"
    contact: object
    name: str
    company: str
    subline: str
    pill: str
    tone: str                # a result_rows tone
    task_id: str = ""
    order: int = 0           # lower comes first
    deal: object = None      # the deals.Deal, for kind "deal"
    touch: object = None     # the sequences.Enrolment, for kind "touch"


def _day(stamp) -> Optional[date]:
    try:
        return date.fromisoformat(str(stamp or "").strip()[:10])
    except ValueError:
        return None


def last_activity(contact) -> Optional[date]:
    """The most recent thing that happened with this contact, as a day: a history line, a note, a task, or the save itself."""
    days = [_day(h.get("at")) for h in getattr(contact, "history", None) or ()]
    days += [_day(n.get("at")) for n in getattr(contact, "notes", None) or ()]
    days += [_day(t.get("at")) for t in getattr(contact, "tasks", None) or ()]
    days += [_day(getattr(contact, "updated_at", "")), _day(getattr(contact, "saved_at", ""))]
    days = [d for d in days if d is not None]
    return max(days) if days else None


def _plural(n: int, one: str, many: str) -> str:
    return i18n.t(one if n == 1 else many).format(n=n)


def due_items(contacts, today: Optional[date] = None, quiet_days: int = QUIET_DAYS, deals=(), touches=()) -> list:
    """Everything that needs the owner today, most urgent first. `touches` are sequences.Enrolment already due."""
    today = today or date.today()
    out = []
    touched = set()
    for e in touches or ():
        if not e.is_due() or e.next_step is None:
            continue
        lead = e.contact.lead
        touched.add(id(e.contact))
        label = i18n.t("Touch {n} of {total}").format(n=e.done + 1, total=e.total)
        out.append(DueItem("touch", e.contact, lead.name or i18n.t("(no name)"), lead.company or "",
                           (label + " " + _plural(e.late_days, "was due 1 day ago", "was due {n} days ago")) if e.late_days
                           else label + " " + i18n.t("is due today"),
                           _plural(e.late_days, "Late 1 day", "Late {n} days") if e.late_days else i18n.t("Today"),
                           "warn" if e.late_days else "quiet", order=-2000 - e.late_days, touch=e))
    for d in deals or ():
        stalled = DL.stalled_days(d, today)
        if stalled:
            out.append(DueItem("deal", None, d.title, d.company if d.company.casefold() != d.title.casefold() else "",
                               i18n.t("No movement for {n} days. Next step: {step}").format(n=stalled, step=d.next_step)
                               if d.next_step else i18n.t("No movement for {n} days. No next step set.").format(n=stalled),
                               i18n.t("Stalled {n}d").format(n=stalled), "warn", order=-stalled, deal=d))
    for c in contacts or ():
        lead = c.lead
        name, company = lead.name or i18n.t("(no name)"), lead.company or ""
        open_tasks = [t for t in (c.tasks or ()) if not t.get("done")]
        for t in open_tasks:
            due = _day(t.get("due"))
            if due is None or due > today:
                continue
            late = (today - due).days
            out.append(DueItem("task", c, name, company, str(t.get("text") or ""),
                               _plural(late, "Late 1 day", "Late {n} days") if late else i18n.t("Today"),
                               "warn" if late else "quiet", task_id=str(t.get("id") or ""), order=-1000 - late))
        if c.stage == "Replied":
            since = last_activity(c)
            replied_on = next((_day(h.get("at")) for h in reversed(c.history or ())
                               if h.get("kind") == "stage" and str(h.get("text", "")).endswith("Replied")), None)
            nothing_since = replied_on is not None and not any(
                (_day(h.get("at")) or date.min) > replied_on and h.get("kind") in ("sent", "email", "call", "meeting", "message")
                for h in c.history or ())
            if not c.history or nothing_since:
                when = replied_on or since
                out.append(DueItem("replied", c, name, company,
                                   i18n.t("Marked as replied {when}, nothing done since").format(when=when.strftime("%d %b")) if when
                                   else i18n.t("Marked as replied, nothing done since"),
                                   i18n.t("Replied"), "info", order=-500))
        elif c.stage in ACTIVE_STAGES and not open_tasks and id(c) not in touched:
            seen = last_activity(c)
            if seen is not None and (today - seen).days >= quiet_days:
                gone = (today - seen).days
                out.append(DueItem("quiet", c, name, company,
                                   i18n.t("Nothing for {n} days. Last: {when}").format(n=gone, when=seen.strftime("%d %b")),
                                   i18n.t("Quiet {n}d").format(n=gone), "warn", order=-gone))
    out.sort(key=lambda i: (i.order, i.name.casefold()))
    return out


class DueTodayPage(QWidget):
    """The list. It sends nothing: Open shows the person, Done ticks a task off."""

    openRequested = Signal(object)                 # the lead
    taskDoneRequested = Signal(object, str, bool)  # lead, task id, done
    dealOpenRequested = Signal(object)             # the deals.Deal
    touchCopied = Signal(object)                   # the lead, after its drafted touch went to the clipboard

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("dueHead")
        head.setStyleSheet(f"QFrame#dueHead{{background:{theme.CARD};border:none;border-bottom:1px solid {theme.HAIRLINE};}}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        hl.setSpacing(2)
        hl.addWidget(C.label(i18n.t("Due today"), level="SECTION", weight=700))
        self.summary = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        hl.addWidget(self.summary)
        outer.addWidget(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        col.setSpacing(0)
        self.list = RR.ResultList()
        col.addWidget(self.list)
        self.empty = C.EmptyState("check", i18n.t("Nothing is due"),
                                  i18n.t("A task that falls due, someone who replies, or a contact who goes quiet will show up here."))
        col.addWidget(self.empty)
        col.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self.set_contacts([])

    def count(self) -> int:
        return len(self._items)

    def set_contacts(self, contacts, today: Optional[date] = None, deals=(), touches=()) -> None:
        self._items = due_items(contacts, today, deals=deals, touches=touches)
        self.list.clear()
        self.list.add_all([self._row(i, it) for i, it in enumerate(self._items)])
        self.list.setVisible(bool(self._items))
        self.empty.setVisible(not self._items)
        n = len(self._items)
        self.summary.setText(i18n.t("Nothing needs you right now.") if not n else
                             (_plural(n, "One thing needs you. Nothing here sends by itself.",
                                      "{n} things need you. Nothing here sends by itself.")))

    def _row(self, idx: int, it: DueItem) -> QWidget:
        if it.kind == "deal":
            row = RR.ResultRow(RR.RowSpec(key=idx, name=it.name, company=it.company, subline=it.subline, pills=[(it.pill, it.tone)],
                                          actions=[(i18n.t("Open deal"), True, lambda _=False, d=it.deal: self.dealOpenRequested.emit(d))],
                                          checkable=False))
            row.clicked.connect(lambda _i, d=it.deal: self.dealOpenRequested.emit(d))
            return row
        lead = it.contact.lead
        actions = [(i18n.t("Open"), True, lambda _=False, l=lead: self.openRequested.emit(l))]
        if it.kind == "touch":
            actions.append((i18n.t("Copy touch"), False, lambda _=False, e=it.touch: self.copy_touch(e)))
        if it.kind == "task":
            actions.append((i18n.t("Done"), False,
                            lambda _=False, l=lead, tid=it.task_id: self.taskDoneRequested.emit(l, tid, True)))
        row = RR.ResultRow(RR.RowSpec(key=idx, name=it.name, company=it.company, subline=it.subline,
                                      pills=[(it.pill, it.tone)], actions=actions, checkable=False))
        row.clicked.connect(lambda _i, l=lead: self.openRequested.emit(l))
        return row

    def copy_touch(self, enrolment) -> bool:
        """Put the drafted touch (subject, then text, the person's details filled in) on the clipboard to paste into a message."""
        from PySide6.QtWidgets import QApplication
        from addons.leads import sequences as SQ
        step = enrolment.next_step
        if step is None:
            return False
        subject, body = SQ.render(step, enrolment.contact.lead)
        QApplication.clipboard().setText(f"Subject: {subject}\n\n{body}")
        self.touchCopied.emit(enrolment.contact.lead)
        return True

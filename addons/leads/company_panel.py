"""
Leads & Outreach — the company profile (Apollo's account profile)
────────────────────────────────────────────────────────────────
Apollo opens a company from the Companies list into its account profile
(knowledge.apollo.io, "View and Edit Accounts", read 24-Oct-2026), and so does
Prism, as a page of its own with a way back to the list:

    header       the face, the name (its website beside it), "Industry ·
                 Location"; Save, Add to list, Find people, and "…" — Edit
                 company info, Flag as inaccurate, Delete account
    on the left  Company details · Record details · Tasks · Contacts · Notes
    tabs         Overview · Activities · People · Enrichment · All fields

Apollo's own widgets and tabs that Prism has nothing real behind are left out,
never drawn empty: Deals (Prism keeps no deals yet), Conversations, Locations,
Files, the owner, the meeting assistant, lookalike companies and its paid
"company insights" (score, funding, technologies, website visitors).

Everything shown is a record Prism holds — the company (the pool's row), its
saved account as the file has it (stage, lists, notes, tasks, Activities) and
the people Prism holds there — gathered by the controller into a CompanyView.
The panel changes nothing itself: every act is a signal the controller carries
out on the stores, and the panel is then handed the record as it now stands.
Acting on a company that is not saved saves it first — Apollo's rule: "save a
company to turn it into an account. This unlocks key actions like enrichment,
ownership, and timeline tracking."

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
from addons.leads import accounts as AC
from addons.leads import evidence
from addons.leads import person as PN
from widgets import controls as C
from widgets import icons

_WIDE = 700            # at least this wide: the widgets beside the tabs
_LEFT_W = 288          # the widgets' column when it sits beside the tabs
_STICKY_H = 440        # at least this tall: the header stays pinned above the scroll
_LIST_MAX = 8          # notes / tasks / contacts shown before "and N more"
_PEOPLE_MAX = 200      # the People tab draws this many rows, then says how many more
# The tabs, Apollo's order, left to right.
TABS = (("overview", "Overview"), ("activities", "Activities"), ("people", "People"),
        ("enrichment", "Enrichment"), ("fields", "All fields"))
# How the saved-via keys read in Activities (accounts.VIA).
_VIA_WORDS = {"import": "Imported from a CSV", "contact": "Saved with one of its contacts",
              "save": "Saved as an account", "enrich": "Saved by a company lookup"}
_EDIT_LABELS = {"name": "Name", "website": "Website", "location": "Headquarters",
                "industry": "Industry", "headcount": "Employees", "revenue": "Annual revenue",
                "phone": "Phone", "linkedin": "LinkedIn", "description": "Description"}
# What a lookup can fill in (workers.LeadsAccountEnrichWorker), in the order shown.
_LOOKUP_FIELDS = (("website", "Website"), ("headcount", "Employees"),
                  ("revenue", "Annual revenue"), ("location", "Headquarters"),
                  ("description", "Description"))


@dataclass
class CompanyView:
    """Everything the panel shows about one company — plain data, gathered by
    the controller (companies_controller.CompaniesController.view_of)."""
    company: object                                 # companies.Company, the pool's row
    account: object = None                          # accounts.Account, as saved
    people: list = field(default_factory=list)      # pool.Person who work there

    @property
    def name(self) -> str:
        return getattr(self.company, "name", "") or ""

    @property
    def saved(self) -> bool:
        return self.account is not None


def activities(view: CompanyView) -> list:
    """The Activities tab — every line Prism can stand behind, newest first:
    [{"at", "kind", "text"}]: the account's own history (how it was saved,
    stage moves, lists, edits, lookups, what the owner logged), its notes and
    tasks. A line with no date sorts last."""
    out = []
    account = view.account
    for h in list(getattr(account, "history", None) or ()):
        kind, text = h.get("kind", ""), h.get("text", "")
        if kind == "saved":
            line = i18n.t(_VIA_WORDS.get(text, "Saved as an account"))
        elif kind == "stage":
            old, _sep, new = text.partition(" → ")
            line = (i18n.t("Stage changed from {old} to {new}").format(old=old, new=new)
                    if new else i18n.t("Stage set to {new}").format(new=text))
        elif kind == "list":
            line = i18n.t("Added to the list {name}").format(name=text)
        elif kind == "edited":
            line = i18n.t("Company info edited: {fields}").format(fields=text)
        elif kind == "enriched":
            line = i18n.t("Looked up on Exa") + (f": {text}" if text else "")
        elif kind == "flagged":
            line = i18n.t("Flagged as inaccurate") + (f": {text}" if text else "")
        else:
            said = dict(PN._LOG_KINDS).get(kind, "Other")
            line = i18n.t("{kind} logged").format(kind=i18n.t(said)) + (
                f": {text}" if text else "")
        out.append({"at": h.get("at", ""), "kind": kind, "text": line})
    for note in getattr(account, "notes", None) or ():
        out.append({"at": note.get("at", ""), "kind": "note",
                    "text": i18n.t("Note: {text}").format(text=note.get("text", ""))})
    for task in getattr(account, "tasks", None) or ():
        done = i18n.t(" (done)") if task.get("done") else ""
        out.append({"at": task.get("at", ""), "kind": "task",
                    "text": i18n.t("Task: {text}").format(text=task.get("text", "")) + done})
    dated = [a for a in out if PN._moment(a["at"]) is not None]
    dated.sort(key=lambda a: PN._moment(a["at"]), reverse=True)
    return dated + [a for a in out if PN._moment(a["at"]) is None]


def all_fields(view: CompanyView) -> list:
    """All fields: (field, value) for the company — every field Prism holds,
    the sheet's own columns included."""
    c, account = view.company, view.account
    rows = [(i18n.t("Company"), c.name), (i18n.t("Website"), c.website),
            (i18n.t("Domain"), c.domain), (i18n.t("Industry"), c.industry),
            (i18n.t("Employees"), c.headcount), (i18n.t("Annual revenue"), c.revenue),
            (i18n.t("Headquarters"), c.location), (i18n.t("Phone"), c.phone),
            (i18n.t("LinkedIn"), c.linkedin), (i18n.t("Description"), c.description)]
    if account is not None:
        rows.append((i18n.t("Stage"), account.stage))
        rows.append((i18n.t("Lists"), ", ".join(account.lists)))
        rows.append((i18n.t("Saved"), evidence.when(account.saved_at)))
    rows.append((i18n.t("People held"), str(len(view.people))))
    rows.append((i18n.t("Saved contacts"), str(sum(1 for p in view.people if p.saved))))
    for key in sorted(c.custom, key=lambda k: str(k).casefold()):
        rows.append((PN._text(key), PN._text(c.custom[key])))
    return [(k, PN._text(v)) for k, v in rows if k]


def _plural(n: int, one: str, many: str) -> str:
    return i18n.t(one) if n == 1 else i18n.t(many).format(n=f"{n:,}")


# ── the panel ─────────────────────────────────────────────────────────────────

class CompanyPanel(QWidget):
    """Apollo's account profile for one company — see the module docstring.

        panel.show_company(view)            # a CompanyView
        panel.stageRequested.connect(...)   # the controller does the rest

    Test seams (no modal box in a test): ask_edit, confirm_delete, open_url."""

    backRequested = Signal()
    saveRequested = Signal(object)                 # Company — save it as an account
    stageRequested = Signal(object, str)           # Company, account stage
    listRequested = Signal(object)                 # Company — Add to list
    findPeopleRequested = Signal(object)           # Company — Find people there
    noteRequested = Signal(object, str)            # Company, text
    taskRequested = Signal(object, str, str)       # Company, text, due (ISO date or "")
    taskDoneRequested = Signal(object, str, bool)  # Company, task id, done
    logRequested = Signal(object, str, str)        # Company, kind (accounts.LOGGED), text
    editRequested = Signal(object, dict)           # Company, {field: value}
    flagRequested = Signal(object)                 # Company
    deleteRequested = Signal(object)               # Company
    enrichRequested = Signal(object)               # Company — look it up on Exa
    personPicked = Signal(object)                  # a pool.Person who works there

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("personPanel")           # person.py's sheet, one look for both
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(PN._sheet())
        self.view: CompanyView | None = None
        self._tab = "overview"
        self._activity = "all"
        self._wide = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root = root
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
        self._head_slot = QVBoxLayout()
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
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        self._back_btn = QPushButton("‹ " + i18n.t("Companies"))
        self._back_btn.setObjectName("pLink")
        self._back_btn.setCursor(Qt.PointingHandCursor)
        self._back_btn.clicked.connect(lambda _=False: self.backRequested.emit())
        col.addWidget(self._back_btn, 0, Qt.AlignLeft)
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
        self.name = PN._label("", "pName", wrap=True, select=True)
        name_row.addWidget(self.name, 0)
        self._site_btn = C.icon_button("globe", i18n.t("Open the company's website"),
                                       on_click=self._open_site)
        self._site_btn.setFixedSize(26, 26)
        name_row.addWidget(self._site_btn, 0, Qt.AlignVCenter)
        self._linkedin_btn = C.icon_button("linkedin", i18n.t("Open its LinkedIn page"),
                                           on_click=self._open_linkedin)
        self._linkedin_btn.setFixedSize(26, 26)
        name_row.addWidget(self._linkedin_btn, 0, Qt.AlignVCenter)
        name_row.addStretch(1)
        who.addLayout(name_row)
        self.role = PN._label("", "pRole", wrap=True, select=True)
        who.addWidget(self.role)
        top.addLayout(who, 1)
        col.addLayout(top)
        acts = QHBoxLayout()
        acts.setContentsMargins(0, 0, 0, 0)
        acts.setSpacing(theme.SPACE_2)
        self._task_btn = C.icon_button("check-square", i18n.t("Add a task"),
                                       on_click=lambda: self._task_form(True))
        self._call_btn = C.icon_button("phone", i18n.t("Call the company"), on_click=self._call)
        acts.addWidget(self._call_btn)
        acts.addWidget(self._task_btn)
        acts.addStretch(1)
        self._save_btn = C.button(i18n.t("Save"), on_click=self._save)
        self._list_btn = C.button(i18n.t("Add to list"), icon_name="list-plus",
                                  on_click=lambda: self.listRequested.emit(self.view.company))
        self._find_btn = C.button(i18n.t("Find people"), "primary", icon_name="search",
                                  on_click=lambda: self.findPeopleRequested.emit(
                                      self.view.company))
        acts.addWidget(self._save_btn)
        acts.addWidget(self._list_btn)
        acts.addWidget(self._find_btn)
        self._more = QToolButton()
        self._more.setObjectName("pMore")
        self._more.setIcon(icons.icon("more-horizontal", 17, theme.NEUTRAL[700]))
        self._more.setIconSize(QSize(17, 17))
        self._more.setFixedSize(34, 34)
        self._more.setToolTip(i18n.t("More"))
        self._more.setPopupMode(QToolButton.InstantPopup)
        self._more.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self._more)
        self._act_edit = menu.addAction(i18n.t("Edit company info"))
        self._act_edit.triggered.connect(self._edit)
        self._act_flag = menu.addAction(i18n.t("Flag as inaccurate"))
        self._act_flag.setToolTip(i18n.t("Its details are wrong: it is noted in Activities"))
        self._act_flag.triggered.connect(lambda: self.flagRequested.emit(self.view.company))
        menu.addSeparator()
        self._act_delete = menu.addAction(i18n.t("Delete account"))
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

    def set_tab(self, key: str) -> None:
        if key not in self.tab_btns:
            return
        self._tab = key
        for k, b in self.tab_btns.items():
            b.setChecked(k == key)
        self._stack.setCurrentIndex([k for k, _n in TABS].index(key))

    def tab(self) -> str:
        return self._tab

    # ── showing a company ─────────────────────────────────────────────────────
    def show_company(self, view: CompanyView | None) -> None:
        """Draw one company's profile, or nothing for None. The tab the owner
        was on stays."""
        self.view = view
        for lay in list(self._pages.values()) + [self.left_lay]:
            PN._clear(lay)
        if view is None:
            return
        c = view.company
        from addons.leads.cockpit import _initials
        self._avatar.setText(_initials(c.name))
        self.name.setText(c.name or i18n.t("(no name)"))
        # A wrapping label in a stretch-less row is sized for the person drawer
        # and breaks "Acme Tooling Pvt Ltd" in two on a page this wide: give it
        # its own line's width, up to a cap.
        self.name.ensurePolished()
        self.name.setMinimumWidth(min(
            self.name.fontMetrics().horizontalAdvance(self.name.text()) + 8, 640))
        self.role.setText(" · ".join(p for p in (PN._text(c.industry), PN._text(c.location)) if p))
        self._site_btn.setVisible(bool(self._site_url()))
        self._linkedin_btn.setVisible(bool(evidence.safe_url(PN.PersonPanel._url(c.linkedin))))
        self._call_btn.setEnabled(bool(PN._text(c.phone)))
        self._save_btn.setVisible(not view.saved)
        self._act_delete.setEnabled(view.saved)
        self._act_flag.setEnabled(view.saved)
        self._fill_left(view)
        self._fill_overview(view)
        self._fill_activities()
        self._fill_people(view)
        self._fill_enrichment(view)
        self._fill_fields()
        self.set_tab(self._tab)

    def _site_url(self) -> str:
        c = self.view.company if self.view is not None else None
        return evidence.safe_url(PN.PersonPanel._url((c.website or c.domain) if c else ""))

    # left: Company details, Record details, Tasks, Contacts, Notes
    def _fill_left(self, view: CompanyView) -> None:
        lay, c = self.left_lay, view.company
        if not view.saved:
            banner = QFrame()
            banner.setObjectName("pBanner")
            row = QHBoxLayout(banner)
            row.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
            row.addWidget(PN._label(i18n.t("Not saved yet — save it to keep a stage, lists, "
                                           "notes, tasks and its activity."), "pBannerText"), 1)
            lay.addWidget(banner)

        box, col = PN._widget(i18n.t("Company details"))
        if c.description:
            self.description = PN._label(c.description, select=True)
            col.addWidget(self.description)
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        r = 0
        for key, label in (("industry", "Industry"), ("headcount", "Employees"),
                           ("revenue", "Annual revenue"), ("location", "Headquarters"),
                           ("phone", "Phone")):
            value = PN._text(getattr(c, key, ""))
            grid.addWidget(PN._label(i18n.t(label), "pKey", wrap=False), r, 0, Qt.AlignTop)
            grid.addWidget(PN._label(value or i18n.t("Not on record"),
                                     "pVal" if value else "pMuted", select=True), r, 1)
            r += 1
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        site = self._site_url()
        if site:
            col.addWidget(PN._link(site.split("://", 1)[-1].rstrip("/"),
                                   lambda u=site: self.open_url(u)))
        if not (c.website or c.domain):
            self.find_site = PN._link(i18n.t("Find its website…"),
                                      lambda: self.enrichRequested.emit(self.view.company))
            col.addWidget(self.find_site)
        lay.addWidget(box)

        box, col = PN._widget(i18n.t("Record details"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        r = 0
        self.stage = QComboBox()
        self.stage.setObjectName("pStage")
        current = view.account.stage if view.saved else ""
        stages = list(AC.STAGES)
        if current and current not in stages:
            stages.append(current)
        if not current:
            self.stage.addItem(i18n.t("No stage yet"), "")
        for s in stages:
            self.stage.addItem(s, s)
        self.stage.setCurrentIndex(max(0, self.stage.findData(current)))
        self.stage.activated.connect(self._stage_picked)
        grid.addWidget(PN._label(i18n.t("Stage"), "pKey", wrap=False), r, 0)
        grid.addWidget(self.stage, r, 1)
        r += 1
        lists = list(view.account.lists) if view.saved else []
        grid.addWidget(PN._label(i18n.t("Lists"), "pKey", wrap=False), r, 0, Qt.AlignTop)
        grid.addWidget(PN._label(", ".join(lists) or i18n.t("None"),
                                 "pVal" if lists else "pMuted"), r, 1)
        r += 1
        latest = next((a["at"] for a in activities(view) if a["at"]), "")
        grid.addWidget(PN._label(i18n.t("Last activity"), "pKey", wrap=False), r, 0)
        grid.addWidget(PN._label(evidence.when(latest) or i18n.t("None yet"),
                                 "pVal" if latest else "pMuted"), r, 1)
        r += 1
        if view.saved:
            grid.addWidget(PN._label(i18n.t("Saved"), "pKey", wrap=False), r, 0)
            grid.addWidget(PN._label(evidence.when(view.account.saved_at)), r, 1)
            r += 1
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        col.addWidget(PN._link(i18n.t("See all fields"), lambda: self.set_tab("fields")))
        lay.addWidget(box)

        box, col = PN._widget(i18n.t("Tasks"), (i18n.t("Add a task"),
                                                lambda: self._task_form(True)))
        self._task_box = col
        self._task_editor = self._task_form_widget()
        self._task_editor.hide()
        col.addWidget(self._task_editor)
        tasks = list(getattr(view.account, "tasks", None) or ())
        open_first = sorted(tasks, key=lambda t: (t["done"], t.get("due") or "9999",
                                                  t.get("at", "")))
        self.task_boxes: dict = {}
        self.task_labels: dict = {}
        for task in open_first[:_LIST_MAX]:
            row, cb, words = PN._check_row(
                task["text"] + (f"  · {i18n.t('due')} {evidence.when(task['due'])}"
                                if task.get("due") else ""))
            cb.setChecked(task["done"])
            cb.toggled.connect(lambda on, tid=task["id"]: self.taskDoneRequested.emit(
                self.view.company, tid, bool(on)))
            col.addWidget(row)
            self.task_boxes[task["id"]] = cb
            self.task_labels[task["id"]] = words
        if not tasks:
            col.addWidget(PN._label(i18n.t("No tasks."), "pMuted"))
        elif len(tasks) > _LIST_MAX:
            col.addWidget(PN._label(i18n.t("and {n} more — under Activities").format(
                n=len(tasks) - _LIST_MAX), "pMuted"))
        lay.addWidget(box)

        box, col = PN._widget(i18n.t("Contacts"))
        saved_people = [p for p in view.people if p.saved]
        self.contact_links: list = []
        for p in saved_people[:_LIST_MAX]:
            line = QHBoxLayout()
            who = PN._link(p.lead.name or i18n.t("(no name)"),
                           lambda person=p: self.personPicked.emit(person))
            self.contact_links.append(who)
            line.addWidget(who)
            line.addWidget(PN._label(PN._text(p.lead.title), "pMuted", wrap=False), 1)
            col.addLayout(line)
        if not saved_people:
            col.addWidget(PN._label(i18n.t("No saved contacts here yet."), "pMuted"))
        if len(view.people) > len(saved_people[:_LIST_MAX]):
            col.addWidget(PN._link(_plural(len(view.people), "See the 1 person Prism holds",
                                           "See all {n} people Prism holds"),
                                   lambda: self.set_tab("people")))
        lay.addWidget(box)

        box, col = PN._widget(i18n.t("Notes"))
        self.note_edit = QPlainTextEdit()
        self.note_edit.setObjectName("pNote")
        self.note_edit.setPlaceholderText(i18n.t("Add a note"))
        self.note_edit.setFixedHeight(64)
        col.addWidget(self.note_edit)
        self.note_btn = C.button(i18n.t("Add note"), small=True, on_click=self._add_note)
        col.addWidget(self.note_btn, 0, Qt.AlignRight)
        notes = list(getattr(view.account, "notes", None) or ())
        for note in reversed(notes[-_LIST_MAX:]):
            col.addWidget(PN._label(evidence.when(note.get("at", "")), "pKey", wrap=False))
            col.addWidget(PN._label(note.get("text", ""), select=True))
        lay.addWidget(box)
        lay.addStretch(1)

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

    # right: Overview
    def _fill_overview(self, view: CompanyView) -> None:
        lay, c = self._pages["overview"], view.company
        box, col = PN._widget(i18n.t("At a glance"))
        n, saved = len(view.people), sum(1 for p in view.people if p.saved)
        with_mail = sum(1 for p in view.people if PN._text(p.lead.email))
        self.glance = [
            _plural(n, "1 person Prism holds here", "{n} people Prism holds here"),
            i18n.t("{a} saved as contacts · {b} with an e-mail").format(
                a=f"{saved:,}", b=f"{with_mail:,}"),
        ]
        for line in self.glance:
            col.addWidget(PN._label(line))
        if n:
            col.addWidget(PN._link(i18n.t("Find more people at {name}…").format(
                name=c.name or i18n.t("this company")),
                lambda: self.findPeopleRequested.emit(self.view.company)))
        lay.addWidget(box)
        if view.people:
            box, col = PN._widget(i18n.t("People here"))
            self.overview_links: list = []
            for p in view.people[:6]:
                line = QHBoxLayout()
                who = PN._link(p.lead.name or i18n.t("(no name)"),
                               lambda person=p: self.personPicked.emit(person))
                self.overview_links.append(who)
                line.addWidget(who)
                line.addWidget(PN._label(PN._text(p.lead.title), "pMuted", wrap=False), 1)
                line.addWidget(PN._pill(i18n.t("Saved") if p.saved else i18n.t("Net New"),
                                        theme.NEUTRAL[700], theme.NEUTRAL[200]))
                col.addLayout(line)
            if len(view.people) > 6:
                col.addWidget(PN._link(i18n.t("See the People tab"),
                                       lambda: self.set_tab("people")))
            lay.addWidget(box)
        else:
            lay.addWidget(PN._label(i18n.t("Prism holds nobody at this company yet. Use "
                                           "Find people to search for the people there."),
                                    "pMuted"))
        lay.addStretch(1)

    # right: Activities
    def _fill_activities(self) -> None:
        lay = self._pages["activities"]
        bar = QWidget()
        row = C.FlowLayout(bar, margin=0, h_space=4, v_space=4)
        self.activity_btns = {}
        for key, name in PN._ACTIVITY_FILTERS:
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
        for kind, name in PN._LOG_KINDS:
            act = log_menu.addAction(i18n.t(name))
            act.triggered.connect(lambda _=False, k=kind: self._log_form(k))
        self.log_btn.setMenu(log_menu)
        row.addWidget(self.log_btn)
        lay.addWidget(bar)
        self.log_box = QWidget()
        form = QVBoxLayout(self.log_box)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.SPACE_1)
        self.log_title = PN._label("", "pKey", wrap=False)
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
        PN._clear(self.activity_list)
        shown = [a for a in activities(self.view) if PN._matches(a["kind"], self._activity)]
        if not shown:
            self.activity_list.addWidget(PN._label(i18n.t("Nothing here yet."), "pMuted"))
        for a in shown:
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_3)
            line.addWidget(PN._label(evidence.when(a["at"]) or "—", "pKey", wrap=False), 0,
                           Qt.AlignTop)
            line.addWidget(PN._label(a["text"], select=True), 1)
            self.activity_list.addLayout(line)

    def _filter_activities(self, key: str) -> None:
        self._activity = key
        for k, b in self.activity_btns.items():
            b.setChecked(k == key)
        self._draw_activities()

    def _log_form(self, kind: str) -> None:
        self._log_kind = kind
        self.log_title.setText(i18n.t("Log a {kind}").format(
            kind=i18n.t(dict(PN._LOG_KINDS)[kind]).lower()))
        self.log_box.show()
        self.log_text.setFocus(Qt.OtherFocusReason)

    def _log_it(self) -> None:
        if self.view is not None:
            self.logRequested.emit(self.view.company, self._log_kind,
                                   self.log_text.toPlainText().strip())

    # right: People
    def _fill_people(self, view: CompanyView) -> None:
        lay = self._pages["people"]
        if not view.people:
            lay.addWidget(PN._label(i18n.t("Prism holds nobody at this company yet."),
                                    "pMuted"))
            lay.addWidget(PN._link(i18n.t("Find people…"),
                                   lambda: self.findPeopleRequested.emit(self.view.company)))
            lay.addStretch(1)
            return
        lay.addWidget(PN._label(_plural(len(view.people), "1 person Prism holds here",
                                        "{n} people Prism holds here"), "pMuted"))
        self.people_links: list = []
        from addons.leads.pool import EMAIL_STATUS_LABEL, email_status_of
        for p in view.people[:_PEOPLE_MAX]:
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_2)
            who = PN._link(p.lead.name or i18n.t("(no name)"),
                           lambda person=p: self.personPicked.emit(person))
            self.people_links.append(who)
            line.addWidget(who)
            line.addWidget(PN._label(PN._text(p.lead.title), "pMuted", wrap=False), 1)
            key = email_status_of(p.lead, p.draft)
            tone = {"verified": (theme.OK_INK, theme.OK_BG),
                    "invalid": (theme.ERR_INK, theme.ERR_BG)}.get(
                        key, (theme.NEUTRAL[700], theme.NEUTRAL[200]))
            line.addWidget(PN._pill(i18n.t(EMAIL_STATUS_LABEL[key]), tone[0], tone[1]))
            line.addWidget(PN._pill(i18n.t("Saved") if p.saved else i18n.t("Net New"),
                                    theme.NEUTRAL[700], theme.NEUTRAL[200]))
            lay.addLayout(line)
        if len(view.people) > _PEOPLE_MAX:
            lay.addWidget(PN._label(i18n.t("and {n} more — narrow them on the People page")
                                    .format(n=f"{len(view.people) - _PEOPLE_MAX:,}"), "pMuted"))
        lay.addStretch(1)

    # right: Enrichment
    def _fill_enrichment(self, view: CompanyView) -> None:
        """Apollo's Enrichment tab: "displays any account fields that are ready
        to enrich with new data." Prism has one lookup — an Exa search for the
        company — and it fills only what is MISSING, so the tab lists what is
        and says what it costs; it still asks before it spends."""
        lay, c = self._pages["enrichment"], view.company
        lay.addWidget(PN._label(i18n.t("One Exa search fills in what is missing. Fields "
                                       "that already have a value are left as they are."),
                                "pMuted"))
        missing = []
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        for r, (key, label) in enumerate(_LOOKUP_FIELDS):
            value = PN._text(c.website or c.domain if key == "website" else getattr(c, key, ""))
            if not value:
                missing.append(key)
            grid.addWidget(PN._label(i18n.t(label), "pKey", wrap=False), r, 0, Qt.AlignTop)
            grid.addWidget(PN._label(value or i18n.t("Not on record"),
                                     "pVal" if value else "pMuted", select=True), r, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        self.missing_fields = missing
        self.enrich_btn = C.button(i18n.t("Look it up"), on_click=self._enrich)
        self.enrich_btn.setEnabled(bool(missing) and bool(c.name or c.domain))
        lay.addWidget(self.enrich_btn, 0, Qt.AlignLeft)
        last = next((h for h in reversed(getattr(view.account, "history", None) or ())
                     if h.get("kind") == "enriched"), None)
        if last:
            lay.addWidget(PN._label(i18n.t("Last looked up {when}").format(
                when=evidence.when(last.get("at", "")) or i18n.t("recently")), "pMuted"))
        lay.addStretch(1)

    def _enrich(self) -> None:
        if self.view is not None:
            self.enrichRequested.emit(self.view.company)

    # right: All fields
    def _fill_fields(self) -> None:
        lay = self._pages["fields"]
        self.field_search = QLineEdit()
        self.field_search.setPlaceholderText(i18n.t("Search fields"))
        self.field_search.setClearButtonEnabled(True)
        self.field_search.textChanged.connect(lambda _t: self._draw_fields())
        lay.addWidget(self.field_search)
        self.field_grid = QGridLayout()
        self.field_grid.setHorizontalSpacing(theme.SPACE_3)
        self.field_grid.setVerticalSpacing(theme.SPACE_2)
        self.field_grid.setColumnStretch(1, 1)
        lay.addLayout(self.field_grid)
        self._draw_fields()
        lay.addStretch(1)

    def _draw_fields(self) -> None:
        PN._clear(self.field_grid)
        want = self.field_search.text().strip().casefold()
        rows = [(k, v) for k, v in all_fields(self.view)
                if not want or want in k.casefold() or want in v.casefold()]
        self.field_rows = rows
        for r, (key, value) in enumerate(rows):
            self.field_grid.addWidget(PN._label(key, "pKey"), r, 0, Qt.AlignTop)
            self.field_grid.addWidget(PN._label(value or "—", "pVal" if value else "pMuted",
                                                select=True), r, 1)

    # ── acting ────────────────────────────────────────────────────────────────
    def open_url(self, url: str) -> None:
        """Open an http(s) link in the browser. A test seam."""
        safe = evidence.safe_url(url)
        if safe:
            QDesktopServices.openUrl(QUrl(safe))

    def _open_site(self) -> None:
        self.open_url(self._site_url())

    def _open_linkedin(self) -> None:
        if self.view is not None:
            self.open_url(PN.PersonPanel._url(self.view.company.linkedin))

    def _call(self) -> None:
        phone = PN._text(self.view.company.phone) if self.view is not None else ""
        if phone:
            QDesktopServices.openUrl(QUrl("tel:" + "".join(ch for ch in phone
                                                           if ch.isdigit() or ch == "+")))

    def _save(self) -> None:
        if self.view is not None:
            self.saveRequested.emit(self.view.company)

    def _stage_picked(self, _index: int) -> None:
        stage = self.stage.currentData() or ""
        if stage and self.view is not None:
            self.stageRequested.emit(self.view.company, stage)

    def _add_note(self) -> None:
        text = self.note_edit.toPlainText().strip()
        if text and self.view is not None:
            self.noteRequested.emit(self.view.company, text)

    def _add_task(self) -> None:
        text = self.task_text.text().strip()
        if not text or self.view is None:
            return
        due = self.task_due.date().toString(Qt.ISODate) if self.task_due_on.isChecked() else ""
        self.taskRequested.emit(self.view.company, text, due)

    def ask_edit(self, values: dict):
        """Edit company info: a small form over the fields Prism keeps; the
        changed values, or None on Cancel. A test seam."""
        from dialogs.base import PrismDialog
        dlg = PrismDialog(i18n.t("Edit company info"), parent=self)
        form = QGridLayout()
        edits = {}
        for r, key in enumerate(AC.EDITABLE):
            form.addWidget(PN._label(i18n.t(_EDIT_LABELS[key]), "pKey", wrap=False), r, 0)
            edit = QLineEdit(values.get(key, ""))
            form.addWidget(edit, r, 1)
            edits[key] = edit
        dlg.body.addLayout(form)
        dlg.footer.add_secondary(dlg.button(i18n.t("Cancel"), on_click=dlg.reject))
        dlg.footer.set_primary(dlg.button(i18n.t("Save company"), "primary",
                                          on_click=dlg.accept))
        if dlg.exec() != PrismDialog.Accepted:
            return None
        return {k: e.text() for k, e in edits.items() if e.text().strip() != values.get(k, "")}

    def _edit(self) -> None:
        if self.view is None:
            return
        c = self.view.company
        values = {k: PN._text(getattr(c, k, "")) for k in AC.EDITABLE}
        changes = self.ask_edit(values)
        if changes:
            self.editRequested.emit(c, changes)

    def confirm_delete(self, name: str) -> bool:
        """Apollo's warning, in Prism's words. A test seam. Built rather than
        QMessageBox.question(...): `name` comes from an imported sheet or a
        provider, and the static helpers would render markup in it."""
        box = QMessageBox(
            QMessageBox.Icon.Question, i18n.t("Delete account"),
            i18n.t("Delete {name} from your accounts? Its stage, lists, notes, tasks and "
                   "activity go with it. Its people stay in Prism, and the company stays "
                   "on the page as net new.").format(name=name or i18n.t("this company")),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _delete(self) -> None:
        if self.view is not None and self.view.saved \
                and self.confirm_delete(self.view.name):
            self.deleteRequested.emit(self.view.company)

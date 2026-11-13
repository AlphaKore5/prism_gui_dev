"""A walkthrough that points at the real Leads screen.

The help panel (addons/leads/help.py) answers "what is this screen". The
Alphakore team read it and then still asked which control each paragraph was
about — a wall of chips, spin boxes and columns does not name itself. So this
is the other half of the same answer: a coach mark that dims the screen, rings
ONE real control at a time and says in a sentence or two what it does, walking
every filter, tag and action on the surface.

It never touches the thing it points at. The tour reads geometry and nothing
else — no ticking rows, no starting runs, no writing into a field — and three
things keep it honest. The overlay swallows the clicks that land on it instead
of passing them through (a tour that let clicks through would put "Find
e-mails", which spends a credit a row, one stray click away); it keeps the
keyboard focus on its own card, so Tab cannot walk on to a control under the
scrim for Space to press; and a step whose control cannot be found is skipped
rather than conjured up.

The copy lives in STEPS, one module-level tuple of (key, title, body) records,
for the same two reasons help.py keeps SECTIONS: a sentence changes without
touching a widget, and STEPS is a name devtools/extract_strings.py already
scans (COPY_TABLES), so every line reaches the catalogue and can be translated.
Keep the copy free of braces, angle brackets and semicolons — _is_copy() reads
those as stylesheet or markup and drops the string. The keys are snake_case
with no spaces, which is the shape that same function rejects, so they never
reach the catalogue themselves.

The keys are a contract with the SCREEN, not with this file. Anything that can
be pointed at answers

    help_targets() -> {key: QWidget}      or {key: (QWidget, QRect)}
    help_reveal(key) -> None              optional: open the fold, switch the
                                          tab, scroll the rail
    help_snapshot() -> object             optional: what a reveal may move —
    help_restore(snapshot) -> None        the tab, a fold, the rail's scroll —
                                          taken when the walk opens and put
                                          back when it closes

and `Guide` gathers every such part of one screen into the single owner this
overlay talks to. A key nobody answers today is skipped, so a step can name a
control that is folded away, empty, or not built yet, and the walk still
reaches the end.

Reveals unfold, switch and scroll — that is their job — so the snapshot is what
makes the walk leave no trace: the owner who hid the filters, sat on Sessions
and had two facets open gets exactly that back, whether he walks off the end or
presses Esc halfway.
"""
from __future__ import annotations

from PySide6.QtCore import (
    QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractScrollArea, QApplication, QFrame, QHBoxLayout, QVBoxLayout,
    QWidget,
)

import i18n
import theme
from widgets import controls as C

SCRIM = QColor(20, 30, 40, 148)     # dark enough to read the card against a
                                    # white table, light enough to still see
                                    # where the ringed control sits on screen
RING_PAD = 6                        # breathing room between control and ring
RING_R = theme.R_CONTROL + 2        # a hair rounder than the control inside it
GAP = 14                            # ring to card


# The walk, in the order someone reads Apollo's Find People page: the title
# row, the toolbar left to right (Search settings is one step — its rows sit
# in a modal dialog the walk must not open over its own card), then the rail
# top to bottom — the three tabs, the pinned filters, More filters, Find new
# people — then the results: the table, its columns, the pages, the rows you
# tick, what the action bar spends — and last the tabs everything else lives
# under. One record per control. A step is allowed to name a control that is
# not on screen today (the action bar before anything is ticked); it is
# skipped.
STEPS = (
    ("import_menu", "Import",
     "Brings a sheet in — people as contacts, or companies as accounts. "
     "Nothing is searched: the import becomes a filter on the left, and "
     "the page shows what came in."),

    ("views_menu", "Default view",
     "Your saved searches, a starter search to begin from, and Table or "
     "Cards. Picking a search filters the page at once — it never runs one."),

    ("hide_filters", "Hide filters",
     "Folds the whole rail away and gives the width to the table. The "
     "number beside it is how many filters are on, so you can still see "
     "them working with the rail out of sight."),

    ("people_search", "Search people",
     "Narrows the page by name, title, company, e-mail or place. It costs "
     "nothing and starts no search."),

    ("research_menu", "Research with AI",
     "Qualify and draft the people you ticked, or find new people and "
     "qualify them in one run. Both spend your credits — a why-now search, "
     "a score and a draft for each person — and both ask before a big "
     "batch."),

    ("save_as_search", "Save as new search",
     "Keeps this whole set of filters under a name, in Default view and "
     "the Saved searches tab, to use again next week."),

    ("view_toggle", "Table or Cards",
     "The same people in two shapes. Cards show more of each person, the "
     "table fits far more people on one screen."),

    ("sort", "Sort",
     "Reorders everyone the filters let through — by relevance, name, "
     "newest or company — across every page. It never removes anybody."),

    ("search_settings", "Search settings",
     "What Find new people runs with — how many to find, what you sell and "
     "the claims you approve. Every search is charged to your credits, and a "
     "search that finds nobody is not. Find new people tells you the most it "
     "can cost before it asks. Hover any setting for what it does."),

    ("people_tabs", "Total, Net New and Saved",
     "Total is everyone Prism holds who passes the filters. Saved is the "
     "ones you saved as contacts, Net New is everyone else. The numbers "
     "move as you filter."),

    ("filters_head", "The filters",
     "Every filter narrows everyone Prism already holds, the moment you "
     "click it. It is free — nothing is searched until you press Find new "
     "people."),

    ("facet_job_titles", "Job title",
     "The words in the person's own title. Include the titles you sell to, "
     "and exclude the ones that waste a draft, like Intern or Assistant."),

    ("similar_titles", "Include similar titles",
     "On, a title also matches its close cousins — Head of Operations reaches "
     "Operations Manager. Off, only the words you typed count."),

    ("facet_seniority", "Seniority",
     "The level rather than the wording — owner, C-level, VP, director, "
     "manager. An oddly worded title is still judged on its level."),

    ("facet_companies", "Current company",
     "Name the companies you want, or the ones you never want. Excluding your "
     "own customers here stops every search rediscovering them."),

    ("facet_locations", "Location",
     "Where the person is. Include the places you sell into and exclude the "
     "ones you never want — anybody outside the includes is left out."),

    ("facet_industries", "Industry",
     "The company's line of business. A search can only steer by it, so the "
     "people a search found for an industry stay under it — read those as "
     "likely rather than certain."),

    ("facet_contact_imports", "Contact CSV import",
     "Tick an import to see the people it brought in. Each sheet you import "
     "is listed here by its file name."),

    ("facet_account_imports", "Account CSV import",
     "Tick an import to see the people Prism holds at its companies — and "
     "press Find new people to search for more there, one search a company, "
     "every company in one press."),

    ("more_filters", "More filters",
     "Opens every filter at once, grouped and searchable: lists, stage, "
     "function, company size, revenue, your own columns and the rest. Pin the "
     "ones you use to keep them here. A filter that is set always stays."),

    ("facet_lists", "Lists",
     "The lists you put people and companies on. Include a list to work "
     "through it, or exclude one — a company list takes out everyone who "
     "works at those companies."),

    ("facet_stages", "Stage",
     "Where each saved contact, or their company, stands with you: Cold, "
     "Approaching, Interested and the rest. Exclude Do Not Contact before a "
     "send. People you have not saved have no stage."),

    ("facet_functions", "Function",
     "The part of the business the person runs, such as operations or "
     "engineering. Use it where the same title means different jobs at "
     "different companies."),

    ("facet_keywords", "Keywords",
     "Words to look for around the person and the company. A search can "
     "only steer by them, like Industry."),

    ("facet_headcount", "Company headcount",
     "How many people the company employs, in bands. A company whose size "
     "is not on record is let through, not guessed."),

    ("facet_revenue", "Annual revenue",
     "The company's revenue, in bands, for when headcount does not describe "
     "your buyer. Nobody is dropped for a revenue that is simply not "
     "published."),

    ("facet_company_hq", "Company HQ location",
     "Where the business is based, which is not always where the person sits. "
     "Location is the person, this is the company."),

    ("facet_years", "Years in current role",
     "How long they have held this job, in bands. Someone eight months in is "
     "still deciding how things get bought."),

    ("facet_changed_jobs", "Changed jobs in the last 90 days",
     "Keeps only people who started somewhere new this quarter. A new job is "
     "the strongest reason to write this week rather than next quarter."),

    ("facet_email_status", "Email status",
     "Verified, Unverified, Catch-all, Unknown, Invalid, No email or Mailed. "
     "Verified alone is the usual view just before a send."),

    ("facet_scores", "Fit score",
     "The lowest fit to show, and whether to show only the people Prism has "
     "qualified. Nobody is deleted — lower it and they come back."),

    ("facet_custom_fields", "Custom fields",
     "The columns your own sheets brought in that Prism has no field for, "
     "such as Lead Quality or Region. Pick a column, then the values to keep."),

    ("count_badge", "How many filters are on",
     "The number of filters across every facet, including the folded ones. "
     "It is the quickest answer to why the page shows four people."),

    ("clear_all", "Clear all",
     "Empties every filter at once, folded ones included, and the page "
     "shows everyone Prism holds again."),

    ("btn_find", "Find new people",
     "The one button here that spends. It searches with these filters for "
     "people Prism does not hold yet, says what that costs in credits, and "
     "asks first. No e-mail lookups and no drafting — you choose afterwards "
     "who is worth it."),

    ("notice", "The run line",
     "Live progress on the left while something runs, and on the right the "
     "summary of what the last search produced."),

    ("table", "The people",
     "One row per person, however many ways Prism met them. Click a row to "
     "open that person's dossier on the right."),

    ("select_all", "Tick what you want",
     "The box on a row picks that person and the box in the header picks "
     "this page. The arrow beside it picks all of them, or a number — at "
     "most so many from one company. Picks stay when you turn the page."),

    ("col_lead", "Lead",
     "The person's name, with the company they work at under it. The name is "
     "what a draft greets them by."),

    ("col_focus", "Focus",
     "Their job title, with where they sit under it. Two people with the same "
     "title in two countries are not the same lead."),

    ("col_fit", "Fit",
     "A cheap ranking off the title and the company, worked out without "
     "spending anything. It sorts the list. It is not a promise about "
     "anybody."),

    ("col_status", "Status",
     "Deliverability, never interest. Verified is checked and good, "
     "Unverified is a real address no verifier has ruled on yet, Catch-all is "
     "a domain that accepts "
     "anything, Unknown is a check that could not tell, Invalid means do not "
     "send, No email means Prism has not found one, and Mailed means you "
     "already wrote."),

    ("col_signal", "Signal",
     "The why-now Prism found for that person — a hire, a new plant, a "
     "funding round. Not qualified means found but never researched."),

    ("pager", "Pages",
     "Twenty-five people a page, with how many the filters let through. "
     "Sort and filters work on every page, not only this one."),

    ("bulk_bar", "The action bar",
     "It appears the moment you tick a row, and everything on it acts on the "
     "people you picked, on every page, and no one else. Nothing here can "
     "run on the whole list by accident."),

    ("bulk_save", "Save",
     "Saves the ticked people as contacts, so they move from Net New to "
     "Saved. Exporting, e-mailing or sequencing someone saves them too."),

    ("bulk_remove", "Remove",
     "Takes the ticked people off the list. They leave Total, Net New and "
     "Saved, and new searches skip them. Nothing is deleted. The line under "
     "the three tabs counts them and brings any of them back."),

    ("bulk_verify", "Verify",
     "Checks the ticked addresses and reports only what it can prove. A "
     "credit is used for each address a verifier answers for, and none for "
     "one it could not reach."),

    ("bulk_emails", "Find e-mails",
     "Looks up a real address for every ticked person and checks it. Credits "
     "are used for every row you ticked and not a sample of them, and an "
     "address is only charged when a finder knows the person. Nothing is "
     "guessed."),

    ("bulk_phones", "Find phones",
     "Looks up the number each ticked person's company publishes on its own "
     "website or a business directory: one lookup per company, and a credit "
     "only for a number found. It is the company's number, not a direct dial, "
     "and Prism has not called it."),

    ("bulk_list", "Add to list",
     "Writes the ticked people to a sheet on your own machine, which then "
     "appears under the Lists tab."),

    ("bulk_export", "Export",
     "The same ticked people as a file to hand to somebody else. It sends "
     "nothing and spends nothing."),

    ("bulk_stage", "Set stage",
     "Moves the ticked people to a stage: Cold, Approaching, Interested and "
     "the rest. Anyone not saved yet is saved first. Sending someone a "
     "message moves Cold to Approaching on its own."),

    ("bulk_qualify", "Qualify and draft",
     "Researches each ticked person and writes them an opener. A why-now "
     "search, a score and a draft each, all charged to your credits, so "
     "spend them on the people you actually want."),

    ("bulk_sequence", "Add to sequence",
     "Puts the ticked people into the follow-up steps that run after the "
     "first message. Nothing leaves until you send it."),

    ("drawer", "The person",
     "Everything Prism holds on one person, the way Apollo lays a contact "
     "out: their details, stage, tasks, company and notes on the left, then "
     "why they fit, their activity, the e-mail drafted for them and every "
     "field. Any row opens it. Acting here saves them first."),

    ("tab_people", "People",
     "This screen. Everyone Prism holds — imported, saved or found by a "
     "search — filtered as you click."),

    ("tab_companies", "Companies",
     "Every company Prism knows — the ones you saved, and the employers of "
     "everyone it holds — filtered as you click. Save a company to make it an "
     "account, then open it for its stage, notes, tasks and the people there."),

    ("tab_sessions", "Sessions",
     "Every search you have run, with its filters and its results. Open one "
     "to see only its people."),

    ("tab_lists", "Lists",
     "The sheets written to disk. Real files on your machine that you can "
     "send to anyone."),

    ("tab_saved", "Saved searches",
     "The filter sets you saved under a name, ready to use again on a week "
     "when nobody wants to rebuild them."),

    ("tab_sequences", "Sequences",
     "The follow-up steps a lead walks through after the first message."),

    ("tab_analytics", "Analytics",
     "What the last search actually produced — found, verified, drafted, "
     "sent — counted for that run."),

    ("tab_deals", "Deals",
     "The pipeline, one column per stage, with each deal's value and next "
     "step. A deal that has not moved for a week is flagged. Won asks for the "
     "value and Lost asks why."),

    ("tab_due", "Due today",
     "The screen to open each morning: tasks that fall due, people who "
     "replied and are waiting on you, and contacts who have gone quiet. "
     "Nothing on it sends by itself."),

    ("tab_stats", "Stats",
     "Reply rate, time to reply, pipeline and win rate for the last 30 days, "
     "with the funnel and why deals were lost. Every number is counted from "
     "what Prism stored."),
)


# ── geometry (pure, so the awkward cases are tested without a screen) ────────
def _clamp(value: int, low: int, high: int) -> int:
    if high < low:              # the card is bigger than the room it has
        return low
    return max(low, min(value, high))


def _centred(middle: int, size: int, low: int, high: int) -> int:
    return _clamp(middle - size // 2, low, high - size)


def ring_rect(target: QRect, bounds: QRect, pad: int = RING_PAD) -> QRect:
    """The outline drawn around one target, clipped to what is on screen.

    Clipped rather than dropped: a rail control scrolled half out of view is
    still the thing being talked about, and half a ring says so honestly.
    """
    return target.adjusted(-pad, -pad, pad, pad).intersected(bounds)


def place_card(target: QRect, card: QSize, bounds: QRect, gap: int = GAP) -> QRect:
    """Where the card goes for this target — beside it if there is room, and
    always inside `bounds`.

    Beside first, and only then below or above: the rail is a column, so a card
    dropped under a facet covers the facets the next two steps are about, while
    a card beside it covers the table, which is not being discussed yet.

    And when no side has room — the whole table, which fills the results — the
    card goes INSIDE the ring, in its bottom-right corner. Clamped to the top
    instead, it sat over the ring's own edge and the column headings the next
    five steps are about; a target that big can spare a corner of its body.
    """
    w, h = card.width(), card.height()
    right = target.right() + 1 + gap
    left = target.left() - gap - w
    below = target.bottom() + 1 + gap
    above = target.top() - gap - h
    if right + w <= bounds.right() + 1:
        x, y = right, _centred(target.center().y(), h, bounds.top(),
                               bounds.bottom() + 1)
    elif left >= bounds.left():
        x, y = left, _centred(target.center().y(), h, bounds.top(),
                              bounds.bottom() + 1)
    elif below + h <= bounds.bottom() + 1:
        x, y = _centred(target.center().x(), w, bounds.left(),
                        bounds.right() + 1), below
    elif above >= bounds.top():
        x, y = _centred(target.center().x(), w, bounds.left(),
                        bounds.right() + 1), above
    elif target.width() >= w + 2 * gap and target.height() >= h + 2 * gap:
        x, y = target.right() + 1 - gap - w, target.bottom() + 1 - gap - h
    else:
        x, y = _centred(target.center().x(), w, bounds.left(),
                        bounds.right() + 1), above
    # The last word, for the cases the four branches cannot satisfy at all — a
    # target hard against the bottom edge, or a window shorter than the card.
    x = _clamp(x, bounds.left(), bounds.right() + 1 - w)
    y = _clamp(y, bounds.top(), bounds.bottom() + 1 - h)
    return QRect(x, y, w, h)


def _drawn(widget: QWidget) -> bool:
    """Would this widget be drawn if its window were on screen?

    isVisible() is the wrong question, and so is asking the window: a screen
    being built is not on screen yet, and no test ever shows one. What matters
    is that nothing BELOW the window has been hidden on purpose — a folded
    facet, a bulk bar with nothing ticked, the tab that is not current.
    """
    node = widget
    while node is not None and not node.isWindow():
        if node.isHidden():
            return False
        node = node.parentWidget()
    return True


# ── the parts of a screen that can be pointed at ────────────────────────────
def parts_of(root: QWidget) -> list:
    """Every widget in (and including) `root` that answers help_targets().

    Walked rather than named. On the Leads screen the targets live in three
    places — the workbench rail, the filter panel inside it and the cockpit —
    and two of those hang off private attributes of the third. A walk finds
    them without this module knowing any of that, and finds the next part to
    grow targets without an edit here.
    """
    if root is None:
        return []
    found = [root] if hasattr(root, "help_targets") else []
    found += [w for w in root.findChildren(QWidget) if hasattr(w, "help_targets")]
    return found


class Guide:
    """One screen's parts as the single owner the overlay talks to."""

    def __init__(self, root: QWidget):
        self._root = root
        self._parts = None

    def parts(self) -> list:
        if self._parts is None:
            self._parts = parts_of(self._root)
        return self._parts

    def help_refresh(self) -> None:
        """Forget the walk. The workbench is built lazily, so the parts found
        before a screen was opened are not the parts it has afterwards."""
        self._parts = None

    def help_targets(self) -> dict:
        merged = {}
        for part in self.parts():
            try:
                found = part.help_targets() or {}
            except Exception:                               # noqa: BLE001
                # A part that cannot answer — or has been deleted since the
                # walk — costs its own keys, never the whole tour.
                continue
            for key, target in found.items():
                # Nearest the root wins: the workspace owns the tab a key is
                # on, whatever the cockpit inside it calls the same name.
                merged.setdefault(key, target)
        return merged

    def help_reveal(self, key: str) -> None:
        """Ask every part, not only the one that owns the key.

        A part that does not know a key ignores it, and the two that might both
        answer (the workspace forwards to the cockpit) do the same idempotent
        thing — switch a tab, open a fold. Asking all of them keeps this
        indifferent to which part ends up owning which key.
        """
        for part in self.parts():
            reveal = getattr(part, "help_reveal", None)
            if reveal is None:
                continue
            try:
                reveal(key)
            except Exception:                               # noqa: BLE001
                continue

    def help_snapshot(self) -> list:
        """Every part's own record of what a reveal may move, kept with the
        part it came from — so a part built later, or gone since, restores
        nothing it never recorded."""
        taken = []
        for part in self.parts():
            snap = getattr(part, "help_snapshot", None)
            if snap is None:
                continue
            try:
                taken.append((part, snap()))
            except Exception:                               # noqa: BLE001
                continue
        return taken

    def help_restore(self, taken) -> None:
        """Put every part back, innermost first.

        The walk finds a part before the parts inside it, so backwards is inside
        out: the facets fold shut and the cockpit's rail and scroll come back
        before the tab strip that holds them switches — the tab lands last, on
        a screen that is already the one the owner left.
        """
        for part, snap in reversed(list(taken or ())):
            restore = getattr(part, "help_restore", None)
            if restore is None:
                continue
            try:
                restore(snap)
            except Exception:                               # noqa: BLE001
                # A part deleted since the snapshot (Qt has freed it) costs its
                # own state, never the rest of the screen's.
                continue


class Tour(QWidget):
    """The coach-mark overlay. Parent it to the region it should cover, then
    `start()`.

    A child widget, never a window, and it paints nothing inside the ring — so
    the parent's own pixels show through the hole and a test can walk the whole
    thing without anything reaching a screen.
    """

    CARD_W = 330                # ~46 characters a line at SUPPORT, and still
                                # a quarter of the 1296pt body at 1536x830
    _SETTLE_MS = 280            # longer than the longest slide on this screen

    finished = Signal()         # ended, either way — the opener takes its
                                # focus back

    def __init__(self, owner, parent=None, steps=None):
        super().__init__(parent)
        self._owner = owner
        self.steps = tuple(STEPS if steps is None else steps)
        # The indices actually SHOWN, in order. Not a plain counter: steps are
        # skipped, so this is the only thing that can count the cards honestly
        # and still walk back through exactly the ones that were seen.
        self._trail = []
        self._ring = QRect()
        self._clip = QRect()        # what the current target's scroll areas show
        self._snapshot = None       # the screen as the walk found it
        self._watching_focus = False
        self.setObjectName("leadsTour")
        # No background of its own: the scrim is painted, the hole is not, and
        # the control underneath shows through it.
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._remeasure)
        self._build_card()
        self.hide()

    # ── the card ─────────────────────────────────────────────────────────────
    def _build_card(self):
        self._card = QFrame(self)
        self._card.setObjectName("tourCard")
        self._card.setAttribute(Qt.WA_StyledBackground, True)
        self._card.setStyleSheet(
            f"QFrame#tourCard{{background:{theme.CARD};"
            f"border:1px solid {theme.DIVIDER};"
            f"border-radius:{theme.R_CARD}px;}}")
        # The card takes the focus, and the keys are handled by the overlay
        # around it (Qt hands an unwanted key up the parent chain). Its buttons
        # take no focus at all, so Space and Enter mean "next step" and never
        # "press whatever the Tab key last landed on".
        self._card.setFocusPolicy(Qt.StrongFocus)
        self._card.setFixedWidth(self.CARD_W)

        col = QVBoxLayout(self._card)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4,
                               theme.SPACE_4, theme.SPACE_4)
        col.setSpacing(theme.SPACE_2)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_2)
        self._title = C.label("", level="CARD_TITLE", wrap=True)
        head.addWidget(self._title, 1)
        self._leave_btn = C.icon_button("x", i18n.t("Leave the walkthrough"),
                                        on_click=self.leave)
        self._leave_btn.setFocusPolicy(Qt.NoFocus)
        head.addWidget(self._leave_btn, alignment=Qt.AlignTop)
        col.addLayout(head)

        self._body = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self._body)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, theme.SPACE_1, 0, 0)
        foot.setSpacing(theme.SPACE_2)
        self._count = C.label("", level="META")
        foot.addWidget(self._count)
        foot.addStretch(1)
        self._back_btn = C.button(i18n.t("Back"), "secondary", small=True,
                                  on_click=self.back)
        self._next_btn = C.button(i18n.t("Next"), "primary",
                                  icon_name="chevron-right",
                                  on_click=self.next_step)
        for button in (self._back_btn, self._next_btn):
            button.setFocusPolicy(Qt.NoFocus)
            foot.addWidget(button)
        col.addLayout(foot)

    # ── walking ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Open at the first step with something to point at. Safe to call on
        a tour that is already up: it restarts, it does not stack."""
        refresh = getattr(self._owner, "help_refresh", None)
        if callable(refresh):
            refresh()
        if not self.is_open():
            # Only when opening. A restart mid-walk keeps the screen as it was
            # BEFORE the walk, not as the last reveal left it.
            self._snapshot = self._take_snapshot()
        self._trail = []
        self.place()
        self.setVisible(True)
        self.raise_()
        self._card.setFocus(Qt.OtherFocusReason)
        self._watch_focus(True)
        self._enter(0, 1)

    def next_step(self) -> None:
        self._enter((self._trail[-1] + 1) if self._trail else 0, 1)

    def back(self) -> None:
        """Back to the previous card that was actually shown. A step that has
        gone away since (a bulk bar whose ticks were cleared) is stepped over
        the same way it would be going forwards."""
        seen = self._trail[:-1]
        while seen:
            index = seen[-1]
            key = self.steps[index][0]
            self._reveal(key)
            measured = self._measure(key)
            if measured is not None:
                self._trail = seen
                self._show_step(index, measured)
                return
            seen = seen[:-1]
        # Nothing behind us any more: the card that is up stays up.

    def leave(self) -> None:
        """Esc, the x, or the panel closing the tour. The screen goes back to
        how the walk found it, the same as walking off the end: a reader who
        quits on the Saved searches step did not ask to be left there."""
        self._shut()

    def _finish(self) -> None:
        """Walked off the end — the screen goes back to how it was found.

        An owner that cannot say how it was (no help_snapshot) is at least put
        back on the People tab: the last six steps are the tabs, and finishing
        a tour on the Analytics tab looks like the tour broke something."""
        if self._snapshot is None:
            self._reveal("tab_people")
        self._shut()

    def _shut(self) -> None:
        if self.isHidden():
            return
        self._settle.stop()
        self._watch_focus(False)
        self._ring = QRect()
        self.setVisible(False)
        self._restore_snapshot()
        self.finished.emit()

    # ── leaving no trace ─────────────────────────────────────────────────────
    def _take_snapshot(self):
        snap = getattr(self._owner, "help_snapshot", None)
        if snap is None:
            return None
        try:
            return snap()
        except Exception:                                   # noqa: BLE001
            return None

    def _restore_snapshot(self) -> None:
        """Twice, with a layout pass between, for the reason _reveal asks
        twice: the facets folding shut change how far the rail CAN scroll, and
        a scroll put back before that layout is clamped to the old range.
        help_restore sets only what differs, so the second pass costs nothing
        where the first one already landed."""
        taken, self._snapshot = self._snapshot, None
        restore = getattr(self._owner, "help_restore", None)
        if taken is None or restore is None:
            return
        for _ in range(2):
            try:
                restore(taken)
            except Exception:                               # noqa: BLE001
                return
            self._relayout()

    # ── the focus stays on the card ──────────────────────────────────────────
    def focusNextPrevChild(self, next_):
        """Tab and Shift+Tab, handed up here from the card, go nowhere.

        Qt's focus chain runs straight on from the card to the controls under
        the scrim — the tabs, the refine boxes, the table — and from there Space
        ticks a box the reader cannot see, while Esc and the arrows stop
        reaching this overlay at all."""
        if self.is_open():
            return True
        return super().focusNextPrevChild(next_)

    def _watch_focus(self, on: bool) -> None:
        app = QApplication.instance()
        if app is None or on == self._watching_focus:
            return
        if on:
            app.focusChanged.connect(self._hold_focus)
        else:
            try:
                app.focusChanged.disconnect(self._hold_focus)
            except (RuntimeError, TypeError):
                pass
        self._watching_focus = on

    def _hold_focus(self, _old, now) -> None:
        """The backstop for every other way in — a mnemonic, a widget under the
        scrim that focuses itself. Focus landing BELOW the overlay is taken back
        to the card; focus on something stacked above it (the help panel, opened
        over the walk with F1) or outside the region it covers is left alone."""
        if not self.is_open() or now is None or not self._below(now):
            return
        self._card.setFocus(Qt.OtherFocusReason)

    def _below(self, widget) -> bool:
        """Whether `widget` sits under this overlay: inside the parent it covers,
        in a sibling stacked beneath it (children paint in list order)."""
        parent = self.parentWidget()
        if parent is None or widget is self or self.isAncestorOf(widget):
            return False
        node = widget
        while node is not None and node.parentWidget() is not parent:
            node = node.parentWidget()
        if node is None:
            return False                    # not in the region we cover
        siblings = [c for c in parent.children() if isinstance(c, QWidget)]
        try:
            return siblings.index(node) < siblings.index(self)
        except ValueError:
            return False

    def _enter(self, index: int, direction: int) -> bool:
        """Show the first step from `index` onwards that resolves to something.

        help_reveal comes BEFORE the measurement, always: the facet has to be
        open and the tab has to be current before there is a rectangle worth
        asking for.
        """
        i = index
        while 0 <= i < len(self.steps):
            key = self.steps[i][0]
            self._reveal(key)
            measured = self._measure(key)
            if measured is not None:
                self._trail.append(i)
                self._show_step(i, measured)
                return True
            i += direction
        if direction > 0:
            self._finish()
        return False

    def _show_step(self, index: int, measured: tuple) -> None:
        _, title, body = self.steps[index]
        self._title.setText(i18n.t(title))
        self._body.setText(i18n.t(body))
        self._count.setText(i18n.t("{n} of {total}").format(
            n=len(self._trail), total=len(self.steps)))
        last = index >= len(self.steps) - 1
        self._next_btn.setText(i18n.t("Done") if last else i18n.t("Next"))
        self._back_btn.setEnabled(len(self._trail) > 1)
        self._lay_out(*measured)
        # Some reveals ANIMATE. The dossier drawer slides in from the right
        # edge, so measured on the tick it opens, the ring lands on the 16px
        # sliver it starts as. A layout pass cannot help — an animation needs
        # frames — so measure once more when the slide is over. The timer is a
        # child of this overlay, so it dies with it rather than firing into a
        # widget Qt has already deleted.
        self._settle.start(self._SETTLE_MS)

    def _remeasure(self) -> None:
        """Where the target ended up, a slide later. Silent if the reader has
        moved on, or left."""
        if not self.is_open() or not self._trail:
            return
        measured = self._measure(self.key())
        if measured is not None and ring_rect(*measured) != self._ring:
            self._lay_out(*measured)

    def _lay_out(self, target: QRect, clip: QRect = None) -> None:
        # The ring is clipped to what the target's scroll areas show, not only
        # to the overlay; the card still has the whole overlay to sit in.
        self._ring = ring_rect(target, self.rect() if clip is None else clip)
        height = self._card.heightForWidth(self.CARD_W)
        if height <= 0:
            height = self._card.sizeHint().height()
        self._card.setGeometry(place_card(self._ring,
                                          QSize(self.CARD_W, height),
                                          self.rect()))
        self._card.raise_()
        self.update()

    # ── the screen underneath ────────────────────────────────────────────────
    def _targets(self) -> dict:
        try:
            return self._owner.help_targets() or {}
        except Exception:                                   # noqa: BLE001
            return {}

    def _relayout(self) -> None:
        """Let the layouts catch up with what a reveal just opened — now, and
        without an event loop.

        Not processEvents(): this runs inside a click handler and letting every
        queued event in would re-enter it. Only the layout requests are
        delivered, which is the one thing the next measurement depends on.
        """
        QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
        window = self.window()
        layout = window.layout() if window is not None else None
        if layout is not None:
            layout.activate()

    def _reveal(self, key: str) -> None:
        """Open the fold, switch the tab, scroll the rail — twice, with a
        layout pass between the two.

        Once is not enough, and the render showed it: a fold unhidden by the
        first half of help_reveal has not been laid out when its second half
        scrolls to it, so the scroll aims at the geometry the rail had a moment
        ago and the step lands on empty space. help_reveal is idempotent by
        contract — it opens what is shut and leaves alone what is already open
        — so asking again, once the geometry is real, costs nothing.
        """
        reveal = getattr(self._owner, "help_reveal", None)
        if reveal is None:
            return
        for _ in range(2):
            try:
                reveal(key)
            except Exception:                               # noqa: BLE001
                return  # a screen that cannot open its own fold is a screen
                        # with one step fewer, not a broken tour
            self._relayout()

    def _target_rect(self, key: str):
        """This step's target in our own coordinates, or None to skip it."""
        measured = self._measure(key)
        return None if measured is None else measured[0]

    def _measure(self, key: str):
        """(target, clip) in our own coordinates, or None to skip the step.

        `clip` is the part of the overlay the target can actually be seen in:
        the overlay itself, cut down by every scroll area the target is scrolled
        inside. Without it a rail control half past the rail's bottom edge was
        ringed in full — the ring ran down over the page margin, round boxes the
        reader could not see.
        """
        entry = self._targets().get(key)
        if entry is None:
            return None
        # A key answers with the widget, or with (widget, QRect) when the thing
        # being pointed at is part of one — a header section, a table cell.
        if isinstance(entry, (tuple, list)) and len(entry) == 2:
            widget, sub = entry
        else:
            widget, sub = entry, None
        if not isinstance(widget, QWidget) or not _drawn(widget):
            return None
        area = QRect(QPoint(0, 0), widget.size()) if sub is None else QRect(sub)
        if area.isEmpty():
            return None
        # Through global coordinates on purpose: the target is somewhere under
        # a splitter, a scroll area and a stack, and mapTo() only speaks to an
        # ancestor of the widget — which this overlay is not.
        clip = self.rect().intersected(self._viewports_of(widget))
        here = QRect(self.mapFromGlobal(widget.mapToGlobal(area.topLeft())),
                     area.size()).intersected(clip)
        return (here, clip) if not here.isEmpty() else None

    def _viewports_of(self, widget: QWidget) -> QRect:
        """The overlap of every scroll-area viewport `widget` is scrolled in,
        in our coordinates — the overlay's own rect where there is none.

        Only a viewport clips. A table's header is a child of the table but not
        of its viewport, and cut to the viewport it would vanish, taking every
        column step with it."""
        seen = QRect(self.rect())
        node = widget
        while node is not None and not node.isWindow():
            parent = node.parentWidget()
            if (isinstance(parent, QAbstractScrollArea)
                    and node is parent.viewport()):
                shown = QRect(self.mapFromGlobal(node.mapToGlobal(QPoint(0, 0))),
                              node.size())
                seen = seen.intersected(shown)
            node = parent
        return seen

    # ── geometry, painting, input ────────────────────────────────────────────
    def place(self) -> None:
        """Cover the whole of whatever this overlay was parented to."""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def is_open(self) -> bool:
        return not self.isHidden()

    def index(self) -> int:
        """The STEPS index on screen, or -1."""
        return self._trail[-1] if self._trail else -1

    def key(self) -> str:
        return self.steps[self._trail[-1]][0] if self._trail else ""

    def position(self) -> int:
        """How many cards have been shown, this being the last of them."""
        return len(self._trail)

    def ring(self) -> QRect:
        return QRect(self._ring)

    def card(self) -> QWidget:
        return self._card

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._trail and self.is_open():
            # The window changed shape under us, so the control has moved. Re-
            # measured without revealing again: nothing folded shut on a resize.
            measured = self._measure(self.key())
            if measured is not None:
                self._lay_out(*measured)

    def paintEvent(self, event):
        if self._ring.isNull() or self._ring.isEmpty():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # One subtracted path rather than four bands around the hole: the bands
        # would leave the ring's four rounded corners unscrimmed.
        whole = QPainterPath()
        whole.addRect(QRectF(self.rect()))
        hole = QPainterPath()
        hole.addRoundedRect(QRectF(self._ring), RING_R, RING_R)
        painter.fillPath(whole.subtracted(hole), SCRIM)
        halo = QColor(theme.ACCENT)
        halo.setAlpha(90)
        painter.setBrush(Qt.NoBrush)
        # A soft outer ring under the crisp one, so the outline still reads
        # where it crosses a white table cell.
        painter.setPen(QPen(halo, 6))
        painter.drawRoundedRect(QRectF(self._ring).adjusted(-1.5, -1.5, 1.5, 1.5),
                                RING_R + 2, RING_R + 2)
        painter.setPen(QPen(QColor(theme.ACCENT), 2))
        painter.drawRoundedRect(QRectF(self._ring).adjusted(1, 1, -1, -1),
                                RING_R, RING_R)

    # Every mouse event that lands on the overlay stops here. Not passed
    # through: the ring is often around a button that spends money, and the
    # first thing anyone does with a coach mark is click the thing it points
    # at. The card's own buttons are children and get their clicks normally.
    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        # Scrolling the rail under the scrim would leave the ring pointing at
        # empty space, since nothing re-measures until the next step.
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self.leave()
        elif key in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space,
                     Qt.Key_Down, Qt.Key_PageDown):
            self.next_step()
        elif key in (Qt.Key_Left, Qt.Key_Backspace, Qt.Key_Up, Qt.Key_PageUp):
            self.back()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

"""The Leads & Outreach workspace — Apollo's Find People (addons.leads.cockpit,
addons.leads.workbench).

Widget behaviour first — no pipeline, no workers, no network: the page shows
exactly the rows it is handed, the Total / Net New / Saved tabs and the pager
say what they show and ask for what the owner picks, ticking rows arms the
action bar and the *Requested signals carry exactly the ticked leads, and the
deliverability status is read correctly per lead. Then the surrounding
`LeadsWorkspace`: its six tabs, that it re-exposes the cockpit's signals, that
Analytics counts the run, and that Lists scans a real folder. Last, the
workbench around it: the People page over everyone Prism holds (the pool —
instant, free), Import as its own action that never searches, an account
import searched fifty companies at a time from where it stopped, what a Find
new people search hands its worker after asking what it may spend, and saved
searches — save, use, delete, and a run counted.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QShowEvent              # noqa: E402
from PySide6.QtTest import QTest                               # noqa: E402
from PySide6.QtWidgets import (                                # noqa: E402
    QAbstractItemView, QApplication, QHeaderView, QWidget,
)

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector.models import Dossier, Lead                    # noqa: E402
from addons.leads import cockpit as CK                         # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _dos(name, fit, email="", check="", signal="none", company="Acme"):
    lead = Lead(name=name, title="Founder", company=company, email=email,
                fit_score=fit, fit_reason="matches automation")
    lead.extra = {"email_check": check} if check else {}
    return Dossier(lead=lead, verdict="warm", score=int(fit),
                   signal_status=signal, opener=f"Hi {name}")


class StatusReading(unittest.TestCase):
    def test_every_status_maps(self):
        self.assertEqual(CK.status_of(_dos("A", 90, "a@x.com", "valid")), "Verified")
        # No verifier has ruled on it: "Unverified" (it read "Guessed" until
        # 24-Sep-2026, when Prism stopped guessing addresses at all).
        self.assertEqual(CK.status_of(_dos("B", 80, "b@x.com", "")), "Unverified")
        self.assertEqual(CK.status_of(_dos("C", 70, "c@x.com", "catch-all")), "Catch-all")
        self.assertEqual(CK.status_of(_dos("D", 60, "d@x.com", "invalid")), "Invalid")
        self.assertEqual(CK.status_of(_dos("E", 50, "")), "No email")

    def test_a_sent_draft_reads_mailed(self):
        d = _dos("F", 70, "f@x.com", "valid")
        draft = type("Dr", (), {"dossier": d, "status": "sent", "body": "hi"})()
        self.assertEqual(CK.status_of(d, draft), "Mailed")


class CockpitBehaviour(unittest.TestCase):
    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])

    def _find(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    def test_all_leads_shown(self):
        self.assertEqual(self.c._table.rowCount(), 4)
        # One run shown straight from its dossiers has no pages to turn.
        self.assertTrue(self.c._pager.isHidden())

    def test_the_people_tabs_show_their_counts_and_say_which_was_picked(self):
        c = self.c
        c.set_counts({"total": 1234, "net_new": 1200, "saved": 34})
        self.assertEqual(c._tab_btns["total"].text(), "Total\n1,234")
        self.assertEqual(c._tab_btns["net_new"].text(), "Net New\n1,200")
        self.assertEqual(c._tab_btns["saved"].text(), "Saved\n34")
        self.assertTrue(c._tab_btns["total"].isChecked())
        got = []
        c.tabChanged.connect(got.append)
        c._tab_btns["saved"].click()
        self.assertEqual((got, c.tab()), (["saved"], "saved"))
        self.assertTrue(c._tab_btns["saved"].isChecked())
        self.assertFalse(c._tab_btns["total"].isChecked())
        c.set_tab("total")                            # the workbench, restoring
        self.assertEqual(got, ["saved"])              # …without asking again
        self.assertTrue(c._tab_btns["total"].isChecked())

    def test_a_pooled_page_shows_exactly_its_rows_in_their_order(self):
        """The workbench sorts and pages the pool; the table must not re-sort
        what it is handed (a Name sort would otherwise be undone by Fit)."""
        from addons.leads import pool as P
        people = [P.Person(lead=d.lead) for d in (self.d4, self.d1, self.d3)]
        self.c.set_people(people, {"rows": people, "page": 1, "pages": 2,
                                   "start": 26, "end": 28, "total": 28},
                          {"total": 28, "net_new": 28, "saved": 0})
        self.assertEqual([self.c._dossier_at(r).lead.name for r in range(3)],
                         ["Bad", "Kunyi", "NoMail"])
        self.assertEqual(self.c._range_lbl.text(), "26 - 28 of 28")
        self.assertFalse(self.c._pager.isHidden())
        self.assertTrue(self.c._prev_btn.isEnabled())
        self.assertFalse(self.c._next_btn.isEnabled())
        # A person never qualified is a placeholder row, not a dossier.
        self.assertTrue(all(self.c._dossier_at(r).status == CK.UNQUALIFIED
                            for r in range(3)))
        self.assertIs(self.c.person_for(self.c._dossier_at(0)), people[0])

    def test_the_pager_asks_for_the_page_it_wants(self):
        from addons.leads import pool as P
        people = [P.Person(lead=d.lead) for d in (self.d1, self.d2)]
        asked = []
        self.c.pageRequested.connect(asked.append)
        self.c.set_people(people, {"rows": people, "page": 1, "pages": 3,
                                   "start": 26, "end": 27, "total": 52})
        self.c._next_btn.click()
        self.c._prev_btn.click()
        self.c._page_box.activated.emit(2)
        self.assertEqual(asked, [2, 0, 2])
        self.assertEqual(self.c._page_box.count(), 3)

    def test_search_people_asks_the_workbench_once_the_typing_stops(self):
        asked = []
        self.c.queryChanged.connect(asked.append)
        self.c._search.setText("  dubai ")
        self.assertEqual(asked, [])                   # debounced, not per key
        self.assertTrue(self.c._search_timer.isActive())
        self.c._search_timer.timeout.emit()           # the debounce, run now
        self.assertEqual(asked, ["dubai"])

    def test_a_new_page_starts_with_nothing_ticked(self):
        r = self._find(self.d4)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.assertEqual(self.c.selected(), [self.d4])
        self.c.set_dossiers([self.d1, self.d2])      # the next page, a new filter
        self.assertEqual(self.c.selected(), [])
        self.assertTrue(self.c._bulk.isHidden())

    def test_check_arms_bulk_and_selects(self):
        self.assertFalse(self.c._b_seq.isEnabled())
        r = self._find(self.d1)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.assertTrue(self.c._b_seq.isEnabled())
        self.assertIn("1 selected", self.c._sel_lbl.text())
        self.assertEqual(self.c.selected(), [self.d1])

    def test_sequence_signal_carries_checked(self):
        got = []
        self.c.sequenceRequested.connect(got.append)
        r = self._find(self.d2)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.c._b_seq.click()
        self.assertEqual(got, [[self.d2]])

    def test_save_makes_the_ticked_people_contacts(self):
        got = []
        self.c.saveContactsRequested.connect(got.append)
        self.assertFalse(self.c._b_contact.isEnabled())
        self.c._table.item(self._find(self.d3), 0).setCheckState(Qt.Checked)
        self.assertTrue(self.c._b_contact.isEnabled())
        self.c._b_contact.click()
        self.assertEqual(got, [[self.d3]])

    def test_import_asks_for_the_kind_it_was_given(self):
        got = []
        self.c.importRequested.connect(got.append)
        for action in self.c._import_btn.menu().actions():
            action.trigger()
        self.assertEqual(got, ["contacts", "accounts"])

    def test_research_with_ai_arms_its_items_as_their_buttons_are(self):
        """A pick that silently did nothing was 22-Sep's "Nothing changes at
        all": each item is armed when the menu opens, with the reason on it
        when it is not."""
        c = CK.LeadsCockpit()
        raw = Lead(name="Sourced", title="Head", company="Acme", fit_score=50)
        c.set_dossiers([self.d1], all_leads=[self.d1.lead, raw])
        c._research_btn.menu().aboutToShow.emit()
        self.assertFalse(c._act_qualify.isEnabled())         # nothing ticked
        self.assertIn("Tick people", c._act_qualify.toolTip())
        row = next(r for r in range(2) if c._dossier_at(r).lead is raw)
        c._table.item(row, 0).setCheckState(Qt.Checked)
        c._research_btn.menu().aboutToShow.emit()
        self.assertTrue(c._act_qualify.isEnabled())
        c.set_find_prepare_ready(lambda: (False, "Add a job title first."))
        c._research_btn.menu().aboutToShow.emit()
        self.assertFalse(c._act_find_prepare.isEnabled())
        self.assertEqual(c._act_find_prepare.toolTip(), "Add a job title first.")

    def test_default_view_lists_saved_searches_and_the_starters(self):
        picked, started = [], []
        self.c.savedSearchPicked.connect(picked.append)
        self.c.starterPicked.connect(started.append)
        self.c.set_saved_searches([{"id": "s1", "name": "Plants"}])
        self.c.set_starters([("icp", "Automation leaders")])
        actions = {a.text(): a for a in self.c._views_menu.actions() if a.text()}
        actions["Plants"].trigger()
        actions["Automation leaders"].trigger()
        self.assertEqual((picked, started), (["s1"], ["icp"]))
        actions["List"].trigger()                   # the layouts live here too (the row list was the "Cards" view)
        self.assertEqual(self.c._view, "cards")

    def test_drawer_renders_on_select(self):
        r = self._find(self.d1)
        self.c._table.setCurrentCell(r, 1)
        # The person panel opens on them (Apollo's contact profile), and the
        # qualification they earned leads its Prospect tab — more than the
        # stretch. (Was: the old drawer's layout held over 3 cards; its Fit and
        # Deliverability now sit in the panel's Record details and Contact
        # information, so the count moved with them.)
        from PySide6.QtWidgets import QLabel
        panel = self.c.person_panel
        self.assertEqual(panel.name.text(), "Kunyi")
        texts = [w.text() for w in self.c._drawer_w.findChildren(QLabel)]
        self.assertIn("WARM · 96 / 100", texts)
        self.assertIn("k@x.com", texts)
        self.assertGreater(self.c._drawer_lay.count(), 1)


class LayoutStates(unittest.TestCase):
    """The shapes that stop the screen crushing on a short window: an empty
    state instead of an empty grid, a drawer that only opens for a picked lead
    (and closes on ✕), and a rail slot the workbench mounts its search into."""

    def test_empty_cockpit_shows_the_empty_state_not_a_grid(self):
        c = CK.LeadsCockpit()
        self.assertEqual(c._view_stack.currentIndex(), 2)
        self.assertTrue(c._bulk.isHidden())
        self.assertTrue(c._pager.isHidden())
        # The toolbar stays: it holds Import and the filters' switch — the
        # way from nobody to somebody — and Apollo's never goes away either.
        self.assertFalse(c._toolbar.isHidden())
        self.assertFalse(c._import_btn.isHidden())

    def test_loading_leads_leaves_the_empty_state(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("A", 90, "a@x.com", "valid")])
        self.assertEqual(c._view_stack.currentIndex(), 1)          # the row list is the default view; 2 is the empty state
        self.assertFalse(c._toolbar.isHidden())
        # The bulk bar waits for a tick now: "0 selected" over five dead
        # buttons was the heaviest thing on the screen.
        self.assertTrue(c._bulk.isHidden())
        c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertFalse(c._bulk.isHidden())

    def test_drawer_stays_shut_until_a_lead_is_picked(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("A", 90, "a@x.com", "valid"),
                        _dos("B", 80, "b@x.com", "")])
        self.assertTrue(c._drawer_w.isHidden())
        c._table.setCurrentCell(0, 1)
        self.assertFalse(c._drawer_w.isHidden())
        c._dismiss_drawer()
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)

    def test_search_panel_mounts_in_the_rail(self):
        c = CK.LeadsCockpit()
        panel = QWidget()
        c.set_search_panel(panel)
        self.assertIs(panel.parentWidget(), c._rail.widget())

    def test_find_new_people_mounts_under_the_filters(self):
        c = CK.LeadsCockpit()
        filters, find = QWidget(), QWidget()
        c.set_search_panel(filters)
        c.set_find_panel(find)
        self.assertIs(find.parentWidget(), c._rail.widget())
        self.assertGreaterEqual(c._find_slot.indexOf(find), 0)
        self.assertEqual(c._search_slot.indexOf(find), -1)
        rail = c._rail.widget().layout()
        # Total / Net New / Saved over the filters, Find new people under them.
        # Between the tabs and the filters, the "N removed · Restore" line
        # (23-Sep-2026: Remove) — hidden while nobody is removed.
        self.assertIs(rail.itemAt(0).widget(), c._tabs_frame)
        self.assertIs(rail.itemAt(1).widget(), c._removed_link)
        self.assertTrue(c._removed_link.isHidden())
        self.assertIs(rail.itemAt(2).layout(), c._search_slot)
        self.assertIs(rail.itemAt(3).layout(), c._find_slot)


class TableFeel(unittest.TestCase):
    """The table the owner works through, on any platform style: checkboxes it
    paints itself (row and select-all), no stray sort arrow, per-pixel
    scrolling, columns and panes that resize and keep their widths, a bulk bar
    that waits for a tick, and the keys a list needs. No event loop: events are
    sent straight to the widgets, and layouts are run by hand."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])

    def _row(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    @staticmethod
    def _mouse(widget, pos, kind=QEvent.MouseButtonPress):
        QApplication.sendEvent(widget, QMouseEvent(
            kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))

    def _click_header_box(self):
        head = self.c._head
        self._mouse(head.viewport(),
                    QPoint(head.sectionSize(CK._C_TICK) // 2, CK._HEAD_H // 2))

    def _lay_out(self, width, height):
        """A real size with no event loop: resize, run each layout, then the
        splitter, all synchronously."""
        c = self.c
        c.resize(width, height)
        c.layout().activate()
        c._body.layout().activate()
        c._split.refresh()

    def test_the_header_checkbox_ticks_the_page_and_shows_partial(self):
        c = self.c
        self._click_header_box()                      # none → the whole page
        self.assertEqual(len(c.selected()), 4)
        self.assertEqual(c._head.check_state(), Qt.Checked)
        c._table.item(self._row(self.d3), 0).setCheckState(Qt.Unchecked)
        self.assertEqual(c._head.check_state(), Qt.PartiallyChecked)
        self._click_header_box()                      # some → all
        self.assertEqual(len(c.selected()), 4)
        self.assertEqual(c._table.item(self._row(self.d3), 0).checkState(), Qt.Checked)
        self._click_header_box()                      # all → none
        self.assertEqual(c.selected(), [])
        self.assertEqual(c._head.check_state(), Qt.Unchecked)

    def test_a_click_anywhere_in_the_tick_cell_ticks_without_opening_the_drawer(self):
        c = self.c
        rect = c._table.visualRect(c._table.model().index(self._row(self.d2), 0))
        # The cell's far edges, well off the box: a platform indicator only
        # answers on itself, and the owner could see no box to aim at.
        for spot, want in ((QPoint(rect.right() - 2, rect.center().y()), [self.d2]),
                           (QPoint(rect.left() + 2, rect.bottom() - 2), [])):
            self._mouse(c._table.viewport(), spot)
            self._mouse(c._table.viewport(), spot, QEvent.MouseButtonRelease)
            self.assertEqual(c.selected(), want)
            self.assertTrue(c._drawer_w.isHidden())
            self.assertEqual(c._table.currentRow(), -1)

    def test_space_ticks_the_current_row_and_esc_closes_the_drawer(self):
        c = self.c
        c._table.setCurrentCell(self._row(self.d3), 1)
        self.assertFalse(c._drawer_w.isHidden())
        QTest.keyClick(c._table, Qt.Key_Space)
        self.assertEqual(c.selected(), [self.d3])
        QTest.keyClick(c._table, Qt.Key_Space)
        self.assertEqual(c.selected(), [])
        QTest.keyClick(c._table, Qt.Key_Escape)
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)

    def test_the_sort_arrow_never_shows(self):
        c = self.c
        self.assertFalse(c._head.isSortIndicatorShown())
        self.assertFalse(c._table.isSortingEnabled())    # live sorting re-showed it
        c._sort.setCurrentIndex(1)
        c.set_dossiers([self.d2, self.d1])
        self.assertFalse(c._head.isSortIndicatorShown())
        self.assertEqual(c._dossier_at(0), self.d1)       # Name A–Z still sorts

    def test_scrolling_is_per_pixel_in_small_steps(self):
        c = self.c
        self.assertEqual(c._table.verticalScrollMode(), QAbstractItemView.ScrollPerPixel)
        self.assertEqual(c._table.horizontalScrollMode(), QAbstractItemView.ScrollPerPixel)
        self.assertEqual(c._table.verticalScrollBar().singleStep(), CK._STEP)
        self.assertEqual(c._gallery.verticalScrollBar().singleStep(), CK._STEP)
        self.assertEqual(c._table.verticalHeader().defaultSectionSize(), CK._ROW_H)

    def test_the_rail_and_the_results_share_a_splitter_within_bounds(self):
        c = self.c
        self.assertIs(c._split.widget(0), c._rail)
        self.assertIs(c._split.widget(1), c._center_w)
        self.assertEqual((c._rail.minimumWidth(), c._rail.maximumWidth()),
                         (CK._RAIL_MIN, CK._RAIL_MAX))
        self._lay_out(1700, 900)
        self.assertEqual(c._split.sizes()[0], CK._RAIL_W)
        c._split.moveSplitter(900, 1)                     # drag the rail's edge far right
        self.assertEqual(c._split.sizes()[0], CK._RAIL_MAX)
        self.assertEqual(c._rail_pref, CK._RAIL_MAX)      # remembered for a fold
        c._split.moveSplitter(100, 1)                     # and far left
        self.assertEqual(c._split.sizes()[0], CK._RAIL_MIN)
        c._split.setSizes([400, 1300])
        c.set_dossiers([self.d1, self.d2])                # a new run keeps the width
        c._split.refresh()
        self.assertEqual(c._split.sizes()[0], 400)

    def test_hide_filters_folds_the_rail_and_restores_its_width(self):
        c = self.c
        self._lay_out(1700, 900)
        c._split.setSizes([410, 1290])
        c._on_split_moved(410, 1)                         # what a drag reports
        c._filters_btn.click()
        self.assertTrue(c._rail.isHidden())
        self.assertEqual(c._filters_btn.text(), "Show filters")
        self.assertEqual(c._split.sizes()[0], 0)
        c._filters_btn.click()
        self.assertFalse(c._rail.isHidden())
        self.assertEqual(c._filters_btn.text(), "Hide filters")
        self.assertEqual(c._split.sizes()[0], 410)

    def test_the_bulk_bar_waits_for_a_tick_and_offers_select_all_and_clear(self):
        c = self.c
        self.assertTrue(c._bulk.isHidden())
        c._table.item(self._row(self.d1), 0).setCheckState(Qt.Checked)
        self.assertFalse(c._bulk.isHidden())
        self.assertEqual(c._bulk.maximumHeight(), CK._QMAX)     # landed, not mid-slide
        self.assertFalse(c._sel_all.isHidden())
        self.assertEqual(c._sel_all.text(), "Select all 4")
        c._sel_all.click()
        self.assertEqual(len(c.selected()), 4)
        self.assertTrue(c._sel_all.isHidden())                  # nothing left to add
        c._bulk_clear.click()
        self.assertEqual(c.selected(), [])
        self.assertTrue(c._bulk.isHidden())
        self.assertTrue(all(c._table.item(r, 0).checkState() == Qt.Unchecked
                            for r in range(c._table.rowCount())))

    def test_clear_and_select_all_would_still_look_disabled_if_ever_disabled(self):
        # Live report, 22-Sep-2026: a customer pressed "Clear" while a
        # background search held the whole bulk bar disabled
        # (workbench._set_running used to disable cockpit.leads._bulk
        # outright) and nothing happened, with no visible sign why — "Clear"
        # and "Select all" are QPushButton#bulkLink, a MORE SPECIFIC selector
        # than the bar's plain "QPushButton:disabled" rule, so without a
        # "#bulkLink:disabled" rule of its own they kept rendering in the
        # same clickable accent-blue regardless of setEnabled(False). The
        # real fix was to stop disabling them at all (see
        # ClearAndSelectAllStayUsableDuringARun below) — this rule stays as
        # a second line of defence, so if anything ever disables them again
        # it will at least be honest about it.
        c = self.c
        qss = c._bulk_bar_w.styleSheet()
        self.assertIn("QPushButton#bulkLink:disabled", qss)

    def test_a_narrow_bulk_bar_folds_again_every_time_it_comes_back(self):
        """The fold was measured while the bar was still hidden, so it came
        back unfolded — and at an unchanged width no Resize put it right: Qt
        crushed six buttons into the bar and cut their labels to stubs."""
        c = self.c
        # Tests never show a window, so "on screen" is the bar not being hidden.
        c._bulk.isVisible = lambda: not c._bulk.isHidden()
        tick = c._table.item(self._row(self.d1), 0)
        tick.setCheckState(Qt.Checked)
        # Room for the primary, Export and More — not for Verify and Save too.
        c._bulk_bar_w.setFixedWidth(c._bulk_need(2))
        c._fit_bulk()                                     # what the bar's first resize does
        self.assertFalse(c._b_more.isHidden())
        self.assertTrue(c._b_verify.isHidden())
        for _ in range(2):                                # clear, tick again: same width
            c._bulk_clear.click()
            self.assertTrue(c._bulk.isHidden())
            tick.setCheckState(Qt.Checked)
            self.assertFalse(c._bulk.isHidden())
            self.assertFalse(c._b_more.isHidden())
            self.assertTrue(c._b_verify.isHidden())
            self.assertTrue(c._b_save.isHidden())
            self.assertTrue(c._sel_all.isHidden())

    def test_coming_back_on_screen_refolds_the_toolbar_and_the_bulk_bar(self):
        """Off screen (another tab showing) both keep everything; a session
        opened from Sessions, or ticks changed meanwhile, unfold them there. The
        tab coming back at the same width sends Show but no Resize."""
        c = self.c
        on_screen = [True]
        c._bulk.isVisible = lambda: on_screen[0] and not c._bulk.isHidden()
        c._toolbar.isVisible = lambda: on_screen[0] and not c._toolbar.isHidden()
        c._table.item(self._row(self.d1), 0).setCheckState(Qt.Checked)
        # Short "Save search", no Table|Cards, Search settings as its icon.
        c._toolbar.setFixedWidth(c._toolbar_need(3))
        c._bulk_bar_w.setFixedWidth(c._bulk_need(2))      # Verify and Add to list in More
        c._fit_toolbar()                                  # what their resizes do
        c._fit_bulk()

        def folded():
            return (c._save_search_btn.text() == "Save search", c._seg.isHidden(),
                    c._settings_btn.text() == "", c._b_verify.isHidden(),
                    not c._b_more.isHidden())

        self.assertEqual(folded(), (True,) * 5)
        on_screen[0] = False                              # the Sessions tab is showing
        c._table.item(self._row(self.d2), 0).setCheckState(Qt.Checked)
        c._apply_filters()
        self.assertEqual(folded(), (False,) * 5)
        on_screen[0] = True                               # and Leads comes back
        for widget in (c._toolbar, c._bulk_bar_w):
            QApplication.sendEvent(widget, QShowEvent())
        self.assertEqual(folded(), (True,) * 5)

    def test_column_widths_survive_a_new_run(self):
        c, head = self.c, self.c._head
        self.assertEqual(head.sectionResizeMode(CK._C_TICK), QHeaderView.Fixed)
        self.assertEqual(head.sectionResizeMode(CK._C_LEAD), QHeaderView.Interactive)
        head.resizeSection(CK._C_LEAD, 340)
        head.resizeSection(CK._C_STATUS, 150)
        head.resizeSection(CK._C_FIT, 20)                 # under its minimum
        c.set_dossiers([self.d2, self.d3])
        self.assertEqual(head.sectionSize(CK._C_LEAD), 340)
        self.assertEqual(head.sectionSize(CK._C_STATUS), 150)
        self.assertEqual(head.sectionSize(CK._C_FIT), CK._COL_MIN[CK._C_FIT])

    def test_the_focus_cell_carries_the_location(self):
        lead = Lead(name="Aarti", title="Plant Head", company="Gulf Works",
                    email="a@x.com", fit_score=70)
        lead.extra = {"location": "Dubai, United Arab Emirates"}
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[lead])
        focus = c._table.item(0, CK._C_FOCUS)
        self.assertEqual(focus.text(), "Plant Head")
        self.assertEqual(focus.data(CK._WHERE_ROLE), "Dubai, United Arab Emirates")
        self.assertIn("Dubai", focus.toolTip())

    def test_the_drawer_docks_when_wide_and_floats_when_narrow(self):
        c = self.c
        self._lay_out(1900, 900)
        c._table.setCurrentCell(0, 1)
        self.assertTrue(c._drawer_docked)
        self.assertIs(c._split.widget(2), c._drawer_w)
        self._lay_out(1000, 700)
        c._place_drawer()                                 # what the body's resize does
        self.assertFalse(c._drawer_docked)
        self.assertIs(c._drawer_w.parentWidget(), c)      # the page's, not the body's
        self.assertFalse(c._drawer_w.isHidden())

    def test_a_floating_drawer_runs_the_pages_full_height(self):
        """Owner, 26-Sep-2026: "i cant see the contact's details properly". The
        drawer floated in the strip UNDER the toolbar — ~340px of a 1080p window
        was already spent above the results, so the person got a ~190px viewport
        (57px on a 768p laptop). Now it is Apollo's side panel: from the top of
        the page to the foot of the results."""
        c = self.c
        self._lay_out(1000, 700)
        c._table.setCurrentCell(0, 1)
        c._place_drawer()
        w = c._drawer_w
        self.assertFalse(c._drawer_docked)
        self.assertEqual(w.y(), 0)                        # over the title row and toolbar…
        foot = c.mapFromGlobal(c._view_stack.mapToGlobal(QPoint(0, c._view_stack.height()))).y()
        self.assertEqual(w.y() + w.height(), foot)        # …down to the pager, which stays clear
        self.assertGreater(c._body.y(), 0)                # there IS a title row and toolbar…
        self.assertGreater(w.height(), foot - c._body.y())    # …and the drawer is taller than
        self.assertGreater(w.x(), 0)                      # the strip it used to get; the left stays clear

    def test_expanded_covers_the_whole_cockpit_and_goes_back(self):
        c = self.c
        self._lay_out(1000, 700)
        c._table.setCurrentCell(0, 1)
        c._place_drawer()
        before = c._drawer_w.geometry()
        c._set_expanded(True)
        self.assertEqual(c._drawer_w.geometry(), QRect(0, 0, c.width(), c.height()))
        c._set_expanded(False)
        self.assertEqual(c._drawer_w.geometry(), before)


class CardGallery(unittest.TestCase):
    """The Pinterest-style card view is the same leads as the table, one
    selection model behind both: a card per lead, ticking a card selects it and
    mirrors the table row, and the filters hide cards just as they hide rows."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.d3 = _dos("NoMail", 60, "")
        self.d4 = _dos("Bad", 40, "b@x.com", "invalid")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2, self.d3, self.d4])
        self.c._set_view("cards")

    def _row(self, dos):
        for r in range(self.c._table.rowCount()):
            if self.c._dossier_at(r) is dos:
                return r
        return -1

    def test_gallery_shows_a_card_per_lead(self):
        self.assertEqual(self.c._view, "cards")
        self.assertEqual(self.c._grid.count(), 4)

    def test_ticking_a_card_selects_it_and_mirrors_the_table(self):
        self.c._card_cbs[0].setChecked(True)             # d1 is dossier index 0
        self.assertEqual(self.c.selected(), [self.d1])
        self.assertTrue(self.c._b_seq.isEnabled())
        self.assertEqual(self.c._table.item(self._row(self.d1), 0).checkState(),
                         Qt.Checked)

    def test_the_cards_follow_the_page(self):
        self.c.set_dossiers([self.d1, self.d2])          # the next page, a filter
        self.assertEqual(self.c._grid.count(), 2)
        self.assertEqual(self.c._view, "cards")          # still in cards

    def test_table_tick_reflects_on_the_card(self):
        r = self._row(self.d2)
        self.c._table.item(r, 0).setCheckState(Qt.Checked)
        self.assertTrue(self.c._card_cbs[1].isChecked())  # d2 is index 1


class WorkspaceSurface(unittest.TestCase):
    """The tab strip over the five screens, and the two things the dialog leans
    on: the re-exposed signals/set_dossiers, and Analytics tracking this run."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid", signal="found")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())

    def test_ten_tabs_over_ten_screens(self):
        # Deals and Due today (the CRM mockup's boards) joined the original seven, at the end so nothing earlier moved.
        self.assertEqual(len(self.w._tabs), 10)
        self.assertEqual(self.w._stack.count(), 10)
        self.assertIs(self.w._stack.currentWidget(), self.w.leads)  # Leads default

    def test_selecting_a_tab_switches_the_stack(self):
        self.w._select(6)                                   # Analytics
        self.assertIs(self.w._stack.currentWidget(), self.w._analytics)
        self.w._select(3)                                   # Lists
        self.assertIs(self.w._stack.currentWidget(), self.w._lists)
        self.w._select(2)                                   # Sessions
        self.assertIs(self.w._stack.currentWidget(), self.w._sessions)
        self.w._select(1)                                   # Companies
        self.assertIs(self.w._stack.currentWidget(), self.w.companies)

    def test_set_dossiers_reaches_leads_and_analytics(self):
        self.w.set_dossiers([self.d1, self.d2])
        self.assertEqual(self.w.leads._table.rowCount(), 2)
        qualified = self.w._analytics._stats.itemAt(0).widget()   # first stat card
        self.assertEqual(qualified._num.text(), "2")

    def test_reexposes_the_bulk_signals(self):
        got = []
        self.w.sequenceRequested.connect(got.append)
        self.w.set_dossiers([self.d1])
        self.w.leads._table.item(0, 0).setCheckState(Qt.Checked)
        self.w.leads._b_seq.click()
        self.assertEqual(got, [[self.d1]])

    def test_analytics_counts_mailed(self):
        draft = type("Dr", (), {"dossier": self.d1, "status": "sent", "body": "hi"})()
        self.w.set_dossiers([self.d1, self.d2], [draft])
        mailed = self.w._analytics._stats.itemAt(2).widget()      # Qualified,Drafted,Mailed
        self.assertEqual(mailed._num.text(), "1")


class ListsTab(unittest.TestCase):
    """Lists is real — it scans a folder for the sheets Prism writes."""

    def test_scans_csv_and_xlsx_newest_first(self):
        d = tempfile.mkdtemp()
        p1 = os.path.join(d, "old list.csv")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("name,email\nA,a@x.com\nB,b@x.com\n")
        p2 = os.path.join(d, "Prism leads.xlsx")
        with open(p2, "wb") as f:
            f.write(b"PK\x03\x04 fake xlsx")
        os.utime(p1, (time.time() - 100, time.time() - 100))      # make the csv older
        tab = CK._ListsTab(d)
        self.assertEqual([os.path.basename(p) for p, *_ in tab._scan()],
                         ["Prism leads.xlsx", "old list.csv"])
        self.assertEqual(tab._grid.count(), 2)                    # two cards, no empty-state

    def test_csv_row_count_excludes_header(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "x.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("h1,h2\n1,2\n3,4\n5,6\n")
        self.assertEqual(CK._csv_rows(p), 3)

    def test_empty_folder_shows_one_empty_state(self):
        # The empty state left the grid on 12-Oct-2026 (/polish: Lists said
        # "nothing yet" in bare grey text while Saved searches had an icon
        # state): the grid now holds only cards, so an empty folder is no cards
        # and exactly one EmptyState showing in their place.
        tab = CK._ListsTab(tempfile.mkdtemp())
        self.assertEqual(tab._grid.count(), 0)
        self.assertFalse(tab._empty.isHidden())
        self.assertTrue(tab._scroll.isHidden())


class _Workbench(unittest.TestCase):
    """A workbench that only ever touches temp folders — sheets, sessions,
    saved searches, saved contacts and CSV imports — plus a finished run to
    hand it. Find new people's "this costs N searches — go?" answers Yes and
    is recorded (self.asked), so a test never meets a modal box."""

    def setUp(self):
        from addons.leads import workbench as WB
        self._WB = WB
        self._tmp = tempfile.mkdtemp()
        self._sessions = tempfile.mkdtemp()
        self._searches = tempfile.mkdtemp()
        self._contacts = tempfile.mkdtemp()
        self._imports = tempfile.mkdtemp()
        self._accounts = tempfile.mkdtemp()
        self.asked = []
        self._saved_attrs = {
            name: getattr(WB.LeadsWorkbench, name)
            for name in ("_autosave_dir", "_sessions_dir", "_searches_dir",
                         "_contacts_dir", "_imports_dir", "_accounts_dir",
                         "_removed_dir", "_confirm_search")}
        WB.LeadsWorkbench._autosave_dir = lambda _self: self._tmp        # no real Documents
        WB.LeadsWorkbench._sessions_dir = lambda _self: self._sessions   # no real workspace
        WB.LeadsWorkbench._searches_dir = lambda _self: self._searches
        WB.LeadsWorkbench._contacts_dir = lambda _self: self._contacts
        WB.LeadsWorkbench._imports_dir = lambda _self: self._imports
        WB.LeadsWorkbench._accounts_dir = lambda _self: self._accounts
        self._removed = tempfile.mkdtemp()
        WB.LeadsWorkbench._removed_dir = lambda _self: self._removed

        def confirm(_self, spec, companies, note):
            self.asked.append((spec, list(companies), note))
            return True
        WB.LeadsWorkbench._confirm_search = confirm

    def tearDown(self):
        for name, value in self._saved_attrs.items():
            setattr(self._WB.LeadsWorkbench, name, value)

    def _run(self):
        """A finished sheet run: two qualified leads, one draft already sent."""
        from prospector.engine import RunResult
        from prospector.reach import Draft
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        d2 = _dos("Vaibhav", 80, "v@x.com", "")
        res = RunResult(dossiers=[d1, d2], total_in_sheet=2, signal_source="",
                        all_leads=[d1.lead, d2.lead])
        return res, [Draft(dossier=d1, subject="Hi", body="Hello", status="sent")]

    def _finished(self, wb):
        wb._start_export = lambda *a, **k: None     # no MX lookups, no files
        wb._next_mode = "sheet"
        wb._next_params = {"mode": "sheet", "sheet_path": "leads.xlsx", "limit": 25}
        res, drafts = self._run()
        wb._jobs = 1
        wb._on_prepared(res, drafts)
        return res, drafts


class WorkbenchAndPanel(_Workbench):
    """The workbench is now the full in-window surface (no modal); the panel
    hosts it lazily. Guard the extraction: it builds, the setup folds, the
    status line hides when empty, and the panel builds the workbench on show."""

    def test_a_finished_run_is_kept_as_a_session(self):
        from addons.leads import sessions
        wb = self._WB.LeadsWorkbench({})
        self._finished(wb)
        heads = sessions.list_sessions(self._sessions)
        self.assertEqual(len(heads), 1)
        self.assertEqual(heads[0]["id"], wb._session_id)
        self.assertEqual(heads[0]["counts"]["sent"], 1)
        self.assertEqual(wb._jobs, 0)

    def test_an_opened_session_comes_back_as_it_was(self):
        from addons.leads import sessions
        first = self._WB.LeadsWorkbench({})
        self._finished(first)
        loaded = sessions.load(self._sessions, first._session_id)
        wb = self._WB.LeadsWorkbench({})
        wb._apply_session(loaded)
        self.assertEqual(wb._cockpit.leads._table.rowCount(), 2)
        mailed = [d for d in wb._res.dossiers
                  if CK.status_of(d, wb._draft_by.get(id(d))) == "Mailed"]
        self.assertEqual(len(mailed), 1)
        self.assertFalse(wb._send_btn.isEnabled())       # nothing left unmailed
        # The table shows the session's own objects, so the Mailed tag is
        # read off the draft the session kept.
        statuses = {wb._cockpit.leads._table.item(r, CK._C_STATUS).text()
                    for r in range(2)}
        self.assertIn("Mailed", statuses)

    def test_the_next_run_skips_people_already_pulled(self):
        from addons.leads.workers import _seen_index
        wb = self._WB.LeadsWorkbench({})
        res, _ = self._finished(wb)
        self.assertIsNone(_seen_index(self._sessions, include_earlier=True))
        seen = _seen_index(self._sessions, include_earlier=False)
        self.assertIn(res.dossiers[0].lead, seen)
        stranger = _dos("Someone Else", 70, "else@y.com", "")
        self.assertNotIn(stranger.lead, seen)

    def test_a_running_job_blocks_a_second_send(self):
        wb = self._WB.LeadsWorkbench({})
        _res, drafts = self._run()
        drafts[0].status = "draft"
        wb._drafts, wb._jobs = drafts, 1
        wb._on_send()                                     # must not start a worker
        self.assertIsNone(wb._send_worker)

    def test_pending_leaves_out_mailed_drafts(self):
        _res, drafts = self._run()
        from prospector.reach import Draft
        fresh = Draft(dossier=drafts[0].dossier, subject="s", body="b")
        self.assertEqual(self._WB.LeadsWorkbench._pending(drafts + [fresh]), [fresh])

    def test_create_deal_on_a_person_ties_the_deal_to_them(self):
        from unittest import mock
        from addons.leads import deals as DL
        wb = self._WB.LeadsWorkbench({})
        dos = _dos("Kunyi", 96, "k@x.com", "valid")
        values = {"title": "Panel order", "company": "Co", "value": 120000, "stage": "Proposal", "next_step": "Call Thu"}
        with mock.patch.object(wb, "_ask_new_deal", return_value=None):
            wb._panel_create_deal(dos.lead)                       # cancelled: nothing is written
        self.assertEqual(DL.list_deals(self._contacts), [])
        with mock.patch.object(wb, "_ask_new_deal", return_value=values):
            wb._panel_create_deal(dos.lead)
        [mine] = wb._person_view(dos).deals
        self.assertEqual((mine.title, mine.person, mine.stage), ("Panel order", dos.lead.name, "Proposal"))
        stranger = _dos("Someone Else", 70, "else@y.com", "")
        self.assertEqual(wb._person_view(stranger).deals, [])     # a deal is only the drawer's of the person it is tied to

    def test_workbench_builds_with_the_cockpit(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertIsNotNone(wb._cockpit)
        self.assertEqual(len(wb._cockpit._tabs), 10)
        self.assertEqual(wb._cockpit._tabs[0].text(), "People")

    def test_status_line_hides_until_it_has_text(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertTrue(wb._status.isHidden())          # empty → no grey band
        wb._status.setText("Sending…")
        self.assertFalse(wb._status.isHidden())
        wb._status.setText("")
        self.assertTrue(wb._status.isHidden())

    def test_search_settings_is_a_dialog_the_toolbar_opens(self):
        """Apollo keeps what a search runs with behind "Search settings" — the
        database, how far it goes, what you sell, the keys — not in the rail
        over the filters."""
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        dlg = wb._settings_dlg
        self.assertFalse(dlg.isVisible())
        wb._cockpit.leads._settings_btn.click()
        self.addCleanup(dlg.hide)
        self.assertTrue(dlg.isVisible())
        for widget in (wb._source_row, wb._target_row, wb._qualify_row,
                       wb._verify_row, wb._offer, wb._skip_seen, wb._keys_toggle):
            self.assertTrue(dlg.isAncestorOf(widget))
        self.assertTrue(wb._keys_box.isHidden())         # key saved → keys folded
        dlg.hide()
        wb._open_settings(keys=True)                    # a search short of a key
        self.assertFalse(wb._keys_box.isHidden())

    def test_the_filters_and_find_new_people_live_in_the_people_rail(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        rail = wb._cockpit.leads._rail.widget()
        self.assertIs(wb._filters.parentWidget(), rail)
        self.assertIs(wb._find_panel.parentWidget(), rail)
        self.assertEqual(wb._prepare.text(), "Find new people")
        self.assertTrue(wb._prepare_all.isHidden())      # Research with AI's, not the rail's
        self.assertEqual(len(wb.action_buttons()), 2)

    def test_keys_open_when_the_exa_key_is_missing(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertFalse(wb._keys_box.isHidden())

    def test_panel_lazy_builds_workbench(self):
        from addons.leads.panel import LeadsPanel
        p = LeadsPanel({})
        self.assertIsNone(p._workbench)                 # nothing built at rest
        p._build()                                       # what showEvent triggers
        self.assertIsNotNone(p._workbench)
        self.assertEqual(p.header.actions_row.count(), 3)  # ?, Export, Send all
        self.assertTrue(all(hasattr(p, s)
                            for s in ("opened", "navigate", "open_run", "refresh")))



class _FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class _FakeSourceWorker:
    """Stands in for SourceWorker: records what it was handed; start() only
    records that it was started — no thread, no network."""
    made: list = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs, self.started = args, kwargs, False
        self.progress, self.done, self.failed = _FakeSignal(), _FakeSignal(), _FakeSignal()
        self.blocked = _FakeSignal()        # Apollo's plan/scope refusal
        self.companiesAsked = _FakeSignal()  # a group of an import's companies asked
        _FakeSourceWorker.made.append(self)

    def start(self):
        self.started = True


class LeadFiltersInTheWorkbench(_Workbench):
    """The rail's lead filters, end to end on the UI side: a Find-people run
    hands the worker the filters (not a line of location text), an old
    session's "Global except india" comes back as an exclusion, and saved
    searches save, load, delete and count their runs."""

    def _spec(self):
        from prospector.filters import SearchSpec
        return SearchSpec.from_dict({
            "locations": {"exclude": ["India"]},
            "job_titles": {"include": ["Plant Head", "Head of Manufacturing"]},
            "industries": {"include": ["Tyre", "Steel Manufacturing"]},
            "seniority": {"include": ["head", "director"]}})

    def test_the_rail_opens_empty_and_the_starter_search_is_one_pick_away(self):
        """Apollo's page opens with no filters. A pre-filled rail filtered
        everyone Prism holds down to one vertical before the owner had asked
        for anything; the owner's own ICP is now a starter in Default view."""
        wb = self._WB.LeadsWorkbench({})
        self.assertEqual(wb._filters.spec().active_count(), 0)
        self.assertFalse(wb._prepare.isEnabled())       # nobody to look for yet
        self.assertIn("job title", wb._find_meta.text())
        wb.use_starter("icp")
        spec = wb._filters.spec()
        self.assertEqual(len(spec.job_titles.include), 6)
        self.assertEqual(len(spec.industries.include), 10)
        self.assertEqual(spec.location_label(), "Anywhere")
        self.assertTrue(wb._prepare.isEnabled())
        self.assertRegex(wb._find_meta.text(), r"About \d+ Exa searches")
        self.assertIn("Loaded", wb._status.text())
        wb.use_starter("nonsense")                      # an unknown key moves nothing
        self.assertEqual(wb._filters.spec(), spec)

    def test_place_suggestions_lead_with_places_and_fall_back_to_the_starters(self):
        from unittest import mock
        got = self._WB._suggest("locations", "ger")
        self.assertEqual(got[0], "Germany")
        self.assertNotIn("Nigeria", got)            # no mid-word matches beside places
        with mock.patch("prospector.places.suggest", side_effect=RuntimeError("gone")):
            self.assertIn("Germany", self._WB._suggest("company_hq", "ger"))
        self.assertEqual(self._WB._suggest("job_titles", "plant"), ["Plant Head"])

    def test_prepare_needs_someone_to_look_for(self):
        from prospector.filters import SearchSpec
        wb = self._WB.LeadsWorkbench({})
        wb._filters.set_spec(SearchSpec.from_dict({"locations": {"exclude": ["India"]}}))
        self.assertFalse(wb._prepare.isEnabled())
        wb._filters.set_spec(SearchSpec.from_dict({"functions": {"include": ["operations"]}}))
        self.assertTrue(wb._prepare.isEnabled())

    def test_a_legacy_global_except_india_session_restores_as_an_exclusion(self):
        wb = self._WB.LeadsWorkbench({})
        wb._restore_inputs({"mode": "icp", "industries": ["Tyre", "Mining"],
                            "roles": ["Plant Head"], "location": "Global except india",
                            "target": 400, "include_earlier": True})
        spec = wb._filters.spec()
        self.assertEqual(spec.locations.exclude, ["India"])
        self.assertEqual(spec.locations.include, [])
        self.assertEqual(spec.job_titles.include, ["Plant Head"])
        self.assertEqual(spec.industries.include, ["Tyre", "Mining"])
        self.assertEqual((wb._target.value(), wb._skip_seen.isChecked()), (400, False))

    def test_a_find_people_run_hands_the_worker_the_filters(self):
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})   # same key: no config write
            spec = self._spec()
            wb._filters.set_spec(spec)
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        # It asked first, naming the searches it would make (23-Sep-2026:
        # the owner approves every credit).
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(self.asked[0][0].to_dict(), spec.to_dict())
        self.assertEqual(len(_FakeSourceWorker.made), 1)
        worker = _FakeSourceWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual(worker.kwargs["spec"], spec.to_dict())
        self.assertEqual(worker.args[0], ["Tyre", "Steel Manufacturing"])
        self.assertEqual(worker.args[1], ["Plant Head", "Head of Manufacturing"])
        self.assertEqual(worker.kwargs["location"], "Anywhere except India")
        # The primary button is the cheap run: the people, and nothing else.
        self.assertEqual((worker.kwargs["emails"], worker.kwargs["leads_only"]),
                         ("later", True))
        params = wb._next_params
        self.assertEqual(params["mode"], "icp_leads_only")
        self.assertEqual(params["filters"], spec.to_dict())
        self.assertEqual(params["location"], "Anywhere except India")
        self.assertEqual(wb._jobs, 1)

    def test_the_two_run_buttons_are_the_cheap_run_and_the_whole_pipeline(self):
        """"Find new people" costs its searches and stops; Research with AI ▸
        "Find new people and qualify them" is the whole run — addresses,
        Groq, drafts — in one press."""
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
            wb._filters.set_spec(self._spec())
            self.assertEqual(wb._prepare.text(), "Find new people")
            self.assertEqual(wb._prepare_all.text(), "Find and prepare")
            wb._prepare.click()
            wb._jobs = 0                                  # the run "finished"
            wb._set_running(False)
            wb._cockpit.leads._act_find_prepare.trigger()
        finally:
            self._WB.SourceWorker = orig
        cheap, whole = _FakeSourceWorker.made
        self.assertEqual((cheap.kwargs["emails"], cheap.kwargs["leads_only"]),
                         ("later", True))
        self.assertEqual((whole.kwargs["emails"], whole.kwargs["leads_only"]),
                         ("now", False))
        self.assertEqual(wb._next_params["mode"], "icp")
        self.assertEqual(len(self.asked), 2)             # each asked before it spent

    def test_find_and_qualify_is_armed_only_when_find_new_people_is(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        menu = wb._cockpit.leads._research_btn.menu()
        act = wb._cockpit.leads._act_find_prepare
        menu.aboutToShow.emit()
        self.assertFalse(act.isEnabled())                 # the rail names nobody
        self.assertIn("job title", act.toolTip())
        wb._filters.set_spec(self._spec())
        menu.aboutToShow.emit()
        self.assertTrue(act.isEnabled())
        wb._jobs = 1                                      # a search is running
        menu.aboutToShow.emit()
        self.assertFalse(act.isEnabled())
        self.assertIn("Wait", act.toolTip())

    def test_a_no_to_the_cost_spends_nothing(self):
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        self._WB.LeadsWorkbench._confirm_search = lambda _self, *a: False
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
            wb._filters.set_spec(self._spec())
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        self.assertEqual(_FakeSourceWorker.made, [])
        self.assertEqual(wb._jobs, 0)
        self.assertTrue(wb._prepare.isEnabled())

    def test_the_confirmation_names_the_cost_and_who_it_asks_for(self):
        """The real question, read rather than clicked: the number of Exa
        searches, and — for companies with nobody named — the decision-makers
        it will ask for."""
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        confirm = self._saved_attrs["_confirm_search"]     # the real one
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        spec = self._spec()
        asked = []

        def answer(reply):
            return lambda *a, **k: asked.append(a[2]) or reply

        # The rail names nobody (an account import alone): it says who.
        with mock.patch.object(QMessageBox, "question",
                               side_effect=answer(QMessageBox.StandardButton.No)):
            ok = confirm(wb, spec, ["Acme Tooling"], "companies 1–1 of 1 from the import")
        self.assertFalse(ok)
        # One company, one search — the location's exclusion is checked on
        # who comes back, not spread over twelve regions (24-Sep-2026).
        self.assertIn("It will run 1 Exa search, asking the company", asked[0])
        self.assertIn("companies 1–1 of 1", asked[0])
        self.assertIn("Owners, Founders, Chiefs and Directors", asked[0])
        # The owner named titles himself: no word about who it asks for.
        wb._filters.set_spec(spec)
        with mock.patch.object(QMessageBox, "question",
                               side_effect=answer(QMessageBox.StandardButton.Yes)):
            self.assertTrue(confirm(wb, spec, [], ""))
        self.assertNotIn("Owners", asked[1])
        # Apollo is billed per person revealed, not per search.
        wb._set_source("apollo")
        with mock.patch.object(QMessageBox, "question",
                               side_effect=answer(QMessageBox.StandardButton.Yes)):
            confirm(wb, spec, [], "")
        self.assertIn("Apollo credit", asked[2])

    def test_the_run_summary_says_who_the_filters_left_out(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        res.filtered_out = {"location": 380, "job_title": 32}
        self.assertIn("412 outside your filters (location)", wb._run_summary(res, drafts))
        res.filtered_out = {}
        self.assertNotIn("outside your filters", wb._run_summary(res, drafts))

    def test_nobody_left_names_the_filters_and_the_reasons(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {"location": 380, "job_title": 32})
        self.assertIn("412 were outside them (380 location, 32 job title)", text)
        self.assertIn("Only find people no earlier search found", _nobody_left(12, {}))
        self.assertIn("Search settings", _nobody_left(12, {}))

    def test_every_search_failing_names_the_key_not_the_filters(self):
        # 22-Sep-2026: reported live three times on a sheet with well-known
        # companies that should have been easy to find someone for.
        # _exa_people distinguishes "the call failed" (None) from "it
        # answered with nothing" ([]) and source.py counts both, but
        # nothing downstream read query_errors before this — every one of
        # these calls failing (a bad key, no balance) produced the exact
        # same "widen the filters" text as a genuine zero-match search.
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=100, queries_used=100)
        self.assertIn("Every one of the 100 searches to Exa failed", text)
        self.assertIn("key or balance", text)
        self.assertNotIn("widen the filters", text)   # not a filters problem

    def test_some_searches_failing_gets_a_note_not_a_false_certainty(self):
        # A few failures do not prove the account is broken — the rest may
        # genuinely have found nobody. Named, not hidden, but not claimed
        # as the definite cause the all-failed case is.
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=3, queries_used=100)
        self.assertIn("No people came back", text)
        self.assertIn("3 of 100 searches to Exa failed", text)

    def test_zero_query_errors_is_unchanged(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "exa", query_errors=0, queries_used=100)
        self.assertEqual(text,
                         "No people came back — widen the filters, or check your Exa balance.")
        # And the default (no stats passed at all) behaves the same way.
        self.assertEqual(_nobody_left(0, {}, "exa"), text)

    def test_apollo_names_apollo_not_exa_when_every_search_fails(self):
        from addons.leads.workers import _nobody_left
        text = _nobody_left(0, {}, "apollo", query_errors=10, queries_used=10)
        self.assertIn("Every one of the 10 searches to Apollo failed", text)
        self.assertNotIn("Exa", text)

    def test_save_search_keeps_the_filters_and_shows_a_card(self):
        from addons.leads import saved_searches
        wb = self._WB.LeadsWorkbench({})
        spec = self._spec()
        wb._filters.set_spec(spec)
        wb._target.setValue(500)
        wb._ask_search_name = lambda suggested="": ("Global plants, not India", True)
        wb._filters._save_btn.click()
        records = saved_searches.list_searches(self._searches)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Global plants, not India")
        self.assertEqual(records[0]["filters"], spec.to_dict())
        self.assertEqual(records[0]["settings"]["target"], 500)
        self.assertEqual(wb._cockpit._saved.cards(), 1)
        self.assertIn("Saved", wb._status.text())

    def test_a_cancelled_or_taken_name_saves_nothing_new(self):
        from addons.leads import saved_searches
        wb = self._WB.LeadsWorkbench({})
        wb._ask_search_name = lambda suggested="": ("", False)
        wb._save_search()
        self.assertEqual(saved_searches.list_searches(self._searches), [])
        saved_searches.save(self._searches, "Taken", self._spec().to_dict())
        wb._ask_search_name = lambda suggested="": ("taken", True)
        wb._save_search()
        self.assertEqual(len(saved_searches.list_searches(self._searches)), 1)
        self.assertIn("Couldn't save this search", wb._status.text())

    def test_use_search_loads_its_filters_and_settings(self):
        from addons.leads import saved_searches
        spec = self._spec()
        record = saved_searches.save(
            self._searches, "Plants", spec.to_dict(),
            settings={"target": 700, "limit": 40, "verify_limit": 5,
                      "include_earlier": True, "offer": "Line retrofits"})
        wb = self._WB.LeadsWorkbench({})
        wb._cockpit.refresh_searches()
        wb._cockpit._select(4)
        card = wb._cockpit._saved._grid.itemAt(0).widget()
        card._use.click()
        self.assertEqual(wb._filters.spec(), spec)
        self.assertEqual((wb._target.value(), wb._limit.value(),
                          wb._verify_limit.value()), (700, 40, 5))
        self.assertFalse(wb._skip_seen.isChecked())
        self.assertEqual(wb._offer.toPlainText(), "Line retrofits")
        self.assertIs(wb._cockpit._stack.currentWidget(), wb._cockpit.leads)
        self.assertEqual(wb._active_search_id, record["id"])
        self.assertIn("Find new people", wb._status.text())
        self.assertIsNone(wb._worker)                   # used, never run

    def test_default_view_picks_a_saved_search_like_the_tab_does(self):
        from addons.leads import saved_searches
        spec = self._spec()
        record = saved_searches.save(self._searches, "Plants", spec.to_dict())
        wb = self._WB.LeadsWorkbench({})
        wb._cockpit.refresh_searches()
        menu = wb._cockpit.leads._views_menu
        pick = next(a for a in menu.actions() if a.text() == "Plants")
        pick.trigger()
        self.assertEqual(wb._filters.spec(), spec)
        self.assertEqual(wb._active_search_id, record["id"])

    def test_use_search_waits_while_a_job_runs(self):
        from addons.leads import saved_searches
        record = saved_searches.save(self._searches, "Plants", self._spec().to_dict())
        wb = self._WB.LeadsWorkbench({})
        before = wb._filters.spec()
        wb._jobs = 1
        wb.use_saved_search(record["id"])
        self.assertEqual(wb._filters.spec(), before)
        self.assertIn("Wait", wb._status.text())

    def test_delete_asks_first_then_removes_the_search(self):
        from addons.leads import saved_searches
        saved_searches.save(self._searches, "Plants", self._spec().to_dict())
        wb = self._WB.LeadsWorkbench({})
        wb._cockpit.refresh_searches()
        wb._confirm_delete = lambda name: False
        wb._cockpit._saved._grid.itemAt(0).widget()._delete.click()
        self.assertEqual(len(saved_searches.list_searches(self._searches)), 1)
        wb._confirm_delete = lambda name: True
        wb._cockpit._saved._grid.itemAt(0).widget()._delete.click()
        self.assertEqual(saved_searches.list_searches(self._searches), [])
        self.assertEqual(wb._cockpit._saved.cards(), 0)
        self.assertFalse(wb._cockpit._saved._empty.isHidden())

    def test_a_finished_run_of_the_search_on_the_rail_is_counted(self):
        from addons.leads import saved_searches
        spec = self._spec()
        record = saved_searches.save(self._searches, "Plants", spec.to_dict())
        wb = self._WB.LeadsWorkbench({})
        wb.use_saved_search(record["id"])
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "filters": spec.to_dict()}
        res, _ = self._run()
        wb._jobs = 1
        wb._on_prepared(res, [])
        after = saved_searches.get(self._searches, record["id"])
        self.assertEqual((after["runs"], after["last_new"]), (1, 2))
        self.assertEqual(after["last_session_id"], wb._session_id)
        # Filters edited after Use are a different search: not counted.
        wb._next_params = {"mode": "icp",
                           "filters": dict(spec.to_dict(), similar_titles=False)}
        wb._jobs = 1
        wb._on_prepared(res, [])
        self.assertEqual(saved_searches.get(self._searches, record["id"])["runs"], 1)



class ApolloIsTheOtherDatabase(_Workbench):
    """The same filters, asked of Apollo instead of Exa: the key is entered
    once and saved on Prepare, the switch picks the source (Exa by default even
    with an Apollo key — Apollo's search is not in its free plan), the run
    setting says what that source charges, and what a run cost in credits is on
    the summary."""

    def _spec(self):
        from prospector.filters import SearchSpec
        return SearchSpec.from_dict({
            "job_titles": {"include": ["Plant Head"]},
            "seniority": {"include": ["owner"]}})

    def _prepared(self, wb):
        """Press Find new people with the worker stubbed out; return it, or
        None. The rail opens empty, so a test that set no filters of its own
        searches for this class's."""
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        if not wb._filters.spec().is_searchable():
            wb._filters.set_spec(self._spec())
        try:
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        return _FakeSourceWorker.made[0] if _FakeSourceWorker.made else None

    def test_exa_is_the_default_even_when_an_apollo_key_is_set(self):
        """Apollo's people search is not in its FREE plan (its own API Keys
        page), so leading with it sends most owners into a 403. It is there to
        be picked, with a tooltip saying what it needs."""
        plain = self._WB.LeadsWorkbench({})
        self.assertEqual(plain._source, "exa")
        self.assertTrue(plain._src_exa.isChecked())
        self.assertFalse(plain._keys_box.isHidden())        # no key at all: open
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertFalse(wb._src_apollo.isChecked())
        self.assertTrue(wb._src_apollo.isEnabled())
        self.assertIn("PAID Apollo plan", wb._src_apollo.toolTip())
        self.assertTrue(wb._keys_box.isHidden())            # either key folds it
        wb._filters.set_spec(self._spec())
        self.assertIn("Exa searches", wb._find_meta.text())  # what the press costs
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")
        self.assertIn("credit per person revealed", wb._find_meta.text())

    def test_the_apollo_key_is_saved_and_nothing_else_in_the_config_is(self):
        """The rail saves the key it was given by loading the config fresh and
        writing back only that key — self.cfg can predate an account saved
        elsewhere, and the real config is never touched by a test."""
        from unittest import mock
        wb = self._WB.LeadsWorkbench({"exa_api_key": "exa-k"})
        wb._apollo.setText("ap-secret")
        saved = []
        with mock.patch("core_bridge.config.load",
                        return_value={"api_key": "gsk_kept"}), \
                mock.patch("core_bridge.config.save", side_effect=saved.append):
            worker = self._prepared(wb)
        self.assertIsNotNone(worker)
        self.assertEqual(saved, [{"api_key": "gsk_kept",
                                  "apollo_api_key": "ap-secret"}])
        self.assertEqual(wb.cfg["apollo_api_key"], "ap-secret")

    def test_done_in_search_settings_keeps_a_new_exa_key(self):
        """24-Sep-2026: the owner's Exa key expired. A new one pasted into
        Search settings › Keys & claims was only kept once Find new people
        was pressed — Done forgot it, and Find e-mails and the company
        look-ups went on with the old key. Done keeps it now, and writes
        nothing else in the config."""
        from unittest import mock
        wb = self._WB.LeadsWorkbench({"exa_api_key": "exa-old"})
        wb._exa.setText("exa-new")
        saved = []
        with mock.patch("core_bridge.config.load",
                        return_value={"api_key": "gsk_kept", "exa_api_key": "exa-old"}), \
                mock.patch("core_bridge.config.save", side_effect=saved.append):
            wb._settings_dlg.accept()                   # Done
        self.assertEqual(saved, [{"api_key": "gsk_kept", "exa_api_key": "exa-new"}])
        self.assertEqual(wb.cfg["exa_api_key"], "exa-new")

    def test_an_apollo_run_hands_the_worker_the_source_and_the_filters(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        wb._src_apollo.click()                          # Exa is the default now
        spec = self._spec()
        wb._filters.set_spec(spec)
        worker = self._prepared(wb)
        self.assertTrue(worker.started)
        self.assertEqual(worker.kwargs["source"], "apollo")
        self.assertEqual(worker.kwargs["spec"], spec.to_dict())
        self.assertEqual(wb._next_params["source"], "apollo")
        self.assertEqual(wb._jobs, 1)

    def test_either_source_can_be_picked_and_the_session_brings_it_back(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_exa.click()
        self.assertEqual(self._prepared(wb).kwargs["source"], "exa")
        wb._restore_inputs({"mode": "icp", "source": "apollo", "target": 400})
        self.assertEqual(wb._source, "apollo")
        self.assertTrue(wb._src_apollo.isChecked())

    def test_a_session_that_names_no_source_reopens_on_exa(self):
        """Every session saved before Prism could ask Apollo — and every sheet
        run — carries no source, so it can only have been an Exa run; reopening
        one must not re-point it at the database that bills per person."""
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_apollo.click()                           # pick Apollo, then reopen
        self.assertEqual(wb._source, "apollo")
        wb._restore_inputs({"mode": "icp", "target": 400})
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertEqual(wb._target_row.name.text(), "Source up to")
        self.assertEqual(self._prepared(wb).kwargs["source"], "exa")

    def test_prepare_says_which_key_is_missing(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "exa-k"})
        wb._src_apollo.click()
        self.assertIsNone(self._prepared(wb))
        self.assertIn("Apollo API key", wb._status.text())
        self.assertFalse(wb._keys_box.isHidden())    # opened at the missing key
        self.assertEqual(wb._jobs, 0)
        wb._src_exa.click()
        self.assertIsNotNone(self._prepared(wb))

    def test_the_run_setting_says_what_the_source_charges(self):
        wb = self._WB.LeadsWorkbench({})
        self.assertEqual(wb._target_row.name.text(), "Source up to")
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")
        self.assertEqual(wb._target_row.name.text(), "Reveal up to")
        self.assertIn("one Apollo credit", wb._target.toolTip())
        wb._src_exa.click()
        self.assertEqual(wb._target_row.name.text(), "Source up to")

    def test_the_summary_counts_what_the_run_cost_in_credits(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        res.apollo_stats = {"searched": 240, "revealed": 25, "reveal_calls": 3}
        self.assertIn("Apollo: 240 found · 25 revealed (about 25 credits)",
                      wb._run_summary(res, drafts))
        res.apollo_stats = {}                       # an Exa run says nothing
        self.assertNotIn("Apollo", wb._run_summary(res, drafts))


def _apollo_module():
    """prospector.apollo — the Apollo client the worker calls — or a stand-in
    registered under that name while it is being written beside these tests.
    Either way the tests patch the same two functions on the same module, so
    they say the same thing about the worker once the real client lands."""
    import types

    import prospector
    try:
        from prospector import apollo
        return apollo
    except ImportError:
        apollo = types.ModuleType("prospector.apollo")

        class ApolloError(Exception):
            pass

        apollo.ApolloError = ApolloError
        apollo.api_key = lambda cfg: (cfg.get("apollo_api_key") or "").strip()
        apollo.search_people = lambda spec, key, **kw: []
        apollo.find_email = lambda lead, key: ("", "")
        sys.modules["prospector.apollo"] = apollo
        prospector.apollo = apollo
        return apollo


class SourceWorkerSearchesApollo(unittest.TestCase):
    """SourceWorker.run() with source="apollo", called inline (no thread, no
    network): the filters go to Apollo and never to Exa, only the people Apollo
    had no address for are enriched, what the run cost rides home on the
    result, and an ApolloError is what the failure says."""

    def _worker(self, cfg=None, **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["owner"]},
                                     "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits",
                         {"apollo_api_key": "ap-test"} if cfg is None else cfg,
                         source="apollo", target=25, verify_limit=0,
                         spec=spec.to_dict(), **kw)
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, spec, got

    def _people(self):
        """What Apollo hands back: one person it had an address for, one it
        did not."""
        known = Lead(name="Ana Ruiz", company="Acme", title="Owner",
                     email="ana@acme.com")
        known.extra = {"apollo_id": "a1", "email_check": "valid"}
        unknown = Lead(name="Bo Lund", company="Globex", title="Owner")
        unknown.extra = {"apollo_id": "a2"}
        return known, unknown

    def _patched(self, search, enriched=None):
        """Every seam the Apollo path touches, stubbed. prospector.source is
        stubbed to raise: asking Exa on an Apollo run would be the bug."""
        from unittest import mock
        from prospector.engine import RunResult
        apollo = _apollo_module()

        def fake_run_leads(leads, offer, cfg, **kw):
            return RunResult(dossiers=[Dossier(lead=l) for l in leads],
                             total_in_sheet=len(leads), signal_source="",
                             all_leads=list(leads))

        return [
            mock.patch.object(apollo, "api_key", return_value="ap-test"),
            mock.patch.object(apollo, "search_people", side_effect=search),
            mock.patch("prospector.source.source",
                       side_effect=AssertionError("Exa must not be asked")),
            mock.patch("prospector.signals.exa_key", return_value=""),
            mock.patch("prospector.signals.make_provider", return_value=None),
            mock.patch("prospector.enrich.enrich",
                       side_effect=lambda leads, key="", **kw: (
                           enriched.append(list(leads)) if enriched is not None
                           else None)),
            mock.patch("prospector.engine.run_leads", side_effect=fake_run_leads),
            mock.patch("prospector.verify.collect_keys", return_value={}),
            mock.patch("prospector.reach.draft_batch", return_value=[]),
        ]

    @staticmethod
    def _run(worker, patches):
        for patch in patches:
            patch.start()
        try:
            worker.run()
        finally:
            for patch in patches:
                patch.stop()

    def test_the_filters_go_to_apollo_and_the_credits_come_back(self):
        from prospector.filters import SearchSpec
        known, unknown = self._people()
        calls, enriched = {}, []

        def fake_search(spec, key, **kw):
            calls.update(spec=spec, key=key, **kw)
            kw["stats"].update(searched=240, revealed=2, reveal_calls=1,
                               filtered={"location": 40}, skipped_seen=3)
            kw["on_progress"]("search", 3, 0, 240)
            kw["on_progress"]("reveal", 12, 25, 0)
            return [known, unknown]

        w, spec, got = self._worker()
        self._run(w, self._patched(fake_search, enriched))
        self.assertEqual(got["failed"], [])
        self.assertIsInstance(calls["spec"], SearchSpec)
        self.assertEqual(calls["spec"], spec)
        self.assertEqual((calls["key"], calls["target"]), ("ap-test", 25))
        self.assertIsNone(calls["skip"])                 # no sessions folder
        # The person Apollo had no address for is NOT guessed one (24-Sep-2026:
        # "hunter + apollo only to find mails") — the finders look them up
        # later, for the hot and warm, or from Find e-mails.
        self.assertEqual(enriched, [])
        self.assertEqual(unknown.email, "")
        res, _drafts = got["done"][0]
        self.assertEqual(res.apollo_stats["revealed"], 2)
        self.assertEqual(res.filtered_out, {"location": 40})
        self.assertEqual(res.skipped_seen, 3)
        self.assertIn("Searching Apollo — page 3 · 240 found", got["progress"])
        self.assertIn("Revealing 12 of 25 (Apollo credits)", got["progress"])

    def test_an_apollo_error_is_what_the_failure_says(self):
        apollo = _apollo_module()

        def boom(spec, key, **kw):
            raise apollo.ApolloError("Apollo refused that key (401).")

        w, _spec, got = self._worker()
        self._run(w, self._patched(boom))
        self.assertEqual(got["done"], [])
        self.assertEqual(got["failed"], ["Apollo refused that key (401)."])

    def test_nobody_left_names_apollo(self):
        from addons.leads.workers import _nobody_left
        w, _spec, got = self._worker()
        self._run(w, self._patched(lambda spec, key, **kw: []))
        self.assertEqual(got["done"], [])
        self.assertIn("Apollo", got["failed"][0])
        self.assertIn("Exa balance", _nobody_left(0, {}))     # unchanged for Exa

    def test_without_a_key_apollo_is_never_asked(self):
        from unittest import mock
        apollo = _apollo_module()
        w, _spec, got = self._worker(cfg={})
        asked = []
        patches = self._patched(lambda spec, key, **kw: asked.append(kw) or [])
        patches[0] = mock.patch.object(apollo, "api_key", return_value="")
        self._run(w, patches)
        self.assertEqual(asked, [])
        self.assertIn("Apollo API key", got["failed"][0])


class SourceWorkerHandsOnTheFilters(unittest.TestCase):
    """SourceWorker.run(), called inline (no thread, no network): the filters
    reach source.source as a SearchSpec, the roles it ranks by are the
    filters' role terms, and who the filters turned away rides on the result —
    or, when nobody is left, is said in the failure."""

    def _worker(self, **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({
            "locations": {"exclude": ["India"]},
            "seniority": {"include": ["head"]},
            "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", {}, leads_only=True,
                         spec=spec.to_dict(), **kw)
        got = {"done": [], "failed": []}
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, spec, got

    def _patched(self, found, filtered):
        from unittest import mock
        calls = {}

        def fake_source(industries, roles, key, **kw):
            calls.update(roles=roles, spec=kw.get("spec"))
            kw["stats"].update(filtered=dict(filtered), company_unverified=3)
            return list(found)

        return calls, [
            mock.patch("prospector.signals.exa_key", return_value="exa-test"),
            mock.patch("prospector.source.source", side_effect=fake_source),
            mock.patch("prospector.enrich.enrich", return_value=None),
            mock.patch("prospector.triage.rank",
                       side_effect=lambda leads, offer, roles=None: list(leads)),
        ]

    def _run(self, worker, patches):
        for patch in patches:
            patch.start()
        try:
            worker.run()
        finally:
            for patch in patches:
                patch.stop()

    def test_the_spec_reaches_the_source_and_the_counts_come_back(self):
        from prospector.filters import SearchSpec
        w, spec, got = self._worker()
        people = [Lead(name="Ana Ruiz", company="Acme", title="Head Operations")]
        calls, patches = self._patched(people, {"location": 40, "seniority": 2})
        self._run(w, patches)
        self.assertEqual(got["failed"], [])
        self.assertIsInstance(calls["spec"], SearchSpec)
        self.assertEqual(calls["spec"], spec)
        self.assertEqual(calls["roles"], spec.role_terms())
        res, drafts = got["done"][0]
        self.assertEqual(res.filtered_out, {"location": 40, "seniority": 2})
        self.assertEqual(res.company_unverified, 3)
        self.assertEqual(len(res.all_leads), 1)

    def test_nobody_inside_the_filters_says_why(self):
        w, _spec, got = self._worker()
        _calls, patches = self._patched([], {"location": 380, "job_title": 32})
        self._run(w, patches)
        self.assertEqual(got["done"], [])
        self.assertIn("Nobody who came back matched your filters", got["failed"][0])
        self.assertIn("(380 location, 32 job title)", got["failed"][0])


class EverySourcedPersonIsListed(unittest.TestCase):
    """A leads-sheet-only run sources people and qualifies none; a full run
    qualifies only the top slice of what it sourced. Both used to leave the
    unqualified off the table — the owner opened a 100-lead session to an empty
    screen. Now every sourced person is a row: a qualified one keeps its
    dossier, the rest read "Not qualified", and Analytics still counts only
    the qualified."""

    def _lead(self, name, fit, location=""):
        lead = Lead(name=name, title="Plant Head", company=f"{name} Works",
                    email=f"{name.lower()}@x.com", fit_score=fit)
        lead.extra = {"location": location} if location else {}
        return lead

    def test_a_leads_only_run_fills_the_table(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[self._lead(f"P{i}", 50 + i) for i in range(5)])
        self.assertEqual(c._table.rowCount(), 5)
        self.assertNotEqual(c._view_stack.currentIndex(), 2)   # not the empty state
        self.assertFalse(c._toolbar.isHidden())
        self.assertEqual({c._table.item(r, 5).text() for r in range(5)},
                         {"Not qualified"})
        self.assertTrue(all(d.status == CK.UNQUALIFIED for d in c._dossiers))

    def test_a_qualified_lead_is_listed_once_with_its_dossier(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        other = self._lead("Vaibhav", 40)
        c = CK.LeadsCockpit()
        c.set_dossiers([d1], all_leads=[d1.lead, other])
        self.assertEqual(c._table.rowCount(), 2)
        self.assertIs(c._dossiers[0], d1)
        self.assertEqual([d.lead for d in c._dossiers], [d1.lead, other])

    def test_qualified_only_leaves_the_rest_out(self):
        """"Qualified by Prism only" is a filter now (Fit score, in More
        filters), over everyone Prism holds — not a switch on one run."""
        from addons.leads import pool as P
        from prospector.filters import SearchSpec
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        people = P.build(runs=[("s1", "2026-09-23T10:00:00", [
            d1.lead, self._lead("A", 60), self._lead("B", 70)], [d1])])
        shown = P.filter_people(people, SearchSpec(qualified_only=True))
        self.assertEqual([p.dossier for p in shown], [d1])
        self.assertEqual(len(P.filter_people(people, SearchSpec())), 3)

    def test_an_unqualified_lead_can_be_picked_exported_and_opened(self):
        from PySide6.QtWidgets import QLabel
        lead = self._lead("Aarti", 80, "Dubai, United Arab Emirates")
        c = CK.LeadsCockpit()
        c.set_dossiers([], all_leads=[lead])
        got = []
        c.exportRequested.connect(got.append)
        c._table.item(0, 0).setCheckState(Qt.Checked)
        c._b_export.click()
        self.assertEqual([d.lead for d in got[0]], [lead])
        c._table.setCurrentCell(0, 1)
        texts = [w.text() for w in c._drawer_w.findChildren(QLabel)]
        self.assertTrue(any("Not qualified yet" in t for t in texts))
        self.assertTrue(any("Dubai" in t for t in texts))

    def test_analytics_counts_only_the_qualified(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        w = CK.LeadsWorkspace(leads_folder=folder.name)
        w.set_dossiers([d1], [], all_leads=[d1.lead, self._lead("A", 60)])
        self.assertEqual(w.leads._table.rowCount(), 2)
        self.assertEqual(len(w._analytics._dossiers), 1)


class AnImportsCompaniesAreAskedInGroupsInOnePress(unittest.TestCase):
    """SourceWorker.run(), inline: an Account CSV import searched whole (the
    owner, 24-Sep-2026) hands the worker every company — more than one
    Current company facet holds — and it asks them in groups of that size,
    one after another in this one run, every company once, saying after each
    group how many are asked."""

    def test_seventy_two_companies_go_in_two_groups_every_one_asked(self):
        from unittest import mock
        from addons.leads.workers import SourceWorker
        from prospector.filters import MAX_FACET_VALUES, SearchSpec
        names = [f"Company {i}" for i in range(1, 73)]
        spec = SearchSpec.from_dict({"seniority": {"include": ["owner", "director"]},
                                     "companies": {"include": names[:MAX_FACET_VALUES]}})
        w = SourceWorker([], [], "Line retrofits", {}, leads_only=True, emails="later",
                         spec=spec.to_dict(), companies=names)
        asked, calls, got = [], [], {"done": [], "failed": []}
        w.companiesAsked.connect(asked.append)
        w.done.connect(lambda res, drafts: got["done"].append(res))
        w.failed.connect(got["failed"].append)

        def fake_source(industries, roles, key, **kw):
            part = kw["spec"]
            calls.append((list(part.companies.include), kw["target"], kw["per_company"]))
            kw["stats"].update(queries_used=len(part.companies.include),
                               filtered={"seniority": 1})
            return [Lead(name=f"P {c}", company=c, title="Owner")
                    for c in part.companies.include[:2]]
        patches = [mock.patch("prospector.signals.exa_key", return_value="exa-test"),
                   mock.patch("prospector.source.source", side_effect=fake_source),
                   mock.patch("prospector.triage.rank",
                              side_effect=lambda leads, offer, roles=None: list(leads))]
        for patch in patches:
            patch.start()
        try:
            w.run()
        finally:
            for patch in patches:
                patch.stop()
        self.assertEqual(got["failed"], [])
        self.assertEqual([len(c) for c, _t, _p in calls], [MAX_FACET_VALUES, 72 - MAX_FACET_VALUES])
        self.assertEqual(calls[0][0] + calls[1][0], names)      # every company, once
        # The run's target never cuts a group short: up to 3 from each company.
        self.assertEqual([(t, p) for _c, t, p in calls],
                         [(MAX_FACET_VALUES * 3, 3), ((72 - MAX_FACET_VALUES) * 3, 3)])
        self.assertEqual(asked, [MAX_FACET_VALUES, 72])
        res = got["done"][0]
        self.assertEqual(len(res.all_leads), 4)
        self.assertEqual(res.filtered_out, {"seniority": 2})     # both groups counted


class ALeadsOnlyRunShowsItsPeople(_Workbench):

    def test_opening_a_leads_only_run_lists_every_person(self):
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i}", title="Plant Head", company=f"Co {i}",
                      email=f"p{i}@x.com", fit_score=60 + i) for i in range(4)]
        res = RunResult(dossiers=[], total_in_sheet=4, signal_source="",
                        all_leads=leads)
        wb = self._WB.LeadsWorkbench({})
        wb._show_result(res, [])
        self.assertEqual(wb._cockpit.leads._table.rowCount(), 4)
        self.assertTrue(wb._export_btn.isEnabled())


def _contacts_result(tmp, leads, name="Apollo_leads (1).csv", **settings):
    """What ImportWizard.result() hands back for a contacts import."""
    return {"kind": "contacts", "path": os.path.join(tmp, name), "name": name,
            "sheet": "", "mapping": {"Name": "name", "Email": "email"},
            "rows": len(leads), "skipped": 0,
            "settings": {"update_existing": True, "add_to_list": False,
                         "list_name": "", "find_emails": False, **settings},
            "leads": list(leads)}


def _accounts_result(tmp, names, name="companies.xlsx"):
    """What ImportWizard.result() hands back for an accounts import."""
    return {"kind": "accounts", "path": os.path.join(tmp, name), "name": name,
            "sheet": "Sheet1", "mapping": {"Company Name": "name"},
            "rows": len(names), "skipped": 0, "settings": {},
            "companies": [{"name": n} for n in names]}


class ImportIsItsOwnAction(_Workbench):
    """Apollo's People > Import > CSV (23-Sep-2026, "copy the entire
    architecture and interface of apollo"): importing is an action at the top
    of the page with a mapping step — never a mode of the search — and it
    never searches (22-Sep: "sheets are here to load the data from it"). A
    contacts import saves the people as contacts tagged with the import; an
    accounts import records the companies. Either way the page then shows
    what came in: that import's filter, and nothing else."""

    def setUp(self):
        super().setUp()
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        self.addCleanup(setattr, self._WB, "SourceWorker", orig)

    @staticmethod
    def _leads(n=3, **kw):
        return [Lead(name=f"P{i} Shah", title="Purchase Manager", company=f"Co {i}",
                     email=f"p{i}@co{i}.com", **kw) for i in range(n)]

    def test_import_opens_the_wizard_for_that_kind_and_a_cancel_writes_nothing(self):
        from unittest import mock
        from PySide6.QtWidgets import QDialog
        from addons.leads import imports as IM
        from addons.leads.import_wizard import ImportWizard
        opened = []
        wb = self._WB.LeadsWorkbench({})
        with mock.patch.object(ImportWizard, "exec",
                               lambda w: opened.append(w.kind) or QDialog.Rejected):
            for action in wb._cockpit.leads._import_btn.menu().actions():
                action.trigger()
        self.assertEqual(opened, ["contacts", "accounts"])
        self.assertEqual(IM.list_imports(self._imports), [])
        self.assertEqual(_FakeSourceWorker.made, [])

    def test_a_contacts_import_saves_them_and_shows_only_them(self):
        from addons.leads import contacts as CT
        from addons.leads import imports as IM
        from prospector.filters import SearchSpec
        wb = self._WB.LeadsWorkbench({})
        wb._filters.set_spec(SearchSpec.from_dict(
            {"job_titles": {"include": ["Plant Head"]}}))     # would hide them all
        wb._run_import(_contacts_result(self._tmp, self._leads()))
        heads = IM.list_imports(self._imports)
        self.assertEqual([(h["kind"], h["name"]) for h in heads],
                         [("contacts", "Apollo_leads (1).csv")])
        self.assertEqual((heads[0]["counts"]["rows"], heads[0]["counts"]["added"]), (3, 3))
        saved = CT.list_contacts(self._contacts)
        self.assertEqual(len(saved), 3)
        self.assertTrue(all(c.imports == [heads[0]["id"]] for c in saved))
        # "Hide Filters 1": the import's filter, and the job title is gone.
        spec = wb._filters.spec()
        self.assertEqual(spec.contact_imports, [heads[0]["id"]])
        self.assertEqual(spec.active_count(), 1)
        ck = wb._cockpit.leads
        self.assertEqual(ck._table.rowCount(), 3)
        self.assertEqual(ck._tab_counts, {"total": 3, "net_new": 0, "saved": 3})
        self.assertIn("Imported 3 contacts from Apollo_leads (1).csv", wb._status.text())
        self.assertEqual(_FakeSourceWorker.made, [])        # nothing searched
        self.assertIsNone(wb._worker)

    def test_someone_already_held_is_updated_not_listed_twice(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._leads(1), name="a.csv"))
        again = self._leads(1)
        again[0].title = "Head of Purchase"
        wb._run_import(_contacts_result(self._tmp, again, name="b.csv"))
        saved = CT.list_contacts(self._contacts)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].lead.title, "Head of Purchase")
        self.assertEqual(len(saved[0].imports), 2)          # both imports hold her
        self.assertEqual(wb._cockpit.leads._table.rowCount(), 1)
        keep = self._leads(1)
        keep[0].title = "Intern"
        wb._run_import(_contacts_result(self._tmp, keep, name="c.csv",
                                        update_existing=False))
        self.assertEqual(CT.list_contacts(self._contacts)[0].lead.title,
                         "Head of Purchase")

    def test_find_emails_on_import_asks_for_the_ones_without(self):
        wb = self._WB.LeadsWorkbench({})
        made = []
        wb._find_emails = lambda dossiers: made.append([d.lead.name for d in dossiers])
        leads = self._leads()
        leads[1].email = ""
        leads[2].email = ""
        wb._run_import(_contacts_result(self._tmp, leads, find_emails=True))
        self.assertEqual(made, [["P1 Shah", "P2 Shah"]])

    def test_add_to_a_list_writes_the_sheet_the_lists_tab_shows(self):
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._leads(), add_to_list=True,
                                        list_name="Vadodara buyers"))
        path = os.path.join(self._tmp, "Vadodara buyers.csv")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(CK._csv_rows(path), 3)

    def test_an_accounts_import_records_the_companies_and_searches_nothing(self):
        from addons.leads import imports as IM
        wb = self._WB.LeadsWorkbench({})                    # no key at all
        wb._run_import(_accounts_result(self._tmp, ["Acme Tooling", "Beta Corp"]))
        heads = IM.list_imports(self._imports, "accounts")
        self.assertEqual((heads[0]["n_companies"], heads[0]["searched"]), (2, 0))
        self.assertEqual(wb._filters.spec().account_imports, [heads[0]["id"]])
        self.assertEqual(wb._filters.spec().active_count(), 1)
        self.assertEqual(_FakeSourceWorker.made, [])
        self.assertIn("Find new people", wb._status.text())
        self.assertNotIn("Exa API key", wb._status.text())
        # Find new people is armed for them: decision-makers, a batch named.
        self.assertTrue(wb._prepare.isEnabled())
        self.assertIn("companies 1–2 of 2 from the import", wb._find_meta.text())

    def test_a_contacts_file_that_is_really_companies_says_so_in_the_wizard(self):
        """22-Sep-2026: a company-research export (Company Name, Industry,
        City — never a person) went in as people and nothing came of it. The
        mapping step now says which import it is."""
        import openpyxl
        from addons.leads.import_wizard import ImportWizard
        path = os.path.join(self._tmp, "companies.xlsx")
        book = openpyxl.Workbook()
        book.active.append(["Company Name", "Industry Category", "City"])
        book.active.append(["Acme Tooling", "Packaging Machinery", "Vadodara"])
        book.save(path)
        w = ImportWizard("contacts")
        self.assertTrue(w.load(path))                       # straight to the mapping
        self.assertFalse(w._import.isEnabled())
        self.assertIn("looks like a list of companies", w._map_error.text())
        people = ImportWizard("contacts")
        book = openpyxl.Workbook()
        book.active.append(["Name", "Company"])
        book.active.append(["Jane Doe", "Acme Tooling"])
        other = os.path.join(self._tmp, "people.xlsx")
        book.save(other)
        self.assertTrue(people.load(other))
        self.assertTrue(people._import.isEnabled())
        self.assertEqual(people._map_error.text(), "")


class ImportSettingsReachTheStores(_Workbench):
    """The import page's settings, end to end into the stores (knowledge.apollo.io
    "Import a CSV of Contacts / Accounts"): the stage — from the CSV or one for
    everyone — "If … already exist", "Auto-assign accounts?", "Add to a list?",
    and an accounts import's enrichment, which asks before it spends."""

    @staticmethod
    def _people():
        a = Lead(name="Asha Rao", title="Owner", company="Rao Precision Works",
                 email="asha@raoprecision.example")
        a.extra["stage"] = "Interested"
        b = Lead(name="Vikram Das", title="Director", company="Das Steel",
                 email="vikram@gmail.com")
        b.extra["website"] = "dassteel.example"
        c = Lead(name="Nita Shah", title="CEO", company="Shah Forgings")
        c.extra["linkedin"] = "linkedin.com/in/nita-shah-example"
        return [a, b, c]

    def test_the_stage_from_the_csv_or_one_for_everyone(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._people(), stage="csv"))
        stages = {c.lead.name: c.stage for c in CT.list_contacts(self._contacts)}
        self.assertEqual(stages, {"Asha Rao": "Interested", "Vikram Das": "Cold",
                                  "Nita Shah": "Cold"})
        other = tempfile.mkdtemp()
        self._WB.LeadsWorkbench._contacts_dir = lambda _self: other
        wb2 = self._WB.LeadsWorkbench({})
        wb2._run_import(_contacts_result(self._tmp, self._people(), stage="Approaching"))
        self.assertEqual({c.stage for c in CT.list_contacts(other)}, {"Approaching"})

    def test_auto_assign_creates_the_accounts_by_website_or_email_domain(self):
        from addons.leads import accounts as AC
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._people(),
                                        assign_accounts="domain"))
        accounts = {a.name: a.domain for a in AC.list_accounts(self._accounts)}
        # Asha by her e-mail, Vikram by his company's website (his address is
        # gmail — nobody's company), Nita gives no domain at all.
        self.assertEqual(accounts, {"Rao Precision Works": "raoprecision.example",
                                    "Das Steel": "dassteel.example"})
        self.assertIn("2 new accounts", wb._status.text())

    def test_auto_assign_by_name_and_not_at_all(self):
        from addons.leads import accounts as AC
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._people(), assign_accounts="none"))
        self.assertEqual(AC.list_accounts(self._accounts), [])
        wb._run_import(_contacts_result(self._tmp, self._people(), name="again.csv",
                                        assign_accounts="name"))
        self.assertEqual(sorted(a.name for a in AC.list_accounts(self._accounts)),
                         ["Das Steel", "Rao Precision Works", "Shah Forgings"])

    def test_add_to_a_list_tags_every_contact_with_it(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        wb._run_import(_contacts_result(self._tmp, self._people(), add_to_list=True,
                                        list_name="Expo leads"))
        self.assertEqual({tuple(c.lists) for c in CT.list_contacts(self._contacts)},
                         {("Expo leads",)})
        self.assertIn("Expo leads", wb._list_names())

    def test_an_accounts_import_saves_the_accounts_with_their_stage(self):
        from addons.leads import accounts as AC
        wb = self._WB.LeadsWorkbench({})
        result = _accounts_result(self._tmp, ["Google", "SPI Technologies Inc"])
        result["companies"][1]["stage"] = "Current Client"
        result["settings"] = {"stage": "csv", "update_existing": True}
        wb._run_import(result)
        stages = {a.name: a.stage for a in AC.list_accounts(self._accounts)}
        self.assertEqual(stages, {"Google": "Cold", "SPI Technologies Inc": "Current Client"})

    def test_enrichment_asks_first_then_fills_the_import_and_the_accounts(self):
        from addons.leads import accounts as AC
        from addons.leads import imports as IM
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        asked, made = [], []
        from addons.leads import workers as WK
        orig = WK.LeadsAccountEnrichWorker

        class _Worker(_FakeSourceWorker):
            wants = staticmethod(orig.wants)            # the real rule, no thread

            def __init__(self, companies, cfg, mode):
                super().__init__(companies, cfg, mode)
                made.append(self)

        WK.LeadsAccountEnrichWorker = _Worker
        self.addCleanup(setattr, WK, "LeadsAccountEnrichWorker", orig)
        wb._confirm_enrich = lambda n: asked.append(n) or True
        result = _accounts_result(self._tmp, ["Google", "Tiny Co"])
        result["companies"][0]["website"] = "google.com"
        result["settings"] = {"stage": "Cold", "update_existing": True,
                              "find_websites": True}
        wb._run_import(result)
        self.assertEqual(asked, [1])                    # only Tiny Co has no website
        self.assertEqual(len(made), 1)
        self.assertTrue(made[0].started)
        self.assertEqual(wb._jobs, 1)
        head = IM.list_imports(self._imports, "accounts")[0]
        found = [dict(c) for c in made[0].args[0]]
        found[1].update(website="tinyco.example", headcount="12", location="Pune, India")
        wb._on_accounts_enriched(head["id"], found, 1)
        self.assertEqual(wb._jobs, 0)
        self.assertEqual(IM.get(self._imports, head["id"])["companies"][1]["domain"],
                         "tinyco.example")
        tiny = next(a for a in AC.list_accounts(self._accounts) if a.name == "Tiny Co")
        self.assertEqual((tiny.domain, tiny.headcount, tiny.location),
                         ("tinyco.example", "12", "Pune, India"))
        self.assertIn("Filled in 1 companies", wb._status.text())

    def test_a_no_to_the_enrichment_spends_nothing(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        wb._confirm_enrich = lambda n: False
        result = _accounts_result(self._tmp, ["Tiny Co"])
        result["settings"] = {"stage": "Cold", "enrich_all": True}
        wb._run_import(result)
        self.assertEqual(wb._jobs, 0)
        self.assertIsNone(wb._enrich_worker)

    def test_enrichment_without_an_exa_key_says_so(self):
        wb = self._WB.LeadsWorkbench({})
        wb._confirm_enrich = lambda n: self.fail("must not ask without a key")
        result = _accounts_result(self._tmp, ["Tiny Co"])
        result["settings"] = {"stage": "Cold", "enrich_all": True}
        wb._run_import(result)
        self.assertIn("Exa API key", wb._status.text())


class SendingMovesContactsToApproaching(_Workbench):
    """Apollo's stage trigger: "Approaching — you have sent the contact at
    least one message". Sending saves the person as a contact (Apollo:
    "Adding prospects to a sequence saves them as contacts") and moves a
    Cold one on; a stage the owner set by hand stands."""

    def test_the_people_sent_to_move_on_from_cold_only(self):
        from addons.leads import contacts as CT
        from prospector.reach import Draft
        wb = self._WB.LeadsWorkbench({})
        a = Lead(name="Asha Rao", company="Rao", email="asha@rao.example")
        b = Lead(name="Bo Lund", company="Lund", email="bo@lund.example")
        wb._keep_as_contacts([a, b], "save")
        CT.set_stage(self._contacts, b, "Interested")
        for c in wb._contacts:
            if c.lead is b:
                c.stage = "Interested"
        drafts = [Draft(dossier=Dossier(lead=a), subject="Hi", body="x", status="sent"),
                  Draft(dossier=Dossier(lead=b), subject="Hi", body="x", status="sent")]
        wb._send_worker = type("W", (), {"drafts": drafts})()
        wb._jobs = 1
        from unittest import mock
        with mock.patch.object(self._WB.QMessageBox, "information"):
            wb._on_sent(["asha@rao.example", "bo@lund.example"], [])
        stages = {c.lead.name: c.stage for c in CT.list_contacts(self._contacts)}
        self.assertEqual(stages, {"Asha Rao": "Approaching", "Bo Lund": "Interested"})
        self.assertEqual({c.lead.name: c.stage for c in wb._contacts}, stages)

    def test_sending_saves_the_people_as_contacts_first(self):
        from addons.leads import contacts as CT
        from prospector.reach import Draft
        wb = self._WB.LeadsWorkbench({})
        a = Lead(name="Asha Rao", company="Rao", email="asha@rao.example")
        drafts = [Draft(dossier=Dossier(lead=a), subject="Hi", body="x")]
        orig = self._WB.LeadsSendWorker
        self._WB.LeadsSendWorker = _FakeSourceWorker
        self.addCleanup(setattr, self._WB, "LeadsSendWorker", orig)
        wb._run_send(drafts)
        [c] = CT.list_contacts(self._contacts)
        self.assertEqual((c.lead.name, c.via), ("Asha Rao", ["sequence"]))


class AnAccountImportIsSearchedInOnePress(_Workbench):
    """Find new people over an Account CSV import asks Exa for people at
    every company not searched yet — one search a company, all of them in one
    press (the owner, 24-Sep-2026: "all at once"; it used to be 50 a press,
    and a hidden cap on a run's calls asked most of them for one role only),
    up to _COMPANIES_PER_PRESS. A company counts as searched once its group
    really was asked, kept on disk so a restart never pays for the same
    companies twice. With no job title or seniority of the owner's own it asks
    for the decision-makers an Indian SME actually has (22-Sep-2026: MD, CEO,
    Founder, Director, Owner — not one vertical's automation heads)."""

    def setUp(self):
        super().setUp()
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        self.addCleanup(setattr, self._WB, "SourceWorker", orig)

    def _imported(self, names, cfg=None, name="companies.xlsx"):
        wb = self._WB.LeadsWorkbench(cfg if cfg is not None else {"exa_api_key": "k"})
        wb._run_import(_accounts_result(self._tmp, names, name=name))
        return wb

    def _press(self, wb, asked=None):
        """Find new people, the worker asking `asked` of the companies it was
        handed (all of them unless told), then the search "finishing" so it
        can be pressed again; the spec the worker was handed."""
        before = len(_FakeSourceWorker.made)
        wb._on_prepare()
        if len(_FakeSourceWorker.made) == before:
            return None
        worker = _FakeSourceWorker.made[-1]
        companies = worker.kwargs.get("companies") or []
        if companies:
            worker.companiesAsked.emit(len(companies) if asked is None else asked)
        wb._jobs = 0
        wb._set_running(False)
        return worker.kwargs["spec"]

    def _handed(self):
        """The companies the last search was handed."""
        return _FakeSourceWorker.made[-1].kwargs.get("companies")

    def _searched(self):
        from addons.leads import imports as IM
        return [h["searched"] for h in IM.list_imports(self._imports, "accounts")]

    def test_the_first_press_asks_for_the_decision_makers_at_the_first_batch(self):
        names = [f"Company {i}" for i in range(1, 6)]
        wb = self._imported(names)
        spec = self._press(wb)
        self.assertEqual(spec["companies"]["include"], names)
        self.assertEqual(spec["seniority"]["include"],
                         list(self._WB._COMPANY_SEARCH_SENIORITY))
        self.assertEqual(spec["job_titles"]["include"], [])
        self.assertEqual(spec["industries"]["include"], [])
        self.assertEqual(spec["account_imports"], [])       # companies, not the id
        _spec, companies, note = self.asked[0]
        self.assertEqual(companies, names)
        self.assertEqual(self._handed(), names)
        self.assertEqual(note, "companies 1–5 of 5 from the import")
        # The session keeps the RAIL's filters: the import, not 5 chips.
        self.assertEqual(wb._next_params["filters"]["account_imports"],
                         wb._filters.spec().account_imports)
        self.assertEqual(self._searched(), [5])

    def test_a_big_import_goes_in_one_press_and_a_stopped_one_carries_on(self):
        from prospector.filters import MAX_FACET_VALUES
        n = MAX_FACET_VALUES * 2 + 10
        names = [f"Company {i}" for i in range(1, n + 1)]
        wb = self._imported(names)
        self.assertIn(f"{n} Exa searches — one per company", wb._find_meta.text())
        # The press stops after its first group (a crash, a closed window):
        # only what was asked counts as searched.
        spec = self._press(wb, asked=MAX_FACET_VALUES)
        self.assertEqual(self._handed(), names)             # every company, one press
        self.assertEqual(spec["companies"]["include"], names[:MAX_FACET_VALUES])
        self.assertEqual(self._searched(), [MAX_FACET_VALUES])
        # A new launch: the position came off disk, not memory.
        again = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        from addons.leads import imports as IM
        head = IM.list_imports(self._imports, "accounts")[0]
        again._filters.set_spec({"account_imports": [head["id"]]})
        self.assertIn(f"companies {MAX_FACET_VALUES + 1}–{n} of {n}", again._find_meta.text())
        self._press(again)
        self.assertEqual(self._handed(), names[MAX_FACET_VALUES:])   # no gaps, no repeats
        self.assertEqual(self._searched(), [n])
        self.assertIn("all searched", IM.label(IM.list_imports(self._imports)[0]))

    def test_the_box_says_exactly_what_the_press_spends(self):
        from unittest import mock
        wb = self._imported([f"Company {i}" for i in range(1, 73)])
        spec, companies, note, _marks = wb._search_spec()
        said = []
        box = self._WB.QMessageBox
        with mock.patch.object(box, "question", side_effect=lambda _p, _t, text, *a, **k:
                               (said.append(text), box.StandardButton.No)[1]):
            self._saved_attrs["_confirm_search"](wb, spec, companies, note)
        self.assertIn("It will run 72 Exa searches: one for each company", said[0])
        self.assertIn("companies 1–72 of 72 from the import", said[0])

    def test_nothing_counts_as_searched_until_it_is_asked(self):
        names = [f"Company {i}" for i in range(1, 6)]
        wb = self._imported(names)
        self._press(wb, asked=0)
        self.assertEqual(self._searched(), [0])             # never asked: never paid
        self._press(wb, asked=2)
        self.assertEqual(self._handed(), names)             # the same five again
        self.assertEqual(self._searched(), [2])

    def test_a_press_asks_at_most_so_many_companies(self):
        self._WB._COMPANIES_PER_PRESS, orig = 3, self._WB._COMPANIES_PER_PRESS
        self.addCleanup(setattr, self._WB, "_COMPANIES_PER_PRESS", orig)
        names = [f"Company {i}" for i in range(1, 6)]
        wb = self._imported(names)
        self._press(wb)
        self.assertEqual(self._handed(), names[:3])
        self._press(wb)
        self.assertEqual(self._handed(), names[3:])
        self.assertEqual(self._searched(), [5])

    def test_once_every_company_is_searched_it_says_so_and_starts_again(self):
        wb = self._imported(["Acme Tooling", "Beta Corp"])
        self._press(wb)
        self.assertIn("starts again from the first", wb._find_meta.text())
        spec = self._press(wb)
        self.assertEqual(spec["companies"]["include"], ["Acme Tooling", "Beta Corp"])
        self.assertIn("starts again from the first", self.asked[-1][2])
        self.assertEqual(self._searched(), [2])

    def test_a_no_to_the_cost_spends_nothing_and_moves_nothing(self):
        self._WB.LeadsWorkbench._confirm_search = lambda _self, *a: False
        wb = self._imported(["Acme Tooling"])
        self.assertIsNone(self._press(wb))
        self.assertEqual(self._searched(), [0])             # free to try again

    def test_two_imports_share_a_batch_without_asking_twice_for_one_company(self):
        from addons.leads import imports as IM
        wb = self._imported(["Acme Tooling", "Beta Corp"], name="a.xlsx")
        wb._run_import(_accounts_result(self._tmp, ["beta corp", "Gamma Inc"],
                                        name="b.xlsx"))
        ids = [h["id"] for h in IM.list_imports(self._imports, "accounts")]
        wb._filters.set_spec({"account_imports": ids})
        spec = self._press(wb)
        got = [c.casefold() for c in spec["companies"]["include"]]
        self.assertEqual(sorted(got), ["acme tooling", "beta corp", "gamma inc"])
        self.assertEqual(self._searched(), [2, 2])

    def test_the_owners_own_titles_are_respected(self):
        wb = self._imported(["Only Co"])
        spec = wb._filters.spec()
        spec.job_titles.include = ["Purchase Head"]
        wb._filters.set_spec(spec)
        got = self._press(wb)
        self.assertEqual(got["job_titles"]["include"], ["Purchase Head"])
        self.assertEqual(got["seniority"]["include"], [])

    def test_the_owners_own_seniority_is_kept(self):
        wb = self._imported(["Only Co"])
        spec = wb._filters.spec()
        spec.seniority.include = ["vp"]
        wb._filters.set_spec(spec)
        self.assertEqual(self._press(wb)["seniority"]["include"], ["vp"])

    def test_the_starter_searchs_one_vertical_titles_are_never_used_for_companies(self):
        """The owner's starter titles name one vertical — digital-
        transformation and automation heads. Asked of a list of small
        Vadodara manufacturers they find nobody, so a search over an account
        import replaces them with the decision-makers, whatever else was
        touched on the rail."""
        wb = self._imported(["Only Co"])
        wb.use_starter("icp")
        spec = wb._filters.spec()
        spec.account_imports = self._searched_ids()
        spec.locations.exclude = ["Pakistan"]               # something else touched
        wb._filters.set_spec(spec)
        got = self._press(wb)
        self.assertEqual(got["job_titles"]["include"], [])
        self.assertEqual(got["industries"]["include"], [])
        self.assertEqual(got["seniority"]["include"],
                         list(self._WB._COMPANY_SEARCH_SENIORITY))
        self.assertEqual(got["locations"]["exclude"], ["Pakistan"])

    def _searched_ids(self):
        from addons.leads import imports as IM
        return [h["id"] for h in IM.list_imports(self._imports, "accounts")]

    def test_a_managing_director_ceo_or_founder_is_not_filtered_out(self):
        # Live report, 22-Sep-2026: a real 50-company batch came back with
        # 2199 people found and 2162 of them thrown out as "outside your
        # filters (seniority)" — only 37 survived. filters.seniority_of()
        # reads "Managing Director", "CEO", "Chairman" and "President" as
        # c_suite, and "Founder"/"Co-Founder" as founder, never as director
        # or owner — exactly the titles a real Indian SME's decision-maker
        # carries.
        from prospector.filters import SearchSpec, match_person
        wb = self._imported(["Only Co"])
        spec = SearchSpec.from_dict(self._press(wb))
        for title in ("Managing Director", "CEO", "Chairman", "President",
                      "Founder", "Co-Founder", "Founder & CEO",
                      "Director", "Owner"):
            lead = Lead(name="P", title=title, company="Only Co")
            self.assertEqual(match_person(spec, lead), "", title)
        # Still not a decision-maker: this widens who counts, not everyone.
        for title in ("Quality Engineer", "Assistant Manager", "Intern"):
            lead = Lead(name="P", title=title, company="Only Co")
            self.assertEqual(match_person(spec, lead), "seniority", title)

    def test_the_page_shows_the_people_prism_holds_at_those_companies(self):
        from prospector.engine import RunResult
        wb = self._imported(["Acme Tooling"])
        at = Lead(name="Ravi Patel", title="Director", company="Acme Tooling Pvt Ltd")
        away = Lead(name="Sara Khan", title="Director", company="Globex")
        wb._show_result(RunResult(dossiers=[], total_in_sheet=2, signal_source="",
                                  all_leads=[at, away]), [])
        ck = wb._cockpit.leads
        self.assertEqual([ck._dossier_at(r).lead.name for r in range(ck._table.rowCount())],
                         ["Ravi Patel"])


class ThePeoplePageIsThePool(_Workbench):
    """Find People over everyone Prism holds (addons/leads/pool.py): saved
    contacts and every past run, one row per person. The owner chose
    (23-Sep-2026) "instant locally, button fetches new": every filter click,
    tab, sort, search and page re-reads what is held and spends nothing;
    only Find new people searches."""

    def _held_run(self, wb, leads, dossiers=(), params=None, sid="s-older",
             when="2026-09-20T10:00:00+05:30"):
        wb._runs[sid] = (sid, when, list(leads), list(dossiers), [], dict(params or {}))
        wb._rebuild_pool()

    @staticmethod
    def _people(n, title="Plant Head", **kw):
        return [Lead(name=f"Person {i:02d}", title=title, company=f"Firm {i:02d}",
                     email=f"p{i}@firm{i}.com", fit_score=50 + i, **kw)
                for i in range(n)]

    def _names(self, wb):
        ck = wb._cockpit.leads
        return [ck._dossier_at(r).lead.name for r in range(ck._table.rowCount())]

    def test_everyone_held_is_on_the_page_split_into_the_three_tabs(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        people = self._people(4)
        saved = CT.Contact(lead=people[0], saved_at="2026-09-21T09:00:00+05:30")
        wb._contacts = [saved]
        self._held_run(wb, people)                       # person 0 is also saved
        ck = wb._cockpit.leads
        self.assertEqual(ck._table.rowCount(), 4)   # nobody listed twice
        self.assertEqual(ck._tab_counts, {"total": 4, "net_new": 3, "saved": 1})
        ck._tab_btns["saved"].click()
        self.assertEqual(self._names(wb), ["Person 00"])
        ck._tab_btns["net_new"].click()
        self.assertEqual(len(self._names(wb)), 3)
        self.assertNotIn("Person 00", self._names(wb))

    def test_a_filter_click_narrows_at_once_and_spends_nothing(self):
        from prospector.filters import SearchSpec
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        self.addCleanup(setattr, self._WB, "SourceWorker", orig)
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        self._held_run(wb, self._people(3)
                  + [Lead(name="Owner Person", title="Owner", company="Solo Co")])
        wb._filters.set_spec(SearchSpec.from_dict({"seniority": {"include": ["owner"]}}))
        self.assertEqual(self._names(wb), ["Owner Person"])
        self.assertEqual(wb._cockpit.leads._tab_counts["total"], 1)
        self.assertEqual(wb._cockpit.leads._filter_count, 1)   # "Hide filters 1"
        self.assertEqual(_FakeSourceWorker.made, [])
        self.assertIsNone(wb._worker)

    def test_twenty_five_to_a_page_and_the_pager_turns_them(self):
        wb = self._WB.LeadsWorkbench({})
        self._held_run(wb, self._people(30))
        ck = wb._cockpit.leads
        self.assertEqual(ck._table.rowCount(), 25)
        self.assertEqual(ck._range_lbl.text(), "1 - 25 of 30")
        ck._next_btn.click()
        self.assertEqual(ck._table.rowCount(), 5)
        self.assertEqual(ck._range_lbl.text(), "26 - 30 of 30")
        self.assertFalse(ck._next_btn.isEnabled())
        wb._filters.set_spec({"job_titles": {"include": ["Plant Head"]}})
        self.assertEqual(ck._range_lbl.text(), "1 - 25 of 30")   # a filter: page 1

    def test_sort_orders_the_whole_pool_before_it_is_paged(self):
        wb = self._WB.LeadsWorkbench({})
        people = self._people(30)
        self._held_run(wb, people)
        ck = wb._cockpit.leads
        self.assertEqual(self._names(wb)[0], "Person 29")       # best fit first
        ck._sort.setCurrentIndex(ck._sort.findData("name"))
        self.assertEqual(self._names(wb)[0], "Person 00")       # A–Z, across pages
        self.assertEqual(ck.sort_key(), "name")

    def test_search_people_narrows_by_name_title_company_or_place(self):
        wb = self._WB.LeadsWorkbench({})
        people = self._people(3)
        people[2].extra["location"] = "Dubai, United Arab Emirates"
        self._held_run(wb, people)
        wb._cockpit.leads._search.setText("dubai")
        wb._cockpit.leads._search_timer.timeout.emit()        # the debounce, run now
        self.assertEqual(self._names(wb), ["Person 02"])
        wb._on_query("firm 01")
        self.assertEqual(self._names(wb), ["Person 01"])

    def test_a_search_never_loses_the_people_it_found_to_its_own_filters(self):
        """Industry, keywords and similar titles only STEER a search, which
        takes whoever comes back — Exa's own industry label, an Apollo tag, a
        "Works Manager" for "Plant Head". The page must show them under the
        same filters, or Find new people "finds 300" and shows twelve."""
        from prospector.filters import SearchSpec
        wb = self._WB.LeadsWorkbench({})
        spec = SearchSpec.from_dict({"job_titles": {"include": ["Plant Head"]},
                                     "industries": {"include": ["Steel Manufacturing"]},
                                     "keywords": {"include": ["rolling mill"]}})
        found = [Lead(name="Asha Rao", title="Works Manager", company="Jindal Co",
                      industry="mining & metals"),
                 Lead(name="Vikram Das", title="GM Operations", company="Tata Co")]
        self._held_run(wb, found, params={"mode": "icp_leads_only",
                                     "filters": spec.to_dict()})
        imported = Lead(name="Imported Person", title="Accountant", company="Other Co")
        from addons.leads import contacts as CT
        wb._contacts = [CT.Contact(lead=imported)]
        wb._rebuild_pool()
        wb._filters.set_spec(spec)
        self.assertEqual(sorted(self._names(wb)), ["Asha Rao", "Vikram Das"])
        # A different industry is a different question: they are not steered
        # by it, and carry nothing that says they match it.
        wb._filters.set_spec({"industries": {"include": ["Pharmaceuticals"]}})
        self.assertEqual(self._names(wb), [])

    def test_save_moves_the_ticked_people_from_net_new_to_saved(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held_run(wb, self._people(3))
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        ck._table.item(1, 0).setCheckState(Qt.Checked)
        ck._b_contact.click()
        self.assertEqual(len(CT.list_contacts(self._contacts)), 2)
        self.assertEqual(ck._tab_counts, {"total": 3, "net_new": 1, "saved": 2})
        self.assertIn("Saved 2 as contacts", wb._status.text())

    def test_exporting_someone_saves_them_as_apollo_does(self):
        from unittest import mock
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held_run(wb, self._people(2))
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        out = os.path.join(self._tmp, "picked.csv")
        with mock.patch.object(self._WB.QFileDialog, "getSaveFileName",
                               return_value=(out, "")), \
                mock.patch.object(self._WB.QMessageBox, "information"):
            ck._b_export.click()
        self.assertTrue(os.path.exists(out))
        self.assertEqual([c.via for c in CT.list_contacts(self._contacts)], [["export"]])
        self.assertEqual(ck._tab_counts["saved"], 1)

    def test_an_opened_session_shows_only_its_people_until_show_everyone(self):
        from addons.leads import sessions
        wb = self._WB.LeadsWorkbench({})
        self._held_run(wb, self._people(3), sid="s-other")
        first = self._WB.LeadsWorkbench({})
        self._finished(first)
        loaded = sessions.load(self._sessions, first._session_id)
        wb._apply_session(loaded, scope=True)
        self.assertEqual(sorted(self._names(wb)), ["Kunyi", "Vaibhav"])
        self.assertFalse(wb._scope_btn.isHidden())
        wb._scope_btn.click()
        self.assertEqual(len(self._names(wb)), 5)
        self.assertTrue(wb._scope_btn.isHidden())

    def test_the_pool_worker_reads_every_contact_and_every_run(self):
        from addons.leads import contacts as CT
        from addons.leads.workers import LeadsPoolWorker
        first = self._WB.LeadsWorkbench({})
        self._finished(first)
        CT.save(self._contacts, [Lead(name="Held One", company="Held Co",
                                      email="h@held.com")], via="save")
        got = []
        w = LeadsPoolWorker(self._contacts, self._sessions)
        w.done.connect(lambda contacts, runs: got.append((contacts, runs)))
        w.failed.connect(lambda msg: got.append(msg))
        w.run()                                              # inline: no thread
        contacts, runs = got[0]
        self.assertEqual([c.lead.name for c in contacts], ["Held One"])
        self.assertEqual(len(runs), 1)
        sid, when, leads, dossiers, drafts, params = runs[0]
        self.assertEqual(sid, first._session_id)
        self.assertEqual(len(leads), 2)
        self.assertEqual(params["mode"], "sheet")
        wb = self._WB.LeadsWorkbench({})
        wb._on_pool_loaded(contacts, runs)
        self.assertEqual(wb._cockpit.leads._tab_counts, {"total": 3, "net_new": 2,
                                                          "saved": 1})

    def test_the_run_on_screen_keeps_its_own_objects_when_the_pool_arrives(self):
        """The workers verify and enrich the run on screen IN PLACE; a copy of
        it read from disk must not replace it in the page."""
        from addons.leads.workers import LeadsPoolWorker
        wb = self._WB.LeadsWorkbench({})
        res, _drafts = self._finished(wb)
        got = []
        w = LeadsPoolWorker(self._contacts, self._sessions)
        w.done.connect(lambda contacts, runs: got.append((contacts, runs)))
        w.run()
        wb._on_pool_loaded(*got[0])
        ck = wb._cockpit.leads
        on_screen = {id(ck._dossier_at(r).lead) for r in range(ck._table.rowCount())}
        self.assertEqual(on_screen, {id(l) for l in res.all_leads})


class SelectionAcrossPages(_Workbench):
    """Apollo's selection over a result that runs to many pages (knowledge.
    apollo.io "Search for People"): tick people on one page, go on to the
    next, and they stay picked; Bulk Selection offers "Select this page",
    "Select all" and "Select number of people" with "Max people per
    company"; every action acts on everyone picked, on every page. A new
    search starts with nobody picked."""

    def _held(self, wb, n=60, companies=None):
        people = [Lead(name=f"Person {i:02d}", title="Plant Head",
                       company=(companies[i] if companies else f"Firm {i:02d}"),
                       email=f"p{i}@firm{i}.com", fit_score=100 - i) for i in range(n)]
        wb._runs["s1"] = ("s1", "2026-09-23T10:00:00+05:30", people, [], [], {})
        wb._rebuild_pool()
        return people

    @staticmethod
    def _names(rows):
        return [d.lead.name for d in rows]

    def test_ticks_stay_when_the_page_turns(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        ck._table.item(1, 0).setCheckState(Qt.Checked)
        ck._next_btn.click()
        self.assertEqual(ck._sel_lbl.text(), "2 selected")
        self.assertEqual(ck._head.check_state(), Qt.Unchecked)   # this page: none
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertEqual(self._names(ck.selected()), ["Person 00", "Person 01", "Person 25"])
        ck._prev_btn.click()
        ticked = [r for r in range(ck._table.rowCount())
                  if ck._table.item(r, 0).checkState() == Qt.Checked]
        self.assertEqual(ticked, [0, 1])
        self.assertEqual(ck._head.check_state(), Qt.PartiallyChecked)

    def test_select_all_is_everyone_on_every_page(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertEqual(ck._sel_all.text(), "Select all 60")
        ck._sel_all.click()
        self.assertEqual(len(ck.selected()), 60)
        self.assertEqual(ck._sel_lbl.text(), "60 selected")
        self.assertEqual(ck._head.check_state(), Qt.Checked)
        ck._bulk_clear.click()                              # every page, not one
        self.assertEqual(ck.selected(), [])
        ck._next_btn.click()
        self.assertEqual(ck.selected(), [])

    def test_bulk_selection_a_number_at_most_so_many_per_company(self):
        wb = self._WB.LeadsWorkbench({})
        firms = ["Acme Pvt Ltd", "Acme", "Beta", "ACME Ltd.", "Gamma", "Beta", "Delta"] * 5
        self._held(wb, n=35, companies=firms)
        ck = wb._cockpit.leads
        pop = ck._bulk_select
        pop.number.setValue(4)
        pop.per_company.setValue(1)
        pop.apply_btn.click()
        picked = ck.selected()
        self.assertEqual([d.lead.company for d in picked], ["Acme Pvt Ltd", "Beta", "Gamma",
                                                            "Delta"])
        pop.pageRequested.emit()                            # Select this page (25)
        self.assertEqual(len(ck.selected()), 25)
        pop.clearRequested.emit()
        self.assertEqual(ck.selected(), [])

    def test_the_header_caret_opens_bulk_selection_with_its_counts(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        head = ck._head
        caret = head._caret_rect(head._tick_section())
        QApplication.sendEvent(head.viewport(), QMouseEvent(
            QEvent.MouseButtonPress, QPointF(caret.center()),
            QPointF(head.viewport().mapToGlobal(caret.center())),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        self.addCleanup(ck._bulk_select.hide)
        self.assertTrue(ck._bulk_select.isVisible())
        self.assertEqual(ck._bulk_select.page_btn.text(), "Select this page (25)")
        self.assertEqual(ck._bulk_select.all_btn.text(), "Select all (60)")
        self.assertEqual(ck.selected(), [])                 # opening ticks nothing

    def test_a_new_search_starts_with_nobody_picked_a_sort_or_page_keeps_them(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        wb._on_sort("name")
        self.assertEqual(len(ck.selected()), 1)
        wb._on_page(1)
        self.assertEqual(len(ck.selected()), 1)
        wb._filters.set_spec({"job_titles": {"include": ["Plant Head"]}})
        self.assertEqual(ck.selected(), [])
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        wb._on_query("person 0")
        self.assertEqual(ck.selected(), [])

    def test_every_action_gets_everyone_picked_on_every_page(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        got = []
        wb._cockpit.saveListRequested.disconnect()
        wb._cockpit.saveListRequested.connect(got.append)
        ck._table.item(3, 0).setCheckState(Qt.Checked)
        ck._next_btn.click()
        ck._table.item(4, 0).setCheckState(Qt.Checked)
        ck._b_save.click()
        self.assertEqual(self._names(got[0]), ["Person 03", "Person 29"])

    def test_a_save_keeps_the_selection(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb, n=3)
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        ck._b_contact.click()                   # the pool is rebuilt under it
        self.assertEqual(self._names(ck.selected()), ["Person 00"])


class SetStageAndTheRecordFilters(_Workbench):
    """Apollo's Edit > Set stage on the people picked, and the Stage, Lists
    and Custom fields filters over the owner's own records, end to end."""

    def _held(self, wb, n=3):
        people = [Lead(name=f"Person {i}", title="Owner", company=f"Firm {i}",
                       email=f"p{i}@firm{i}.com") for i in range(n)]
        wb._runs["s1"] = ("s1", "2026-09-23T10:00:00+05:30", people, [], [], {})
        wb._rebuild_pool()
        return people

    def _names(self, wb):
        ck = wb._cockpit.leads
        return sorted(ck._dossier_at(r).lead.name for r in range(ck._table.rowCount()))

    def _set_stage(self, wb, stage):
        ck = wb._cockpit.leads
        [act] = [a for a in ck._stage_menu.actions() if a.text() == stage]
        act.trigger()

    def test_set_stage_saves_the_people_first_then_moves_them(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        self.assertFalse(ck._b_stage.isEnabled())           # nobody picked
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        ck._table.item(1, 0).setCheckState(Qt.Checked)
        self.assertTrue(ck._b_stage.isEnabled())
        self._set_stage(wb, "Interested")
        stages = {c.lead.name: c.stage for c in CT.list_contacts(self._contacts)}
        self.assertEqual(stages, {"Person 0": "Interested", "Person 1": "Interested"})
        self.assertIn("Moved 2 to Interested", wb._status.text())
        self.assertEqual(ck._tab_counts["saved"], 2)

    def test_the_stage_filter_shows_who_is_at_a_stage(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        ck._table.item(0, 0).setCheckState(Qt.Checked)
        self._set_stage(wb, "Do Not Contact")
        wb._filters.set_spec({"contact_stages": {"exclude": ["Do Not Contact"]}})
        self.assertEqual(self._names(wb), ["Person 1", "Person 2"])
        wb._filters.set_spec({"contact_stages": {"include": ["Do Not Contact"]}})
        self.assertEqual(self._names(wb), ["Person 0"])

    def test_a_list_added_to_is_offered_and_filters(self):
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        wb._keep_as_contacts(people[:2], "list", list_name="Expo leads")
        self.assertEqual(wb._filters._records["contact_lists"], ["Expo leads"])
        wb._filters.set_spec({"contact_lists": {"include": ["Expo leads"]}})
        self.assertEqual(self._names(wb), ["Person 0", "Person 1"])

    def test_an_account_stage_reads_the_saved_accounts(self):
        from addons.leads import accounts as AC
        AC.save(self._accounts, [{"name": "Firm 1", "website": "firm1.com",
                                  "stage": "Current Client"}],
                via="import", stage_of=lambda c: c.get("stage"))
        wb = self._WB.LeadsWorkbench({})
        wb._reload_accounts()
        self._held(wb)
        wb._filters.set_spec({"account_stages": {"include": ["Current Client"]}})
        self.assertEqual(self._names(wb), ["Person 1"])

    def test_an_imported_column_becomes_a_custom_field(self):
        wb = self._WB.LeadsWorkbench({})
        a = Lead(name="Asha Rao", company="Rao Works", email="asha@rao.example")
        a.extra["custom"] = {"Lead Quality": "A"}
        b = Lead(name="Bo Lund", company="Lund Steel", email="bo@lund.example")
        b.extra["custom"] = {"Lead Quality": "C"}
        wb._run_import(_contacts_result(self._tmp, [a, b]))
        panel = wb._filters
        self.assertEqual(panel._records["custom"]["contact"]["Lead Quality"], ["A", "C"])
        panel.set_spec({"custom_fields": {"contact:Lead Quality": ["A"]}})
        self.assertEqual(self._names(wb), ["Asha Rao"])

    def test_pinned_filters_are_kept_between_sessions(self):
        saved = {}
        wb = self._WB.LeadsWorkbench({"leads_pinned_filters": ["lists", "job_titles"]})
        self.assertEqual(wb._filters.pinned(), ["job_titles", "lists"])
        self.assertFalse(wb._filters._sections["lists"].isHidden())
        wb._save_cfg = lambda name, value: saved.__setitem__(name, value)   # no real config

        def pin_stage(dlg):
            dlg.panel._pin_btns["stages"].setChecked(True)
            return True
        wb._filters._ask = pin_stage
        wb._filters._more_btn.click()
        self.assertEqual(saved["leads_pinned_filters"], ["job_titles", "lists", "stages"])

    def test_the_pool_worker_hands_the_saved_accounts_first(self):
        from addons.leads import accounts as AC
        from addons.leads.workers import LeadsPoolWorker
        AC.save(self._accounts, [{"name": "Firm 1", "website": "firm1.com"}], via="import")
        got = []
        w = LeadsPoolWorker(self._contacts, self._sessions, self._accounts)
        w.accounts_read.connect(lambda accounts: got.append(("accounts", accounts)))
        w.done.connect(lambda contacts, runs: got.append(("done", contacts)))
        w.run()
        self.assertEqual([kind for kind, _v in got], ["accounts", "done"])
        self.assertEqual([a.name for a in got[0][1]], ["Firm 1"])


class RemoveTakesThemOffTheList(_Workbench):
    """The owner, 23-Sep-2026: "still can't clear the selected people". Clear
    only ever unticked — the recorder showed it working — and what he wanted
    was the people GONE. He chose "Remove from list": out of Total, Net New
    and Saved, out of new searches, restorable, nothing deleted
    (addons/leads/removed.py). End to end, through the real buttons."""

    def _held(self, wb, n=3):
        people = [Lead(name=f"Person {i}", title="Owner", company=f"Firm {i}",
                       email=f"p{i}@firm{i}.com") for i in range(n)]
        wb._runs["s1"] = ("s1", "2026-09-23T10:00:00+05:30", people, [], [], {})
        wb._rebuild_pool()
        return people

    def _names(self, wb):
        ck = wb._cockpit.leads
        return sorted(ck._dossier_at(r).lead.name for r in range(ck._table.rowCount()))

    def _tick(self, wb, *names):
        ck = wb._cockpit.leads
        for r in range(ck._table.rowCount()):
            if ck._dossier_at(r).lead.name in names:
                ck._table.item(r, 0).setCheckState(Qt.Checked)

    def _remove(self, wb, *names, answer=True):
        asked = []
        wb._confirm_remove = lambda n: (asked.append(n), answer)[1]
        self._tick(wb, *names)
        wb._cockpit.leads._b_remove.click()
        return asked

    def _gone(self):
        from addons.leads import removed as RM
        return sorted(r.name for r in RM.list_removed(self._removed))

    def test_remove_takes_them_off_every_tab_and_off_the_page(self):
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        wb._keep_as_contacts([people[2]], "save")             # one of them is Saved
        ck = wb._cockpit.leads
        asked = self._remove(wb, "Person 0", "Person 2")
        self.assertEqual(asked, [2])                          # it asked first
        self.assertEqual(self._names(wb), ["Person 1"])
        self.assertEqual((ck._tab_counts["total"], ck._tab_counts["net_new"],
                          ck._tab_counts["saved"]), (1, 1, 0))
        self.assertEqual(self._gone(), ["Person 0", "Person 2"])
        self.assertEqual(ck.selected(), [])                   # nobody left picked
        self.assertFalse(ck._bulk_open)
        self.assertEqual(wb._status.text(), "Removed 2 from the list.")
        self.assertFalse(wb._undo_btn.isHidden())
        self.assertFalse(ck._removed_link.isHidden())
        self.assertEqual(ck._removed_link.text(), "2 removed · Restore")

    def test_nothing_is_deleted_the_contact_stays_on_file(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        wb._keep_as_contacts([people[0]], "save")
        self._remove(wb, "Person 0")
        self.assertEqual([c.lead.name for c in CT.list_contacts(self._contacts)],
                         ["Person 0"])

    def test_saying_no_removes_nobody(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        self._remove(wb, "Person 1", answer=False)
        self.assertEqual(self._names(wb), ["Person 0", "Person 1", "Person 2"])
        self.assertEqual(self._gone(), [])
        self.assertEqual(len(wb._cockpit.leads.selected()), 1)   # still picked

    def test_undo_puts_them_straight_back(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        self._remove(wb, "Person 1")
        wb._undo_btn.click()
        self.assertEqual(self._names(wb), ["Person 0", "Person 1", "Person 2"])
        self.assertEqual(self._gone(), [])
        self.assertEqual(wb._status.text(), "Put 1 back on the list.")
        self.assertTrue(wb._undo_btn.isHidden())              # one Undo per Remove
        self.assertTrue(wb._cockpit.leads._removed_link.isHidden())

    def test_undo_retires_with_the_next_message(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        self._remove(wb, "Person 1")
        wb._status.setText("Something else happened.")
        self.assertTrue(wb._undo_btn.isHidden())

    def test_restore_brings_a_saved_contact_back_as_it_stood(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        wb._keep_as_contacts([people[0]], "save")
        CT.set_stage(self._contacts, people[0], "Interested")
        wb._contacts = CT.list_contacts(self._contacts)
        wb._rebuild_pool()
        self._remove(wb, "Person 0")
        shown = []
        wb._restore_dialog = lambda records: (shown.append([r.name for r in records]),
                                              [r.id for r in records])[1]
        wb._cockpit.leads._removed_link.click()               # "1 removed · Restore"
        self.assertEqual(shown, [["Person 0"]])
        self.assertEqual(self._names(wb), ["Person 0", "Person 1", "Person 2"])
        ck = wb._cockpit.leads
        self.assertEqual(ck._tab_counts["saved"], 1)
        wb._filters.set_spec({"contact_stages": {"include": ["Interested"]}})
        self.assertEqual(self._names(wb), ["Person 0"])       # the stage came back too

    def test_the_real_removed_window_path_runs(self):
        """_restore_dialog used QDialog without importing it, so the moment the
        Removed window closed it raised NameError and nothing was restored.
        Every other test replaces _restore_dialog, which is why none saw it."""
        from PySide6.QtWidgets import QDialog
        from unittest import mock
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)

        class _Window:
            def __init__(self, records, parent=None):
                self.records = records
            def exec(self):
                return self.result
            def chosen_ids(self):
                return [r.id for r in self.records]

        records = [mock.Mock(id="a"), mock.Mock(id="b")]
        with mock.patch("addons.leads.removed_dialog.RemovedDialog", _Window):
            _Window.result = QDialog.Accepted
            self.assertEqual(wb._restore_dialog(records), ["a", "b"])
            _Window.result = QDialog.Rejected
            self.assertEqual(wb._restore_dialog(records), [])

    def test_closing_the_removed_window_restores_nobody(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        self._remove(wb, "Person 0")
        wb._restore_dialog = lambda records: []
        wb._open_removed()
        self.assertEqual(self._gone(), ["Person 0"])

    def test_the_open_person_goes_with_them(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        row = next(r for r in range(ck._table.rowCount())
                   if ck._dossier_at(r).lead.name == "Person 1")
        ck._table.setCurrentCell(row, 1)
        self.assertFalse(ck._drawer_w.isHidden())
        self._remove(wb, "Person 1")
        self.assertTrue(ck._drawer_w.isHidden())

    def test_clear_selection_only_unticks(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        self.assertEqual(ck._bulk_clear.text(), "Clear selection")
        self._tick(wb, "Person 0", "Person 1")
        ck._bulk_clear.click()
        self.assertEqual(ck.selected(), [])
        self.assertEqual(self._names(wb), ["Person 0", "Person 1", "Person 2"])
        self.assertEqual(self._gone(), [])

    def test_remove_stays_usable_while_a_job_runs(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        ck = wb._cockpit.leads
        self._tick(wb, "Person 0")
        wb._set_running(True)
        self.assertTrue(ck._b_remove.isEnabled())             # a local write, like Save
        self.assertFalse(ck._b_export.isEnabled())
        wb._set_running(False)

    def test_send_all_leaves_them_out(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        from prospector.reach import Draft
        kunyi, vaibhav = res.dossiers
        wb._drafts = [Draft(dossier=kunyi, subject="Hi", body="Hello"),
                      Draft(dossier=vaibhav, subject="Hi", body="Hello")]
        from addons.leads import removed as RM
        RM.remove(self._removed, [kunyi.lead])
        wb._reload_removed()
        self.assertEqual([d.dossier.lead.name for d in wb._sendable(wb._drafts)],
                         ["Vaibhav"])

    def test_export_sheets_leave_them_out(self):
        wb = self._WB.LeadsWorkbench({})
        res, drafts = self._run()
        wb._res, wb._drafts = res, drafts
        from addons.leads import removed as RM
        RM.remove(self._removed, [res.dossiers[0].lead])
        wb._reload_removed()
        made = []

        class _Export:
            def __init__(self, leads, dossiers, folder):
                made.append(([l.name for l in leads], [d.lead.name for d in dossiers]))
                self.progress = self.done = self.failed = _FakeSignal()

            def start(self):
                pass
        orig = self._WB.LeadsExportWorker
        self._WB.LeadsExportWorker = _Export
        try:
            wb._start_export(self._tmp, announce=False)
        finally:
            self._WB.LeadsExportWorker = orig
        self.assertEqual(made, [(["Vaibhav"], ["Vaibhav"])])

    def test_a_new_search_is_told_who_to_skip(self):
        _FakeSourceWorker.made = []
        orig = self._WB.SourceWorker
        self._WB.SourceWorker = _FakeSourceWorker
        try:
            wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
            wb._filters.set_spec({"job_titles": {"include": ["Plant Head"]}})
            wb._on_prepare()
        finally:
            self._WB.SourceWorker = orig
        self.assertEqual(_FakeSourceWorker.made[0].kwargs["removed_dir"], self._removed)

    def test_an_import_naming_a_removed_person_brings_them_back(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        self._remove(wb, "Person 0")
        again = Lead(name="Person 0", company="Firm 0", email="p0@firm0.com")
        wb._run_import(_contacts_result(self._tmp, [again]))
        self.assertEqual(self._gone(), [])
        self.assertIn("1 back from Removed", wb._status.text())

    def test_the_pool_worker_hands_the_removed_before_everyone(self):
        from addons.leads import removed as RM
        from addons.leads.workers import LeadsPoolWorker
        RM.remove(self._removed, [Lead(name="Person 0", company="Firm 0",
                                       email="p0@firm0.com")])
        got = []
        w = LeadsPoolWorker(self._contacts, self._sessions, self._accounts, self._removed)
        w.removed_read.connect(lambda records: got.append(("removed", records)))
        w.done.connect(lambda contacts, runs: got.append(("done", contacts)))
        w.run()
        self.assertEqual([kind for kind, _v in got], ["removed", "done"])
        self.assertEqual([r.name for r in got[0][1]], ["Person 0"])


class ThePersonPanelActsOnTheStores(_Workbench):
    """Apollo's contact profile, end to end: a row opens the person's panel
    with what the stores hold about them, and every act on it lands in the
    stores — someone not saved yet is saved first — and on the page."""

    def _held(self, wb):
        people = [Lead(name="Asha Rao", title="Owner", company="Rao Works",
                       email="asha@rao.example"),
                  Lead(name="Bo Rao", title="CFO", company="Rao Works",
                       email="bo@rao.example"),
                  Lead(name="Cy Lund", title="CEO", company="Lund Steel",
                       email="cy@lund.example")]
        wb._runs["s1"] = ("s1", "2026-09-22T10:00:00+05:30", people, [], [],
                          {"mode": "icp_leads_only",
                           "filters": {"job_titles": {"include": ["Owner"]}}})
        wb._rebuild_pool()
        return people

    def _open(self, wb, name):
        ck = wb._cockpit.leads
        for r in range(ck._table.rowCount()):
            if ck._dossier_at(r).lead.name == name:
                ck._table.setCurrentCell(r, 1)
                return ck.person_panel
        self.fail(f"{name} is not on the page")

    def test_a_row_opens_what_the_stores_hold_about_them(self):
        from addons.leads.person import activities
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        view = panel.view
        self.assertIsNone(view.contact)                       # not saved yet
        self.assertEqual([p.lead.name for p in view.colleagues], ["Bo Rao"])
        self.assertEqual([a["text"] for a in activities(view)],
                         ["Found by a search: 1 title · Anywhere"])

    def test_a_stage_from_the_panel_saves_them_first_then_moves_them(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        panel.stage.setCurrentIndex(panel.stage.findData("Interested"))
        panel.stage.activated.emit(panel.stage.currentIndex())
        [c] = CT.list_contacts(self._contacts)
        self.assertEqual((c.lead.name, c.stage), ("Asha Rao", "Interested"))
        self.assertEqual([h["kind"] for h in c.history], ["saved", "stage"])
        self.assertEqual(panel.view.contact.stage, "Interested")   # drawn again
        wb._filters.set_spec({"contact_stages": {"include": ["Interested"]}})
        ck = wb._cockpit.leads
        self.assertEqual([ck._dossier_at(r).lead.name for r in range(ck._table.rowCount())],
                         ["Asha Rao"])

    def test_notes_tasks_and_logged_calls_land_in_activities(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        panel = self._open(wb, "Cy Lund")
        panel.noteRequested.emit(people[2], "Met at the expo")
        panel.taskRequested.emit(people[2], "Send the brochure", "2026-09-30")
        panel.logRequested.emit(people[2], "call", "Wants a quote")
        c = CT.get(self._contacts, people[2])
        self.assertEqual([n["text"] for n in c.notes], ["Met at the expo"])
        self.assertEqual([(t["text"], t["due"]) for t in c.tasks],
                         [("Send the brochure", "2026-09-30")])
        lines = [a["text"] for a in __import__("addons.leads.person",
                                               fromlist=["activities"]).activities(panel.view)]
        self.assertIn("Call logged: Wants a quote", lines)
        self.assertIn("Note: Met at the expo", lines)
        panel.taskDoneRequested.emit(people[2], c.tasks[0]["id"], True)
        self.assertTrue(CT.get(self._contacts, people[2]).tasks[0]["done"])

    def test_edit_contact_info_changes_the_record_and_the_page(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        panel.ask_edit = lambda values: {"title": "Managing Director"}
        panel._act_edit.trigger()
        self.assertEqual(CT.get(self._contacts, panel.view.lead).lead.title,
                         "Managing Director")
        ck = wb._cockpit.leads
        titles = {ck._dossier_at(r).lead.name: ck._dossier_at(r).lead.title
                  for r in range(ck._table.rowCount())}
        self.assertEqual(titles["Asha Rao"], "Managing Director")
        self.assertEqual(panel.role.text(), "Managing Director at Rao Works")

    def test_flag_as_inaccurate_is_bad_data(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        people = self._held(wb)
        panel = self._open(wb, "Bo Rao")
        panel._act_flag.trigger()
        c = CT.get(self._contacts, people[1])
        self.assertEqual(c.stage, "Bad Data")
        self.assertIn("flagged", [h["kind"] for h in c.history])

    def test_delete_contact_leaves_someone_found_as_net_new(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        panel.saveRequested.emit(panel.view.lead)
        self.assertEqual(wb._cockpit.leads._tab_counts["saved"], 1)
        panel.confirm_delete = lambda name: True
        panel._act_delete.trigger()
        self.assertEqual(CT.list_contacts(self._contacts), [])
        self.assertEqual(wb._cockpit.leads._tab_counts, {"total": 3, "net_new": 3,
                                                         "saved": 0})
        self.assertIsNone(panel.view.contact)                 # still open, net new

    def test_the_account_side(self):
        from addons.leads import accounts as AC
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Cy Lund")
        self.assertIsNone(panel.view.account)
        panel.accountSaveRequested.emit(panel.view.lead)
        [acc] = AC.list_accounts(self._accounts)
        self.assertEqual((acc.name, acc.domain), ("Lund Steel", "lund.example"))
        self.assertEqual(panel.view.account.name, "Lund Steel")
        panel.accountStageRequested.emit(panel.view.account, "Active Opportunity")
        self.assertEqual(AC.list_accounts(self._accounts)[0].stage, "Active Opportunity")
        self.assertEqual(panel.account_stage.currentData(), "Active Opportunity")

    def test_a_colleague_opens_in_the_same_panel(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        panel.personPicked.emit(panel.view.colleagues[0])
        self.assertEqual(panel.name.text(), "Bo Rao")

    def test_enrichment_runs_the_picks_one_after_another(self):
        wb = self._WB.LeadsWorkbench({})
        self._held(wb)
        panel = self._open(wb, "Asha Rao")
        ran = []

        def email(dossiers):
            ran.append(("email", dossiers[0].lead.name))
            wb._jobs = 1                                    # it started a job

        wb._find_emails = email
        wb._qualify_selected = lambda dossiers: ran.append(("qualify", dossiers[0].lead.name))
        panel.enrichRequested.emit(panel.view.row, ["qualify", "email"])
        self.assertEqual(ran, [("email", "Asha Rao")])      # e-mail first, then waits
        wb._jobs = 0
        wb._after_job()                                     # the job's end moves it on
        self.assertEqual(ran, [("email", "Asha Rao"), ("qualify", "Asha Rao")])

    def test_a_send_is_logged_in_their_activities(self):
        from addons.leads import contacts as CT
        from prospector.reach import Draft
        from unittest import mock
        wb = self._WB.LeadsWorkbench({})
        a = Lead(name="Asha Rao", company="Rao", email="asha@rao.example")
        wb._keep_as_contacts([a], "save")
        drafts = [Draft(dossier=Dossier(lead=a), subject="Your second plant", body="x",
                        status="sent")]
        wb._send_worker = type("W", (), {"drafts": drafts})()
        wb._jobs = 1
        with mock.patch.object(self._WB.QMessageBox, "information"):
            wb._on_sent(["asha@rao.example"], [])
        c = CT.get(self._contacts, a)
        self.assertIn(("sent", "Your second plant"),
                      [(h["kind"], h["text"]) for h in c.history])
        self.assertEqual(c.stage, "Approaching")


class _FakeQualifyWorker(_FakeSourceWorker):
    """Stands in for LeadsQualifyWorker: records the leads it was handed."""
    made: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _FakeQualifyWorker.made.append(self)


class QualifySelected(_Workbench):
    """Tick people a run sourced but never qualified and press Qualify & draft:
    the qualify pass runs on exactly them, their rows turn into real outcomes,
    their drafts join Send, and the session is saved with them."""

    def _leads_only_run(self, wb, n=4):
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i}", title="Plant Head", company=f"Co {i}",
                      email=f"p{i}@x.com", fit_score=60 + i) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="",
                        all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "roles": ["Plant Head"],
                           "offer": "Automation retrofits"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, cockpit, leads):
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead in leads:
                cockpit._table.item(r, 0).setCheckState(Qt.Checked)

    def test_the_button_arms_only_for_unqualified_rows(self):
        d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        other = Lead(name="Vaibhav", title="Plant Head", company="Globex", fit_score=50)
        c = CK.LeadsCockpit()
        c.set_dossiers([d1], all_leads=[d1.lead, other])
        self.assertFalse(c._b_qualify.isHidden())
        self._tick(c, [d1.lead])
        self.assertFalse(c._b_qualify.isEnabled())       # already qualified
        self._tick(c, [other])
        self.assertTrue(c._b_qualify.isEnabled())
        got = []
        c.qualifyRequested.connect(got.append)
        c._b_qualify.click()
        self.assertEqual({d.lead.name for d in got[0]}, {"Kunyi", "Vaibhav"})

    def test_the_button_hides_when_everyone_is_qualified(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])
        self.assertTrue(c._b_qualify.isHidden())

    def test_only_the_unqualified_people_go_to_the_worker(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        wb._confirm_qualify = lambda n: True
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        try:
            self._tick(wb._cockpit.leads, leads[:2])
            wb._qualify_selected(wb._cockpit.leads.selected())
        finally:
            self._WB.LeadsQualifyWorker = orig
        self.assertEqual(len(_FakeQualifyWorker.made), 1)
        worker = _FakeQualifyWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual({l.name for l in worker.args[0]}, {"P0", "P1"})
        self.assertEqual(worker.kwargs["roles"], ["Plant Head"])
        self.assertEqual(wb._jobs, 1)

    def test_a_big_batch_asks_first_and_a_no_starts_nothing(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb, n=12)
        wb._confirm_qualify = lambda n: False
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        try:
            self._tick(wb._cockpit.leads, leads)
            wb._qualify_selected(wb._cockpit.leads.selected())
        finally:
            self._WB.LeadsQualifyWorker = orig
        self.assertEqual(_FakeQualifyWorker.made, [])
        self.assertEqual(wb._jobs, 0)

    def test_results_fold_into_the_run_and_the_session(self):
        from addons.leads import sessions
        from prospector.engine import RunResult
        from prospector.reach import Draft
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        hot = Dossier(lead=leads[0], verdict="hot", score=90, opener="Hi P0")
        cold = Dossier(lead=leads[1], verdict="cold", score=20)
        wb._jobs = 1
        wb._on_qualified(RunResult(dossiers=[hot, cold], total_in_sheet=2,
                                   signal_source="", all_leads=[leads[0], leads[1]]),
                         [Draft(dossier=hot, subject="Hi", body="Hello P0")])
        cockpit = wb._cockpit.leads
        self.assertEqual(cockpit._table.rowCount(), 4)            # nobody listed twice
        still = {cockpit._dossier_at(r).lead.name for r in range(4)
                 if cockpit._dossier_at(r).status == CK.UNQUALIFIED}
        self.assertEqual(still, {"P2", "P3"})
        self.assertTrue(wb._send_btn.isEnabled())
        self.assertEqual(wb._jobs, 0)
        head = sessions.list_sessions(self._sessions)[0]
        self.assertEqual((head["counts"]["qualified"], head["counts"]["drafted"]), (2, 1))
        self.assertEqual(head["mode"], "icp")        # no longer a leads-sheet-only run

    def _patched_worker(self):
        _FakeQualifyWorker.made = []
        orig = self._WB.LeadsQualifyWorker
        self._WB.LeadsQualifyWorker = _FakeQualifyWorker
        self.addCleanup(setattr, self._WB, "LeadsQualifyWorker", orig)

    def test_without_a_groq_key_nothing_starts_and_it_says_so(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._leads_only_run(wb)
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:1])
        wb._qualify_selected(wb._cockpit.leads.selected())
        self.assertEqual(_FakeQualifyWorker.made, [])
        self.assertIn("Groq key", wb._status.text())
        self.assertEqual(wb._jobs, 0)

    def test_a_failed_pass_is_not_stored_as_qualified_and_stays_retryable(self):
        from addons.leads import sessions
        from prospector.engine import RunResult
        from prospector.models import NO_MODEL
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        failed = [Dossier(lead=l, status=NO_MODEL, note="No Groq API key configured.")
                  for l in leads[:2]]
        wb._jobs = 1
        wb._on_qualified(RunResult(dossiers=failed, total_in_sheet=2,
                                   signal_source="", all_leads=leads[:2]), [])
        cockpit = wb._cockpit.leads
        self.assertEqual(cockpit._table.rowCount(), 4)
        self.assertTrue(all(cockpit._dossier_at(r).status == CK.UNQUALIFIED
                            for r in range(4)))
        self.assertIn("couldn't be qualified", wb._status.text())
        head = sessions.list_sessions(self._sessions)[0]
        self.assertEqual((head["mode"], head["counts"]["qualified"]),
                         ("icp_leads_only", 0))
        self._tick(cockpit, leads[:2])
        self.assertTrue(cockpit._b_qualify.isEnabled())       # try again

    def test_a_retry_that_works_replaces_the_failed_dossier(self):
        from prospector.engine import RunResult
        from prospector.models import QUALIFY_ERROR
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        good = _dos("Kunyi", 96, "k@x.com", "valid")
        broken = _dos("Vaibhav", 80, "v@x.com", "")
        broken.status, broken.note = QUALIFY_ERROR, "Groq rate limit"
        wb._start_export = lambda *a, **k: None
        wb._next_mode, wb._next_params = "icp", {"mode": "icp", "roles": ["Founder"]}
        wb._jobs = 1
        wb._on_prepared(RunResult(dossiers=[good, broken], total_in_sheet=2,
                                  signal_source="", all_leads=[good.lead, broken.lead]), [])
        cockpit = wb._cockpit.leads
        self._tick(cockpit, [broken.lead])
        self.assertTrue(cockpit._b_qualify.isEnabled())
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        wb._qualify_selected(cockpit.selected())
        self.assertEqual([l.name for l in _FakeQualifyWorker.made[0].args[0]], ["Vaibhav"])
        redone = Dossier(lead=broken.lead, verdict="warm", score=70)
        wb._on_qualified(RunResult(dossiers=[redone], total_in_sheet=1,
                                   signal_source="", all_leads=[broken.lead]), [])
        self.assertEqual(cockpit._table.rowCount(), 2)
        self.assertEqual(len(wb._res.dossiers), 2)
        self.assertIn(redone, wb._res.dossiers)
        self.assertNotIn(broken, wb._res.dossiers)
        self.assertTrue(cockpit._b_qualify.isHidden())        # nothing left to qualify

    def test_a_sheet_run_keeps_its_own_scoring(self):
        wb = self._WB.LeadsWorkbench({"api_key": "gsk_test"})
        leads = self._leads_only_run(wb)
        wb._session_mode = "sheet"
        wb._run_params = {"mode": "sheet", "roles": ["Plant Head"]}
        wb._confirm_qualify = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:1])
        wb._qualify_selected(wb._cockpit.leads.selected())
        self.assertEqual(_FakeQualifyWorker.made[0].kwargs["roles"], [])

    def test_the_worker_spends_the_pass_on_exactly_those_leads(self):
        from unittest import mock
        from prospector.engine import RunResult
        from addons.leads.workers import LeadsQualifyWorker
        leads = [Lead(name=f"P{i}", company=f"Co {i}", fit_score=50) for i in range(3)]
        calls = []

        def fake_run_leads(passed, offer, cfg, **kw):
            calls.append((passed, kw))
            return RunResult(dossiers=[Dossier(lead=l) for l in passed],
                             total_in_sheet=len(passed), signal_source="",
                             all_leads=list(passed))

        w = LeadsQualifyWorker(leads, "Automation", {}, roles=["Plant Head"],
                               verify_limit=0)
        done = []
        w.done.connect(lambda res, drafts: done.append((res, drafts)))
        with mock.patch("prospector.signals.make_provider", return_value=None), \
                mock.patch("prospector.engine.run_leads", side_effect=fake_run_leads), \
                mock.patch("prospector.verify.collect_keys", return_value={}), \
                mock.patch("prospector.reach.draft_batch", return_value=[]):
            w.run()                                  # inline: no thread
        self.assertEqual(len(calls), 1)
        passed, kw = calls[0]
        self.assertEqual(passed, leads)
        self.assertEqual(kw["limit"], 3)
        self.assertIsNone(kw.get("skip"))            # they belong to this session
        self.assertEqual(kw["roles"], ["Plant Head"])
        self.assertEqual(len(done[0][0].dossiers), 3)


class ClearAndSelectAllStayUsableDuringARun(_Workbench):
    """22-Sep-2026, the real fix behind the "Clear doesn't work" report:
    workbench._set_running(True) used to disable cockpit.leads._bulk
    outright — the whole bulk bar — while ANY background job (a search, a
    verify pass, a qualify pass…) was running. That correctly holds off the
    six action buttons, which would each start ANOTHER job on top of the
    one already going. It also, as collateral, held off "Clear" and "Select
    all" — pure local selection state that touches no running worker and
    had no reason to be blocked at all. A customer pressed "Clear" mid-run,
    watched it do nothing, and had no way to know it wasn't just broken
    (compounded by the styling gap fixed just above — it didn't even LOOK
    disabled). Now only the six action buttons are held off; "Clear" and
    "Select all" work in every state."""

    def _leads_only_run(self, wb, n=4):
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i}", title="Plant Head", company=f"Co {i}",
                      email=f"p{i}@x.com", fit_score=60 + i) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="",
                        all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "roles": ["Plant Head"],
                           "offer": "Automation retrofits"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, cockpit, leads):
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead in leads:
                cockpit._table.item(r, 0).setCheckState(Qt.Checked)

    def test_the_actions_that_start_a_job_are_held_off_mid_run(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        leads = self._leads_only_run(wb)
        cockpit = wb._cockpit.leads
        self._tick(cockpit, leads)
        wb._set_running(True)
        for b in cockpit._bulk_actions():
            if b in (cockpit._b_contact, cockpit._b_stage, cockpit._b_remove):
                # Save, Set stage and Remove are local writes, not jobs: they
                # stay usable.
                self.assertTrue(b.isEnabled(), b.text())
            else:
                self.assertFalse(b.isEnabled(), b.text())

    def test_clear_and_select_all_are_not_touched_by_a_run(self):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        leads = self._leads_only_run(wb)
        cockpit = wb._cockpit.leads
        self._tick(cockpit, leads)
        wb._set_running(True)
        self.assertTrue(cockpit._bulk_clear.isEnabled())
        self.assertTrue(cockpit._sel_all.isEnabled())

    def test_pressing_clear_mid_run_actually_clears(self):
        # The real bug, reproduced and fixed: this used to leave
        # cockpit.selected() at 4 no matter how many times "Clear" was
        # clicked, because the button was disabled underneath a normal-
        # looking face.
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        leads = self._leads_only_run(wb)
        cockpit = wb._cockpit.leads
        self._tick(cockpit, leads)
        wb._set_running(True)
        self.assertEqual(len(cockpit.selected()), 4)
        cockpit._bulk_clear.click()
        self.assertEqual(cockpit.selected(), [])

    def test_the_action_buttons_come_back_selection_correct_not_blindly_on(self):
        # _set_running(False) must not just flip every action button back
        # on — "Qualify" with nothing ticked, or nothing left to qualify,
        # has to stay off exactly as _refresh_bulk would already say.
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        self._leads_only_run(wb)
        cockpit = wb._cockpit.leads
        wb._set_running(True)
        wb._set_running(False)
        for b in cockpit._bulk_actions():
            self.assertFalse(b.isEnabled(), b.text())    # nothing is ticked
        leads = [d.lead for d in
                [cockpit._dossier_at(r) for r in range(cockpit._table.rowCount())]]
        self._tick(cockpit, leads[:2])
        wb._set_running(True)
        wb._set_running(False)
        self.assertTrue(cockpit._b_verify.isEnabled())    # 2 ticked, now real again


class _FakeEmailWorker(_FakeSourceWorker):
    """Stands in for LeadsEmailWorker: records the leads it was handed."""
    made: list = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.refused = _FakeSignal()         # finders that turned the account away
        _FakeEmailWorker.made.append(self)


class FindEmailsOnTheRowsYouPick(_Workbench):
    """The other half of "find people first": the bulk bar's Find e-mails. It
    arms for rows without a confirmed address, hands the worker exactly those
    leads, and what comes back re-renders the rows and is saved."""

    def _people(self, wb, n=3, email=""):
        """A finished Find-people run: n people, none with an address."""
        from prospector.engine import RunResult
        leads = [Lead(name=f"P{i} Singh", title="Plant Head", company=f"Co {i}",
                      email=email, fit_score=60 + i) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="",
                        all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "offer": "Automation"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, cockpit, leads):
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead in leads:
                cockpit._table.item(r, 0).setCheckState(Qt.Checked)

    def _patched_worker(self):
        _FakeEmailWorker.made = []
        orig = self._WB.LeadsEmailWorker
        self._WB.LeadsEmailWorker = _FakeEmailWorker
        self.addCleanup(setattr, self._WB, "LeadsEmailWorker", orig)

    def _status_at(self, cockpit, lead) -> str:
        for r in range(cockpit._table.rowCount()):
            if cockpit._dossier_at(r).lead is lead:
                return cockpit._table.item(r, CK._C_STATUS).text()
        return ""

    def test_the_bulk_bar_arms_for_rows_without_a_confirmed_address(self):
        c = CK.LeadsCockpit()
        good = _dos("Kunyi", 96, "k@x.com", "valid")
        guess = _dos("Vaibhav", 80, "v@x.com", "")
        none = _dos("NoMail", 60, "")
        c.set_dossiers([good, guess, none])
        self.assertFalse(c._b_emails.isHidden())
        self._tick(c, [good.lead])
        self.assertFalse(c._b_emails.isEnabled())         # already verified
        self._tick(c, [guess.lead, none.lead])
        self.assertTrue(c._b_emails.isEnabled())
        got = []
        c.emailsRequested.connect(got.append)
        c._b_emails.click()
        self.assertEqual({d.lead.name for d in got[0]},
                         {"Kunyi", "Vaibhav", "NoMail"})

    def test_the_button_goes_away_once_every_address_is_confirmed(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])
        self.assertTrue(c._b_emails.isHidden())

    def test_find_phones_arms_for_people_with_no_phone_at_a_company(self):
        """Find phones looks up the number each COMPANY publishes, so it is for
        people with no phone of any kind who work somewhere it can look up."""
        c = CK.LeadsCockpit()
        has = _dos("Kunyi", 96, "k@x.com", "valid")
        has.lead.phone = "+91 98250 12345"                       # came with a number
        found = _dos("Vaibhav", 80, "v@x.com", "")
        found.lead.extra["phones"] = [{"number": "+912652345678", "kind": "landline"}]
        bare = _dos("Asha", 70, "")
        nowhere = _dos("Ravi", 60, "", company="")               # no company to look up
        c.set_dossiers([has, found, bare, nowhere])
        self.assertFalse(c._b_phones.isHidden())                 # someone still needs one
        self._tick(c, [has.lead, found.lead, nowhere.lead])
        self.assertFalse(c._b_phones.isEnabled())                # each has one, or can't be looked up
        self._tick(c, [bare.lead])
        self.assertTrue(c._b_phones.isEnabled())
        got = []
        c.phonesRequested.connect(got.append)
        c._b_phones.click()
        self.assertEqual({d.lead.name for d in got[0]}, {"Kunyi", "Vaibhav", "Asha", "Ravi"})

    def test_find_phones_leaves_the_bar_once_everyone_has_one(self):
        c = CK.LeadsCockpit()
        d = _dos("Kunyi", 96, "k@x.com", "valid")
        d.lead.phone = "+91 98250 12345"
        c.set_dossiers([d])
        self.assertTrue(c._b_phones.isHidden())

    def test_find_phones_folds_into_more_before_anything_else_on_a_narrow_bar(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Asha", 70, "")])
        actions = c._bulk_actions()
        self.assertIn(c._b_phones, CK.LeadsCockpit._fold_set(2, actions))
        self.assertNotIn(c._b_emails, CK.LeadsCockpit._fold_set(3, actions))   # e-mails stay longest
        self.assertIn(c._b_emails, CK.LeadsCockpit._fold_set(4, actions))

    def test_the_workspace_re_exposes_the_signal(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        w = CK.LeadsWorkspace(leads_folder=folder.name)
        d = _dos("Kunyi", 96, "", "")
        w.set_dossiers([d], [])
        got = []
        w.emailsRequested.connect(got.append)
        w.leads._table.item(0, 0).setCheckState(Qt.Checked)
        w.leads._b_emails.click()
        self.assertEqual(got, [[d]])
        phones = []
        w.phonesRequested.connect(phones.append)                # and Find phones, the same way
        w.leads._b_phones.click()
        self.assertEqual(phones, [[d]])

    def test_exactly_the_ticked_leads_go_to_the_worker(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads[:2])
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(len(_FakeEmailWorker.made), 1)
        worker = _FakeEmailWorker.made[0]
        self.assertTrue(worker.started)
        self.assertEqual(sorted(l.name for l in worker.args[0]), ["P0 Singh", "P1 Singh"])
        self.assertEqual(wb._jobs, 1)

    def test_the_rails_verify_setting_does_not_cap_this_action(self):
        """Verify is a budget for a RUN, whose top slice the run picks. These
        rows were ticked by hand, so none of them is left as an unchecked
        guess — not even with the rail wound down to nobody."""
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._verify_limit.setValue(0)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        worker = _FakeEmailWorker.made[0]
        self.assertNotIn("verify_limit", worker.kwargs)
        self.assertEqual(len(worker.args[0]), 3)

    def test_what_comes_back_re_renders_the_rows_and_is_saved(self):
        from addons.leads import sessions
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        cockpit = wb._cockpit.leads
        self.assertEqual(self._status_at(cockpit, leads[0]), "No email")
        # What the worker does on its thread: an address each, one confirmed.
        leads[0].email, leads[1].email = "p0@co0.com", "p1@co1.com"
        leads[0].extra["email_check"] = "valid"
        wb._jobs = 1
        wb._on_emails_found(2, 1)
        self.assertEqual(self._status_at(cockpit, leads[0]), "Verified")
        self.assertEqual(self._status_at(cockpit, leads[1]), "Unverified")
        self.assertEqual(self._status_at(cockpit, leads[2]), "No email")
        self.assertIn("2 new address", wb._status.text())
        self.assertIn("1 verified", wb._status.text())
        self.assertEqual(wb._jobs, 0)
        loaded = sessions.load(self._sessions, wb._session_id)
        self.assertEqual([l.email for l in loaded["all_leads"]][:2],
                         ["p0@co0.com", "p1@co1.com"])

    def test_a_second_one_cannot_start_while_a_job_runs(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb)
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        picked = wb._cockpit.leads.selected()
        wb._find_emails(picked)
        wb._find_emails(picked)                      # the job counter holds it
        self.assertEqual(len(_FakeEmailWorker.made), 1)
        self.assertEqual(wb._jobs, 1)

    def test_a_big_batch_asks_first_and_a_no_starts_nothing(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb, n=12)
        wb._confirm_emails = lambda n: False
        self._patched_worker()
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(_FakeEmailWorker.made, [])
        self.assertEqual(wb._jobs, 0)

    def test_select_all_then_the_button_starts_the_worker(self):
        """The owner's own clicks, with nothing patched between the button and
        the worker but the worker and the Yes: 24-Sep-2026 a changed call to
        _confirm_emails raised inside the click, and every test above — each
        replacing _confirm_emails — still passed while the button did nothing."""
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        wb = self._WB.LeadsWorkbench({})
        self._people(wb, n=12)                       # past ten: the question is asked
        self._patched_worker()
        asked = []
        with mock.patch.object(QMessageBox, "question",
                               side_effect=lambda *a, **k: (
                                   asked.append(a),
                                   QMessageBox.StandardButton.Yes)[1]):
            wb._cockpit.leads._select_all()
            wb._cockpit.leads._b_emails.click()
        self.assertEqual(len(asked), 1)
        self.assertEqual(len(_FakeEmailWorker.made), 1)
        self.assertTrue(_FakeEmailWorker.made[0].started)
        self.assertEqual(len(_FakeEmailWorker.made[0].args[0]), 12)

    _APOLLO_NO = "Apollo: finding e-mails isn't in your Basic (Trial) plan. Only paid Apollo plans include it."
    _HUNTER_NO = "Hunter: this month's searches are used up. They come back on 27 Sep."

    def _refused_run(self, wb, found):
        """The worker's two last words: who refused, then the count."""
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        self._people(wb)
        self._patched_worker()
        wb._cockpit.leads._select_all()
        wb._find_emails(wb._cockpit.leads.selected())
        worker = _FakeEmailWorker.made[0]
        with mock.patch.object(QMessageBox, "warning") as warned:
            worker.refused.emit({"Apollo": self._APOLLO_NO, "Hunter": self._HUNTER_NO})
            worker.done.emit(found, 0)
        return warned

    def test_finders_that_refused_the_account_are_named_when_nothing_is_found(self):
        """24-Sep-2026: Apollo's Free plan and Hunter's spent quota refused
        every one of 159 lookups, and all the owner saw was "Found 0". The
        refusals are the answer — said in a box, and on the status line."""
        wb = self._WB.LeadsWorkbench({})
        warned = self._refused_run(wb, found=0)
        self.assertEqual(warned.call_count, 1)
        said = warned.call_args[0][2]
        self.assertIn(self._APOLLO_NO, said)
        self.assertIn(self._HUNTER_NO, said)
        self.assertIn("Basic (Trial) plan", wb._status.text())
        self.assertIn("used up", wb._status.text())

    def test_a_partial_result_names_the_refusal_without_a_box(self):
        wb = self._WB.LeadsWorkbench({})
        warned = self._refused_run(wb, found=2)
        warned.assert_not_called()
        self.assertIn("2 new address", wb._status.text())
        self.assertIn("Basic (Trial) plan", wb._status.text())

    def test_leads_that_are_already_verified_are_left_alone(self):
        wb = self._WB.LeadsWorkbench({})
        leads = self._people(wb, n=2, email="p@x.com")
        for lead in leads:
            lead.extra["email_check"] = "valid"
        self._patched_worker()
        wb._cockpit.set_dossiers([], [], leads)      # re-render with the statuses
        self._tick(wb._cockpit.leads, leads)
        wb._find_emails(wb._cockpit.leads.selected())
        self.assertEqual(_FakeEmailWorker.made, [])
        self.assertIn("already have a verified address", wb._status.text())

    def test_an_imported_sheet_can_have_its_emails_found_too(self):
        """The sheet the owner exported from Prism comes back with names and
        no addresses — the whole point of bringing it back is to find them.
        Imported people are contacts, on the page with no run at all."""
        wb = self._WB.LeadsWorkbench({})
        leads = [Lead(name=f"P{i} Singh", title="Plant Head", company=f"Co {i}")
                 for i in range(3)]
        wb._run_import(_contacts_result(self._tmp, leads, name="Prism leads.xlsx"))
        self.assertIsNone(wb._res)                    # no run on screen
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        cockpit = wb._cockpit.leads
        for r in range(cockpit._table.rowCount()):
            cockpit._table.item(r, 0).setCheckState(Qt.Checked)
        wb._find_emails(cockpit.selected())
        self.assertEqual(sorted(l.name for l in _FakeEmailWorker.made[0].args[0]),
                         [l.name for l in leads])

    def test_what_comes_back_for_imported_people_is_kept_on_their_contacts(self):
        from addons.leads import contacts as CT
        wb = self._WB.LeadsWorkbench({})
        lead = Lead(name="Asha Rao", title="Owner", company="Rao Works")
        wb._run_import(_contacts_result(self._tmp, [lead]))
        wb._confirm_emails = lambda n: True
        self._patched_worker()
        cockpit = wb._cockpit.leads
        cockpit._table.item(0, 0).setCheckState(Qt.Checked)
        wb._find_emails(cockpit.selected())
        held = _FakeEmailWorker.made[0].args[0][0]    # what the worker fills in
        held.email = "asha@raoworks.com"
        held.extra["email_check"] = "valid"
        wb._jobs = 1
        wb._on_emails_found(1, 1)
        self.assertEqual(self._status_at(cockpit, held), "Verified")
        saved = CT.list_contacts(self._contacts)
        self.assertEqual(saved[0].lead.email, "asha@raoworks.com")


class ApolloIsNotOfferedOnceItsPlanRefuses(_Workbench):
    """Apollo's search endpoints are not in its free plan, so a 403 is the end
    of Apollo for this key: the rail goes back to Exa, the switch is off with
    Apollo's own words on it, and the config remembers — a flag, never a key."""

    def _refusal(self) -> str:
        from prospector import apollo
        return apollo.SCOPED_KEY.format(path="/mixed_people/api_search")

    def _blocked(self, wb, saved=None):
        from unittest import mock
        with mock.patch("core_bridge.config.load",
                        return_value={"apollo_api_key": "ap-k"}), \
                mock.patch("core_bridge.config.save",
                           side_effect=(saved if saved is not None else []).append):
            wb._jobs = 1
            wb._on_source_blocked(self._refusal())

    def test_a_403_run_disables_apollo_and_flips_the_source_to_exa(self):
        saved = []
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k"})
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")
        self._blocked(wb, saved)
        self.assertEqual(wb._source, "exa")
        self.assertTrue(wb._src_exa.isChecked())
        self.assertFalse(wb._src_apollo.isEnabled())
        self.assertIn("Apollo would not let this key", wb._src_apollo.toolTip())
        self.assertIn("paid Apollo plan", wb._status.text())
        self.assertEqual(wb._jobs, 0)
        # The flag is a flag: a switch the next launch reads, not the key.
        self.assertIs(saved[-1]["apollo_api_blocked"], True)
        self.assertIs(wb.cfg["apollo_api_blocked"], True)
        # And it cannot be picked again by a click or by an old session.
        wb._src_apollo.click()
        wb._restore_inputs({"mode": "icp", "source": "apollo"})
        self.assertEqual(wb._source, "exa")

    def test_the_next_launch_does_not_offer_it_at_all(self):
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k",
                                      "exa_api_key": "exa-k",
                                      "apollo_api_blocked": True})
        self.assertEqual(wb._source, "exa")
        self.assertFalse(wb._src_apollo.isEnabled())
        self.assertIn("free Apollo plan", wb._src_apollo.toolTip())
        wb._set_running(True)                    # a run, then the run finishing
        wb._set_running(False)
        self.assertFalse(wb._src_apollo.isEnabled())

    def test_a_different_key_lifts_the_block(self):
        from unittest import mock
        saved = []
        wb = self._WB.LeadsWorkbench({"apollo_api_key": "ap-k"})
        self._blocked(wb)
        with mock.patch("core_bridge.config.load",
                        return_value={"apollo_api_key": "ap-k"}), \
                mock.patch("core_bridge.config.save", side_effect=saved.append):
            wb._apollo.setText("ap-new")
            wb._apollo.textEdited.emit("ap-new")      # what typing one does
        self.assertTrue(wb._src_apollo.isEnabled())
        self.assertIn("PAID Apollo plan", wb._src_apollo.toolTip())
        self.assertIs(saved[-1]["apollo_api_blocked"], False)
        wb._src_apollo.click()
        self.assertEqual(wb._source, "apollo")

    def test_only_a_plan_refusal_counts_as_blocked(self):
        from prospector import apollo
        from addons.leads.workers import _plan_refusal
        self.assertEqual(_plan_refusal(apollo.ApolloError(self._refusal()), apollo),
                         self._refusal())
        self.assertEqual(
            _plan_refusal(apollo.ApolloError(apollo.BAD_KEY), apollo), "")
        self.assertEqual(
            _plan_refusal(apollo.ApolloError(apollo.RATE_LIMITED), apollo), "")


class ExportsStayHonestWithoutAddresses(_Workbench):
    """A lead with no address exports as a BLANK e-mail — never the guess the
    old flow used to make on the way past."""

    def test_the_sheet_and_the_csv_leave_a_missing_address_empty(self):
        import csv as _csv
        from prospector import exports
        lead = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        self.assertEqual(exports.build_email_checks([lead]), {})   # nothing to look up
        self.assertEqual(exports.check_of(lead, {}), "no-domain")
        wb = self._WB.LeadsWorkbench({})
        path = os.path.join(self._tmp, "selected.csv")
        wb._write_leads_csv(CK.unqualified_rows([], [lead]), path)
        with open(path, encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
        self.assertEqual(rows[0]["email"], "")
        self.assertEqual(rows[0]["status"], "No email")

    def test_the_whole_run_sheet_is_written_for_a_run_with_no_addresses(self):
        """"Export sheets" writes the leads sheet and the hot list. With no
        addresses there is nothing to look up (no network) and the E-mail
        column stays empty — never the guess the old flow made on the way."""
        import openpyxl
        from prospector import exports
        leads = [Lead(name=f"P{i} Singh", company=f"Co {i}", title="Plant Head",
                      industry="Steel") for i in range(3)]
        path = exports.leads_xlsx(leads, os.path.join(self._tmp, "Prism leads.xlsx"))
        ws = openpyxl.load_workbook(path).worksheets[0]
        head = [c.value for c in ws[1]]
        col = head.index("E-mail") + 1
        self.assertEqual([ws.cell(r, col).value for r in range(2, 5)],
                         [None, None, None])
        self.assertEqual({ws.cell(r, head.index("Email check") + 1).value
                          for r in range(2, 5)}, {"no-domain"})
        exports.hotlist_xlsx([], os.path.join(self._tmp, "Prism hot list.xlsx"))


class FindPeopleFirstEmailsLater(unittest.TestCase):
    """SourceWorker with emails="later", called inline (no thread, no network):
    a run finds the PEOPLE and spends nothing on their addresses — no domain
    lookups, no verifier — and still lists everyone it found."""

    def _worker(self, emails="later", **kw):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]},
                                     "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", {}, leads_only=True,
                         spec=spec.to_dict(), emails=emails, **kw)
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        return w, got

    @staticmethod
    def _people(n=3):
        return [Lead(name=f"P{i} Singh", company=f"Co {i}", title="Head Operations")
                for i in range(n)]

    def test_a_find_people_run_never_looks_up_an_address(self):
        from unittest import mock
        people = self._people()
        w, got = self._worker()
        with mock.patch("prospector.signals.exa_key", return_value="exa-test"), \
                mock.patch("prospector.source.source",
                           side_effect=lambda i, r, k, **kw: list(people)), \
                mock.patch("prospector.enrich.enrich") as enriched, \
                mock.patch("prospector.verify.collect_keys") as keys, \
                mock.patch("prospector.verify.find_and_verify") as checked:
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_not_called()
        keys.assert_not_called()
        checked.assert_not_called()
        res, drafts = got["done"][0]
        self.assertEqual(len(res.all_leads), 3)          # everyone is listed
        self.assertEqual(drafts, [])
        self.assertTrue(all(not l.email for l in res.all_leads))
        self.assertTrue(any("left for later" in p for p in got["progress"]))

    def test_emails_now_guesses_nobody_either(self):
        """It used to write firstname.lastname@<website> for everyone found.
        The owner, 24-Sep-2026: "the emails shouldn't be guessed any day" —
        a run that finds addresses finds them for the hot and warm, after
        qualifying, with Hunter then Apollo (verify_reachable)."""
        from unittest import mock
        people = self._people()
        w, got = self._worker(emails="now")
        with mock.patch("prospector.signals.exa_key", return_value="exa-test"), \
                mock.patch("prospector.source.source",
                           side_effect=lambda i, r, k, **kw: list(people)), \
                mock.patch("prospector.enrich.enrich") as enriched:
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_not_called()
        res, _drafts = got["done"][0]
        self.assertTrue(all(not l.email for l in res.all_leads))


class TheEmailWorkerSpendsOnTheChosenPeople(unittest.TestCase):
    """LeadsEmailWorker, called inline: every lead goes through
    find_and_verify once — an address they came with is checked, anyone
    without one is looked up by the finders (Hunter, then Apollo) — and what
    came back is counted, found and of those confirmed. Nobody's address is
    guessed (the owner, 24-Sep-2026)."""

    def _worker(self, leads, cfg=None):
        from addons.leads.workers import LeadsEmailWorker
        w = LeadsEmailWorker(leads, cfg or {})
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(lambda i, n, l: got["progress"].append((i, n, l)))
        w.done.connect(lambda f, v: got["done"].append((f, v)))
        w.failed.connect(got["failed"].append)
        return w, got

    def test_everyone_is_found_or_checked_once_and_nothing_is_guessed(self):
        from unittest import mock
        blank = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        held = Lead(name="Bo Lund", company="Globex", title="Owner",
                    email="bo@globex.com")
        seen = []

        def fake_find(lead, keys=None, refused=None):
            # What a finder does: a real address, and whose it was.
            seen.append((lead, dict(keys or {})))
            if not lead.email:
                lead.email = "ana.ruiz@acme.com"
                lead.extra["email_source"] = "hunter"
            lead.extra["email_check"] = "valid" if "@acme" in lead.email else "catch-all"

        w, got = self._worker([blank, held], cfg={"hunter_api_key": "h",
                                                  "reoon_api_key": "r"})
        with mock.patch("prospector.signals.exa_key", return_value=""), \
                mock.patch("prospector.enrich.enrich") as enriched, \
                mock.patch("prospector.verify.find_and_verify", side_effect=fake_find):
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_not_called()          # no Exa key: the domain step is skipped
        self.assertEqual((blank.email, blank.extra["email_source"]),
                         ("ana.ruiz@acme.com", "hunter"))
        self.assertEqual([l for l, _k in seen], [blank, held])
        self.assertEqual(got["done"], [(1, 1)])          # one found, one verified
        self.assertEqual(seen[0][1], {"hunter_api_key": "h", "reoon_api_key": "r"})

    def test_a_refused_apollo_plan_is_not_asked_to_find_either(self):
        from unittest import mock
        lead = Lead(name="Ana Ruiz", company="Acme", title="Owner",
                    email="ana@acme.com")
        keys = []
        w, _got = self._worker([lead], cfg={"apollo_api_key": "ap-k",
                                            "reoon_api_key": "r",
                                            "apollo_api_blocked": True})
        with mock.patch("prospector.signals.exa_key", return_value=""), \
                mock.patch("prospector.enrich.enrich"), \
                mock.patch("prospector.verify.find_and_verify",
                           side_effect=lambda l, k=None, refused=None: keys.append(dict(k or {}))):
            w.run()
        self.assertNotIn("apollo_api_key", keys[0])
        self.assertIn("reoon_api_key", keys[0])

    def test_the_companys_domain_is_found_once_before_any_finder_is_asked(self):
        """27-Sep-2026, the owner's real run: Hunter answered nothing for
        "company=Asian Paints" but found its CEO instantly for "domain=
        asianpaints.com" — the domain step existed (enrich.enrich) but nothing
        ever called it. Find e-mails now looks each COMPANY's site up once
        (not once per lead) before any finder is asked."""
        from unittest import mock
        a = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        b = Lead(name="Bo Diaz", company="Acme", title="Manager")   # same firm: one lookup, not two
        order = []

        def fake_enrich(leads, api_key, on_progress=None):
            order.append(("enrich", list(leads), api_key))
            for l in leads:
                l.extra["company_domain"] = "acme.example"

        def fake_find(lead, keys=None, refused=None):
            order.append(("find", lead))

        w, got = self._worker([a, b], cfg={"hunter_api_key": "h", "exa_api_key": "exa-k"})
        with mock.patch("prospector.enrich.enrich", side_effect=fake_enrich) as enriched, \
                mock.patch("prospector.verify.find_and_verify", side_effect=fake_find):
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_called_once_with([a, b], "exa-k")
        self.assertEqual([tag for tag, *_ in order], ["enrich", "find", "find"])
        # The pre-existing "Finding e-mail domains…" progress line (i == 0).
        self.assertEqual(got["progress"][0], (0, 2, None))

    def test_a_pool_key_looks_the_domain_up_too(self):
        """The run's OWN cfg is what find_domains reads — pooled, that already
        carries the sentinel (gateway.effective_cfg), so this is the SAME
        website lookup Find e-mails already prices in (_confirm_pool_emails:
        "Prism looks up each company's website"), now actually made."""
        from unittest import mock
        from prospector import gateway as G
        a = Lead(name="Ana Ruiz", company="Acme", title="Owner")
        w, got = self._worker([a], cfg={"exa_api_key": G.POOL_KEY, "leads_pool": True})
        with mock.patch("prospector.enrich.enrich") as enriched, \
                mock.patch("prospector.verify.find_and_verify"):
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_called_once_with([a], G.POOL_KEY)

    def test_a_refused_account_is_said_once_before_the_result(self):
        """The batch shares one `refused`: whatever find_and_verify writes
        there reaches the workbench once, ahead of the count it explains."""
        from unittest import mock
        leads = [Lead(name=f"P{i} Singh", company="Acme", title="Owner") for i in range(3)]
        w, got = self._worker(leads, cfg={"apollo_api_key": "ap-k"})
        order = []
        w.refused.connect(lambda why: order.append(("refused", why)))
        w.done.connect(lambda f, v: order.append(("done", f)))
        shared = []

        def fake_find(lead, keys=None, refused=None):
            shared.append(refused)
            refused["Apollo"] = "Apollo: finding e-mails isn't in your Free plan. Only paid Apollo plans include it."

        with mock.patch("prospector.verify.find_and_verify", side_effect=fake_find):
            w.run()
        self.assertEqual(got["failed"], [])
        self.assertTrue(all(r is shared[0] for r in shared))   # one dict, the whole batch
        self.assertEqual([k for k, _ in order], ["refused", "done"])
        self.assertIn("Free plan", order[0][1]["Apollo"])

    def test_every_ticked_person_is_looked_up_and_none_is_made_up(self):
        """Every row ticked is looked up — none skipped, none sampled — and a
        person no finder knows keeps NO address. (It used to write a pattern
        address for every blank row first; those reached the exported sheet as
        guesses that read like findings, 24-Sep-2026.)"""
        from unittest import mock
        leads = [Lead(name=f"P{i} Singh", company="Acme", title="Owner")
                 for i in range(30)]
        checked = []
        w, got = self._worker(leads)
        with mock.patch("prospector.signals.exa_key", return_value=""), \
                mock.patch("prospector.enrich.enrich") as enriched, \
                mock.patch("prospector.verify.find_and_verify",
                           side_effect=lambda l, k=None, refused=None: checked.append(l)):
            w.run()
        self.assertEqual(got["failed"], [])
        enriched.assert_not_called()          # no Exa key: the domain step is skipped
        self.assertEqual(len(checked), len(leads))
        self.assertTrue(all(not l.email for l in leads))
        self.assertEqual(got["done"], [(0, 0)])


class TriageScoresThePersonNotTheFlow(unittest.TestCase):
    """An e-mail is worth points only where having one says something about the
    LEAD. A run that has not fetched addresses yet leaves everyone blank, so
    the old +15 (and "no email" on all of them) scored the flow."""

    def _lead(self, name, email=""):
        return Lead(name=name, title="Plant Head", company="Acme",
                    industry="Steel Manufacturing", email=email)

    def test_an_address_less_batch_is_not_marked_down_for_it(self):
        from prospector import triage
        leads = [self._lead("A"), self._lead("B")]
        triage.rank(leads, "steel plant automation", ["Plant Head"])
        self.assertTrue(all("no email" not in l.fit_reason for l in leads))
        with_email = self._lead("C")
        scored, _why = triage.score_lead(with_email, "steel plant automation",
                                         ["Plant Head"], False)
        self.assertEqual(leads[0].fit_score, scored)

    def test_a_batch_that_carries_addresses_still_scores_them(self):
        from prospector import triage
        has, hasnt = self._lead("A", "a@acme.com"), self._lead("B")
        triage.rank([has, hasnt], "steel plant automation", ["Plant Head"])
        self.assertEqual(has.fit_score - hasnt.fit_score, 15)
        self.assertIn("no email", hasnt.fit_reason)


# Every key the "?" walkthrough asks this screen for. Spelled out so renaming a
# widget the tour points at fails here rather than on the owner's screen.
_TOOLBAR_KEYS = ("import_menu", "views_menu", "hide_filters", "people_search",
                 "research_menu", "save_as_search", "view_toggle", "sort",
                 "search_settings", "people_tabs")
_COCKPIT_KEYS = _TOOLBAR_KEYS + ("table", "select_all", "col_lead", "col_focus",
                                 "col_fit", "col_status", "col_signal")
_BULK_KEYS = ("bulk_bar", "bulk_save", "bulk_remove", "bulk_verify", "bulk_emails",
              "bulk_phones", "bulk_list", "bulk_export", "bulk_stage", "bulk_qualify",
              "bulk_sequence")
_TAB_KEYS = ("tab_people", "tab_companies", "tab_sessions", "tab_lists", "tab_saved",
             "tab_sequences", "tab_analytics", "tab_deals", "tab_due", "tab_stats")
# The workbench's own: Find new people. (Search settings' rows are one
# toolbar step — they sit in a modal dialog the walk must not open.)
_SEARCH_KEYS = ("btn_find",)


def _descends(widget, root) -> bool:
    while widget is not None:
        if widget is root:
            return True
        widget = widget.parentWidget()
    return False


class PointAtMeCockpit(unittest.TestCase):
    """The guided walkthrough asks the cockpit where each part IS
    (help_targets) and to make it reachable (help_reveal). Every key answers
    with a real widget of this screen — or a region of one, for a column the
    header paints itself — and a reveal never ticks a row, never touches a
    filter and never starts anything."""

    def setUp(self):
        self.d1 = _dos("Kunyi", 96, "k@x.com", "valid")
        self.d2 = _dos("Vaibhav", 80, "v@x.com", "")
        self.c = CK.LeadsCockpit()
        self.c.set_dossiers([self.d1, self.d2])
        # These keys name the table's own parts (its column headings, its select-all). The list, the default view, has none of those, so the
        # tour skips those steps there (see test_the_list_view_*); here the table is asked for.
        self.c._set_view("table")

    def test_the_list_view_points_results_at_the_list_and_skips_the_column_steps(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([self.d1, self.d2])
        t = c.help_targets()
        self.assertIs(t["table"], c._gallery)
        for key in ("select_all", "col_lead", "col_focus", "col_fit", "col_status", "col_signal"):
            self.assertNotIn(key, t)

    def test_every_key_points_at_something_on_this_screen(self):
        targets = self.c.help_targets()
        # No row is ticked, no lead open and no page to turn, so the action
        # bar, the drawer and the pager are not on screen to be pointed at.
        self.assertEqual(sorted(targets), sorted(_COCKPIT_KEYS))
        for key, target in targets.items():
            widget, rect = target if isinstance(target, tuple) else (target, None)
            self.assertTrue(_descends(widget, self.c), key)
            if rect is not None:
                self.assertFalse(rect.isEmpty(), key)

    def test_the_targets_are_the_real_controls(self):
        t, c = self.c.help_targets(), self.c
        for key, widget in (("import_menu", c._import_btn), ("views_menu", c._views_btn),
                            ("hide_filters", c._filters_btn),
                            ("people_search", c._search),
                            ("research_menu", c._research_btn),
                            ("save_as_search", c._save_search_btn),
                            ("view_toggle", c._seg), ("sort", c._sort),
                            ("search_settings", c._settings_btn),
                            ("people_tabs", c._tabs_frame), ("table", c._table)):
            self.assertIs(t[key], widget, key)

    def test_a_column_key_rings_its_own_header_section(self):
        head = self.c._head
        cols = (("select_all", 0), ("col_lead", 1), ("col_focus", 2),
                ("col_fit", 3), ("col_status", 4), ("col_signal", 5))
        for key, col in cols:
            widget, rect = self.c.help_targets()[key]
            self.assertIs(widget, head)
            at = head.viewport().mapTo(head, QPoint(head.sectionViewportPosition(col), 0))
            self.assertEqual((rect.x(), rect.y()), (at.x(), at.y()), key)
            self.assertEqual(rect.width(), head.sectionSize(col), key)
            self.assertEqual(rect.height(), head.viewport().height(), key)

    def test_the_action_bar_keys_arrive_with_the_first_tick(self):
        for key in _BULK_KEYS:
            self.assertNotIn(key, self.c.help_targets())
        for key in _BULK_KEYS:
            self.c.help_reveal(key)                 # must not tick a row to show off
        self.assertEqual(self.c.selected(), [])
        self.assertNotIn("bulk_bar", self.c.help_targets())
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        t = self.c.help_targets()
        self.assertIs(t["bulk_bar"], self.c._bulk_bar_w)
        self.assertIs(t["bulk_save"], self.c._b_contact)      # Apollo's Save
        self.assertIs(t["bulk_verify"], self.c._b_verify)
        self.assertIs(t["bulk_emails"], self.c._b_emails)
        self.assertIs(t["bulk_phones"], self.c._b_phones)
        self.assertIs(t["bulk_list"], self.c._b_save)         # Add to list
        self.assertIs(t["bulk_export"], self.c._b_export)
        self.assertIs(t["bulk_sequence"], self.c._b_seq)

    def test_qualify_is_there_while_someone_is_still_unqualified(self):
        # It leaves the bar once every lead is qualified, so the step goes too.
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertNotIn("bulk_qualify", self.c.help_targets())
        raw = Lead(name="Sourced", title="Head", company="Acme", fit_score=50)
        self.c.set_dossiers([self.d1], all_leads=[self.d1.lead, raw])
        self.c._table.item(0, 0).setCheckState(Qt.Checked)
        self.assertIs(self.c.help_targets()["bulk_qualify"], self.c._b_qualify)

    def test_the_pager_joins_on_a_page_of_the_pool(self):
        from addons.leads import pool as P
        self.assertNotIn("pager", self.c.help_targets())
        people = [P.Person(lead=self.d1.lead)]
        self.c.set_people(people, {"rows": people, "page": 0, "pages": 1,
                                   "start": 1, "end": 1, "total": 1})
        self.assertIs(self.c.help_targets()["pager"], self.c._pager)

    def test_a_folded_rail_comes_back_for_the_people_tabs(self):
        self.c.set_filters_shown(False)
        self.assertNotIn("people_tabs", self.c.help_targets())
        self.c.help_reveal("people_tabs")
        self.assertFalse(self.c._rail.isHidden())
        self.assertIs(self.c.help_targets()["people_tabs"], self.c._tabs_frame)

    def test_the_drawer_step_opens_it_on_a_lead_and_ticks_nobody(self):
        self.assertNotIn("drawer", self.c.help_targets())
        self.c.help_reveal("drawer")
        self.assertIs(self.c.help_targets()["drawer"], self.c._drawer_panel)
        self.assertEqual(self.c._table.currentRow(), 0)
        self.assertEqual(self.c.selected(), [])

    def test_a_step_on_a_control_the_full_height_drawer_covers_shuts_it(self):
        """The floating drawer runs the page's full height, so a step BACK from
        the drawer step can land on Import, which is then under it."""
        c = self.c
        c.resize(1500, 700)                     # wide enough to float, not dock
        c.layout().activate()
        c._body.layout().activate()
        c._split.refresh()
        row, chain = c._import_btn.parentWidget(), []      # the title row lays itself
        while row is not None and row is not c:            # out only when shown, so do
            chain.append(row)                              # what showing it would: top-down
            row = row.parentWidget()
        for row in reversed(chain):
            if row.layout() is not None:
                row.layout().activate()
        c.help_reveal("drawer")
        c._place_drawer()
        self.assertFalse(c._drawer_w.isHidden())
        self.assertFalse(c._drawer_docked)
        self.assertTrue(c._drawer_covers("import_menu"))
        self.assertFalse(c._drawer_covers("people_tabs"))
        c.help_reveal("people_tabs")            # the rail is beside it: it stays open
        self.assertFalse(c._drawer_w.isHidden())
        c.help_reveal("import_menu")            # Import is under it: it shuts
        self.assertTrue(c._drawer_w.isHidden())

    def test_no_reveal_ticks_filters_or_starts_anything(self):
        fired = []
        for signal in (self.c.verifyRequested, self.c.emailsRequested,
                       self.c.exportRequested, self.c.saveListRequested,
                       self.c.sequenceRequested, self.c.qualifyRequested,
                       self.c.saveContactsRequested, self.c.importRequested,
                       self.c.tabChanged, self.c.pageRequested,
                       self.c.sortChanged, self.c.queryChanged,
                       self.c.settingsRequested, self.c.saveSearchRequested,
                       self.c.findPrepareRequested):
            signal.connect(lambda *a: fired.append(a))

        def state():
            return (self.c._search.text(), self.c._sort.currentIndex(), self.c.tab(),
                    self.c._view, sorted(self.c._checked), sorted(self.c._hidden))

        before = state()
        for key in _COCKPIT_KEYS + _BULK_KEYS + ("pager", "drawer", "nonsense"):
            self.c.help_reveal(key)
        self.assertEqual(state(), before)
        self.assertEqual(fired, [])
        self.assertEqual(self.c.selected(), [])

    def test_the_snapshot_puts_back_what_the_reveals_moved(self):
        """The walk unfolds the rail, opens the drawer on the first lead and
        scrolls the table; closing it must leave the screen as the owner had
        it — and must not untick, filter or reopen anything doing so."""
        c = self.c
        c._table.item(1, 0).setCheckState(Qt.Checked)
        c.set_filters_shown(False)
        snap = c.help_snapshot()
        for key in ("people_tabs", "col_signal", "drawer"):
            c.help_reveal(key)
        self.assertFalse(c._rail.isHidden())
        self.assertFalse(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), 0)
        for _ in (0, 1):                            # the walk restores twice
            c.help_restore(snap)
        self.assertTrue(c._rail.isHidden())
        self.assertTrue(c._drawer_w.isHidden())
        self.assertEqual(c._table.currentRow(), -1)
        self.assertEqual(c._table.selectedItems(), [])
        self.assertEqual(sorted(c._checked), [1])

    def test_a_drawer_the_owner_had_open_stays_open_on_his_lead(self):
        c = self.c
        c._table.setCurrentCell(1, CK._C_LEAD)
        snap = c.help_snapshot()
        c.help_reveal("people_tabs")
        c._table.setCurrentCell(0, CK._C_LEAD)     # anything that moved the row
        c.help_restore(snap)
        self.assertEqual(c._table.currentRow(), 1)
        self.assertFalse(c._drawer_w.isHidden())

    def test_an_empty_screen_offers_only_what_is_on_it(self):
        empty = CK.LeadsCockpit()
        targets = empty.help_targets()
        for gone in ("table", "select_all", "col_lead", "pager", "drawer",
                     "bulk_bar"):
            self.assertNotIn(gone, targets)
        # The toolbar and the rail stay: they are how nobody becomes somebody.
        for kept in _TOOLBAR_KEYS:
            self.assertIn(kept, targets)


class PointAtMeWorkspace(unittest.TestCase):
    """The tab strip's keys are the workspace's own; everything else it lends
    from the People tab, and revealing one comes back to that tab first."""

    def setUp(self):
        self.ws = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        self.ws.set_dossiers([_dos("Kunyi", 96, "k@x.com", "valid")])

    def test_the_tabs_are_its_own_keys_and_the_cockpit_lends_the_rest(self):
        self.ws.leads._set_view("table")        # the column keys are the table's; the list, the default, has none (see the cockpit tests)
        t = self.ws.help_targets()
        for i, key in enumerate(_TAB_KEYS):
            self.assertIs(t[key], self.ws._tabs[i])
        self.assertIs(t["table"], self.ws.leads._table)
        self.assertIs(t["col_fit"][0], self.ws.leads._head)
        self.assertEqual(sorted(t), sorted(_COCKPIT_KEYS + _TAB_KEYS))

    def test_reveal_switches_the_tab_and_comes_back_for_the_leads(self):
        self.ws.help_reveal("tab_sessions")
        self.assertIs(self.ws._stack.currentWidget(), self.ws._sessions)
        self.ws.help_reveal("people_tabs")
        self.assertIs(self.ws._stack.currentWidget(), self.ws.leads)
        self.assertFalse(self.ws.leads._rail.isHidden())

    def test_an_unknown_key_moves_nothing(self):
        self.ws.help_reveal("tab_analytics")
        self.ws.help_reveal("nonsense")
        self.assertIs(self.ws._stack.currentWidget(), self.ws._analytics)

    def test_the_snapshot_brings_back_the_tab_the_walk_started_on(self):
        # Not always People: an owner who pressed "?" on Sessions ends there.
        self.ws.help_reveal("tab_sessions")
        snap = self.ws.help_snapshot()
        self.ws.help_reveal("people_tabs")
        self.ws.help_reveal("tab_saved")
        self.ws.help_restore(snap)
        self.assertIs(self.ws._stack.currentWidget(), self.ws._sessions)


class PointAtMeWorkbench(_Workbench):
    """The search half of the walkthrough: Find new people and the run line,
    unfolded and scrolled to, without a run being started, a setting moved —
    or Search settings opened: a window-modal dialog over the tour would sit
    on its own Next button."""

    def _wb(self, cfg=None):
        wb = self._WB.LeadsWorkbench(cfg or {})
        self.addCleanup(wb._settings_dlg.hide)          # never leave one up
        return wb

    def test_at_rest_only_find_new_people_is_on_the_page(self):
        wb = self._wb()
        self.assertEqual(sorted(wb.help_targets()), ["btn_find"])
        self.assertIs(wb.help_targets()["btn_find"], wb._prepare)

    def test_no_step_ever_opens_search_settings(self):
        from addons.leads import tour as T
        wb = self._wb()
        guide = T.Guide(wb)
        for key, _title, _body in T.STEPS:
            guide.help_reveal(key)
            self.assertFalse(wb._settings_dlg.isVisible(), key)

    def test_the_notice_joins_once_it_says_something(self):
        wb = self._wb()
        self.assertNotIn("notice", wb.help_targets())
        wb._status.setText("Qualifying 3 of 25…")
        self.assertIs(wb.help_targets()["notice"], wb._notice)

    def test_a_hidden_rail_comes_back_for_every_step_inside_it(self):
        """Hide filters folded the rail away, and only some steps brought it
        back — so every facet and Find new people were skipped. The filter
        panel's keys are unfolded here too, because the filter panel cannot
        reach the rail."""
        from addons.leads import tour as T
        wb = self._wb()
        rail = wb._cockpit.leads._rail
        for key, target in (("facet_locations", lambda: wb._filters.help_targets()["facet_locations"]),
                            ("similar_titles", lambda: wb._filters._similar),
                            ("btn_find", lambda: wb._prepare)):
            wb._cockpit.leads.set_filters_shown(False)
            self.assertFalse(T._drawn(target()), key)
            wb.help_reveal(key)
            wb._filters.help_reveal(key)
            self.assertFalse(rail.isHidden(), key)
            self.assertTrue(T._drawn(target()), key)
        wb._cockpit.leads.set_filters_shown(False)
        wb.help_reveal("notice")                     # not in the rail: left folded
        self.assertTrue(rail.isHidden())

    def test_the_whole_walk_leaves_the_screen_as_it_found_it(self):
        """Hide filters on, the Sessions tab up, a run on screen: walked to the
        end, or left with Esc halfway, the tour gives every one of those back,
        and the facets were still walked."""
        from addons.leads import tour as T
        wb = self._wb({"exa_api_key": "already-set"})
        self._finished(wb)
        ws, ck, fp = wb._cockpit, wb._cockpit.leads, wb._filters

        def state():
            return (ws._stack.currentIndex(), ck._rail.isHidden(),
                    ck._table.currentRow(), ck._drawer_w.isHidden(),
                    wb._settings_dlg.isVisible(), wb._keys_box.isHidden(),
                    fp.spec().to_dict(), sorted(ck._checked))

        ck.set_filters_shown(False)
        ws._select(2)
        before = state()
        walk = T.Tour(T.Guide(wb), wb)
        walk.start()
        seen = []
        while walk.is_open() and len(seen) < 90:
            seen.append(walk.key())
            walk.next_step()
        for key in ("import_menu", "search_settings", "people_tabs",
                    "facet_locations", "facet_account_imports", "btn_find",
                    "table", "tab_analytics"):
            self.assertIn(key, seen)
        self.assertEqual(seen[0], "import_menu")
        self.assertEqual(state(), before)

        walk.start()
        for _ in range(90):
            if walk.key() == "tab_saved" or not walk.is_open():
                break
            walk.next_step()
        self.assertEqual((walk.key(), walk.is_open()), ("tab_saved", True))
        walk.leave()
        self.assertEqual(state(), before)

    def test_no_reveal_starts_a_run_or_moves_a_setting(self):
        wb = self._wb()

        def state():
            return (wb._filters.spec().to_dict(), wb._source,
                    wb._target.value(), wb._limit.value(), wb._verify_limit.value(),
                    wb._offer.toPlainText(), wb._skip_seen.isChecked(), dict(wb.cfg))

        before = state()
        for key in _SEARCH_KEYS + ("notice", "nonsense"):
            wb.help_reveal(key)
        self.assertEqual(state(), before)
        self.assertIsNone(wb._worker)
        self.assertEqual(wb._jobs, 0)


class ResultRows(unittest.TestCase):
    """The default People view is a list of calm rows (addons/leads/result_rows.py), the look drafted in "Prism CRM: interface mockups"
    (3 Nov 2026). The table is still there as the other view."""

    def _person(self, name, title, company, location, fit, saved=False, check="valid"):
        from addons.leads import pool
        lead = Lead(name=name, title=title, company=company, email=name.lower() + "@x.com", fit_score=fit)
        lead.extra = {"email_check": check, "location": location}
        return pool.Person(lead=lead, saved=saved, stage="Cold" if saved else "", keys=frozenset({"n:" + name.lower()}))

    def test_it_opens_on_the_list_and_the_toggle_says_list(self):
        c = CK.LeadsCockpit()
        self.assertEqual(c._view, "cards")
        self.assertEqual((c._view_table_btn.text(), c._view_cards_btn.text()), ("Table", "List"))
        self.assertTrue(c._view_cards_btn.isChecked())

    def test_a_row_says_who_why_and_how_good(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("Ramesh Patel", 92, "r@x.com", "valid", company="Patel Switchgear")])
        row = c._grid.rows()[0]
        self.assertEqual(row.name.full_text(), "Ramesh Patel")
        self.assertIn("Patel Switchgear", row.company.full_text())
        self.assertIn("Founder", row.subline.full_text())
        self.assertEqual([p.text() for p in row.pills][:2], ["Verified", "Fit 92"])

    def test_open_opens_the_person_and_save_asks_to_save_someone_not_yet_saved(self):
        c = CK.LeadsCockpit()
        c.set_people([self._person("Anita Shah", "Head of Procurement", "Shah Automation", "Ahmedabad", 81),
                      self._person("Kale", "Owner", "Kale Panels", "Pune", 64, saved=True)],
                     {"page": 0, "pages": 1, "start": 1, "end": 2, "total": 2}, {"total": 2, "net_new": 1, "saved": 1})
        rows = c._grid.rows()
        self.assertEqual([b.text() for b in rows[0].buttons], ["Open", "Save"])
        self.assertEqual([b.text() for b in rows[1].buttons], ["Open"])               # already saved
        self.assertIn("Cold", [p.text() for p in rows[1].pills])                      # a saved person shows their stage
        asked = []
        c.saveContactsRequested.connect(asked.append)
        rows[0].buttons[1].click()
        self.assertEqual([d.lead.name for d in asked[0]], ["Anita Shah"])
        rows[0].buttons[0].click()
        self.assertFalse(c._drawer_w.isHidden())

    def test_the_table_is_still_one_click_away(self):
        c = CK.LeadsCockpit()
        c.set_dossiers([_dos("A", 90, "a@x.com", "valid")])
        c._set_view("table")
        self.assertEqual(c._view_stack.currentIndex(), 0)
        self.assertEqual(c._table.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()

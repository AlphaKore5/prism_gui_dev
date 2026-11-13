"""The Leads & Outreach walkthrough (addons.leads.tour).

The owner asked for a "?" that points at every filter, tag and feature on the
Leads screen and explains it, because his team read the help panel and still
could not tell which control a paragraph was about. These tests hold the two
promises that makes: the copy names every control by the key the screen
publishes, and the walk survives a screen that cannot show half of them.

They also hold the promise the tour must never break — that it only ever LOOKS
at the screen. A spy owner hands it widgets that scream if anything is ticked,
clicked or started, and the walk goes end to end without a sound.

Geometry is tested as pure rectangles (place_card, ring_rect), which is the
only way to check the awkward cases — a target hard against the right edge, a
card taller than the window — without showing a window.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QRect, QSize, Qt                # noqa: E402
from PySide6.QtGui import QKeyEvent                                # noqa: E402
from PySide6.QtWidgets import (                                    # noqa: E402
    QAbstractScrollArea, QApplication, QCheckBox, QWidget,
)

from addons.leads import tour as T                                 # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

# The keys the screen publishes — the shared contract between this walkthrough
# and the three parts that answer help_targets(). A step may only name one of
# these: a typo'd key is a step that silently never shows, which is the one
# failure nobody would notice by looking.
CONTRACT = {
    # addons/leads/workbench.py — Find new people, the run line. (Search
    # settings' rows are one toolbar step: they sit in a modal dialog.)
    "btn_find", "notice",
    # addons/leads/filter_panel.py
    "filters_head", "count_badge", "clear_all", "more_filters",
    "facet_locations", "facet_job_titles", "similar_titles", "facet_seniority",
    "facet_functions", "facet_industries", "facet_headcount", "facet_revenue",
    "facet_companies", "facet_company_hq", "facet_years", "facet_changed_jobs",
    "facet_keywords", "facet_contact_imports", "facet_account_imports",
    "facet_email_status", "facet_scores", "facet_lists", "facet_stages",
    "facet_custom_fields",
    # addons/leads/cockpit.py — Apollo's title row and toolbar, the three
    # tabs, the table, the pages, the action bar, the drawer, the tab strip
    "import_menu", "views_menu", "hide_filters", "people_search",
    "research_menu", "save_as_search", "view_toggle", "sort",
    "search_settings", "people_tabs", "table", "select_all", "col_lead",
    "col_focus", "col_fit", "col_status", "col_signal", "pager", "bulk_bar",
    "bulk_save", "bulk_remove", "bulk_verify", "bulk_emails", "bulk_phones", "bulk_list",
    "bulk_export", "bulk_stage", "bulk_qualify", "bulk_sequence", "drawer", "tab_people",
    "tab_companies", "tab_sessions",
    "tab_lists", "tab_saved", "tab_sequences", "tab_analytics", "tab_deals", "tab_due", "tab_stats",
}


class _Owner:
    """A screen that publishes some of the keys.

    A target only becomes findable once help_reveal() has been called for it,
    which is how "revealed before measured" is asserted: measure first and the
    tour finds nothing at all.
    """

    def __init__(self, host, keys, needs_reveal=True):
        self.host = host
        self.revealed = []
        self._needs_reveal = needs_reveal
        self._widgets = {}
        for i, key in enumerate(keys):
            w = QWidget(host)
            w.setGeometry(20, 20 + i * 40, 160, 30)
            self._widgets[key] = w

    def help_targets(self):
        if not self._needs_reveal:
            return dict(self._widgets)
        return {k: w for k, w in self._widgets.items() if k in self.revealed}

    def help_reveal(self, key):
        self.revealed.append(key)

    def widget(self, key):
        return self._widgets[key]


class _Loud(QWidget):
    """A target that shouts if the tour does anything but measure it."""

    def __init__(self, host, heard):
        super().__init__(host)
        self._heard = heard

    def click(self):
        self._heard.append("click")

    def start(self):
        self._heard.append("start")

    def setCheckState(self, *a):
        self._heard.append("setCheckState")

    def setChecked(self, *a):
        self._heard.append("setChecked")


def _host(w=1200, h=760):
    host = QWidget()
    host.resize(w, h)
    return host


def _key(tour, code):
    tour.keyPressEvent(QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))


class TheSteps(unittest.TestCase):
    def test_every_step_is_a_key_a_title_and_a_body(self):
        self.assertGreater(len(T.STEPS), 40)     # it points at everything
        for step in T.STEPS:
            self.assertEqual(len(step), 3, step)
            key, title, body = step
            self.assertIn(key, CONTRACT, key)
            self.assertTrue(title.strip(), key)
            self.assertLess(len(title), 44, title)          # a heading
            self.assertGreater(len(body.strip()), 60, key)  # a real answer
            self.assertLess(len(body), 420, key)            # not the help panel

    def test_it_points_at_every_filter_facet(self):
        keys = [k for k, _, _ in T.STEPS]
        for facet in (k for k in CONTRACT if k.startswith("facet_")):
            self.assertIn(facet, keys, facet)
        for extra in ("similar_titles", "count_badge", "clear_all",
                      "more_filters", "filters_head"):
            self.assertIn(extra, keys, extra)

    def test_it_points_at_every_part_the_screen_publishes(self):
        keys = set(k for k, _, _ in T.STEPS)
        self.assertEqual(CONTRACT - keys, set())

    def test_the_walk_reads_the_page_top_down_then_the_tabs(self):
        """Apollo's page as it is read: the title row, the toolbar, the
        rail, the results, the tabs."""
        keys = [k for k, _, _ in T.STEPS]
        where = [keys.index(k) for k in
                 ("import_menu", "views_menu", "search_settings",
                  "people_tabs", "facet_job_titles", "more_filters",
                  "facet_scores", "btn_find", "table", "col_fit", "pager",
                  "bulk_save", "bulk_qualify", "tab_people", "tab_analytics")]
        self.assertEqual(where, sorted(where))

    def test_what_a_thing_costs_is_said_where_it_is_spent(self):
        """The whole reason the help exists: nothing on the screen said which
        buttons spend money."""
        body = dict((k, b) for k, _, b in T.STEPS)
        # Leads runs on the Prism credit pool: every paid step says "credits",
        # and none of them names a vendor key the customer no longer holds.
        for key in ("bulk_emails", "bulk_qualify", "bulk_verify", "research_menu",
                    "btn_find", "search_settings"):
            self.assertIn("credit", body[key].lower(), key)
            for vendor in ("Groq", "Exa", "Apollo", "Hunter", "your keys"):
                self.assertNotIn(vendor, body[key], (key, vendor))
        self.assertIn("costs nothing", body["people_search"])
        self.assertIn("spends", body["btn_find"])
        self.assertIn("Nothing is searched", body["import_menu"])
        self.assertIn("free", body["filters_head"])
        # What the search it runs costs, where the settings are.
        self.assertIn("finds nobody is not", body["search_settings"])

    def test_the_status_tags_are_all_named(self):
        body = dict((k, b) for k, _, b in T.STEPS)["col_status"]
        for tag in ("Verified", "Unverified", "Catch-all", "Unknown", "Invalid",
                    "No email", "Mailed"):
            self.assertIn(tag, body, tag)

    def test_the_copy_survives_the_string_extractor(self):
        # _is_copy() drops anything that looks like a stylesheet or markup, and
        # a dropped body ships untranslatable.
        for key, title, body in T.STEPS:
            for text in (title, body):
                self.assertNotIn(";", text, key)
                self.assertNotIn("<", text, key)
                self.assertNotIn(">", text, key)
                self.assertNotIn("{", text, key)
            # ...and a key must stay the shape _is_copy() rejects, or every
            # one of them lands in the translation catalogue as a phrase.
            self.assertNotIn(" ", key)
            self.assertTrue("_" in key or (key.islower() and len(key) < 14
                                           and key.isalnum()), key)


class TheGeometry(unittest.TestCase):
    BOUNDS = QRect(0, 0, 1000, 800)
    CARD = QSize(330, 200)

    def test_it_sits_beside_the_target_when_there_is_room(self):
        target = QRect(200, 300, 160, 40)
        card = T.place_card(target, self.CARD, self.BOUNDS)
        self.assertGreater(card.left(), target.right())
        self.assertFalse(card.intersects(target))
        self.assertTrue(self.BOUNDS.contains(card))

    def test_no_room_on_the_right_puts_it_on_the_left(self):
        target = QRect(700, 300, 160, 40)
        card = T.place_card(target, self.CARD, self.BOUNDS)
        self.assertLess(card.right(), target.left())
        self.assertFalse(card.intersects(target))

    def test_a_wide_target_pushes_it_below(self):
        target = QRect(20, 100, 960, 40)         # the notice line, full width
        card = T.place_card(target, self.CARD, self.BOUNDS)
        self.assertGreater(card.top(), target.bottom())
        self.assertFalse(card.intersects(target))

    def test_a_wide_target_at_the_foot_puts_it_above(self):
        target = QRect(20, 700, 960, 60)         # the bulk bar
        card = T.place_card(target, self.CARD, self.BOUNDS)
        self.assertLess(card.bottom(), target.top())
        self.assertFalse(card.intersects(target))

    def test_it_is_always_inside_the_window(self):
        for target in (QRect(0, 0, 40, 20), QRect(960, 0, 40, 20),
                       QRect(0, 780, 40, 20), QRect(960, 780, 40, 20),
                       QRect(400, 380, 200, 40), QRect(-40, -40, 120, 60)):
            card = T.place_card(target, self.CARD, self.BOUNDS)
            self.assertTrue(self.BOUNDS.contains(card), target)

    def test_a_card_taller_than_the_window_starts_at_the_top(self):
        card = T.place_card(QRect(400, 100, 100, 40), QSize(330, 900),
                            self.BOUNDS)
        self.assertEqual((card.left() >= 0, card.top()), (True, 0))

    def test_a_target_that_fills_the_area_takes_the_card_in_its_corner(self):
        """The whole table: no side has room, and clamped to the top the card
        sat on the ring's own edge and the column headings. Inside the ring's
        bottom-right corner it covers neither."""
        bounds, card = QRect(0, 0, 1296, 640), QSize(330, 178)
        table = QRect(342, 152, 938, 456)
        placed = T.place_card(table, card, bounds)
        self.assertTrue(table.contains(placed))
        self.assertEqual(placed.right(), table.right() - T.GAP)
        self.assertEqual(placed.bottom(), table.bottom() - T.GAP)
        self.assertTrue(bounds.contains(placed))

    def test_a_small_target_with_no_room_anywhere_still_fits_the_window(self):
        # Too small to hold the card: the old clamp, never a card over it all.
        bounds, card = QRect(0, 0, 400, 300), QSize(330, 178)
        placed = T.place_card(QRect(150, 120, 100, 40), card, bounds)
        self.assertTrue(bounds.contains(placed))

    def test_the_ring_pads_the_target_and_is_clipped_to_the_window(self):
        ring = T.ring_rect(QRect(100, 100, 60, 20), self.BOUNDS)
        self.assertEqual(ring, QRect(100 - T.RING_PAD, 100 - T.RING_PAD,
                                     60 + 2 * T.RING_PAD, 20 + 2 * T.RING_PAD))
        # Half scrolled out of view: what is left still reads.
        half = T.ring_rect(QRect(-30, 400, 60, 20), self.BOUNDS)
        self.assertEqual(half.left(), 0)
        self.assertLess(half.width(), 60 + 2 * T.RING_PAD)


class Walking(unittest.TestCase):
    def _tour(self, keys, steps=None, needs_reveal=True):
        host = _host()
        owner = _Owner(host, keys, needs_reveal=needs_reveal)
        walk = T.Tour(owner, host, steps=steps)
        return host, owner, walk

    def test_it_opens_on_the_first_step_it_can_point_at(self):
        steps = (("import_menu", "One", "The first body, long enough to be a "
                                        "real sentence about a real control."),
                 ("table", "Two", "The second body, also long enough to read "
                                  "as prose rather than as a label."))
        host, owner, walk = self._tour(["table"], steps=steps)
        walk.start()
        self.assertTrue(walk.is_open())
        self.assertEqual(walk.key(), "table")        # step one had no target
        self.assertEqual(walk.position(), 1)
        self.assertFalse(walk.ring().isEmpty())

    def test_reveal_happens_before_the_measurement(self):
        # _Owner publishes a target only AFTER its key has been revealed, so a
        # tour that measured first would find nothing and end at once.
        host, owner, walk = self._tour(["table"])
        walk.start()
        self.assertEqual(walk.key(), "table")
        # Every step up to that one was asked to open itself, in order — and
        # each asked TWICE, because a fold that has only just been unhidden has
        # not been laid out when the same call goes on to scroll to it.
        keys = [k for k, _, _ in T.STEPS]
        self.assertEqual(owner.revealed,
                         [k for k in keys[:keys.index("table") + 1]
                          for _ in (0, 1)])

    def test_next_and_back_walk_the_steps_that_exist(self):
        keys = ["import_menu", "table", "tab_analytics"]
        host, owner, walk = self._tour(keys)
        walk.start()
        self.assertEqual(walk.key(), "import_menu")
        walk.next_step()
        self.assertEqual(walk.key(), "table")
        self.assertEqual(walk.position(), 2)
        walk.back()
        self.assertEqual(walk.key(), "import_menu")
        self.assertEqual(walk.position(), 1)
        walk.back()                                  # nothing behind the first
        self.assertEqual(walk.key(), "import_menu")
        self.assertTrue(walk.is_open())

    def test_a_screen_with_almost_nothing_on_it_still_reaches_the_end(self):
        host, owner, walk = self._tour(["bulk_export"])
        ended = []
        walk.finished.connect(lambda: ended.append(1))
        walk.start()
        self.assertEqual(walk.key(), "bulk_export")
        walk.next_step()                             # nothing after it resolves
        self.assertFalse(walk.is_open())
        self.assertEqual(ended, [1])

    def test_a_screen_with_no_targets_at_all_ends_instead_of_stranding(self):
        host, owner, walk = self._tour([])
        ended = []
        walk.finished.connect(lambda: ended.append(1))
        walk.start()
        self.assertFalse(walk.is_open())
        self.assertEqual(ended, [1])

    def test_an_owner_without_a_snapshot_finishes_on_the_leads_tab(self):
        """The walk ends on Analytics, six tabs away from the work. A screen
        that cannot say where it was is at least put back on Leads."""
        host, owner, walk = self._tour(["tab_people", "tab_analytics"])
        walk.start()
        self.assertEqual(walk.key(), "tab_people")
        walk.next_step()
        self.assertEqual(walk.key(), "tab_analytics")
        walk.next_step()
        self.assertFalse(walk.is_open())
        self.assertEqual(owner.revealed[-1], "tab_people")

    def test_finishing_or_escaping_restores_the_screen_it_found(self):
        """Hide filters, the Sessions tab, two open facets: a walk moves all of
        them to point at things, and must hand every one back — walked off the
        end, or left with Esc on the Saved searches step."""
        host, owner, walk = self._tour(["tab_people", "tab_saved", "tab_analytics"])
        screen = {"tab": "sessions"}
        owner.help_snapshot = lambda: dict(screen)
        restored = []

        def restore(snap):
            restored.append(dict(snap))
            screen.clear()
            screen.update(snap)

        owner.help_restore = restore
        for leave in (lambda: _key(walk, Qt.Key_Escape),
                      lambda: [walk.next_step() for _ in range(3)]):
            restored.clear()
            walk.start()
            screen["tab"] = "saved"                  # what a reveal did
            walk.next_step()
            walk.start()                             # a restart keeps the FIRST
            screen["tab"] = "analytics"              # snapshot, not this one
            leave()
            self.assertFalse(walk.is_open())
            self.assertEqual(screen, {"tab": "sessions"})
            self.assertTrue(restored)
        # Walked off the end with a snapshot: no extra trip to the Leads tab
        # on the way out, or the restore would land on the wrong screen. The last
        # reveal is the last step the walk tried (it tries every step, found or
        # not), which is now Due today, the final tab, and no longer Analytics.
        self.assertEqual(owner.revealed[-1], T.STEPS[-1][0])

    def test_tab_never_walks_the_focus_under_the_scrim(self):
        """Qt's focus chain runs on from the card to whatever is underneath —
        a Verified box, a tab button — and Space then ticks it while the tour
        stays up. Tab and Shift+Tab must leave the focus on the card."""
        host, owner, walk = self._tour(["table"])
        under = QCheckBox("Verified", host)
        under.setFocusPolicy(Qt.StrongFocus)
        under.setChecked(True)
        walk.start()
        self.assertIs(host.focusWidget(), walk.card())
        for code in (Qt.Key_Tab, Qt.Key_Backtab):
            QApplication.sendEvent(walk.card(),
                                   QKeyEvent(QEvent.KeyPress, code, Qt.NoModifier))
            self.assertIs(host.focusWidget(), walk.card())
        self.assertTrue(under.isChecked())
        self.assertTrue(walk.is_open())

    def test_focus_that_lands_under_the_scrim_is_taken_back(self):
        # The backstop, for a mnemonic or a control that focuses itself.
        host, owner, walk = self._tour(["table"])
        under = QCheckBox("Verified", host)
        under.setFocusPolicy(Qt.StrongFocus)
        walk.start()
        under.setFocus()
        walk._hold_focus(None, under)
        self.assertIs(host.focusWidget(), walk.card())
        # ...but something raised OVER the walk (the help panel, on F1) keeps it.
        above = QCheckBox("Close", host)
        above.raise_()
        self.assertFalse(walk._below(above))
        self.assertTrue(walk._below(under))
        walk.leave()
        under.setFocus()                             # a closed walk holds nothing
        walk._hold_focus(None, under)
        self.assertIs(host.focusWidget(), under)

    def test_a_ring_stops_at_the_edge_of_the_scroll_area_it_is_in(self):
        """A rail control half past the rail's bottom was ringed in full, down
        over the page margin. The ring stops where the viewport does — and a
        header, a child of the table but not of its viewport, is not cut."""
        host = _host()
        area = QAbstractScrollArea(host)
        area.setGeometry(100, 100, 300, 300)
        port = area.viewport()
        port.setGeometry(0, 40, 300, 200)           # shows y 140..339 of host
        head = QWidget(area)
        head.setGeometry(0, 0, 300, 40)             # like a table header
        inner = QWidget(port)
        inner.setGeometry(0, 0, 300, 600)
        grid = QWidget(inner)
        grid.setGeometry(20, 170, 160, 80)          # host y 310..389, half out

        class Owner:
            def help_targets(self):
                return {"people_tabs": grid, "col_fit": head}

        walk = T.Tour(Owner(), host, steps=(
            ("people_tabs", "Grid", "A body long enough to be read as a "
                                              "sentence about the grid."),
            ("col_fit", "Head", "A body long enough to be read as a sentence "
                                "about the header row.")))
        walk.start()
        port_rect = QRect(100, 140, 300, 200)
        self.assertEqual(walk.key(), "people_tabs")
        self.assertTrue(port_rect.contains(walk.ring()))
        self.assertEqual(walk.ring().bottom(), port_rect.bottom())
        walk.next_step()
        self.assertEqual(walk.key(), "col_fit")
        self.assertTrue(walk.ring().contains(QRect(100, 100, 300, 40)))

    def test_the_keys_move_and_escape_leaves(self):
        host, owner, walk = self._tour(["import_menu", "table"])
        walk.start()
        _key(walk, Qt.Key_Right)
        self.assertEqual(walk.key(), "table")
        _key(walk, Qt.Key_Left)
        self.assertEqual(walk.key(), "import_menu")
        _key(walk, Qt.Key_Space)
        self.assertEqual(walk.key(), "table")
        _key(walk, Qt.Key_Backspace)
        self.assertEqual(walk.key(), "import_menu")
        _key(walk, Qt.Key_Escape)
        self.assertFalse(walk.is_open())

    def test_the_cards_buttons_do_the_same_as_the_keys(self):
        host, owner, walk = self._tour(["import_menu", "table"])
        walk.start()
        walk._next_btn.click()
        self.assertEqual(walk.key(), "table")
        walk._back_btn.click()
        self.assertEqual(walk.key(), "import_menu")
        walk._leave_btn.click()
        self.assertFalse(walk.is_open())

    def test_the_card_says_where_you_are_and_is_inside_the_window(self):
        host, owner, walk = self._tour(["facet_keywords"])
        walk.start()
        self.assertIn(str(len(T.STEPS)), walk._count.text())
        self.assertTrue(walk._title.text())
        self.assertTrue(walk._body.text())
        self.assertTrue(walk.rect().contains(walk.card().geometry()))
        self.assertFalse(walk.card().geometry().intersects(walk.ring()))

    def test_the_buttons_never_take_the_focus_from_the_card(self):
        # Otherwise Space would press whatever the last click focused instead
        # of stepping the tour.
        host, owner, walk = self._tour(["table"])
        walk.start()
        for button in (walk._next_btn, walk._back_btn, walk._leave_btn):
            self.assertEqual(button.focusPolicy(), Qt.NoFocus)
        self.assertEqual(walk.card().focusPolicy(), Qt.StrongFocus)

    def test_starting_twice_does_not_stack_two_overlays(self):
        host, owner, walk = self._tour(["import_menu", "table"])
        walk.start()
        walk.next_step()
        walk.start()
        self.assertEqual(len(host.findChildren(T.Tour)), 1)
        self.assertEqual(walk.position(), 1)          # back at the beginning
        self.assertEqual(walk.key(), "import_menu")

    def test_a_resize_re_measures_without_re_revealing(self):
        host, owner, walk = self._tour(["table"])
        walk.start()
        seen = len(owner.revealed)
        host.resize(900, 700)
        walk.place()
        self.assertTrue(walk.rect().contains(walk.card().geometry()))
        self.assertEqual(len(owner.revealed), seen)

    def test_it_never_touches_the_screen_it_points_at(self):
        host = _host()
        heard = []
        loud = {key: _Loud(host, heard) for key in
                ("import_menu", "table", "bulk_qualify", "tab_analytics")}
        for i, w in enumerate(loud.values()):
            w.setGeometry(30, 30 + i * 60, 200, 40)

        class Spy:
            def __init__(self):
                self.revealed = []

            def help_targets(self):
                return dict(loud)

            def help_reveal(self, key):
                self.revealed.append(key)

        walk = T.Tour(Spy(), host)
        walk.start()
        for _ in range(len(T.STEPS) + 2):
            walk.next_step()
        self.assertEqual(heard, [])
        self.assertFalse(walk.is_open())

    def test_a_hidden_target_is_skipped(self):
        host, owner, walk = self._tour(["import_menu", "table"],
                                       needs_reveal=False)
        owner.widget("import_menu").hide()       # a folded facet, a bulk bar
        walk.start()                             # with nothing ticked
        self.assertEqual(walk.key(), "table")

    def test_a_sub_rectangle_target_is_ringed_where_it_sits(self):
        """A column heading is part of one header widget, so a key may answer
        with (widget, QRect) instead of a widget."""
        host = _host()
        head = QWidget(host)
        head.setGeometry(100, 50, 800, 36)
        cell = QRect(300, 0, 120, 36)

        class Owner:
            def help_targets(self):
                return {"col_fit": (head, cell)}

        walk = T.Tour(Owner(), host)
        walk.start()
        self.assertEqual(walk.key(), "col_fit")
        self.assertTrue(walk.ring().contains(QRect(400, 60, 20, 20)))
        self.assertLess(walk.ring().width(), head.width())

    def test_an_owner_that_raises_is_survived(self):
        host = _host()

        class Broken:
            def help_targets(self):
                raise RuntimeError("no")

            def help_reveal(self, key):
                raise RuntimeError("no")

        walk = T.Tour(Broken(), host)
        walk.start()
        self.assertFalse(walk.is_open())          # ended, not crashed


class TheGuide(unittest.TestCase):
    """Guide gathers the parts of one screen into a single owner."""

    def _screen(self):
        host = _host()
        inner = QWidget(host)
        rail = _Part(inner, {"import_menu": QWidget(inner)})
        deep = _Part(inner, {"facet_keywords": QWidget(inner)})
        return host, rail, deep

    def test_it_finds_every_part_of_the_tree(self):
        host, rail, deep = self._screen()
        guide = T.Guide(host)
        self.assertEqual(set(guide.help_targets()),
                         {"import_menu", "facet_keywords"})

    def test_it_asks_every_part_to_reveal(self):
        host, rail, deep = self._screen()
        guide = T.Guide(host)
        guide.help_reveal("facet_keywords")
        self.assertEqual(rail.revealed, ["facet_keywords"])
        self.assertEqual(deep.revealed, ["facet_keywords"])

    def test_a_part_built_later_is_found_after_a_refresh(self):
        host, rail, deep = self._screen()
        guide = T.Guide(host)
        guide.help_targets()                       # the walk is cached
        _Part(host, {"table": QWidget(host)})
        self.assertNotIn("table", guide.help_targets())
        guide.help_refresh()
        self.assertIn("table", guide.help_targets())

    def test_it_restores_every_part_inside_out(self):
        """The facets and the cockpit come back before the tab strip holding
        them switches, so the tab lands last on a screen already put back."""
        host = _host()
        order = []

        class Snap(_Part):
            def __init__(self, parent, name):
                super().__init__(parent, {name: QWidget(parent)})
                self.name = name

            def help_snapshot(self):
                return self.name

            def help_restore(self, snap):
                order.append(snap)

        tabs = Snap(host, "tabs")
        cockpit = Snap(tabs, "cockpit")
        Snap(cockpit, "facets")
        guide = T.Guide(host)
        taken = guide.help_snapshot()
        guide.help_restore(taken)
        self.assertEqual(order, ["facets", "cockpit", "tabs"])

    def test_a_broken_part_does_not_take_the_others_down(self):
        host, rail, deep = self._screen()

        class Broken(QWidget):
            def help_targets(self):
                raise RuntimeError("no")

        Broken(host)
        guide = T.Guide(host)
        self.assertIn("import_menu", guide.help_targets())


class _Part(QWidget):
    """A widget that answers the contract, for the Guide tests."""

    def __init__(self, parent, targets):
        super().__init__(parent)
        self._targets = targets
        self.revealed = []

    def help_targets(self):
        return dict(self._targets)

    def help_reveal(self, key):
        self.revealed.append(key)


if __name__ == "__main__":
    unittest.main()

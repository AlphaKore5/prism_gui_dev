"""Find buyers — the store, the page, the controller and the tab (addons/leads/buyers_*.py).

No network, no model, no thread and no real folder: the licence server is a fake
transport, the workers are mocks (a test never runs a QThread's event loop), and
every folder is a temp one. Nothing here may reach the real ~/.prism."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                       # noqa: E402

import core_bridge  # noqa: F401,E402
from addons.leads import buyers_controller as BC                # noqa: E402
from addons.leads import buyers_page as BP                      # noqa: E402
from addons.leads import buyers_store as BS                     # noqa: E402
from addons.leads import cockpit as CK                          # noqa: E402
from addons.leads import result_rows as RR                      # noqa: E402
from addons.leads import contacts as CT                         # noqa: E402
from addons.leads.store import StoreError                       # noqa: E402
from prospector import buyers as B                              # noqa: E402
from prospector import gateway as G                             # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

def _score_of(hits, who):
    return next(h.score for h in hits if h.who == who)


OFFER = B.Offer("We make PCBs for hardware startups", website="https://acme.in", regions="Gujarat")


def _types():
    return [B.BuyerType(key="startups", name="Hardware startups", why="They order boards.",
                        needs=["pcb fabrication"], who_decides=["Founder"]),
            B.BuyerType(key="makers", name="EV makers", why="They need BMS boards.")]


def _hit(n: int, *, channel=B.TENDER, status=B.OPEN, intent=80, decision=B.NEW, closes="2026-12-01"):
    return B.Hit(id=f"id{n}", channel=channel, kind=B.KIND_OF[channel], who=f"Buyer {n}", title=f"Title {n}",
                 snippet=f"Evidence {n}", url=f"https://site{n}.in/page", source=f"site{n}.in",
                 closes=closes if channel == B.TENDER else "", status=status, fit=70, intent=intent,
                 why=f"Why {n}", buyer_type="startups", scored_by="model", decision=decision)


def _result(hits=None, notes=(), **stats):
    return B.HuntResult(hits=hits if hits is not None else [_hit(1), _hit(2, intent=50)],
                        stats={"searches": 2, **stats}, notes=list(notes))


class _Status:
    def __init__(self):
        self.text = ""

    def setText(self, text):
        self.text = text


class _Host:
    """What the controller reads off the workbench."""

    def __init__(self, folder):
        self.folder = folder
        self.cfg = {}
        self._status = _Status()
        self.kept: list = []
        self.keep_ok = True
        self.answer = True
        self.asked: list = []
        self.refreshed = 0

    def _contacts_dir(self):
        return os.path.join(self.folder, "leads", "contacts")

    def _keep_as_contacts(self, leads, via, list_name=""):
        self.kept.append((list(leads), via))
        return self.keep_ok

    def _confirm_pool(self, title, lines):
        self.asked.append((title, list(lines)))
        return self.answer

    def _refresh_credits(self):
        self.refreshed += 1


class TheStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_a_hunt_is_kept_newest_first_and_cards_come_back_as_cards(self):
        a = BS.save_hunt(self.folder, offer=OFFER, summary="one", types=_types(), channels=(B.TENDER,),
                         preview=True, result=_result())
        b = BS.save_hunt(self.folder, offer=OFFER, summary="two", types=_types(), channels=(B.TENDER, B.NEWS),
                         preview=False, result=_result(notes=["a note"]))
        hunts = BS.list_hunts(self.folder)
        self.assertEqual([h["id"] for h in hunts], [b["id"], a["id"]])
        self.assertEqual(hunts[0]["channels"], [B.TENDER, B.NEWS])
        self.assertEqual(hunts[0]["notes"], ["a note"])
        self.assertTrue(all(isinstance(h, B.Hit) for h in hunts[0]["hits"]))
        self.assertEqual(hunts[1]["hits"][0].who, "Buyer 1")
        self.assertTrue(hunts[1]["preview"])

    def test_a_decision_is_kept_and_only_for_that_card(self):
        hunt = BS.save_hunt(self.folder, offer=OFFER, summary="", types=_types(), channels=(B.TENDER,),
                            preview=False, result=_result())
        self.assertEqual(BS.set_decisions(self.folder, hunt["id"], ["id1"], B.NOT_A_FIT, "too big"), 1)
        again = BS.get_hunt(self.folder, hunt["id"])
        self.assertEqual([(h.id, h.decision, h.reason) for h in again["hits"]],
                         [("id1", B.NOT_A_FIT, "too big"), ("id2", B.NEW, "")])
        self.assertEqual(BS.set_decisions(self.folder, hunt["id"], ["id1"], B.NOT_A_FIT, "too big"), 0)
        self.assertEqual(BS.set_decisions(self.folder, "nope", ["id1"], B.SKIPPED), 0)

    def test_only_thirty_hunts_are_kept(self):
        for i in range(BS.KEEP + 3):
            BS.save_hunt(self.folder, offer=OFFER, summary=str(i), types=[], channels=(), preview=False,
                         result=_result([]))
        hunts = BS.list_hunts(self.folder)
        self.assertEqual(len(hunts), BS.KEEP)
        self.assertEqual(hunts[0]["summary"], str(BS.KEEP + 2))

    def test_the_offer_is_remembered_with_what_was_read_from_it(self):
        self.assertEqual(BS.load_offer(self.folder)[0].text, "")
        BS.save_offer(self.folder, OFFER, "PCBs for startups", _types())
        offer, summary, types = BS.load_offer(self.folder)
        self.assertEqual((offer.text, offer.website, offer.regions), (OFFER.text, OFFER.website, OFFER.regions))
        self.assertEqual((summary, [t.name for t in types]), ("PCBs for startups", ["Hardware startups", "EV makers"]))
        self.assertEqual(types[0].needs, ["pcb fabrication"])

    def test_a_card_from_an_old_hunt_that_would_be_blocked_now_is_not_shown_but_stays_on_disk(self):
        """The exa.ai listing was saved in a hunt run before it was learnt to be no buyer, and came back on every open."""
        bad = _hit(1)
        bad.url, bad.source, bad.who = "https://exa.ai/library/places?ids=l768k0p051x%2Ckwnh075ll2k%2Cssml64f70pw%2C25wstgx9gcy%2Crgvk7cwdgqs%2C63d277y5j62%2Cgsfdx6yk3kl%2Cql62nsfx6wc%2Cnws3y4w02kp%2C0w68d4clv5n", "exa.ai", "exa.ai"
        own = _hit(2)
        own.url, own.source = "https://shop.acme.in/page", "shop.acme.in"
        hunt = BS.save_hunt(self.folder, offer=OFFER, summary="", types=_types(), channels=(B.ASKING,), preview=False,
                            result=_result([bad, own, _hit(3)]))
        self.assertEqual([h.id for h in hunt["hits"]], ["id3"])                      # OFFER's website is acme.in
        self.assertEqual([h.id for h in BS.get_hunt(self.folder, hunt["id"])["hits"]], ["id3"])
        with open(os.path.join(self.folder, BS.HUNTS_FILE), encoding="utf-8") as f:
            self.assertIn("exa.ai/library/places", f.read())                         # nothing was rewritten or lost

    def test_a_damaged_file_reads_as_nothing_and_a_newer_prisms_file_is_never_written_over(self):
        path = os.path.join(self.folder, BS.HUNTS_FILE)
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(BS.list_hunts(self.folder), [])
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"schema": 99, "hunts": [{"id": "x"}]}')
        with self.assertRaises(StoreError):
            BS.save_hunt(self.folder, offer=OFFER, summary="", types=[], channels=(), preview=False,
                         result=_result([]))
        with open(path, encoding="utf-8") as f:
            self.assertIn('"schema": 99', f.read())


class ThePage(unittest.TestCase):
    def setUp(self):
        self.p = BP.BuyersPage()
        self.read, self.hunts, self.accepted, self.decided, self.opened = [], [], [], [], []
        self.p.readRequested.connect(self.read.append)
        self.p.huntRequested.connect(lambda *a: self.hunts.append(a))
        self.p.acceptRequested.connect(self.accepted.append)
        self.p.decisionRequested.connect(lambda *a: self.decided.append(a))
        self.p.openRequested.connect(self.opened.append)

    def _ready(self):
        self.p.offer_edit.setPlainText(OFFER.text)
        self.p.set_types("PCBs for startups", _types())

    def test_it_starts_with_one_box_and_nothing_else(self):
        self.assertFalse(self.p.find_btn.isEnabled())
        self.assertTrue(self.p._understood.isHidden())
        self.assertTrue(self.p._results.isHidden())
        self.p.find_btn.click()
        self.assertEqual(self.read, [])

    def test_describing_the_offer_enables_find_and_sends_it_with_the_website_and_region(self):
        self.p.offer_edit.setPlainText("  We make PCBs ")
        self.p.site_edit.setText("https://acme.in")
        self.p.region_edit.setText("Gujarat")
        self.assertTrue(self.p.find_btn.isEnabled())
        self.p.find_btn.click()
        [o] = self.read
        self.assertEqual((o.text, o.website, o.regions), ("We make PCBs", "https://acme.in", "Gujarat"))

    def test_what_prism_understood_shows_the_types_and_the_default_sources(self):
        self._ready()
        self.assertFalse(self.p._understood.isHidden())
        self.assertEqual(self.p.summary.text(), "PCBs for startups")
        self.assertEqual(list(self.p.type_boxes), ["startups", "makers"])
        self.assertTrue(all(b.isChecked() for b in self.p.type_boxes.values()))
        self.assertEqual(self.p.channels(), (B.LIST,))      # the company list; every web search is opt-in
        self.assertIn("web searches", self.p.estimate.text())

    def test_a_long_reason_wraps_and_never_makes_the_page_wider_than_the_window(self):
        """What matters is not a number of pixels (fonts differ) but that long words add no width."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QScrollArea

        def width_with(reason, summary, note):
            page = BP.BuyersPage()
            page.offer_edit.setPlainText(OFFER.text)
            page.set_types(summary, [B.BuyerType(key="a", name="Hardware startups", why=reason),
                                     B.BuyerType(key="b", name="EV makers", why=reason)])
            page.set_hunt({"id": "h", "preview": False, "stats": {}, "notes": [note], "hits": [_hit(1), _hit(2)]})
            return page._host.minimumSizeHint().width(), page
        short, _p = width_with("Short.", "Short.", "Short.")
        long, page = width_with("They order boards every month, in volumes that change with each round. " * 6,
                                "A summary that is also rather long. " * 8, "A long note. " * 40)
        self.assertLessEqual(long, short + 4)
        self.assertEqual(page.findChild(QScrollArea).horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff)

    def test_the_words_beside_a_tick_box_tick_it(self):
        self._ready()
        row = self.p._types_col.itemAt(0).widget()
        self.assertTrue(row.box.isChecked())
        row.words.clicked.emit()
        self.assertFalse(self.p.type_boxes["startups"].isChecked())
        self.assertFalse(self.p.run_btn.isEnabled() and not any(
            t.enabled for t in self.p.types()))

    def test_the_preview_and_the_full_search_send_what_is_ticked(self):
        self._ready()
        self.p.type_boxes["makers"].setChecked(False)
        self.p.channel_boxes[B.LIST].setChecked(False)
        self.p.channel_boxes[B.TENDER].setChecked(True)
        self.p.channel_boxes[B.HIRING].setChecked(True)
        self.p.preview_btn.click()
        self.p.run_btn.click()
        (offer, summary, types, channels, preview), (_o, _s, _t, _c, full) = self.hunts
        self.assertEqual((summary, channels, preview, full), ("PCBs for startups", (B.TENDER, B.HIRING), True, False))
        self.assertEqual([(t.key, t.enabled) for t in types], [("startups", True), ("makers", False)])
        self.assertEqual(offer.text, OFFER.text)

    def test_nothing_ticked_means_nothing_to_run(self):
        self._ready()
        for box in self.p.type_boxes.values():
            box.setChecked(False)
        self.assertFalse(self.p.run_btn.isEnabled())
        self.assertIn("at least one", self.p.estimate.text())
        self.p.type_boxes["startups"].setChecked(True)
        for box in self.p.channel_boxes.values():
            box.setChecked(False)
        self.assertFalse(self.p.preview_btn.isEnabled())

    def test_a_busy_page_cannot_start_another_search(self):
        self._ready()
        self.p.set_busy(True, "Searching 1 of 6…")
        self.assertEqual(self.p.status.text(), "Searching 1 of 6…")
        self.assertFalse(self.p.find_btn.isEnabled() or self.p.run_btn.isEnabled() or self.p.preview_btn.isEnabled())
        self.p.set_busy(False, "")
        self.assertTrue(self.p.run_btn.isEnabled())
        self.assertTrue(self.p.status.isHidden())

    def _hunt(self, hits, **kw):
        return {"id": "h1", "preview": False, "hits": hits, "stats": {}, "notes": [], **kw}

    def test_cards_show_the_best_and_hide_closed_bids_until_asked(self):
        shut = _hit(3, status=B.CLOSED, intent=0, closes="2026-11-20")
        self.p.set_hunt(self._hunt([_hit(1), _hit(2, channel=B.HIRING, status=B.RECENT), shut]))
        self.assertEqual(self.p.list.count(), 2)
        self.assertIn("2 buyers worth a look", self.p.headline.text())
        self.assertIn("1 closed bid hidden", self.p.headline.text())
        self.p.show_closed.setChecked(True)
        self.assertEqual(self.p.list.count(), 3)
        self.assertNotIn("hidden", self.p.headline.text())

    def test_a_click_on_a_row_opens_the_panel_and_does_not_leave_the_app(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.assertTrue(self.p.panel.isHidden())
        self.p.list.rows()[0].clicked.emit(0)
        panel = self.p.panel
        self.assertFalse(panel.isHidden())
        self.assertEqual(self.opened, [])                                   # the browser was not opened
        self.assertEqual(panel.name.text(), "Buyer 1")
        self.assertEqual(panel.hit.id, "id1")
        self.assertIn("Public tender", panel.role.text())
        self.assertEqual(panel.reach.text(), "site1.in")

    def test_the_panel_draws_the_same_qualification_the_person_drawer_does(self):
        self.p.set_types("s", _types())
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.p.list.rows()[0].clicked.emit(0)
        from PySide6.QtWidgets import QLabel
        words = " | ".join(l.text() for l in self.p.panel._pages["buyer"].parentWidget().findChildren(QLabel))
        for expect in ("HOT", f"{_hit(1).score} / 100", "Why 1", "QUALIFICATION", "Fit", "Need", "Timing", "Pass",
                       "The bid closes on 1 Dec 2026.", "WHY NOW", "Evidence 1", "Read the source"):
            self.assertIn(expect, words)
        info = " | ".join(l.text() for l in self.p.panel._left.findChildren(QLabel))
        self.assertIn("Hardware startups", info)                           # the kind of buyer it was found for
        self.assertIn("1 Dec 2026", info)

    def test_the_panel_has_the_three_tabs_and_the_whole_page_text(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.p.list.rows()[0].clicked.emit(0)
        panel = self.p.panel
        self.assertEqual(list(panel.tab_btns), ["buyer", "page", "fields"])
        self.assertEqual(panel.tab(), "buyer")
        panel.set_tab("page")
        self.assertEqual(panel._stack.currentIndex(), 1)
        from PySide6.QtWidgets import QLabel
        self.assertIn("Evidence 1", [l.text() for l in panel._pages["page"].parentWidget().findChildren(QLabel)])
        panel.set_tab("fields")
        self.assertIn("https://site1.in/page", " ".join(
            l.text() for l in panel._pages["fields"].parentWidget().findChildren(QLabel)))

    def test_the_panel_can_accept_put_away_open_the_source_and_copy_the_link(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.p.list.rows()[0].clicked.emit(0)
        panel = self.p.panel
        panel.act_open.trigger()
        self.assertEqual(self.opened, ["https://site1.in/page"])
        with mock.patch.object(type(panel), "_copy") as copied:
            panel.act_copy.trigger()
        copied.assert_called_once()
        panel.accept_btn.click()
        self.assertEqual([h.id for h in self.accepted[0]], ["id1"])
        by_label = {a.text(): a for a in panel.notfit_btn.menu().actions()}              # one tap says why
        self.assertEqual(list(by_label), ["Wrong size", "Wrong country or place", "They sell the same thing",
                                          "Not buying what I sell", "Already my customer", "Something else"])
        by_label["Wrong size"].trigger()
        self.assertEqual(self.decided, [(["id1"], B.NOT_A_FIT, "Wrong size")])

    def test_a_card_already_judged_shows_no_accept_and_says_where_it_stands(self):
        self.p.set_hunt(self._hunt([_hit(1, decision=B.ACCEPTED)]))
        self.p.list.rows()[0].clicked.emit(0)
        panel = self.p.panel
        self.assertTrue(panel.accept_btn.isHidden() and panel.notfit_btn.isHidden())
        self.assertEqual(panel._state_pill.text(), "Accepted")

    def test_the_open_panel_follows_a_decision_and_closes_on_x(self):
        hunt = self._hunt([_hit(1)])
        self.p.set_hunt(hunt)
        self.p.list.rows()[0].clicked.emit(0)
        B.decide(hunt["hits"], ["id1"], B.ACCEPTED)
        self.p.set_hunt(hunt)                                               # the controller redraws after a decision
        self.assertEqual(self.p.panel._state_pill.text(), "Accepted")
        self.p.panel.closeRequested.emit()
        self.assertTrue(self.p.panel.isHidden())
        self.assertIsNone(self.p.panel.hit)

    def test_the_page_is_never_wider_than_the_window_it_scrolls_in_with_the_panel_open(self):
        """The bug: the content was 850px wide in an 800px viewport, cut off on the left and running off the right."""
        from PySide6.QtWidgets import QScrollArea, QSizePolicy
        long = "needs a single tool to replace manual spreadsheets, email and WhatsApp for sales outreach " * 3
        types = [B.BuyerType(key="a", name="Founder / Owner", why=long, who_decides=["Founder", "CEO"] * 4,
                             needs=["find qualified B2B leads"] * 4, exclude=["large enterprises"] * 4)]
        self.p.show()
        self.p.resize(1500, 800)
        self.p.offer_edit.setPlainText(OFFER.text)
        self.p.set_types("A long summary. " * 20, types)
        self.p.set_hunt(self._hunt([_hit(i) for i in range(1, 30)]))
        scroll = self.p.findChild(QScrollArea)
        self.assertEqual(self.p._host.sizePolicy().horizontalPolicy(), QSizePolicy.Ignored)
        self.p.list.rows()[0].clicked.emit(0)
        self.assertLessEqual(self.p._host.width(), scroll.viewport().width())
        self.p.close_panel()
        self.assertLessEqual(self.p._host.width(), scroll.viewport().width())

    def _open_at(self, width, height=800):
        self.p.show()                                                       # a hidden widget is not sent resize events
        self.p.resize(width, height)
        self.p.set_hunt(self._hunt([_hit(1), _hit(2)]))
        self.p.list.rows()[0].clicked.emit(0)

    def test_on_a_wide_page_the_panel_sits_beside_the_list_and_covers_nothing(self):
        self._open_at(1500)
        self.assertNotEqual(self.p._body_lay.indexOf(self.p.panel), -1)     # in the layout, not over it
        self.assertEqual(self.p.panel.width(), BP.PANEL_W)
        self.assertEqual(self.p.panel.maximumWidth(), BP.PANEL_W)
        self.assertTrue(self.p._compact)
        self.assertEqual(self.p.search_edit.parentWidget().isVisible(), True)  # the toolbar is not under it

    def test_beside_the_panel_the_rows_are_short_and_whole_again_when_it_closes(self):
        self._open_at(1500)
        row = self.p.list.rows()[0]
        self.assertEqual(len(row.pills), 1)                                 # one pill
        self.assertEqual(row.buttons, [])                                   # Accept and Not a fit are on the panel
        self.p.close_panel()
        self.assertFalse(self.p._compact)
        row = self.p.list.rows()[0]
        self.assertEqual(len(row.pills), 3)
        self.assertEqual([b.text() for b in row.buttons], ["Accept", "Not a fit"])
        self.assertEqual(self.p._body_lay.indexOf(self.p.panel), -1)

    def test_on_a_narrow_page_the_panel_floats_over_the_list_within_the_page(self):
        self._open_at(800)
        self.assertEqual(self.p._body_lay.indexOf(self.p.panel), -1)
        g, body = self.p.panel.geometry(), self.p._body
        self.assertEqual((g.right() + 1, g.top(), g.height()), (body.width(), 0, body.height()))
        self.assertLessEqual(g.width(), body.width())
        self.assertFalse(self.p._compact)

    def test_expanding_the_panel_takes_the_whole_body_and_going_back_docks_it_again(self):
        self._open_at(1500)
        self.p.panel._expand_btn.click()
        self.assertEqual(self.p._body_lay.indexOf(self.p.panel), -1)
        self.assertEqual(self.p.panel.geometry().width(), self.p._body.width())
        self.p.panel._expand_btn.click()
        self.assertNotEqual(self.p._body_lay.indexOf(self.p.panel), -1)

    def test_nothing_on_the_page_opens_a_hover_window(self):
        """Every tooltip is a small window; the page says things in the page instead."""
        from PySide6.QtWidgets import QWidget
        self.p.set_types("s", _types())
        self.p.set_hunt(self._hunt([_hit(1), _hit(2, status=B.CLOSED, intent=0)]))
        tips = [(type(w).__name__, w.toolTip()) for w in self.p.findChildren(QWidget) if w.toolTip()
                and w is not self.p.panel and not self.p.panel.isAncestorOf(w)]
        self.assertEqual(tips, [])
        for action in self.p.filters_menu.actions() + self.p.sort_menu.actions() + self.p.hunts_menu.actions():
            self.assertEqual(action.toolTip(), action.text())               # Qt's default: nothing extra to show

    def test_the_kinds_of_buyer_say_who_decides_inline(self):
        self.p.set_types("s", _types())
        row = self.p._types_col.itemAt(0).widget()
        self.assertFalse(row.detail.isHidden())
        self.assertIn("Decides: Founder", row.detail.text())
        self.assertIn("Looks for: pcb fabrication", row.detail.text())
        self.assertTrue(self.p._types_col.itemAt(1).widget().detail.isHidden())     # nothing to say for the second

    def test_the_tabs_count_what_they_hold_and_filter_the_list(self):
        done, away = _hit(2, decision=B.ACCEPTED), _hit(3, decision=B.NOT_A_FIT)
        shut = _hit(4, status=B.CLOSED, intent=0)
        self.p.set_hunt(self._hunt([_hit(1), done, away, shut]))
        labels = {k: b.text() for k, b in self.p.tabs._buttons.items()}
        self.assertEqual(labels, {"total": "Total  2", "new": "New  1", "accepted": "Accepted  1", "away": "Put away  1"})
        self.assertEqual([r.name.text() for r in self.p.list.rows()], ["Buyer 1", "Buyer 2"])
        self.p.tabs._buttons["accepted"].click()
        self.assertEqual([r.name.text() for r in self.p.list.rows()], ["Buyer 2"])
        self.p.tabs._buttons["away"].click()                                # the tab IS the ones put away
        self.assertEqual([r.name.text() for r in self.p.list.rows()], ["Buyer 3"])
        self.p.tabs._buttons["new"].click()
        self.assertEqual([r.name.text() for r in self.p.list.rows()], ["Buyer 1"])

    def test_search_filters_by_name_reason_and_text(self):
        a, b = _hit(1), _hit(2)
        b.who, b.why, b.snippet = "Drogo Aerospace", "Hiring a drone PCB engineer", "UAV electronics"
        self.p.set_hunt(self._hunt([a, b]))
        self.p.search_edit.setText("drone")
        self.assertEqual([r.name.text() for r in self.p.list.rows()], ["Drogo Aerospace"])
        self.p.search_edit.setText("uav")
        self.assertEqual(self.p.list.count(), 1)
        self.p.search_edit.setText("nothing like this")
        self.assertEqual(self.p.list.count(), 0)
        self.assertFalse(self.p.empty.isHidden())
        self.p.search_edit.clear()
        self.assertEqual(self.p.list.count(), 2)

    def test_sort_best_match_closing_soonest_and_newest(self):
        a = _hit(1, intent=60, closes="2026-12-09")
        b = _hit(2, intent=90, closes="2026-11-25")
        c = _hit(3, channel=B.NEWS, intent=70, status=B.RECENT)
        c.published = "2026-11-10"
        d = _hit(4, channel=B.NEWS, intent=65, status=B.RECENT)
        d.published = "2026-10-01"
        self.p.set_hunt(self._hunt([a, b, c, d]))
        names = lambda: [r.name.text() for r in self.p.list.rows()]          # noqa: E731
        self.assertEqual(names(), ["Buyer 2", "Buyer 3", "Buyer 4", "Buyer 1"])           # best score first
        self.p.set_sort("closing")
        self.assertEqual(names(), ["Buyer 2", "Buyer 1", "Buyer 3", "Buyer 4"])           # bids by date, then the rest
        self.p.set_sort("newest")
        self.assertEqual(names()[:2], ["Buyer 3", "Buyer 4"])
        self.assertEqual(self.p.sort_btn.text(), "Newest")
        self.p.set_sort("nonsense")
        self.assertEqual(self.p.sort_btn.text(), "Newest")

    def test_the_hunts_menu_lists_earlier_searches_and_picks_one(self):
        picked = []
        self.p.huntPicked.connect(picked.append)
        self.p.set_hunts([{"id": "h2", "label": "22 Nov, 17:51 · 4 buyers"}, {"id": "h1", "label": "21 Nov, 10:00 · 2 buyers"}])
        self.assertEqual([a.text() for a in self.p.hunts_menu.actions()],
                         ["22 Nov, 17:51 · 4 buyers", "21 Nov, 10:00 · 2 buyers"])
        self.p.hunt_actions["h1"].trigger()
        self.assertEqual(picked, ["h1"])
        self.p.set_hunts([])
        [only] = self.p.hunts_menu.actions()
        self.assertFalse(only.isEnabled())

    def test_a_finished_hunt_folds_the_setup_away_and_show_setup_brings_it_back(self):
        self._ready()
        self.assertFalse(self.p._describe.isHidden() or self.p._understood.isHidden())
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.assertTrue(self.p._describe.isHidden() and self.p._understood.isHidden())     # the list has the room
        self.assertEqual(self.p.setup_btn.text(), "Show setup")
        self.p.setup_btn.click()
        self.assertFalse(self.p._describe.isHidden() or self.p._understood.isHidden())
        self.assertEqual(self.p.setup_btn.text(), "Hide setup")
        self.p.set_hunt(self._hunt([_hit(1), _hit(2)]))                     # a redraw does not fold it again
        self.assertFalse(self.p._describe.isHidden())
        self.p.setup_btn.click()
        self.assertTrue(self.p._describe.isHidden() and self.p._understood.isHidden())
        self.p.set_types("s", _types())                                    # a read while hidden stays hidden
        self.assertTrue(self.p._understood.isHidden())
        self.p.new_btn.click()
        self.assertFalse(self.p._describe.isHidden() or self.p._understood.isHidden())
        self.assertEqual(self.p.setup_btn.text(), "Hide setup")
        self.assertEqual(self.p._tab, "total")

    def test_a_name_is_never_stuck_short_after_the_list_was_narrow(self):
        """The bug: names read "Gujar..." and stayed so once the list widened, because a label sized itself to
        the text it was showing."""
        from PySide6.QtGui import QFontMetrics
        from PySide6.QtWidgets import QHBoxLayout, QWidget
        box = QWidget()
        lay = QHBoxLayout(box)
        name = RR._Elided("Gujarat Energy Limited", "")
        name.setSizePolicy(__import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Preferred,
                           __import__("PySide6.QtWidgets", fromlist=["QSizePolicy"]).QSizePolicy.Preferred)
        lay.addWidget(name)
        box.show()
        box.resize(40, 30)                                                  # narrow: the name is elided
        self.assertNotEqual(name.text(), "Gujarat Energy Limited")
        box.resize(600, 30)                                                 # wide again: the whole name is back
        self.assertEqual(name.text(), "Gujarat Energy Limited")
        self.assertGreaterEqual(name.sizeHint().width(), QFontMetrics(name.font()).horizontalAdvance("Gujarat Energy Limited"))
        self.assertEqual(name.minimumSizeHint().width(), 0)

    def test_every_name_is_whole_when_there_is_room_for_it(self):
        self.p.show()
        self.p.resize(1500, 800)
        names = ["Gujarat Energy Limited", "Unnamed Indian B2B firm", "NOTICE INVITING ONLINE TENDER FOR EMPANELMENT"]
        hits = []
        for i, n in enumerate(names, 1):
            h = _hit(i)
            h.who = n
            hits.append(h)
        self.p.set_hunt(self._hunt(hits))
        self.assertEqual([r.name.text() for r in self.p.list.rows()], sorted(names, key=lambda n: -_score_of(hits, n)))

    def test_monid_sources_are_said_to_be_on_or_how_to_turn_them_on(self):
        self._ready()
        self.assertFalse(self.p._monid)
        self.assertIn("MONID_API_KEY", self.p.monid_note.text())
        self.p.channel_boxes[B.ASKING].setChecked(True)
        off = self.p.estimate.text()
        self.p.set_monid(True)
        self.assertIn("Indeed", self.p.monid_note.text())
        self.assertNotIn("MONID_API_KEY", self.p.monid_note.text())
        self.assertNotEqual(self.p.estimate.text(), off)                   # asked online is two searches on Monid, so the count moves
        self.assertIn("web searches", self.p.estimate.text())

    def test_funding_and_asked_online_are_options_the_panel_can_show(self):
        for channel in (B.FUNDING, B.ASKING, B.NEWS):
            hit = _hit(1, channel=channel, status=B.RECENT)
            self.p.set_hunt(self._hunt([hit]))
            self.p.list.rows()[0].clicked.emit(0)
            self.assertIn(BP.CHANNEL_LABEL[channel], self.p.panel.role.text())
            self.assertEqual(self.p.panel.name.text(), "Buyer 1")
            self.p.close_panel()

    def test_weak_matches_are_counted_and_hidden_until_asked(self):
        weak = _hit(3, intent=10)
        weak.fit = 20
        self.p.set_hunt(self._hunt([_hit(1), weak]))
        self.assertEqual(self.p.list.count(), 1)
        self.assertIn("1 buyer worth a look", self.p.headline.text())
        self.assertIn("1 weak match hidden", self.p.headline.text())
        self.p.show_weak.setChecked(True)
        self.assertEqual(self.p.list.count(), 2)
        self.assertNotIn("weak", self.p.headline.text())

    def test_they_asked_is_only_said_when_the_model_read_the_page_and_agrees(self):
        unchecked = _hit(2)
        unchecked.scored_by = "rule"
        lukewarm = _hit(3, intent=55)
        self.p.set_hunt(self._hunt([_hit(1), unchecked, lukewarm]))
        pills = [[p.text() for p in r.pills] for r in self.p.list.rows()]
        self.assertEqual(pills[0][0], "They asked")
        self.assertEqual(pills[1][:2], ["Possible", "Not checked"])
        self.assertEqual(pills[2][0], "Possible")
        self.assertNotIn("Not checked", pills[2])

    def test_a_card_says_who_why_and_what_kind_of_proof(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        row = self.p.list.rows()[0]
        self.assertEqual(row.name.text(), "Buyer 1")
        self.assertIn("Public tender", row.company.text())
        self.assertEqual(row.subline.text(), "Why 1")
        pills = [p.text() for p in row.pills]
        self.assertEqual(pills[0], "They asked")
        self.assertTrue(pills[1].startswith("Closes "))
        self.assertEqual(pills[2], f"Score {_hit(1).score}")
        self.assertEqual(row.toolTip(), "")                                    # no hover window: the panel has the evidence

    def test_accept_not_a_fit_and_open_say_what_was_asked(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        buttons = {b.text(): b for b in self.p.list.rows()[0].buttons}
        self.assertEqual(list(buttons), ["Accept", "Not a fit"])            # Open source is on the card
        buttons["Accept"].click()
        buttons["Not a fit"].click()
        self.assertEqual([h.id for h in self.accepted[0]], ["id1"])
        self.assertEqual(self.decided, [(["id1"], B.NOT_A_FIT, "")])
        self.assertEqual(self.opened, [])

    def test_an_accepted_card_cannot_be_accepted_twice_and_a_put_away_one_is_hidden(self):
        self.p.set_hunt(self._hunt([_hit(1, decision=B.ACCEPTED), _hit(2, decision=B.NOT_A_FIT), _hit(3)]))
        self.assertEqual(self.p.list.count(), 2)
        accepted = self.p.list.rows()[0]
        self.assertEqual([b.text() for b in accepted.buttons], [])
        self.assertIn("Accepted", [p.text() for p in accepted.pills])
        self.p.show_aside.setChecked(True)
        self.assertEqual(self.p.list.count(), 3)

    def test_a_hunt_with_nothing_says_that_is_an_answer_and_not_a_failure(self):
        self.p.set_hunt(self._hunt([]))
        self.assertEqual(self.p.list.count(), 0)
        self.assertFalse(self.p.empty.isHidden())
        self.assertIn("real answer", self.p.empty.text())
        self.assertIn("0", self.p.headline.text())

    def test_a_hunt_where_every_search_failed_is_not_called_an_answer(self):
        # 25-Nov-2026: the live licence server had no hunt lookup, all 8 searches failed, and the page still said
        # "That is a real answer".
        self.p.set_hunt(self._hunt([], stats={"searches": 8, "failed": 8}))
        self.assertNotIn("real answer", self.p.empty.text())
        self.assertIn("No search could run", self.p.empty.text())

    def test_a_hunt_where_some_searches_ran_can_still_be_an_answer(self):
        self.p.set_hunt(self._hunt([], stats={"searches": 8, "failed": 3}))
        self.assertIn("real answer", self.p.empty.text())

    def test_notes_and_credits_are_said_out_loud(self):
        self.p.set_hunt(self._hunt([_hit(1)], notes=["1 of 4 searches failed."], stats={"credits": 7}))
        self.assertIn("1 of 4 searches failed.", self.p.notes.text())
        self.assertIn("7 credits", self.p.notes.text())
        self.p.set_hunt(self._hunt([_hit(1)], preview=True))
        self.assertTrue(self.p.headline.text().startswith("Quick preview"))

    def test_clearing_the_hunt_hides_the_results(self):
        self.p.set_hunt(self._hunt([_hit(1)]))
        self.assertFalse(self.p._results.isHidden())
        self.p.set_hunt(None)
        self.assertTrue(self.p._results.isHidden())


class TheController(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.host = _Host(self.root)
        self.page = BP.BuyersPage()
        self.ctl = BC.BuyersController(self.host, self.page)
        self.folder = self.ctl.folder()
        direct = mock.patch.object(G, "pooled", return_value=False)
        direct.start()
        self.addCleanup(direct.stop)

    def _saved(self, hits=None):
        hunt = BS.save_hunt(self.folder, offer=OFFER, summary="s", types=_types(), channels=(B.TENDER,),
                            preview=False, result=_result(hits))
        self.ctl._current = hunt
        self.page.set_hunt(hunt)
        return hunt

    def test_it_keeps_its_files_beside_the_members_contacts(self):
        self.assertEqual(self.folder, os.path.join(self.root, "leads", "buyers"))

    def test_reading_the_offer_saves_it_and_starts_one_worker(self):
        with mock.patch.object(BC, "BuyerOfferWorker") as W:
            self.ctl._read(OFFER)
            self.ctl._read(OFFER)                           # a second press while one runs does nothing
        W.assert_called_once_with(OFFER, self.host.cfg)
        W.return_value.start.assert_called_once()
        self.assertEqual(BS.load_offer(self.folder)[0].text, OFFER.text)
        self.assertEqual(self.page.status.text(), "Reading what you sell…")
        self.assertFalse(self.page.find_btn.isEnabled())

    def test_the_read_offer_fills_the_page_and_is_remembered(self):
        self.ctl._on_read(OFFER, B.Reading("PCBs for startups", _types(), ["PCB makers", "EMS companies"],
                                           (B.TENDER, B.HIRING)))
        self.assertEqual(self.page.summary.text(), "PCBs for startups")
        self.assertEqual(len(self.page.type_boxes), 2)
        self.assertEqual(BS.load_offer(self.folder)[1], "PCBs for startups")
        self.assertEqual(self.host.refreshed, 1)

    def test_the_competitors_are_said_and_only_the_sources_that_fit_are_ticked_and_both_are_remembered(self):
        reading = B.Reading("A tool", _types(), ["WhatsApp marketing agencies", "SMS providers"], (B.HIRING, B.FUNDING))
        self.ctl._on_read(OFFER, reading)
        self.assertFalse(self.page.competitors_label.isHidden())
        self.assertIn("WhatsApp marketing agencies", self.page.competitors_label.text())
        self.assertIn("sell the same thing", self.page.competitors_label.text())
        self.assertEqual(self.page.channels(), (B.HIRING, B.FUNDING))                # tenders and news were not ticked
        self.assertIn("WhatsApp marketing agencies", self.page.offer().competitors)   # a hunt carries it to the scorer
        offer, _summary, _types_back = BS.load_offer(self.folder)
        self.assertEqual((offer.competitors, offer.channels), ("WhatsApp marketing agencies \u00b7 SMS providers", (B.HIRING, B.FUNDING)))
        # a new session: the same page comes back the same way
        fresh = BP.BuyersPage()
        BC.BuyersController(self.host, fresh).on_shown()
        self.assertEqual(fresh.channels(), (B.HIRING, B.FUNDING))
        self.assertIn("SMS providers", fresh.competitors_label.text())

    def test_the_customer_is_said_remembered_and_sent_with_the_hunt(self):
        self.ctl._on_read(OFFER, B.Reading("A tool", _types(), [], (), "Small Indian B2B firms, not enterprises"))
        self.assertFalse(self.page.ideal_label.isHidden())
        self.assertIn("Small Indian B2B firms", self.page.ideal_label.text())
        self.assertEqual(self.page.offer().ideal, "Small Indian B2B firms, not enterprises")
        offer, _summary, _types_back = BS.load_offer(self.folder)
        self.assertEqual(offer.ideal, "Small Indian B2B firms, not enterprises")
        fresh = BP.BuyersPage()
        BC.BuyersController(self.host, fresh).on_shown()
        self.assertIn("Small Indian B2B firms", fresh.ideal_label.text())

    def test_a_reading_with_no_competitors_says_nothing_and_leaves_the_default_sources(self):
        self.ctl._on_read(OFFER, B.Reading("A tool", _types(), [], ()))
        self.assertTrue(self.page.competitors_label.isHidden())
        self.assertEqual(self.page.channels(), B.DEFAULT_CHANNELS)

    def test_a_failed_read_says_why_and_frees_the_page(self):
        self.page.offer_edit.setPlainText("x")
        self.ctl._on_read_failed("The model is down.")
        self.assertEqual(self.page.status.text(), "The model is down.")
        self.assertTrue(self.page.find_btn.isEnabled())

    def test_on_the_pool_every_credit_is_asked_for_first(self):
        with mock.patch.object(G, "pooled", return_value=True), mock.patch.object(BC, "BuyerHuntWorker") as W:
            self.host.answer = False
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER, B.HIRING), False)
            W.assert_not_called()
            title, lines = self.host.asked[0]
            self.assertIn("web searches", lines[0])
            self.assertIn("credits", lines[0])
            self.assertIn("not charged", lines[1])
            self.host.answer = True
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER, B.HIRING), False)
        W.assert_called_once()
        self.assertEqual(W.call_args.args[:5], (OFFER, "s", _types(), (B.TENDER, B.HIRING), self.host.cfg))
        W.return_value.start.assert_called_once()

    def test_on_the_developers_own_keys_nothing_is_asked(self):
        with mock.patch.object(BC, "BuyerHuntWorker") as W:
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER,), True)
        self.assertEqual(self.host.asked, [])
        self.assertTrue(W.call_args.args[5])                # the preview flag went through

    def test_a_hunt_with_nothing_picked_does_not_start(self):
        with mock.patch.object(BC, "BuyerHuntWorker") as W:
            self.ctl._hunt(OFFER, "s", _types(), (), False)
        W.assert_not_called()
        self.assertIn("at least one", self.page.status.text())

    def test_a_hunt_with_the_company_list_on_an_old_reading_reads_the_offer_again_first_then_runs(self):
        """22-Nov-2026: the owner pressed Quick preview on a reading from before the list existed and was told, after
        the run, to press Find my buyers. It now reads first and then runs the hunt he asked for."""
        self.page.set_types("old", _types())                    # a saved reading with no company kinds
        with mock.patch.object(BC, "BuyerOfferWorker") as R, mock.patch.object(BC, "BuyerHuntWorker") as H:
            self.ctl._hunt(OFFER, "old", _types(), (B.LIST,), True)
            R.assert_called_once()                              # the offer is read again ...
            H.assert_not_called()                               # ... and nothing is hunted yet
            self.ctl._on_read(OFFER, B.Reading("fresh", _types(), [], (B.LIST,), "Small firms",
                                               ("small pump maker",), 100))
            H.assert_called_once()                              # then the hunt he asked for runs, as a preview
        self.assertEqual(H.call_args.args[0].company_kinds, ("small pump maker",))
        self.assertEqual((H.call_args.args[3], H.call_args.args[5]), ((B.LIST,), True))

    def test_a_reading_that_still_has_no_company_kinds_does_not_loop_the_read(self):
        with mock.patch.object(BC, "BuyerOfferWorker") as R, mock.patch.object(BC, "BuyerHuntWorker") as H:
            self.ctl._hunt(OFFER, "old", _types(), (B.LIST,), False)
            self.ctl._on_read(OFFER, B.Reading("fresh", _types(), [], (B.LIST,)))
        R.assert_called_once()                                  # read once, never in a loop
        H.assert_not_called()                                   # nothing to search for
        self.assertIn("what kind of companies your customers are", self.page.status.text())

    def test_a_failed_read_cancels_the_hunt_that_was_waiting_for_it(self):
        with mock.patch.object(BC, "BuyerOfferWorker"), mock.patch.object(BC, "BuyerHuntWorker") as H:
            self.ctl._hunt(OFFER, "old", _types(), (B.LIST,), False)
            self.ctl._on_read_failed("The model is down.")
            self.ctl._hunt(OFFER, "old", _types(), (B.TENDER,), False)
        self.assertEqual(H.call_count, 1)                       # only the second, ordinary hunt started

    def test_the_other_sources_never_trigger_a_read(self):
        with mock.patch.object(BC, "BuyerOfferWorker") as R, mock.patch.object(BC, "BuyerHuntWorker") as H:
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER, B.HIRING), False)
        R.assert_not_called()
        H.assert_called_once()

    def test_a_rate_limit_wait_is_shown_on_the_page_not_left_as_a_frozen_search(self):
        with mock.patch.object(BC, "BuyerHuntWorker") as H:
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER,), False)
        wire = H.return_value.waiting.connect.call_args.args[0]
        wire("Pacing the AI so it stays under its rate limit (12s)…")
        self.assertIn("rate limit", self.page.status.text())

    def test_a_decision_is_remembered_with_its_reason_and_the_page_says_what_it_shows(self):
        self._saved([_hit(1), _hit(2, channel=B.HIRING)])
        self.ctl._decide(["id1"], B.NOT_A_FIT, "Wrong size")
        self.ctl._decide(["id2"], B.ACCEPTED, "")
        memory = BS.load_memory(self.folder)
        self.assertEqual([(e["who"], e["decision"], e["reason"]) for e in memory],
                         [("Buyer 2", B.ACCEPTED, ""), ("Buyer 1", B.NOT_A_FIT, "size")])
        text = self.page.learned_label.text()
        self.assertFalse(self.page.learned_label.isHidden())
        self.assertIn("What your decisions say", text)
        self.assertIn("Public tender: 0 accepted, 1 put away", text)
        self.assertIn("Hiring: 1 accepted, 0 put away", text)

    def test_putting_a_card_back_forgets_what_was_remembered_about_it(self):
        self._saved([_hit(1)])
        self.ctl._decide(["id1"], B.NOT_A_FIT, "Wrong size")
        self.ctl._decide(["id1"], B.NEW, "")
        self.assertEqual(BS.load_memory(self.folder), [])
        self.assertTrue(self.page.learned_label.isHidden())

    def test_the_memory_outlives_the_thirty_hunts_the_hunts_file_keeps(self):
        self._saved([_hit(1)])
        self.ctl._decide(["id1"], B.NOT_A_FIT, "")
        for _ in range(BS.KEEP + 2):
            BS.save_hunt(self.folder, offer=OFFER, summary="", types=_types(), channels=(B.TENDER,), preview=False,
                         result=_result([_hit(50)]))
        self.assertEqual(len(BS.load_memory(self.folder)), 1)

    def test_a_damaged_memory_file_reads_as_no_memory_and_a_failed_write_is_said(self):
        self._saved([_hit(1)])
        with mock.patch.object(BS, "remember", side_effect=StoreError("Disk full.")):
            self.ctl._decide(["id1"], B.NOT_A_FIT, "")
        self.assertIn("Disk full.", self.page.status.text())
        with open(os.path.join(self.folder, BS.MEMORY_FILE), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(BS.load_memory(self.folder), [])

    def test_the_hunt_worker_is_handed_what_the_owner_already_judged(self):
        self._saved([_hit(1)])
        self.ctl._decide(["id1"], B.NOT_A_FIT, "Wrong size")
        with mock.patch.object(BC, "BuyerHuntWorker") as W:
            self.ctl._hunt(OFFER, "s", _types(), (B.TENDER,), False)
        self.assertEqual([e["who"] for e in W.call_args.kwargs["memory"]], ["Buyer 1"])

    def test_how_the_accepted_buyers_did_in_people_is_shown_per_source(self):
        self._saved([_hit(1, channel=B.HIRING), _hit(2, channel=B.HIRING)])
        self.ctl._decide(["id1", "id2"], B.ACCEPTED, "")
        rows = [(B.HIRING, "Replied"), (B.HIRING, "Cold")]
        with mock.patch.object(type(self.ctl), "_contact_rows", return_value=rows):
            self.ctl.refresh_learned()
        self.assertIn("Hiring: 2 accepted, 0 put away, 1 of 2 replied", self.page.learned_label.text())

    def test_a_source_nearly_all_put_away_is_named_so_it_can_be_turned_off(self):
        hits = [_hit(i, channel=B.HIRING) for i in range(1, 8)]
        self._saved(hits)
        self.ctl._decide([h.id for h in hits], B.NOT_A_FIT, "Wrong size")
        self.assertIn("consider turning it off", self.page.learned_label.text())

    def test_the_page_opens_with_what_was_learnt_before(self):
        self._saved([_hit(1)])
        self.ctl._decide(["id1"], B.NOT_A_FIT, "Wrong size")
        fresh = BP.BuyersPage()
        BC.BuyersController(self.host, fresh).on_shown()
        self.assertIn("Public tender: 0 accepted, 1 put away", fresh.learned_label.text())

    def test_a_finished_hunt_is_kept_and_shown(self):
        self.ctl._on_hunted(OFFER, "s", _types(), (B.TENDER,), False, _result())
        self.assertEqual(self.page.list.count(), 2)
        self.assertEqual(len(BS.list_hunts(self.folder)), 1)
        self.assertTrue(self.ctl._current["id"])

    def test_a_hunt_that_cannot_be_saved_is_still_shown_with_the_reason(self):
        with mock.patch.object(BS, "save_hunt", side_effect=StoreError("Disk full.")):
            self.ctl._on_hunted(OFFER, "s", _types(), (B.TENDER,), False, _result())
        self.assertEqual(self.page.list.count(), 2)
        self.assertIn("Disk full.", self.page.notes.text())
        self.assertEqual(BS.list_hunts(self.folder), [])

    def test_a_failed_hunt_says_so_and_frees_the_page(self):
        self.ctl._on_hunt_failed("Finding buyers needs an Exa key.")
        self.assertEqual(self.page.status.text(), "Finding buyers needs an Exa key.")

    def test_accept_saves_the_organisation_as_a_contact_and_keeps_the_decision(self):
        hunt = self._saved()
        card = self.ctl._current["hits"][0]
        self.page.list.rows()[0].buttons[0].click()
        [(leads, via)] = self.host.kept
        self.assertEqual((via, leads[0].company, leads[0].name), ("buyers", "Buyer 1", ""))
        self.assertEqual(leads[0].extra["source_url"], card.url)
        self.assertEqual(BS.get_hunt(self.folder, hunt["id"])["hits"][0].decision, B.ACCEPTED)
        self.assertIn("Added 1 to People", self.host._status.text)
        self.assertEqual(self.page.list.rows()[0].buttons, [])                   # accepted: nothing more to press here

    def test_a_refused_save_leaves_the_card_to_try_again(self):
        hunt = self._saved()
        self.host.keep_ok = False
        self.page.list.rows()[0].buttons[0].click()
        self.assertEqual(BS.get_hunt(self.folder, hunt["id"])["hits"][0].decision, B.NEW)
        self.assertEqual(self.page.list.rows()[0].buttons[0].text(), "Accept")

    def test_not_a_fit_puts_the_card_away_for_good(self):
        hunt = self._saved()
        self.page.list.rows()[0].buttons[1].click()
        self.assertEqual(self.page.list.count(), 1)
        self.assertEqual(BS.get_hunt(self.folder, hunt["id"])["hits"][0].decision, B.NOT_A_FIT)
        self.page.show_aside.setChecked(True)
        self.assertEqual(self.page.list.count(), 2)

    def test_opening_a_source_opens_web_addresses_only(self):
        with mock.patch.object(BC.QDesktopServices, "openUrl") as opener:
            self.ctl.open_url("https://site1.in/page")
            self.ctl.open_url("file:///C:/Windows/system32/calc.exe")
            self.ctl.open_url("javascript:alert(1)")
            self.ctl.open_url("")
        self.assertEqual(opener.call_count, 1)

    def test_opening_the_tab_puts_back_the_last_offer_and_hunt_once(self):
        BS.save_offer(self.folder, OFFER, "PCBs for startups", _types())
        BS.save_hunt(self.folder, offer=OFFER, summary="s", types=_types(), channels=(B.TENDER,), preview=False,
                     result=_result())
        self.ctl.on_shown()
        self.assertEqual(self.page.offer_edit.toPlainText(), OFFER.text)
        self.assertEqual(self.page.region_edit.text(), "Gujarat")
        self.assertEqual(len(self.page.type_boxes), 2)
        self.assertEqual(self.page.list.count(), 2)
        self.page.offer_edit.setPlainText("changed since")
        self.ctl.on_shown()                                 # not a second time: the owner's edit stays
        self.assertEqual(self.page.offer_edit.toPlainText(), "changed since")

    def test_the_hunts_menu_is_filled_when_the_tab_opens_and_after_every_hunt(self):
        BS.save_hunt(self.folder, offer=OFFER, summary="s", types=_types(), channels=(B.TENDER,), preview=True,
                     result=_result())
        self.ctl.on_shown()
        [first] = self.page.hunts_menu.actions()
        self.assertTrue(first.text().startswith("Preview, "))
        self.assertTrue(first.text().endswith("2 buyers"))
        self.ctl._on_hunted(OFFER, "s", _types(), (B.TENDER,), False, _result())
        self.assertEqual(len(self.page.hunts_menu.actions()), 2)
        self.assertFalse(self.page.hunts_menu.actions()[0].text().startswith("Preview"))     # newest first

    def test_picking_an_earlier_hunt_shows_it_with_its_decisions_and_closes_the_panel(self):
        old = BS.save_hunt(self.folder, offer=OFFER, summary="s", types=_types(), channels=(B.TENDER,),
                           preview=False, result=_result([_hit(7)]))
        BS.set_decisions(self.folder, old["id"], ["id7"], B.ACCEPTED)
        self._saved()                                       # a newer hunt is on screen, with its panel open
        self.page.open_card(self.ctl._current["hits"][0])
        self.assertFalse(self.page.panel.isHidden())
        self.page.huntPicked.emit(old["id"])
        self.assertTrue(self.page.panel.isHidden())
        self.assertEqual(self.ctl._current["id"], old["id"])
        self.assertEqual([r.name.text() for r in self.page.list.rows()], ["Buyer 7"])
        self.assertEqual(self.page.tabs._buttons["accepted"].text(), "Accepted  1")

    def test_picking_a_hunt_that_is_gone_says_so(self):
        self.page.huntPicked.emit("h-not-there")
        self.assertIn("no longer kept", self.page.status.text())

    def test_opening_the_tab_with_nothing_kept_is_quiet(self):
        self.ctl.on_shown()
        self.assertEqual(self.page.offer_edit.toPlainText(), "")
        self.assertTrue(self.page._results.isHidden())


class TheTab(unittest.TestCase):
    def test_find_buyers_sits_after_companies_and_opens_its_page(self):
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        names = [b.text().split("  ")[0] for b in w._tabs]
        self.assertEqual(names[:3], ["People", "Companies", "Find buyers"])
        self.assertEqual(len(w._tabs), w._stack.count())
        self.assertIs(w._stack.widget(2), w.buyers)
        shown = []
        w.buyersShown.connect(lambda: shown.append(1))
        w._tabs[2].click()
        self.assertIs(w._stack.currentWidget(), w.buyers)
        self.assertEqual(shown, [1])

    def test_the_tour_can_point_at_the_tab(self):
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        self.assertIs(w.help_targets()["tab_buyers"], w._tabs[2])
        w.help_reveal("tab_buyers")
        self.assertIs(w._stack.currentWidget(), w.buyers)


class TheContactVia(unittest.TestCase):
    def test_a_buyer_saved_from_the_page_is_a_contact_that_says_where_it_came_from(self):
        folder = tempfile.mkdtemp()
        lead = B.to_lead(_hit(1))
        self.assertEqual(CT.save(folder, [lead], via="buyers")["added"], 1)
        [contact] = CT.list_contacts(folder)
        self.assertEqual((contact.lead.company, contact.via), ("Buyer 1", ["buyers"]))
        self.assertEqual(CT.save(folder, [B.to_lead(_hit(1))], via="buyers")["added"], 0)   # the same page is the same lead


class TheGatewayCall(unittest.TestCase):
    def setUp(self):
        self.sent: list = []

        def send(path, body):
            self.sent.append((path, body))
            return {"result": {"results": [{"url": "https://a.in/x"}]}, "charged": 1, "balance": 9}
        G.set_transport(send)
        patch = mock.patch.object(G, "_auth_body", lambda **extra: {"license_id": "L-TEST", **extra})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(G.forget)

    def test_a_hunt_search_goes_to_the_hunt_route_with_clamped_limits(self):
        rows = G.hunt_rows("open tender for pcb fabrication " * 20, num_results=99, days=9999)
        self.assertEqual(rows, [{"url": "https://a.in/x"}])
        [(path, body)] = self.sent
        self.assertEqual(path, "/v1/leads/hunt")
        self.assertEqual((body["num_results"], body["days"]), (10, 730))
        self.assertLessEqual(len(body["query"]), 300)
        self.assertTrue(body["idem_key"].startswith("pc"))

    def test_a_refused_search_is_none_not_an_empty_list(self):
        def refuse(path, body):
            raise G.GatewayError("PROVIDER_ERROR", "Exa is down.")
        G.set_transport(refuse)
        self.assertIsNone(G.hunt_rows("x"))

    def test_the_pooled_search_and_model_are_the_gateways(self):
        cfg = {"exa_api_key": G.POOL_KEY, "api_key": G.POOL_KEY}
        search, ask = B.make_search(cfg), B.make_ask(cfg)
        self.assertEqual(search(B.Query(B.TENDER, "k", "pcb tender", 5, 0)), [{"url": "https://a.in/x"}])
        self.assertEqual(self.sent[0][0], "/v1/leads/hunt")
        G.set_transport(lambda path, body: {"result": {"text": "{}"}, "charged": 1, "balance": 8})
        self.assertEqual(ask("p", "qualify", True, 0.1), "{}")

    def test_no_key_means_no_search_and_no_model(self):
        with mock.patch.dict(os.environ, {"EXA_API_KEY": ""}):
            self.assertIsNone(B.make_search({}))
        self.assertIsNone(B.make_ask({}))


if __name__ == "__main__":
    unittest.main()

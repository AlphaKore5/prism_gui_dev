"""A widget with no parent that is made visible becomes a window of its own, for as long as it takes to be put in a layout.

That was the "small boxes that appear when I click Companies" (22-Nov-2026, found with devtools/window_trace.py): the
checkbox in every People and Companies row was shown before it was in the row, and so was a label on the Find buyers
page. They are gone in a blink, so no screenshot of the finished page shows them and no test that looks at the finished
page sees them. This one listens for the Show event itself: a window that opens at all is a failure, however briefly.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QObject                    # noqa: E402
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget   # noqa: E402

import core_bridge  # noqa: F401,E402
from addons.leads import buyers_page as BP                    # noqa: E402
from addons.leads import result_rows as RR                    # noqa: E402
from prospector import buyers as B                            # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


class _Spy(QObject):
    """Writes down every top-level widget that is shown, except the ones the test said it would open itself."""

    def __init__(self, allowed=()):
        super().__init__()
        self.allowed = {id(w) for w in allowed}
        self.windows: list = []

    def eventFilter(self, obj, event):                          # noqa: N802
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow() and id(obj) not in self.allowed:
            label = obj.text() if hasattr(obj, "text") and callable(obj.text) else ""
            self.windows.append(f"{type(obj).__name__} {obj.objectName()!r} {label!r}".strip())
        return False


class Watching(unittest.TestCase):
    def watch(self, *allowed) -> _Spy:
        spy = _Spy(allowed)
        _app.installEventFilter(spy)
        self.addCleanup(_app.removeEventFilter, spy)
        return spy


class TheRows(Watching):
    def test_a_row_with_a_tick_box_opens_no_window_while_it_is_built(self):
        spy = self.watch()
        for n in range(12):
            RR.ResultRow(RR.RowSpec(key=n, name=f"Name {n}", company="Co", subline="why", checkable=True,
                                    pills=[("Pill", "ok")], actions=[("Open", True, lambda: None)]))
        self.assertEqual(spy.windows, [])

    def test_the_rows_list_opens_none_either(self):
        spy = self.watch()
        host = QWidget()
        lay = QVBoxLayout(host)
        rows = RR.ResultList()
        lay.addWidget(rows)
        spy.allowed.add(id(host))
        host.show()
        rows.add_all([RR.ResultRow(RR.RowSpec(key=n, name=f"N{n}", checkable=(n % 2 == 0))) for n in range(10)])
        rows.clear()
        self.assertEqual(spy.windows, [])


class TheRunHeader(Watching):
    def test_the_progress_bar_in_the_run_header_is_not_a_window_while_it_is_built(self):
        from widgets.output_panel import RunHeader
        spy = self.watch()
        RunHeader()
        self.assertEqual(spy.windows, [])


class TheFindBuyersPage(Watching):
    def hits(self):
        out = []
        for n in range(1, 7):
            channel = [B.TENDER, B.HIRING, B.NEWS, B.FUNDING, B.ASKING, B.TENDER][n - 1]
            out.append(B.Hit(id=f"i{n}", channel=channel, kind=B.KIND_OF[channel], who=f"Buyer {n}", title="t",
                             snippet="Evidence " * 10, url=f"https://s{n}.in/p", source=f"s{n}.in", closes="2026-12-01" if channel == B.TENDER else "",
                             status=B.OPEN if channel == B.TENDER else B.RECENT, fit=70, intent=60 + n, why="Why",
                             buyer_type="a", scored_by="model", published="" if channel == B.TENDER else "2026-11-10"))
        return out

    def test_describing_reading_hunting_and_opening_a_buyer_opens_no_window(self):
        page = BP.BuyersPage()
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addWidget(page)
        spy = self.watch(host)
        host.resize(1500, 800)
        host.show()
        page.offer_edit.setPlainText("We make PCBs for hardware startups")
        types = [B.BuyerType(key="a", name="Founder", why="needs a tool", who_decides=["Founder", "CEO"],
                             needs=["find leads", "send messages"], exclude=["agencies"]),
                 B.BuyerType(key="b", name="Sales lead", why="needs more pipeline")]
        page.set_types("A summary", types)
        hits = self.hits()
        page.set_hunt({"id": "h", "preview": False, "hits": hits, "stats": {"credits": 3}, "notes": ["a note"]})
        for hit in hits:
            page.open_card(hit)
        page.panel._expand_btn.click()
        page.panel._expand_btn.click()
        page.search_edit.setText("Buyer")
        page.set_sort("closing")
        page.set_sort("newest")
        for key in ("new", "accepted", "away", "total"):
            page.tabs._buttons[key].click()
        page.set_hunts([{"id": "h", "label": "x"}])
        page.set_monid(True)
        page.setup_btn.click()
        page.new_btn.click()
        page.close_panel()
        self.assertEqual(spy.windows, [])

    def test_a_narrow_page_with_the_panel_floating_opens_none(self):
        page = BP.BuyersPage()
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addWidget(page)
        spy = self.watch(host)
        host.resize(800, 700)
        host.show()
        hits = self.hits()
        page.set_hunt({"id": "h", "preview": False, "hits": hits, "stats": {}, "notes": []})
        page.open_card(hits[0])
        page.close_panel()
        self.assertEqual(spy.windows, [])


if __name__ == "__main__":
    unittest.main()

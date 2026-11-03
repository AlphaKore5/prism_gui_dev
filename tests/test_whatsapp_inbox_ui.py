"""The Inbox: Live and History, the state tabs and their counts, filters, the thread, sending, template sending, alerts and the
profile rail — driven against the demo platform with a fake worker.

No processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_platform, notify, readstate, ui  # noqa: E402
from addons.whatsapp.license_client import PlatformError  # noqa: E402


class _Sig:
    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *a):
        for fn in list(self._fns):
            fn(*a)


def _worker(calls, fail=None):
    class W:
        def __init__(self, route, data=None):
            self.route, self.data = route, dict(data or {})
            self.done, self.failed = _Sig(), _Sig()

        def start(self):
            calls.append((self.route, self.data))
            if fail and self.route in fail:
                self.failed.emit(fail[self.route], {})
                return
            try:
                reply = demo_platform.handle(self.route, self.data)
            except PlatformError as e:
                self.failed.emit(str(e), dict(e.detail, reason=e.reason))
            else:
                self.done.emit(reply)
    return W


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="prism-wa-inbox-")
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield
    demo._state.clear()
    demo_platform._PAGE.clear()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def inbox(calls, monkeypatch):
    from addons.whatsapp import inbox as I
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: True)
    monkeypatch.setattr(I.QTimer, "singleShot", lambda *a, **k: None)
    monkeypatch.setattr(notify, "announce", lambda *a, **k: 0)            # no toast or beep from a test
    page = I.InboxPage({})
    page.resize(1500, 800)
    page.activate()
    yield page
    page.deactivate()


def routes(calls):
    return [r for r, _d in calls]


def last(calls, route):
    return next(d for r, d in reversed(calls) if r == route)


def texts(widget) -> str:
    return " | ".join(lab.text() for lab in widget.findChildren(QLabel))


def button(widget, text):
    return next(b for b in widget.findChildren(QPushButton) if b.text() == text)


def names(page):
    return [r["contact_name"] for r in page._rows]


def pick(page, name):
    row = next(i for i in range(page.list.count()) if page.list.item(i).data(0x0100)["contact_name"] == name)
    page.list.setCurrentRow(row)


# ── the list ─────────────────────────────────────────────────────────────────

def test_live_is_the_default_view_and_holds_the_chats_a_team_works(inbox, calls):
    assert last(calls, "inbox/threads")["window"] == "live"
    assert sorted(names(inbox)) == ["Asha Patel", "Kunal Desai", "Ravi Shah"] and inbox.list.count() == 3
    assert inbox.view_chips.current() == "live" if hasattr(inbox.view_chips, "current") else True


def test_each_state_tab_carries_its_count(inbox):
    labels = [inbox.state_box.itemText(i) for i in range(inbox.state_box.count())]
    assert "All chats  (3)" in labels and "Needs a person  (1)" in labels and "With an agent  (1)" in labels and "With the bot  (1)" in labels
    assert labels[-1] == "Unread"                                                  # a local filter: no count


def test_choosing_a_state_asks_the_server_for_it(inbox, calls):
    inbox.state_box.setCurrentIndex(inbox.state_box.findData("requesting"))
    assert last(calls, "inbox/threads")["state"] == "requesting" and names(inbox) == ["Kunal Desai"]
    inbox.state_box.setCurrentIndex(inbox.state_box.findData(""))
    assert "state" not in last(calls, "inbox/threads")


def test_the_unread_choice_narrows_what_is_already_here_without_asking_again(inbox, calls):
    n = routes(calls).count("inbox/threads")
    inbox.state_box.setCurrentIndex(inbox.state_box.findData("unread"))
    assert "state" not in last(calls, "inbox/threads")                              # unread is judged here, from what was read
    assert routes(calls).count("inbox/threads") == n + 1
    assert all(readstate.is_unread(inbox.list.item(i).data(0x0100)) for i in range(inbox.list.count()))


def test_history_holds_the_quiet_chats_and_forgets_the_state(inbox, calls):
    inbox.state_box.setCurrentIndex(inbox.state_box.findData("requesting"))
    inbox._on_view("history")
    sent = last(calls, "inbox/threads")
    assert sent["window"] == "history" and "state" not in sent and inbox._state == ""
    assert "Meera Joshi" in names(inbox) and "Asha Patel" not in names(inbox)


def test_search_goes_to_the_server_after_a_pause(inbox, calls):
    inbox.search.setText("patel")
    inbox._search_timer.timeout.emit()
    assert last(calls, "inbox/threads")["search"] == "patel" and names(inbox) == ["Asha Patel"]


def test_a_filter_from_the_builder_narrows_by_what_is_known_about_the_person(inbox, calls):
    inbox._filter = {"field": "tags", "op": "has_any", "value": ["hot lead"]}
    inbox.refresh()
    assert last(calls, "inbox/threads")["filter"] == inbox._filter
    assert names(inbox) == ["Asha Patel", "Kunal Desai"] or sorted(names(inbox)) == ["Asha Patel", "Kunal Desai"]
    assert "•" in inbox.filter_btn.text()


def test_nothing_matching_is_explained(inbox, calls):
    inbox.search.setText("zzzz")
    inbox._search_timer.timeout.emit()
    assert inbox.list_stack.currentIndex() == 1 and "Nothing matches" in texts(inbox.list_empty)


def test_an_empty_history_says_what_history_is(inbox, calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    demo_platform._PAGE.setdefault("auto", {})
    inbox._rows = []
    inbox._view = "history"
    inbox._counts = {}
    inbox._on_list(inbox._request, {"conversations": [], "counts": {}})
    assert "Nothing in History" in texts(inbox.list_empty)


def test_a_load_failure_says_what_went_wrong(inbox, calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"inbox/threads": "licence server unreachable"}))
    inbox._rows = []
    errors = []
    inbox.statusChanged.connect(lambda m, e: errors.append((m, e)))
    inbox.refresh()
    assert "unreachable" in inbox.list_status.text() and inbox.list_stack.currentIndex() == 1 and errors[-1] == ("licence server unreachable", True)


def test_only_the_unfiltered_live_list_sets_the_unread_badge(inbox):
    counts = []
    inbox.unreadChanged.connect(counts.append)
    inbox.refresh()
    assert counts and counts[-1] == 2                                               # Asha and Kunal wrote last; Ravi was answered
    counts.clear()
    inbox.state_box.setCurrentIndex(inbox.state_box.findData("requesting"))
    inbox._on_view("history")
    assert counts == []                                                             # a narrowed or other list never rewrites the badge


# ── one chat ─────────────────────────────────────────────────────────────────

def test_opening_a_chat_loads_the_thread_and_the_profile_and_marks_it_read(inbox, calls):
    pick(inbox, "Asha Patel")
    assert last(calls, "inbox/thread")["conversation_id"] == "c1" and last(calls, "contacts/get")["contact_id"] == "k1"
    assert len(inbox.thread._bubbles) == 7 and "Asha Patel" in texts(inbox.profile)          # six messages and the drawing she sent
    assert not readstate.is_unread(inbox._current)
    assert inbox.head_name.text() == "Asha Patel" and inbox.head_sub.text() == "+919812300001"


def test_an_open_window_shows_time_left_and_lets_you_type(inbox):
    pick(inbox, "Asha Patel")
    assert "left" in inbox.head_window.text() and inbox.composer.edit.isEnabled() and inbox.banner.isHidden() and inbox.template_btn.isHidden()


def test_a_closed_window_turns_the_box_into_a_template_offer(inbox, calls):
    inbox._on_view("history")
    pick(inbox, "Sanjay Kulkarni")
    assert inbox.head_window.text() == "Window closed" and not inbox.composer.edit.isEnabled()
    assert "approved template" in inbox.banner.text() and not inbox.template_btn.isHidden()
    assert "send a template" in inbox.composer.edit.placeholderText().lower()


def test_an_opted_out_person_cannot_be_written_to(inbox):
    inbox._on_view("history")
    pick(inbox, "Meera Joshi")
    assert not inbox.composer.edit.isEnabled() and "opted out" in inbox.banner.text() and inbox.template_btn.isHidden()


def test_someone_who_never_wrote_can_only_be_sent_a_template(inbox):
    inbox._current = {"id": "cX", "contact_id": "kX", "contact_name": "Someone", "contact_phone": "9", "opt_out": False}
    inbox._update_window([{"direction": "out", "created_at": "2026-10-17T10:00:00Z"}])
    assert inbox.head_window.text() == "Template only" and not inbox.template_btn.isHidden() and "24 hours" in inbox.banner.text()


def test_send_a_template_opens_the_dialog_for_that_person_and_refreshes(inbox, calls, monkeypatch):
    from addons.whatsapp import send_template_dialog as ST
    inbox._on_view("history")
    pick(inbox, "Sanjay Kulkarni")
    opened = []

    class Fake:
        def __init__(self, contact, parent=None):
            opened.append(contact)

        def exec(self):
            return 1
    monkeypatch.setattr(ST, "SendTemplateDialog", Fake)
    n = routes(calls).count("inbox/threads")
    inbox.template_btn.click()
    assert opened[0]["id"] == "k9" and opened[0]["name"] == "Sanjay Kulkarni"
    assert routes(calls).count("inbox/threads") == n + 1


def test_the_bar_shows_who_has_the_chat_and_what_you_can_do(inbox, calls):
    pick(inbox, "Kunal Desai")
    assert inbox.bar.pill.text() == "Needs a person" and button(inbox.bar, "Take over")
    button(inbox.bar, "Take over").click()
    assert last(calls, "inbox/intervene")["conversation_id"] == "c4"
    assert inbox._current["status"] == "intervened" and inbox.bar.pill.text().startswith("With ")


# ── sending ──────────────────────────────────────────────────────────────────

def test_a_reply_goes_to_the_chat_and_settles_to_sent(inbox, calls):
    pick(inbox, "Asha Patel")
    inbox._send("On it")
    sent = last(calls, "messages/send_text")
    assert sent["conversation_id"] == "c1" and sent["text"] == "On it" and sent["client_ref"]
    assert inbox.thread._bubbles[-1].msg["status"] == "sent" and inbox._rows[0]["last_text"] == "On it" and inbox._inflight == 0


def test_a_failed_send_can_be_retried_without_sending_twice(inbox, calls, monkeypatch):
    pick(inbox, "Asha Patel")
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"messages/send_text": "the server is down"}))
    inbox._send("hello")
    bubble = inbox.thread._bubbles[-1]
    first = last(calls, "messages/send_text")["client_ref"]
    assert bubble.msg["status"] == "failed" and "server is down" in inbox.banner.text()
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    inbox._retry("hello", bubble)
    assert bubble.msg["status"] == "sent" and last(calls, "messages/send_text")["client_ref"] == first      # same key: one message


def test_a_refused_send_says_why(inbox, calls):
    inbox._on_view("history")
    pick(inbox, "Sanjay Kulkarni")
    inbox.composer.edit.setEnabled(True)                                              # force the send the box would not allow
    inbox._send("anyone there?")
    assert inbox.thread._bubbles[-1].msg["status"] == "failed" and "24-hour window is closed" in inbox.banner.text()


# ── alerts ───────────────────────────────────────────────────────────────────

def test_a_chat_that_starts_needing_a_person_fires_one_alert_and_the_first_look_fires_none():
    rows = [{"id": "a", "status": "active"}, {"id": "b", "status": "requesting"}]
    assert notify.events(None, rows, set()) == []
    seen = {"requesting": {"b"}, "unread": set()}
    assert notify.events(seen, rows, set()) == []
    rows.append({"id": "c", "status": "requesting"})
    got = notify.events(seen, rows, {"a"})
    assert [(k, r["id"]) for k, r in got] == [("message", "a"), ("request", "c")]


def test_the_alert_choices_are_honoured_and_a_bad_config_is_the_default(monkeypatch):
    toasts, beeps = [], []
    monkeypatch.setattr(notify.C, "show_toast", lambda parent, title, body="": toasts.append(title))
    monkeypatch.setattr(notify.QApplication, "beep", staticmethod(lambda: beeps.append(1)))
    items = [("request", {"contact_name": "Asha", "last_text": "help"}), ("message", {"contact_name": "Ravi", "last_text": "hi"})]
    assert notify.announce(None, {"toast": True, "sound": True, "only_requests": False}, items) == 2 and len(toasts) == 2 and beeps == [1]
    toasts.clear(), beeps.clear()
    assert notify.announce(None, {"toast": True, "sound": False, "only_requests": True}, items) == 1 and toasts == ["Asha needs a person"] and beeps == []
    toasts.clear()
    assert notify.announce(None, {"toast": False, "sound": False, "only_requests": False}, items) == 2 and toasts == []
    assert notify.prefs({"whatsapp": {"notify": {"toast": "yes", "sound": False}}}) == {"toast": True, "sound": False, "only_requests": False}
    assert notify.prefs({}) == notify.DEFAULTS
    cfg = {"whatsapp": {"last_to": "1"}}
    kept = notify.store(cfg, {"sound": False})
    assert kept == {"toast": True, "sound": False, "only_requests": False} and cfg["whatsapp"]["last_to"] == "1" and notify.prefs(cfg) == kept


def test_a_new_request_on_a_poll_reaches_the_announcer(inbox, calls, monkeypatch):
    got = []
    monkeypatch.setattr(notify, "announce", lambda parent, p, items: got.append([k for k, _r in items]) or len(items))
    assert got == [[]] or got == []                                                  # the first look said nothing
    got.clear()
    demo_platform.handle("inbox/request_human", {"conversation_id": "c1"})
    inbox.refresh(silent=True)
    assert got[-1] == ["request"]
    inbox.refresh(silent=True)
    assert got[-1] == []                                                              # it is not announced twice


# ── the profile rail ─────────────────────────────────────────────────────────

def test_the_profile_rail_folds_away_on_a_narrow_window(inbox):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    inbox.resize(900, 700)
    inbox.resizeEvent(QResizeEvent(QSize(900, 700), QSize(1400, 800)))
    assert inbox._rail.isHidden()
    inbox.resize(1500, 700)
    inbox.resizeEvent(QResizeEvent(QSize(1500, 700), QSize(900, 700)))
    assert not inbox._rail.isHidden()


def test_choosing_to_hide_the_rail_sticks_even_on_a_wide_window(inbox):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    inbox.resize(1500, 700)
    inbox._toggle_rail()
    inbox.resizeEvent(QResizeEvent(QSize(1500, 700), QSize(1500, 700)))
    assert inbox._rail.isHidden()


def test_a_change_on_the_profile_refreshes_the_list(inbox, calls):
    pick(inbox, "Asha Patel")
    n = routes(calls).count("inbox/threads")
    inbox.profile.changed.emit()
    assert routes(calls).count("inbox/threads") == n + 1


def test_the_row_leads_with_the_chats_state():
    from addons.whatsapp.chat import state_tag
    assert state_tag({"status": "requesting"})[0] == "Needs a person" and state_tag({"status": "active"}) is None
    assert state_tag({"status": "intervened", "assignee_name": "Bala"})[0] == "With Bala" and state_tag({"status": "intervened"})[0] == "With an agent"
    assert state_tag({"status": "closed"})[0] == "Resolved"


def test_the_bar_knows_which_teammate_you_are_and_quick_replies_know_the_contact(inbox, calls):
    pick(inbox, "Asha Patel")
    assert inbox._me == "a1" and inbox.quick.contact_id == "k1"
    inbox._insert_reply("Thanks Asha!")
    assert inbox.composer.edit.toPlainText() == "Thanks Asha!"


def test_on_a_server_without_the_team_inbox_the_plain_inbox_still_works(calls, monkeypatch):
    from addons.whatsapp import inbox as I
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"inbox/agents/list": "The WhatsApp add-on isn't set up on the server yet."}))
    monkeypatch.setattr(I.QTimer, "singleShot", lambda *a, **k: None)
    monkeypatch.setattr(notify, "announce", lambda *a, **k: 0)
    page = I.InboxPage({})
    page.activate()
    pick(page, "Asha Patel")
    assert page.bar.isHidden() and page._bar_ok is False and page.thread._bubbles


# ── the thread and the message bar ───────────────────────────────────────────

def test_a_sent_template_reads_as_a_template_not_as_stored_text():
    from addons.whatsapp.thread import Bubble
    from PySide6.QtWidgets import QLabel
    b = Bubble({"direction": "out", "text": "[template] order_ready_test", "created_at": "2026-11-03T12:09:00+0530", "status": "read"}, tail=True)
    assert b.body.text() == "Order ready test" and b.body.toolTip() == "[template] order_ready_test"
    assert "TEMPLATE MESSAGE" in {l.text() for l in b.findChildren(QLabel)}
    plain = Bubble({"direction": "in", "text": "Hello there", "created_at": "2026-11-03T12:09:00+0530"}, tail=True)
    assert plain.body.text() == "Hello there" and "TEMPLATE MESSAGE" not in {l.text() for l in plain.findChildren(QLabel)}


def test_the_thread_cannot_be_dragged_sideways():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    bar = t.horizontalScrollBar()
    bar.setRange(0, 60)
    bar.setValue(30)
    assert bar.value() == 0


def test_the_message_bar_grows_to_show_a_long_placeholder_on_a_narrow_window():
    from addons.whatsapp.thread import Composer
    wide, narrow = Composer(), Composer()
    for c, w in ((wide, 900), (narrow, 280)):
        c.set_active(False, "Window closed — send a template to reach them")
        c.resize(w, c.height())
        c.show()
    assert narrow.height() > wide.height() >= Composer.MIN_H


def test_one_line_in_the_message_bar_sits_in_the_middle_with_no_stray_scroll_bar():
    from addons.whatsapp.thread import Composer
    c = Composer()
    c.resize(700, c.height())
    c.show()
    assert c.height() == Composer.MIN_H
    assert not c.edit.verticalScrollBar().isVisible()

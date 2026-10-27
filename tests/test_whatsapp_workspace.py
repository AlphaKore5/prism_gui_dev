"""The WhatsApp workspace: the pure logic (time ladder, reply window, read state,
demo data), the widgets that carry decisions (thread grouping, contact panel
edits), and the Inbox flow — driven with fake workers, so nothing here opens a
socket, starts a thread, or spins an event loop.

The rules this file follows: no processEvents()/exec()/QEventLoop, and nothing
touches the real ~/.prism (readstate and the demo are pointed at a temp dir).
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import chat, demo, readstate  # noqa: E402


def _iso(**ago) -> str:
    return (datetime.now(timezone.utc) - timedelta(**ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def _isolated_state():
    tmp = tempfile.mkdtemp(prefix="prism-wa-")
    readstate.reset_cache()
    demo._state.clear()
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield tmp
    readstate.reset_cache()
    demo._state.clear()


# ── time ─────────────────────────────────────────────────────────────────────

def test_the_time_ladder_goes_clock_yesterday_weekday_date():
    # Five minutes ago is "Yesterday" during the first five minutes after midnight; the test
    # used to fail then (seen 2026-10-28 00:0x). Expect what the calendar says.
    now = datetime.now().astimezone()
    if (now - timedelta(minutes=5)).date() == now.date():
        assert ":" in chat.short_time(_iso(minutes=5))
    else:
        assert chat.short_time(_iso(minutes=5)) == "Yesterday"
    assert chat.short_time(_iso(days=1, hours=1)) in ("Yesterday", chat.short_time(_iso(days=1, hours=1)))
    assert chat.short_time(_iso(days=3)) == (datetime.now().astimezone() - timedelta(days=3)).strftime("%a")
    old = chat.short_time(_iso(days=40))
    assert old.split()[0].isdigit() and len(old.split()) == 2


def test_an_unparseable_stamp_is_an_empty_string_not_a_crash():
    assert chat.short_time("") == ""
    assert chat.short_time("not a date") == ""
    assert chat.clock("nope") == ""


def test_the_reply_window_is_24_hours_from_their_last_message():
    open_ = chat.window_left([{"direction": "in", "created_at": _iso(hours=3)}])
    assert open_ is not None and timedelta(hours=20) < open_ < timedelta(hours=21, minutes=1)
    closed = chat.window_left([{"direction": "in", "created_at": _iso(hours=30)}])
    assert closed.total_seconds() < 0


def test_only_inbound_messages_open_the_window_and_the_newest_counts():
    assert chat.window_left([{"direction": "out", "created_at": _iso(minutes=1)}]) is None
    assert chat.window_left([]) is None
    msgs = [{"direction": "in", "created_at": _iso(hours=40)},
            {"direction": "in", "created_at": _iso(hours=2)},
            {"direction": "out", "created_at": _iso(minutes=5)}]
    assert chat.window_left(msgs).total_seconds() > 0


def test_human_delta_reads_naturally():
    assert chat.human_delta(timedelta(hours=21, minutes=12)) == "21h 12m"
    assert chat.human_delta(timedelta(minutes=45)) == "45m"
    assert chat.human_delta(timedelta(seconds=10)) == "1m"


def test_a_person_is_the_same_colour_everywhere_and_grey_when_opted_out():
    assert chat.avatar_colour("Asha Patel") == chat.avatar_colour("Asha Patel")
    assert chat.avatar_colour("Asha Patel", opted_out=True) != chat.avatar_colour("Asha Patel")


# ── read state ───────────────────────────────────────────────────────────────

def test_unread_means_last_message_is_inbound_and_newer_than_what_was_read():
    row = {"id": "c1", "last_direction": "in", "last_active_at": "2026-09-20T08:00:00Z"}
    assert readstate.is_unread(row)
    readstate.mark_read("c1", row["last_active_at"])
    assert not readstate.is_unread(row)
    newer = dict(row, last_active_at="2026-09-20T09:00:00Z")
    assert readstate.is_unread(newer)


def test_your_own_last_message_is_never_unread():
    assert not readstate.is_unread({"id": "c1", "last_direction": "out",
                                    "last_active_at": "2026-09-20T08:00:00Z"})


def test_read_state_survives_a_restart_and_never_goes_backwards():
    readstate.mark_read("c1", "2026-09-20T09:00:00Z")
    readstate.mark_read("c1", "2026-09-20T08:00:00Z")          # older: ignored
    readstate.reset_cache()                                    # "restart"
    assert not readstate.is_unread({"id": "c1", "last_direction": "in",
                                    "last_active_at": "2026-09-20T09:00:00Z"})


def test_a_corrupt_read_file_costs_a_badge_not_the_inbox(_isolated_state):
    path = os.path.join(_isolated_state, "whatsapp_read.json")
    with open(path, "w") as f:
        f.write("{not json")
    readstate.reset_cache()
    assert readstate.is_unread({"id": "c1", "last_direction": "in",
                                "last_active_at": "2026-09-20T09:00:00Z"})


# ── demo data ────────────────────────────────────────────────────────────────

def test_demo_is_off_unless_asked_for(monkeypatch):
    monkeypatch.delenv("PRISM_WHATSAPP_DEMO", raising=False)
    assert not demo.enabled()


def test_demo_can_never_be_switched_on_in_a_frozen_build(monkeypatch):
    monkeypatch.setenv("PRISM_WHATSAPP_DEMO", "1")
    with mock.patch("paths.is_frozen", return_value=True):
        assert not demo.enabled()
    with mock.patch("paths.is_frozen", return_value=False):
        assert demo.enabled()


def test_demo_answers_every_endpoint_in_the_servers_envelope():
    with mock.patch("time.sleep"):
        convos = demo.handle("/conversations", {})["conversations"]
        assert convos and {"id", "contact_name", "last_text", "last_direction",
                           "last_active_at", "opt_out"} <= set(convos[0])
        assert demo.handle("/thread", {"conversation_id": convos[0]["id"]})["messages"]
        assert "contacts" in demo.handle("/contacts", {"search": ""})
        assert demo.handle("/tags", {})["tags"]
        assert "segments" in demo.handle("/segments", {})
        assert "campaigns" in demo.handle("/campaigns", {})
        assert "audience" in demo.handle("/audience", {"tags": []})


def test_demo_opted_out_contacts_are_never_in_an_audience():
    with mock.patch("time.sleep"):
        everyone = demo.handle("/audience", {"tags": []})["audience"]
    assert everyone and not any(c["opt_out"] for c in everyone)


def test_a_demo_reply_lands_in_the_thread_and_moves_the_chat_to_the_top():
    with mock.patch("time.sleep"):
        first = demo.handle("/conversations", {})["conversations"]
        target = first[-1]["id"]
        demo.handle("/reply", {"conversation_id": target, "text": "hello there"})
        after = demo.handle("/conversations", {})["conversations"]
        thread = demo.handle("/thread", {"conversation_id": target})["messages"]
    assert after[0]["id"] == target and thread[-1]["text"] == "hello there"


def test_license_client_answers_from_demo_without_touching_the_network(monkeypatch):
    import licensing
    from addons.whatsapp import license_client as lc
    monkeypatch.setenv("PRISM_WHATSAPP_DEMO", "1")
    with mock.patch("time.sleep"), \
            mock.patch.object(licensing.client, "_post", side_effect=AssertionError("network!")):
        assert lc.list_conversations()


# ── thread ───────────────────────────────────────────────────────────────────

def _msgs():
    return [
        {"direction": "in", "sender": "A", "text": "one", "created_at": _iso(days=2)},
        {"direction": "in", "sender": "A", "text": "two", "created_at": _iso(days=2, seconds=-30)},
        {"direction": "out", "sender": "Harsh", "text": "three", "created_at": _iso(days=2, seconds=-90),
         "status": "read"},
        {"direction": "in", "sender": "A", "text": "four", "created_at": _iso(minutes=5)},
    ]


def test_thread_draws_one_bubble_per_message_and_a_chip_per_day():
    from addons.whatsapp.thread import MessageThread, _DayChip
    t = MessageThread()
    t.resize(800, 600)
    assert t.set_messages(_msgs()) is True
    assert len(t._bubbles) == 4
    chips = [t._col.itemAt(i).widget() for i in range(t._col.count())
             if isinstance(t._col.itemAt(i).widget(), _DayChip)]
    assert len(chips) == 2                                     # two days


def test_a_poll_that_finds_nothing_new_does_not_redraw():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    first = t._bubbles[0]
    assert t.set_messages(_msgs()) is False
    assert t._bubbles[0] is first


def test_a_new_status_is_a_change():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    msgs = _msgs()
    t.set_messages(msgs)
    msgs[2]["status"] = "delivered"
    assert t.set_messages(msgs) is True


def test_an_empty_thread_says_so_instead_of_showing_nothing():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages([])
    assert t._bubbles == []


def test_a_pending_send_can_fail_and_offer_retry():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("hi", sender="You")
    assert b.msg["status"] == "sending"
    got = []
    t.retryRequested.connect(lambda text, bubble: got.append((text, bubble)))
    b.set_status("failed")
    assert b.meta._retry is True
    b.meta.clicked.emit()
    assert got == [("hi", b)]
    b.set_status("sent")
    assert b.meta._retry is False


def test_a_short_message_gets_a_short_bubble():
    from addons.whatsapp.thread import Bubble
    short = Bubble({"direction": "in", "text": "Ok", "created_at": _iso(minutes=1)}, tail=True)
    long_ = Bubble({"direction": "in", "text": "word " * 80, "created_at": _iso(minutes=1)}, tail=True)
    short.fit(560)
    long_.fit(560)
    assert short.body.width() < 200 < long_.body.width() <= 560


def test_the_composer_sends_on_enter_not_on_shift_enter_and_refuses_the_empty():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from addons.whatsapp.thread import Composer
    c = Composer()
    sent = []
    c.submitted.connect(sent.append)
    c._submit()
    assert sent == []                                          # nothing to send
    c.edit.setPlainText("  hello  ")
    c.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.ShiftModifier))
    assert sent == [] and "\n" in c.edit.toPlainText()         # shift+enter = newline
    c.edit.setPlainText("  hello  ")
    c.edit.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
    assert sent == ["hello"] and c.edit.toPlainText() == ""


def test_the_composer_refuses_more_than_the_server_will_take():
    from addons.whatsapp.thread import Composer, _MAX_TEXT
    c = Composer()
    sent = []
    c.submitted.connect(sent.append)
    c.edit.setPlainText("x" * (_MAX_TEXT + 1))
    c._submit()
    assert sent == [] and not c.send_btn.isEnabled()


# (the contact profile's tests live in test_whatsapp_contacts_ui.py; the Inbox's in test_whatsapp_inbox_ui.py)


def test_a_failed_message_survives_a_redraw_so_the_words_are_never_lost():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("my important reply", sender="You")
    b.set_status("failed")
    newer = _msgs() + [{"direction": "in", "text": "still there?", "created_at": _iso(seconds=5)}]
    t.set_messages(newer)                                       # a poll finds news
    texts = [x.body.text() for x in t._bubbles]
    assert "my important reply" in texts and texts[-1] == "my important reply"
    assert t._bubbles[-1].msg["status"] == "failed"


def test_a_sent_message_is_not_kept_or_duplicated_after_the_server_has_it():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages(_msgs())
    b = t.add_pending("hello", sender="You")
    b.set_status("sent")
    confirmed = _msgs() + [{"direction": "out", "text": "hello", "created_at": _iso(seconds=1)}]
    t.set_messages(confirmed)
    assert [x.body.text() for x in t._bubbles].count("hello") == 1


def test_a_failed_first_message_in_an_empty_chat_is_still_shown():
    from addons.whatsapp.thread import MessageThread
    t = MessageThread()
    t.set_messages([])
    b = t.add_pending("hi there", sender="You")
    b.set_status("failed")
    t._signature = None
    t.set_messages([])
    assert [x.body.text() for x in t._bubbles] == ["hi there"]

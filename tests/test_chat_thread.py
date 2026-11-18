"""Stage 26: the task page is a conversation.

Real MainWindow, real widgets, real automation.run over the fake Prism server
(127.0.0.1, FakeAi from test_ai_via_server). Chrome is forbidden. Workers are
run inline (`start` -> `run`) so no event loop is needed; sockets on the UI
thread are recorded separately in the last test.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s26c-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

import pytest                                                       # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox             # noqa: E402
_app = QApplication.instance() or QApplication([])

import chatlog                                                      # noqa: E402
import licensing                                                    # noqa: E402
import main_window                                                  # noqa: E402
import workers                                                      # noqa: E402
import core_bridge as CB                                            # noqa: E402
from main_window import MainWindow, RUNNING                         # noqa: E402
from widgets import chat_thread as T                                # noqa: E402
from widgets import output_panel as OP                              # noqa: E402
from widgets.file_card import FileCard                              # noqa: E402
from test_ai_via_server import FakeAi, ai, PNG                      # noqa: E402,F401
from test_chrome_removed import no_chrome                           # noqa: E402,F401

_WIN: list = []


def _kinds(panel) -> list[str]:
    """What the thread holds, top to bottom."""
    out = []
    for i in range(panel.cards_box.count()):
        w = panel.cards_box.itemAt(i).widget()
        if w is None or w.isHidden():
            continue
        if isinstance(w, OP.StageCard):
            out.append("step")
        elif isinstance(w, T.NoteLine):
            out.append("note")
        elif w.findChildren(T.UserBubble):
            out.append("user")
        elif w.findChildren(T.AnswerBubble):
            out.append("answer")
        elif w.findChildren(FileCard):
            out.append("files")
    return out


@pytest.fixture(autouse=True)
def inline_workers(monkeypatch, tmp_path_factory):
    import workspace
    runs = str(tmp_path_factory.mktemp("runs"))
    monkeypatch.setattr(workspace, "runs_dir", lambda *a, **k: runs)
    monkeypatch.setattr(workers._Worker, "start", lambda self, *a, **k: self.run())
    monkeypatch.setattr(licensing, "has", lambda *a, **k: True)
    monkeypatch.setattr(licensing, "require", lambda *a, **k: True)
    monkeypatch.setattr(licensing, "report_usage", lambda *a, **k: None)

    def no_modal(*a, **k):
        raise AssertionError("a window popped up in the conversation")
    monkeypatch.setattr(QMessageBox, "exec", no_modal)
    monkeypatch.setattr(QMessageBox, "information", no_modal)
    monkeypatch.setattr(main_window.MainWindow, "_explain",
                        lambda self, *a, **k: None)


@pytest.fixture(scope="module")
def _window():
    with mock.patch.object(licensing, "has", lambda *a, **k: True), \
            mock.patch.object(MainWindow, "_first_run"):
        w = MainWindow()
    w.cfg = dict(w.cfg or {})
    w.cfg.update({"api_key": "prism-ai", "onboarded": True,
                  "agents": {"content": "ChatGPT", "research": "Perplexity"}})
    return w


@pytest.fixture
def win(ai, _window):
    w = _window
    w.output_panel.clear()
    w._followup_session = None
    w._current_run_file = None
    w._is_followup_run = False
    w._followup_text = ""
    w._chat_run = False
    w._turn_begun = False
    w._task_runs, w._task_queue, w._task_pos, w._queue_stopped = [], [], 0, False
    w.output_panel.set_finished(False)
    return w


def _task(win, text="write about trees", stages=None):
    stages = stages or [("content", "ChatGPT", ["Write about trees."])]
    win._last_query = text
    win.routing = {}
    win.attachments = []
    win._start_run(types.SimpleNamespace(allowed=True, run_id="r-test"),
                   {s: a for s, a, _ in stages}, stages)


def _send(win, text, paths=None):
    win.output_panel.composer.edit.setPlainText(text)
    win.output_panel.composer.add_paths(paths or [])
    win.output_panel.composer._send()


def _chats(ai):
    return [c for c in ai.calls if c["path"] == "/v1/ai/chat"]


def _record(win):
    with open(win._current_run_file, encoding="utf-8") as f:
        return json.load(f)


# ── the thread ───────────────────────────────────────────────────────────────

def test_thread_renders_user_steps_answer_files_and_notes(ai, tmp_path):
    f = tmp_path / "Quote.csv"
    f.write_text("a,b\n1,2\n")
    panel = OP.OutputPanel()
    panel.load_thread([
        {"kind": "user", "text": "make a quote", "files": ["brief.pdf"]},
        {"kind": "steps", "label": "", "steps": [
            {"stage": "content", "agent": "ChatGPT", "title": "", "state": "completed",
             "seconds": 12.0, "note": "", "text": "# Quote\n\nHere it is."}]},
        {"kind": "answer", "text": "# Quote\n\n* one\n* two", "by": "Prism AI"},
        {"kind": "files", "paths": [str(f)]},
        {"kind": "note", "text": "Stopped.", "bad": False}])
    assert _kinds(panel) == ["user", "step", "answer", "files", "note"]
    card = panel._cards["content"]
    assert card.state() == "completed" and card._collapsed          # folded once done
    assert "12s" in card.status_text()
    bubble = panel.findChildren(T.AnswerBubble)[0]
    plain = bubble.reader.toPlainText()
    assert "Quote" in plain and "#" not in plain and "one" in plain  # real Markdown
    assert panel.findChildren(T.UserBubble)[0].files == ["brief.pdf"]
    assert panel.composer.blocked_reason() == ""                     # can carry on


def test_composer_says_why_it_is_shut(ai):
    panel = OP.OutputPanel()
    assert "Start a task first" in panel.composer.blocked_reason()
    assert panel.composer.edit.placeholderText() == panel.composer.blocked_reason()
    assert panel.composer.send_btn.toolTip() == panel.composer.blocked_reason()
    panel.load_thread([{"kind": "user", "text": "hi"}, {"kind": "answer", "text": "yo"}])
    assert panel.composer.blocked_reason() == ""
    panel.set_running(True)
    why = panel.composer.blocked_reason()
    assert "working" in why and not panel.composer.attach_btn.isEnabled()
    assert panel.composer.attach_btn.toolTip() == why
    panel.set_running(False)
    assert panel.composer.blocked_reason() == ""


# ── a run, then re-chat ──────────────────────────────────────────────────────

def test_a_run_becomes_a_stored_thread(ai, win, no_chrome):
    ai.text = "# Trees\n\nTrees are tall."
    _task(win)
    assert _kinds(win.output_panel) == ["user", "step", "answer"]
    assert win.output_panel.composer.blocked_reason() == ""
    rec = _record(win)
    kinds = [i["kind"] for i in rec["thread"]]
    assert kinds == ["user", "steps", "answer"]
    assert rec["thread"][0]["text"] == "write about trees"
    assert "Trees are tall" in rec["thread"][2]["text"]
    assert rec["responses"]["content"]                    # the old shape is still written


def test_composer_continues_the_same_conversation_with_history(ai, win, no_chrome):
    ai.text = "FIRST-ANSWER about trees."
    _task(win)
    before = len(_chats(ai))
    ai.text = "Oaks live long."
    _send(win, "and what about oaks?")
    new = _chats(ai)[before:]
    assert len(new) == 1
    prompt = json.dumps(new[0]["body"]["messages"])
    assert "write about trees" in prompt                  # the first message
    assert "FIRST-ANSWER about trees." in prompt          # what Prism AI said
    assert "and what about oaks?" in prompt               # the new one
    assert new[0]["body"]["role"] == "writer"
    assert _kinds(win.output_panel) == ["user", "step", "answer", "user", "step", "answer"]
    assert "Oaks live long." in win.output_panel.findChildren(T.AnswerBubble)[-1].text()
    assert win.output_panel.header.task.full_text() == "write about trees"
    assert "oaks" in win.output_panel.header.followups.text()
    rec = _record(win)
    assert [i["kind"] for i in rec["thread"]].count("user") == 2
    assert len(rec["followups"]) == 1
    assert win.output_panel.composer.blocked_reason() == ""


def test_the_history_sent_is_capped(ai, win, no_chrome):
    ai.text = "x" * 40000
    _task(win)
    _send(win, "again")
    ai.text = "y" * 40000
    before = len(_chats(ai))
    _send(win, "once more")
    sent = json.dumps(_chats(ai)[before]["body"]["messages"])
    assert len(sent) < 70000


def test_a_format_request_converts_locally_with_no_ai_call(ai, win, no_chrome):
    ai.text = "# Trees\n\nTrees are tall."
    _task(win)
    before = len(_chats(ai))
    _send(win, "give me this in a pdf")
    assert len(_chats(ai)) == before                      # nothing was asked
    assert _kinds(win.output_panel)[-2:] == ["answer", "files"]
    cards = win.output_panel.findChildren(FileCard)
    assert cards and cards[-1].path.lower().endswith(".pdf") and os.path.isfile(cards[-1].path)
    items = [i["kind"] for i in _record(win)["thread"]]
    assert items[-2:] == ["answer", "files"]


def test_a_new_file_request_runs_a_pipeline_step_with_a_distinct_title(ai, win, no_chrome):
    ai.text = "Trees."
    _task(win)
    ai.text = "Trees, but shorter."
    _send(win, "make it shorter and give me a word file")
    titles = [c._title for c in win.output_panel._cards.values()]
    assert len(titles) == 2 and len(set(titles)) == 2
    assert any(t in ("Make a Word file", "Revise the answer") for t in titles)


def test_attachments_go_through_the_server_seam(ai, win, no_chrome, tmp_path):
    img = tmp_path / "site.png"
    img.write_bytes(base64.b64decode(PNG))
    ai.text = "A first answer."
    _task(win)
    before = len(_chats(ai))
    ai.text = "I see a picture."
    _send(win, "what is in this picture?", [str(img)])
    body = _chats(ai)[before]["body"]
    assert body["role"] == "vision"                       # a picture upgrades the role
    content = body["messages"][-1]["content"]
    assert isinstance(content, list) and any(b.get("type") == "image_url" for b in content)
    user = win.output_panel.findChildren(T.UserBubble)[-1]
    assert user.files == ["site.png"]


# ── stored, reopened, continued ──────────────────────────────────────────────

def test_save_reopen_continue_round_trip(ai, win, no_chrome):
    ai.text = "FIRST about cedar."
    _task(win, "tell me about cedar")
    ai.text = "SECOND about cedar."
    _send(win, "more please")
    path = win._current_run_file
    before_items = [i["kind"] for i in _record(win)["thread"]]
    # leave, come back from History
    win.output_panel.clear()
    win._followup_session = None
    win._open_run_record(path)
    assert win.work_stack.currentIndex() == RUNNING
    assert _kinds(win.output_panel) == ["user", "step", "answer", "user", "step", "answer"]
    assert [i["kind"] for i in win.output_panel.thread_items()] == before_items
    assert win.output_panel.composer.blocked_reason() == ""
    before = len(_chats(ai))
    ai.text = "THIRD about cedar."
    _send(win, "and one more")
    prompt = json.dumps(_chats(ai)[before]["body"]["messages"])
    assert "FIRST about cedar." in prompt and "SECOND about cedar." in prompt
    assert [i["kind"] for i in _record(win)["thread"]].count("user") == 3


def _old_record(tmp_path):
    rec = {"query": "plan a launch", "routing": {}, "title": "Launch",
           "responses": {"research": ["Facts about launches."],
                         "content": ["REVISED launch plan."]},
           "agents": {"research": "Perplexity", "content": "ChatGPT"},
           "durations": {"research": 4.0, "content": 9.0}, "links": {},
           "attachments": ["brief.docx"], "artifacts": "",
           "followups": [{"index": 1, "query": "make it shorter", "timestamp": 1.0,
                          "responses": {"content": ["REVISED launch plan."]},
                          "agents": {"content": "ChatGPT"}, "durations": {"content": 9.0}}]}
    p = tmp_path / "run_old.json"
    p.write_text(json.dumps(rec))
    return str(p), rec


def test_an_old_record_opens_as_a_transcript_and_can_be_continued(ai, win, no_chrome, tmp_path):
    path, rec = _old_record(tmp_path)
    assert "thread" not in rec
    items = chatlog.thread_of(rec)
    assert [i["kind"] for i in items] == ["user", "steps", "answer", "user", "steps", "answer"]
    assert items[0]["files"] == ["brief.docx"]
    win._open_run_record(path)
    assert _kinds(win.output_panel) == ["user", "step", "answer", "user", "step", "answer"]
    assert win.output_panel.composer.blocked_reason() == ""
    before = len(_chats(ai))
    ai.text = "Sure."
    _send(win, "thanks, one question")
    prompt = json.dumps(_chats(ai)[before]["body"]["messages"])
    assert "plan a launch" in prompt and "REVISED launch plan." in prompt
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["thread"][-1]["kind"] == "answer" and "responses" in saved   # same file, same store


def test_a_record_with_no_answer_says_why_it_cannot_continue(ai, win, tmp_path):
    p = tmp_path / "run_empty.json"
    p.write_text(json.dumps({"query": "x", "responses": {}, "error": "boom", "routing": {}}))
    win._open_thread(str(p), json.loads(p.read_text()))
    assert "nothing to continue" in win.output_panel.composer.blocked_reason()


# ── Stop, Chrome, the UI thread ──────────────────────────────────────────────

def test_stop_works_mid_run_and_keeps_what_finished(ai, win, no_chrome):
    def responder(body):
        win._active_run.stop()                            # pressed during step one
        return "Step one result."
    ai.responder = responder
    _task(win, "research then write", [("research", "Perplexity", ["Find facts."]),
                                       ("content", "ChatGPT", ["Write it."])])
    assert len(_chats(ai)) == 1                           # step two never asked
    panel = win.output_panel
    states = {k: c.state() for k, c in panel._cards.items()}
    assert states["content"] == "cancelled"                # never reached, said so
    assert "completed" not in states.values() or states["research"] == "completed"
    assert "Stopped" in " ".join(l.text() for l in panel.findChildren(T.NoteLine))
    assert "answer" in panel.composer.blocked_reason()    # nothing to continue, and it says so


def test_stop_button_is_on_the_running_step_and_composer_waits(ai, win):
    panel = win.output_panel
    panel.set_plan({"content": "ChatGPT"})
    panel.begin_turn("hi")
    panel.stage_started("content", "ChatGPT")
    panel.set_running(True)
    assert not panel.stop_btn.isHidden() and not panel.skip_btn.isHidden()
    assert panel.composer.blocked_reason()
    stopped = []
    panel.stop_requested.connect(lambda: stopped.append(1))
    panel.stop_btn.click()
    assert stopped == [1]


def test_nothing_touches_the_network_on_the_ui_thread(ai, win, no_chrome):
    import socket
    ai.text = "An answer."
    _task(win)
    main = threading.main_thread()
    seen = []
    orig = socket.socket.connect

    def watch(sock, addr):
        if threading.current_thread() is main:
            seen.append(addr)
        return orig(sock, addr)
    started = []
    with mock.patch.object(socket.socket, "connect", watch), \
            mock.patch.object(workers._Worker, "start", lambda self, *a, **k: started.append(self)):
        _send(win, "tell me more")          # submit only; the worker is not started
        assert started and seen == []        # the UI thread did no I/O

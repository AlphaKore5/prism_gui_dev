"""AI steps run on Prism's server; no consumer website and no Chrome.

Real code paths: automation.run() with a plan, drafting.draft(), the follow-up
conversation. The only fake is Prism's server (FakeAi, real HTTP on 127.0.0.1,
shared with test_ai_via_server). Every test also proves Chrome was never asked
for: the driver factory, Playwright's launcher and Selenium's Chrome all raise.

Run on its own, in a fresh HOME:  HOME=$(mktemp -d) python -m pytest tests/test_chrome_removed.py
"""
from __future__ import annotations

import json
import os
import sys
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402
from core import ai_client                                          # noqa: E402
from test_ai_via_server import FakeAi, ai, PNG                      # noqa: E402,F401


@pytest.fixture
def no_chrome(monkeypatch):
    """Anything that would start a browser fails the test."""
    from core import automation, browser

    def boom(*a, **k):
        raise AssertionError("Chrome was launched -- AI must run on Prism's server")

    monkeypatch.setattr(automation, "_get_driver", boom)
    monkeypatch.setattr(browser, "launch_chromium", boom)
    fake_uc = types.ModuleType("undetected_chromedriver")
    fake_uc.Chrome = boom
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", fake_uc)
    try:
        import selenium.webdriver as wd
        monkeypatch.setattr(wd, "Chrome", boom)
    except ImportError:
        pass


def _run(stages, **kw):
    from core import automation, config as C
    events = []
    out = automation.run({}, C.load(), custom_stages=stages, chatgpt_analysis=False,
                         on_event=lambda k, p: events.append((k, p)), failover=True,
                         query=kw.pop("query", "write about our cranes"), **kw)
    return out, events


def _kinds(events, kind):
    return [p for k, p in events if k == kind]


def test_text_stages_run_on_the_right_roles(ai, no_chrome):
    ai.text = "An answer from the server."
    (responses, _links), events = _run([
        ("research", "Perplexity", ["Find facts about crane hire in Pune."]),
        ("brains", "ChatGPT", ["Plan the post."]),
        ("content", "Claude", ["Write the post."]),
        ("development", "Kimi 2.6", ["Write a landing page."]),
        ("summary", "Claude", ["Summarise."]),
    ])
    assert [c["body"]["role"] for c in ai.chats()] == [
        "search", "reasoner", "writer", "code", "summary"]
    assert responses["content"] and "An answer from the server." in responses["content"][0]
    assert [p["stage"] for p in _kinds(events, "stage_done")] == [
        "research", "brains", "content", "development", "summary"]
    assert not _kinds(events, "stage_error")


def test_the_chain_hands_the_previous_answer_forward(ai, no_chrome):
    ai.text = "FINDING-ABC-123"
    _run([("research", "Perplexity", ["Find facts."]),
          ("content", "Claude", ["Write it."])])
    second = ai.chats()[1]["body"]["messages"][-1]["content"]
    assert "FINDING-ABC-123" in json.dumps(second)


@pytest.mark.parametrize("stage,agent", [
    ("presentation", "Gamma.app"), ("presentation", "Canva"),
    ("audio", "ElevenLabs"), ("audio", "Suno"), ("media", "Runway"),
    ("media", "HeyGen"), ("media", "Google Flow"), ("visual", "Midjourney"),
    ("visual", "Canva"), ("leads", "Apollo"), ("media", "NotebookLM")])
def test_tools_with_no_server_equivalent_are_left_out_plainly(ai, no_chrome, stage, agent):
    _out, events = _run([(stage, agent, ["Make it."])])
    skipped = _kinds(events, "stage_skipped")
    assert len(skipped) == 1
    assert "not part of your Prism plan" in skipped[0]["reason"]
    assert agent in skipped[0]["reason"]
    assert not _kinds(events, "stage_error")
    assert not [c for c in ai.calls if c["path"] in ("/v1/ai/chat", "/v1/ai/image")]


def test_a_picture_site_becomes_prism_image(ai, no_chrome, tmp_path):
    ai.text = "A calm red crane at dawn."
    _out, events = _run([("visual", "Leonardo.ai", ["Draw a red crane."])],
                        query="draw a red crane")
    started = _kinds(events, "stage_start")
    assert started and started[0]["agent"] == "Prism Image"
    assert any(c["path"] == "/v1/ai/image" for c in ai.calls)
    assert not [c for c in ai.chats() if c["body"]["role"] in ("search", "reasoner")]


def test_a_server_refusal_is_shown_and_not_retried_elsewhere(ai, no_chrome):
    ai.error = (402, "INSUFFICIENT_CREDITS", "You are out of credits. Top up to continue.", {})
    (responses, _l), events = _run([("content", "Claude", ["Write it."]),
                                    ("summary", "Claude", ["Sum it."])])
    errs = _kinds(events, "stage_error")
    assert errs and "out of credits" in errs[0]["error"]
    assert not responses.get("content")
    # one try per stage, no second tool, no retry pass
    assert len(ai.chats()) == 2


def test_followup_prompts_keep_the_conversation(ai, no_chrome):
    from core import automation
    from core.server_session import ServerSession
    s = ServerSession()
    s.begin("design", "Claude", "code")
    ai.text = "FIRST-REPLY"
    assert automation._reask(s, {}, "turn one") == ["FIRST-REPLY"]
    ai.text = "second"
    automation._reask(s, {}, "turn two")
    body = json.dumps(ai.chats()[1]["body"]["messages"])
    assert "turn one" in body and "FIRST-REPLY" in body and "turn two" in body
    assert ai.chats()[1]["body"]["role"] == "code"
    assert automation._capture(s, {}) == ["FIRST-REPLY", "second"]


def test_a_server_error_in_a_followup_turn_is_empty_not_a_crash(ai, no_chrome):
    from core import automation
    from core.server_session import ServerSession
    s = ServerSession()
    ai.error = (503, "AI_NOT_AVAILABLE", "AI is not switched on yet.", {})
    assert automation._reask(s, {}, "hi") == []
    assert "not switched on" in s.last_error


def test_pictures_attached_to_a_step_go_as_vision(ai, no_chrome, tmp_path):
    from core import files
    png = tmp_path / "drawing.png"
    import base64
    png.write_bytes(base64.b64decode(PNG))
    att = [files.attach(str(png))]
    ai.text = "I can see it."
    _run([("brains", "Claude", ["What is in the picture?"])], attachments=att)
    body = ai.chats()[0]["body"]
    assert body["role"] == "vision"
    assert "image_url" in json.dumps(body["messages"])


def test_email_write_with_ai_is_one_writer_call(ai, no_chrome):
    from core import drafting
    ok, why = drafting.available(CB.config.load())
    assert ok and not why
    ai.text = "```\nDear Mr Rao,\nThanks for your reply.\n```"
    d = drafting.draft(CB.config.load(), "Write a polite reply.", purpose="reply")
    assert d.ok and d.text.startswith("Dear Mr Rao")
    call = ai.chats()[-1]["body"]
    assert call["role"] == "writer" and call["addon"] == "email"


def test_email_error_is_the_servers_sentence(ai, no_chrome):
    from core import drafting
    ai.error = (402, "INSUFFICIENT_CREDITS", "You are out of credits.", {})
    d = drafting.draft(CB.config.load(), "Write.", purpose="reply")
    assert not d.ok and "out of credits" in d.error


def test_no_other_website_is_offered_when_a_step_fails(ai):
    from core import agents
    assert agents.alternatives_for("content", tried=["Claude"], cfg={}) == []


def test_login_tabs_open_nothing_in_server_mode(ai, no_chrome, monkeypatch):
    from widgets import login_tabs
    shown = []
    monkeypatch.setattr(login_tabs.QMessageBox, "information",
                        lambda *a, **k: shown.append(a[2]))
    assert login_tabs.open_login_tabs(None, {"brains": "Claude"}) is False
    assert shown and "nothing to sign in to" in shown[0]


def test_the_direct_switch_still_uses_the_old_path(ai, monkeypatch):
    """PRISM_AI_DIRECT is the one dev escape hatch that exists: it keeps the browser path."""
    monkeypatch.setenv("PRISM_AI_DIRECT", "1")
    from core import drafting, automation
    seen = {}

    def fake_run(*a, **k):
        seen["stages"] = k["custom_stages"]
        return {"reply": ["Dear Sir"]}, {}
    monkeypatch.setattr(automation, "run", fake_run)
    d = drafting.draft(CB.config.load(), "Write.", purpose="reply", agent="Claude")
    assert seen["stages"][0][1] == "Claude" and d.text == "Dear Sir"
    assert not ai.calls

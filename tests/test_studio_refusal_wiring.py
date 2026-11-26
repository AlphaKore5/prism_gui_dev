"""Studio run wiring (26 Nov 2026): an AI refusal on the design step is shown once.

Drives the real automation.run() on the fake server (see test_reel_video_via_api):
script -> pictures -> art direction -> render. Only the art-direction call is made
to fail the way the server fails when credits run out.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402,F401
from core import ai_client                                          # noqa: E402
from test_ai_via_server import FakeAi, ai                           # noqa: E402,F401
from test_reel_video_via_api import (                               # noqa: E402,F401
    REEL, no_ai_browser, _responder)

REFUSAL = ("Not enough AI credits for that: it needs 337.6 and you have 256.4. "
           "Ask Alphakore to top up and it will run straight away. Nothing was charged.")
NOTHING_FILMED = ("Nothing was filmed: the design step was stopped by the AI error above.")


def _run(ai, monkeypatch, tmp_path, design_error=None, design_text=None):
    import ai_server
    from core import automation, config as C, reel_web, ui
    shown: list[str] = []
    monkeypatch.setattr(ui, "err", lambda m, *a, **k: shown.append(str(m)))
    monkeypatch.setattr(reel_web, "available", lambda: (True, ""))
    kept: list = []
    monkeypatch.setattr(automation, "_keep_failed_spec",
                        lambda *a, **k: kept.append(a) or str(tmp_path / "x.txt"))
    base = _responder([])
    ai.responder = lambda body: (design_text if design_text is not None
                                 and "ART DIRECTOR" in str(body["messages"][-1]["content"])
                                 else base(body))
    real_chat = ai_client.chat

    def chat(role, prompt, *a, **k):
        if "ART DIRECTOR" in str(prompt) and design_error is not None:
            raise design_error
        return real_chat(role, prompt, *a, **k)

    monkeypatch.setattr(ai_client, "chat", chat)
    events: list = []
    ai_server.begin_run("run-refusal-1")
    try:
        out = automation.run({}, C.load(), custom_stages=[
            ("content", "Claude", ["Write the reel script."]),
            ("media", "Prism Studio", ["Make the reel."])],
            chatgpt_analysis=False, query=REEL, failover=True,
            on_event=lambda k, p: events.append((k, p)))
    finally:
        ai_server.end_run()
    return out, events, shown, kept


def test_a_refused_design_step_is_shown_once_and_blamed_on_the_ai(
        ai, no_ai_browser, monkeypatch, tmp_path):
    err = ai_client.AiError("NO_CREDITS", REFUSAL)
    (responses, links), events, shown, kept = _run(ai, monkeypatch, tmp_path, err)
    assert sum(REFUSAL in s for s in shown) == 1, shown      # once, not twice
    assert not kept, "an AI refusal is not a design that would not parse"
    errs = [p["error"] for k, p in events if k == "stage_error"]
    assert any(NOTHING_FILMED in e for e in errs), (errs, shown)
    assert not any("did not return a design" in e for e in errs + shown)
    assert not links.get("media")


def test_a_design_that_would_not_parse_keeps_its_wording_and_its_file(
        ai, no_ai_browser, monkeypatch, tmp_path):
    (responses, links), events, shown, kept = _run(
        ai, monkeypatch, tmp_path, design_text="I am sorry, I cannot do that.")
    errs = [p["error"] for k, p in events if k == "stage_error"]
    assert kept, "a design that would not parse is still kept as evidence"
    assert not any(NOTHING_FILMED in e for e in errs), errs

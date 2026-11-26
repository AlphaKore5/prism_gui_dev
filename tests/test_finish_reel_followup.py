"""Finishing a failed reel from the chat (26 Nov 2026, prism-release #29).

The owner wrote "Continue this reel and finish it. Reuse the script and the five
pictures already made..." under a reel whose design step had been refused for
credits. It went to the text writer (49 credits) which answered that it cannot
make a video. It must instead film the reel from the saved script and pictures,
with no new script call and no new picture call, and the simple version when
the design step is refused for credits.

The window is real; the engine runs for real over the fake Prism server
(tests/test_ai_via_server.py). No event loop is run.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest                                                       # noqa: E402

import chatlog                                                      # noqa: E402
from test_chat_thread import (win, _window, ai, no_chrome, PNG,     # noqa: E402,F401
                              inline_workers, _workers_start_patched_once)
from test_reel_video_via_api import SCRIPT                          # noqa: E402

OWNER = ("Continue this reel and finish it. Reuse the script and the five pictures "
         "already made in this task. Do not write a new script and do not create "
         "new pictures. Make the 9:16 video file now.")
REFUSAL = ("Not enough AI credits for that: it needs 337.6 and you have 256.4. "
           "Ask Alphakore to top up and it will run straight away. Nothing was charged.")
SCRIPT_TEXT = "```json\n" + json.dumps(SCRIPT) + "\n```"
QUERY = "Make a 9:16 studio-style reel for Delta"


def _failed_reel(win, tmp_path, pictures=5, media_state="failed"):
    folder = tmp_path / "task"
    folder.mkdir()
    for n in range(1, pictures + 1):
        (folder / f"Delta — Artwork {n}.png").write_bytes(base64.b64decode(PNG))
    responses = {"artwork": ["Prism AI drew 5 image(s)."], "content": [SCRIPT_TEXT],
                 "design": [REFUSAL], "media": ["Nothing was filmed."]}
    step = lambda stage, agent, state, text: {   # noqa: E731
        "stage": stage, "agent": agent, "title": "", "state": state,
        "seconds": 3.0, "note": "", "text": text}
    win.output_panel.load_thread([
        {"kind": "user", "text": QUERY},
        {"kind": "steps", "label": "", "steps": [
            step("content", "Jasper", "completed", SCRIPT_TEXT),
            step("artwork", "Prism Image", "completed", "Prism AI drew 5 image(s)."),
            step("design", "ChatGPT", "failed", REFUSAL),
            step("media", "Prism Studio", media_state, "Nothing was filmed.")]},
        {"kind": "answer", "text": REFUSAL, "by": "Prism AI", "stage": "design"}])
    win._followup_session = {
        "query": QUERY, "title": "", "run_file": "", "responses": responses,
        "links": {"artwork": str(folder / "Delta — Artwork 1.png")},
        "agents": {"content": "Jasper", "artwork": "Prism Image",
                   "design": "ChatGPT", "media": "Prism Studio"},
        "artifacts_dir": str(folder)}
    win._followup_responses = responses
    win._last_query = QUERY
    win.routing = {}
    win._stage_agents = dict(win._followup_session["agents"])
    win._is_followup_run = True
    win._current_run_file = None
    return folder


# ── the intent ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    OWNER, "continue this reel", "finish it", "retry", "try again",
    "make the video", "Make the video file now.", "wrap it up", "Please finish the reel",
    "Continue this reel and finish it.", "make the 9:16 video file now"])
def test_finish_wording_is_recognised(text):
    assert chatlog.is_finish_request(text), text


@pytest.mark.parametrize("text", [
    "", "what happened?", "why did it fail?", "how do I finish it?",
    "make the video shorter", "make the logo blue", "finish it and add snow",
    "write a new script", "make a video about dogs", "describe the reel",
    "Finish it. Make the text bigger."])
def test_questions_and_changes_are_not_finish_requests(text):
    assert not chatlog.is_finish_request(text), text


def test_only_a_reel_that_did_not_finish_counts(win, tmp_path):
    _failed_reel(win, tmp_path)
    assert chatlog.reel_did_not_finish(win.output_panel.thread_items())
    win.output_panel.clear()
    (tmp_path / "ok").mkdir()
    _failed_reel(win, tmp_path / "ok", media_state="completed")
    assert not chatlog.reel_did_not_finish(win.output_panel.thread_items())
    win.output_panel.clear()
    win.output_panel.load_thread([{"kind": "user", "text": "write about trees"},
                                  {"kind": "answer", "text": "Trees."}])
    assert not chatlog.reel_did_not_finish(win.output_panel.thread_items())


# ── routing ──────────────────────────────────────────────────────────────────

def test_the_owners_message_goes_to_the_reel_not_the_writer(win, tmp_path):
    _failed_reel(win, tmp_path)
    with mock.patch.object(win, "_start_chat_reply") as writer, \
            mock.patch.object(win, "_submit_followup") as submit, \
            mock.patch.object(win, "_start_followup_run") as run:
        win._on_chat_submitted(OWNER, [])
    assert not writer.called and not submit.called
    assert run.call_count == 1
    assert run.call_args.args[0] == ["content", "media"]
    kw = run.call_args.kwargs
    assert kw["reuse_stages"] == ["content", "artwork"]
    assert len(kw["files_out"]) == 5
    assert all(f["path"].endswith(".png") and os.path.isfile(f["path"])
               for f in kw["files_out"])
    assert win._followup_responses["content"] == [SCRIPT_TEXT]
    assert not {"design", "media"} & set(win._followup_responses), "errors are not answers"
    notes = [i["text"] for i in win.output_panel.thread_items() if i["kind"] == "note"]
    assert any("Continuing your reel from the script and pictures already made. "
               "No new pictures will be drawn." in n for n in notes)


def test_a_question_about_the_failed_reel_still_goes_to_the_writer(win, tmp_path):
    _failed_reel(win, tmp_path)
    with mock.patch.object(win, "_start_chat_reply") as writer, \
            mock.patch.object(win, "_start_followup_run") as run:
        win._on_chat_submitted("why did it fail?", [])
    assert writer.called and not run.called


def test_a_missing_picture_set_asks_nothing_and_says_so(win, tmp_path):
    _failed_reel(win, tmp_path, pictures=0)
    win._followup_session["links"] = {}
    with mock.patch.object(win, "_start_chat_reply") as writer, \
            mock.patch.object(win, "_start_followup_run") as run:
        win._on_chat_submitted(OWNER, [])
    assert not writer.called and not run.called
    notes = [i["text"] for i in win.output_panel.thread_items() if i["kind"] == "note"]
    assert any("no credits were used" in n for n in notes)
    assert not win._run_in_flight()


# ── the real run ─────────────────────────────────────────────────────────────

def _calls(ai):
    return [c for c in ai.calls if c["path"] in (
        "/v1/ai/chat", "/v1/ai/image", "/v1/ai/chat/stream")]


def _arrange_engine(ai, monkeypatch, tmp_path, design_error):
    from core import ai_client, automation, config as C, reel_web
    from test_reel_video_via_api import _responder
    ai.responder = _responder([])
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(reel_web, "available", lambda: (True, ""))
    rendered: list = []

    def render(spec, out, **kw):
        rendered.append(spec)
        with open(out, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return out

    monkeypatch.setattr(reel_web, "render", render)
    monkeypatch.setattr(automation, "_keep_failed_spec", lambda *a, **k: "")
    real_chat = ai_client.chat

    def chat(role, prompt, *a, **k):
        if design_error is not None and "ART DIRECTOR" in str(prompt):
            raise design_error
        return real_chat(role, prompt, *a, **k)

    monkeypatch.setattr(ai_client, "chat", chat)
    return rendered


def test_finishing_with_the_design_refused_films_the_simple_reel_with_no_ai_call(
        win, ai, no_chrome, monkeypatch, tmp_path):
    from core import ai_client
    rendered = _arrange_engine(
        ai, monkeypatch, tmp_path, ai_client.AiError("INSUFFICIENT_CREDITS", REFUSAL))
    _failed_reel(win, tmp_path)
    before = len(ai.calls)
    win._on_chat_submitted(OWNER, [])
    assert _calls(ai)[before:] == [] and not [
        c for c in _calls(ai) if c["path"] == "/v1/ai/image"], "no script, picture or writer call"
    assert len(rendered) == 1 and rendered[0].get("_lite") is True
    stages = [r["stage"] for r in win._stage_results]
    assert "followup" not in stages and "media" in stages
    mp4s = [p for r in win._stage_results for p in (r.get("files") or [])
            + [r.get("url") or ""] if str(p).endswith(".mp4")]
    assert mp4s, win._stage_results


def test_finishing_with_credits_pays_for_the_design_step_only(
        win, ai, no_chrome, monkeypatch, tmp_path):
    rendered = _arrange_engine(ai, monkeypatch, tmp_path, None)
    _failed_reel(win, tmp_path)
    before = len(ai.calls)
    win._on_chat_submitted(OWNER, [])
    new = _calls(ai)[before:]
    assert new and not [c for c in new if c["path"] == "/v1/ai/image"]
    assert not [c for c in new if c["body"].get("role") == "writer"], "no writer call"
    assert not any("SCRIPT for a short vertical" in json.dumps(c["body"]["messages"])
                   for c in new)
    assert len(rendered) == 1 and not rendered[0].get("_lite")

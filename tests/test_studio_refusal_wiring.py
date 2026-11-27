"""Studio run wiring (26 Nov 2026): an AI refusal on the design step is shown once.

Drives the real automation.run() on the fake server (see test_reel_video_via_api):
script -> pictures -> art direction -> render. Only the art-direction call is made
to fail the way the server fails when credits run out.
"""
from __future__ import annotations

import json
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


def _run(ai, monkeypatch, tmp_path, design_error=None, design_text=None,
         script_text=None, render=None, run_kwargs=None):
    import ai_server
    from core import automation, config as C, reel_web, ui
    shown: list[str] = []
    monkeypatch.setattr(ui, "err", lambda m, *a, **k: shown.append(str(m)))
    monkeypatch.setattr(reel_web, "available", lambda: (True, ""))
    kept: list = []
    monkeypatch.setattr(automation, "_keep_failed_spec",
                        lambda *a, **k: kept.append(a) or str(tmp_path / "x.txt"))
    base = _responder([])
    asked = "SCRIPT for a short vertical"

    def reply(body):
        last = str(body["messages"][-1]["content"])
        if design_text is not None and "ART DIRECTOR" in last:
            return design_text
        if script_text is not None and asked in last:
            return script_text
        return base(body)

    ai.responder = reply
    if render is not None:
        monkeypatch.setattr(reel_web, "render", render)
    ai.after_refusal = None
    real_chat = ai_client.chat

    def chat(role, prompt, *a, **k):
        if "ART DIRECTOR" in str(prompt) and design_error is not None:
            ai.after_refusal = len(ai.calls)
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
            on_event=lambda k, p: events.append((k, p)), **(run_kwargs or {}))
    finally:
        ai_server.end_run()
    return out, events, shown, kept


def test_a_refused_design_step_is_shown_once_and_blamed_on_the_ai(
        ai, no_ai_browser, monkeypatch, tmp_path):
    # An unreadable script leaves nothing to film: the old message stays.
    err = ai_client.AiError("NO_CREDITS", REFUSAL)
    (responses, links), events, shown, kept = _run(
        ai, monkeypatch, tmp_path, err, script_text="I could not write that.")
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


# ── zero-credit fallback: a refused design step still films a simple reel ──

def _fake_render(seen):
    def render(spec, out, **kw):
        seen.append(spec)
        with open(out, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return out
    return render


def _refused_run(ai, monkeypatch, tmp_path, script_text=None, design_error=None):
    from core import config as C
    runs = tmp_path / "runs"
    monkeypatch.setattr(C, "RUNS_DIR", str(runs))
    seen: list = []
    err = design_error or ai_client.AiError("INSUFFICIENT_CREDITS", REFUSAL)
    res = _run(ai, monkeypatch, tmp_path, err, script_text=script_text,
               render=_fake_render(seen))
    return res, seen, runs


def test_a_refused_design_step_still_films_a_simple_reel_with_no_more_ai_calls(
        ai, no_ai_browser, monkeypatch, tmp_path):
    (out, events, shown, kept), seen, runs = _refused_run(ai, monkeypatch, tmp_path)
    (responses, links) = out
    assert links.get("media", "").endswith(".mp4"), (links, shown)
    assert os.path.getsize(links["media"]) > 0
    assert len(seen) == 1 and seen[0].get("_lite") is True
    assert ai.after_refusal is not None
    later = [c["path"] for c in ai.calls[ai.after_refusal:]
             if c["path"] in ("/v1/ai/chat", "/v1/ai/image", "/v1/ai/chat/stream")]
    assert later == [], "the simple version must not ask the AI for anything"
    assert not [p for k, p in events if k == "stage_error"
                and NOTHING_FILMED in p["error"]]


def test_the_saved_spec_of_a_simple_reel_is_marked_and_has_no_studio_chat(
        ai, no_ai_browser, monkeypatch, tmp_path):
    import json
    (out, events, shown, kept), seen, runs = _refused_run(ai, monkeypatch, tmp_path)
    saved = [f for f in os.listdir(runs) if f.startswith("reel_") and f.endswith(".json")]
    assert len(saved) == 1
    spec = json.load(open(runs / saved[0], encoding="utf-8"))
    assert spec["_lite"] is True and "_studio" not in spec
    assert {k for sc in spec["scenes"] for k in ("html",) if sc.get(k)}


def test_the_simple_reel_is_announced_once_and_noted_in_the_result(
        ai, no_ai_browser, monkeypatch, tmp_path):
    from core import ui
    said: list[str] = []
    monkeypatch.setattr(ui, "warn", lambda m, *a, **k: said.append(str(m)))
    (out, events, shown, kept), seen, runs = _refused_run(ai, monkeypatch, tmp_path)
    assert sum(f"The full design step did not run: {REFUSAL}" in s for s in said) == 1
    assert sum("It cost nothing extra." in s for s in said) == 1
    notes = [str(p) for k, p in events]
    assert any("Simple version, no art direction" in n for n in notes), notes[-3:]


def test_a_provider_error_on_the_design_step_is_not_called_a_credit_problem(
        ai, no_ai_browser, monkeypatch, tmp_path):
    from core import ui
    said: list[str] = []
    monkeypatch.setattr(ui, "warn", lambda m, *a, **k: said.append(str(m)))
    why = "The AI service refused that request. Nothing was charged."
    (out, events, shown, kept), seen, runs = _refused_run(
        ai, monkeypatch, tmp_path,
        design_error=ai_client.AiError("PROVIDER_ERROR", why, {"kind": "rejected"}))
    told = [s for s in said if "The full design step did not run" in s]
    assert len(told) == 1 and why in told[0], said
    assert not any("credits" in s.lower() for s in said + shown), (said, shown)


def test_a_script_that_cannot_be_read_still_says_nothing_was_filmed(
        ai, no_ai_browser, monkeypatch, tmp_path):
    (out, events, shown, kept), seen, runs = _refused_run(
        ai, monkeypatch, tmp_path, script_text="I could not write that.")
    errs = [p["error"] for k, p in events if k == "stage_error"]
    assert any(NOTHING_FILMED in e for e in errs), errs
    assert not seen


def test_a_placeholder_script_stop_is_not_rescued(monkeypatch, tmp_path):
    """The design step was never asked (nothing charged): not an out-of-credits case."""
    from core import automation, reel_web, config as C
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(reel_web, "available", lambda: (True, ""))
    rendered: list = []
    monkeypatch.setattr(reel_web, "render", _fake_render(rendered))
    script = ('{"scenes": [{"role": "hook", "seconds": 4, "kicker": "k", '
              '"headline": "h"}]}')
    path, note = automation._run_studio(
        [script], [], {}, design={"texts": [], "error": "x", "refused": False,
                                  "stopped": "placeholders"})
    assert path == "" and "design step was not run" in note
    assert not rendered


# ── continuing a failed reel: the saved script and pictures are reused ──────

def _saved_reel(tmp_path):
    """What a failed reel leaves: the script text and five pictures on disk."""
    import base64
    from test_ai_via_server import PNG
    pics = []
    for n in range(1, 6):
        p = tmp_path / f"Artwork {n}.png"
        p.write_bytes(base64.b64decode(PNG))
        pics.append({"path": str(p), "kind": "image", "name": p.name})
    from test_reel_video_via_api import SCRIPT
    import json
    script = "```json\n" + json.dumps(SCRIPT) + "\n```"
    return {"content": [script], "artwork": ["Prism AI drew 5 image(s)."]}, pics


def _continue(ai, monkeypatch, tmp_path, design_error=None, design_text=None):
    from core import config as C
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    seen: list = []
    prior, pics = _saved_reel(tmp_path)
    kwargs = dict(prior_responses=prior, pipeline_files_out=pics,
                  reuse_stages=["content", "artwork"])
    res = _run(ai, monkeypatch, tmp_path, design_error, design_text=design_text,
               render=_fake_render(seen), run_kwargs=kwargs)
    return res, seen


def _ai_calls(ai):
    return [c for c in ai.calls if c["path"] in (
        "/v1/ai/chat", "/v1/ai/image", "/v1/ai/chat/stream")]


def test_continuing_with_the_design_refused_films_the_simple_reel_with_zero_ai_calls(
        ai, no_ai_browser, monkeypatch, tmp_path):
    err = ai_client.AiError("INSUFFICIENT_CREDITS", REFUSAL)
    ((responses, links), events, shown, kept), seen = _continue(
        ai, monkeypatch, tmp_path, err)
    assert links.get("media", "").endswith(".mp4"), (links, shown)
    assert len(seen) == 1 and seen[0].get("_lite") is True
    assert len(seen[0]["scenes"]) >= 1
    assert _ai_calls(ai) == [], "no script, picture or design call may be made"
    reused = {p["stage"]: p for k, p in events if k == "stage_done"
              and p["stage"] in ("content", "artwork")}
    assert set(reused) == {"content", "artwork"} and reused["content"]["texts"]


def test_continuing_with_credits_pays_only_for_the_design_step(
        ai, no_ai_browser, monkeypatch, tmp_path):
    ((responses, links), events, shown, kept), seen = _continue(
        ai, monkeypatch, tmp_path)
    assert links.get("media", "").endswith(".mp4"), (links, shown)
    calls = _ai_calls(ai)
    assert [c["path"] for c in calls if c["path"] == "/v1/ai/image"] == []
    texts = [json.dumps(c["body"]["messages"][-1]["content"]) for c in calls
             if c["path"] != "/v1/ai/image"]
    assert texts, "the design step is the one paid call"
    assert not any("SCRIPT for a short vertical" in t for t in texts)
    assert any("Design the reel" in t for t in texts)
    assert responses["content"] and "scenes" in responses["content"][0]

"""Engine side of Best / Balanced / Fast, driven through the real automation.run()
against the fake of Prism's server (the same Studio reel as test_simple_reel_offer).

  * the pinned quality is sent as `level` on every AI call; unset sends none
  * the server's model / level_used / stepped_down / bar_pct reach the run's events
    and the run ends with one summary event and one plain line
  * a simple Reel (lite) makes zero art-direction calls, on purpose
  * a Reel from the person's own pictures makes no pictures
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
from test_reel_video_via_api import no_ai_browser                   # noqa: E402,F401
from test_studio_refusal_wiring import _run, _fake_render, _ai_calls  # noqa: E402


@pytest.fixture(autouse=True)
def _level_reset():
    yield
    ai_client.set_level(None)


def _go(ai, monkeypatch, tmp_path, **kw):
    from core import config as C
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    return _run(ai, monkeypatch, tmp_path, render=_fake_render([]), **kw)


def test_a_pinned_quality_is_sent_on_every_ai_call(ai, no_ai_browser, monkeypatch, tmp_path):
    ai_client.set_level("fast")
    _go(ai, monkeypatch, tmp_path)
    calls = _ai_calls(ai)
    assert len(calls) >= 4
    assert {c["body"].get("level") for c in calls} == {"fast"}, \
        "chat AND image calls must carry the pin"


def test_auto_sends_no_level_so_the_server_decides(ai, no_ai_browser, monkeypatch, tmp_path):
    ai_client.set_level(None)
    _go(ai, monkeypatch, tmp_path)
    assert not [c for c in _ai_calls(ai) if "level" in c["body"]]


def test_the_stepdown_reaches_run_events_and_the_summary_line(
        ai, no_ai_browser, monkeypatch, tmp_path):
    from core import ui
    lines: list[str] = []
    monkeypatch.setattr(ui, "info", lambda m, *a, **k: lines.append(str(m)))
    # The bar fills as the run goes: best at first, balanced after the 60% line.
    ai.meta = lambda n: ({"level_used": "best", "stepped_down": False, "bar_pct": 40,
                          "model_id": "s", "model": {"key": "s", "label": "Claude Sonnet"}} if n < 6 else
                         {"level_used": "balanced", "stepped_down": True, "bar_pct": 61,
                          "model_id": "h", "model": {"key": "h", "label": "Claude Haiku"}})
    (out, events, shown, kept) = _go(ai, monkeypatch, tmp_path)
    q = [p for k, p in events if k == "quality"]
    assert q[0]["level_used"] == "best" and q[0]["stepped_down"] is False
    assert q[-1]["level_used"] == "balanced" and q[-1]["stepped_down"] is True
    assert q[-1]["model"] == "Claude Haiku" and q[-1]["bar_pct"] == 61
    assert len(q) == 2, "an event only when the quality changes"
    done = [p for k, p in events if k == "quality_summary"]
    assert len(done) == 1 and done[0]["stepped_down"] is True and done[0]["bar_pct"] == 61
    assert any(ln.strip().startswith("Made with ") and "quality (" in ln for ln in lines), lines
    assert events[-1][0] == "quality_summary" or any(k == "quality_summary" for k, _ in events)


def test_an_older_server_gives_no_quality_events(ai, no_ai_browser, monkeypatch, tmp_path):
    (out, events, shown, kept) = _go(ai, monkeypatch, tmp_path)
    assert not [k for k, _ in events if k.startswith("quality")]


def test_the_meta_hook_is_cleared_after_the_run(ai, no_ai_browser, monkeypatch, tmp_path):
    _go(ai, monkeypatch, tmp_path)
    assert getattr(ai_client._meta_hook, "fn", None) is None


def test_a_simple_reel_chosen_on_purpose_asks_for_no_art_direction(
        ai, no_ai_browser, monkeypatch, tmp_path):
    (out, events, shown, kept) = _go(ai, monkeypatch, tmp_path, run_kwargs={"lite": True})
    bodies = [str(c["body"]["messages"][-1]["content"]) for c in _ai_calls(ai)
              if c["path"] != "/v1/ai/image"]
    assert not any("ART DIRECTOR" in b or "Design the reel" in b for b in bodies)
    assert out[1].get("media", "").endswith(".mp4")


def test_a_reel_from_my_own_pictures_makes_no_pictures(
        ai, no_ai_browser, monkeypatch, tmp_path):
    from PIL import Image
    from core import files
    pic = tmp_path / "mine.png"
    Image.new("RGB", (64, 64), (200, 30, 30)).save(pic)
    (out, events, shown, kept) = _go(
        ai, monkeypatch, tmp_path,
        run_kwargs={"skip_stages": ["visual"], "attachments": [files.attach(str(pic))]})
    assert not [c for c in _ai_calls(ai) if c["path"] == "/v1/ai/image"], \
        "no picture may be bought when the person brought their own"
    assert out[1].get("media", "").endswith(".mp4"), (out[1], shown)

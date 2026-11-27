"""The up-front offer on a reel that costs more than the balance (26 Nov 2026,
prism-release #28).

  * `automation.run(lite=True)` never asks the art-direction step and films the
    simple reel from the script and pictures (FakeAi call log).
  * `router.estimate_run` also says what that simpler version still costs.
  * Before a Studio reel starts, when the estimate is over a KNOWN balance, the
    person chooses: simpler version / full version / cancel. Nothing is spent or
    started before the answer; an unknown balance is not nagged about.
"""
from __future__ import annotations

import os
import sys
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402,F401
from test_ai_via_server import FakeAi, ai                           # noqa: E402,F401
from test_reel_video_via_api import no_ai_browser                   # noqa: E402,F401
from test_studio_refusal_wiring import (_run, _fake_render, _ai_calls)  # noqa: E402


# ── the engine ───────────────────────────────────────────────────────────────

def test_lite_run_asks_no_art_direction_and_films_the_simple_reel(
        ai, no_ai_browser, monkeypatch, tmp_path):
    from core import config as C
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    seen: list = []
    (out, events, shown, kept) = _run(
        ai, monkeypatch, tmp_path, render=_fake_render(seen),
        run_kwargs={"lite": True})
    responses, links = out
    assert links.get("media", "").endswith(".mp4"), (links, shown)
    assert len(seen) == 1 and seen[0].get("_lite") is True
    bodies = [str(c["body"]["messages"][-1]["content"]) for c in _ai_calls(ai)
              if c["path"] != "/v1/ai/image"]
    assert bodies and not any("ART DIRECTOR" in b or "Design the reel" in b
                              for b in bodies), "the design step must not be asked"
    assert any("SCRIPT for a short vertical" in b for b in bodies), "the script is still written"
    assert [c for c in _ai_calls(ai) if c["path"] == "/v1/ai/image"], "pictures are still drawn"
    skipped = [p["stage"] for k, p in events if k == "stage_skipped"]
    assert "design" in skipped


def test_without_lite_the_design_step_is_asked(ai, no_ai_browser, monkeypatch, tmp_path):
    from core import config as C
    monkeypatch.setattr(C, "RUNS_DIR", str(tmp_path / "runs"))
    seen: list = []
    _run(ai, monkeypatch, tmp_path, render=_fake_render(seen))
    assert any("Design the reel" in str(c["body"]["messages"][-1]["content"])
               for c in _ai_calls(ai) if c["path"] != "/v1/ai/image")
    assert not seen[0].get("_lite")


def test_the_estimate_says_what_the_simpler_version_still_costs(monkeypatch):
    from core import ai_client, router
    monkeypatch.setattr(ai_client, "active", lambda: True)
    prices = {"code": 10_000, "writer": 1_000, "image": 5_000}

    def estimate(role, approx_in_chars=0, images=0, **kw):
        mc = prices["image" if images else role]
        return {"typical_mc": mc, "max_mc": mc * 2}

    monkeypatch.setattr(ai_client, "estimate", estimate)
    routing = {"media": {"needed": True, "questions": ["Make the reel."]}}
    got = router.estimate_run(routing, {"media": "Prism Studio"})
    assert got["typical_mc"] == 8 * 10_000 + 2 * 1_000 + 5 * 5_000
    assert got["simple_mc"] == 2 * 1_000 + 5 * 5_000


# ── the window ───────────────────────────────────────────────────────────────

from test_chat_thread import win, _window, inline_workers           # noqa: E402,F401
from PySide6.QtWidgets import QMessageBox                           # noqa: E402
import main_window                                                  # noqa: E402

SIMPLE, FULL, CANCEL = "Make a simpler version", "Continue with the full version", "Cancel"


def _clicker(choice, shown):
    def exec_(self):
        shown.append((self.text(), self.informativeText(),
                      [b.text() for b in self.buttons()]))
        for b in self.buttons():
            if b.text() == choice:
                b.click()
        return 0
    return exec_


def _arm(win, monkeypatch, estimate, status):
    win.routing = {"_estimate": estimate}
    win._last_query = "make a reel for Delta"
    win._auto_run = False
    monkeypatch.setattr(win.agents_panel, "selected_agents",
                        lambda: {"content": "Claude", "media": "Prism Studio"})
    monkeypatch.setattr(win.agents_panel, "selected_steps",
                        lambda: [("content", "Claude", ["Write."]),
                                 ("media", "Prism Studio", ["Make."])])
    monkeypatch.setattr(win.agents_panel, "unprompted_steps", lambda: [])
    monkeypatch.setattr(win.agents_panel, "left_out_stages", lambda: [])
    monkeypatch.setattr(main_window.licensing, "has", lambda *a, **k: True)
    monkeypatch.setattr(main_window.licensing, "require", lambda *a, **k: True)
    monkeypatch.setattr(main_window.CB, "studio_available", lambda: (True, ""))
    monkeypatch.setattr(main_window.ai_server, "active", lambda: True)
    monkeypatch.setattr(main_window.ai_server, "status_now", lambda: status)
    monkeypatch.setattr(main_window.CB.router, "plan_changed", lambda *a: False)
    started = []
    monkeypatch.setattr(win, "_authorize_and_start",
                        lambda agents, steps, skip: started.append(
                            (agents, steps, skip, win._lite_run)))
    return started


EST = {"typical_mc": 337_600, "max_mc": 500_000, "calls": 15, "simple_mc": 120_000}
READY = {"ready": True, "balance_mc": 256_400}


def test_offer_is_a_clear_three_way_choice_with_the_numbers(win, monkeypatch):
    started, shown = _arm(win, monkeypatch, EST, READY), []
    monkeypatch.setattr(QMessageBox, "exec", _clicker(SIMPLE, shown))
    win._run_pipeline()
    text, more, buttons = shown[0]
    assert ("This reel is estimated at about 338 credits and you have about 256. "
            "Make a simpler version that fits your credits?") in text
    assert "about 120 credits" in more and "script" in more and "pictures" in more
    assert sorted(buttons) == sorted([SIMPLE, FULL, CANCEL])
    assert started and started[0][3] is True, "the simpler version runs lite"


def test_the_full_version_is_one_click_away_and_not_lite(win, monkeypatch):
    started, shown = _arm(win, monkeypatch, EST, READY), []
    monkeypatch.setattr(QMessageBox, "exec", _clicker(FULL, shown))
    win._run_pipeline()
    assert started and started[0][3] is False


def test_cancel_starts_nothing_and_arms_nothing(win, monkeypatch):
    started, shown = _arm(win, monkeypatch, EST, READY), []
    monkeypatch.setattr(QMessageBox, "exec", _clicker(CANCEL, shown))
    win._run_pipeline()
    assert shown and not started and not win._auto_run


def test_an_unknown_balance_is_not_nagged_about(win, monkeypatch):
    for status in ({}, {"ready": False, "reason": "no_plan"}):
        started = _arm(win, monkeypatch, EST, status)
        monkeypatch.setattr(QMessageBox, "exec", lambda self: (_ for _ in ()).throw(
            AssertionError("asked although the balance is unknown")))
        win._run_pipeline()
        assert started and started[0][3] is False


def test_no_offer_when_the_reel_fits(win, monkeypatch):
    started = _arm(win, monkeypatch, EST, {"ready": True, "balance_mc": 400_000})
    monkeypatch.setattr(QMessageBox, "exec", lambda self: (_ for _ in ()).throw(
        AssertionError("asked although the reel fits")))
    win._run_pipeline()
    assert started and started[0][3] is False


def test_without_a_simple_price_it_says_much_less(win, monkeypatch):
    est = {k: v for k, v in EST.items() if k != "simple_mc"}
    _arm(win, monkeypatch, est, READY)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", _clicker(CANCEL, shown))
    win._run_pipeline()
    assert "much less" in shown[0][1] and "about" not in shown[0][1]


def test_a_plan_with_no_studio_reel_is_never_offered_it(win, monkeypatch):
    started = _arm(win, monkeypatch, EST, READY)
    monkeypatch.setattr(win.agents_panel, "selected_agents",
                        lambda: {"content": "Claude"})
    monkeypatch.setattr(QMessageBox, "exec", lambda self: (_ for _ in ()).throw(
        AssertionError("asked about a plan with no reel")))
    win._run_pipeline()
    assert started


def test_the_worker_carries_the_choice_to_the_engine(monkeypatch):
    import workers
    seen = {}
    fake = types.SimpleNamespace(
        FOLLOWUP_MIN_WAIT=1, run=lambda *a, **k: seen.update(k) or ({}, {}))
    monkeypatch.setattr(workers.CB, "automation_available", lambda: (True, ""))
    monkeypatch.setattr(workers.CB, "get_automation", lambda: fake)
    w = workers.AutomationWorker({}, {}, [], "q", lite=True)
    w.run()
    assert seen.get("lite") is True
    seen.clear()
    workers.AutomationWorker({}, {}, [], "q").run()
    assert "lite" not in seen

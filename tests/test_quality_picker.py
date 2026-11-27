"""Best / Balanced / Fast in the real app, offscreen, against the fake servers.

  * Settings > Usage shows the quality chips, the weekly bar (percent, reset day),
    "Quality now", the plain step-down sentence, and at 100% the top-up / simple
    Reel choice. Drawn by the real UsagePanel from the real worker thread over
    real HTTP (test_usage_panel's fake of GET /v1/ai/usage, with the new fields).
  * Picking a chip saves to the config and tells the engine (`level` on the wire).
  * A plan whose top quality is lower switches the higher chips off, with the reason.
  * The main window says the step-down once, ends a run with
    "Made with Balanced quality (model)", and the Reel style reaches the run.

Run on its own, sandbox HOME:  python -m pytest tests/test_quality_picker.py
"""
from __future__ import annotations

import os
import sys
import time
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import test_usage_panel as TU                                       # noqa: E402
from test_usage_panel import _Base, contract, _texts, _wait         # noqa: E402,F401
import ai_server                                                    # noqa: E402
import quality                                                      # noqa: E402
from core import ai_client                                          # noqa: E402

MONDAY = 1796083200            # a Monday 00:00 UTC (2026-12-07); weekday() is local, so test in-range


def _monday_local() -> int:
    """The next epoch whose LOCAL weekday is Monday, so the sentence is stable."""
    t = int(time.time()) + 86400
    while time.strftime("%A", time.localtime(t)) != "Monday":
        t += 86400
    return t


def week(pct, now, **over):
    return contract(bar_pct=pct, week_resets_at=_monday_local(), quality_now=now, **over)


@pytest.fixture(autouse=True)
def _clean():
    ai_server._quality.update({"level_used": "", "model": "", "stepped_down": False,
                               "bar_pct": None})
    ai_server._announced.clear()
    yield
    ai_client.set_level(None)


class CardTests(_Base):
    def setUp(self):
        super().setUp()
        self.card = self.panel.quality
        self.card.cfg.pop("quality", None)
        self.card.cfg.pop("reel_style", None)
        self._active = mock.patch.object(ai_server, "active", lambda: True)
        self._status = mock.patch.object(ai_server, "status_now",
                                         lambda: {"ready": True, "balance_mc": 40_000})
        self._saved = mock.patch("core.config.save", lambda cfg: None)
        for p in (self._active, self._status, self._saved):
            p.start()

    def tearDown(self):
        for p in (self._active, self._status, self._saved):
            p.stop()
        super().tearDown()

    def text(self):
        return " | ".join(_texts(self.card))

    def test_the_week_bar_the_reset_day_and_quality_now_are_shown(self):
        self.fake.body = week(62, "balanced")
        self.load()
        t = self.text()
        self.assertIn("62% of your week used", t)
        self.assertIn("Resets Monday.", t)
        self.assertIn("Quality now: Balanced", t)
        self.assertAlmostEqual(self.card.bar._fraction, 0.62)

    def test_the_stepdown_sentence_is_plain_and_only_when_auto_has_stepped_down(self):
        self.fake.body = week(62, "balanced")
        self.load()
        self.assertEqual(self.card.notice.text(),
                         "Quality moved to Balanced to make your week last. Resets Monday.")
        self.assertTrue(self.card.notice.isVisibleTo(self.card))
        self.fake.body = week(10, "best")
        self.load()
        self.assertFalse(self.card.notice.isVisibleTo(self.card))
        self.assertIn("Quality now: Best", self.text())

    def test_a_plan_default_below_the_top_is_not_called_a_step_down(self):
        self.fake.body = week(10, "balanced", stepped_down=False)
        self.load()
        self.assertFalse(self.card.notice.isVisibleTo(self.card))
        self.fake.body = contract(bar_pct=None, week_resets_at=None, quality_now="balanced")
        self.load()
        self.assertFalse(self.card.notice.isVisibleTo(self.card))
        self.assertIn("Your week: not shown yet", self.text())

    def test_a_customer_who_pinned_fast_is_not_told_it_was_stepped_down(self):
        self.card.cfg["quality"] = "fast"
        self.fake.body = week(30, "fast")
        self.load()
        self.assertFalse(self.card.notice.isVisibleTo(self.card))

    def test_picking_a_quality_saves_it_and_tells_the_engine(self):
        for pick, level in (("fast", "fast"), ("balanced", "balanced"), ("auto", None)):
            self.card.chips._buttons[pick].click()
            self.assertEqual(self.card.cfg["quality"], pick)
            self.assertEqual(ai_client.get_level(), level)

    def test_the_pin_is_on_the_wire_for_the_next_call(self):
        sent = []
        ai_client.set_transport(lambda path, body, bearer: sent.append(body) or
                                {"text": "x", "balance_mc": 1, "charged_mc": 0})
        try:
            self.card.chips._buttons["fast"].click()
            ai_client.chat("writer", "hi")
            self.card.chips._buttons["auto"].click()
            ai_client.chat("writer", "hi")
        finally:
            ai_client.set_transport(None)
        self.assertEqual(sent[0]["level"], "fast")
        self.assertNotIn("level", sent[1])

    def test_a_plan_that_tops_out_at_balanced_switches_best_off_and_says_why(self):
        with mock.patch.object(ai_server, "status_now",
                               lambda: {"ready": True, "max_level": "balanced"}):
            self.card.refresh_state()
            best = self.card.chips._buttons["best"]
            self.assertFalse(best.isEnabled())
            self.assertEqual(best.toolTip(), "Your plan's top quality is Balanced.")
            self.assertIn("top quality is Balanced", self.card.why.text())
            self.assertTrue(self.card.chips._buttons["balanced"].isEnabled())
            self.assertTrue(self.card.chips._buttons["fast"].isEnabled())
            # a stale higher pin is clamped, never sent
            self.assertEqual(quality.effective({"quality": "best"},
                                               {"max_level": "balanced"}), "balanced")

    def test_without_ai_through_prism_every_chip_is_off_with_a_reason(self):
        with mock.patch.object(ai_server, "active", lambda: False):
            self.card.refresh_state()
            for k, btn in self.card.chips._buttons.items():
                self.assertFalse(btn.isEnabled(), k)
                self.assertIn("Prism plan", btn.toolTip())
            self.assertIn("not running through your Prism plan", self.card.why.text())

    def test_at_100_percent_the_plain_choice_is_offered(self):
        self.fake.body = week(100, "fast")
        self.load()
        self.assertTrue(self.card.full.isVisibleTo(self.card))
        self.assertIn("used this week's AI allowance. Resets Monday.", self.card.full_text.text())
        self.assertIn("top-up", self.card.full_text.text())
        self.assertIn("no AI", self.card.full_text.text())
        opened = []
        with mock.patch("widgets.quality_card.QDesktopServices.openUrl",
                        lambda url: opened.append(url.toString())):
            self.card.topup_btn.click()
        self.assertTrue(opened and opened[0].startswith("mailto:") and "top-up" in opened[0].lower())
        self.card.simple_btn.click()
        self.assertEqual(self.card.cfg["reel_style"], "simple")
        self.assertFalse(self.card.simple_btn.isEnabled())
        self.assertTrue(self.card.simple_btn.toolTip())      # off, and says why

    def test_the_status_answer_alone_can_drive_the_bar_and_a_full_bar_has_no_quality(self):
        st = {"ready": True, "bar_pct": 100, "week_resets_at": _monday_local(),
              "quality_now": None}
        with mock.patch.object(ai_server, "status_now", lambda: st):
            self.card.set_usage({})
        self.assertIn("100% of your week used", self.text())
        self.assertTrue(self.card.full.isVisibleTo(self.card))
        self.assertNotIn("Quality now", self.text())

    def test_under_100_percent_the_choice_is_hidden(self):
        self.fake.body = week(99, "fast")
        self.load()
        self.assertFalse(self.card.full.isVisibleTo(self.card))

    def test_reel_style_is_saved(self):
        self.card.reels._buttons["own"].click()
        self.assertEqual(self.card.cfg["reel_style"], "own")
        self.assertIn("pictures you attach", self.card.reel_note.text())

    def test_settings_usage_page_carries_the_card(self):
        from widgets.settings_panel import SettingsPanel
        self.fake.body = week(62, "balanced")
        with mock.patch.object(SettingsPanel, "_licence", lambda self, col: None):
            sp = SettingsPanel({})
        sp.show_section("usage")
        self.assertTrue(_wait(lambda: sp.usage_panel._worker is None))
        t = " | ".join(_texts(sp.usage_panel))
        self.assertIn("Quality now: Balanced", t)
        self.assertIn("62% of your week used", t)
        sp.close()

    def test_a_screenshot_of_the_card(self):
        self.fake.body = week(62, "balanced")
        self.load()
        out = os.environ.get("QUALITY_SHOT")
        if out:
            self.panel.resize(560, 900)
            self.panel.grab().save(out)


# ── the main window ──────────────────────────────────────────────────────────

from test_chat_thread import win, _window, inline_workers           # noqa: E402,F401,E501
from test_ai_via_server import FakeAi, ai                           # noqa: E402,F401
from test_simple_reel_offer import _arm, EST                        # noqa: E402


def _notes(win):
    return [i.get("text", "") for i in win.output_panel.thread_items()
            if i.get("kind") == "note"]


def test_the_stepdown_is_said_once(win):
    ai_server._heard({"role": "writer", "level_used": "balanced", "stepped_down": True,
                      "bar_pct": 62, "model": "Claude Haiku", "balance_mc": 1})
    win._on_stage_event("quality", {"level_used": "balanced", "stepped_down": True})
    win._on_stage_event("quality", {"level_used": "balanced", "stepped_down": True})
    said = [n for n in _notes(win) if n.startswith("Quality moved to Balanced")]
    assert len(said) == 1, _notes(win)


def test_a_locked_role_does_not_hide_or_fake_a_stepdown(win):
    ai_server._heard({"role": "writer", "level_used": "balanced", "stepped_down": True,
                      "bar_pct": 62, "model": "H", "balance_mc": 1})
    ai_server._heard({"role": "boq.agent_a", "level_used": "best", "stepped_down": False,
                      "bar_pct": 62, "model": "S", "balance_mc": 1})
    assert ai_server.quality_state()["level_used"] == "balanced"
    assert ai_server.quality_state()["stepped_down"] is True


def test_the_run_summary_names_the_quality_and_the_model(win):
    win._on_stage_event("quality_summary", {"level_used": "balanced", "model": "Claude Haiku",
                                            "stepped_down": True, "bar_pct": 62, "calls": 5})
    win._add_turn_result({}, {}, False)
    assert "Made with Balanced quality (Claude Haiku)" in _notes(win)


def test_an_older_server_adds_no_quality_line(win):
    win._run_quality = {}
    win._add_turn_result({}, {}, False)
    assert not [n for n in _notes(win) if n.startswith("Made with")]


def test_simple_reel_style_runs_lite_without_asking(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    started = _arm(win, monkeypatch, EST, {"ready": True, "balance_mc": 1_000})
    win.cfg["reel_style"] = "simple"
    monkeypatch.setattr(QMessageBox, "exec", lambda self: (_ for _ in ()).throw(
        AssertionError("asked although the person chose simple Reels")))
    win._run_pipeline()
    assert started and started[0][3] is True


def test_own_pictures_style_leaves_pictures_out_only_when_pictures_are_attached(win, monkeypatch):
    started = _arm(win, monkeypatch, EST, {"ready": True, "balance_mc": 400_000})
    win.cfg["reel_style"] = "own"
    win.attachments = []
    win._run_pipeline()
    assert "visual" not in started[0][2]
    started.clear()
    win.attachments = [{"name": "a.png", "path": "/x/a.png", "kind": "image"}]
    win._run_pipeline()
    assert "visual" in started[0][2]


def test_a_full_bar_refusal_is_shown_as_its_own_plain_words():
    import friendly
    msg = ("You have used this week's AI allowance. It resets Monday. You can ask "
           "Alphakore for a top-up, or make a simple Reel, which uses no AI. "
           "Nothing was charged.")
    assert friendly.explain(msg, "run").what == msg

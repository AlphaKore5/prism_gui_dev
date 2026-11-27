"""Follow-ups to AI-via-server: dropped tools are not offered, the usage chip
shows this run's cost, the run id reaches the server.

Run on its own, in a fresh HOME:  python -m pytest tests/test_ai_followups.py
"""
from __future__ import annotations

import os
import sys
import threading
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

from test_ai_via_server import ai, all_server  # noqa: E402,F401  (the fake-server fixtures)

DROPPED = ("Canva", "Midjourney", "Runway", "HeyGen", "ElevenLabs", "Suno",
           "NotebookLM", "Gamma.app", "Tome", "Claude Design", "Google Flow",
           "InVideo AI", "Pika Labs", "Apollo")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _join(name):
    for t in [t for t in threading.enumerate() if t.name == name]:
        t.join(5)


def test_dropped_tools_are_not_offered_in_any_category(all_server, ai):
    from core import agents as A
    for stage, meta in A.CATEGORIES.items():
        assert not [n for n in meta["agents"] if n in DROPPED], stage
    assert "audio" not in A.CATEGORIES and "presentation" not in A.CATEGORIES
    assert "Prism Image" in A.CATEGORIES["visual"]["agents"]


def test_old_saved_plan_still_resolves_and_is_skipped_at_run_time(ai):
    from core import agents as A
    from core import server_session as SS
    cfg = A.resolve_agent("visual", "Canva")
    assert cfg is not None                        # registry kept for old plans
    assert "not part of your Prism plan" in SS.unsupported_reason("visual", "Canva", cfg)


def test_settings_and_wizard_do_not_show_dropped_tools_or_chrome_signin(all_server, ai, qapp):
    from PySide6.QtWidgets import QLabel, QPushButton, QComboBox
    from core import config as C
    from widgets import settings_panel as SP
    from widgets.wizard_panel import WizardPanel
    cfg = C.load()
    import licensing
    with mock.patch.object(SP.licensing, "state",
                           lambda: licensing.LicenseState(status=licensing.NONE)):
        p = SP.SettingsPanel(cfg)
        p.show_section("agents")
    w = WizardPanel(cfg)
    w.start(cfg)
    w._go_to(2)
    for root in (p, w):
        texts = [l.text() for l in root.findChildren(QLabel)]
        texts += [b.text() for b in root.findChildren(QPushButton) if b.isVisibleTo(root)]
        for cb in root.findChildren(QComboBox):
            texts += [cb.itemText(i) for i in range(cb.count())]
        blob = " | ".join(texts)
        for name in DROPPED:
            if name == "Apollo":
                continue      # Settings also has the Leads data key card (not an AI picker)
            assert name not in blob, (root.__class__.__name__, name)
        assert "Open login tabs" not in blob
    assert "nothing to sign in to" in " ".join(l.text() for l in w.findChildren(QLabel))


def test_a_run_tags_its_calls_and_the_chip_shows_balance_and_run_cost(ai, qapp):
    import ai_server
    import workers
    import core_bridge as CB
    from widgets.usage_chip import UsageChip
    seen = {}

    class FakeAutomation:
        FOLLOWUP_MIN_WAIT = 0

        def run(self, *a, **kw):
            CB.router.groq_chat("k", "m", "p")
            CB.router.groq_chat("k", "m", "p")
            seen["during"] = True
            return {}, {}

    ai_server.refresh_async(force=True)
    _join("prism-ai-status")
    with mock.patch.object(workers.CB, "automation_available", return_value=(True, "")), \
         mock.patch.object(workers.CB, "get_automation", return_value=FakeAutomation()):
        w = workers.AutomationWorker({}, {}, [], "q")
        # Cost is reported by the server only for the id the calls carried.
        orig = ai.run_costs
        w.run()
    chats = ai.chats()
    assert len(chats) == 2
    rid = chats[0]["body"]["run_id"]
    assert rid and chats[1]["body"]["run_id"] == rid
    # the run ended on the worker: nothing after it is tagged
    from core import ai_client
    assert ai_client._run_id() == ""
    # last reading (taken at end_run) asked for that id only
    _join("prism-ai-runcost")
    posts = [c for c in ai.calls if c["path"] == "/v1/ai/run-cost"]
    assert posts and posts[-1]["body"]["run_ids"] == [rid]
    assert orig == {}
    # now the server knows the cost: 2.5 credits -> shown rounded up
    ai.run_costs[rid] = {"mc": 2500, "calls": 2}
    ai_server._run.update({"at": 0.0})
    ai_server.usage()
    _join("prism-ai-runcost")
    chip = UsageChip()
    assert chip.number.text() == "39"   # balance kept current by the calls
    assert chip.run.text() == "This run: 3 credits"


def test_chip_shows_no_run_cost_before_any_run_and_stays_hidden_until_ready(ai, qapp):
    import ai_server
    from widgets.usage_chip import UsageChip
    ai_server._run.update({"id": "", "mc": None})
    ai.status_body = {"api": 1, "ready": False, "reason": "not_enabled"}
    ai_server.refresh_async(force=True)
    _join("prism-ai-status")
    assert ai_server.usage() is None
    assert UsageChip().isHidden()
    ai.status_body = dict(ai.status_body, ready=True, mc_per_credit=1000, balance_mc=5000,
                          allowance_mc=10000, plan={"name": "Pro"}, cycle={"days_left": 3})
    ai_server.refresh_async(force=True)
    _join("prism-ai-status")
    u = ai_server.usage()
    assert u.credits_left == 5 and u.run_cost is None
    assert not ai.calls or all(c["path"] != "/v1/ai/run-cost" for c in ai.calls)


def test_run_cost_is_polled_lightly_not_per_call(ai, qapp):
    import ai_server
    ai_server.refresh_async(force=True)
    _join("prism-ai-status")
    ai_server.begin_run("rpoll")
    for _ in range(5):
        ai_server.usage()
        _join("prism-ai-runcost")
    asks = [c for c in ai.calls if c["path"] == "/v1/ai/run-cost"]
    assert len(asks) == 1
    ai_server.end_run()

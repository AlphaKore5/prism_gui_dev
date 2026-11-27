""""Prism default work": the person's own task is worked in their browser.

Owner, 27 Nov 2026: research, thinking, writing, building, slides and voice go
back to the person's own Chrome and AI accounts, with a short list of tools for
each step. Pictures, video, the planner and every add-on stay on Prism's server.

The only fake is Prism's server (FakeAi, real HTTP on 127.0.0.1). No real
browser is ever started: the driver factory is replaced, so these tests prove
WHERE each step is sent, not that a website answers.

Run on its own, in a fresh HOME:  python -m pytest tests/test_default_work.py
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
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton  # noqa: E402

import core_bridge as CB                                            # noqa: E402
from core import automation, default_work as DW                     # noqa: E402
from test_ai_via_server import FakeAi, ai, all_server, PNG          # noqa: E402,F401

_app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def chrome(monkeypatch):
    """Counts every attempt to open the browser, and opens nothing."""
    opened = []

    def no_browser(cfg):
        opened.append(True)
        raise RuntimeError("no browser in tests")
    monkeypatch.setattr(automation, "_get_driver", no_browser)
    return opened


def _run(stages, **kw):
    from core import config as C
    events = []
    out = automation.run({}, C.load(), custom_stages=stages, chatgpt_analysis=False,
                         on_event=lambda k, p: events.append((k, p)),
                         query=kw.pop("query", "write about our cranes"), **kw)
    return out, events


def _started(events) -> dict:
    return {p["stage"]: p.get("on", "") for k, p in events if k == "stage_start"}


# ── the rules ────────────────────────────────────────────────────────────────

def test_the_offered_tools_are_the_owners_list(ai):
    assert DW.enabled()
    offered = {s: m["agents"] for s, m in CB.agents.CATEGORIES.items() if s in DW.CHOICES}
    assert offered == {s: list(v) for s, v in DW.CHOICES.items()}
    assert offered["audio"] == ["ElevenLabs", "Sarvam"]
    assert "Kimi 2.6" in offered["development"]
    # pictures and video did not move
    assert "Prism Image" in CB.agents.CATEGORIES["visual"]["agents"]
    assert CB.agents.CATEGORIES["media"]["agents"] == [
        "Prism Studio", "Prism Reel", "Prism Motion"]
    for tools in DW.CHOICES.values():
        for name in tools:
            assert (CB.agents.AGENT_REGISTRY[name].get("url") or "").startswith("https://"), name


def test_pictures_and_video_stay_on_the_server_and_so_does_a_videos_script(ai):
    steps = [("research", "ChatGPT"), ("brains", "Claude"), ("content", "ChatGPT"),
             ("audio", "Sarvam"), ("visual", "Leonardo.ai"), ("media", "Prism Studio")]
    assert DW.places(steps) == ["browser", "browser", "server", "browser",
                                "server", "server"]
    # the same writing step with no video behind it is the person's own work
    assert DW.places(steps[:3]) == ["browser"] * 3


def test_an_old_pick_gets_the_steps_default_and_nothing_is_written_back(ai):
    saved = {"research": "Perplexity", "content": "Jasper", "visual": "Leonardo.ai"}
    got = CB.agents.server_effective(saved)
    assert got["research"] == "ChatGPT" and got["content"] == "ChatGPT"
    assert got["brains"] == "Claude" and got["presentation"] == "Claude"
    assert got["visual"] == "Prism Image" and got["media"] == "Prism Studio"
    assert "audio" not in got and "leads" not in got      # only when picked
    assert saved == {"research": "Perplexity", "content": "Jasper",
                     "visual": "Leonardo.ai"}


def test_sign_in_is_asked_only_for_browser_tools(ai):
    picks = DW.sign_in_picks(
        CB.agents.server_effective({"audio": "Sarvam", "visual": "Leonardo.ai"}),
        {"analysis_agent": "Claude"})
    assert set(picks.values()) == {"ChatGPT", "Claude", "Sarvam"}
    assert len(picks) == len(set(picks.values()))


def test_the_off_switch_keeps_everything_on_the_server(all_server, ai, chrome):
    assert not DW.enabled()
    ai.text = "From the server."
    _out, events = _run([("content", "Claude", ["Write it."])], default_work=True)
    assert not chrome and len(ai.chats()) == 1
    assert _started(events) == {"content": ""}


# ── the engine ───────────────────────────────────────────────────────────────

def test_an_add_on_run_never_opens_the_browser(ai, chrome):
    ai.text = "From the server."
    _run([("research", "ChatGPT", ["Find facts."]),
          ("content", "Claude", ["Write it."])])
    assert not chrome and len(ai.chats()) == 2
    assert not DW.in_browser_run()


def test_a_task_sends_text_steps_to_the_browser_and_spends_no_credits(ai, chrome):
    _out, events = _run([("research", "ChatGPT", ["Find facts."]),
                         ("content", "Claude", ["Write it."])],
                        default_work=True, failover=False)
    assert len(chrome) == 2                      # each step asked for the browser
    assert not ai.chats()
    assert _started(events) == {"research": "browser", "content": "browser"}
    errors = [p["error"] for k, p in events if k == "stage_error"]
    assert errors and all("couldn't open Chrome" in e for e in errors)
    assert not DW.in_browser_run()               # the mark ends with the run


def test_a_tasks_picture_step_still_uses_the_server_without_a_browser(ai, chrome):
    ai.text = "A calm red crane at dawn."
    _out, events = _run([("visual", "Leonardo.ai", ["Draw a red crane."])],
                        query="draw a red crane", default_work=True)
    assert not chrome
    assert any(c["path"] == "/v1/ai/image" for c in ai.calls)


def test_attached_files_are_read_by_the_chosen_reader(ai, chrome, tmp_path):
    from core import config as C, files
    note = tmp_path / "note.txt"
    note.write_text("cranes", encoding="utf-8")
    cfg = {**C.load(), "analysis_agent": "Claude"}
    events = []
    automation.run({}, cfg, custom_stages=[("content", "ChatGPT", ["Write it."])],
                   attachments=[files.attach(str(note))], query="summarise",
                   on_event=lambda k, p: events.append((k, p)),
                   failover=False, default_work=True)
    first = [p for k, p in events if k == "stage_start"][0]
    assert (first["stage"], first["agent"]) == ("analysis", "Claude")


def test_another_tool_is_offered_only_inside_a_task_run(ai):
    assert CB.agents.alternatives_for("content", tried=["Claude"], cfg={}) == []
    with DW.running(True):
        assert CB.agents.alternatives_for("content", tried=["Claude"], cfg={}) == [
            "ChatGPT", "Kimi 2.6"]
        assert CB.agents.alternatives_for("visual", tried=[], cfg={}) == []


def test_the_estimate_counts_only_what_the_plan_spends(ai, monkeypatch):
    asked = []
    monkeypatch.setattr(CB.ai_client, "estimate",
                        lambda role, **k: asked.append(role) or {"typical_mc": 1000,
                                                                 "max_mc": 2000})
    routing = {s: {"needed": True, "questions": ["q"]}
               for s in ("research", "content", "visual")}
    agents = CB.agents.server_effective({})
    CB.router.estimate_run(routing, agents)
    assert sorted(asked) == ["image", "writer"]   # the picture and its brief only


# ── the screens ──────────────────────────────────────────────────────────────

def _texts(root) -> str:
    out = [w.text() for w in root.findChildren(QLabel)]
    out += [b.text() for b in root.findChildren(QPushButton) if b.isVisibleTo(root)]
    for cb in root.findChildren(QComboBox):
        out += [cb.itemText(i) for i in range(cb.count())]
    return " | ".join(out)


def _settings(cfg):
    from unittest import mock
    import licensing
    from widgets import settings_panel as SP
    with mock.patch.object(SP.licensing, "state",
                           lambda: licensing.LicenseState(status=licensing.NONE)):
        panel = SP.SettingsPanel(cfg)
        panel.show_section("agents")
    return panel


def test_settings_offers_the_tools_and_the_sign_in_and_still_no_key(ai):
    panel = _settings(CB.config.load())
    blob = _texts(panel)
    for name in ("ChatGPT", "Claude", "Grok", "Kimi 2.6", "Gamma.app", "Sarvam"):
        assert name in blob, name
    assert "Open login tabs" in blob
    assert "Groq key" not in blob and "OpenRouter key" not in blob
    assert "Leonardo.ai" not in blob             # pictures have nothing to pick


def test_saving_the_picks_keeps_the_ones_the_form_does_not_show(ai, monkeypatch):
    from widgets.agents_picker import AgentsPicker
    picker = AgentsPicker({"visual": "Leonardo.ai", "content": "Jasper"},
                          file_reader="Claude")
    got = picker.current_agents()
    assert got["visual"] == "Leonardo.ai" and got["content"] == "ChatGPT"
    assert picker.current_file_reader() == "Claude"
    assert "visual" not in picker.visible_agents()


def test_the_setup_walk_ends_on_the_sign_in_page_with_the_picked_sites(ai):
    from widgets.wizard_panel import WizardPanel, LOGIN
    walk = WizardPanel(CB.config.load())
    walk.start(CB.config.load())
    walk._go_next()
    walk._go_next()
    assert walk.stack.currentIndex() == LOGIN
    blob = _texts(walk)
    assert "https://chatgpt.com" in blob and "https://claude.ai" in blob
    assert "Open login tabs" in blob
    walk._finish()
    saved = CB.config.load()
    assert saved["default_work_setup"] is True and saved["analysis_agent"] == "ChatGPT"
    with open(CB.config.CONFIG_PATH, encoding="utf-8") as f:
        assert CB.ai_client.AI_KEY not in f.read()      # the real keys survive


def test_login_tabs_open_only_the_browser_tools(ai, monkeypatch):
    from widgets import login_tabs, loader
    import workers
    asked = []

    class Worker:
        def __init__(self, urls, parent=None):
            asked.extend(urls)
            self.done = self.failed = type("S", (), {"connect": lambda *a: None})()

        def start(self):
            pass

        def isRunning(self):
            return False

    class Wait:
        def __init__(self, *a, **k):
            pass

        def show(self):
            pass

        def close(self):
            pass
    monkeypatch.setattr(workers, "LoginTabsWorker", Worker)
    monkeypatch.setattr(loader, "LoadingDialog", Wait)
    parent = type("P", (), {})()
    assert login_tabs.open_login_tabs(
        parent, {"brains": "Claude", "visual": "Leonardo.ai", "media": "Prism Studio"})
    assert any("claude.ai" in u for u in asked)
    assert not any("leonardo" in u or u.startswith("local:") for u in asked)


def test_the_plan_names_browser_tools_and_says_prism_ai_for_the_video(ai):
    from widgets.agents_panel import AgentsPanel
    routing = {s: {"needed": True, "questions": ["q"]}
               for s in ("research", "content", "media")}
    panel = AgentsPanel()
    panel.set_content(routing, CB.agents.server_effective({}), "make a reel")
    rows = {r.stage: r for r in panel._rows}
    assert rows["research"].chip.shown() == "ChatGPT" and rows["research"].where == "browser"
    assert rows["content"].chip.shown().startswith("Prism AI")      # the video's script
    assert rows["media"].chip.shown().startswith("Prism AI")
    rows["media"].toggle()                      # no video: the writing is theirs
    panel._apply_places()
    assert rows["content"].chip.shown() == "ChatGPT"


def test_a_run_card_names_the_site_for_a_browser_step_only(ai):
    from widgets.output_panel import OutputPanel
    panel = OutputPanel()
    panel.set_plan({"content": "Claude", "visual": "Prism Image"},
                   places={"content": "browser", "visual": "server"})
    panel.set_running(True)
    assert panel._cards["content"].tool_name.text() == "Claude"
    assert panel._cards["visual"].tool_name.text().startswith("Prism AI")
    assert not panel.fallback_btn.isHidden()
    panel.set_plan({"visual": "Prism Image"}, places={"visual": "server"})
    panel.set_running(True)
    assert panel.fallback_btn.isHidden()


# ── the window: who asks for the browser ─────────────────────────────────────

def test_the_worker_asks_for_the_browser_only_when_told(ai, monkeypatch):
    import workers
    seen = []
    monkeypatch.setattr(automation, "run",
                        lambda *a, **k: seen.append(k) or ({}, {}))
    for kw in ({}, {"default_work": True}):
        workers.AutomationWorker({}, {}, [], "q", **kw).run()
    assert "default_work" not in seen[0] and seen[1]["default_work"] is True


@pytest.fixture(scope="module")
def _window():
    from unittest import mock
    import licensing
    from main_window import MainWindow
    with mock.patch.object(licensing, "has", lambda *a, **k: True), \
            mock.patch.object(MainWindow, "_first_run"):
        return MainWindow()


@pytest.fixture
def win(ai, _window, monkeypatch, tmp_path):
    """The real window; the run worker is recorded instead of started."""
    import awake
    import licensing
    import main_window
    import workspace
    made = []

    class Signal:
        def connect(self, *a):
            pass

    class Worker:
        def __init__(self, routing, cfg, attachments, query, **kw):
            self.kw = kw
            self.stage_event = self.done = self.failed = Signal()
            made.append(self)

        def start(self):
            pass

        def isRunning(self):
            return False

        def stopping(self):
            return False

    monkeypatch.setattr(main_window, "AutomationWorker", Worker)
    monkeypatch.setattr(awake, "acquire", lambda: None)
    monkeypatch.setattr(awake, "release", lambda: None)
    monkeypatch.setattr(licensing, "has", lambda *a, **k: True)
    monkeypatch.setattr(workspace, "runs_dir", lambda *a, **k: str(tmp_path))
    w = _window
    w.cfg = {**w.cfg, "api_key": "prism-ai", "onboarded": True}
    w.output_panel.clear()
    w._followup_session = None
    w._current_run_file = None
    w._is_followup_run = False
    w._followup_text = ""
    w._run_default_work = False
    w._stage_where = {}
    w._turn_begun = False
    w.made = made
    return w


def _home_task(win):
    import types
    win._last_query = "write about trees"
    win.routing = {}
    win.attachments = []
    win._start_run(types.SimpleNamespace(allowed=True, run_id="r-test"),
                   {"content": "Claude"},
                   [("content", "Claude", ["Write about trees."])])


def test_a_home_task_asks_for_the_browser_and_so_does_its_follow_up(win):
    _home_task(win)
    assert win.made[-1].kw["default_work"] is True
    card = win.output_panel._cards["content"]
    assert card.where == "browser" and card.tool_name.text() == "Claude"

    win._on_stage_event("stage_start", {"stage": "content", "agent": "Claude",
                                        "on": "browser"})
    win._save_run({"content": ["Trees."]}, {"content": "https://claude.ai/chat/1"})
    with open(win._current_run_file, encoding="utf-8") as f:
        record = json.load(f)
    assert record["default_work"] is True and record["ran_in"] == {"content": "browser"}

    win._prime_followup_session({"content": ["Trees."]},
                                {"content": "https://claude.ai/chat/1"})
    win._followup_text = "shorter"
    win._start_followup_run(["content"], [])
    sent = win.made[-1].kw
    assert sent["default_work"] is True
    assert sent["resume_urls"] == {"content": "https://claude.ai/chat/1"}


def test_a_follow_up_on_an_add_ons_result_stays_on_the_server(win, monkeypatch):
    _home_task(win)                              # a task ran earlier
    monkeypatch.setattr(win, "_offer_followup",
                        lambda r, l=None, artifacts_dir="":
                        win._prime_followup_session(r, l, artifacts_dir))
    win._offer_followup_for_dialog("BOQ - tower", {"format": ["The schedule."]},
                                   {"format": "Claude"}, {})
    win._followup_text = "add a total"
    win._start_followup_run(["format"], [])
    assert "default_work" not in win.made[-1].kw
    assert not win._followup_in_browser()


def test_a_task_saved_before_this_change_continues_on_the_server(win, tmp_path):
    record = {"query": "old task", "responses": {"content": ["Old."]},
              "agents": {"content": "ChatGPT"}}
    path = tmp_path / "run_1.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    win._open_thread(str(path), record)
    assert not win._followup_in_browser()


def test_the_setup_walk_is_offered_once_and_never_blocks_a_task(win):
    win.cfg.pop("default_work_setup", None)
    assert win._browser_setup_due() and win._ready_to_plan()
    win.cfg["default_work_setup"] = True
    assert not win._browser_setup_due()

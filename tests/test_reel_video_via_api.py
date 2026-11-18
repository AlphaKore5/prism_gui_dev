"""A reel is a video pipeline on Prism's server, never one picture and never Chrome.

Real code: router.route (planner call, guardrails), automation.run (script ->
pictures -> art direction -> local render), ai_client, the STEP model pick.
The only fakes: Prism's server (FakeAi, real HTTP on 127.0.0.1, other hosts fail
the test) and, in one test, the encoder. Every test also fails if an AI step
asks for a browser: the driver factory, undetected_chromedriver and Selenium
all raise. Playwright is allowed to start ONLY for drawing frames locally.

Run on its own, in a fresh HOME with a .prism folder:
    HOME=$d python -m pytest tests/test_reel_video_via_api.py
"""
from __future__ import annotations

import json
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402,F401
from core import ai_client                                          # noqa: E402
from test_ai_via_server import FakeAi, ai, PNG                      # noqa: E402,F401

REEL = "make an Instagram reel about Tulsi Vivah for customers"
SCRIPT = {"scenes": [
    {"role": "hook", "seconds": 4, "kicker": "Tulsi Vivah", "headline": "Our tulsi is getting married", "support": ""},
    {"role": "statement", "seconds": 5, "kicker": "The ritual", "headline": "Light a diya at dusk", "support": "Bring the family together"},
    {"role": "endcard", "seconds": 4, "headline": "Shri Tulsi Garden", "support": "Fresh tulsi, all season", "contact": "tulsigarden.example"}]}
DESIGN_REPLY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "studio_design_reply.txt")
OWNER_AGENTS = {"brains": "ChatGPT", "content": "Claude", "visual": "ChatGPT", "research": "Grok"}


@pytest.fixture
def no_ai_browser(monkeypatch):
    """An AI step that asks for Chrome fails the test. Local drawing may use Playwright."""
    from core import automation

    def boom(*a, **k):
        raise AssertionError("an AI step launched a browser -- AI must run on Prism's server")

    monkeypatch.setattr(automation, "_setup_chrome_driver", boom)
    fake_uc = types.ModuleType("undetected_chromedriver")
    fake_uc.Chrome = boom
    monkeypatch.setitem(sys.modules, "undetected_chromedriver", fake_uc)
    try:
        import selenium.webdriver as wd
        monkeypatch.setattr(wd, "Chrome", boom)
    except ImportError:
        pass


def _plan(ai, planner_json: dict, query: str, agents: dict):
    from core import router, config as C
    ai.text = json.dumps(planner_json)
    cfg = C.load()
    cfg["agents"] = dict(agents)
    routing = router.route(query, cfg)
    return routing, router.planned_steps(routing, C.active_agents(cfg))


# ── the plan ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("planner", [
    {"visual": {"needed": True, "kind": "image", "questions": ["Create an image for the reel"]}},
    {},
    {"brains": {"needed": True, "questions": ["Think about it"]}},
])
def test_a_reel_is_script_then_render_never_a_lone_picture(ai, no_ai_browser, planner):
    routing, steps = _plan(ai, planner, REEL, OWNER_AGENTS)
    stages = [s for s, _ in steps]
    assert "media" in stages and "content" in stages
    assert stages.index("content") < stages.index("media")
    assert "visual" not in stages, "the renderer makes the scene pictures itself"
    media_tool = dict(steps)["media"]
    assert media_tool in ("Prism Studio", "Prism Reel", "Prism Motion")
    assert routing["media"].get("kind") == "video"


def test_a_picture_site_in_the_saved_config_is_never_the_tool(ai, no_ai_browser):
    """The owner's config said visual = ChatGPT and no video tool at all."""
    _routing, steps = _plan(ai, {"visual": {"needed": True, "kind": "image",
                                            "questions": ["Draw a poster"]}},
                            "design a poster for Diwali sale", OWNER_AGENTS)
    assert dict(steps)["visual"] == "Prism Image"


def test_pictures_only_requests_stay_pictures(ai, no_ai_browser):
    for q in ("design a poster for Diwali sale", "make a logo for my shop",
              "make an image for my reel cover", "create a thumbnail for my video"):
        _routing, steps = _plan(ai, {"visual": {"needed": True, "kind": "image",
                                                "questions": ["Make the picture"]}},
                                q, OWNER_AGENTS)
        stages = [s for s, _ in steps]
        assert "visual" in stages and "media" not in stages, q


def test_a_reel_that_also_asks_for_a_poster_keeps_both(ai, no_ai_browser):
    _r, steps = _plan(ai, {"visual": {"needed": True, "kind": "image", "questions": ["A poster"]}},
                      "make an instagram reel and a poster for tulsi vivah", OWNER_AGENTS)
    stages = [s for s, _ in steps]
    assert "media" in stages and "visual" in stages


@pytest.mark.parametrize("q,expected", [
    (REEL, True), ("make a 20 second video ad for our cranes", True),
    ("an animated explainer about GST", True), ("youtube shorts script and video", True),
    ("design a poster", False), ("write a blog post about reels", True),
    ("image for my reel", False), ("write a report on crane hire", False),
    ("send an email to the customer", False)])
def test_what_counts_as_a_video_request(q, expected):
    from core import router
    assert router.is_video_request(q) is expected


def test_the_planner_prompt_says_a_video_is_a_pipeline(ai):
    from core import router
    p = router.build_prompt(REEL, "", {"content": "Claude", "visual": "Prism Image",
                                       "media": "Prism Studio"})
    assert "A VIDEO IS NEVER ONE PICTURE" in p
    assert "in a browser" not in p


def test_agents_are_filled_for_server_mode_and_untouched_otherwise(ai, monkeypatch):
    from core import agents as A
    eff = A.server_effective({"visual": "ChatGPT", "media": "Runway"})
    assert eff["visual"] == "Prism Image" and eff["media"] == "Prism Studio"
    assert eff["brains"] and eff["content"] and eff["research"]
    assert A.server_effective({"media": "Prism Motion"})["media"] == "Prism Motion"
    monkeypatch.setenv("PRISM_AI_DIRECT", "1")
    assert A.server_effective({"visual": "ChatGPT"}) == {"visual": "ChatGPT"}


def test_the_server_mode_browser_launcher_refuses(ai):
    from core import automation
    with pytest.raises(RuntimeError, match="never opens a browser"):
        automation._get_driver({})


# ── the run ─────────────────────────────────────────────────────────────────

def _responder(seen):
    def resp(body):
        txt = json.dumps(body["messages"][-1]["content"])
        seen.append(body)
        if "ART DIRECTOR" in txt:
            return open(DESIGN_REPLY, encoding="utf-8").read()
        if "SCRIPT for a short vertical" in txt:
            return "```json\n" + json.dumps(SCRIPT) + "\n```"
        return "A calm answer."
    return resp


def _run_reel(ai, monkeypatch=None, render=None):
    import ai_server
    from core import automation, config as C
    seen: list = []
    ai.responder = _responder(seen)
    events: list = []
    ai_server.begin_run("run-reel-1")
    try:
        out = automation.run({}, C.load(), custom_stages=[
            ("content", "Claude", ["Write the reel script."]),
            ("media", "Prism Studio", ["Make the reel."])],
            chatgpt_analysis=False, query=REEL, failover=True,
            on_event=lambda k, p: events.append((k, p)))
    finally:
        ai_server.end_run()
    return out, events


def _no_browser_launched(monkeypatch):
    """Records Playwright launches: allowed for drawing, and counted."""
    from core import browser
    launched = []
    real = browser.launch_chromium

    def spy(pw, *a, **k):
        launched.append(1)
        return real(pw, *a, **k)

    monkeypatch.setattr(browser, "launch_chromium", spy)
    return launched


def test_reel_run_transport_with_a_fake_encoder(ai, no_ai_browser, tmp_path, monkeypatch):
    """Script, picture briefs, pictures, art direction and the render call all
    happen, every call is tagged with the run, and no browser starts. The
    encoder is replaced by one that writes a file, so this holds on a box
    without Chromium."""
    from core import reel_web

    def fake_render(spec, out, **kw):
        with open(out, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        return out

    monkeypatch.setattr(reel_web, "render", fake_render)
    (responses, links), events = _run_reel(ai)
    kinds = [k for k, _ in events]
    assert "stage_error" not in kinds, [p for k, p in events if k == "stage_error"]
    done = [p["stage"] for k, p in events if k == "stage_done"]
    assert done[:1] == ["content"] and "artwork" in done and "design" in done and done[-1] == "media"
    assert links.get("media", "").endswith(".mp4") and os.path.getsize(links["media"]) > 0
    chats = ai.chats()
    assert {c["body"]["role"] for c in chats} <= {"writer", "code"}
    assert any(c["body"]["role"] == "code" for c in chats)
    images = [c for c in ai.calls if c["path"] == "/v1/ai/image"]
    assert images, "the scene pictures come from the image role"
    for c in chats + images:
        assert c["body"]["run_id"] == "run-reel-1", c["body"]["feature"]
        assert c["body"]["addon"] and c["body"]["feature"]
    # Playwright may start for the local layout check of the scenes; that is
    # drawing, not AI, and no_ai_browser proves nothing else asked for Chrome.


def test_reel_run_really_renders_an_mp4(ai, no_ai_browser, tmp_path, monkeypatch):
    from core import reel_web
    ok, why = reel_web.available()
    if not ok:
        pytest.skip("local renderer not available here: " + why)
    launched = _no_browser_launched(monkeypatch)
    (responses, links), events = _run_reel(ai)
    assert not [p for k, p in events if k == "stage_error"]
    mp4 = links.get("media", "")
    assert mp4.endswith(".mp4") and os.path.getsize(mp4) > 20_000
    assert launched, "frames are drawn by the local renderer"


def test_an_out_of_credits_reel_says_so_and_does_not_open_chrome(ai, no_ai_browser):
    from core import automation, config as C
    ai.error = (402, "INSUFFICIENT_CREDITS", "You are out of credits. Top up to continue.", {})
    events = []
    automation.run({}, C.load(), custom_stages=[
        ("content", "Claude", ["Write the reel script."]),
        ("media", "Prism Studio", ["Make the reel."])],
        chatgpt_analysis=False, query=REEL, failover=True,
        on_event=lambda k, p: events.append((k, p)))
    errs = [p for k, p in events if k == "stage_error"]
    assert errs and "out of credits" in errs[0]["error"]


def test_the_chrome_guardrail_line_never_appears_in_server_mode(ai, no_ai_browser, capsys):
    _plan(ai, {"visual": {"needed": True, "kind": "image", "questions": ["Make a picture"]}},
          REEL, OWNER_AGENTS)
    out = capsys.readouterr().out
    assert "visual (ChatGPT)" not in out and "Chrome" not in out


# ── cost on the plan ────────────────────────────────────────────────────────

def test_the_plan_gets_an_about_n_credits_figure(ai):
    from core import router, config as C
    routing, steps = _plan(ai, {}, REEL, OWNER_AGENTS)
    cfg = C.load()
    cfg["agents"] = dict(OWNER_AGENTS)
    est = router.estimate_run(routing, C.active_agents(cfg))
    assert est["calls"] >= 10 and est["typical_mc"] > 0 and est["max_mc"] >= est["typical_mc"]
    est_paths = [c for c in ai.calls if c["path"] == "/v1/ai/estimate"]
    assert est_paths and all(c["body"]["feature"] == "plan_estimate" for c in est_paths)
    assert [c for c in est_paths if c["body"]["images"] >= 1], "the pictures are priced too"
    import main_window
    note = main_window.MainWindow._estimate_note({"_estimate": est})
    assert "about" in note and "credits" in note


def test_no_estimate_when_ai_is_not_on_the_server(ai, monkeypatch):
    from core import router
    monkeypatch.setenv("PRISM_AI_DIRECT", "1")
    assert router.estimate_run({"content": {"needed": True, "questions": ["x"]}},
                               {"content": "Claude"}) == {}


# ── STEP model pick and wording ─────────────────────────────────────────────

@pytest.mark.parametrize("pick,expected", [
    ("Claude Haiku 5.5", "anthropic/claude-haiku-5.5"),
    ("Claude Sonnet 5.5", "anthropic/claude-sonnet-5.5")])
def test_step_haiku_sonnet_pick_reaches_the_server(ai, monkeypatch, pick, expected):
    from addons.step import workers, dialog
    monkeypatch.setattr(workers.CB, "get_stepfile", lambda: types.SimpleNamespace(
        ask_prompt=lambda r, q: "q", plan_prompt=lambda r, q, s: "p"))
    got = []
    for cls, args in ((workers.StepAskWorker, ({}, {}, "why")),
                      (workers.StepPlanWorker, ({}, {}, "why", "ideas"))):
        w = cls(*args, model=dialog.MODEL_IDS[pick])
        w.done.connect(got.append)
        w.failed.connect(lambda m: got.append("FAILED " + m))
        w.run()
    assert not [g for g in got if str(g).startswith("FAILED")], got
    bodies = [c["body"] for c in ai.chats()]
    assert [b["model"] for b in bodies] == [expected, expected]
    assert {b["role"] for b in bodies} == {"reasoner"}


def test_a_model_hint_is_still_not_sent_when_nobody_picked_it(ai):
    from core import openrouter
    openrouter.openrouter_chat("", "anthropic/claude-sonnet-5.5", "hi", role="writer",
                               addon="step", feature="x")
    assert "model" not in ai.chats()[-1]["body"]


def test_step_wording_says_prism_plan_not_own_key(ai):
    import i18n
    from addons.step import panel, dialog
    src = open(dialog.__file__, encoding="utf-8").read()
    assert "Both run on your Prism plan. Haiku answers in seconds and costs fewer credits" in src
    roles = panel.StepPanel.tool_roles.__doc__ + json.dumps(
        panel.StepPanel.tool_roles(types.SimpleNamespace()))
    assert "OpenRouter key" not in roles and "browser tab" not in roles
    cat = open(os.path.join(ROOT, "lang", "_catalogue.json"), encoding="utf-8").read()
    assert "own OpenRouter key" not in cat or "STEP" not in cat.split("own OpenRouter key")[0][-200:]


def test_chrome_and_sign_in_sentences_are_reworded_in_server_mode(ai):
    import i18n
    import ai_server
    from dialogs import guide_dialog
    login = [t for t in guide_dialog.TOPICS if t.title == "Signing in to the AI tools"][0]
    assert "Chrome" not in i18n.t(login.body) and "sign in to each" not in i18n.t(login.body)
    for old, new in ai_server._SERVER_WORDS.items():
        assert i18n.t(old) == new
    i18n.set_rewording({})
    assert i18n.t("It drives your own browser") == "It drives your own browser"

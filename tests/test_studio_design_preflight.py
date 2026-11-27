"""Studio: no paid design call for a script that is still a template.

26 Nov 2026: with no brand files attached the writer returned a script made of
"[HOOK WORD - awaiting brand copy]" and "[BRAND NAME]"; the art director was
paid to design it and returned something that could not be filmed. The design
step now stops first, in plain words, with nothing charged.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import core_bridge as CB                                            # noqa: E402,F401
from test_ai_via_server import FakeAi, ai, PNG                      # noqa: E402,F401
from test_reel_video_via_api import REEL, SCRIPT, no_ai_browser, DESIGN_REPLY  # noqa: E402,F401

PLACEHOLDER_SCRIPT = copy.deepcopy(SCRIPT)
PLACEHOLDER_SCRIPT["scenes"][0]["kicker"] = "[BRAND NAME]"
PLACEHOLDER_SCRIPT["scenes"][0]["headline"] = "[HOOK WORD - awaiting brand copy]"


def _run(ai, monkeypatch, tmp_path, script, attachments=None, cfg_over=None):
    import ai_server
    from core import automation, config as C, reel_web, ui
    shown: list[str] = []
    monkeypatch.setattr(ui, "err", lambda m, *a, **k: shown.append(str(m)))
    monkeypatch.setattr(reel_web, "available", lambda: (True, ""))
    kept: list = []
    monkeypatch.setattr(automation, "_keep_failed_spec",
                        lambda *a, **k: kept.append(a) or str(tmp_path / "x.txt"))

    def resp(body):
        txt = json.dumps(body["messages"][-1]["content"])
        if "ART DIRECTOR" in txt:
            return open(DESIGN_REPLY, encoding="utf-8").read()
        if "SCRIPT for a short vertical" in txt:
            return "```json\n" + json.dumps(script) + "\n```"
        return "A calm answer."

    ai.responder = resp
    cfg = C.load()
    cfg.update(cfg_over or {})
    events: list = []
    ai_server.begin_run("run-preflight-1")
    try:
        out = automation.run({}, cfg, custom_stages=[
            ("content", "Claude", ["Write the reel script."]),
            ("media", "Prism Studio", ["Make the reel."])],
            chatgpt_analysis=False, query=REEL, failover=True,
            attachments=attachments, on_event=lambda k, p: events.append((k, p)))
    finally:
        ai_server.end_run()
    designs = [c for c in ai.chats() if "ART DIRECTOR" in json.dumps(c["body"]["messages"][-1]["content"])]
    return out, events, shown, kept, designs


def test_a_placeholder_script_with_nothing_attached_makes_no_design_call(ai, no_ai_browser, monkeypatch, tmp_path):
    (responses, links), events, shown, kept, designs = _run(
        ai, monkeypatch, tmp_path, PLACEHOLDER_SCRIPT)
    assert designs == []
    assert not kept, "nothing came back, so there is no would-not-parse file"
    errs = [p["error"] for k, p in events if k == "stage_error"]
    said = " ".join(errs + shown)
    assert "still has placeholders" in said and "Nothing was charged" in said
    assert "Attach your brand files" in said
    assert not links.get("media")


def test_a_real_script_still_gets_its_design(ai, no_ai_browser, monkeypatch, tmp_path):
    _out, events, _shown, _kept, designs = _run(ai, monkeypatch, tmp_path, SCRIPT)
    assert designs
    assert not [p for k, p in events if k == "stage_error"
                and "placeholders" in p["error"]]


def test_a_placeholder_script_with_attachments_goes_ahead(ai, no_ai_browser, monkeypatch, tmp_path):
    from core import files
    logo = tmp_path / "logo.png"
    logo.write_bytes(base64.b64decode(PNG))
    _out, _events, _shown, _kept, designs = _run(
        ai, monkeypatch, tmp_path, PLACEHOLDER_SCRIPT, attachments=[files.attach(str(logo))])
    assert designs


def test_a_placeholder_script_with_a_brand_kit_goes_ahead(ai, no_ai_browser, monkeypatch, tmp_path):
    _out, _events, _shown, _kept, designs = _run(
        ai, monkeypatch, tmp_path, PLACEHOLDER_SCRIPT,
        cfg_over={"brand_kit": {"name": "Shri Tulsi Garden"}})
    assert designs

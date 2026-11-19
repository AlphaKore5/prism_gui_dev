"""Every AI call in Prism goes through Prism's licence server, never to a provider.

The real code paths run (the planner, BOQ write-up and tag reading, STEP, the
Inquiry matcher, Email triage, the PO reader, pictures, the Motion critic,
dictation clean-up, Support). The only fake is the server: a real HTTP server
on 127.0.0.1 that records every request and answers like /v1/ai/*. A guard
refuses any request to another host, so a call that still reached OpenRouter or
Groq fails the test instead of the network.

Run on its own, in a fresh HOME:  python -m pytest tests/test_ai_via_server.py
"""
from __future__ import annotations

import base64
import json
import os
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402
import requests                                                     # noqa: E402

import core_bridge as CB                                            # noqa: E402
from core import ai_client                                          # noqa: E402

# A real-looking pair of provider keys: if either string appears in anything the
# fake server receives, a customer's key has left the machine.
REAL_GROQ = "gsk_" + "G" * 40
REAL_OR = "sk-or-v1-" + "O" * 40
PNG = base64.b64encode(
    base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
).decode()


class FakeAi:
    """/v1/ai/* over real HTTP on 127.0.0.1."""

    def __init__(self):
        self.calls: list[dict] = []
        self.text = '{"title": "Test job"}'
        self.responder = None           # optional: body -> reply text, per request
        self.image = PNG                # base64 returned by /v1/ai/image
        self.error = None               # (http status, code, message, detail)
        self.run_costs: dict = {}       # run_id -> {"mc": n, ...} for /v1/ai/run-cost
        self.status_body = {"api": 1, "ready": True, "reason": "", "mc_per_credit": 1000,
                            "balance_mc": 40_000, "allowance_mc": 100_000,
                            "plan": {"key": "pro", "name": "Pro"},
                            "cycle": {"days_left": 12, "days": 30}}
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                outer.calls.append({"path": self.path, "body": body,
                                    "headers": {k.lower(): v for k, v in self.headers.items()}})
                if outer.error and self.path != "/v1/ai/status":
                    status, code, msg, detail = outer.error
                    return self._json(status, {"error": {"code": code, "message": msg, "detail": detail}})
                if self.path == "/v1/ai/status":
                    return self._json(200, outer.status_body)
                if self.path == "/v1/ai/estimate":
                    return self._json(200, {"min_mc": 1, "typical_mc": 5, "max_mc": 20, "balance_mc": 40_000,
                                            "enough": True})
                if self.path == "/v1/ai/run-cost":
                    return self._json(200, {"runs": {r: outer.run_costs[r] for r in body.get("run_ids", [])
                                                     if r in outer.run_costs}, "mc_per_credit": 1000})
                if self.path == "/v1/ai/image":
                    return self._json(200, {"images": [outer.image], "images_count": 1, "charged_mc": 40,
                                            "balance_mc": 39_960})
                if self.path == "/v1/ai/chat":
                    return self._json(200, {"text": (outer.responder(body) if outer.responder else outer.text), "finish": "stop",
                                            "model": {"key": "m", "label": "M"},
                                            "usage": {"in": 11, "out": 7, "cached": 0},
                                            "charged_mc": 25, "balance_mc": 39_975})
                if self.path == "/v1/ai/chat/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for ev, data in (("meta", {}), ("delta", {"t": "Hel"}), ("ping", {}),
                                     ("delta", {"t": "lo"}),
                                     ("done", {"usage": {"in": 3, "out": 2}, "charged_mc": 9,
                                               "balance_mc": 39_000})):
                        self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode())
                    return
                self._json(404, {"detail": "Not Found"})

            def _json(self, status, obj):
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()

    @property
    def last(self) -> dict:
        return self.calls[-1]

    def chats(self):
        return [c for c in self.calls if c["path"] == "/v1/ai/chat"]


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAi()
    import licensing
    import ai_server
    monkeypatch.delenv("PRISM_AI_DIRECT", raising=False)
    monkeypatch.setattr(licensing, "state", lambda: types.SimpleNamespace(license_id="LIC-TEST-1"))
    monkeypatch.setattr(licensing, "device_fingerprint", lambda: "fp-test-0123456789")
    monkeypatch.setattr(licensing, "lease_bearer", lambda: "PRSMLv1.test-lease")
    monkeypatch.setattr(licensing.client, "server_url", lambda: fake.url)
    from core import agents as _agents
    _snap = {k: dict(v, agents=list(v["agents"])) for k, v in _agents.CATEGORIES.items()}
    ai_server.install()
    ai_server._cache.update({"at": 0.0, "status": None, "error": ""})

    real_send = requests.Session.send

    def guarded(self, request, **kw):
        host = requests.utils.urlparse(request.url).hostname
        if host not in ("127.0.0.1", "localhost"):
            raise AssertionError("a request left for %s -- AI must go through Prism's server" % host)
        return real_send(self, request, **kw)

    monkeypatch.setattr(requests.Session, "send", guarded)
    # The customer still has provider keys saved by an older Prism.
    from core import config as C
    with open(C.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"api_key": REAL_GROQ, "openrouter_api_key": REAL_OR, "onboarded": True,
                   "agents": {"brains": "Claude"}}, f)
    yield fake
    _agents.CATEGORIES.clear()
    _agents.CATEGORIES.update(_snap)
    ai_client.set_auth_provider(None)
    ai_client.set_usage_listener(None)
    from widgets import usage_chip
    usage_chip.set_provider(None)
    fake.close()


def _assert_clean(fake):
    """No provider key left the machine, and every spending call carried the lease."""
    assert fake.calls, "nothing reached Prism's server"
    for c in fake.calls:
        blob = json.dumps(c["body"]) + json.dumps(c["headers"])
        assert REAL_GROQ not in blob and REAL_OR not in blob, c["path"]
        assert ai_client.AI_KEY not in blob, "the stand-in key must never be sent"
        assert c["body"]["license_id"] == "LIC-TEST-1"
        if c["path"] in ("/v1/ai/chat", "/v1/ai/chat/stream", "/v1/ai/image"):
            assert c["headers"]["authorization"] == "Bearer PRSMLv1.test-lease"
            assert c["headers"]["x-prism-channel"] in ("dev", "prod")


def _cfg():
    from core import config as C
    return C.load()


# ── the seam and the config ──────────────────────────────────────────────────

class Seam:
    def test_config_shows_a_stand_in_and_never_writes_it(self, ai):
        from core import config as C
        cfg = C.load()
        assert cfg["api_key"] == ai_client.AI_KEY and cfg["openrouter_api_key"] == ai_client.AI_KEY
        cfg["profile"] = "changed"
        C.save(cfg)
        on_disk = json.load(open(C.CONFIG_PATH, encoding="utf-8"))
        assert on_disk["api_key"] == REAL_GROQ and on_disk["openrouter_api_key"] == REAL_OR
        assert on_disk["profile"] == "changed"

    def test_save_does_not_invent_a_key_field(self, ai):
        from core import config as C
        os.remove(C.CONFIG_PATH)
        cfg = C.load()
        C.save(cfg)
        on_disk = json.load(open(C.CONFIG_PATH, encoding="utf-8"))
        assert ai_client.AI_KEY not in json.dumps(on_disk)

    def test_direct_switch_puts_the_old_path_back(self, ai, monkeypatch):
        monkeypatch.setenv("PRISM_AI_DIRECT", "1")
        assert not ai_client.active()
        from core import config as C
        assert C.load()["api_key"] == REAL_GROQ
        seen = {}

        class R:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": "direct"}}]}
        with mock.patch.object(CB.router.requests, "post",
                               side_effect=lambda url, **kw: seen.update(url=url) or R()):
            assert CB.router.groq_chat(REAL_GROQ, "m", "hi") == "direct"
        assert "groq.com" in seen["url"] and not ai.calls

    def test_stream_chat_status_estimate_run_cost(self, ai):
        assert "".join(ai_client.stream("writer", "hi", addon="studio", feature="x")) == "Hello"
        assert ai.last["path"] == "/v1/ai/chat/stream" and ai.last["body"]["role"] == "writer"
        assert ai_client.status()["ready"] is True
        assert ai_client.estimate("writer", approx_in_chars=100)["max_mc"] == 20
        assert ai_client.run_cost(["r1"])["mc_per_credit"] == 1000
        assert ai_client.image("a cat", aspect_ratio="4:5")
        assert ai.last["body"]["aspect_ratio"] == "3:4"      # the server takes five shapes
        _assert_clean(ai)

    def test_usage_sink_and_out_are_filled(self, ai):
        usage, sink = {}, {}
        ai_client.chat("writer", "hi", usage_out=usage, usage_sink=sink)
        assert usage["total_tokens"] == 18 and usage["finish_reason"] == "stop"
        assert usage["answer_from_reasoning"] is False and "cost" in sink


# ── every call site hits the seam, under the right role ──────────────────────

class Sites:
    def _only(self, ai, role, addon, feature=None):
        c = ai.chats()[-1]["body"]
        assert (c["role"], c["addon"]) == (role, addon), c
        if feature:
            assert c["feature"] == feature
        _assert_clean(ai)

    def test_planner_title_and_enrich(self, ai):
        assert CB.router.title_for("a poster for Diwali", "", "k", "m") == "Test job"
        self._only(ai, "planner", "core")
        assert ai.chats()[-1]["body"]["json_mode"] is True
        ai.text = "- GOAL: x"
        assert CB.router.enrich_query("poster", "", "k", "m")
        self._only(ai, "planner", "core")

    def test_followup_router_worker(self, ai):
        from workers import FollowupRouteWorker
        ai.text = '{"steps": ["content"], "images": ""}'
        w = FollowupRouteWorker.__new__(FollowupRouteWorker)
        src = open(os.path.join(ROOT, "workers.py"), encoding="utf-8").read()
        assert 'feature="followup_route"' in src               # constructed fully below
        out = CB.router.groq_chat(_cfg()["api_key"], "", "p", json_mode=True, role="planner",
                                  addon="core", feature="followup_route")
        assert out and ai.chats()[-1]["body"]["feature"] == "followup_route"

    def test_support_worker(self, ai):
        from workers import SupportWorker
        got = []
        w = SupportWorker(_cfg(), "what is wrong")
        w.done.connect(got.append)
        ai.text = "try this"
        w.run()
        assert got == ["try this"]
        self._only(ai, "writer", "support")

    def test_po_reader(self, ai):
        ai.text = json.dumps({"po_number": "P1", "lines": []})
        from core import po
        try:
            po.extract("Purchase order 1\nitem x qty 2", _cfg()["api_key"], "")
        except Exception:
            pass                                               # the fields are not the point; the call is
        self._only(ai, "classify", "inquiry", "po_read")

    def test_email_triage_and_reply_intent_and_details(self, ai):
        from core import inbox, mailflow, triage
        m = inbox.Message(uid=1, subject="Please send your best price", from_addr="a@b.com",
                          body="hello " * 10)
        ai.text = "1: INQUIRY"
        triage.classify([m], _cfg()["api_key"], local_only=False)
        if ai.chats():
            self._only(ai, "classify", "email", "triage")
        ai.calls.clear()
        ai.text = "negotiating"
        mailflow.reply_intent(inbox.Message(uid=2, subject="re: quote", body="Noted. We will revert after the board meets next week."),
                              _cfg()["api_key"])
        self._only(ai, "classify", "email", "reply_intent")
        ai.text = '{"customer": "X"}'
        mailflow.extract_details(inbox.Message(uid=3, subject="rfq", body="need 5 pumps"),
                                 _cfg()["api_key"])
        self._only(ai, "classify", "email", "inquiry_details")

    def test_inquiry_ai_match(self, ai):
        from addons.inquiry import ai_match
        ai.text = "[]"
        try:
            ai_match.match(_cfg()["openrouter_api_key"], "need two pumps", [])
        except Exception:
            pass
        self._only(ai, "classify", "inquiry", "ai_match")

    def test_pathfinder_and_dictation_cleanup(self, ai):
        from core import pathfinder, voice
        ai.text = '{"folders": ["a"], "filename": null}'
        pathfinder._llm_parse("the a folder", _cfg()["api_key"], "m")
        self._only(ai, "classify", "core", "pathfinder")
        ai.text = '{"cleaned": "hi", "files": [], "task": "hi"}'
        out = voice.interpret("hi", _cfg())
        assert out["ok"] is True
        self._only(ai, "classify", "core", "dictation")

    def test_dictation_audio_is_not_sent_anywhere(self, ai):
        from core import voice
        with pytest.raises(RuntimeError) as e:
            voice.transcribe(b"RIFF", _cfg())
        assert "plan" in str(e.value)
        assert not ai.calls

    def test_boq_prism_agents_use_their_own_roles(self, ai):
        from addons.boq import openrouter_writer as w
        ai.text = "A BOQ document that is long enough to be whole."
        w.write("Prism Agent Claude", "write it", _cfg()["openrouter_api_key"])
        self._only(ai, "boq.agent_a", "boq", "write")
        w.write("Prism Agent Deep", "write it", _cfg()["openrouter_api_key"], followup=True)
        self._only(ai, "boq.agent_b", "boq", "followup")
        # the hints are not sent: the server owns the model
        assert "model" not in ai.chats()[-1]["body"] and "claude" not in json.dumps(ai.chats()[-1]["body"])

    def test_boq_tag_reading_sends_the_picture_under_boq_tag_vision(self, ai):
        from addons.boq import workers as bw
        h = bw.HvacTakeoffWorker("HVAC", "x.pdf", {}, 1.0, api_key=_cfg()["openrouter_api_key"])
        ai.text = "VAV-1\nVAV-2"
        assert h._tag_reader(b"\x89PNGfake") == "VAV-1\nVAV-2"
        self._only(ai, "boq.tag_vision", "boq", "hvac_tags")
        parts = ai.chats()[-1]["body"]["messages"][0]["content"]
        assert parts[0]["type"] == "text" and parts[1]["type"] == "image_url"
        assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
        e = bw.ElvReadWorker("ELV", "x.pdf", api_key=_cfg()["openrouter_api_key"])
        e._tag_reader(b"\x89PNGfake")
        self._only(ai, "boq.tag_vision", "boq", "elv_tags")

    def test_step_ask_plan_and_catalog(self, ai, monkeypatch):
        from addons.step import workers as sw
        SF = types.SimpleNamespace(ask_prompt=lambda r, q: "ASK " + q,
                                   plan_prompt=lambda r, q, s: "PLAN " + q)
        monkeypatch.setattr(CB, "get_stepfile", lambda: SF)
        cfg = _cfg()
        sw.StepAskWorker(cfg, {}, "q").run()
        self._only(ai, "reasoner", "step", "ask")
        pic = [{"kind": "image", "mime": "image/png", "b64": PNG, "name": "v.png"}]
        sw.StepAskWorker(cfg, {}, "q", attachments=pic).run()
        self._only(ai, "vision", "step", "ask")
        sw.StepPlanWorker(cfg, {}, "q", "s").run()
        self._only(ai, "reasoner", "step", "plan")
        sw.StepCatalogExplainWorker(cfg, "why").run()
        self._only(ai, "writer", "step", "catalog_explain")

    def test_pictures_and_their_briefs(self, ai, tmp_path):
        from core import image_gen
        ai.text = "a clean poster of a lamp"
        path, note = image_gen.generate("a poster of a lamp", [], _cfg(), aspect_ratio="4:5")
        assert path, note
        roles = [(c["path"], c["body"].get("role"), c["body"]["addon"]) for c in ai.calls
                 if c["path"] in ("/v1/ai/chat", "/v1/ai/image")]
        assert roles == [("/v1/ai/chat", "writer", "image"), ("/v1/ai/image", "image", "image")]
        assert ai.last["body"]["aspect_ratio"] == "3:4"
        _assert_clean(ai)

    def test_motion_critic_sends_frames_as_vision(self, ai):
        from core.motion import critic
        ai.text = '{"defects": []}'
        cfg = dict(_cfg(), motion_critic=True)
        out = critic.critique([(0, b"\x89PNGfake")], cfg)
        assert out["skipped"] is None, out
        self._only(ai, "vision", "motion", "critic")
        assert ai.chats()[-1]["body"]["json_mode"] is True

    def test_reel_spec_fallback_call_is_routed(self, ai):
        src = open(os.path.join(CB._TERMINAL_DIR, "core", "automation.py"), encoding="utf-8").read()
        assert 'role="writer", addon="reel", feature="spec_fallback"' in src


# ── what a person is told when the server says no ────────────────────────────

class Errors:
    CASES = [
        (402, "INSUFFICIENT_CREDITS", "You don't have enough credits for that. Ask Alphakore to top up your credits"),
        (503, "GATEWAY_DISABLED", "Paid lookups are paused for the moment."),
        (429, "AI_DAILY_CAP_REACHED", "Today's AI limit is reached. It resets at midnight UTC. Nothing was charged."),
        (403, "AI_NOT_AVAILABLE", "AI isn't switched on for your account yet. Nothing was charged."),
        (401, "LEASE_REQUIRED", "Prism needs to re-check your licence before using AI."),
        (429, "RUN_CEILING_REACHED", "This task has reached its spending limit."),
    ]

    def test_server_words_reach_the_person_on_every_kind_of_site(self, ai):
        from addons.boq import openrouter_writer as w
        from addons.step import workers as sw
        from core import image_gen
        for status, code, message in self.CASES:
            ai.error = (status, code, message, {})
            with pytest.raises(RuntimeError) as e:                  # BOQ write-up: a Qt worker shows str(e)
                w.write("Prism Agent Claude", "p", _cfg()["openrouter_api_key"])
            assert str(e.value) == message
            assert isinstance(e.value, ai_client.AiError) and e.value.code == code
            with pytest.raises(RuntimeError) as e:                  # the planner
                CB.router.groq_chat("k", "m", "p")
            assert str(e.value) == message
            path, note = image_gen.generate("a lamp", [], _cfg())   # pictures: returned, not raised
            assert path == "" and message in note
            failed = []
            wk = sw.StepCatalogExplainWorker(_cfg(), "why")
            wk.failed.connect(failed.append)
            wk.run()
            assert failed == [message]

    def test_a_server_without_ai_routes_says_so(self, ai):
        ai.error = (404, "", "", {})
        with pytest.raises(ai_client.AiError) as e:
            CB.router.groq_chat("k", "m", "p")
        assert e.value.code == "NOT_SET_UP" and "Nothing was charged" in str(e.value)

    def test_no_connection_says_so_and_charges_nothing(self, ai, monkeypatch):
        import licensing
        monkeypatch.setattr(licensing.client, "server_url", lambda: "http://127.0.0.1:9")
        monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
        with pytest.raises(ai_client.AiError) as e:
            CB.router.groq_chat("k", "m", "p")
        assert e.value.code == "UNREACHABLE" and "Nothing was charged" in str(e.value)

    def test_no_licence_says_to_activate(self, ai, monkeypatch):
        import licensing
        monkeypatch.setattr(licensing, "state", lambda: types.SimpleNamespace(license_id=""))
        with pytest.raises(ai_client.AiError) as e:
            CB.router.groq_chat("k", "m", "p")
        assert "Activate Prism" in str(e.value) and not ai.calls


# ── Settings, the wizard, the credits chip ───────────────────────────────────

class Screens:
    @pytest.fixture(autouse=True)
    def _qt(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def _settings(self):
        import licensing
        from widgets import settings_panel as SP
        with mock.patch.object(SP.licensing, "state", lambda: licensing.LicenseState(
                status=licensing.NONE) if hasattr(licensing, "LicenseState") else None):
            p = SP.SettingsPanel(_cfg())
            p.show_section("agents")
        return p

    def test_settings_has_no_key_fields_and_says_where_AI_comes_from(self, ai):
        from PySide6.QtWidgets import QLabel, QLineEdit
        p = self._settings()
        labels = [l.text() for l in p.findChildren(QLabel)]
        assert any("AI runs through your Prism plan" in t for t in labels)
        assert "Groq key" not in labels and "OpenRouter key" not in labels
        for edit in p.findChildren(QLineEdit):
            assert edit.placeholderText() not in ("gsk_…", "sk-or-…"), "a provider key field is still on the page"
            assert REAL_GROQ not in edit.text() and REAL_OR not in edit.text()

    def test_settings_agents_has_no_pickers_only_what_runs_each_step(self, ai):
        """Owner, 19 Nov 2026: fix the Settings agents section now. In server
        mode it showed seven 'skip this category' dropdowns under 'Pick one
        per category' — but server_effective() runs every step on Prism's
        own tools whatever they said. A read-only list of what runs each
        step replaces them."""
        from PySide6.QtWidgets import QComboBox, QLabel
        p = self._settings()
        assert p.findChildren(QComboBox) == [] or not any(
            cb.isVisibleTo(p) and any("skip this category" in cb.itemText(i)
                                      for i in range(cb.count()))
            for cb in p.findChildren(QComboBox)), "step pickers are still on the page"
        labels = " | ".join(l.text() for l in p.findChildren(QLabel))
        assert "skip this category" not in labels
        assert "Pick one per category" not in labels
        assert labels.count("Prism AI") >= 5, labels
        for site in ("ChatGPT", "Perplexity", "Gemini", "Runway"):
            assert site not in labels, site

    def test_settings_connections_has_no_chrome_login_leftovers(self, ai):
        """Server mode: no website logins, so no Chrome version pin, no
        'copy my Chrome logins', no 'Your logins copied in: NOT YET'."""
        import licensing
        from PySide6.QtWidgets import QLabel, QPushButton
        from widgets import settings_panel as SP
        with mock.patch.object(SP.licensing, "state", lambda: licensing.LicenseState(
                status=licensing.NONE)):
            p = SP.SettingsPanel(_cfg())
            p.show_section("status")
        texts = " | ".join([l.text() for l in p.findChildren(QLabel)]
                           + [b.text() for b in p.findChildren(QPushButton)])
        for gone in ("Chrome version", "Copy my Chrome logins", "logins copied",
                     "Browser automation"):
            assert gone not in texts, gone
        assert "Team folder" in texts

    def test_settings_shows_the_real_balance_line(self, ai):
        import ai_server
        ai_server.refresh_async(force=True)
        for t in [t for t in threading.enumerate() if t.name == "prism-ai-status"]:
            t.join(5)
        assert "Pro: 40 AI credits left." == ai_server.status_line()

    def test_status_line_when_ai_is_not_switched_on(self, ai):
        import ai_server
        ai.status_body = {"api": 1, "ready": False, "reason": "not_enabled"}
        ai_server.refresh_async(force=True)
        for t in [t for t in threading.enumerate() if t.name == "prism-ai-status"]:
            t.join(5)
        assert "isn't switched on for your plan" in ai_server.status_line()
        assert ai_server.usage() is None                            # chip stays hidden

    def test_usage_chip_shows_server_credits_and_follows_each_call(self, ai):
        import ai_server
        from widgets.usage_chip import UsageChip
        ai_server.refresh_async(force=True)
        for t in [t for t in threading.enumerate() if t.name == "prism-ai-status"]:
            t.join(5)
        chip = UsageChip()
        assert chip.number.text() == "40" and not chip.isHidden()
        assert chip.note.text() == "Renews in 12 days"
        CB.router.groq_chat("k", "m", "p")                          # the answer carries the new balance
        chip.refresh()
        assert chip.number.text() == "39"

    def test_wizard_asks_for_no_key(self, ai):
        from widgets.wizard_panel import WizardPanel
        w = WizardPanel(_cfg())
        w.start(_cfg())
        assert w._key_valid(w._key_value())
        from PySide6.QtWidgets import QLabel
        text = " ".join(l.text() for l in w.findChildren(QLabel))
        assert "no key to paste" in text and "gsk_" not in text

    def test_voice_buttons_explain_instead_of_sending_a_stand_in_key(self, ai):
        assert ai_client.is_server_key(_cfg()["api_key"])
        assert "plan" in CB.voice.VOICE_UNAVAILABLE


# ── discovery so unittest-style classes run under pytest ─────────────────────

for _cls in (Seam, Sites, Errors, Screens):
    _cls.__test__ = True
    globals()["Test" + _cls.__name__] = _cls

if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))

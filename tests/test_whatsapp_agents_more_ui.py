"""The AI agent screens: draft and published, the business profile and voice, skills, actions, what it knows and the state of each source, settings, trying it, and results.

Driven with a fake worker that answers from the demo platform, so nothing opens a socket, starts a thread or spins an event loop. Rules this file follows: no
processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_agents, demo_platform, readstate, ui  # noqa: E402
from addons.whatsapp.license_client import PlatformError  # noqa: E402


class _Sig:
    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *a):
        for fn in list(self._fns):
            fn(*a)


def _worker(calls, fail=None):
    class W:
        def __init__(self, route, data=None):
            self.route, self.data = route, dict(data or {})
            self.done, self.failed = _Sig(), _Sig()

        def start(self):
            calls.append((self.route, self.data))
            if fail and self.route in fail:
                self.failed.emit(fail[self.route], {})
                return
            try:
                reply = demo_platform.handle(self.route, self.data)
            except PlatformError as e:
                self.failed.emit(str(e), dict(e.detail, reason=e.reason))
            else:
                self.done.emit(reply)
    return W


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="prism-wa-agents-")
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    monkeypatch.setattr(demo_agents.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield
    demo._state.clear()
    demo_platform._PAGE.clear()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def served(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    return calls


def routes(calls):
    return [r for r, _d in calls]


def acts(calls):
    """What was done, leaving out the list of agents the screen refreshes after nearly everything."""
    return [r for r, _d in calls if r != "ai/agents/list"]


def texts(widget) -> str:
    return " | ".join(lab.text() for lab in widget.findChildren(QLabel))


@pytest.fixture
def agents(served):
    from addons.whatsapp import agents_page as AG
    sec = AG.AgentsSection({})
    sec.activate()
    return sec


@pytest.fixture
def editor(agents):
    agents._new()
    return agents.editor


def state():
    from addons.whatsapp import demo_automation
    return demo_automation._auto(demo_platform._state())


def stored(editor):
    return state()["ai"][editor.agent["id"]]


# ── draft and published ──────────────────────────────────────────────────────

def test_a_new_agent_is_a_draft_that_customers_do_not_meet(editor):
    assert editor.live.text() == "Draft — not live yet" and editor.agent["status"] == "draft"
    assert editor.publish_btn.text() == "Publish" and editor.publish_btn.isEnabled() and editor.pause_btn.isHidden()


def test_switching_an_agent_on_for_the_first_time_publishes_it(editor):
    editor.on.setChecked(True)
    assert editor.live.text() == "Live · v1" and editor.agent["status"] == "published" and stored(editor)["published_version"] == 1
    assert editor.publish_btn.text() == "Publish changes" and not editor.publish_btn.isEnabled() and not editor.pause_btn.isHidden()


def test_an_edit_waits_to_be_published_and_says_so(editor):
    editor.on.setChecked(True)
    editor.profile.business.setText("Shakti Builders")
    assert editor.live.text() == "Live · v1 · unpublished changes" and editor.publish_btn.isEnabled() and editor.dirty and editor._timer.isActive()
    assert editor.saved.text() == "Unsaved changes…"


def test_publishing_saves_first_then_publishes_and_names_the_version(editor, calls):
    editor.on.setChecked(True)
    editor.profile.business.setText("Shakti Builders")
    del calls[:]
    editor.publish()
    assert acts(calls) == ["ai/agents/update", "ai/agents/publish"]
    assert editor.live.text() == "Live · v2" and "Published as version 2" in editor.note.text() and not editor.dirty
    assert stored(editor)["live"]["profile"]["business_name"] == "Shakti Builders"


def test_publishing_says_what_is_missing_without_refusing(editor):
    editor.publish()
    assert editor.live.text() == "Live · v1" and "has not been told" in editor.note.text()


def test_pausing_takes_the_agent_down_and_publishing_brings_it_back(editor):
    editor.on.setChecked(True)
    editor.pause()
    assert editor.live.text() == "Paused" and editor.pause_btn.isHidden() and editor.publish_btn.text() == "Publish" and editor.publish_btn.isEnabled()
    assert "no AI answers" in editor.note.text()
    editor.publish()
    assert editor.live.text() == "Live · v2"


def test_a_failed_publish_says_why_and_leaves_the_button_usable(served, monkeypatch):
    from addons.whatsapp import agents_page as AG
    monkeypatch.setattr(ui, "PlatformWorker", _worker(served, fail={"ai/agents/publish": "AI agents are part of the Premium plan."}))
    sec = AG.AgentsSection({})
    sec.activate()
    sec._new()
    ed = sec.editor
    ed.publish()
    assert "Premium plan" in ed.note.text() and ed.publish_btn.isEnabled()


# ── saving ───────────────────────────────────────────────────────────────────

def test_an_edit_saves_itself_after_a_moment_and_only_changed_agents_go_to_the_server(editor, calls):
    editor.name.setText("Aria")
    assert editor._timer.isActive() and "ai/agents/update" not in routes(calls)
    editor._timer.timeout.emit()
    assert acts(calls)[-1] == "ai/agents/update" and editor.saved.text() == "Saved." and not editor.dirty and stored(editor)["name"] == "Aria"


def test_there_is_no_save_when_nothing_changed_and_something_waits_for_the_save_otherwise(editor, calls):
    ran = []
    editor.ensure_saved(lambda: ran.append("now"))
    assert ran == ["now"] and "ai/agents/update" not in routes(calls)
    editor.name.setText("Aria")
    editor.ensure_saved(lambda: ran.append("after"))
    assert ran == ["now", "after"] and acts(calls)[-1] == "ai/agents/update"


def test_a_change_made_while_saving_is_saved_again(editor, calls):
    editor._saving = True
    editor.save()
    assert editor._again is True
    editor._saving = False
    editor._again = False
    editor.name.setText("Aria")
    editor.save()
    editor.name.setText("Aria 2")
    editor.save()
    assert [d["changes"]["name"] for r, d in calls if r == "ai/agents/update"][-2:] == ["Aria", "Aria 2"]


def test_a_failed_save_keeps_the_edit_and_says_why(served, monkeypatch):
    from addons.whatsapp import agents_page as AG
    sec = AG.AgentsSection({})
    sec.activate()
    sec._new()
    ed = sec.editor
    monkeypatch.setattr(ui, "PlatformWorker", _worker(served, fail={"ai/agents/update": "Tone is one of: friendly."}))
    ed.name.setText("Aria")
    ed.save(then=lambda: served.append(("then-ran", {})))
    assert "Tone is one of" in ed.saved.text() and ed.dirty and ("then-ran", {}) not in served


# ── the business and the voice ───────────────────────────────────────────────

def test_the_business_and_voice_are_written_into_the_draft(editor):
    p = editor.profile
    p.business.setText(" Shakti Builders ")
    p.website.setText("https://shakti.example")
    p.description.setPlainText("We build boundary walls.")
    p.greeting.setText("Namaste!")
    p.rules.setPlainText("Never promise a date\n\nNo discounts")
    p.instructions.setPlainText("Do not discuss rivals.")
    p.tone.setCurrentIndex(p.tone.findData("empathetic"))
    p.tone.activated.emit(p.tone.currentIndex())
    p.length.setCurrentIndex(p.length.findData("detailed"))
    p.length.activated.emit(p.length.currentIndex())
    p.language.setCurrentIndex(p.language.findData("gujarati"))
    p.language.activated.emit(p.language.currentIndex())
    d = editor.draft
    assert d["profile"] == {"business_name": "Shakti Builders", "website": "https://shakti.example", "description": "We build boundary walls.", "greeting": "Namaste!",
                            "ground_rules": ["Never promise a date", "No discounts"]}
    assert d["voice"] == {"tone": "empathetic", "length": "detailed", "language": "gujarati"} and d["instructions"] == "Do not discuss rivals."


def test_ground_rules_stop_at_ten(editor):
    editor.profile.rules.setPlainText("\n".join("rule %d" % i for i in range(14)))
    assert len(editor.draft["profile"]["ground_rules"]) == 10


def test_filling_the_business_from_its_website_drafts_it_and_changes_nothing_else(editor, calls):
    p = editor.profile
    p.website.setText("https://shakti-builders.example/about")
    p.greeting.setText("My own hello")
    p.fill_from_website()
    assert routes(calls)[-1] == "ai/agents/draft_profile" and p.draft_btn.isEnabled()
    assert p.business.text() == "Shakti Builders" and "Gujarat" in p.description.toPlainText() and "Never promise a date" in p.rules.toPlainText()
    assert p.greeting.text().startswith("Namaste! Welcome to Shakti Builders") and "Drafted from your website" in p.profile_note.text()
    assert editor.draft["profile"]["business_name"] == "Shakti Builders"


def test_filling_from_a_website_needs_a_secure_address(editor, calls):
    editor.profile.website.setText("shakti.example")
    editor.profile.fill_from_website()
    assert "starting with https://" in editor.profile.profile_note.text() and "ai/agents/draft_profile" not in routes(calls)


def test_a_website_that_cannot_be_read_is_explained(served, monkeypatch):
    from addons.whatsapp import agents_page as AG
    sec = AG.AgentsSection({})
    sec.activate()
    sec._new()
    monkeypatch.setattr(ui, "PlatformWorker", _worker(served, fail={"ai/agents/draft_profile": "That page answered with an error (404)."}))
    sec.editor.profile.website.setText("https://nope.example")
    sec.editor.profile.fill_from_website()
    assert "error (404)" in sec.editor.profile.profile_note.text() and sec.editor.profile.draft_btn.isEnabled()


def test_the_default_box_still_takes_effect_at_once(editor, calls):
    editor.on.setChecked(True)
    editor.default.setChecked(True)
    assert acts(calls)[-1] == "ai/agents/set_default" and editor.agent["is_default"] and stored(editor)["is_default"]


# ── skills ───────────────────────────────────────────────────────────────────

def test_every_kind_of_skill_starts_with_words_the_owner_can_change():
    from addons.whatsapp import agent_skills as SK
    for kind, name, _hint in SK.kinds():
        s = SK.preset(kind)
        assert s["kind"] == kind and s["name"] == name and s["enabled"] is True
    assert [v["name"] for v in SK.preset("lead")["variables"]] == ["name", "city", "requirement", "budget"]
    assert SK.preset("lead")["on_complete"]["tag"] == "qualified-lead" and SK.preset("faq")["variables"] == []


def test_adding_a_skill_from_a_ready_made_one_keeps_it_in_the_draft_and_saves(editor, calls):
    from addons.whatsapp import agent_skills as SK
    with mock.patch.object(SK.SkillDialog, "exec", return_value=1):
        editor.skills.add("booking")
    s = editor.draft["skills"][0]
    assert s["name"] == "Book an appointment" and [v["name"] for v in s["variables"]] == ["name", "day", "time"] and editor._timer.isActive()
    assert "Collects: Name, Preferred day, Preferred time" in texts(editor.skills)
    editor._timer.timeout.emit()
    assert [x["id"] for x in stored(editor)["skills"]] == ["book_an_appointment"]


def test_cancelling_the_skill_window_adds_nothing(editor):
    from addons.whatsapp import agent_skills as SK
    with mock.patch.object(SK.SkillDialog, "exec", return_value=0):
        editor.skills.add("lead")
    assert editor.draft["skills"] == []


def test_the_skill_window_gives_back_what_was_typed(editor):
    from addons.whatsapp import agent_skills as SK
    d = SK.SkillDialog(SK.preset("lead"), new=True)
    d.name.setText("Take a quote request")
    d.when.setText("they ask for a price")
    d.rows[0]["attribute"].setText("Full name!")
    d.rows[3]["required"].setChecked(True)
    d.tag.setText("hot-lead")
    d.handoff.setChecked(True)
    d.reason.setText("ready")
    v = d.value()
    assert v["name"] == "Take a quote request" and v["when"] == "they ask for a price"
    assert v["variables"][0] == {"name": "name", "label": "Name", "description": "", "required": True, "attribute": "Full_name"}
    assert v["variables"][3]["required"] is True and v["on_complete"] == {"tag": "hot-lead", "handoff": True, "reason": "ready"}


def test_details_can_be_added_removed_and_are_limited_to_eight(editor):
    from addons.whatsapp import agent_skills as SK
    d = SK.SkillDialog(SK.preset("faq"), new=True)
    for _ in range(12):
        d.add_detail({"label": "Thing"})
    assert len(d.rows) == 8 and d.add_btn.isHidden()
    names = [x["name"] for x in d.value()["variables"]]
    assert len(names) == len(set(names)) == 8                                   # two details with the same label still get their own names
    d._remove(d.rows[0])
    assert len(d.rows) == 7 and not d.add_btn.isHidden()


def test_a_skill_without_a_name_is_not_saved(editor):
    from addons.whatsapp import agent_skills as SK
    d = SK.SkillDialog(SK.preset("faq"), new=True)
    d.name.setText("")
    d._go()
    assert "Give the skill a name" in d.error.text()


def test_a_hand_over_note_is_only_for_a_skill_that_hands_over(editor):
    from addons.whatsapp import agent_skills as SK
    d = SK.SkillDialog(SK.preset("faq"), new=True)
    assert not d.reason.isEnabled()
    d.handoff.setChecked(True)
    assert d.reason.isEnabled()


def test_a_skill_is_switched_off_changed_and_deleted_from_the_list(editor):
    from PySide6.QtWidgets import QMessageBox
    from addons.whatsapp import agent_skills as SK
    editor.skills.add("faq", dialog=False)
    editor.skills.add("lead", dialog=False)
    switch = next(w for w in editor.skills.findChildren(type(editor.on)))
    switch.setChecked(False)
    assert editor.draft["skills"][0]["enabled"] is False
    with mock.patch.object(SK.SkillDialog, "exec", return_value=1), mock.patch.object(SK.SkillDialog, "value", lambda self: {**self.skill, "name": "Renamed"}):
        editor.skills.change(editor.draft["skills"][1])
    assert editor.draft["skills"][1]["name"] == "Renamed"
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        editor.skills.remove(editor.draft["skills"][0])
    assert len(editor.draft["skills"]) == 2
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        editor.skills.remove(editor.draft["skills"][0])
    assert len(editor.draft["skills"]) == 1 and "Renamed" in texts(editor.skills)


def test_no_more_than_twelve_skills(editor):
    for _ in range(14):
        editor.skills.add("faq", dialog=False)
    assert len(editor.draft["skills"]) == 14                                    # the screen stops offering at 12; the server is what refuses
    assert editor.skills.add_btn.isHidden()


def test_the_server_refuses_a_skill_with_a_bad_detail_and_the_screen_says_so(editor):
    editor.draft["skills"] = [{"name": "Bad", "kind": "custom", "variables": [{"name": "City!"}]}]
    editor.save()
    assert "short name" in editor.saved.text() and editor.dirty


# ── actions ──────────────────────────────────────────────────────────────────

def action(**kw):
    return {"name": "Order status", "description": "Look up an order", "method": "GET", "url": "https://shop.example/orders/{{order}}",
            "headers": {"Authorization": "Bearer abc123456"}, "body": "", "parameters": [{"name": "order", "description": "", "required": True}], "response_path": "order.status",
            "enabled": True, **kw}


def test_the_details_an_address_needs_are_found_in_it():
    from addons.whatsapp import agent_actions as AC
    assert AC.details_in("https://x.example/{{order}}?c={{mobile}}&n={{name}}", '{"day": "{{ day }}", "order": "{{order}}"}') == ["order", "day"]
    assert AC.lines_to_headers("Authorization: Bearer a:b\nbad line\nX-Id: 7") == {"Authorization": "Bearer a:b", "X-Id": "7"}


def test_the_action_window_finds_the_details_and_gives_back_what_was_typed(editor):
    from addons.whatsapp import agent_actions as AC
    d = AC.ActionDialog(action(parameters=[]), new=True)
    d.find_params()
    assert [e["name"].text() for e in d.params] == ["order"]
    d.find_params()
    assert len(d.params) == 1
    d.method.setCurrentText("POST")
    d.headers.setPlainText("X-Key: k1")
    v = d.value()
    assert v["method"] == "POST" and v["headers"] == {"X-Key": "k1"} and v["parameters"] == [{"name": "order", "description": "", "required": True}]


def test_the_action_window_asks_for_a_value_per_detail_and_tries_the_call(editor, calls):
    from addons.whatsapp import agent_actions as AC
    d = AC.ActionDialog(action(), agent_id=editor.agent["id"])
    assert list(d.try_values) == ["order"]
    d.try_values["order"].setText("A17")
    d.try_it()
    assert routes(calls)[-1] == "ai/actions/test" and calls[-1][1]["args"] == {"order": "A17"} and calls[-1][1]["agent_id"] == editor.agent["id"]
    assert "It answered 200" in d.result.text() and "Packed" in d.result.text() and d.try_btn.isEnabled()


def test_trying_a_call_without_a_needed_detail_or_to_a_private_address_says_why(editor):
    from addons.whatsapp import agent_actions as AC
    d = AC.ActionDialog(action(), agent_id=editor.agent["id"])
    d.try_it()
    assert "missing: order" in d.result.text()
    d.url.setText("https://localhost/x")
    d.try_values["order"].setText("1")
    d.try_it()
    assert "cannot be called" in d.result.text()


def test_the_action_window_wants_a_name_a_purpose_and_a_secure_address(editor):
    from addons.whatsapp import agent_actions as AC
    d = AC.ActionDialog(action(name="", description=""), new=True)
    d._go()
    assert "name" in d.error.text().lower()
    d.name.setText("Stock")
    d.description.setText("Check stock")
    d.url.setText("http://insecure.example")
    d._go()
    assert "https://" in d.error.text()


def test_an_action_is_added_changed_switched_off_and_deleted(editor):
    from addons.whatsapp import agent_actions as AC
    with mock.patch.object(AC.ActionDialog, "exec", return_value=1), mock.patch.object(AC.ActionDialog, "value", lambda self: action()):
        editor.actions.add()
    assert editor.draft["actions"][0]["name"] == "Order status" and "Look up an order" in texts(editor.actions)
    switch = next(w for w in editor.actions.findChildren(type(editor.on)))
    switch.setChecked(False)
    assert editor.draft["actions"][0]["enabled"] is False
    with mock.patch.object(AC.ActionDialog, "exec", return_value=1), mock.patch.object(AC.ActionDialog, "value", lambda self: action(name="Where is it")):
        editor.actions.change(editor.draft["actions"][0])
    assert editor.draft["actions"][0]["name"] == "Where is it"
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        editor.actions.remove(editor.draft["actions"][0])
    assert editor.draft["actions"] == []


def test_an_action_that_changes_something_says_it_is_not_run_in_a_test(editor):
    editor.draft["actions"] = [action(method="POST")]
    editor.actions.render()
    assert "not run when you try the agent out" in texts(editor.actions)
    editor.draft["actions"] = [action()]
    editor.actions.render()
    assert "not run when you try" not in texts(editor.actions)


def test_a_header_secret_comes_back_hidden_and_is_kept_when_the_agent_is_saved_again(agents):
    agents._new()
    ed = agents.editor
    ed.draft["actions"] = [action()]
    ed.draft["settings"]["handoff_webhook"] = {"url": "https://crm.example/h", "headers": {"X-Key": "secret-key-9"}}
    ed.save()
    agents.open_agent(ed.agent["id"])
    shown = agents.editor
    assert shown.draft["actions"][0]["headers"]["Authorization"] == "Bea••••" and shown.draft["settings"]["handoff_webhook"]["headers"]["X-Key"] == "sec••••"
    shown.name.setText("Aria")
    shown.save()
    kept = stored(shown)
    assert kept["actions"][0]["headers"]["Authorization"] == "Bearer abc123456" and kept["settings"]["handoff_webhook"]["headers"]["X-Key"] == "secret-key-9"


# ── what it knows ────────────────────────────────────────────────────────────

def test_a_website_shows_as_being_read_then_ready_and_the_list_checks_again_until_it_is(editor, calls):
    from addons.whatsapp import agent_knowledge as KN
    d = KN.KnowledgeDialog(editor.agent["id"], "site")
    d.url.setText("https://shakti.example")
    d.pages.setValue(4)
    d._go()
    assert calls[-1][0] == "ai/knowledge/add_site" and calls[-1][1]["max_pages"] == 4
    editor.knowledge.load()
    assert "Reading…" in texts(editor.knowledge) and editor.knowledge.timer.isActive()
    editor.knowledge.load()                                                      # what the timer does
    assert "Reading…" not in texts(editor.knowledge) and not editor.knowledge.timer.isActive()
    assert "About us" in texts(editor.knowledge) and "Services" in texts(editor.knowledge) and texts(editor.knowledge).count("Ready") >= 3


def test_a_site_needs_a_secure_address(editor):
    from addons.whatsapp import agent_knowledge as KN
    d = KN.KnowledgeDialog(editor.agent["id"], "site")
    d.url.setText("http://insecure.example")
    d._go()
    assert "https://" in d.error.text() and d.go.isEnabled()


def test_a_page_can_be_read_again_and_only_a_page(editor, calls):
    from addons.whatsapp import agent_knowledge as KN
    u = KN.KnowledgeDialog(editor.agent["id"], "url")
    u.url.setText("https://shakti.example/contact")
    u._go()
    t = KN.KnowledgeDialog(editor.agent["id"], "text")
    t.title.setText("Hours")
    t.text.setPlainText("Open at ten.")
    t._go()
    editor.knowledge.load()
    again = [b for b in editor.knowledge.findChildren(QPushButton) if b.text() == "Read again"]
    assert len(again) == 1                                                       # the text note has none
    again[0].click()
    assert routes(calls)[-2] == "ai/knowledge/refresh" and "Reading…" in texts(editor.knowledge) and editor.knowledge.timer.isActive()


def test_a_source_that_failed_shows_why_and_one_found_by_meaning_says_so(editor):
    editor.knowledge._loaded({"knowledge": [
        {"id": "k1", "title": "Contact", "kind": "url", "source": "https://x.example/c", "characters": 400, "status": "failed", "error": "That page answered with an error (404).", "chunks": 1, "embedded": 0},
        {"id": "k2", "title": "Returns", "kind": "faq", "characters": 120, "status": "ready", "chunks": 2, "embedded": 2},
        {"id": "k3", "title": "Hours", "kind": "text", "characters": 90, "status": "ready", "chunks": 1, "embedded": 0}]})
    t = texts(editor.knowledge)
    assert "Couldn't read" in t and t.count("Found by meaning") == 1 and "https://x.example/c" in t and not editor.knowledge.timer.isActive()
    pill = next(p for p in editor.knowledge.findChildren(QLabel) if p.text() == "Couldn't read")
    assert "error (404)" in pill.toolTip()


def test_forgetting_a_note_asks_first_and_the_old_names_still_work(editor, calls):
    from addons.whatsapp import agent_knowledge as KN
    t = KN.KnowledgeDialog(editor.agent["id"], "text")
    t.title.setText("Old")
    t.text.setPlainText("Outdated information here.")
    t._go()
    editor.load_knowledge()
    doc = editor.knowledge.docs[0]
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        editor._forget(doc)
    assert "ai/knowledge/delete" not in routes(calls)
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        editor._forget(doc)
    assert "It has not been taught anything yet." in texts(editor.knowledge)


# ── settings ─────────────────────────────────────────────────────────────────

def test_the_settings_are_written_into_the_draft(editor):
    s = editor.settings
    s.fallback.setPlainText("Sorry, a person will help.")
    s.handoff_message.setPlainText("One moment.")
    s.hook_url.setText("https://crm.example/handover")
    s.hook_headers.setPlainText("X-Key: k1")
    s.tests[0].setText("+91 98765 43210")
    s.tests[1].setText("919800000001")
    d = editor.draft["settings"]
    assert d["fallback_text"] == "Sorry, a person will help." and d["handoff_message"] == "One moment."
    assert d["handoff_webhook"] == {"url": "https://crm.example/handover", "headers": {"X-Key": "k1"}} and d["test_numbers"] == ["919876543210", "919800000001"]
    s.hook_url.setText("")
    assert editor.draft["settings"]["handoff_webhook"] is None


def test_a_test_number_that_is_not_a_phone_number_is_flagged(editor):
    editor.settings.tests[0].setText("123")
    assert "country code" in editor.settings.tests_note.text()
    editor.settings.tests[0].setText("919876543210")
    assert editor.settings.tests_note.text() == ""


def test_the_numbers_it_may_answer_on_are_chosen_from_the_workspaces_numbers(editor, calls):
    assert "numbers/list" in routes(calls)
    boxes = editor.settings.numbers_boxes
    assert boxes and not any(b.isChecked() for b in boxes.values())
    first = next(iter(boxes))
    boxes[first].setChecked(True)
    assert editor.draft["settings"]["numbers"] == [first]
    boxes[first].setChecked(False)
    assert editor.draft["settings"]["numbers"] == []


def test_the_saved_settings_survive_reopening(agents):
    agents._new()
    ed = agents.editor
    ed.settings.fallback.setPlainText("Sorry.")
    ed.settings.tests[0].setText("919876543210")
    ed.save()
    agents.open_agent(ed.agent["id"])
    again = agents.editor
    assert again.settings.fallback.toPlainText() == "Sorry." and again.settings.tests[0].text() == "919876543210"


# ── trying it ────────────────────────────────────────────────────────────────

def test_trying_says_it_is_the_draft_and_what_customers_meet(editor):
    assert "Customers meet nothing yet" in editor.train.banner.text() and "Add test numbers in Settings" in editor.train.banner.text()
    editor.on.setChecked(True)
    editor.settings.tests[0].setText("919876543210")
    editor.train.refresh_banner()
    assert "version 1" in editor.train.banner.text() and "1 test numbers" in editor.train.banner.text()
    editor.pause()
    assert "paused" in editor.train.banner.text()


def test_trying_saves_the_draft_first_so_the_agent_answers_from_what_is_on_screen(editor, calls):
    editor.profile.instructions.setPlainText("We build walls.")
    del calls[:]
    editor.train.edit.setText("hello")
    editor.train._send()
    assert acts(calls)[:2] == ["ai/agents/update", "ai/test"]


def test_trying_shows_the_details_it_would_keep_and_what_it_would_call(editor):
    editor.draft["skills"] = [{"name": "Quote", "kind": "lead", "variables": [{"name": "city", "label": "City", "required": True, "attribute": "City"}]}]
    editor.draft["actions"] = [action()]
    editor.edited()
    from addons.whatsapp import agent_knowledge as KN
    f = KN.KnowledgeDialog(editor.agent["id"], "faq")
    f.title.setText("Do you build in Surat?")
    f.answer.setPlainText("Yes, we build in Surat.")
    f._go()
    editor.train.edit.setText("do you build in Surat")
    editor.train._send()
    t = texts(editor.train)
    assert "Yes, we build in Surat." in t and "It would keep: city = Surat" in t
    editor.train.edit.setText("where is my order")
    editor.train._send()
    assert "It called “Order status”." in texts(editor.train)


def test_an_action_that_changes_something_is_shown_as_not_run_when_trying(editor):
    editor.draft["actions"] = [action(method="POST", name="Book a visit", description="Book a visit slot")]
    editor.edited()
    editor.train.edit.setText("book a visit")
    editor.train._send()
    assert "It would call “Book a visit” (not run here)." in texts(editor.train)


# ── results ──────────────────────────────────────────────────────────────────

def test_the_results_are_asked_for_only_when_the_tab_is_opened_and_say_what_they_mean(editor, calls):
    editor.on.setChecked(True)
    assert "ai/analytics" not in routes(calls)
    editor.show_section("results")
    assert routes(calls)[-1] == "ai/analytics" and editor.stack.currentIndex() == editor._keys.index("results")
    r = editor.results
    assert r.k_replies.value.text() != "—" and "%" in r.k_settled.value.text() and "does not say the customer was happy" in r.explain.text()
    assert "not in the knowledge" in texts(r) and r.chart._days


def test_results_for_an_agent_nobody_has_talked_to_say_so(editor):
    editor.show_section("results")
    assert "No customer has chatted" in editor.results.explain.text() and "None in this time." in texts(editor.results)


def test_a_slow_answer_for_an_old_range_is_ignored(editor):
    r = editor.results
    r._token = 5
    r._shown(4, {"totals": {"replies": 99}, "days": [], "reasons": [], "gaps": []})
    assert r.k_replies.value.text() == "—"


def test_the_questions_it_could_not_answer_are_listed_most_asked_first(editor):
    demo_agents.seed_gaps(state(), editor.agent["id"], [("what is the price per sqft", 7), ("do you do solar", 2)])
    editor.show_section("results")
    t = texts(editor.results)
    assert t.index("what is the price per sqft") < t.index("do you do solar") and "Asked 7 times" in t


def test_teaching_the_answer_to_a_question_adds_a_note_and_clears_the_question(editor, calls):
    from addons.whatsapp import agent_results as AR
    demo_agents.seed_gaps(state(), editor.agent["id"], [("do you deliver to Surat", 3)])
    editor.show_section("results")
    gap = editor.results.gaps[0]
    def write_and_accept(self):
        self.answer.setPlainText("Yes, within three hundred kilometres.")
        return 1
    with mock.patch.object(AR.TeachDialog, "exec", write_and_accept):
        editor.results.teach(gap)
    assert "ai/gaps/answer" in routes(calls)
    assert "Nothing right now" in texts(editor.results) and "Learned" in editor.results.gaps_note.text()
    assert "do you deliver to Surat" in texts(editor.knowledge)


def test_the_teach_window_wants_an_answer():
    from addons.whatsapp import agent_results as AR
    d = AR.TeachDialog("What is the price?")
    d._go()
    assert "Write the answer first" in d.error.text()
    d.answer.setPlainText("Rs 1,800 per sq ft.")
    d.accept = lambda: setattr(d, "accepted_", True)
    d._go()
    assert getattr(d, "accepted_", False)


def test_a_question_can_be_ignored(editor):
    demo_agents.seed_gaps(state(), editor.agent["id"], [("what is your wifi password", 1)])
    editor.show_section("results")
    editor.results.ignore(editor.results.gaps[0])
    assert "Nothing right now" in texts(editor.results)


def test_the_allowance_is_shown_in_results(editor):
    assert "0 of 1000 AI replies used this month." in editor.usage_text.text()
    editor.show_usage({"replies": 0, "limit": 1000, "configured": False})
    assert "not switched on for this server" in editor.usage_text.text()


# ── the list of agents ───────────────────────────────────────────────────────

def test_the_list_shows_a_draft_a_paused_agent_and_how_many_questions_wait(agents):
    agents._new()
    ed = agents.editor
    ed.on.setChecked(True)
    ed.pause()
    demo_agents.seed_gaps(state(), ed.agent["id"], [("a", 1), ("b", 1)])
    agents.refresh_list()
    t = texts(agents)
    assert "Paused" in t and "2 questions it could not answer" in t


# ── the demo platform's rules ────────────────────────────────────────────────

@pytest.mark.parametrize("field,value,fragment", [
    ("voice", {"tone": "angry"}, "Tone is one of"), ("voice", {"length": "novel"}, "Answer length is one of"), ("profile", {"website": "http://x.example"}, "https://"),
    ("skills", [{"name": "A", "kind": "dancing"}], "A skill is one of"), ("skills", [{"name": "A", "variables": [{"name": "City!"}]}], "short name"),
    ("actions", [{"name": "A", "description": "d", "url": "http://x.example"}], "https://"), ("actions", [{"name": "A", "description": "d", "url": "https://x.example", "method": "PUT"}], "GET or POST"),
    ("settings", {"test_numbers": ["1", "2", "3", "4"]}, "Up to 3 test numbers"),
])
def test_the_demo_refuses_what_the_server_refuses_in_the_same_words(editor, field, value, fragment):
    with pytest.raises(PlatformError) as why:
        demo_platform.handle("ai/agents/update", {"agent_id": editor.agent["id"], "changes": {field: value}})
    assert fragment in str(why.value)


def test_the_demo_keeps_a_draft_apart_from_what_is_live(editor):
    aid = editor.agent["id"]
    demo_platform.handle("ai/agents/set_enabled", {"agent_id": aid, "enabled": True})
    demo_platform.handle("ai/agents/update", {"agent_id": aid, "changes": {"instructions": "Draft words."}})
    got = demo_platform.handle("ai/agents/get", {"agent_id": aid})["agent"]
    assert got["status"] == "published" and got["unpublished_changes"] is True and "live" not in got
    assert demo_platform.handle("ai/agents/publish", {"agent_id": aid})["version"] == 2
    assert demo_platform.handle("ai/agents/get", {"agent_id": aid})["agent"]["unpublished_changes"] is False


def test_try_it_bubbles_are_as_tall_as_their_words_however_tall_the_tab_is():
    # In a tab taller than its content the spare height went into the chat, so "hey" was drawn as a 280px-tall black pill.
    from PySide6.QtWidgets import QVBoxLayout, QWidget
    from addons.whatsapp.agent_train import TrainPanel

    class _Editor:
        agent = {"status": "published", "published_version": 6}
        draft = {"settings": {}}

    host = QWidget()
    QVBoxLayout(host).addWidget(TrainPanel(_Editor()))
    panel = host.layout().itemAt(0).widget()
    panel._bubble("customer", "hey")
    panel._bubble("bot", "Hi there! Welcome to Alpha.Kore. We are excited to help turn your ideas into real solutions.")
    host.resize(1000, 800)
    host.show()
    host.layout().activate()
    panel.layout().activate()
    from PySide6.QtWidgets import QLabel
    bubbles = [l for l in panel.findChildren(QLabel) if l.text() in ("hey",) or l.text().startswith("Hi there")]
    assert len(bubbles) == 2
    for lab in bubbles:
        assert lab.height() <= lab.heightForWidth(lab.width()) + 4, (lab.text(), lab.height())

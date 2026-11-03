"""The WhatsApp platform screens — Templates, the template editor, Campaigns, contact import.

Driven with a fake worker that answers from the demo platform (the same shapes the real service
returns), so nothing here opens a socket, starts a thread, or spins an event loop. The rules this
file follows: no processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QLabel, QMessageBox, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_platform, readstate, ui  # noqa: E402
from addons.whatsapp.license_client import PlatformError  # noqa: E402


class _Sig:
    def __init__(self):
        self._fns = []

    def connect(self, fn):
        self._fns.append(fn)

    def emit(self, *a):
        for fn in list(self._fns):
            fn(*a)


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="prism-wa-ui-")
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield tmp
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()


@pytest.fixture
def calls():
    """Every platform call made, as (route, data). Patched into each screen by its fixture."""
    return []


def _worker(calls: list, fail: dict = None):
    """A worker that answers from the demo platform. `fail` maps a route to the message it should fail with."""
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


def routes(calls: list) -> list:
    """The routes called, in order. The per-template numbers (templates/stats) are a bonus call beside every load of the list, so they are
    left out: these tests are about what the list, sync and delete do."""
    return [r for r, _d in calls if r != "templates/stats"]


def labels_of(widget) -> str:
    return " | ".join(lab.text() for lab in widget.findChildren(QLabel))


# ── the pure pieces ──────────────────────────────────────────────────────────

def test_variables_are_found_in_order_and_once():
    from addons.whatsapp.template_editor import variables_of
    assert variables_of("Hi {{1}}, {{ 2 }} and {{1}} again") == [1, 2]
    assert variables_of("no blanks") == []
    assert variables_of("") == []


def test_components_carry_samples_only_for_the_variables_used():
    from addons.whatsapp.template_editor import components_from
    comps = components_from("Offer", "Hello {{1}}, {{2}} ends soon.", "Reply STOP to opt out", ["Yes", "", "No"],
                            {1: "Asha", 2: "Friday", 3: "unused"})
    assert [c["type"] for c in comps] == ["HEADER", "BODY", "FOOTER", "BUTTONS"]
    assert comps[1]["example"] == {"body_text": [["Asha", "Friday"]]}
    assert [b["text"] for b in comps[3]["buttons"]] == ["Yes", "No"]


def test_a_blank_sample_is_left_out_so_it_is_reported_not_sent():
    from addons.whatsapp.template_editor import components_from
    comps = components_from("", "Hello {{1}}, {{2}} ends soon.", "", [], {1: "Asha", 2: "   "})
    assert comps[0]["example"] == {"body_text": [["Asha"]]}


def test_a_body_with_no_variables_has_no_example_block():
    from addons.whatsapp.template_editor import components_from
    assert components_from("", "Thanks for visiting us today.", "", [], {}) == [{"type": "BODY", "text": "Thanks for visiting us today."}]


def test_website_and_phone_buttons_are_built_the_way_meta_wants():
    from addons.whatsapp.template_editor import components_from
    comps = components_from("", "Thanks for visiting us today.", "", [
        ("URL", "See offer", "https://shop.in/offer"), ("URL", "Track", "https://shop.in/t/{{1}}"),
        ("PHONE_NUMBER", "Call us", "+919876543210")], {})
    b = comps[1]["buttons"]
    assert b[0] == {"type": "URL", "text": "See offer", "url": "https://shop.in/offer"}
    assert b[1]["example"] == ["https://shop.in/t/sample"]
    assert b[2] == {"type": "PHONE_NUMBER", "text": "Call us", "phone_number": "+919876543210"}


def test_a_header_variable_carries_its_own_sample():
    from addons.whatsapp.template_editor import components_from
    comps = components_from("Offer for {{1}}", "Thanks for visiting us today.", "", [], {}, header_sample="Asha")
    assert comps[0]["example"] == {"header_text": ["Asha"]}


def test_a_template_on_file_fills_the_form_fields_back_in():
    from addons.whatsapp.template_editor import components_from, fields_from
    comps = components_from("Offer", "Hello {{1}}, see you on {{2}} then.", "Bye", [("URL", "Go", "https://x.in"), ("PHONE_NUMBER", "Call", "+911234567890")],
                            {1: "Asha", 2: "Friday"})
    f = fields_from(comps)
    assert f["header"] == "Offer" and f["body"].startswith("Hello") and f["footer"] == "Bye"
    assert f["samples"] == {1: "Asha", 2: "Friday"}
    assert f["buttons"] == [("URL", "Go", "https://x.in"), ("PHONE_NUMBER", "Call", "+911234567890")]


def test_the_preview_text_shows_each_sample_or_leaves_the_blank_visible():
    from addons.whatsapp.template_editor import filled
    assert filled("Hi {{1}}, on {{2}}.", {1: "Asha"}) == "Hi Asha, on {{2}}."
    assert filled("Hi {{1}}", {1: "  "}) == "Hi {{1}}"


def test_a_blank_maps_to_the_shape_the_server_wants():
    from addons.whatsapp.campaigns_page import variable_spec
    assert variable_spec("first_name", "") == {"source": "field", "field": "first_name"}
    assert variable_spec("mobile", "x") == {"source": "field", "field": "mobile"}
    assert variable_spec("attribute", " City ") == {"source": "attribute", "key": "City"}
    assert variable_spec("static", " Diwali ") == {"source": "static", "value": "Diwali"}
    assert variable_spec("tracked_link", "https://x.in") == {"source": "tracked_link", "target": "https://x.in"}


def test_a_template_lists_everything_the_sender_must_supply():
    from addons.whatsapp.campaigns_page import template_blanks
    t = {"components": [
        {"type": "HEADER", "format": "IMAGE"},
        {"type": "BODY", "text": "Hi {{1}}, see {{2}} today and tomorrow for you."},
        {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Yes"},
                                        {"type": "URL", "text": "Track", "url": "https://x.in/t/{{1}}"}]}]}
    assert template_blanks(t) == [("1", "{{1}}", "text"), ("2", "{{2}}", "text"), ("header", "Header image", "link"), ("101", "Button 2", "text")]
    assert template_blanks({}) == []


def test_the_preview_uses_believable_stand_ins():
    from addons.whatsapp.campaigns_page import sample_for
    assert sample_for({"source": "field", "field": "first_name"}) == "Asha"
    assert sample_for({"source": "attribute", "key": "City"}) == "‹City›"
    assert sample_for({"source": "static", "value": "Diwali"}) == "Diwali"
    assert sample_for({}) == ""


def test_drafts_made_by_a_check_are_not_shown_as_history():
    from addons.whatsapp.campaigns_page import history_rows
    rows = [{"id": "1", "status": "draft", "total": 0}, {"id": "2", "status": "cancelled", "total": 0},
            {"id": "3", "status": "cancelled", "total": 40}, {"id": "4", "status": "done", "total": 9}]
    assert [r["id"] for r in history_rows(rows)] == ["3", "4"]


def test_a_rejection_code_becomes_something_to_change():
    from addons.whatsapp.templates_page import reject_reason_words, summary_of
    assert "variable" in reject_reason_words("INVALID_FORMAT")
    assert reject_reason_words("SOMETHING_NEW") == ""
    assert reject_reason_words(None) == ""
    assert summary_of([]) == ""
    assert summary_of([{"status": "APPROVED"}, {"status": "APPROVED"}, {"status": "PENDING"}]) == "3 templates  ·  2 approved  ·  1 in review"
    assert summary_of([{"status": "REJECTED"}]) == "1 template  ·  1 rejected"


# ── the template editor ──────────────────────────────────────────────────────

@pytest.fixture
def editor(calls):
    from addons.whatsapp import template_editor as T
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        yield T.TemplateEditor()


def test_the_ready_made_list_is_offered(editor):
    titles = [editor.start_from.itemText(i) for i in range(editor.start_from.count())]
    assert "Quotation sent" in titles and "Festival greeting" in titles
    assert not editor.start_field.isHidden()


def test_no_library_means_no_start_from_choice(calls):
    from addons.whatsapp import template_editor as T
    with mock.patch.object(T, "PlatformWorker", _worker(calls, fail={"templates/library": "down"})):
        assert T.TemplateEditor().start_field.isHidden()


def test_submit_stays_off_until_there_is_a_name_and_a_message(editor):
    assert not editor.submit_btn.isEnabled()
    editor.name_edit.setText("hello_there")
    assert not editor.submit_btn.isEnabled()
    editor.body_edit.setPlainText("Thank you for visiting our site today.")
    assert editor.submit_btn.isEnabled()


def test_meta_rules_are_checked_and_block_submit(editor, calls):
    # Typing "Bad Name" is now cleaned to "bad_name" in the field (test_whatsapp_templates_ui), so the service's name rule can only be met
    # by a name that arrives some other way, such as one already on file in a resubmit. Read-only is how the editor holds such a name.
    editor.name_edit.setReadOnly(True)
    editor.name_edit.setText("Bad Name")
    editor.body_edit.setPlainText("{{1}} is here for you")
    editor._lint()
    assert {"bad_name", "variable_at_start"} <= {i["code"] for i in editor._issues}
    assert not editor.submit_btn.isEnabled()
    assert "templates/lint" in routes(calls)


def test_fixing_the_problems_turns_submit_back_on(editor):
    editor.name_edit.setText("order_note")
    editor.body_edit.setPlainText("Hello {{1}}, your order is on its way to you.")
    editor._sample_edits[1].setText("Asha")
    editor._lint()
    assert editor._issues == [] and editor.submit_btn.isEnabled()


def test_a_sample_box_appears_for_each_variable(editor):
    editor.body_edit.setPlainText("Hi {{1}}, {{2}} is ready, thanks for waiting.")
    assert sorted(editor._sample_edits) == [1, 2]
    assert not editor.samples_field.isHidden()
    editor.body_edit.setPlainText("Plain message with nothing to fill in.")
    assert editor._sample_edits == {} and editor.samples_field.isHidden()


def test_submit_waits_for_every_sample_and_the_message_says_why(editor):
    editor.name_edit.setText("order_note")
    editor.body_edit.setPlainText("Hello {{1}}, your order is on its way to you.")
    editor._lint()
    assert not editor.submit_btn.isEnabled()
    assert "sample value" in labels_of(editor.check_box).lower()
    editor._sample_edits[1].setText("Asha")
    editor._lint()
    assert editor._issues == [] and editor.submit_btn.isEnabled()


def test_the_phone_shows_the_message_as_the_customer_will_read_it(editor):
    editor.header_edit.setText("Order update")
    editor.body_edit.setPlainText("Hello {{1}}, your order is on its way to you.")
    editor._sample_edits[1].setText("Asha")
    editor.footer_edit.setText("Reply STOP to opt out")
    kind, text, _v = editor.button_rows[0]
    kind.setCurrentIndex(kind.findData("QUICK_REPLY"))
    text.setText("Track it")
    assert editor.preview.text.text() == "Hello Asha, your order is on its way to you."
    assert editor.preview.head.text() == "Order update" and editor.preview.foot.text() == "Reply STOP to opt out"
    assert not editor.preview.bubble.isHidden() and editor.preview.empty.isHidden()
    editor.body_edit.setPlainText("")
    assert editor.preview.bubble.isHidden() and not editor.preview.empty.isHidden()


def test_a_button_needs_its_type_before_it_takes_text(editor):
    kind, text, value = editor.button_rows[0]
    assert not text.isEnabled() and value.isHidden()
    kind.setCurrentIndex(kind.findData("URL"))
    assert text.isEnabled() and not value.isHidden() and "https" in value.placeholderText()
    kind.setCurrentIndex(kind.findData("PHONE_NUMBER"))
    assert "+91" in value.placeholderText()
    kind.setCurrentIndex(0)
    assert not text.isEnabled() and value.isHidden() and editor.buttons() == []


def test_buttons_reach_the_submitted_template(editor, calls):
    editor.name_edit.setText("order_note")
    editor.body_edit.setPlainText("Thank you for visiting our shop, do come again soon.")
    for (kind, text, value), (k, t, v) in zip(editor.button_rows, (("URL", "See offers", "https://shop.in"),
                                                                    ("PHONE_NUMBER", "Call us", "+919876543210"))):
        kind.setCurrentIndex(kind.findData(k))
        text.setText(t)
        value.setText(v)
    editor._lint()
    editor._submit()
    data = [d for r, d in calls if r == "templates/create"][0]
    buttons = data["components"][-1]["buttons"]
    assert [b["type"] for b in buttons] == ["URL", "PHONE_NUMBER"]


def test_a_header_variable_needs_a_sample_of_its_own(editor):
    editor.name_edit.setText("offer_note")
    editor.header_edit.setText("Offer for {{1}}")
    editor.body_edit.setPlainText("Thank you for visiting our shop, do come again soon.")
    assert not editor.header_sample.isHidden() and not editor.submit_btn.isEnabled()
    editor.header_sample.setText("Asha")
    editor._lint()
    assert editor.submit_btn.isEnabled()


def test_choosing_from_the_library_fills_the_form(editor):
    i = next(k for k in range(editor.start_from.count()) if editor.start_from.itemText(k) == "Site visit confirmation")
    editor.start_from.setCurrentIndex(i)
    assert editor.name_edit.text() == "site_visit_confirmation"
    assert "site visit is confirmed" in editor.body_edit.toPlainText()
    assert editor.category.currentData() == "UTILITY"
    assert [b[:2] for b in editor.buttons()][:2] == [("QUICK_REPLY", "Confirm"), ("QUICK_REPLY", "Reschedule")]
    assert editor._sample_edits[1].text() == "Asha"
    editor._lint()
    assert editor.submit_btn.isEnabled()


def test_resubmitting_a_rejected_template_keeps_its_name(calls):
    from addons.whatsapp import template_editor as T
    big_sale = next(t for t in demo_platform._state()["templates"] if t["name"] == "big_sale")
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        ed = T.TemplateEditor(prefill=big_sale, mode="resubmit")
    assert ed.windowTitle() == "Edit and resubmit" and ed.name_edit.isReadOnly() and not ed.lang.isEnabled()
    assert ed.name_edit.text() == "big_sale" and ed.start_field.isHidden()
    assert ed.submit_btn.text() == "Resubmit to Meta"
    assert "templates/library" not in routes(calls)


def test_a_duplicate_gets_a_new_name_and_the_same_words(calls):
    from addons.whatsapp import template_editor as T
    src = next(t for t in demo_platform._state()["templates"] if t["name"] == "diwali_offer")
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        ed = T.TemplateEditor(prefill=src, mode="duplicate")
    assert ed.name_edit.text() == "diwali_offer_copy" and not ed.name_edit.isReadOnly()
    assert ed.body_edit.toPlainText().startswith("Hello {{1}}, our Diwali offer")
    assert ed._sample_edits[1].text() == "Asha"


def test_submitting_sends_the_template_and_closes(editor, calls):
    editor.name_edit.setText("order_note")
    editor.body_edit.setPlainText("Hello {{1}}, your order is on its way to you.")
    editor._sample_edits[1].setText("Asha")
    editor._lint()
    editor._submit()
    route, data = [c for c in calls if c[0] == "templates/create"][0]
    assert data["name"] == "order_note" and data["category"] == "MARKETING"
    assert data["components"][0]["example"] == {"body_text": [["Asha"]]}
    assert editor.result() == QDialog.Accepted


def test_a_refusal_from_the_server_is_shown_and_submit_can_be_retried(editor):
    editor.name_edit.setText("ok_name")
    editor.body_edit.setPlainText("Fine message that is long enough to pass.")
    from addons.whatsapp import demo_templates
    with mock.patch.object(demo_templates, "lint", lambda d: [
            {"severity": "error", "code": "x", "message": "Meta says no.", "where": "", "meta_code": None}]):
        editor._submit()
    assert any(i["message"] == "Meta says no." for i in editor._issues)
    assert not editor._busy and editor.submit_btn.text() == "Submit to Meta"


# ── the templates screen ─────────────────────────────────────────────────────

@pytest.fixture
def templates(calls):
    from addons.whatsapp import templates_page as TP
    with mock.patch.object(TP, "PlatformWorker", _worker(calls)):
        page = TP.TemplatesPage({})
        page.activate()
        yield page
        page.deactivate()


def test_every_template_is_listed_with_its_status(templates):
    assert [t["name"] for t in templates.visible_rows()] == ["diwali_offer", "order_update", "quotation_followup", "big_sale"]
    assert templates.stack.currentIndex() == 0
    assert templates.summary.text() == "4 templates  ·  2 approved  ·  1 in review  ·  1 rejected"


def test_the_status_filter_narrows_the_list(templates):
    templates._set_filter("REJECTED")
    assert [t["name"] for t in templates.visible_rows()] == ["big_sale"]
    templates._set_filter("PENDING")
    assert [t["name"] for t in templates.visible_rows()] == ["quotation_followup"]


def test_search_looks_at_the_name_and_the_words(templates):
    templates.search.setText("diwali")
    assert [t["name"] for t in templates.visible_rows()] == ["diwali_offer"]
    templates.search.setText("shipped")
    assert [t["name"] for t in templates.visible_rows()] == ["order_update"]
    templates.search.setText("zzzz")
    assert templates.visible_rows() == [] and templates.stack.currentIndex() == 1
    assert templates.state.title.text() == "No template matches"


def test_an_account_with_no_templates_is_invited_to_write_one(calls):
    from addons.whatsapp import templates_page as TP
    demo_platform._state()["templates"].clear()
    with mock.patch.object(TP, "PlatformWorker", _worker(calls)):
        page = TP.TemplatesPage({})
        page.activate()
    assert page.stack.currentIndex() == 1 and page.state.title.text() == "No templates yet"
    assert page.state.action.text() == "New template"


def test_update_from_meta_syncs_then_reloads(templates, calls):
    del calls[:]
    templates._sync()
    assert routes(calls) == ["templates/sync", "templates/list"]
    assert templates.sync_btn.isEnabled() and templates.sync_btn.text() == "Update from Meta"


def test_a_first_load_failure_says_why_and_offers_another_try(calls):
    from addons.whatsapp import templates_page as TP
    with mock.patch.object(TP, "PlatformWorker", _worker(calls, fail={"templates/list": "The WhatsApp add-on isn't set up on the server yet."})):
        page = TP.TemplatesPage({})
        page.activate()
    assert page.stack.currentIndex() == 1
    assert page.state.title.text() == "Couldn't load your templates" and "isn't set up" in page.state.body.text()
    assert page.state.action.text() == "Try again"


def test_trying_again_loads_the_list(calls):
    from addons.whatsapp import templates_page as TP
    fail = {"templates/list": "down"}
    with mock.patch.object(TP, "PlatformWorker", _worker(calls, fail=fail)):
        page = TP.TemplatesPage({})
        page.activate()
        fail.clear()
        page._state_action()
    assert page.stack.currentIndex() == 0 and len(page.visible_rows()) == 4


def test_a_failed_refresh_keeps_the_list_that_was_on_screen(templates, calls):
    from addons.whatsapp import templates_page as TP
    with mock.patch.object(TP, "PlatformWorker", _worker(calls, fail={"templates/list": "blip"})):
        templates._load()
    assert len(templates.visible_rows()) == 4 and templates.stack.currentIndex() == 0
    assert not templates.note.isHidden() and "blip" in templates.note.text()


def test_a_template_in_review_makes_the_page_look_again_by_itself(templates):
    assert templates._poll.isActive()
    templates.deactivate()
    assert not templates._poll.isActive()


def test_nothing_in_review_means_no_background_refresh(calls):
    from addons.whatsapp import templates_page as TP
    for t in demo_platform._state()["templates"]:
        t["status"] = "APPROVED"
    with mock.patch.object(TP, "PlatformWorker", _worker(calls)):
        page = TP.TemplatesPage({})
        page.activate()
    assert not page._poll.isActive()


def test_each_kind_of_row_offers_the_right_actions(templates):
    def actions(row):
        return [b.text() for b in row.findChildren(type(templates.sync_btn)) if b.text()]
    rows = {r.t["name"]: r for r in (templates.list_col.itemAt(i).widget() for i in range(templates.list_col.count()))
            if r is not None and hasattr(r, "t")}
    assert "Use in a campaign" in actions(rows["diwali_offer"])
    assert "Edit and resubmit" in actions(rows["big_sale"]) and "Use in a campaign" not in actions(rows["big_sale"])
    assert actions(rows["quotation_followup"]) == []          # in review: nothing to do but wait (copy and delete are icons)


def test_using_an_approved_template_announces_its_name(templates):
    got = []
    templates.useTemplate.connect(got.append)
    templates.list_col.itemAt(0).widget().use.emit({"name": "diwali_offer"})
    assert got == ["diwali_offer"]


def test_editing_a_rejected_one_opens_the_editor_in_resubmit_mode(templates):
    from addons.whatsapp import template_editor as T
    big_sale = next(t for t in templates._rows if t["name"] == "big_sale")
    with mock.patch.object(T.TemplateEditor, "exec", return_value=1), mock.patch.object(T, "PlatformWorker", _worker([])):
        templates._open_editor(big_sale, "resubmit")
    assert "Submitted" in templates.note.text()


def test_deleting_asks_first_then_removes_it_and_reloads(templates, calls):
    del calls[:]
    target = next(t for t in templates._rows if t["name"] == "big_sale")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        templates._delete(target)
    assert "templates/delete" not in routes(calls)
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes) as q:
        templates._delete(target)
    assert ("templates/delete", {"template_id": target["id"]}) in calls and routes(calls)[-1] == "templates/list"
    assert "big_sale" not in [t["name"] for t in templates.visible_rows()]
    assert "can't be undone" in q.call_args[0][2]


def test_deleting_an_approved_one_warns_it_leaves_whatsapp_too(templates):
    target = next(t for t in templates._rows if t["name"] == "order_update")
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No) as q:
        templates._delete(target)
    assert "WhatsApp account" in q.call_args[0][2]


def test_a_template_a_live_campaign_uses_cannot_be_deleted_and_the_reason_is_shown(templates):
    target = next(t for t in templates._rows if t["name"] == "order_update")
    next(c for c in demo_platform._state()["campaigns"] if c["id"] == "c2")["status"] = "scheduled"
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        templates._delete(target)
    assert "Cancel that campaign first" in templates.note.text()
    assert "order_update" in [t["name"] for t in templates.visible_rows()]


# ── the campaigns screen ─────────────────────────────────────────────────────

@pytest.fixture
def campaigns(calls):
    from addons.whatsapp import campaigns_page as CP
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)):
        page = CP.CampaignsPage({})
        page.activate()
        yield page
        page.deactivate()


def _yes():
    return mock.patch.object(QMessageBox, "question", return_value=QMessageBox.Yes)


def test_the_screen_shows_nothing_but_a_loading_state_until_it_has_loaded(calls):
    from addons.whatsapp import campaigns_page as CP
    page = CP.CampaignsPage({})
    assert page.stack.currentIndex() == 1 and page.state.title.text() == "Loading…"


def test_a_first_load_failure_is_explained_with_a_way_to_retry(calls):
    from addons.whatsapp import campaigns_page as CP
    with mock.patch.object(CP, "PlatformWorker", _worker(calls, fail={"templates/list": "The WhatsApp add-on isn't set up on the server yet."})):
        page = CP.CampaignsPage({})
        page.activate()
    assert page.stack.currentIndex() == 1 and page.state.title.text() == "Couldn't load your campaigns"
    assert "isn't set up" in page.state.body.text() and page.state.action.text() == "Try again"


def test_only_approved_templates_can_be_chosen(campaigns):
    assert campaigns.stack.currentIndex() == 0
    assert [campaigns.template_combo.itemData(i) for i in range(campaigns.template_combo.count())] == ["diwali_offer", "order_update"]


def test_with_no_approved_template_the_screen_sends_you_to_write_one(calls):
    from addons.whatsapp import campaigns_page as CP
    for t in demo_platform._state()["templates"]:
        t["status"] = "PENDING"
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)):
        page = CP.CampaignsPage({})
        page.activate()
    assert page.template_combo.isHidden() and not page.no_templates.isHidden() and page.vars_card.isHidden()
    got = []
    page.openTemplates.connect(lambda: got.append(1))
    page._on_templates({"templates": []})
    page.no_templates.findChildren(type(page.check_btn))[0].click()
    assert got == [1]


def test_each_blank_in_the_message_gets_a_row(campaigns):
    assert list(campaigns._var_rows) == ["1", "2"]
    campaigns.choose_template("order_update")
    assert campaigns.current_template()["name"] == "order_update" and list(campaigns._var_rows) == ["1", "2"]


def test_a_text_box_shows_only_for_blanks_that_need_one(campaigns):
    combo, edit, _kind, _fb = campaigns._var_rows["2"]
    assert edit.isHidden()                                   # first name needs nothing more
    combo.setCurrentIndex(combo.findData("static"))
    assert not edit.isHidden() and "same" in combo.currentText().lower()


def test_the_message_is_previewed_with_what_each_blank_will_hold(campaigns):
    assert campaigns.preview.text.text().startswith("Hello Asha, our Diwali offer on Asha ends")
    combo, edit, _k, _fb = campaigns._var_rows["2"]
    combo.setCurrentIndex(combo.findData("static"))
    edit.setText("boundary walls")
    assert "offer on boundary walls ends" in campaigns.preview.text.text()


def test_a_template_with_a_media_header_asks_for_the_file_link(campaigns):
    campaigns._templates.append({"name": "promo", "language": "en_US", "status": "APPROVED", "components": [
        {"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Our new range is in the shop today, come and see."}]})
    campaigns.template_combo.addItem("promo", "promo")
    campaigns.template_combo.setCurrentIndex(campaigns.template_combo.findData("promo"))
    assert list(campaigns._var_rows) == ["header"]
    _c, edit, kind, _fb = campaigns._var_rows["header"]
    edit.setText("https://x.in/a.jpg")
    assert kind == "link" and campaigns.variables() == {"header": {"link": "https://x.in/a.jpg"}}


def test_send_is_off_until_a_check_has_passed(campaigns):
    assert not campaigns.send_btn.isEnabled()
    campaigns._check()
    assert campaigns.send_btn.isEnabled() and not campaigns.verdict.isHidden()


def test_changing_anything_after_a_check_asks_for_another(campaigns):
    campaigns._check()
    assert campaigns.send_btn.isEnabled()
    campaigns.audience_combo.setCurrentIndex(1)              # People with a tag…
    campaigns.tags_edit.setText("vip")
    assert not campaigns.send_btn.isEnabled() and campaigns.verdict.isHidden()


def test_an_audience_nobody_is_in_blocks_with_the_reason(campaigns):
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns.tags_edit.setText("nobody-has-this-tag")
    campaigns._check()
    assert not campaigns.send_btn.isEnabled()
    texts = labels_of(campaigns.verdict)
    assert "Nobody" in texts and "can't be sent" in texts


def test_sending_asks_first_and_declining_sends_nothing(campaigns, calls):
    campaigns._check()
    del calls[:]
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        campaigns._send()
    assert "campaigns/launch" not in routes(calls)


def test_confirming_launches_the_checked_draft(campaigns, calls):
    campaigns._check()
    cid = campaigns._checked[1]
    with _yes():
        campaigns._send()
    assert [d for r, d in calls if r == "campaigns/launch"] == [{"campaign_id": cid}]
    assert campaigns.verdict.isHidden() and not campaigns.note.isHidden() and "Started" in campaigns.note.text()


def test_checking_again_tidies_the_stale_draft(campaigns, calls):
    campaigns._check()
    first = campaigns._checked[1]
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns.tags_edit.setText("vip")
    campaigns._check()
    assert ("campaigns/cancel", {"campaign_id": first}) in calls and campaigns._checked[1] != first


def test_a_check_leaves_no_clutter_in_the_history(campaigns):
    campaigns._check()
    campaigns._check()
    campaigns._reload_history()
    shown = [campaigns.history_col.itemAt(i).widget() for i in range(campaigns.history_col.count())]
    assert len([w for w in shown if w is not None and hasattr(w, "act")]) == 2        # only the two real campaigns


def test_scheduling_sends_a_time_and_a_zone(campaigns, calls):
    campaigns.when_combo.setCurrentIndex(1)
    assert campaigns.send_btn.text() == "Schedule" and not campaigns.when_edit.isHidden()
    campaigns._check()
    data = [d for r, d in calls if r == "campaigns/create"][0]
    assert data["timezone"] == "Asia/Kolkata" and "T" in data["schedule_at"]
    with _yes():
        campaigns._send()
    assert "campaigns/launch" in routes(calls)


def test_the_audience_is_sent_the_way_the_server_reads_it(campaigns):
    assert campaigns.audience() == {"tags": []}
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns.tags_edit.setText("vip, builder ,")
    assert campaigns.audience() == {"tags": ["vip", "builder"]}
    campaigns._on_segments({"segments": [{"id": "s9", "name": "Vadodara"}]})
    campaigns.audience_combo.setCurrentIndex(campaigns.audience_combo.findData("segment:s9"))
    assert campaigns.audience() == {"segment_id": "s9", "segment_name": "Vadodara"}


def test_the_people_who_can_be_reached_are_counted_as_you_choose(campaigns, calls):
    del calls[:]
    campaigns._count()
    assert ("segments/count", {"filter": {"all": []}}) in calls and campaigns.reach.text() == "9 people can be messaged right now."
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns._count()
    assert "Type a tag" in campaigns.reach.text()
    campaigns.tags_edit.setText("vip")
    campaigns._count()
    assert calls[-1] == ("segments/count", {"filter": {"field": "tags", "op": "has_any", "value": ["vip"]}})
    assert campaigns.reach.text() == "2 people can be messaged right now."


def test_an_old_count_never_overwrites_a_newer_one(campaigns):
    campaigns._count_token = 5
    campaigns._counted(4, {"count": 99})
    assert "99" not in campaigns.reach.text()


def test_a_set_of_tags_can_be_kept_as_a_group_and_is_then_chosen(campaigns, calls):
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns.tags_edit.setText("vip, builder")
    assert not campaigns.save_group_btn.isHidden()
    with mock.patch.object(QInputDialog, "getText", return_value=("VIP builders", True)):
        campaigns._save_group()
    assert [d for r, d in calls if r == "segments/save"] == [
        {"name": "VIP builders", "filter": {"field": "tags", "op": "has_any", "value": ["vip", "builder"]}}]
    assert campaigns.audience_combo.currentText() == "Saved group: VIP builders"
    assert campaigns.audience()["segment_id"] and campaigns.save_group_btn.isHidden()


def test_saving_a_group_without_tags_says_so(campaigns, calls):
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns._save_group()
    assert "at least one tag" in campaigns.reach.text() and "segments/save" not in routes(calls)


def test_an_earlier_campaign_can_be_the_audience(campaigns):
    campaigns.add_retarget("c1", "Diwali offer", "read", True)
    assert campaigns.audience_combo.currentText() == "Didn't read “Diwali offer”"
    a = campaigns.audience()
    assert a["filter"] == {"not": {"field": "campaign", "op": "read", "campaign": "c1"}}
    campaigns.add_retarget("c1", "Diwali offer", "read", True)                   # asking again does not add a second entry
    assert [campaigns.audience_combo.itemText(i) for i in range(campaigns.audience_combo.count())].count("Didn't read “Diwali offer”") == 1
    campaigns._check()
    assert campaigns.send_btn.isEnabled()


def test_several_numbers_means_choosing_one_before_checking(calls):
    from addons.whatsapp import campaigns_page as CP
    demo_platform._state()["numbers"] = [{"id": "n1", "display": "+91 98765 43210", "status": "CONNECTED", "quality": "GREEN"},
                                         {"id": "n2", "display": "+91 91234 56789", "status": "CONNECTED", "quality": "GREEN"}]
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)):
        page = CP.CampaignsPage({})
        page.activate()
        assert not page.number_combo.isHidden() and page.number_combo.count() == 3
        page._check()
        assert "more than one WhatsApp number" in labels_of(page.verdict) and "campaigns/create" not in routes(calls)
        page.number_combo.setCurrentIndex(page.number_combo.findData("n2"))
        page._check()
        assert [d for r, d in calls if r == "campaigns/create"][0]["number_id"] == "n2" and page.send_btn.isEnabled()


def test_one_number_means_no_choice_to_make(campaigns):
    assert campaigns.number_combo.isHidden() and "number_id" not in campaigns.collect()


def test_history_shows_each_campaign_and_its_actions(campaigns):
    shown = [campaigns.history_col.itemAt(i).widget() for i in range(campaigns.history_col.count())]
    assert len([w for w in shown if w is not None and hasattr(w, "act")]) == 2


def test_the_history_looks_again_by_itself_only_while_something_is_sending(campaigns):
    assert not campaigns._poll.isActive()
    campaigns._on_history({"campaigns": [{"id": "z", "name": "Live", "status": "sending", "total": 10, "sent": 3, "failed": 0,
                                          "template_name": "diwali_offer", "created_at": "2026-10-17T10:00:00Z"}]})
    assert campaigns._poll.isActive()
    campaigns.deactivate()
    assert not campaigns._poll.isActive()
    campaigns._on_history({"campaigns": []})
    assert not campaigns._poll.isActive()


def test_cancelling_a_scheduled_campaign_asks_first(campaigns, calls):
    del calls[:]
    with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        campaigns._row_action("cancel", "c2")
    assert "campaigns/cancel" not in routes(calls)
    with _yes():
        campaigns._row_action("cancel", "c2")
    assert ("campaigns/cancel", {"campaign_id": "c2"}) in calls


def test_a_scheduled_campaign_can_be_moved(campaigns, calls):
    from addons.whatsapp import campaigns_page as CP
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)), mock.patch.object(CP.RescheduleDialog, "exec", return_value=1):
        campaigns._row_action("reschedule", "c2")
    assert "Moved" in campaigns.note.text()
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)):
        dlg = CP.RescheduleDialog({"id": "c2", "name": "Site visit reminders"})
        dlg._save()
    route, data = [c for c in calls if c[0] == "campaigns/reschedule"][-1]
    assert data["campaign_id"] == "c2" and data["timezone"] == "Asia/Kolkata" and "T" in data["schedule_at"]
    assert dlg.result() == QDialog.Accepted


def test_moving_a_campaign_that_has_already_started_is_refused_with_the_reason(calls):
    from addons.whatsapp import campaigns_page as CP
    with mock.patch.object(CP, "PlatformWorker", _worker(calls)):
        dlg = CP.RescheduleDialog({"id": "c1", "name": "Diwali offer"})
        dlg._save()
    assert not dlg.error.isHidden() and "scheduled" in dlg.error.text() and dlg.save_btn.isEnabled()


def test_the_results_show_how_far_it_got_and_offer_a_follow_up(calls):
    from addons.whatsapp import campaigns_page as CP
    picked = []
    with mock.patch.object(ui, "PlatformWorker", _worker(calls)):
        dlg = CP.CampaignReport("c1", "Diwali offer", on_retarget=lambda *a: picked.append(a), quick_replies=["Yes", "No"])
    text = labels_of(dlg)
    assert "Delivered" in text and "Read" in text and "Replied" in text and "8 could not be delivered" in text
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "estimate" in text and "Message people who pressed “Yes”" in buttons and "Message people who pressed “No”" in buttons
    assert "Message people who read it" in buttons and "Message people who didn't read it" in buttons
    dlg._retarget("read", True)
    assert picked == [("c1", "read", True, None)] and dlg.result() == QDialog.Accepted


def test_a_failed_report_says_so(calls):
    from addons.whatsapp import campaigns_page as CP
    with mock.patch.object(ui, "PlatformWorker", _worker(calls, fail={"campaigns/report": "Couldn't reach the server."})):
        dlg = CP.CampaignReport("c1", "Diwali offer")
    assert "Couldn't reach" in labels_of(dlg)


# ── importing contacts ───────────────────────────────────────────────────────

CSV = "Name,Mobile,City\nAsha,9812345678,Vadodara\nRavi,98123,Surat\nMeera,9898989898,Anand\n"


@pytest.fixture
def importer(calls, tmp_path):
    from addons.whatsapp import import_dialog as I
    f = tmp_path / "people.csv"
    f.write_text(CSV, encoding="utf-8")
    with mock.patch.object(I, "PlatformWorker", _worker(calls)):
        dlg = I.ImportContactsDialog()
        dlg.csv_path = str(f)
        yield dlg


def test_choosing_a_file_shows_its_first_rows_before_anything_is_imported(importer):
    assert not importer.go.isEnabled() and importer.table.isHidden()
    importer.load(importer.csv_path)
    assert importer.go.isEnabled() and "3 rows" in importer.glance.text()
    assert importer.table.columnCount() == 3 and importer.table.rowCount() == 3
    assert importer.table.horizontalHeaderItem(1).text() == "Mobile" and importer.table.item(0, 0).text() == "Asha"


def test_a_file_with_no_mobile_column_is_stopped_with_what_to_do(importer, tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("Name,City\nAsha,Vadodara\n", encoding="utf-8")
    importer.load(str(f))
    assert not importer.go.isEnabled() and not importer.problem.isHidden() and "marked as the mobile number" in importer.problem.text()
    importer.load(importer.csv_path)                          # then a good file clears it
    assert importer.go.isEnabled() and importer.problem.isHidden()


def test_the_mobile_column_may_go_by_other_names():
    from addons.whatsapp.import_dialog import has_mobile_column
    assert has_mobile_column(["Name", "WhatsApp Number"]) and has_mobile_column(["phone"]) and not has_mobile_column(["Name", "City"])


def test_an_empty_file_is_refused(importer, tmp_path):
    f = tmp_path / "empty.csv"
    f.write_text("", encoding="utf-8")
    importer.load(str(f))
    assert "empty" in importer.problem.text() and not importer.go.isEnabled()


def test_an_excel_style_file_still_reads(tmp_path):
    from addons.whatsapp.import_dialog import read_csv_text
    p = tmp_path / "x.csv"
    p.write_bytes(CSV.encode("utf-8-sig"))
    assert read_csv_text(str(p)).startswith("Name,")
    q = tmp_path / "y.csv"
    q.write_bytes("Name,Mobile\nAsha ₹,9812345678\n".encode("cp1252", errors="ignore"))
    assert "9812345678" in read_csv_text(str(q))


def test_text_is_decoded_by_its_marker_not_by_luck():
    from addons.whatsapp.import_dialog import decode_text
    assert decode_text("Name,Mobile\n".encode("utf-16")) == "Name,Mobile\n"
    assert decode_text("Caf\u00e9".encode("cp1252")) == "Caf\u00e9"
    assert decode_text("\u20b95".encode("utf-8")) == "\u20b95"
    assert decode_text(b"Caf\xe9 5") == "Caf\u00e9 5"                 # an even number of odd bytes is not UTF-16


def test_a_huge_file_is_refused_with_a_reason(tmp_path):
    from addons.whatsapp import import_dialog as I
    p = tmp_path / "big.csv"
    p.write_bytes(b"a" * (I.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="8 MB"):
        I.read_csv_text(str(p))


def test_a_dropped_csv_is_loaded_and_anything_else_ignored(importer):
    from PySide6.QtCore import QMimeData, QUrl
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(importer.csv_path)])
    event = mock.Mock()
    event.mimeData.return_value = md
    importer.dropEvent(event)
    assert importer.go.isEnabled() and importer.file_label.text() == "people.csv"
    other = QMimeData()
    other.setUrls([QUrl.fromLocalFile("C:/x/photo.png")])
    event2 = mock.Mock()
    event2.mimeData.return_value = other
    importer.dragEnterEvent(event2)
    event2.acceptProposedAction.assert_not_called()


def test_the_sample_file_is_a_file_the_importer_accepts(tmp_path):
    from addons.whatsapp import import_dialog as I
    rows, header = I.glance(I.SAMPLE_CSV)
    assert rows == 2 and I.has_mobile_column(header)


def test_consent_is_not_claimed_unless_ticked(importer, calls):
    importer.load(importer.csv_path)
    assert importer.payload()["attest_consent"] is False and importer.evidence_edit.isEnabled() is False
    importer._go()
    data = [d for r, d in calls if r == "contacts/import"][0]
    assert data["attest_consent"] is False and data["evidence"] == ""


def test_ticking_consent_needs_a_note_of_where_they_agreed(importer, calls):
    importer.load(importer.csv_path)
    importer.attest.setChecked(True)
    importer._go()
    assert not importer.error.isHidden() and "contacts/import" not in routes(calls)
    importer.evidence_edit.setText("enquiry form")
    importer._go()
    data = [d for r, d in calls if r == "contacts/import"][0]
    assert data["attest_consent"] is True and data["evidence"] == "enquiry form"


def test_the_report_says_what_happened_and_what_was_skipped(importer):
    importer.load(importer.csv_path)
    importer.tags_edit.setText("diwali-list, builders")
    importer.attest.setChecked(True)
    importer.evidence_edit.setText("shop counter")
    importer._go()
    flat = labels_of(importer)
    assert "Added" in flat and "Skipped" in flat and "Row 3" in flat
    assert importer.go.text() == "Done" and importer.cancel.isHidden()
    assert importer.property("report")["created"] == 2 and importer.property("report")["invalid"] == 1


def test_a_finished_import_replaces_the_form_with_what_happened(importer):
    importer.load(importer.csv_path)
    importer._go()
    assert importer.form.isHidden()
    assert "Imported 2 contacts" in labels_of(importer)


def test_an_empty_reach_line_takes_no_room(campaigns):
    campaigns.audience_combo.setCurrentIndex(1)
    campaigns._count_timer.stop()
    campaigns._reach("")
    assert campaigns.reach.isHidden()
    campaigns._reach("3 people can be messaged right now.")
    assert not campaigns.reach.isHidden()


def test_tags_go_to_the_server_as_a_list(importer):
    importer.tags_edit.setText(" a , b,, ")
    importer._text = CSV
    assert importer.payload()["tags"] == ["a", "b"]


def test_a_failed_import_says_why_and_can_be_retried(importer):
    from addons.whatsapp import import_dialog as I
    importer.load(importer.csv_path)
    with mock.patch.object(I, "PlatformWorker", _worker([], fail={"contacts/import": "The file needs a Mobile column."})):
        importer._go()
    assert "Mobile column" in importer.error.text() and importer.go.isEnabled() and importer.go.text() == "Import"


# ── the tab strip ────────────────────────────────────────────────────────────

class _FakeInbox(QWidget):
    unreadChanged = Signal(int)
    statusChanged = Signal(str, bool)
    orderRequested = Signal(dict)
    formRequested = Signal(dict)

    def __init__(self, cfg):
        super().__init__()
        self.deactivated = 0

    def activate(self):
        pass

    def deactivate(self):
        self.deactivated += 1


def _workbench(calls):
    from addons.whatsapp import campaigns_page as CP
    from addons.whatsapp import templates_page as TP
    from addons.whatsapp import workbench as W
    patches = (mock.patch("addons.whatsapp.inbox.InboxPage", _FakeInbox), mock.patch.object(TP, "PlatformWorker", _worker(calls)),
               mock.patch.object(CP, "PlatformWorker", _worker(calls)))
    return W, patches


def test_the_new_tabs_are_in_the_strip_in_order(calls):
    from addons.whatsapp import workbench as W
    assert W._tab_names()[W._TEMPLATES] == "Templates" and W._tab_names()[W._CAMPAIGNS] == "Campaigns"
    assert len(W._tab_names()) == 10 and W._SETTINGS == 9 and W._ANALYTICS == 8 and W._FORMS == 7 and W._SHOP == 6 and W._AUTOMATIONS == 4 and W._ADS == 5
    assert W._tab_names()[W._ANALYTICS] == "Analytics" and W._tab_names()[W._SHOP] == "Shop" and W._tab_names()[W._FORMS] == "Forms"
    assert "Broadcasts" not in W._tab_names()               # broadcasting is Campaigns now: one place for it


def test_use_in_a_campaign_opens_campaigns_with_that_template(calls):
    W, (p1, p2, p3) = _workbench(calls)
    with p1, p2, p3:
        wb = W.WhatsAppWorkbench({})
        wb.show_tab(W._TEMPLATES)
        wb._pages[W._TEMPLATES].useTemplate.emit("order_update")
        assert wb._current == W._CAMPAIGNS
        assert wb._pages[W._CAMPAIGNS].current_template()["name"] == "order_update"


def test_no_approved_template_on_campaigns_takes_you_to_templates(calls):
    W, (p1, p2, p3) = _workbench(calls)
    with p1, p2, p3:
        wb = W.WhatsAppWorkbench({})
        wb.show_tab(W._CAMPAIGNS)
        wb._pages[W._CAMPAIGNS].openTemplates.emit()
        assert wb._current == W._TEMPLATES


def test_leaving_a_tab_stops_what_it_was_doing_in_the_background(calls):
    W, (p1, p2, p3) = _workbench(calls)
    with p1, p2, p3:
        wb = W.WhatsAppWorkbench({})
        wb.show_tab(W._TEMPLATES)
        templates = wb._pages[W._TEMPLATES]
        assert templates._poll.isActive()                      # a template is in review
        wb.show_tab(W._CAMPAIGNS)
        assert not templates._poll.isActive()
        assert wb._pages[W._INBOX].deactivated == 1
        wb.deactivate()                                       # the whole panel is hidden
        assert not wb._pages[W._CAMPAIGNS]._poll.isActive()


def test_the_header_button_opens_the_campaigns_tab():
    from addons.whatsapp import workbench as W
    from addons.whatsapp.panel import WhatsAppPanel
    panel = WhatsAppPanel({})
    assert panel.broadcast_btn.text() == "New campaign"
    shown = []
    panel._workbench = mock.Mock(show_tab=lambda i: shown.append(i))
    panel.new_broadcast()
    assert shown == [W._CAMPAIGNS]

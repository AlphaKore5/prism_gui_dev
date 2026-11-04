"""The Templates tab beyond plain text: authentication, picture / video / document / location headers with a sample for Meta, a
limited-time offer, a carousel, message validity, the ready-made library by industry, the AI writer and the rejection helper — and what
the list shows (kind, validity, numbers).

Driven against the demo platform with a fake worker. No processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_media, demo_platform, demo_templates, media_lib, readstate, ui  # noqa: E402
from addons.whatsapp import template_editor as T  # noqa: E402
from addons.whatsapp import template_kinds as TK  # noqa: E402
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
    tmp = tempfile.mkdtemp(prefix="prism-wa-templates-")
    readstate.reset_cache()
    media_lib._CACHE.clear()
    demo._state.clear()
    demo_platform._PAGE.clear()
    demo_media._BYTES.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield
    media_lib._CACHE.clear()
    demo._state.clear()
    demo_platform._PAGE.clear()
    demo_media._BYTES.clear()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def editor(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        ed = T.TemplateEditor()
        yield ed


def last(calls, route):
    return next(d for r, d in reversed(calls) if r == route)


def lint_now(ed):
    """Run the check that normally waits for a pause in typing."""
    ed._timer.stop()
    ed._lint()


def codes(ed) -> set:
    return {i["code"] for i in ed._issues}


def name_and_words(ed, name="my_template", body="Hello {{1}}, our new range is in the shop and we would love to show it to you."):
    ed.name_edit.setText(name)
    ed.body_edit.setPlainText(body)
    ed._sample_edits[1].setText("Asha")


def choose_sample(picker, asset_id):
    """What clicking Choose file and picking a library file does."""
    picker.field.set_asset_id(asset_id)
    picker.field.changed.emit()


# ── authentication ───────────────────────────────────────────────────────────

def test_authentication_swaps_the_form_for_the_code_options(editor):
    editor.category.setCurrentIndex(editor.category.findData("AUTHENTICATION"))
    assert editor.auth_field.isVisibleTo(editor) and not editor.body_field.isVisibleTo(editor) and not editor.header_field.isVisibleTo(editor)
    assert not editor.kind_field.isVisibleTo(editor) and not editor.buttons_field.isVisibleTo(editor) and not editor.footer_field.isVisibleTo(editor)
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    assert editor.body_field.isVisibleTo(editor) and not editor.auth_field.isVisibleTo(editor)


@pytest.mark.parametrize("mode,fields", [
    ("COPY_CODE", {"type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code"}),
    ("ONE_TAP", {"otp_type": "ONE_TAP", "autofill_text": "Autofill", "package_name": "com.example.app", "signature_hash": "K8a/AX6ELnR"}),
    ("ZERO_TAP", {"otp_type": "ZERO_TAP", "zero_tap_terms_accepted": True, "package_name": "com.example.app", "signature_hash": "K8a/AX6ELnR"})])
def test_each_code_button_becomes_the_components_meta_wants(editor, mode, fields):
    editor.category.setCurrentIndex(editor.category.findData("AUTHENTICATION"))
    editor.name_edit.setText("login_code")
    p = editor.auth_panel
    p.mode.setCurrentIndex(p.mode.findData(mode))
    p.package.setText("com.example.app")
    p.signature.setText("K8a/AX6ELnR")
    p.terms.setChecked(True)
    comps = editor.data()["components"]
    assert comps[0] == {"type": "BODY", "add_security_recommendation": True} and comps[1] == {"type": "FOOTER", "code_expiration_minutes": 10}
    assert fields.items() <= comps[2]["buttons"][0].items()
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled()


def test_a_one_tap_template_cannot_be_submitted_without_its_app(editor):
    editor.category.setCurrentIndex(editor.category.findData("AUTHENTICATION"))
    editor.name_edit.setText("login_code")
    editor.auth_panel.mode.setCurrentIndex(editor.auth_panel.mode.findData("ONE_TAP"))
    lint_now(editor)
    assert {"bad_package", "bad_signature_hash"} <= codes(editor) and not editor.submit_btn.isEnabled()


def test_the_code_expiry_can_be_left_out_and_the_preview_reads_like_the_message(editor):
    editor.category.setCurrentIndex(editor.category.findData("AUTHENTICATION"))
    editor.auth_panel.expires.setChecked(False)
    assert [c["type"] for c in editor.data()["components"]] == ["BODY", "BUTTONS"]
    assert "verification code" in editor.preview.text.text() and "expires" not in editor.preview.text.text()
    editor.auth_panel.expires.setChecked(True)
    editor.auth_panel.minutes.setValue(15)
    assert "expires in 15 minutes" in editor.preview.text.text()


# ── a picture, video, document or location above the words ───────────────────

def test_a_picture_template_cannot_be_submitted_until_meta_has_its_sample(editor):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("image"))
    name_and_words(editor)
    assert editor.media_field.isVisibleTo(editor) and not editor.header_field.isVisibleTo(editor)
    lint_now(editor)
    assert "missing_example" in codes(editor) and not editor.submit_btn.isEnabled()
    assert "sample file" in " ".join(lab.text() for lab in editor.check_box.findChildren(QLabel)).lower()


def test_choosing_a_sample_hands_it_to_meta_and_the_handle_becomes_the_headers_example(editor, calls):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("image"))
    name_and_words(editor)
    choose_sample(editor.sample_picker, "m1")
    assert last(calls, "templates/upload_sample") == {"asset_id": "m1", "format": "image"}
    assert editor.sample_picker.handle() == "4::demo-m1" and "with Meta" in editor.sample_picker.note.text()
    assert editor.data()["components"][0] == {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::demo-m1"]}}
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled()
    assert "picture goes here" in editor.preview.extra.text()


def test_a_sample_that_meta_will_not_take_is_explained_and_blocks_submit(editor, calls, monkeypatch):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("document"))
    name_and_words(editor)
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"templates/upload_sample": "Meta would not take that file"}))
    choose_sample(editor.sample_picker, "m2")
    assert editor.sample_picker.handle() == "" and "would not take" in editor.sample_picker.note.text() and not editor.submit_btn.isEnabled()


def test_changing_the_kind_of_media_drops_a_sample_of_the_wrong_kind(editor):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("image"))
    choose_sample(editor.sample_picker, "m1")
    assert editor.sample_picker.handle()
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("video"))
    assert editor.sample_picker.handle() == "" and editor.sample_picker.field.kinds == ("video",) and editor.sample_picker.kind() == "video"


def test_a_location_header_needs_no_sample(editor):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("location"))
    name_and_words(editor)
    assert not editor.media_field.isVisibleTo(editor)
    assert editor.data()["components"][0] == {"type": "HEADER", "format": "LOCATION"}
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled() and "map location" in editor.preview.extra.text()


def test_the_text_header_still_works_as_before(editor):
    name_and_words(editor)
    editor.header_edit.setText("Our new range")
    assert editor.data()["components"][0] == {"type": "HEADER", "format": "TEXT", "text": "Our new range"}
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("image"))
    assert editor.data()["components"][0]["format"] == "IMAGE"                       # the text header is not carried into a picture one


# ── a limited-time offer ─────────────────────────────────────────────────────

def make_offer(editor):
    editor.category.setCurrentIndex(editor.category.findData("MARKETING"))
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("offer"))
    name_and_words(editor, "festival_offer", "Hello {{1}}, our festival offer is on for a short time only, so use the code below to claim it.")
    editor.offer_panel.text.setText("Festival offer")
    kind, text, value = editor.button_rows[0]
    kind.setCurrentIndex(kind.findData("COPY_CODE"))
    text.setText("Copy offer code")
    value.setText("FEST25")


def test_an_offer_is_built_from_its_picture_its_words_a_countdown_and_a_coupon(editor):
    make_offer(editor)
    choose_sample(editor.sample_picker, "m1")
    assert editor.offer_field.isVisibleTo(editor) and editor.media_field.isVisibleTo(editor) and editor.offer_media_field.isVisibleTo(editor)
    types = [c["type"] for c in editor.data()["components"]]
    assert types == ["HEADER", "BODY", "LIMITED_TIME_OFFER", "BUTTONS"]
    comps = {c["type"]: c for c in editor.data()["components"]}
    assert comps["LIMITED_TIME_OFFER"]["limited_time_offer"] == {"text": "Festival offer", "has_expiration": True}
    assert comps["BUTTONS"]["buttons"] == [{"type": "COPY_CODE", "text": "Copy offer code", "example": "FEST25"}]
    editor.offer_panel.countdown.setChecked(False)
    assert editor.data()["components"][2]["limited_time_offer"]["has_expiration"] is False
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled() and "Festival offer" in editor.preview.extra.text()


def test_an_offer_can_show_a_video_and_is_only_ever_marketing(editor):
    make_offer(editor)
    editor.offer_media.setCurrentIndex(editor.offer_media.findData("video"))
    assert editor.sample_picker.kind() == "video"
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    lint_now(editor)
    assert "offer_is_marketing" in codes(editor)


def test_the_offer_text_stops_at_sixteen_characters(editor):
    make_offer(editor)
    editor.offer_panel.text.setText("x" * 30)
    assert len(editor.offer_panel.text.text()) == 16


# ── a carousel ───────────────────────────────────────────────────────────────

def make_carousel(editor, handles=True):
    editor.category.setCurrentIndex(editor.category.findData("MARKETING"))
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("carousel"))
    name_and_words(editor, "new_arrivals", "Hello {{1}}, here are this week's new arrivals. Swipe through them and tap the one you like.")
    for i, card in enumerate(editor.cards_editor._cards):
        card.text.setText("Product number %d in strong steel" % (i + 1))
        if handles:
            choose_sample(card.sample, "m1")
    kind, text, _v = editor.button_rows[0]
    kind.setCurrentIndex(kind.findData("QUICK_REPLY"))
    text.setText("Tell me more")


def test_a_carousel_starts_with_two_cards_grows_to_ten_and_no_further(editor):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("carousel"))
    cards = editor.cards_editor
    assert cards.count() == 2 and not cards.remove_btn.isEnabled()
    for _ in range(12):
        cards.add_card()
    assert cards.count() == 10 and not cards.add_btn.isEnabled()
    for _ in range(12):
        cards.remove_last()
    assert cards.count() == 2


def test_a_carousel_has_its_intro_the_cards_and_the_shared_buttons_and_no_footer(editor):
    make_carousel(editor)
    comps = editor.data()["components"]
    assert [c["type"] for c in comps] == ["BODY", "CAROUSEL"]
    cards = comps[1]["cards"]
    assert len(cards) == 2 and cards[0]["components"][0] == {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::demo-m1"]}}
    assert cards[1]["components"][1]["text"] == "Product number 2 in strong steel"
    assert cards[0]["components"][2]["buttons"] == [{"type": "QUICK_REPLY", "text": "Tell me more"}] == cards[1]["components"][2]["buttons"]
    assert not editor.footer_field.isVisibleTo(editor) and editor.cards_field.isVisibleTo(editor)
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled() and "2 cards" in editor.preview.extra.text()


def test_a_carousel_cannot_be_submitted_while_a_card_lacks_its_sample(editor):
    make_carousel(editor, handles=False)
    choose_sample(editor.cards_editor._cards[0].sample, "m1")
    lint_now(editor)
    assert editor.cards_editor.missing_samples() and not editor.submit_btn.isEnabled()
    choose_sample(editor.cards_editor._cards[1].sample, "m1")
    lint_now(editor)
    assert not editor.cards_editor.missing_samples() and editor.submit_btn.isEnabled()


def test_every_card_uses_the_same_kind_of_media(editor):
    editor.kind_box.setCurrentIndex(editor.kind_box.findData("carousel"))
    for card in editor.cards_editor._cards:
        choose_sample(card.sample, "m1")
    editor.cards_editor.kind_box.setCurrentIndex(editor.cards_editor.kind_box.findData("video"))
    assert all(c.sample.kind() == "video" and c.sample.handle() == "" for c in editor.cards_editor._cards)
    assert editor.cards_editor.component([])["cards"][0]["components"][0]["format"] == "VIDEO"


# ── message validity ─────────────────────────────────────────────────────────

def test_the_validity_choices_follow_the_category(editor):
    def labels():
        return [editor.validity.itemText(i) for i in range(editor.validity.count())]
    editor.category.setCurrentIndex(editor.category.findData("MARKETING"))
    assert labels()[0] == "Meta's default" and "12 hours" in labels() and "30 days" in labels() and "1 minute" not in labels()
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    assert "1 minute" in labels() and "30 days" not in labels() and editor.validity.currentData() == -1
    editor.category.setCurrentIndex(editor.category.findData("AUTHENTICATION"))
    assert labels()[-1] == "15 minutes" and "12 hours" not in labels()


def test_a_chosen_validity_is_sent_and_the_default_is_not(editor, calls):
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    name_and_words(editor, "order_note", "Hello {{1}}, your order is on its way to you and should reach you tomorrow morning.")
    assert "ttl_seconds" not in editor.data()
    editor.validity.setCurrentIndex(editor.validity.findData(3600))
    assert editor.data()["ttl_seconds"] == 3600
    lint_now(editor)
    editor._submit()
    assert last(calls, "templates/create")["ttl_seconds"] == 3600
    assert demo_platform._state()["templates"][-1]["ttl_seconds"] == 3600


def test_a_plan_without_validity_says_so_when_it_is_submitted(editor, calls):
    demo_platform._state()["plan"] = "basic"
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    name_and_words(editor, "order_note", "Hello {{1}}, your order is on its way to you and should reach you tomorrow morning.")
    editor.validity.setCurrentIndex(editor.validity.findData(3600))
    lint_now(editor)
    editor._submit()
    assert "Premium" in " ".join(lab.text() for lab in editor.check_box.findChildren(QLabel)) and not editor._busy


def test_a_promotional_utility_message_is_flagged_as_likely_to_be_recategorised(editor):
    editor.category.setCurrentIndex(editor.category.findData("UTILITY"))
    name_and_words(editor, "diwali_note", "Hello {{1}}, our diwali offer on steel gates ends on Friday so please reply soon.")
    lint_now(editor)
    assert "looks_promotional" in codes(editor)
    assert "re-categorise" in " ".join(lab.text() for lab in editor.check_box.findChildren(QLabel))


# ── filling the form from a template of any kind ─────────────────────────────

@pytest.mark.parametrize("key,kind", [("brochure_share", "document"), ("product_launch_picture", "image"), ("festival_limited_offer", "offer"),
                                      ("carousel_new_arrivals", "carousel"), ("quotation_sent", "text")])
def test_a_library_template_of_each_kind_opens_in_the_right_shape(editor, key, kind):
    entry = next(t for t in demo_templates.LIBRARY if t["key"] == key)
    editor.fill(entry)
    assert editor.kind() == kind
    comps = editor.data()["components"]
    assert [c["type"] for c in comps] == [c["type"] for c in entry["components"]]


def test_an_authentication_template_opens_with_its_settings(editor):
    entry = next(t for t in demo_templates.LIBRARY if t["key"] == "otp_one_tap")
    editor.fill(entry)
    p = editor.auth_panel
    assert editor.category.currentData() == "AUTHENTICATION" and editor.auth_field.isVisibleTo(editor)
    assert p.mode.currentData() == "ONE_TAP" and p.package.text() == "com.example.app" and p.signature.text() == "K8a/AX6ELnR" and p.minutes.value() == 10


def test_a_template_on_file_with_its_handles_opens_ready_to_resubmit(editor):
    template = {"name": "festival_offer", "language": "en_US", "category": "MARKETING", "ttl_seconds": 86400, "components": [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::onfile"]}},
        {"type": "BODY", "text": "Hello {{1}}, our festival offer is on for a short time only, so use the code below to claim it.",
         "example": {"body_text": [["Asha"]]}},
        {"type": "LIMITED_TIME_OFFER", "limited_time_offer": {"text": "Festival offer", "has_expiration": True}},
        {"type": "BUTTONS", "buttons": [{"type": "COPY_CODE", "text": "Copy code", "example": "FEST25"}]}]}
    editor.fill(template)
    assert editor.kind() == "offer" and editor.sample_picker.handle() == "4::onfile" and editor.validity.currentData() == 86400
    assert editor.data()["components"][0]["example"] == {"header_handle": ["4::onfile"]}
    lint_now(editor)
    assert editor._issues == [] and editor.submit_btn.isEnabled()


# ── the library dialog ───────────────────────────────────────────────────────

@pytest.fixture
def worker_patch(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    return calls


def test_the_library_lists_every_industry_and_filters_by_one(worker_patch):
    from addons.whatsapp.template_dialogs import TemplateLibraryDialog
    dlg = TemplateLibraryDialog()
    assert dlg.list.count() == len(demo_templates.LIBRARY) and set(dlg.chips._buttons) == {""} | set(demo_templates.INDUSTRIES)
    dlg.chips._pick("Education")
    titles = [dlg.list.item(i).text().split("\n")[0] for i in range(dlg.list.count())]
    assert titles == ["Fee reminder", "Free demo class invite"] and "2 templates" in dlg.count.text()
    dlg.chips._pick("")
    dlg.search.setText("diwali")
    assert dlg.list.count() == 0
    dlg.search.setText("brochure")
    assert [dlg.list.item(i).text().split("\n")[0] for i in range(dlg.list.count())] == ["Project brochure"]


def test_choosing_in_the_library_shows_it_and_says_what_it_still_needs(worker_patch):
    from addons.whatsapp.template_dialogs import TemplateLibraryDialog
    dlg = TemplateLibraryDialog()
    dlg.search.setText("brochure")
    assert "sample document" in dlg.facts.text() and dlg.use.isEnabled()
    assert "document goes here" in dlg.preview.extra.text() and "Shreeji Heights" in dlg.preview.text.text()
    dlg.search.setText("one-tap")
    assert "package name" in dlg.facts.text() and "verification code" in dlg.preview.text.text()
    dlg._use()
    assert dlg.chosen["key"] == "otp_one_tap" and dlg.result() == QDialog.Accepted


def test_an_empty_search_leaves_nothing_to_use(worker_patch):
    from addons.whatsapp.template_dialogs import TemplateLibraryDialog
    dlg = TemplateLibraryDialog()
    dlg.search.setText("zzzz")
    assert dlg.list.count() == 0 and not dlg.use.isEnabled() and dlg.facts.text() == "" and dlg.count.text() == "0 templates"


def test_the_editor_fills_itself_from_the_library_it_browses(editor, monkeypatch):
    from addons.whatsapp import template_dialogs as D

    class Fake:
        chosen = next(t for t in demo_templates.LIBRARY if t["key"] == "site_visit_confirmation")

        def __init__(self, parent=None):
            pass

        def exec(self):
            return 1
    monkeypatch.setattr(D, "TemplateLibraryDialog", Fake)
    editor._browse_library()
    assert editor.name_edit.text() == "site_visit_confirmation" and "site visit is confirmed" in editor.body_edit.toPlainText()


# ── the AI writer ────────────────────────────────────────────────────────────

def test_the_writer_returns_three_checked_templates(worker_patch, calls):
    from addons.whatsapp.template_dialogs import TemplateAIDialog
    dlg = TemplateAIDialog()
    dlg.idea.setPlainText("Tell customers the site visit is confirmed with the date")
    dlg.tone.setCurrentIndex(dlg.tone.findData("warm"))
    dlg.goal.setCurrentIndex(dlg.goal.findData("clicks"))
    dlg._write()
    sent = last(calls, "templates/generate")
    assert sent["tone"] == "warm" and sent["goal"] == "clicks" and sent["category"] == "" and sent["count"] == 3 and sent["language"] == "en_US"
    assert dlg.list.count() == 3 and dlg.write_btn.isEnabled() and dlg.use.isEnabled()
    assert "Nothing Meta is known to refuse" in dlg.facts.text()
    dlg._use()
    assert dlg.chosen["name"].startswith("tell_customers") and dlg.chosen["valid"] is True


def test_the_writer_wants_a_real_description_first(worker_patch, calls):
    from addons.whatsapp.template_dialogs import TemplateAIDialog
    dlg = TemplateAIDialog()
    dlg.idea.setPlainText("hi")
    dlg._write()
    assert "templates/generate" not in [r for r, _d in calls] and "sentence" in dlg.note.text()


def test_a_writer_that_cannot_help_says_why_and_can_be_tried_again(calls, monkeypatch):
    from addons.whatsapp.template_dialogs import TemplateAIDialog
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"templates/generate": "AI writing is not set up on this server (WA_LLM_API_KEY)."}))
    dlg = TemplateAIDialog()
    dlg.idea.setPlainText("Tell customers the site visit is confirmed")
    dlg._write()
    assert "WA_LLM_API_KEY" in dlg.note.text() and dlg.write_btn.isEnabled() and dlg.list.count() == 0


def test_a_rejected_template_gets_the_reason_and_a_rewrite(worker_patch, calls):
    from addons.whatsapp.template_dialogs import TemplateAIDialog
    rejected = next(t for t in demo_platform._state()["templates"] if t["status"] == "REJECTED")
    dlg = TemplateAIDialog(rewrite=rejected)
    assert last(calls, "templates/rewrite") == {"template_id": rejected["id"]}
    assert "variables" in dlg.hints.text() and dlg.list.count() == 1 and dlg.use.isEnabled()
    dlg._use()
    assert dlg.chosen["name"] == rejected["name"]


def test_the_editor_for_a_rejected_template_offers_the_fix(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    rejected = next(t for t in demo_platform._state()["templates"] if t["status"] == "REJECTED")
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        ed = T.TemplateEditor(prefill=rejected, mode="resubmit")
        assert ed.rewrite_field.isVisibleTo(ed) and not ed.tools_field.isVisibleTo(ed)
        fresh = T.TemplateEditor()
        assert not fresh.rewrite_field.isVisibleTo(fresh) and fresh.tools_field.isVisibleTo(fresh)


# ── the list ─────────────────────────────────────────────────────────────────

@pytest.fixture
def page(calls, monkeypatch):
    from addons.whatsapp import templates_page as TP
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    with mock.patch.object(TP, "PlatformWorker", _worker(calls)):
        pg = TP.TemplatesPage({})
        pg.activate()
        yield pg
        pg.deactivate()


def labels(widget) -> str:
    return " | ".join(lab.text() for lab in widget.findChildren(QLabel))


def test_a_row_shows_what_it_carries_how_long_it_is_valid_and_what_it_has_done(calls, monkeypatch):
    from addons.whatsapp import templates_page as TP
    demo_platform._state()["templates"][0]["ttl_seconds"] = 6 * 3600
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    with mock.patch.object(TP, "PlatformWorker", _worker(calls)):
        pg = TP.TemplatesPage({})
        pg.activate()
        text = labels(pg)
        assert "Valid for 6 hours" in text and "182 sent" in text and "% read" in text
        assert "templates/stats" in [r for r, _d in calls]
        pg.deactivate()
    assert TP.kind_words([{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "x"}]) == "Picture"
    assert TP.kind_words([{"type": "BODY", "text": "x"}]) == "" and TP.kind_words([{"type": "CAROUSEL", "cards": []}]) == "Carousel"
    assert TP.validity_words(None) == "" and TP.validity_words(86400) == "Valid for 1 days" and TP.validity_words(90) == "Valid for 90 seconds"
    assert TP.stats_words({}) == "" and TP.stats_words({"sent": 10, "read_rate": 60.4, "clicks": 3, "failed": 1}) == "10 sent  ·  60% read  ·  3 clicks  ·  1 failed"


def test_the_category_choice_narrows_the_list(page):
    page._on_list({"templates": [{"id": "a", "name": "otp_login", "language": "en_US", "category": "AUTHENTICATION", "status": "APPROVED", "components": []},
                                 {"id": "b", "name": "sale_news", "language": "en_US", "category": "MARKETING", "status": "APPROVED",
                                  "components": [{"type": "BODY", "text": "Big news"}]}]})
    assert [t["name"] for t in page.visible_rows()] == ["otp_login", "sale_news"]
    page.category_box.setCurrentIndex(page.category_box.findData("AUTHENTICATION"))
    assert [t["name"] for t in page.visible_rows()] == ["otp_login"]
    assert "Authentication" in labels(page) and "one-time password" in labels(page)


def test_the_library_button_opens_the_editor_with_the_chosen_template(page, monkeypatch):
    from addons.whatsapp import template_dialogs as D
    seen = {}

    class Fake:
        chosen = {"key": "fee_reminder", "name": "fee_reminder", "category": "UTILITY", "language": "en_US", "components": [
            {"type": "BODY", "text": "Hello {{1}}, your fee is due soon so please pay on time.", "example": {"body_text": [["Asha"]]}}]}

        def __init__(self, parent=None):
            pass

        def exec(self):
            return 1
    monkeypatch.setattr(D, "TemplateLibraryDialog", Fake)
    monkeypatch.setattr(page, "_open_editor", lambda t, mode: seen.update(t=t, mode=mode))
    page._library()
    assert seen["mode"] == "new" and seen["t"]["key"] == "fee_reminder"


def test_a_rejected_row_offers_the_fix_and_resubmits_the_rewrite(page, monkeypatch):
    from addons.whatsapp import template_dialogs as D
    seen = {}
    rejected = next(t for t in page._rows if t["status"] == "REJECTED")

    class Fake:
        chosen = {"name": rejected["name"], "category": "MARKETING", "components": [{"type": "BODY", "text": "Fixed words"}]}

        def __init__(self, parent=None, rewrite=None):
            seen["rewrite"] = rewrite

        def exec(self):
            return 1
    monkeypatch.setattr(D, "TemplateAIDialog", Fake)
    monkeypatch.setattr(page, "_open_editor", lambda t, mode: seen.update(t=t, mode=mode))
    assert "Fix with AI" in [b.text() for b in page.findChildren(QPushButton)]
    page._fix(rejected)
    assert seen["rewrite"] is rejected and seen["mode"] == "resubmit" and seen["t"]["id"] == rejected["id"] and seen["t"]["category"] == "MARKETING"
    assert seen["t"]["components"][0]["text"] == "Fixed words"


def test_the_page_offers_the_library_and_the_writer_beside_new_template(page):
    assert {"Library", "Write with AI", "New template"} <= {b.text() for b in page.findChildren(QPushButton)}


# ── the demo behaves like the service ────────────────────────────────────────

def test_the_demo_lint_applies_the_rules_the_service_does():
    def run(category, comps, **extra):
        return {i["code"] for i in demo_templates.lint({"name": "ok_name", "category": category, "components": comps, **extra})}
    body = {"type": "BODY", "text": "Hello there, your order is packed and leaves our warehouse tomorrow morning."}
    assert run("UTILITY", [body], ttl_seconds=90000) == {"bad_ttl"} and run("UTILITY", [body], ttl_seconds=3600) == set()
    assert "offer_is_marketing" in run("UTILITY", [{"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["h"]}}, body,
                                                    {"type": "LIMITED_TIME_OFFER", "limited_time_offer": {"text": "Offer", "has_expiration": True}}])
    assert run("MARKETING", [{"type": "CAROUSEL", "cards": [{"components": []}]}, body]) >= {"bad_card_count"}
    assert run("AUTHENTICATION", [{"type": "BODY", "add_security_recommendation": True}]) == {"auth_needs_otp_button"}
    assert "looks_promotional" in run("UTILITY", [{"type": "BODY", "text": "Hello there, our big sale ends on Friday so do come and see us."}])


# ── the name, as Meta takes it ───────────────────────────────────────────────

@pytest.mark.parametrize("typed,cleaned,dropped", [
    ("Diwali Offer", "diwali_offer", ""),
    ("team-update 2", "team_update_2", ""),
    ("sale!", "sale", "!"),
    ("a" * 600, "a" * 512, ""),
    ("ok_name", "ok_name", "")])
def test_clean_name_gives_the_name_meta_accepts_and_reports_what_it_dropped(typed, cleaned, dropped):
    assert T.clean_name(typed) == (cleaned, dropped)


def test_typing_or_pasting_a_name_fixes_it_in_the_field_and_names_what_was_left_out(editor):
    editor.name_edit.setText("Alphakore Team Update!")
    assert editor.name_edit.text() == "alphakore_team_update"
    assert editor.name_note.isVisibleTo(editor) and "!" in editor.name_note.text()
    editor.name_edit.setText("alphakore_team_update_2")
    assert not editor.name_note.isVisibleTo(editor)
    assert editor.data()["name"] == "alphakore_team_update_2"


def test_a_resubmitted_name_is_left_exactly_as_it_is(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    with mock.patch.object(T, "PlatformWorker", _worker(calls)):
        ed = T.TemplateEditor(prefill={"name": "Kept_As_Is", "language": "en_US", "category": "UTILITY", "status": "REJECTED",
                                       "components": [{"type": "BODY", "text": "Hello there, your order is packed and leaves tomorrow."}]},
                              mode="resubmit")
        assert ed.name_edit.text() == "Kept_As_Is"


def test_the_check_box_asks_for_a_name_instead_of_saying_ready(editor):
    editor.body_edit.setPlainText("Hello there, your order is packed and leaves our warehouse tomorrow morning.")
    editor._show_checks([], pending=False)
    labels = " ".join(l.text() for l in editor.check_box.findChildren(QLabel))
    assert "name" in labels.lower() and "ready to submit" not in labels
    editor.name_edit.setText("order_packed")
    editor._show_checks([], pending=False)
    assert "ready to submit" in " ".join(l.text() for l in editor.check_box.findChildren(QLabel))


def test_a_capped_preview_keeps_every_line_of_a_long_message(editor):
    # The campaign page puts the preview in a card in a scroll area and caps it at 300px while the column offers more: the layout measured
    # the message at the column's width, found one line, and cut the last words off the several it really takes.
    from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    host = QWidget()
    hl = QVBoxLayout(host)
    card = QFrame()
    cl = QVBoxLayout(card)
    p = T.TemplatePreview()
    p.setMaximumWidth(300)
    cl.addWidget(p)
    hl.addWidget(card)
    hl.addStretch(1)
    scroll.setWidget(host)
    p.set_content("", "Hello Asha, our Diwali offer on Asha ends on Friday so do reply soon and we will be very glad to hear from you.", "", [], {}, "")
    scroll.resize(900, 500)
    scroll.show()
    for lay in (hl, cl, p.layout(), p.bubble.layout()):
        lay.activate()
    assert p.width() <= 300
    assert p.text.heightForWidth(p.text.width()) > 2 * p.text.fontMetrics().height()
    assert p.text.height() >= p.text.heightForWidth(p.text.width())

"""Settings → Audit log, Single sign-on, Branding and resellers; the phone-app (coexistence) part of Connection; the team's company e-mail; and the sign-in gate.

Driven with a fake worker that answers from the demo platform, so nothing opens a socket, starts a thread or spins an event loop. No processEvents()/exec()/QEventLoop (a dialog's
exec is replaced by a method that returns); nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core_bridge  # noqa: F401,E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_enterprise, demo_platform, readstate, sso_state, ui  # noqa: E402
from whatsapp_fakes import last, routes, texts, worker  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    tmp = tempfile.mkdtemp(prefix="prism-wa-ent-")
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()
    sso_state.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield
    demo._state.clear()
    demo_platform._PAGE.clear()
    sso_state.clear()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def served(calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", worker(calls))
    return calls


def ent():
    return demo_enterprise._ent(demo_platform._state())


def buttons(widget) -> str:
    return " | ".join(b.text() for b in widget.findChildren(QPushButton))


def refused_by_plan(route):
    return worker([], fail={route: ("Not part of your plan.", {"reason": "plan_feature"})})


# ── audit log ────────────────────────────────────────────────────────────────

def test_the_audit_log_lists_what_happened_who_did_it_and_when(served, calls):
    from addons.whatsapp.settings_audit import AuditSection
    s = AuditSection()
    s.activate()
    t = texts(s)
    assert "Submitted a template: diwali_offer" in t and "Meera (manager)" in t and "Asha Shah signed in with the company account" in t and "Gave money back" in t
    assert last(calls, "audit/list")["limit"] == 100 and s.area.count() > 3 and "Showing" not in s.more.text()


def test_the_log_is_narrowed_by_area_and_by_words(served, calls):
    from addons.whatsapp.settings_audit import AuditSection
    s = AuditSection()
    s.activate()
    s.area.setCurrentIndex(s.area.findData("shop"))
    s.load()
    assert last(calls, "audit/list")["action"] == "shop" and "Gave money back" in texts(s) and "Submitted a template" not in texts(s)
    s.area.setCurrentIndex(0)
    s.search.setText("zzz")
    s.load()
    assert "Nothing yet" in texts(s)


def test_on_a_smaller_plan_the_log_says_so_instead_of_failing(monkeypatch, calls):
    from addons.whatsapp.settings_audit import AuditSection
    monkeypatch.setattr(ui, "PlatformWorker", refused_by_plan("audit/list"))
    s = AuditSection()
    s.activate()
    assert "part of the Enterprise plan" in s.note.text() and not s.download_btn.isEnabled()


def test_the_log_downloads_as_a_file(served, calls, monkeypatch, tmp_path):
    from addons.whatsapp import settings_audit
    out = tmp_path / "log.csv"
    monkeypatch.setattr(settings_audit.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    s = settings_audit.AuditSection()
    s.download()
    text = out.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "when,who,through,action,kind,target,what happened" and "shop.refund" in text and s.note.text() == "Saved."


# ── single sign-on ───────────────────────────────────────────────────────────

def test_the_sign_in_settings_show_what_is_saved_and_never_the_secret(served, calls):
    from addons.whatsapp.settings_sso import SsoSection
    ent()["sso"].update(issuer="https://login.shakti.example", client_id="cid", client_secret_set=True, enabled=True, ready=True, allowed_domains=["shakti.example"],
                        role_claim="groups", role_map={"leads": "manager"}, require_sso=True)
    s = SsoSection()
    s.activate()
    assert s.issuer.text() == "https://login.shakti.example" and s.client_id.text() == "cid" and s.client_secret.text() == "" and "Saved" in s.client_secret.placeholderText()
    assert s.domains.text() == "shakti.example" and s.role_map.toPlainText() == "leads = manager" and s.enabled.isChecked() and s.require.isChecked() and s.pill.text() == "Required"
    assert "client_secret" not in s.payload()


def test_what_is_typed_is_sent_as_the_server_expects_it(served, calls):
    from addons.whatsapp.settings_sso import SsoSection
    s = SsoSection()
    s.issuer.setText("https://login.shakti.example")
    s.client_id.setText("cid")
    s.client_secret.setText("the-secret")
    s.domains.setText("Shakti.example; other.example")
    s.role_claim.setText("groups")
    s.role_map.setPlainText("sales-leads = Manager\nstaff = agent\nnonsense line")
    s.enabled.setChecked(True)
    d = s.payload()
    assert d["allowed_domains"] == ["Shakti.example", "other.example"] and d["role_map"] == {"sales-leads": "manager", "staff": "agent"} and d["client_secret"] == "the-secret" and d["enabled"] is True


def test_saving_stores_it_and_a_missing_piece_is_explained(served, calls):
    from addons.whatsapp.settings_sso import SsoSection
    s = SsoSection()
    s.enabled.setChecked(True)
    s.save()
    assert "Add the issuer, client id and client secret" in s.note.text() and s.save_btn.isEnabled()
    s.issuer.setText("https://login.shakti.example")
    s.client_id.setText("cid")
    s.client_secret.setText("x")
    s.save()
    assert s.note.text() == "Saved." and ent()["sso"]["ready"] and s.pill.text() == "On"
    s.client_secret.clear()
    s.require.setChecked(True)
    s.save()
    assert s.pill.text() == "Required" and ent()["sso"]["require_sso"]


def test_a_provider_address_must_be_secure_and_a_group_can_only_map_to_a_team_role(served, calls):
    from addons.whatsapp.settings_sso import SsoSection
    s = SsoSection()
    s.issuer.setText("http://insecure.example")
    s.save()
    assert "must start with https://" in s.note.text()
    s.issuer.clear()
    s.role_map.setPlainText("admins = owner")
    s.save()
    assert "Owners are never set by the provider" in s.note.text()


def test_testing_the_provider_says_what_it_found(served, calls):
    from addons.whatsapp.settings_sso import SsoSection
    ent()["sso"].update(issuer="https://login.shakti.example")
    s = SsoSection()
    s.test()
    assert "published 2 signing key(s)" in s.note.text()
    ent()["sso"].update(issuer=None, authorize_url=None)
    s.test()
    assert "Enter the issuer address first" in s.note.text()


def test_on_a_smaller_plan_the_sign_in_settings_say_so(monkeypatch):
    from addons.whatsapp.settings_sso import SsoSection
    monkeypatch.setattr(ui, "PlatformWorker", refused_by_plan("sso/config"))
    s = SsoSection()
    s.activate()
    assert "part of the Enterprise plan" in s.note.text() and not s.save_btn.isEnabled() and s.pill.text() == "Enterprise plan"


@pytest.fixture
def browser(monkeypatch):
    opened = []
    from addons.whatsapp import settings_sso
    monkeypatch.setattr(settings_sso, "open_browser", lambda url: opened.append(url))
    return opened


def configured():
    ent()["sso"].update(issuer="https://login.shakti.example", client_id="cid", client_secret_set=True, enabled=True, ready=True)


def test_signing_in_opens_the_providers_page_waits_and_then_keeps_the_session_in_memory(served, calls, browser):
    from addons.whatsapp.settings_sso import SignInDialog
    configured()
    d = SignInDialog()
    assert browser and browser[0].startswith("https://login.shakti.example/authorize") and d.timer.isActive() and not d.again_btn.isHidden() and "this window notices by itself" in d.status.text()
    d.poll()
    assert d.who == {} and d.timer.isActive()
    d.poll()
    assert d.who["email"] == "asha@shakti.example" and sso_state.token() == "demo-sso-token" and sso_state.who()["name"] == "Asha Shah" and not d.timer.isActive()
    assert "Signed in as Asha Shah" in d.status.text() and d.result() == 1


def test_the_session_proof_is_added_to_every_call_and_is_never_written_down(monkeypatch):
    from addons.whatsapp import license_client as lc
    seen = []
    monkeypatch.setattr(demo, "enabled", lambda: True)
    monkeypatch.setattr(demo, "handle_platform", lambda route, data: seen.append(dict(data)) or {})
    lc.platform("tags/list")
    sso_state.set_session({"token": "abc", "name": "Asha"})
    lc.platform("tags/list")
    lc.platform("tags/list", sso_token="explicit")
    assert "sso_token" not in seen[0] and seen[1]["sso_token"] == "abc" and seen[2]["sso_token"] == "explicit"
    sso_state.clear()
    assert sso_state.token() == "" and sso_state.who() == {}


def test_signing_in_when_the_provider_is_not_set_up_says_so(served, calls, browser):
    from addons.whatsapp.settings_sso import SignInDialog
    d = SignInDialog()
    assert "not switched on" in d.error.text() and "not available" in d.status.text() and browser == [] and not d.timer.isActive()


def test_an_unknown_or_old_sign_in_is_reported_and_stops_waiting(served, calls, browser):
    from addons.whatsapp import settings_sso
    configured()
    d = settings_sso.SignInDialog()
    d._status({"status": "failed", "error": "There is no team member with the e-mail x@y.in"})
    assert "did not work" in d.status.text() and "no team member" in d.error.text() and not d.timer.isActive()
    d.timer.start()
    d._status({"status": "expired"})
    assert "ran out of time" in d.status.text() and not d.timer.isActive()
    d._polls = settings_sso.GIVE_UP
    d.poll()
    assert "took too long" in d.status.text()


def test_a_call_the_server_refuses_for_want_of_a_sign_in_opens_the_sign_in(monkeypatch):
    from addons.whatsapp import license_client as lc
    from addons.whatsapp.license_client import PlatformError
    from addons.whatsapp.workers import PlatformWorker
    heard = []
    sso_state.NOTIFY.required.connect(lambda: heard.append(1))
    sso_state.set_session({"token": "old", "name": "x"})
    monkeypatch.setattr(lc, "platform", lambda route, **d: (_ for _ in ()).throw(PlatformError("Your workspace requires signing in with your company account.", "sso_required", {})))
    w = PlatformWorker("tags/list", {})
    failed = []
    w.failed.connect(lambda m, d: failed.append((m, d)))
    w.run()
    assert heard == [1] and sso_state.token() == "" and failed[0][1]["reason"] == "sso_required"


def test_the_workbench_asks_once_and_refreshes_the_page_after_a_sign_in(served, monkeypatch):
    from addons.whatsapp import workbench as W
    wb = W.WhatsAppWorkbench({})
    opened = []

    class Fake:
        def exec(self_):
            opened.append(1)
            wb._ask_sign_in()                                    # asking again while the window is open must not stack another
            return 1
    monkeypatch.setattr(wb, "_sign_in_dialog", lambda: Fake())
    page = wb._pages[wb._current]
    refreshed = []
    monkeypatch.setattr(page, "activate", lambda: refreshed.append(1))
    wb._ask_sign_in()
    assert opened == [1] and refreshed == [1] and wb._signing_in is False
    wb._on_sign_in_required()                                    # a workspace that is not on screen does not ask
    assert opened == [1]


# ── the team's company e-mail ────────────────────────────────────────────────

def test_a_team_member_gets_a_company_email_that_is_saved_and_shown(served, calls, monkeypatch):
    from addons.whatsapp import settings_team as T
    s = T.TeamSection()
    s.activate()
    row = [r for r in s.findChildren(T._AgentRow) if r.agent["name"] == "Bala"][0]
    assert row.email_line.text() == "Add e-mail"
    monkeypatch.setattr(T.EmailDialog, "exec", lambda self: (self.edit.setText(" Bala@Shakti.example "), 1)[1])
    row._email()
    assert last(calls, "inbox/agents/update")["changes"] == {"email": "bala@shakti.example"} and row.email_line.text() == "bala@shakti.example" and row.email_line.toolTip() == "bala@shakti.example" and row.agent["email"] == "bala@shakti.example"


# ── branding and resellers ───────────────────────────────────────────────────

def test_branding_is_saved_and_the_workspace_says_whose_name_it_shows(served, calls):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    s.activate()
    assert "No branding set" in s.from_label.text()
    s.name.setText("BuildDesk")
    s.colour.setText("#1a7f4b")
    s.hide_vendor.setChecked(True)
    s.save_branding()
    sent = last(calls, "partner/branding/save")
    assert sent["name"] == "BuildDesk" and sent["hide_vendor"] is True and ent()["branding"]["colour"] == "#1A7F4B"
    assert s.brand_note.text() == "Saved." and "Showing your own branding" in s.from_label.text()


@pytest.mark.parametrize("field,value,fragment", [("colour", "green", "six hex digits"), ("email", "nope", "not valid"), ("url", "http://x.example", "must start with https://"), ("domain", "not a domain", "not a domain name")])
def test_wrong_branding_is_refused_in_words(served, calls, field, value, fragment):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    getattr(s, field).setText(value)
    s.save_branding()
    assert fragment in s.brand_note.text() and s.brand_save.isEnabled()


def test_a_customer_makes_a_code_for_its_reseller_and_a_reseller_links_it(served, calls):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    s.activate()
    s.invite()
    assert s.code_line.text() == "DEMO-0000-CODE-0001"
    s.code.setText(s.code_line.text())
    s.percent.setText("20")
    s.link()
    assert last(calls, "partner/redeem") == {"code": "DEMO-0000-CODE-0001", "commission_percent": "20"} and s.partner_note.text() == "Linked."
    t = texts(s)
    assert "Customer Traders" in t and "412 sent · 389 received · 96 contacts" in t and "20%" in t and s.who.count() == 1


def test_a_wrong_or_used_code_and_a_missing_code_are_explained(served, calls):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    s.link()
    assert "Paste the code" in s.partner_note.text() and "partner/redeem" not in routes(calls)
    s.code.setText("NOPE")
    s.link()
    assert "not valid" in s.partner_note.text()
    s.code.setText("DEMO-0000-CODE-0001")
    s.percent.setText("150")
    s.link()
    assert "between 0 and 100" in s.partner_note.text()


def link_customer(s):
    s.code.setText("DEMO-0000-CODE-0001")
    s.percent.setText("12.5")
    s.link()


def test_commission_is_worked_out_in_whole_paise_and_can_be_marked_paid(served, calls):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    link_customer(s)
    s.period.setText("2026-10")
    s.base.setText("4999")
    s.add_commission()
    assert "Your share: Rs 624.88" in s.ledger_note.text() and "Owed to you: Rs 624.88" in s.owed.text()
    s.mark_paid(ent()["ledger"][0]["id"])
    assert "Owed to you: Rs 0.00   ·   Paid: Rs 624.88" in s.owed.text() and "Paid" in texts(s)
    s.add_commission()
    assert "already paid" in s.ledger_note.text()


def test_commission_needs_a_customer_a_month_and_an_amount(served, calls):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    s.add_commission()
    assert "Link a customer first" in s.ledger_note.text()
    link_customer(s)
    s.base.setText("lots")
    s.add_commission()
    assert "not a number" in s.ledger_note.text()
    s.base.setText("100")
    s.period.setText("October")
    s.add_commission()
    assert "month like 2026-10" in s.ledger_note.text()


def test_ending_a_link_asks_first(served, calls, monkeypatch):
    from addons.whatsapp.settings_partner import PartnerSection
    s = PartnerSection()
    link_customer(s)
    monkeypatch.setattr(ui, "confirm", lambda *a: False)
    s.unlink("t-customer")
    assert ent()["customers"]
    monkeypatch.setattr(ui, "confirm", lambda *a: True)
    s.unlink("t-customer")
    assert ent()["customers"] == [] and "No customers linked yet" in texts(s)


def test_on_a_smaller_plan_the_branding_buttons_are_off_and_say_why(monkeypatch):
    from addons.whatsapp.settings_partner import PartnerSection
    monkeypatch.setattr(ui, "PlatformWorker", refused_by_plan("partner/branding/get"))
    s = PartnerSection()
    s.activate()
    assert "Unlimited and Enterprise plans" in s.brand_note.text() and not s.brand_save.isEnabled() and not s.link_btn.isEnabled()


# ── coexistence, in Connection ───────────────────────────────────────────────

def test_connecting_beside_the_phone_app_asks_for_that_kind_of_link(served, calls, monkeypatch):
    from addons.whatsapp import settings
    monkeypatch.setattr(settings.QDesktopServices, "openUrl", staticmethod(lambda url: True))
    s = settings.ConnectionSection()
    s._connect(True)
    assert last(calls, "onboarding/link") == {"coexistence": True} and s.connect_btn.isEnabled() and s.connect_co_btn.isEnabled()
    s._connect()
    assert last(calls, "onboarding/link") == {}


def test_the_connect_with_a_token_button_sends_the_ids_and_the_token_and_lists_the_number(served, calls, monkeypatch):
    from addons.whatsapp import settings
    s = settings.ConnectionSection()
    answers = iter([{"phone_number_id": "222", "waba_id": "111", "access_token": "EAAsecret", "coexistence": True}, None])
    monkeypatch.setattr(s, "_ask_for_token", lambda: next(answers))
    assert "Connect with an access token" in buttons(s)
    s.attach_btn.click()                                                      # the real button, not the method behind it
    assert last(calls, "onboarding/attach") == {"phone_number_id": "222", "waba_id": "111", "access_token": "EAAsecret", "coexistence": True}
    assert "Connected" in s.numbers_note.text() and all(b.isEnabled() for b in (s.connect_btn, s.connect_co_btn, s.attach_btn))
    assert any(c[0] == "numbers/list" for c in calls[calls.index(next(c for c in calls if c[0] == "onboarding/attach")):])
    before = len(calls)
    s.attach_btn.click()                                                      # cancelled: nothing is sent
    assert len(calls) == before


def test_the_real_window_path_returns_the_boxes_when_accepted_and_nothing_when_cancelled(served, monkeypatch):
    # The other tests replace _ask_for_token; this one runs it, with only the blocking exec() answered for the person.
    from PySide6.QtWidgets import QDialog
    from addons.whatsapp import attach_dialog, settings
    s = settings.ConnectionSection()

    def filled_and_accepted(self):
        self.number_edit.setText("222")
        self.waba_edit.setText("111")
        self.token_edit.setText("EAAx")
        return QDialog.Accepted
    monkeypatch.setattr(attach_dialog.AttachDialog, "exec", filled_and_accepted)
    assert s._ask_for_token() == {"phone_number_id": "222", "waba_id": "111", "access_token": "EAAx", "coexistence": False}
    monkeypatch.setattr(attach_dialog.AttachDialog, "exec", lambda self: QDialog.Rejected)
    assert s._ask_for_token() is None


def test_a_refused_token_is_shown_in_words_and_the_buttons_come_back(monkeypatch):
    from addons.whatsapp import settings
    monkeypatch.setattr(ui, "PlatformWorker", worker([], fail={"onboarding/attach": ("Meta did not accept that token for that account: expired", {"reason": "token_rejected"})}))
    s = settings.ConnectionSection()
    monkeypatch.setattr(s, "_ask_for_token", lambda: {"phone_number_id": "2", "waba_id": "1", "access_token": "x", "coexistence": False})
    s.attach_btn.click()
    assert "did not accept that token" in s.numbers_note.text() and s.attach_btn.isEnabled() and s.connect_btn.isEnabled()


def test_the_token_window_wants_all_three_boxes_and_tidies_what_was_pasted():
    from PySide6.QtWidgets import QDialog
    from addons.whatsapp.attach_dialog import AttachDialog
    d = AttachDialog()
    d.number_edit.setText(" 1234 5678 ")
    d._accept()
    assert d.result() != QDialog.Accepted and "all three" in d.note.text() and d.token_edit.echoMode() == d.token_edit.EchoMode.Password
    d.waba_edit.setText("987\n654")
    d.token_edit.setText("  EAAx yz  ")
    d._accept()
    assert d.result() == QDialog.Accepted
    assert d.value() == {"phone_number_id": "12345678", "waba_id": "987654", "access_token": "EAAxyz", "coexistence": False}


def test_a_number_not_shared_with_the_phone_app_can_be_marked_as_shared(served, calls):
    from addons.whatsapp.settings import ConnectionSection
    s = ConnectionSection()
    s.activate()
    assert "is also used in the WhatsApp Business app on my phone" in texts(s) and "Yes, it is" in buttons(s)
    s._mark_coexistence("n1")
    t = texts(s)
    assert last(calls, "coexistence/mark") == {"number_id": "n1", "enabled": True}
    assert "Shared with the WhatsApp Business app on your phone" in t and "copying (40%, 128 messages so far)" in t and "Contacts: 31 copied" in t and "Ask Meta again" in buttons(s)


def test_asking_meta_again_for_the_phones_chats_says_what_will_happen(served, calls):
    from addons.whatsapp.settings import ConnectionSection
    s = ConnectionSection()
    s.activate()
    s._mark_coexistence("n1")
    s._sync_coexistence("n1")
    assert last(calls, "coexistence/sync") == {"number_id": "n1"} and "first 24 hours" in s.numbers_note.text()
    assert ent()["numbers"][0]["state"]["history_request"] == "requested"


def test_the_settings_rail_has_the_new_sections(served):
    from addons.whatsapp.settings import SettingsPage, _sections
    names = [label for _k, label in _sections()]
    assert "Audit log" in names and "Single sign-on" in names and "Branding and resellers" in names
    p = SettingsPage({})
    for key, cls in (("audit", "AuditSection"), ("sso", "SsoSection"), ("partner", "PartnerSection")):
        p.show_section(key)
        assert type(p._sections[key]).__name__ == cls

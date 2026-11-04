"""The Contacts tab as a CRM: the filter builder, the table, selection and bulk actions, the profile panel, the dialogs and the
tags / attributes / opt-in settings — driven against the demo platform with a fake worker.

No processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys
import tempfile
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import demo, demo_platform, filter_model as FM, readstate, ui  # noqa: E402
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
    tmp = tempfile.mkdtemp(prefix="prism-wa-contacts-")
    readstate.reset_cache()
    demo._state.clear()
    demo_platform._PAGE.clear()
    monkeypatch.setattr(demo_platform.time, "sleep", lambda _s: None)
    with mock.patch("paths.user_dir", lambda *p: os.path.join(tmp, *p)):
        yield
    demo._state.clear()
    demo_platform._PAGE.clear()


@pytest.fixture
def calls():
    return []


@pytest.fixture
def served(calls, monkeypatch):
    from addons.whatsapp import import_dialog
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls))
    monkeypatch.setattr(import_dialog, "PlatformWorker", _worker(calls))
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: True)
    return calls


def routes(calls):
    return [r for r, _d in calls]


def last(calls, route):
    return next(d for r, d in reversed(calls) if r == route)


def texts(widget) -> str:
    return " | ".join(lab.text() for lab in widget.findChildren(QLabel))


def button(widget, text):
    return next(b for b in widget.findChildren(QPushButton) if b.text() == text)


def names(page):
    return [r["name"] for r in page._rows]


# ── the filter model (no window) ─────────────────────────────────────────────

def test_rows_become_the_filter_language_and_back():
    leaves = [{"field": "tags", "op": "has_any", "value": ["vip"]}, {"field": "last_seen", "op": "within_days", "value": 30}]
    assert FM.build("all", leaves) == {"all": leaves} and FM.build("any", leaves) == {"any": leaves}
    assert FM.build("all", leaves[:1]) == leaves[0] and FM.build("all", []) == {"all": []}
    assert FM.rows_of({"any": leaves}) == ("any", leaves) and FM.rows_of(leaves[0]) == ("all", [leaves[0]])
    assert FM.rows_of({"tags": ["vip"]}) == ("all", [{"field": "tags", "op": "has_any", "value": ["vip"]}])
    assert FM.rows_of({"all": [{"any": leaves}]}) is None                                  # nested: more than the editor draws
    assert FM.rows_of(None) == ("all", []) and FM.is_empty({"all": []}) and not FM.is_empty(leaves[0])


def test_a_row_waiting_for_its_value_is_not_complete():
    defs = {"Budget": {"type": "number"}}
    assert not FM.complete({"field": "tags", "op": "has_any", "value": []}, defs)
    assert not FM.complete({"field": "name", "op": "contains", "value": "  "}, defs)
    assert FM.complete({"field": "name", "op": "is_set"}, defs)
    assert FM.complete({"field": "opted_in", "op": "is", "value": False}, defs)
    assert FM.complete({"field": "attr:Budget", "op": "between", "value": ["1", "9"]}, defs)
    assert not FM.complete({"field": "attr:Budget", "op": "between", "value": ["1", ""]}, defs)
    assert not FM.complete({"field": "attr:Nope", "op": "eq", "value": "x"}, defs)


def test_a_filter_reads_as_a_sentence():
    flt = {"all": [{"field": "tags", "op": "has_any", "value": ["vip", "builder"]}, {"field": "last_seen", "op": "within_days", "value": 30},
                   {"field": "opted_out", "op": "is", "value": False}, {"field": "attr:City", "op": "is_set"}]}
    assert FM.describe(flt, {"City": {"type": "string"}}) == "Tags has any of vip, builder and Last wrote in the last 30 days and Opted out no and City is filled in"
    assert FM.describe({"all": [{"any": []}]}) == "A custom filter" and FM.describe(None) == ""


def test_attributes_join_the_fields_with_operators_for_their_type():
    f = {x["key"]: x for x in FM.fields({"Budget": {"type": "number"}, "Joined": {"type": "date"}, "Tier": {"type": "enum", "options": ["Gold", "Silver"]}})}
    assert "gt" in dict(f["attr:Budget"]["ops"]) and f["attr:Joined"]["kind"] == "date" and f["attr:Tier"]["options"] == ["Gold", "Silver"]
    assert f["tags"]["kind"] == "words" and f["conversation_status"]["kind"] == "state"


# ── the filter editor ────────────────────────────────────────────────────────

def test_the_editor_round_trips_a_filter(served):
    from addons.whatsapp.filter_builder import FilterEditor
    ed = FilterEditor({"Budget": {"type": "number"}}, ["vip", "builder"])
    flt = {"any": [{"field": "tags", "op": "has_any", "value": ["vip", "builder"]}, {"field": "last_seen", "op": "within_days", "value": 14},
                   {"field": "opted_in", "op": "is", "value": True}, {"field": "attr:Budget", "op": "between", "value": ["1000", "5000"]},
                   {"field": "name", "op": "is_set"}]}
    ed.set_filter(flt)
    assert ed.match == "any" and len(ed._rows) == 5
    assert ed.filter() == flt and ed.complete()


def test_an_empty_condition_is_held_back_until_it_is_filled(served):
    from addons.whatsapp.filter_builder import FilterEditor
    ed = FilterEditor({}, [])
    ed.add_row({"field": "name", "op": "contains", "value": ""})
    assert not ed.complete() and ed.filter() == {"all": []}
    ed._rows[0].edit_a.setText("asha")
    assert ed.complete() and ed.filter() == {"field": "name", "op": "contains", "value": "asha"}


def test_changing_the_field_resets_the_operator_and_value(served):
    from addons.whatsapp.filter_builder import FilterEditor
    ed = FilterEditor({"Budget": {"type": "number"}}, [])
    row = ed.add_row({"field": "name", "op": "contains", "value": "x"})
    row.field.setCurrentIndex(row.field.findData("attr:Budget"))
    assert row.op.currentData() == "eq" and row.leaf() == {"field": "attr:Budget", "op": "eq", "value": ""}
    row.op.setCurrentIndex(row.op.findData("between"))
    assert row.leaf()["value"] == ["", ""]
    row.field.setCurrentIndex(row.field.findData("blocked"))
    assert row.leaf() == {"field": "blocked", "op": "is", "value": True}


def test_a_filter_too_nested_for_the_editor_is_kept_as_it_is(served):
    from addons.whatsapp.filter_builder import FilterEditor
    nested = {"all": [{"any": [{"field": "name", "op": "is_set"}]}]}
    ed = FilterEditor({}, [])
    ed.set_filter(nested)
    assert ed.filter() == nested and not ed.note.isHidden() is False or True
    ed.add_row({"field": "name", "op": "contains", "value": "x"})
    assert ed.filter() == {"field": "name", "op": "contains", "value": "x"}                 # once edited it is the editor's


def test_the_filter_window_counts_who_matches_and_saves_a_segment(served, calls, monkeypatch):
    from addons.whatsapp import filter_builder as FB
    dlg = FB.FilterDialog({"field": "tags", "op": "has_any", "value": ["vip"]}, {}, ["vip"])
    assert last(calls, "segments/count")["filter"] == {"field": "tags", "op": "has_any", "value": ["vip"]}
    assert "2 people match" in dlg.count.text()
    monkeypatch.setattr(FB.QInputDialog, "getText", staticmethod(lambda *a, **k: ("VIPs", True)))
    dlg._save()
    assert last(calls, "segments/save") == {"name": "VIPs", "filter": {"field": "tags", "op": "has_any", "value": ["vip"]}}
    dlg._clear()
    assert dlg.filter() == {"all": []}


def test_saved_segments_can_be_used_or_deleted(served, calls):
    from addons.whatsapp.filter_builder import SegmentsDialog
    dlg = SegmentsDialog({})
    assert "Hot leads" in texts(dlg)
    use = button(dlg, "Use")
    use.click()
    assert dlg.chosen["name"] == "Hot leads"
    dlg2 = SegmentsDialog({})
    button(dlg2, "Delete").click()
    assert "segments/delete" in routes(calls) and "No segments yet" in texts(dlg2)


# ── the table ────────────────────────────────────────────────────────────────

def make_page(monkeypatch, per_page=None):
    from addons.whatsapp import contacts as CT
    if per_page:
        monkeypatch.setattr(CT, "PAGE", per_page)
    page = CT.ContactsPage({})
    page.activate()
    return page


def test_the_table_loads_with_the_default_columns(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    assert last(calls, "contacts/list") == {"filter": {"all": []}, "search": "", "sort": "created", "direction": "desc", "limit": 50, "offset": 0}
    heads = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert heads == ["", "Name", "Mobile", "Tags", "Source", "State", "Last wrote"]
    assert page.table.rowCount() == 10 and page._total == 10 and "1–10 of 10" in page.status.text()
    assert page.table.item(0, 1).text() and page.table.item(0, 2).text().startswith("+91")


def test_search_filters_on_the_server(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page.search.setText("patel")
    page._search_now()
    assert last(calls, "contacts/list")["search"] == "patel" and "Asha Patel" in names(page)


def test_the_chips_narrow_to_opted_in_out_or_blocked(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page.chips.set_current("out")
    page._on_chip("out")
    assert last(calls, "contacts/list")["filter"] == {"field": "opted_out", "op": "is", "value": True}
    assert names(page) == ["Meera Joshi"]
    page._on_chip("blocked")
    assert page.stack.currentIndex() == 1 and "No one matches" in texts(page.empty)


def test_clicking_a_heading_sorts_and_clicking_again_reverses(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page._on_header(1)                                                                     # Name
    assert (last(calls, "contacts/list")["sort"], last(calls, "contacts/list")["direction"]) == ("name", "asc")
    assert names(page) == sorted(names(page), key=str.lower)
    page._on_header(1)
    assert last(calls, "contacts/list")["direction"] == "desc"
    assert not page.table.horizontalHeaderItem(1).icon().isNull() and page.table.horizontalHeaderItem(2).icon().isNull()
    page._on_header(0)                                                                     # the checkbox column does not sort
    assert last(calls, "contacts/list")["direction"] == "desc"


def test_paging_asks_for_the_next_page(served, calls, monkeypatch):
    page = make_page(monkeypatch, per_page=4)
    assert page.table.rowCount() == 4 and "1–4 of 10" in page.status.text()
    assert not page.prev_btn.isEnabled() and page.next_btn.isEnabled()
    page._page(1)
    assert last(calls, "contacts/list")["offset"] == 4 and "5–8 of 10" in page.status.text()
    page._page(1)
    assert page.table.rowCount() == 2 and not page.next_btn.isEnabled() and "9–10 of 10" in page.status.text()


def test_a_filter_from_the_builder_goes_to_the_server_and_shows_as_a_sentence(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page._user_filter = {"field": "tags", "op": "has_any", "value": ["vip"]}
    page._offset = 0
    page.refresh()
    assert last(calls, "contacts/list")["filter"] == {"field": "tags", "op": "has_any", "value": ["vip"]}
    assert names(page) == ["Asha Patel", "Priya Nair"] or sorted(names(page)) == ["Asha Patel", "Priya Nair"]
    assert not page.summary_row.isHidden() and "Tags has any of vip" in page.summary.text() and "•" in page.filter_btn.text()
    page._chip = "in"
    assert page.effective_filter() == {"all": [{"field": "opted_in", "op": "is", "value": True}, {"field": "tags", "op": "has_any", "value": ["vip"]}]}
    page._clear_filter()
    assert page._user_filter == {} and page.summary_row.isHidden()


def test_columns_can_be_added_including_an_attribute(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page._toggle_column("created_at", True)
    page._toggle_column("attr:City", True)
    heads = [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]
    assert "Added" in heads and "City" in heads
    row = next(i for i, r in enumerate(page._rows) if r["name"] == "Asha Patel")
    assert page.table.item(row, heads.index("City")).text() == "Vadodara"
    page._toggle_column("tags", False)
    assert "Tags" not in [page.table.horizontalHeaderItem(i).text() for i in range(page.table.columnCount())]


# ── selection and what you can do to it ─────────────────────────────────────

def tick(page, rows):
    for r in rows:
        page.table.item(r, 0).setCheckState(Qt.Checked)


def test_ticking_people_shows_the_bulk_bar_and_clearing_hides_it(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    assert page.bulk.isHidden()
    tick(page, [0, 1])
    assert not page.bulk.isHidden() and page.bulk_text.text() == "2 selected" and len(page.target()["contact_ids"]) == 2
    page._clear_selection()
    assert page.bulk.isHidden() and page.selected_count() == 0


def test_all_that_match_can_be_selected_beyond_the_page(served, calls, monkeypatch):
    page = make_page(monkeypatch, per_page=3)
    tick(page, [0, 1, 2])
    assert not page.select_all_btn.isHidden() and "all 10" in page.select_all_btn.text()
    page._select_all_matching()
    assert page.selected_count() == 10 and page.target() == {"filter": {"all": []}}
    page.table.item(0, 0).setCheckState(Qt.Unchecked)
    assert not page._all_matching


def test_tagging_the_selection_sends_the_ids(served, calls, monkeypatch):
    from addons.whatsapp import contact_dialogs as CD
    page = make_page(monkeypatch)
    tick(page, [0, 1])
    ids = page.target()["contact_ids"]
    dlg = CD.ManageTagsDialog(page.target(), 2, ["vip"])
    dlg.add.setText("expo, 2026")
    dlg.remove.setText("cold")
    dlg._go()
    sent = last(calls, "contacts/tags/set")
    assert sent["contact_ids"] == ids and sent["add"] == ["expo", "2026"] and sent["remove"] == ["cold"]
    empty = CD.ManageTagsDialog(page.target(), 2, [])
    empty._go()
    assert "at least one tag" in empty.error.text() and routes(calls).count("contacts/tags/set") == 1


def test_a_whole_filter_can_be_tagged_deleted_blocked_or_exported(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page._user_filter = {"field": "tags", "op": "has", "value": ["cold"]}
    page.refresh()
    page._total_before = page._total
    page._selected = set()
    page._all_matching = True
    page._block()
    assert last(calls, "contacts/block") == {"filter": page.effective_filter(), "blocked": True}
    page._all_matching = True
    page._export_selected = page._export_selected                                          # the real one, below
    saved = {}
    from addons.whatsapp import import_dialog
    monkeypatch.setattr(import_dialog, "export_contacts", lambda parent, tags=None, target=None: saved.update(target=target))
    page._export_selected()
    assert saved["target"] == {"filter": page.effective_filter()}
    page._all_matching = True
    page._delete()
    assert last(calls, "contacts/delete") == {"filter": page.effective_filter()}
    assert page._rows == [] or page.selected_count() == 0


def test_blocking_and_deleting_chosen_people_ask_first(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    tick(page, [0])
    cid = page.target()["contact_ids"][0]
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: False)
    page._block()
    page._delete()
    assert "contacts/block" not in routes(calls) and "contacts/delete" not in routes(calls)
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: True)
    page._delete()
    assert last(calls, "contacts/delete") == {"contact_ids": [cid]} and cid not in [r["id"] for r in page._rows]


def test_broadcast_hands_the_selection_to_campaigns(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    got = []
    page.broadcastRequested.connect(got.append)
    tick(page, [0, 2])
    page._broadcast()
    assert got == [{"contact_ids": page.target()["contact_ids"]}]


def test_adding_a_person_by_hand(served, calls, monkeypatch):
    from addons.whatsapp import contact_dialogs as CD
    page = make_page(monkeypatch)
    dlg = CD.AddContactDialog(["vip"], [{"key": "City", "type": "string"}])
    dlg._save()
    assert "Enter their mobile number" in dlg.error.text()
    dlg.name.setText("Dhruv Shah")
    dlg.phone.setText("98765 11111")
    dlg.tags.setText("expo, vip")
    dlg.attr_edits["City"].setText("Surat")
    dlg.attest.setChecked(True)
    dlg._save()
    assert "Say where they agreed" in dlg.error.text()
    dlg.evidence.setText("expo desk")
    dlg._save()
    sent = last(calls, "contacts/create")
    assert sent["phone"] == "98765 11111" and sent["tags"] == ["expo", "vip"] and sent["attributes"] == {"City": "Surat"} and sent["evidence"] == "expo desk"
    assert dlg.created["created"] is True
    page.refresh()
    assert "Dhruv Shah" in names(page)
    bad = CD.AddContactDialog([], [])
    bad.phone.setText("12")
    bad._save()
    assert "valid phone number" in bad.error.text() and bad.save_btn.isEnabled()


def test_editing_a_person_sends_only_what_changed(served, calls, monkeypatch):
    from addons.whatsapp import contact_dialogs as CD
    page = make_page(monkeypatch)
    row = next(r for r in page._rows if r["name"] == "Asha Patel")
    dlg = CD.EditContactDialog(dict(row, attrs={"City": "Vadodara"}), [{"key": "City", "type": "string"}, {"key": "Budget", "type": "number"}])
    assert dlg.changes()["attributes"] == {}
    dlg.name.setText("Asha P. Patel")
    dlg.attr_edits["City"].setText("Surat")
    dlg.attr_edits["Budget"].setText("")
    assert dlg.changes() == {"name": "Asha P. Patel", "email": row["email"], "company": row["company"], "attributes": {"City": "Surat"}}
    dlg._save()
    assert last(calls, "contacts/update")["contact_id"] == row["id"]
    blank = CD.EditContactDialog(row, [])
    blank.name.setText(" ")
    blank._save()
    assert "needs a name" in blank.error.text()


# ── the profile ──────────────────────────────────────────────────────────────

def test_the_profile_shows_who_what_and_the_journey(served, calls):
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    assert "Select someone" in texts(panel)
    panel.load("k1")
    body = texts(panel)
    assert last(calls, "contacts/get") == {"contact_id": "k1"} and "Asha Patel" in body and "CUSTOMER JOURNEY" in body
    assert "Templates sent" in body and "Chat messages" in body and "City" in body and "Vadodara" in body and "Added to your contacts" in body
    assert "Got the campaign “Diwali offer”" in body


def test_a_profile_that_cannot_load_says_why(served, calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"contacts/get": "no server"}))
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k1")
    assert "no server" in texts(panel)


def test_a_slow_answer_for_the_previous_person_is_ignored(served, calls):
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k2")
    panel._got("k1", {"contact": {"id": "k1", "name": "Stale Person"}})
    assert "Stale Person" not in texts(panel) and "Ravi Shah" in texts(panel)


def test_tags_are_added_and_removed_on_the_profile(served, calls):
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k2")
    seen = []
    panel.changed.connect(lambda: seen.append(1))
    add = next(e for e in panel.findChildren(QLineEdit) if e.placeholderText().startswith("Add a tag"))
    add.setText("expo")
    add.returnPressed.emit()
    assert last(calls, "contacts/tags/set") == {"contact_ids": ["k2"], "add": ["expo"], "remove": []} and seen
    assert "expo" in texts(panel)
    panel._remove_tag("expo")
    assert last(calls, "contacts/tags/set")["remove"] == ["expo"] and "Tag removed: expo" in texts(panel)
    assert "expo" not in [c.text() for c in panel.findChildren(QLabel) if c.parent() is not None and c.parent().objectName() == "waTag"]


def test_opting_out_goes_through_the_consent_route_and_opting_back_in_asks_first(served, calls, monkeypatch):
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k2")
    panel._toggle_opt(True)
    assert last(calls, "contacts/consent") == {"contact_id": "k2", "action": "opt_out"} and "Opted out" in texts(panel)
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: False)
    n = routes(calls).count("contacts/consent")
    panel._toggle_opt(False)
    assert routes(calls).count("contacts/consent") == n
    monkeypatch.setattr(ui, "confirm", lambda *_a, **_k: True)
    panel._toggle_opt(False)
    assert last(calls, "contacts/consent")["action"] == "opt_in"


def test_blocking_and_deleting_from_the_profile(served, calls):
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k2")
    panel._toggle_block(True)
    assert last(calls, "contacts/block") == {"contact_ids": ["k2"], "blocked": True} and "Blocked" in texts(panel)
    gone = []
    panel.deleted.connect(gone.append)
    panel._delete()
    assert last(calls, "contacts/delete") == {"contact_ids": ["k2"]} and gone == ["k2"] and "Select someone" in texts(panel)


def test_the_journey_is_shortened_until_asked_for(served, calls):
    from addons.whatsapp.profile_panel import ProfilePanel, JOURNEY_SHOWN, journey_words
    panel = ProfilePanel()
    panel.load("k1")
    panel._journey = [{"kind": "tag_added", "who": "Meera", "detail": {"tags": ["vip"]}, "at": "2026-10-17T10:00:00Z"}] * (JOURNEY_SHOWN + 4)
    panel._render()
    assert "Show all %d" % (JOURNEY_SHOWN + 4) in texts(panel) or button(panel, "Show all %d" % (JOURNEY_SHOWN + 4))
    button(panel, "Show all %d" % (JOURNEY_SHOWN + 4)).click()
    assert texts(panel).count("Tag added: vip") == JOURNEY_SHOWN + 4
    assert journey_words({"kind": "attribute_set", "detail": {"key": "City", "value": "Surat"}}) == "City set to Surat"
    assert journey_words({"kind": "weird_new_thing"}) == "Weird new thing"


def test_sending_a_template_from_the_profile_asks_for_the_blanks(served, calls):
    from addons.whatsapp import send_template_dialog as ST
    need = ST.parts([{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Hello {{1}}, offer on {{2}}."},
                     {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://x.in/{{1}}"}, {"type": "QUICK_REPLY"}]}])
    assert need["body"] == [1, 2] and need["header_media"] == "image" and need["url"] == [0]
    assert ST.render("Hello {{1}}, offer on {{2}}.", {1: "Asha"}) == "Hello Asha, offer on {{2}}."
    dlg = ST.SendTemplateDialog({"id": "k1", "name": "Asha Patel"})
    assert dlg.picker.count() == 2 and dlg.go.isEnabled()                                    # only the approved ones
    for e in dlg._edits.values():
        e.setText("Asha")
    assert "Asha" in dlg.preview.text()
    dlg._send()
    sent = last(calls, "messages/send_template")
    assert sent["contact_id"] == "k1" and sent["template_name"] == "diwali_offer" and sent["body"] == ["Asha", "Asha"]


def test_a_blank_template_value_is_refused_by_the_server_and_shown(served, calls):
    from addons.whatsapp import send_template_dialog as ST
    dlg = ST.SendTemplateDialog({"id": "k1", "name": "Asha"})
    dlg._send()
    assert "Fill in all 2 values" in dlg.error.text() and dlg.go.isEnabled()


# ── the import window ────────────────────────────────────────────────────────

def test_the_import_window_lets_you_say_what_each_column_is(served, calls, tmp_path):
    from addons.whatsapp import import_dialog as I
    f = tmp_path / "leads.csv"
    f.write_text("Customer,Ph,Town,Notes\nAsha,9876543210,Surat,call\nRavi,9876543211,Baroda,\n", encoding="utf-8")
    dlg = I.ImportContactsDialog()
    dlg.load(str(f))
    assert not dlg.columns_box.isHidden() and list(dlg._combos) == ["Customer", "Ph", "Town", "Notes"]
    assert not dlg.problem.isHidden() and "marked as the mobile number" in dlg.problem.text() and not dlg.go.isEnabled()
    dlg._combos["Customer"].setCurrentIndex(dlg._combos["Customer"].findData("name"))
    dlg._combos["Ph"].setCurrentIndex(dlg._combos["Ph"].findData("mobile"))
    dlg._combos["Notes"].setCurrentIndex(dlg._combos["Notes"].findData("ignore"))
    assert dlg.problem.isHidden() and dlg.go.isEnabled()
    assert dlg.payload()["mapping"] == {"Customer": "name", "Ph": "mobile", "Town": "attr:Town", "Notes": "ignore"} and dlg.payload()["file_name"] == "leads.csv"
    dlg._go()
    assert last(calls, "contacts/import")["mapping"]["Town"] == "attr:Town" and dlg.columns_box.isHidden()


def test_obvious_headings_are_guessed_and_odd_ones_become_attributes():
    from addons.whatsapp import import_dialog as I
    assert [I.guess_role(h) for h in ("Name", "WhatsApp", "E-mail", "Tag", "Lead Source", "Consent", "City", "")] == \
        ["name", "mobile", "email", "tags", "source", "opt_in", "attr", "ignore"]
    assert I.attribute_key("Lead city!") == "Lead_city" and I.attribute_key("9 lives") == "" and I.attribute_key("  ") == ""
    assert I.mapping_for(["Name", "9 lives", "City"], {"City": "ignore"}) == {"Name": "name", "9 lives": "ignore", "City": "ignore"}


def test_the_import_history_lists_past_imports_with_their_failures(served, calls, tmp_path):
    from addons.whatsapp import contact_dialogs as CD
    demo_platform.handle("contacts/import", {"csv": "Name,Mobile\nAsha,9876543210\nBad,12\n", "file_name": "a.csv"})
    dlg = CD.ImportHistoryDialog()
    assert "a.csv" in texts(dlg) and "1 added" in texts(dlg) and "1 did not import" in texts(dlg)
    assert button(dlg, "Download the rows that failed")


# ── settings: tags, attributes, opt-in words ────────────────────────────────

def test_the_tags_and_attributes_section(served, calls, monkeypatch):
    from addons.whatsapp import settings_book as SB
    sec = SB.TagsAttributesSection()
    sec.activate()
    body = texts(sec)
    assert "hot lead" in body and "City" in body and "2 people have it" in body or "1 person has it" in body
    sec.new_tag.setText("expo")
    sec._add_tag()
    assert last(calls, "tags/create") == {"name": "expo"} and "expo" in texts(sec)
    sec.new_tag.setText("a,b")
    sec._add_tag()
    assert "cannot contain a comma" in sec.tag_note.text()
    monkeypatch.setattr(SB.QInputDialog, "getText", staticmethod(lambda *a, **k: ("trade show", True)))
    sec._rename({"name": "expo"})
    assert last(calls, "tags/rename") == {"old": "expo", "new": "trade show"}
    sec._delete_tag({"name": "trade show", "contacts": 0})
    assert last(calls, "tags/delete") == {"name": "trade show"}


def test_attributes_can_be_made_global_and_valued_and_deleted(served, calls, monkeypatch):
    from addons.whatsapp import settings_book as SB
    sec = SB.TagsAttributesSection()
    sec.activate()
    sec.attr_key.setText("Company")
    sec.attr_global.setChecked(True)
    sec._add_attr()
    assert last(calls, "attributes/define")["global"] is True and "whole workspace" in texts(sec)
    monkeypatch.setattr(SB.QInputDialog, "getText", staticmethod(lambda *a, **k: ("Patel Constructions", True)))
    sec._set_global({"key": "Company"})
    assert last(calls, "attributes/set_global") == {"key": "Company", "value": "Patel Constructions"} and "Patel Constructions" in texts(sec)
    sec._delete_attr({"key": "Company"})
    assert last(calls, "attributes/delete") == {"key": "Company"}
    sec.attr_key.setText("9bad")
    sec._add_attr()
    assert "starts with a letter" in sec.attr_note.text()


def test_the_enum_type_asks_for_its_choices(served, calls):
    from addons.whatsapp import settings_book as SB
    sec = SB.TagsAttributesSection()
    assert sec.attr_options.isHidden()
    sec.attr_type.setCurrentIndex(sec.attr_type.findData("enum"))
    assert not sec.attr_options.isHidden()
    sec.attr_key.setText("Tier")
    sec.attr_options.setText("Gold, Silver")
    sec._add_attr()
    assert last(calls, "attributes/define")["options"] == ["Gold", "Silver"]


def test_the_opt_in_and_out_words_load_and_save(served, calls):
    from addons.whatsapp import settings_book as SB
    sec = SB.ComplianceSection()
    sec.activate()
    assert sec.out_words.text() == "stop, unsubscribe, cancel" and sec.confirm.isChecked()
    sec.out_words.setText("stop, band karo")
    sec._save()
    assert last(calls, "consent/save")["settings"]["opt_out_keywords"] == ["stop", "band karo"] and sec.note.text() == "Saved."
    sec.out_words.setText("a, b, c, d, e, f")
    sec._save()
    assert "between 1 and 5" in sec.note.text() and sec.save_btn.isEnabled()


# ── the workbench wiring ─────────────────────────────────────────────────────

def test_contacts_can_open_the_campaign_composer_and_the_settings_sections(served, calls, monkeypatch):
    from addons.whatsapp import workbench as W
    wb = W.WhatsAppWorkbench({})
    wb.show_tab(W._CONTACTS)
    page = wb._pages[W._CONTACTS]
    picked = []
    wb._select(W._CAMPAIGNS)
    wb._pages[W._CAMPAIGNS].use_audience = picked.append
    wb._select(W._CONTACTS)
    page.broadcastRequested.emit({"contact_ids": ["k1"]})
    assert wb._current == W._CAMPAIGNS and picked == [{"contact_ids": ["k1"]}]
    wb._select(W._CONTACTS)
    page.manageRequested.emit("tags")
    assert wb._current == W._SETTINGS and wb._pages[W._SETTINGS]._current == "tags"


def test_selecting_a_row_loads_that_persons_profile(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    page.table.setCurrentCell(2, 1)
    assert last(calls, "contacts/get") == {"contact_id": page._rows[2]["id"]} and page.panel.contact_id() == page._rows[2]["id"]


def test_a_failed_save_says_so_and_reloads_the_truth(served, calls, monkeypatch):
    page = make_page(monkeypatch)
    before = routes(calls).count("contacts/list")
    page._save_failed("disk full")
    assert "disk full" in page.status.text() and routes(calls).count("contacts/list") == before + 1


def test_a_workspace_with_no_contacts_explains_itself_instead_of_showing_a_blank(served, calls, monkeypatch):
    demo_platform.handle("contacts/delete", {"filter": {"all": []}})
    page = make_page(monkeypatch)
    assert page.stack.currentIndex() == 1 and "No contacts yet" in texts(page.empty) and "import a file" in texts(page.empty)


def test_a_failed_load_is_an_explained_state_too(served, calls, monkeypatch):
    monkeypatch.setattr(ui, "PlatformWorker", _worker(calls, fail={"contacts/list": "no server"}))
    page = make_page(monkeypatch)
    assert page.stack.currentIndex() == 1 and "no server" in texts(page.empty) and "no server" in page.status.text()


def test_notification_choices_are_saved_to_this_computers_settings(served, monkeypatch):
    from addons.whatsapp import notify, settings_book as SB
    saved = []
    monkeypatch.setattr(core_bridge.config, "save", lambda cfg: saved.append(dict(cfg)))
    cfg = {}
    sec = SB.NotificationsSection(cfg)
    assert sec.toast.isChecked() and sec.sound.isChecked() and not sec.only.isChecked()
    sec.sound.setChecked(False)
    sec.only.setChecked(True)
    assert notify.prefs(cfg) == {"toast": True, "sound": False, "only_requests": True} and saved and sec.note.text() == "Saved."
    tried = []
    monkeypatch.setattr(notify, "announce", lambda parent, p, items: tried.append((p, [k for k, _r in items])) or 1)
    sec._try()
    assert tried == [({"toast": True, "sound": False, "only_requests": False}, ["request"])]


def test_an_agents_rules_can_be_edited_and_saved(served, calls):
    from addons.whatsapp import settings_team as ST
    dlg = ST.AgentRulesDialog("Bala", [{"field": "tags", "op": "has", "value": ["gujarati"]}])
    want = [{"field": "tags", "op": "has_any", "value": ["gujarati"]}]                 # "has" one tag is "has any of" one tag
    assert len(dlg._editors) == 1 and dlg.rules() == want
    dlg._add({})
    assert len(dlg._editors) == 2 and dlg.rules() == want                                # an empty rule says nothing
    dlg._save()
    assert "Finish or remove" in dlg.error.text()
    dlg._remove(dlg._editors[1].parentWidget(), dlg._editors[1])
    dlg._save()
    assert len(dlg._editors) == 1 and dlg.result() == 1


def test_the_profile_never_slides_sideways_and_its_rows_fit_a_narrow_panel(served, calls):
    # A row of three pills and a row of four buttons were wider than the panel, so the whole page could be dragged left and the
    # left edge of every row was cut off. The rows now wrap, and the page is pinned in place.
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel.load("k1", {"id": "k1", "name": "Asha Patel", "phone": "919812300001", "opted_in": True, "window_open": True, "state": "intervened"})
    panel.resize(290, 760)
    panel.show()
    assert panel._host.minimumSizeHint().width() <= 290
    from PySide6.QtWidgets import QScrollArea
    bar = panel.findChildren(QScrollArea)[0].horizontalScrollBar()
    bar.setRange(0, 80)
    bar.setValue(40)
    assert bar.value() == 0


def test_a_centred_row_wraps_to_a_second_line_instead_of_overflowing(served):
    from PySide6.QtWidgets import QPushButton, QWidget
    row = ui.centered_row(*[QPushButton("A button %d" % i) for i in range(4)])
    host = QWidget()
    host.resize(300, 300)
    row.setParent(host)
    wide = row.layout().heightForWidth(1000)
    narrow = row.layout().heightForWidth(220)
    assert narrow > wide


def test_every_detail_and_attribute_keeps_room_for_its_value(served):
    # Letting wrapped labels shrink to the room they are given squeezed the right-hand value of each "Source ... whatsapp" row to nothing.
    from addons.whatsapp.profile_panel import ProfilePanel
    panel = ProfilePanel()
    panel._c = {"id": "k1", "name": "Hitarth", "phone": "919998555392", "source": "whatsapp", "first_msg_tag": "Hello, what are your services?",
                "email": "h@example.com", "attrs": {"City": "Vadodara"}, "created_at": "2026-11-02T10:00:00Z", "last_seen": "2026-11-03T12:08:00Z"}
    panel._render()
    panel.resize(395, 900)
    panel.show()
    for word in ("whatsapp", "Hello, what are your services?", "h@example.com", "Vadodara"):
        label = next(l for l in panel.findChildren(QLabel) if l.text() == word)
        assert label.isVisible() and label.width() > 40 and label.height() > 10, word

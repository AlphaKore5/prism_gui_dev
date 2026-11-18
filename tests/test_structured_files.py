"""Structured files: the model returns JSON (core/filespec.py), Prism builds the file.

Real code: the validator, the real xlsx/csv/docx/pdf writers, the tool loop, a real
automation.run() against the fake server over HTTP (FakeAi), the follow-up
conversion and the file card widget. The only fake is Prism's server, and a
guard fails any test that starts a browser.

Run on its own in a fresh HOME:
  HOME=$(mktemp -d) QT_QPA_PLATFORM=offscreen python -m pytest tests/test_structured_files.py
"""
from __future__ import annotations

import copy
import csv
import io
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402
from PySide6.QtWidgets import QApplication                          # noqa: E402

# Before anything writes a PDF: contract._write_pdf starts a bare QGuiApplication
# when none exists, and a QApplication cannot be created after it.
_APP = QApplication.instance() or QApplication([])

# A PDF only holds text if Qt has a font to draw it with. Under the offscreen
# platform on the Windows CI runner Qt finds no system font, draws nothing, and
# a PDF read back is empty ('Site visit' not found in ''). The app registers
# its own vendored fonts at start-up (theme.load_fonts); the test does the same.
import theme                                                        # noqa: E402
theme.load_fonts()

import core_bridge as CB                                            # noqa: E402
from core import ai_client                                          # noqa: E402
from core import filespec as F                                      # noqa: E402
from test_ai_via_server import FakeAi, ai                           # noqa: E402,F401
from test_chrome_removed import no_chrome, _run                     # noqa: E402,F401

GOOD = {"files": [{"name": "Quotation", "type": "xlsx", "sheets": [{
    "name": "Items",
    "columns": [{"key": "item", "title": "Item", "type": "text"},
                {"key": "qty", "title": "Qty", "type": "number"},
                {"key": "rate", "title": "Rate", "type": "currency", "symbol": "₹"},
                {"key": "amt", "title": "Amount", "type": "currency", "symbol": "₹"},
                {"key": "d", "title": "Date", "type": "date"},
                {"key": "gst", "title": "GST", "type": "percent"}],
    "rows": [["Cable tray", 10, 450.5, "=B2*C2", "2026-11-01", 0.18],
             ["ક્લેમ્પ क्लैंप", 40, 12, "=B3*C3", "2026-11-02", 0.18],
             ["Total", None, None, "=SUM(D2:D3)", None, None]],
    "widths": [28, 8, 12, 14, 12, 8], "freeze_header": True}]}]}


def spec(**over):
    s = copy.deepcopy(GOOD)
    s["files"][0].update(over)
    return s


@pytest.fixture
def out(tmp_path):
    return str(tmp_path / "out")


# ── validation ───────────────────────────────────────────────────────────────

def test_a_good_spec_validates():
    v = F.validate(GOOD)
    assert v["files"][0]["name"] == "Quotation"


@pytest.mark.parametrize("mutate,words", [
    (lambda s: s["files"][0]["sheets"][0]["rows"].__setitem__(0, ["x", "1,200", 1, 1, "2026-01-01", 0.1]), "JSON number"),
    (lambda s: s["files"][0]["sheets"][0]["columns"][1].update(type="money"), "must be one of"),
    (lambda s: s["files"][0]["sheets"][0]["rows"].__setitem__(0, ["x", 1, 1, 1, "01/02/2026", 0.1]), "YYYY-MM-DD"),
    (lambda s: s["files"][0]["sheets"][0]["rows"].__setitem__(0, ["x", 1, 1, "=HYPERLINK(\"http://x\")", None, None]), "not allowed"),
    (lambda s: s["files"][0].update(type="csv"), "only allowed in an xlsx"),
    (lambda s: s["files"][0]["sheets"][0].update(name="a/b"), "Excel refuses"),
    (lambda s: s["files"][0]["sheets"][0].update(name="x" * 32), "31"),
    (lambda s: s["files"][0]["sheets"][0]["rows"].append([1, 2, 3, 4, 5, 6, 7]), "only 6 columns"),
])
def test_bad_specs_are_rejected_with_the_reason(mutate, words):
    s = copy.deepcopy(GOOD)
    mutate(s)
    with pytest.raises(F.FileSpecError) as e:
        F.validate(s)
    assert words in str(e.value)


def test_duplicate_sheet_names_and_oversize_are_rejected():
    s = copy.deepcopy(GOOD)
    s["files"][0]["sheets"].append(copy.deepcopy(s["files"][0]["sheets"][0]))
    s["files"][0]["sheets"][1]["name"] = "ITEMS"
    with pytest.raises(F.FileSpecError, match="used twice"):
        F.validate(s)
    big = copy.deepcopy(GOOD)
    big["files"][0]["sheets"][0]["rows"] = [["a", 1, 1, 1, None, None]] * (F.MAX_ROWS + 1)
    with pytest.raises(F.FileSpecError, match="limit"):
        F.validate(big)
    wide = copy.deepcopy(GOOD)
    wide["files"][0]["sheets"][0]["columns"] = [
        {"key": f"k{i}", "title": "t", "type": "text"} for i in range(F.MAX_COLS + 1)]
    with pytest.raises(F.FileSpecError, match="limit"):
        F.validate(wide)


@pytest.mark.parametrize("name", ["../evil", "a/b", "..", "C:\\x", "CON", "nul", "com1",
                                  "x" * 81, "", "bad|name", "a\x00b"])
def test_unsafe_file_names_are_rejected(name):
    with pytest.raises(F.FileSpecError):
        F.validate(spec(name=name))


def test_duplicate_file_names_get_a_suffix_and_the_extension_is_repaired(out):
    s = {"files": [dict(copy.deepcopy(GOOD["files"][0]), name="Quote.xlsx"),
                   dict(copy.deepcopy(GOOD["files"][0]), name="quote")]}
    names = [r["name"] for r in F.render(s, out)]
    assert names == ["Quote.xlsx", "quote (2).xlsx"]


def test_non_json_reply_is_a_clear_error():
    with pytest.raises(F.FileSpecError, match="not valid JSON"):
        F.parse_json("Here is your file: sorry")
    assert F.parse_json('```json\n{"files": []}\n```') == {"files": []}


# ── renderers ────────────────────────────────────────────────────────────────

def test_xlsx_opens_typed_with_formulas_kept(out):
    rec = F.render(GOOD, out)[0]
    from openpyxl import load_workbook
    ws = load_workbook(rec["path"]).active
    assert ws.title == "Items"
    assert [c.value for c in ws[1]][:3] == ["Item", "Qty", "Rate"]
    assert ws["D2"].value == "=B2*C2" and ws["D4"].value == "=SUM(D2:D3)"
    assert ws["B2"].value == 10 and isinstance(ws["C2"].value, float)
    assert ws["E2"].number_format == "yyyy-mm-dd" and str(ws["E2"].value)[:10] == "2026-11-01"
    assert ws["F2"].number_format == "0.0%"
    assert ws["A3"].value == "ક્લેમ્પ क्लैंप"
    assert ws.freeze_panes == "A2" and ws["A1"].font.bold
    assert ws.column_dimensions["A"].width == 28
    assert os.path.isfile(rec["path"] + ".spec.json")


def test_text_that_looks_like_a_formula_stays_text_in_xlsx(out):
    s = spec()
    s["files"][0]["sheets"][0]["rows"][0][0] = "=cmd|' /C calc'!A0"
    rec = F.render(s, out)[0]
    from openpyxl import load_workbook
    cell = load_workbook(rec["path"]).active["A2"]
    assert cell.data_type == "s" and cell.value.startswith("=cmd")


def test_csv_has_bom_quoting_native_text_and_the_injection_guard(out):
    s = {"files": [{"name": "Leads", "type": "csv", "sheets": [{
        "name": "L", "columns": [{"key": "a", "title": "Name", "type": "text"},
                                 {"key": "b", "title": "Note", "type": "text"},
                                 {"key": "n", "title": "Amount", "type": "number"}],
        "rows": [["ગુજરાતી नमस्ते", 'He said "hi", ok', -5],
                 ["=SUM(A1)", "+91 98", 2.5], ["@x", "- dash", 0]]}]}]}
    path = F.render(s, out)[0]["path"]
    raw = open(path, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows[1] == ["ગુજરાતી नमस्ते", 'He said "hi", ok', "-5"]     # real number stays a number
    assert rows[2] == ["'=SUM(A1)", "'+91 98", "2.5"]
    assert rows[3][0] == "'@x" and rows[3][1] == "'- dash"


def test_several_csv_sheets_make_a_zip(out):
    s = copy.deepcopy(GOOD)
    s["files"][0]["type"] = "csv"
    s["files"][0]["sheets"][0]["rows"] = [["a", 1, 1, 1, None, None]]
    s["files"][0]["sheets"].append(copy.deepcopy(s["files"][0]["sheets"][0]))
    s["files"][0]["sheets"][1]["name"] = "Second"
    rec = F.render(s, out)[0]
    assert rec["path"].endswith(".zip")
    with zipfile.ZipFile(rec["path"]) as z:
        assert sorted(z.namelist()) == ["Quotation - Items.csv", "Quotation - Second.csv"]
        assert z.read("Quotation - Items.csv").startswith(b"\xef\xbb\xbf")


DOC = {"files": [{"name": "Site report", "type": "docx", "blocks": [
    {"type": "heading", "level": 1, "text": "Site visit"},
    {"type": "paragraph", "text": "We inspected the plant. ગુજરાતી"},
    {"type": "bullets", "items": ["Tray done", "Clamps pending"]},
    {"type": "numbered", "items": ["Fix", "Test"]},
    {"type": "table", "columns": ["Item", "Status"], "rows": [["Tray", "Done"], ["Clamp", "Pending"]]},
    {"type": "code", "text": "make all"}]}]}


def test_docx_opens_and_holds_the_blocks(out):
    rec = F.render(DOC, out)[0]
    assert open(rec["path"], "rb").read(2) == b"PK"
    from docx import Document
    d = Document(rec["path"])
    text = "\n".join(p.text for p in d.paragraphs)
    assert "Site visit" in text and "Clamps pending" in text and "make all" in text
    assert d.tables[0].rows[1].cells[1].text == "Done"


def test_pdf_opens_and_holds_the_text(out):
    s = copy.deepcopy(DOC)
    s["files"][0]["type"] = "pdf"
    rec = F.render(s, out)[0]
    data = open(rec["path"], "rb").read()
    assert data.startswith(b"%PDF")
    from pypdf import PdfReader
    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(rec["path"]).pages)
    assert "Site visit" in text and "Clamps pending" in text


def test_md_and_txt(out):
    for t in ("md", "txt"):
        s = copy.deepcopy(DOC)
        s["files"][0]["type"] = t
        s["files"][0]["name"] = "n" + t
        p = F.render(s, out)[0]["path"]
        assert "site visit" in open(p, encoding="utf-8").read().lower()


# ── conversion from the stored spec ──────────────────────────────────────────

def test_convert_xlsx_to_csv_pdf_docx_without_ai(out, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("an AI call was made during a local conversion")
    monkeypatch.setattr(ai_client, "chat", boom)
    src = F.render(GOOD, out)[0]["path"]
    assert set(F.convertible_to(src)) == {".csv", ".pdf", ".docx"}
    c = F.convert(src, "csv")
    assert open(c["path"], "rb").read().startswith(b"\xef\xbb\xbf")
    assert "=B2*C2" in open(c["path"], encoding="utf-8-sig").read()      # formulas travel
    assert os.path.isfile(c["spec"])
    # PDF and Word get the VALUES (the evaluator), not "=B2*C2".
    p = F.convert(src, "pdf")
    from pypdf import PdfReader
    text = " ".join(" ".join(pg.extract_text().split()) for pg in PdfReader(p["path"]).pages)
    assert "4,505.00" in text and "=B2" not in text
    d = F.convert(src, ".docx")
    from docx import Document
    assert "4,985.00" in "".join(c.text for r in Document(d["path"]).tables[0].rows for c in r.cells)
    # and the csv's own spec converts on, formulas allowed because we wrote it
    assert ".xlsx" in F.convertible_to(c["path"])
    assert F.convert(c["path"], "xlsx")["name"].endswith(".xlsx")


def test_document_to_spreadsheet_needs_a_table_and_says_so(out):
    src = F.render(DOC, out)[0]["path"]
    assert set(F.convertible_to(src)) == {".csv", ".xlsx", ".pdf"}   # it holds a table
    x = F.convert(src, "xlsx")                  # the document has one table
    assert x["name"].endswith(".xlsx")
    s = {"files": [{"name": "Prose", "type": "docx",
                    "blocks": [{"type": "paragraph", "text": "just words"}]}]}
    prose = F.render(s, out)[0]["path"]
    assert ".xlsx" not in F.convertible_to(prose)
    with pytest.raises(F.FileSpecError, match="no table"):
        F.convert(prose, "csv")


def test_convert_without_a_stored_spec_says_why(tmp_path):
    p = tmp_path / "plain.docx"
    p.write_bytes(b"PK")
    assert F.convertible_to(str(p)) == []
    with pytest.raises(F.FileSpecError, match="no stored data"):
        F.convert(str(p), "pdf")


def test_formula_evaluator_does_not_run_code(out):
    s = spec()
    s["files"][0]["sheets"][0]["rows"][0][3] = "=ABS(B2)+(1).__class__"
    with pytest.raises(F.FileSpecError):
        F.validate(s)           # "_" and "." are allowed chars; the function check or evaluator must not run it
    # even if it got through validation the evaluator leaves it as text
    sheet = {"rows": [[1, "=(1).__class__"]]}
    assert F._computed_rows(sheet) == [[1, "=(1).__class__"]]


# ── the tool loop ────────────────────────────────────────────────────────────

class Scripted:
    """An ai_chat that answers from a list and records every call."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, role, prompt, **kw):
        self.calls.append((role, prompt, kw))
        return self.replies[min(len(self.calls), len(self.replies)) - 1]


def call(spec_obj, message="Done."):
    return json.dumps({"tool": "create_file", "message": message, "arguments": spec_obj})


def test_loop_makes_the_file_first_time(out):
    chat = Scripted(call(GOOD))
    r = F.run_file_tool(chat, "make an excel quotation", "", out_dir=out, role="writer",
                        addon="core", feature="file_tool", ext=".xlsx")
    assert r.ok and r.turns == 1 and r.message == "Done."
    role, prompt, kw = chat.calls[0]
    assert role == "writer" and kw["json_mode"] is True and kw["addon"] == "core"
    assert "create_file" in kw["system"] and kw["feature"] == "file_tool"


def test_repair_turn_sends_the_exact_error_and_history(out):
    bad = copy.deepcopy(GOOD)
    bad["files"][0]["sheets"][0]["rows"][0][1] = "1,200"
    chat = Scripted("not json at all", call(bad), call(GOOD))
    r = F.run_file_tool(chat, "make an excel quotation", "", out_dir=out)
    assert r.ok and r.turns == 3
    assert "was not valid JSON" in chat.calls[1][1]
    assert "Your last file spec was rejected" in chat.calls[1][1]
    third = chat.calls[2][1]
    assert "Your last file spec was rejected" in third and "JSON number" in third
    assert "Earlier turns" in third                       # one conversation, history replayed
    assert len(os.listdir(out)) == 2                       # the file and its spec only


def test_turn_cap_and_no_fake_file_when_the_model_keeps_failing(out):
    chat = Scripted("nope")
    r = F.run_file_tool(chat, "make an excel of the leads", "no table here", max_turns=3, out_dir=out)
    assert not r.ok and r.turns == 3 and len(chat.calls) == 3 and not r.fallback
    assert "nothing was saved" in r.message
    assert not os.path.exists(out) or os.listdir(out) == []


def test_markdown_table_fallback_only_when_the_text_has_a_table(out):
    table = "Items:\n| Item | Qty |\n|---|---|\n| Tray | 10 |\n"
    chat = Scripted("nope")
    r = F.run_file_tool(chat, "excel please", table, max_turns=2, out_dir=out, ext=".xlsx")
    assert r.ok and r.fallback and r.files[0]["name"].endswith(".xlsx")
    r2 = F.run_file_tool(Scripted("nope"), "excel please", "prose only", max_turns=2,
                         out_dir=out + "2", ext=".xlsx")
    assert not r2.ok


def test_the_model_can_decline_and_the_person_sees_why(out):
    chat = Scripted(json.dumps({"tool": "none", "message": "Which columns do you want?"}))
    r = F.run_file_tool(chat, "make a sheet", "", out_dir=out)
    assert not r.ok and r.message == "Which columns do you want?" and r.turns == 1


# ── through the real flow: automation.run against the fake server ────────────

def _answer(body):
    """The fake server: prose for the writing step, JSON for the file tool."""
    if body.get("json_mode"):
        return call(GOOD, "Here is your quotation.")
    return "Quotation for cable trays: 10 at 450.50."


def test_run_makes_a_real_excel_through_the_server_and_no_browser(ai, no_chrome):
    ai.responder = _answer
    (responses, _l), events = _run(
        [("content", "ChatGPT", ["Write the quotation."])],
        query="give me an excel sheet quotation for cable trays")
    done = [p for k, p in events if k == "stage_done"][0]
    files = done["files"]
    assert files and files[0]["name"].endswith(".xlsx") and not done["missing"]
    saved = files[0]["saved"]
    assert os.path.isfile(saved) and os.path.isfile(saved + ".spec.json")
    from openpyxl import load_workbook
    assert load_workbook(saved).active["D2"].value == "=B2*C2"
    chats = ai.chats()
    assert [c["body"].get("json_mode", False) for c in chats] == [False, True]
    tool = chats[1]["body"]
    assert tool["feature"] == "file_tool" and tool["addon"] and "create_file" in tool["messages"][0]["content"]
    assert all(c["path"] == "/v1/ai/chat" for c in chats)


def test_run_repairs_through_the_server(ai, no_chrome):
    seen = []

    def answer(body):
        if not body.get("json_mode"):
            return "Quotation text."
        seen.append(body["messages"][-1]["content"])
        return "oops" if len(seen) == 1 else call(GOOD)
    ai.responder = answer
    _r, events = _run([("content", "ChatGPT", ["Write it."])], query="give me an excel sheet of rates")
    done = [p for k, p in events if k == "stage_done"][0]
    assert done["files"] and len(seen) == 2 and "rejected" in seen[1]


def test_run_that_keeps_failing_makes_no_file_and_says_so(ai, no_chrome):
    ai.responder = lambda b: "{}" if b.get("json_mode") else "Some prose, no table."
    _r, events = _run([("content", "ChatGPT", ["Write it."])], query="give me an excel sheet of rates")
    done = [p for k, p in events if k == "stage_done"][0]
    assert not done["files"] and "nothing was saved" in done["missing"]
    assert len([c for c in ai.chats() if c["body"].get("json_mode")]) == 3


def test_plain_prose_document_stays_on_the_markdown_path(ai, no_chrome):
    ai.responder = lambda b: "# Report\n\nSome prose."
    _r, events = _run([("content", "ChatGPT", ["Write it."])], query="write a report as a word document")
    done = [p for k, p in events if k == "stage_done"][0]
    assert done["files"] and done["files"][0]["name"].endswith(".docx")
    assert not any(c["body"].get("json_mode") for c in ai.chats())


# ── follow-up conversion in the GUI helper ───────────────────────────────────

def test_followup_make_it_a_csv_is_local(out, monkeypatch):
    import docexport
    monkeypatch.setattr(ai_client, "chat", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("AI call")))
    F.render(GOOD, out)
    assert docexport.is_pure_format_request("make it a CSV")
    assert docexport.requested_ext("give me this as csv") == ".csv"
    path, note = docexport.convert_stored(out, ".csv", out)
    assert path.endswith(".csv") and "converted" in note
    assert docexport.convert_stored(out + "-none", ".csv", out) == ("", "")


def test_followup_csv_from_prose_with_a_table_uses_the_spec_path(tmp_path):
    import docexport
    p, _ = docexport.export_answer("| A | B |\n|---|---|\n| 1 | x |\n", ".csv", str(tmp_path), "t")
    assert open(p, "rb").read().startswith(b"\xef\xbb\xbf")
    assert docexport.export_answer("no table", ".csv", str(tmp_path), "t") == ("", "")


# ── the file card ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    return _APP


def test_card_shows_preview_convert_buttons_and_converts(qapp, out, tmp_path):
    from widgets.file_card import FileCard, FileCards
    s = copy.deepcopy(GOOD)
    s["files"][0]["sheets"][0]["rows"] = [["r%d" % i, i, 1.0, None, None, None] for i in range(30)]
    s["files"][0]["sheets"][0]["columns"] += [{"key": f"x{i}", "title": f"X{i}", "type": "text"} for i in range(5)]
    path = F.render(s, out)[0]["path"]
    cards = FileCards([path], preview=True)
    card = cards.cards[0]
    assert card.preview.rowCount() == 20 and card.preview.columnCount() == 8
    assert "20 of 30 rows" in card.preview.note() and "8 of 11 columns" in card.preview.note()
    assert set(card.convert_btns) == {".csv", ".pdf", ".docx"} and all(
        b.isEnabled() for b in card.convert_btns.values())
    assert all(b.isEnabled() for b in card.buttons)
    new = card.convert(".csv")
    assert new.endswith(".csv") and os.path.isfile(new)
    assert len(cards.cards) == 2                       # the converted file got its own card
    dest = str(tmp_path / "copy.xlsx")
    assert card.save_to(dest) and os.path.isfile(dest) and os.path.isfile(dest + ".spec.json")


def test_card_for_a_missing_file_is_disabled_and_says_why(qapp, tmp_path):
    from widgets.file_card import FileCard, WHY_MISSING
    card = FileCard(str(tmp_path / "gone.xlsx"))
    assert not any(b.isEnabled() for b in card.buttons)
    assert all("no longer" in b.toolTip() for b in card.buttons)
    assert all(not b.isEnabled() and b.toolTip() for b in card.convert_btns.values())


def test_card_for_a_file_without_a_spec_explains_the_disabled_convert(qapp, tmp_path):
    from widgets.file_card import FileCard
    p = tmp_path / "plain.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    card = FileCard(str(p), preview=True)
    assert card.preview.rowCount() == 1                # read from the file itself
    assert card.convert_btns == {}                     # no spec, no convert row at all


def test_reader_dialog_shows_cards_for_the_files(qapp, out):
    from dialogs.completion_dialog import StageResultDialog
    path = F.render(GOOD, out)[0]["path"]
    dlg = StageResultDialog("content", "ChatGPT", "text", "", None, files=[path])
    assert dlg.file_cards.cards[0].preview.rowCount() == 3


def test_task_result_card_shows_a_file_card_for_a_made_file(qapp, out):
    from widgets.output_panel import StageCard
    path = F.render(GOOD, out)[0]["path"]
    card = StageCard("content", "ChatGPT")
    card.set_done(["Quotation text."], "", files=[
        {"name": "Quotation.xlsx", "kind": "document", "size": 1, "saved": path, "path": ""}],
        prism_note="Prism made this file")
    assert card.file_cards is not None and card.file_cards.cards[0].path == path
    gone = StageCard("content", "ChatGPT")
    gone.set_done(["x"], "", files=[{"name": "a.xlsx", "kind": "document", "saved": out + "/a.xlsx"}])
    assert gone.file_cards.cards[0].open_btn.isEnabled() is False
    plain = StageCard("content", "ChatGPT")
    plain.set_done(["x"], "", files=[{"name": "p.png", "kind": "image", "saved": out + "/p.png"}])
    assert plain.file_cards is None

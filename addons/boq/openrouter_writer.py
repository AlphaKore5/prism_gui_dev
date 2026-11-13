"""BOQ-CHANGES-TODO.md item 30 — the "Prism Agent" write-up path.

Every other writer agent (Claude, ChatGPT, Grok...) is a real tool in a
browser, which can export its own answer as a DOCX/PDF because that tool
has its own file-making feature built in. A plain OpenRouter chat
completion has none of that — it only ever returns text. So this module
is the other half of item 30b: ask the model for a well-structured
answer (headings, a pipe-table of BOQ lines, same shape the write-up
prompt has always asked every agent for), then build the actual
DOCX/CSV/PDF file from that text here, in code, the same way boq_price.py
already builds a document from structured data rather than asking an AI
to produce a file directly.

Deliberately NOT routed through core.boq_price's own Boq/BoqItem/
write_boq_* pipeline: that module's whole premise, stated in its own
docstring, is "no number of record is ever produced by an AI" — it is
the PRICING stage's own deterministic, rate-library-matched pipeline.
The write-up stage has never worked that way; it has always handed back
free-form text built around measured figures that were fixed before the
prompt was written (see dialog.py's _write/_send_followup, which embed
`self.summary` as plain text). This module keeps that same shape — it
is a renderer for the write-up's own text, not a second pricing engine.
"""
from __future__ import annotations

import csv
import html as _html
import os
import re

import core_bridge as CB
from addons.boq import agents as boq_agents


# item 81: the write-up is a transcription-and-layout job on figures that
# are already measured -- on the 13 Nov run above, roughly 58,000 of the
# 65,536 output tokens went on the model's own hidden reasoning and the
# BOQ itself was cut short. Reasoning off leaves the whole output limit
# for the document. The same switch the drawing-tile reader
# (addons/boq/workers.py) has used since item 2.
WRITE_EXTRA = {"reasoning": {"enabled": False}}


def model_for(agent: str, *, followup: bool) -> str:
    """Item 30e's two-tier choice: the heavier generation model, or the
    cheaper same-family sibling for a follow-up/edit."""
    table = (boq_agents.PRISM_AGENT_FOLLOWUP_MODELS if followup
            else boq_agents.PRISM_AGENT_MODELS)
    model = table.get(agent)
    if not model:
        raise ValueError(f"{agent!r} is not a Prism Agent.")
    return model


def has_vision(agent: str) -> bool:
    """item 32: can this agent actually look at a rendered drawing at
    all. dialog.py checks this BEFORE calling write() with attachments,
    so it can tell the user plainly (Prism Agent Deep has none, at any
    tier) rather than silently sending the drawing and having it ignored
    with no explanation."""
    return bool(boq_agents.PRISM_AGENT_HAS_VISION.get(agent))


def write(agent: str, prompt: str, api_key: str, *, followup: bool = False,
         attachments: list[dict] | None = None,
         usage_out: dict | None = None) -> str:
    """One Prism Agent completion. Raises RuntimeError with the real
    reason on failure (no key, a rejected key, a network error, ...) --
    caught and shown to the user by whatever calls this off the GUI
    thread (addons/boq/workers.py:OpenRouterWriteWorker).

    `attachments`: rendered drawings (cad_render.prepare_for_ai()'s own
    shape) to show the model alongside the text, item 32 -- silently
    dropped here if `agent` has no vision capability at all (has_vision()
    already told the caller that before this was ever called; this is
    the last line of defence, not the place a person first learns it).

    `usage_out`: passed straight through to CB.openrouter.openrouter_chat()
    -- item 70's BOQ counter reads it off the worker afterward."""
    model = model_for(agent, followup=followup)
    if attachments and not has_vision(agent):
        attachments = None
    usage = usage_out if usage_out is not None else {}
    text = CB.openrouter.openrouter_chat(api_key, model, prompt, attachments=attachments,
                                         usage_out=usage, extra=WRITE_EXTRA)
    # item 81 (13 Nov 2026), two real failures of the same kind, both
    # saved as finished BOQs with no warning. 5 Nov, "Prism Agent Deep",
    # twice in a row: the answer came back empty and the model's own
    # working notes were written into the workbook -- a 53,000-row "BOQ"
    # sheet of "Let me write the document. OK. Let me go." 13 Nov, "Prism
    # Agent Claude": 65,536 output tokens used, 18,745 characters of
    # answer -- the BOQ stops mid-row in the return-duct table, with
    # every later section missing. A BOQ that is not whole is never
    # handed back as if it were.
    if usage.get("answer_from_reasoning") is True:
        raise RuntimeError(
            f"{agent} returned only its working notes, not a BOQ. Nothing was saved. "
            "Press Make my BOQ again.")
    if usage.get("finish_reason") == "length":
        raise RuntimeError(
            f"{agent} ran out of room before finishing -- the BOQ stops part-way. "
            "Nothing was saved. Press Make my BOQ again; if it happens twice, "
            "ask for a shorter BOQ in the request box.")
    return text


# ── a small markdown model -- just enough for a BOQ write-up's own shape ──
# Headings, paragraphs, bullet/numbered lists, pipe tables. Not a general
# markdown engine -- the write-up prompt has always asked for exactly
# these four things (see prompts.py's formatting_prompt), so parsing only
# what it actually asks for is a smaller, more honest surface than a
# general parser that silently mishandles the rest.

def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def _is_table_sep(line: str) -> bool:
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    cells = [c.strip() for c in s.strip("|").split("|")]
    # each cell is dashes, optionally with a leading/trailing ':' for
    # alignment ("---", ":---", "---:", ":---:") -- a bare "|" stripped of
    # its own pipes leaves "-" characters PLUS more "|"s between cells,
    # which the old `all(c in "-: " for c in s)` check (scanning the whole
    # row as one string) wrongly failed on, since "|" itself was never in
    # that allowed set. Splitting into cells first is what fixes it.
    return bool(cells) and all(c and set(c) <= set("-:") for c in cells)


def _split_row(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_markdown(text: str) -> list[dict]:
    """[{'type': 'heading'|'para'|'bullet'|'table', ...}, ...] in document
    order. `heading`: level, text. `para`: text. `bullet`: items (a list
    of strings). `table`: headers, rows (list of list of strings)."""
    lines = (text or "").replace("\r\n", "\n").split("\n")
    blocks: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)),
                           "text": m.group(2).strip()})
            i += 1
            continue
        if _is_table_row(line) and i + 1 < n and _is_table_sep(lines[i + 1]):
            headers = _split_row(stripped)
            rows = []
            i += 2
            while i < n and _is_table_row(lines[i]):
                rows.append(_split_row(lines[i]))
                i += 1
            blocks.append({"type": "table", "headers": headers, "rows": rows})
            continue
        if re.match(r"^([-*]|\d+\.)\s", stripped):
            items = []
            while i < n and re.match(r"^([-*]|\d+\.)\s", lines[i].strip()):
                items.append(re.sub(r"^([-*]|\d+\.)\s+", "", lines[i].strip()))
                i += 1
            blocks.append({"type": "bullet", "items": items})
            continue
        para = [stripped]
        i += 1
        while (i < n and lines[i].strip()
              and not re.match(r"^#{1,4}\s", lines[i].strip())
              and not _is_table_row(lines[i])
              and not re.match(r"^([-*]|\d+\.)\s", lines[i].strip())):
            para.append(lines[i].strip())
            i += 1
        blocks.append({"type": "para", "text": " ".join(para)})
    return blocks


# item 49 (3 Nov 2026), found live, visually -- not assumed from reading the
# code, confirmed by actually rendering a real generated .docx (macOS Quick
# Look) and looking at it: every `**bold**`/`` `code` `` span the writing AI
# put in its own answer (and every prompt in this add-on asks for markdown,
# same as core/boq.py's formatting_prompt() always has) came out as LITERAL
# asterisks and backticks in the Word file -- "**Client:** Pharmatech
# Company" sitting there with its own punctuation marks, in the title line,
# in every TO CONFIRM note, in every emphasised table cell. parse_markdown()
# only ever parsed BLOCK structure (headings/paragraphs/bullets/tables); the
# text INSIDE a block was always passed through verbatim. The same root
# cause already existed in dialog.py's own result box before item 37 fixed
# it there (QPlainTextEdit vs QTextEdit) -- this is the identical bug, one
# layer over, in the actual DELIVERABLE file the person opens afterwards.
_INLINE_SPAN = re.compile(r"\*\*(.+?)\*\*|`(.+?)`")


def _add_inline_markdown(paragraph, text: str) -> None:
    """Add `text` to a docx Paragraph (or an equivalent object with a
    `.add_run()` method, e.g. a table cell's own paragraph) as real runs --
    `**bold**` becomes a bold run, `` `code` `` becomes a monospace run,
    everything else plain -- instead of one run holding the markdown
    syntax characters themselves."""
    pos = 0
    for m in _INLINE_SPAN.finditer(text or ""):
        if m.start() > pos:
            paragraph.add_run(text[pos:m.start()])
        bold_span, code_span = m.group(1), m.group(2)
        if bold_span is not None:
            paragraph.add_run(bold_span).bold = True
        else:
            run = paragraph.add_run(code_span)
            run.font.name = "Courier New"
        pos = m.end()
    if pos < len(text or ""):
        paragraph.add_run(text[pos:])


def _set_column_widths(table, headers: list, rows: list) -> None:
    """Proportional column widths from actual content length, instead of
    python-docx's own default (dividing the page evenly across columns,
    regardless of whether a column holds "Qty" or three sentences of
    description) -- found live, visually, alongside item 49's bold-text
    bug: a 7-column BOQ table with even widths wrapped "Description /
    source" into 6+ lines per row while "Unit" sat mostly empty at the
    same width. Every BOQ table seen in this add-on's own real client
    files has this shape (a few narrow numeric/unit columns beside one or
    two long description columns) -- not specific to one document.
    Narrow (<= 4 chars, e.g. "Qty", "No.") and wide (> 40 chars, long
    descriptions) columns are clamped so one freak value does not starve
    or swallow the whole row."""
    import docx
    widest = []
    for c in range(len(headers)):
        cells = [headers[c]] + [r[c] if c < len(r) else "" for r in rows]
        widest.append(max((len(str(v)) for v in cells), default=1))
    clamped = [max(4, min(w, 40)) for w in widest]
    total = sum(clamped) or 1
    page_width = docx.shared.Inches(10.0)   # landscape content width, see below
    table.autofit = False
    for i, col in enumerate(table.columns):
        width = docx.shared.Inches(10.0 * clamped[i] / total)
        col.width = width
        for cell in col.cells:              # python-docx needs both set
            cell.width = width


def markdown_to_docx(text: str, path: str) -> str:
    import docx
    blocks = parse_markdown(text)
    doc = docx.Document()
    # A readable, consistent body font -- python-docx's own default
    # ("Calibri" at Word's base size, applied inconsistently across
    # locales/templates) is not itself the bug this item fixes, but costs
    # nothing to set explicitly while already touching this function.
    doc.styles["Normal"].font.name = "Calibri"
    doc.styles["Normal"].font.size = docx.shared.Pt(10.5)
    # Landscape, not Word's own portrait default: every real BOQ this
    # add-on has produced or been shown (item 44/45/48's own test files
    # included) has a wide table -- 5 to 9 columns -- that a portrait
    # page's ~6.5" of content width was never going to fit without the
    # same cramped wrapping _set_column_widths exists to fix. A text-only
    # answer (no table at all) reads fine in landscape too; nothing about
    # it depends on the narrower page.
    section = doc.sections[0]
    section.orientation = docx.enum.section.WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    for b in blocks:
        if b["type"] == "heading":
            h = doc.add_heading("", level=min(b["level"], 4))
            _add_inline_markdown(h, b["text"])
        elif b["type"] == "para":
            p = doc.add_paragraph()
            _add_inline_markdown(p, b["text"])
        elif b["type"] == "bullet":
            for item in b["items"]:
                p = doc.add_paragraph(style="List Bullet")
                _add_inline_markdown(p, item)
        elif b["type"] == "table" and b["headers"]:
            cols = len(b["headers"])
            t = doc.add_table(rows=1, cols=cols)
            try:
                t.style = "Light Grid Accent 1"
            except KeyError:                                 # template-dependent
                pass
            for c, h in enumerate(b["headers"]):
                cell = t.rows[0].cells[c]
                cell.paragraphs[0].text = ""
                _add_inline_markdown(cell.paragraphs[0], h)
                for run in cell.paragraphs[0].runs:
                    run.bold = True          # header row, even if the AI's own text wasn't already **bold**
            for row in b["rows"]:
                cells = t.add_row().cells
                for c, val in enumerate(row[:cols]):
                    cells[c].paragraphs[0].text = ""
                    _add_inline_markdown(cells[c].paragraphs[0], val)
            _set_column_widths(t, b["headers"], b["rows"])
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    doc.save(path)
    return path


# item 66 (11 Nov 2026): an ELV client's own "Rajesh Nagda Hostel" sample only
# ever matched the WRITE-UP's wording and section order -- markdown_to_docx()
# above always renders into a brand-new, generic docx, so a client's real
# letterhead, logo, fonts and column widths never survived no matter how
# closely the write-up copied the sample's shape. The fix is not a smarter
# prompt -- it is a different operation: open the client's OWN template file
# and fill it in place, never rebuild one from scratch. Column matching is a
# small synonym table rather than an AI call -- every header in this add-on's
# own real client files so far (an ELV client's and CCTV_ELV_BOQ
# samples included) is covered by it, and a column it genuinely doesn't
# recognise is safer left blank than guessed at by a model.
import copy

_COLUMN_SYNONYMS: dict[str, set[str]] = {
    "no": {"no", "sr no", "sr", "s no", "sl no", "item no"},
    "description": {"description", "item description", "item", "particulars",
                    "site feature", "feature"},
    "qty": {"qty", "quantity"},
    "unit": {"unit", "uom"},
    "rate": {"rate", "rate inr", "unit rate"},
    "amount": {"amount", "amount inr", "total", "total value inr",
              "total price inr"},
    "basis": {"basis", "design basis", "basis reason", "reason", "basis / reason"},
    "value": {"value", "measured value"},
    "reference": {"layer block", "drawing reference layer block", "reference",
                  "layer", "drawing reference"},
}


def _normalize_header(h: str) -> str:
    h = (h or "").lower().strip()
    h = re.sub(r"[().,/]", " ", h)
    h = re.sub(r"\s+", " ", h).strip()
    return h


def _column_group(h: str) -> str | None:
    """Which synonym group `h` belongs to ('no', 'description', 'qty', ...),
    or None if it doesn't look like a BOQ line-item column at all (a
    letterhead's "To"/"Ref" cell, a notice box's only cell)."""
    norm = _normalize_header(h)
    if not norm:
        return None
    for group, names in _COLUMN_SYNONYMS.items():
        if norm in names:
            return group
    # Loose fallback: the synonym word appears INSIDE the header text (e.g.
    # "Drawing Reference (Layer / Block)" contains "layer block"). Checked
    # one-way only -- the reverse ("to" is a substring of "total") would
    # wrongly match a short, unrelated header against a longer synonym.
    for group, names in _COLUMN_SYNONYMS.items():
        for name in names:
            if len(name) >= 4 and name in norm:
                return group
    return None


def _map_columns(template_headers: list[str], drafted_headers: list[str]
                 ) -> dict[int, int]:
    """template column index -> drafted column index, matched by synonym
    group ("Sr No" <-> "No", "Item Description" <-> "Description", ...). A
    template column with no confident match is left out of the map -- its
    cells stay blank in the output rather than guess wrong."""
    t_groups = [_column_group(h) for h in template_headers]
    d_groups = [_column_group(h) for h in drafted_headers]
    mapping: dict[int, int] = {}
    used_drafted: set[int] = set()
    for t_idx, t_group in enumerate(t_groups):
        if t_group is None:
            continue
        for d_idx, d_group in enumerate(d_groups):
            if d_idx in used_drafted:
                continue
            if d_group == t_group:
                mapping[t_idx] = d_idx
                used_drafted.add(d_idx)
                break
    return mapping


def _best_table_match(template_headers: list[str], drafted_tables: list[dict],
                      used: set[int]) -> tuple[int | None, dict[int, int]]:
    """Among `drafted_tables` (parse_markdown()'s table blocks) not already
    in `used`, the one whose columns cover the most of `template_headers`,
    together with its column map. (None, {}) if nothing covers at least
    half of the template table's own recognisable columns -- matched by
    HEADER OVERLAP, not by position, since the drafted BOQ and the
    client's template rarely have the same number of sections."""
    best_idx, best_map, best_score = None, {}, 0.0
    real_cols = sum(1 for h in template_headers if _column_group(h))
    if not real_cols:
        return None, {}
    for idx, block in enumerate(drafted_tables):
        if idx in used:
            continue
        mapping = _map_columns(template_headers, block["headers"])
        score = len(mapping) / real_cols
        if score > best_score:
            best_idx, best_map, best_score = idx, mapping, score
    if best_score < 0.5:
        return None, {}
    return best_idx, best_map


def fill_template_docx(text: str, template_path: str, out_path: str) -> dict:
    """Fill the CLIENT'S OWN template -- their letterhead, logo, fonts,
    column widths, everything already in `template_path` -- with the line
    items from `text` (the same markdown a write-up agent returns, parsed
    the same way markdown_to_docx() parses it).

    A template table that finds no confident match (see _best_table_match)
    is left COMPLETELY untouched, stale data and all, rather than guessed
    into. A drafted table that finds no matching template section is
    appended at the end of the document under a clearly marked heading
    instead of silently dropped -- the same rule the write-up prompt
    itself already uses for measured figures ("nothing measured should be
    silently dropped").

    Returns {"path", "matched", "unmatched_template", "unmatched_drafted"}:
    `matched`/`unmatched_template` are counts of template tables;
    `unmatched_drafted` is the list of drafted section headings that had
    nowhere to go in this template.
    """
    import docx
    blocks = parse_markdown(text)
    drafted_tables = [b for b in blocks if b["type"] == "table" and b["headers"]]
    headings: list[str] = []
    last_heading = ""
    for b in blocks:
        if b["type"] == "heading":
            last_heading = b["text"]
        elif b["type"] == "table" and b["headers"]:
            headings.append(last_heading)

    doc = docx.Document(template_path)
    used: set[int] = set()
    matched = 0
    unmatched_template = 0
    for table in doc.tables:
        if not table.rows:
            continue
        t_headers = [c.text.strip() for c in table.rows[0].cells]
        idx, col_map = _best_table_match(t_headers, drafted_tables, used)
        if idx is None:
            if any(_column_group(h) for h in t_headers):
                unmatched_template += 1
            continue
        used.add(idx)
        matched += 1
        block = drafted_tables[idx]
        data_rows = list(table.rows[1:])
        style_tr = copy.deepcopy(data_rows[-1]._tr) if data_rows else None
        for row in data_rows:
            table._tbl.remove(row._tr)
        for drafted_row in block["rows"]:
            if style_tr is not None:
                table._tbl.append(copy.deepcopy(style_tr))
                new_row = table.rows[-1]
            else:
                new_row = table.add_row()
            for t_idx, d_idx in col_map.items():
                if t_idx >= len(new_row.cells):
                    continue
                val = drafted_row[d_idx] if d_idx < len(drafted_row) else ""
                cell = new_row.cells[t_idx]
                cell.paragraphs[0].text = ""
                _add_inline_markdown(cell.paragraphs[0], val)

    def _heading(doc_, text_, level_):
        # Not every real client template keeps python-docx's own default
        # "Heading N" styles -- a real-world export (confirmed against
        # an ELV client's own approved CCTV_ELV_BOQ) can strip unused
        # built-in styles entirely, which makes add_heading() raise
        # KeyError. A bold paragraph says the same thing without relying
        # on a style name the template may not define.
        try:
            doc_.add_heading(text_, level=level_)
        except KeyError:
            p = doc_.add_paragraph()
            p.add_run(text_).bold = True

    unmatched_drafted = [headings[i] or f"Section {i + 1}"
                         for i in range(len(drafted_tables)) if i not in used]
    if unmatched_drafted:
        doc.add_page_break()
        _heading(doc, "NOT IN THE TEMPLATE — appended below, unplaced", 2)
        for i in range(len(drafted_tables)):
            if i in used:
                continue
            block = drafted_tables[i]
            if headings[i]:
                _heading(doc, headings[i], 3)
            cols = len(block["headers"])
            t = doc.add_table(rows=1, cols=cols)
            try:
                t.style = "Light Grid Accent 1"
            except KeyError:                                     # template-dependent
                pass
            for c, h in enumerate(block["headers"]):
                cell = t.rows[0].cells[c]
                cell.paragraphs[0].text = ""
                _add_inline_markdown(cell.paragraphs[0], h)
                for run in cell.paragraphs[0].runs:
                    run.bold = True
            for row in block["rows"]:
                cells = t.add_row().cells
                for c, val in enumerate(row[:cols]):
                    cells[c].paragraphs[0].text = ""
                    _add_inline_markdown(cells[c].paragraphs[0], val)

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    doc.save(out_path)
    return {
        "path": out_path,
        "matched": matched,
        "unmatched_template": unmatched_template,
        "unmatched_drafted": unmatched_drafted,
    }


# item 51 (4 Nov 2026): the owner compared a Prism BOQ against the same job
# done on claude.ai, which hands back a real multi-sheet .xlsx -- editable,
# formula-capable, summable -- next to Prism's single flat .docx table. This
# module was never going to grow Inputs/BOQ/Summary sheets with live
# formulas (that is a different, much bigger piece of work -- the AI's own
# free-text answer has no formulas to carry over, only the finished figures
# it already computed), but the smaller, real gap this closes today: a BOQ
# reader can filter, sort and sum a real spreadsheet in a way a Word table
# never lets them, and every other export here (docx/csv/pdf) already runs
# off the same `parse_markdown()` blocks, so xlsx is the one obvious format
# missing from that list, not a new capability.
def _strip_inline_markdown(text: str) -> str:
    """Plain text for a spreadsheet cell -- same `**bold**`/`` `code` `` spans
    _add_inline_markdown turns into separate bold/monospace runs in a docx
    paragraph, with the markdown syntax characters themselves simply
    dropped: one spreadsheet cell holds one plain value, never mixed runs,
    and the content underneath the asterisks/backticks is what a BOQ reader
    actually needs in the cell."""
    parts: list[str] = []
    pos = 0
    for m in _INLINE_SPAN.finditer(text or ""):
        if m.start() > pos:
            parts.append(text[pos:m.start()])
        parts.append(m.group(1) if m.group(1) is not None else m.group(2))
        pos = m.end()
    parts.append((text or "")[pos:])
    return "".join(parts)


_NUMERIC_CELL = re.compile(r"^-?\d+(\.\d+)?$")


def _xlsx_cell_value(raw: str):
    """A real number for a cell that is nothing but one, e.g. "26.213" or
    "4" -- so Qty/Kg columns can actually be summed/filtered in Excel, the
    whole reason this format exists next to the docx table -- otherwise the
    plain stripped text (a cell like "60.56 kg provisional @2.0 mm" stays
    text; inventing a number out of a sentence would be worse than leaving
    it as a string).

    item 72 (12 Nov 2026), found live: a real run's Inputs sheet had a
    Value cell written as "={shs40_mm}*{shs40_mm}-..." -- a formula
    _compile_cell gave up compiling (its own {name} tokens never
    resolved), which this function has always been its documented
    fallback for. But a string starting with '=' becomes a REAL Excel
    formula the moment it is assigned to a cell -- openpyxl's own rule,
    nothing to do with whether the text is valid formula syntax -- so the
    unsubstituted "{shs40_mm}" tokens went straight into the saved file's
    own <f> element. Curly braces are not legal there; Excel's stricter
    parser (silently accepted by openpyxl's own reader, caught only by
    the real application) rejected the whole workbook on open and
    "repaired" it by stripping the broken formula along with everything
    else on its calc chain. A single leading space defeats openpyxl's
    formula check while leaving the text exactly as written -- still
    visibly starting with '=' to whoever reads the cell, just never
    interpreted as one. This is every caller of _xlsx_cell_value, not
    only the Inputs sheet -- the flat (no-INPUTS-table) sheet routes
    every one of its own cells through this same function with no
    formula compilation step at all, so it shares the exact same risk."""
    val = _strip_inline_markdown(raw).strip()
    if _NUMERIC_CELL.match(val):
        return int(val) if "." not in val else float(val)
    if val.startswith("="):
        return " " + val
    return val


# item 57 (4 Nov 2026): this module's own copy of core.boq_price's palette
# (prism_terminal/core/boq_price.py's `_INK`/`_HEAD_FILL`/etc.) -- not
# imported from there, since those are that module's own private, unitless
# strings, not a published shared constant, and this module stays on the
# app side of core_bridge's own boundary (CONTRIBUTING.md rule 3: only
# core_bridge imports the engine). Copied, not re-derived, so every xlsx
# Prism writes -- the deterministic priced BOQ and a Prism Agent's own
# free-text one alike -- reads as the same product.
_XLSX_INK = "1F2A44"
_XLSX_HEAD_FILL = "1F2A44"
_XLSX_SECTION_FILL = "E8EDF5"
_XLSX_GRAND_FILL = "D9E7D6"
_XLSX_GRID = "C7CDD6"
_XLSX_MONEY_FMT = "#,##,##0.00"
# item 59 (4 Nov 2026): the owner's own words -- "all the reference and
# everything important should be highlighted, all the sections in the BOQ
# should look like a single TOPIC that draws the user attention". A
# TO CONFIRM line (the AI's own convention, used throughout every real BOQ
# this add-on has produced) is the single most consequence-bearing kind of
# text in the whole document -- it is the model saying "I did not invent
# this, you must" -- and it was sitting in the exact same plain black text
# as an ordinary paragraph. Same warning palette core.boq_price.py already
# uses for an unpriced BOQ line (`_UNPRICED_FILL`/its own note-colour ink).
_XLSX_WARN_FILL = "FBE4E4"
_XLSX_WARN_INK = "7A2E2E"
_XLSX_TO_CONFIRM = re.compile(r"to\s*confirm", re.I)
# item 61 (4 Nov 2026): a section heading naming itself a re-grouping of
# material already counted elsewhere -- "RAW MATERIAL REQUIREMENT",
# "MATERIAL SUMMARY", "PROCUREMENT SUMMARY" -- rather than a distinct set
# of line items. See _write_summary_sheet's own comment for why this
# disables the Grand Total rather than guessing which earlier sections it
# restates.
_XLSX_RECAP_HEADING = re.compile(
    r"raw material (requirement|summary)|material requirement|"
    r"procurement summary|material summary", re.I)


def _section_span(blocks: list, start: int) -> int:
    """How many columns the table(s) under the heading at `blocks[start]`
    actually use -- the widest one, up to the next heading or the end of
    the document -- so that heading's own row can be merged across the
    full width of its section instead of sitting alone in column A. 1
    (no merge) when nothing but plain text follows before the next
    heading, e.g. the document's own opening title."""
    span = 1
    for b in blocks[start + 1:]:
        if b["type"] == "heading":
            break
        if b["type"] == "table" and b["headers"]:
            span = max(span, len(b["headers"]))
    return span


def _write_blocks_to_sheet(ws, blocks: list, compile_cell) -> list[dict]:
    """The body both xlsx shapes share -- headings/paragraphs/bullets as
    plain rows, each table as real header/data rows. `compile_cell(raw)`
    turns one table-cell's raw text into whatever `ws.cell()` should hold
    -- `_xlsx_cell_value` for the flat sheet, `_compile_cell` (formula-
    aware) for the live workbook -- the only thing that differs between
    the two shapes. Returns one dict per table actually written: the
    heading text seen most recently above it (the section's own label),
    its headers, and the sheet row range its data occupies -- what
    `_write_summary_sheet` needs to point a live total at this sheet
    without re-walking the markdown itself.

    item 57 (4 Nov 2026), found live: the owner compared this sheet
    against the same job's claude.ai file and said, plainly, "look how
    clean the claude one looks, and look how our looks" -- the formulas
    and structure already matched (item 52), but every cell here was
    still plain black-on-white, no border, no header contrast, raw
    decimals with no thousands separator. Styled to the same palette
    core.boq_price.write_boq_xlsx already uses for the deterministic BOQ
    path -- the navy header bar, section fill, thin grid -- so a Prism
    Agent's own workbook looks like it came from the same product as the
    priced one, not a plainer, separate tool."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    thin_side = Side(style="thin", color=_XLSX_GRID)
    thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    row = 1
    widths: dict[int, int] = {}
    last_heading = ""
    sections: list[dict] = []

    def touch(col: int, value) -> None:
        widths[col] = max(widths.get(col, 10), min(len(str(value)), 60))

    for idx, b in enumerate(blocks):
        if b["type"] == "heading":
            text = _strip_inline_markdown(b["text"])
            cell = ws.cell(row, 1, text)
            cell.font = Font(bold=True, color=_XLSX_INK,
                             size=max(11, 16 - 2 * (b["level"] - 1)))
            touch(1, cell.value)
            # item 59: a section heading now reads as one real divider
            # band -- filled and merged across its own section's full
            # width -- instead of a bold line of text sitting alone in
            # column A with eight empty columns beside it. Only when
            # there IS a width to merge across (the document's own
            # opening title, with nothing tabular under it before the
            # next heading, stays a plain single-cell title line).
            span = _section_span(blocks, idx)
            if span > 1:
                ws.merge_cells(start_row=row, start_column=1,
                              end_row=row, end_column=span)
                cell.fill = PatternFill("solid", fgColor=_XLSX_SECTION_FILL)
                cell.alignment = Alignment(horizontal="left", vertical="center")
                for c in range(1, span + 1):
                    ws.cell(row, c).border = thin
            last_heading = cell.value
            row += 1
        elif b["type"] == "para":
            text = _strip_inline_markdown(b["text"])
            cell = ws.cell(row, 1, text)
            touch(1, cell.value)
            if _XLSX_TO_CONFIRM.search(text):
                cell.font = Font(bold=True, color=_XLSX_WARN_INK)
                cell.fill = PatternFill("solid", fgColor=_XLSX_WARN_FILL)
            row += 1
        elif b["type"] == "bullet":
            for item in b["items"]:
                text = "• " + _strip_inline_markdown(item)
                cell = ws.cell(row, 1, text)
                touch(1, cell.value)
                if _XLSX_TO_CONFIRM.search(text):
                    cell.font = Font(bold=True, color=_XLSX_WARN_INK)
                    cell.fill = PatternFill("solid", fgColor=_XLSX_WARN_FILL)
                row += 1
        elif b["type"] == "table" and b["headers"]:
            headers = b["headers"]
            for c, h in enumerate(headers, start=1):
                cell = ws.cell(row, c, _strip_inline_markdown(h))
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = PatternFill("solid", fgColor=_XLSX_HEAD_FILL)
                cell.alignment = Alignment(horizontal="center", vertical="center",
                                           wrap_text=True)
                cell.border = thin
                touch(c, cell.value)
            row += 1
            first_data_row = row
            # which column ended up holding a number or a live formula in
            # EVERY data row -- the one a Summary total can safely SUM.
            # Picked by column, not guessed from the header's own wording
            # (a real BOQ's amount column is called "Kg", "Gross wt (kg)",
            # "Amount"... too many spellings to pattern-match reliably);
            # the rightmost one is kept when more than one qualifies, the
            # same left-to-right-is-detail, rightmost-is-the-total shape
            # every real BOQ table seen in this add-on already has.
            #
            # item 53 (4 Nov 2026), found live on the owner's own first real
            # run: a "Bought-out / Miscellaneous Items" section whose every
            # weight cell was honestly "TO CONFIRM" (not stated anywhere,
            # correctly not guessed) left column 1 -- the Item/Sr NUMBER --
            # as the only column numeric in every row, and the Summary
            # sheet summed item numbers 1..6 into a "Total" of 21: a real
            # number sitting where a weight total belongs, meaningless and
            # worse than no total at all. Column 1 is excluded from
            # candidacy outright (every BOQ table in this whole add-on
            # starts with a serial/item number, never an amount) unless
            # it is the table's only column.
            # item 58 (4 Nov 2026), found live: a real table had ONE column
            # headed "Qty/Length/Area/Weight" -- the model's own choice,
            # mixing an area-in-m² row ("Back panel") directly above a
            # weight-in-kg row ("Back panel - weight") in the SAME column,
            # with no separate column for each. A header naming two or
            # more distinct measures at once can never be safely summed --
            # the result mixes units and means nothing, confirmed live:
            # SUM()'d this exact column by hand and got 555.78, a number
            # that is not m², not kg, not anything real. Disqualified
            # outright, before a single row is even read.
            _UNIT_WORDS = ("qty", "length", "width", "area", "weight", "wt",
                          "amount")
            numeric_cols = {c for c in range(1, len(headers) + 1)
                            if sum(w in headers[c - 1].lower()
                                  for w in _UNIT_WORDS) < 2}
            if len(headers) > 1:
                numeric_cols.discard(1)
            # item 58, same finding: the model's own last row in that table
            # was "Total sheet metal weight" -- already the sum of every
            # weight row above it. SUM()-ing a range that includes a row
            # which is ITSELF a sum of earlier rows in that same range
            # double (here, triple) counts. The first row whose own
            # description reads as a running total is where the SUM range
            # ends -- a real total still gets WRITTEN to the sheet exactly
            # where the model put it, just never folded into a further sum.
            _TOTAL_WORD = re.compile(r"\btotal\b", re.I)
            sum_last_row = None
            for r in b["rows"]:
                for c, val in enumerate(r[:len(headers)], start=1):
                    cell = ws.cell(row, c, compile_cell(val))
                    touch(c, _strip_inline_markdown(val))
                    cell.border = thin
                    is_numeric = isinstance(cell.value, (int, float)) or (
                        isinstance(cell.value, str) and cell.value.startswith("="))
                    if is_numeric:
                        cell.number_format = _XLSX_MONEY_FMT
                        cell.alignment = Alignment(horizontal="right")
                    else:
                        numeric_cols.discard(c)
                        cell.alignment = Alignment(
                            horizontal="left", vertical="top", wrap_text=True)
                        # item 59: a cell reading "TO CONFIRM" is the model
                        # saying a number here was never real -- the same
                        # weight as the standalone TO CONFIRM notes get,
                        # not left in the same plain text as an ordinary
                        # description cell beside it.
                        if _XLSX_TO_CONFIRM.search(str(cell.value)):
                            cell.font = Font(bold=True, color=_XLSX_WARN_INK)
                            cell.fill = PatternFill("solid", fgColor=_XLSX_WARN_FILL)
                if sum_last_row is None and any(
                        _TOTAL_WORD.search(_strip_inline_markdown(v)) for v in r):
                    sum_last_row = row - 1
                row += 1
            last_data_row = row - 1
            sum_last_row = last_data_row if sum_last_row is None else sum_last_row
            if sum_last_row >= first_data_row:
                amount_col = max(numeric_cols) if numeric_cols else None
                sections.append({
                    "label": last_heading or headers[0],
                    "header": headers[amount_col - 1] if amount_col else "",
                    "col": amount_col, "first": first_data_row,
                    "last": sum_last_row,
                })
            row += 1
        row += 1   # a blank row between blocks, the same visual break a
                   # heading/paragraph/table gets in the docx version
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w + 2
    return sections


_FORMULA_TOKEN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", name.strip().lower().replace(" ", "_"))


def _find_inputs_table(blocks: list) -> tuple[dict | None, list]:
    """The model's own '## INPUTS' table (see item 52's prompt instruction
    this answers), and the rest of the document with that heading and
    table lifted out -- or (None, blocks) UNCHANGED when the model never
    produced one, which is every answer before this item existed and any
    answer a model doesn't follow the new instruction on. That is the
    fallback this whole feature leans on: no Inputs table found is not an
    error, it is `markdown_to_xlsx` building exactly today's flat sheet,
    the same as if item 52 had never been written."""
    for i, b in enumerate(blocks):
        if b["type"] != "heading" or not re.search(r"\binputs?\b", b["text"], re.I):
            continue
        for j in range(i + 1, len(blocks)):
            if blocks[j]["type"] == "heading":
                break
            if blocks[j]["type"] == "table" and blocks[j]["headers"]:
                rest = [x for k, x in enumerate(blocks) if k not in (i, j)]
                return blocks[j], rest
    return None, blocks


def _inputs_columns(headers: list) -> dict:
    low = [h.strip().lower() for h in headers]

    def find(name, default):
        return low.index(name) if name in low else default

    return {"name": find("name", 0),
           "value": find("value", 1 if len(low) > 1 else 0),
           "unit": find("unit", 2 if len(low) > 2 else None),
           "note": find("note", 3 if len(low) > 3 else None)}


def _write_inputs_sheet(wb, table: dict) -> dict:
    """The Inputs sheet (Name | Value | Unit | Note, one editable row per
    design parameter) and the name -> cell-address map every formula in
    the BOQ sheet is compiled against. Matched on BOTH the model's own
    Name text and a slugged version of it -- the prompt asks for
    lowercase_with_underscores, but a formula cell and the Inputs row it
    refers to must still resolve to the same entry even when the model
    is slightly inconsistent between the two (a real, not hypothetical,
    risk any free-text contract like this one carries)."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    thin_side = Side(style="thin", color=_XLSX_GRID)
    thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    ws = wb.create_sheet("Inputs")
    for c, h in enumerate(("Name", "Value", "Unit", "Note"), start=1):
        cell = ws.cell(1, c, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=_XLSX_HEAD_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin
    cols = _inputs_columns(table["headers"])
    name_to_cell: dict[str, str] = {}
    row = 2
    for r in table["rows"]:
        def get(idx):
            return _strip_inline_markdown(r[idx]).strip() if (
                idx is not None and idx < len(r)) else ""
        name = get(cols["name"])
        if not name:
            continue
        name_cell = ws.cell(row, 1, name)
        name_cell.font = Font(bold=True, color=_XLSX_INK)
        # item 72 (12 Nov 2026), found live: a real run wrote a Value cell
        # here as "={shs40_mm}*{shs40_mm}-..." -- a derived input (a
        # pipe's own mass/m) computed from earlier, more basic ones, the
        # model's own reasonable idea, just never asked for in THIS
        # column. Plain _xlsx_cell_value() has no formula concept at all,
        # but openpyxl itself still reads any string starting with '='
        # as a real formula the moment it is assigned to a cell -- so the
        # UNCOMPILED "{shs40_mm}" tokens went straight into the saved
        # file's own <f> element verbatim. Curly braces are not valid
        # Excel formula syntax; Excel's own stricter parser (unlike
        # openpyxl's, which stayed silent) flagged the workbook as
        # needing repair on open, and stripped the broken formula along
        # with everything else sharing its calc chain -- "most of the
        # formulas just vanished" was that repair, not a separate bug.
        # _compile_cell already has the exact right fallback (a real
        # formula when every {name} it names resolves -- an EARLIER
        # Inputs row, since name_to_cell is built top-down as this loop
        # runs; a plain literal otherwise, never a broken <f>) -- it was
        # simply never reached for this column before now.
        value_cell = ws.cell(row, 2, _compile_cell(get(cols["value"]), name_to_cell))
        if isinstance(value_cell.value, (int, float)):
            value_cell.number_format = _XLSX_MONEY_FMT
        if (isinstance(value_cell.value, str)
                and _XLSX_TO_CONFIRM.search(value_cell.value)):
            # item 59: this ONE cell is where it actually matters most --
            # an unresolved Value here is not just a note to read, it is
            # the reason every formula on the BOQ sheet that names this
            # row comes back blank or #VALUE! until a real number is
            # typed in. The warning fill wins over the ordinary
            # "editable" blue tint below, not alongside it.
            value_cell.font = Font(bold=True, color=_XLSX_WARN_INK)
            value_cell.fill = PatternFill("solid", fgColor=_XLSX_WARN_FILL)
        else:
            # Blue-on-light ink for the editable Value column -- the same
            # "blue is editable, black is formula" convention claude.ai's
            # own comparison file already uses, so changing a number here
            # reads as something the sheet INVITES, not something that
            # might break it.
            value_cell.font = Font(color="1A56DB")
            value_cell.fill = PatternFill("solid", fgColor="EFF6FF")
        unit_cell = ws.cell(row, 3, get(cols["unit"]))
        note_cell = ws.cell(row, 4, get(cols["note"]))
        note_cell.alignment = Alignment(wrap_text=True, vertical="top")
        if _XLSX_TO_CONFIRM.search(note_cell.value or ""):
            note_cell.font = Font(color=_XLSX_WARN_INK)
        for cell in (name_cell, value_cell, unit_cell, note_cell):
            cell.border = thin
        ref = f"Inputs!$B${row}"
        name_to_cell[name.lower()] = ref
        name_to_cell[_slug(name)] = ref
        row += 1
    for c, w in zip("ABCD", (30, 14, 10, 50)):
        ws.column_dimensions[c].width = w
    ws.freeze_panes = "A2"
    return name_to_cell


_BARE_TOKEN = re.compile(r"^\{([A-Za-z_][A-Za-z0-9_]*)\}$")


def _compile_cell(raw: str, name_to_cell: dict):
    """A `={...}` cell from the model's own answer (item 52's prompt
    instruction) becomes a REAL Excel formula, `{name}` tokens replaced by
    the Inputs cell they name. A `{name}` the Inputs table never declared
    -- or a cell that was never a formula at all -- falls back to
    `_xlsx_cell_value`'s own plain literal: a workbook that is honestly
    static where the model didn't follow the contract beats a cell
    silently showing Excel's #NAME? with nothing telling the reader why.

    item 61 (4 Nov 2026), found live: a real run's Hardware section had
    "Handles" / "Legs" / "Rubber pads" quantity cells written as a BARE
    `{number_of_handles}`, `{legs_count}`... -- the model's own clear
    intent to reference an Input, just missing the leading '=' the
    contract asks for. Left as plain text, the cell literally showed the
    curly braces in Excel rather than the number 12. A cell that is
    NOTHING BUT one declared token, with or without the '=' the model
    forgot, resolves the same way -- this is not guessing at intent from
    partial text (a cell that mixes a token into a sentence still needs
    its own explicit '=' to be read as a formula), only the one
    unambiguous case where the whole cell already IS the reference."""
    s = _strip_inline_markdown(raw).strip()
    if not s.startswith("="):
        bare = _BARE_TOKEN.match(s)
        if bare and bare.group(1).lower() in name_to_cell:
            return "=" + name_to_cell[bare.group(1).lower()]
        return _xlsx_cell_value(raw)
    expr = s[1:]
    tokens = _FORMULA_TOKEN.findall(expr)
    if not tokens or any(t.lower() not in name_to_cell for t in tokens):
        return _xlsx_cell_value(raw)
    return "=" + _FORMULA_TOKEN.sub(
        lambda m: name_to_cell[m.group(1).lower()], expr)


def _write_summary_sheet(wb, sections: list[dict]) -> None:
    """One row per BOQ section, a live `=SUM(...)` of that section's own
    detected amount column on the BOQ sheet, plus a grand total that SUMs
    this sheet's own Total column -- so editing one Inputs value recalcs
    the BOQ sheet's formulas, which recalcs this one too, the whole point
    of a "live" workbook over a static snapshot. A section with no
    reliably-numeric column (every real row had some non-numeric cell in
    every column -- a TO CONFIRM note row, say) is still listed, with no
    total rather than a guessed one."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    thin_side = Side(style="thin", color=_XLSX_GRID)
    thin = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    ws = wb.create_sheet("Summary", 0)
    for c, h in enumerate(("Section", "Column", "Total"), start=1):
        cell = ws.cell(1, c, h)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=_XLSX_HEAD_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin
    row = 2
    for sec in sections:
        label = ws.cell(row, 1, sec["label"])
        label.font = Font(bold=True)
        label.fill = PatternFill("solid", fgColor=_XLSX_SECTION_FILL)
        ws.cell(row, 2, sec["header"])
        total_cell = ws.cell(row, 3)
        if sec["col"]:
            letter = get_column_letter(sec["col"])
            total_cell.value = f"=SUM(BOQ!{letter}{sec['first']}:{letter}{sec['last']})"
            total_cell.number_format = _XLSX_MONEY_FMT
        for cell in (label, ws.cell(row, 2), total_cell):
            cell.border = thin
        row += 1
    if row > 2:
        label = ws.cell(row + 1, 2, "Grand total")
        label.font = Font(bold=True, italic=True)
        label.fill = PatternFill("solid", fgColor=_XLSX_GRAND_FILL)
        grand = ws.cell(row + 1, 3)
        grand.font = Font(bold=True)
        grand.fill = PatternFill("solid", fgColor=_XLSX_GRAND_FILL)
        grand.number_format = _XLSX_MONEY_FMT
        # item 61 (4 Nov 2026), found live on the owner's own next run
        # right after item 58's fix: a model that gives its BOQ a
        # dedicated "RAW MATERIAL REQUIREMENT" section (grouping the SAME
        # sheet/pipe weight already counted in an earlier "Fabricated
        # Items" section by material type, for ordering) gets correctly
        # summed section by section now -- but blindly SUM-ing those
        # section totals together double-counts: the recap section is
        # not an ADDITIONAL quantity, it is the same material re-grouped.
        # No generic rule can tell which EARLIER sections a recap section
        # re-states (here: Fabricated Items, not Hardware) without
        # understanding what each section actually contains -- so rather
        # than guess which to exclude and risk a new, different wrong
        # number, the Grand Total abstains entirely whenever a recap
        # section is present, and says so. The recap section's OWN total,
        # two rows above whichever one matches, stays correct and is the
        # one to read -- the same "section of record" shape every real
        # BOQ's own raw-material section this add-on has seen already has.
        recap = next((s for s in sections
                     if _XLSX_RECAP_HEADING.search(s["label"] or "")), None)
        if recap is None:
            grand.value = f"=SUM(C2:C{row - 1})"
        else:
            label.value = "Grand total — not shown"
            grand.value = ""
            grand.alignment = Alignment(wrap_text=True, vertical="top")
            note = ws.cell(row + 1, 4, (
                f"Summing every section above would double-count "
                f"\"{recap['label'] or ''}\" -- it re-groups material "
                f"already counted elsewhere by type. Read that section's "
                f"own total directly."))
            note.font = Font(italic=True, color=_XLSX_WARN_INK)
            note.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in (label, grand):
            cell.border = thin
    for c, w in zip("ABCD", (34, 28, 16, 60)):
        ws.column_dimensions[c].width = w
    ws.freeze_panes = "A2"


def markdown_to_xlsx(text: str, path: str) -> str:
    """Same blocks `markdown_to_docx` reads. Two shapes, picked by what
    the model's own answer actually contains:

    - item 52 (4 Nov 2026): an '## INPUTS' table plus `={expr}` formula
      cells in the BOQ table(s) -- asked for only when this format is
      chosen for a Prism Agent (dialog.py's own `_format_request_line`) --
      becomes a real 3-sheet LIVE workbook (Inputs/BOQ/Summary), the same
      shape a real client comparison found claude.ai's own answer to the
      identical job already has: change one Inputs value and the BOQ and
      Summary sheets recalculate, because the cells are real Excel
      formulas, not numbers this module computed in Python and pasted in.
    - item 51 (3 Nov 2026): no Inputs table at all -- a model that was
      never asked for one, or didn't follow the instruction -- is exactly
      today's single flat worksheet, numeric cells kept numeric, nothing
      about this function's old behaviour changed."""
    import openpyxl

    blocks = parse_markdown(text)
    inputs_table, rest_blocks = _find_inputs_table(blocks)
    wb = openpyxl.Workbook()
    if inputs_table is not None:
        wb.remove(wb.active)   # the default empty "Sheet" -- not one of ours
        # Built Inputs, then BOQ, then Summary inserted at 0 -- same sheet
        # order (Summary, Inputs, BOQ) the real claude.ai comparison file
        # that prompted this item has, left-to-right in the workbook tabs.
        name_to_cell = _write_inputs_sheet(wb, inputs_table)
        ws = wb.create_sheet("BOQ")
        sections = _write_blocks_to_sheet(
            ws, rest_blocks, lambda raw: _compile_cell(raw, name_to_cell))
        _write_summary_sheet(wb, sections)
    else:
        ws = wb.active
        ws.title = "BOQ"
        _write_blocks_to_sheet(ws, blocks, _xlsx_cell_value)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    wb.save(path)
    return path


def markdown_to_csv(text: str, path: str) -> str:
    """The BIGGEST table in the answer (most rows) -- almost always the
    BOQ item schedule itself, not a small preamble table. No table found
    at all -> the plain text, one line per row, so a CSV is still
    produced rather than silently nothing."""
    blocks = parse_markdown(text)
    tables = [b for b in blocks if b["type"] == "table"]
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not tables:
            w.writerow(["text"])
            for line in (text or "").splitlines():
                if line.strip():
                    w.writerow([line.strip()])
            return path
        table = max(tables, key=lambda t: len(t["rows"]))
        w.writerow(table["headers"])
        for row in table["rows"]:
            w.writerow(row)
    return path


def _inline_markdown_to_html(text: str) -> str:
    """Same job as _add_inline_markdown (docx), for the PDF path: turn
    `**bold**`/`` `code` `` into real <b>/<code> spans instead of leaving
    the asterisks/backticks as literal escaped text. Every text segment
    (plain, bold or code) is still run through _html.escape -- only the
    markdown syntax characters themselves are consumed, never the
    person's/AI's own content, so an amount like "a < b" stays safe."""
    parts: list[str] = []
    pos = 0
    for m in _INLINE_SPAN.finditer(text or ""):
        if m.start() > pos:
            parts.append(_html.escape(text[pos:m.start()]))
        bold_span, code_span = m.group(1), m.group(2)
        if bold_span is not None:
            parts.append(f"<b>{_html.escape(bold_span)}</b>")
        else:
            parts.append(f"<code>{_html.escape(code_span)}</code>")
        pos = m.end()
    if pos < len(text or ""):
        parts.append(_html.escape(text[pos:]))
    return "".join(parts)


def _markdown_to_html(text: str) -> str:
    blocks = parse_markdown(text)
    parts = [
        "<html><head><meta charset='utf-8'><style>",
        "body{font-family:Arial,Helvetica,sans-serif;font-size:11px;padding:16px}",
        "table{border-collapse:collapse;width:100%;margin:10px 0}",
        "th,td{border:1px solid #999;padding:4px 6px;text-align:left;"
        "vertical-align:top}",
        "th{background:#eee}",
        "h1{font-size:18px}h2{font-size:15px}h3{font-size:13px}h4{font-size:12px}",
        "</style></head><body>",
    ]
    for b in blocks:
        if b["type"] == "heading":
            lvl = min(b["level"], 4)
            parts.append(f"<h{lvl}>{_inline_markdown_to_html(b['text'])}</h{lvl}>")
        elif b["type"] == "para":
            parts.append(f"<p>{_inline_markdown_to_html(b['text'])}</p>")
        elif b["type"] == "bullet":
            items = "".join(f"<li>{_inline_markdown_to_html(i)}</li>" for i in b["items"])
            parts.append(f"<ul>{items}</ul>")
        elif b["type"] == "table":
            head = "".join(f"<th>{_inline_markdown_to_html(h)}</th>" for h in b["headers"])
            rows = "".join(
                "<tr>" + "".join(f"<td>{_inline_markdown_to_html(c)}</td>" for c in row) + "</tr>"
                for row in b["rows"])
            parts.append(f"<table><tr>{head}</tr>{rows}</table>")
    parts.append("</body></html>")
    return "".join(parts)


_PDF_FOOTER = (
    "<div style='font-size:8px;width:100%;text-align:center;color:#888;'>"
    "<span class='pageNumber'></span> / <span class='totalPages'></span></div>")


def markdown_to_pdf(text: str, path: str) -> str:
    """Same technique core.boq_price.write_boq_pdf already uses: render an
    HTML page with the bundled Chromium (Playwright) and print it."""
    html_str = _markdown_to_html(text)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                  # noqa: BLE001
        raise RuntimeError(
            "Exporting a PDF needs the bundled browser engine "
            "(Playwright/Chromium), which isn't available here. DOCX and "
            "CSV still work without it.") from e
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with sync_playwright() as pw:
        b = CB.browser.launch_chromium(
            pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        try:
            page = b.new_page()
            page.set_content(html_str, wait_until="load")
            page.pdf(path=path, format="A4", print_background=True,
                    margin={"top": "14mm", "bottom": "16mm",
                           "left": "12mm", "right": "12mm"},
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=_PDF_FOOTER)
        finally:
            b.close()
    return path


FORMAT_WRITERS = {
    "docx": markdown_to_docx,
    "csv": markdown_to_csv,
    "pdf": markdown_to_pdf,
    "xlsx": markdown_to_xlsx,
}


def write_file(text: str, fmt: str, path: str) -> str:
    writer = FORMAT_WRITERS.get((fmt or "").lower())
    if writer is None:
        raise ValueError(f"No writer for format {fmt!r}.")
    return writer(text, path)

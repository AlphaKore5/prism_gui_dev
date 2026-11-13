"""addons/boq/openrouter_writer.py -- item 30's "Prism Agent" write-up
path. The model returns text; this is what turns that text into the
actual DOCX/CSV/PDF file, since a plain API call has no file-export
feature of its own the way a browser tool does.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from addons.boq import openrouter_writer as W                      # noqa: E402
from addons.boq import agents as boq_agents                        # noqa: E402

_SAMPLE = """# BILL OF QUANTITIES

HVAC works for a commercial office floor.

## Section A

| Sr. | Description | Unit | Qty |
| --- | --- | --- | --- |
| A1 | GI duct 16x4, 24G | m | 12.22 |
| A2 | GI duct 20x10, 24G | m | 8.33 |

Notes:
- Rates are not included.
- Quantities are measured, not estimated.
"""


class ParseMarkdownReadsHeadingsParasListsAndTables(unittest.TestCase):
    def test_headings_keep_their_level(self):
        blocks = W.parse_markdown("# One\n\n### Three")
        self.assertEqual([(b["type"], b["level"]) for b in blocks],
                         [("heading", 1), ("heading", 3)])

    def test_a_table_is_found_between_its_header_and_separator_rows(self):
        blocks = W.parse_markdown(_SAMPLE)
        tables = [b for b in blocks if b["type"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["headers"], ["Sr.", "Description", "Unit", "Qty"])
        self.assertEqual(len(tables[0]["rows"]), 2)
        self.assertEqual(tables[0]["rows"][0], ["A1", "GI duct 16x4, 24G", "m", "12.22"])

    def test_a_separator_row_with_alignment_colons_still_counts(self):
        text = "| A | B |\n| :--- | ---: |\n| 1 | 2 |"
        tables = [b for b in W.parse_markdown(text) if b["type"] == "table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0]["rows"], [["1", "2"]])

    def test_a_pipe_row_with_no_separator_after_it_is_not_a_table(self):
        """A single pipe-looking line with ordinary text below it must not
        be mistaken for a table header with no rows."""
        text = "| not a table |\njust a paragraph"
        types = [b["type"] for b in W.parse_markdown(text)]
        self.assertNotIn("table", types)

    def test_bullets_and_numbered_items_both_become_a_bullet_block(self):
        blocks = W.parse_markdown("- one\n- two\n\n1. three\n2. four")
        bullets = [b for b in blocks if b["type"] == "bullet"]
        self.assertEqual(len(bullets), 2)
        self.assertEqual(bullets[0]["items"], ["one", "two"])
        self.assertEqual(bullets[1]["items"], ["three", "four"])

    def test_a_multi_line_paragraph_joins_into_one_block(self):
        blocks = W.parse_markdown("line one\nline two continues it")
        paras = [b for b in blocks if b["type"] == "para"]
        self.assertEqual(len(paras), 1)
        self.assertEqual(paras[0]["text"], "line one line two continues it")


class MarkdownToDocxBuildsARealDocument(unittest.TestCase):
    def test_headings_paragraphs_and_the_table_all_land_in_the_file(self):
        import docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.docx")
            W.markdown_to_docx(_SAMPLE, path)
            doc = docx.Document(path)
            texts = [p.text for p in doc.paragraphs if p.text]
            self.assertIn("BILL OF QUANTITIES", texts)
            self.assertEqual(len(doc.tables), 1)
            rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
            self.assertEqual(rows[0], ["Sr.", "Description", "Unit", "Qty"])
            self.assertEqual(len(rows), 3)   # header + 2 data rows


class MarkdownToDocxRendersInlineMarkdownForReal(unittest.TestCase):
    """item 49 (3 Nov 2026), found live by actually rendering a real
    generated .docx (macOS Quick Look) and looking at it: every
    `**bold**`/`` `code` `` span the writing AI put in its own answer --
    every prompt in this add-on asks for markdown -- came out as LITERAL
    asterisks and backticks in the Word file. parse_markdown() only ever
    parsed BLOCK structure; the text inside a block was passed through
    verbatim. The same root cause item 37 already fixed in the dialog's
    own result box (QPlainTextEdit vs QTextEdit) -- this is that bug one
    layer over, in the actual file the person opens afterwards."""

    def _doc(self, text: str):
        import docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.docx")
            W.markdown_to_docx(text, path)
            return docx.Document(path)

    def test_bold_markers_become_a_real_bold_run_not_literal_asterisks(self):
        doc = self._doc("**Client:** Pharmatech Company, qty **16**.")
        para = next(p for p in doc.paragraphs if "Pharmatech" in p.text)
        self.assertNotIn("*", para.text)
        bold_runs = [r.text for r in para.runs if r.bold]
        self.assertIn("Client:", bold_runs)
        self.assertIn("16", bold_runs)

    def test_code_span_becomes_monospace_not_literal_backticks(self):
        doc = self._doc("Source: `LN2_rack.pdf`, both pages.")
        para = next(p for p in doc.paragraphs if "LN2_rack.pdf" in p.text)
        self.assertNotIn("`", para.text)
        code_run = next(r for r in para.runs if r.text == "LN2_rack.pdf")
        self.assertEqual(code_run.font.name, "Courier New")

    def test_table_header_cells_are_bold_even_without_their_own_asterisks(self):
        doc = self._doc(_SAMPLE)
        header_cell = doc.tables[0].rows[0].cells[0]
        self.assertTrue(all(r.bold for r in header_cell.paragraphs[0].runs))

    def test_bold_inside_a_table_cell_also_renders_not_literal(self):
        text = (
            "| Item | Note |\n| --- | --- |\n"
            "| A1 | **200 kg** per bay |\n"
        )
        doc = self._doc(text)
        cell = doc.tables[0].rows[1].cells[1]
        self.assertNotIn("*", cell.text)
        self.assertTrue(any(r.bold for r in cell.paragraphs[0].runs))


class MarkdownToDocxUsesLandscapeAndRealColumnWidths(unittest.TestCase):
    """item 49: a 7-column BOQ table at python-docx's own default (equal
    widths, portrait page) wrapped a long description into 6+ lines per
    row while a 3-character "Unit" column sat mostly empty at the same
    width -- found visually, not assumed. Every real BOQ this add-on has
    produced or been shown has this shape (a few narrow columns beside
    one or two long description columns)."""

    def test_the_page_is_landscape(self):
        import docx
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.docx")
            W.markdown_to_docx(_SAMPLE, path)
            doc = docx.Document(path)
        section = doc.sections[0]
        self.assertGreater(section.page_width, section.page_height)

    def test_a_long_description_column_is_wider_than_a_short_qty_column(self):
        import docx
        text = (
            "| Item | Description | Qty |\n| --- | --- | --- |\n"
            "| A1 | A full sentence long enough to need real width | 1 |\n"
        )
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.docx")
            W.markdown_to_docx(text, path)
            doc = docx.Document(path)
        cols = doc.tables[0].columns
        self.assertGreater(cols[1].width, cols[0].width)
        self.assertGreater(cols[1].width, cols[2].width)


class MarkdownToCsvUsesTheBiggestTableNeverSilentlyEmpty(unittest.TestCase):
    def test_the_table_rows_land_in_the_csv_with_its_own_header(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            W.markdown_to_csv(_SAMPLE, path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], ["Sr.", "Description", "Unit", "Qty"])
            self.assertEqual(len(rows), 3)

    def test_the_bigger_of_two_tables_is_chosen(self):
        text = ("| a | b |\n| --- | --- |\n| 1 | 2 |\n\n"
               "| x | y |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n| 5 | 6 |")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            W.markdown_to_csv(text, path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], ["x", "y"])
            self.assertEqual(len(rows), 4)   # header + 3 data rows

    def test_no_table_at_all_still_produces_a_csv_not_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            W.markdown_to_csv("just some plain text\nanother line", path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], ["text"])
            self.assertEqual(len(rows), 3)   # header + 2 lines


class MarkdownToXlsxBuildsARealSpreadsheet(unittest.TestCase):
    """item 51 (4 Nov 2026): the owner compared a Prism BOQ against the
    same job made on claude.ai, which hands back a real .xlsx a reader can
    filter and sum -- next to Prism's single flat .docx table. This is the
    smaller, real gap: the same parse_markdown() blocks every other export
    already uses, into one worksheet instead of a Word table."""

    def test_the_heading_and_table_both_land_on_the_sheet(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_SAMPLE, path)
            wb = openpyxl.load_workbook(path)
            ws = wb.active
            values = [[c.value for c in row] for row in ws.iter_rows()]
            self.assertIn(["BILL OF QUANTITIES"], [r[:1] for r in values
                                                    if r and r[0] == "BILL OF QUANTITIES"])
            self.assertIn(["Sr.", "Description", "Unit", "Qty"],
                          [r[:4] for r in values])

    def test_a_qty_cell_is_a_real_number_not_text(self):
        """The whole reason this format exists next to the docx table --
        a reader can sum a Qty/Kg column in Excel, which a Word table or a
        plain-text cell never lets them do."""
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_SAMPLE, path)
            ws = openpyxl.load_workbook(path).active
            qty_cells = [c.value for row in ws.iter_rows() for c in row
                        if c.value == 12.22]
            self.assertEqual(qty_cells, [12.22])

    def test_a_header_cell_is_bold(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_SAMPLE, path)
            ws = openpyxl.load_workbook(path).active
            header_cells = [c for row in ws.iter_rows() for c in row
                            if c.value == "Description"]
            self.assertEqual(len(header_cells), 1)
            self.assertTrue(header_cells[0].font.bold)

    def test_a_bold_marker_in_a_cell_is_stripped_not_left_literal(self):
        import openpyxl
        text = "| Item | Note |\n| --- | --- |\n| A1 | **urgent** check |"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            values = [c.value for row in ws.iter_rows() for c in row]
            self.assertIn("urgent check", values)
            self.assertNotIn("**urgent** check", values)


class MarkdownToXlsxDrawsAttentionToSectionsAndToConfirmLines(unittest.TestCase):
    """item 59 (4 Nov 2026): the owner's own words -- "all the reference
    and everything important should be highlighted, all the sections in
    the BOQ should look like a single TOPIC that draws the user
    attention". A section heading used to be one bold cell in column A
    with the rest of its own row plain white; a TO CONFIRM line -- the
    model's own way of saying "this number is not real, you must supply
    it" -- sat in the exact same plain black text as an ordinary
    paragraph next to it."""

    def test_a_heading_merges_across_its_own_tables_full_width(self):
        import openpyxl
        text = ("# Section A\n\n| Sr | Description | Qty |\n"
                "| --- | --- | --- |\n| 1 | Wall | 12.22 |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            self.assertIn("A1:C1", [str(m) for m in ws.merged_cells.ranges])
            self.assertEqual(ws["A1"].fill.fgColor.rgb, "00E8EDF5")

    def test_a_title_with_nothing_tabular_under_it_is_not_merged(self):
        """The document's own opening title, with only plain paragraphs
        under it before the next heading -- nothing to merge across."""
        import openpyxl
        text = "# BOQ for Acme\n\nSome preamble text.\n\n# Section A\n\nMore text.\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            self.assertEqual(list(ws.merged_cells.ranges), [])

    def test_a_to_confirm_paragraph_gets_the_warning_fill(self):
        import openpyxl
        text = "# Notes\n\nTO CONFIRM: density not stated in the source.\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            cell = [c for row in ws.iter_rows() for c in row
                   if c.value and "density" in str(c.value)][0]
            self.assertEqual(cell.fill.fgColor.rgb, "00FBE4E4")
            self.assertTrue(cell.font.bold)

    def test_a_to_confirm_table_cell_gets_the_warning_fill_too(self):
        import openpyxl
        text = ("| Item | Weight (kg) |\n| --- | --- |\n"
                "| 1 | TO CONFIRM |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            cell = [c for row in ws.iter_rows() for c in row
                   if c.value == "TO CONFIRM"][0]
            self.assertEqual(cell.fill.fgColor.rgb, "00FBE4E4")

    def test_an_ordinary_line_gets_no_warning_treatment(self):
        import openpyxl
        text = "# Section A\n\nNothing unusual here.\n"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path).active
            cell = [c for row in ws.iter_rows() for c in row
                   if c.value == "Nothing unusual here."][0]
            self.assertEqual(cell.fill.fgColor.rgb, "00000000")


_LIVE_SAMPLE = """# BOQ - Test Rack

## INPUTS

| Name | Value | Unit | Note |
| --- | --- | --- | --- |
| frame_length_ft | 8.5 | ft | spec |
| wastage_mm | 100 | mm | client instruction |

## Section A

| Sr | Description | Qty | Unit | Net wt (kg) |
| --- | --- | --- | --- | --- |
| 1 | Main frame rail | 2 | m | ={frame_length_ft}*0.3048*2 |
| 2 | Cross member | 4 | m | ={wastage_mm}/1000*4 |
"""


class MarkdownToXlsxBuildsALiveWorkbookWhenTheModelProvidesOne(unittest.TestCase):
    """item 52 (4 Nov 2026): the owner asked for the bigger piece item 51's
    own writeup had deferred -- a real multi-sheet, live-formula workbook,
    the shape the same LN2 rack job's own claude.ai answer already has
    (Summary/Inputs/BOQ, change one input and the sheet recalculates).
    Scoped to when the model's own answer actually contains an '## INPUTS'
    table (dialog.py's own prompt instruction asks for one only when xlsx
    is chosen for a Prism Agent) -- every other answer still gets item
    51's own flat single sheet, unchanged."""

    def test_an_inputs_table_produces_three_sheets_in_claude_dot_ais_own_order(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_LIVE_SAMPLE, path)
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb.sheetnames, ["Summary", "Inputs", "BOQ"])

    def test_a_formula_cell_becomes_a_real_cross_sheet_excel_formula(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_LIVE_SAMPLE, path)
            wb = openpyxl.load_workbook(path)
            boq, inputs = wb["BOQ"], wb["Inputs"]
            self.assertEqual(inputs["A2"].value, "frame_length_ft")
            self.assertEqual(inputs["B2"].value, 8.5)
            formula_cells = [c.value for row in boq.iter_rows() for c in row
                             if isinstance(c.value, str) and c.value.startswith("=")]
            self.assertIn("=Inputs!$B$2*0.3048*2", formula_cells)
            self.assertIn("=Inputs!$B$3/1000*4", formula_cells)

    def test_an_undeclared_input_name_falls_back_to_plain_text_not_a_broken_formula(self):
        """A `{name}` the INPUTS table never declared must never become a
        formula Excel would show as #NAME? with no explanation -- it stays
        the model's own raw text, visible and honest about not being live.

        item 72 (12 Nov 2026): this test's own ORIGINAL assertions only
        ever checked `.value` (the same string whether the cell is a
        formula or plain text) -- they never caught that openpyxl was
        STILL writing this as a real `<f>` formula underneath, unresolved
        "{made_up_name}" token and all, which is exactly what made a real
        file need "repair" in Excel. A leading space now keeps the cell
        out of formula territory; `.value` keeps the content, `.data_type`
        is what actually proves it's text."""
        import openpyxl
        text = _LIVE_SAMPLE.replace(
            "={frame_length_ft}*0.3048*2", "={made_up_name}*2")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["BOQ"]
            cells = [c for row in ws.iter_rows() for c in row]
            match = [c for c in cells if isinstance(c.value, str)
                    and "made_up_name" in c.value]
            self.assertEqual(len(match), 1)
            self.assertEqual(match[0].value, " ={made_up_name}*2")
            self.assertNotEqual(match[0].data_type, "f")

    def test_a_bare_token_with_no_equals_sign_still_becomes_a_real_formula(self):
        """item 61 (4 Nov 2026), found live: a real run's Hardware section
        wrote quantity cells as a bare "{number_of_handles}" -- the
        model's own clear intent to reference an Input, just missing the
        '=' the contract asks for. Left as text, Excel showed the literal
        curly braces instead of the number. A cell that is NOTHING BUT
        one declared token resolves the same whether or not it has the
        '='; a token mixed into other text still needs it explicitly."""
        import openpyxl
        text = _LIVE_SAMPLE.replace(
            "| 1 | Main frame rail | 2 | m | ={frame_length_ft}*0.3048*2 |",
            "| 1 | Main frame rail | {frame_length_ft} | m | 10 |")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["BOQ"]
            values = [c.value for row in ws.iter_rows() for c in row]
            self.assertIn("=Inputs!$B$2", values)
            self.assertNotIn("{frame_length_ft}", values)

    def test_an_inputs_value_formula_referencing_an_earlier_row_becomes_real(self):
        """item 72 (12 Nov 2026), found live: a real run wrote an Inputs
        row's own Value as "={frame_length_ft}*2" -- a derived input
        computed from an earlier, more basic one. name_to_cell is built
        top-down as the Inputs sheet is written, so an earlier row is
        already resolvable by the time a later one names it."""
        import openpyxl
        text = _LIVE_SAMPLE.replace(
            "| wastage_mm | 100 | mm | client instruction |",
            "| wastage_mm | 100 | mm | client instruction |\n"
            "| derived_double_length | ={frame_length_ft}*2 | ft | computed |")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["Inputs"]
            self.assertEqual(ws["B4"].value, "=Inputs!$B$2*2")

    def test_an_inputs_value_formula_with_an_unresolved_name_never_becomes_a_broken_formula(self):
        """The real bug this item fixes: before this, ANY string starting
        with '=' assigned to a cell became a real Excel <f> formula
        whether or not its {name} tokens ever got substituted --
        openpyxl's own behaviour, not this module's choice. A formula
        naming something not yet declared (a forward reference, or a
        typo) must fall back to plain text, the same safe rule the BOQ
        sheet already had, never leaving a literal "{...}" inside a
        saved <f> element for Excel's own stricter parser to reject."""
        import openpyxl
        text = _LIVE_SAMPLE.replace(
            "| wastage_mm | 100 | mm | client instruction |",
            "| wastage_mm | 100 | mm | client instruction |\n"
            "| derived_bad | ={not_declared_anywhere}*2 | ft | computed |")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["Inputs"]
            self.assertEqual(ws["B4"].value, " ={not_declared_anywhere}*2")
            # The real regression: this cell must be a plain string, not
            # a formula -- a formula cell with unresolved {name} tokens
            # in it is exactly what made Excel's own stricter parser
            # reject the real file and offer to "repair" it.
            self.assertNotEqual(ws["B4"].data_type, "f")

    def test_the_summary_sheet_sums_the_boq_sections_own_amount_column(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_LIVE_SAMPLE, path)
            ws = openpyxl.load_workbook(path)["Summary"]
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            self.assertEqual(rows[0], ["Section", "Column", "Total"])
            self.assertEqual(rows[1][0], "Section A")
            self.assertEqual(rows[1][1], "Net wt (kg)")
            self.assertTrue(str(rows[1][2]).startswith("=SUM(BOQ!"))
            grand_total = [r for r in rows if r[1] == "Grand total"][0]
            self.assertTrue(str(grand_total[2]).startswith("=SUM("))

    def test_a_raw_material_requirement_section_disables_the_grand_total(self):
        """item 61 (4 Nov 2026), found live: a real run had a "Fabricated
        Items" section AND a "RAW MATERIAL REQUIREMENT" section that
        re-grouped the SAME sheet/pipe weight by material type for
        ordering -- not an additional quantity. Summing both into one
        Grand Total double-counted it. No generic rule can tell which
        earlier sections a recap section restates without understanding
        what each one actually contains, so the Grand Total abstains
        entirely whenever one is present, rather than guess and risk a
        new, different wrong number. Each section's own total (including
        the recap section's) stays correct and visible."""
        import openpyxl
        text = (_LIVE_SAMPLE +
               "\n## RAW MATERIAL REQUIREMENT\n\n"
               "| Material | Net Weight (kg) |\n| --- | --- |\n"
               "| SS304 | ={frame_length_ft}*8 |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["Summary"]
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            section_a = [r for r in rows if r[0] == "Section A"][0]
            recap = [r for r in rows if r[0] == "RAW MATERIAL REQUIREMENT"][0]
            self.assertTrue(str(section_a[2]).startswith("=SUM("))
            self.assertTrue(str(recap[2]).startswith("=SUM("))
            grand_row = [r for r in rows if r[1] == "Grand total — not shown"]
            self.assertEqual(len(grand_row), 1)
            self.assertIn(grand_row[0][2], (None, ""))
            self.assertFalse(any(
                r[1] == "Grand total" and str(r[2]).startswith("=SUM(")
                for r in rows))

    def test_a_section_with_no_real_amount_column_never_sums_the_item_number(self):
        """item 53 (4 Nov 2026), found live on the owner's own first real
        run: a "Bought-out / Miscellaneous Items" section whose every
        weight cell was honestly "TO CONFIRM" (correctly not guessed) left
        column 1 -- the Item/Sr NUMBER -- as the only column numeric in
        every row, and the real Summary sheet summed item numbers 1..6
        into a meaningless "Total" of 21. Column 1 is never eligible."""
        import openpyxl
        text = (_LIVE_SAMPLE + "\n## Section B\n\n"
               "| Item | Description | Weight (kg) |\n| --- | --- | --- |\n"
               "| 1 | Alignment tracks | TO CONFIRM |\n"
               "| 2 | Door mechanism | TO CONFIRM |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["Summary"]
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            section_b = [r for r in rows if r[0] == "Section B"][0]
            self.assertIsNone(section_b[2])

    def test_a_column_naming_two_different_measures_is_never_summed(self):
        """item 58 (4 Nov 2026), found live on a real run: a table headed
        "Qty/Length/Area/Weight" put an area-in-m2 row directly above a
        weight-in-kg row in the SAME column, with a "Total ..." row of
        its own at the bottom. The real Summary sheet summed all of it --
        area + weight + the already-summed total -- into 555.78, a number
        that is not m2, not kg, not anything real (confirmed: opened the
        real file in Excel and it computed that exact figure). A header
        naming 2+ distinct measures is now never eligible at all, and a
        row that is itself labelled "Total ..." is never folded into a
        further sum."""
        import openpyxl
        text = (_LIVE_SAMPLE +
               "\n## Mixed Section\n\n"
               "| Item | Description | Unit | Qty/Length/Area/Weight |\n"
               "| --- | --- | --- | --- |\n"
               "| 1.1 | Back panel - area | m2 | ={frame_length_ft}*{wastage_mm} |\n"
               "| 1.2 | Back panel - weight | kg | ={frame_length_ft}*8 |\n"
               "| 2 | Total sheet metal weight | kg | ={frame_length_ft}*8 |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            ws = openpyxl.load_workbook(path)["Summary"]
            rows = [[c.value for c in row] for row in ws.iter_rows()]
            mixed = [r for r in rows if r[0] == "Mixed Section"][0]
            self.assertIsNone(mixed[2])

    def test_a_trailing_total_row_is_never_folded_into_a_further_sum(self):
        """Same finding, isolated: even with single-unit headers (which
        DO stay eligible), a row whose own description is a running total
        must never be included in the SUM range above it -- that would
        double-count whatever it already adds up."""
        import openpyxl
        from openpyxl.utils import get_column_letter
        text = (_LIVE_SAMPLE +
               "\n## Weighed Section\n\n"
               "| Item | Description | Weight (kg) |\n"
               "| --- | --- | --- |\n"
               "| 1 | Part A | ={frame_length_ft}*2 |\n"
               "| 2 | Part B | ={frame_length_ft}*3 |\n"
               "| 3 | Total weight | ={frame_length_ft}*5 |\n")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(text, path)
            wb = openpyxl.load_workbook(path)
            boq = wb["BOQ"]
            # Find the row holding "Part A" to know where the real data starts.
            part_a_row = next(r for r in range(1, boq.max_row + 1)
                              if boq.cell(r, 2).value == "Part A")
            rows = [[c.value for c in row] for row in wb["Summary"].iter_rows()]
            weighed = [r for r in rows if r[0] == "Weighed Section"][0]
            letter = get_column_letter(3)
            self.assertEqual(
                weighed[2],
                f"=SUM(BOQ!{letter}{part_a_row}:{letter}{part_a_row + 1})")

    def test_no_inputs_table_at_all_stays_the_flat_single_sheet(self):
        """item 51's own behaviour, unchanged, for every answer that never
        has an INPUTS section -- most of them, and every one before this
        item existed."""
        import openpyxl
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.xlsx")
            W.markdown_to_xlsx(_SAMPLE, path)
            self.assertEqual(openpyxl.load_workbook(path).sheetnames, ["BOQ"])


class ModelForPicksTheTwoTierCorrectly(unittest.TestCase):
    def test_generation_uses_the_heavier_model(self):
        self.assertEqual(W.model_for("Prism Agent Claude", followup=False),
                         boq_agents.PRISM_AGENT_MODELS["Prism Agent Claude"])

    def test_followup_uses_the_lighter_model(self):
        self.assertEqual(W.model_for("Prism Agent Claude", followup=True),
                         boq_agents.PRISM_AGENT_FOLLOWUP_MODELS["Prism Agent Claude"])
        # item 62 (7 Nov 2026): both tiers are claude-haiku-5.5 now, on
        # purpose (see tests/test_boq_agents.py's own fuller comment on
        # this exact exception) -- "lighter" no longer means "a different
        # model" for this one agent, just the right dict either way, which
        # the assertEqual calls above and below already check.
        self.assertEqual(
            W.model_for("Prism Agent Claude", followup=True),
            W.model_for("Prism Agent Claude", followup=False))

    def test_an_unknown_agent_raises_rather_than_guessing_a_model(self):
        with self.assertRaises(ValueError):
            W.model_for("Not A Prism Agent", followup=False)


class WriteCallsOpenrouterWithTheRightModel(unittest.TestCase):
    def test_write_passes_the_generation_model_and_returns_the_text(self):
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="the answer") as chat:
            out = W.write("Prism Agent Deep", "a prompt", "sk-or-x")
        self.assertEqual(out, "the answer")
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Deep"], "a prompt",
            attachments=None, usage_out=mock.ANY, extra=W.WRITE_EXTRA)

    def test_a_cut_off_answer_is_refused_not_saved_as_a_boq(self):
        """item 81, 13 Nov 2026: a real run used 65,536 output tokens and
        the BOQ stopped mid-row in the return-duct table -- saved and
        opened as if finished."""
        def chat(*a, usage_out=None, **k):
            usage_out.update({"finish_reason": "length", "answer_from_reasoning": False})
            return "| RET-11 | 27 | ={duct_h_in} | 0.61 | 1 | ={perim_factor"
        with mock.patch.object(W.CB.openrouter, "openrouter_chat", side_effect=chat):
            with self.assertRaises(RuntimeError) as cm:
                W.write("Prism Agent Claude", "a prompt", "sk-or-x")
        self.assertIn("stops part-way", str(cm.exception))

    def test_working_notes_in_place_of_an_answer_are_refused(self):
        """item 81, 5 Nov 2026: "Prism Agent Deep" twice wrote 53,000 rows
        of its own reasoning into the BOQ sheet."""
        def chat(*a, usage_out=None, **k):
            usage_out.update({"finish_reason": "length", "answer_from_reasoning": True})
            return "The user wants a BOQ document. Let me go. OK."
        with mock.patch.object(W.CB.openrouter, "openrouter_chat", side_effect=chat):
            with self.assertRaises(RuntimeError) as cm:
                W.write("Prism Agent Deep", "a prompt", "sk-or-x")
        self.assertIn("working notes", str(cm.exception))

    def test_a_whole_answer_still_comes_back_and_fills_the_callers_usage(self):
        usage = {}
        def chat(*a, usage_out=None, **k):
            usage_out.update({"total_tokens": 9, "finish_reason": "stop",
                              "answer_from_reasoning": False})
            return "the BOQ"
        with mock.patch.object(W.CB.openrouter, "openrouter_chat", side_effect=chat):
            self.assertEqual(W.write("Prism Agent Claude", "p", "sk-or-x", usage_out=usage), "the BOQ")
        self.assertEqual(usage["total_tokens"], 9)

    def test_write_passes_the_followup_model_when_asked(self):
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="x") as chat:
            W.write("Prism Agent Deep", "a prompt", "sk-or-x", followup=True)
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_FOLLOWUP_MODELS["Prism Agent Deep"], "a prompt",
            attachments=None, usage_out=mock.ANY, extra=W.WRITE_EXTRA)


class HasVisionAndAttachmentGating(unittest.TestCase):
    """item 32: an attachment (a rendered drawing) only ever reaches
    OpenRouter for an agent that can actually look at it."""

    def test_claude_and_deep_both_have_vision(self):
        # item 38 (2 Nov 2026): Prism Agent Deep now maps to
        # deepseek-v4.1-flash at both tiers (was deepseek-v3.2/v4-flash,
        # text-only at any tier) -- verified for real, not just by
        # metadata, with a live OpenRouter call sending an actual client
        # drawing as a "file" block and getting back the real, correct
        # figures read off it. See agents.py's own comment on
        # PRISM_AGENT_HAS_VISION for the full evidence.
        self.assertTrue(W.has_vision("Prism Agent Claude"))
        self.assertTrue(W.has_vision("Prism Agent Deep"))

    def test_an_attachment_reaches_openrouter_for_a_vision_capable_agent(self):
        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="ok") as chat:
            W.write("Prism Agent Claude", "check it", "sk-or-x", attachments=att)
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Claude"], "check it",
            attachments=att, usage_out=mock.ANY, extra=W.WRITE_EXTRA)

    def test_an_attachment_also_reaches_openrouter_for_deep_now(self):
        """item 38: Deep used to be the no-vision example here -- now
        both Prism Agents can see a drawing, so this is the same
        assertion as the Claude test above, for the other agent."""
        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="ok") as chat:
            W.write("Prism Agent Deep", "check it", "sk-or-x", attachments=att)
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Deep"], "check it",
            attachments=att, usage_out=mock.ANY, extra=W.WRITE_EXTRA)

    def test_an_attachment_is_dropped_for_an_agent_with_no_vision(self):
        """Not an error -- the text-only question still gets answered,
        just without the drawing it can't see. Both real Prism Agents
        have vision as of item 38, so PRISM_AGENT_HAS_VISION is patched
        here to exercise write()'s own drop-on-no-vision logic directly,
        independent of which real agent currently has that property."""
        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.dict(boq_agents.PRISM_AGENT_HAS_VISION,
                             {"Prism Agent Deep": False}), \
             mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="ok") as chat:
            out = W.write("Prism Agent Deep", "check it", "sk-or-x", attachments=att)
        self.assertEqual(out, "ok")
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Deep"], "check it",
            attachments=None, usage_out=mock.ANY, extra=W.WRITE_EXTRA)


class WriteFileDispatchesByFormat(unittest.TestCase):
    def test_docx_csv_pdf_and_xlsx_are_all_registered(self):
        self.assertEqual(set(W.FORMAT_WRITERS), {"docx", "csv", "pdf", "xlsx"})

    def test_an_unknown_format_raises_rather_than_silently_doing_nothing(self):
        with self.assertRaises(ValueError):
            W.write_file(_SAMPLE, "rtf", "/tmp/whatever.rtf")

    def test_write_file_routes_csv_to_markdown_to_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            W.write_file(_SAMPLE, "CSV", path)   # case-insensitive
            self.assertTrue(os.path.exists(path))


class ColumnGroupAndMappingMatchRealHeaderVariants(unittest.TestCase):
    """The exact header wordings seen in this add-on's own real client
    files (an ELV client's and approved CCTV_ELV_BOQ samples),
    not invented ones."""
    def test_sr_no_and_no_are_the_same_group(self):
        self.assertEqual(W._column_group("Sr No"), W._column_group("No"))

    def test_item_description_and_description_are_the_same_group(self):
        self.assertEqual(W._column_group("Item Description"),
                         W._column_group("Description"))

    def test_rate_inr_and_rate_are_the_same_group(self):
        self.assertEqual(W._column_group("Rate\n(INR)"), W._column_group("Rate"))

    def test_a_letterhead_cell_matches_no_group(self):
        self.assertIsNone(W._column_group("To"))

    def test_map_columns_skips_a_template_column_with_no_match(self):
        mapping = W._map_columns(["Sr No", "Item Description", "Basis"],
                                 ["Sr.", "Description", "Qty"])
        self.assertEqual(mapping, {0: 0, 1: 1})   # "Basis" stays unmapped


def _template_docx(path: str) -> None:
    """A small stand-in for a client's own approved BOQ: one real
    line-item table with stale data (to prove it gets REPLACED, not
    appended to) and one letterhead-style table (to prove it is left
    alone -- it has nothing a BOQ line item could ever map onto)."""
    import docx
    doc = docx.Document()
    doc.add_paragraph("CLIENT NAME (letterhead)")
    info = doc.add_table(rows=1, cols=2)
    info.rows[0].cells[0].text = "To"
    info.rows[0].cells[1].text = "Client name"
    items = doc.add_table(rows=2, cols=6)
    for c, h in enumerate(["Sr No", "Item Description", "Qty", "Unit",
                          "Rate (INR)", "Amount (INR)"]):
        items.rows[0].cells[c].text = h
    for c, v in enumerate(["1", "STALE old line item", "99", "Nos", "1", "99"]):
        items.rows[1].cells[c].text = v
    doc.save(path)


_DRAFTED_MATCHING = """# BILL OF QUANTITIES

## CCTV Component

| Sr. | Description | Qty | Unit | Rate (INR) | Amount (INR) |
| --- | --- | --- | --- | --- | --- |
| C1 | IR Dome Camera, 5MP | 48 | Nos |  |  |
| C2 | PTZ Camera, 20x zoom | 2 | Nos |  |  |

## Access Control

| No | Note |
| --- | --- |
| E1 | Not covered by the template at all |
"""


class FillTemplateDocxKeepsTheClientsOwnFileAndFillsItInPlace(unittest.TestCase):
    def test_the_matching_table_is_replaced_not_appended_to(self):
        with tempfile.TemporaryDirectory() as d:
            template = os.path.join(d, "template.docx")
            out = os.path.join(d, "out.docx")
            _template_docx(template)
            report = W.fill_template_docx(_DRAFTED_MATCHING, template, out)
            self.assertEqual(report["matched"], 1)
            import docx
            doc = docx.Document(out)
            rows = [[c.text for c in r.cells] for r in doc.tables[1].rows]
            self.assertEqual(rows[0], ["Sr No", "Item Description", "Qty",
                                       "Unit", "Rate (INR)", "Amount (INR)"])
            self.assertEqual(rows[1][:4], ["C1", "IR Dome Camera, 5MP", "48", "Nos"])
            self.assertEqual(rows[2][:4], ["C2", "PTZ Camera, 20x zoom", "2", "Nos"])
            self.assertEqual(len(rows), 3)   # header + 2 -- the stale row is gone

    def test_the_letterhead_table_is_left_completely_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            template = os.path.join(d, "template.docx")
            out = os.path.join(d, "out.docx")
            _template_docx(template)
            W.fill_template_docx(_DRAFTED_MATCHING, template, out)
            import docx
            doc = docx.Document(out)
            rows = [[c.text for c in r.cells] for r in doc.tables[0].rows]
            self.assertEqual(rows, [["To", "Client name"]])

    def test_a_drafted_section_with_nowhere_to_go_is_appended_not_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            template = os.path.join(d, "template.docx")
            out = os.path.join(d, "out.docx")
            _template_docx(template)
            report = W.fill_template_docx(_DRAFTED_MATCHING, template, out)
            self.assertEqual(report["unmatched_drafted"], ["Access Control"])
            import docx
            doc = docx.Document(out)
            texts = " ".join(p.text for p in doc.paragraphs)
            self.assertIn("NOT IN THE TEMPLATE", texts)
            self.assertIn("Access Control", texts)
            last_table_rows = [[c.text for c in r.cells] for r in doc.tables[-1].rows]
            self.assertEqual(last_table_rows[1][:2], ["E1", "Not covered by the template at all"])

    def test_a_template_with_no_matching_section_at_all_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            template = os.path.join(d, "template.docx")
            out = os.path.join(d, "out.docx")
            _template_docx(template)
            report = W.fill_template_docx("# Empty\n\nNo tables here at all.",
                                          template, out)
            self.assertEqual(report["matched"], 0)
            self.assertEqual(report["unmatched_template"], 1)   # the items table


if __name__ == "__main__":
    unittest.main()

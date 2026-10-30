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


class ModelForPicksTheTwoTierCorrectly(unittest.TestCase):
    def test_generation_uses_the_heavier_model(self):
        self.assertEqual(W.model_for("Prism Agent Claude", followup=False),
                         boq_agents.PRISM_AGENT_MODELS["Prism Agent Claude"])

    def test_followup_uses_the_lighter_model(self):
        self.assertEqual(W.model_for("Prism Agent Claude", followup=True),
                         boq_agents.PRISM_AGENT_FOLLOWUP_MODELS["Prism Agent Claude"])
        self.assertNotEqual(
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
            attachments=None)

    def test_write_passes_the_followup_model_when_asked(self):
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="x") as chat:
            W.write("Prism Agent Deep", "a prompt", "sk-or-x", followup=True)
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_FOLLOWUP_MODELS["Prism Agent Deep"], "a prompt",
            attachments=None)


class HasVisionAndAttachmentGating(unittest.TestCase):
    """item 32: an attachment (a rendered drawing) only ever reaches
    OpenRouter for an agent that can actually look at it."""

    def test_claude_has_vision_deep_does_not(self):
        self.assertTrue(W.has_vision("Prism Agent Claude"))
        self.assertFalse(W.has_vision("Prism Agent Deep"))

    def test_an_attachment_reaches_openrouter_for_a_vision_capable_agent(self):
        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="ok") as chat:
            W.write("Prism Agent Claude", "check it", "sk-or-x", attachments=att)
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Claude"], "check it",
            attachments=att)

    def test_an_attachment_is_dropped_for_an_agent_with_no_vision(self):
        """Not an error -- the text-only question still gets answered,
        just without the drawing it can't see."""
        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="ok") as chat:
            out = W.write("Prism Agent Deep", "check it", "sk-or-x", attachments=att)
        self.assertEqual(out, "ok")
        chat.assert_called_once_with(
            "sk-or-x", boq_agents.PRISM_AGENT_MODELS["Prism Agent Deep"], "check it",
            attachments=None)


class WriteFileDispatchesByFormat(unittest.TestCase):
    def test_docx_csv_and_pdf_are_all_registered(self):
        self.assertEqual(set(W.FORMAT_WRITERS), {"docx", "csv", "pdf"})

    def test_an_unknown_format_raises_rather_than_silently_doing_nothing(self):
        with self.assertRaises(ValueError):
            W.write_file(_SAMPLE, "xlsx", "/tmp/whatever.xlsx")

    def test_write_file_routes_csv_to_markdown_to_csv(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            W.write_file(_SAMPLE, "CSV", path)   # case-insensitive
            self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()

"""widgets/markdown.render_markdown: tables and links.

The answer window, History, the completion screen, the follow-up window and
the file viewer all render AI answers with render_markdown. It drew a table
as raw `| a | b |` lines and a link as raw `[text](url)`, while the chat
thread (Qt's own setMarkdown) drew both properly: the same answer looked
right in the chat and broken in History. Everything stays escaped: the text
comes from an AI or a customer's email.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtGui import QTextTable                              # noqa: E402
from PySide6.QtWidgets import QApplication, QTextBrowser          # noqa: E402

from widgets.markdown import render_markdown                      # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

TABLE = """Here is the BOQ:

| Item | Qty | Rate |
|:-----|----:|-----:|
| GI duct **600x400** | 42 | 1,450 |
| Diffuser | 12 | 2,300 |

Total below."""


_VIEWS = []        # the tables live in their document; keep each view alive


def _tables(html: str):
    view = QTextBrowser()
    view.setHtml(html)
    _VIEWS.append(view)
    frames = view.document().rootFrame().childFrames()
    return [f for f in frames if isinstance(f, QTextTable)]


def test_a_table_becomes_a_real_qt_table_with_its_rows_and_columns():
    tables = _tables(render_markdown(TABLE))
    assert len(tables) == 1
    t = tables[0]
    assert (t.rows(), t.columns()) == (3, 3)
    assert t.cellAt(0, 0).firstCursorPosition().block().text() == "Item"
    assert t.cellAt(1, 0).firstCursorPosition().block().text() == "GI duct 600x400"
    assert t.cellAt(2, 2).firstCursorPosition().block().text() == "2,300"


def test_text_around_the_table_is_kept_and_no_raw_pipes_remain():
    html = render_markdown(TABLE)
    assert "Here is the BOQ:" in html and "Total below." in html
    assert "|" not in html
    assert "<b>600x400</b>" in html          # inline markdown works inside a cell


def test_a_table_without_outer_pipes_is_still_a_table():
    tables = _tables(render_markdown("Floor | AHU\n--- | ---\nL2 | AHU-2"))
    assert len(tables) == 1 and (tables[0].rows(), tables[0].columns()) == (2, 2)


def test_a_line_with_pipes_but_no_separator_row_stays_a_paragraph():
    html = render_markdown("Use a | b when piping.\nNext line.")
    assert "<table" not in html and "a | b" in html


def test_a_cell_cannot_inject_html():
    html = render_markdown("| a | b |\n|---|---|\n| <script>x()</script> | <img src=x> |")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html


def test_a_short_row_is_padded_and_a_long_row_is_not_lost():
    t = _tables(render_markdown("| a | b | c |\n|---|---|---|\n| 1 |\n| 1 | 2 | 3 | 4 |"))[0]
    assert t.columns() >= 3 and t.rows() == 3


def test_a_web_link_becomes_a_link():
    html = render_markdown("See [the spec](https://example.com/spec?a=1&b=2).")
    assert "<a href=\"https://example.com/spec?a=1&amp;b=2\">the spec</a>" in html


def test_a_local_file_link_becomes_a_link_the_viewer_routes():
    html = render_markdown("[report](file:///tmp/report.csv)")
    assert "<a href=\"file:///tmp/report.csv\">report</a>" in html


def test_a_junk_scheme_is_shown_as_text_not_a_link():
    html = render_markdown("[click](javascript:alert(1)) and [d](data:text/html,x)")
    assert "<a " not in html
    assert "click" in html


def test_a_quote_in_a_url_cannot_break_out_of_the_attribute():
    html = render_markdown('[x](https://a.com/"onmouseover="alert(1))')
    assert 'onmouseover="' not in html


def test_the_file_viewer_shows_a_markdown_table_as_a_table(tmp_path):
    from unittest import mock
    from dialogs import file_viewer as FV
    md = tmp_path / "notes.md"
    md.write_text(TABLE, encoding="utf-8")
    with mock.patch.object(FV, "_ReadWorker"):            # the builder is what is tested
        dlg = FV.FileViewer(str(md))
    dlg._build_markdown({"text": TABLE})
    views = dlg.findChildren(QTextBrowser)
    assert any(isinstance(f, QTextTable)
               for v in views for f in v.document().rootFrame().childFrames())

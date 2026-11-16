"""The on-screen look of a written BOQ. Display only.

Qt renders the writer's markdown with browser-default tables (black grid,
Times-like margins, bold black headings). This restyles the DOCUMENT the
result box shows, after `setMarkdown`, to the AlphaKore look: hairline row
rules, a soft header band, mono tabular numbers, Geist headings, a heavier
totals row. It changes formats only, never text, so the plain text and the
markdown the box reports are identical before and after, and nothing saved
or exported is read from this box (that comes from the raw answer and the
engine's own writers).
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt

from PySide6.QtGui import (
    QBrush, QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextFrameFormat, QTextLength, QTextTable, QTextTableCellFormat, QTextTableFormat,
)

import theme

_NUMBER = re.compile(r"^[\s₹$€£+-]*[\d][\d,]*(\.\d+)?\s*[%a-zA-Z²³/.]*$")
_TOTAL = re.compile(r"^\s*(grand\s+total|total|sub-?total)\b", re.I)
_HEADING_PT = {1: 17, 2: 15, 3: 13.5, 4: 12.5}


def _mono() -> QFont:
    f = QFont(theme.FONT_MONO)
    f.setStyleHint(QFont.Monospace)
    f.setPixelSize(13)
    return f


def style_document(doc, body_px: int = 14) -> None:
    doc.setDocumentMargin(4)
    _headings(doc)
    root = doc.rootFrame()
    for table in _tables(root):
        _table(table)


def _headings(doc) -> None:
    block = doc.begin()
    while block.isValid():
        level = block.blockFormat().headingLevel()
        if level:
            cur = QTextCursor(block)
            fmt = QTextCharFormat()
            fmt.setFontFamilies([theme.FONT_BODY])
            fmt.setFontWeight(QFont.Medium)
            fmt.setForeground(QBrush(QColor(theme.INK)))
            fmt.setFontPointSize(_HEADING_PT.get(level, 13))
            cur.movePosition(QTextCursor.StartOfBlock)
            cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            cur.mergeCharFormat(fmt)
            bf = QTextBlockFormat(block.blockFormat())
            bf.setTopMargin(14 if level <= 2 else 10)
            bf.setBottomMargin(4)
            cur.mergeBlockFormat(bf)
        block = block.next()


def _tables(frame):
    it = frame.begin()
    while not it.atEnd():
        child = it.currentFrame()
        if isinstance(child, QTextTable):
            yield child
        elif child is not None:
            yield from _tables(child)
        it += 1


def _table(table: QTextTable) -> None:
    fmt = table.format()
    fmt.setBorder(0)
    fmt.setCellSpacing(0)
    fmt.setCellPadding(8)
    fmt.setBorderStyle(QTextFrameFormat.BorderStyle_None)
    fmt.setWidth(QTextLength(QTextLength.PercentageLength, 100))
    fmt.setTopMargin(6)
    fmt.setBottomMargin(10)
    table.setFormat(fmt)
    rows, cols = table.rows(), table.columns()
    numeric_cols = {c for c in range(1, cols)
                    if rows > 1 and all(_NUMBER.match(_text(table, r, c)) or not _text(table, r, c)
                                        for r in range(1, rows))
                    and any(_text(table, r, c) for r in range(1, rows))}
    for r in range(rows):
        first = table.cellAt(r, 0)
        cur = first.firstCursorPosition()
        is_total = bool(_TOTAL.match(_text(table, r, 0)))
        for c in range(cols):
            cell = table.cellAt(r, c)
            cf = cell.format().toTableCellFormat()
            cf.setBorder(0)
            cf.setBottomBorder(1)
            cf.setBottomBorderBrush(QBrush(QColor(theme.HAIRLINE)))
            cf.setBottomBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            if r == 0:
                cf.setBackground(QBrush(QColor(theme.WELL)))
            elif is_total:
                cf.setTopBorder(1)
                cf.setTopBorderBrush(QBrush(QColor(theme.INK)))
                cf.setTopBorderStyle(QTextFrameFormat.BorderStyle_Solid)
            cell.setFormat(cf)
            cc = cell.firstCursorPosition()
            cc.movePosition(QTextCursor.StartOfBlock)
            cc.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            text = cc.selectedText().strip()
            ch = QTextCharFormat()
            bf = QTextBlockFormat()
            numeric = False
            if r == 0:
                ch.setFontFamilies([theme.FONT_MONO])
                ch.setFontPointSize(8.5)
                ch.setFontWeight(QFont.DemiBold)
                ch.setForeground(QBrush(QColor(theme.MUTE)))
                cc.mergeCharFormat(ch)
                if c in numeric_cols:
                    bf.setAlignment(Qt.AlignRight)
                    numeric = True
            else:
                ch.setForeground(QBrush(QColor(theme.INK)))
                ch.setFontWeight(QFont.DemiBold if is_total else QFont.Normal)
                if c in numeric_cols and _NUMBER.match(text):
                    ch.setFontFamilies([theme.FONT_MONO])
                    ch.setFontPointSize(10)
                    bf.setAlignment(Qt.AlignRight)
                    numeric = True
                cc.mergeCharFormat(ch)
            if numeric:
                cc.mergeBlockFormat(bf)


def _text(table: QTextTable, r: int, c: int) -> str:
    cur = table.cellAt(r, c).firstCursorPosition()
    cur.movePosition(QTextCursor.StartOfBlock)
    cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
    return cur.selectedText().strip()

"""Tiny, defensive markdown → Qt-rich-text renderer.

Shared by the Prompt panel (task brief) and the Output panel (a stage's AI
response). Chat/LLM output is overwhelmingly prose + markdown, so rendering
it as real headings/bullets/bold reads far better than a monospace dump —
while the caller keeps the RAW text for copy/paste.

Qt's rich-text engine supports no border-radius and only a CSS subset, so
filled `<table>` cells stand in for code blocks (same trick as elsewhere).
Anything not recognized falls through to a clean paragraph, so unexpected
shapes still render sensibly rather than breaking."""
from __future__ import annotations
import html
import re

import theme

_MONO = "'JetBrains Mono','DejaVu Sans Mono',Consolas,monospace"

_H_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[\*\-•]\s+(.*)$")
_NUM_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_LABEL_RE = re.compile(r"^[A-Z0-9][A-Z0-9 &/,()#\-]{1,44}:?$")
_FENCE_RE = re.compile(r"^\s*```")
# A table's second line: cells of dashes, optional colons, optional outer pipes.
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
# [text](url) after escaping; the url stops at whitespace or ")".
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
# Only these become clickable; viewer.open_link routes them (web to the
# browser, file to Prism's viewer). Anything else stays plain text.
_LINK_SCHEMES = ("http://", "https://", "mailto:", "file://")


def _inline(text: str) -> str:
    """Escape, then apply the inline markdown these outputs actually use."""
    s = html.escape(text)
    s = _LINK_RE.sub(_link, s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+?)`",
               rf"<span style='font-family:{_MONO};"
               rf"color:{theme.ACCENT_RAMP[800]}'>\1</span>", s)
    return s


def _link(m: re.Match) -> str:
    """One escaped [text](url). The url is already escaped (so a quote is
    &quot; and cannot end the attribute); a scheme not in the list is left
    as the original text."""
    label, url = m.group(1), m.group(2)
    if not url.lower().startswith(_LINK_SCHEMES):
        return m.group(0)
    return f'<a href="{url}">{label}</a>'


def _cells(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def _table(head: list[str], rows: list[list[str]]) -> str:
    """A Markdown table as a Qt rich-text table: header bold on a tint, thin
    rules, every cell escaped through _inline."""
    width = max([len(head)] + [len(r) for r in rows])
    pad = lambda r: r + [""] * (width - len(r))          # noqa: E731
    out = ["<table border='1' cellspacing='0' cellpadding='6' "
           "style='border-collapse:collapse;border-color:#d4d4d8;margin:6px 0'>"]
    out.append("<tr>" + "".join(
        f"<th bgcolor='#efeff1' align='left' style='color:#1d1f20'>{_inline(c)}</th>"
        for c in pad(head)) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(
            f"<td style='color:#424244'>{_inline(c)}</td>" for c in pad(r)) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _label(text: str) -> str:
    return (f"<p style='color:{theme.ACCENT_RAMP[700]};font-weight:600;"
            f"font-size:11px;"
            f"letter-spacing:0.8px;margin:12px 0 4px 0'>"
            f"{html.escape(text.rstrip(':'))}</p>")


def _code_block(inner_escaped: str) -> str:
    return (f"<table width='100%' cellspacing='0' cellpadding='9' "
            f"style='margin:6px 0'><tr><td bgcolor='#e7e7ea'>"
            f"<pre style='white-space:pre-wrap;margin:0;font-family:{_MONO};"
            f"font-size:12px;color:#2b2b2d'>{inner_escaped}</pre></td></tr></table>")


def render_markdown(text: str) -> str:
    lines = (text or "").split("\n")
    out: list[str] = []
    i = 0
    list_kind: str | None = None   # "ul" | "ol" | None

    def close_list():
        nonlocal list_kind
        if list_kind:
            out.append(f"</{list_kind}>")
            list_kind = None

    def want_list(kind: str, style: str):
        nonlocal list_kind
        if list_kind != kind:
            close_list()
            out.append(f"<{kind} style='{style}'>")
            list_kind = kind

    while i < len(lines):
        raw = lines[i]

        if _FENCE_RE.match(raw):                       # ``` fenced code block
            close_list()
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1                                     # skip closing fence
            out.append(_code_block(html.escape("\n".join(code))))
            continue

        if not raw.strip():
            close_list()
            i += 1
            continue

        if ("|" in raw and i + 1 < len(lines)
                and _TABLE_SEP_RE.match(lines[i + 1]) and "|" in lines[i + 1] + raw):
            close_list()                                # | a | b | over |---|---|
            head = _cells(raw)
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            out.append(_table(head, rows))
            continue

        h = _H_RE.match(raw)
        if h:                                          # # / ## / ### heading
            close_list()
            level = len(h.group(1))
            size = {1: 16, 2: 14, 3: 13}.get(level, 12)
            out.append(f"<p style='color:#1d1f20;font-weight:600;"
                       f"font-size:{size}px;margin:12px 0 4px 0'>"
                       f"{_inline(h.group(2).strip())}</p>")
            i += 1
            continue

        b = _BULLET_RE.match(raw)
        if b:
            content = b.group(2).rstrip()
            plain = re.sub(r"\*\*(.+?)\*\*", r"\1", content).strip()
            if len(b.group(1)) <= 1 and _LABEL_RE.match(plain):
                close_list()
                out.append(_label(plain))
            else:
                want_list("ul", "margin:2px 0 8px 4px")
                out.append(f"<li style='margin:3px 0;color:#424244'>"
                           f"{_inline(content)}</li>")
            i += 1
            continue

        n = _NUM_RE.match(raw)
        if n:
            want_list("ol", "margin:2px 0 8px 18px")
            out.append(f"<li style='margin:3px 0;color:#424244'>"
                       f"{_inline(n.group(3).rstrip())}</li>")
            i += 1
            continue

        close_list()                                   # plain line
        line = raw.strip()
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", line).strip()
        if _LABEL_RE.match(plain):
            out.append(_label(plain))
        else:
            out.append(f"<p style='margin:5px 0;color:#424244;"
                       f"line-height:150%'>{_inline(line)}</p>")
        i += 1

    close_list()
    return "".join(out)


def plain_preview(text: str) -> str:
    """One line of plain words from Markdown, for a preview: a folded step
    card showed '# 5 Ways ...  **1. Prefabricate**' with the symbols in it.
    Headings, emphasis, code ticks, link brackets, table pipes and rules,
    bullets and numbering marks go; the words stay. Plain text, not HTML."""
    out = []
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line or _TABLE_SEP_RE.match(line) or _FENCE_RE.match(line):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[\*\-•]\s+", "", line)
        line = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"(\*\*|__)(.+?)\1", r"\2", line)
        line = re.sub(r"(?<![\w*])([*_])(?!\s)(.+?)(?<!\s)\1(?![\w*])", r"\2", line)
        line = line.replace("`", "")
        if "|" in line:
            line = " ".join(c.strip() for c in line.strip("|").split("|") if c.strip())
        out.append(line)
    return " ".join(out).strip()

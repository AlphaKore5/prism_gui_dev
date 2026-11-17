"""Local documents for follow-ups: "give me this as a PDF" is a change of FORMAT,
not a new question, so Prism turns the answer it already has into the file on this
computer instead of asking the AI the same question again."""
from __future__ import annotations

import os
import re

import core_bridge as CB

# Words that only ask for a different format; if nothing else is left, the
# follow-up is a pure format request.
_FILLER = {
    "give", "me", "in", "this", "that", "as", "a", "an", "the", "pdf", "word",
    "excel", "docx", "xlsx", "doc", "form", "format", "version", "please", "it",
    "make", "convert", "to", "into", "file", "document", "spreadsheet", "send",
    "can", "you", "u", "i", "want", "also", "now", "ms", "copy", "same", "export",
    "create", "generate", "provide", "and", "just", "for", "my", "one", "of",
}


def requested_ext(text: str) -> str:
    """".pdf" / ".docx" / ".xlsx" when the text asks to RECEIVE one, else ""."""
    ext = CB.contract.wanted_ext(text or "")
    return ext if ext in (".pdf", ".docx", ".xlsx") else ""


def is_pure_format_request(text: str) -> bool:
    if not requested_ext(text):
        return False
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return all(w in _FILLER for w in words)


def latest_answer(responses: dict) -> str:
    """The newest non-empty step text (responses keep run order)."""
    for texts in reversed(list((responses or {}).values())):
        joined = "\n\n".join(t for t in (texts if isinstance(texts, list) else [texts])
                             if str(t or "").strip())
        if joined.strip():
            return joined
    return ""


def export_answer(text: str, ext: str, out_dir: str, stem: str = "answer") -> tuple[str, str]:
    """Write `text` as a real file. Returns (path, note); ("", "") when it cannot."""
    return CB.contract.document_from_text(text, out_dir, stem, ext)

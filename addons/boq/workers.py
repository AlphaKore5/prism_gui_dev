"""BOQ's own background workers.

A PDF-takeoff extraction (addons/boq/industries.py's `extract`) reads and
OCRs a real tender PDF -- seconds on a small sheet, real time on a large,
multi-page one -- so it runs off the GUI thread the same way every other
blocking call in this app does (see workers.py's own docstring: "every
worker's job is ONLY to call into [its target] and turn the result into a
Qt signal; no decision-making lives here").
"""
from __future__ import annotations

import base64

from PySide6.QtCore import Signal

import core_bridge as CB
from addons.boq import industries
from addons.boq import openrouter_writer
from workers import _Worker

# item 2 (5 Nov 2026): HVAC's own AI VAV-tag re-check -- the model chosen
# after testing several candidates live against a real drawing's actual
# tiles (not picked on price or name alone): Qwen's vision line read
# noticeably more real VAV tags than RapidOCR at the same 2400px tiling,
# for a small fraction of a rupee per drawing. Named here, once, so a
# future swap is "change this one string", not a hunt through workers.py.
HVAC_VISION_MODEL = "qwen/qwen3-vl-30b-a3b-instruct"
# Capped and reasoning-off for both reasons found live testing this exact
# model on this exact kind of tile: with no cap, a run produced 18k+
# characters of repeated lines before stopping itself (one tile took 10
# minutes instead of ~20 seconds); some vision models on OpenRouter default
# to a "thinking" mode that can spend the whole token budget on its own
# reasoning and return a null final answer -- off avoids that outright.
_HVAC_VISION_PROMPT = (
    "This is a cropped section of a dense HVAC engineering drawing. "
    "List EVERY distinct text label/tag you can read in this image, one per "
    "line, exactly as written, including any VAV tags (format VAV-#-##), "
    "diffuser sizes, CFM numbers, disc valve labels, duct size labels. Do "
    "not summarize or skip any. If you see no legible text, say NONE. List "
    "each distinct tag only ONCE -- do not repeat the same line more than "
    "once, even if it appears on the drawing multiple times.")


# item 63 (7 Nov 2026): ELV/CCTV's own AI drawing reading -- same model as
# HVAC's (HVAC_VISION_MODEL above), on purpose, not a fresh pick: it was
# chosen for being a strong, cheap general-purpose vision-OCR model, not
# for anything HVAC-specific, so there is no reason to re-test a second
# one here until a real ELV drawing says otherwise.
ELV_VISION_MODEL = HVAC_VISION_MODEL
# No VAV-style regex to ask for (elv_takeoff.py's own docstring says why:
# no real drawing yet to calibrate one against) -- this prompt asks for
# everything legible, in plain language, and addons/boq's write-up stage
# (DeepSeek) does the interpretation from the raw text, not this call.
_ELV_VISION_PROMPT = (
    "This is a section of an ELV/CCTV/low-voltage engineering drawing. "
    "List EVERY distinct text label you can read in this image, one per "
    "line, exactly as written -- device tags (cameras, access points, "
    "readers, panels), cable/conduit types and counts, schedule or "
    "legend text, equipment notes, counts written beside a symbol. Do "
    "not summarize, group or skip any. If you see no legible text, say "
    "NONE. List each distinct label only ONCE -- do not repeat the same "
    "line more than once, even if it appears on the drawing multiple "
    "times.")


class ElvReadWorker(_Worker):
    """Runs an ELV-industry drawing reading (item 63, generalized into the
    shared reader at item 64) off the GUI thread -- industries.
    has_ai_read_modes()'s own worker, a sibling of HvacTakeoffWorker, not
    an extension of it: the two industries dispatch through different
    entry points in industries.py (extract_ai_read() vs extract()) because
    ELV has no layer_map/pt_per_ft geometry shape to pass. No `mode`
    parameter any more -- drawing_reader.py decides DXF-entities-first vs
    AI-tiled from the file itself, never a user choice; `api_key` is only
    ever actually used if the file needs the AI-tiled fallback."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, industry: str, path: str, *, api_key: str = ""):
        super().__init__()
        self.industry = industry
        self.path = path
        self.api_key = api_key

    def _tag_reader(self, png_bytes: bytes) -> str:
        b64 = base64.b64encode(png_bytes).decode()
        return CB.openrouter.openrouter_chat(
            self.api_key, ELV_VISION_MODEL, _ELV_VISION_PROMPT,
            attachments=[{"kind": "image", "mime": "image/png", "b64": b64}],
            temperature=0.1, max_tokens=900,
            extra={"frequency_penalty": 0.4, "reasoning": {"enabled": False}})

    def run(self):
        try:
            result = industries.extract_ai_read(
                self.industry, self.path, self._tag_reader)
            self.done.emit(result)
        except Exception as e:                           # noqa: BLE001
            self.failed.emit(str(e))


class HvacTakeoffWorker(_Worker):
    """Runs one industry's PDF-takeoff extraction (today, only HVAC has
    one) off the GUI thread. `industry` is threaded through rather than
    hardcoded so a second industry's own extractor plugs into this same
    worker later, not a copy of it.

    `api_key`/`use_ai_tags`: HVAC's own optional AI VAV-tag re-check (item
    2) -- off unless both an OpenRouter key AND the checkbox are present,
    same two-gate shape _run_prism_agent() already uses for the BOQ
    write-up path. This worker is the one place that builds the actual
    `tag_reader` callback hvac_takeoff.vision_vav_recount() calls -- the
    engine function itself never imports core_bridge or sees a key (its
    own docstring explains why)."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, industry: str, pdf_path: str, layer_map: dict,
                 pt_per_ft: float, use_ocr: bool = True, *,
                 api_key: str = "", use_ai_tags: bool = False):
        super().__init__()
        self.industry = industry
        self.pdf_path = pdf_path
        self.layer_map = layer_map
        self.pt_per_ft = pt_per_ft
        self.use_ocr = use_ocr
        self.api_key = api_key
        self.use_ai_tags = use_ai_tags

    def _tag_reader(self, png_bytes: bytes) -> str:
        b64 = base64.b64encode(png_bytes).decode()
        return CB.openrouter.openrouter_chat(
            self.api_key, HVAC_VISION_MODEL, _HVAC_VISION_PROMPT,
            attachments=[{"kind": "image", "mime": "image/png", "b64": b64}],
            # item 80: 0, not 0.1 -- the same drawing read 42, 38 and 34
            # VAV tags on three runs with this code unchanged; a read that
            # is meant to be repeatable should not be sampled.
            temperature=0, max_tokens=900,
            extra={"frequency_penalty": 0.4, "reasoning": {"enabled": False}})

    def run(self):
        try:
            reader = self._tag_reader if (self.use_ai_tags and self.api_key) else None
            result = industries.extract(
                self.industry, self.pdf_path, self.layer_map, self.pt_per_ft,
                use_ocr=self.use_ocr, vision_tag_reader=reader)
            self.done.emit(result)
        except Exception as e:                           # noqa: BLE001
            self.failed.emit(str(e))


class OpenRouterWriteWorker(_Worker):
    """BOQ-CHANGES-TODO.md item 30b/30c: one "Prism Agent" completion off
    the GUI thread -- a plain OpenRouter API call, not a browser tab, so
    this never touches AutomationWorker/BoqRunDialog's fallback-chain
    machinery at all; see addons/boq/dialog.py's _run_prism_agent()."""

    done = Signal(str)
    failed = Signal(str)

    def __init__(self, agent: str, prompt: str, api_key: str, *, followup: bool = False,
                 attachments: list[dict] | None = None):
        super().__init__()
        self.agent = agent
        self.prompt = prompt
        self.api_key = api_key
        self.followup = followup
        self.attachments = attachments
        # item 70: filled in place by write() before `done` fires -- read
        # by dialog.py's _on_prism_agent_done() straight off this worker
        # instance (still the same object `self._worker` points at when
        # the signal is handled), not threaded through the signal itself,
        # since `done` already has callers matching on a one-`str` shape.
        self.usage: dict = {}

    def run(self):
        try:
            text = openrouter_writer.write(
                self.agent, self.prompt, self.api_key, followup=self.followup,
                attachments=self.attachments, usage_out=self.usage)
            self.done.emit(text)
        except Exception as e:                           # noqa: BLE001
            self.failed.emit(str(e))

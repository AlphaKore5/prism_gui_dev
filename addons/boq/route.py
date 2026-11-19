"""Which road a BOQ job takes, said in plain words (stdlib only, no Qt).

Two choices decide the road, and the user makes both on purpose:

  1. WHAT DO YOU HAVE?  a CAD drawing (DXF/DWG), a PDF or picture of a
     drawing, or no drawing at all (just describe the job).
  2. WHAT KIND OF JOB IS IT?  General building, Electrical / ELV, or HVAC.
     This is never guessed from a file (see industries.py for why).

From those two, this module answers three questions the screen needs:

  * `availability()`  does this combination work today, and if not, why not
  * `stages()`        the steps of the road, each marked as running on this
                      computer, on Prism AI, or needing the user
  * `kind_of_file()`  which of the three a file the user dropped belongs to

It only DESCRIBES the existing engines (ezdxf measuring, hvac_takeoff for a
vector PDF, the shared drawing reader for ELV, the writer for the BOQ). It
runs none of them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from addons.boq import industries

# What the user has ----------------------------------------------------------
CAD = "cad"
SCAN = "scan"            # a PDF or a picture of a drawing
DESCRIBE = "describe"
INPUTS = (CAD, SCAN, DESCRIBE)

CAD_EXTS = (".dxf", ".dwg")
PICTURE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
SCAN_EXTS = (".pdf",) + PICTURE_EXTS

INPUT_CARDS = (
    (CAD, "A CAD drawing", "DXF or DWG from AutoCAD or any CAD program."),
    (SCAN, "A PDF or picture of a drawing", "A PDF, or a photo or screenshot of a drawing."),
    (DESCRIBE, "No drawing, just describe the job", "Say it in your own words."),
)

# What kind of job -----------------------------------------------------------
JOB_CARDS = (
    (industries.GENERAL, "General building",
     "Rooms, walls, floors, doors, furniture."),
    (industries.ELV, "Electrical / ELV",
     "CCTV, access control, cabling, fibre, data points."),
    (industries.HVAC, "HVAC",
     "Ducts, grilles, dampers, air-handling units."),
)

# What each built-in trade has of its own, said plainly (shown under the cards).
TOOL_NOTES = {
    industries.GENERAL: "No takeoff tool of its own: a DXF or DWG is measured by layer.",
    industries.ELV: "Its own PDF and picture reader; DXF or DWG counted by device.",
    industries.HVAC: "Its own duct takeoff for tender PDFs and DXF or DWG.",
}
OTHER_NOTE = "No takeoff tool of its own: measured like General. Nothing is guessed about your trade."

# Short names for the compact strip.
SHORT = {"describe": "Describe", "read": "Read", "measure": "Measure", "tags": "Read tags",
         "check": "Check", "scale": "Scale", "layers": "Colours", "drawing": "With drawing", "write": "Write", "prices": "Prices", "files": "Files"}

# Who does a step ------------------------------------------------------------
LOCAL = "local"          # on this computer
AI = "ai"                # Prism AI, through Prism's server
LOCAL_AI = "local+ai"    # on this computer; an optional AI check if you agree
YOU = "you"

# State of a step ------------------------------------------------------------
WAITING = "waiting"
RUNNING = "running"
DONE = "done"
NEEDS_YOU = "needs_you"
SKIPPED = "skipped"
FAILED = "failed"
STATES = (WAITING, RUNNING, DONE, NEEDS_YOU, SKIPPED, FAILED)


@dataclass(frozen=True)
class Stage:
    key: str
    label: str      # short, in the strip
    where: str      # LOCAL / AI / LOCAL_AI / YOU
    detail: str     # one plain sentence: what this step does and where


def kind_of_file(path: str) -> str | None:
    """CAD, SCAN, or None for anything else (a sample BOQ, a note...)."""
    ext = os.path.splitext(path or "")[1].lower()
    if ext in CAD_EXTS:
        return CAD
    if ext in SCAN_EXTS:
        return SCAN
    return None


def is_picture(path: str) -> bool:
    return os.path.splitext(path or "")[1].lower() in PICTURE_EXTS


def availability(input_kind: str, industry: str, path: str = "") -> tuple[bool, str]:
    """(works, why-not). Only combinations that really run are offered; a
    disabled card carries its reason in plain words."""
    if input_kind == SCAN and industry == industries.HVAC and is_picture(path):
        return False, ("Ducts can't be measured from a picture. Use the PDF or a CAD "
                       "file instead, or pick General or Electrical to read the labels.")
    return True, ""


def stages(input_kind: str, industry: str, path: str = "") -> list[Stage]:
    """The road for this combination, in order."""
    tail = [
        Stage("prices", "Prices", LOCAL,
              "Optional. Add your rates and Prism adds them up on this computer."),
        Stage("files", "Excel / Word / PDF", LOCAL,
              "Your BOQ is saved as a file you can open, edit and send."),
    ]
    write = Stage("write", "Write the BOQ", AI,
                  "Prism AI writes the BOQ from the figures you checked. Only the numbers "
                  "go, not the drawing.")
    check = Stage("check", "You check the count", YOU,
                  "Look at what was counted and fix anything that looks wrong.")

    if input_kind == DESCRIBE:
        return [
            Stage("describe", "Describe the job", YOU,
                  "Say what the BOQ is for. Without a drawing nothing is measured."),
            Stage("write", "Write the BOQ", AI,
                  "Prism AI lists the items from your words. Quantities are estimates "
                  "and are marked as estimates."),
            Stage("check", "You check the BOQ", YOU,
                  "Nothing was measured, so read every line and quantity yourself."),
        ] + tail

    if input_kind == CAD:
        # core.boq.measure() is ONE routine: it adds up line lengths and areas by
        # layer and counts block symbols. HVAC only adds Hitarth's HVAC drawing rules
        # (pair duct lines into runs, bridge gaps, read size labels, count elbows).
        # There is no ELV-specific measuring, so ELV and General share the plain one.
        measure = (Stage(
            "measure", "Measure (HVAC rules)", LOCAL,
            "Adds up lengths and areas by layer and counts symbols, and applies the HVAC "
            "drawing rules: pairs duct lines into runs, reads duct size labels, counts "
            "elbows. On this computer.") if industry == industries.HVAC else Stage(
            "measure", "Measure", LOCAL,
            "Adds up lengths and areas by layer and counts block symbols, on this computer."))
        return [
            Stage("read", "Read the drawing", LOCAL,
                  "Opens the DXF (a DWG is converted first) on this computer. Nothing is "
                  "sent anywhere."),
            measure, check, write] + tail

    # SCAN: a PDF or a picture
    if industry == industries.HVAC:
        # The same order as the HVAC PDF takeoff tool (hvac_takeoff/README.md):
        # open the PDF, set the scale, Step 1 map each line colour to a role,
        # Step 2 extract, then look at the warnings and readings.
        return [
            Stage("read", "Open the PDF", LOCAL,
                  "Opens your tender PDF on this computer. It has to be a PDF made from "
                  "CAD: a scan has no lines to measure."),
            Stage("scale", "Set the drawing scale", YOU,
                  "Pick the scale from the title block (for example 1/8\" = 1'-0\"), or "
                  "measure one dimension you know. You confirm it before extracting."),
            Stage("layers", "Step 1: map the line colours", YOU,
                  "Say what each line colour or layer is (supply, return and so on). "
                  "Prism remembers it for the next drawing."),
            Stage("measure", "Step 2: extract", LOCAL_AI,
                  "Pairs the duct lines into runs and reads size, CFM and TR labels from "
                  "the PDF's text and OCR, on this computer. If you agree, small cropped "
                  "pieces also go to Prism AI to catch tags OCR missed."),
            Stage("check", "You check the readings", YOU,
                  "Look at the warnings and each reading before the numbers are used."),
            write] + tail
    if industry == industries.ELV:
        return [
            Stage("read", "Open the drawing", LOCAL,
                  "Opens the PDF or picture on this computer."),
            Stage("tags", "Read the labels and symbols", LOCAL_AI,
                  "OCR on this computer, plus Prism AI reading small cropped pieces. This is "
                  "a reading, not a measurement. Prism asks you first."),
            check, write] + tail
    # General (and Other / your own industry): "Make with drawing" is Hitarth's one
    # step in which the AI reads the file and writes the BOQ from it.
    return [
        Stage("read", "Open the drawing", LOCAL,
              "Opens the PDF or picture on this computer."),
        Stage("drawing", "Make with the drawing", AI,
              "Prism AI looks at the whole drawing and writes the BOQ from it. This is a "
              "reading, not a measurement. Prism asks you first."),
        Stage("check", "You check the BOQ", YOU,
              "Nothing was measured, so check every quantity against the drawing."),
    ] + tail


def where_words(where: str) -> str:
    return {LOCAL: "On this computer", AI: "Prism AI", LOCAL_AI: "This computer + optional Prism AI",
            YOU: "You"}.get(where, "")

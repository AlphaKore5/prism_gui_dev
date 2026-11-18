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
        measure = {
            industries.HVAC: Stage(
                "measure", "Measure ducts and fittings", LOCAL,
                "Pairs duct lines into runs and counts dampers and units, on this computer."),
            industries.ELV: Stage(
                "measure", "Count devices and cable", LOCAL,
                "Counts camera, reader and outlet symbols and adds up cable lines, "
                "on this computer."),
        }.get(industry, Stage(
            "measure", "Measure", LOCAL,
            "Adds up lengths and areas by layer and counts symbols, on this computer."))
        return [
            Stage("read", "Read the drawing", LOCAL,
                  "Opens the DXF (a DWG is converted first) on this computer. Nothing is "
                  "sent anywhere."),
            measure, check, write] + tail

    # SCAN: a PDF or a picture
    if industry == industries.HVAC:
        return [
            Stage("read", "Read the PDF", LOCAL,
                  "Opens the PDF's own lines and text on this computer."),
            Stage("measure", "Find the ducts", LOCAL,
                  "Pairs the PDF's lines into duct runs. It needs a PDF made from CAD; a "
                  "scan has no lines to measure."),
            Stage("tags", "Read the size tags", LOCAL_AI,
                  "Reads sizes and tags (OCR) on this computer. If you agree, small cropped "
                  "pieces also go to Prism AI to catch tags OCR missed."),
            check, write] + tail
    if industry == industries.ELV:
        return [
            Stage("read", "Open the drawing", LOCAL,
                  "Opens the PDF or picture on this computer."),
            Stage("tags", "Read the labels and symbols", LOCAL_AI,
                  "OCR on this computer, plus Prism AI reading small cropped pieces. This is "
                  "a reading, not a measurement. Prism asks you first."),
            check, write] + tail
    return [
        Stage("read", "Open the drawing", LOCAL,
              "Opens the PDF or picture on this computer."),
        Stage("tags", "AI reads the drawing", AI,
              "Prism AI looks at the whole drawing and its notes. This is a reading, not a "
              "measurement. Prism asks you first."),
        Stage("check", "You check the BOQ", YOU,
              "Nothing was measured, so check every quantity against the drawing."),
        Stage("write", "Write the BOQ", AI,
              "Prism AI writes the BOQ from its reading of your drawing."),
    ] + tail


def where_words(where: str) -> str:
    return {LOCAL: "On this computer", AI: "Prism AI", LOCAL_AI: "This computer + optional Prism AI",
            YOU: "You"}.get(where, "")

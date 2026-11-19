"""Bill of Quantities — say what you need, get the document.

The screen is deliberately one prompt and one button. The user does not
choose a mode, does not fill a form, and is never asked what a "scope
filter" is. Attach a drawing and it gets measured; attach nothing and the
quantities are derived from the words. Both are the same button.

The measuring itself is done locally by the engine (core.boq, ezdxf) and
never by an AI — real geometry in, an auditable CSV out — and only then do
the agents write it up. The measured figures are shown before anything is
generated, because that is what makes the number checkable.
"""
from __future__ import annotations
import os
import re
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QTextEdit, QLineEdit, QMessageBox, QCheckBox, QFileDialog,
    QComboBox, QWidget, QStackedWidget, QGridLayout, QSizePolicy, QFrame,
)

import core_bridge as CB
from addons import registry
import i18n
import theme
import deps
from dialogs.base import PrismDialog
from workers import AutomationWorker, MeasureWorker, RecordWorker
from widgets import controls as C
from widgets.loader import Loader
from widgets.stepper import ChoiceCard, FileCard, StepTabs
from widgets.usage_chip import UsageChip
from widgets.ask_panel import AskPanel, MoreOptions
from addons.boq import agents as boq_agents
from addons.boq import evidence
from addons.boq import industries
from addons.boq import route
from addons.boq import custom_industries as CI
from addons.boq.takeoff_block import TakeoffBlock
from addons.boq.continue_list import ContinueList
from addons.boq.workers import CadPeekWorker
from addons.boq import credits as credit_words
import friendly
from addons.boq.industry_dialog import IndustryDialog
from addons.boq.pipeline_strip import PipelineStrip
from addons.boq import cad_render
from addons.boq import openrouter_writer
from addons.boq import result_view
from addons.boq.measured import MeasuredTable
from addons.boq.pricing import PricingTable
from addons.boq.elv_dialog import ElvReadDialog
from addons.boq.takeoff import IndustryTakeoffDialog
from addons.boq.workers import OpenRouterWriteWorker, CreditEstimateWorker
from widgets.output_panel import short_duration
from widgets import send_to_ai
from addons.boq import converter_dialog, converter_setup


# Said once a drawing is measured. Shown on steps 1-2 only: from "make" on it is
# old news taking a line the page needs.
_MEASURED_MSG = "Measured from the drawing itself — not by an AI."


class _Pager:
    """Routes the dialog's `root.addWidget(...)` calls onto one of its step
    pages. The dialog used to be one long column; the widgets are the same
    objects with the same handlers, they are only dealt out to four pages."""

    def __init__(self, layouts: list):
        self._layouts = layouts
        self._i = 0

    def page(self, i: int):
        self._i = i

    def addWidget(self, *args, **kwargs):
        self._layouts[self._i].addWidget(*args, **kwargs)

    def addLayout(self, *args, **kwargs):
        self._layouts[self._i].addLayout(*args, **kwargs)

    def setSpacing(self, n: int):
        for lay in self._layouts:
            lay.setSpacing(n)


# item 67 (11 Nov 2026), found live on a real pharma-client job: an SS
# rack drawn as 8 visually separate compartments (a middle divider between
# upper/lower, a line between each of the 4 columns) came back with the
# frame (posts/rails) and the outer panels/doors in the BOM, but no
# partition or middle-shelf line at all -- not because the model never saw
# the drawing (it correctly cited page-2-only text elsewhere in the same
# answer), but because nothing in the file ever NAMES a divider as its own
# part, only the frame members are named, so a plain "use only what's
# stated" reading leaves the compartment boundaries uncosted. Every one of
# the three prompts below that asks the model to read a file's drawing
# directly shares this same risk, so the fix is one shared note, not a
# one-off sentence in just the prompt that happened to catch it this time.
_COMPARTMENT_DIVIDER_NOTE = (
    " If the file shows an object divided into separate sections or "
    "compartments -- by colour, a label, or a drawn boundary -- each "
    "boundary between two of them needs its own enclosing panel (a "
    "divider, shelf or partition) as its own BOM line, unless the file "
    "states or clearly shows that a frame member alone is what separates "
    "them. A drawn boundary is not automatically covered by the frame.")

# item 68 (11 Nov 2026), found live reviewing four more real client files
# before testing: a hand-scanned sketch (0 extractable text -- a photo of a
# handwritten sheet) stated its own +100mm sheet allowance ONLY by hand, in
# the margin, as a brace grouping five named parts together ("Top, Bottom,
# Sides, H. Partition, V. Partition") -- with "Doors" and "Legs" listed
# OUTSIDE that brace, i.e. deliberately NOT covered by the same rule. A
# reading pass that only looks for printed or typed instructions misses a
# real, client-stated rule entirely; one that reads it but applies it
# everywhere misapplies it to parts the client's own note excluded.
_HANDWRITTEN_NOTE = (
    " Read every annotation on every page, not only printed or typed text "
    "-- a handwritten note, a margin scribble, or a brace grouping several "
    "part names together is exactly as real a source as anything printed, "
    "and often states a rule (an allowance, a material choice) that "
    "applies ONLY to the parts it is grouped with, not to the whole "
    "object. Don't skip something because it's handwritten, and don't "
    "apply a rule found next to one list of parts to a part that isn't in "
    "that list.")

# item 68, same review: a single PDF held ten completely different,
# separately-named products (a trolley, a storage cabinet, a table, ...),
# not ten views of one object -- two of its own pages carried no product
# name at all. Nothing before this said a file could BE a catalogue rather
# than one job, so a reading pass had no reason not to blend one item's own
# dimension into a neighbouring, similar-looking item's section.
_MULTI_ITEM_NOTE = (
    " If the file describes more than one separate, distinctly-named item "
    "-- not just multiple views or pages of the same one object -- give "
    "each item its own BOM section under its own heading, and never carry "
    "a dimension, count or material note from one item into another "
    "item's section, even where two items look similar. An unlabelled "
    "page still belongs to whichever single item its own content "
    "describes, never to more than one.")

# item 44 (3 Nov 2026): every prompt below used to say "the attached
# drawing" / "labelled on the drawing" throughout. cad_render.prepare_for_ai
# already sends a .pdf whole, every page, unchanged (its own docstring: "A
# PDF is sent AS-IS... Claude reads a real PDF document natively (every
# page, any real text in it too)") -- the attachment was never the problem.
# Found live: a real client file had a written specification on page 1
# (explicit answers to several things the drawing itself left unlabelled --
# a caster count, a wall thickness) and the actual drawing on page 2. The
# model's own answer said "Source: Extracted from the attached drawing
# only" and never touched page 1 at all -- not because it couldn't see it
# (it was sent whole), but because "the drawing" in the prompt's own
# wording reads as "the visual/CAD page", and "labelled on the drawing"
# as "ignore anything that isn't drawn". The owner's own words: "i dont
# care how many pages... not only drawing, everything." Every prompt here
# now says "the attached file" and spells out that it covers EVERY page,
# a written specification exactly as much as a drawn sketch -- never
# "the drawing" alone again.
VERIFY_PROMPT = (
    "Verify and remake: recheck every measured quantity against the attached "
    "file. The file is the source of truth -- read ALL of it, every page, "
    "whatever's on each one (a drawn sketch, a written specification, both); "
    "the measured figures were computed locally from it. For every quantity "
    "that does not match what the file actually says, state the file's own "
    "value and the measured value. Then remake the whole BOQ in the same "
    "format as the previous answer with the corrected figures, and list what "
    "changed." + _COMPARTMENT_DIVIDER_NOTE + _HANDWRITTEN_NOTE + _MULTI_ITEM_NOTE)

# "Make with drawing" pressed before any BOQ exists yet -- there is no
# previous answer to remake, so this does NOT reuse VERIFY_PROMPT's "remake
# in the same format... list what changed" framing, which only makes sense
# once something has already been written. Same job either way (read the
# attached file itself, not just the measured figures), different starting
# point.
MAKE_WITH_DRAWING_PROMPT = (
    "Make the whole BOQ by reading the attached file directly, not only the "
    "measured figures below -- every page of it, whatever each one holds (a "
    "drawn sketch, a written specification, both); do not treat only a drawn "
    "page as real and a written one as background. The measured figures were "
    "computed locally from the same file -- use them as a cross-check, and "
    "where your own reading disagrees with a measured figure, say so and use "
    "what the file itself says." + _COMPARTMENT_DIVIDER_NOTE + _HANDWRITTEN_NOTE + _MULTI_ITEM_NOTE)

# item 38: a PDF attachment has no vector geometry Prism can measure itself --
# unlike MAKE_WITH_DRAWING_PROMPT above, there is no "measured figures"
# section to cross-check against; telling the AI to cross-check against an
# empty one would be confusing, not reassuring. Every quantity has to come
# from the AI's own reading of the file, so it is told that plainly, with
# the same "never guess" rule every other BOQ prompt in this add-on carries.
MAKE_WITH_DRAWING_NO_MEASUREMENT_PROMPT = (
    "Make the whole BOQ by reading the attached file directly -- there is no "
    "separately measured data for this one; everything must come from your "
    "own reading of it. Read EVERY page -- a written specification page is "
    "exactly as real a source as a drawn sketch page, never background or "
    "secondary; if the file has both, use both together, and say so where a "
    "written spec gives a figure the drawing itself leaves unlabelled (or "
    "the two disagree). Use only dimensions, quantities, materials and notes "
    "actually stated somewhere in the file. Where something needed is not "
    "stated anywhere or is unclear, say so as a question or a TO CONFIRM "
    "line rather than inventing a figure." + _COMPARTMENT_DIVIDER_NOTE + _HANDWRITTEN_NOTE + _MULTI_ITEM_NOTE)


class InputMeasurementsDialog(QDialog):
    """Paste measurements, or upload a file of them — the second way into
    the BOQ pipeline, for numbers measured by a tool outside Prism (a PDF
    takeoff extractor, a rate list, anyone's own CSV). Returns plain text;
    it never tries to parse a specific schema, so it works with whatever
    the other tool actually produced, the same way a sample BOQ or a
    legend note is handed to the writer as text, not reinterpreted here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Input measurements"))
        self.resize(620, 420)
        col = QVBoxLayout(self)
        col.addWidget(C.label(i18n.t(
            "Paste measurements from another tool, or upload a file of "
            "them — a PDF takeoff's JSON/CSV, a rate list, your own "
            "notes. Treated exactly like a drawing's own measured "
            "figures from here: handed to the writer as plain text, "
            "never as an image, never sent anywhere until you press "
            "\"Make my BOQ\"."), level="SUPPORT", wrap=True))

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.upload_btn = C.button(i18n.t("Upload a file…"), "secondary",
                                   icon_name="paperclip", small=True,
                                   on_click=self._upload)
        row.addWidget(self.upload_btn)
        self.file_label = QLabel("")
        self.file_label.setWordWrap(True)
        row.addWidget(self.file_label, stretch=1)
        col.addLayout(row)

        self.text = QPlainTextEdit()
        self.text.setPlaceholderText(i18n.t(
            "Paste measurements here, or upload a file above…"))
        col.addWidget(self.text, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(C.button(i18n.t("Cancel"), "secondary",
                                   on_click=self.reject))
        self.ok_btn = C.button(i18n.t("Use these measurements"), "primary",
                               on_click=self._confirm)
        btn_row.addWidget(self.ok_btn)
        col.addLayout(btn_row)

    def _upload(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Measurements file"), os.path.expanduser("~"),
            i18n.t("Text, JSON or CSV (*.txt *.json *.csv *.md);;All files (*)"))
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:                              # noqa: BLE001
            QMessageBox.warning(self, "BOQ", f"Couldn't read that file: {e}")
            return
        self.text.setPlainText(content)
        self.file_label.setText(i18n.t("Loaded: {name}").format(
            name=os.path.basename(path)))

    def _confirm(self):
        if not self.text.toPlainText().strip():
            QMessageBox.information(
                self, "BOQ", i18n.t("Paste some measurements, or upload a file, first."))
            return
        self.accept()

    def measurements_text(self) -> str:
        return self.text.toPlainText().strip()


class _CurrentPageStack(QWidget):
    """The pages of the steps, one showing at a time, as tall as the page showing.

    Qt's QStackedWidget answers every size question with the TALLEST page (its
    height-for-width takes the maximum over all pages), so step 1 scrolled
    because step 2's table exists, though step 2 was not on screen. Same few
    methods as QStackedWidget, which the dialog and its tests already use."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(0)
        self._pages: list = []
        self._current = -1

    def addWidget(self, page):
        self._lay.addWidget(page)
        self._pages.append(page)
        page.setVisible(len(self._pages) == 1)
        if self._current < 0:
            self._current = 0

    def widget(self, i: int):
        return self._pages[i]

    def count(self) -> int:
        return len(self._pages)

    def currentIndex(self) -> int:
        return self._current

    def currentWidget(self):
        return self._pages[self._current] if 0 <= self._current < len(self._pages) else None

    def setCurrentIndex(self, i: int):
        self._current = i
        for n, page in enumerate(self._pages):
            page.setVisible(n == i)
        self.updateGeometry()


class _IndustryChip(QPushButton):
    """One choice in the "What kind of work is this?" row."""

    def __init__(self, key: str, title: str, hint: str, add: bool = False):
        super().__init__(title)
        self.key = key
        self.hint_text = hint
        self.setObjectName("industryChip")
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False)
        self.setProperty("add", add)
        self.setAccessibleName(title)

    def selected(self) -> bool:
        return bool(self.property("selected"))

    def set_selected(self, on: bool):
        self.setProperty("selected", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)


class BoqDialog(PrismDialog):
    def __init__(self, cfg: dict, attachments: list, parent=None,
                 mode: str = "boq"):
        # One dialog, two documents. BOQ = quantities of construction WORK for a
        # QS to price; BOM = the PARTS list to fabricate a manufactured assembly.
        # The measurement backbone is identical (core.boq measures either way) —
        # only the write-up/research prompts and the on-screen copy differ, so
        # this is one class parameterised by mode rather than two that drift
        # apart (and BOM inherits every fix BOQ has: dedup, agent picker,
        # follow-up, timing, the scroll). Set before super() — the header copy
        # below reads self._doc.
        self.mode = "bom" if mode == "bom" else "boq"
        # This dialog offers its own follow-up after each answer, so callers
        # must not offer a second one.
        self.owns_followup = True
        self._doc = "Bill of Materials" if self.mode == "bom" else "Bill of Quantities"
        self._noun = "BOM" if self.mode == "bom" else "BOQ"
        # The run-title prefix comes from this add-on's OWN manifest, so this
        # dialog and History cannot disagree about it. They did, silently,
        # from 6b16cbb until now: that commit scaffolded BOM mode and
        # switched these titles from a hardcoded "BOQ" to self._doc, so every
        # run was recorded as "Bill of Quantities — …" while the prefix table
        # still said "BOQ — ". History matched none of them — no chip, no
        # prefix stripped, and the front door could not find its own recent
        # runs. Nothing raised, so nothing said so.
        self._run_prefix = registry.by_key(self.mode).run_prefixes[0]
        super().__init__(
            i18n.t(self._doc),
            i18n.t("Make a {noun} from your drawing in {n} easy steps. It is measured "
                   "on this computer. AI only writes it up.").format(
                       noun=self._noun, n=3 if self.mode == "bom" else 4),
            icon="file", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle(self._doc)
        self.resize(780, 700)
        self.setMinimumSize(620, 600)
        self.cfg = cfg
        self.boq = CB.get_boq()
        # The research + write-up prompts come from core.bom in BOM mode and
        # core.boq in BOQ mode; measurement, interpretation and roles_text
        # always come from self.boq (they are mode-independent).
        self._pm = CB.bom if self.mode == "bom" else self.boq

        # item 70: summed across every Prism-Agent (API) call this job
        # makes -- format, recheck, any follow-up -- never a browser
        # agent's own turn, since there is no token count to read off one
        # of those at all. Zero for a job that only ever used a browser
        # agent, which is the honest figure, not a missing one.
        self._tokens_used = {"prompt_tokens": 0, "completion_tokens": 0,
                             "total_tokens": 0}
        self.cad_path = ""
        self.templates: list[dict] = []
        self.images: list[dict] = []
        self.notes: list[dict] = []
        self.q = None
        self.summary = ""
        self.csv_path = ""
        self._hvac = False
        # The Industry dropdown's own value, snapshotted at measurement
        # time (see _measure()/_measure_external()'s own comments on
        # self._hvac for why: the dropdown can change between measuring
        # and writing, and the write-up prompt's own per-industry rules
        # must match whatever the measurement actually used, not
        # whatever the dropdown currently shows).
        self._industry = industries.GENERAL
        self._worker = None
        self._rec = None
        self._run_pending = False   # "Make my BOQ" pressed while still measuring
        # Task timing: t0 is when the run began, and _stage_log accumulates
        # (stage, seconds) as each stage finishes, so completion can report how
        # long the whole BOQ took and where the time went.
        self._t0 = 0.0
        self._last_t = 0.0
        self._stage_log: list[tuple[str, float]] = []
        self._standards = ""
        self._brief = ""        # the interpreter's legend & scope brief
        self._links: dict = {}
        # Who answered most recently, and that exact chat's own URL -- a
        # follow-up by the SAME agent resumes THIS chat (resume_urls, see
        # _fu_start_next) instead of a fresh one opening every time, the
        # same mechanism addons/step/dialog.py already uses.
        self._last_agent = ""
        self._last_link = ""
        # The latest real file an AI stage actually produced (write-up,
        # verify-and-remake or a follow-up) — as opposed to self.csv_path,
        # which is the LOCALLY measured quantities, made before any AI runs
        # at all and never touched again. Shown ahead of csv_path in the
        # follow-up window once there is one, so that window stops showing
        # a stale measurement file after an answer that made something new.
        self._deliverable_path = ""
        self._write_made_files: list = []
        self._fu_made_files: list = []
        # One live-progress window for the WHOLE BOQ session, not one per
        # click or per stage — see _start_followup_run (verify/follow-up)
        # and _run_stage (the initial research/interpret/write pipeline,
        # item 22). _active_runner says which of the two owns it right
        # now, so the window's three signals can be wired exactly once and
        # still reach the right handler either way.
        self._fu_dialog = None
        self._active_runner = ""
        # Accumulated across the stage chain so the main window can offer its
        # post-completion follow-up once this dialog closes: every stage's
        # output, and which agent produced it. The dialog runs its own worker
        # chain (never the main window's _on_run_done), so without carrying
        # these out the "anything to change?" refinement was unreachable here.
        self._all_responses: dict = {}
        self._stage_agents_map: dict = {}

        # The base class owns the header and the footer; `root` is its body
        # column, which already carries the page padding and the card gutter.
        #
        # Four steps (three for a BOM, which has nothing to price): what you
        # have, check the count, make it, add prices. Every widget below is
        # the same object it always was; `root` just deals them onto pages.
        self._step_names = ([i18n.t("What you have"), i18n.t("Check the count"),
                             i18n.t("Make the BOM")] if self.mode == "bom" else
                            [i18n.t("What you have"), i18n.t("Check the count"),
                             i18n.t("Make the BOQ"), i18n.t("Add prices")])
        if self.mode == "boq":     # the whole of step 1 has to fit 780x700 without a scroll bar
            self.body.setContentsMargins(theme.PAGE_PAD, theme.SPACE_3, theme.PAGE_PAD, theme.SPACE_2)
            self.body.setSpacing(theme.SPACE_2)
        self.tabs = StepTabs(self._step_names)
        self.tabs.step_clicked.connect(self._show_step)
        self.body.addWidget(self.tabs)
        # Display only: hidden until Prism has a server to ask (widgets/usage_chip.py).
        self.usage_chip = UsageChip()
        self.body.addWidget(self.usage_chip, alignment=Qt.AlignRight)
        # The road this job takes (addons/boq/route.py), one tile per step. A BOM
        # has its own shorter road and keeps the old header.
        self.pipe = PipelineStrip()
        self.pipe.detail_requested.connect(self._open_stage_detail)
        self.pipe.setVisible(False)
        if self.mode == "boq":
            self.body.addWidget(self.pipe)
        self._input_kind = ""          # what the user has; set by the cards or the file
        self._tool_result = None       # (kind, result) of the PDF tool or reader last used
        self.pages = _CurrentPageStack()
        page_layouts = []
        for _ in self._step_names:
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, theme.SPACE_3, 0, 0)
            self.pages.addWidget(page)
            page_layouts.append(lay)
        self._page_layouts = page_layouts
        root = _Pager(page_layouts)
        self.body.addWidget(self.pages, stretch=1)
        # A stacked form, not a grid of cards: the 16px card gutter
        # between every row of a single column is what turns a short
        # form into a tall one with bands of canvas through it.
        root.setSpacing(6 if self.mode == "boq" else theme.ROW_GAP)

        if self.mode == "boq":
            self._build_route_cards(root)
        title = QLabel(i18n.t("What is this {noun} for?").format(noun=self._noun))
        title.setObjectName("stepQ" if self.mode == "boq" else "h4")
        sub = C.label(i18n.t("Say it in your own words. One line is enough."),
                      level="SUPPORT", wrap=True)
        if self.mode == "boq":
            trow = QHBoxLayout()
            trow.setContentsMargins(0, 0, 0, 0)
            trow.setSpacing(theme.SPACE_3)
            trow.addWidget(title)
            trow.addWidget(sub, stretch=1)
            root.addLayout(trow)
        else:
            root.addWidget(title)
            root.addWidget(sub)

        if self.mode == "bom":
            placeholder = (
                "Just say it — for example:\n"
                "\"Parts list to fabricate this over-band magnetic separator\"  (attach the GA drawing)\n"
                "\"BOM for one 36x24 jaw crusher, 100 TPH\"  (no drawing needed)")
        else:
            placeholder = (
                "Just say it — for example:\n"
                "\"BOQ for CCTV, cabling and fibre for this site\"  (attach the drawing)\n"
                "\"materials to build one 36x24 jaw crusher, 100 TPH\"  (no drawing needed)")
        self.ask = AskPanel(placeholder, compact=self.mode == "boq")
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        if self.mode == "boq":
            self.ask.edit.setFixedHeight(66)     # step 1 must fit 780x700 without scrolling
        root.addWidget(self.ask)

        # "Or pick one": the two example jobs the add-on's front door already
        # offers, one click to fill the box. Gone once something is typed.
        examples = ([i18n.t("Parts list to fabricate this over-band magnetic separator"),
                     i18n.t("BOM for one 36x24 jaw crusher, 100 TPH")]
                    if self.mode == "bom" else
                    [i18n.t("BOQ for CCTV, cabling and fibre for this site"),
                     i18n.t("Materials to build one 36x24 jaw crusher, 100 TPH")])
        self.example_row = QWidget()
        erow = QHBoxLayout(self.example_row)
        erow.setContentsMargins(0, 0, 0, 0)
        erow.setSpacing(theme.SPACE_2)
        elab = QLabel(i18n.t("Or pick one:"))
        elab.setObjectName("meta")
        erow.addWidget(elab)
        for text in examples:
            chip = QPushButton(text)
            chip.setObjectName("tryChip")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, t=text: self.ask.set_text(t))
            erow.addWidget(chip)
        erow.addStretch(1)
        root.addWidget(self.example_row)

        # The drawing, as a drop zone: drag a file onto it or press the button.
        # Both go through AskPanel's own add_paths, the same door "Add file"
        # uses, so a drop can do nothing a click does not. Empty until one is
        # attached, then "Drawing added" with its name and a way to swap it.
        self.drawing_card = FileCard(
            i18n.t("Add your drawing (optional)") if self.mode == "bom" else i18n.t("Add your drawing"),
            i18n.t("Drag a DXF, DWG, PDF or picture here, or choose one. No drawing? "
                   "Describe the job above and Prism lists the items.") if self.mode == "bom" else
            i18n.t("DXF, DWG, PDF or picture. Measured on this computer. Sent to AI only if you say yes."),
            i18n.t("Drawing added"), i18n.t("Choose drawing"),
            i18n.t("Change drawing"), on_click=self.ask._pick_file,
            button_kind="secondary", accept_drops=True)
        self.drawing_card.files_dropped.connect(self.ask.add_paths)
        if self.mode == "boq":
            self.drawing_card.layout().setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        root.addWidget(self.drawing_card)

        # Say which format works BEFORE a drawing is attached, not in an error
        # afterwards.
        #
        # .dwg is Autodesk's closed format. ODA File Converter reads it best
        # but Prism is not allowed to ship it (only distributed through a
        # registration form with an EULA that forbids redistribution), and on
        # an Intel Mac, Linux box or 32-bit Windows machine there's nothing
        # Prism bundles either (core.boq.find_dwg_converter() now installs
        # Prism's own bundled dwg2dxf -- GPL, redistributable -- on an Apple
        # Silicon Mac or 64-bit Windows, see
        # prism_terminal/core/vendor/dwg2dxf/README.md). So on whatever's
        # left without any converter at all, a customer who attached the
        # obvious file got told to go and install a program — after picking
        # the file, naming the job and pressing the button.
        #
        # .dxf needs none of that. Every CAD program exports it in one step,
        # ezdxf reads it directly, and it is the same geometry. Making that the
        # expected input is the difference between a five-minute detour and a
        # dead end — and it costs the customer one menu item they already know.
        #
        # Shown only when this machine genuinely has no converter at all
        # (bundled or installed): a client on a covered platform, or one who
        # has installed ODA themselves, can attach .dwg all day and must not
        # be nagged about a problem they do not have.
        converter_setup.apply_saved(self.cfg)
        if not self.boq.find_dwg_converter():
            dxf_note = QLabel(
                "Only have a .dwg? Save it as <b>DXF</b> first (AutoCAD: File → Save As → "
                "<i>AutoCAD DXF</i>). This computer has no .dwg converter.")
            dxf_note.setObjectName("note")
            dxf_note.setWordWrap(True)
            root.addWidget(dxf_note)

        # The engine already treats a sample/previous BOQ as its own role
        # (core.boq.classify_inputs's "templates", described to the writer
        # as "an example BOQ showing the firm's usual style") -- attaching
        # one through the same "Add file" box above already worked. What
        # was missing was telling the user it is even possible: nothing
        # said so, so nobody attached one on purpose. _absorb() below fills
        # this in once a template actually lands; until then it stands as
        # an invitation, with the one reassurance the owner asked for —
        # that this is NOT the drawing, and the drawing is handled
        # separately (see "Make with drawing").
        self.template_hint = QLabel(i18n.t(
            "You can also attach a sample BOQ or your usual template above "
            "— Prism will match its style, logo and layout. This is "
            "separate from the drawing, which is only ever sent to an AI "
            "after you say so, in \"Make with drawing\"."))
        self.template_hint.setObjectName("note")
        self.template_hint.setWordWrap(True)
        # (placed in More options below: step 1 shows only the request, the
        # drawing and the industry.)

        # item 38 (2 Nov 2026): a scanned/vector-less PDF drawing has no
        # geometry Prism can measure itself — classify_inputs() files it as
        # the drawing (cad_path), same as a .dwg/.dxf, but _absorb() below
        # skips the automatic measurement step for it (there is nothing for
        # MeasureWorker to measure) and shows this instead of a silent
        # "not a CAD drawing" error. Hidden until that actually happens —
        # most jobs attach a real .dwg/.dxf and never need to see it.
        self.pdf_drawing_hint = QLabel("")
        self.pdf_drawing_hint.setObjectName("note")
        self.pdf_drawing_hint.setWordWrap(True)
        self.pdf_drawing_hint.setVisible(False)
        root.addWidget(self.pdf_drawing_hint)

        # A second way in, beside measuring a drawing: the owner's own ask,
        # 24 Oct 2026, built for a tool like the PDF takeoff extractor that
        # measures OUTSIDE Prism and hands back numbers, not a drawing file.
        # Paste or upload that text here and it is treated exactly like a
        # drawing's own measured figures from this point on — handed to the
        # writer as plain text, never as an image, never sent anywhere
        # until "Make my {noun}" is actually pressed.
        meas_row = QHBoxLayout()
        meas_row.setContentsMargins(0, 0, 0, 0)
        meas_row.setSpacing(theme.SPACE_2)
        self.input_meas_btn = self.button(
            i18n.t("Input measurements…"), "secondary", icon_name="paperclip",
            small=True, on_click=self._open_input_measurements)
        # (placed in More options below, next to Favourites.)
        # Only ever shown for an industry that actually has its own
        # PDF-takeoff tool (today, only HVAC) -- picked explicitly from
        # the Industry dropdown above, never guessed from a file. See
        # addons/boq/industries.has_takeoff and BOQ-CHANGES-TODO.md item 26.
        self.takeoff_btn = self.button(
            i18n.t("{industry} PDF takeoff…").format(industry=industries.HVAC),
            "secondary", icon_name="paperclip", small=True,
            on_click=self._open_industry_takeoff)
        self.takeoff_btn.setVisible(False)
        # For "A PDF or picture": the one button that reads it for the chosen trade.
        self.route_btn = self.button(
            i18n.t("Read this drawing…"), "secondary", icon_name="paperclip",
            small=True, on_click=self._open_route_tool)
        self.route_btn.setVisible(False)
        meas_row.addWidget(self.route_btn)
        meas_row.addStretch(1)
        root.addLayout(meas_row)
        if self.mode == "boq":
            # The preview's two optional extras, side by side so step 1 stays one screen.
            opt = QHBoxLayout()
            opt.setContentsMargins(0, 0, 0, 0)
            opt.setSpacing(theme.SPACE_2)
            opt_lab = QLabel(i18n.t("Optional:"))
            opt_lab.setObjectName("meta")
            opt.addWidget(opt_lab)
            self.format_btn = self.button(
                i18n.t("Add my company's BOQ format"), "secondary", icon_name="file",
                small=True, on_click=self.ask._pick_file,
                tooltip=i18n.t("Add one of your past BOQs (Excel or Word). The new one will look the same."))
            self.meas_btn2 = self.button(
                i18n.t("Add measurements I already have"), "secondary", icon_name="paperclip",
                small=True, on_click=self._open_input_measurements,
                tooltip=i18n.t("From a site visit or another tool. Prism uses them exactly as given."))
            opt.addWidget(self.format_btn)
            opt.addWidget(self.meas_btn2)
            opt.addStretch(1)
            root.addLayout(opt)

        # Only appears once external measurements have actually been given —
        # a second, independent result panel from meas_box: that one is only
        # ever filled by Prism's own geometry engine measuring a real
        # drawing, and must stay that way so the two are never confused
        # about what actually measured something.
        self.ext_meas_box = QGroupBox(i18n.t("External measurements"))
        ext_l = QVBoxLayout(self.ext_meas_box)
        self.ext_meas_view = QPlainTextEdit()
        self.ext_meas_view.setReadOnly(True)
        self.ext_meas_view.setMaximumHeight(160)
        ext_l.addWidget(self.ext_meas_view)
        self.ext_meas_label = QLabel("")
        self.ext_meas_label.setWordWrap(True)
        self.ext_meas_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        ext_l.addWidget(self.ext_meas_label)
        self.ext_meas_box.setVisible(False)
        # ── step 2: check the count ──────────────────────────────────────
        root.page(1)
        # Said only when there is nothing to count, so the page is never a
        # blank: a BOQ can be made from words alone.
        self.count_head = QLabel("")
        self.count_head.setObjectName("stepQ")
        root.addWidget(self.count_head)
        self.count_hint = C.label(i18n.t(
            "Nothing to count yet. With a drawing, Prism counts it here for "
            "you to check. Without one, it lists the items from your words "
            "in the next step."), level="SUPPORT", wrap=True)
        root.addWidget(self.count_hint)
        # What the numbers rest on, above the table: counts, flags, and what is
        # measured versus estimated (addons/boq/evidence.py).
        self.evidence_box = QLabel("")
        self.evidence_box.setTextFormat(Qt.RichText)
        self.evidence_box.setWordWrap(True)
        self.evidence_box.setStyleSheet(
            f"background: {theme.CANVAS}; border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        self.evidence_box.setVisible(False)
        root.addWidget(self.evidence_box)
        root.addWidget(self.ext_meas_box)

        # Only appears once a drawing has actually been measured.
        self.meas_box = QGroupBox("Measured from your drawing")
        meas_l = QVBoxLayout(self.meas_box)
        # A table, not the prompt text: one row per measured item, the way
        # the CSV has it (addons/boq/measured.py). The prompt text is still
        # built -- it is what the AI stages receive -- it is just not what
        # the person is shown.
        self.meas_table = MeasuredTable()
        meas_l.addWidget(self.meas_table)
        # Not the dashed #emptyState box it used to be: this line says "your
        # numbers are saved, here is where", which is a result and not the
        # absence of one. A dashed placeholder box around a success message
        # reads as a slot still waiting to be filled.
        self.csv_label = QLabel("")
        self.csv_label.setWordWrap(True)
        self.csv_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px;"
            f" font-size: 13px;")
        meas_l.addWidget(self.csv_label)
        self.meas_box.setVisible(False)
        root.addWidget(self.meas_box)

        # Optional, and only for a BOQ: price the measured lines. The engine
        # half (core.boq_price) prices by arithmetic from a rate list the
        # customer brings; this card is its window. Appears with the
        # measurement, because there is nothing to price before it.
        # A plain container, not a titled group frame: the step tab already
        # says "Add prices", and the cards inside say how.
        self.price_box = QWidget()
        price_l = QVBoxLayout(self.price_box)
        price_l.setContentsMargins(0, 0, 0, 0)
        self.price_table = PricingTable(self.cfg)
        price_l.addWidget(self.price_table)
        self.price_box.setVisible(False)
        # ── step 4: add prices (a BOQ only; a BOM has no step for it) ────
        root.page(3 if self.mode == "boq" else 2)
        price_head = QLabel(i18n.t("Add prices to your {noun}?").format(noun=self._noun))
        price_head.setObjectName("stepQ")
        root.addWidget(price_head)
        self.price_hint = C.label(i18n.t(
            "Prices are optional. Once your {noun} is made, the rates you "
            "bring go here and Prism adds them up.").format(noun=self._noun),
            level="SUPPORT", wrap=True)
        root.addWidget(self.price_hint)
        root.addWidget(self.price_box)
        root.page(0)

        # Which AIs run the BOQ. Re-pickable per BOQ: the write-up tool
        # (Prism Agent Claude vs ChatGPT vs …) and the standards-research
        # tool (No research vs Perplexity vs …) each change the result,
        # and the user should be able to choose them for one document
        # without editing the global Agents setup. The interpreter
        # (screenshot reader) stays automatic — it only runs when an image
        # is attached, and ChatGPT is the right tool for it.
        #
        # The POOL each picker offers is BOQ's own (addons/boq/agents.py),
        # not the engine's shared CATEGORIES — see that file for why. Since
        # item 30a/30b, the default is no longer "whatever's configured in
        # Settings" (see the comment just below) — it starts on index 0 of
        # each list instead: "Prism Agent Claude" and "No research".
        writer_opts = list(boq_agents.WRITER) or ["Claude", "ChatGPT"]
        research_opts = list(boq_agents.RESEARCH) or ["Perplexity"]
        self.writer_combo = QComboBox()
        self.writer_combo.addItems(writer_opts)
        self.research_combo = QComboBox()
        self.research_combo.addItems(research_opts)
        # item 30a/30b: the default is now "Prism Agent Claude" (an
        # OpenRouter API call) and "No research" -- both are index 0 of
        # their own list (addons/boq/agents.py), so simply NOT calling
        # _preselect() here is what makes them win over whatever a
        # generic Settings agent pick would otherwise override them with.
        # A person who wants a browser agent, or research back on, still
        # picks it from the dropdown same as always -- this only changes
        # what a fresh BOQ starts on.
        # One label + control per row, in a grid: the old single row of
        # four label/combo pairs was wider than the dialog.
        picker = QWidget()
        pgrid = QGridLayout(picker)
        pgrid.setContentsMargins(0, 0, 0, 0)
        pgrid.setHorizontalSpacing(theme.SPACE_3)
        pgrid.setVerticalSpacing(theme.SPACE_2)
        pgrid.setColumnStretch(1, 1)

        def pick_row(r: int, text: str, widget):
            lab = QLabel(i18n.t(text)); lab.setObjectName("meta")
            pgrid.addWidget(lab, r, 0)
            pgrid.addWidget(widget, r, 1)

        pick_row(0, "Write with", self.writer_combo)
        pick_row(1, "Research with", self.research_combo)
        # item 30d: "someone made 3 BOQs today, needs to follow up on the
        # first one this afternoon" — a new job's own dialog instance has
        # no memory of a PAST one (each open of this add-on is a fresh
        # BoqDialog), so resuming one has to come from the side, not from
        # continuing the live screen.
        self.history_btn = C.button(i18n.t("History"), "tertiary", small=True,
                                    icon_name="clock", on_click=self._open_history)
        pgrid.addWidget(self.history_btn, 3, 0, 1, 2, Qt.AlignLeft)
        # What file the write-up, "Verify and remake" and a follow-up should
        # hand back — the owner's own ask: "a dedicated button just to
        # select in which file format does the user want the file", after
        # "Verify and remake" came back with nothing to open at all. "Let
        # the tool decide" (empty) changes nothing about today's behaviour;
        # picking a format adds one line to the prompt AND promotes the
        # stage to a `file` step in the engine's own contract (see
        # core/contract.py), which re-asks once and, worst case, writes the
        # document out of the tool's own words itself — so a format, once
        # chosen, is a promise, not just a request.
        self.format_combo = QComboBox()
        self.format_combo.addItem(i18n.t("Let the tool decide"), "")
        self.format_combo.addItem(i18n.t("Word document (.docx)"), "docx")
        self.format_combo.addItem(i18n.t("Excel spreadsheet (.xlsx)"), "xlsx")
        self.format_combo.addItem(i18n.t("CSV"), "csv")
        self.format_combo.addItem(i18n.t("PDF"), "pdf")
        pick_row(2, "File format", self.format_combo)
        # Which industry this job is for -- item 26: BOQ is sold across
        # industries, and each one reads its own drawings by its own
        # rules, so the rule-set that runs (HVAC_DRAWING_RULES.md's
        # write-up guidance, and below, which PDF-takeoff tool offers
        # itself) is this explicit choice, never guessed from the request
        # text or from an uploaded file's own content -- see
        # addons/boq/industries.py and self._on_industry_changed.
        ilab = QLabel(i18n.t("Industry")); ilab.setObjectName("meta")
        self.industry_combo = QComboBox()
        self.industry_combo.addItems(industries.NAMES)
        self.industry_combo.currentTextChanged.connect(self._on_industry_changed)
        # Visible on step 1, not folded away: it decides which drawing rules
        # run, so a person has to be able to see it before measuring.
        ind_row = QWidget()
        irow = QHBoxLayout(ind_row)
        irow.setContentsMargins(0, 0, 0, 0)
        irow.setSpacing(theme.SPACE_3)
        irow.addWidget(ilab)
        irow.addWidget(self.industry_combo)
        irow.addStretch(1)
        root.addWidget(ind_row)
        # For a BOQ the job-kind cards at the top of this page are the choice;
        # this box stays as the one value they set (the engines read it).
        ind_row.setVisible(self.mode == "bom")
        # Says out loud which drawing rules will run, the preview's one line.
        self.rules_line = C.label(i18n.t(
            "HVAC drawing rules are on, because your industry is HVAC."),
            level="SUPPORT", wrap=True, colour=theme.OK_INK)
        self.rules_line.setVisible(False)
        self.industry_combo.currentTextChanged.connect(
            lambda name: self.rules_line.setVisible(name == industries.HVAC))
        _lay = root._layouts[0]                         # step 1's column
        _at = _lay.indexOf(self.drawing_card) + 1      # right under the drawing, before the optional row
        _lay.insertWidget(_at, self.rules_line)
        # The trade's own tool, always visible for HVAC / ELV (the owner could not find
        # scale and colours when this was folded away), plus what a CAD file holds.
        self.takeoff_block = TakeoffBlock()
        self.takeoff_block.open_tool.connect(self._open_trade_tool)
        self.takeoff_block.setVisible(False)
        _lay.insertWidget(_at + 1, self.takeoff_block)

        # Everything technical lives here, shut by default.
        self.more = MoreOptions("More settings: most people skip this", optional_suffix=False)
        # Who writes and researches, the file format and a way back to an
        # earlier job: each changes the result, so they stay one click away,
        # but a first-time person never has to read them.
        self.more.add(picker)
        # Extra files: a sample/template BOQ, measurements made elsewhere and
        # starred files. Same buttons and handlers, moved out of step 1.
        self.more.add(self.template_hint)
        extra_row = QHBoxLayout()
        extra_row.setContentsMargins(0, 0, 0, 0)
        extra_row.setSpacing(theme.SPACE_2)
        extra_row.addWidget(self.input_meas_btn)
        extra_row.addWidget(self.ask.fav_btn)
        extra_row.addWidget(self.takeoff_btn)     # the old HVAC/ELV PDF takeoff, for experts
        extra_row.addStretch(1)
        self.more.add_layout(extra_row)
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText(i18n.t("Drawing unit, if you know it — e.g. meters"))
        self.more.add(self.unit_edit)
        self.scope_edit = QLineEdit()
        self.scope_edit.setPlaceholderText("Only include layers containing… (comma separated)")
        self.more.add(self.scope_edit)
        # The CLI takes this as a `legend:` directive on /boq. Same thing, so
        # the interpreter stage gets the same hint in both apps.
        self.legend_edit = QLineEdit()
        self.legend_edit.setPlaceholderText(
            "What the drawing's symbols mean, if the sheet doesn't say — e.g. "
            "circles = light points")
        self.more.add(self.legend_edit)
        self.derive_cb = QCheckBox(
            "Estimate items the drawing doesn't contain (marked as an estimate)")
        self.derive_cb.setChecked(True)
        self.more.add(self.derive_cb)
        root.addWidget(self.more)
        # The preview's "Continue where you left off": past BOQs, entry state only.
        self.continue_list = ContinueList()
        self.continue_list.chosen.connect(self._continue_run)
        self.continue_list.artifacts.connect(self._open_artifacts)
        if self.mode == "boq":
            root.addWidget(self.continue_list)
            self.continue_list.refresh()
            self._sync_continue()

        # Progress and status sit under the tabs, outside the pages, so
        # "reading your drawing..." is seen whichever step you are on.
        self.progress = Loader("stages", [i18n.t(n) for n in ['Measure', 'Check', 'Write']])
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.body.insertWidget(2, self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.body.insertWidget(3, self.status)
        # One plain sentence about what went wrong, and ONE button that fixes it.
        self.fix_bar = QFrame()
        self.fix_bar.setObjectName("fixBar")
        fl = QHBoxLayout(self.fix_bar)
        fl.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        fl.setSpacing(theme.SPACE_3)
        self.fix_text = QLabel("")
        self.fix_text.setWordWrap(True)
        fl.addWidget(self.fix_text, stretch=1)
        self.fix_btn = self.button(i18n.t("Fix it"), "primary", small=True, on_click=self._do_fix)
        fl.addWidget(self.fix_btn)
        self.fix_bar.setStyleSheet(
            f"#fixBar {{ background: {theme.ERR_BG}; border-radius: {theme.R_CONTROL}px; }}"
            f" #fixBar QLabel {{ color: {theme.ERR_INK}; background: transparent; }}")
        self.fix_bar.setVisible(False)
        self._fix_action = None
        self.body.insertWidget(self.body.indexOf(self.pages), self.fix_bar)
        self._est = {}                 # {"write": mc, "drawing": mc} from the server, when it says
        self._est_worker = None
        self._est_asked = ""
        self._credits_before = None

        # ── step 3: make the BOQ ─────────────────────────────────────────
        root.page(2)
        # Two ways to make it, one button below. Both existed before as
        # "Make my BOQ" and "Make with drawing"; the cards just say what each
        # one does with the drawing, in plain words, before anything is sent.
        self.make_choice = QWidget()
        mrow = QHBoxLayout(self.make_choice)
        mrow.setContentsMargins(0, 0, 0, 0)
        mrow.setSpacing(theme.SPACE_3)
        self.choice_count = ChoiceCard(
            "list", i18n.t("From the count (recommended)"),
            i18n.t("Your drawing stays on this computer. Only the checked "
                   "numbers go to AI to write the {noun}.").format(noun=self._noun))
        self.choice_drawing = ChoiceCard(
            "eye", i18n.t("With the drawing"),
            i18n.t("AI reads the drawing itself as well. Prism asks you first: "
                   "the drawing leaves this computer only if you say yes."))
        self.choice_count.clicked.connect(lambda: self._pick_make_way(False))
        self.choice_drawing.clicked.connect(lambda: self._pick_make_way(True))
        mrow.addWidget(self.choice_count)
        mrow.addWidget(self.choice_drawing)
        make_title = QLabel(i18n.t("How should Prism make your {noun}?").format(
            noun=self._noun))
        make_title.setObjectName("h4")
        self.make_choice_box = QWidget()
        mbox = QVBoxLayout(self.make_choice_box)
        mbox.setContentsMargins(0, 0, 0, 0)
        mbox.setSpacing(theme.ROW_GAP)
        mbox.addWidget(make_title)
        mbox.addWidget(self.make_choice)
        self.make_choice_box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(self.make_choice_box)
        self._with_drawing = False

        # QTextEdit, not QPlainTextEdit: the writing AI returns markdown
        # (**bold**, > notices, tables) -- QPlainTextEdit shows that literally,
        # asterisks and all, instead of rendering it. Reading it back for a
        # follow-up/recheck prompt uses toMarkdown(), not toPlainText(): Qt
        # renders a markdown table into a real QTextTable, and toPlainText()
        # on that just concatenates the cell text with no row/column
        # separators -- unreadable to the AI. toMarkdown() round-trips a
        # table (and round-trips plain text with no markdown in it, too).
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText(f"Your {self._noun} will appear here.")
        self.result.setMinimumHeight(120)
        # Once a document exists, what you can do with it sits right above it
        # as pill buttons, not in the footer (which keeps Back, Close and the
        # one primary so nothing is clipped).
        self.result_actions = QWidget()
        self._actions = QHBoxLayout(self.result_actions)
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(theme.SPACE_2)
        self.made_head = QLabel(i18n.t("Your {noun} is ready").format(noun=self._noun))
        self.made_head.setObjectName("stepQ")
        self.made_sub = C.label(i18n.t(
            "Check it against the saved file. Prices are added in the next step."),
            level="SUPPORT", wrap=True)
        root.addWidget(self.made_head)
        root.addWidget(self.made_sub)
        root.addWidget(self.result_actions)
        root.addWidget(self.result, stretch=1)
        # "Want to change something? Just type it": the follow-up the old pop-up offered,
        # right under the document.
        self.change_box = QWidget()
        cb = QVBoxLayout(self.change_box)
        cb.setContentsMargins(0, 0, 0, 0)
        cb.setSpacing(theme.SPACE_1)
        cb.addWidget(C.label(i18n.t("Want to change something? Just type it."), level="SUPPORT"))
        crow = QHBoxLayout()
        crow.setSpacing(theme.SPACE_2)
        self.change_edit = QLineEdit()
        self.change_edit.setPlaceholderText(i18n.t("e.g. split the ductwork floor by floor"))
        self.change_btn = self.button(i18n.t("Change it"), "secondary", small=True,
                                      on_click=self._change_it)
        crow.addWidget(self.change_edit, stretch=1)
        crow.addWidget(self.change_btn)
        cb.addLayout(crow)
        self.change_edit.returnPressed.connect(self._change_it)
        root.addWidget(self.change_box)

        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self._actions.addWidget(self.open_btn)
        # item 66: fill the CLIENT'S OWN template (their logo, letterhead,
        # column widths) with this result's line items, instead of handing
        # them Prism's own generic docx and leaving them to copy the
        # numbers across by hand. Enabled once there is a result to fill a
        # template WITH -- _show_result is the one place every write/
        # recheck/follow-up path already funnels through.
        self.fill_template_btn = self.button(
            i18n.t("Fill into template…"), "secondary", icon_name="paperclip",
            small=True, on_click=self._fill_template)
        self.fill_template_btn.setEnabled(False)
        self._actions.addWidget(self.fill_template_btn)
        # Same job "Verify and remake" (the follow-up window's quick action)
        # already does -- read the drawing itself, not just the measured
        # figures -- so one button now covers both: pressed before any BOQ
        # exists, it MAKES the BOQ straight from the drawing; pressed after
        # one exists, it rechecks/corrects it, same as before. Enabled by a
        # drawing alone (see _on_measured), not by also requiring a result
        # first -- that was the one thing stopping it standing beside
        # "Make my BOQ" from the start.
        self.recheck_btn = self.button(i18n.t("Make with drawing"), "secondary",
                                       icon_name="eye", small=True,
                                       on_click=self._ask_recheck)
        self.recheck_btn.setEnabled(False)
        self._actions.addWidget(self.recheck_btn)
        self._actions.addStretch(1)
        self.back_btn = self.button(i18n.t("Back"), icon_name="chevron-left",
                                    on_click=self._back)
        self.footer.add_utility(self.back_btn)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        # One primary whose job follows the step: Next, Next, Make, Next/Finish.
        # Making the document is `_run` (or `_ask_recheck` when "With the
        # drawing" is picked), exactly the two handlers the old "Make my BOQ"
        # and "Make with drawing" buttons had.
        self.run_btn = self.button("", "primary", on_click=self._primary)
        self.footer.set_primary(self.run_btn)
        self.skip_btn = self.button(i18n.t("Finish without prices"), on_click=self.reject)
        self.skip_btn.setVisible(False)
        self.footer.add_secondary(self.skip_btn)
        self._why = QLabel("")
        self._why.setObjectName("note")
        self._why.setWordWrap(True)
        self._why.setVisible(False)
        self.footer.add_note(self._why)
        for i, lay in enumerate(self._page_layouts):
            # Spare height goes under the content of a page, never between its rows;
            # the make-it page keeps its document box as the one thing that grows.
            lay.addStretch(0 if i == self.S_MAKE else 1)
        self._step = 0
        self.ask.edit.textChanged.connect(self._refresh_primary)
        self.ask.edit.textChanged.connect(
            lambda: (self.example_row.setVisible(not self.ask.text() and not self.cad_path),
                     self._sync_continue()))
        self.ask.files_added.connect(self._refresh_primary)
        self.ask.file_removed.connect(self._refresh_primary)
        self.ask.file_removed.connect(lambda *_: self._sync_chips())
        self._show_step(0)
        if self.mode == "boq":
            self._init_route()

        # Files already attached on the home screen come along automatically.
        if attachments:
            self._absorb([a["path"] for a in attachments])

    # ── what do you have / what kind of job ─────────────────────────────

    def _build_route_cards(self, root):
        """One question in plain words, as a short row of choices: what kind of
        work this is. It is always an explicit choice (a file never decides the
        trade). What the person HAS (a CAD file, a PDF or picture, nothing) is
        no longer asked: the file they add, or the lack of one, says it."""
        head = QLabel(i18n.t("What kind of work is this?"))
        head.setObjectName("stepQ")
        root.addWidget(head)
        self.chip_box = QWidget()
        self.chip_lay = QVBoxLayout(self.chip_box)
        self.chip_lay.setContentsMargins(0, 0, 0, 0)
        self.chip_lay.setSpacing(theme.SPACE_2)
        root.addWidget(self.chip_box)
        self.job_cards = {}            # the built-in trades, by name
        self.extra_chips = {}          # "other" and "custom:<id>"
        self._custom = None            # the user's own industry, when one is chosen
        self._other = False            # "Other / My industry" with nothing described
        self.add_chip = None
        cap = QHBoxLayout()
        cap.setContentsMargins(0, 0, 0, 0)
        cap.setSpacing(theme.SPACE_2)
        self.job_caption = C.label("", level="META", wrap=True)
        cap.addWidget(self.job_caption, stretch=1)
        self.edit_industry_btn = QPushButton(i18n.t("Edit"))
        self.edit_industry_btn.setObjectName("linkBtn")
        self.edit_industry_btn.setCursor(Qt.PointingHandCursor)
        self.edit_industry_btn.clicked.connect(self._edit_industry)
        self.remove_industry_btn = QPushButton(i18n.t("Remove"))
        self.remove_industry_btn.setObjectName("linkBtn")
        self.remove_industry_btn.setCursor(Qt.PointingHandCursor)
        self.remove_industry_btn.clicked.connect(self._remove_industry)
        cap.addWidget(self.edit_industry_btn)
        cap.addWidget(self.remove_industry_btn)
        root.addLayout(cap)
        self.job_note = C.label("", level="SUPPORT", wrap=True, colour=theme.WARN_INK)
        self.job_note.setVisible(False)
        root.addWidget(self.job_note)
        self._rebuild_chips()

    def _rebuild_chips(self):
        """Draw the choices: the built-in trades, the user's own, Other, and Add."""
        while self.chip_lay.count():
            item = self.chip_lay.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w is not None:
                        w.hide(); w.setParent(None); w.deleteLater()
                lay.deleteLater()
        self.job_cards, self.extra_chips = {}, {}
        chips = []
        for name, title, hint in route.JOB_CARDS:
            c = _IndustryChip(name, i18n.t(title), hint)
            c.clicked.connect(lambda _=False, n=name: self._pick_job(n))
            self.job_cards[name] = c
            chips.append(c)
        for e in CI.load(self.cfg):
            title = e["name"] if len(e["name"]) <= 18 else e["name"][:17] + "…"
            c = _IndustryChip(CI.choice_key(e), title, e["what"])
            c.setToolTip(e["name"])
            c.clicked.connect(lambda _=False, k=CI.choice_key(e): self._pick_job(k))
            self.extra_chips[CI.choice_key(e)] = c
            chips.append(c)
        c = _IndustryChip(CI.OTHER, i18n.t("Other / My industry"), "")
        c.clicked.connect(lambda _=False: self._pick_job(CI.OTHER))
        self.extra_chips[CI.OTHER] = c
        chips.append(c)
        self.add_chip = _IndustryChip("add", i18n.t("+ Add your industry"), "", add=True)
        self.add_chip.clicked.connect(self._add_industry)
        chips.append(self.add_chip)
        for i in range(0, len(chips), 5):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(theme.SPACE_2)
            for c in chips[i:i + 5]:
                row.addWidget(c)
            row.addStretch(1)
            self.chip_lay.addLayout(row)
        if hasattr(self, "industry_combo"):
            self._refresh_cards()

    def _job_key(self) -> str:
        if self._custom:
            return CI.choice_key(self._custom)
        if self._other:
            return CI.OTHER
        return self.industry_combo.currentText()

    def _init_route(self):
        """Start on the kind of job this person chose last time (General the first time)."""
        saved = str((self.cfg or {}).get(CI.LAST_KEY) or "")
        if saved == CI.OTHER:
            self._other = True
        elif saved.startswith(CI.CUSTOM_PREFIX):
            self._custom = CI.get(self.cfg, saved[len(CI.CUSTOM_PREFIX):])
        elif saved in industries.NAMES:
            self.industry_combo.setCurrentText(saved)
        self._refresh_cards()

    def _refresh_cards(self):
        industry = self.industry_combo.currentText()
        why_now = ""
        for name, title, hint in route.JOB_CARDS:
            card = self.job_cards[name]
            ok, why = route.availability(self._input_kind, name, self.cad_path)
            card.setEnabled(ok)
            card.hint_text = i18n.t(hint) if ok else i18n.t(why)
            card.setToolTip("" if ok else i18n.t(why))
            if not ok and not why_now:
                why_now = why
            if name == industry and not ok and not (self._custom or self._other):
                self.industry_combo.setCurrentText(industries.GENERAL)
                industry = industries.GENERAL
        key = self._job_key()
        for name, card in self.job_cards.items():
            card.set_selected(key == name)
        for k, chip in self.extra_chips.items():
            chip.set_selected(k == key)
        if self._custom:
            e = self._custom
            n = len(e.get("items") or [])
            text = i18n.t("{what}. No takeoff tool of its own: measured like General; "
                          "your words guide the write-up.").format(what=e["what"].rstrip("."))
        elif self._other:
            text = i18n.t(route.OTHER_NOTE)
        else:
            card = self.job_cards.get(industry)
            text = " ".join(i18n.t(t) for t in (
                next((h for n, _t, h in route.JOB_CARDS if n == industry), ""),
                route.TOOL_NOTES.get(industry, "")) if t)
        self.job_caption.setText(text)
        self.edit_industry_btn.setVisible(bool(self._custom))
        self.remove_industry_btn.setVisible(bool(self._custom))
        self.job_note.setText(i18n.t(why_now) if why_now else "")
        self.job_note.setVisible(bool(why_now))

    def _set_input(self, kind):
        if not kind or self.mode != "boq":
            return
        self._input_kind = kind
        self.example_row.setVisible(not self.ask.text() and not self.cad_path)
        self._sync_continue()
        self._refresh_cards()
        self._on_industry_changed(self.industry_combo.currentText())
        self._replay_pipe()

    def _save_cfg(self):
        try:
            CB.config.save(self.cfg)
        except Exception:                               # noqa: BLE001
            pass

    def _pick_job(self, industry: str):
        """Choose the kind of work: a built-in trade, "other", or "custom:<id>"."""
        if industry == CI.OTHER or str(industry).startswith(CI.CUSTOM_PREFIX):
            entry = None if industry == CI.OTHER else CI.get(
                self.cfg, str(industry)[len(CI.CUSTOM_PREFIX):])
            if industry != CI.OTHER and entry is None:
                return
            self._custom, self._other = entry, industry == CI.OTHER
            self.industry_combo.setCurrentText(industries.GENERAL)   # the General measuring path
        else:
            ok, _why = route.availability(self._input_kind, industry, self.cad_path)
            if not ok or industry not in industries.NAMES:
                return
            self._custom, self._other = None, False
            self.industry_combo.setCurrentText(industry)
        self.job_note.setVisible(False)
        self.cfg[CI.LAST_KEY] = industry              # remembered for next time
        self._save_cfg()
        self._refresh_cards()
        # Numbers measured under another trade's rules are stale: measure again.
        now = self.industry_combo.currentText()
        if (self.q is not None and not self.q.get("external") and self.cad_path
                and now != self._industry
                and os.path.splitext(self.cad_path)[1].lower() in (".dwg", ".dxf")):
            self.q = None
            self.meas_box.setVisible(False)
            self._measure()
        self._replay_pipe()
        self._refresh_primary()

    def _add_industry(self):
        dlg = IndustryDialog(self.cfg, None, self)
        if dlg.exec() == QDialog.Accepted and dlg.saved_entry():
            self._save_cfg()
            self._rebuild_chips()
            self._pick_job(CI.choice_key(dlg.saved_entry()))

    def _edit_industry(self):
        if not self._custom:
            return
        dlg = IndustryDialog(self.cfg, self._custom, self)
        if dlg.exec() == QDialog.Accepted and dlg.saved_entry():
            self._save_cfg()
            self._custom = dlg.saved_entry()
            self._rebuild_chips()

    def _remove_industry(self):
        if not self._custom:
            return
        name = self._custom["name"]
        if QMessageBox.question(self, "BOQ", i18n.t(
                "Remove \"{name}\" from your industries? Past BOQs keep what they were "
                "written with.").format(name=name)) != QMessageBox.Yes:
            return
        CI.delete(self.cfg, self._custom["id"])
        self._custom = None
        self._save_cfg()
        self._rebuild_chips()

    # ── the pipeline strip ───────────────────────────────────────────────

    def _pipe(self, key: str, state: str, line: str = ""):
        if self.mode == "boq":
            self.pipe.set_stage(key, state, line)

    def _replay_pipe(self):
        """Draw the road for the chosen input and trade, then mark what is already done."""
        if self.mode != "boq":
            return
        kind = self._input_kind
        self.pipe.setVisible(bool(kind))
        if not kind:
            return
        industry = self.industry_combo.currentText()
        self.pipe.set_route(route.stages(kind, industry, self.cad_path))
        if kind == route.DESCRIBE:
            self._pipe("describe", route.DONE if self.ask.text() else route.NEEDS_YOU,
                       i18n.t("Your words are the only input. Nothing is measured."))
            return
        if self._tool_result or (self.q and self.q.get("external")):
            self._pipe_tool_done()
        elif self.q is not None:
            self._pipe_measured(self.q)
        elif not self.cad_path:
            self._pipe("read", route.NEEDS_YOU, i18n.t("Add your drawing above."))
        elif kind == route.SCAN:
            self._pipe_scan_waiting()

    def _pipe_scan_waiting(self):
        industry = self.industry_combo.currentText()
        self._pipe("read", route.DONE, i18n.t("{name} added. It has not left this computer.")
                   .format(name=os.path.basename(self.cad_path)))
        if industry == industries.GENERAL:
            self._pipe("drawing", route.NEEDS_YOU, i18n.t(
                "In step 3 pick \"With the drawing\". Prism asks you before the drawing "
                "leaves this computer."))
        elif industry == industries.HVAC:
            self._pipe("scale", route.NEEDS_YOU, i18n.t(
                "Open the HVAC tool: set the scale, map the colours, extract."))
        else:
            self._pipe("tags", route.NEEDS_YOU,
                       i18n.t("Press \"{btn}\" below.").format(btn=self.route_btn.text()))

    def _pipe_measured(self, q: dict):
        ev = evidence.for_quantities(q)
        self._pipe("read", route.DONE, i18n.t("Read on this computer: {n:,} drawing objects. "
                                             "Nothing was sent anywhere.").format(
                                                 n=int(q.get("entity_count") or 0)))
        self._pipe("measure", route.DONE, i18n.t("{headline}. Measured on this computer, "
                                                 "no AI.").format(headline=ev["headline"]))
        self._pipe("check", route.NEEDS_YOU, i18n.t(
            "{n} item(s) flagged. Look at them in step 2.").format(n=ev["flagged"])
            if ev["flagged"] else i18n.t("Nothing was flagged. Have a look at the count in step 2."))
        self._show_evidence(ev)

    def _pipe_tool_done(self):
        kind = self._input_kind
        industry, result = self._tool_result or (self.industry_combo.currentText(), None)
        if result is None:
            ev = {"headline": "Numbers you gave", "rows": [], "flagged": 0, "warnings": [],
                  "basis": "Used exactly as you gave them. Prism did not measure or check them.",
                  "source": "given"}
            self._pipe("read", route.DONE, i18n.t("Your own numbers are used."))
        elif industry == industries.HVAC:
            ev = evidence.for_takeoff(result)
            self._pipe("read", route.DONE, i18n.t("PDF opened on this computer."))
            self._pipe("scale", route.DONE, i18n.t("You confirmed the scale in the takeoff tool."))
            self._pipe("layers", route.DONE, i18n.t("You mapped the line colours in the takeoff tool."))
            if ev["ai_used"]:
                tags = i18n.t("Tags read on this computer (text and OCR). Prism AI also checked "
                              "small cropped pieces, with your OK.")
            elif ev["ocr_reads"]:
                tags = i18n.t("Tags read on this computer (text and OCR). Prism AI was not used.")
            else:
                tags = i18n.t("Tags read from the PDF's own text only. OCR found nothing "
                              "extra and Prism AI was not used.")
            self._pipe("measure", route.DONE, i18n.t("{h}. On this computer. {tags}").format(h=ev["headline"], tags=tags))
        else:
            ev = evidence.for_reading(result)
            self._pipe("read", route.DONE, i18n.t("Drawing opened."))
            ai = ev["source"] == "read"
            self._pipe("tags", route.DONE, i18n.t("{h}.{ai}").format(
                h=ev["headline"], ai=i18n.t(" Prism AI was used.") if ai else i18n.t(" No AI.")))
        self._pipe("check", route.NEEDS_YOU, i18n.t("Check the count in step 2."))
        self._show_evidence(ev)

    def _show_evidence(self, ev: dict):
        self.evidence_box.setText(evidence.as_html(ev))
        self.evidence_box.setVisible(True)

    def _open_stage_detail(self, key: str):
        if key in ("tags", "scale", "layers") or (key == "measure" and self._input_kind == route.SCAN):
            if self._input_kind == route.SCAN and self.cad_path \
                    and self.industry_combo.currentText() != industries.GENERAL:
                self._open_route_tool()
                return
        if key in ("read", "measure", "tags", "check"):
            self._show_step(self.S_COUNT)
        elif key in ("write", "files"):
            self._show_step(self.S_MAKE)
        elif key == "prices" and self.mode == "boq":
            self._show_step(self.S_PRICE)

    def _route_button_text(self) -> str:
        industry = self.industry_combo.currentText()
        if industry == industries.HVAC:
            return i18n.t("Measure the ducts in this PDF…")
        return i18n.t("Read this drawing…")

    def _open_route_tool(self):
        """The PDF/picture tool for the chosen trade, with the file already picked."""
        industry = self.industry_combo.currentText()
        if not self.cad_path or industry == industries.GENERAL:
            return
        if industry == industries.HVAC:
            dlg = IndustryTakeoffDialog(industry, self, cfg=self.cfg, path=self.cad_path)
        else:
            dlg = ElvReadDialog(industry, self, cfg=self.cfg, path=self.cad_path)
        if dlg.exec() == QDialog.Accepted:
            self._tool_result = (industry, getattr(dlg, "result", None))
            self._use_external_measurements(dlg.measurements_text())

    # ── the steps ────────────────────────────────────────────────────────

    S_HAVE, S_COUNT, S_MAKE, S_PRICE = range(4)

    def _last_step(self) -> int:
        return len(self._step_names) - 1

    def _busy(self) -> bool:
        return self.progress.isVisibleTo(self)

    def _have_a_result(self) -> bool:
        return bool(self.result.toPlainText().strip())

    def _pick_make_way(self, with_drawing: bool):
        if with_drawing and not self.cad_path:
            return              # the card is disabled and says why; nothing to pick
        self._with_drawing = with_drawing
        self._refresh_primary()

    def _show_step(self, index: int):
        index = max(0, min(index, self._last_step()))
        self._step = index
        self.pages.setCurrentIndex(index)
        self.pages.updateGeometry()
        # The stack is as tall as its tallest page unless the others say they do not
        # count; step 1 now holds the two question rows and would stretch every step.
        for i in range(self.pages.count()):
            self.pages.widget(i).setSizePolicy(
                QSizePolicy.Preferred,
                QSizePolicy.Preferred if i == index else QSizePolicy.Ignored)
        self.tabs.set_current(index)
        self.back_btn.setVisible(index > 0)
        if index >= self.S_COUNT and hasattr(self, "_est"):
            self._want_estimates()
        self._refresh_primary()

    def _back(self):
        self._show_step(self._step - 1)

    def _route_tool_pending(self) -> bool:
        """A PDF or picture for a trade that has its own tool, not yet used: the one
        next action is to open that tool (HVAC: scale, colours, extract)."""
        return (self.mode == "boq" and self._input_kind == route.SCAN and bool(self.cad_path)
                and self.industry_combo.currentText() != industries.GENERAL
                and not self._tool_result and self.q is None)

    def _primary(self):
        if self._step == self.S_HAVE and self._route_tool_pending():
            self._open_route_tool()
        elif self._step == self.S_HAVE:
            self._show_step(self.S_COUNT)
        elif self._step == self.S_COUNT:
            self._show_step(self.S_MAKE)
        elif self._step == self.S_MAKE and not self._have_a_result():
            if self._with_drawing and self.cad_path:
                self._ask_recheck()
            else:
                self._run()
        elif self._step == self._last_step():
            self.reject()
        else:
            self._show_step(self._step + 1)

    def _primary_state(self) -> tuple:
        """(text, enabled, why-not): what the one primary button says and
        whether it works on this step. A greyed button always says why."""
        busy = self._busy()
        noun = self._noun
        if self._step == self.S_HAVE:
            ok = bool(self.ask.text() or self.q or self.cad_path)
            if self._route_tool_pending():
                return (i18n.t("Open the HVAC tool") if self.industry_combo.currentText() == industries.HVAC
                        else i18n.t("Read the drawing"), not busy, "")
            return (i18n.t("Next: count it"), ok and not busy,
                    "" if ok else i18n.t(
                        "Say what the {noun} is for, or attach a drawing.").format(noun=noun))
        if self._step == self.S_COUNT:
            return (i18n.t("Next: make the {noun}").format(noun=noun), not busy, "")
        if self._step == self.S_MAKE:
            if not self._have_a_result():
                ok = bool(self.ask.text() or self.q or self.cad_path)
                return (i18n.t("Make my {noun}").format(noun=noun), ok and not busy,
                        "" if ok else i18n.t(
                            "Say what the {noun} is for, or attach a drawing.").format(noun=noun))
            return (i18n.t("Finish") if self._last_step() == self.S_MAKE
                    else i18n.t("Next: add prices"), not busy, "")
        return (i18n.t("Finish"), True, "")

    def _refresh_primary(self, *_):
        text, ok, why = self._primary_state()
        self.run_btn.setText(text)
        self.run_btn.setEnabled(ok)
        self.run_btn.setToolTip(why)
        if self.mode == "boq":
            # a greyed button says why; otherwise the footer says what happens next
            self._why.setText(why if (why and not ok) else self._next_line())
            self._why.setObjectName("meta")
            self._why.style().unpolish(self._why); self._why.style().polish(self._why)
            # on the result step the footer is full (Back, Close, Finish without prices, Next)
            self._why.setVisible(not (hasattr(self, "skip_btn") and self._step == self.S_MAKE
                                      and self._have_a_result()))
        else:
            self._why.setText(why)
            self._why.setVisible(bool(why) and not ok)
        # The count page says so when there is nothing to count.
        has_count = self.meas_box.isVisibleTo(self) or self.ext_meas_box.isVisibleTo(self)
        self.count_hint.setVisible(not has_count)
        if self._input_kind == route.DESCRIBE and not has_count:
            self.count_head.setText(i18n.t("Nothing is counted without a drawing"))
        elif has_count:
            self.count_head.setText(i18n.t("Here is what Prism counted"))
        else:
            self.count_head.setText(i18n.t("Nothing to count yet"))
        self.price_hint.setVisible(not self.price_box.isVisibleTo(self))
        # The two ways to make it, until there is something made.
        has_result = self._have_a_result()
        self.make_choice_box.setVisible(not has_result)
        self.result.setVisible(has_result)
        can_draw = bool(self.cad_path)
        self.choice_drawing.setEnabled(can_draw)
        self.choice_drawing.setToolTip("" if can_draw else i18n.t(
            "Add a drawing in step 1 to use this."))
        if not can_draw:
            self._with_drawing = False
        self.choice_count.set_selected(not self._with_drawing)
        self.choice_drawing.set_selected(self._with_drawing)
        # Utilities that only mean something once there is something to act
        # on: re-checking against the drawing once a document exists, and the
        # browser link and the template once it is made.
        self.result_actions.setVisible(self._step == self.S_MAKE and has_result)
        self.made_head.setVisible(has_result)
        self.made_sub.setVisible(has_result)
        self.change_box.setVisible(has_result and self.mode == "boq")
        if hasattr(self, "skip_btn"):
            self.skip_btn.setVisible(self.mode == "boq" and self._step == self.S_MAKE and has_result)
        base_c = i18n.t("Your drawing stays on this computer. Only the checked numbers go to AI to write the {noun}.").format(noun=self._noun)
        base_d = i18n.t("AI reads the drawing itself as well. Prism asks you first: the drawing leaves this computer only if you say yes.")
        for card, base, key in ((self.choice_count, base_c, "write"), (self.choice_drawing, base_d, "drawing")):
            c = self._credit_phrase(key)
            card.hint.setText(base + (" " + i18n.t("Uses {c}.").format(c=c) if c else ""))
        self.status.setVisible(bool(self.status.text()) and not (
            (self._step >= self.S_MAKE or self.mode == "boq") and self.status.text() == _MEASURED_MSG))
        self.recheck_btn.setToolTip("" if can_draw else i18n.t(
            "Add a drawing in step 1 to use this."))
        self.open_btn.setToolTip("" if self.open_btn.isEnabled() else i18n.t(
            "The tool that wrote it gave no web link for this one."))

        self.usage_chip.refresh()

    # ── a problem, with one button that fixes it ─────────────────────────

    def _show_fix(self, error, label: str, action, text: str = ""):
        """Say what went wrong in plain words and offer the one fix. Replaces a
        pop-up the person had to dismiss before seeing what to do."""
        if text:
            self.fix_text.setText(text)
        else:
            problem = friendly.explain(error)
            first = problem.steps[0] if problem.steps else ""
            self.fix_text.setText(f"{problem.title}. {problem.what} {first}".strip())
        self.fix_btn.setText(i18n.t(label))
        self._fix_action = action
        self.fix_bar.setVisible(True)

    def _clear_fix(self):
        self.fix_bar.setVisible(False)
        self._fix_action = None

    def _do_fix(self):
        action, self._fix_action = self._fix_action, None
        self.fix_bar.setVisible(False)
        if callable(action):
            action()

    def _change_it(self):
        text = self.change_edit.text().strip()
        if not text or not self._have_a_result() or self._busy():
            return
        self.change_edit.clear()
        self._send_followup(text, [], verify=False)

    # ── what the AI steps will cost, and what they did ──────────────────

    def _writer_role(self) -> str:
        return "boq.agent_b" if self.writer_combo.currentText() == "Prism Agent Deep" else "boq.agent_a"

    def _want_estimates(self):
        """Ask the server (off the UI thread, never charging) what writing would
        typically cost. Nothing is shown when the server cannot say."""
        if self.mode != "boq" or not CB.ai_client.active():
            return
        key = f"{self._writer_role()}|{len(self.summary)}|{len(self.ask.text())}|{bool(self.cad_path)}"
        if key == self._est_asked or (self._est_worker is not None and self._est_worker.isRunning()):
            return
        self._est_asked = key
        chars = len(self.summary) + len(self.ask.text()) + 4000
        wanted = {"write": (self._writer_role(), chars, 0)}
        if self.cad_path:
            wanted["drawing"] = (self._writer_role(), chars, 1)
        self._est_worker = CreditEstimateWorker(wanted)
        self._est_worker.done.connect(self._on_estimates)
        self._est_worker.start()

    def _on_estimates(self, est: dict):
        self._est = dict(est)
        self._refresh_primary()

    def _credit_phrase(self, key: str) -> str:
        words = credit_words.credits_words(self._est.get(key))
        return i18n.t(words) if words else ""

    def _usage_now(self):
        from widgets import usage_chip
        return usage_chip.current_usage()

    def _note_credits_before(self):
        use = self._usage_now()
        self._credits_before = getattr(use, "credits_left", None)

    def _charge_text(self) -> str:
        use = self._usage_now()
        after = getattr(use, "credits_left", None)
        return credit_words.charge_words(self._credits_before, after,
                                         getattr(use, "run_cost", None))

    def _next_line(self) -> str:
        """The plain 'what happens next' line for this step (the footer shows it)."""
        kind, industry = self._input_kind, self.industry_combo.currentText()
        if self._step == self.S_HAVE:
            if kind == route.SCAN and industry == industries.HVAC and self.cad_path:
                return i18n.t("Next: open the HVAC tool: scale, line colours, extract.")
            if kind == route.SCAN and industry == industries.ELV and self.cad_path:
                return i18n.t("Next: Prism reads the labels and symbols. It asks you before anything is sent.")
            if kind == route.SCAN:
                return i18n.t("Next: you check what was added, then Prism AI reads the drawing, with your OK.")
            if self.cad_path:
                return i18n.t("Next: you check what Prism counted on this computer.")
            return i18n.t("Next: Prism AI lists the items from your words.")
        if self._step == self.S_COUNT:
            cost = self._credit_phrase("write")
            return i18n.t("Next: Prism AI writes the {noun} from these numbers.").format(noun=self._noun) \
                + (" " + i18n.t("Uses {c}.").format(c=cost) if cost else "")
        if self._step == self.S_MAKE:
            if not self._have_a_result():
                key = "drawing" if self._with_drawing and self.cad_path else "write"
                cost = self._credit_phrase(key)
                return i18n.t("Next: Prism AI writes it now.") + (
                    " " + i18n.t("Uses {c}.").format(c=cost) if cost else "")
            return i18n.t("Next: add prices (optional), or finish without them.")
        return i18n.t("Your files are saved. Press Finish when you are done.")

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        self._absorb(paths)

    def _absorb(self, paths: list):
        self._absorb_files(paths)
        self._sync_chips()
        self._sync_takeoff_block()
        self._refresh_primary()

    def _absorb_files(self, paths: list):
        """Work out what each file IS. The user should never be asked which
        box a file belongs in — a .dwg is the drawing, a .docx is the sample,
        an image is a screenshot of the sheet."""
        atts = []
        for p in paths:
            try:
                atts.append(CB.files.attach(p))
            except Exception:
                pass
        if not atts:
            return
        cad, templates, images, notes = self.boq.classify_inputs(atts)
        if self.mode == "boq" and (self._input_kind == route.SCAN
                                   or (not self._input_kind and not cad and not self.cad_path)):
            # A picture added with no CAD file is the drawing itself (a photo or
            # screenshot of it), not a legend screenshot.
            pics = [a for a in images if route.is_picture(a["path"])]
            images = [a for a in images if a not in pics]
            cad = pics + cad
        self.templates += templates
        self.images += images
        self.notes += notes
        # emit=False: we are already inside the files_added handler, and
        # add_paths dedupes on its own now — re-emitting would re-enter here
        # and classify every file (and re-count templates/images) twice.
        self.ask.add_paths([a["path"] for a in atts], emit=False)
        if templates:
            self._update_template_hint()
        if cad:
            self.cad_path = cad[0]["path"]
            self.drawing_card.set_file(os.path.basename(self.cad_path))
            if self.mode == "boq":
                self._set_input(route.kind_of_file(self.cad_path))
            if os.path.splitext(self.cad_path)[1].lower() in (".dwg", ".dxf"):
                self.pdf_drawing_hint.setVisible(False)
                self._measure()
            else:
                # A PDF classified as the drawing (core.boq.classify_inputs:
                # little/no extractable text, so not a sample BOQ either) —
                # no vector geometry exists to measure automatically.
                # _measure() would just raise "not a .dwg/.dxf" here, which
                # reads as an error on the very file the user correctly
                # attached as the drawing. The real path for this is "Make
                # with drawing" -- enabled directly, the same as _on_measured
                # does for a real measurement, since there is no measurement
                # to wait for.
                self.recheck_btn.setEnabled(True)
                if self.mode == "boq" and self.industry_combo.currentText() == industries.GENERAL:
                    self._with_drawing = True    # nothing to measure: the AI reads it, after you say yes
                self.pdf_drawing_hint.setText(i18n.t(
                    "{name} has no vector geometry to measure automatically "
                    "— it's a PDF/scan, not a .dwg/.dxf. Press \"Make with "
                    "drawing\" to let the AI read it directly, or use "
                    "\"Input measurements\" to type the numbers yourself.")
                    .replace("{name}", os.path.basename(self.cad_path)))
                # a trade with its own PDF tool is told by the strip and the button instead
                self.pdf_drawing_hint.setVisible(not (self.mode == "boq" and self.industry_combo.currentText() != industries.GENERAL))
                if self.mode == "boq":
                    self._pipe_scan_waiting()

    def _sync_continue(self):
        """Shown only at the very start: nothing typed, no file, nothing measured or made."""
        if not hasattr(self, "continue_list") or self.mode != "boq":
            return
        entry = (not self.ask.text() and not self.cad_path and self.q is None
                 and not getattr(self, "_boq_run_path", ""))
        self.continue_list.setVisible(entry and bool(self.continue_list.rows))
        if hasattr(self, "example_row") and entry and self.continue_list.rows:
            self.example_row.setVisible(False)       # keep step 1 on one screen

    def _continue_run(self, record: dict):
        if record.get("last_text"):
            self._resume_from_history(record)
        else:                                        # older record with no saved result: start from its request
            self.ask.set_text(record.get("request") or "")
            self._boq_run_path = record.get("_path", "")
        self.continue_list.setVisible(False)

    def _open_artifacts(self):
        parent = self.parent()
        self.reject()
        if parent is not None and hasattr(parent, "_show_screen"):
            parent._show_screen("artifacts")

    def _sync_chips(self):
        """BOQ: the drawing already has its own card, so the attachment list under the
        box only shows when something else (a sample BOQ, a note) is attached."""
        if self.mode != "boq":
            return
        extra = len(self.ask.paths()) - (1 if self.cad_path else 0)
        self.ask.chips.setVisible(extra > 0)
        self.example_row.setVisible(not self.ask.text() and not self.cad_path)

    def _update_template_hint(self):
        """Turns the standing invitation above into a confirmation once a
        sample/template BOQ has actually been attached — count included,
        so a second one landing is visibly noticed too, not silently
        folded into the same unchanged sentence."""
        n = len(self.templates)
        word = (i18n.t("sample template") if n == 1
               else i18n.t("sample templates"))
        self.template_hint.setText(
            i18n.t("{n} {word} attached — Prism will match the style "
                  "shown. The drawing itself is only ever sent to an AI "
                  "after you say so, in \"Make with drawing\".")
            .replace("{n}", str(n)).replace("{word}", word))

    # ── external measurements (the second way in, besides a drawing) ─────

    def _open_input_measurements(self):
        dlg = InputMeasurementsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._tool_result = None
            self._use_external_measurements(dlg.measurements_text())

    def _on_industry_changed(self, industry: str):
        """Item 26: the PDF-takeoff button is only ever offered for an
        industry that has one of its own (HVAC, ELV) -- a pharma-tech job
        must not be shown a button that would silently run HVAC's own
        OCR/rules (or ELV's own AI read) against a drawing that was never
        either one. The button's own TEXT must follow the selection too --
        found live, 7 Nov 2026: it was hardcoded to say "HVAC PDF
        takeoff…" even while ELV was selected, left over from when HVAC
        was the only industry with one."""
        scan = getattr(self, "_input_kind", "") == route.SCAN
        self.takeoff_btn.setVisible(industries.has_takeoff(industry) and not scan)
        self.takeoff_btn.setText(i18n.t("{industry} PDF takeoff…").format(industry=industry))
        self._sync_takeoff_block()
        if hasattr(self, "route_btn"):
            self.route_btn.setText(self._route_button_text())
            self.route_btn.setVisible(scan and industry != industries.GENERAL
                                      and bool(self.cad_path))

    def _sync_takeoff_block(self):
        """Show the trade's tool block for HVAC and ELV (always, with or without a file);
        the Drawing unit field lives in it while it is up, otherwise back under More settings."""
        if not hasattr(self, "takeoff_block") or self.mode != "boq":
            return
        industry = self.industry_combo.currentText()
        on = industries.has_takeoff(industry)
        cad = bool(self.cad_path) and os.path.splitext(self.cad_path)[1].lower() in (".dwg", ".dxf")
        self.takeoff_block.setVisible(on)
        if on:
            self.takeoff_block.set_trade(industry, cad, industries.has_ai_read_modes(industry))
            self.takeoff_block.unit_slot.addWidget(self.unit_edit)
            if cad:
                self._peek_cad()
        else:
            self.more.add(self.unit_edit)
        self.unit_edit.setVisible(True)

    def _peek_cad(self):
        path = self.cad_path
        if getattr(self, "_peeked", "") == path:
            return
        self._peeked = path
        import tempfile
        self._peek_worker = CadPeekWorker(path, tempfile.mkdtemp(prefix="prism-peek-"))
        self._peek_worker.done.connect(self._on_peek)
        self._peek_worker.start()

    def _on_peek(self, path: str, info: dict):
        if path == self.cad_path:
            self.takeoff_block.show_peek(info)
            self.scroll.ensureWidgetVisible(self.takeoff_block.peek)

    def _open_trade_tool(self):
        """The block's one button: the trade's own tool (HVAC: scale, colours, extract)."""
        industry = self.industry_combo.currentText()
        if self._input_kind == route.SCAN and self.cad_path:
            self._open_route_tool()
        else:
            self._open_industry_takeoff()

    def _open_industry_takeoff(self):
        # item 63: an industry read purely by an AI vision model (no
        # geometry engine of its own, today only ELV) gets its own dialog
        # shape -- IndustryTakeoffDialog's Step 1 (which line colour is
        # which) has nothing to show for an industry with no layer
        # geometry to map. Both dialogs expose the same measurements_text()
        # interface, so everything from here down stays unchanged either way.
        industry = self.industry_combo.currentText()
        dlg = (ElvReadDialog(industry, self, cfg=self.cfg)
              if industries.has_ai_read_modes(industry)
              else IndustryTakeoffDialog(industry, self, cfg=self.cfg))
        if dlg.exec() == QDialog.Accepted:
            self._tool_result = (industry, getattr(dlg, "result", None))
            self._use_external_measurements(dlg.measurements_text())

    def _use_external_measurements(self, text: str):
        """Numbers already measured by a tool outside Prism (a PDF takeoff,
        a rate list, anyone's own notes), pasted or uploaded. Treated as
        plain text from here on — never parsed into a specific schema (the
        other tool's own shape is trusted, not reinterpreted), never sent
        anywhere as an image. `self.q` is set to a small, clearly-marked
        dict only so the rest of this dialog (has_cad, the pending-run
        wait) sees that SOMETHING measured is now available, same as it
        would once a real drawing finishes measuring.

        Replaces whatever a real drawing measured before, rather than
        merging with it — two measurement sources feeding the same prompt
        at once is exactly the kind of silent ambiguity this whole add-on
        refuses to allow elsewhere; only one is ever the active one, and
        the other's panel is hidden so the screen never claims both.

        Also decides `self._hvac` the same way `_measure()` does — item 26
        (26 Oct 2026) moved this from guessing at the ask box's own typed
        words to the explicit Industry dropdown, so it must be read here
        too, regardless of which path the measurements came in by; this
        path must not quietly skip that check just because no drawing was
        ever measured here."""
        self._industry = self.industry_combo.currentText()
        self._hvac = self._industry == industries.HVAC
        self.q = {"external": True, "text": text}
        if self.mode == "boq" and self._input_kind:
            self._pipe_tool_done()
        self.summary = text
        self.cad_path = ""
        self.recheck_btn.setEnabled(False)
        self.meas_box.setVisible(False)
        self.ext_meas_view.setPlainText(text)
        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        self.csv_path = os.path.join(
            CB.config.RUNS_DIR, f"boq_external_measurements_{int(time.time())}.txt")
        with open(self.csv_path, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            task_label = getattr(self, "_task_name", "") or f"{self._doc} — {getattr(self, 'request', '')}"
            CB.config.save_artifact(self.csv_path, "external_measurements.txt",
                                    kind="boq", task=task_label)
        except Exception:                               # noqa: BLE001
            pass
        self.ext_meas_label.setText(i18n.t(
            "Saved so you can check it later → {path}").format(path=self.csv_path))
        self.ext_meas_box.setVisible(True)
        self._refresh_primary()
        if self._run_pending:
            self._run_pending = False
            self._run()

    # ── measuring ───────────────────────────────────────────────────────

    def _measure(self):
        if not self.cad_path or not os.path.exists(self.cad_path):
            return
        converter_setup.apply_saved(self.cfg)
        self.progress.set_stage(0)
        self._pipe("read", route.RUNNING, i18n.t("Reading {name} on this computer…").format(
            name=os.path.basename(self.cad_path)))
        self._set_busy(True, f"Reading {os.path.basename(self.cad_path)} — "
                             "a large drawing can take a minute…")
        # HVAC_DRAWING_RULES.md's rules only ever apply when the person has
        # explicitly picked HVAC from the Industry dropdown — the owner's
        # own instruction (22 Oct 2026, widened 26 Oct 2026, item 26):
        # trade-specific rules must not quietly start reading an
        # electrical or plumbing drawing's lines differently too, just
        # because the geometry happens to look similar, and (now that BOQ
        # targets several industries) must never be guessed from the
        # request's own typed words either — only this explicit choice.
        self._industry = self.industry_combo.currentText()
        hvac = self._industry == industries.HVAC
        # Remembered, not re-read at write time: the write-up prompt's own
        # per-industry guidance (below) must match whatever this
        # measurement actually used -- telling the writer "use the real
        # duct sizes" when the measurement never looked for any would be
        # noise, and the ask box's text could change between measuring
        # and writing.
        self._hvac = hvac
        self._measure_worker = MeasureWorker(
            self.cad_path, self.unit_edit.text().strip(),
            [s.strip() for s in self.scope_edit.text().split(",") if s.strip()],
            hvac=hvac)
        self._measure_worker.done.connect(self._on_measured)
        self._measure_worker.failed.connect(self._on_measure_failed)
        self._measure_worker.start()

    def _on_measured(self, q, notes: list):
        self.q = q
        self.summary = self.boq.summary_text(q)
        self._pipe_measured(q)
        self.meas_table.set_quantities(q)
        self.meas_box.setVisible(True)
        self.ext_meas_box.setVisible(False)   # only one measurement source is ever active
        if self.mode == "boq":
            # Data is ready now, but the box itself stays hidden until a
            # BOQ actually exists (see _on_written) -- the owner's report:
            # it sat there, visible and inert, before "Make my BOQ" was
            # even pressed, which read as a static, useless section
            # rather than a deliberate next step once there was something
            # to price.
            self.price_table.set_quantities(
                q, title=f"Bill of Quantities — {getattr(self, 'request', '') or 'measured drawing'}")

        os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
        self.csv_path = os.path.join(
            CB.config.RUNS_DIR, f"boq_quantities_{int(time.time())}.csv")
        self.boq.write_quantities_csv(q, self.csv_path)
        # A real, usable file — the numbers a customer or estimator would
        # want to keep even if they never open the formatted deck. RUNS_DIR
        # is a hidden working folder; Artifacts is where a copy survives.
        # `task` matches the query _write() below gives the "format" stage,
        # so the quantities CSV and the written-up deck land in the same
        # Artifacts subfolder rather than two differently-named ones.
        try:
            task_label = getattr(self, "_task_name", "") or f"{self._doc} — {self.request}"
            CB.config.save_artifact(
                self.csv_path, os.path.basename(self.cad_path), kind="boq",
                task=task_label)
        except Exception:                               # noqa: BLE001
            pass
        # `notes` is the CONVERTER's own notes (MeasureWorker.done's second
        # value, e.g. a DWG repair) — a different list from q["notes"]
        # (measurement-level findings, e.g. HVAC_DRAWING_RULES.md rule 1's
        # "read N pairs as one run"). Both belong here: this line is the
        # one place a person actually sees what Prism did to a number
        # before trusting it.
        note = "  ".join(list(notes) + list(q.get("notes") or []))
        self.csv_label.setText(
            f"Saved so you can check every number → {self.csv_path}"
            + (f"\n⚠ {note}" if note else ""))
        # "Make with drawing" needs nothing but the drawing itself -- it no
        # longer waits for "Make my BOQ" to be pressed first.
        self.recheck_btn.setEnabled(bool(self.cad_path))
        self._set_busy(False, _MEASURED_MSG)
        self._refresh_primary()
        # If the user already pressed "Make my BOQ" while this was measuring,
        # start it now — with the measured quantities it was waiting for.
        if self._run_pending:
            self._run_pending = False
            self._run()

    def _on_measure_failed(self, error: str):
        self._set_busy(False, "")
        self._pipe("read", route.FAILED, i18n.t(
            "Could not read the drawing: {why}").format(why=str(error).strip()[:200]))
        # Don't auto-start a deferred run on a failed measure — the user should
        # see the error and decide (they can still run a derived/spec BOQ).
        self._run_pending = False
        if converter_setup.is_missing_message(error):
            self._offer_converter()
            return
        self._show_fix(error, "Choose another drawing", self.ask._pick_file, text=i18n.t(
            "Prism could not read this drawing ({why}). Choose another file, or save it as a "
            "DXF from your drawing program and add that.").format(why=str(error).strip()[:140].rstrip(".")))

    def _offer_converter(self):
        """No DWG converter on this computer: the install / choose / DXF window."""
        outcome = converter_dialog.ask_for_converter(self, self.cfg)
        if outcome == "ready":
            self._measure()
        elif outcome == "dxf":
            self.status.setText(i18n.t(
                "In your drawing program, save the drawing as a DXF file, then press "
                "\"Change drawing\" and pick that file."))

    # ── voice ───────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self._rec:
            self._rec.stop()
            self.ask.set_recording(False)
            return
        problem = deps.voice_problem(self.cfg)
        if problem:
            QMessageBox.information(self, "Speak", problem)
            return
        self.ask.set_recording(True)
        self.status.setText("Listening — press Stop when you're done.")
        self._rec = RecordWorker(self.cfg)
        self._rec.done.connect(self._on_spoken)
        self._rec.failed.connect(self._on_spoken_failed)
        self._rec.start()

    def _on_spoken(self, text: str, lang: str):
        self._rec = None
        self.ask.set_recording(False)
        self.status.setText("")
        if text:
            self.ask.append_text(text)

    def _on_spoken_failed(self, error: str):
        self._rec = None
        self.ask.set_recording(False)
        self.status.setText("")
        QMessageBox.information(self, "Speak", error)

    # ── the run ─────────────────────────────────────────────────────────

    def _run(self):
        request = self.ask.text()
        if not request and not self.q:
            QMessageBox.information(
                self, "BOQ",
                f"Tell me what the {self._noun} is for — or attach a drawing.")
            return

        # A drawing is attached but still being measured: wait for it. The
        # measured quantities now feed EVERY stage's prompt (research, interpret
        # and format), so starting before they land would quietly produce a BOQ
        # blind to the drawing. Re-enters _run automatically from _on_measured.
        worker = getattr(self, "_measure_worker", None)
        if self.cad_path and self.q is None and worker is not None and worker.isRunning():
            self._run_pending = True
            self.progress.set_stage(0)
            self._set_busy(True, "Finishing measuring the drawing — your BOQ "
                                 "starts the moment it's done…")
            return

        # item 71 (12 Nov 2026), found live: a real run pressed "Make my
        # BOQ" on a PDF with no vector geometry (self.q stays None forever
        # for one of these -- only a .dwg/.dxf ever auto-measures). "Make
        # my BOQ"/_write() never shows the AI the file itself, by design,
        # the same rule Gerber and STEP keep -- it only ever shows measured
        # text, and there was none. Nothing stopped the run; the AI filled
        # the gap with a plausible-sounding, completely fabricated generic
        # design, built off the one-line typed request alone, with no
        # resemblance to the real file at all. The pdf_drawing_hint label
        # already said "press Make with drawing" at attach time, but a
        # passive hint a person has long since scrolled past is not a
        # stop -- this is. Any cad_path that reached _run() with no
        # measurement (a PDF/scan, or a DWG/DXF whose measurement came
        # back empty) means the same thing: there is nothing for "Make my
        # BOQ" to work from, so it must not run blind.
        if self.cad_path and self.q is None:
            self._show_fix("", "Make with the drawing", self._ask_recheck, text=i18n.t(
                "{name} is a PDF or picture, so there is nothing to measure automatically. "
                "Make the {noun} with the drawing instead: Prism AI reads it, after you say yes.")
                .format(name=os.path.basename(self.cad_path), noun=self._noun))
            return

        if self.mode == "boq" and not self._input_kind and not self.cad_path and self.q is None:
            self._set_input(route.DESCRIBE)       # typed words and nothing else
        if self.q is None:
            # Nothing measured (a description alone): the trade still comes from the
            # explicit choice, so its write-up rules apply.
            self._industry = self.industry_combo.currentText()
            self._hvac = self._industry == industries.HVAC

        # The agent pickers are the source of truth now. This also removes
        # the old "no writing agent set up yet" dead end — the picker
        # always offers the registry's tools.
        self.writer_agent = self.writer_combo.currentText().strip()
        if not self.writer_agent:
            QMessageBox.warning(self, "BOQ",
                                "Pick an AI to write the BOQ (the 'Write with' box).")
            return
        # item 30a: "No research" is a real choice in the dropdown, not a
        # blank one — mapped to "" here so the existing
        # `if self.derive_cb.isChecked() and self.researcher:` guard below
        # already skips the standards-research stage for it, same as it
        # always has for an empty researcher.
        researcher = self.research_combo.currentText().strip()
        self.researcher = "" if researcher == boq_agents.NO_RESEARCH else researcher
        # ChatGPT specifically, and only when there is something it can read.
        # It is the stage that turns a screenshot of the sheet plus a sample
        # BOQ into the legend, scope and house style the writer then follows.
        # Matches cmd_boq in prism_terminal/prism.py — the pipelines have to
        # agree, or the same drawing produces two different documents.
        self.interpreter = "ChatGPT" if self.images else None
        self.request = request or f"Produce a {self._doc} from the attached drawing."
        self._task_name = f"{self._doc} — {self.request}"
        self._artifacts_dir = CB.config.begin_run(self._task_name, title=self._task_name)

        # Start the clock for this run's timing report.
        self._t0 = time.time()
        self._last_t = self._t0
        self._stage_log = []

        if self.derive_cb.isChecked() and self.researcher:
            prompt = self._pm.standards_prompt(
                self.request, project_context=self.request,
                measured_text=self.summary)
            self._run_stage("standards", self.researcher, prompt, [],
                            self._on_standards)
        else:
            self._interpret()

    def _lap(self, stage: str):
        """Record how long the stage that just finished took, and restart the
        clock for the next one."""
        now = time.time()
        self._stage_log.append((stage, now - (self._last_t or now)))
        self._last_t = now

    # Human labels for the stage keys, in the order a person reads the run.
    _STAGE_LABELS = {"standards": "research", "interpret": "read drawing",
                     "format": "write"}

    def _timing_text(self) -> str:
        """"2m 34s  ·  research 1m 02s · read drawing 45s · write 47s" — the
        total this run took and where it went. Empty if the run wasn't timed."""
        if not self._t0:
            return ""
        total = short_duration(time.time() - self._t0)
        parts = [f"{self._STAGE_LABELS.get(s, s)} {short_duration(d)}"
                 for s, d in self._stage_log]
        return total + (f"  ·  {' · '.join(parts)}" if parts else "")

    def _on_standards(self, responses: dict, links: dict):
        got = [t for t in (responses.get("standards") or []) if t.strip()]
        self._standards = got[0] if got else ""
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["standards"] = self.researcher
        self._lap("standards")
        self._interpret()

    def _interpret(self):
        """Read the screenshot and the sample BOQ for legend, scope and style.

        A separate automation.run from the others because each stage needs a
        DIFFERENT file set — and this one must never receive the .dwg.
        ChatGPT cannot parse a binary CAD file; handing it one is what made
        this stage return nothing in the CLI, leaving the writer following a
        brief that did not exist.
        """
        if not self.interpreter:
            self._write()
            return
        prompt = self.boq.interpretation_prompt(
            self.request, self.summary,
            self.boq.roles_text([], self.templates, self.images, self.notes),
            legend_hint=self.legend_edit.text().strip())
        # Images, sample and notes only — deliberately not the drawing.
        files = list(self.images) + list(self.templates) + list(self.notes)
        self._run_stage("interpret", self.interpreter, prompt, files,
                        self._on_interpreted)

    def _on_interpreted(self, responses: dict, links: dict):
        got = [t for t in (responses.get("interpret") or []) if t.strip()]
        self._brief = got[0] if got else ""
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["interpret"] = self.interpreter
        self._lap("interpret")
        self._write()

    # ── the file-format picker ──────────────────────────────────────────
    _FORMAT_PHRASE = {
        "docx": "a downloadable Word (.docx) file",
        "xlsx": "a downloadable Excel (.xlsx) file",
        "csv": "a downloadable CSV file",
        "pdf": "a downloadable PDF file",
    }

    def _wanted_format(self) -> str:
        """"" (let the tool decide), or "docx"/"csv"/"pdf" from the picker."""
        return self.format_combo.currentData() or ""

    def _format_request_line(self, free_text: str = "") -> str:
        """One line asking for the chosen format, appended to a prompt — or
        "" when the picker is left on "Let the tool decide", which changes
        nothing about today's prompt.

        Also "" when `free_text` (the person's own typed ask or follow-up
        note) already names a format or asks for a download in their own
        words — `prism_terminal/core/contract.py`'s own engine-side system
        scans the WHOLE prompt (this line included) for exactly that and
        asks the tool for whatever it finds there first. Appending the
        picker's choice on top, when it disagrees with what the person
        just typed, puts two different format requests in one message —
        the picker left on a stale choice from an earlier run while a
        follow-up note asked for a different one was a real, reproduced
        bug (2026-10-24), not a hypothetical. Deferring to the person's
        own words here means there is only ever one request in the
        prompt, and it is always the one that matches what they typed."""
        if free_text and CB.contract.wants_file(free_text):
            return ""
        fmt = self._wanted_format()
        if not fmt:
            return ""
        line = ("\n\nGive me the result as " + self._FORMAT_PHRASE[fmt]
               + ", built here rather than only pasted into the chat.")
        # item 52 (4 Nov 2026): a Prism Agent (OpenRouter) answer has no
        # file-export feature of its own -- openrouter_writer.py builds the
        # actual file from this text, in code (see item 30's own module
        # docstring). A browser-driven agent (plain "Claude", "ChatGPT"...)
        # already has its own native xlsx export and needs none of this --
        # the owner's own claude.ai-made LN2 rack workbook (3 linked
        # sheets, live formulas) was made exactly that way, outside Prism
        # entirely, with no special prompting at all. This is scoped to
        # the ONE path that has no such capability of its own.
        if fmt == "xlsx" and self.writer_combo.currentText().strip() in boq_agents.PRISM_AGENTS:
            line += (
                "\n\nMAKE IT A LIVE WORKBOOK, not just a table of finished "
                "numbers. First, under its own '## INPUTS' heading, give one "
                "markdown table of every design parameter you used anywhere "
                "below (every dimension, density, wastage/scrap allowance, "
                "unit weight, count) -- columns exactly 'Name | Value | Unit "
                "| Note', one short lowercase_with_underscores Name per row "
                "(e.g. frame_length_ft), no two rows sharing a Name. Then, in "
                "the BOQ table(s) below it, write every Qty/Length/Area/"
                "Weight cell that is CALCULATED from one or more of those "
                "inputs as a formula instead of a plain number -- start the "
                "cell with '=' and refer to an input by its Name in curly "
                "braces, e.g. '={frame_length_ft}*2+{wastage_mm}/304.8' -- "
                "ordinary arithmetic (+ - * /), nothing else. Only use a "
                "Name that is actually a row in the INPUTS table above. A "
                "quantity that is NOT calculated from an input (a fixed "
                "catalogue count, e.g. '8 casters') stays a plain number. "
                "This is what lets a reader change one input and have the "
                "whole workbook recalculate, instead of a static snapshot.")
            # item 60 (4 Nov 2026): the owner compared a Prism BOQ against
            # a REAL estimator's own BOM for the same job and asked for
            # that same depth -- separate finished-size and cut-size
            # columns (so a reader can see exactly what the scrap
            # allowance added, not a single number that already has it
            # folded in), per-piece AND total weight as two columns, and
            # a raw-material procurement summary a buyer could actually
            # place an order from. The one-column-per-measure rule here is
            # also item 58's own fix, stated at the SOURCE: a real run put
            # an area-in-m² row directly above a weight-in-kg row in one
            # column headed "Qty/Length/Area/Weight", and summing it
            # (555.78) meant nothing. Asking for this up front should mean
            # fewer answers ever reach that shape at all.
            line += (
                "\n\nGIVE EACH FABRICATED BOM LINE THIS MUCH DETAIL, the way "
                "a real estimator's own bill of material does: separate "
                "'Finished L/W (mm)' columns (the as-designed, net size) from "
                "'Cut L/W (mm)' columns (finished size plus the wastage/scrap "
                "allowance -- what is actually ordered and cut), and separate "
                "'Wt/Pc (kg)' from 'Total Wt (kg)' (per-piece weight times "
                "quantity). NEVER give one column a header naming more than "
                "one kind of quantity (e.g. never 'Qty/Length/Area/Weight') -- "
                "split every distinct measure into its own column, always, "
                "even when that makes the table wider. "
                # item 69 (12 Nov 2026), found live on a real 40-off locker
                # job: with an order quantity above 1, "Total Wt" alone is
                # ambiguous between "this part's own weight for the ONE
                # unit it belongs to" and "this part's weight across the
                # WHOLE order" -- a real run picked the whole-order meaning
                # and never showed the one-unit figure at all, so getting
                # it back meant multiplying two separated columns (Wt/Pc
                # and Qty) by hand. Split it into two named columns instead
                # whenever this applies, so neither figure is ever a mental
                # multiplication away.
                "If the order itself is for more than one unit (a quantity "
                "above 1 is stated anywhere), split 'Total Wt' into two "
                "columns rather than one: 'Total Wt per unit (kg)' (that "
                "part's own quantity-per-unit times Wt/Pc) and 'Total Wt, "
                "all units (kg)' (that figure times the number of units "
                "ordered). A reader should never have to multiply two "
                "separated columns themselves to reach either number. "
                "Finish with its own "
                "'## RAW MATERIAL REQUIREMENT' section: one row per distinct "
                "raw material (e.g. 'SS304 sheet 1.5 mm', 'SS304 square pipe "
                "38.1 mm'), each with its net weight (sum of that material's "
                "own BOM lines, before wastage) and gross weight (with the "
                "wastage/scrap allowance applied) -- the actual figure a "
                "buyer would place a purchase order against, grouped by "
                "material rather than scattered across the line items above.")
        return line

    def _save_deliverable(self, made_files: list, stage: str):
        """A real file the engine harvested off the page for `stage` (or
        wrote itself from the tool's own text, when the tool wouldn't) —
        copy it into this run's own Artifacts folder and remember it as the
        thing to show next, the same way addons/step/dialog.py's
        _on_drafted copies its own harvested sheet. `made_files` is a
        AutomationWorker(files_out=...) list: [{"path": ..., "name": ...,
        "kind": ...}, ...], newest-ish last; empty when nothing was ever
        made for this stage (the common case for "format" and "followup",
        a correct plain text answer, not a bug)."""
        task = getattr(self, "_task_name", "") or self._doc
        for rec in reversed(made_files):
            src = rec.get("path", "") if isinstance(rec, dict) else str(rec)
            if not src or not os.path.exists(src):
                continue
            try:
                saved = CB.config.save_artifact(
                    src, task, kind=stage, task=task,
                    name=rec.get("name") or rec.get("_site_name") or "")
            except Exception:                                   # noqa: BLE001
                continue
            self._deliverable_path = saved
            return

    def _industry_record(self) -> dict:
        """What was chosen, for the saved record: a built-in, Other, or the user's own."""
        return CI.describe(self._custom, CI.OTHER if self._other else self._industry)

    def _write(self):
        # Reset up front, not only once the AutomationWorker starts — a
        # failed/skipped earlier run must not leave _on_written looking at a
        # PREVIOUS run's harvested files and saving a stale one as if this
        # run had just made it.
        self._write_made_files = []
        # Known only now, not at submit time: pricing can be filled in after
        # the first measurement, so whether there is a priced CSV to hand
        # the writer is only certain once we're actually about to write.
        reference = self._reference_csv()
        self._note_credits_before()
        self.progress.set_stage(2)
        self._pipe("write", route.RUNNING, i18n.t(
            "Prism AI is writing your BOQ from the figures. Only the numbers are sent."))
        self._set_busy(True, f"{self.writer_agent} is writing your BOQ…")
        prompt = self._pm.formatting_prompt(
            self.summary, project_context=self.request,
            has_template=bool(self.templates),
            legend=self.legend_edit.text().strip(),
            scoped=bool(self.scope_edit.text().strip()),
            # Threaded through explicitly rather than relying on the browser
            # relay to carry it between stages — the CLI learned that the hard
            # way, with an empty handoff and then a garbled one.
            brief_text=self._brief,
            standards_text=self._standards,
            allow_derived=self.derive_cb.isChecked() or not self.q,
            has_cad=bool(self.q),
            # Per-industry write-up guidance (duplicate-layer judgement,
            # legend caution, the "don't borrow a type from elsewhere"
            # rule, HVAC's own worked derivation example) now comes from
            # addons/boq/industries.py -- the same app-side home every
            # other per-industry rule already lives in, not hardcoded
            # inside the engine's formatting_prompt() itself. Trade-
            # specific the same way the measurement rules are -- only
            # ever non-empty when this run's own measurement actually
            # used that industry, never guessed or applied to an
            # ELV/CCTV/cabling/plumbing/fire-hydrant BOQ by default.
            industry_note=industries.writeup_note(self._industry),
            derivation_example=industries.derivation_example(self._industry))

        # Templates and notes only. The drawing itself is never attached to
        # any AI stage -- the same rule Gerber and STEP keep. The writer is
        # handed the MEASURED figures (in the prompt) and nothing else about
        # the drawing; until 2026-09-10 the CAD file rode along here "so the
        # tool could check", which put the customer's drawing on a third
        # party's server for a formatting job that never needed it.
        if reference:
            prompt += (
                "\n\nREFERENCE ONLY: the attached CSV is the offline measured and "
                "priced take-off. Use it to lay out and check your figures. It is "
                "not the firm's record: do not recompute totals or change any "
                "quantity. Lines with a blank rate are unpriced.")

        prompt += self._format_request_line(self.request)
        # The user's own industry (if they chose one), as labelled DATA at the end.
        prompt += CI.prompt_block(self._custom)

        files = list(self.templates) + list(self.notes) + reference
        self._run_stage("format", self.writer_agent, prompt, files,
                        self._on_written, worker_kwargs={
            # The skill formatting_prompt was written against, so its
            # checker also reads the answer -- a parts row with no grade, a
            # 250 mm emergency stop. Only this stage: the standards and
            # interpret stages return checklists and notes, not the table.
            "stage_skills": {"format": [s.key for s in CB.skills.for_feature(
                f"{self.mode}.format")]},
            # "format" is already a `file`-kind step by default (see
            # core/contract.py's _BY_STAGE) — this just lets the dialog
            # actually SEE what the engine harvested or wrote out for it,
            # which nothing captured before (see _save_deliverable).
            "files_out": self._write_made_files,
        })

    def _reference_csv(self) -> list:
        """The priced grid as a CSV for the writer, or the measured quantities
        CSV when nothing is priced yet. Numbers only: the drawing never goes."""
        if self.mode == "boq" and self.price_table.boq() is not None:
            # A fresh install has no runs folder yet; the export does not
            # create it, so the first priced BOQ silently wrote nothing.
            os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
            path = os.path.join(CB.config.RUNS_DIR,
                                f"boq_priced_reference_{int(time.time())}.csv")
            self.price_table.export("csv", path)
            return [CB.files.attach(path)]
        if self.csv_path:
            return [CB.files.attach(self.csv_path)]
        return []

    def _show_result(self, text: str) -> None:
        """Render the writing AI's own markdown instead of showing it as
        literal asterisks and '>' marks (see the comment on self.result).
        Also keeps the RAW text in `self._raw_result` -- item 54 (4 Nov
        2026), found live comparing two real follow-up turns of the same
        job: the second answer's own notes said it had "corrected missing
        multiplication operators" in formula cells the first answer never
        actually had wrong. Traced to `self.result.toMarkdown()` itself --
        confirmed by round-tripping a table cell containing
        `=(...)*0.3048*2*0.092903*Inputs!$B$21` through a real QTextEdit:
        Qt's markdown EXPORT escapes an asterisk immediately before a
        letter as `\\*`, to stop it being read as italic markup on a later
        import -- harmless for ordinary prose, silently corrupts a live
        formula's own multiplication operator, which every "PREVIOUS
        ANSWER" section (_send_followup, a few calls down) used to read
        straight out of this round-trip. The AI then "fixed" an operator
        that was never missing in its own first answer, because the copy
        it was shown already had it mangled by the inbetween render."""
        self.result.setMarkdown(text)
        result_view.style_document(self.result.document())   # looks only, text unchanged
        self._raw_result = text
        self.fill_template_btn.setEnabled(True)
        # The document lands on the "make it" step, wherever it was asked for.
        if self._step < self.S_MAKE:
            self._show_step(self.S_MAKE)
        else:
            self._refresh_primary()

    def _fill_template(self):
        """item 66: open a copy of the CLIENT'S OWN BOQ template -- their
        logo, letterhead, column widths, everything already in that file
        -- and fill its line-item tables with this run's own result, in
        place. Never the drawing (same rule every AI stage in this dialog
        already keeps) and never an AI call at all: the column match is
        deterministic (openrouter_writer._map_columns), so there is
        nothing here that needs a key or a network round-trip."""
        text = getattr(self, "_raw_result", "").strip()
        if not text:
            QMessageBox.information(self, "BOQ", i18n.t(
                "Make the {noun} first — there is nothing yet to fill a "
                "template with.").replace("{noun}", self._noun))
            return
        template_path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Pick the client's own BOQ template"), "",
            "Word documents (*.docx)")
        if not template_path:
            return
        try:
            os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
            out_path = os.path.join(
                CB.config.RUNS_DIR, f"boq_filled_{int(time.time())}.docx")
            report = openrouter_writer.fill_template_docx(
                text, template_path, out_path)
        except Exception as e:                                   # noqa: BLE001
            QMessageBox.warning(self, "BOQ", i18n.t(
                "Could not fill that template: {error}").replace(
                    "{error}", str(e)))
            return
        task = getattr(self, "_task_name", "") or self._doc
        saved = CB.config.save_artifact(
            report["path"], task, kind="template_fill", task=task,
            name=os.path.basename(template_path))
        self._deliverable_path = saved or report["path"]
        lines = [i18n.t("Filled {n} section(s) into the template.").replace(
            "{n}", str(report["matched"]))]
        if report["unmatched_template"]:
            lines.append(i18n.t(
                "{n} table(s) in the template found no matching section "
                "and were left untouched.").replace(
                    "{n}", str(report["unmatched_template"])))
        if report["unmatched_drafted"]:
            lines.append(i18n.t(
                "No matching place in the template for: {list} — "
                "appended at the end instead.").replace(
                    "{list}", ", ".join(report["unmatched_drafted"])))
        QMessageBox.information(self, "BOQ",
                               "\n".join(lines) + f"\n\n{self._deliverable_path}")

    def _on_written(self, responses: dict, links: dict):
        self._set_busy(False, "")
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map["format"] = self.writer_agent
        # Who to resume, and where -- see _fu_start_next.
        self._last_agent = self.writer_agent
        self._last_link = links.get("format") or self._last_link
        self._lap("format")
        # How long the whole BOQ took, and where the time went — the stages are
        # web round-trips of tens of seconds each, so "why did that take three
        # minutes" is answered here rather than left a mystery.
        timing = self._timing_text()
        texts = [t for t in (responses.get("format") or []) if t.strip()]
        if not texts:
            self.status.setText("Nothing came back. The measured numbers above "
                                "are still saved." + (f"  ({timing})" if timing else ""))
        else:
            self._show_result(texts[0])
            self.status.setText(
                (f"Done in {timing}. " if timing else "Done. ")
                + "Check the numbers against the saved file above.")
        self._save_deliverable(self._write_made_files, "format")
        self._pipe_written(bool(texts))
        self.open_btn.setEnabled(bool(self._links.get("format")))
        self._refresh_primary()
        self.recheck_btn.setEnabled(bool(self.cad_path))
        # "Price it" becomes available once there is a BOQ to price, not
        # before — the box's data has been ready since _on_measured, only
        # its visibility was moved here.
        if self.mode == "boq" and texts:
            self.price_box.setVisible(True)
            self._refresh_primary()
        task_label = getattr(self, "_task_name", "") or f"{self._noun} — {self.request}"
        # item 30d: "addon" is what lets History's own list (addons/boq/
        # history.py) find BOQ's runs without guessing from the title
        # text; "request"/"last_text"/"deliverable_path" are what a
        # resumed job actually needs to carry a follow-up forward with --
        # the SAME fields _on_followed_up below updates in place via
        # `path=`, so reopening this exact job later always reads the
        # latest turn, not just the first one.
        self._boq_run_path = CB.config.save_run({
            "addon": "boq", "query": task_label, "request": getattr(self, "request", ""),
            "responses": responses, "links": self._links,
            "last_text": texts[0] if texts else "",
            "artifacts": getattr(self, "_artifacts_dir", "") or CB.config.current_run_dir(),
            "deliverable_path": getattr(self, "_deliverable_path", ""),
            "boq": {"quantities_csv": self.csv_path, "source": self.cad_path},
            "industry": self._industry_record(),
            "tokens": dict(self._tokens_used),
        })
        if texts:
            self._offer_followup()

    def _pipe_written(self, ok: bool):
        if not ok:
            self._pipe("write", route.FAILED, i18n.t("Nothing came back. Your measured numbers are still saved."))
            return
        spent = self._charge_text()
        cost = i18n.t(" It used {n}.").format(n=spent) if spent else ""
        self._pipe("write", route.DONE, i18n.t("Written by Prism AI.{cost}").format(cost=cost))
        self._pipe("drawing", route.DONE, i18n.t("Prism AI read the drawing and wrote the BOQ.{cost}").format(cost=cost))
        if self._input_kind == route.DESCRIBE:
            self._pipe("check", route.NEEDS_YOU, i18n.t(
                "Nothing was measured. Read every line: the quantities are estimates."))
        files = [f for f in (self._deliverable_path,) if f]
        self._pipe("files", route.DONE if files else route.WAITING,
                   i18n.t("Saved: {name}").format(name=os.path.basename(files[0])) if files
                   else i18n.t("The text is above. Pick a file format in More options to get a file."))
        self._pipe("prices", route.NEEDS_YOU, i18n.t("Optional. Add your rates in step 4."))

    def _on_failed(self, error: str):
        self._pipe("write", route.FAILED, i18n.t("Writing did not work: {why}").format(
            why=str(error).strip()[:200]))
        self._set_busy(False, "")
        self._show_fix(error, "Try again", self._retry_write)

    def _retry_write(self):
        self._show_step(self.S_MAKE)
        if self._have_a_result():
            return
        if self._with_drawing and self.cad_path:
            self._ask_recheck()
        else:
            self._run()

    def _set_busy(self, busy: bool, message: str):
        if not busy and getattr(self, "_sending", None) is not None:
            send_to_ai.hide_panel(self._sending)
            self._sending = None
        if busy:
            self._clear_fix()
            self.progress.set_message(message)
        self.progress.setVisible(busy)
        self.recheck_btn.setEnabled(not busy and bool(self.cad_path))
        self.status.setText("" if busy else message)   # the loader carries it while busy
        self._refresh_primary()

    def _drawing_consent(self) -> bool:
        """The drawing leaves this computer only after the shared 'Send to Prism AI?'
        yes (asked once, "Don't ask again" remembered). Shows the sending card."""
        if not send_to_ai.ask_consent(self, self.cfg, self.cad_path, what=i18n.t("drawing")):
            return False
        send_to_ai.hide_panel(getattr(self, "_sending", None))
        self._sending = send_to_ai.show_panel(self, self.cad_path)
        return True

    def _ask_recheck(self):
        if not self._drawing_consent():
            return
        self._note_credits_before()
        # No BOQ made yet -- "Make with drawing" is the FIRST thing this
        # session does, not a recheck of something already written, so
        # there is no previous answer to remake. VERIFY_PROMPT's own
        # wording ("remake... in the same format as the previous answer...
        # list what changed") only makes sense once one exists. Reads
        # _raw_result, not self.result.toMarkdown() -- item 54's own
        # round-trip corruption risk applies here too, even though this
        # call site only checks for emptiness rather than embedding the
        # text: a one-character difference between "empty" and "not" is
        # exactly the kind of thing that round-trip could tip either way.
        if getattr(self, "_raw_result", "").strip():
            note = VERIFY_PROMPT
        elif self.summary.strip():
            note = MAKE_WITH_DRAWING_PROMPT
        else:
            # item 38: a PDF drawing with no deterministic measurement at
            # all (self.summary never got set -- see _absorb()'s non-.dwg/
            # .dxf branch) -- MAKE_WITH_DRAWING_PROMPT's "cross-check
            # against the measured figures below" would point at nothing.
            note = MAKE_WITH_DRAWING_NO_MEASUREMENT_PROMPT
        self._send_followup(note, [CB.files.attach(self.cad_path)], verify=True)

    def _send_followup(self, note: str, extra_files: list, verify: bool):
        agent = self.writer_combo.currentText().strip() or "the writing AI"
        stage = "recheck" if verify else "followup"
        # item 48 (3 Nov 2026), found live: a real BOQ .docx landed inside
        # an UNRELATED earlier session's artifacts folder ("Create an
        # Instagram post for Dhanteras"). Root cause, traced through
        # core/config.py: self._task_name / self._artifacts_dir are only
        # ever set inside _run() ("Make my BOQ", see its own
        # CB.config.begin_run() call) -- "Make with drawing" pressed as
        # the FIRST action in a session (item 38's own real workflow)
        # never calls it, so _save_deliverable()'s `task` argument falls
        # back to the bare, generic self._doc ("Bill of Quantities"). That
        # alone would still be safe -- config.artifact_task_dir() opens a
        # fresh folder when `task` doesn't match the module-level `_run`
        # state's own task -- except `_run["continued"]` is a GLOBAL,
        # process-wide flag, not scoped per add-on or session: once ANY
        # earlier add-on's own follow-up left it True, artifact_task_dir's
        # own check (`_run.get("continued") or _run.get("task") == task`)
        # is satisfied regardless of whether `task` matches, and it keeps
        # returning whatever folder was last active -- another add-on's,
        # from however long ago. The same fix as items 45/47: establish
        # the real per-job context _run() would have, the first time this
        # function is reached without it, instead of silently falling
        # through to stale global state.
        if not getattr(self, "_task_name", ""):
            self._task_name = f"{self._doc} — {self.ask.text().strip()}"
            self._artifacts_dir = CB.config.begin_run(
                self._task_name, title=self._task_name)
        # Same reasoning as the "PREVIOUS ANSWER" section just below: a
        # PDF-only drawing (item 38) never has measured figures at all
        # (self.summary stays ""), and "MEASURED FIGURES:\n" with nothing
        # under it reads as a blank measurement rather than there being
        # none to give.
        prompt = note
        # item 45 (3 Nov 2026), found live: what the person actually typed
        # in "What do you need a BOQ for?" (material, extras like "add raw
        # material in Kg" or "add 100mm to length and breadth for scrap",
        # anything else that makes this job theirs) was never included
        # anywhere in this function. "Make with drawing" pressed as the
        # FIRST thing in a session (no measured figures, no previous answer
        # -- exactly the PDF-only case item 38 built this path for) sent
        # nothing but the bare boilerplate note: the person's own
        # requirements never reached the model at all.
        #
        # Read live from self.ask.text(), NOT self.request: self.request is
        # only ever set inside _run() ("Make my BOQ") or restored from
        # History -- pressing "Make with drawing" as the very first action
        # in a session (the real workflow this bug was found in) means it
        # does not exist as an attribute yet at all, which an earlier draft
        # of this fix would have turned into a crash on exactly the path it
        # was meant to repair. self.ask.text() is also simply more correct
        # even once self.request does exist: it is whatever is CURRENTLY in
        # the box, not whatever request._run() happened to freeze earlier --
        # if the person edited their ask after the first write-up and before
        # pressing "Verify and remake", the edit is what should apply.
        current_ask = self.ask.text().strip()
        if current_ask:
            prompt += f"\n\nTHE PERSON'S OWN REQUEST FOR THIS JOB:\n{current_ask}"
        # item 50 (4 Nov 2026), found live by comparing a real generated BOQ
        # against one the same job's PDF produced on claude.ai: the owner's
        # own request that run said "add 100mm in length and breadth for
        # scrap" -- words that read as a 2D, sheet-panel instruction ("length
        # and breadth" of a panel), and that is exactly how the model took
        # it: every sheet/plate line got +100mm on both edges, but every
        # tube, flat-bar and rod CUT LENGTH was left at its bare spec figure,
        # with the model's own notes saying so plainly ("Tubes use cut
        # lengths from stated dimensions; no tube scrap allowance is
        # specified"). The claude.ai answer, asked nothing more than the
        # same PDF plus the same instruction, applied the allowance to every
        # cut piece, tube and rod included -- a difference in how an
        # ambiguous instruction was read, not a calculation error on either
        # side (every other figure checked out, line by line). Said once,
        # plainly, whenever the person's own words raise it at all, instead
        # of leaving the scope of "scrap"/"wastage" to the model's own guess.
        if current_ask and re.search(
                r"\bscrap\b|\bwastage\b|\bwaste\b", current_ask, re.I):
            prompt += (
                "\n\nSCRAP/WASTAGE ALLOWANCE. The person's own request above "
                "asks for a cutting allowance. Apply it to EVERY raw-material "
                "cut piece, not sheet panels alone: the cut length of every "
                "tube, pipe, flat bar and rod section, AND the length and "
                "width of every sheet/plate panel. Show both figures on each "
                "line -- the net (as-designed) figure and the gross (with "
                "the allowance added) figure -- so the two can be told apart, "
                "and state the allowance you used once, plainly, near the "
                "top.")
        # item 47 (3 Nov 2026): core.boq.formatting_prompt()'s own
        # has_template branch tells the writer, explicitly, to match a
        # sample's format/conventions but never copy ITS rows or
        # quantities -- every number must trace back to THIS job's own
        # data. That instruction lives only in formatting_prompt(), called
        # only from _write() ("Make my BOQ"). This function never called
        # it, so "Make with drawing" -- a PDF-only drawing's only path to
        # a BOQ at all, item 38 -- sent a template with no guidance either
        # way on its own numbers. Found asking whether a reference BOQ
        # that happened to already contain this exact product's own prior
        # weight figure could leak into the answer: nothing in the prompt
        # said it shouldn't. The model derived its own number anyway that
        # time -- its own judgement, not something this path enforced.
        if self.templates:
            prompt += (
                "\n\nA SAMPLE/REFERENCE DOCUMENT IS ALSO ATTACHED. Match its "
                "format and conventions -- sections, column set, numbering, "
                "wording, units, boilerplate. Where it makes a design "
                "decision for a comparable item (a spacing, an allowance, a "
                "material spec), you may use the same one and say the "
                "sample is the basis. Do NOT copy its own rows, quantities "
                "or weights, even if an item in it looks like the same "
                "product -- every number in your answer must come from your "
                "own reading of the file above, not from the sample.")
        if self.summary.strip():
            prompt += f"\n\nMEASURED FIGURES:\n{self.summary}"
        # Only when there IS one -- "Make with drawing" pressed before any
        # BOQ exists has nothing previous to show, and an empty section
        # ("PREVIOUS ANSWER:\n\n") would read as a previous answer that
        # happens to be blank rather than there being none at all.
        #
        # item 54 (4 Nov 2026): this USED to read self.result.toMarkdown()
        # -- the live, on-screen QTextEdit re-serialised back to markdown.
        # Confirmed live that round-trip is lossy for a live-workbook
        # formula cell (item 52): Qt's markdown EXPORT escapes an asterisk
        # immediately before a letter as "\*", to stop it reading as
        # italic markup on a later import -- harmless for prose, but it
        # silently mangled a real multiplication operator inside a formula
        # cell (e.g. "...*0.092903*Inputs!$B$21" lost its last "*"), which
        # the model then "corrected" in its next answer, believing an
        # operator was missing that never actually was in its own first
        # one -- confirmed by round-tripping the exact cell text through a
        # real QTextEdit and finding the escape appear. _raw_result (see
        # _show_result) is the text exactly as the AI returned it, never
        # pushed through Qt's own markdown renderer at all.
        previous = getattr(self, "_raw_result", "").strip()
        if previous:
            prompt += f"\n\nPREVIOUS ANSWER:\n{previous}"
        files = list(extra_files) + list(self.templates) + list(self.notes)
        # The actual previous deliverable, attached alongside the pasted
        # text above rather than in place of it (the text stays — some
        # tools cannot read an attached .docx/.csv at all, so dropping it
        # would lose the previous answer for them). When the tool CAN read
        # it, handing it the real file to open and edit is a stronger
        # "remake this" than asking it to reconstruct the document from
        # its own pasted-text summary.
        if self._deliverable_path and os.path.exists(self._deliverable_path):
            try:
                files.append(CB.files.attach(self._deliverable_path))
            except OSError:
                pass
        prompt += self._format_request_line(note)
        self._start_followup_run(stage, agent, prompt, files)

    # ── the live run window: one StageCard, a fallback chain, Skip/Use
    # fallback/Stop wired to the real AutomationWorker — see
    # addons/boq/run_dialog.py's module docstring for exactly what each
    # control does and does not do, and why. _fu_* holds this one run's
    # state; one BoqRunDialog is kept for the whole BOQ session (see
    # self._fu_dialog's init) and restart() carries it into the next job,
    # the same way main_window.py's single OutputPanel carries the core
    # Run screen from stage to stage — a fresh window popping up for
    # "Verify and remake" after an ordinary follow-up read as a brand new,
    # disconnected run instead of a continuation of this one.
    def _start_followup_run(self, stage: str, agent: str, prompt: str,
                            files: list):
        # item 30b/30c/30e: same bypass as _run_stage, and this is the
        # path that uses the CHEAPER, same-family model tier — a
        # follow-up is an edit to something already written, not a fresh
        # generation.
        if agent in boq_agents.PRISM_AGENTS:
            # item 41 (2 Nov 2026): found live -- "Make with drawing" via a
            # Prism Agent crashed with AttributeError: no _followup_stage.
            # _on_followed_up (below) reads self._followup_stage, but that
            # was only ever set in _fu_start_next(), the BROWSER-agent half
            # of this same method, past the early return a Prism Agent
            # takes right here. _on_followed_up is shared by both paths;
            # this early-return branch owes it the same assignment
            # _fu_start_next makes for its own path.
            # Same gap, same reason: _on_followed_up also reads
            # self._followup_agent (_fu_start_next's own
            # self._followup_agent = tool), to label history/
            # _stage_agents_map with which agent actually answered.
            # Unset here it would be worse than the crash above once
            # fixed -- a later browser-agent follow-up's STALE value
            # silently mislabelling this one, not an error.
            self._followup_stage = stage
            self._followup_agent = agent
            self._run_prism_agent(stage, agent, prompt, files,
                                  self._on_followed_up, followup=True)
            return
        from addons.boq.run_dialog import BoqRunDialog
        self._fu_stage = stage
        self._fu_prompt = prompt
        self._fu_files = files
        self._fu_chain = [agent] + [a for a in boq_agents.FALLBACK_ORDER
                                    if a != agent]
        self._fu_stopped = False
        self._fu_skipped = False
        self._fu_token = 0
        # "recheck" covers two different moments now: "Make with drawing"
        # pressed before any BOQ exists (nothing to verify yet -- making
        # it) and the same button, or "Verify and remake", pressed once
        # one does. `prompt` already carries "PREVIOUS ANSWER:" only in
        # the second case (see _send_followup) -- cheaper and more
        # reliable than re-checking self.result here, which may no longer
        # match what this particular call was actually built from.
        making_from_scratch = stage == "recheck" and "PREVIOUS ANSWER:" not in prompt
        titles = {"recheck": (i18n.t("Making your BOQ from the drawing")
                              if making_from_scratch
                              else i18n.t("Verifying against the drawing")),
                 "followup": i18n.t("Carrying your follow-up on")}
        # Verify-and-remake reads the drawing itself, not just a chat reply
        # — the owner's own report is ~20 minutes for that, far past what a
        # plain follow-up takes, and the window used to give no hint of
        # that, reading as stuck rather than working.
        notes = {"recheck": i18n.t(
            "{agent} is reading the drawing itself, not just answering from "
            "memory — this can take up to 20 minutes.").replace("{agent}", agent)}
        title = titles[stage]
        note = notes.get(stage, "")
        self._active_runner = "fu"
        if self._fu_dialog is None:
            self._fu_dialog = BoqRunDialog(title, stage, agent, parent=self,
                                           note=note)
            self._fu_dialog.skip_requested.connect(self._rundlg_on_skip)
            self._fu_dialog.fallback_requested.connect(self._rundlg_on_fallback)
            self._fu_dialog.stop_requested.connect(self._rundlg_on_stop)
        else:
            self._fu_dialog.restart(title, stage, agent, note=note)
        self._fu_start_next()
        # show(), not exec(): a modal exec() enters its own event loop and
        # only returns once the window closes, so the SAME instance could
        # never be reused for a later job without first destroying it.
        # setModal(True) in __init__ already keeps this BOQ dialog from
        # being clicked underneath it.
        self._fu_dialog.show()
        self._fu_dialog.raise_()
        self._fu_dialog.activateWindow()

    def _fu_start_next(self):
        if not self._fu_chain:
            self._fu_dialog.finish_error(i18n.t(
                "None of the fallback tools could answer either. The "
                "previous answer is still shown."))
            self._set_busy(False, "")
            self.status.setText(i18n.t(
                "Nothing came back. The previous answer is still shown."))
            return
        tool = self._fu_chain.pop(0)
        self._fu_token += 1
        token = self._fu_token
        self._followup_agent = tool
        self._followup_stage = self._fu_stage
        self.progress.set_stage(2)
        self._set_busy(True, f"{tool} is working on your {self._noun}…")
        self._fu_dialog.set_agent(tool)
        self._fu_made_files: list = []
        # The real fix for "every follow-up opens a fresh tab": resume the
        # SAME chat this exact tool already answered in, keyed by THIS
        # call's own stage name (automation.py's _open_agent_page looks
        # resume_urls up by the stage it is about to run, not by whichever
        # stage the link was originally saved under) — never across a
        # fallback to a DIFFERENT tool, which has no chat of its own to
        # resume. addons/step/dialog.py's _on_answer_followup does the
        # identical check for the same reason.
        resume = ({self._fu_stage: self._last_link}
                 if tool == self._last_agent and self._last_link else None)
        self._worker = AutomationWorker(
            {}, self.cfg, self._fu_files,
            # The actual prompt, not a short task label — this is what the
            # engine's wants_file()/_requested_formats() scan to decide
            # whether this stage owes a FILE (core/contract.py), which is
            # the only way a chosen format or "make it a docx" in the
            # person's own words ever reaches that check. A plain task
            # label never mentioned either.
            self._fu_prompt,
            custom_stages=[(self._fu_stage, tool, [self._fu_prompt])],
            chatgpt_analysis=False,
            # Same wait ceiling and same-folder artifacts as any other
            # follow-up (automation.FOLLOWUP_MIN_WAIT); "recheck" alone
            # gets a much higher floor on top — see min_wait below.
            followup=True,
            min_wait=1200 if self._fu_stage == "recheck" else 0,
            # So _fu_on_done can learn what, if anything, got produced —
            # nothing surfaced this before (see _save_deliverable).
            files_out=self._fu_made_files,
            resume_urls=resume)
        self._worker.done.connect(
            lambda responses, links, t=token: self._fu_on_done(t, responses, links))
        self._worker.failed.connect(
            lambda error, t=token: self._fu_on_failed(t, error))
        self._worker.start()

    def _fu_on_done(self, token: int, responses: dict, links: dict):
        if token != self._fu_token:
            return      # a superseded attempt's late signal
        stage = self._fu_stage
        texts = responses.get(stage) or []
        self._save_deliverable(self._fu_made_files, stage)
        if self._fu_skipped:
            self._fu_dialog.finish_skipped()
        elif self._fu_stopped:
            self._fu_dialog.finish_cancelled()
        else:
            self._fu_dialog.finish_ok(texts, links.get(stage, ""))
        self._on_followed_up(responses, links)

    def _fu_on_failed(self, token: int, error: str):
        if token != self._fu_token or self._fu_stopped or self._fu_skipped:
            return
        if self._fu_chain:
            self._fu_dialog.finish_error(
                (i18n.t("{tool} could not answer ({error}) — trying the "
                       "next fallback tool…")
                 .replace("{tool}", self._followup_agent)
                 .replace("{error}", error)),
                exhausted=False)
            self._fu_start_next()
        else:
            self._fu_dialog.finish_error(error)
            self._set_busy(False, "")
            self.status.setText(i18n.t(
                "Nothing came back. The previous answer is still shown."))

    def _fu_on_skip(self):
        self._fu_skipped = True
        if self._worker and self._worker.isRunning():
            self._worker.skip()

    def _fu_on_fallback(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
        self._fu_start_next()

    def _fu_on_stop(self):
        self._fu_stopped = True
        if self._worker and self._worker.isRunning():
            self._worker.stop()

    # ── item 30d: History — resume a past job on THIS screen ───────────────
    def _open_history(self):
        from addons.boq.history import BoqHistoryDialog
        dlg = BoqHistoryDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.chosen:
            self._resume_from_history(dlg.chosen)

    def _restore_industry(self, info: dict):
        """A reopened job keeps the industry it was made for (a custom one only if
        it still exists; otherwise it is Other, and says so)."""
        if self.mode != "boq" or not isinstance(info, dict):
            return
        kind, name = info.get("kind"), info.get("name")
        if kind == "custom":
            entry = CI.get(self.cfg, str(info.get("id") or ""))
            self._pick_job(CI.choice_key(entry) if entry else CI.OTHER)
        elif kind == "other":
            self._pick_job(CI.OTHER)
        elif name in industries.NAMES:
            self._pick_job(name)

    def _resume_from_history(self, record: dict):
        """Load a past BOQ job's saved state onto this screen so a
        follow-up on it is grounded in what that job actually produced —
        its last answer, its deliverable file, and (via continue_run)
        its own artifacts folder, so a new document this follow-up makes
        lands beside the old ones instead of starting a fresh folder."""
        self._boq_run_path = record.get("_path", "")
        self.request = record.get("request") or record.get("query") or ""
        self._task_name = record.get("query") or self.request
        self._all_responses = dict(record.get("responses") or {})
        self._links = dict(record.get("links") or {})
        boq = record.get("boq") or {}
        self.csv_path = boq.get("quantities_csv") or ""
        self.cad_path = boq.get("source") or ""
        self._deliverable_path = record.get("deliverable_path") or ""
        self._restore_industry(record.get("industry") or {})
        artifacts = record.get("artifacts") or ""
        if artifacts and os.path.isdir(artifacts):
            self._artifacts_dir = CB.config.continue_run(
                artifacts, task=self._task_name, title=self._task_name)
        from addons.boq.history import when_label
        text = record.get("last_text") or ""
        self._show_result(text)
        self.status.setText(i18n.t(
            "Opened from History: {when}. Type a follow-up below to carry "
            "it on.").replace("{when}", when_label(record.get("_path", ""))))
        self.open_btn.setEnabled(bool(self._deliverable_path or self._links))
        self._refresh_primary()
        self.recheck_btn.setEnabled(bool(self.cad_path))
        if self.mode == "boq" and text:
            self.price_box.setVisible(True)
            self._refresh_primary()
        if text:
            self._offer_followup()

    # ── item 30b/30c: a "Prism Agent" writer, a plain OpenRouter call ──────
    def _save_prompt_record(self, stage: str, agent: str, prompt: str):
        """item 30d: this job's own folder (the SAME one begin_run()
        already opened for it — see _write()'s own `CB.config.begin_run`
        call) gets the exact prompt that went to the API, as a .txt (for
        a person to open and read) and a .json (for a future follow-up,
        or History, to load back in). Best-effort — a BOQ never fails to
        write just because its own prompt couldn't be logged."""
        folder = getattr(self, "_artifacts_dir", "") or CB.config.current_run_dir()
        if not folder:
            return
        import json as _json
        stamp = time.strftime("%Y-%m-%d %H-%M-%S")
        stem = os.path.join(folder, f"prompt_{stage}_{stamp}")
        try:
            with open(stem + ".txt", "w", encoding="utf-8") as f:
                f.write(prompt)
            with open(stem + ".json", "w", encoding="utf-8") as f:
                _json.dump({"stage": stage, "agent": agent, "prompt": prompt,
                           "request": getattr(self, "request", ""), "at": stamp}, f,
                          indent=2, ensure_ascii=False)
        except OSError:
            pass

    def _prepare_drawing_attachment(self, stage: str, agent: str, files: list
                                    ) -> tuple[list, dict | None]:
        """item 32: pull the real drawing (never a browser agent's text-
        extraction stand-in) out of `files` and turn it into something
        OpenRouter can actually look at, for the one stage that ever
        attaches it — "recheck" (_ask_recheck/_offer_followup's "Verify
        and remake"), always as `files[0]` there, straight after the SAME
        `_drawing_consent()` yes a browser agent's own upload already goes
        through. Returns (files with the drawing removed if it was
        pulled out, the attachment dict or None) — `files` unchanged, and
        None, for every other stage or agent.

        item 65 superseded an earlier version of this method that tried
        drawing_reader.extract() here, specifically, before falling back
        to a whole-image render: a DXF/DWG's real TEXT/MTEXT now reaches
        the writer a simpler way, for EVERY stage and EVERY industry, not
        just this one method's own "recheck" case -- core.boq.measure()
        itself returns that text (`text_entities`), and self.summary
        (built from it the moment the file was attached, see _measure())
        is already folded into the prompt for every write-up/recheck call
        below, drawing or no drawing. So by the time this method runs,
        the real text is already in the model's hands either way; what
        THIS method still decides is only whether to ALSO show the model
        an actual picture of the drawing, as a visual cross-check against
        those already-correct numbers -- a vision-capable agent only."""
        if stage != "recheck" or not files or not self.cad_path:
            return files, None
        if files[0].get("path") != self.cad_path:
            return files, None
        rest = files[1:]
        if not openrouter_writer.has_vision(agent):
            QMessageBox.warning(self, "BOQ", i18n.t(
                "{agent} can't look at drawings — it will recheck against "
                "the measured figures and text only, not the drawing "
                "itself. Pick Prism Agent Claude for a real look at the "
                "drawing.").replace("{agent}", agent))
            return files, None
        try:
            attachment = cad_render.prepare_for_ai(self.cad_path)
        except cad_render.CadRenderError as e:
            QMessageBox.warning(self, "BOQ", i18n.t(
                "Couldn't prepare the drawing for {agent} to look at "
                "({error}). Rechecking against the measured figures and "
                "text only instead.").replace("{agent}", agent).replace(
                    "{error}", str(e)))
            return files, None
        return rest, attachment

    def _run_prism_agent(self, stage: str, agent: str, prompt: str, files: list,
                         on_success, *, followup: bool = False):
        """No browser tab, no live window, no fallback chain — a bad key or
        a down API is reported once, directly; retrying it against five
        different BROWSER agents (FALLBACK_ORDER) would not help an API
        problem anyway. `on_success(responses, links)` is called with the
        same `{stage: [text]}` / `{}` shape a browser run's own done signal
        already produces, so _on_standards/_on_interpreted/_on_written/
        _on_followed_up all work completely unchanged — they cannot tell
        the difference between this and a browser agent's answer."""
        api_key = (self.cfg.get("openrouter_api_key") or "").strip()
        if not api_key:
            QMessageBox.warning(self, "BOQ", i18n.t(
                "Prism AI is not set up on this computer yet, so {agent} "
                "cannot write the BOQ. Check that Prism is activated and "
                "try again.").replace("{agent}", agent))
            self._set_busy(False, "")
            return
        files, attachment = self._prepare_drawing_attachment(stage, agent, files)
        # A plain chat completion has no file-upload feature the way a
        # browser tool does — any attachment left here (a template, notes,
        # the priced/measured reference CSV) has to reach the model as
        # TEXT. The drawing itself, when one was pulled out above into
        # `attachment`, goes separately as a real image/file block instead.
        if files:
            prompt = prompt + "\n\n" + CB.files.context_block(files)
        # item 41 (2 Nov 2026), found in the real file a Prism Agent
        # produced: without this, both Claude and DeepSeek opened with "I
        # can't attach a file in this chat" and then spent roughly half
        # the document dumping a broken, half-formatted python-docx
        # SCRIPT for the person to run themselves -- reasonable behaviour
        # for a model that only knows it is in a plain chat with no file
        # tool, wrong here: openrouter_writer.write_file() (this stage's
        # own on_success, a few calls up the chain) already turns
        # whatever text comes back into the real .docx/.csv/.pdf, no
        # script, no download link, needed from the model at all. Only
        # for the document-producing stages -- "standards"/"interpret"
        # never claim or need a file, so telling them about one they were
        # never asked for would be a non-sequitur.
        if stage in ("format", "recheck", "followup"):
            prompt += (
                "\n\nAbout delivering this: you are not attaching, "
                "downloading or building a file yourself, and there is no "
                "need to write a script that would. Just answer with the "
                "content itself, in the structure already asked for above "
                "(headings, bold, a markdown table) -- the real document "
                "file is built automatically from this text, by code, the "
                "moment you answer. Do not say you can't attach a file, "
                "and do not include a script, download link or setup "
                "instructions of any kind.")
        self._save_prompt_record(stage, agent, prompt)
        self.progress.set_stage(2 if stage in ("format", "recheck", "followup") else 1)
        self._set_busy(True, f"{agent} is writing your {self._noun}…")
        self._worker = OpenRouterWriteWorker(
            agent, prompt, api_key, followup=followup,
            attachments=[attachment] if attachment else None)
        self._worker.done.connect(
            lambda text, s=stage, a=agent, cb=on_success:
                self._on_prism_agent_done(s, a, text, cb))
        self._worker.failed.connect(self._on_prism_agent_failed)
        self._worker.start()

    def _on_prism_agent_done(self, stage: str, agent: str, text: str, on_success):
        self._set_busy(False, "")
        # item 70: the ONE place real token figures exist at all -- a
        # browser-driven stage never reaches here, so this stays
        # (correctly) at zero for a job that never used a Prism Agent.
        # isinstance-checked, not just truthy -- a mocked worker in a test
        # auto-creates a `.usage` attribute of its own (a Mock, not a
        # dict), which `or {}` alone does not catch.
        usage = getattr(self._worker, "usage", None)
        if not isinstance(usage, dict):
            usage = {}
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            value = usage.get(key)
            if isinstance(value, int):
                self._tokens_used[key] += value
        made_files: list = []
        # "standards"/"interpret" are text-only stages (a research brief, a
        # read of an attached sample) — only a document-producing stage
        # gets turned into an actual DOCX/CSV/PDF file.
        if stage in ("format", "recheck", "followup"):
            fmt = self._wanted_format() or "docx"
            try:
                os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
                safe_agent = agent.replace(" ", "_").lower()
                path = os.path.join(
                    CB.config.RUNS_DIR, f"boq_{safe_agent}_{int(time.time())}.{fmt}")
                openrouter_writer.write_file(text, fmt, path)
                made_files = [{"path": path, "name": os.path.basename(path),
                              "kind": stage}]
            except Exception as e:                           # noqa: BLE001
                QMessageBox.warning(self, "BOQ", i18n.t(
                    "The answer came back, but building the {fmt} file "
                    "failed: {error}").replace(
                        "{fmt}", fmt.upper()).replace("{error}", str(e)))
        self._save_deliverable(made_files, stage)
        on_success({stage: [text]}, {})

    def _on_prism_agent_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "BOQ", error)

    # ── the SAME live window, for the initial research/interpret/write
    # pipeline (item 22) — self._fu_dialog is shared with the verify/
    # follow-up flow above (one window for the whole session, per item 7),
    # so its three signals are wired exactly once, here, to these
    # dispatchers rather than straight to either flow's own handlers —
    # whichever flow is actually running right now (_active_runner) is the
    # one that gets the click.
    def _rundlg_on_skip(self):
        (self._fu_on_skip if self._active_runner == "fu" else self._rs_on_skip)()

    def _rundlg_on_fallback(self):
        (self._fu_on_fallback if self._active_runner == "fu" else self._rs_on_fallback)()

    def _rundlg_on_stop(self):
        (self._fu_on_stop if self._active_runner == "fu" else self._rs_on_stop)()

    def _run_stage(self, stage: str, agent: str, prompt: str, files: list,
                   on_success, worker_kwargs: dict | None = None):
        """Same live-window + fallback-chain shape as _start_followup_run,
        for the FIRST run of the pipeline (research, interpret, write) —
        kept as its own small state (`_rs_*`) rather than reusing `_fu_*`,
        so neither flow can ever read the other's token, chain or stopped/
        skipped flags. `on_success(responses, links)` is `_on_standards`/
        `_on_interpreted`/`_on_written` — unchanged, called directly, since
        they already expect exactly this shape from a plain
        AutomationWorker.done signal."""
        # item 30b/30c: a Prism Agent is a plain API call, never a browser
        # tab — it never reaches BoqRunDialog's live window or fallback
        # chain at all. See _run_prism_agent's own docstring for why.
        if agent in boq_agents.PRISM_AGENTS:
            self._run_prism_agent(stage, agent, prompt, files, on_success)
            return
        from addons.boq.run_dialog import BoqRunDialog
        self._rs_stage = stage
        self._rs_agent_requested = agent
        self._rs_prompt = prompt
        self._rs_files = files
        self._rs_on_success = on_success
        self._rs_worker_kwargs = worker_kwargs or {}
        self._rs_chain = [agent] + [a for a in boq_agents.FALLBACK_ORDER if a != agent]
        self._rs_stopped = False
        self._rs_skipped = False
        self._rs_token = 0
        self._active_runner = "rs"
        titles = {
            "standards": i18n.t("Researching standards and norms"),
            "interpret": i18n.t("Reading the drawing and your sample"),
            "format": i18n.t("Writing your {noun}").replace("{noun}", self._noun),
        }
        title = titles[stage]
        if self._fu_dialog is None:
            self._fu_dialog = BoqRunDialog(title, stage, agent, parent=self)
            self._fu_dialog.skip_requested.connect(self._rundlg_on_skip)
            self._fu_dialog.fallback_requested.connect(self._rundlg_on_fallback)
            self._fu_dialog.stop_requested.connect(self._rundlg_on_stop)
        else:
            self._fu_dialog.restart(title, stage, agent)
        self._rs_start_next()
        self._fu_dialog.show()
        self._fu_dialog.raise_()
        self._fu_dialog.activateWindow()

    def _rs_start_next(self):
        if not self._rs_chain:
            self._fu_dialog.finish_error(i18n.t(
                "None of the fallback tools could answer either."))
            self._on_failed(i18n.t("Nothing came back from any writer tool."))
            return
        tool = self._rs_chain.pop(0)
        self._rs_token += 1
        token = self._rs_token
        self.progress.set_stage(2 if self._rs_stage == "format" else 1)
        self._set_busy(True, f"{tool} is working on your {self._noun}…")
        self._fu_dialog.set_agent(tool)
        self._worker = AutomationWorker(
            {}, self.cfg, self._rs_files, self._rs_prompt,
            custom_stages=[(self._rs_stage, tool, [self._rs_prompt])],
            chatgpt_analysis=False,
            # Found live, 24 Oct 2026: before item 22, these three stages
            # were never a "follow-up" to the engine at all, so they got
            # only each tool's own everyday wait_time -- no floor whatsoever,
            # not even the one a plain follow-up already gets. Claude's own
            # registered wait_time (600s) is already the highest of the six
            # writer agents; Kimi's (1000s) is higher still — ChatGPT, Grok
            # and Gemini (300s each) are the ones that were genuinely short,
            # and ALL of them now get at least FOLLOWUP_MIN_WAIT (480s), the
            # same floor a follow-up turn gets, since writing a full BOQ is
            # exactly the "redoes a whole deliverable" case that floor
            # exists for. A ceiling only — the wait still ends the moment
            # the answer settles, so this costs a fast agent nothing.
            followup=True,
            min_wait=900 if self._rs_stage == "format" else 0,
            **self._rs_worker_kwargs)
        self._worker.done.connect(
            lambda responses, links, t=token: self._rs_on_done(t, tool, responses, links))
        self._worker.failed.connect(
            lambda error, t=token: self._rs_on_failed(t, tool, error))
        self._worker.start()

    _RS_AGENT_ATTR = {"standards": "researcher", "interpret": "interpreter",
                      "format": "writer_agent"}

    def _rs_on_done(self, token: int, tool: str, responses: dict, links: dict):
        if token != self._rs_token:
            return                             # a superseded attempt's late signal
        # A fallback may have answered instead of the originally requested
        # agent — _on_standards/_on_interpreted/_on_written read self.
        # researcher/interpreter/writer_agent for _stage_agents_map and
        # _last_agent, so this must name whoever actually answered, exactly
        # the way _fu_start_next already does for follow-ups.
        setattr(self, self._RS_AGENT_ATTR[self._rs_stage], tool)
        if self._rs_skipped:
            self._fu_dialog.finish_skipped()
        elif self._rs_stopped:
            self._fu_dialog.finish_cancelled()
        else:
            texts = responses.get(self._rs_stage) or []
            self._fu_dialog.finish_ok(texts, links.get(self._rs_stage, ""))
        self._rs_on_success(responses, links)

    def _rs_on_failed(self, token: int, tool: str, error: str):
        if token != self._rs_token or self._rs_stopped or self._rs_skipped:
            return
        if self._rs_chain:
            self._fu_dialog.finish_error(
                i18n.t("{tool} could not answer ({error}) — trying the "
                      "next fallback tool…")
                .replace("{tool}", tool).replace("{error}", error),
                exhausted=False)
            self._rs_start_next()
        else:
            self._fu_dialog.finish_error(error)
            self._on_failed(error)

    def _rs_on_skip(self):
        self._rs_skipped = True
        if self._worker and self._worker.isRunning():
            self._worker.skip()

    def _rs_on_fallback(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
        self._rs_start_next()

    def _rs_on_stop(self):
        self._rs_stopped = True
        if self._worker and self._worker.isRunning():
            self._worker.stop()
        self.status.setText(i18n.t(
            "Stopping — finishing up, keeping what's done…"))

    def _on_followed_up(self, responses: dict, links: dict):
        stage = self._followup_stage
        self._set_busy(False, "")
        self._links.update(links)
        self._all_responses.update(responses)
        self._stage_agents_map[stage] = self._followup_agent
        # Updated on EVERY stage, not only the first write-up -- a third
        # follow-up by the same agent must resume the SECOND follow-up's
        # chat, not keep reaching back to the very first one.
        self._last_agent = self._followup_agent
        self._last_link = links.get(stage) or self._last_link
        self._lap(stage)
        texts = [t for t in (responses.get(stage) or []) if t.strip()]
        if texts:
            self._show_result(texts[0])
            self.status.setText(i18n.t("Done. Check the numbers against the drawing and the saved file."))
            if self.mode == "boq":
                self._pipe_written(True)
        else:
            self.status.setText(i18n.t("Nothing came back. The previous answer is still shown."))
        self.open_btn.setEnabled(bool(self._links.get(stage) or self._links.get("format")))
        self._refresh_primary()
        # "Make with drawing" pressed before any BOQ existed (item 8) is
        # also a real first BOQ, produced through this handler rather than
        # _on_written -- "Price it" must become available here too, not
        # only after the ordinary "Make my BOQ" path.
        if self.mode == "boq" and texts:
            self.price_box.setVisible(True)
            self._refresh_primary()
        # item 30d: update the SAME History record a follow-up belongs
        # to, rather than leaving it stuck at whatever the first write-up
        # said — save_run's own `path=` does an in-place update
        # (core/config.py's own docstring). No path yet (a follow-up
        # answering before any "Make my BOQ" ever ran, e.g. "Make with
        # drawing" straight off) -- same call still works, it just
        # creates the first record instead of updating one.
        run_path = getattr(self, "_boq_run_path", "")
        request = getattr(self, "request", "")
        task_label = getattr(self, "_task_name", "") or f"{self._noun} — {request}"
        self._boq_run_path = CB.config.save_run({
            "addon": "boq", "query": task_label, "request": request,
            "responses": self._all_responses, "links": self._links,
            "last_text": texts[0] if texts else "",
            "artifacts": getattr(self, "_artifacts_dir", "") or CB.config.current_run_dir(),
            "deliverable_path": getattr(self, "_deliverable_path", ""),
            "boq": {"quantities_csv": self.csv_path, "source": self.cad_path},
            "industry": self._industry_record(),
            "tokens": dict(self._tokens_used),
        }, path=run_path)
        self._offer_followup()

    def _offer_followup(self):
        """The same 'anything to change?' window Prism shows after any run,
        opened here on this screen so it comes straight after the output."""
        from dialogs.followup_dialog import FollowupDialog
        # item 54: _raw_result, not self.result.toMarkdown() -- see
        # _show_result's own comment. Also avoids showing the person a
        # stray "\*" the round-trip could have introduced in this recap.
        answer = getattr(self, "_raw_result", "").strip()
        if not answer:
            return
        actions = []
        if self.cad_path:
            actions.append(("verify", i18n.t("Verify and remake"), VERIFY_PROMPT))
        # self._deliverable_path (the latest file an AI stage actually made —
        # write-up, verify-and-remake or a follow-up) goes FIRST: it is what
        # the person just asked for and, until now, this window kept showing
        # self.csv_path instead — the locally measured quantities, made
        # before any AI ran and never touched again, regardless of what a
        # follow-up had just produced. Both are kept (not one replacing the
        # other) since the measured CSV is still a real, checkable artifact
        # of this run.
        dlg = FollowupDialog(
            answer, self,
            artifacts=[p for p in [self._deliverable_path, self.csv_path] if p],
            quick_actions=actions)
        dlg.exec()
        if not dlg.submitted():
            return
        if dlg.chosen_quick() == "verify":
            if not self._drawing_consent():
                return
            self._send_followup(dlg.followup_text(),
                                [CB.files.attach(self.cad_path)], verify=True)
            return
        extra = []
        for path in dlg.file_paths():
            try:
                extra.append(CB.files.attach(path))
            except Exception:                           # noqa: BLE001
                pass
        self._send_followup(dlg.followup_text(), extra, verify=False)

    def closeEvent(self, event):
        """Wind up any worker before this dialog is destroyed.

        A QThread destroyed while still running aborts the whole process —
        "QThread: Destroyed while thread is still running", then a core dump —
        so closing the BOQ window mid-run took Prism down with it. The
        automation worker polls a stop flag between stages and inside its
        waits, so asking first lets it close its browser tab cleanly instead
        of being killed.
        """
        for worker in (getattr(self, "_worker", None),
                       getattr(self, "_measure_worker", None),
                       getattr(self, "_rec", None)):
            if worker is None or not worker.isRunning():
                continue
            if hasattr(worker, "stop"):
                worker.stop()
            # Bounded: a stage mid-scrape can take a moment to notice, but a
            # dialog that refuses to close is its own bug.
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    def _open_link(self):
        import webbrowser
        url = self._links.get("format")
        if url:
            webbrowser.open(url)

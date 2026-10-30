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
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QPushButton,
    QPlainTextEdit, QLineEdit, QMessageBox, QCheckBox, QFileDialog,
    QComboBox, QWidget,
)

import core_bridge as CB
from addons import registry
import i18n
import theme
import wakeword
from dialogs.base import PrismDialog
from workers import AutomationWorker, MeasureWorker, RecordWorker
from widgets import controls as C
from widgets.loader import Loader
from widgets.ask_panel import AskPanel, MoreOptions
from addons.boq import agents as boq_agents
from addons.boq import industries
from addons.boq import cad_render
from addons.boq import openrouter_writer
from addons.boq.measured import MeasuredTable
from addons.boq.pricing import PricingTable
from addons.boq.takeoff import IndustryTakeoffDialog
from addons.boq.workers import OpenRouterWriteWorker
from widgets.output_panel import short_duration


VERIFY_PROMPT = (
    "Verify and remake: recheck every measured quantity against the attached "
    "drawing. The drawing is the source of truth; the measured figures were "
    "computed locally from it. For every quantity that does not match the "
    "drawing, state the drawing value and the measured value. Then remake the "
    "whole BOQ in the same format as the previous answer with the corrected "
    "figures, and list what changed.")

# "Make with drawing" pressed before any BOQ exists yet -- there is no
# previous answer to remake, so this does NOT reuse VERIFY_PROMPT's "remake
# in the same format... list what changed" framing, which only makes sense
# once something has already been written. Same job either way (read the
# drawing itself, not just the measured figures), different starting point.
MAKE_WITH_DRAWING_PROMPT = (
    "Make the whole BOQ by reading the attached drawing directly, not only "
    "the measured figures below. The measured figures were computed locally "
    "from the same drawing -- use them as a cross-check, and where your own "
    "reading of the drawing disagrees with a measured figure, say so and use "
    "the drawing's own value.")


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
            i18n.t("Attach a drawing and it is measured here, on this "
                   "machine. Nothing is measured by an AI."),
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

        self.cad_path = ""
        self.templates: list[dict] = []
        self.images: list[dict] = []
        self.notes: list[dict] = []
        self.q = None
        self.summary = ""
        self.csv_path = ""
        self._hvac = False
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
        root = self.body
        # A stacked form, not a grid of cards: the 16px card gutter
        # between every row of a single column is what turns a short
        # form into a tall one with bands of canvas through it.
        root.setSpacing(theme.ROW_GAP)

        title = QLabel(f"What do you need a {self._noun} for?")
        title.setObjectName("h4")
        root.addWidget(title)

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
        self.ask = AskPanel(placeholder)
        self.ask.speak_clicked.connect(self._toggle_record)
        self.ask.files_added.connect(self._on_files_added)
        root.addWidget(self.ask)

        # Say which format works BEFORE a drawing is attached, not in an error
        # afterwards.
        #
        # .dwg is Autodesk's closed format, and reading it needs a separate
        # converter Prism is not allowed to ship: ODA File Converter is only
        # distributed through a registration form with an EULA, and its licence
        # forbids redistribution. So on a machine without one, a customer who
        # attached the obvious file got told to go and install a program —
        # after picking the file, naming the job and pressing the button.
        #
        # .dxf needs none of that. Every CAD program exports it in one step,
        # ezdxf reads it directly, and it is the same geometry. Making that the
        # expected input is the difference between a five-minute detour and a
        # dead end — and it costs the customer one menu item they already know.
        #
        # Shown only when this machine genuinely has no converter: a client who
        # has installed one can attach .dwg all day and must not be nagged
        # about a problem they do not have.
        if not self.boq.find_dwg_converter():
            dxf_note = QLabel(
                "Attaching a drawing? Save it as <b>DXF</b> first — in AutoCAD "
                "that is File → Save As → <i>AutoCAD DXF</i>, and most other "
                "CAD programs have the same option. Prism measures DXF "
                "directly. A .dwg needs an extra converter this computer "
                "does not have.")
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
        root.addWidget(self.template_hint)

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
        meas_row.addWidget(self.input_meas_btn)
        # Only ever shown for an industry that actually has its own
        # PDF-takeoff tool (today, only HVAC) -- picked explicitly from
        # the Industry dropdown above, never guessed from a file. See
        # addons/boq/industries.has_takeoff and BOQ-CHANGES-TODO.md item 26.
        self.takeoff_btn = self.button(
            i18n.t("{industry} PDF takeoff…").format(industry=industries.HVAC),
            "secondary", icon_name="paperclip", small=True,
            on_click=self._open_industry_takeoff)
        self.takeoff_btn.setVisible(False)
        meas_row.addWidget(self.takeoff_btn)
        meas_row.addStretch(1)
        root.addLayout(meas_row)

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
        self.price_box = QGroupBox(i18n.t("Price it (optional)"))
        price_l = QVBoxLayout(self.price_box)
        self.price_table = PricingTable(self.cfg)
        price_l.addWidget(self.price_table)
        self.price_box.setVisible(False)
        root.addWidget(self.price_box)

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
        picker = QWidget()
        prow = QHBoxLayout(picker)
        prow.setContentsMargins(0, 0, 0, 0)
        prow.setSpacing(theme.SPACE_2)
        wlab = QLabel(i18n.t("Write with")); wlab.setObjectName("meta")
        rlab = QLabel(i18n.t("· Research with")); rlab.setObjectName("meta")
        prow.addWidget(wlab)
        prow.addWidget(self.writer_combo)
        prow.addWidget(rlab)
        prow.addWidget(self.research_combo)
        prow.addStretch(1)
        # item 30d: "someone made 3 BOQs today, needs to follow up on the
        # first one this afternoon" — a new job's own dialog instance has
        # no memory of a PAST one (each open of this add-on is a fresh
        # BoqDialog), so resuming one has to come from the side, not from
        # continuing the live screen.
        self.history_btn = C.button(i18n.t("History"), "tertiary", small=True,
                                    icon_name="clock", on_click=self._open_history)
        prow.addWidget(self.history_btn)
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
        flab = QLabel(i18n.t("· File format")); flab.setObjectName("meta")
        self.format_combo = QComboBox()
        self.format_combo.addItem(i18n.t("Let the tool decide"), "")
        self.format_combo.addItem(i18n.t("Word document (.docx)"), "docx")
        self.format_combo.addItem(i18n.t("CSV"), "csv")
        self.format_combo.addItem(i18n.t("PDF"), "pdf")
        prow.addWidget(flab)
        prow.addWidget(self.format_combo)
        # Which industry this job is for -- item 26: BOQ is sold across
        # industries, and each one reads its own drawings by its own
        # rules, so the rule-set that runs (HVAC_DRAWING_RULES.md's
        # write-up guidance, and below, which PDF-takeoff tool offers
        # itself) is this explicit choice, never guessed from the request
        # text or from an uploaded file's own content -- see
        # addons/boq/industries.py and self._on_industry_changed.
        ilab = QLabel(i18n.t("· Industry")); ilab.setObjectName("meta")
        self.industry_combo = QComboBox()
        self.industry_combo.addItems(industries.NAMES)
        self.industry_combo.currentTextChanged.connect(self._on_industry_changed)
        prow.addWidget(ilab)
        prow.addWidget(self.industry_combo)
        prow.addStretch(1)
        root.addWidget(picker)

        # Everything technical lives here, shut by default.
        self.more = MoreOptions("More options")
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("Drawing unit, if you know it — e.g. meters")
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

        self.progress = Loader("stages", [i18n.t(n) for n in ['Measure', 'Check', 'Write']])
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText(f"Your {self._noun} will appear here.")
        self.result.setMinimumHeight(120)
        root.addWidget(self.result, stretch=1)

        self.open_btn = self.button(i18n.t("Open in browser"), "secondary",
                                    icon_name="external", small=True,
                                    on_click=self._open_link)
        self.open_btn.setEnabled(False)
        self.footer.add_utility(self.open_btn)
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
        self.footer.add_utility(self.recheck_btn)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.run_btn = self.button(f"Make my {self._noun}", "primary", icon_name="check",
                                   on_click=self._run)
        self.footer.set_primary(self.run_btn)

        # Files already attached on the home screen come along automatically.
        if attachments:
            self._absorb([a["path"] for a in attachments])

    # ── files ───────────────────────────────────────────────────────────

    def _on_files_added(self, paths: list):
        self._absorb(paths)

    def _absorb(self, paths: list):
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
            self._measure()

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
            self._use_external_measurements(dlg.measurements_text())

    def _on_industry_changed(self, industry: str):
        """Item 26: the PDF-takeoff button is only ever offered for an
        industry that has one of its own (today, only HVAC) -- an ELV or
        pharma-tech job must not be shown a button that would silently run
        HVAC's own OCR/rules against a drawing that was never one."""
        self.takeoff_btn.setVisible(industries.has_takeoff(industry))

    def _open_industry_takeoff(self):
        dlg = IndustryTakeoffDialog(self.industry_combo.currentText(), self)
        if dlg.exec() == QDialog.Accepted:
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
        self._hvac = self.industry_combo.currentText() == industries.HVAC
        self.q = {"external": True, "text": text}
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
        if self._run_pending:
            self._run_pending = False
            self._run()

    # ── measuring ───────────────────────────────────────────────────────

    def _measure(self):
        if not self.cad_path or not os.path.exists(self.cad_path):
            return
        self.progress.set_stage(0)
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
        hvac = self.industry_combo.currentText() == industries.HVAC
        # Remembered, not re-read at write time: the write-up prompt's own
        # HVAC-only guidance (below) must match whatever this measurement
        # actually used -- telling the writer "use the real duct sizes"
        # when the measurement never looked for any would be noise, and
        # the ask box's text could change between measuring and writing.
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
        self._set_busy(False, "Measured from the drawing itself — not by an AI.")
        # If the user already pressed "Make my BOQ" while this was measuring,
        # start it now — with the measured quantities it was waiting for.
        if self._run_pending:
            self._run_pending = False
            self._run()

    def _on_measure_failed(self, error: str):
        self._set_busy(False, "")
        # Don't auto-start a deferred run on a failed measure — the user should
        # see the error and decide (they can still run a derived/spec BOQ).
        self._run_pending = False
        QMessageBox.warning(self, "BOQ", error)

    # ── voice ───────────────────────────────────────────────────────────

    def _toggle_record(self):
        if self._rec:
            self._rec.stop()
            self.ask.set_recording(False)
            return
        if not CB.voice.available():
            QMessageBox.information(
                self, "Speak",
                "Voice needs PyAudio on this machine:\n\n"
                f"    {wakeword.install_hint()}\n\n"
                "Everything else works — just type instead.")
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
        return ("\n\nGive me the result as " + self._FORMAT_PHRASE[fmt]
                + ", built here rather than only pasted into the chat.")

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
        self.progress.set_stage(2)
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
            # HVAC_DRAWING_RULES.md's write-up guidance (duplicate-layer
            # judgement, legend caution, real sizes) is trade-specific the
            # same way the measurement rules are -- only ever on when this
            # run's own measurement used them, never guessed or applied to
            # an ELV/CCTV/cabling/plumbing/fire-hydrant BOQ by default.
            hvac=self._hvac)

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
            self.result.setPlainText(texts[0])
            self.status.setText(
                (f"Done in {timing}. " if timing else "Done. ")
                + "Check the numbers against the saved file above.")
        self._save_deliverable(self._write_made_files, "format")
        self.open_btn.setEnabled(bool(self._links.get("format")))
        self.recheck_btn.setEnabled(bool(self.cad_path))
        # "Price it" becomes available once there is a BOQ to price, not
        # before — the box's data has been ready since _on_measured, only
        # its visibility was moved here.
        if self.mode == "boq" and texts:
            self.price_box.setVisible(True)
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
        })
        if texts:
            self._offer_followup()

    def _on_failed(self, error: str):
        self._set_busy(False, "")
        QMessageBox.warning(self, "BOQ", error)

    def _set_busy(self, busy: bool, message: str):
        if busy:
            self.progress.set_message(message)
        self.progress.setVisible(busy)
        self.run_btn.setEnabled(not busy)
        self.recheck_btn.setEnabled(not busy and bool(self.cad_path))
        self.status.setText("" if busy else message)   # the loader carries it while busy

    def _drawing_consent(self) -> bool:
        """The drawing leaves this computer only after this explicit yes."""
        agent = self.writer_combo.currentText().strip() or "the writing AI"
        answer = QMessageBox.question(
            self, i18n.t("Send the drawing to AI?"),
            i18n.t("You are now permitting {name} to be sent to {agent} so it "
                   "can recheck the measured quantities. The drawing file "
                   "leaves this computer. Continue?").replace(
                       "{name}", os.path.basename(self.cad_path)).replace(
                       "{agent}", agent),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _ask_recheck(self):
        if not self._drawing_consent():
            return
        # No BOQ made yet -- "Make with drawing" is the FIRST thing this
        # session does, not a recheck of something already written, so
        # there is no previous answer to remake. VERIFY_PROMPT's own
        # wording ("remake... in the same format as the previous answer...
        # list what changed") only makes sense once one exists.
        note = (VERIFY_PROMPT if self.result.toPlainText().strip()
               else MAKE_WITH_DRAWING_PROMPT)
        self._send_followup(note, [CB.files.attach(self.cad_path)], verify=True)

    def _send_followup(self, note: str, extra_files: list, verify: bool):
        agent = self.writer_combo.currentText().strip() or "the writing AI"
        stage = "recheck" if verify else "followup"
        prompt = f"{note}\n\nMEASURED FIGURES:\n{self.summary}"
        # Only when there IS one -- "Make with drawing" pressed before any
        # BOQ exists has nothing previous to show, and an empty section
        # ("PREVIOUS ANSWER:\n\n") would read as a previous answer that
        # happens to be blank rather than there being none at all.
        previous = self.result.toPlainText().strip()
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
        artifacts = record.get("artifacts") or ""
        if artifacts and os.path.isdir(artifacts):
            self._artifacts_dir = CB.config.continue_run(
                artifacts, task=self._task_name, title=self._task_name)
        from addons.boq.history import when_label
        text = record.get("last_text") or ""
        self.result.setPlainText(text)
        self.status.setText(i18n.t(
            "Opened from History: {when}. Type a follow-up below to carry "
            "it on.").replace("{when}", when_label(record.get("_path", ""))))
        self.open_btn.setEnabled(bool(self._deliverable_path or self._links))
        self.recheck_btn.setEnabled(bool(self.cad_path))
        if self.mode == "boq" and text:
            self.price_box.setVisible(True)
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
        None, for every other stage or agent."""
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
                "No OpenRouter key set for {agent}. Add one in Settings → "
                "AI tools, or pick a different agent.").replace("{agent}", agent))
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
            self.result.setPlainText(texts[0])
            self.status.setText(i18n.t("Done. Check the numbers against the drawing and the saved file."))
        else:
            self.status.setText(i18n.t("Nothing came back. The previous answer is still shown."))
        self.open_btn.setEnabled(bool(self._links.get(stage) or self._links.get("format")))
        # "Make with drawing" pressed before any BOQ existed (item 8) is
        # also a real first BOQ, produced through this handler rather than
        # _on_written -- "Price it" must become available here too, not
        # only after the ordinary "Make my BOQ" path.
        if self.mode == "boq" and texts:
            self.price_box.setVisible(True)
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
        }, path=run_path)
        self._offer_followup()

    def _offer_followup(self):
        """The same 'anything to change?' window Prism shows after any run,
        opened here on this screen so it comes straight after the output."""
        from dialogs.followup_dialog import FollowupDialog
        answer = self.result.toPlainText().strip()
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

"""Shown once the run finishes: what each step produced, with an Open button
per step so the user opens only the ones they actually need instead of
scrolling through everything."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QFrame, QApplication, QDialogButtonBox, QScrollArea, QWidget,
    QTextBrowser, QFileDialog, QMessageBox,
)

import os

import i18n
import ai_server
import paths
import viewer
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import Chip, heading
from widgets.markdown import render_markdown


class StageResultDialog(PrismDialog):
    """One step's full output, popped out into its own window."""

    def __init__(self, stage: str, agent: str, text: str, url: str, parent=None,
                 unfinished: bool = False, files: list | None = None,
                 where: str = ""):
        icon_name, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
        agent = ai_server.display_agent(agent, where=where)
        super().__init__(title, agent, icon=icon_name, parent=parent,
                         closable=False)
        self.setWindowTitle(f"{title} · {agent}")
        self.resize(720, 560)
        root = self.body
        root.setSpacing(theme.SPACE_3)
        if paths.is_local_result(url):
            # A file, not a tab — an <a href> to a bare path opens nothing, so
            # this step's result used to be unreachable from here.
            video = url.lower().endswith((".mp4", ".mov", ".m4v", ".webm"))
            files = QHBoxLayout()
            files.setSpacing(8)
            play = QPushButton("Play video" if video else "Open file")
            play.setObjectName("smallBtn")
            icons.button_icon(play, "play" if video else "folder", 14, theme.TEXT)
            play.clicked.connect(lambda: paths.open_result(url))
            files.addWidget(play)
            show = QPushButton("Show in folder")
            show.setObjectName("smallBtn")
            icons.button_icon(show, "folder", 14, theme.TEXT)
            show.clicked.connect(lambda: paths.reveal_result(url))
            files.addWidget(show)
            where = QLabel(os.path.basename(url))
            where.setObjectName("meta")
            files.addWidget(where)
            files.addStretch(1)
            root.addLayout(files)
            if os.path.splitext(url)[1].lower() in (".xlsx", ".csv", ".zip",
                                                    ".docx", ".pdf"):
                from widgets.file_card import FileCards
                self.file_cards = FileCards([url], preview=True)
                root.addWidget(self.file_cards)
        elif url and not files:
            # When Prism didn't get the text, this link is the whole result —
            # the tool keeps working in that tab after we stop watching.
            label = (f"The result is still being made in {agent} — open it"
                     if unfinished else f"Open in {agent}")
            # The one QLabel in the app that genuinely wants markup, so it opts
            # back in — i18n.install() makes every other one PlainText, because
            # register values come from customer email. Safe here: both halves
            # are ours. `url` is a tool tab we opened, `label` is our own copy.
            link = QLabel(f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                          f'{label}</a>')
            link.setTextFormat(Qt.RichText)
            link.setOpenExternalLinks(True)
            root.addWidget(link)
        if files:
            # Files Prism built from the AI's structured answer: cards with
            # Open / Show in folder / Save as / Convert to, and a preview
            # table for a spreadsheet.
            from widgets.file_card import FileCards
            self.file_cards = FileCards(files, preview=True)
            root.addWidget(self.file_cards)
        body = QTextBrowser()
        self.reader = body
        body.setObjectName("answerReader")
        body.setReadOnly(True)
        viewer.route_links(body)
        body.setFrameShape(QFrame.NoFrame)
        body.setStyleSheet(
            f"QTextBrowser#answerReader {{ background: transparent; border: none;"
            f" color: {theme.TEXT}; selection-background-color: {theme.ACCENT_RAMP[200]}; }}")
        # The reader keeps a comfortable line length: the text sits in a
        # centred column however wide the window is made.
        body.document().setDocumentMargin(24)
        body.document().setDefaultStyleSheet(_READER_CSS)
        if text:
            body.document().setMarkdown(text)
        elif url:
            body.setPlainText(
                "No text was captured here — the link above is where this step "
                "landed, and it is the one to open.")
        else:
            body.setPlainText("(no response text captured)")
        root.addWidget(body, stretch=1)
        self._text = text or ""
        self.footer.add_utility(self.button(
            i18n.t("Copy"), "secondary", icon_name="copy", small=True,
            on_click=lambda: QApplication.clipboard().setText(
                text or body.toPlainText())))
        self.save_btn = self.button(
            i18n.t("Save as…"), "secondary", icon_name="folder", small=True,
            on_click=self._save_as)
        self.footer.add_utility(self.save_btn)
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))

    def save_to(self, path: str) -> str:
        """Write the answer to `path`; the extension picks the format
        (.txt .md .docx .pdf). Returns the path written, "" when it could not."""
        import docexport
        ext = os.path.splitext(path)[1].lower()
        text = self._text or self.reader.toPlainText()
        if ext in (".docx", ".pdf"):
            folder, name = os.path.split(path)
            made, _ = docexport.export_answer(text, ext, folder,
                                              os.path.splitext(name)[0])
            return made if made.lower().endswith(ext) else ""
        with open(path, "w", encoding="utf-8") as f:
            f.write(text if ext == ".md" else self.reader.toPlainText())
        return path

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save this answer"), "answer.pdf",
            "PDF (*.pdf);;Word (*.docx);;Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".pdf"
        try:
            ok = self.save_to(path)
        except OSError:
            ok = ""
        if not ok:
            QMessageBox.warning(self, i18n.t("Could not save"),
                                i18n.t("Prism could not write that file. Try another "
                                       "folder or another format."))


_READER_CSS = (
    f"body {{ font-size: 15px; line-height: 160%; color: {theme.TEXT}; }}"
    "h1 { font-size: 26px; font-weight: 500; margin-top: 6px; margin-bottom: 10px; }"
    "h2 { font-size: 21px; font-weight: 500; margin-top: 18px; margin-bottom: 6px; }"
    "h3 { font-size: 17px; font-weight: 600; margin-top: 14px; margin-bottom: 4px; }"
    "p { margin-top: 0px; margin-bottom: 10px; }"
    "li { margin-bottom: 4px; }"
    f"code, pre {{ font-family: 'Geist Mono','JetBrains Mono',Consolas,monospace;"
    f" font-size: 13px; background-color: {theme.NEUTRAL[100]}; }}"
    f"th {{ background-color: {theme.NEUTRAL[100]}; font-weight: 600; }}"
    f"a {{ color: {theme.ACCENT_RAMP[700]}; }}"
)


class _StageRow(QFrame):
    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(12)

        stage = info["stage"]
        icon_name, title, _ = STAGE_COPY.get(stage, ("grid", stage.title(), ""))
        ok = info.get("ok", True)
        url = info.get("url", "")
        # Either the wait cap expired or the step broke — in both cases the tool
        # may still deliver at its link, so the row says "still going", not
        # "done", and never "failed" without offering that link.
        unfinished = bool(info.get("timed_out")) or (not ok and bool(url))

        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(icon_name, 18, theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        row.addWidget(glyph)

        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(8)
        name = QLabel(title)
        name.setObjectName("h5")
        head.addWidget(name)
        tool = QLabel(ai_server.display_agent(info["agent"],
                                              where=info.get("where", "")))
        tool.setObjectName("tagNeutral")
        head.addWidget(tool)
        if info.get("timed_out"):
            head.addWidget(Chip("still generating", "clock", "tagWarn"))
        elif not ok and url:
            # It broke on our side but the tab lives on — "failed" alone would
            # send the user away from a page that may still deliver.
            head.addWidget(Chip("failed · link kept", "alert", "tagWarn"))
        else:
            head.addWidget(Chip("done" if ok else "failed",
                                "check" if ok else "alert",
                                "tagOk" if ok else "tagErr"))
        head.addStretch(1)
        text.addLayout(head)
        snippet = QLabel(info.get("snippet", ""))
        snippet.setObjectName("meta")
        snippet.setWordWrap(True)
        text.addWidget(snippet)
        row.addLayout(text, stretch=1)

        # A rendered video wants one click, not a dialog about itself.
        plays = paths.is_local_result(url) and url.lower().endswith(
            (".mp4", ".mov", ".m4v", ".webm"))
        open_btn = QPushButton("Play" if plays else "Open")
        open_btn.setObjectName("smallBtn")
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.clicked.connect(
            (lambda: paths.open_result(url)) if plays else
            (lambda: StageResultDialog(
                stage, info["agent"], info.get("text", ""), url,
                self.window(), unfinished, files=info.get("files"),
                where=info.get("where", "")).exec()))
        row.addWidget(open_btn)


class _TaskHeader(QFrame):
    """Names one task in a multi-task run, and says how it went before any of
    its steps are read."""

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("row")
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 10, 14, 10)
        box.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)
        num = QLabel(i18n.t("Task {n}").format(n=group.get("index", 0)))
        num.setObjectName("h5")
        head.addWidget(num)
        stages = group.get("stages", [])
        tools = []
        for s in stages:                       # ordered, de-duplicated
            a = ai_server.display_agent(s.get("agent", ""),
                                        where=s.get("where", ""))
            if a and a not in tools:
                tools.append(a)
        if group.get("error"):
            head.addWidget(Chip("failed", "alert", "tagErr"))
        else:
            ok = sum(1 for s in stages if s.get("ok", True))
            head.addWidget(Chip(f"{ok}/{len(stages)} steps", "check", "tagOk"))
        head.addStretch(1)
        box.addLayout(head)

        what = QLabel(" ".join(group.get("task", "").split()) or "(no task text)")
        what.setWordWrap(True)
        box.addWidget(what)

        # The question this window exists to answer at a glance: which AIs ran
        # for THIS task. The per-step rows below carry the links.
        line = (f"Used: {', '.join(tools)}" if tools else "No tool ran.")
        if group.get("error"):
            line += f" · {group['error']}"
        used = QLabel(line)
        used.setObjectName("meta")
        used.setWordWrap(True)
        box.addWidget(used)


class CompletionDialog(PrismDialog):
    """Shown when the work finishes.

    `task_groups` turns this into the multi-task view: a heading per queued
    task, then that task's steps beneath it. Left out, the dialog behaves
    exactly as it always did and just lists `stage_infos` — a single task
    should not have to read as "Task 1 of 1".
    """

    def __init__(self, stage_infos: list[dict], parent=None,
                 task_groups: list[dict] | None = None):
        multi = bool(task_groups and len(task_groups) > 1)
        # theme.OK, not theme.ACCENT. "Finished" is a success state, and the
        # accent rotates with the role — this tick was the same hue as every
        # neutral chrome element in a blue profile and would have been the
        # same hue as a "failed" cue in a red one.
        pad = C.IconPad("check", theme.OK, 38, theme.R_CONTROL, 19)
        super().__init__(i18n.t("Prism finished the work"), parent=parent,
                         leading=pad, closable=False)
        self.setWindowTitle("All done")
        # Sized to what a single task actually produces. The old 460/560 pair
        # predated the header and footer bands; 520 left a band of bare canvas
        # under a three-step run, which reads as "something else was meant to
        # be here" on the one screen whose whole job is to say the work is
        # finished.
        self.resize(720, 620 if multi else 470)
        outer = self.body
        outer.setSpacing(theme.SPACE_3)

        rows = task_groups if multi else [{"stages": stage_infos}]
        every = [s for g in rows for s in g.get("stages", [])]
        pending = [i for i in every
                   if i.get("timed_out") or (not i.get("ok", True) and i.get("url"))]
        if multi:
            lead = (f"All {len(task_groups)} tasks are done — here's what each "
                    f"one used and what it produced.")
        else:
            lead = "Here's what each step produced — open only the ones you need."
        if pending:
            lead += (f" {len(pending)} step(s) ran past Prism's wait — their "
                     "tools are still working, so open those links to collect "
                     "the finished result.")
        self.header.set_subtitle(lead)

        # A ten-task run is far taller than any screen, so the body scrolls.
        body_host = QWidget()
        root = QVBoxLayout(body_host)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(13)
        for group in rows:
            if multi:
                root.addWidget(_TaskHeader(group))
            for info in group.get("stages", []):
                root.addWidget(_StageRow(info))
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body_host)
        outer.addWidget(scroll, stretch=1)

        # Same result as the QDialogButtonBox it replaces — Close called
        # accept(), not reject() — without Qt's platform icons riding along.
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))

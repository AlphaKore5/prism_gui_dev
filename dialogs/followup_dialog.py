"""Follow up — the refinement step after a whole task has finished.

When a task completes, Prism offers this: inspect the deliverables produced,
then either accept them and be done ("No, I'm done"), or type an adjustment and
(optionally) attach files. Prism routes that follow-up to whichever step's
assigned agent it is actually about — automatically, without requiring manual
agent selection.

The dialog is designed to handle tasks producing 1 to 20+ files cleanly:
- Primary deliverables (videos, voiceover audio, documents) are highlighted up front.
- Secondary assets (scene artwork sets, metadata JSONs) are neatly grouped and collapsible.
- Spacious follow-up text input with Ctrl+Enter keyboard submission.
- Scrollable body so no controls or text ever get crushed or clipped.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

import i18n
import paths
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.markdown import render_markdown


def _format_size(path: str) -> str:
    try:
        kb = os.path.getsize(path) / 1024
        return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb:.0f} KB"
    except OSError:
        return ""


def _classify_artifacts(paths_list: list[str]) -> tuple[list[dict], list[dict]]:
    """Partition artifacts into primary deliverables (videos, audios, documents)
    and secondary/supporting assets (scene artwork, metadata JSONs)."""
    video_exts = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
    audio_exts = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
    doc_exts = {".pdf", ".docx", ".xlsx", ".csv", ".pptx", ".html"}
    image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    has_video_or_audio = any(
        os.path.splitext(p)[1].lower() in (video_exts | audio_exts | doc_exts)
        for p in paths_list)

    primaries: list[dict] = []
    secondaries: list[dict] = []

    for p in paths_list:
        ext = os.path.splitext(p)[1].lower()
        size = _format_size(p)
        name = os.path.basename(p)

        if ext in video_exts:
            primaries.append({"path": p, "name": name, "size": size, "type": "video", "icon": "video"})
        elif ext in audio_exts:
            primaries.append({"path": p, "name": name, "size": size, "type": "audio", "icon": "mic"})
        elif ext in doc_exts:
            primaries.append({"path": p, "name": name, "size": size, "type": "doc", "icon": "file"})
        elif ext in image_exts:
            if not has_video_or_audio:
                # If no video/audio/doc, image IS the primary deliverable
                primaries.append({"path": p, "name": name, "size": size, "type": "image", "icon": "image"})
            else:
                secondaries.append({"path": p, "name": name, "size": size, "type": "image", "icon": "image"})
        else:
            secondaries.append({
                "path": p, "name": name, "size": size, "type": "file",
                "icon": "code" if ext == ".json" else "file",
            })

    return primaries, secondaries


class _FollowupTextEdit(QTextEdit):
    """QTextEdit that triggers submission on Ctrl+Enter or Cmd+Enter."""

    def __init__(self, submit_callback=None, text_change_callback=None, parent=None):
        super().__init__(parent)
        self._submit_callback = submit_callback
        self._text_change_callback = text_change_callback
        self.setObjectName("followupInput")
        self.textChanged.connect(self._on_changed)
        self._set_default_style()

    def _set_default_style(self):
        self.setStyleSheet(f"""
            #followupInput {{
                background: {theme.NEUTRAL[100]};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.R_CONTROL}px;
                padding: 10px 12px;
                font-size: 13px;
                color: {theme.TEXT};
            }}
            #followupInput:focus {{
                background: #ffffff;
                border: 1.5px solid {theme.ACCENT};
            }}
        """)

    def mark_error(self):
        self.setStyleSheet(f"""
            #followupInput {{
                background: {theme.NEUTRAL[100]};
                border: 1.5px solid {theme.ERR_INK};
                border-radius: {theme.R_CONTROL}px;
                padding: 10px 12px;
                font-size: 13px;
                color: {theme.TEXT};
            }}
        """)

    def _on_changed(self):
        self._set_default_style()
        if self._text_change_callback:
            self._text_change_callback()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier)):
            if self._submit_callback:
                self._submit_callback()
                return
        super().keyPressEvent(event)


class FollowupDialog(PrismDialog):
    """Post-completion refinement. Read submitted()/followup_text()/file_paths()
    after exec()."""

    def __init__(self, result_summary: str = "", parent=None,
                 artifacts: list[str] | None = None,
                 quick_actions: list[tuple[str, str, str]] | None = None):
        super().__init__(
            i18n.t("Anything to change?"),
            i18n.t("The task is done. Tell Prism what to adjust and it will "
                   "send your note to the right step — or close this if it's "
                   "good."),
            icon="sparkles", parent=parent, scrollable=True, closable=False)
        self.setWindowTitle(i18n.t("Follow up"))
        self.resize(720, 680)
        self.setMinimumSize(580, 520)

        self._submitted = False
        self._quick_key = ""
        self._paths: list[str] = []
        self._artifacts = [p for p in (artifacts or []) if p
                           and not p.endswith(".link.txt") and os.path.isfile(p)]

        root = self.body
        root.setSpacing(16)

        # ── 1. WHAT PRISM PRODUCED (DELIVERABLES) ─────────────────────────
        if self._artifacts:
            root.addWidget(self._build_deliverables_section())

        # ── 2. YOUR FOLLOW-UP (HERO INPUT) ────────────────────────────────
        root.addWidget(self._build_followup_input_section())

        # ── 3. RUN NOTES / RECAP (IF ANY) ─────────────────────────────────
        if result_summary:
            root.addWidget(self._build_summary_section(result_summary))

        # ── FOOTER ACTIONS ────────────────────────────────────────────────
        self.footer.add_utility(
            self.button(i18n.t("Add files"), icon_name="paperclip",
                        on_click=self._add_files))
        if self._artifacts:
            self.footer.add_utility(
                self.button(i18n.t("Open folder"), icon_name="folder",
                            on_click=self._open_artifacts_folder))
        for key, label, prompt in quick_actions or []:
            self.footer.add_utility(
                self.button(label, icon_name="check",
                            on_click=lambda _=False, k=key, p=prompt: self._quick(k, p)))
        self.footer.add_secondary(
            self.button(i18n.t("No, I'm done"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Send follow-up"), "primary",
                        icon_name="arrow-up", on_click=self._send,
                        tooltip="Ctrl+Enter"))

    # ── public result accessors ───────────────────────────────────────────
    def submitted(self) -> bool:
        return self._submitted

    def followup_text(self) -> str:
        return self._note.toPlainText().strip()

    def file_paths(self) -> list[str]:
        return list(self._paths)

    def chosen_quick(self) -> str:
        """The key of the one-click action pressed, or "" if none was."""
        return self._quick_key

    def _quick(self, key: str, prompt: str):
        self._quick_key = key
        self._note.setPlainText(prompt)
        self._note.setFocus()

    # ── UI builders ───────────────────────────────────────────────────────
    def _build_deliverables_section(self) -> QWidget:
        container = QFrame()
        container.setObjectName("deliverablesCard")
        container.setStyleSheet(f"""
            #deliverablesCard {{
                background: {theme.CARD};
                border: 1px solid {theme.HAIRLINE};
                border-radius: {theme.R_CONTROL}px;
                padding: 12px;
            }}
        """)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # Section header
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(C.kicker(i18n.t("WHAT PRISM PRODUCED")), stretch=1)

        count_badge = QLabel(i18n.t("{n} items").format(n=len(self._artifacts)))
        count_badge.setObjectName("meta")
        top_row.addWidget(count_badge)
        lay.addLayout(top_row)

        primaries, secondaries = _classify_artifacts(self._artifacts)

        # Render primary deliverables (videos, voiceover audio, docs)
        for item in primaries:
            lay.addWidget(self._deliverable_row(item, is_primary=True))

        # Render secondary assets (e.g. 5 artwork scene pngs, json files)
        if secondaries:
            if len(secondaries) <= 2:
                for item in secondaries:
                    lay.addWidget(self._deliverable_row(item, is_primary=False))
            else:
                lay.addWidget(self._grouped_secondaries_widget(secondaries))

        return container

    def _deliverable_row(self, item: dict, is_primary: bool = True) -> QWidget:
        row = QFrame()
        row.setObjectName("delivRow")
        row.setStyleSheet(f"""
            #delivRow {{
                background: {theme.WELL if is_primary else "transparent"};
                border: 1px solid {theme.BORDER if is_primary else theme.HAIRLINE};
                border-radius: {theme.R_CONTROL - 2}px;
                padding: 6px 10px;
            }}
        """)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(10)

        # Icon glyph
        icon_lbl = QLabel()
        icon_color = theme.ACCENT if is_primary else theme.NEUTRAL[500]
        icon_lbl.setPixmap(icons.pixmap(item["icon"], 18, icon_color))
        lay.addWidget(icon_lbl)

        # Title & size details
        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(1)

        name_lbl = QLabel(item["name"])
        name_lbl.setStyleSheet(f"font-weight: {'600' if is_primary else '500'}; font-size: 13px; color: {theme.TEXT};")
        name_lbl.setWordWrap(True)
        info_col.addWidget(name_lbl)

        if item.get("size"):
            size_lbl = QLabel(item["size"])
            size_lbl.setObjectName("meta")
            info_col.addWidget(size_lbl)
        lay.addLayout(info_col, stretch=1)

        # Action buttons
        path = item["path"]
        open_btn = self.button(
            i18n.t("Open"), icon_name="external", small=True,
            on_click=lambda *_, p=path: paths.open_result(p))
        lay.addWidget(open_btn)

        folder_btn = self.button(
            i18n.t("Folder"), icon_name="folder", small=True,
            on_click=lambda *_, p=path: paths.reveal_result(p))
        lay.addWidget(folder_btn)

        return row

    def _grouped_secondaries_widget(self, secondaries: list[dict]) -> QWidget:
        wrap = QFrame()
        wrap.setObjectName("groupedSecondaries")
        wrap.setStyleSheet(f"""
            #groupedSecondaries {{
                background: {theme.WELL};
                border: 1px dashed {theme.BORDER};
                border-radius: {theme.R_CONTROL - 2}px;
            }}
        """)
        v_lay = QVBoxLayout(wrap)
        v_lay.setContentsMargins(8, 6, 8, 6)
        v_lay.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)

        icon_lbl = QLabel()
        icon_lbl.setPixmap(icons.pixmap("image", 16, theme.NEUTRAL[600]))
        header_row.addWidget(icon_lbl)

        img_count = sum(1 for s in secondaries if s["type"] == "image")
        desc = (i18n.t("{n} supporting images & assets").format(n=len(secondaries))
                if img_count else i18n.t("{n} supporting assets").format(n=len(secondaries)))
        label = QLabel(desc)
        label.setObjectName("meta")
        header_row.addWidget(label, stretch=1)

        # Expand / collapse toggle
        toggle_btn = QPushButton(i18n.t("Show all ({n}) ▾").format(n=len(secondaries)))
        toggle_btn.setObjectName("smallBtn")
        header_row.addWidget(toggle_btn)
        v_lay.addLayout(header_row)

        # Collapsible child list
        list_container = QWidget()
        list_lay = QVBoxLayout(list_container)
        list_lay.setContentsMargins(0, 4, 0, 2)
        list_lay.setSpacing(4)
        for item in secondaries:
            list_lay.addWidget(self._deliverable_row(item, is_primary=False))
        list_container.setVisible(False)
        v_lay.addWidget(list_container)

        def _toggle():
            vis = not list_container.isVisible()
            list_container.setVisible(vis)
            toggle_btn.setText(
                i18n.t("Hide ▴") if vis
                else i18n.t("Show all ({n}) ▾").format(n=len(secondaries)))

        toggle_btn.clicked.connect(_toggle)
        return wrap

    def _build_followup_input_section(self) -> QWidget:
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        hdr_row = QHBoxLayout()
        hdr_row.setContentsMargins(0, 0, 0, 0)
        hdr_row.addWidget(C.kicker(i18n.t("YOUR FOLLOW-UP INSTRUCTION")), stretch=1)
        shortcut_hint = QLabel("Ctrl+Enter ↵")
        shortcut_hint.setObjectName("meta")
        hdr_row.addWidget(shortcut_hint)
        lay.addLayout(hdr_row)

        self._note = _FollowupTextEdit(submit_callback=self._send, parent=self)
        self._note.setPlaceholderText(
            i18n.t("e.g. Make the voiceover faster · Brighten scene 3 artwork · "
                   "Shorten the hook… (Press Ctrl+Enter to send)"))
        self._note.setMinimumHeight(110)
        self._note.setMaximumHeight(160)
        lay.addWidget(self._note)

        # Dynamic attachment chips container
        self._att_wrap = QWidget()
        self._att_lay = QHBoxLayout(self._att_wrap)
        self._att_lay.setContentsMargins(0, 2, 0, 0)
        self._att_lay.setSpacing(6)
        self._att_wrap.setVisible(False)
        lay.addWidget(self._att_wrap)

        return wrap

    def _build_summary_section(self, result_summary: str) -> QWidget:
        container = QFrame()
        container.setObjectName("summaryCard")
        container.setStyleSheet(f"""
            #summaryCard {{
                background: {theme.WELL};
                border: 1px solid {theme.HAIRLINE};
                border-radius: {theme.R_CONTROL}px;
                padding: 8px 12px;
            }}
        """)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.addWidget(C.kicker(i18n.t("NOTES FROM THE RUN")), stretch=1)

        toggle_btn = QPushButton(i18n.t("Hide ▴"))
        toggle_btn.setObjectName("smallBtn")
        header_row.addWidget(toggle_btn)
        lay.addLayout(header_row)

        recap = QTextEdit()
        recap.setReadOnly(True)
        recap.setPlainText(result_summary)
        recap.setFixedHeight(100)
        recap.setStyleSheet(f"""
            background: transparent;
            border: none;
            color: {theme.NEUTRAL[700]};
            font-size: 12px;
        """)
        lay.addWidget(recap)

        def _toggle():
            vis = not recap.isVisible()
            recap.setVisible(vis)
            toggle_btn.setText(i18n.t("Hide ▴") if vis else i18n.t("View ▾"))

        toggle_btn.clicked.connect(_toggle)
        return container

    # ── attachment management ─────────────────────────────────────────────
    def _add_files(self):
        paths_selected, _ = QFileDialog.getOpenFileNames(
            self, i18n.t("Add files"), paths.picker_start_dir())
        for p in paths_selected:
            if p and p not in self._paths:
                self._paths.append(p)
        self._update_attachments_ui()

    def _remove_file(self, path: str):
        if path in self._paths:
            self._paths.remove(path)
        self._update_attachments_ui()

    def _update_attachments_ui(self):
        while self._att_lay.count():
            item = self._att_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._paths:
            self._att_wrap.setVisible(False)
            return

        label = QLabel(i18n.t("Attached: "))
        label.setObjectName("meta")
        self._att_lay.addWidget(label)

        for p in self._paths:
            chip = QFrame()
            chip.setStyleSheet(f"""
                background: {theme.WELL};
                border: 1px solid {theme.BORDER};
                border-radius: 12px;
                padding: 2px 6px;
            """)
            c_lay = QHBoxLayout(chip)
            c_lay.setContentsMargins(6, 2, 6, 2)
            c_lay.setSpacing(4)

            name = os.path.basename(p)
            nlbl = QLabel(name)
            nlbl.setStyleSheet(f"font-size: 11px; color: {theme.TEXT};")
            c_lay.addWidget(nlbl)

            del_btn = QPushButton("×")
            del_btn.setFixedSize(16, 16)
            del_btn.setStyleSheet("""
                QPushButton {
                    border: none;
                    background: transparent;
                    color: #71717a;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover {
                    color: #dc2626;
                }
            """)
            del_btn.clicked.connect(lambda _, path_to_rm=p: self._remove_file(path_to_rm))
            c_lay.addWidget(del_btn)
            self._att_lay.addWidget(chip)

        self._att_lay.addStretch(1)
        self._att_wrap.setVisible(True)

    def _open_artifacts_folder(self):
        if self._artifacts:
            paths.reveal_result(self._artifacts[0])
        else:
            paths.open_result(paths.user_dir("runs"))

    def _send(self):
        if not self.followup_text() and not self._paths:
            self._note.setFocus()
            self._note.mark_error()
            return
        self._submitted = True
        self.accept()

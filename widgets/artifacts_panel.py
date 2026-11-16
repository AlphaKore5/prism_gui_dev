"""Artifacts — every generated file Prism has copied out to a place you can
still find it once the app that made it is closed.

Reel renders, and any pipeline stage that produces a real image, document,
deck or code file, save a copy into config.ARTIFACTS_DIR (see that module) —
named after the prompt that made them, not a run id. When a caller passes
`task=`, everything that one New Task (or BOQ/Gerber/quote job) produced
lands in its own subfolder there instead — one row here, opened in
Finder/Explorer rather than browsed inline. Before this screen, that folder
only existed on disk: the one way to know it was there was to be told, or to
stumble on it in Finder/Explorer. This is Prism saying so.

Read straight off the folder each time the screen is shown — it is plain
files on disk, and the user's own Finder/Explorer can add to or remove from
it between visits just as freely as Prism can. Same LAZY-plus-explicit-
refresh contract History uses: MainWindow._show_screen() calls refresh() on
arrival rather than this class reloading itself, so it stays a passive report
like every other screen here.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

import core_bridge as CB
import i18n
import theme
from widgets import controls as C
from widgets.files_panel import kind_label, size_label
from widgets.panel_base import Page, bucket_for

# Extension -> the same "kind" vocabulary core.files.attach() uses, so
# kind_label() (built for attachment chips) reads correctly here too without
# running every file in the folder through the heavier attach() pipeline just
# to list them.
_KINDS = {
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".webp": "image",
    ".mp4": "video", ".mov": "video", ".webm": "video",
    ".pdf": "pdf",
    ".doc": "doc", ".docx": "doc", ".odt": "doc",
    ".xls": "sheet", ".xlsx": "sheet", ".csv": "sheet", ".ods": "sheet",
    ".ppt": "presentation", ".pptx": "presentation", ".odp": "presentation",
    ".py": "code", ".js": "code", ".ts": "code", ".tsx": "code",
    ".jsx": "code", ".json": "code", ".html": "code", ".css": "code",
    ".txt": "text", ".md": "text",
}
# kind_label()'s own vocabulary is narrower than the table above (it has no
# "presentation" word yet) — fall back to "file" rather than an untranslated
# label reaching the screen.
_ICON_FOR_KIND = {"image": "image", "video": "video", "code": "code"}

_THUMB = 38   # the preview's .thumbsm tile


def _thumbnail(path: str):
    """A real rounded-corner crop of the image itself, for the row's leading
    slot — a generic file glyph can't tell two pictures apart, and in a
    folder that's mostly pictures, telling them apart at a glance is most of
    what looking at the list is for. Returns None (falls back to the usual
    glyph) for anything that isn't a real, decodable image."""
    src = QPixmap(path)
    if src.isNull():
        return None
    src = src.scaled(_THUMB, _THUMB, Qt.KeepAspectRatioByExpanding,
                     Qt.SmoothTransformation)
    x = max(0, (src.width() - _THUMB) // 2)
    y = max(0, (src.height() - _THUMB) // 2)
    src = src.copy(x, y, _THUMB, _THUMB)
    out = QPixmap(_THUMB, _THUMB)
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(0, 0, _THUMB, _THUMB, 9, 9)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, src)
    painter.end()
    label = QLabel()
    label.setFixedSize(_THUMB, _THUMB)
    label.setPixmap(out)
    return label


def _tile(icon: str):
    """The preview's file tile: ink line glyph on a soft stone square."""
    pad = C.IconPad(icon, theme.INK, _THUMB, 9, 15)
    pad.setStyleSheet("background: #EFEEEA; border-radius: 9px;")
    return pad


def _open_button(on_click):
    """The preview's per-row "Open" pill (same slot, same handler as the old
    glyph-only button; the tooltip stays)."""
    btn = C.button(i18n.t("Open"), "secondary", icon_name="external",
                   small=True, on_click=on_click)
    btn.setProperty("pill", True)
    btn.setToolTip(i18n.t("Open"))
    return btn


import re as _re

# A run folder's name: the stamp config.begin_run() gives it.
_RUN_STAMP = _re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}( \(\d+\))?$")


def _run_time(run_dir: str) -> str:
    """"16:18" off a run folder named "2026-09-07 16-18"."""
    m = _re.match(r"^\d{4}-\d{2}-\d{2} (\d{2})-(\d{2})", os.path.basename(run_dir))
    return f"{m.group(1)}:{m.group(2)}" if m else os.path.basename(run_dir)


def _folder_stats(path: str) -> tuple[int, str]:
    """File count and total size of everything under a task subfolder —
    config.artifact_task_dir()'s folders can themselves hold nested folders
    (Gerber's cleaned-copy output keeps its own "previews/" subfolder), so
    this walks rather than assuming one flat level."""
    count, total = 0, 0.0
    for root, _dirs, names in os.walk(path):
        for name in names:
            if name.endswith(".link.txt") or name == CB.config.ABOUT_FILE:
                continue
            count += 1
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    size = ""
    for unit in ("B", "KB", "MB", "GB"):
        if total < 1024 or unit == "GB":
            size = f"{total:.0f} {unit}" if unit == "B" else f"{total:.1f} {unit}"
            break
        total /= 1024.0
    return count, size


def _editable_reel(path: str) -> bool:
    """A video with a Studio spec saved beside it — reel_<stamp>.json next
    to reel_<stamp>.mp4, scenes carrying real HTML. Same check
    widgets.output_panel.StageCard._editable_reel makes on a just-finished
    run's card — this is the same fact read off disk instead of off a
    fresh render, so a reel found here days later is just as editable."""
    if not path.lower().endswith(".mp4"):
        return False
    try:
        import json as _json
        with open(path[:-4] + ".json", encoding="utf-8") as f:
            spec = _json.load(f)
        return CB.get_reel_edit().is_studio_spec(spec)
    except Exception:                                   # noqa: BLE001
        return False


def _chat_link(path: str) -> str:
    """The AI conversation this artifact came from, if save_artifact() had
    one to record — see config.save_artifact's `link` param. Empty for a
    local render (Reel, Motion) that was never a chat to begin with."""
    sidecar = path + ".link.txt"
    if not os.path.isfile(sidecar):
        return ""
    try:
        with open(sidecar, "r", encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


class ArtifactsPanel(Page):
    TITLE = "Artifacts"
    BLURB = ("Everything Prism has generated for you — reels, images, "
             "documents — kept here even after you close it.")
    LAZY = True

    # A Studio reel found here wants fixing by hand, same as one still on
    # the workbench. Carries the mp4 path; MainWindow owns the browser
    # editor and re-render (see _edit_reel_layout), so this row only asks.
    edit_reel = Signal(str)

    def header_actions(self) -> list:
        return [C.button(i18n.t("Open the folder"), "secondary",
                         icon_name="folder", small=True,
                         on_click=self._open_folder)]

    def _open_folder(self):
        folder = CB.config.artifacts_root()
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def build(self):
        # artifacts_root(), not ARTIFACTS_DIR: the folder that is actually
        # written on this machine, which on a Mac that refused Desktop
        # access is the fallback under the home folder.
        folder = CB.config.artifacts_root()
        paths = []
        self._labels: dict[str, str] = {}
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                # A ".link.txt" is the sidecar save_artifact() writes next to
                # the file it belongs to (see config.save_artifact) — the
                # chat's URL, not a deliverable of its own, so it rides along
                # on its artifact's row (_row, below) instead of getting one.
                if name.endswith(".link.txt"):
                    continue
                # Skip json specs that accompany an mp4 reel
                if name.endswith(".json") and os.path.isfile(os.path.join(folder, os.path.splitext(name)[0] + ".mp4")):
                    continue
                path = os.path.join(folder, name)
                if os.path.isfile(path):
                    paths.append(path)
                    continue
                if not os.path.isdir(path):
                    continue
                # A task's folder holds one subfolder per RUN (see
                # config.begin_run) — and each run is its own card here,
                # named for the task and the time, so two runs of the same
                # words never read as one. A task folder from before runs
                # were separated (files loose in it) stays one card.
                runs = [os.path.join(path, n) for n in os.listdir(path)
                        if _RUN_STAMP.match(n)
                        and os.path.isdir(os.path.join(path, n))]
                loose = [n for n in os.listdir(path)
                         if not os.path.isdir(os.path.join(path, n))
                         and not n.endswith(".link.txt")
                         and not (n.endswith(".json") and os.path.isfile(os.path.join(path, os.path.splitext(n)[0] + ".mp4")))]
                for run in runs:
                    self._labels[run] = f"{name}  ·  {_run_time(run)}"
                    paths.append(run)
                if loose or not runs:
                    paths.append(path)
        if not paths:
            self._col.addWidget(C.EmptyState(
                "file", i18n.t("Nothing generated yet"),
                i18n.t("Run Reel/Studio, or any task that produces an "
                       "image, document or code file, and it lands here — "
                       "named after what you asked for.")), stretch=1)
            return
        # Newest first: the thing you just generated is the thing you came
        # here to check. Grouped by day, with the same bucket labels History
        # already uses — a flat mtime-sorted dump was the actual complaint,
        # and this is the app's own established pattern for a date-ordered
        # list, not a second, divergent one invented just for this screen.
        paths.sort(key=os.path.getmtime, reverse=True)
        groups: list[tuple[str, list]] = []
        for path in paths:
            bucket = bucket_for("", os.path.getmtime(path))
            if not groups or groups[-1][0] != bucket:
                groups.append((bucket, []))
            groups[-1][1].append(path)

        for n, (bucket, items) in enumerate(groups):
            head = C.SectionHeader(
                i18n.t(bucket),
                (i18n.t("1 file") if len(items) == 1
                 else i18n.t("{n} files").format(n=len(items))).upper())
            head.subtitle.setProperty("mono", True)
            # Same day-heading rhythm as History (the preview's .day).
            head.layout().setContentsMargins(4, 6 if n == 0 else 17, 4, 10)
            self._col.addWidget(head)
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)
            for i, path in enumerate(items):
                if i:
                    col.addWidget(C.hairline())
                col.addWidget(self._row(path))
            self._col.addWidget(card)
        self._col.addStretch(1)

    def _row(self, path: str) -> C.FileItem:
        if os.path.isdir(path):
            return self._folder_row(path)
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        kind = _KINDS.get(ext, "")
        # `name` too, not just `kind` — kind_label() falls back to the
        # extension for a kind it has no word for yet (e.g. "presentation"),
        # and that fallback reads the name/path itself, not the kind we
        # already tried to derive from it.
        detail = " · ".join(p for p in (kind_label({"kind": kind, "name": name}),
                                        size_label(path)) if p)
        actions = [_open_button(lambda _=False, p=path: self._open_file(p))]
        if kind == "video" and _editable_reel(path):
            actions.append(C.icon_button(
                "pencil", i18n.t("Edit the layout"),
                lambda _=False, p=path: self.edit_reel.emit(p)))
        link = _chat_link(path)
        if link:
            actions.append(C.icon_button(
                "globe", i18n.t("Open the chat that made this"),
                lambda _=False, u=link: self._open_link(u)))
        leading = ((_thumbnail(path) if kind == "image" else None)
                   or _tile(_ICON_FOR_KIND.get(kind, "file")))
        row = C.FileItem(name, detail, _ICON_FOR_KIND.get(kind, "file"),
                         actions, leading=leading, flat=True)
        row.setToolTip(path)
        row.activated.connect(lambda p=path: self._open_file(p))
        return row

    def _folder_row(self, path: str) -> C.FileItem:
        name = getattr(self, "_labels", {}).get(path) or os.path.basename(path)
        count, size = _folder_stats(path)
        files_word = (i18n.t("1 file") if count == 1
                     else i18n.t("{n} files").format(n=count))
        detail = " · ".join(p for p in (files_word, size) if p)

        single_target = self._single_deliverable(path)
        target_path = single_target if single_target else path

        actions = [_open_button(
            lambda _=False, p=target_path: self._open_file(p))]

        reel_target = (single_target if single_target and single_target.lower().endswith(".mp4") and _editable_reel(single_target)
                       else self._primary_reel(path))
        if reel_target and _editable_reel(reel_target):
            actions.append(C.icon_button(
                "pencil", i18n.t("Edit the layout"),
                lambda _=False, p=reel_target: self.edit_reel.emit(p)))

        link = _chat_link(single_target) if single_target else _chat_link(path)
        if link:
            actions.append(C.icon_button(
                "globe", i18n.t("Open the chat that made this"),
                lambda _=False, u=link: self._open_link(u)))

        icon = "folder"
        leading = None
        if single_target:
            ext = os.path.splitext(single_target)[1].lower()
            kind = _KINDS.get(ext, "")
            icon = _ICON_FOR_KIND.get(kind, "folder")
            if kind == "image":
                leading = _thumbnail(single_target)

        row = C.FileItem(name, detail, icon, actions,
                         leading=leading or _tile(icon), flat=True)
        row.setToolTip(path)
        row.activated.connect(lambda p=target_path: self._open_file(p))
        return row

    @staticmethod
    def _single_deliverable(folder: str) -> str | None:
        """If a task/run folder contains exactly one primary deliverable file,
        return its path directly so clicking opens it instead of an empty or
        intermediate 1-file folder view."""
        try:
            files = []
            for root, _dirs, names in os.walk(folder):
                for n in names:
                    if n.endswith(".link.txt") or n == CB.config.ABOUT_FILE:
                        continue
                    if n.endswith(".json") and os.path.isfile(os.path.join(root, os.path.splitext(n)[0] + ".mp4")):
                        continue
                    files.append(os.path.join(root, n))
            return files[0] if len(files) == 1 else None
        except Exception:
            return None

    @staticmethod
    def _primary_reel(folder: str) -> str | None:
        """Find the main editable reel .mp4 in a run folder (if any)."""
        try:
            candidates = []
            for root, _dirs, names in os.walk(folder):
                for n in names:
                    if n.lower().endswith(".mp4"):
                        p = os.path.join(root, n)
                        if _editable_reel(p):
                            candidates.append(p)
            if candidates:
                candidates.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
                return candidates[0]
        except Exception:
            pass
        return None

    def _open_file(self, path: str):
        # In-app, not handed to the OS — see dialogs/preview_dialog.py's own
        # note on why an Artifact gets different treatment than an ordinary
        # attachment chip. Only a real chat URL (_open_link, below) still
        # leaves the window.
        from dialogs.preview_dialog import open_preview
        open_preview(path, self)

    @staticmethod
    def _open_link(url: str):
        QDesktopServices.openUrl(QUrl(url))

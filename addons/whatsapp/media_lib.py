"""The Media Library on screen — the files a workspace sends, kept once and used everywhere.

    LibraryView          the grid: search, kind filter, upload, storage used. Pick mode chooses one; manage mode also deletes and saves a copy.
    MediaLibraryDialog   the grid in a dialog; `.asset` is what was chosen (the paperclip in a chat, a template's picture, a saved reply)
    AssetField           "no file / name · size · Change · Remove" — the control a form puts where it wants one file
    fetch()              one file's bytes (cached): thumbnails, opening, saving
    upload_paths()       read local files and send them to the library, one after another
    open_asset() / save_asset()   what a click on a file in a chat does

Everything that talks to the server runs through ui.call, so no screen waits on a file.
"""
from __future__ import annotations

import base64
import mimetypes
import os
import re
import tempfile
from collections import OrderedDict

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import ui
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons

MB = 1024 * 1024
UPLOAD_CAP = 16 * MB                          # what the service accepts in one file
THUMB = 88
_CACHE_BYTES = 24 * MB
_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
KIND_ICON = {"image": "image", "sticker": "image", "video": "video", "audio": "mic", "document": "file-text"}


def kind_choices() -> list:
    """(kind, label). Literal i18n.t calls, so the extractor sees every word."""
    return [("", i18n.t("All")), ("image", i18n.t("Pictures")), ("video", i18n.t("Videos")), ("audio", i18n.t("Audio")), ("document", i18n.t("Documents"))]


def kind_name(kind: str) -> str:
    return {"image": i18n.t("Picture"), "sticker": i18n.t("Sticker"), "video": i18n.t("Video"), "audio": i18n.t("Voice note"),
            "document": i18n.t("Document")}.get(kind or "", i18n.t("File"))


def size_text(n) -> str:
    n = int(n or 0)
    if n >= 1024 * MB:
        return "%.1f GB" % (n / (1024 * MB))
    if n >= MB:
        return "%.1f MB" % (n / MB)
    if n >= 1024:
        return "%d KB" % round(n / 1024)
    return "%d B" % n


def quota_text(q: dict) -> str:
    used = int((q or {}).get("used") or 0)
    limit = (q or {}).get("limit")
    if limit is None:
        return i18n.t("{used} used · no limit on your plan").format(used=size_text(used))
    return i18n.t("{used} of {limit} used").format(used=size_text(used), limit=size_text(limit))


def safe_name(name: str, fallback: str = "file") -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", os.path.basename(name or "")).strip(" .") or fallback
    return name[:120]


# ── fetching ─────────────────────────────────────────────────────────────────

def _remember(asset_id: str, asset: dict, data: bytes) -> None:
    _CACHE[asset_id] = (asset, data)
    _CACHE.move_to_end(asset_id)
    while len(_CACHE) > 1 and sum(len(v[1]) for v in _CACHE.values()) > _CACHE_BYTES:
        _CACHE.popitem(last=False)


def forget(asset_id: str) -> None:
    _CACHE.pop(str(asset_id), None)


def cached(asset_id: str):
    return _CACHE.get(str(asset_id))


def fetch(owner, asset_id: str, done, failed=None, max_bytes: int = 0) -> None:
    """done(asset, bytes_or_None). bytes is None when the file is bigger than `max_bytes` (or than the service hands over in one go)."""
    hit = _CACHE.get(str(asset_id))
    if hit is not None and (not max_bytes or len(hit[1]) <= max_bytes):
        _CACHE.move_to_end(str(asset_id))
        done(hit[0], hit[1])
        return

    def got(reply: dict):
        asset, raw = reply.get("asset") or {}, reply.get("data")
        data = base64.b64decode(raw) if raw else None
        if data is not None:
            _remember(str(asset_id), asset, data)
        done(asset, data)
    ui.call(owner, "media/get", {"asset_id": asset_id, "max_bytes": max_bytes or None}, done=got,
            failed=failed or (lambda _m, _d: done({}, None)))


def pixmap_from(data: bytes) -> QPixmap:
    pm = QPixmap()
    pm.loadFromData(data)
    return pm


def tile_icon(kind: str) -> QIcon:
    """The picture for a file we cannot show (or have not fetched yet): a soft tile with the kind's glyph."""
    pm = QPixmap(THUMB, THUMB)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(theme.c(theme.NEUTRAL[100]))
    p.drawRoundedRect(0, 0, THUMB, THUMB, 12, 12)
    glyph = icons.pixmap(KIND_ICON.get(kind, "file"), 34, theme.NEUTRAL[600])
    p.drawPixmap((THUMB - 34) // 2, (THUMB - 34) // 2, glyph)
    p.end()
    return QIcon(pm)


def thumb_icon(data: bytes) -> QIcon | None:
    pm = pixmap_from(data)
    if pm.isNull():
        return None
    scaled = pm.scaled(THUMB, THUMB, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x, y = (scaled.width() - THUMB) // 2, (scaled.height() - THUMB) // 2
    return QIcon(scaled.copy(x, y, THUMB, THUMB))


# ── uploading ────────────────────────────────────────────────────────────────

def pick_paths(parent, kinds=None) -> list:
    paths, _f = QFileDialog.getOpenFileNames(parent, i18n.t("Choose files to upload"), "", i18n.t("Pictures, videos, audio and documents") +
                                             " (*.jpg *.jpeg *.png *.webp *.mp4 *.3gp *.mp3 *.m4a *.aac *.ogg *.amr *.pdf *.doc *.docx *.xls *.xlsx *.ppt *.pptx *.txt)")
    return list(paths or [])


def upload_paths(owner, paths: list, *, one_done, failed, finished=None) -> None:
    """Upload each file in turn. `one_done(reply)` after each that succeeds; `failed(filename, message)` for each that does not."""
    queue = list(paths)

    def step():
        if not queue:
            if finished:
                finished()
            return
        path = queue.pop(0)
        name = safe_name(path)
        try:
            with open(path, "rb") as fh:
                data = fh.read(UPLOAD_CAP + 1)
        except OSError as exc:
            failed(name, i18n.t("Couldn't read it: {e}").format(e=exc))
            return step()
        if len(data) > UPLOAD_CAP:
            failed(name, i18n.t("That file is over 16 MB, the most that can be sent."))
            return step()
        ui.call(owner, "media/upload", {"filename": name, "mime": mimetypes.guess_type(path)[0] or "", "data": base64.b64encode(data).decode("ascii"),
                                        "_timeout": 120},
                done=lambda r: (one_done(r), step()), failed=lambda m, _d, n=name: (failed(n, m), step()))
    step()


# ── opening a file from a chat ───────────────────────────────────────────────

def open_asset(owner, asset: dict, failed) -> None:
    """Fetch the file, put it in a temporary folder under its own name and hand it to whatever opens that kind of file here."""
    def got(meta, data):
        if data is None:
            return failed(i18n.t("That file is too big to open from here."))
        folder = os.path.join(tempfile.gettempdir(), "prism-wa-media", safe_name(str(asset.get("id")), "x"))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, safe_name(asset.get("filename") or meta.get("filename"), kind_name(asset.get("kind")).lower()))
        with open(path, "wb") as fh:
            fh.write(data)
        import paths
        paths.open_file(path, owner)
    fetch(owner, asset["id"], got, failed=lambda m, _d: failed(m))


def save_asset(owner, asset: dict, failed, parent=None) -> None:
    target, _f = QFileDialog.getSaveFileName(parent or owner, i18n.t("Save a copy"), safe_name(asset.get("filename"), "file"))
    if not target:
        return

    def got(_meta, data):
        if data is None:
            return failed(i18n.t("That file is too big to download from here."))
        try:
            with open(target, "wb") as fh:
                fh.write(data)
            C.show_toast(owner, i18n.t("Saved"), os.path.basename(target))
        except OSError as exc:
            failed(i18n.t("Couldn't save it: {e}").format(e=exc))
    fetch(owner, asset["id"], got, failed=lambda m, _d: failed(m))


# ── the grid ─────────────────────────────────────────────────────────────────

class LibraryView(QWidget):
    selected = Signal(object)          # the chosen asset (a dict), or None when nothing is
    activated = Signal(object)         # double-clicked
    changed = Signal()                 # a file was added or removed

    def __init__(self, manage: bool = False, kinds=None, parent=None):
        super().__init__(parent)
        self.manage = manage
        self.kinds = tuple(kinds) if kinds else None
        self._assets: list = []
        self._gen = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_2)
        self.search = C.SearchField(i18n.t("Search by file name"))
        self.search.changed.connect(lambda _t: self._later.start())
        bar.addWidget(self.search, stretch=1)
        self.upload_btn = C.button(i18n.t("Upload files"), "secondary", "upload", on_click=self._upload)
        bar.addWidget(self.upload_btn)
        root.addLayout(bar)

        options = [(k, label) for k, label in kind_choices() if not k or not self.kinds or k in self.kinds]
        self.chips = C.FilterChips(options, "")
        self.chips.changed.connect(lambda _k: (self.note.clear_note(), self.reload()))
        root.addWidget(self.chips)
        self.chips.setVisible(len(options) > 2)

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setWrapping(True)
        self.grid.setUniformItemSizes(True)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(124, THUMB + 46))
        self.grid.setSpacing(4)
        self.grid.setWordWrap(True)
        self.grid.setTextElideMode(Qt.ElideMiddle)
        self.grid.setFrameShape(QFrame.NoFrame)
        self.grid.setMinimumHeight(132)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.setStyleSheet("QListWidget { background: transparent; } QListWidget::item { border-radius: 10px; padding: 4px; }"
                                f" QListWidget::item:selected {{ background: {theme.NEUTRAL[100]}; color: {theme.TEXT}; }}")
        self.grid.currentItemChanged.connect(lambda cur, _prev: self._on_current(cur))
        self.grid.itemDoubleClicked.connect(lambda it: self.activated.emit(it.data(Qt.UserRole)))
        root.addWidget(self.grid, stretch=1)

        self.empty = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        self.empty.setAlignment(Qt.AlignCenter)
        root.addWidget(self.empty)

        self.note = ui.note()
        root.addWidget(self.note)

        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE_3)
        meter = QVBoxLayout()
        meter.setSpacing(4)
        self.quota_bar = C.ProgressBar(0.0)
        meter.addWidget(self.quota_bar)
        self.quota_label = C.label("", level="META", colour=theme.NEUTRAL[600])
        meter.addWidget(self.quota_label)
        foot.addLayout(meter, stretch=1)
        if manage:
            self.save_btn = C.button(i18n.t("Save a copy"), "secondary", "download", small=True, on_click=self._save)
            self.delete_btn = C.button(i18n.t("Delete"), "destructive", "trash", small=True, on_click=self._delete)
            for b in (self.save_btn, self.delete_btn):
                b.setEnabled(False)
                foot.addWidget(b)
        root.addLayout(foot)

        self._later = QTimer(self)
        self._later.setSingleShot(True)
        self._later.setInterval(280)
        self._later.timeout.connect(self.reload)

    def say(self, message: str, error: bool = False):
        (self.note.error if error else self.note.ok)(message)

    # ── data ─────────────────────────────────────────────────────────────────
    def reload(self):
        data = {"kind": self.chips.current() or None, "search": self.search.text().strip(), "limit": 200}
        ui.call(self, "media/list", data, done=self._loaded, failed=lambda m, _d: self.note.error(m))

    def _loaded(self, reply: dict):
        self._gen += 1
        gen = self._gen
        rows = [a for a in reply.get("assets") or [] if not self.kinds or a.get("kind") in self.kinds]
        self._assets = rows
        keep = (self.current() or {}).get("id")
        self.grid.blockSignals(True)
        self.grid.clear()
        fm = self.grid.fontMetrics()
        for a in rows:
            item = QListWidgetItem(tile_icon(a.get("kind")), fm.elidedText(a.get("filename") or "", Qt.ElideMiddle, 108))
            item.setData(Qt.UserRole, a)
            item.setToolTip("%s\n%s · %s" % (a.get("filename") or "", kind_name(a.get("kind")), size_text(a.get("size"))))
            item.setSizeHint(QSize(124, THUMB + 46))
            self.grid.addItem(item)
            if a.get("id") == keep:
                self.grid.setCurrentItem(item)
        self.grid.blockSignals(False)
        self._on_current(self.grid.currentItem())
        searching = bool(self.search.text().strip() or self.chips.current())
        self.empty.setText("" if rows else (i18n.t("No file matches that.") if searching else
                                            i18n.t("Nothing here yet. Upload a picture, video, voice note or document and it can be sent from any chat, "
                                                   "campaign or auto-reply.")))
        self.empty.setVisible(not rows)
        q = reply.get("quota") or {}
        limit = q.get("limit")
        self.quota_bar.set_fraction((int(q.get("used") or 0) / limit) if limit else 0.0)
        self.quota_label.setText(quota_text(q))
        for a in rows:
            if a.get("kind") == "image" and int(a.get("size") or 0) <= 1500 * 1024:
                fetch(self, a["id"], lambda meta, data, aid=a["id"], g=gen: self._thumb(g, aid, data), max_bytes=1500 * 1024)

    def _thumb(self, gen: int, asset_id: str, data):
        if gen != self._gen or not data:
            return
        icon = thumb_icon(data)
        if icon is None:
            return
        for i in range(self.grid.count()):
            item = self.grid.item(i)
            if (item.data(Qt.UserRole) or {}).get("id") == asset_id:
                item.setIcon(icon)
                return

    def current(self):
        item = self.grid.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _on_current(self, item):
        asset = item.data(Qt.UserRole) if item is not None else None
        if self.manage:
            self.save_btn.setEnabled(asset is not None)
            self.delete_btn.setEnabled(asset is not None)
        self.selected.emit(asset)

    # ── actions ──────────────────────────────────────────────────────────────
    def _upload(self):
        paths = pick_paths(self, self.kinds)
        if not paths:
            return
        self.upload_btn.setEnabled(False)
        done, bad = [], []
        self.note.set(i18n.t("Uploading…"), "quiet")

        def finish():
            self.upload_btn.setEnabled(True)
            if bad:
                self.note.error("; ".join("%s: %s" % b for b in bad[:3]))
            else:
                self.note.ok(i18n.t("Uploaded {n}.").format(n=len(done)) if len(done) != 1 else i18n.t("Uploaded."))
            self.reload()
            self.changed.emit()
        upload_paths(self, paths, one_done=lambda r: done.append(r.get("asset") or {}), failed=lambda n, m: bad.append((n, m)), finished=finish)

    def pick_after_upload(self, asset_id: str):
        """Select a file by id once the list has loaded (the one just uploaded)."""
        for i in range(self.grid.count()):
            if (self.grid.item(i).data(Qt.UserRole) or {}).get("id") == asset_id:
                self.grid.setCurrentRow(i)

    def _delete(self):
        a = self.current()
        if not a or not ui.confirm(self, i18n.t("Delete file"), i18n.t("Delete {n} from the library?").format(n=a.get("filename"))):
            return
        ui.call(self, "media/delete", {"asset_id": a["id"]}, done=lambda _r: (forget(a["id"]), self.note.ok(i18n.t("Deleted.")), self.reload(), self.changed.emit()),
                failed=lambda m, _d: self.note.error(m))

    def _save(self):
        a = self.current()
        if a:
            save_asset(self, a, lambda m: self.note.error(m))


class MediaLibraryDialog(PrismDialog):
    """Choose one file from the library, or upload one and choose it. `.asset` is the choice after the dialog is accepted."""

    def __init__(self, kinds=None, title: str = "", parent=None):
        super().__init__(title or i18n.t("Choose a file"), i18n.t("From your Media Library. Upload a new one if it is not there yet."),
                         icon="image", parent=parent)
        self.asset = None
        self.view = LibraryView(manage=False, kinds=kinds)
        self.body.addWidget(self.view, stretch=1)
        self.use = self.button(i18n.t("Use this file"), "primary", on_click=self._use)
        self.use.setEnabled(False)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.use)
        self.view.selected.connect(lambda a: self.use.setEnabled(a is not None))
        self.view.activated.connect(lambda _a: self._use())
        self.resize(720, 580)
        self.view.reload()

    def _use(self):
        a = self.view.current()
        if a is not None:
            self.asset = a
            self.accept()


# ── the one-file field ───────────────────────────────────────────────────────

class AssetField(QWidget):
    """Where a form wants one file from the library: shows its name and size, with Choose / Change and Remove."""

    changed = Signal()

    def __init__(self, kinds=None, empty_text: str = "", parent=None):
        super().__init__(parent)
        self.kinds = tuple(kinds) if kinds else None
        self._asset = None
        self._asset_id = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.glyph = QLabel()
        self.glyph.setFixedSize(20, 20)
        row.addWidget(self.glyph)
        self.name = C.label("", level="SUPPORT", weight=700)
        self.name.setMinimumWidth(80)
        row.addWidget(self.name, stretch=1)
        self.pick = C.button(i18n.t("Choose file"), "secondary", small=True, on_click=self._choose)
        row.addWidget(self.pick)
        self.remove = C.icon_button("x", i18n.t("Remove the file"), on_click=self.clear, colour=theme.NEUTRAL[600])
        row.addWidget(self.remove)
        self._empty = empty_text or i18n.t("No file")
        self._show()

    def asset(self):
        return self._asset

    def asset_id(self):
        return self._asset_id

    def set_asset(self, asset) -> None:
        self._asset = dict(asset) if asset else None
        self._asset_id = self._asset.get("id") if self._asset else None
        self._show()

    def set_asset_id(self, asset_id) -> None:
        """Show a file we only know the id of (read back from a saved setting)."""
        if not asset_id:
            return self.set_asset(None)
        self._asset, self._asset_id = None, str(asset_id)
        self._show(loading=True)
        ui.call(self, "media/get", {"asset_id": asset_id, "max_bytes": 1}, done=lambda r: self._known(asset_id, r.get("asset")),
                failed=lambda _m, _d: self._known(asset_id, None))

    def _known(self, asset_id, asset):
        if self._asset_id != str(asset_id):
            return
        if asset:
            self._asset = dict(asset)
        else:
            self._asset_id = None
        self._show()

    def clear(self):
        self.set_asset(None)
        self.changed.emit()

    def _choose(self):
        dlg = MediaLibraryDialog(self.kinds, parent=self)
        if dlg.exec() and dlg.asset:
            self.set_asset(dlg.asset)
            self.changed.emit()

    def _show(self, loading: bool = False):
        a = self._asset
        if a:
            self.glyph.setPixmap(icons.pixmap(KIND_ICON.get(a.get("kind"), "file"), 18, theme.NEUTRAL[700]))
            self.name.setText("%s · %s" % (a.get("filename") or "", size_text(a.get("size"))))
            self.name.setStyleSheet(f"color: {theme.TEXT};")
        else:
            self.glyph.setPixmap(icons.pixmap("paperclip", 18, theme.NEUTRAL[500]))
            self.name.setText(i18n.t("Loading…") if loading else self._empty)
            self.name.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-weight: 400;")
        self.pick.setText(i18n.t("Change") if (a or loading) else i18n.t("Choose file"))
        self.remove.setVisible(bool(a or loading))

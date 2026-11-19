"""One way to open a file chooser (RELEASE_ISSUES.md ISS-009 / ISS-012).

It opens the platform's own dialog (Recent, places, drives) in the folder the person used
last for that kind of file; the first time, in their REAL Downloads/Documents (never `~`,
which a dev build points at its private data folder, and never the program folder).
The last folder is remembered per kind in the config under `last_dirs`.
"""
from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

import i18n
import paths

# Filters people actually want: the group they are after first, everything else one click away.
PIC = "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"
DRAWINGS = ("Drawings (*.dxf *.dwg *.pdf " + PIC + ");;DXF or DWG (*.dxf *.dwg);;PDF (*.pdf);;"
            "Pictures (" + PIC + ");;All files (*)")
PDF = "PDF (*.pdf);;All files (*)"
DOCUMENTS = "Word or Excel (*.docx *.xlsx *.xlsm);;All files (*)"
WORD = "Word documents (*.docx);;All files (*)"
MEASUREMENTS = "Text, JSON or CSV (*.txt *.json *.csv *.md);;All files (*)"
PRICES = "Price lists (*.csv *.xlsx *.xlsm *.pdf *.docx *.txt);;All files (*)"
ANY = "All files (*)"


def start_dir(cfg: dict | None, kind: str) -> str:
    last = ((cfg or {}).get("last_dirs") or {}).get(kind) or ""
    if last and os.path.isdir(last):
        return last
    return paths.picker_start_dir()


def remember(cfg: dict | None, kind: str, picked: str) -> None:
    """Keep the folder of what was picked for next time (never raises)."""
    if cfg is None or not picked:
        return
    folder = os.path.dirname(os.path.abspath(picked))
    dirs = dict(cfg.get("last_dirs") or {})
    if dirs.get(kind) == folder or not os.path.isdir(folder):
        return
    dirs[kind] = folder
    cfg["last_dirs"] = dirs
    try:
        import core_bridge as CB
        CB.config.save(cfg)
    except Exception:                                    # noqa: BLE001
        pass


def open_file(parent, title: str, kind: str, filters: str = ANY, cfg: dict | None = None) -> str:
    path, _ = QFileDialog.getOpenFileName(parent, i18n.t(title), start_dir(cfg, kind), i18n.t(filters))
    if path:
        remember(cfg, kind, path)
    return path or ""


def open_files(parent, title: str, kind: str, filters: str = ANY, cfg: dict | None = None) -> list:
    paths_, _ = QFileDialog.getOpenFileNames(parent, i18n.t(title), start_dir(cfg, kind), i18n.t(filters))
    if paths_:
        remember(cfg, kind, paths_[0])
    return list(paths_ or [])


def save_file(parent, title: str, kind: str, name: str, filters: str = ANY, cfg: dict | None = None) -> str:
    path, _ = QFileDialog.getSaveFileName(
        parent, i18n.t(title), os.path.join(start_dir(cfg, kind), name), i18n.t(filters))
    if path:
        remember(cfg, kind, path)
    return path or ""

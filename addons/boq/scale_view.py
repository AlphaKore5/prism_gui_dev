"""Set the drawing scale by measuring something whose real length is known.

Click one end of a ruler line or a labelled dimension, then the other end, then type its
real length. The arithmetic is the one the tool has always used (pixel distance on a page
shown at `dpi` pixels per inch is paper points; points / real feet = points per foot);
this module only makes the PAGE easier to look at: choose the page (the one with the most
drawn lines is offered first), big view, wheel zoom, drag to move, snapping to line ends and
corners, clear start/end markers with the measured paper length, undo, and a length in feet,
metres or millimetres. The dropdown's standard scales stay the shortcut in the tool window;
the closest standard scale to what was measured is shown beside the result.
"""
from __future__ import annotations

import math
import os

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QGraphicsEllipseItem, QGraphicsLineItem, QGraphicsPixmapItem,
    QGraphicsScene, QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel,
    QLineEdit, QVBoxLayout,
)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from addons.boq import industries
from addons.boq.workers import PageScanWorker

# A page with fewer drawn lines than this is much more likely a table or a text page.
PLAN_MIN_OBJECTS = 300
UNITS = (("ft", 1.0), ("m", 1 / 0.3048), ("mm", 1 / 304.8))     # factor: this unit -> feet
_SNAP_CELL = 20.0
_SNAP_RADIUS_PX = 12.0                                           # on screen


def closest_standard(pt_per_ft: float, scales: dict):
    """(label, how close 0..1) of the standard scale nearest to a measured one, or (None, 0)."""
    best, best_err = None, 9.0
    for label, ppf in (scales or {}).items():
        if ppf > 0 and pt_per_ft > 0:
            err = abs(math.log(pt_per_ft / ppf))
            if err < best_err:
                best, best_err = label, err
    return (best, max(0.0, 1.0 - best_err)) if best else (None, 0.0)


class _PageView(QGraphicsView):
    clicked = Signal(float, float)       # scene (100-dpi pixel) coordinates
    hovered = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(theme.CANVAS)))
        self.setMouseTracking(True)
        self.setMinimumHeight(360)
        self._press = None
        self._moved = False

    def zoom_by(self, factor: float):
        cur = self.transform().m11()
        new = max(0.03, min(60.0, cur * factor))
        self.scale(new / cur, new / cur)

    def zoom_level(self) -> float:
        return self.transform().m11()

    def fit(self):
        rect = self.scene().itemsBoundingRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        if dy:
            self.zoom_by(1.2 ** (dy / 120.0))
            event.accept()

    def mousePressEvent(self, event):
        self._press = event.position()
        self._moved = False
        self._pan_from = event.position()
        event.accept()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._press is not None and event.buttons():
            if (pos - self._press).manhattanLength() > 4:
                self._moved = True
            if self._moved:
                d = pos - self._pan_from
                self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
                self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
                self.setCursor(Qt.ClosedHandCursor)
        else:
            sp = self.mapToScene(pos.toPoint())
            self.hovered.emit(sp.x(), sp.y())
        self._pan_from = pos
        event.accept()

    def mouseReleaseEvent(self, event):
        self.unsetCursor()
        if self._press is not None and not self._moved and event.button() == Qt.LeftButton:
            sp = self.mapToScene(event.position().toPoint())
            self.clicked.emit(sp.x(), sp.y())
        self._press = None
        event.accept()


class ScaleMeasureDialog(PrismDialog):
    """`pt_per_ft` is None until two points and a real length make a scale."""

    def __init__(self, pdf_path: str, page_index: int | None = 0, parent=None, industry: str = ""):
        super().__init__(i18n.t("Set the drawing scale"),
                         i18n.t("Measure one thing whose real length you know."),
                         icon="file", parent=parent, body_spacing=theme.SPACE_2)
        self.setWindowTitle(i18n.t("Measure a known dimension"))
        self.resize(1040, 880)
        self.pdf_path = pdf_path
        self.industry = industry
        self._auto_page = page_index is None
        self.page_index = 0 if page_index is None else int(page_index)
        self.page_count = 1
        self.dpi = 100.0                     # scene units are pixels at this many per inch
        self.render_dpi = 200.0              # the picture itself is sharper than that
        self._points: list[tuple[float, float]] = []
        self.pt_per_ft: float | None = None
        self.closest_label: str | None = None
        self._snap: dict = {}
        self._items: list = []
        self._pix_item = None
        self._fitted = False
        self._scan = None

        col = self.body
        col.addWidget(C.label(i18n.t(
            "Click one end of a ruler line or a labelled dimension, then the other end, then "
            "type its real length."), level="BODY", wrap=True))
        col.addWidget(C.label(i18n.t(
            "Scroll to zoom, drag to move. Points jump to the nearest line end or corner."),
            level="SUPPORT", wrap=True))

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_2)
        self.page_combo = QComboBox()
        self.page_combo.currentIndexChanged.connect(self._on_page_picked)
        bar.addWidget(QLabel(i18n.t("Page")))
        bar.addWidget(self.page_combo)
        bar.addStretch(1)
        self.zoom_out_btn = C.button("−", "secondary", small=True, on_click=lambda: self.view.zoom_by(1 / 1.25))
        self.zoom_in_btn = C.button("+", "secondary", small=True, on_click=lambda: self.view.zoom_by(1.25))
        self.fit_btn = C.button(i18n.t("Fit page"), "secondary", small=True, on_click=lambda: self.view.fit())
        self.undo_btn = C.button(i18n.t("Undo point"), "secondary", small=True, on_click=self.undo)
        self.restart_btn = C.button(i18n.t("Start again"), "secondary", small=True, on_click=self.restart)
        for b in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.undo_btn, self.restart_btn):
            bar.addWidget(b)
        col.addLayout(bar)
        self.page_note = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self.page_note)

        self.view = _PageView()
        self.view.clicked.connect(self._on_view_click)
        self.view.hovered.connect(self._on_hover)
        col.addWidget(self.view, stretch=1)

        self._hover_ring = QGraphicsEllipseItem(-6, -6, 12, 12)
        ring = QPen(QColor(theme.ERR_INK)); ring.setCosmetic(True); ring.setWidth(2)
        self._hover_ring.setPen(ring)
        self._hover_ring.setZValue(20)
        self._hover_ring.setVisible(False)
        self.view.scene().addItem(self._hover_ring)

        self.points_label = C.label("", level="SUPPORT")
        col.addWidget(self.points_label)

        row = QHBoxLayout()
        row.addWidget(QLabel(i18n.t("Real length between the two points:")))
        self.distance_edit = QLineEdit()
        self.distance_edit.setPlaceholderText(i18n.t("for example 6.0"))
        self.distance_edit.setMaximumWidth(140)
        self.distance_edit.textChanged.connect(self._recompute)
        row.addWidget(self.distance_edit)
        self.unit_combo = QComboBox()
        for label, factor in UNITS:
            self.unit_combo.addItem(label, factor)
        self.unit_combo.currentIndexChanged.connect(self._recompute)
        row.addWidget(self.unit_combo)
        row.addStretch(1)
        col.addLayout(row)

        self.result_label = C.label("", level="BODY", wrap=True)
        col.addWidget(self.result_label)

        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.use_btn = self.button(i18n.t("Use this scale"), "primary", on_click=self.accept)
        self.use_btn.setEnabled(False)
        self.footer.set_primary(self.use_btn)

        self._load_error = None
        self._load_image()
        self._show_pixmap()
        self._start_scan(None if self._auto_page else self.page_index)
        self._update_points_text()

    # ── the page ────────────────────────────────────────────────────────
    def _load_image(self):
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(self.pdf_path)
            self.page_count = len(pdf)
            page = pdf[min(self.page_index, len(pdf) - 1)]
            w_pt, h_pt = page.get_size()
            dpi = self.render_dpi
            longest = max(w_pt, h_pt) / 72.0 * dpi
            if longest > 7000:                                   # keep very large sheets sane
                dpi = dpi * 7000 / longest
            img = page.render(scale=dpi / 72).to_pil().convert("RGB")
            self.render_dpi = dpi
        except Exception as e:                              # noqa: BLE001
            self._load_error = str(e)
            self.points_label.setText(i18n.t("Couldn't render the drawing: {error}").format(error=e))
            return
        data = img.tobytes("raw", "RGB")
        qimg = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888).copy()
        self.pixmap = QPixmap.fromImage(qimg)

    def _show_pixmap(self):
        sc = self.view.scene()
        if self._pix_item is not None:
            sc.removeItem(self._pix_item)
            self._pix_item = None
        if not hasattr(self, "pixmap"):
            return
        self._pix_item = QGraphicsPixmapItem(self.pixmap)
        self._pix_item.setTransformationMode(Qt.SmoothTransformation)
        self._pix_item.setScale(self.dpi / self.render_dpi)
        self._pix_item.setZValue(0)
        sc.addItem(self._pix_item)
        sc.setSceneRect(self._pix_item.sceneBoundingRect())

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self._fitted = True
            self.view.fit()

    # ── which page ──────────────────────────────────────────────────────
    def _start_scan(self, only_page):
        if not os.path.exists(self.pdf_path):
            return
        self.page_note.setText(i18n.t("Looking at the pages…"))
        self._scan = PageScanWorker(self.pdf_path, only_page)
        self._scan.done.connect(self._on_scanned)
        self._scan.start()

    def _on_scanned(self, info: dict):
        pages = info.get("pages") or []
        if pages and "best" in info:                              # the whole-PDF scan
            best = info["best"]
            self.page_combo.blockSignals(True)
            self.page_combo.clear()
            for i, p in enumerate(pages):
                tag = i18n.t(" (most drawn lines)") if i == best and len(pages) > 1 else ""
                self.page_combo.addItem(i18n.t("Page {n} of {total}").format(n=i + 1, total=len(pages)) + tag, i)
            self.page_combo.setCurrentIndex(self.page_index)
            self.page_combo.blockSignals(False)
            self._page_objects = [p["objects"] for p in pages]
            if self._auto_page and best != self.page_index:
                self._auto_page = False
                self._go_to_page(best)
                return
            self._auto_page = False
        self._snap = self._grid(info.get("points") or [])
        n = (getattr(self, "_page_objects", None) or [0] * (self.page_index + 1))[self.page_index]
        if n < PLAN_MIN_OBJECTS:
            self.page_note.setText(i18n.t(
                "Few drawn lines here. This looks like a table or text, not a plan. Try another "
                "page or file."))
        else:
            self.page_note.setText(i18n.t(
                "This is the sheet to measure on. Extract reads every page of the PDF."))

    def _on_page_picked(self, _i):
        idx = self.page_combo.currentData()
        if idx is not None and idx != self.page_index:
            self._go_to_page(int(idx))

    def _go_to_page(self, idx: int):
        self.page_index = idx
        self.page_combo.blockSignals(True)
        self.page_combo.setCurrentIndex(idx)
        self.page_combo.blockSignals(False)
        self.restart()
        self._load_image()
        self._show_pixmap()
        self.view.fit()
        self._snap = {}
        self._start_scan(idx)

    # ── snapping ────────────────────────────────────────────────────────
    @staticmethod
    def _grid(points):
        grid: dict = {}
        for x, y in points:
            grid.setdefault((int(x // _SNAP_CELL), int(y // _SNAP_CELL)), []).append((x, y))
        return grid

    def _snap_to(self, x: float, y: float):
        if not self._snap:
            return x, y, False
        radius = _SNAP_RADIUS_PX / max(self.view.zoom_level(), 1e-6)
        cx, cy = int(x // _SNAP_CELL), int(y // _SNAP_CELL)
        reach = int(radius // _SNAP_CELL) + 1
        best, best_d = None, radius
        for gx in range(cx - reach, cx + reach + 1):
            for gy in range(cy - reach, cy + reach + 1):
                for px, py in self._snap.get((gx, gy), ()):
                    d = math.hypot(px - x, py - y)
                    if d < best_d:
                        best, best_d = (px, py), d
        return (best[0], best[1], True) if best else (x, y, False)

    def _on_hover(self, x: float, y: float):
        sx, sy, hit = self._snap_to(x, y)
        self._hover_ring.setVisible(hit)
        if hit:
            self._hover_ring.setPos(sx, sy)

    def _on_view_click(self, x: float, y: float):
        sx, sy, _ = self._snap_to(x, y)
        self._on_click(sx, sy)

    # ── points ──────────────────────────────────────────────────────────
    def _on_click(self, x: float, y: float):
        if not hasattr(self, "pixmap"):
            return
        if len(self._points) >= 2:
            self._points = []
        self._points.append((x, y))
        self._redraw_markers()
        self._recompute()

    def undo(self):
        if self._points:
            self._points.pop()
            self._redraw_markers()
            self._recompute()

    def restart(self):
        self._points = []
        self._redraw_markers()
        self._recompute()

    def paper_length_pt(self) -> float | None:
        if len(self._points) != 2:
            return None
        (x0, y0), (x1, y1) = self._points
        return math.hypot(x0 - x1, y0 - y1) * 72.0 / self.dpi

    def _redraw_markers(self):
        sc = self.view.scene()
        for it in self._items:
            sc.removeItem(it)
        self._items = []
        pen = QPen(QColor(theme.ERR_INK))
        pen.setCosmetic(True)
        pen.setWidth(2)
        for n, (x, y) in enumerate(self._points):
            for dx, dy in ((14, 0), (0, 14)):
                ln = QGraphicsLineItem(x - dx, y - dy, x + dx, y + dy)
                ln.setPen(pen); ln.setZValue(10); ln.setFlag(QGraphicsLineItem.ItemIgnoresTransformations, False)
                sc.addItem(ln); self._items.append(ln)
            tag = QGraphicsSimpleTextItem(i18n.t("Start") if n == 0 else i18n.t("End"))
            tag.setBrush(QBrush(QColor(theme.ERR_INK)))
            tag.setFlag(QGraphicsSimpleTextItem.ItemIgnoresTransformations, True)
            tag.setPos(x + 6, y + 6); tag.setZValue(11)
            sc.addItem(tag); self._items.append(tag)
        if len(self._points) == 2:
            (x0, y0), (x1, y1) = self._points
            ln = QGraphicsLineItem(x0, y0, x1, y1)
            ln.setPen(pen); ln.setZValue(9)
            sc.addItem(ln); self._items.append(ln)
        self._update_points_text()

    def _update_points_text(self):
        n = len(self._points)
        if n == 0:
            self.points_label.setText(i18n.t("Step 1 of 3: click the first end."))
        elif n == 1:
            self.points_label.setText(i18n.t("Step 2 of 3: click the other end."))
        else:
            pt = self.paper_length_pt()
            self.points_label.setText(i18n.t(
                "Step 3 of 3: type its real length. You measured {pt:.1f} points on paper "
                "({mm:.1f} mm).").format(pt=pt, mm=pt * 25.4 / 72.0))

    def _recompute(self, *_):
        self.pt_per_ft = None
        self.closest_label = None
        self.use_btn.setEnabled(False)
        self.result_label.setText("")
        if len(self._points) != 2:
            return
        try:
            real = float(self.distance_edit.text())
        except ValueError:
            return
        if real <= 0:
            return
        real_ft = real * float(self.unit_combo.currentData() or 1.0)
        # The page is shown at self.dpi pixels per inch, so pixel distance -> PDF points is
        # that inverse (72 pt per inch is the PDF unit definition, not a guess).
        self.pt_per_ft = self.paper_length_pt() / real_ft
        label, closeness = closest_standard(self.pt_per_ft, industries.scales(self.industry))
        self.closest_label = label if closeness >= 0.9 else None
        text = i18n.t("Scale from your measurement: {ppf:.2f} points per foot.").format(ppf=self.pt_per_ft)
        if label:
            if closeness >= 0.9:
                text += " " + i18n.t("That is the standard scale {s}.").format(s=label)
            else:
                text += " " + i18n.t("The nearest standard scale is {s}, but yours is not close "
                                     "to it. Your measured scale will be used.").format(s=label)
        self.result_label.setText(text)
        self.use_btn.setEnabled(True)

"""The measured quantities, as a table a person can read.

Until 10 Sep 2026 the BOQ window showed the measurement as the same plain
text the AI prompt carries -- "LENGTHS BY LAYER:" and a wall of
"  layer: 498.44 unspecified" lines in a 120 px box -- which is a prompt,
not a report. The owner asked for the numbers the way the CSV has them:
one row per measured item, columns, readable at a glance.

23 Oct 2026, the owner's next report, on a real multi-building site file:
the warnings (look-alike layers, blocks on another site, every duct/pipe/
tray the HVAC pairing rule touched) had grown into a wall of text again --
now a flat orange box instead of a flat grey one -- and the table itself
was too short to read without a separate "Show every layer name" dance.
Changes made that day:

1. The warnings move into a collapsed, bulleted dropdown (`warn_btn` /
   `warn_list`) instead of one ever-growing label.
2. Every row is tinted by how much the owner should trust it (see
   `severity_for()`).
3. The Value column is editable; editing a cell marks that row confirmed.
   `MeasuredTableWindow` opens the same table full-size in its own window,
   and "Save as CSV (Desktop)" writes exactly what is on screen.

Same day, a second round: the owner tried it and reported two things still
wrong. First, the row tint alone (a pale background, same token the rest of
the app already uses for banners) was too subtle to read as "colour coding"
at a glance -- so there is now a dedicated Trust column, a solid dot in the
full ink colour (green/yellow/red), impossible to miss regardless of how
the background renders. Second, every value was locked to the drawing's own
unit with no way to look at it in anything else -- so `unit_combo` now lets
a person pick mm / cm / m / ft / in and the whole table re-renders in that
unit on the spot, no re-measuring. Length values convert by a plain factor,
area values by its square, counts never convert. Switching units re-draws
from the original measured figures, so an in-progress hand edit is not
carried across a unit change -- pick the unit first, then correct a number.

Pure widget over the `q` dict core.boq.measure() returns; the prompt text
(core.boq.summary_text) is untouched and still what the AI is given.
"""
from __future__ import annotations

import csv
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import i18n
import theme
from widgets import controls as C


class _TintDelegate(QStyledItemDelegate):
    """Paints a cell's own background and text colour directly, bypassing
    style.qss's `QTableWidget::item { color: #09090b; ... }` rule.

    Found 23 Oct 2026, the owner's own screenshot: every Trust dot showed
    black and no row tint was visible at all, in the real running app,
    even though the unit tests (which never load style.qss) passed and an
    earlier offscreen screenshot (same gap) looked right. Reproduced by
    rendering with the real stylesheet applied: once a stylesheet declares
    `color`/`background` on `QTableWidget::item`, Qt's style sheet engine
    paints every item with that fixed value — a `QTableWidgetItem`'s own
    `Qt.BackgroundRole` / `Qt.ForegroundRole` brush is silently ignored at
    paint time, even though the item's own data still reports it back
    correctly (`.background().color()` returns the right value; the
    screen does not). This delegate draws the cell itself — fill, text,
    font, alignment, a light selection tint — never going through
    `style()->drawControl()`, which is the one path style.qss intercepts.
    Set once, on the whole table (`setItemDelegate`), not per column."""

    def paint(self, painter, option, index):
        painter.save()
        bg = index.data(Qt.BackgroundRole)
        if bg is not None:
            painter.fillRect(option.rect, bg)
        if option.state & QStyle.State_Selected:
            sel = QColor(option.palette.highlight().color())
            sel.setAlpha(60)
            painter.fillRect(option.rect, sel)
        fg = index.data(Qt.ForegroundRole)
        if isinstance(fg, QBrush):
            color = fg.color()
        elif isinstance(fg, QColor):
            color = fg
        else:
            color = option.palette.text().color()
        painter.setPen(color)
        font = index.data(Qt.FontRole)
        painter.setFont(font if font else option.font)
        text = str(index.data(Qt.DisplayRole) or "")
        if text == "●":
            # The Trust dot is drawn, not typed: a font without U+25CF (Qt's
            # offscreen Windows runner, CI 27 Oct 2026) drew nothing at all
            # and the cell showed only its tint.
            d = max(6, min(10, option.rect.height() - 6))
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            c = option.rect.center()
            painter.drawEllipse(c.x() - d // 2, c.y() - d // 2, d, d)
            painter.restore()
            return
        align = index.data(Qt.TextAlignmentRole)
        align = int(align) if align is not None else int(Qt.AlignLeft | Qt.AlignVCenter)
        rect = option.rect.adjusted(8, 0, -8, 0)
        painter.drawText(rect, align, text)
        painter.restore()

KIND_LENGTH = "Length"
KIND_AREA = "Area"
KIND_COUNT = "Count"

SEV_GOOD = "good"
SEV_WARN = "warn"
SEV_BAD = "bad"
_SEV_BG = {SEV_GOOD: theme.OK_BG, SEV_WARN: theme.WARN_BG, SEV_BAD: theme.ERR_BG}
_SEV_INK = {SEV_GOOD: theme.OK_INK, SEV_WARN: theme.WARN_INK, SEV_BAD: theme.ERR_INK}

# The on-screen table has 6 visible columns and a 7th, hidden, sort column.
COL_TRUST, COL_ITEM, COL_KIND, COL_LAYER, COL_VALUE, COL_UNIT, COL_SORT = range(7)

# Millimetres per unit, for the "show it in..." conversion -- the same
# canonical names core.boq._UNIT_NAMES already uses, so a q["unit"] or
# q["site"]["unit_inferred"] string plugs straight in with no translation
# table of its own to drift out of sync.
_TO_MM = {
    "millimeters": 1.0, "centimeters": 10.0, "meters": 1000.0,
    "inches": 25.4, "feet": 304.8, "miles": 1_609_344.0,
    "US survey feet": 1_200.0 / 3937.0 * 1000.0,
}
_UNIT_LABEL = {
    "millimeters": "Millimeters (mm)", "centimeters": "Centimeters (cm)",
    "meters": "Meters (m)", "feet": "Feet (ft)", "inches": "Inches (in)",
}
_UNIT_ABBR = {
    "millimeters": "mm", "centimeters": "cm", "meters": "m",
    "feet": "ft", "inches": "in",
}
# The order offered in the dropdown -- the common run for a drawing's own
# native units plus the handful anyone actually re-expresses a BOQ in.
_UNIT_CHOICES = ("millimeters", "centimeters", "meters", "feet", "inches")


def rows_for(q: dict) -> list[tuple[str, str, str, float, str]]:
    """(item, kind, layer, value, unit) for every measured figure, lengths
    first, then areas, then block counts -- the CSV's own order. Values are
    always in the drawing's own unit; MeasuredTable converts for display."""
    unit = q.get("unit") or "unspecified"
    out = []
    for layer, length in (q.get("lengths_by_layer") or {}).items():
        out.append((layer, KIND_LENGTH, layer, float(length), unit))
    for layer, area in (q.get("areas_by_layer") or {}).items():
        out.append((layer, KIND_AREA, layer, float(area), f"sq {unit}"))
    layers_of = q.get("block_layers") or {}
    for name, count in (q.get("block_counts") or {}).items():
        out.append((name, KIND_COUNT, ", ".join(layers_of.get(name) or []),
                    float(count), "nos"))
    return out


def severity_for(q: dict) -> dict[str, str]:
    """item/layer name -> SEV_GOOD / SEV_WARN / SEV_BAD, read from the same
    signals the warnings list already shows -- never a second, independent
    judgement of what Prism is or isn't sure about.

    SEV_BAD (red): the model found something it cannot resolve on its own
    -- two layers that look like the same thing (lookalikes), or blocks
    whose own coordinates place them on another site entirely.
    SEV_WARN (yellow): the HVAC double-line pairing rule acted on this
    layer (HVAC_DRAWING_RULES.md rule 1) -- usually right, always worth a
    look before pricing.
    SEV_GOOD (green): nothing flagged it.
    """
    site = q.get("site") or {}
    sev: dict[str, str] = {}
    for lk in site.get("lookalikes") or []:
        for layer in lk.get("layers") or []:
            sev[layer] = SEV_BAD
    for rb in site.get("remote_blocks") or []:
        sev[rb["name"]] = SEV_BAD
    for note in (q.get("notes") or []):
        layer = str(note).split(":", 1)[0].strip()
        if layer and sev.get(layer) != SEV_BAD:
            sev[layer] = SEV_WARN
    return sev


def _sev_tooltip(sev: str) -> str:
    if sev == SEV_BAD:
        return i18n.t("Prism can't resolve this by itself — a person must check it.")
    if sev == SEV_WARN:
        return i18n.t("The HVAC duct-pairing rule touched this layer — worth a look before pricing.")
    return i18n.t("Nothing flagged this — trusted as measured.")


def convert_value(kind: str, value: float, from_unit: str | None, to_unit: str | None) -> float:
    """`value`, measured in `from_unit`, re-expressed in `to_unit`. Counts
    never convert; area converts by the squared length factor. Either unit
    missing or unrecognised (an unconfirmed drawing unit) leaves `value`
    exactly as given -- Prism never guesses a conversion it isn't sure of."""
    if kind == KIND_COUNT or not from_unit or not to_unit:
        return value
    from_mm, to_mm = _TO_MM.get(from_unit), _TO_MM.get(to_unit)
    if not from_mm or not to_mm:
        return value
    factor = from_mm / to_mm
    return value * (factor ** 2 if kind == KIND_AREA else factor)


def desktop_dir() -> str:
    """The user's Desktop -- its own function so a test can patch it instead
    of ever writing to the real one (the owner's standing rule: nothing a
    test runs ever touches a real user-owned path)."""
    return os.path.join(os.path.expanduser("~"), "Desktop")


def _fmt(kind: str, value: float) -> str:
    if kind == KIND_COUNT:
        return f"{int(value):,}"
    return f"{value:,.2f}"


class MeasuredTable(QWidget):
    """Header line, a collapsible bulleted list of rules/warnings, a unit
    picker, and the table itself: a Trust column (solid colour), the other
    columns tinted to match, Value editable."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q: dict | None = None
        self._raw_rows: list = []
        self._sev_map: dict[str, str] = {}
        self._base_unit: str | None = None
        self._display_unit = "native"
        self._warnings: list[str] = []
        self._filling = False
        self._big_window: MeasuredTableWindow | None = None

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)

        self.header = C.label("", level="BODY", wrap=True)
        col.addWidget(self.header)

        # Rules & warnings -- collapsed by default and bulleted, not one
        # label that keeps growing: a real site file can flag dozens of
        # layers (remote blocks, look-alikes, every duct pairing).
        self.warn_btn = C.button("", "tertiary", small=True,
                                 on_click=self._toggle_warnings)
        self.warn_btn.setVisible(False)
        col.addWidget(self.warn_btn, alignment=Qt.AlignLeft)
        self.warn_list = QListWidget()
        self.warn_list.setVisible(False)
        self.warn_list.setMaximumHeight(180)
        self.warn_list.setStyleSheet(
            f"QListWidget {{ border-radius: {theme.R_CONTROL}px; }}"
            f" QListWidget::item {{ padding: {theme.SPACE_1}px {theme.SPACE_2}px; }}")
        col.addWidget(self.warn_list)

        unit_row = QHBoxLayout()
        unit_row.setContentsMargins(0, 0, 0, 0)
        unit_row.setSpacing(theme.SPACE_2)
        unit_row.addWidget(QLabel(i18n.t("Show values in:")))
        self.unit_combo = QComboBox()
        self.unit_combo.blockSignals(True)
        self.unit_combo.addItem(i18n.t("As measured"), "native")
        for key in _UNIT_CHOICES:
            self.unit_combo.addItem(i18n.t(_UNIT_LABEL[key]), key)
        self.unit_combo.blockSignals(False)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        unit_row.addWidget(self.unit_combo)
        unit_row.addStretch(1)
        col.addLayout(unit_row)

        # Trust, then the 5 columns a person reads, and a 7th, hidden, that
        # holds the CSV's own order: a sortable table re-sorts itself on
        # whatever column was last clicked when it is refilled, and the
        # default view must be the file's order, lengths then areas then
        # counts.
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            i18n.t("Trust"), i18n.t("Item"), i18n.t("Measured as"),
            i18n.t("Layer"), i18n.t("Value"), i18n.t("Unit"), "#"])
        self.table.setColumnHidden(COL_SORT, True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setItemDelegate(_TintDelegate(self.table))
        self.table.itemChanged.connect(self._on_edited)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_TRUST, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_TRUST, 36)
        head.setSectionResizeMode(COL_ITEM, QHeaderView.Stretch)
        for column in (COL_KIND, COL_LAYER, COL_VALUE, COL_UNIT):
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        row_h = self.table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        # Ten rows on screen, the rest scroll: a 64-layer survey is a long
        # list, and a table that shows only its header is a table nobody reads.
        self.table.setMinimumHeight(head_h + 6 * row_h + 4)
        self.table.setMaximumHeight(head_h + 10 * row_h + 4)
        col.addWidget(self.table)

        legend = C.label(i18n.t(
            "Trust column: green — nothing flagged it. Yellow — the HVAC "
            "duct-pairing rule touched it, worth a look. Red — Prism can't "
            "resolve this by itself, a person must. Double-click Value to "
            "correct a number; the row turns green once you do. Changing "
            "\"Show values in\" re-draws from the original measured figures "
            "— pick the unit first, then correct a number."),
            level="SUPPORT", wrap=True)
        col.addWidget(legend)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(theme.SPACE_2)
        self.layers_btn = C.button(i18n.t("Show every layer name"), "tertiary",
                                   small=True, on_click=self._toggle_layers)
        actions.addWidget(self.layers_btn)
        self.expand_btn = C.button(i18n.t("Open in a bigger window"), "tertiary",
                                   small=True, icon_name="maximize",
                                   on_click=self._open_big)
        actions.addWidget(self.expand_btn)
        self.desktop_csv_btn = C.button(i18n.t("Save as CSV (Desktop)"), "secondary",
                                        small=True, on_click=self._save_desktop_csv)
        actions.addWidget(self.desktop_csv_btn)
        actions.addStretch(1)
        col.addLayout(actions)

        self.saved_label = QLabel("")
        self.saved_label.setWordWrap(True)
        self.saved_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        self.saved_label.setVisible(False)
        col.addWidget(self.saved_label)

        self.layers = C.label("", level="SUPPORT", wrap=True)
        self.layers.setVisible(False)
        col.addWidget(self.layers)
        self._layer_names: list[str] = []

    # ── data ─────────────────────────────────────────────────────────────
    def set_quantities(self, q: dict):
        self._q = q
        self._raw_rows = rows_for(q)
        unit = q.get("unit") or "unspecified"
        site = q.get("site") or {}
        inferred = site.get("unit_inferred") if not q.get("unit_confirmed", True) else ""
        base = inferred or unit
        self._base_unit = base if base in _TO_MM else None
        self.unit_combo.setEnabled(self._base_unit is not None)
        self.unit_combo.setToolTip("" if self._base_unit is not None else i18n.t(
            "The drawing's unit isn't confirmed, so Prism won't guess a "
            "conversion — confirm it against the source first."))
        shown_unit = (i18n.t("{unit} (inferred from the coordinates)").format(unit=inferred)
                      if inferred else unit)
        self.header.setText(i18n.t(
            "Drawing units: {unit} · {entities:,} entities · {layers} layers").format(
            unit=shown_unit, entities=int(q.get("entity_count") or 0),
            layers=len(q.get("layers") or [])))
        warnings = []
        if inferred:
            warnings.append(i18n.t(
                "Unit not recorded in the file, but the coordinates say {unit}: "
                "{why}.").format(unit=inferred, why="; ".join(site.get("unit_evidence") or [])))
        elif not q.get("unit_confirmed", q.get("unit_code", 0) != 0):
            warnings.append(i18n.t(
                "Unit not confirmed — the drawing's unit was not recorded. "
                "Every value is in the drawing's raw unit (mm, m or ft); "
                "confirm it against the source before this goes near a rate."))
        for lk in site.get("lookalikes") or []:
            warnings.append(i18n.t("Look-alike layers {a} and {b}: {verdict}.").format(
                a=lk["layers"][0], b=lk["layers"][1], verdict=lk["verdict"]))
        for rb in site.get("remote_blocks") or []:
            warnings.append(i18n.t(
                "{count} of {of} {name} blocks are {km} km away — another site, "
                "not on this one's network.").format(
                count=rb["count"], of=rb["of"], name=rb["name"],
                km=", ".join(f"{d/1000:.1f}" for d in rb["distances_m"][:6])))
        if "scope_keywords" in q:
            warnings.append(i18n.t(
                "Scope filter on ({words}) — {shown} of the drawing's {total} "
                "layers are shown.").format(
                words=", ".join(q["scope_keywords"]),
                shown=len(q.get("layers") or []),
                total=q.get("scope_total_layers", len(q.get("layers") or []))))
        warnings += [str(n) for n in (q.get("notes") or [])]
        self._set_warnings(warnings)

        self._sev_map = severity_for(q)
        self._render_rows()

        self._layer_names = list(q.get("layers") or [])
        self.layers_btn.setVisible(bool(self._layer_names))
        self.layers.setText(i18n.t("All {n} layers: {names}").format(
            n=len(self._layer_names), names=", ".join(self._layer_names)))

    def _render_rows(self):
        """(Re)draws the table from `self._raw_rows` in whatever unit is
        currently selected -- called on a fresh measurement and again, with
        no re-measuring, whenever the unit picker changes."""
        converting = self._display_unit != "native" and self._base_unit is not None
        self._filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._raw_rows))
        for r, (item, kind, layer, value, unit_name) in enumerate(self._raw_rows):
            if converting and kind != KIND_COUNT:
                shown_value = convert_value(kind, value, self._base_unit, self._display_unit)
                abbr = _UNIT_ABBR[self._display_unit]
                shown_unit = abbr if kind == KIND_LENGTH else f"sq {abbr}"
            else:
                shown_value, shown_unit = value, unit_name
            sev = self._sev_map.get(item) or self._sev_map.get(layer) or SEV_GOOD
            bg = theme.qcolor(_SEV_BG[sev])

            dot = QTableWidgetItem("●")
            dot.setForeground(theme.qcolor(_SEV_INK[sev]))
            dot.setTextAlignment(Qt.AlignCenter)
            dot.setToolTip(_sev_tooltip(sev))
            dot.setBackground(bg)
            dot.setFlags(dot.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_TRUST, dot)

            cells = [item, i18n.t(kind), layer, _fmt(kind, shown_value), shown_unit]
            for offset, text in enumerate(cells):
                c = COL_ITEM + offset
                cell = QTableWidgetItem(text)
                cell.setBackground(bg)
                if c == COL_VALUE:
                    cell.setData(Qt.UserRole, shown_value)
                    cell.setData(Qt.UserRole + 1, kind)
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    font = cell.font()
                    font.setBold(True)
                    cell.setFont(font)
                else:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, cell)
            hidden = QTableWidgetItem(f"{r:06d}")
            hidden.setFlags(hidden.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_SORT, hidden)
        self.table.setSortingEnabled(True)
        self.table.sortItems(COL_SORT, Qt.AscendingOrder)
        if not self._raw_rows:
            self.table.setRowCount(1)
            self.table.setItem(0, COL_ITEM, QTableWidgetItem(i18n.t(
                "No measurable lines, polylines, hatches or blocks were found.")))
        self._filling = False

    def _on_unit_changed(self, _index: int = 0):
        if self._q is None:
            return
        self._display_unit = self.unit_combo.currentData()
        self._render_rows()

    def rows(self) -> list:
        """What is on screen, row by row -- for tests, for eyes, and for
        the CSV export (edits included)."""
        out = []
        for r in range(self.table.rowCount()):
            out.append(tuple(
                (self.table.item(r, c).text() if self.table.item(r, c) else "")
                for c in range(COL_ITEM, COL_UNIT + 1)))
        return out

    # ── warnings dropdown ────────────────────────────────────────────────
    def _set_warnings(self, warnings: list[str]):
        self._warnings = warnings
        self.warn_list.clear()
        for w in warnings:
            item = QListWidgetItem(f"•  {w}")
            item.setBackground(theme.qcolor(theme.WARN_BG))
            item.setForeground(theme.qcolor(theme.WARN_INK))
            self.warn_list.addItem(item)
        self.warn_btn.setVisible(bool(warnings))
        self.warn_list.setVisible(False)
        self._refresh_warn_btn_text()

    def _refresh_warn_btn_text(self):
        arrow = "▴" if self.warn_list.isVisible() else "▾"
        self.warn_btn.setText(i18n.t("⚠ {n} rules & warnings {arrow}").format(
            n=len(self._warnings), arrow=arrow))

    def _toggle_warnings(self):
        self.warn_list.setVisible(not self.warn_list.isVisible())
        self._refresh_warn_btn_text()

    def warning_lines(self) -> list[str]:
        """The raw warning text, one per rule -- for tests and for callers
        that still want the plain list rather than the widget."""
        return list(self._warnings)

    # ── editing ──────────────────────────────────────────────────────────
    def _on_edited(self, cell: QTableWidgetItem):
        if self._filling or cell.column() != COL_VALUE:
            return
        kind = cell.data(Qt.UserRole + 1) or KIND_LENGTH
        text = cell.text().strip().replace(",", "")
        try:
            value = float(text)
        except ValueError:
            return                  # a bad edit is left alone, never crashes
        self._filling = True
        cell.setData(Qt.UserRole, value)
        cell.setText(_fmt(kind, value))
        self._filling = False
        cell.setToolTip(i18n.t("Edited and confirmed by you."))
        r = cell.row()
        bg = theme.qcolor(theme.OK_BG)
        for c in (COL_TRUST, COL_ITEM, COL_KIND, COL_LAYER, COL_VALUE, COL_UNIT):
            it = self.table.item(r, c)
            if it:
                it.setBackground(bg)
        dot = self.table.item(r, COL_TRUST)
        if dot:
            dot.setForeground(theme.qcolor(theme.OK_INK))
            dot.setToolTip(_sev_tooltip(SEV_GOOD))

    # ── the bigger window ────────────────────────────────────────────────
    def _open_big(self):
        if self._q is None:
            return
        if self._big_window is None:
            self._big_window = MeasuredTableWindow(self._q, self)
        else:
            self._big_window.set_quantities(self._q)
        self._big_window.show()
        self._big_window.raise_()
        self._big_window.activateWindow()

    # ── CSV to the Desktop ───────────────────────────────────────────────
    def _save_desktop_csv(self):
        rows = self.rows()
        if not rows:
            return
        out_dir = desktop_dir()
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"BOQ_Quantities_{int(time.time())}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([i18n.t("Item"), i18n.t("Measured as"), i18n.t("Layer"),
                       i18n.t("Value"), i18n.t("Unit")])
            w.writerows(rows)
        self.saved_label.setText(i18n.t("Saved to your Desktop → {path}").format(path=path))
        self.saved_label.setVisible(True)

    def _toggle_layers(self):
        show = not self.layers.isVisible()
        self.layers.setVisible(show)
        self.layers_btn.setText(i18n.t("Hide the layer names") if show
                                else i18n.t("Show every layer name"))


class MeasuredTableWindow(QDialog):
    """The same table, full size, in its own resizable window -- for a
    sheet with more rows than the embedded panel's capped height can show
    without most of it scrolling out of sight."""

    def __init__(self, q: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Measured quantities — full view"))
        self.resize(900, 640)
        col = QVBoxLayout(self)
        self.table_widget = MeasuredTable()
        self.table_widget.table.setMaximumHeight(16_777_215)   # QWIDGETSIZE_MAX
        col.addWidget(self.table_widget)
        self.set_quantities(q)

    def set_quantities(self, q: dict):
        self.table_widget.set_quantities(q)

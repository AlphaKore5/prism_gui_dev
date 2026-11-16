"""
Leads & Outreach — Import (Apollo's People / Companies > Import > CSV)
──────────────────────────────────────────────────────────────────────
Apollo's import is two screens (knowledge.apollo.io, "Import a CSV of Contacts"
and "… of Accounts", read 23-Sep-2026, and the owner's screenshots):

  1  Two cards side by side — Import contacts, Import accounts — each saying
     which columns a file needs, with "Select CSV File" and "Download sample
     template".
  2  One page: "Column Mappings" — every column of the file as a card, the
     field it maps to picked for it where Apollo recognises the header, with
     the first rows' values under it; "N columns detected · K recognized ·
     M need mapping" and "Hide recognised columns" — over the settings:
     for contacts a Settings tab (stage, "If contacts already exist",
     "Auto-assign accounts?", "Add to a list?") and a Data enrichment tab;
     for accounts one Settings tab (stage, "If accounts already exist",
     "Add to a list?", Intelligent enrichment). The file sits at the foot
     with a bin to start over, beside Cancel and Import.

Nothing is searched: the import becomes a Contact / Account CSV import filter
the owner applies when he wants to. Settings Prism has no use for (record
owners, CRM push) are left out rather than shown doing nothing; enrichment is
offered only where Prism has a real source for it, and says what it costs.

The dialog only COLLECTS: `result()` hands the parsed people (or companies)
and the settings back, and the workbench writes the stores (contacts.py,
accounts.py, imports.py) — so this stays a plain modal a test can drive
without a disk. `choose_file` and `save_template_to` are the two file dialogs;
a test replaces them.
"""
from __future__ import annotations

import csv
import os

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from prospector import importing as IMP

KINDS = ("contacts", "accounts")
# Apollo: "Avoid uploading CSV files with more than 10,000 rows." Prism keeps
# every contact in one local file, so here it is the limit, said up front.
MAX_ROWS = 10000
_SAMPLES = 3                    # sample values shown under each column
_CARD_W = 248                   # one column card in the mapping row

# What makes a row importable — Apollo's rule, as Prism reads it (importing.py).
_NEEDS = {
    "contacts": ({"name", "first_name", "last_name", "email", "linkedin"},
                 "Map at least one column to a contact name, Contact email or "
                 "Contact LinkedIn URL — that is what tells people apart."),
    "accounts": ({"name", "website"},
                 "Map at least one column to Account name or Account website."),
}
# The sample template "Download sample template" writes — Apollo's recommended
# columns, one made-up row showing the format.
_TEMPLATES = {
    "contacts": [["First Name", "Last Name", "Title", "Company Name", "Company Website",
                  "Email", "Person LinkedIn URL", "City", "State", "Country",
                  "Contact Stage"],
                 ["Asha", "Rao", "Managing Director", "Rao Precision Works",
                  "raoprecision.example", "asha@raoprecision.example",
                  "linkedin.com/in/asha-rao-example", "Vadodara", "Gujarat", "India",
                  "Cold"]],
    "accounts": [["Account Name", "Account Website", "Industry", "# Employees", "City",
                  "Country", "Account Stage"],
                 ["Rao Precision Works", "raoprecision.example", "Machinery", "51-200",
                  "Vadodara", "India", "Cold"]],
}


def _title(kind: str) -> str:
    return i18n.t("Import contacts") if kind == "contacts" else i18n.t("Import accounts")


def _needs_line(kind: str) -> str:
    if kind == "contacts":
        return i18n.t("For accurate mapping, include at least one of these fields: "
                      "Company Name, Company Website, LinkedIn URL and/or Contact "
                      "Email — and each person's name.")
    return i18n.t("For accurate mapping, include at least one of these fields: "
                  "Account Name and/or Account Website (the domain, without www).")


def _examples(rows, index: int) -> list:
    """The first few non-empty values of one column."""
    seen = []
    for row in rows or ():
        value = row[index] if index < len(row) else None
        text = " ".join(str(value).split()) if value is not None else ""
        if text and text not in seen:
            seen.append(text)
            if len(seen) >= _SAMPLES:
                break
    return seen


def _badge_pixmap(icon_name: str, size: int = 76) -> QPixmap:
    """Apollo's card mark: a round well with the kind's icon, and a small
    accent disc with an up-arrow over its lower right."""
    app_dpr = 2.0
    px = QPixmap(int(size * app_dpr), int(size * app_dpr))
    px.setDevicePixelRatio(app_dpr)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    well = size - 12
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.NEUTRAL[100]))
    p.drawEllipse(QRectF(0, 0, well, well))
    glyph = icons.pixmap(icon_name, 30, theme.NEUTRAL[700], 1.8)
    p.drawPixmap(int((well - 30) / 2), int((well - 30) / 2), glyph)
    disc = 30
    p.setBrush(QColor(theme.ACCENT))
    p.drawEllipse(QRectF(size - disc, size - disc, disc, disc))
    arrow = icons.pixmap("arrow-up", 18, "#ffffff", 2.2)
    p.drawPixmap(int(size - disc + (disc - 18) / 2), int(size - disc + (disc - 18) / 2),
                 arrow)
    p.end()
    return px


class _KindCard(QFrame):
    """One of the landing page's two cards."""

    def __init__(self, kind: str, primary: bool, on_select, on_template, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setObjectName("importCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#importCard{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}")
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_6, theme.SPACE_6, theme.SPACE_6, theme.SPACE_5)
        col.setSpacing(theme.SPACE_3)
        mark = QLabel()
        mark.setPixmap(_badge_pixmap("users" if kind == "contacts" else "building"))
        mark.setStyleSheet("background:transparent;border:none;")
        col.addWidget(mark, 0, Qt.AlignHCenter)
        col.addWidget(C.label(_title(kind), level="SECTION"), 0, Qt.AlignHCenter)
        rows = C.label(i18n.t("You can import up to {n} rows at a time.").format(
            n=f"{MAX_ROWS:,}"), level="BODY")
        col.addWidget(rows, 0, Qt.AlignHCenter)
        info = QHBoxLayout()
        info.setSpacing(theme.SPACE_2)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("help", 16, theme.NEUTRAL[600]))
        glyph.setStyleSheet("background:transparent;border:none;")
        info.addWidget(glyph, 0, Qt.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(theme.SPACE_2)
        text.addWidget(C.label(_needs_line(kind), level="SUPPORT", wrap=True))
        text.addWidget(C.label(i18n.t(
            "The file is read on this computer and kept in your Prism folder — it "
            "is not sent anywhere."), level="META", wrap=True))
        info.addLayout(text, 1)
        col.addLayout(info)
        col.addSpacing(theme.SPACE_2)
        self.select_btn = C.button(i18n.t("Select CSV File"),
                                   "primary" if primary else "secondary",
                                   on_click=lambda: on_select(kind))
        col.addWidget(self.select_btn, 0, Qt.AlignHCenter)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.hairline())
        self.template_btn = C.button(i18n.t("Download sample template"), "link",
                                     icon_name="download",
                                     on_click=lambda: on_template(kind))
        col.addWidget(self.template_btn, 0, Qt.AlignHCenter)
        col.addStretch(1)


class _ColumnCard(QFrame):
    """One column of the file on the mapping page: its header and whether
    Prism recognised it, the field it goes to, and its first values."""

    changed = Signal()

    def __init__(self, header: str, samples: list, choices: list, guess: str,
                 parent=None):
        super().__init__(parent)
        self.setObjectName("mapCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(_CARD_W)
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.title = QLabel(header or i18n.t("(no header)"))
        self.title.setStyleSheet(theme.type_css("CARD_TITLE", theme.TEXT))
        self.title.setToolTip(header)
        head.addWidget(self.title, 1)
        self.mark = QLabel()
        self.mark.setStyleSheet("background:transparent;border:none;")
        head.addWidget(self.mark, 0, Qt.AlignVCenter)
        col.addLayout(head)
        self.combo = QComboBox()
        for key, label in choices:
            self.combo.addItem(label, key)
        self.combo.setCurrentIndex(max(0, self.combo.findData(guess)))
        self.combo.currentIndexChanged.connect(lambda _i: self._sync())
        col.addWidget(self.combo)
        for value in samples or [""]:
            cell = QLabel(value)
            cell.setObjectName("mapSample")
            cell.setToolTip(value)
            cell.setMinimumWidth(0)
            cell.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            cell.setStyleSheet(
                f"QLabel#mapSample{{color:{theme.NEUTRAL[800]};font-size:13px;"
                f"padding:8px 2px;border:none;border-top:1px solid {theme.HAIRLINE};"
                f"background:transparent;}}")
            col.addWidget(cell)
        col.addStretch(1)
        self._sync()

    def value(self) -> str:
        return self.combo.currentData()

    def recognized(self) -> bool:
        return self.value() not in (IMP.CUSTOM, IMP.SKIP)

    def _sync(self):
        ok = self.recognized()
        self.mark.setPixmap(icons.pixmap("check" if ok else "alert", 16,
                                         theme.OK_INK if ok else theme.WARN_INK, 2.0))
        self.mark.setToolTip(i18n.t("Recognised") if ok else (
            i18n.t("Kept as a custom field") if self.value() == IMP.CUSTOM
            else i18n.t("Not imported")))
        edge = theme.HAIRLINE if ok else theme.WARN_INK
        self.setStyleSheet(
            f"QFrame#mapCard{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};"
            f"border-top:3px solid {edge};border-radius:{theme.R_CONTROL}px;}}")
        self.changed.emit()


def _chip(text: str, ink: str, bg: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(
        f"color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
        f"padding:3px 10px;font-size:12px;font-weight:500;")
    return lab


def _field_row(label: str, control: QWidget) -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(theme.SPACE_1)
    col.addWidget(C.label(label, level="SUPPORT"))
    col.addWidget(control)
    return box


class ImportWizard(PrismDialog):
    """Apollo's import, in a window. `kind` is the card that leads (its
    Select CSV File is the primary button); either card can be used. `lists`
    are the list names "Add to a list?" offers."""

    def __init__(self, kind: str, start_dir: str = "", parent=None, lists=()):
        if kind not in KINDS:
            raise ValueError(f"unknown import kind {kind!r}")
        super().__init__(i18n.t("Import"), i18n.t(
            "People or companies from a CSV or Excel file — nothing is searched"),
            icon="upload", parent=parent)
        self.kind = kind
        self.start_dir = start_dir
        self.lists = [str(n) for n in lists or () if str(n).strip()]
        self.path = ""
        self.sheet = ""
        self.columns: list = []
        self.rows: list = []
        self._cards: list = []
        self._stack = QStackedWidget()
        self._stack.addWidget(self._landing_page())
        self._map_host = QWidget()                  # rebuilt for each file
        self._map_lay = QVBoxLayout(self._map_host)
        self._map_lay.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._map_host)
        self.body.addWidget(self._stack, 1)

        self._file_chip = self._chip_widget()
        self.footer.add_utility(self._file_chip)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self._import = self.button(i18n.t("Import"), "primary", icon_name="upload",
                                   on_click=self._go_import)
        self.footer.set_primary(self._import)
        self.resize(1120, 760)
        self._show(0)

    # ── what the caller gets ──────────────────────────────────────────────────
    def result(self) -> dict:
        """{"kind", "path", "name", "sheet", "mapping" ({header: field}),
        "settings", "rows", "skipped", and "leads" or "companies"} — read
        after exec() returns Accepted."""
        mapping = self.mapping()
        out = {"kind": self.kind, "path": self.path,
               "name": os.path.basename(self.path), "sheet": self.sheet,
               "mapping": {str(h) or f"Column {i + 1}": m
                           for i, (h, m) in enumerate(zip(self.columns, mapping))},
               "settings": self.settings(), "rows": len(self.rows)}
        if self.kind == "contacts":
            # A tab's name stands in for a missing industry — one tab's. All of
            # them at once carry theirs on each row, in the Sheet column.
            one_tab = "" if self.sheet == IMP.ALL_SHEETS_NAME else self.sheet
            out["leads"], out["skipped"] = IMP.contacts_from_rows(
                self.columns, self.rows, mapping, one_tab)
        else:
            out["companies"], out["skipped"] = IMP.accounts_from_rows(
                self.columns, self.rows, mapping)
        return out

    def mapping(self) -> list:
        return [card.value() for card in self._cards]

    def settings(self) -> dict:
        if not self.path:
            return {}
        list_name = " ".join(self._list_box.currentText().split())
        out = {"stage": self._stage.currentData() or "Cold",
               "update_existing": self._existing.currentData() == "update",
               "add_to_list": bool(list_name), "list_name": list_name}
        if self.kind == "contacts":
            out["assign_accounts"] = self._assign.currentData() or "none"
            out["find_emails"] = self._find_emails.isChecked()
            out["find_phones"] = False          # no phone source connected yet
        else:
            out["find_websites"] = self._find_websites.isChecked()
            out["enrich_all"] = self._enrich_all.isChecked()
        return out

    # ── page 1: the two cards ─────────────────────────────────────────────────
    def _landing_page(self) -> QWidget:
        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_5)
        row.addStretch(1)
        self._kind_cards = {}
        for kind in KINDS:
            card = _KindCard(kind, kind == self.kind, self._select, self._template)
            card.setMaximumWidth(460)
            self._kind_cards[kind] = card
            row.addWidget(card, 2)
        row.addStretch(1)
        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.addWidget(page, 1)
        self._file_error = C.label("", level="META", colour=theme.ERR_INK, wrap=True)
        col.addWidget(self._file_error)
        return wrap

    def choose_file(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self, _title(self.kind), self.start_dir,
            i18n.t("Sheets") + " (*.csv *.xlsx *.xlsm)")
        return path

    def save_template_to(self, kind: str) -> str:
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save the sample template"),
            os.path.join(self.start_dir, f"Prism {kind} template.csv"), "CSV (*.csv)")
        return path

    def _select(self, kind: str):
        self.kind = kind
        path = self.choose_file()
        if path:
            self.load(path)

    def _template(self, kind: str):
        path = self.save_template_to(kind)
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                csv.writer(f).writerows(_TEMPLATES[kind])
        except OSError as e:
            self._file_error.setText(i18n.t("Couldn't save the template: {err}")
                                     .format(err=e))
            return
        self._file_error.setText(i18n.t("Saved the sample template to {path}")
                                 .format(path=path))

    def load(self, path: str, sheet: str = "") -> bool:
        """Read a file (and one of its tabs) and open the mapping page; False,
        with the reason on the landing page, when it can't be read, holds no
        rows or holds more than MAX_ROWS."""
        self._file_error.setText("")
        try:
            tabs = IMP.tabs(path)
            # Every tab unless the owner picks one: a workbook's second tab
            # was never read while the picker sat on the first.
            if not sheet and len(tabs) > 1:
                sheet = IMP.ALL_SHEETS
            name, header, rows = IMP.read_table(path, sheet)
        except Exception as e:                              # noqa: BLE001
            self._file_error.setText(i18n.t("Couldn't read this file: {err}")
                                     .format(err=str(e) or e.__class__.__name__))
            return False
        if len(rows) > MAX_ROWS:
            self._file_error.setText(i18n.t(
                "This file has {n} rows — split it into files of up to {max} rows "
                "each and import them one at a time.").format(
                    n=f"{len(rows):,}", max=f"{MAX_ROWS:,}"))
            return False
        self.path, self.sheet, self.columns, self.rows = path, name, header, rows
        self._sheet_key = IMP.ALL_SHEETS if sheet == IMP.ALL_SHEETS else name
        self._tabs = tabs
        self._build_map_page()
        self._show(1)
        return True

    # ── page 2: mappings over settings ────────────────────────────────────────
    def _build_map_page(self):
        while self._map_lay.count():
            item = self._map_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, theme.SPACE_2, 0)
        col.setSpacing(theme.SPACE_3)
        scroll.setWidget(page)
        self._map_lay.addWidget(scroll)

        col.addWidget(C.label(i18n.t("Column Mappings"), level="SECTION"))
        col.addWidget(C.label(i18n.t(
            "Each column below is mapped to a field in Prism. Where it can, Prism "
            "detects and maps the field for you. For the rest, pick the field that "
            "best describes the column — or keep it as a custom field. This decides "
            "how every record is read."), level="BODY", wrap=True))
        note = QFrame()
        note.setObjectName("mapNote")
        note.setAttribute(Qt.WA_StyledBackground, True)
        note.setStyleSheet(f"QFrame#mapNote{{background:{theme.WELL};border:none;"
                           f"border-radius:{theme.R_CONTROL}px;}}")
        nl = QHBoxLayout(note)
        nl.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        nl.addWidget(C.label(i18n.t(
            "Don't see the field you want? Choose Keep as a custom field — the "
            "column stays on every record, and Search people finds it."),
            level="SUPPORT", wrap=True))
        col.addWidget(note)

        if len(getattr(self, "_tabs", ())) > 1:
            pick = QHBoxLayout()
            pick.addWidget(C.label(i18n.t("Sheet"), level="SUPPORT"))
            self._tab = QComboBox()
            total = sum(n for _tab, n in self._tabs)
            self._tab.addItem(i18n.t("All sheets ({n})").format(n=f"{total:,}"),
                              IMP.ALL_SHEETS)
            for tab, n in self._tabs:
                self._tab.addItem(f"{tab} ({n})", tab)
            self._tab.setCurrentIndex(max(0, self._tab.findData(
                getattr(self, "_sheet_key", self.sheet))))
            self._tab.activated.connect(
                lambda _i: self.load(self.path, self._tab.currentData() or ""))
            pick.addWidget(self._tab)
            pick.addStretch(1)
            col.addLayout(pick)

        counts = QHBoxLayout()
        counts.setSpacing(theme.SPACE_2)
        counts.addWidget(C.label(i18n.t("{n} columns detected:").format(
            n=len(self.columns)), level="SUPPORT"))
        self._recognized_chip = _chip("", theme.OK_INK, theme.OK_BG)
        self._unmapped_chip = _chip("", theme.WARN_INK, theme.WARN_BG)
        counts.addWidget(self._recognized_chip)
        counts.addWidget(self._unmapped_chip)
        self._hide_known = QCheckBox(i18n.t("Hide recognised columns"))
        self._hide_known.toggled.connect(lambda _on: self._sync())
        counts.addSpacing(theme.SPACE_2)
        counts.addWidget(self._hide_known)
        counts.addStretch(1)
        col.addLayout(counts)

        strip = QScrollArea()
        strip.setObjectName("mapStrip")
        strip.setWidgetResizable(True)
        strip.setFrameShape(QFrame.NoFrame)
        strip.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        strip.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        strip.setStyleSheet(
            f"QScrollArea#mapStrip{{background:transparent;border:none;}}"
            f"QScrollArea#mapStrip QScrollBar:horizontal{{height:9px;"
            f"background:transparent;}}"
            f"QScrollArea#mapStrip QScrollBar::handle:horizontal{{"
            f"background:{theme.NEUTRAL[300]};border-radius:4px;min-width:30px;}}"
            f"QScrollArea#mapStrip QScrollBar::add-line:horizontal,"
            f"QScrollArea#mapStrip QScrollBar::sub-line:horizontal{{width:0px;}}")
        inner = QWidget()
        row = QHBoxLayout(inner)
        row.setContentsMargins(0, 0, 0, theme.SPACE_2)
        row.setSpacing(theme.SPACE_3)
        guess = IMP.guess_mapping(self.columns, self.kind)
        choices = ([(k, i18n.t(label)) for k, label in IMP.FIELDS[self.kind]]
                   + [(k, i18n.t(label)) for k, label in IMP.EXTRA_CHOICES])
        self._cards = []
        for i, header in enumerate(self.columns):
            card = _ColumnCard(header, _examples(self.rows, i), choices, guess[i])
            card.changed.connect(self._sync)
            row.addWidget(card)
            self._cards.append(card)
        row.addStretch(1)
        strip.setWidget(inner)
        strip.setMinimumHeight(250)
        col.addWidget(strip)
        self._map_error = C.label("", level="META", colour=theme.ERR_INK, wrap=True)
        col.addWidget(self._map_error)

        col.addWidget(self._settings_block())
        col.addStretch(1)
        self._sync()

    def _settings_block(self) -> QWidget:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, theme.SPACE_2, 0, 0)
        col.setSpacing(theme.SPACE_3)
        tabs = QHBoxLayout()
        tabs.setSpacing(theme.SPACE_4)
        self._tab_btns = []
        self._settings_stack = QStackedWidget()
        names = [i18n.t("Settings")]
        pages = [self._settings_page()]
        if self.kind == "contacts":
            names.append(i18n.t("Data enrichment"))
            pages.append(self._enrichment_page())
        for i, (name, page) in enumerate(zip(names, pages)):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setObjectName("setTab")
            b.clicked.connect(lambda _=False, k=i: self._pick_settings(k))
            tabs.addWidget(b)
            self._tab_btns.append(b)
            self._settings_stack.addWidget(page)
        tabs.addStretch(1)
        bar = QWidget()
        bar.setObjectName("setTabs")
        bar.setStyleSheet(
            f"QWidget#setTabs{{border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QPushButton#setTab{{background:transparent;border:none;border-radius:0px;"
            f"border-bottom:2px solid transparent;color:{theme.NEUTRAL[600]};"
            f"padding:8px 2px;font-size:13px;font-weight:500;}}"
            f"QPushButton#setTab:checked{{color:{theme.TEXT};"
            f"border-bottom:2px solid {theme.ACCENT};}}")
        bar.setLayout(tabs)
        col.addWidget(bar)
        col.addWidget(self._settings_stack)
        self._pick_settings(0)
        return box

    def _pick_settings(self, index: int):
        self._settings_stack.setCurrentIndex(index)
        for i, b in enumerate(self._tab_btns):
            b.setChecked(i == index)

    def _stage_combo(self) -> QComboBox:
        from addons.leads import accounts, contacts
        stages = contacts.STAGES if self.kind == "contacts" else accounts.STAGES
        combo = QComboBox()
        combo.addItem(i18n.t("Use stage from CSV"), "csv")
        for stage in stages:
            combo.addItem(i18n.t("Set every one to: {stage}").format(stage=i18n.t(stage)),
                          stage)
        return combo

    def _settings_page(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_4)
        grid.setVerticalSpacing(theme.SPACE_3)
        what = i18n.t("contacts") if self.kind == "contacts" else i18n.t("accounts")
        self._stage = self._stage_combo()
        self._stage_touched = False
        # A pick the owner made is kept; until then the stage follows the
        # mapping ("Use stage from CSV" the moment a stage column is mapped).
        self._stage.activated.connect(self._touch_stage)
        grid.addWidget(_field_row(i18n.t("Stage"), self._stage), 0, 0)
        self._existing = QComboBox()
        self._existing.addItem(i18n.t("Update the existing record with information "
                                      "from CSV"), "update")
        self._existing.addItem(i18n.t("Do not update the existing record"), "keep")
        grid.addWidget(_field_row(i18n.t("If {what} already exist in Prism").format(
            what=what), self._existing), 0, 1)
        row = 1
        if self.kind == "contacts":
            self._assign = QComboBox()
            self._assign.addItem(i18n.t("Assign/create account based on Website/Email "
                                        "Domain in the CSV"), "domain")
            self._assign.addItem(i18n.t("Assign/create account based on Account Name "
                                        "in the CSV"), "name")
            self._assign.addItem(i18n.t("Do not assign accounts"), "none")
            grid.addWidget(_field_row(i18n.t("Auto-assign accounts?"), self._assign),
                           row, 0)
            row += 1
        self._list_box = QComboBox()
        self._list_box.setEditable(True)
        self._list_box.addItem("")
        for name in self.lists:
            self._list_box.addItem(name)
        self._list_box.lineEdit().setPlaceholderText(i18n.t("Enter or create a list…"))
        self._list_box.setCurrentIndex(0)
        grid.addWidget(_field_row(i18n.t("Add to a list?"), self._list_box), row, 0, 1, 2)
        row += 1
        if self.kind == "accounts":
            grid.addWidget(C.label(i18n.t("Intelligent enrichment"), level="SUPPORT"),
                           row, 0, 1, 2)
            row += 1
            self._find_websites = QCheckBox(i18n.t(
                "Find a website for rows with only an account name — one Exa search "
                "each; Prism keeps a match only when the name clearly fits"))
            self._enrich_all = QCheckBox(i18n.t(
                "Fill in the website, size, revenue and HQ of every account from "
                "Exa — one search each"))
            for w in (self._find_websites, self._enrich_all):
                w.toggled.connect(lambda _on: self._sync_estimate())
                grid.addWidget(w, row, 0, 1, 2)
                row += 1
            self._estimate = C.label("", level="META", wrap=True)
            grid.addWidget(self._estimate, row, 0, 1, 2)
            row += 1
        grid.addWidget(self._info_box(), row, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        return page

    def _info_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("setInfo")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setStyleSheet(f"QFrame#setInfo{{background:{theme.WELL};border:none;"
                          f"border-radius:{theme.R_CONTROL}px;}}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        if self.kind == "contacts":
            text = i18n.t(
                "You can find these contacts' e-mails two ways: turn on Find e-mail "
                "addresses on the Data enrichment tab above, or after importing, "
                "filter People by this import (Contact CSV import), tick them and "
                "press Find e-mails.")
        else:
            text = i18n.t(
                "Importing never finds e-mails or phone numbers. To find people at "
                "these companies, filter People by this import (Account CSV "
                "import) and press Find new people.")
        lay.addWidget(C.label(text, level="SUPPORT", wrap=True))
        return box

    def _enrichment_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        self._find_emails = QCheckBox(i18n.t("Find e-mail addresses"))
        self._find_emails.toggled.connect(lambda _on: self._sync_estimate())
        col.addWidget(self._find_emails)
        self._email_meta = C.label("", level="META", wrap=True)
        self._email_meta.setContentsMargins(26, 0, 0, 0)
        col.addWidget(self._email_meta)
        # Not a checkbox: a phone lookup is made on people you have chosen, after
        # the import, where it shows what it will cost and asks first.
        meta = C.label(i18n.t("Phone numbers: once they are imported, select people and "
                              "press Find phones."), level="META", wrap=True)
        col.addWidget(meta)
        col.addStretch(1)
        return page

    def _chip_widget(self) -> QWidget:
        chip = QFrame()
        chip.setObjectName("fileChip")
        chip.setAttribute(Qt.WA_StyledBackground, True)
        chip.setStyleSheet(
            f"QFrame#fileChip{{background:{theme.CARD};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;}}")
        row = QHBoxLayout(chip)
        row.setContentsMargins(theme.SPACE_2, 2, 2, 2)
        row.setSpacing(theme.SPACE_1)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("file", 16, theme.NEUTRAL[700]))
        glyph.setStyleSheet("background:transparent;border:none;")
        row.addWidget(glyph)
        self._file_name = QLabel("")
        self._file_name.setStyleSheet(f"color:{theme.TEXT};font-size:13px;"
                                      f"font-weight:600;background:transparent;border:none;")
        row.addWidget(self._file_name)
        self._drop_file = C.icon_button("trash", i18n.t("Remove this file and choose "
                                                        "another"),
                                        on_click=self._start_over)
        row.addWidget(self._drop_file)
        return chip

    # ── keeping the page honest ───────────────────────────────────────────────
    def _sync(self):
        if not self._cards:
            return
        known = sum(1 for c in self._cards if c.recognized())
        self._recognized_chip.setText(i18n.t("✓ {n} recognized").format(n=known))
        rest = len(self._cards) - known
        self._unmapped_chip.setText(i18n.t("{n} need mapping").format(n=rest))
        self._unmapped_chip.setVisible(rest > 0)
        hide = self._hide_known.isChecked()
        for card in self._cards:
            card.setVisible(not (hide and card.recognized()))
        # "Use stage from CSV" means something only with a stage column.
        mapped_stage = "stage" in self.mapping()
        item = self._stage.model().item(0)
        if item is not None:
            item.setEnabled(mapped_stage)
        if self._stage.currentData() == "csv" and not mapped_stage:
            self._stage.setCurrentIndex(max(0, self._stage.findData("Cold")))
        elif mapped_stage and not self._stage_touched:
            self._stage.setCurrentIndex(0)
        self._sync_estimate()
        self._sync_import()

    def _mapping_ok(self) -> bool:
        needed, message = _NEEDS[self.kind]
        ok = bool(needed & set(self.mapping()))
        text = "" if ok else i18n.t(message)
        # 22-Sep-2026: a company-research export (Company Name, Industry,
        # City — never a person) went in as people and nothing came of it.
        # Say which import it is instead of only what it lacks.
        if not ok and self.kind == "contacts" and \
                _NEEDS["accounts"][0] & set(IMP.guess_mapping(self.columns, "accounts")):
            text += " " + i18n.t("This file looks like a list of companies — cancel, "
                                 "then use Import ▾ › Accounts.")
        self._map_error.setText(text)
        return ok

    def _sync_estimate(self):
        if not self._cards:
            return
        data = self.result()
        if self.kind == "contacts":
            missing = sum(1 for l in data["leads"] if not (l.email or "").strip())
            self._email_meta.setText(i18n.t(
                "{n} of the {m} contacts have no e-mail. Each one is looked up — "
                "free verifiers first, then a finder credit where they can't "
                "confirm it — and Prism asks before it spends.").format(
                    n=missing, m=len(data["leads"])))
        else:
            companies = data["companies"]
            if self._enrich_all.isChecked():
                n = len(companies)
            elif self._find_websites.isChecked():
                n = sum(1 for c in companies
                        if c.get("name") and not (c.get("website") or "").strip())
            else:
                n = 0
            text = (i18n.t("About 1 Exa search — Prism asks before it runs it.")
                    if n == 1 else
                    i18n.t("About {n} Exa searches — Prism asks before it runs "
                           "them.").format(n=n) if n else "")
            self._estimate.setText(text)

    def _sync_import(self):
        self._import.setEnabled(bool(self.path) and self._mapping_ok())

    # ── moving between the two pages ──────────────────────────────────────────
    def _show(self, step: int):
        self._step = step
        self._stack.setCurrentIndex(step)
        self._file_chip.setVisible(step == 1)
        self._import.setVisible(step == 1)
        if step == 0:
            self.header.set_title(i18n.t("Import"))
            self.header.set_subtitle(i18n.t(
                "People or companies from a CSV or Excel file — nothing is searched"))
        else:
            self.header.set_title(_title(self.kind))
            self.header.set_subtitle(i18n.t("{n} rows included").format(
                n=f"{len(self.rows):,}"))
            self._file_name.setText(os.path.basename(self.path))
            self._sync_import()

    def _touch_stage(self, _index: int):
        self._stage_touched = True

    def _start_over(self):
        self.path, self.sheet, self.columns, self.rows = "", "", [], []
        self._cards = []
        self._show(0)

    def _go_import(self):
        if self.path and self._mapping_ok():
            self.accept()

"""
Leads & Outreach — every filter at once, Apollo's "More Filters"
─────────────────────────────────────────────────────────────────
Apollo keeps a few filters in the rail and the rest behind a button: "Click
Show Filters > More Filters to see all the available filters … Click Apply
filters" (knowledge.apollo.io, "Search filters glossary", read 23-Sep-2026) —
a window of every filter, searchable and grouped, each with a pin that keeps
it in the rail.

This is that window over the filters Prism can really back. Its body is the
rail's own panel (filter_panel.FilterPanel, in its `catalog` form) editing a
COPY of the rail's filters and pins: nothing on the page moves while it is
open, Apply hands both back (FilterPanel.open_all_filters), Cancel leaves the
page exactly as it was.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import icons


class AllFiltersDialog(PrismDialog):
    """Every filter, from the rail's panel `source`:

        dlg = AllFiltersDialog(rail_panel)
        if dlg.exec() == QDialog.Accepted:
            spec, pinned = dlg.result()
    """

    def __init__(self, source, parent=None):
        super().__init__(i18n.t("All filters"),
                         i18n.t("Search them, pin the ones you use to keep them in the "
                                "rail, then Apply."), parent=parent)
        from addons.leads.filter_panel import FilterPanel
        self.setMinimumSize(760, 600)
        self.panel = FilterPanel(suggest=source._suggest, catalog=True, kind=source.kind)
        imports = source._imports
        self.panel.set_imports(imports.get("contact_imports", ()),
                               imports.get("account_imports", ()))
        self.panel.set_record_options(source._records)
        self.panel.set_pinned(source.pinned())
        self.panel.set_spec(source.spec())

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_4)
        # The groups, Apollo's column down the left.
        groups = QVBoxLayout()
        groups.setContentsMargins(0, 0, 0, 0)
        groups.setSpacing(2)
        self.group_btns: dict = {}
        for key, name in (("", "All filters"),) + tuple(source.categories()):
            b = QPushButton(i18n.t(name))
            b.setObjectName("fgroupBtn")
            b.setCheckable(True)
            b.setChecked(key == "")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._pick_group(k))
            groups.addWidget(b)
            self.group_btns[key] = b
        groups.addStretch(1)
        side = QWidget()
        side.setFixedWidth(168)
        side.setLayout(groups)
        side.setStyleSheet(
            f"QPushButton#fgroupBtn{{background:transparent;border:none;text-align:left;"
            f"padding:7px 10px;border-radius:{theme.R_CONTROL}px;min-height:20px;"
            f"color:{theme.NEUTRAL[700]};font-size:13px;font-weight:600;}}"
            f"QPushButton#fgroupBtn:hover{{background:{theme.WELL};}}"
            f"QPushButton#fgroupBtn:checked{{background:{theme.INFO_BG};"
            f"color:{theme.INFO_INK};}}")
        row.addWidget(side)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(theme.SPACE_3)
        self.search = QLineEdit()
        self.search.setObjectName("finput")
        self.search.setPlaceholderText(i18n.t("Search filters"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icons.icon("search", 15, theme.NEUTRAL[500]),
                              QLineEdit.LeadingPosition)
        self.search.textChanged.connect(lambda _t: self._narrow())
        right.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setObjectName("allFiltersScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea#allFiltersScroll{background:transparent;"
                             "border:none;}")
        scroll.setWidget(self.panel)
        right.addWidget(scroll, 1)
        row.addLayout(right, 1)
        self.body.addLayout(row, 1)

        self._group = ""
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Apply filters"), "primary",
                                            on_click=self.accept))

    def _pick_group(self, key: str) -> None:
        self._group = key
        for k, b in self.group_btns.items():
            b.setChecked(k == key)
        self._narrow()

    def _narrow(self) -> None:
        self.panel.set_catalog_filter(self.search.text(), self._group)

    def result(self) -> tuple:
        """(the filters as set here, the filters pinned to the rail)."""
        return self.panel.spec(), self.panel.pinned()

"""The only way Prism tells someone something went wrong.

A QMessageBox with a technical string in it is a phone call. This is the
replacement: what happened, what to do about it as numbered steps, and — where
Prism can do something for them — a button that goes straight there.

Three deliberate choices:

  · The steps are the point, so they get the visual weight, not the error.
  · The technical detail is present but folded away. A business owner does not
    want it; the person they forward the screenshot to does.
  · "Save diagnostics" only appears when contacting us is genuinely the next
    step. Offering it every time trains people to send a file instead of
    reading the fix.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

import friendly
import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.controls import heading, meta


class ProblemDialog(PrismDialog):
    """Shows a friendly.Problem. `chosen_action` is the action key the user
    pressed, or "" — the caller decides what to do with it, because only the
    window knows how to open its own Settings."""

    def __init__(self, problem: friendly.Problem, detail: str = "", parent=None):
        # The alert glyph used to be #8a5a2f — one digit off theme.WARN_INK,
        # so it was a colour the palette did not contain and the accent
        # rotation could not see. It is the warn tone now, on the warn tint,
        # which is also what every other "a person is needed here" cue in the
        # app wears.
        pad = C.IconPad("alert", theme.WARN, 38, theme.R_CONTROL, 19)
        super().__init__(problem.title, problem.what, parent=parent,
                         leading=pad, closable=False)
        self.problem = problem
        self.chosen_action = ""
        self._detail = detail or ""
        self.setWindowTitle(i18n.t("Prism"))
        self.setMinimumWidth(560)

        root = self.body

        # ── what to do ─────────────────────────────────────────────────
        if problem.steps:
            box = QFrame()
            box.setObjectName("stepsBox")
            box.setAttribute(Qt.WA_StyledBackground, True)
            box.setStyleSheet(
                f"QFrame#stepsBox {{ background: {theme.INFO_BG};"
                f" border: 1px solid {theme.HAIRLINE};"
                f" border-radius: {theme.R_CARD}px; }}")
            inner = QVBoxLayout(box)
            inner.setContentsMargins(theme.CARD_PAD, theme.SPACE_4,
                                     theme.CARD_PAD, theme.SPACE_4)
            inner.setSpacing(theme.SPACE_2 + 1)
            inner.addWidget(C.kicker(i18n.t("Try this")))
            for index, step in enumerate(problem.steps, 1):
                inner.addWidget(_Step(index, step))
            root.addWidget(box)

        # ── the technical detail, folded away ──────────────────────────
        if self._detail:
            self._detail_label = QLabel(self._detail)
            self._detail_label.setWordWrap(True)
            self._detail_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._detail_label.setStyleSheet(
                f"color: {theme.NEUTRAL[600]}; font-size: 11.5px;"
                f"font-family: monospace;")
            self._detail_label.setVisible(False)
            self._toggle = QPushButton(i18n.t("Show technical details"))
            self._toggle.setObjectName("linkBtn")
            self._toggle.setCursor(Qt.PointingHandCursor)
            self._toggle.setFlat(True)
            self._toggle.setStyleSheet(
                f"text-align: left; border: none; color: {theme.NEUTRAL[600]};"
                f"font-size: 12px; padding: 0;")
            self._toggle.clicked.connect(self._toggle_detail)
            root.addWidget(self._toggle, alignment=Qt.AlignLeft)
            root.addWidget(self._detail_label)

        # ── the way out ────────────────────────────────────────────────
        root.addStretch(1)
        if problem.ask_support:
            self.footer.add_utility(self.button(
                i18n.t("Save details to send us"), "secondary",
                icon_name="file", small=True,
                on_click=self._save_diagnostics,
                tooltip=i18n.t("Writes a file describing what happened. Your "
                               "API key, passwords and licence key are not "
                               "in it.")))

        # Exactly one primary either way. When Prism can DO something about
        # the problem, that is the primary and dismissing is the secondary;
        # when it cannot, the only button there is becomes the primary.
        if problem.action:
            self.footer.add_secondary(
                self.button(i18n.t("Not now"), on_click=self.accept))
            self.footer.set_primary(self.button(
                i18n.t(problem.action_label or "Fix this"), "primary",
                on_click=self._take_action))
        else:
            self.footer.set_primary(
                self.button(i18n.t("OK"), "primary", on_click=self.accept))

    # ── behaviour ──────────────────────────────────────────────────────
    def _toggle_detail(self):
        showing = not self._detail_label.isVisible()
        self._detail_label.setVisible(showing)
        self._toggle.setText(i18n.t("Hide technical details") if showing
                             else i18n.t("Show technical details"))
        self.adjustSize()

    def _take_action(self):
        self.chosen_action = self.problem.action
        self.accept()

    def _save_diagnostics(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import os
        import time

        import diagnostics
        import paths
        suggested = os.path.join(
            paths.picker_start_dir(),
            f"prism-problem-{time.strftime('%Y%m%d-%H%M')}.txt")
        target, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save details"), suggested, "Text (*.txt)")
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(friendly.as_text(self.problem))
                f.write("\n\n" + "=" * 60 + "\n\n")
                if self._detail:
                    f.write(f"Technical detail:\n{self._detail}\n\n")
                f.write(diagnostics.report())
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Prism"), i18n.t(
                "Couldn't write the file: {error}").format(error=e))
            return
        QMessageBox.information(self, i18n.t("Prism"), i18n.t(
            "Saved to {path}\n\nEmail it to us and we'll be able to see "
            "exactly what happened.").format(path=target))


class _Step(QWidget):
    """One numbered instruction. The number is a real column so the wrapped
    text lines up under itself rather than under the digit."""

    def __init__(self, index: int, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        number = QLabel(str(index))
        number.setFixedWidth(18)
        number.setAlignment(Qt.AlignTop | Qt.AlignRight)
        # 13.5px was one of nine shipped sizes inside a single 4px band. Both
        # halves of the row are on the scale now — SUPPORT — so a step reads
        # as the same size as every other explanatory line in the app.
        number.setStyleSheet(
            theme.type_css("SUPPORT", theme.ACCENT_RAMP[700])
            + " font-weight: 700;")
        row.addWidget(number)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(theme.type_css("SUPPORT", theme.NEUTRAL[800]))
        row.addWidget(body, stretch=1)


def show_problem(parent, error: object, context: str = "") -> str:
    """Explain an error and show it. Returns the action key the user chose.

    The one call every error site should make. Also logs the real error, so
    the friendly version on screen never costs us the technical one.
    """
    try:
        import diagnostics
        diagnostics.write("ERROR", f"[{context or 'general'}] {error}")
    except Exception:                                   # noqa: BLE001
        pass
    problem = friendly.explain(error, context)
    dialog = ProblemDialog(problem, detail=str(error), parent=parent)
    dialog.exec()
    return dialog.chosen_action

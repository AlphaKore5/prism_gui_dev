"""The Guide screen: how to use Prism, in the order you meet it."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QSizePolicy,
)

import i18n
import theme
from widgets import controls as C
from widgets.panel_base import (
    _Elided, _ActionCard, _wrapped, Page,
)


class GuidePanel(Page):
    TITLE = "How to use Prism"
    BLURB = "For someone who has never used AI before."

    navigate = Signal(str)          # a key for MainWindow._handle_command

    # The five stages of the mental model, which is the one thing a first-time
    # user has to hold. Same order the engine runs them in.
    STEPS = [
        ("pencil", "Describe",
         "Say the job in your own words. No form, no settings, no prompt."),
        ("list", "Plan",
         "Prism works out the stages and which tool should run each one."),
        ("check", "Review",
         "Read the plan. Drop a step you don't want, or send it elsewhere."),
        ("play", "Execute",
         "Your Chrome opens and the tools are worked as you, in order."),
        ("archive", "Results",
         "Everything comes back in one place, and is kept in History."),
    ]

    CARDS = [
        ("pencil", "Describe a job in your own words",
         "“Write a proposal for a 40-camera CCTV project.” Prism works out "
         "which AI tools are needed, uses them in order, and hands you the "
         "finished result."),
        ("sliders", "Review the plan before it runs",
         "Every stage is shown as a plain-English step. Drop any you don't "
         "want, or send a step to a different tool."),
        ("grid", "The add-ons are purpose-built",
         "Email inquiry automation, BOQ and Email spamming are dedicated tools for "
         "recurring jobs — they don't need a plan, just your files."),
        ("globe", "Prism's own language, and the AI's, are separate",
         "Set them independently in Settings — a Gujarati-speaking owner may "
         "still want the output in English."),
        # Not in the design, but the single most common support question: the
        # tools run in the customer's own Chrome, signed in as them, and
        # nobody guesses that from the outside.
        ("lock", "It drives your own browser",
         "Prism opens your Chrome and works the tools as you, using the "
         "accounts you already pay for. Nothing is sent to a Prism server."),
    ]

    # Every destination the rail can reach, as a way out of the guide. The
    # rail was slimmed to eleven controls on purpose and several screens now
    # live inside Settings, so "where is it" is a real question and this is
    # the screen it should be answered on. The keys are MainWindow's own
    # command names — see _handle_command.
    DIRECT = [
        ("workbench", "plus", "Start a task",
         "Describe a job and let Prism plan it."),
        ("runs", "clock", "History",
         "Everything you have run, and what came back."),
        ("inquiry", "inbox", "Email inquiry automation",
         "Inquiries logged, quoted and followed up."),
        ("boq", "file", "BOQ",
         "Quantities off a drawing or a written spec."),
        ("agents", "sliders", "Settings",
         "Your tools, your languages, your workspace and your licence."),
    ]

    def header_actions(self):
        return [
            C.button(i18n.t("Start a task"), "primary", icon_name="plus",
                     on_click=lambda: self.navigate.emit("workbench")),
        ]

    def build(self):
        self._col.setContentsMargins(0, 0, 0, 48)
        self._col.addWidget(C.SectionHeader(
            i18n.t("What happens when you start a task"),
            i18n.t("Five steps, always in this order.")))
        flow = C.CardGrid(min_col_width=150, max_columns=5)
        flow.add_all([self._step_card(i + 1, icon, title, body)
                      for i, (icon, title, body) in enumerate(self.STEPS)])
        self._col.addWidget(flow)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Worth knowing"),
            i18n.t("The five things people ask about first.")))
        grid = C.CardGrid(min_col_width=310)
        grid.add_all([self._note_card(icon, title, body)
                      for icon, title, body in self.CARDS])
        self._col.addWidget(grid)

        self._col.addWidget(C.SectionHeader(
            i18n.t("Where things are"),
            i18n.t("The rail keeps eleven controls; everything else lives "
                   "inside one of these.")))
        where = C.CardGrid(min_col_width=272)
        cards = []
        for key, icon, title, body in self.DIRECT:
            card = _ActionCard(icon, i18n.t(title), i18n.t(body))
            card.clicked.connect(lambda k=key: self.navigate.emit(k))
            cards.append(card)
        where.add_all(cards)
        self._col.addWidget(where)
        self._col.addStretch(1)

    def _step_card(self, index: int, icon: str, title: str, body: str):
        card = C.Card()
        card.setMinimumHeight(130)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_2)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15))
        top.addWidget(C.kicker(f"{index:02d}"), stretch=1)
        col.addLayout(top)
        col.addWidget(_Elided(i18n.t(title), "CARD_TITLE"))
        col.addWidget(_wrapped(i18n.t(body), "META"))
        return card

    def _note_card(self, icon: str, title: str, body: str):
        card = C.Card()
        card.setMinimumHeight(120)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.SPACE_3)
        top.addWidget(C.IconPad(icon, theme.ACCENT, 30, theme.R_CONTROL, 15),
                      alignment=Qt.AlignTop)
        top.addWidget(_wrapped(i18n.t(title), "CARD_TITLE"), stretch=1)
        col.addLayout(top)
        col.addWidget(_wrapped(i18n.t(body), "SUPPORT"))
        return card


# ── AI tools ────────────────────────────────────────────────────────────────

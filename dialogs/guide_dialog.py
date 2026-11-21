"""The guide — what Prism can do, for someone who has never used AI.

Not documentation. Documentation describes features; this answers the two
questions a first-time user actually has, in this order:

    "What is this for?"        — one paragraph, no jargon
    "What do I type?"          — real examples they can copy

Every section ends with something they can press, because reading about a
thing and finding it are different problems and the second one is where
people give up.

Written at the level of someone who runs a fabrication shop or a marketing
agency and has never used ChatGPT. No word appears here that they would have
to look up: not "prompt", not "pipeline", not "LLM", not "agent" — Prism's own
screens say "tool" and "step", and so does this.

Locked add-ons still appear, greyed, with what they do. That is deliberate:
this is the only place a customer can find out what else Prism does, and a
list with holes in it teaches them nothing.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

import i18n
import licensing
import theme
from addons import registry
from dialogs.base import PrismDialog
from widgets import icons
from widgets.controls import heading, kicker, meta


@dataclass(frozen=True)
class Topic:
    icon: str
    title: str
    body: str
    examples: tuple[str, ...] = ()
    action: str = ""            # a sidebar command key
    action_label: str = ""
    feature: str = ""           # the entitlement it needs, "" if always on
    addon: str = ""             # the add-on it describes; skipped while that is off


TOPICS: tuple[Topic, ...] = (
    Topic(
        "home", "Start here — what Prism actually is",
        "Prism does jobs for you using the AI websites you already have "
        "accounts for. You describe the job in your own words, in one box. "
        "Prism works out which tools are needed, opens them in a browser, "
        "asks each one, passes the answer to the next, and puts the finished "
        "result in front of you.\n\n"
        "You do not need to know which AI does what. That is the whole point "
        "of it.",
        ("write a proposal for a 40-camera CCTV job at a textile mill",
         "find me 20 packaging companies in Gujarat and draft an intro email",
         "make an Instagram post announcing our new CNC machine"),
    ),
    Topic(
        "pencil", "Writing your task",
        "Write it the way you would explain it to a new employee. Say what "
        "you want, who it is for, and anything that must be included. Longer "
        "is better than shorter — Prism can use every detail you give it.\n\n"
        "If a file matters, attach it with Add file. You can attach from this "
        "computer or straight from your Google Drive.",
        ("Vague:  make a post\n"
         "Better: make an Instagram post for our new CNC machine, aimed at "
         "small fabrication shops, mentioning the 3-year warranty",),
    ),
    Topic(
        "list", "Doing several jobs in a row",
        "Type your first job, press Add task, then type the next one. Prism "
        "queues them and works through them one at a time while you do "
        "something else. When they are all finished, one window shows you "
        "each job, which tools were used, and a link to every result.",
        action="home", action_label="Go to the task box",
    ),
    Topic(
        "search", "The steps, and changing them",
        "Before anything runs, Prism shows you the steps it intends to take — "
        "look things up, think it through, write it up, and so on. Each step "
        "names the tool that will do it.\n\n"
        "Click any step to leave it out. Click the tool name next to a step "
        "to use a different tool for that one. Nothing happens until you "
        "press Start the work.",
    ),
    Topic(
        "mic", "Speaking instead of typing",
        "Press Speak and say the job out loud. Useful on site, or when the "
        "job is long enough that typing it is a chore.\n\n"
        "You can also switch on Listen for \"Prism\" in the sidebar and it "
        "will start a recording whenever it hears its name.",
    ),
    Topic(
        "clock", "Finding what you did before",
        "Everything Prism finishes is kept. History shows every past job — "
        "what you asked, which tools ran, and what each one said.\n\n"
        "Nothing is ever deleted automatically, and an expired licence does "
        "not lock you out of it.",
        action="runs", action_label="Open History",
    ),
    Topic(
        "lock", "Signing in to the AI tools",
        "Prism uses your own accounts, in its own browser window. The first "
        "time — and occasionally after that — you need to sign in.\n\n"
        "Click Login tabs, sign in to each tool in the window that opens, and "
        "close it. Prism remembers from then on.",
        action="login", action_label="Open Login tabs",
    ),
    # ── the add-ons ────────────────────────────────────────────────────
    Topic(
        "file", "BOQ — bills of quantities",
        "Attach a CAD drawing and Prism measures it: counts the symbols, adds "
        "up the cable runs, and produces a priced bill of quantities you can "
        "check line by line. It saves the measured numbers to a spreadsheet "
        "so you can verify every figure.\n\n"
        "No drawing? Describe the job in words and it will work from that.",
        ("BOQ for a 40-camera CCTV job, drawing attached, circles are cameras",),
        action="boq", action_label="Open BOQ", feature="boq",
    ),
    Topic(
        "mail", "Email — write and send",
        "Prism finds who to contact, writes the email from your attached "
        "files, shows you the draft to edit, and sends each person their own "
        "copy through your own email account.\n\n"
        "You always see the draft before anything is sent.",
        ("email our new price list to packaging companies in Ahmedabad",),
        action="email", action_label="Open Email", feature="email",
    ),
    Topic(
        "video", "Reel — short videos",
        "Turns a script into a finished vertical video, in your brand "
        "colours, ready to post.",
        ("a 20-second reel introducing our workshop",),
        action="reel", action_label="Open Reel", feature="reel",
    ),
    Topic(
        "list", "BOM & Stock",
        "Match a parts list against what you actually have in stock and get "
        "the shortage list.",
        feature="boq", addon="bom",
    ),
    # ── settings ───────────────────────────────────────────────────────
    Topic(
        "sliders", "Settings you may want",
        "Language — read Prism in Hindi or Gujarati, and choose separately "
        "what language the AI writes back in.\n\n"
        "Your role — if your company gave you a designation key, this is "
        "where it goes.\n\n"
        "Specialists — which tool handles which kind of step.",
        action="config", action_label="Open Settings",
    ),
    Topic(
        "help", "When something goes wrong",
        "Prism tells you what happened and what to do about it. Follow the "
        "numbered steps in the message — they are in order of what usually "
        "fixes it.\n\n"
        "If that isn't enough, Lumi has a written answer for most "
        "things, and opens the way to our team when none of them fits.",
        action="support", action_label="Ask Lumi",
    ),
)


class GuideDialog(PrismDialog):
    command_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(
            i18n.t("How to use Prism"),
            i18n.t("Everything Prism can do, and what to type to get it. No "
                   "experience needed."),
            icon="help", parent=parent, scrollable=True)
        self.setWindowTitle(i18n.t("How to use Prism"))
        self.resize(760, 720)
        self.setMinimumSize(560, 480)

        state = licensing.state()
        for topic in TOPICS:
            if topic.addon and (registry.is_off(topic.addon)
                                or registry.is_absent(topic.addon)):
                continue
            unlocked = not topic.feature or state.has(topic.feature)
            self.body.addWidget(
                _TopicCard(topic, unlocked, self.command_requested))
        self.body.addStretch(1)

        note = meta(i18n.t("Anything greyed out isn't part of your plan — "
                           "ask us and we'll switch it on."))
        note.setWordWrap(True)
        self.footer.add_note(note)
        # Close is the ONLY thing this footer does, so it is the primary. A
        # solid accent "Close" beside nothing else is not a competing call to
        # action; a hairline one on an otherwise empty bar is just quiet.
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))


class _TopicCard(QFrame):
    def __init__(self, topic: Topic, unlocked: bool, signal, parent=None):
        super().__init__(parent)
        self.setObjectName("row" if unlocked else "rowMuted")
        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(9)

        head = QHBoxLayout()
        head.setSpacing(10)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(
            topic.icon if unlocked else "lock", 17,
            theme.ACCENT if unlocked else theme.NEUTRAL[400]))
        glyph.setAlignment(Qt.AlignTop)
        head.addWidget(glyph)
        title = QLabel(i18n.t(topic.title))
        title.setObjectName("h5")
        title.setWordWrap(True)
        if not unlocked:
            title.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        head.addWidget(title, stretch=1)
        if not unlocked:
            tag = QLabel(i18n.t("Not in your plan"))
            tag.setObjectName("tagOutline")
            head.addWidget(tag)
        box.addLayout(head)

        body = QLabel(i18n.t(topic.body))
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {theme.NEUTRAL[700] if unlocked else theme.NEUTRAL[500]};"
            f"font-size: 13.5px;")
        box.addWidget(body)

        if topic.examples:
            box.addWidget(kicker(i18n.t("Try typing"), muted=True))
            for example in topic.examples:
                sample = QLabel(example)
                sample.setWordWrap(True)
                sample.setTextInteractionFlags(Qt.TextSelectableByMouse)
                sample.setStyleSheet(
                    f"background: {theme.NEUTRAL[100]}; padding: 9px 12px;"
                    f"border-radius: 3px; font-size: 13px;"
                    f"color: {theme.NEUTRAL[800]};")
                box.addWidget(sample)

        if topic.action and unlocked:
            go = QPushButton(i18n.t(topic.action_label or "Open"))
            go.setObjectName("smallBtn")
            go.setCursor(Qt.PointingHandCursor)
            go.clicked.connect(
                lambda _=False, key=topic.action: signal.emit(key))
            box.addWidget(go, alignment=Qt.AlignLeft)

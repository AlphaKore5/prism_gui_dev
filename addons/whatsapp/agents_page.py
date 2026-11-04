"""Automations → AI agents: a teammate that answers from what you have taught it.

You tell an agent who your business is and how it should sound, give it skills (jobs, some of which collect details from the customer), teach it (text, question and
answer pairs, a web page, a whole website, a file), and — if you like — give it addresses of yours to call. When no flow takes a customer's message, the default agent
answers from that knowledge, and hands the chat to your team when it does not know, when the customer asks for a person, or after a number of replies you choose.

What you change is a DRAFT. Customers meet the published copy, and it only changes when you press Publish. "Try it" talks to the draft; up to three test numbers can chat
with the draft on real WhatsApp. Results show what the agent did, and the questions it could not answer, ready to be taught.
"""
from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp import ui
from addons.whatsapp.agent_actions import ActionsSection
from addons.whatsapp.agent_knowledge import MAX_FILE_BYTES, KnowledgeDialog, KnowledgeSection, read_document  # noqa: F401  (kept importable from here)
from addons.whatsapp.agent_profile import ProfileSection
from addons.whatsapp.agent_results import ResultsSection
from addons.whatsapp.agent_settings import AgentSettingsSection
from addons.whatsapp.agent_skills import SkillsSection
from addons.whatsapp.agent_train import TrainPanel
from widgets import controls as C

CONFIG_KEYS = ("instructions", "handoff_words", "max_replies", "business_hours_only", "profile", "voice", "skills", "actions", "settings")
EMPTY = {"instructions": "", "handoff_words": [], "max_replies": 12, "business_hours_only": False, "profile": {}, "voice": {}, "skills": [], "actions": [], "settings": {}}
SAVE_MS = 1500


def sections() -> list:
    return [("business", i18n.t("Business and voice")), ("skills", i18n.t("Skills")), ("knowledge", i18n.t("Knowledge")), ("actions", i18n.t("Actions")),
            ("settings", i18n.t("Settings")), ("train", i18n.t("Try it")), ("results", i18n.t("Results"))]


def live_words(agent: dict) -> tuple:
    """(words, tone) for whether customers are meeting this agent."""
    status, version = agent.get("status") or "draft", agent.get("published_version") or 0
    if status == "published":
        return ((i18n.t("Live · v{n} · unpublished changes").format(n=version), "warn") if agent.get("unpublished_changes") else (i18n.t("Live · v{n}").format(n=version), "ok"))
    return (i18n.t("Paused"), "warn") if status == "paused" else (i18n.t("Draft — not live yet"), "quiet")


class AgentEditor(QWidget):
    def __init__(self, owner: "AgentsSection", agent: dict, parent=None):
        super().__init__(parent)
        self.owner, self.agent = owner, agent
        self.draft = {k: copy.deepcopy(agent.get(k, EMPTY[k])) for k in CONFIG_KEYS}
        self.dirty = False
        self._saving = False
        self._again = False
        self._after: list = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_MS)
        self._timer.timeout.connect(self.save)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, theme.SPACE_3, 0)
        outer.setSpacing(theme.SPACE_3)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.name = QLineEdit(agent.get("name") or "")
        self.name.setMinimumHeight(38)
        self.name.setAccessibleName(i18n.t("Agent name"))
        self.name.textChanged.connect(lambda _t: self.edited())
        head.addWidget(self.name, 1)
        self.live = C.Pill("", "quiet")
        head.addWidget(self.live)
        self.status = C.Pill("", "quiet")
        head.addWidget(self.status)
        head.addWidget(C.label(i18n.t("On"), level="META", colour=theme.NEUTRAL[600]))
        self.on = C.ToggleSwitch()
        self.on.setChecked(bool(agent.get("enabled")))
        self.on.toggled.connect(self._toggle)
        head.addWidget(self.on)
        self.pause_btn = C.button(i18n.t("Pause"), "tertiary", on_click=self.pause)
        head.addWidget(self.pause_btn)
        self.publish_btn = C.button(i18n.t("Publish"), "primary", on_click=self.publish)
        head.addWidget(self.publish_btn)
        head.addWidget(C.icon_button("trash", i18n.t("Delete this agent"), on_click=self._delete, colour=theme.ERR_INK))
        outer.addLayout(head)
        line = QHBoxLayout()
        self.note = ui.note()
        line.addWidget(self.note, 1)
        self.saved = ui.note()
        line.addWidget(self.saved)
        outer.addLayout(line)

        self.chips = C.FilterChips(sections(), "business")
        self.chips.setMinimumWidth(640)
        self.chips.changed.connect(self.show_section)
        outer.addWidget(self.chips)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        hl = QVBoxLayout(host)
        hl.setContentsMargins(0, 0, theme.SPACE_2, theme.SPACE_4)
        self.stack = QStackedWidget()
        hl.addWidget(self.stack)
        hl.addStretch(1)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self.profile = ProfileSection(self)
        self.skills = SkillsSection(self)
        self.knowledge = KnowledgeSection(self)
        self.actions = ActionsSection(self)
        self.settings = AgentSettingsSection(self)
        self.results = ResultsSection(self)
        card, tc = ui.card("")
        self.train = TrainPanel(self)
        tc.addWidget(self.train)
        train_page = QWidget()
        QVBoxLayout(train_page).addWidget(card)
        train_page.layout().setContentsMargins(0, 0, 0, 0)
        self._keys = [k for k, _l in sections()]
        for w in (self.profile, self.skills, self.knowledge, self.actions, self.settings, train_page, self.results):
            self.stack.addWidget(w)

        # names the rest of the screen (and its tests) know the controls by
        self.instructions, self.words, self.max, self.closed_only, self.default = (self.profile.instructions, self.profile.words, self.profile.max, self.profile.closed_only,
                                                                                    self.profile.default)
        self.try_it = self.train
        self.usage_card, self.usage_text, self.usage_bar = self.results.usage_card, self.results.usage_text, self.results.usage_bar
        self.kb_col = self.knowledge.kb_col

        self._status()
        self._live_status()
        self.knowledge.load()
        self.settings.load_numbers()
        self.show_usage(owner.usage)

    # ── showing ──────────────────────────────────────────────────────────────
    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    def show_section(self, key: str):
        if key in self._keys:
            self.stack.setCurrentIndex(self._keys.index(key))
            self.chips.set_current(key)
            if key == "results":
                self.results.load()
            elif key == "train":
                self.train.refresh_banner()

    def _status(self):
        if not self.agent.get("enabled"):
            self.status.setText(i18n.t("Off"))
            self.status.set_tone("quiet")
        elif self.agent.get("is_default"):
            self.status.setText(i18n.t("Answering"))
            self.status.set_tone("ok")
        else:
            self.status.setText(i18n.t("On — only when a flow hands over"))
            self.status.set_tone("info")

    def _live_status(self):
        words, tone = live_words(self.agent)
        self.live.setText(words)
        self.live.set_tone(tone)
        published = self.agent.get("status") == "published"
        self.pause_btn.setVisible(published)
        self.publish_btn.setText(i18n.t("Publish changes") if published else i18n.t("Publish"))
        self.publish_btn.setEnabled(not published or bool(self.agent.get("unpublished_changes")) or self.dirty)
        self.train.refresh_banner()

    def show_usage(self, usage: dict):
        self.results.show_usage(usage)

    # ── saving ───────────────────────────────────────────────────────────────
    def changes(self) -> dict:
        out = copy.deepcopy(self.draft)
        out["name"] = self.name.text().strip()
        return out

    def edited(self):
        self.dirty = True
        self.saved.set(i18n.t("Unsaved changes…"), "quiet")
        self.agent["unpublished_changes"] = True
        self._timer.start()
        self._live_status()

    def ensure_saved(self, then):
        """Run `then` once the draft on screen is the draft on the server."""
        if self.dirty or self._saving:
            self.save(then)
        else:
            then()

    def save(self, then=None):
        if self._saving:
            self._again = True
            if then:
                self._after.append(then)
            return
        if then:
            self._after.append(then)
        self._timer.stop()
        self._saving = True
        self.dirty = False
        ui.call(self, "ai/agents/update", {"agent_id": self.agent["id"], "changes": self.changes()}, done=self._saved, failed=lambda m, _d: self._save_failed(m))

    def _save_failed(self, message: str):
        self._saving = False
        self.dirty = True
        self._after = []
        self.saved.error(message)
        self._live_status()

    def _saved(self, reply: dict):
        self._saving = False
        shown = reply.get("agent") or {}
        self.agent.update({k: shown[k] for k in ("name", "status", "unpublished_changes", "published_version", "updated_at") if k in shown})
        self.saved.ok(i18n.t("Saved."))
        self.owner.refresh_list()
        if self._again:
            self._again = False
            self.save()
            return
        self._live_status()
        after, self._after = self._after, []
        for fn in after:
            fn()

    # ── publishing ───────────────────────────────────────────────────────────
    def publish(self):
        self.publish_btn.setEnabled(False)
        self.ensure_saved(lambda: ui.call(self, "ai/agents/publish", {"agent_id": self.agent["id"]}, done=self._published, failed=lambda m, _d: self._publish_failed(m)))

    def _publish_failed(self, message: str):
        self._live_status()
        self.say(message, error=True)

    def _published(self, reply: dict):
        self.agent.update(status="published", unpublished_changes=False, published_version=int(reply.get("version") or 1))
        warnings = list(reply.get("warnings") or [])
        text = i18n.t("Published as version {n}. Customers meet it from now on.").format(n=self.agent["published_version"])
        if warnings:
            self.note.set(text + " " + " ".join(warnings), "warn")
        else:
            self.say(text)
        self._live_status()
        self.owner.refresh_list()

    def pause(self):
        ui.call(self, "ai/agents/unpublish", {"agent_id": self.agent["id"]},
                done=lambda r: (self.agent.update(status="paused", unpublished_changes=True), self.say(i18n.t("Paused. Customers get no AI answers from this agent until you publish again.")),
                                self._live_status(), self.owner.refresh_list()), failed=lambda m, _d: self.say(m, error=True))

    # ── on, default, delete ──────────────────────────────────────────────────
    def _toggle(self, on: bool):
        def revert(message: str):
            self.on.blockSignals(True)
            self.on.setChecked(bool(self.agent.get("enabled")))
            self.on.blockSignals(False)
            self.say(message, error=True)

        def done(_r):
            self.agent.update(enabled=on, **({} if on else {"is_default": False}))
            if on and self.agent.get("status") == "draft":                  # switching on for the first time publishes it
                self.agent.update(status="published", published_version=1, unpublished_changes=False)
            self.profile.default.blockSignals(True)
            self.profile.default.setChecked(bool(self.agent.get("is_default")))
            self.profile.default.blockSignals(False)
            self._status()
            self._live_status()
            self.owner.refresh_list()
        self.ensure_saved(lambda: ui.call(self, "ai/agents/set_enabled", {"agent_id": self.agent["id"], "enabled": on}, done=done, failed=lambda m, _d: revert(m)))

    def set_default(self, on: bool):
        def revert(message: str):
            self.profile.default.blockSignals(True)
            self.profile.default.setChecked(bool(self.agent.get("is_default")))
            self.profile.default.blockSignals(False)
            self.say(message, error=True)
        ui.call(self, "ai/agents/set_default", {"agent_id": self.agent["id"], "default": on},
                done=lambda r: (self.agent.update(is_default=on), self._status(), self.owner.refresh_list()), failed=lambda m, _d: revert(m))

    def _delete(self):
        if ui.confirm(self, i18n.t("Delete agent"), i18n.t("Delete “{n}” and everything it was taught? This can't be undone.").format(n=self.agent.get("name"))):
            self._timer.stop()
            self.knowledge.stop()
            ui.call(self, "ai/agents/delete", {"agent_id": self.agent["id"]}, done=lambda r: self.owner.deleted())

    # ── knowledge (kept under the names the screen has always used) ──────────
    def load_knowledge(self):
        self.knowledge.load()

    def _teach(self, mode: str):
        self.knowledge.teach(mode)

    def _forget(self, doc: dict):
        self.knowledge.forget(doc)


class AgentsSection(QWidget):
    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self.agents: list = []
        self.usage: dict = {}
        self.editor: Optional[AgentEditor] = None
        self._selected = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_4)
        left = QVBoxLayout()
        left.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("AI agents"), level="CARD_TITLE"), stretch=1)
        self.new_btn = C.button(i18n.t("New agent"), "primary", icon_name="plus", on_click=self._new)
        top.addWidget(self.new_btn)
        left.addLayout(top)
        self.note = ui.note()
        left.addWidget(self.note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        self.list_col = QVBoxLayout(host)
        self.list_col.setSpacing(theme.SPACE_2)
        self.list_col.setContentsMargins(0, 0, theme.SPACE_2, 0)
        scroll.setWidget(host)
        left.addWidget(scroll, 1)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(300)
        root.addWidget(holder)
        self.stack = QStackedWidget()
        self.state = C.EmptyState("sparkles", i18n.t("Loading…"), "", i18n.t("Try again"))
        self.state.clicked.connect(self._state_action)
        self.stack.addWidget(self.state)
        self.editor_holder = QWidget()
        self.editor_lay = QVBoxLayout(self.editor_holder)
        self.editor_lay.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.editor_holder)
        root.addWidget(self.stack, 1)
        self._state_kind = "loading"

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    def activate(self):
        ui.call(self, "ai/status", done=self._status, failed=lambda m, _d: None)
        self.refresh_list(first=True)

    def deactivate(self):
        pass

    def _status(self, reply: dict):
        self.usage = dict(reply.get("usage") or {})
        self.included = bool(reply.get("included", True))
        if self.editor is not None:
            self.editor.show_usage(self.usage)
        if not self.included:
            self.say(i18n.t("AI agents are part of the Premium plan and above."), error=True)

    def refresh_list(self, first: bool = False):
        ui.call(self, "ai/agents/list", done=lambda r: self._listed(r, first), failed=lambda m, _d: self._failed(m))

    def _failed(self, message: str):
        if not self.agents:
            self._show_state("failed", message)
        self.say(message, error=True)

    def _listed(self, reply: dict, first: bool):
        self.agents = list(reply.get("agents") or [])
        ui.clear(self.list_col)
        for a in self.agents:
            self.list_col.addWidget(self._row(a))
        self.list_col.addStretch(1)
        if self.editor is None and not self.agents:
            self._show_state("none")
        elif self.editor is None and first and self.agents:
            self.open_agent(self.agents[0]["id"])

    def _row(self, a: dict) -> QWidget:
        sel = str(a["id"]) == self._selected
        row = QFrame()
        row.setObjectName("waAgentRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(f"#waAgentRow {{ background: {'rgba(0,0,0,0.05)' if sel else 'rgba(255,255,255,0.55)'}; border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        col = QVBoxLayout(row)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(C.label(a.get("name") or "", level="SUPPORT", weight=700, wrap=True), stretch=1)
        word, tone = ((i18n.t("Answering"), "ok") if a.get("enabled") and a.get("is_default") else (i18n.t("On"), "info") if a.get("enabled") else (i18n.t("Off"), "quiet"))
        top.addWidget(C.Pill(word, tone))
        col.addLayout(top)
        stand = a.get("status")
        if stand in ("draft", "paused"):
            col.addWidget(C.Pill(i18n.t("Draft — not live yet") if stand == "draft" else i18n.t("Paused"), "warn" if stand == "paused" else "quiet"))
        col.addWidget(C.label(i18n.t("{n} things it knows").format(n=a.get("documents", 0)), level="META", colour=theme.NEUTRAL[600]))
        if a.get("open_gaps"):
            col.addWidget(C.label(i18n.t("{n} questions it could not answer").format(n=a["open_gaps"]), level="META", colour=theme.WARN_INK))
        row.mousePressEvent = lambda e, aid=a["id"]: self.open_agent(aid)
        return row

    def _show_state(self, kind: str, message: str = ""):
        title, body, action = {
            "loading": (i18n.t("Loading…"), "", None),
            "failed": (i18n.t("Couldn't load your AI agents"), message, i18n.t("Try again")),
            "none": (i18n.t("No AI agent yet"), i18n.t("An agent answers customers from what you teach it, and hands over to your team when it does not know."), i18n.t("New agent")),
            "pick": (i18n.t("Choose an agent"), i18n.t("Pick one on the left, or make a new one."), None),
        }[kind]
        self.state.set_text(title, body)
        if self.state.action is not None:
            self.state.action.setText(action or "")
            self.state.action.setVisible(bool(action))
        self._state_kind = kind
        self.stack.setCurrentIndex(0)

    def _state_action(self):
        if self._state_kind == "failed":
            self.activate()
        elif self._state_kind == "none":
            self._new()

    def open_agent(self, agent_id: str):
        self._selected = str(agent_id)
        ui.call(self, "ai/agents/get", {"agent_id": agent_id}, done=self._opened, failed=lambda m, _d: self.say(m, error=True))

    def _opened(self, reply: dict):
        if self.editor is not None:
            self.editor.hide()
            self.editor.setParent(None)
            self.editor.deleteLater()
        self.editor = AgentEditor(self, dict(reply.get("agent") or {}))
        self.editor_lay.addWidget(self.editor)
        self.stack.setCurrentIndex(1)
        self.refresh_list()

    def deleted(self):
        self.editor = None
        self._selected = ""
        self.say(i18n.t("Deleted."))
        self.refresh_list()
        self._show_state("pick")

    def _new(self):
        ui.call(self, "ai/agents/create", {"name": i18n.t("New agent"), "instructions": ""}, done=lambda r: self.open_agent(r["agent_id"]),
                failed=lambda m, _d: self.say(m, error=True))

"""Run history — every past run, as something you can actually read.

Runs are stored as raw JSON dumps (`~/.prism/runs/run_<epoch>.json`, written
by prism_terminal's config.save_run). Showing that file verbatim makes the
user parse a machine format to answer human questions: what did I ask, which
tool did what, what came back. So the file is read as data and re-rendered —
one section per step, with the step's plain-English name, the tool that ran
it, what Prism asked it, and what it said back as formatted prose."""
from __future__ import annotations
import json
import os
import time
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTextBrowser, QWidget, QPushButton, QSplitter, QSizePolicy,
    QComboBox,
)

import ai_server
import core_bridge as CB
import i18n
import identity
import paths
import roles as R
import theme
import viewer
import workspace
import entitlement_copy
from addons import registry
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons
from widgets.agents_panel import STAGE_COPY
from widgets.controls import heading, kicker
from widgets.markdown import render_markdown

_PATH_ROLE = 1000
_RECORD_ROLE = 1001


# Record keys that name the add-on that made the run (key == add-on key).
_RECORD_ADDON_KEYS = ("boq", "gerber", "step", "email", "reel")


def _when(path: str) -> tuple[str, str]:
    """('22 Jul 2026', '14:21') from run_<epoch>.json, falling back to the
    file's own mtime if the name isn't in that shape.

    Takes a FULL PATH, not a bare name: the fallback stats the file, and it
    was previously handed only the basename — so any name that failed the
    int() parse raised FileNotFoundError instead of falling back."""
    stamp = os.path.basename(path).removeprefix("run_").removesuffix(".json")
    try:
        moment = time.localtime(int(stamp))
    except ValueError:
        try:
            moment = time.localtime(os.path.getmtime(path))
        except OSError:
            return "—", "—"
    return time.strftime("%d %b %Y", moment), time.strftime("%H:%M", moment)


def _one_line(text: str, limit: int = 90) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def _editable_reel(url: str) -> bool:
    """A video with a Studio spec saved beside it — reel_<stamp>.json next
    to reel_<stamp>.mp4, scenes carrying real HTML. Same check
    widgets.output_panel.StageCard._editable_reel and
    widgets.artifacts_panel._editable_reel make — a past run's reel is no
    less editable than one still on the workbench."""
    if not url.lower().endswith(".mp4"):
        return False
    spec_path = url[:-4] + ".json"
    if not os.path.isfile(spec_path):
        folder = os.path.dirname(url)
        stem = os.path.splitext(os.path.basename(url))[0]
        cand = os.path.join(folder, stem + ".json")
        if os.path.isfile(cand):
            spec_path = cand
        elif folder and os.path.isdir(folder):
            try:
                jsons = [os.path.join(folder, f) for f in os.listdir(folder)
                         if f.lower().endswith(".json")]
                jsons.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                           reverse=True)
                if jsons:
                    spec_path = jsons[0]
            except OSError:
                pass
    try:
        with open(spec_path, encoding="utf-8") as f:
            spec = json.load(f)
        return CB.get_reel_edit().is_studio_spec(spec)
    except Exception:                                   # noqa: BLE001
        return False


def _attachment_name(entry) -> str:
    """Records written by the CLI store attachments as bare names; the GUI
    matches that, but a dict could turn up from an older or hand-edited file,
    so read both rather than throwing on the whole run."""
    if isinstance(entry, dict):
        return str(entry.get("name") or entry.get("path") or "?")
    return str(entry)


class _Elided(QLabel):
    """A label that shortens to fit rather than being cut off mid-word. The
    run list lives in a splitter, so the available width isn't known up front
    and a fixed character budget would clip at some sizes and waste space at
    others."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def paintEvent(self, event):
        metrics = QFontMetrics(self.font())
        self.setText(metrics.elidedText(self._full, Qt.ElideRight, self.width()))
        super().paintEvent(event)


class _RunItem(QWidget):
    """Two-line list row: when it ran, and what was asked."""

    def __init__(self, day: str, clock: str, query: str, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(2)
        when = QLabel(f"{day} · {clock}")
        when.setObjectName("meta")
        box.addWidget(when)
        what = _Elided(_one_line(query, 160) or "(no task recorded)")
        what.setStyleSheet("font-size: 13px; font-weight: 500;")
        box.addWidget(what)


def _person_label(person: dict) -> str:
    """'Ravi Patel — Sales' for the profile picker, degrading to whatever is
    known: a folder can exist for someone the roster has never heard of."""
    name = person.get("name") or ""
    role = R.label(person.get("role", ""))
    if person.get("is_self"):
        return f"{name or 'Me'} — {role or 'my work'}  (me)"
    if name and role:
        return f"{name} — {role}"
    return name or role or person["mid"]


def _role_chip(me: dict) -> QLabel:
    """A quiet marker on a working member's History saying whose it is. It is
    also the honest answer to 'why can I only see my own runs?'."""
    chip = QLabel(R.label(me.get("role", "")))
    chip.setObjectName("tagOutline")
    chip.setToolTip("Your own runs. Each role's work stays in its own folder.")
    return chip


class HistoryDialog(PrismDialog):
    # A Studio reel from a past run wants fixing by hand. Carries the mp4
    # path; MainWindow owns the browser editor and re-render (see
    # _edit_reel_layout on the main window), so this dialog only asks — and
    # closes itself first, since the editor and the re-render both surface
    # through the main window, which this modal dialog sits in front of.
    edit_reel = Signal(str)
    # A past run wants a change. Carries the whole record — its query, every
    # stage's output, the tab each answered in, the tool that did each — which
    # is exactly what a follow-up session is made of. MainWindow owns the
    # follow-up (see _follow_up_from_history); this dialog only asks, and
    # closes first for the same reason edit_reel does.
    follow_up = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(
            i18n.t("Run history"),
            i18n.t("Every run, re-rendered from its own record."),
            icon="clock", parent=parent)
        self.setWindowTitle("Run history")
        self.resize(960, 660)
        self.setMinimumSize(720, 480)

        root = self.body

        # Whose history is on screen. An owner or manager gets a picker over
        # everyone in the workspace; everybody else gets nothing at all — not
        # a disabled picker, which would advertise that other people's work is
        # there to be asked for.
        self.cfg = CB.config.load()
        self._me = identity.current()
        self._people = workspace.readable_members(self.cfg, self._me)
        self.who = None
        if self._me["admin"] and len(self._people) > 1:
            self.who = QComboBox()
            self.who.setToolTip(
                "Whose work to show. As a manager you can open any member's "
                "history; they only ever see their own.")
            for person in self._people:
                self.who.addItem(_person_label(person), person["mid"])
            self.who.currentIndexChanged.connect(self._switch_person)
            self.who.setMinimumHeight(C.MIN_TARGET)
            self.header.add_action(C.label(i18n.t("Showing"), role="meta"))
            self.header.add_action(self.who)
        elif R.label(self._me.get("role", "")):
            self.header.add_action(_role_chip(self._me))

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_box = QVBoxLayout(left)
        left_box.setContentsMargins(0, 0, 0, 0)
        left_box.setSpacing(7)
        left_box.addWidget(kicker("Past runs", muted=True))
        self.runs = QListWidget()
        self.runs.setFrameShape(QListWidget.NoFrame)
        self.runs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.runs.currentItemChanged.connect(self._show)
        left_box.addWidget(self.runs, stretch=1)
        split.addWidget(left)

        right = QWidget()
        right_box = QVBoxLayout(right)
        right_box.setContentsMargins(0, 0, 0, 0)
        right_box.setSpacing(7)
        right_box.addWidget(kicker("What happened", muted=True))
        self.view = QTextBrowser()
        viewer.route_links(self.view)
        right_box.addWidget(self.view, stretch=1)
        self._current_reel = ""
        self.edit_reel_btn = C.button(
            i18n.t("Edit the layout"), "secondary", icon_name="pencil",
            small=True, on_click=self._edit_current_reel)
        self.edit_reel_btn.setToolTip(i18n.t(
            "Open this reel in your browser: drag anything into place, "
            "resize it, retype it or delete it, then render it again."))
        self.edit_reel_btn.setVisible(False)
        right_box.addWidget(self.edit_reel_btn)
        self._current_record = None
        self.follow_up_btn = C.button(
            i18n.t("Follow up"), "secondary", icon_name="arrow-up",
            small=True, on_click=self._follow_up_current)
        self.follow_up_btn.setToolTip(i18n.t(
            "Ask for a change to what this run produced. Prism sends your "
            "note to the step it is about, in the same chat that step used "
            "— a reel goes back to the conversation that designed it."))
        self.follow_up_btn.setVisible(False)
        right_box.addWidget(self.follow_up_btn)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        split.setSizes([280, 620])
        root.addWidget(split, stretch=1)

        # accept(), not reject() — History has always closed with Accepted and
        # a caller may be reading that.
        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.accept))

        self._load()

    # ── data ──────────────────────────────────────────────────────────────
    def _switch_person(self):
        """An admin picked somebody else. Read-only: view_as changes which
        folder is listed and nothing else."""
        try:
            identity.view_as(self.who.currentData())
        except PermissionError as e:
            self._current_reel = ""
            self._current_record = None
            self.edit_reel_btn.setVisible(False)
            self.follow_up_btn.setVisible(False)
            self.view.setHtml(self._page(f"<p>{e}</p>"))
            return
        self.runs.clear()
        self.runs.setEnabled(True)
        self._load()

    def _load(self):
        who = identity.viewing()
        runs_dir = workspace.runs_dir(who["mid"], self.cfg)
        names = []
        if os.path.isdir(runs_dir):
            names = sorted((n for n in os.listdir(runs_dir)
                            if n.startswith("run_") and n.endswith(".json")),
                           reverse=True)
        if not names:
            fb = paths.user_dir("runs")
            if os.path.isdir(fb):
                fb_names = sorted((n for n in os.listdir(fb)
                                   if n.startswith("run_") and n.endswith(".json")),
                                  reverse=True)
                if fb_names:
                    runs_dir = fb
                    names = fb_names
        if not names:
            self.runs.setEnabled(False)
            self._current_reel = ""
            self._current_record = None
            self.edit_reel_btn.setVisible(False)
            self.follow_up_btn.setVisible(False)
            nobody = ("No runs saved yet. Once Prism finishes a task, it "
                      "turns up here.")
            if who["mid"] != self._me["mid"]:
                nobody = (f"{who.get('name') or who['mid']} hasn't run "
                          f"anything yet, or their Prism hasn't synced to "
                          f"this workspace.")
            self.view.setHtml(self._page(
                "<p style='color:%s'>%s</p>" % (theme.NEUTRAL[600], nobody)))
            return
        chains: dict[str, list[dict]] = {}
        order: list[str] = []
        user_art_dir = ""
        try:
            user_art_dir = os.path.normpath(paths.user_dir("artifacts"))
        except Exception:
            pass

        for name in names:
            path = os.path.join(runs_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    rec = json.load(f) or {}
            except Exception:
                rec = {}
            rec["_path"] = path
            rec["_name"] = name
            try:
                rec["_mtime"] = os.path.getmtime(path)
            except OSError:
                rec["_mtime"] = 0

            art = (rec.get("artifacts") or "").strip()
            norm_art = os.path.normpath(art) if art else ""
            title = (rec.get("title") or "").strip()
            if norm_art and norm_art != user_art_dir:
                # Key by artifacts dir + title so two separate tasks never collide
                # even if artifact folders were mistakenly shared.
                key = f"{norm_art}::{title}" if title else norm_art
            else:
                key = path

            if key not in chains:
                chains[key] = []
                order.append(key)
            chains[key].append(rec)

        for key in order:
            chain_items = sorted(chains[key], key=lambda r: r["_mtime"])
            root_rec = chain_items[0]
            root_path = root_rec["_path"]

            followups = list(root_rec.get("followups") or [])
            seen_fu_queries = {fu.get("query") for fu in followups if fu.get("query")}

            # Merge legacy separate sibling files as followups
            for sib in chain_items[1:]:
                sib_title = (sib.get("title") or "").strip()
                root_title = (root_rec.get("title") or "").strip()
                if sib_title and root_title and sib_title != root_title:
                    continue
                sib_query = (sib.get("query") or "").strip()
                if sib_query and sib_query not in seen_fu_queries and sib_query != (root_rec.get("query") or "").strip():
                    followups.append({
                        "index": len(followups) + 1,
                        "query": sib_query,
                        "timestamp": sib.get("_mtime") or sib.get("updated_at") or 0,
                        "responses": sib.get("responses") or {},
                        "links": sib.get("links") or {},
                        "agents": sib.get("agents") or {},
                        "durations": sib.get("durations") or {},
                        "error": sib.get("error"),
                    })
                    seen_fu_queries.add(sib_query)
                for sfu in (sib.get("followups") or []):
                    if sfu.get("query") and sfu.get("query") not in seen_fu_queries:
                        followups.append(sfu)
                        seen_fu_queries.add(sfu.get("query"))
                if sib.get("responses"):
                    root_rec.setdefault("responses", {}).update(sib["responses"])
                if sib.get("links"):
                    root_rec.setdefault("links", {}).update(sib["links"])
                if sib.get("agents"):
                    root_rec.setdefault("agents", {}).update(sib["agents"])

            root_rec["followups"] = followups

            day, clock = _when(chain_items[-1]["_path"])
            fu_count = len(followups)
            clock_text = f"{clock} · {fu_count} follow-up{'s' if fu_count != 1 else ''}" if fu_count > 0 else clock
            query = (root_rec.get("title") or "").strip() or root_rec.get("query", "") or "(no task recorded)"

            item = QListWidgetItem()
            item.setData(_PATH_ROLE, root_path)
            item.setData(_RECORD_ROLE, root_rec)
            item.setToolTip(root_rec["_name"])
            widget = _RunItem(day, clock_text, query)
            item.setSizeHint(QSize(0, widget.sizeHint().height() + 4))
            self.runs.addItem(item)
            self.runs.setItemWidget(item, widget)
        self.runs.setCurrentRow(0)

    def _show(self, item: QListWidgetItem, _previous=None):
        if item is None:
            return
        path = item.data(_PATH_ROLE)
        record = item.data(_RECORD_ROLE)
        if not record:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception as e:
                self._current_reel = ""
                self._current_record = None
                self.edit_reel_btn.setVisible(False)
                self.follow_up_btn.setVisible(False)
                self.view.setHtml(self._page(
                    f"<p style='color:{theme.ERR_INK}'>Couldn't read "
                    f"{os.path.basename(path)}: "
                    f"{e}</p>"))
                return
        record["_path"] = path
        # Read-only for a run whose add-on this build does not contain
        # (never true in the complete build): shown, not continued.
        gone = [k for k in _RECORD_ADDON_KEYS
                if record.get(k) and registry.is_absent(k)]
        page = self._render(record, os.path.basename(path))
        if gone:
            page = ("<p style='color:%s'>%s</p>" % (
                theme.MUTE, _esc(entitlement_copy.read_only_note(gone[0])))
                + page)
        self.view.setHtml(self._page(page))
        # A follow-up needs something to follow up: a run that saved stage
        # output, links, or add-on details. NOT `record.get("query")` --
        # that is the user's original request, present on every saved run
        # including a planning failure that produced nothing at all, so it
        # made this check true unconditionally and the button showed on
        # every run in History (see tests/test_followup_session.py).
        has_output = bool(
            any(v for v in (record.get("responses") or {}).values())
            or record.get("links")
            or record.get("step")
            or record.get("reel")
            or record.get("boq")
            or record.get("gerber")
            or record.get("email")
        ) and not gone
        self._current_record = record if has_output else None
        self.follow_up_btn.setVisible(has_output)

        # Detect editable reel from reel, artifacts, or links
        self._current_reel = self._find_reel(record)
        self.edit_reel_btn.setVisible(bool(self._current_reel) and not gone)

    @staticmethod
    def _find_reel(record: dict) -> str:
        reel_info = record.get("reel") or {}
        if isinstance(reel_info, dict):
            for key in ("mp4", "artifact"):
                c = reel_info.get(key) or ""
                if c and _editable_reel(c):
                    return c
        artifacts = record.get("artifacts") or {}
        if isinstance(artifacts, dict):
            for val in artifacts.values():
                if val and isinstance(val, str) and _editable_reel(val):
                    return val
        elif isinstance(artifacts, str):
            if _editable_reel(artifacts):
                return artifacts
            if os.path.isdir(artifacts):
                try:
                    cands = [os.path.join(artifacts, f) for f in os.listdir(artifacts)
                             if f.lower().endswith(".mp4")]
                    cands.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0,
                               reverse=True)
                    for cand in cands:
                        if _editable_reel(cand):
                            return cand
                except OSError:
                    pass
        for url in (record.get("links") or {}).values():
            if url and isinstance(url, str) and _editable_reel(url):
                return url
        return ""

    def _edit_current_reel(self):
        if not self._current_reel:
            return
        url = self._current_reel
        self.accept()
        self.edit_reel.emit(url)

    def _follow_up_current(self):
        if not self._current_record:
            return
        record = self._current_record
        self.accept()
        self.follow_up.emit(record)

    # ── rendering ─────────────────────────────────────────────────────────
    @staticmethod
    def _page(body: str) -> str:
        return (f"<body style='font-family:{theme.FONT_BODY}; font-size:14px; "
                f"color:{theme.TEXT}'>{body}</body>")

    def _render(self, record: dict, filename: str) -> str:
        A = CB.agents
        # History is a reader for records from several Prism versions (and
        # occasionally a hand-edited recovery file). A pre-structured record
        # can hold ``routing[stage]`` as its old plain string prompt rather
        # than the current {needed, questions} object. Treat that as an older
        # prompt, never as an object to call .get() on; one malformed field
        # must not make the entire History screen unusable.
        routing = record.get("routing") or {}
        routing = routing if isinstance(routing, dict) else {}
        responses = record.get("responses") or {}
        responses = responses if isinstance(responses, dict) else {}
        links = record.get("links") or {}
        links = links if isinstance(links, dict) else {}
        attachments = record.get("attachments") or []
        attachments = attachments if isinstance(attachments, list) else []

        def stage_routing(stage: str) -> dict:
            data = routing.get(stage)
            if isinstance(data, dict):
                return data
            # Old runs stored the prompt itself here. Render it as the
            # question rather than hiding it, while retaining a safe shape.
            if isinstance(data, str) and data.strip():
                return {"questions": [data]}
            return {}
        day, clock = _when(filename)
        step_info = record.get("step") or {}
        reel_info = record.get("reel") or {}

        # Collect all stages: pipeline order first, then any extra stages from responses, links, or routing
        ran = [s for s in A.PIPELINE_ORDER
               if stage_routing(s).get("needed")
               and stage_routing(s).get("questions")]
        all_stage_keys = list(responses.keys()) + list(links.keys()) + list(routing.keys())
        for s in all_stage_keys:
            # `_brief`, `_title`, and the other routing metadata are not
            # stages. They are strings too, so letting them through would
            # make a History card titled "Brief" after fixing legacy strings.
            if isinstance(s, str) and s and not s.startswith("_") and s not in ran:
                ran.append(s)
        # STEP's own response keys ("ask · <model>", "plan · <model>",
        # "draft · <model>") are not pipeline stages — they are its own
        # conversation, one per attached model, rendered below as an
        # actual labelled back-and-forth (_step_conversation) instead of a
        # raw joined text dump under a stage title that just repeated the
        # key ("Ask · Pet Core 02 06"). Left in `ran` they duplicated that
        # block and, worse, showed only the single latest saved answer
        # with no "you asked / it answered" structure at all.
        #
        # Only dropped from `ran` when that model's conversation file
        # actually rendered something — a run saved before this existed
        # has no such file, and must keep showing its old raw answer here
        # rather than silently losing it.
        step_conversations = {}
        for m in step_info.get("models") or []:
            html = self._step_conversation(m.get("conversation", ""))
            if html:
                step_conversations[os.path.splitext(m.get("file", ""))[0]] = html
        if step_conversations:
            ran = [s for s in ran if not any(
                s == f"{p} · {stem}"
                for p in ("ask", "plan", "draft") for stem in step_conversations)]

        step_count = len(ran) + (1 if step_info else 0) + (1 if reel_info else 0)
        query_html = _esc(str(record.get("query") or ""))
        query_html = (query_html.replace("\r\n", "<br>")
                      .replace("\r", "<br>").replace("\n", "<br>"))
        has_fus = bool(record.get("followups"))
        initial_tag = (f"<div style='margin-bottom:6px;'><span style='background:{theme.ACCENT_RAMP[100]}; "
                       f"color:{theme.ACCENT_RAMP[800]}; padding:2px 8px; border-radius:4px; "
                       f"font-size:11px; font-weight:700; text-transform:uppercase;'>Initial Task</span></div>"
                       if has_fus else "")
        parts = [
            initial_tag,
            f"<div style='font-family:{theme.FONT_BODY};font-size:16px;"
            f"line-height:145%;margin:0 0 8px 0'>"
            f"{query_html}</div>",
            f"<p style='color:{theme.NEUTRAL[600]};font-size:12px;margin:0 0 4px 0'>"
            f"{day} at {clock} &nbsp;·&nbsp; {step_count} step{'' if step_count == 1 else 's'}"
            + (f" &nbsp;·&nbsp; {len(attachments)} file"
               f"{'' if len(attachments) == 1 else 's'}" if attachments else "")
            + "</p>",
        ]

        if attachments:
            names = ", ".join(_esc(_attachment_name(a)) for a in attachments)
            parts.append(f"<p style='color:{theme.NEUTRAL[600]};font-size:12px;"
                         f"margin:0 0 14px 0'>Files: {names}</p>")
        if record.get("error"):
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='10'"
                f"><tr><td bgcolor='#fef2f2'>"
                f"<span style='color:{theme.ERR_INK}'>"
                f"This run stopped early — {_esc(record['error'])}</span>"
                f"</td></tr></table>")
        # /email runs carry a block the plain-run renderer knows nothing about —
        # and it's the part you actually come back for: who got the email.
        email = record.get("email") or {}
        if email:
            sent = email.get("sent") or []
            failed = email.get("failed") or []
            total = email.get("recipients", len(sent) + len(failed))
            if not sent and not failed:
                line = f"Drafted but never sent — {total} recipient(s) were lined up."
            else:
                line = f"Sent to {len(sent)} of {total} recipient(s)."
                if failed:
                    line += f" {len(failed)} failed."
            parts.append(
                f"<table width='100%' cellspacing='0' cellpadding='10'>"
                f"<tr><td bgcolor='#f5f5f7'>"
                f"<b>✉&nbsp; {_esc(email.get('subject', '(no subject)'))}</b><br>"
                f"<span style='color:{theme.NEUTRAL[700]};font-size:12px'>"
                f"{_esc(line)}</span></td></tr></table>")

        if step_info:
            action = step_info.get("action", "draft")
            models = step_info.get("models") or []
            parts.append(
                f"<div style='margin:12px 0; padding:10px; background:{theme.ACCENT_RAMP[100]}; border-radius:6px;'>"
                f"<b>📐 STEP CAD: {_esc(action.upper())}</b><br>")
            for m in models:
                parts.append(f"<span style='font-size:12px;'>File: <b>{_esc(m.get('file', ''))}</b> &nbsp;·&nbsp; "
                             f"Folder: {_esc(m.get('out_dir', ''))}</span><br>")
            parts.append("</div>")
            for m in models:
                stem = os.path.splitext(m.get("file", ""))[0]
                if stem in step_conversations:
                    parts.append(step_conversations[stem])

        if reel_info:
            mp4 = reel_info.get("mp4") or reel_info.get("artifact") or ""
            parts.append(
                f"<div style='margin:12px 0; padding:10px; background:{theme.ACCENT_RAMP[100]}; border-radius:6px;'>"
                f"<b>🎬 Reel Generated:</b> {_esc(os.path.basename(mp4))}<br>"
                f"<span style='font-size:12px; color:{theme.NEUTRAL[600]}'>{_esc(mp4)}</span>"
                f"</div>")

        parts.append(f"<hr style='height:1px;background:{theme.DIVIDER};border:0'>")

        rendered_urls = set()
        agents = record.get("agents") or {}
        for number, stage in enumerate(ran, start=1):
            stage_clean = stage.replace("_", " ").replace("-", " ")
            _, title, _ = STAGE_COPY.get(stage, ("grid", stage_clean.title(), ""))
            url = links.get(stage) or ""
            if url:
                rendered_urls.add(url)
            texts = responses.get(stage) or []
            ran_by = ai_server.display_agent(
                agents.get(stage), stage,
                (record.get("ran_in") or {}).get(stage, "")) or stage

            parts.append(
                f"<p style='margin:20px 0 2px 0'>"
                f"<span style='font-family:{theme.FONT_HEADING};font-size:20px;"
                f"color:{theme.ACCENT_RAMP[700]}'>{number:02d}</span>"
                f"<span style='font-family:{theme.FONT_HEADING};font-size:18px'>"
                f"&nbsp;&nbsp;{_esc(title)}</span>"
                f"<span style='color:{theme.NEUTRAL[600]};font-size:12px'>"
                f"&nbsp;&nbsp;·&nbsp;&nbsp;{_esc(ran_by)}</span></p>")
            if url:
                parts.append(f"<p style='margin:0 0 8px 0;font-size:12px'>"
                             f"🔗 <a href='{_esc(url)}' style='color:"
                             f"{theme.ACCENT_RAMP[700]}; text-decoration: underline; font-weight: 500;'>"
                             f"{_esc(_one_line(url, 75))}</a></p>")

            questions = stage_routing(stage).get("questions") or []
            if questions:
                parts.append(self._sub("What Prism asked"))
                for question in questions:
                    parts.append(self._quote(_esc(question), theme.NEUTRAL[100]))

            if texts:
                parts.append(self._sub("What came back"))
                joined = "\n\n———\n\n".join(t for t in texts if t)
                parts.append(self._quote(render_markdown(joined), theme.SURFACE,
                                         raw_html=True)
                             if joined.strip() else self._nothing(url))
            elif not questions and not url:
                parts.append(self._nothing(url))

        # Render any additional tool links not yet shown
        extra_links = {k: v for k, v in links.items() if v and v not in rendered_urls}
        if extra_links:
            parts.append(self._sub("Tool & AI Links"))
            for k, u in extra_links.items():
                parts.append(
                    f"<p style='margin:4px 0 8px 0;font-size:13px'>"
                    f"<b>{_esc(k)}:</b> &nbsp;<a href='{_esc(u)}' style='color:{theme.ACCENT_RAMP[700]}; text-decoration: underline; font-weight: 500;'>"
                    f"{_esc(u)}</a></p>")

        followups = record.get("followups") or []
        for fu in followups:
            fu_idx = fu.get("index", 1)
            fu_query = fu.get("query") or "Follow-up refinement"
            fu_timestamp = fu.get("timestamp")
            fu_time_str = ""
            if fu_timestamp:
                try:
                    fu_moment = time.localtime(float(fu_timestamp))
                    fu_time_str = time.strftime("%d %b %Y at %H:%M", fu_moment)
                except Exception:
                    pass

            fu_agents = fu.get("agents") or {}
            fu_ran_in = fu.get("ran_in") or {}
            fu_tools = [ai_server.display_agent(v, where=fu_ran_in.get(k, ""))
                        for k, v in fu_agents.items() if v]
            fu_tools_str = ", ".join(dict.fromkeys(fu_tools)) if fu_tools else ""

            parts.append(
                f"<div style='margin:32px 0 14px 0;'>"
                f"<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                f"<td style='border-bottom:1px dashed {theme.ACCENT_RAMP[300]};'></td>"
                f"<td width='1' style='padding:0 12px; white-space:nowrap;'>"
                f"<span style='background:{theme.ACCENT_RAMP[600]}; color:#ffffff; "
                f"padding:5px 14px; border-radius:14px; font-size:12px; font-weight:700; "
                f"letter-spacing:0.5px;'>"
                f"➔ &nbsp;FOLLOW-UP {fu_idx}</span></td>"
                f"<td style='border-bottom:1px dashed {theme.ACCENT_RAMP[300]};'></td>"
                f"</tr></table></div>")

            # Follow-up header box
            fu_meta_line = " &nbsp;·&nbsp; ".join(filter(None, [fu_time_str, fu_tools_str]))
            parts.append(
                f"<div style='margin:0 0 16px 0; padding:12px 14px; "
                f"background:{theme.ACCENT_RAMP[100]}; border-left:4px solid {theme.ACCENT_RAMP[600]}; "
                f"border-radius:4px;'>"
                f"<div style='font-size:11px; font-weight:700; color:{theme.ACCENT_RAMP[800]}; "
                f"text-transform:uppercase; margin-bottom:4px;'>"
                f"Refinement requested"
                + (f" &nbsp;·&nbsp; <span style='font-weight:500;'>{_esc(fu_meta_line)}</span>" if fu_meta_line else "")
                + f"</div>"
                f"<div style='font-size:14px; color:{theme.NEUTRAL[900]}; font-weight:500; "
                f"line-height:140%;'>"
                f"{_esc(fu_query)}</div></div>")

            if fu.get("error"):
                parts.append(
                    f"<table width='100%' cellspacing='0' cellpadding='8' style='margin:0 0 10px 0;'>"
                    f"<tr><td bgcolor='#fef2f2'>"
                    f"<span style='color:{theme.ERR_INK}; font-size:12px;'>"
                    f"This follow-up stopped early — {_esc(fu['error'])}</span>"
                    f"</td></tr></table>")

            fu_responses = fu.get("responses") or {}
            fu_links = fu.get("links") or {}
            fu_rendered_urls = set()

            for s_name, s_texts in fu_responses.items():
                clean_s = s_name.replace("_", " ").replace("-", " ")
                _, s_title, _ = STAGE_COPY.get(s_name, ("grid", clean_s.title(), ""))
                s_url = fu_links.get(s_name) or ""
                if s_url:
                    fu_rendered_urls.add(s_url)
                s_agent = ai_server.display_agent(
                    fu_agents.get(s_name), s_name,
                    fu_ran_in.get(s_name, "")) or s_name

                parts.append(
                    f"<p style='margin:14px 0 2px 0'>"
                    f"<span style='font-family:{theme.FONT_HEADING};font-size:16px;"
                    f"color:{theme.ACCENT_RAMP[700]}'>◆</span>"
                    f"<span style='font-family:{theme.FONT_HEADING};font-size:15px'>"
                    f"&nbsp;&nbsp;{_esc(s_title)}</span>"
                    f"<span style='color:{theme.NEUTRAL[600]};font-size:12px'>"
                    f"&nbsp;&nbsp;·&nbsp;&nbsp;{_esc(s_agent)}</span></p>")

                if s_url:
                    parts.append(f"<p style='margin:0 0 6px 0;font-size:12px'>"
                                 f"🔗 <a href='{_esc(s_url)}' style='color:"
                                 f"{theme.ACCENT_RAMP[700]}; text-decoration: underline; font-weight: 500;'>"
                                 f"{_esc(_one_line(s_url, 75))}</a></p>")

                joined_fu = "\n\n———\n\n".join(t for t in s_texts if t)
                if joined_fu.strip():
                    parts.append(self._sub("Updated output"))
                    parts.append(self._quote(render_markdown(joined_fu), theme.SURFACE, raw_html=True))

            fu_extra_links = {k: v for k, v in fu_links.items() if v and v not in fu_rendered_urls}
            if fu_extra_links:
                parts.append(self._sub("Generated Links"))
                for k, u in fu_extra_links.items():
                    parts.append(
                        f"<p style='margin:4px 0 6px 0;font-size:12px'>"
                        f"<b>{_esc(k)}:</b> &nbsp;<a href='{_esc(u)}' style='color:{theme.ACCENT_RAMP[700]}; "
                        f"text-decoration: underline; font-weight: 500;'>{_esc(u)}</a></p>")

        if not ran and not step_info and not reel_info and not extra_links and not followups:
            parts.append(f"<p style='color:{theme.NEUTRAL[600]}'>This run didn't "
                         f"record any step responses.</p>")

        return "".join(parts)

    @classmethod
    def _step_conversation(cls, path: str) -> str:
        """The whole back-and-forth about one STEP model, read off the file
        addons/step/dialog.py keeps it in — the same thread the Answer
        popup itself shows, not the generic "what came back" dump above,
        which only ever held the single latest saved answer with no sign
        of who asked what. A run saved before this existed, or a missing
        file, renders nothing here rather than an error."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                thread = json.load(f)
            if not isinstance(thread, list) or not thread:
                return ""
        except (OSError, ValueError, TypeError):
            return ""
        parts = [cls._sub("The conversation")]
        # Solid hex only — bgcolor is an HTML attribute, not a CSS
        # property, and cannot parse the rgba() ACCENT_RAMP carries at
        # low steps. That rendered as plain black with near-black text on
        # top of it, not a tint: wrong value in the wrong kind of slot,
        # not a dark-mode issue. theme.SURFACE is the same solid grey
        # _quote()'s other callers in this file already use successfully.
        you_bg, agent_bg = theme.NEUTRAL[100], theme.SURFACE
        for i, turn in enumerate(thread):
            if not isinstance(turn, (list, tuple)) or len(turn) != 2:
                continue
            speaker, text = turn
            is_you = str(speaker).lower().startswith(("you asked", "you followed"))
            bg = you_bg if is_you else agent_bg
            body = (f"<p style='margin:0 0 4px 0;font-weight:700;"
                    f"color:{theme.NEUTRAL[700]};font-size:11px;"
                    f"text-transform:uppercase'>{_esc(str(speaker))}</p>"
                    + render_markdown(str(text)))
            parts.append(cls._quote(body, bg, raw_html=True))
        return "".join(parts)

    @staticmethod
    def _sub(text: str) -> str:
        return (f"<p style='font-family:{theme.FONT_HEADING};font-size:11px;"
                f"color:{theme.NEUTRAL[600]};margin:12px 0 3px 0'>"
                f"{text.upper()}</p>")

    @staticmethod
    def _quote(inner: str, bg: str, raw_html: bool = False) -> str:
        body = inner if raw_html else (
            f"<p style='margin:0;white-space:pre-wrap;color:{theme.NEUTRAL[800]}'>"
            f"{inner}</p>")
        return (f"<table width='100%' cellspacing='0' cellpadding='11' "
                f"style='margin:0 0 4px 0'><tr><td bgcolor='{bg}'>{body}"
                f"</td></tr></table>")

    @staticmethod
    def _nothing(url: str) -> str:
        note = ("Nothing was captured — the step ran, but Prism couldn't read the "
                "answer off the page." if url else "Nothing was captured.")
        return (f"<p style='color:{theme.NEUTRAL[600]};font-style:italic;"
                f"margin:0 0 4px 0'>{note}</p>")


def _esc(text: str) -> str:
    from html import escape
    return escape(str(text))

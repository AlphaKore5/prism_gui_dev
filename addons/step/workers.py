"""STEP's background work, off the UI thread.

Three workers because the dialog's three actions are three different kinds
of wait: OpenCascade reading a model (seconds to a minute), one OpenRouter
call to Claude Haiku 5.5 or Claude Sonnet 5.5 (seconds), and a boolean cut
plus a re-measure plus a render (tens of seconds). Each on its own thread,
each reporting in its own words.

Every one subclasses workers._Worker -- never QThread directly -- so a
running worker is anchored until it finishes and cannot be collected
mid-run (tests/test_worker_mandate.py, and BUGS.md for what that cost).
The engine is reached through core_bridge only (tests/test_engine_facade.py).
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from PySide6.QtCore import Signal

import core_bridge as CB
import i18n
from workers import _Worker


def _modified_name(SF, report: dict) -> str:
    """The file an Edit writes, stamped with when it was built, so two
    requests on one model never share a name. The engine names it
    (core.stepfile.modified_name); an engine build that predates that
    function -- the one on GitHub did when 1.6.3 was cut -- would have
    failed every Edit with "no attribute 'modified_name'", so the same
    shape is made here when it is missing."""
    ask = getattr(SF, "modified_name", None)
    if ask is not None:
        return ask(report)
    base, ext = os.path.splitext(SF.names(report)["modified"])
    return f"{base} {_dt.datetime.now():%Y-%m-%d %H%M%S}{ext}"


class StepMeasureWorker(_Worker):
    """Measure one or more STEP models -- the offline half every action
    starts with. Each model lands in its own folder under `root`, named
    after it, with its Excel sheet and drawing sheet, and every file
    carries the model's name (core.stepfile.names)."""
    progress = Signal(str)
    done = Signal(list)              # [{"path","report","out_dir","drawn","xlsx"}]
    failed = Signal(str)

    def __init__(self, paths: list[str], mode: str, root: str,
                k_factor: float = 0.0):
        super().__init__()
        self.paths, self.mode, self.root = paths, mode, root
        self.k_factor = k_factor

    def run(self):
        try:
            SF = CB.get_stepfile()
            ok, why = SF.available()
            if not ok:
                self.failed.emit(why)
                return
            results = []
            for path in self.paths:
                name = os.path.basename(path)
                self.progress.emit(f"measuring {name} ({self.mode})…")
                report = SF.analyse(path, mode=self.mode, k_factor=self.k_factor)
                out_dir = SF.output_dir(path, self.root)
                names = SF.names(report)
                xlsx = ""
                try:
                    xlsx = SF.write_xlsx(
                        report, os.path.join(out_dir, names["xlsx"]))
                except Exception as e:                  # noqa: BLE001
                    self.progress.emit(f"! Excel sheet not written: {e}")
                self.progress.emit(f"drawing the parts of {name}…")
                drawn = SF.render_sheet(report, out_dir)
                results.append({"path": path, "report": report,
                                "out_dir": out_dir, "drawn": drawn,
                                "xlsx": xlsx})
            self.done.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


def image_attachment(path: str) -> dict:
    """A rendered drawing-sheet PNG -> the content-block shape
    core.openrouter's own openrouter_chat() expects for a vision model:
    {"kind": "image", "mime": "image/png", "b64": "...", "name": "..."}.
    Stdlib-only (base64) on purpose -- this is Prism's OWN already-drawn
    picture of the parts, never the STEP file, so no engine call is needed
    to prepare it, only a file read."""
    import base64
    with open(path, "rb") as f:
        data = f.read()
    return {"kind": "image", "mime": "image/png",
            "b64": base64.b64encode(data).decode("ascii"),
            "name": os.path.basename(path)}


# Which way a cheap-first answer was reached, in words a customer can use.
# Kept in English in run records; workbench.shown_name translates on screen.
PATH_WORDS = {
    "local": "Measured from the file",
    "cheap": "Quick check",
    "escalated": "Full check",
    "strong": "Full check",
    "unverified": "Could not be verified",
}


def path_label(result: dict | None) -> str:
    """"" when the answer did not come from the cheap-first pipeline."""
    return PATH_WORDS.get((result or {}).get("path", ""), "")


def cheap_first_on() -> bool:
    """True when STEP asks go through the engine's step_cheap: it needs
    Prism's server (the cheap `step.fast` role lives there) and an engine
    that has the module."""
    return CB.ai_client.active() and CB.get_step_cheap() is not None


def _cheap_first():
    """The step_cheap module when STEP should use it, else None."""
    return CB.get_step_cheap() if cheap_first_on() else None


def answers_locally(report: dict, question: str, history=None) -> bool:
    """True when asking would send nothing anywhere (so no picture is asked
    for either)."""
    cheap = _cheap_first()
    return cheap is not None and cheap.answers_locally(report, question, history)


def _licence_id() -> str:
    try:
        return str(CB.ai_client._auth().get("license_id", ""))
    except Exception:                                   # noqa: BLE001
        return ""


def _cheap_ask(cheap, report: dict, question: str, model: str,
               attachments: list, history: list) -> dict:
    """step_cheap.ask(), with its fixed sentences in the app's language."""
    res = cheap.ask(report, question, licence_id=_licence_id(), model=model,
                    attachments=attachments, history=history)
    if res.get("path") in ("capped", "unverified"):
        res = dict(res, text=i18n.t(res["text"]))
    return res


class StepAskWorker(_Worker):
    """One OpenRouter call: the measured numbers (individually tagged
    holes) and the question -- and, only with the person's own consent
    each session, Prism's own rendered picture of the parts -- in,
    suggestions out. Never the STEP file itself.

    On Prism's server the question goes through the engine's
    step_cheap.ask() instead: a fact the measuring code knows is answered
    locally for free; otherwise the Haiku pick gets a checked quick pass with
    one escalation to Sonnet, and the Sonnet pick goes straight to Sonnet.
    `answered` carries the whole result (which path answered, the plan) just
    before `done`; a reached daily/monthly cap comes back as `failed` with
    the plain sentence. For a follow-up, `plain_question` is the person's own
    words (`question` has the conversation folded in, for the direct route)
    and `history` the earlier exchanges, which the engine trims."""
    done = Signal(str)
    answered = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: dict, report: dict, question: str,
                 model: str = "anthropic/claude-haiku-5.5",
                 attachments: list | None = None, plain_question: str = "",
                 history: list | None = None):
        super().__init__()
        self.cfg, self.report, self.question = cfg, report, question
        self.model, self.attachments = model, list(attachments or [])
        self.plain_question, self.history = plain_question, list(history or [])

    def run(self):
        try:
            cheap = _cheap_first()
            if cheap is not None:
                res = _cheap_ask(cheap, self.report,
                                 self.plain_question or self.question,
                                 self.model, self.attachments, self.history)
                if res.get("capped"):
                    self.failed.emit(res["text"])
                    return
                self.answered.emit(res)
                self.done.emit(res["text"].strip())
                return
            SF = CB.get_stepfile()
            text = CB.openrouter.openrouter_chat(
                self.cfg.get("openrouter_api_key", ""), self.model,
                SF.ask_prompt(self.report, self.question),
                attachments=self.attachments,
                temperature=0.4, timeout=90,
                role="vision" if self.attachments else "reasoner",
                addon="step", feature="ask", pin_model=True).strip()
            self.done.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class StepPlanWorker(_Worker):
    """One OpenRouter call that turns an answer into an exact change plan
    (JSON) -- the same model the question was asked with reviews its own
    suggestions, in-house, no browser.

    With the cheap-first pipeline the plan is already in the answer to the
    question (`prior`, the result `StepAskWorker.answered` gave), so no
    second call is made. Without one (a conversation reopened from History)
    the question is asked again."""
    done = Signal(str)
    answered = Signal(dict)
    failed = Signal(str)

    def __init__(self, cfg: dict, report: dict, question: str,
                 suggestions: str, model: str = "anthropic/claude-haiku-5.5",
                 attachments: list | None = None, prior: dict | None = None,
                 plain_question: str = "", history: list | None = None):
        super().__init__()
        self.cfg, self.report = cfg, report
        self.question, self.suggestions = question, suggestions
        self.model, self.attachments = model, list(attachments or [])
        self.prior, self.plain_question = prior, plain_question
        self.history = list(history or [])

    def run(self):
        try:
            cheap = _cheap_first()
            if cheap is not None:
                res = self.prior
                if res is None:
                    res = _cheap_ask(
                        cheap, self.report,
                        self.plain_question or self.question
                        or self.suggestions,
                        self.model, self.attachments, self.history)
                    if res.get("capped"):
                        self.failed.emit(res["text"])
                        return
                plan = dict(res.get("plan") or {})
                plan.setdefault("changes", [])
                plan.setdefault("advice", [])
                if res.get("path") == "unverified" and not plan["advice"]:
                    plan["advice"] = [res.get("text", "")]
                self.answered.emit(res)
                self.done.emit(json.dumps(plan))
                return
            SF = CB.get_stepfile()
            text = CB.openrouter.openrouter_chat(
                self.cfg.get("openrouter_api_key", ""), self.model,
                SF.plan_prompt(self.report, self.question, self.suggestions),
                attachments=self.attachments,
                temperature=0.2, timeout=90,
                role="vision" if self.attachments else "reasoner",
                addon="step", feature="plan", pin_model=True).strip()
            self.done.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class StepCatalogExplainWorker(_Worker):
    """One OpenRouter call, numbers only: why an inquiry's ID/OD missed
    every row in the shop's own material/mould catalog within tolerance.
    Fired only on a miss (dialog.py) -- a confident deterministic match
    needs no second opinion. The prompt (core.stepfile.
    catalog_explain_prompt) carries four numbers, two Sr Nos and nothing
    else: never the catalog file, never the STEP file."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, prompt: str,
                 model: str = "anthropic/claude-haiku-5.5"):
        super().__init__()
        self.cfg, self.prompt, self.model = cfg, prompt, model

    def run(self):
        try:
            text = CB.openrouter.openrouter_chat(
                self.cfg.get("openrouter_api_key", ""), self.model,
                self.prompt, temperature=0.3, timeout=60,
                role="writer", addon="step", feature="catalog_explain").strip()
            self.done.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class StepApplyWorker(_Worker):
    """Apply a validated plan to a COPY of the model, re-measure the copy,
    and rewrite the review page with the real After column. The original
    file is never written -- core.stepfile.apply_plan exports a new one."""
    done = Signal(dict)              # {"out", "log", "after", "review"}
    failed = Signal(str)

    def __init__(self, path: str, plan: dict, report: dict, mode: str,
                 out_dir: str, question: str, k_factor: float = 0.0):
        super().__init__()
        self.path, self.plan, self.report = path, plan, report
        self.mode, self.out_dir, self.question = mode, out_dir, question
        self.k_factor = k_factor

    def run(self):
        try:
            import shutil
            SF = CB.get_stepfile()
            names = SF.names(self.report)
            out_path = os.path.join(self.out_dir, _modified_name(SF, self.report))
            built = SF.apply_plan(self.path, self.plan, out_path)
            after = SF.analyse(out_path, mode=self.mode, k_factor=self.k_factor)
            try:
                SF.write_xlsx(after,
                              os.path.join(self.out_dir, names["xlsx_after"]))
            except Exception:                           # noqa: BLE001
                pass
            try:
                drawn = SF.render_sheet(
                    after, os.path.join(self.out_dir, names["after_dir"]))
                if drawn.get("png"):
                    shutil.copyfile(drawn["png"], os.path.join(
                        self.out_dir, names["png_after"]))
            except Exception:                           # noqa: BLE001
                pass
            review = SF.review_html(self.report, self.plan, self.out_dir,
                                    question=self.question, after=after)
            self.done.emit({"out": out_path, "log": built["log"],
                            "after": after, "review": review})
        except Exception as e:
            self.failed.emit(str(e))

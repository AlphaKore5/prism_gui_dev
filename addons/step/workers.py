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
import os

from PySide6.QtCore import Signal

import core_bridge as CB
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


class StepAskWorker(_Worker):
    """One OpenRouter call: the measured numbers (individually tagged
    holes) and the question -- and, only with the person's own consent
    each session, Prism's own rendered picture of the parts -- in,
    suggestions out. Never the STEP file itself."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, report: dict, question: str,
                 model: str = "anthropic/claude-haiku-5.5",
                 attachments: list | None = None):
        super().__init__()
        self.cfg, self.report, self.question = cfg, report, question
        self.model, self.attachments = model, list(attachments or [])

    def run(self):
        try:
            SF = CB.get_stepfile()
            text = CB.openrouter.openrouter_chat(
                self.cfg.get("openrouter_api_key", ""), self.model,
                SF.ask_prompt(self.report, self.question),
                attachments=self.attachments,
                temperature=0.4, timeout=90).strip()
            self.done.emit(text)
        except Exception as e:
            self.failed.emit(str(e))


class StepPlanWorker(_Worker):
    """One OpenRouter call that turns an answer into an exact change plan
    (JSON) -- the same model the question was asked with reviews its own
    suggestions, in-house, no browser."""
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, report: dict, question: str,
                 suggestions: str, model: str = "anthropic/claude-haiku-5.5",
                 attachments: list | None = None):
        super().__init__()
        self.cfg, self.report = cfg, report
        self.question, self.suggestions = question, suggestions
        self.model, self.attachments = model, list(attachments or [])

    def run(self):
        try:
            SF = CB.get_stepfile()
            text = CB.openrouter.openrouter_chat(
                self.cfg.get("openrouter_api_key", ""), self.model,
                SF.plan_prompt(self.report, self.question, self.suggestions),
                attachments=self.attachments,
                temperature=0.2, timeout=90).strip()
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

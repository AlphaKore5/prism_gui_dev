"""
Prism GUI — background workers
───────────────────────────────
Routing, browser automation and Groq calls all block for real seconds/minutes
— every one of them runs on a QThread so the UI never freezes. Each worker's
job is ONLY to call into core_bridge and turn the result into a Qt signal;
no decision-making lives here.
"""
from __future__ import annotations
import os
import threading
from PySide6.QtCore import QThread, Signal

import core_bridge as CB


# Every worker that has been started and not yet finished keeps itself in here.
#
# A QThread that is garbage-collected while its underlying thread is still
# running triggers a Qt *fatal* — "QThread: Destroyed while thread is still
# running" — which aborts the whole process (a 0xC0000409 fast-fail on Windows,
# with no Python traceback to show for it). The trap is that a Signal.connect()
# does NOT keep the emitter alive, so a worker held only through its `done`/
# `failed` connections has an effective refcount of zero the moment the caller's
# own reference goes: a dialog closing, an attribute being reassigned to the
# next run's worker, or simply a local going out of scope. The next garbage
# collection then destroys it mid-run and Prism dies.
#
# Making each worker anchor ITSELF here from start() until its finished signal
# fires removes that whole class of crash: no call site can drop a running
# worker by accident, because the worker is never only referenced by the call
# site. The set drains itself — _forget runs on the GUI thread when the thread
# has actually finished, so the eventual destruction is always safe.
_running: "set[QThread]" = set()


class _Worker(QThread):
    """A QThread that cannot be garbage-collected while it is still running."""

    def start(self, *args, **kwargs):
        _running.add(self)
        self.finished.connect(self._forget)
        super().start(*args, **kwargs)

    def _forget(self):
        _running.discard(self)


class AuthorizeWorker(_Worker):
    """Ask the licence server whether this run may go ahead.

    On its own thread because the answer takes a network round trip and the
    customer has just pressed a button — freezing the window while we wait
    reads as a crash, which is exactly the moment they decide the software is
    broken.
    """

    done = Signal(object)      # licensing.Authorization

    def __init__(self, feature: str = "core", action: str = "run", parent=None):
        super().__init__(parent)
        self._feature = feature
        self._action = action

    def run(self):
        import licensing
        try:
            self.done.emit(licensing.authorize(self._feature, self._action))
        except Exception as e:                      # noqa: BLE001
            # Never strand the caller: a bug in here must not mean the button
            # silently does nothing forever.
            self.done.emit(licensing.Authorization(
                False, message=f"Couldn't check your licence: {e}"))


class RouteWorker(_Worker):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, query: str, cfg: dict, attachments: list):
        super().__init__()
        self.query, self.cfg, self.attachments = query, cfg, attachments

    def run(self):
        try:
            routing = CB.router.route(self.query, self.cfg, self.attachments)
            self.done.emit(routing)
        except Exception as e:
            self.failed.emit(str(e))


class PlanBriefWorker(_Worker):
    """Write the prompts for the plan as the owner confirmed it.

    The router wrote its prompts before anyone looked at the plan. Once a
    step has been dropped, added, moved or given another tool, those
    prompts are wrong -- one Groq call rewrites them for the confirmed
    steps, off the GUI thread, before the licence check and the run.
    """
    done = Signal(list)              # [(stage, tool, questions)], in order
    failed = Signal(str)

    def __init__(self, query: str, cfg: dict, steps: list, routing: dict):
        super().__init__()
        self.query, self.cfg, self.steps, self.routing = query, cfg, steps, routing

    def run(self):
        try:
            self.done.emit(CB.router.brief_confirmed_plan(
                self.query, self.cfg, self.steps, self.routing))
        except Exception as e:                      # noqa: BLE001
            self.failed.emit(str(e))


class AutomationWorker(_Worker):
    stage_event = Signal(str, dict)
    done = Signal(dict, dict)
    failed = Signal(str)

    def __init__(self, routing: dict, cfg: dict, attachments: list, query: str,
                 custom_stages=None, chatgpt_analysis: bool = True,
                 reel_design_stage: str = "", motion_design_stage: str = "",
                 resume_urls: dict | None = None,
                 skip_stages: list | None = None, followup: bool = False,
                 files_out: list | None = None,
                 image_stages=None, failover: bool = True,
                 motion_skeleton: str = "",
                 stage_skills: dict | None = None,
                 prior_responses: dict | None = None,
                 min_wait: int = 0):
        super().__init__()
        self.routing, self.cfg = routing, cfg
        self.attachments, self.query = attachments, query
        self.prior_responses = prior_responses
        # Stage keys the caller promises will produce a picture — they get
        # the engine's full image budget. See automation.run(image_stages=).
        self.image_stages = set(image_stages or ())
        # False = a stage that produced nothing is NOT handed to another
        # tool in its category. The STEP dialog's Draft is ChatGPT's job and
        # nobody else's: a "fallback" sheet from a different image model is
        # a second, differently-wrong drawing, not a rescue.
        self.failover = failover
        # {stage: conversation_url} — a follow-up resumes the SAME chat the
        # stage answered in, instead of opening a fresh one. None = normal run.
        self.resume_urls = resume_urls
        # Steps the plan screen left out. The engine inserts a few stages of
        # its own (Studio's image maker, for one) and has to be told which
        # of them the owner switched off, or it puts them back.
        self.skip_stages = list(skip_stages or [])
        # A follow-up redoes a whole deliverable and gets the engine's longer
        # wait ceiling (automation.FOLLOWUP_MIN_WAIT); the everyday budget
        # was cutting those answers off mid-way.
        self.followup = bool(followup)
        # A raw wait-ceiling floor for a caller who knows this particular
        # stage is heavier than a normal follow-up (BOQ's "recheck" — the
        # tool has to actually read the drawing, which the owner reports can
        # take ~20 minutes, far past automation.FOLLOWUP_MIN_WAIT's 8).
        # Independent of `followup` so it can raise the ceiling further
        # without claiming the folder-continuation behaviour that flag also
        # triggers. 0 = no floor of its own; automation.run()'s default (or
        # followup's) stands.
        self.min_wait = int(min_wait or 0)
        # A caller-owned list the engine appends every harvested file record
        # to (its pipeline_files_out) — how the STEP dialog gets the drawing
        # sheet an image tool returned, the same way the terminal's
        # /step-auto does. None = the caller does not want them.
        self.files_out = files_out
        # custom_stages lets an add-on (e.g. BOQ) name its own ordered stages
        # instead of going through the router's fixed categories; the engine
        # accepts them directly. None = ordinary routed run, unchanged.
        self.custom_stages = custom_stages
        self.chatgpt_analysis = chatgpt_analysis
        # Prism Studio art-directs over several turns rather than one reply —
        # the look and a storyboard, then a scene at a time. A caller that
        # built its own stages names the stage that does it; a routed run
        # works it out from the renderer in its plan.
        self.reel_design_stage = reel_design_stage
        # Same idea for core.motion — its storyboard stage becomes a
        # scene-at-a-time conversation the same way. Motion has no routed-run
        # auto-detection, so every caller names this stage explicitly.
        self.motion_design_stage = motion_design_stage
        self.motion_skeleton = motion_skeleton
        # {stage label: [skill key]} for an add-on that built its own
        # stages, so the skill its prompt was written against also checks
        # the answer. See automation.run(stage_skills=).
        self.stage_skills = dict(stage_skills or {})
        self._stop = threading.Event()
        # One press skips one step: the engine clears it when it acts.
        self._skip = threading.Event()
        # "Use fallback": hand the running stage to the next tool in its
        # category now, instead of waiting out the cap. Cleared by the
        # engine per press, like _skip.
        self._fallback = threading.Event()

    def skip(self):
        """Skip the stage that is running right now and move on — for a tool
        stuck generating. The rest of the run continues."""
        self._skip.set()

    def use_fallback(self):
        self._fallback.set()

    def stop(self):
        """Ask the run to wind up at the next safe point.

        The engine polls this between stages and inside its waits, so a stop
        lands within a second or two rather than at the end of the current
        step — and it keeps everything already finished, emitting a
        "cancelled" event with the count. Nothing is killed mid-write.
        """
        self._stop.set()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def run(self):
        ok, err = CB.automation_available()
        if not ok:
            self.failed.emit(f"Automation deps not available ({err}).")
            return
        automation = CB.get_automation()
        try:
            kwargs = {}
            if self.custom_stages is not None:
                kwargs["custom_stages"] = self.custom_stages
                kwargs["chatgpt_analysis"] = self.chatgpt_analysis
            if self.reel_design_stage:
                kwargs["reel_design_stage"] = self.reel_design_stage
            if self.motion_design_stage:
                kwargs["motion_design_stage"] = self.motion_design_stage
            if self.motion_skeleton:
                kwargs["motion_skeleton"] = self.motion_skeleton
            if self.resume_urls:
                kwargs["resume_urls"] = self.resume_urls
            if self.skip_stages:
                kwargs["skip_stages"] = self.skip_stages
            if self.followup:
                kwargs["followup"] = True
                kwargs["min_wait"] = automation.FOLLOWUP_MIN_WAIT
            if self.min_wait:
                kwargs["min_wait"] = max(kwargs.get("min_wait", 0), self.min_wait)
            if self.files_out is not None:
                kwargs["pipeline_files_out"] = self.files_out
            if self.image_stages:
                kwargs["image_stages"] = self.image_stages
            if not self.failover:
                kwargs["failover"] = False
            if self.stage_skills:
                kwargs["stage_skills"] = self.stage_skills
            if self.prior_responses:
                kwargs["prior_responses"] = self.prior_responses
            responses, links = automation.run(
                self.routing, self.cfg, attachments=self.attachments,
                on_event=lambda kind, payload: self.stage_event.emit(kind, payload),
                query=self.query, should_stop=self._stop.is_set,
                skip_signal=self._skip, fallback_signal=self._fallback,
                **kwargs,
            )
            self.done.emit(responses, links)
        except Exception as e:
            self.failed.emit(str(e))


class FollowupRouteWorker(_Worker):
    """Work out which finished steps a post-completion follow-up needs, in
    order — Prism's "assign it automatically" rule, applied to refinements.
    A quick Groq classify (JSON mode).

    A plan, not one step: "make a picture of the new truck and put it in
    scene 3" needs the image tool, then the design chat, then the renderer.
    For a task that filmed a reel, two engine-owned steps join the list —
    `artwork` (make new pictures) and `reel` (change the scenes and re-film)
    — and the plan says what pictures, if any.
    """
    done = Signal(dict)     # {"steps": [keys in order], "images": "…"}
    failed = Signal(str)

    def __init__(self, followup: str, stages_info: list, cfg: dict,
                 reel: bool = False):
        super().__init__()
        self.followup = followup
        self.stages_info = stages_info   # [{"stage","agent","summary"}]
        self.cfg = cfg
        self.reel = reel

    def run(self):
        try:
            import json
            lines = "\n".join(
                f'- key "{s["stage"]}" — done by {s["agent"]}: {s["summary"]}'
                for s in self.stages_info)
            keys = [s["stage"] for s in self.stages_info]

            universal = {
                "content": "write, summarize, draft prose, or produce a document (.docx, .pdf, markdown report, article)",
                "audio": "generate audio, voiceover, podcast, speech, or narration",
                "presentation": "create slides, a deck, or presentation",
            }
            if self.reel:
                universal["artwork"] = "make pictures, graphics, diagrams, or visual assets"
                universal["reel"] = "change reel scenes or look in its design chat and film it again"

            for k in universal:
                if k not in keys:
                    keys.append(k)

            cap_lines = "\n".join(f'- key "{k}": {desc}' for k, desc in universal.items())
            extra = (
                f"\nAdditional capabilities available if requested:\n{cap_lines}\n"
                "- If the user asks to summarize, explain, or get a document/report/file, include 'content'.\n"
                "- If the user asks for audio, voice, or narration, include 'audio'.\n"
                "- If the user asks to modify an earlier step, include that step's key."
            )
            if self.reel:
                extra += (
                    '\nThis task filmed a reel. Any change that should show in the video ends with "reel". '
                    'If the user asks for audio or voiceover for the reel, include "audio" before "reel" '
                    '(e.g. ["audio", "reel"] or ["content", "audio", "reel"]).'
                )

            prompt = (
                "A task just finished. The steps that ran:\n"
                f"{lines}\n{extra}\n\n"
                f'The user now says: "{self.followup}"\n\n'
                "Which steps does this follow-up need, IN ORDER? Reply with ONLY a JSON object: "
                '{"steps": ["<key>", …], "images": "<what pictures to make, or empty>"}. Valid keys: '
                + ", ".join(f'"{k}"' for k in keys)
                + ". If genuinely unsure, use the last step that ran."
            )
            out = CB.router.groq_chat(
                self.cfg.get("api_key", ""), self.cfg.get("model", ""),
                prompt, json_mode=True, timeout=45)
            data = json.loads(out)
            steps = [str(s).strip() for s in (data.get("steps") or [])
                     if str(s).strip() in keys]
            if not steps and str(data.get("stage", "")).strip() in keys:
                steps = [str(data["stage"]).strip()]     # the old one-key shape
            plan = {"steps": list(dict.fromkeys(steps)),
                    "images": str(data.get("images") or "").strip()}
            self.done.emit(plan)
        except Exception as e:
            self.failed.emit(str(e))


class RecordWorker(_Worker):
    """Push-to-talk: recording starts as soon as this thread runs, and stops
    the instant .stop() is called from the GUI thread (e.g. a toggle
    button's second click) — no terminal/keypress dependency."""
    done = Signal(str, str)   # text, language
    failed = Signal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            wav = CB.voice.record_until(self._stop.is_set)
            text, lang = CB.voice.transcribe(wav, self.cfg)
            self.done.emit(text, lang)
        except Exception as e:
            self.failed.emit(str(e))


class InterpretWorker(_Worker):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, text: str, cfg: dict):
        super().__init__()
        self.text, self.cfg = text, cfg

    def run(self):
        try:
            self.done.emit(CB.voice.interpret(self.text, self.cfg))
        except Exception as e:
            self.failed.emit(str(e))


class SendWorker(_Worker):
    """The email blast. SMTP login, then one message per recipient with a
    provider-friendly pause between them — minutes of blocking for a real
    list, which is exactly as long as the window would be frozen if this ran
    where it used to (straight off the Send button)."""
    progress = Signal(int, int, str, bool, str)   # i, total, email, ok, error
    waiting = Signal(int)                         # seconds until a scheduled start
    done = Signal(list, list)                     # sent, failed
    failed = Signal(str)                          # couldn't even connect

    def __init__(self, cfg: dict, recipients: list, subject: str, body: str,
                 files: list, *, delay: float | None = None,
                 jitter: float = 0.0, limit: int = 0, start_at: float = 0.0):
        super().__init__()
        self.cfg, self.recipients = cfg, recipients
        self.subject, self.body, self.files = subject, body, files
        # The pace and the limits, as the window resolved them from
        # email_config.send_policy -- passed through, never re-read here, so
        # what the customer confirmed is what goes out. delay None = the
        # engine's own default.
        self.delay, self.jitter = delay, jitter
        self.limit, self.start_at = limit, start_at
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self):
        try:
            kwargs = {}
            if self.delay is not None:
                kwargs["delay"] = self.delay
            sent, failed = CB.mailer.send_bulk(
                self.cfg, self.recipients, self.subject, self.body, self.files,
                on_progress=lambda i, n, email, ok, err:
                    self.progress.emit(i, n, email, ok, err),
                should_stop=self._stop.is_set,
                jitter=self.jitter, limit=self.limit, start_at=self.start_at,
                on_wait=self.waiting.emit, **kwargs,
            )
            self.done.emit(sent, failed)
        except Exception as e:
            # Raised out of the login/connect, before any message went out —
            # nothing was sent, so this is a failure of the account, not of a
            # recipient. explain_error() is the same translator
            # mailer.verify() already runs its caught exceptions through —
            # without it, a bare "timed out" reaches friendly.py and reads as
            # "no internet", when the actual, more useful answer
            # (mailer.explain_error already knows this) is "some networks
            # block SMTP ports — try the other one".
            email_cfg = self.cfg.get("email") or {}
            self.failed.emit(CB.mailer.explain_error(
                str(e), email_cfg.get("address", ""), email_cfg.get("port", "")))


class VerifyWorker(_Worker):
    """Log in and hang up, to check the account before a real blast."""
    done = Signal(str)   # "" == fine, else the reason

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            self.done.emit(CB.mailer.verify(self.cfg))
        except Exception as e:
            # verify() already runs its own caught exceptions through
            # explain_error() — this is only the defensive fallback for
            # something verify() itself didn't catch, so it must not skip
            # the same translation.
            email_cfg = self.cfg.get("email") or {}
            self.done.emit(CB.mailer.explain_error(
                str(e), email_cfg.get("address", ""), email_cfg.get("port", "")))


class FindWorker(_Worker):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, desc: str, cfg: dict):
        super().__init__()
        self.desc, self.cfg = desc, cfg

    def run(self):
        try:
            self.done.emit(CB.pathfinder.find(self.desc, self.cfg))
        except Exception as e:
            self.failed.emit(str(e))


class MeasureWorker(_Worker):
    """Parse a CAD drawing off the UI thread.

    A 13 MB DWG takes ~40 s to convert and measure. Doing that inline froze
    the whole dialog with no feedback — the app looked hung, which on a
    client's laptop reads as broken software.
    """
    done = Signal(object, list)      # quantities dict, converter notes
    failed = Signal(str)

    def __init__(self, path: str, unit: str = "", scope: list | None = None,
                 hvac: bool = False):
        super().__init__()
        self.path, self.unit, self.scope = path, unit, scope or []
        self.hvac = hvac

    def run(self):
        try:
            boq = CB.get_boq()
            dxf_path, notes = boq.ensure_dxf(self.path)
            q = boq.measure(dxf_path, hvac=self.hvac)
            if self.unit:
                boq.apply_known_unit(q, self.unit)
            if self.scope:
                q = boq.filter_by_keywords(q, self.scope)
            self.done.emit(q, notes)
        except Exception as e:
            self.failed.emit(str(e))


class GerberWorker(_Worker):
    """Measure a PCB job (or several) off the UI thread.

    A twelve-layer board with 187,674 traces on one layer takes minutes —
    real, on a real customer job — so this cannot run inline any more than a
    13 MB DWG can in MeasureWorker. `progress` carries the same per-layer
    lines the terminal prints to its log file, so the window has something
    to show for the wait instead of a frozen dialog.
    """
    progress = Signal(str)
    done = Signal(list)              # [(job_name, job_dict), ...]
    failed = Signal(str)

    def __init__(self, paths: list[str]):
        super().__init__()
        self.paths = paths

    def run(self):
        try:
            gerber = CB.get_gerber()
            gathered = gerber.gather(self.paths)
            if not gathered:
                self.failed.emit("Nothing readable in that — check the path.")
                return
            jobs = gerber.split_jobs(gathered)
            results = []
            for name, group in jobs:
                if len(jobs) > 1:
                    self.progress.emit(f"── {name} ──")
                job = gerber.analyse(group, on_progress=self.progress.emit)
                results.append((name, job))
            self.done.emit(results)
        except Exception as e:
            self.failed.emit(str(e))


class GerberCleanWorker(_Worker):
    """Clean a job outside its board outline, off the UI thread — a
    twelve-layer job is a few seconds of reading and writing, which is
    enough to look frozen inline."""
    progress = Signal(str)
    done = Signal(dict)              # the cleaning report
    failed = Signal(str)

    def __init__(self, paths: list[str], out_dir: str):
        super().__init__()
        self.paths = paths
        self.out_dir = out_dir

    def run(self):
        try:
            cleaner = CB.get_gerber_clean()
            report = cleaner.clean_job(self.paths, self.out_dir,
                                       on_progress=self.progress.emit)
            self.done.emit(report)
        except Exception as e:
            self.failed.emit(str(e))


class ReelWorker(_Worker):
    """Render the reel off the UI thread.

    A 30-second reel is 900 frames of drawing plus encoding — around 16
    seconds. Inline that would freeze the window with no feedback, which on a
    client's laptop reads as a crash.
    """
    progress = Signal(int, int)      # frames done, total
    done = Signal(str)               # output path
    failed = Signal(str)

    def __init__(self, spec: dict, out_path: str, studio: bool = False):
        super().__init__()
        self.spec, self.out_path = spec, out_path
        # Two renderers, one worker. Pillow draws the frames in Python;
        # Studio films a real web page in a paused browser. Same spec shape
        # from here on, same progress callback, same output.
        self.studio = studio

    def run(self):
        engine = CB.get_studio() if self.studio else CB.get_reel()
        if self.studio and hasattr(engine, "ensure_accent_applied"):
            try:
                self.spec = engine.ensure_accent_applied(self.spec)
            except Exception:
                pass
        try:
            engine.render(self.spec, self.out_path,
                          on_progress=lambda d, t: self.progress.emit(d, t))
            if self.spec.get("_audio") and os.path.isfile(self.spec["_audio"]):
                try:
                    CB.get_footage().mix_audio(self.out_path, self.spec["_audio"])
                except Exception:
                    pass
            self.done.emit(self.out_path)
        except Exception as e:
            if self.studio and hasattr(engine, "ensure_accent_applied"):
                try:
                    self.spec = engine.ensure_accent_applied(self.spec)
                    engine.render(self.spec, self.out_path,
                                  on_progress=lambda d, t: self.progress.emit(d, t))
                    if self.spec.get("_audio") and os.path.isfile(self.spec["_audio"]):
                        try:
                            CB.get_footage().mix_audio(self.out_path, self.spec["_audio"])
                        except Exception:
                            pass
                    self.done.emit(self.out_path)
                    return
                except Exception as retry_e:
                    self.failed.emit(str(retry_e))
                    return
            self.failed.emit(str(e))


class StudioFollowupWorker(_Worker):
    """A change to a filmed Studio reel: asked in the conversation that
    designed it, then re-filmed here. See core.automation.studio_followup."""
    stage_event = Signal(str, dict)
    progress = Signal(int, int)      # frames done, total
    done = Signal(str, str, str)     # mp4, spec path, note
    failed = Signal(str)

    def __init__(self, cfg: dict, spec: dict, agent: str, design_url: str,
                 change: str, attachments: list | None = None,
                 images: str = "", context: str = "", task: str = "",
                 title: str = ""):
        super().__init__()
        self.cfg, self.spec, self.agent = cfg, spec, agent
        self.design_url, self.change = design_url, change
        self.attachments = list(attachments or [])
        self.images, self.context = images or "", context or ""
        self.task, self.title = task or "", title or ""
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def stopping(self) -> bool:
        return self._stop.is_set()

    def run(self):
        try:
            out, spec_path, note = CB.get_automation().studio_followup(
                self.cfg, self.spec, self.agent, self.design_url, self.change,
                attachments=self.attachments, images=self.images,
                context=self.context, task=self.task, title=self.title,
                on_event=lambda k, p: self.stage_event.emit(k, p),
                on_progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit(out, spec_path, note)
        except Exception as e:
            self.failed.emit(str(e))


class MotionWorker(_Worker):
    """Render a Motion Graphics project to MP4 off the UI thread."""
    progress = Signal(int, int)  # frames done, total
    done = Signal(str)           # output path
    failed = Signal(str)

    def __init__(self, spec: dict, out_path: str):
        super().__init__()
        self.spec = spec
        self.out_path = out_path

    def run(self):
        try:
            motion = CB.get_motion()
            motion.render(self.spec, self.out_path,
                          on_progress=lambda d, t: self.progress.emit(d, t))
            self.done.emit(self.out_path)
        except Exception as e:
            self.failed.emit(str(e))


# ── Email inquiry automation ──────────────────────────────────────────────────────────

class GroqKeyWorker(_Worker):
    """Ask Groq whether a key works, off the UI thread, at the moment it is
    saved — so a wrong key is told apart from a right one on the spot instead
    of failing the first real task."""
    done = Signal(str)       # "" == the key works, else why not

    def __init__(self, api_key: str, model: str = ""):
        super().__init__()
        self.api_key, self.model = api_key, model

    def run(self):
        try:
            self.done.emit(CB.router.verify_key(self.api_key, self.model))
        except Exception as e:                          # noqa: BLE001
            self.done.emit(str(e))


class InboxVerifyWorker(_Worker):
    """Find the mail server and check the password, off the UI thread.

    A wrong host means a DNS timeout, and three of those in a row is most of a
    minute with the window frozen — at the exact moment somebody is deciding
    whether this software works.
    """
    done = Signal(dict, str)      # settings (empty on failure), error ("" on success)

    def __init__(self, address: str, password: str, host: str = ""):
        super().__init__()
        self.address, self.password = address, password
        # Whatever the user typed into the Mail server box, tried before any
        # guess. Empty means "work it out".
        self.host = host

    def run(self):
        try:
            inbox = CB.get_inbox()
            settings, error = inbox.discover(self.address, self.password,
                                             host=self.host)
            self.done.emit(settings, error)
        except Exception as e:
            self.done.emit({}, str(e))


class InboxCheckWorker(_Worker):
    """One run of the daily loop: fetch, sort, register, work out what is due.

    Everything it does is a read, so it is safe to run on a timer and safe to
    cancel by simply ignoring the result. mailflow.check() never raises and
    never sends, so there is no partial state to unwind.
    """
    done = Signal(object)         # mailflow.Result
    failed = Signal(str)
    progress = Signal(str, int, int)      # stage, done, total (total 0 = unknown)

    def __init__(self, cfg: dict, root: str, *, state=None, knowledge=None,
                 local_only: bool = False, followup_days: int = 2,
                 max_reminders: int = 3):
        super().__init__()
        self.cfg, self.root, self.state = cfg, root, state
        self.knowledge = knowledge
        self.local_only, self.followup_days = local_only, followup_days
        self.max_reminders = max_reminders

    def run(self):
        try:
            mailflow = CB.get_mailflow()
            result = mailflow.check(
                self.cfg, mailflow.Paths(self.root), state=self.state,
                knowledge=self.knowledge, local_only=self.local_only,
                followup_days=self.followup_days,
                max_reminders=self.max_reminders,
                progress=lambda stage, done, total: self.progress.emit(
                    stage, int(done), int(total)))
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class POReadWorker(_Worker):
    """Read one purchase order into fields, off the UI thread.

    Seconds rather than minutes — one direct Groq call — but a frozen window
    while money is being read is the wrong feeling entirely. The model only
    FINDS the fields: every derived figure is Decimal arithmetic inside
    core/po.py, because a language model does arithmetic approximately and
    an approximately-right order value is a dispute.
    """
    done = Signal(object)          # po.PurchaseOrder
    failed = Signal(str)           # POError text carries what to do next

    def __init__(self, cfg: dict, text: str, source: str = ""):
        super().__init__()
        self.cfg, self.text, self.source = cfg, text, source

    def run(self):
        try:
            po = CB.get_po()
            order = po.extract(self.text, self.cfg.get("api_key", ""),
                               self.cfg.get("model", "") or "",
                               source=self.source)
            self.done.emit(order)
        except Exception as e:
            self.failed.emit(str(e))


# ── Help & support ────────────────────────────────────────────────────────────

class SupportWorker(_Worker):
    """Run an explicitly requested Prism diagnosis through the user's key.

    This is not used for ordinary Help searches. The UI sends a constrained
    diagnostic prompt containing only support material and a scrubbed log; no
    task content, credentials, or raw diagnostics are added by this worker.
    """
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, cfg: dict, prompt: str, parent=None):
        super().__init__(parent)
        self.cfg, self.prompt = cfg, prompt

    def run(self):
        try:
            reply = CB.router.groq_chat(
                self.cfg.get("api_key", ""), self.cfg.get("model", "") or "",
                self.prompt, temperature=0.15, timeout=45, retries=1)
            self.done.emit((reply or "").strip())
        except Exception as e:
            self.failed.emit(str(e))


class DraftWorker(_Worker):
    """Write one email using the AI tools in the customer's own browser.

    Minutes, not seconds: it opens Chrome, types the prompt into whichever
    tool they picked, and waits for the answer to finish streaming. That is
    the price of using their subscription instead of an API key, and it is
    why this is only ever used for the handful of emails a week that are
    worth writing well — never for sorting the inbox.
    """
    progress = Signal(str)           # a line for the status label
    done = Signal(object)            # drafting.Draft
    failed = Signal(str)

    def __init__(self, cfg: dict, prompt: str, *, purpose: str = "draft",
                 attachments: list | None = None):
        super().__init__()
        self.cfg, self.prompt, self.purpose = cfg, prompt, purpose
        self.attachments = list(attachments or [])
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            drafting = CB.get_drafting()
            result = drafting.draft(
                self.cfg, self.prompt, purpose=self.purpose,
                attachments=self.attachments,
                on_event=self._event,
                should_stop=self._stop.is_set)
            self.done.emit(result)
        except Exception as e:
            self.failed.emit(str(e))

    def _event(self, kind: str, payload):
        """Turn the pipeline's own progress events into one readable line.

        The tool names are worth showing: a customer watching Chrome open by
        itself wants to know Prism meant to do that.
        """
        if kind == "stage_start":
            self.progress.emit(
                f"Asking {payload.get('agent', 'the AI tool')}…")
        elif kind == "stage_done":
            self.progress.emit("Reading the answer…")


class UpdateWorker(_Worker):
    """Check for, and if one exists download+stage, a Phase 1 in-app update
    — off the UI thread, same reasoning as FFmpegWorker above (a manifest
    fetch plus however many changed files add up to real seconds, and a
    frozen window for that long reads as a crash).

    Deliberately does the check AND the staging in one worker run rather than
    two separate button presses: by the time a customer has clicked
    "Download", they've already committed to getting the update, and
    updater.check_for_update()'s own verification (signature, expiry,
    monotonic version) is what decides whether `staged` or `none` fires —
    nothing here weakens or skips any of that; see updater.py's docstring.
    """
    progress = Signal(int, int)      # files done, files total
    staged = Signal(object)          # updater.StagedUpdate
    none = Signal()                  # no verified update newer than running
    failed = Signal(str)

    def run(self):
        import updater
        try:
            check = updater.check_for_update()
            if check is None:
                self.none.emit()
                return
            staged = updater.stage_update(
                check, updater.install_dir(),
                on_progress=lambda done, total: self.progress.emit(done, total))
            self.staged.emit(staged)
        except updater.UpdateError as e:
            self.failed.emit(str(e))
        except Exception as e:                        # noqa: BLE001
            self.failed.emit(str(e))


class QuietUpdateWorker(_Worker):
    """The background half of a quiet update: check (honouring the rollout),
    download and verify, and leave the result waiting. Applies nothing -- only
    the customer's restart does (updater.apply_ready).

    Off the UI thread for the same reason as UpdateWorker, and more so: this
    one runs unprompted, and re-proving a waiting update hashes the whole
    staged tree, which is seconds of disk the window must not wait for.
    """
    ready = Signal(object)           # updater.StagedUpdate, verified and waiting
    none = Signal()                  # nothing to offer this device
    failed = Signal(str)

    def run(self):
        import updater
        try:
            staged = updater.auto_stage()
        except Exception as e:                        # noqa: BLE001
            self.failed.emit(str(e))
            return
        if staged is None:
            self.none.emit()
        else:
            self.ready.emit(staged)


class FFmpegWorker(_Worker):
    """Download and install FFmpeg, off the UI thread.

    30 MB over an office connection is a minute of nothing, and a frozen
    window for a minute is indistinguishable from a crash — which is the
    impression this feature exists to avoid making.
    """
    progress = Signal(int, int)      # bytes done, bytes total (0 = unknown)
    done = Signal(str)               # path to the executable
    failed = Signal(str)

    def run(self):
        try:
            ffmpeg = CB.get_ffmpeg()
            self.done.emit(ffmpeg.download(
                lambda done, total: self.progress.emit(done, total)))
        except Exception as e:
            self.failed.emit(str(e))


class LoginTabsWorker(_Worker):
    """Open the sign-in tabs in Prism's own Chrome profile, off the UI thread.

    The engine's open_login_tabs copies the real Chrome profile into Prism's
    the first time — seconds, minutes on a big profile, and on Windows it
    raises when Chrome holds a file open — then waits for Chrome to start
    between tabs. On the UI thread that froze the window, and whatever it
    raised went to the stdout a windowed build does not have: "Open login
    tabs doesn't do anything" on a fresh Windows 10 install (09-Oct-2026).
    """
    done = Signal(int)               # how many tabs were asked for
    failed = Signal(str)             # what went wrong, in one line

    def __init__(self, urls: list, parent=None):
        super().__init__(parent)
        self._urls = list(urls)

    def run(self):
        try:
            CB.get_automation().open_login_tabs(self._urls)
            self.done.emit(len(self._urls))
        except Exception as e:                      # noqa: BLE001
            import diagnostics
            import traceback
            if getattr(diagnostics, "_installed", False):
                diagnostics.write("CRASH", traceback.format_exc())
            self.failed.emit(f"{type(e).__name__}: {e}")

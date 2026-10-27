"""The main window: wires the sidebar + workbench columns together and owns
every background worker's lifecycle. This is the only file that makes
decisions — every widget below it is dumb display + signals.

Layout is direction 1b of the Prism Directions canvas: "everything in view,
nothing to drag". Three fixed columns — rail, work, context — replacing the
old floating QDockWidgets. Nothing here can be closed or lost behind a tab, so
there's no View menu and no way to end up staring at an empty window.

The work column is a two-page stack: composing (task + plan) and running
(live output). Those are the only two things you can be doing, they never
want to be on screen at once, and the plan is one click back."""
from __future__ import annotations
import json
import os
from PySide6.QtCore import Qt, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import QGuiApplication, QFont, QCursor, QDesktopServices, QPainter, QPixmap, QColor, QImage, QLinearGradient
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QMessageBox, QFrame,
    QFileDialog, QDialog, QLabel, QScrollArea, QStackedWidget, QPushButton,
    QMenu, QApplication, QGraphicsScene, QGraphicsBlurEffect,
    QGraphicsOpacityEffect, QAbstractButton, QAbstractItemView, QAbstractSpinBox,
    QComboBox, QLineEdit, QPlainTextEdit, QTextEdit,
)

import app_meta
import awake
import core_bridge as CB
import email_config
import diagnostics
import i18n
from widgets.loader import LoadingDialog
import identity
import licensing
import paths
import theme
import updater
import workspace
from addons import registry
from widgets import icons
from widgets.sidebar import Sidebar
from widgets.home_panel import HomePanel
from addons.inquiry.panel import InquiryPanel
from addons.inquiry.dialog import InquiryDialog
from widgets.artifacts_panel import ArtifactsPanel
from widgets.settings_panel import SettingsPanel
from widgets.wizard_panel import WizardPanel
from widgets.tour import TourOverlay
from addons.bom.panel import BomPanel
from addons.boq.panel import BoqPanel
from widgets.catalog_panel import CatalogPanel
from addons.email.panel import EmailPanel
from addons.gerber.panel import GerberPanel
from addons.step.panel import StepPanel
from addons.leads.panel import LeadsPanel
from addons.leads.dialog import LeadsDialog
from addons.whatsapp.panel import WhatsAppPanel
from widgets.guide_panel import GuidePanel
from widgets.history_panel import HistoryPanel
from widgets.support_panel import SupportPanel
from widgets.controls import kicker
from widgets import controls as C
from widgets.input_panel import InputPanel
from widgets.files_panel import FilesPanel
from widgets.agents_panel import AgentsPanel
from widgets.output_panel import OutputPanel
from workers import (RouteWorker, AutomationWorker, RecordWorker,
                     PlanBriefWorker,
                     StudioFollowupWorker,
                     InterpretWorker, FindWorker, AuthorizeWorker,
                     FFmpegWorker, QuietUpdateWorker, UpdateWorker, FollowupRouteWorker,
                     ReelWorker)
import wakeword
from wakeword import WakeWordListener
from dialogs.ai_directory_dialog import AIDirectoryDialog
from addons.email.dialog import EmailComposeDialog, EmailSetupDialog
from addons.boq.dialog import BoqDialog
from addons.gerber.dialog import GerberDialog
from addons.step.dialog import StepDialog
from addons.reel.dialog import ReelDialog
from addons.motion.dialog import MotionDialog
from addons.whatsapp.dialog import WhatsAppDialog
from dialogs.completion_dialog import CompletionDialog
from dialogs.history_dialog import HistoryDialog

COMPOSE, RUNNING = 0, 1        # pages of the workbench's own inner stack

# ── the body stack ──────────────────────────────────────────────────────────
# ONE ordered table. THE ORDER IS THE INDEX, and everything else about screen
# identity is derived from it: the integer constants below, the name->index
# lookup _show_screen() switches on, and the index->name lookup that keeps the
# rail lit.
#
# Those were four separate hand-maintained sites, in the highest-churn file in
# the repository, and the fourth was written out as the literal inverse of the
# third. A fifth -- the addWidget() call order that actually ASSIGNS these
# integers -- was enforced by nothing but a trailing comment per line. Adding
# or renaming one screen meant getting five places right, and the only symptom
# of missing one is the app quietly showing the wrong screen.
#
# The addWidget order is now asserted against this table by
# tests/test_screen_registry.py, so the comment is no longer the enforcement.
#
# Appending is still the safe move -- these integers are positions, so
# inserting renumbers everything after it -- but nothing has to be renumbered
# BY HAND any more.
SCREENS = (
    "home", "workbench", "inquiry", "config", "guide", "catalog",
    "runs", "boq", "email", "support", "gerber",
    "wizard",           # reached only from _first_run(), never by name
    "artifacts",
    "inquiry_work",     # reached only by drilling in from the launcher panel
    "bom",
    "step",
    "leads",
    "whatsapp",         # appended last: nothing above renumbers
    "step_work",        # STEP's workbench — reached by the rail, never by name
)
_INDEX = {name: i for i, name in enumerate(SCREENS)}

# The two that exist as pages but are NOT addressable by name. Asking
# _show_screen() for either falls through to HOME, exactly as before -- they
# were simply absent from the old hand-written table.
_UNROUTED = {"wizard", "inquiry_work", "step_work"}
SCREEN_INDEX = {n: i for n, i in _INDEX.items() if n not in _UNROUTED}
SCREEN_NAME = {i: n for n, i in SCREEN_INDEX.items()}

HOME = _INDEX["home"]
WORKBENCH = _INDEX["workbench"]
INQUIRY = _INDEX["inquiry"]
SETTINGS = _INDEX["config"]
GUIDE = _INDEX["guide"]
CATALOG = _INDEX["catalog"]
HISTORY = _INDEX["runs"]
BOQ = _INDEX["boq"]
EMAIL = _INDEX["email"]
SUPPORT = _INDEX["support"]
GERBER = _INDEX["gerber"]
WIZARD = _INDEX["wizard"]
ARTIFACTS = _INDEX["artifacts"]
INQUIRY_WORK = _INDEX["inquiry_work"]
BOM = _INDEX["bom"]
STEP = _INDEX["step"]
STEP_WORK = _INDEX["step_work"]

# Wake-word threads that were asked to stop but had not finished in time.
# Module level, not an attribute: on window close there is nothing else left
# holding the reference, and a QThread collected while its OS thread is still
# running aborts the process. Entries remove themselves once finished fires.
_retired_listeners: list = []


def _is_running(worker) -> bool:
    """True if this QThread is still alive.

    A worker whose C++ side has already been deleted raises RuntimeError from
    isRunning() rather than returning False, and that exception thrown during
    closeEvent would skip retiring every worker after it in the list — turning
    a tidy shutdown back into the abort this is here to prevent.
    """
    if worker is None:                  # nothing was ever started
        return False
    try:
        return bool(worker.isRunning())
    except RuntimeError:
        return False


def _retire_listener(listener, wait_ms: int = 3000) -> None:
    """Stop a wake-word listener, and make sure nothing drops it while its
    thread is still alive.

    stop() waits, but only briefly — an in-flight Whisper request holds the
    loop until its own 60s timeout, and blocking the GUI thread for that long
    is worse than the bug. When the wait runs out the listener is parked here,
    referenced and alive, until finished says the thread has really gone.
    Releasing it any earlier is precisely the "Destroyed while thread is still
    running" abort this exists to prevent.
    """
    if listener.stop(wait_ms):
        return
    _retired_listeners.append(listener)

    def _drop():
        try:
            _retired_listeners.remove(listener)
        except ValueError:
            pass

    listener.finished.connect(_drop)

# Routed agents that belong to a paid add-on, DERIVED from the manifests.
# The rail gate alone would miss these: the router can put Prism Reel into a
# plan without the customer ever touching the Reel item in the sidebar -- and
# Reel is not even ON the rail, so for that one there is no other gate at all.
#
# The keys are AGENT_REGISTRY display names, which the licence server also
# uses to key its published payload overrides. Renaming one silently breaks
# both this gate and that payload row, which is why addons/<key>/addon.py
# says so beside every `agents=` entry.
AGENT_FEATURES = {agent: addon.feature
                  for addon in registry.REGISTRY
                  for agent in addon.agents}


class DashboardCentral(QWidget):
    """Central widget that paints the wallpaper background cleanly scaled to cover,
    preserving aspect ratio across any window size, and caches a Gaussian-blurred
    version for pure frosted glassmorphism cards and sidebar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("central")
        self.setAttribute(Qt.WA_StyledBackground, False)
        bg_path = None
        try:
            cfg = CB.config.load()
            custom_bg = cfg.get("custom_bg") if cfg else None
            # Empty string means the user explicitly chose the pure-white default.
            # A non-empty value that exists on disk is a bundled or user wallpaper.
            if custom_bg and os.path.exists(custom_bg):
                bg_path = custom_bg
            # Nothing chosen yet (None) or "" → the default: a plain white
            # screen, no picture and no logo. A wallpaper is only ever
            # something the person picked in Settings → Appearance.
        except Exception:
            bg_path = None
        self._bg_orig = QPixmap(bg_path) if bg_path and os.path.exists(bg_path) else None
        self._cached_pixmap = None
        self._cached_blurred = None
        self._cached_size = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_cache()
        if hasattr(self, "_lumi_overlay"):
            self._lumi_overlay.reposition()

    def _update_cache(self):
        if self._bg_orig and not self._bg_orig.isNull():
            w, h = max(1, self.width()), max(1, self.height())
            self._cached_pixmap = self._bg_orig.scaled(
                w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self._cached_size = (w, h)

            # Generate high-performance Gaussian blurred version for glassmorphic cards
            bw, bh = max(1, w // 2), max(1, h // 2)
            small = self._cached_pixmap.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            scene = QGraphicsScene()
            item = scene.addPixmap(small)
            blur = QGraphicsBlurEffect()
            blur.setBlurRadius(24)
            item.setGraphicsEffect(blur)
            out = QImage(QSize(bw, bh), QImage.Format_ARGB32_Premultiplied)
            out.fill(0)
            p = QPainter(out)
            scene.render(p)
            p.end()
            self._cached_blurred = QPixmap.fromImage(out).scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    def get_blurred_pixmap(self) -> QPixmap | None:
        if self._cached_blurred is None or self._cached_size != (self.width(), self.height()):
            self._update_cache()
        return self._cached_blurred

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._cached_pixmap is None or self._cached_size != (self.width(), self.height()):
            self._update_cache()

        if self._cached_pixmap and not self._cached_pixmap.isNull():
            pw, ph = self._cached_pixmap.width(), self._cached_pixmap.height()
            x = (self.width() - pw) // 2
            y = (self.height() - ph) // 2
            painter.drawPixmap(x, y, self._cached_pixmap)
            grad = QLinearGradient(0, 0, 0, self.height())
            grad.setColorAt(0.0, QColor(255, 255, 255, 75))
            grad.setColorAt(0.45, QColor(255, 255, 255, 45))
            grad.setColorAt(1.0, QColor(255, 255, 255, 30))
            painter.fillRect(self.rect(), grad)
        else:
            painter.fillRect(self.rect(), QColor("#ffffff"))  # the default: plain white

    def set_background(self, path: str):
        if path and os.path.exists(path):
            # A real wallpaper (bundled preset)
            self._bg_orig = QPixmap(path)
        elif path == "" or path is None:
            # Empty string = user chose pure-white default
            self._bg_orig = None
        else:
            # A path that is gone: plain white, never a picture nobody chose.
            self._bg_orig = None
        self._cached_pixmap = None
        self._cached_blurred = None
        self._cached_size = None
        self.update()


class MainWindow(QMainWindow):
    # From the reel layout editor's local server (its own thread — Qt queues
    # these onto the UI thread): the browser pressed Save / Save & render.
    reel_edits_saved = Signal(list)
    reel_edits_rendered = Signal(list)
    reel_refine_requested = Signal(str, dict)

    def set_wallpaper(self, path: str):
        self.cfg["custom_bg"] = path
        central = self.centralWidget()
        if hasattr(central, "set_background"):
            central.set_background(path)
        self.update()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prism")
        self._fit_to_screen()

        self.cfg = CB.config.load()
        try:
            import output_folders
            output_folders.apply(self.cfg)
        except Exception:                                   # noqa: BLE001 - never stop the window opening
            pass
        self.attachments: list[dict] = []
        self.pending_mentions: list[dict] = []   # [{"description","path","kind"}]
        self.routing: dict | None = None

        self._record_worker = None
        self._wake_listener = None
        self._workers = []    # keep references so QThreads aren't GC'd mid-run
        self._stage_agents: dict[str, str] = {}   # stage -> agent, from stage_start
        self._stage_results: list[dict] = []      # built up during a run, for the completion popup
        self._run_finished = False                # a finished plan is spent — see _back_to_plan
        self._run_id = ""                         # licence server's id for the current run
        self._active_run = None                   # the AutomationWorker, so Stop can reach it
        # Whichever worker represents the in-flight "Make a plan" attempt —
        # AuthorizeWorker while the licence check is out, then the RouteWorker
        # once Groq is actually being asked. Neither can be interrupted
        # mid-call (no cancellable HTTP hook), so Cancel doesn't kill the
        # thread — it just clears this, and _on_routed/_on_route_failed
        # compare self.sender() against it and discard the answer if the
        # attempt it belongs to is no longer the current one.
        self._active_plan_worker = None

        # ── the task queue ───────────────────────────────────────────────────
        # Tasks the user lined up before pressing Make a plan. Each one is a
        # full journey of its own — plan, authorise, run — because the router
        # can only plan one task at a time and each is separately billable.
        # _task_runs accumulates {"task", "stages"} so the completion window
        # can say which AIs ran for task 1 as distinct from task 2.
        self._task_queue: list[str] = []
        self._task_pos = 0                        # 1-based index of the running task
        self._task_runs: list[dict] = []
        self._queue_stopped = False               # a licence refusal kills the rest
        self._auto_run = False                    # set once Start the work is pressed
        self._current_run_file = None
        self._is_followup_run = False
        self._followup_session = None
        self._followup_text = ""

        self._build_ui()
        self._wire()
        self.refresh_licence_ui()
        self._start_licence_timer()
        self._start_quiet_update_timer()

        # The explainer needs nothing but eyes on the window, so it no longer
        # waits on the licence — a first launch with a stuck licence sync is
        # exactly when a brand-new user most needs to be told what Prism is,
        # not left alone with a locked sidebar and no context. _first_run
        # keeps the Groq key dialog behind the licence check: a customer who
        # cannot use Prism yet does not need a key dialog on top of that.
        if not CB.config.is_configured(self.cfg):
            # Deferred to the event loop rather than run here. A modal opened
            # from inside __init__ blocks before the window is on screen, so
            # it can appear behind it or with nowhere to centre itself — and
            # the constructor never returns until it is dismissed.
            QTimer.singleShot(0, self._first_run)

    # ── keeping the licence and lease current ───────────────────────────────
    # The authorisation lease is short by design (about half an hour), so a
    # window left open all afternoon would let it lapse and turn the next
    # click into a blocking round trip — the exact latency the lease exists to
    # remove. This tops it up quietly instead.
    #
    # The timer lives here rather than in the licensing package for the same
    # reason set_paywall_handler does: that package deliberately never imports
    # Qt, so the CLI and the tests can use it without a display.
    LICENCE_REFRESH_MS = 10 * 60 * 1000

    def _start_licence_timer(self):
        """Renew token and lease in the background, forever, off the UI thread.

        licensing.refresh() returns immediately and does its work on a daemon
        thread, so this costs the event loop nothing. Ten minutes against a
        thirty-minute lease means two chances to recover from a blip before
        anyone notices one — and /v1/lease records no usage, so a customer is
        never billed for Prism keeping itself current.
        """
        self._licence_timer = QTimer(self)
        self._licence_timer.setInterval(self.LICENCE_REFRESH_MS)
        self._licence_timer.timeout.connect(self._tick_licence)
        self._licence_timer.start()

        # Early repaints, because the first tick is TEN MINUTES away.
        #
        # The window is built from the cached token while _licence_gate's
        # refresh is still in flight. When that token is past its offline
        # window the banner correctly says so — and then the refresh lands a
        # second later, makes the licence valid again, and nothing repainted.
        # The customer sat looking at "Prism hasn't been able to reach the
        # licence server" and an "Enter a licence key" button for up to ten
        # minutes after it had already fixed itself, which reads as being
        # asked to buy something they have already paid for.
        #
        # These cost nothing: refresh_licence_ui() reads the CACHED state and
        # touches the network never. Spread out because a cold host can take
        # 30-50s to answer, and the whole point is to catch the moment it does.
        for delay_ms in (1500, 4000, 10_000, 30_000, 60_000, 90_000, 150_000):
            QTimer.singleShot(delay_ms, self._repaint_licence)

    # ── quiet updates ───────────────────────────────────────────────────────
    # Check for a release now and then, download it in the background, and
    # leave it waiting; the banner offers "Restart now". Nothing is applied
    # without the customer pressing it, and never while a task is running.
    QUIET_UPDATE_FIRST_MS = 60 * 1000          # a minute in: after startup settles
    QUIET_UPDATE_EVERY_MS = 6 * 60 * 60 * 1000

    def _start_quiet_update_timer(self):
        self._ready_update = None
        self._quiet_worker = None
        if not paths.is_frozen():
            return          # a source checkout has no installed folder to swap
        self._quiet_timer = QTimer(self)
        self._quiet_timer.setInterval(self.QUIET_UPDATE_EVERY_MS)
        self._quiet_timer.timeout.connect(self._quiet_update_check)
        self._quiet_timer.start()
        QTimer.singleShot(self.QUIET_UPDATE_FIRST_MS, self._quiet_update_check)

    def _quiet_update_check(self):
        """Start the background check unless one is running or an update is
        already waiting (it was verified when it was staged and is verified
        again before it is applied)."""
        if self._ready_update is not None or _is_running(self._quiet_worker):
            return
        worker = QuietUpdateWorker()
        worker.ready.connect(self._on_quiet_update_ready)
        # none / failed: stay silent. The manual Download path is unchanged,
        # and a background check that cannot reach the host is not news.
        self._quiet_worker = worker
        self._workers.append(worker)
        worker.start()

    def _on_quiet_update_ready(self, staged):
        self._ready_update = staged
        self.refresh_licence_ui()

    def _apply_ready_update(self):
        """The banner's "Restart now"."""
        if _is_running(getattr(self, "_active_run", None)):
            QMessageBox.information(
                self, i18n.t("Update"),
                i18n.t("A task is still running. The update is ready and will "
                       "wait — restart Prism when it finishes."))
            return
        try:
            updater.apply_ready()
        except Exception:                           # noqa: BLE001
            # It failed its re-check (changed, withdrawn, overtaken): forget
            # it and use the download page, as the manual path always has.
            self._ready_update = None
            self.refresh_licence_ui()
            self._open_download_fallback()
            return
        QApplication.instance().quit()

    def _later_ready_update(self):
        if self._ready_update is not None:
            updater.dismiss(self._ready_update.version)
        self.refresh_licence_ui()

    def _repaint_licence(self):
        """Re-read the cached licence and repaint. No network, never raises."""
        try:
            licensing.reload()
            self.refresh_licence_ui()
        except Exception:                          # noqa: BLE001
            pass

    def _tick_licence(self):
        try:
            licensing.refresh()
            updater.report_async()          # outcomes queued by an update; a no-op when empty
            # Repaint from the CACHED state, which the previous tick's refresh
            # has by now written. Reading it here rather than waiting on this
            # tick's network call is what keeps the timer non-blocking.
            licensing.reload()
            self.refresh_licence_ui()
        except Exception:                          # noqa: BLE001
            pass    # a licence refresh must never be able to crash the window

    # ── layout ──────────────────────────────────────────────────────────────
    def _fit_to_screen(self):
        """Size (and center) the window to whatever screen it's actually on,
        instead of a fixed 1400x900 that can overflow a smaller display."""
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail:
            w = min(1360, int(avail.width() * 0.92))
            h = min(880, int(avail.height() * 0.88))
            self.resize(w, h)
            self.move(avail.center().x() - w // 2, avail.center().y() - h // 2)
        else:
            self.resize(1180, 760)
        # Three columns with fixed rails need more floor than the old dock
        # layout did — below this the work column starts eating its own text.
        self.setMinimumSize(1060, 640)

    def _build_ui(self):
        central = DashboardCentral()
        central.setObjectName("central")
        # A vertical shell so the licence banner can span the full width above
        # all three columns. It has to be impossible to miss and impossible to
        # confuse with a run message, which rules out the status bar.
        shell = QVBoxLayout(central)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._licence_banner())

        columns = QWidget()
        columns.setObjectName("columns")
        outer = QHBoxLayout(columns)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        self.sidebar = Sidebar()
        outer.addWidget(self.sidebar)

        # The rail's destinations are screens except Settings, which remains
        # in the stack for registry compatibility but is presented as a
        # focused modal over the current screen. The workbench keeps its own
        # inner stack (compose → running) and its own
        # context rail; both live inside the one screen, because the files and
        # prompt panels are about the task being composed and mean nothing on
        # any other screen — which is why they used to be a permanently
        # visible third column showing "nothing attached yet".
        self.screens = QStackedWidget()
        self.home_panel = HomePanel(self.cfg)
        self.screens.addWidget(self.home_panel)          # HOME
        self.screens.addWidget(self._workbench_screen())  # WORKBENCH
        self.inquiry_panel = InquiryPanel(self.cfg)
        self.screens.addWidget(self.inquiry_panel)        # INQUIRY
        self.settings_panel = SettingsPanel(self.cfg, self)
        self.screens.addWidget(self.settings_panel)       # SETTINGS
        self.guide_panel = GuidePanel(self.cfg)
        self.screens.addWidget(self.guide_panel)          # GUIDE
        self.catalog_panel = CatalogPanel(self.cfg)
        self.screens.addWidget(self.catalog_panel)        # CATALOG
        self.history_panel = HistoryPanel(self.cfg)
        self.screens.addWidget(self.history_panel)        # HISTORY
        self.boq_panel = BoqPanel(self.cfg)
        self.screens.addWidget(self.boq_panel)            # BOQ
        self.email_panel = EmailPanel(self.cfg)
        self.screens.addWidget(self.email_panel)          # EMAIL
        self.support_panel = SupportPanel(self.cfg)
        self.screens.addWidget(self.support_panel)        # SUPPORT
        self.gerber_panel = GerberPanel(self.cfg)
        self.screens.addWidget(self.gerber_panel)          # GERBER
        self.wizard_panel = WizardPanel(self.cfg)
        self.screens.addWidget(self.wizard_panel)          # WIZARD
        self.artifacts_panel = ArtifactsPanel(self.cfg)
        self.screens.addWidget(self.artifacts_panel)        # ARTIFACTS
        # The Email inquiry automation working screen — drilled into from the
        # launcher panel (INQUIRY), never a rail entry of its own. Used to be
        # constructed fresh and .exec()'d as a modal every time it opened;
        # now it is built once, like every other screen, and .enter() is
        # what refreshes it on each visit — see _open_inquiry_dialog.
        self.inquiry_work_panel = InquiryDialog(self.cfg, self)
        self.screens.addWidget(self.inquiry_work_panel)     # INQUIRY_WORK
        self.bom_panel = BomPanel(self.cfg)
        self.screens.addWidget(self.bom_panel)              # BOM
        self.step_panel = StepPanel(self.cfg)
        self.screens.addWidget(self.step_panel)             # STEP
        self.leads_panel = LeadsPanel(self.cfg)
        self.screens.addWidget(self.leads_panel)            # LEADS
        self.whatsapp_panel = WhatsAppPanel(self.cfg)
        self.screens.addWidget(self.whatsapp_panel)         # WHATSAPP (last: no renumber)
        # STEP's workbench page: an empty host now, filled the first time STEP
        # is opened (building it imports the CAD engine, which most sessions
        # never need).
        self.step_host = QWidget()
        host_lay = QVBoxLayout(self.step_host)
        host_lay.setContentsMargins(0, 0, 0, 0)
        self.screens.addWidget(self.step_host)              # STEP_WORK
        outer.addWidget(self.screens, stretch=1)
        shell.addWidget(columns, stretch=1)
        self.setCentralWidget(central)

        # Global floating Lumi Help Center (animated mascot, cards, chat)
        from widgets.lumi_card import LumiOverlay
        self.lumi_panel = SupportPanel(self.cfg)
        self.lumi_panel.command_requested.connect(self._handle_command)
        self.lumi_overlay = LumiOverlay(central, self.lumi_panel)
        self.lumi_overlay.command_requested.connect(self._handle_command)
        central._lumi_overlay = self.lumi_overlay

        self.home_panel.describe_task.connect(
            lambda: self._handle_command("workbench"))
        self.home_panel.task_submitted.connect(self._on_home_task_submitted)
        self.home_panel.open_addon.connect(self._handle_command)
        self.home_panel.open_history.connect(lambda: self._handle_command("runs"))
        # Lumi is a floating Home assistant. Its content is the same support
        # panel used by every recovery route, mounted in the popover on demand.
        self.home_panel.lumi_open_requested.connect(self._open_lumi)
        self.home_panel.lumi_close_requested.connect(self._close_lumi)
        self.inquiry_panel.open_dialog.connect(self._open_inquiry_dialog)
        self.inquiry_panel.check_requested.connect(
            lambda: self._open_inquiry_dialog(auto_check=True))
        self.inquiry_panel.set_up.connect(self._open_inquiry_setup)
        # Same attach path the sidebar's own favourites use (see
        # sidebar.favorite_chosen above) — a customer's attachment becomes
        # a real Prism attachment in one click, from inside the inquiry
        # screen or the quotation window it opens.
        self.inquiry_work_panel.attach_to_prism.connect(self._attach_path)
        self.wizard_panel.finished.connect(self._on_wizard_finished)
        self.wizard_panel.guide_requested.connect(self._open_guide)
        self.settings_panel.login_tabs.connect(self._open_login_tabs)
        # The four screens the rail used to spend a row each on.
        self.settings_panel.navigate.connect(self._navigate_from_settings)
        self.settings_panel.finished.connect(self._close_settings)
        self.settings_panel.tour_requested.connect(self._start_tour)
        self.settings_panel.rename_requested.connect(self._ask_display_name)
        # Releasing this computer's seat happens on the Settings screen now
        # (the danger group at the foot of the Licence section). The rail's
        # padlocks and the licence banner are drawn from licensing.state(), so
        # they have to be told rather than waiting for the ten-minute timer to
        # notice the licence has gone.
        self.settings_panel.licence_changed.connect(self.refresh_licence_ui)
        self.settings_panel.wallpaper_changed.connect(self.set_wallpaper)
        self.history_panel.open_run.connect(self._open_run_record)
        # Deleting runs changes what Home's activity list and its counters
        # add up to, and Home is already built by then -- it re-reads from
        # disk, so it just has to be told to look again.
        self.history_panel.runs_changed.connect(self.home_panel.refresh)
        # A recent-activity row on Home opens the run it names, through the
        # same handler History uses — same record, same viewer.
        self.home_panel.open_run_record.connect(self._open_run_record)
        self.boq_panel.opened.connect(self._open_boq_dialog)
        self.bom_panel.opened.connect(self._open_bom_dialog)
        self.step_panel.opened.connect(self._open_step_dialog)
        self.step_work = None           # built on first visit — see _step_screen
        self.gerber_panel.opened.connect(self._open_gerber_dialog)
        self.email_panel.opened.connect(lambda: self._open_email_dialog("one"))
        self.email_panel.open_compose.connect(self._open_email_dialog)
        self.email_panel.change_account.connect(self._open_email_setup)
        self.leads_panel.opened.connect(self._open_leads_dialog)
        self.whatsapp_panel.opened.connect(self._open_whatsapp_dialog)
        # The screens that now offer a way onward. Same pattern as
        # settings_panel.navigate — the payload is a _handle_command key, so
        # every screen reaches every other through the one router rather than
        # each learning about the others.
        self.catalog_panel.navigate.connect(self._handle_command)
        self.history_panel.navigate.connect(self._handle_command)
        self.guide_panel.navigate.connect(self._handle_command)
        for panel in (self.boq_panel, self.bom_panel, self.gerber_panel,
                      self.step_panel, self.email_panel, self.leads_panel,
                      self.whatsapp_panel):
            panel.navigate.connect(self._handle_command)
            panel.open_run.connect(self._open_run_record)
        self.inquiry_work_panel.navigate.connect(self._handle_command)
        # "Open →" on an active-run card goes to the run itself, not a blank
        # bench — the run is already on the workbench's RUNNING page.
        self.home_panel.open_run.connect(lambda: self._show_screen("workbench"))
        # An answer's button opens the thing it talks about — the same wiring
        # the guide uses, so reading about a setting and reaching it are one
        # gesture.
        self.support_panel.command_requested.connect(self._handle_command)

    def _open_lumi(self):
        """Open the global floating Lumi assistant."""
        self.lumi_overlay.open()

    def _close_lumi(self):
        """Close the global floating Lumi assistant."""
        self.lumi_overlay.close()

    def _workbench_screen(self) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._work_column(), stretch=1)
        # Context rail (files panel) is instantiated for signal wiring
        # but not added to the visible layout — the right-side strip is hidden.
        self._context_column()
        return wrap

    def _show_screen(self, name: str = "workbench"):
        """Switch the body stack and keep the rail's highlight in step."""
        # Leaving the Email inquiry automation working screen: stop its auto-check
        # timer (see InquiryDialog.on_leave) and pick up whatever it wrote —
        # it saves its own settings and reading bookmark, works the register
        # (new inquiries, sent quotes, logged replies), so both the in-memory
        # cfg and the launcher panel behind it are stale the moment you leave.
        if self.screens.currentIndex() == INQUIRY_WORK:
            self.inquiry_work_panel.on_leave()
            self.cfg = CB.config.load()
            self.inquiry_panel.cfg = self.cfg
        # The STEP screen was built with whatever cfg existed on its first
        # visit; this window's cfg is replaced when it is re-read (after the
        # Email inquiries screen, after Setup). A STEP holding the old one would
        # use an old Groq key — and save it back over the new one.
        if getattr(self, "step_work", None) is not None:
            self.step_work.cfg = self.cfg
        index = SCREEN_INDEX.get(name, HOME)
        self.screens.setCurrentIndex(index)
        # Re-read on arrival. Both screens are reports over stores that other
        # parts of the app (and the inquiry dialog) write to, so what was true
        # when they were last built may not be true now.
        if index == HOME:
            self.home_panel.refresh()
        elif index == INQUIRY:
            self.inquiry_panel.refresh()
        elif index == SETTINGS:
            self.settings_panel.cfg = self.cfg
            self.settings_panel.refresh()
        elif index == HISTORY:
            self.history_panel.refresh()
        elif index == ARTIFACTS:
            self.artifacts_panel.refresh()
        elif index == CATALOG:
            self.catalog_panel.cfg = self.cfg
            self.catalog_panel.refresh()
        elif index == SUPPORT:
            # The assistant runs on the customer's own planning key, and a
            # copy taken at launch would miss a key they saved thirty seconds
            # ago — which is exactly when somebody opens the help screen.
            self.support_panel.cfg = self.cfg
        # The rail highlights the screen we actually landed on, not the name we
        # were asked for — an unknown key falls back to HOME above. Before
        # this, every screen but Home passed "", which set_current() ignored,
        # so the rail sat permanently lit on Home wherever you actually were:
        # the app could never tell you where you are.
        self.sidebar.set_current(SCREEN_NAME.get(index, "home"))

    # ── licence ─────────────────────────────────────────────────────────────
    def _licence_banner(self) -> QWidget:
        self.banner = QFrame()
        self.banner.setObjectName("licenceBanner")
        self.banner.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self.banner)
        row.setContentsMargins(20, 9, 14, 9)
        row.setSpacing(10)
        self._banner_icon = QLabel()
        row.addWidget(self._banner_icon)
        self._banner_text = QLabel()
        self._banner_text.setWordWrap(True)
        row.addWidget(self._banner_text, stretch=1)
        # One row, two buttons. The main one is re-labelled per banner (the
        # licence key by default, Download for an update); the quiet second
        # one exists only for the update banner's "Not now" and stays hidden
        # otherwise. Both dispatch through a stored callable rather than
        # reconnecting `clicked` on every repaint — a signal connected twice
        # opens two dialogs, and refresh_licence_ui runs on a timer.
        self._banner_action = None
        self._banner_alt_action = None
        self._banner_alt = QPushButton("Not now")
        self._banner_alt.setObjectName("smallBtn")
        self._banner_alt.setCursor(Qt.PointingHandCursor)
        self._banner_alt.clicked.connect(self._banner_alt_clicked)
        self._banner_alt.setVisible(False)
        row.addWidget(self._banner_alt)
        self._banner_btn = QPushButton("Enter a licence key")
        self._banner_btn.setObjectName("smallBtn")
        self._banner_btn.setCursor(Qt.PointingHandCursor)
        self._banner_btn.clicked.connect(self._banner_clicked)
        row.addWidget(self._banner_btn)
        self.banner.setVisible(False)
        return self.banner

    def _banner_clicked(self):
        (self._banner_action or self._open_license_dialog)()

    def _banner_alt_clicked(self):
        if self._banner_alt_action is not None:
            self._banner_alt_action()

    def refresh_licence_ui(self):
        """Repaint everything that depends on the licence: the banner, the
        locks in the rail, and the idle status message. That last one used to
        be a hardcoded "Ready." set once in _build_ui — which stayed on
        screen, unchanged, underneath a banner saying new work was paused.
        `usable` is the same flag the rest of the licence gate goes by, so the
        status bar never again claims something the banner just denied.
        Called at startup and after any licence change."""
        state = licensing.state()
        self.sidebar.set_entitlements(state.features, state.usable)
        title, detail = self._plan_summary(state)
        self.sidebar.set_plan(title, detail, state.usable)
        self.sidebar.set_profile(identity.display_name(self.cfg))
        if state.usable:
            self.statusBar().showMessage("Ready.")
        else:
            self.statusBar().clearMessage()

        if state.status == licensing.VALID:
            # A healthy licence frees the banner for the other things worth
            # interrupting someone about, in this order:
            #
            #   1. the server has stopped leasing to this build — new work is
            #      already refused, so this outranks everything below;
            #   2. their work is no longer reaching the shared folder, so
            #      their manager cannot see it;
            #   3. a newer Prism exists. Advisory, dismissible per version,
            #      and last — a nudge must never sit on top of a problem.
            if updater.required(state):
                wanted = updater.target(state)
                self._show_banner(
                    i18n.t("This version of Prism can no longer start new "
                           "work. Update to Prism {version} to continue — "
                           "History and everything you've made are still "
                           "here.").format(version=wanted),
                    theme.ERR_INK, "alert",
                    action=("Download update", self._open_download))
                return
            offline = workspace.unreachable(self.cfg)
            if offline:
                self._show_banner(offline, theme.WARN_INK, "alert")
                return
            waiting = getattr(self, "_ready_update", None)
            if waiting is not None and not updater.dismissed(waiting.version):
                self._show_banner(
                    i18n.t("Prism {version} is ready. Restart to finish "
                           "updating — everything you've made stays right "
                           "where it is.").format(version=waiting.version),
                    theme.INFO_INK, "arrow-up",
                    action=("Restart now", self._apply_ready_update),
                    alt=("Later", self._later_ready_update))
                return
            newer = updater.available(state)
            if newer and not updater.dismissed(newer):
                self._show_banner(
                    i18n.t("Prism {version} is available. You have "
                           "{current}.").format(version=newer,
                                                current=app_meta.VERSION),
                    theme.INFO_INK, "arrow-up",
                    action=("Download", self._open_download),
                    alt=("Not now", lambda: self._dismiss_update(newer)))
                return
            self.banner.setVisible(False)
            return

        if (state.status in (licensing.STALE, licensing.GRACE)
                and not licensing.refresh_settled()):
            # The renewal launched at startup has not answered yet, so there is
            # nothing true to say about the server. Say nothing; the early
            # repaints below pick it up the moment it lands.
            self.banner.setVisible(False)
            return

        if state.status == licensing.STALE and state.usable:
            tone, icon_name = theme.NEUTRAL[600], "clock"
            days = state.stale_days_left
            text = ("Prism couldn't reach the licence server just now. "
                    f"Everything keeps working for about {days} more "
                    f"day{'s' if days != 1 else ''} — check this computer's "
                    "internet connection if this stays.")
            # Already activated and still working: a key prompt here asks a
            # paying customer to redo something they have done.
            self._show_banner(text, tone, icon_name, button=False)
            return
        elif state.status == licensing.STALE:
            tone, icon_name = theme.NEUTRAL[600], "clock"
            text = ("Prism hasn't been able to reach the licence server for a "
                    "week. New work is paused until it can — History and "
                    "everything you've already made are still here.")
        elif state.status == licensing.GRACE:
            tone, icon_name = theme.NEUTRAL[600], "clock"
            days = max(state.days_left + state.grace_days, 0)
            text = (f"Prism couldn't confirm your licence. It keeps working for "
                    f"about {days} more day{'s' if days != 1 else ''} — check "
                    f"this computer's internet connection.")
            self._show_banner(text, tone, icon_name, button=False)
            return
        elif state.status == licensing.TAMPERED:
            tone, icon_name = theme.ERR_INK, "lock"
            text = (state.message
                    or "Prism can't verify this computer's licence.")
        else:                                   # EXPIRED or NONE
            tone, icon_name = theme.ERR_INK, "lock"
            text = ("Your licence has ended. History and everything you've "
                    "already made are still here — new runs are paused until "
                    "it's renewed.")
        self._show_banner(text, tone, icon_name)

    @staticmethod
    def _plan_summary(state) -> tuple[str, str]:
        """Two lines for the rail's licence card: what you have, and whether
        it is working.

        Deliberately not the banner's text. The banner interrupts and explains;
        this is a standing label that has to stay true in every state and fit
        on two short lines, so it says the plan name and one clause about it.
        """
        plan = (state.plan or "").strip()
        title = i18n.t("{plan} plan").format(plan=plan) if plan else i18n.t("Licence")
        if state.status == licensing.VALID:
            days = getattr(state, "days_left", 0)
            if 0 < days <= 14:
                return title, i18n.t("Renews in {n} days").format(n=days)
            return title, i18n.t("Your licence is active")
        return title, {
            licensing.STALE: i18n.t("Can't reach the licence server"),
            licensing.GRACE: i18n.t("Couldn't confirm — still working"),
            licensing.TAMPERED: i18n.t("Can't be verified on this computer"),
            licensing.EXPIRED: i18n.t("Ended — renew to start new work"),
        }.get(state.status, i18n.t("No licence yet"))

    def _show_banner(self, text: str, tone: str, icon_name: str,
                     action: tuple | None = None, alt: tuple | None = None,
                     button: bool = True):
        """`action` is (label, callable) for the banner's button; the default
        is the licence-key dialog, which every licence banner wants. `alt` is
        an optional second, quieter (label, callable) — the update banner's
        "Not now" — and is hidden when absent. `button=False` hides the
        button altogether, for a notice the customer has nothing to act on."""
        label, fn = action or ("Enter a licence key", self._open_license_dialog)
        self._banner_btn.setText(label)
        self._banner_btn.setVisible(button)
        self._banner_action = fn
        if alt:
            self._banner_alt.setText(alt[0])
            self._banner_alt_action = alt[1]
        else:
            self._banner_alt_action = None
        self._banner_alt.setVisible(bool(alt))
        self._banner_icon.setPixmap(icons.pixmap(icon_name, 16, "#ffffff"))
        self._banner_text.setText(text)
        self._banner_text.setStyleSheet("color: #f1f5f9; font-size: 13px;")
        self.banner.setStyleSheet(
            "QFrame#licenceBanner { background: rgba(18, 20, 26, 0.85);"
            "border-bottom: 1px solid rgba(255, 255, 255, 0.12); }")
        self.banner.setVisible(True)

    # ── updates (Phase 1: a real in-app download+install, see updater.py) ──
    def _open_download(self):
        """Try the real in-app update first; fall back to the fixed download
        page whenever Phase 1 can't run — running from source, no verified
        manifest available, or anything in between failing. The fallback is
        never a worse outcome than Phase 0's status quo, only ever the same
        one, so trying Phase 1 first costs nothing.
        """
        if not paths.is_frozen():
            self._open_download_fallback()
            return
        if getattr(self, "_ready_update", None) is not None:
            self._apply_ready_update()      # already downloaded and verified
            return
        self._download_progress = LoadingDialog(
            i18n.t("Update"), i18n.t("Checking for an update…"), True, self)

        def moved(done: int, total: int):
            box = self._download_progress
            if box.wasCanceled():
                return
            if total:
                box.setMaximum(total)
                box.setValue(done)
                box.setLabelText(i18n.t("Downloading update… {done}/{total} "
                                        "files").format(done=done, total=total))
            else:
                box.setMaximum(0)

        def staged(update):
            self._download_progress.close()
            answer = QMessageBox.question(
                self, i18n.t("Update"),
                i18n.t("Prism {version} is ready to install. Restart now to "
                       "finish updating — everything you've made stays "
                       "right where it is.").format(version=update.version),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                return
            try:
                updater.begin_apply(update, updater.install_dir())
            except Exception:                       # noqa: BLE001
                self._explain(i18n.t(
                    "Couldn't start the update. Try the download page "
                    "instead."), "run")
                return
            QApplication.instance().quit()

        def none_available():
            # The banner said a newer version exists (Phase 0's advisory,
            # unsigned string from the licence lease); Phase 1's own signed
            # manifest disagreed, is missing, or is for a version this
            # machine already has — any of those means "nothing this flow
            # can safely act on", not "something is wrong".
            self._download_progress.close()
            self._open_download_fallback()

        def broke(_message: str):
            self._download_progress.close()
            self._open_download_fallback()

        worker = UpdateWorker()
        worker.progress.connect(moved)
        worker.staged.connect(staged)
        worker.none.connect(none_available)
        worker.failed.connect(broke)
        self._workers.append(worker)
        self._download_progress.show()
        worker.start()

    def _open_download_fallback(self):
        """Phase 0's original behaviour: send them to the fixed download
        page. The browser, not the app — nothing is fetched or run here."""
        try:
            QDesktopServices.openUrl(QUrl(updater.download_url()))
        except Exception:                          # noqa: BLE001
            pass

    def _dismiss_update(self, version: str):
        """"Not now" — for THIS version. A newer one brings the banner back."""
        updater.dismiss(version)
        self.refresh_licence_ui()

    def _open_license_dialog(self, mode: str = "change"):
        from dialogs.license_dialog import LicenseDialog
        LicenseDialog(self, mode=mode).exec()
        licensing.reload()
        self.refresh_licence_ui()

    def _work_column(self) -> QWidget:
        self.input_panel = InputPanel()
        self.agents_panel = AgentsPanel()
        self.output_panel = OutputPanel()

        # -- page 0: compose ------------------------------------------------
        compose_inner = QWidget()
        compose = QVBoxLayout(compose_inner)
        compose.setContentsMargins(0, 0, 0, 0)
        compose.setSpacing(18)
        compose.addWidget(self.input_panel)
        # THE void. This used to be `addWidget(agents_panel)` followed by
        # `addStretch(1)`, and that stretch was the single biggest piece of
        # dead space in the product: both panels sat at stretch 0, so the
        # stretch item absorbed every spare pixel of window height into one
        # grey band — sitting exactly between the plan and its own Start
        # button, which is pinned to the foot of the column below it.
        #
        # Giving the height to the plan instead is the whole fix. AgentsPanel
        # is Expanding and keeps exactly one stretch-1 item of its own: the
        # centring empty state when there is no plan, an inert tail spacer
        # when there is.
        compose.addWidget(self.agents_panel, stretch=1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(compose_inner)

        # -- the stack ------------------------------------------------------
        self.work_stack = QStackedWidget()
        self.work_stack.addWidget(scroll)             # COMPOSE
        self.work_stack.addWidget(self.output_panel)  # RUNNING

        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        # "Start the work" / "Discard" are pinned to the foot, outside the
        # scroll. Lumi's edge button rests above a footer row
        # (theme.LUMI_REST_FROM_BOTTOM), so no room is reserved for it here.
        layout.setContentsMargins(40, 32, 40, 32)
        layout.setSpacing(20)
        layout.addWidget(self._workbench_header())
        layout.addWidget(self.work_stack, stretch=1)
        # Lifted out of the scrolling column and pinned to its foot. Prism's
        # full pipeline is nine stages, and with nine plan cards on screen
        # "Start the work" sat well below the fold — the one action the screen
        # exists for was the one thing you had to go looking for. The design
        # only ever had to lay out four.
        #
        # addWidget reparents on its own. Do NOT setParent(None) first: that
        # makes the row a top-level widget, and anything that shows it before
        # it lands here pops it up as a floating "Prism" window with its own
        # title bar.
        layout.addWidget(self.agents_panel.cta)
        # Only on the compose page: the running page has its own Stop control,
        # and a Start button under a run in progress invites starting it twice.
        self.work_stack.currentChanged.connect(
            lambda i: self.agents_panel.cta.setVisible(
                i == COMPOSE and bool(self.agents_panel.selected_agents())))
        return wrap

    def _workbench_header(self) -> QWidget:
        """"New task", and the 1 Describe → 2 Plan → 3 Run breadcrumb.

        The breadcrumb is the design's answer to a complaint the old workbench
        earned honestly: the compose card and the results page looked like two
        unrelated screens, and nothing said the plan step sat between them or
        that you could go back to it. Three labels and two chevrons make the
        whole shape of the job visible before any of it has happened.
        """
        crumbs_w = QWidget()
        crumb = QHBoxLayout(crumbs_w)
        crumb.setContentsMargins(0, 0, 0, 0)
        crumb.setSpacing(6)
        self._steps_crumb = {}
        for i, (key, label) in enumerate((("describe", i18n.t("Describe")),
                                          ("plan", i18n.t("Plan")),
                                          ("run", i18n.t("Run")))):
            if i:
                sep = QLabel()
                sep.setPixmap(icons.pixmap("chevron-right", 12,
                                           theme.NEUTRAL[400], stroke=2))
                crumb.addWidget(sep)
            step = QLabel(f"{i + 1} {label}")
            step.setObjectName("stepOff")
            self._steps_crumb[key] = step
            crumb.addWidget(step)

        hdr = C.SectionHeader(i18n.t("New task"), "", [crumbs_w])
        self._set_stage("describe")
        return hdr

    def _ask_display_name(self):
        """Let a solo copy say who it belongs to.

        Stored in config rather than in the licence store, because it is a
        preference and not a claim: a member whose name arrives inside a signed
        designation key keeps that one, and identity.display_name() prefers it.
        """
        from PySide6.QtWidgets import QInputDialog
        current = identity.display_name(self.cfg)
        name, ok = QInputDialog.getText(
            self, i18n.t("Your name"),
            i18n.t("What should Prism call you? This appears on the rail and "
                   "on Home, and stays on this computer."),
            text=current)
        if not ok:
            return
        self.cfg["display_name"] = (name or "").strip()
        CB.config.save(self.cfg)
        self.sidebar.set_profile(identity.display_name(self.cfg))
        self.settings_panel.cfg = self.cfg
        self.settings_panel.refresh()
        self.home_panel.refresh()

    def _start_tour(self):
        """Run the six-step tour, from Home so every step has something to
        point at. Created lazily — most sessions never ask for it."""
        self._show_screen("home")
        if getattr(self, "_tour", None) is None:
            self._tour = TourOverlay(self)
        # restart(), not start(): tour_requested only fires on a
        # deliberate click from Settings, and someone asking for the
        # tour again wants the tour, not the two steps they had left.
        self._tour.restart()

    def _push_active_run(self, stage: str, agent: str):
        """Mirror the live run onto Home's Active runs section.

        Home is a report on what the app is doing, so a run in flight has to
        appear there — otherwise someone who navigated to Home mid-run sees a
        dashboard claiming nothing is happening while a browser is being driven
        behind it.
        """
        from widgets.agents_panel import STAGE_COPY
        planned = list(self.agents_panel.selected_agents().items())
        if not planned:
            planned = [(stage, agent)]
        stages = [(tool, STAGE_COPY.get(key, ("", key.title(), ""))[1])
                  for key, tool in planned]
        keys = [k for k, _ in planned]
        position = keys.index(stage) + 1 if stage in keys else 1
        self.home_panel.set_active([{
            "title": (getattr(self, "_last_query", "") or "").strip()
                     or i18n.t("Untitled task"),
            "stages": stages,
            "fraction": position / max(1, len(keys)),
            "note": i18n.t("{tool} is on “{step}”…").format(
                tool=agent,
                step=STAGE_COPY.get(stage, ("", stage.title(), ""))[1]),
            "started": i18n.t("Step {n} of {total}").format(
                n=position, total=len(keys)),
            "hue": theme.WARN,
        }])

    def _clear_active_run(self):
        self.home_panel.set_active([])

    def _set_stage(self, stage: str):
        """Light the current step in the breadcrumb."""
        for key, label in getattr(self, "_steps_crumb", {}).items():
            label.setObjectName("stepCur" if key == stage else "stepOff")
            label.style().unpolish(label)
            label.style().polish(label)

    def _context_column(self) -> QWidget:
        """The files/prompt rail, which now collapses to a 44px strip.

        It used to be a permanent 272px column, and on a fresh install its
        entire content was "Nothing attached yet" — a fifth of the window
        spent saying nothing. The design collapses it to a strip you can click
        open, and it expands itself the moment a file is actually attached,
        which is the only time it has anything to report.
        """
        self.files_panel = FilesPanel()

        self.context_rail = QFrame()
        self.context_rail.setObjectName("contextRail")
        self.context_rail.setStyleSheet(
            "QFrame#contextRail { border: none; background: transparent; }")
        outer = QVBoxLayout(self.context_rail)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._context_outer = outer

        # -- collapsed: a chevron and a folder glyph -------------------------
        self._context_strip = QWidget()
        strip = QVBoxLayout(self._context_strip)
        strip.setContentsMargins(0, 20, 0, 0)
        strip.setSpacing(14)
        open_btn = QPushButton()
        open_btn.setFlat(True)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setToolTip(i18n.t("Show the files you mentioned"))
        open_btn.setFixedSize(28, 28)
        open_btn.setStyleSheet("border: none; background: transparent;")
        icons.button_icon(open_btn, "chevron-left", 17, theme.NEUTRAL[500])
        open_btn.clicked.connect(lambda: self._set_context_open(True))
        strip.addWidget(open_btn, alignment=Qt.AlignHCenter)
        self._context_count = QLabel()
        self._context_count.setAlignment(Qt.AlignHCenter)
        self._context_count.setPixmap(
            icons.pixmap("folder", 17, theme.NEUTRAL_350))
        strip.addWidget(self._context_count, alignment=Qt.AlignHCenter)
        strip.addStretch(1)
        outer.addWidget(self._context_strip)

        # -- expanded --------------------------------------------------------
        self._context_body = C.Card(radius=18)
        layout = self._context_body.body((16, 18, 16, 18), spacing=16)
        head = QHBoxLayout()
        head.addWidget(kicker(i18n.t("Files you mentioned")), stretch=1)
        shut = QPushButton()
        shut.setFlat(True)
        shut.setCursor(Qt.PointingHandCursor)
        shut.setToolTip(i18n.t("Hide this panel"))
        shut.setFixedSize(22, 22)
        shut.setStyleSheet("border: none; background: transparent;")
        icons.button_icon(shut, "chevron-right", 15, theme.NEUTRAL[500])
        shut.clicked.connect(lambda: self._set_context_open(False))
        head.addWidget(shut)
        layout.addLayout(head)
        layout.addWidget(self.files_panel)
        layout.addStretch(1)

        tip = QLabel(i18n.t("Tip.  Click any step to leave it out, or click "
                            "its tool chip to run that step somewhere else."))
        tip.setObjectName("note")
        tip.setWordWrap(True)
        layout.addWidget(tip)
        outer.addWidget(self._context_body)

        # False, not None: a fresh window has nothing attached, so the rail
        # starts shut but has not been shut *by anyone* — the first attachment
        # is still allowed to open it.
        self._context_user_shut = False
        self._set_context_open(False)
        self._context_user_shut = False
        return self.context_rail

    def _set_context_open(self, open_: bool):
        self._context_body.setVisible(open_)
        self._context_strip.setVisible(not open_)
        self.context_rail.setFixedWidth(296 if open_ else 44)
        if hasattr(self, "_context_outer"):
            self._context_outer.setContentsMargins(6, 6, 6, 6) if open_ else self._context_outer.setContentsMargins(0, 0, 0, 0)
        self._context_user_shut = not open_

    def _sync_context_rail(self):
        """Open the rail the first time something is attached; leave it alone
        after that.

        Auto-opening every time would fight anyone who deliberately shut it —
        attaching a second file would reopen a panel they just closed. So the
        rail opens on the transition from nothing-attached to something, and
        respects the close from then on.
        """
        has = bool(self.attachments) or bool(self.pending_mentions)
        if has and not self._context_body.isVisible() and not self._context_user_shut:
            self._set_context_open(True)
        # The collapsed strip carries the count, so a shut rail still says
        # whether Prism is holding anything.
        self._context_count.setPixmap(icons.pixmap(
            "folder", 17,
            theme.ACCENT if has else theme.NEUTRAL_350))
        self._context_count.setToolTip(
            i18n.t("{n} attached").format(n=len(self.attachments)) if has
            else i18n.t("Nothing attached yet"))

    def _wire(self):
        self.sidebar.command_triggered.connect(self._handle_command)
        self.sidebar.favorite_chosen.connect(self._attach_path)
        self.sidebar.wakeword_toggled.connect(self.toggle_wakeword)
        self.sidebar.tour_requested.connect(self._start_tour)

        self.input_panel.route_clicked.connect(self._route)
        self.input_panel.cancel_route_clicked.connect(self._cancel_route)
        self.input_panel.mic_toggle_clicked.connect(self._toggle_mic)
        self.input_panel.attach_file_clicked.connect(self._attach_file_dialog)
        self.input_panel.attach_folder_clicked.connect(self._attach_folder_dialog)
        self.input_panel.detach_requested.connect(self._detach)
        self.input_panel.detach_folder_requested.connect(self._detach_folder)
        self.input_panel.attachment_activated.connect(
            lambda p: QDesktopServices.openUrl(QUrl.fromLocalFile(p)) if p else None)
        self.input_panel.queue_changed.connect(self._on_queue_changed)

        self.files_panel.mention_accepted.connect(self._accept_mention)
        self.files_panel.mention_change_requested.connect(self._change_mention)
        self.files_panel.detach_requested.connect(self._detach)
        self.files_panel.detach_folder_requested.connect(self._detach_folder)
        self.files_panel.detach_all_requested.connect(self._detach_all)

        self.agents_panel.run_requested.connect(self._run_pipeline)
        self.output_panel.back_requested.connect(self._back_to_plan)
        self.output_panel.stop_requested.connect(self._stop_run)
        self.output_panel.skip_requested.connect(self._skip_step)
        self.output_panel.fallback_requested.connect(self._use_fallback)
        self.output_panel.edit_reel.connect(self._edit_reel_layout)
        self.artifacts_panel.edit_reel.connect(self._edit_reel_layout)
        self.reel_edits_saved.connect(self._on_reel_edits_saved)
        self.reel_edits_rendered.connect(self._on_reel_edits_rendered)
        self.reel_refine_requested.connect(self._on_reel_refine_requested)
        self._reel_edit_stop = None
        self._reel_edit_ctx = None          # {"spec":…, "spec_path":…}
        self._reel_edit_worker = None
        self.agents_panel.discard_requested.connect(self._discard_plan)

    # ── moving between the two pages ────────────────────────────────────────
    def _back_to_plan(self):
        """Leaving the results page. A run that finished has consumed its
        plan — every step in it has already been done, so handing it back
        with Start the work still armed invites re-running the whole thing by
        accident. Wipe it and start clean. A run that FAILED keeps its plan:
        there, retrying is the point."""
        if self._run_finished:
            self._reset_for_new_task()
        self.work_stack.setCurrentIndex(COMPOSE)

    def _reset_for_new_task(self, keep_attachments: bool = False):
        """Back to a blank workbench. After a finished run the attachments go
        too (they belonged to that journey); Discard passes keep_attachments
        because its own dialog promises "Files you've attached stay attached" —
        they are explicit choices sitting visibly in the rail with their own
        Detach button, and the next task usually concerns the same files."""
        self._run_finished = False
        self._set_stage("describe")
        self.routing = None
        self._last_query = ""
        self._current_run_file = None
        self._is_followup_run = False
        self._followup_session = None
        self._followup_text = ""
        getattr(CB.config, "reset_run", lambda: None)()
        self._stage_agents = {}
        self._stage_results = []
        self._run_shortfall = []
        self.pending_mentions = []
        # The queue belongs to the journey that just ended, not the next one.
        self._task_queue = []
        self._task_pos = 0
        self._task_runs = []
        self._queue_stopped = False
        self._auto_run = False
        if not keep_attachments:
            self.attachments = []
        self.files_panel.set_attached(self.attachments)
        self.input_panel.reset()
        # The chips and the "Working from" list are drawn FROM the attachments;
        # clearing them while keeping the list left files attached but hidden,
        # which the first version of this did (seen in the real window, 1 Oct).
        self.input_panel.set_context(self.attachments)
        self.agents_panel.clear()
        self.files_panel.clear_mentions()
        self.output_panel.set_finished(False)
        self.statusBar().showMessage("Ready for the next one.", 4000)

    def _on_queue_changed(self, count: int):
        if count:
            self.statusBar().showMessage(
                f"{count} task{'s' if count != 1 else ''} queued. Add more, or "
                "Show steps to start the first one.", 5000)

    # ── sidebar commands ─────────────────────────────────────────────────────
    def _open_settings(self, section: str = "licence"):
        """Open Settings as a centred modal without navigating away.

        The screen underneath remains the user's context.  While the dialog
        is open, the rail marks Settings as active; closing it restores the
        highlight for the page that was already there.
        """
        self.settings_panel.cfg = self.cfg
        # A modal should separate its work from the workspace without taking
        # it away.  This gives the background the quiet, recessed treatment
        # of the reference while keeping it recognisably in place underneath.
        central = self.centralWidget()
        if central is not None:
            self._settings_dim = QGraphicsOpacityEffect(central)
            self._settings_dim.setOpacity(0.48)
            central.setGraphicsEffect(self._settings_dim)
        self.sidebar.set_current("config")
        self.settings_panel.open_section(section)
        # Settings starts life in the stack so the application's screen
        # registry stays backwards compatible.  Its first modal open promotes
        # it to a top-level dialog, which removes that widget from the stack.
        # Put an inert slot straight back at index 3: otherwise every later
        # index shifts left and Support (9) becomes Gerber (10's old slot).
        if self.screens.count() < len(SCREENS):
            self._settings_stack_placeholder = QWidget()
            self.screens.insertWidget(SETTINGS,
                                      self._settings_stack_placeholder)

    def _close_settings(self, _result=0):
        """Restore the underlying page and its rail state after dismissal."""
        central = self.centralWidget()
        if central is not None:
            central.setGraphicsEffect(None)
        self.sidebar.set_current(SCREEN_NAME.get(
            self.screens.currentIndex(), "home"))

    def _navigate_from_settings(self, key: str):
        """A Settings door (Help, History, &c.) replaces the modal."""
        self.settings_panel.reject()
        self._handle_command(key)

    def _on_home_task_submitted(self, text: str, paths: list):
        for p in paths:
            self._attach_path(p)
        if text:
            self.input_panel.set_query_text(text)
        self._handle_command("workbench")

    def _handle_command(self, key: str):
        if key == "home":
            self._show_screen("home")
        elif key == "workbench":
            # If Home had text or attachments, transfer them over
            if hasattr(self, "home_panel"):
                home_text = self.home_panel.get_prompt_text()
                home_paths = self.home_panel.get_attachments()
                for p in home_paths:
                    self._attach_path(p)
                self.home_panel.clear_attachments()
                if home_text:
                    self.input_panel.set_query_text(home_text)
                    self.home_panel.clear_prompt()
            # "New task" clears the bench; Home → "Describe a task" lands on
            # whatever is already there, because someone who came back to
            # finish a sentence has not asked to lose it.
            if self.work_stack.currentIndex() == RUNNING and self._run_finished:
                self._reset_for_new_task()
            self.work_stack.setCurrentIndex(COMPOSE)
            self._show_screen("workbench")
        elif key == "catalog":
            self._show_screen("catalog")
        elif key == "reel":
            self._open_reel()
        elif key == "motion":
            self._open_motion()
        elif key == "whatsapp":
            self._open_whatsapp()
        elif key == "guide":
            self._show_screen("guide")
        elif key == "support":
            self._open_lumi()
        elif key == "tour":
            self._start_tour()
        elif key in ("agents", "profile", "key", "chrome", "licence",
                     "language", "team", "config", "status"):
            # Every settings shortcut opens the matching section in the
            # focused modal. The workspace behind it stays put, so closing
            # Settings returns a person to exactly what they were doing.
            self._open_settings(
                {"team": "profile", "key": "agents",
                 "chrome": "status", "config": "licence"}.get(key, key))
        elif key == "login":
            self._open_login_tabs()
        elif key == "runs":
            self._show_screen("runs")
        elif key == "artifacts":
            self._show_screen("artifacts")
        elif key == "email":
            self._open_email()
        elif key == "boq":
            self._open_boq()
        elif key == "bom":
            self._open_bom()
        elif key == "gerber":
            self._open_gerber()
        elif key == "step":
            self._open_step()
        elif key == "leads":
            self._open_leads()
        elif key == "inquiry":
            self._open_inquiry()

    def _authorized_then(self, feature: str, action: str, then):
        """Ask the licence server, then run `then()` if it said yes.

        Off the UI thread: it is a network round trip behind a click, and a
        frozen window reads as a crash. The cached `require()` check runs
        first as a fast path so an add-on the customer plainly does not own
        opens the pitch instantly instead of after a round trip.
        """
        if not licensing.require(feature, self):
            return
        self.statusBar().showMessage("Checking your licence…")

        def proceed(auth):
            self.statusBar().clearMessage()
            if not auth.allowed:
                if auth.code == "FEATURE_NOT_LICENSED":
                    licensing.require(feature, self)     # show the pitch
                else:
                    QMessageBox.warning(self, "Licence", auth.message)
                return
            then()

        worker = AuthorizeWorker(feature, action)
        worker.done.connect(proceed)
        self._workers.append(worker)
        worker.start()

    def _open_reel(self):
        self._authorized_then("reel", "addon", self._open_reel_dialog)

    def _open_reel_dialog(self):
        ok, err = CB.reel_available()
        if not ok:
            # FFmpeg specifically is something Prism can fix by itself, so it
            # gets an offer rather than an apology. Everything else missing
            # here (Pillow) is a broken install and needs a person.
            if "ffmpeg" in err.lower():
                self._offer_ffmpeg(then=self._open_reel_dialog)
                return
            QMessageBox.information(self, i18n.t("Reel"), err)
            return
        ReelDialog(self.cfg, [], self).exec()

    def _open_motion(self):
        # Same licence feature as Reel/Studio — Motion is the same "media"
        # capability tier, not a separate purchase, matching AGENT_FEATURES'
        # existing "Prism Reel"/"Prism Studio" -> "reel" mapping.
        self._authorized_then("reel", "addon", self._open_motion_dialog)

    def _open_motion_dialog(self):
        ok, err = CB.motion_available()
        if not ok:
            if "ffmpeg" in err.lower():
                self._offer_ffmpeg(then=self._open_motion_dialog)
                return
            QMessageBox.information(self, "Motion Graphics", err)
            return
        MotionDialog(self.cfg, [], self).exec()

    def _open_whatsapp(self):
        # WhatsApp is a rail add-on now, like Gerber/BOM/STEP -- see
        # addons/whatsapp/addon.py. The rail click lands on its front door;
        # the front door's own button (whatsapp_panel.opened) is what reaches
        # the dialog.
        self._authorized_then("marketing", "addon",
                              lambda: self._show_screen("whatsapp"))

    def _open_whatsapp_dialog(self):
        WhatsAppDialog(self.cfg, self).exec()

    def _offer_ffmpeg(self, then=None):
        """Offer to fetch FFmpeg, then carry on with what they were doing.

        Windows does not ship FFmpeg and nobody installs it by accident, so
        before this the first Windows customer to press Reel was handed a
        codec install guide. A build now bundles it; this is the path for a
        build that somehow did not, and for anyone running from source.
        """
        answer = QMessageBox.question(
            self, i18n.t("Reel"),
            i18n.t("Making a video needs FFmpeg, a free standard program "
                   "that isn't part of Prism.\n\nPrism can download and set "
                   "it up for you — about 30 MB, roughly a minute, and it "
                   "only happens once.\n\nDownload it now?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return

        box = LoadingDialog(i18n.t("Reel"), i18n.t("Downloading FFmpeg…"),
                            False, self)      # a half-written binary helps nobody
        box.setMaximum(100)
        box.setValue(0)
        box.show()

        def moved(done: int, total: int):
            if total:
                box.setMaximum(100)
                box.setValue(int(100 * done / total))
            else:
                # No content-length. Show motion rather than a bar stuck at 0.
                box.setMaximum(0)
            box.setLabelText(i18n.t("Downloading FFmpeg… {mb} MB").replace(
                "{mb}", f"{done / 1e6:.0f}"))

        def finished(_path: str):
            box.close()
            self.statusBar().showMessage(
                i18n.t("FFmpeg is ready. Video will work from now on."), 6000)
            if then:
                then()

        def broke(message: str):
            box.close()
            self._explain(message, "run")

        worker = FFmpegWorker()
        worker.progress.connect(moved)
        worker.done.connect(finished)
        worker.failed.connect(broke)
        self._workers.append(worker)
        worker.start()

    def _open_inquiry(self):
        # The redesign lands this on a screen rather than straight in the
        # dialog: the first thing you want on opening it is the state of the
        # book, not a working modal. The gate is unchanged and still runs
        # first — the screen reads a register the customer may not own.
        self._authorized_then("inbox", "addon",
                              lambda: self._show_screen("inquiry"))

    def _open_inquiry_setup(self):
        """Straight into setup from the screen's empty state.

        It used to route through the working dialog, which then opened setup
        itself — so "Set up Email inquiry automation" put three stacked windows on
        screen (the app, the inbox screen, and the setup sheet on top). The
        empty state's whole point is that there is nothing to work on yet, so
        the working screen in the middle has nothing to show.
        """
        from PySide6.QtWidgets import QDialog
        from addons.inquiry.setup import InquirySetupDialog
        dialog = InquirySetupDialog(self.cfg, self)
        if dialog.exec() == QDialog.Accepted:
            self.cfg = dialog.cfg
            CB.config.save(self.cfg)
            self.inquiry_panel.cfg = self.cfg
            self.inquiry_panel.refresh()
            self.home_panel.refresh()

    def _open_inquiry_dialog(self, tab: int = 0, auto_check: bool = False):
        """The working screen, opened on the tab the owner asked for — the
        launcher's "Quote them" lands on To quote, "Read the answer" on
        They answered, and so on. `auto_check` is set only for the front
        door's "Check my mail now" — see InquiryPanel.check_requested.

        Used to construct a fresh modal InquiryDialog and .exec() it; the
        screen is now built once (see _build_ui) and stays alive for the
        app's whole session, so opening it is just handing it the latest cfg
        and switching to it — enter() does what the constructor + exec used
        to do. Leaving it again (_show_screen) is what used to happen after
        .exec() returned: reload cfg, refresh the launcher behind it.
        """
        self.inquiry_work_panel.cfg = self.cfg
        self.inquiry_work_panel.enter(tab=int(tab or 0), auto_check=auto_check,
                                      view="auto")
        self.screens.setCurrentIndex(INQUIRY_WORK)
        self.sidebar.set_current("inquiry")

    def _open_boq(self):
        # Land on the front door, not straight in the dialog — same reasoning
        # as Inquiry: the rail switches screens everywhere else, and a modal
        # thrown from one rail item teaches nothing consistent. The gate still
        # runs first; the screen's button opens the working dialog.
        self._authorized_then("boq", "addon", lambda: self._show_screen("boq"))

    def _open_boq_dialog(self):
        # Dependency probe comes AFTER the licence check: a customer who
        # hasn't bought BOQ should be told that, not sent off to install ezdxf
        # for a feature they still won't be able to open.
        ok, err = CB.boq_available()
        if not ok:
            QMessageBox.information(
                self, "BOQ",
                "The BOQ add-on needs the ezdxf library to measure drawings:\n\n"
                "    pip install ezdxf\n\n"
                "A .dwg also needs a converter — install ODA File Converter "
                "(free, all platforms) from opendesign.com, or "
                "`brew install libredwg` on macOS. A .dxf needs neither."
                f"\n\nDetail: {err}")
            return
        dlg = BoqDialog(self.cfg, [], self)
        dlg.exec()
        if getattr(dlg, "owns_followup", False):
            return
        # A BOQ runs in its own dialog and never touches the main workbench's
        # completion path, so the post-completion follow-up was never offered
        # after one. Bridge it in now the dialog has closed: hand its finished
        # stages to the same refinement flow every routed run gets. The format
        # stage's query label doubles as the Artifacts task key, so "what came
        # back" shows the BOQ itself.
        task_name = getattr(dlg, "_task_name", "") or f"{dlg._doc} — {getattr(dlg, 'request', '')}"
        self._offer_followup_for_dialog(
            task_name,
            getattr(dlg, "_all_responses", {}),
            getattr(dlg, "_stage_agents_map", {}),
            getattr(dlg, "_links", {}),
            artifacts_dir=getattr(dlg, "_artifacts_dir", "") or CB.config.current_run_dir())

    def _open_bom(self):
        # Same front-door pattern as BOQ. Gated on the BOQ entitlement for now —
        # there is no dedicated "bom" feature on the licence server yet, exactly
        # like Gerber rides on "boq" (see the sidebar entry).
        self._authorized_then("boq", "addon", lambda: self._show_screen("bom"))

    def _open_bom_dialog(self):
        ok, err = CB.boq_available()
        if not ok:
            QMessageBox.information(
                self, "BOM",
                "The BOM add-on needs the ezdxf library to measure drawings:\n\n"
                "    pip install ezdxf\n\n"
                "A .dwg also needs a converter — install the free ODA File "
                f"Converter on Windows.\n\nDetail: {err}")
            return
        # Same dialog as BOQ, in BOM mode — it measures the drawing identically
        # and writes a parts list instead of a quantities schedule.
        dlg = BoqDialog(self.cfg, [], self, mode="bom")
        dlg.exec()
        if getattr(dlg, "owns_followup", False):
            return
        task_name = getattr(dlg, "_task_name", "") or f"{dlg._doc} — {getattr(dlg, 'request', '')}"
        self._offer_followup_for_dialog(
            task_name,
            getattr(dlg, "_all_responses", {}),
            getattr(dlg, "_stage_agents_map", {}),
            getattr(dlg, "_links", {}),
            artifacts_dir=getattr(dlg, "_artifacts_dir", "") or CB.config.current_run_dir())

    def _open_gerber(self):
        # Gerber is its own add-on since 2026-09-10 -- see addons/gerber/addon.py.
        self._authorized_then("gerber", "addon", lambda: self._show_screen("gerber"))

    def _open_gerber_dialog(self):
        # gerber_available() always succeeds — core.gerber has no hard
        # dependency, only an optional one (shapely, for track spacing) — so
        # unlike BOQ this is a defensive check rather than an expected
        # customer-facing message, and stays quiet on the happy path.
        ok, err = CB.gerber_available()
        if not ok:
            QMessageBox.information(
                self, "Gerber",
                f"The Gerber add-on could not load: {err}")
            return
        GerberDialog(self.cfg, [], self).exec()

    def _open_step(self):
        # STEP is its own add-on since 2026-09-10 -- see addons/step/addon.py.
        # It opens straight into its workbench: one screen for measuring,
        # asking, editing, the answer, the plan, the files and the history of
        # past runs. No popup windows stacked on top of each other.
        self._authorized_then("step", "addon", self._open_step_dialog)

    def _step_screen(self):
        """The STEP workbench, built the first time it is needed and kept —
        the same pattern as the Email inquiries screen."""
        if self.step_work is None:
            self.step_work = StepDialog(self.cfg, [], self.step_host,
                                        embedded=True)
            self.step_host.layout().addWidget(self.step_work)
            self.step_work.leave_requested.connect(
                lambda: self._show_screen("home"))
        return self.step_work

    def _open_step_dialog(self, paths=None, run: str = ""):
        # Unlike Gerber this has a hard dependency -- cadquery, which
        # carries OpenCascade -- so the message is a real customer-facing
        # one: the add-on cannot measure anything without it.
        ok, err = CB.step_available()
        if not ok:
            QMessageBox.information(
                self, "STEP",
                "The STEP add-on needs the cadquery library to read 3D "
                "models:\n\n    pip install cadquery\n\n"
                f"Detail: {err}")
            return
        screen = self._step_screen()
        screen.cfg = self.cfg
        screen.enter()
        self.screens.setCurrentIndex(STEP_WORK)
        self.sidebar.set_current("step")
        if run:
            screen.load_run(run)
        elif paths:
            screen._on_files_added(list(paths))
        # Deliberately NOT offering the ordinary routed-pipeline follow-up
        # here (BOQ/BOM still do). STEP's own answer window is the one place
        # a follow-up can actually become a file (it calls apply_plan); the
        # generic one only ever saved a refined TEXT answer, so a customer
        # followed up there and no file appeared. One door, and it works.

    def _open_leads(self):
        # Front door first, like BOQ/Email: the rail switches screens, and the
        # screen's button opens the workbench. Gated on the "leads" feature.
        self._authorized_then("leads", "addon",
                               lambda: self._show_screen("leads"))

    def _open_leads_dialog(self):
        LeadsDialog(self.cfg, self).exec()
        # A run finished in the dialog must show on the screen behind it.
        self.leads_panel.refresh()

    def _open_email(self):
        self._authorized_then("email", "addon",
                               lambda: self._show_screen("email"))

    def _open_email_dialog(self, mode: str = "one"):
        if not email_config.can_send(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
            self.email_panel.cfg = self.cfg
        EmailComposeDialog(self.cfg, [], self,
                           mode=mode if isinstance(mode, str) else "one").exec()
        # A send that just went out must be on the screen behind the window.
        self.email_panel.refresh()

    def _open_email_setup(self):
        """The only door back into the sending-account setup once one is
        already configured — see EmailPanel.header_actions()."""
        dlg = EmailSetupDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.cfg
            self.email_panel.cfg = self.cfg
            self.email_panel.refresh()

    def _first_run(self):
        """A never-configured machine goes straight into the wizard - no
        blocking Welcome popup first. The wizard's own first page carries the
        explanation and a non-blocking link to the guide instead (see
        WizardPanel), so there's one flow, not a decision box in front of it.
        """
        if licensing.state().usable:
            self.wizard_panel.start(self.cfg)
            self.screens.setCurrentIndex(WIZARD)

    def _on_wizard_finished(self, cfg: dict):
        self.cfg = cfg
        self.settings_panel.cfg = cfg
        self.statusBar().showMessage("Setup saved.", 4000)
        self._handle_command("workbench")

    def _open_guide(self):
        """The guide, with its buttons wired back into the rail so reading
        about a thing and reaching it are the same gesture."""
        from dialogs.guide_dialog import GuideDialog
        dialog = GuideDialog(self)
        dialog.command_requested.connect(self._handle_command)
        dialog.exec()

    def _open_login_tabs(self):
        from widgets.login_tabs import open_login_tabs
        if open_login_tabs(self, CB.config.active_agents(self.cfg),
                           on_opened=lambda n: self.statusBar().showMessage(
                               i18n.t("Opened {n} login tab(s) in Chrome.").format(n=n),
                               4000)):
            self.statusBar().showMessage(
                i18n.t("Opening the login tabs in Chrome…"), 15000)

    def _show_status(self):
        agents = CB.config.active_agents(self.cfg)
        lines = [
            f"Profile: {self.cfg.get('profile') or '—'}",
            f"Groq key: {'set' if self.cfg.get('api_key') else 'NOT set'}",
            f"Chrome: {self.cfg.get('chrome_version') or 'auto-detect'}",
            "Agents:",
        ] + [f"  {cat}: {name}" for cat, name in agents.items()]
        QMessageBox.information(self, "Status", "\n".join(lines))

    def _history_dialog(self) -> "HistoryDialog":
        """History, wired to the two things a past run can still ask for:
        the reel editor, and a follow-up. (The menu entry used to open it
        unwired, so Edit the layout did nothing from there.)"""
        dialog = HistoryDialog(self)
        dialog.edit_reel.connect(self._edit_reel_layout)
        dialog.follow_up.connect(self._follow_up_from_history)
        return dialog

    def _show_runs(self):
        self._history_dialog().exec()

    def _follow_up_from_history(self, record: dict):
        """A follow-up on a past run, from its saved record.

        The record holds what a follow-up session is made of — the query,
        every stage's output, the tab each answered in, the tool that did
        each — so it goes through the same bridge an add-on dialog's run
        does. A Studio reel's saved design URL and mp4 make the reel branch
        work from here too. Older records saved no `agents`; the configured
        tool for each stage stands in.
        """
        responses = {k: v for k, v in (record.get("responses") or {}).items() if v}
        if not responses:
            return
        agents = {k: v for k, v in (record.get("agents") or {}).items() if v}
        if not agents:
            try:
                configured = CB.config.active_agents(self.cfg)
            except Exception:                           # noqa: BLE001
                configured = {}
            agents = {s: configured.get(s, "") for s in responses}
        target_path = record.get("_path") or record.get("path") or ""
        self._current_run_file = target_path or getattr(self, "_current_run_file", None)
        self._is_followup_run = True
        # The record is the truth here, not whatever ran last.
        self._followup_session = {
            "query": record.get("query", ""),
            "title": record.get("title", ""),
            "run_file": target_path,
            "responses": responses,
            "links": record.get("links") or {},
            "agents": agents,
            "artifacts_dir": record.get("artifacts") or "",
        }
        self._offer_followup_for_dialog(record.get("query", ""), responses,
                                        agents, record.get("links") or {},
                                        artifacts_dir=record.get("artifacts") or "")

    @staticmethod
    def _is_step_run(path: str) -> bool:
        """A run record written by the STEP add-on — it reopens in STEP's own
        screen, not in the generic history viewer."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return bool((json.load(f) or {}).get("step"))
        except (OSError, ValueError, AttributeError):
            return False

    def _open_run_record(self, path: str):
        """Open History on one particular run.

        The screen lists runs; the dialog is what knows how to re-render a
        stored record into readable output, so clicking a row hands that path
        over rather than duplicating the renderer.
        """
        if self._is_step_run(path):
            self._open_step_dialog(run=path)
            return
        dialog = self._history_dialog()
        runs = getattr(dialog, "runs", None)
        if runs is not None and path:
            norm_path = os.path.normpath(path)
            base_name = os.path.basename(norm_path)
            for i in range(runs.count()):
                item = runs.item(i)
                if item is not None:
                    item_path = os.path.normpath(item.data(1000) or "")
                    if item_path == norm_path or os.path.basename(item_path) == base_name:
                        runs.setCurrentRow(i)
                        break
        dialog.exec()

    # ── attachments ───────────────────────────────────────────────────────────
    def _explain(self, error: object, context: str = "") -> None:
        """Show a problem the way a first-time user needs to see it.

        Every failure the customer can meet goes through here rather than
        through a raw QMessageBox, so each one arrives as "here is what
        happened and here is what to do" — and so the technical text is
        logged even though it is not what fills the screen.

        The dialog can hand back an action, which is the difference between
        telling somebody to open Settings and taking them there.
        """
        from dialogs.problem_dialog import show_problem
        action = show_problem(self, error, context)
        if not action:
            return
        if action.startswith("settings:"):
            self._open_setup(focus=action.split(":", 1)[1])
        elif action == "login":
            self._open_login_tabs()
        elif action == "guide":
            self._open_guide()
        elif action == "support":
            self._show_screen("support")

    def _attach_path(self, path: str):
        """Take one file or folder into the run.

        The whole body is guarded, redrawing the panel included. It used to
        guard only the read: anything that went wrong while RENDERING the new
        row escaped the slot, Qt swallowed it, and the file appeared not to
        attach at all — no error, no row, nothing to go on. A failure here has
        to be visible, because an attachment silently not arriving is
        indistinguishable from a dead button.
        """
        if not path:
            return
        already = {a["path"] for a in self.attachments}
        try:
            if os.path.isdir(path):
                # Stamped with where they came from so the tray can show one
                # row for the folder and take the whole group back out again.
                # The engine still gets the flat list — it uploads files, not
                # folders — so this is presentation only.
                added = [{**a, "from_dir": path} for a in CB.files.attach_dir(path)]
                if not added:
                    self.statusBar().showMessage(
                        i18n.t("Folder contains no supported files to attach."), 4000)
                    return
            else:
                added = [CB.files.attach(path)]
        except Exception as e:                          # noqa: BLE001
            self._explain(e, "attach")
            return

        # Attaching a folder and then a file inside it used to queue the same
        # file twice, and every stage then uploaded it twice.
        fresh = [a for a in added if a["path"] not in already]
        if not fresh:
            self.statusBar().showMessage(
                i18n.t("Already attached."), 4000)
            return
        self.attachments.extend(fresh)
        try:
            self.files_panel.set_attached(self.attachments)
            self.input_panel.set_context(self.attachments)
            self._sync_context_rail()
        except Exception as e:                          # noqa: BLE001
            # The read succeeded; only the drawing failed. Say so rather than
            # letting the exception escape the slot, where Qt swallows it and
            # the attachment appears simply not to have happened.
            QMessageBox.warning(self, "Attach", i18n.t(
                "Attached, but the list couldn't be drawn: {error}"
            ).format(error=e))
            return
        if len(fresh) == 1:
            self.statusBar().showMessage(i18n.t("Attached {name}.").format(
                name=fresh[0]["name"]), 4000)
        else:
            self.statusBar().showMessage(i18n.t(
                "Attached {n} files from {name}.").format(
                    n=len(fresh),
                    name=os.path.basename(path.rstrip(os.sep))), 4000)
        # A folder whose files were all already attached falls out above, at
        # the "Already attached" guard.

    def _attach_file_dialog(self):
        """Ask where the file is before asking which file.

        A plain file dialog can only offer the disk, and half of what a
        company wants to feed Prism lives in its Drive. The choice comes
        first, and is skipped entirely when Drive isn't set up in this build —
        an option that always fails is worse than no option.
        """
        # Every source is a folder on this machine — Drive for Desktop,
        # OneDrive and Dropbox all mount as one — so "pick a source" is really
        # "which folder should the chooser open in". That keeps the whole
        # feature to one extra menu and no credentials at all.
        try:
            import cloud
            places = cloud.sources()
        except Exception:                               # noqa: BLE001
            places = []

        start_in = paths.picker_start_dir()
        if places:
            menu = QMenu(self)
            here = menu.addAction(i18n.t("This computer"))
            menu.addSeparator()
            for place in places:
                act = menu.addAction(place["label"])
                act.setData(place["path"])
            chosen = menu.exec(QCursor.pos())
            if chosen is None:
                return                                  # dismissed the menu
            if chosen is not here:
                start_in = chosen.data() or ""

        # One multi-select chooser either way. Opening it INSIDE the cloud
        # folder is the whole trick: from there it behaves exactly like
        # picking local files, and a client can select every video clip in
        # one pass rather than reopening the picker for each one.
        picked, _ = QFileDialog.getOpenFileNames(
            self, i18n.t("Attach files"), start_in)
        if picked:
            for path in picked:
                self._attach_path(path)
        else:
            # Distinguishes "you closed the chooser" from "the chooser never
            # opened" and from "attaching failed" — three very different bugs
            # that otherwise all look like a button that does nothing.
            self.statusBar().showMessage(i18n.t("No file chosen."), 3000)

    def _attach_from_drive(self):
        """Pick from Drive, download, then hand the local path to the same
        attach path a local file takes — nothing downstream knows the
        difference."""
        from dialogs.drive_dialog import DriveDialog
        picker = DriveDialog(self)
        if picker.exec() == QDialog.Accepted and picker.path:
            self._attach_path(picker.path)
            self.statusBar().showMessage(
                i18n.t("Brought {name} down from Google Drive.").format(
                    name=os.path.basename(picker.path)), 5000)

    def _attach_folder_dialog(self):
        path = QFileDialog.getExistingDirectory(
            self, i18n.t("Attach a folder"), paths.picker_start_dir())
        if path:
            self._attach_path(path)

    def _detach(self, path: str):
        self.attachments = [a for a in self.attachments if a["path"] != path]
        self.files_panel.set_attached(self.attachments)
        self.input_panel.set_context(self.attachments)
        self._sync_context_rail()

    def _detach_folder(self, folder: str):
        """Take a whole "Add folder" back out in one go.

        A folder is attached as its individual files, so before this the only
        way to undo one was to select and detach fifteen rows by hand — and
        Prism would have uploaded all fifteen to every tool in the meantime.
        """
        keep = [a for a in self.attachments if a.get("from_dir") != folder]
        removed = len(self.attachments) - len(keep)
        self.attachments = keep
        self.files_panel.set_attached(self.attachments)
        self.input_panel.set_context(self.attachments)
        self._sync_context_rail()
        if removed:
            where = os.path.basename(folder.rstrip(os.sep))
            self.statusBar().showMessage(
                (i18n.t("Detached 1 file from {name}.").format(name=where)
                 if removed == 1 else
                 i18n.t("Detached {n} files from {name}.").format(
                     n=removed, name=where)), 4000)

    def _detach_all(self):
        if not self.attachments:
            return
        count = len(self.attachments)
        self.attachments = []
        self.files_panel.set_attached(self.attachments)
        self.input_panel.set_context(self.attachments)
        self._sync_context_rail()
        self.statusBar().showMessage(
            (i18n.t("Detached the one attached file.") if count == 1
             else i18n.t("Detached all {n} files.").format(n=count)), 4000)

    # ── voice: record → interpret → resolve mentions ─────────────────────────
    def _toggle_mic(self):
        if self._record_worker is None:
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "Voice", "Set your Groq API key in Setup first.")
                self.input_panel.set_recording(False)
                return
            ok, why = wakeword.available()
            if not ok:
                QMessageBox.warning(self, "Voice", why)
                self.input_panel.set_recording(False)
                return
            self._record_worker = RecordWorker(self.cfg)
            self._record_worker.done.connect(self._on_transcribed)
            self._record_worker.failed.connect(self._on_voice_failed)
            # Join the retirement list like every other worker: without this a
            # mic recording/transcription still running when the window closes
            # is never stopped or wait()-ed, and Qt's ~QThread qFatal()s on a
            # live thread — a hard crash whose log says only "Prism closed".
            self._workers.append(self._record_worker)
            self._record_worker.start()
            self.input_panel.set_recording(True)
            self.input_panel.append_status("Recording — press Stop when you're done…")
        else:
            self._record_worker.stop()
            self.input_panel.set_recording(False)
            self.input_panel.append_status("Transcribing…")

    def _on_transcribed(self, text: str, lang: str):
        self._record_worker = None
        if not text:
            self.input_panel.append_status("Didn't catch anything — try again, or type.")
            return
        note = f"  ({lang})" if lang and lang != "english" else ""
        self.input_panel.append_status(f'Heard: "{text}"{note}')
        worker = InterpretWorker(text, self.cfg)
        worker.done.connect(self._on_interpreted)
        worker.failed.connect(lambda e: self._on_interpreted(
            {"cleaned": text, "files": [], "task": text, "ok": False}))
        self._workers.append(worker)
        worker.start()

    def _on_voice_failed(self, error: str):
        self._record_worker = None
        self.input_panel.set_recording(False)
        QMessageBox.warning(self, "Voice", f"Recording/transcription failed: {error}")

    def _on_interpreted(self, intent: dict):
        if not intent.get("ok", True):
            self.input_panel.append_status(
                "Interpreter unavailable — using your words as-is; "
                "mention any file manually with Add file.")
        self.input_panel.set_query_text(intent.get("task") or intent.get("cleaned") or "")
        self.pending_mentions = []
        self.files_panel.clear_mentions()
        files = intent.get("files") or []
        if files:
            self.input_panel.append_status(
                i18n.t("Searching for mentioned folder(s) and file(s)…"))
            for desc in files:
                self._resolve_mention(desc)

    def _resolve_mention(self, description: str):
        worker = FindWorker(description, self.cfg)
        index = len(self.pending_mentions)
        self.pending_mentions.append({"description": description, "path": None, "kind": None})

        def on_done(res: dict):
            path = res.get("dir") if not res.get("files") else (res["files"][0] if res["files"] else None)
            kind = "folder" if (path and not res.get("files")) else ("file" if path else None)
            self.pending_mentions[index]["path"] = path
            self.pending_mentions[index]["kind"] = kind
            self.files_panel.add_mention(index, description, path or "", kind or "?")
            if path and os.path.exists(path):
                self._attach_path(path)
                name = os.path.basename(path.rstrip("/\\"))
                self.input_panel.append_status(
                    i18n.t("Attached {kind} “{name}” from voice.").format(
                        kind=kind or "item", name=name))
            else:
                self.input_panel.append_status(
                    i18n.t("Could not find “{desc}” on disk. Use “Add file” or “Add folder” to attach it.").format(
                        desc=description))

        def on_failed(err: str):
            self.files_panel.add_mention(index, description, "", "?")
            self.input_panel.append_status(
                i18n.t("Could not locate “{desc}”: {err}").format(desc=description, err=err))

        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        self._workers.append(worker)
        worker.start()

    def _accept_mention(self, index: int):
        m = self.pending_mentions[index]
        if m["path"]:
            self._attach_path(m["path"])

    def _change_mention(self, index: int):
        start = paths.picker_start_dir()
        path = QFileDialog.getExistingDirectory(self, i18n.t("Pick the right folder…"), start)
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, i18n.t("…or pick the right file"), start)
        if path:
            self._attach_path(path)

    # ── routing ───────────────────────────────────────────────────────────────
    def _route(self, query: str):
        """Start the journey. The button hands over whatever is in the box,
        but the queue is the real source of truth — the box is only its last
        entry (see InputPanel.tasks).

        `query` still wins when the panel has nothing, so callers that drive
        the window directly — the wake word, a remote prompt, the tests —
        keep working without going through the text box.
        """
        tasks = self.input_panel.tasks() or (
            [query] if query and query.strip() else [])
        if not tasks:
            self.statusBar().showMessage("Type or speak a task first.", 4000)
            return
        self._task_queue = tasks
        self._task_pos = 0
        self._task_runs = []
        self._queue_stopped = False
        self._plan_task(0)

    def _plan_task(self, index: int):
        """Plan task `index` of the queue. Every task goes through this, so a
        single task is just a queue of one and there is no second code path to
        keep in step."""
        self._task_pos = index + 1
        self._route_one(self._task_queue[index])

    def _route_one(self, query: str):
        if not query.strip():
            self.statusBar().showMessage("Type or speak a task first.", 4000)
            return
        if not licensing.require("core", self):
            return
        if not CB.config.is_configured(self.cfg):
            QMessageBox.warning(self, "Setup needed", "Finish Setup (API key + agents) first.")
            return
        self._last_query = query
        self._current_run_file = None
        self._is_followup_run = False
        self._followup_session = None
        self._followup_text = ""
        getattr(CB.config, "reset_run", lambda: None)()
        if len(self._task_queue) > 1:
            self.statusBar().showMessage(
                f"Planning task {self._task_pos} of {len(self._task_queue)}…", 0)
        self.input_panel.set_busy(True)
        self.input_panel.set_busy_message(i18n.t("Checking your licence…"))
        # Planning is itself a Groq call — it costs tokens and is the step
        # every run begins with — so it is authorised and metered like one.
        # Gating only "Start the work" left the whole planning path reachable
        # with the licence server unreachable, which is not what live
        # authorisation is supposed to mean.
        # action="plan", not "run": planning is the billable step (three Groq
        # calls) and the one the daily allowance counts. The pipeline that
        # follows is browser automation against the customer's own logins and
        # costs us nothing, so counting both would burn two units per journey.
        auth_worker = AuthorizeWorker("core", "plan")
        auth_worker.done.connect(
            lambda result, w=auth_worker: self._start_route(result, query, w))
        self._workers.append(auth_worker)
        self._active_plan_worker = auth_worker
        auth_worker.start()

    def _cancel_route(self):
        """Neither AuthorizeWorker nor RouteWorker can be interrupted
        mid-call — a licence check and a Groq call are each one blocking
        network round trip with no cancellable hook, unlike a browser run,
        which polls a stop flag between and inside its waits. So this
        doesn't stop the thread; it clears the pointer _on_routed and
        _on_route_failed check, so whichever of them the abandoned worker
        eventually reaches finds itself no longer current and discards its
        answer instead of surprising the user with a plan they cancelled."""
        self._active_plan_worker = None
        self.input_panel.set_busy(False)
        self.input_panel.set_state("ready")
        self.statusBar().showMessage("Cancelled — nothing was kept.", 4000)

    def _start_route(self, auth, query: str, worker):
        """Second half of _route, once the server has said yes.

        `worker` (the AuthorizeWorker, passed explicitly rather than read via
        self.sender() — this is reached through a lambda, and sender()'s
        tracking is only reliable for a direct signal-to-bound-method
        connection) confirms this is still the attempt Cancel would affect,
        not one it already abandoned.
        """
        if self._active_plan_worker is not worker:
            return   # cancelled while the licence check was in flight
        if not auth.allowed:
            # A refusal will refuse identically for every task behind this
            # one, so stop the queue rather than firing N hopeless requests
            # at the licence server.
            self._queue_stopped = True
            self._active_plan_worker = None
            self.input_panel.set_busy(False)
            self.input_panel.set_state("ready")
            QMessageBox.warning(self, "Licence", auth.message)
            self._finish_queue()
            return
        self._run_id = getattr(auth, "run_id", "")
        if getattr(auth, "offline", False):
            # Authorised from the cached lease because the server could not be
            # reached. Say so, and do not stop: an arbitrary network failure is
            # not a licence failure, and the whole point of the offline window
            # is that the customer keeps working through it. A status message
            # rather than a dialog — nothing here needs a decision from them.
            self.statusBar().showMessage(
                i18n.t("Working offline — Prism couldn't reach the licence "
                       "server, so it's using this computer's saved "
                       "authorisation."), 8000)
        self.input_panel.set_busy_message(i18n.t("Making a plan for your task…"))
        worker = RouteWorker(query, self.cfg, self.attachments)
        worker.done.connect(self._on_routed)
        worker.failed.connect(self._on_route_failed)
        self._workers.append(worker)
        self._active_plan_worker = worker
        worker.start()

    def _on_routed(self, routing: dict):
        if self.sender() is not self._active_plan_worker:
            return   # cancelled — this RouteWorker's answer came in too late
        self._active_plan_worker = None
        self.input_panel.set_busy(False)
        # The router's Groq calls are already counted by licensing/meter.py;
        # send them now rather than waiting for a run that may never happen.
        licensing.report_usage(getattr(self, "_run_id", ""))
        self.input_panel.set_state("planned")
        self._set_stage("plan")
        self.routing = routing
        agents_cfg = CB.config.active_agents(self.cfg)
        self.agents_panel.set_content(routing, agents_cfg, self._last_query)
        self.agents_panel.set_attachment_count(len(self.attachments))
        self.work_stack.setCurrentIndex(COMPOSE)
        # Tasks 2..n were authorised by the same "Start the work" press as
        # task 1 — stopping to ask again for each would defeat the point of
        # queueing them. Only the first plan is offered for review.
        if self._auto_run:
            self.statusBar().showMessage(
                f"Task {self._task_pos} of {len(self._task_queue)} — starting…",
                4000)
            self._run_pipeline()
            return
        total = len(self._task_queue)
        # If the research guardrail added a research step, surface that in the
        # status bar so the user knows why the step appeared.
        research_data = routing.get("research") or {}
        if (isinstance(research_data, dict) and research_data.get("needed")
                and research_data.get("questions")
                and agents_cfg.get("research")):
            extra = i18n.t(
                " · Prism added Look things up because your task needs research."
            )
        else:
            extra = ""
        self.statusBar().showMessage(
            "Steps ready — drop any you don't want, then Start the work." + extra
            if total <= 1 else
            f"Steps ready for task 1 of {total}. Start the work and Prism will "
            f"run all {total} in order." + extra, 10000)

    def _on_route_failed(self, error: str):
        if self.sender() is not self._active_plan_worker:
            return   # cancelled — this RouteWorker's failure came in too late
        self._active_plan_worker = None
        self.input_panel.set_busy(False)
        self.input_panel.set_state("ready")
        # Keep the task. Planning is where runs fail most often — a Groq rate
        # limit, a dead connection, a key that expired — and it fails before
        # anything has been written down, so the customer's own words were the
        # only casualty. Somebody who spent five minutes describing a job
        # should not have to remember it and type it again.
        self._save_run(error=f"Planning failed: {error}")
        # Mid-queue a planning failure is one bad task, not a dead run — record
        # it and carry on, the same way a failed stage doesn't end a pipeline.
        if self._auto_run and self._task_pos < len(self._task_queue):
            self._record_task_run(failed=f"Planning failed: {error}")
            self.statusBar().showMessage(
                f"Task {self._task_pos} couldn't be planned — moving on.", 6000)
            self._advance_queue()
            return
        self._explain(error, "plan")

    # ── running the pipeline ────────────────────────────────────────────────
    #: Renderers that make their own scene artwork: when one of these is the
    #: media tool, automation.run() inserts an image step ahead of it, so a
    #: reel gets pictures whether or not the plan has a "Make the images"
    #: row of its own.
    _OWN_ARTWORK = ("Prism Studio", "Prism Motion")

    def _makes_own_artwork(self, run_agents: dict) -> bool:
        return any(name in self._OWN_ARTWORK
                   for name in (run_agents or {}).values())

    def _run_pipeline(self):
        if not self.routing:
            return
        if not licensing.require("core", self):
            return
        self.agents_panel.ensure_prompts()
        run_agents = self.agents_panel.selected_agents()
        # The ordered form of the same plan. A dict keyed by stage cannot
        # express order, and cannot hold the same stage twice — which is why
        # reordering, duplicating and editing a step's prompt could never
        # reach the engine, even though automation.run() has taken an ordered
        # (label, agent, questions) list all along. Both are kept: everything
        # that only needs "which tool ran what" still reads the dict.
        run_steps = self.agents_panel.selected_steps()
        if not run_agents:
            QMessageBox.information(self, "Run", "Every step is switched off — "
                                                 "turn at least one back on.")
            return
        # Everything the owner left out, told to the engine by name: some
        # stages are the engine's own insertions (Studio's image maker) and
        # only learn they were switched off this way.
        dropped: set = set(self.agents_panel.left_out_stages())

        # A ticked step with no prompt behind it is the run that uploads the
        # files, asks nothing, and sits out the whole 300s cap — twice over on
        # the 2026-09-07 reel run before the owner pressed Stop. The router
        # writes prompts only for the steps it planned; a step ticked on by
        # hand has none until one is written.
        #
        # Offered as a drop, not a refusal — the same shape as the locked
        # add-on case below. The first version refused outright, and the
        # very next plan showed why that was wrong: "Make the images" ticked
        # on by hand for a Studio reel, which makes its own artwork anyway.
        # A refusal there blocks a run that would have been fine.
        unprompted = self.agents_panel.unprompted_steps()
        if unprompted:
            stages = set(self.agents_panel.unprompted_stages())
            note = (i18n.t("{steps} have no prompt yet, so nothing would be "
                           "sent for them.")
                    if len(unprompted) > 1 else
                    i18n.t("{steps} has no prompt yet, so nothing would be "
                           "sent for it.")).format(steps=", ".join(unprompted))
            if "visual" in stages and self._makes_own_artwork(run_agents):
                note += i18n.t(" The reel still gets its pictures — Prism "
                               "makes its own artwork for it.")
            answer = QMessageBox.question(
                self, "Run",
                note + "\n\n" + i18n.t("Run the rest of the plan without "
                                       "{it}? (Or open Prompt on the step "
                                       "and write one.)").format(
                    it=i18n.t("them") if len(unprompted) > 1 else i18n.t("it")),
                QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                return
            run_agents = {stage: name for stage, name in run_agents.items()
                          if stage not in stages}
            run_steps = [s for s in run_steps if s[2]]
            # Dropped steps reach the engine by name, as everything else the
            # owner left out does — except "Make the images" on a reel Prism
            # illustrates itself. There, skip_stages also switches off the
            # artwork step the engine inserts, which made the dialog's own
            # promise above ("the reel still gets its pictures") false in the
            # same breath as it was made.
            keeps_artwork = self._makes_own_artwork(run_agents)
            dropped |= {stage for stage in stages
                        if not (stage == "visual" and keeps_artwork)}
            if not run_agents:
                QMessageBox.information(
                    self, "Run", i18n.t("Every remaining step needs a prompt "
                                        "— open Prompt on one and write it."))
                return

        # The router can put a paid add-on into a plan without the customer
        # ever opening it from the rail, so the entitlement has to be checked
        # here too. Offer to run everything else rather than refusing outright:
        # losing one step is a far better outcome than losing the whole run.
        locked = {stage: name for stage, name in run_agents.items()
                  if AGENT_FEATURES.get(name)
                  and not licensing.has(AGENT_FEATURES[name])}
        if locked:
            names = ", ".join(sorted(set(locked.values())))
            answer = QMessageBox.question(
                self, "Not in your licence",
                (i18n.t("{tools} isn't part of your licence, so those steps "
                        "can't run.\n\nRun the rest of the steps without them?")
                 if len(locked) > 1 else
                 i18n.t("{tools} isn't part of your licence, so that step "
                        "can't run.\n\nRun the rest of the steps without it?")
                 ).format(tools=names),
                QMessageBox.Yes | QMessageBox.Cancel)
            if answer != QMessageBox.Yes:
                # Straight to the pitch — they have just told us they want it.
                licensing.require(AGENT_FEATURES[next(iter(locked.values()))], self)
                return
            run_agents = {stage: name for stage, name in run_agents.items()
                          if stage not in locked}
            # The same filter on the ordered list, or a step dropped for want
            # of an entitlement would still run.
            run_steps = [s for s in run_steps if s[1] not in set(locked.values())]
            if not run_agents:
                QMessageBox.information(
                    self, "Run", "Every step here needs an add-on that "
                                 "isn't in your licence.")
                return
        # Prism Studio needs a browser engine the rest of Prism does not. Say
        # so before the run rather than at the last stage, an hour of tool
        # calls later — and offer the renderer that does work.
        if "Prism Studio" in run_agents.values():
            ok, why = CB.studio_available()
            if not ok:
                answer = QMessageBox.question(
                    self, "Prism Studio",
                    # Says what the swap costs. Prism Reel has no step that
                    # makes pictures, so choosing it removes the reel's
                    # artwork — and saying nothing about that is how "Prism
                    # doesn't make artwork on Windows" was reported as a
                    # mystery rather than as a choice someone was offered.
                    # Two strings rather than one reworded one, so the
                    # question keeps its existing Hindi and Gujarati text.
                    i18n.t("{why}\n\nRun with the fixed house style "
                           "(Prism Reel) instead?").format(why=why)
                    + " " + i18n.t("Prism Reel makes no pictures of its "
                                   "own, so the reel will be type and "
                                   "colour only."),
                    QMessageBox.Yes | QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return
                run_agents = {k: ("Prism Reel" if v == "Prism Studio" else v)
                              for k, v in run_agents.items()}
                run_steps = [(label, "Prism Reel" if agent == "Prism Studio"
                              else agent, questions)
                             for label, agent, questions in run_steps]
        # Same idea for Prism Motion — its own browser/Electron/FFmpeg needs,
        # same fallback to the one renderer with none of those dependencies.
        if "Prism Motion" in run_agents.values():
            ok, why = CB.motion_available()
            if not ok:
                answer = QMessageBox.question(
                    self, "Prism Motion",
                    # Says what the swap costs. Prism Reel has no step that
                    # makes pictures, so choosing it removes the reel's
                    # artwork — and saying nothing about that is how "Prism
                    # doesn't make artwork on Windows" was reported as a
                    # mystery rather than as a choice someone was offered.
                    # Two strings rather than one reworded one, so the
                    # question keeps its existing Hindi and Gujarati text.
                    i18n.t("{why}\n\nRun with the fixed house style "
                           "(Prism Reel) instead?").format(why=why)
                    + " " + i18n.t("Prism Reel makes no pictures of its "
                                   "own, so the reel will be type and "
                                   "colour only."),
                    QMessageBox.Yes | QMessageBox.Cancel)
                if answer != QMessageBox.Yes:
                    return
                run_agents = {k: ("Prism Reel" if v == "Prism Motion" else v)
                              for k, v in run_agents.items()}
                run_steps = [(label, "Prism Reel" if agent == "Prism Motion"
                              else agent, questions)
                             for label, agent, questions in run_steps]

        skip_stages = sorted(dropped)

        # Pressing Start the work commits the whole queue, not just the plan on
        # screen. From here every later task plans and runs without stopping.
        # Armed only now, after every confirmation above has been answered:
        # a Cancel on one of those returns early, and arming first left the
        # flag set, so the NEXT task planned on this surface started by itself
        # instead of waiting for review.
        self._auto_run = True

        # The prompts were written when the plan was made -- before anyone
        # looked at it. If a step was dropped, added, moved or given another
        # tool here, those prompts are wrong: on the 2026-09-10 deck run the
        # presentation step was switched from Gamma to Canva and Canva was
        # handed Gamma's brief ("plain-text slide format ready for import
        # into Gamma.app"), so it typed an outline back. So the prompts are
        # written again, now, for the plan as it is about to run -- one Groq
        # call, off the thread, before the licence check. An unchanged plan
        # keeps the prompts it has.
        planned = CB.router.planned_steps(
            self.routing, CB.config.active_agents(self.cfg))
        if CB.router.plan_changed(planned, run_steps):
            self.agents_panel.set_run_enabled(False)
            self.statusBar().showMessage(
                i18n.t("Writing the prompts for the steps you confirmed…"))
            worker = PlanBriefWorker(self._last_query, self.cfg, run_steps,
                                     self.routing)
            worker.done.connect(
                lambda steps: self._prompts_written(steps, run_agents,
                                                    skip_stages))
            worker.failed.connect(
                lambda err: self._prompts_written(run_steps, run_agents,
                                                  skip_stages, error=err))
            self._workers.append(worker)
            worker.start()
            return
        self._authorize_and_start(run_agents, run_steps, skip_stages)

    def _prompts_written(self, steps: list, run_agents: dict,
                         skip_stages: list, error: str = ""):
        """The rewritten prompts are back (or could not be written): show
        them on the plan, then carry on to the licence check."""
        if error:
            self.statusBar().showMessage(i18n.t(
                "Couldn't rewrite the prompts ({error}) — running with the "
                "plan's own.").format(error=error), 8000)
        else:
            self.agents_panel.apply_prompts(steps)
            self.statusBar().showMessage(
                i18n.t("Prompts written for the plan as you confirmed it."), 5000)
        self._authorize_and_start(run_agents, steps, skip_stages)

    def _authorize_and_start(self, run_agents: dict, run_steps: list,
                             skip_stages: list):
        # Ask the licence server, live, before committing to the run. This is
        # the ONLY place a run is authorised — never again once it is moving,
        # because a pipeline is tens of minutes of browser automation and
        # killing it half way for a transient reason throws away real work.
        self.agents_panel.set_run_enabled(False)
        self.statusBar().showMessage("Checking your licence…")
        auth_worker = AuthorizeWorker("core", "run")
        auth_worker.done.connect(
            lambda result: self._start_run(result, run_agents, run_steps,
                                           skip_stages))
        self._workers.append(auth_worker)
        auth_worker.start()

    def _start_run(self, auth, run_agents: dict, run_steps: list = None,
                   skip_stages: list = None):
        """Second half of _run_pipeline, once the server has said yes."""
        self.statusBar().clearMessage()
        if not auth.allowed:
            # Same reasoning as the planning refusal: it will say no to every
            # remaining task too, so end the queue instead of grinding through.
            self._queue_stopped = True
            self.agents_panel.set_run_enabled(True)
            QMessageBox.warning(self, "Licence", auth.message)
            self._finish_queue()
            return

        self._run_id = getattr(auth, "run_id", "")
        if not getattr(self, "_is_followup_run", False):
            self._current_run_file = None
            self._followup_session = None
            self._followup_text = ""
            getattr(CB.config, "reset_run", lambda: None)()
        cfg_for_run = dict(self.cfg)
        cfg_for_run["agents"] = run_agents
        self.output_panel.clear()
        # Seed the timeline with the whole plan before anything runs, rather
        # than growing it a card at a time. Three things depend on it: the
        # steps still to come stay on screen instead of the run looking like
        # it is only ever one step long, the header can say "Step 3 of 7",
        # and "Queued" becomes reachable at all — the state was written long
        # ago and could never be seen, because a card was only ever built at
        # the moment its stage started.
        self.output_panel.set_plan(run_agents)
        self.output_panel.set_task(getattr(self, "_last_query", ""))
        self._stage_agents = {}
        self._stage_results = []
        self._run_shortfall = []
        self.input_panel.set_state("running")
        self._set_stage("run")
        self._run_finished = False
        self.output_panel.set_finished(False)
        self.output_panel.set_running(True)
        self.work_stack.setCurrentIndex(RUNNING)
        worker = AutomationWorker(self.routing, cfg_for_run, self.attachments,
                                  self._last_query, custom_stages=run_steps,
                                  skip_stages=skip_stages)
        # Hold the machine awake for the duration. A run is tens of minutes
        # and the whole promise is that you walk away — a laptop that sleeps
        # halfway through takes the browser session with it.
        awake.acquire()
        self._active_run = worker
        worker.stage_event.connect(self._on_stage_event)
        worker.done.connect(self._on_run_done)
        worker.failed.connect(self._on_run_failed)
        self._workers.append(worker)
        worker.start()

    def _discard_plan(self):
        """Throw away a plan the customer doesn't want.

        Attachments survive on purpose — they are explicit choices sitting
        visibly in the rail with their own Detach button, and the next task is
        usually about the same files.
        """
        if QMessageBox.question(
                self, "Discard these steps",
                "Throw these steps away and clear the task?\n\n"
                "Files you've attached stay attached.",
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        self._reset_for_new_task(keep_attachments=True)

    # ── the reel layout editor, from a finished workbench step ──────────
    def _edit_reel_layout(self, mp4_path: str):
        """A Studio reel on a stage card wants fixing by hand. Open the
        page it was filmed from in the browser, with the edit layer on."""
        import json as _json
        spec_path = mp4_path[:-4] + ".json"
        if not os.path.isfile(spec_path):
            folder = os.path.dirname(mp4_path)
            stem = os.path.splitext(os.path.basename(mp4_path))[0]
            cand = os.path.join(folder, stem + ".json")
            if os.path.isfile(cand):
                spec_path = cand
            else:
                for d in [folder, CB.config.current_run_dir(), CB.config.RUNS_DIR]:
                    if d and os.path.isdir(d):
                        try:
                            jsons = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".json")]
                            jsons.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
                            if jsons:
                                spec_path = jsons[0]
                                break
                        except OSError:
                            pass
        try:
            with open(spec_path, encoding="utf-8") as f:
                spec = _json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Reel", i18n.t(
                "The reel's saved design could not be read: {error}").format(
                error=e))
            return
        edit = CB.get_reel_edit()
        if not edit.is_studio_spec(spec):
            QMessageBox.information(self, "Reel", i18n.t(
                "This reel was drawn from templates — there is no page to "
                "edit. Studio reels only."))
            return
        self._stop_reel_editor()
        try:
            url, self._reel_edit_stop = edit.serve(
                spec,
                on_save=self.reel_edits_saved.emit,
                on_render=self.reel_edits_rendered.emit,
                on_refine=self.reel_refine_requested.emit)
        except Exception as e:                          # noqa: BLE001
            QMessageBox.warning(self, "Reel", i18n.t(
                "Could not open the editor: {error}").format(error=e))
            return
        self._reel_edit_ctx = {"spec": spec, "spec_path": spec_path,
                               "mp4_path": mp4_path}
        opened = QDesktopServices.openUrl(QUrl(url))
        if not opened:
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception:
                pass
        self.statusBar().showMessage(i18n.t(
            "The reel is open in your browser — drag things into place, "
            "then press Save & render there."), 12000)

    def _keep_reel_edits(self, edits: list):
        import json as _json
        ctx = self._reel_edit_ctx
        if not ctx:
            return
        ctx["spec"]["edits"] = edits
        try:
            with open(ctx["spec_path"], "w", encoding="utf-8") as f:
                _json.dump(ctx["spec"], f, indent=2)
        except OSError:
            pass    # the render still carries the edits in memory

    def _on_reel_edits_saved(self, edits: list):
        self._keep_reel_edits(edits)
        self.statusBar().showMessage(i18n.t(
            "Reel layout saved — {n} change(s). Press Save & render in the "
            "browser when you are happy.").format(n=len(edits)), 8000)

    def _on_reel_edits_rendered(self, edits: list):
        self._keep_reel_edits(edits)
        ctx = self._reel_edit_ctx
        if not ctx:
            return
        import time as _time
        mp4_path = ctx.get("mp4_path", "")
        folder = os.path.dirname(mp4_path) if (mp4_path and os.path.isdir(os.path.dirname(mp4_path))) else CB.config.current_run_dir()
        task_label = getattr(self, "_last_query", "") or "reel"
        if folder and os.path.isdir(folder):
            CB.config.continue_run(folder, task=task_label, title=CB.config.current_run_title())
        out = os.path.join(CB.config.RUNS_DIR,
                           f"reel_{int(_time.time())}.mp4")
        self.statusBar().showMessage(
            i18n.t("Rendering the fixed reel…"))

        stop_fn = getattr(self, "_reel_edit_stop", None)
        if stop_fn and hasattr(stop_fn, "reset_progress"):
            stop_fn.reset_progress()

        start_time = _time.time()

        def _handle_progress(d: int, t: int):
            if stop_fn and hasattr(stop_fn, "set_progress"):
                stop_fn.set_progress(d, t)
            now = _time.time()
            elapsed = max(0.001, now - start_time)
            pct = int(d / max(1, t) * 100)
            if d > 0 and t > d:
                fps_rate = d / elapsed
                rem_sec = int((t - d) / max(0.1, fps_rate))
                eta_text = f"~{rem_sec}s remaining"
            elif d >= t:
                eta_text = "finishing…"
            else:
                eta_text = "calculating…"
            self.statusBar().showMessage(
                i18n.t("Rendering the fixed reel… {p}% ({eta})").format(
                    p=pct, eta=eta_text))

        def _handle_done(path: str):
            if stop_fn and hasattr(stop_fn, "set_done"):
                stop_fn.set_done(path)
            self._on_reel_edit_rendered_done(path)

        def _handle_failed(e: str):
            if stop_fn and hasattr(stop_fn, "set_error"):
                stop_fn.set_error(e)
            self.statusBar().clearMessage()
            QMessageBox.warning(self, "Reel", e)

        worker = ReelWorker(ctx["spec"], out, studio=True)
        worker.progress.connect(_handle_progress)
        worker.done.connect(_handle_done)
        worker.failed.connect(_handle_failed)
        self._reel_edit_worker = worker
        worker.start()

    def _on_reel_refine_requested(self, change: str, selection: dict):
        """Turn Studio's browser prompt into the existing design-tab follow-up."""
        ctx = self._reel_edit_ctx or {}
        spec = ctx.get("spec") or {}
        meta = spec.get("_studio") or {}
        design_url, agent = meta.get("design_url", ""), meta.get("agent", "")
        if not design_url or not agent:
            self.statusBar().showMessage(
                "This older reel has no saved Studio conversation; manual editing is available.",
                9000)
            return
        scene = int(selection.get("scene_index", 0) or 0) + 1
        layer = selection.get("label") or selection.get("element_id") or "scene"
        self._followup_text = f"{change}\n\nSTUDIO SELECTION: Scene {scene}, {layer}."
        self._followup_links = {"design": design_url}
        # Studio can be opened from the Artifacts panel with no run in this
        # session, so `_last_query` is empty or belongs to something else;
        # the follow-up worker files its run and artifact under it. The
        # change the owner typed IS this run's task.
        self._last_query = change
        self._stop_reel_editor()
        reel = (ctx.get("mp4_path", ""), ctx.get("spec_path", ""), spec)
        self._start_studio_followup(reel, design_url, agent, [], fresh_panel=True)

    def _on_reel_edit_rendered_done(self, path: str):
        ctx = self._reel_edit_ctx or {}
        spec_path = path[:-4] + ".json"
        if ctx.get("spec"):
            import json as _json
            try:
                with open(spec_path, "w", encoding="utf-8") as f:
                    _json.dump(ctx["spec"], f, indent=2)
            except OSError:
                pass
        task_label = getattr(self, "_last_query", "") or "reel"
        try:
            artifact = CB.config.save_artifact(
                path, task_label, kind="reel",
                task=task_label)
        except Exception:                               # noqa: BLE001
            artifact = ""
        shown = artifact or path
        if ctx:
            ctx["mp4_path"] = shown
            ctx["spec_path"] = shown[:-4] + ".json"
            if os.path.isfile(spec_path) and shown != path:
                try:
                    import shutil
                    shutil.copy2(spec_path, ctx["spec_path"])
                except OSError:
                    pass
        sess = getattr(self, "_followup_session", None)
        if sess:
            sess["links"]["media"] = shown
        note = f"reel layout fixed and rendered — {os.path.basename(shown)}"
        self._save_run(responses={"media": [note]}, links={"media": shown})
        self.statusBar().showMessage(i18n.t(
            "Fixed reel rendered — {name}").format(
            name=os.path.basename(shown)), 12000)
        try:
            paths.reveal_result(shown)
        except Exception:                               # noqa: BLE001
            pass

    def _stop_reel_editor(self):
        if self._reel_edit_stop is not None:
            try:
                self._reel_edit_stop()
            except Exception:                           # noqa: BLE001
                pass
            self._reel_edit_stop = None

    def _skip_step(self):
        """Give up on the stage that is running and let the run move on.

        The engine polls the flag inside the stage's waits — including the
        image wait, where a picture that never finishes used to hold the
        run for its whole cap — keeps whatever the tool produced, and
        clears the flag itself so one press skips exactly one step.
        """
        worker = getattr(self, "_active_run", None)
        if worker is None or not worker.isRunning() or not hasattr(worker, "skip"):
            return
        worker.skip()
        self.statusBar().showMessage(
            i18n.t("Skipping this step — moving to the next one…"), 6000)

    def _use_fallback(self):
        """Hand the stage that is running to its fallback tool now.

        Same switch shape as _skip_step: the engine polls the flag inside
        the stage's waits, runs the failover pass for that one stage
        immediately, and clears the flag itself.
        """
        worker = getattr(self, "_active_run", None)
        if (worker is None or not worker.isRunning()
                or not hasattr(worker, "use_fallback")):
            return
        worker.use_fallback()
        self.statusBar().showMessage(
            i18n.t("Handing this step to its fallback tool…"), 6000)

    def _stop_run(self):
        """Ask the running pipeline to wind up.

        Deliberately not a thread kill: the engine polls a flag between stages
        and inside its waits, so it stops at a safe point and keeps every step
        that already finished. Terminating the QThread instead would abandon a
        live Chrome session and lose completed output — the exact work the
        customer is trying to protect by stopping.
        """
        worker = getattr(self, "_active_run", None)
        if worker is None or not worker.isRunning():
            return
        worker.stop()
        self.statusBar().showMessage(
            "Stopping — finishing the current step, keeping what's done…", 0)

    def _shortfall_words(self) -> str:
        """The missing deliverables of the last run, in the person's words."""
        words = {"file": i18n.t("a file to download"),
                 "image": i18n.t("pictures"),
                 "video": i18n.t("a video file")}
        return ", ".join(words.get(k, k)
                         for k in (getattr(self, "_run_shortfall", None) or []))

    def _on_stage_event(self, kind: str, payload: dict):
        stage = payload.get("stage", "")
        if kind == "browser_lost":
            # The run stopped because Chrome went away, not because a step
            # failed. Said plainly and once — the engine already refused to
            # grind through the remaining stages producing the same error.
            done = payload.get("done", 0)
            self.statusBar().showMessage(
                i18n.t("The browser window was closed. {n} step(s) finished "
                       "before that and were kept.").replace("{n}", str(done))
                if done else
                i18n.t("The browser window was closed before anything ran."),
                12000)
            # The engine sends the underlying error and this used to drop it,
            # leaving the card that was in flight saying "Working…" for ever.
            self.output_panel.browser_lost(stage, payload.get("error", ""), done)
            return
        if kind == "cancelled":
            done = payload.get("done", 0)
            self.statusBar().showMessage(
                f"Stopped. {done} step{'s' if done != 1 else ''} finished and "
                f"kept." if done else "Stopped before anything ran.", 8000)
            # Same again: a status-bar line lasts eight seconds, and without
            # this the stopped step kept its clock ticking indefinitely.
            self.output_panel.run_cancelled(stage, done)
            return
        if kind == "run_shortfall":
            # What the run was asked for, against what exists on the disk —
            # see core/contract.py. Kept for the completion screen, and said
            # now, because a row of finished steps over an empty folder is
            # exactly what this exists to stop.
            self._run_shortfall = list(payload.get("missing") or [])
            if self._run_shortfall:
                self.statusBar().showMessage(
                    i18n.t("This run did not produce: {what}").format(
                        what=self._shortfall_words()), 30000)
            return
        if kind == "stage_start":
            agent = payload.get("agent", "")
            self._stage_agents[stage] = agent
            self.output_panel.stage_started(stage, agent)
            self._push_active_run(stage, agent)
        elif kind == "waiting":
            self.output_panel.stage_waiting(stage, payload.get("seconds", 0))
        elif kind == "stage_done":
            texts = payload.get("texts") or []
            url = payload.get("url", "")
            timed_out = bool(payload.get("timed_out"))
            # `blocked` is the engine's own plain-English reason a step came
            # back empty — "out of credit", "sign-in wall", "the site changed
            # its markup". It was computed on every empty result and thrown
            # away here, which is why an out-of-credit step and a genuinely
            # broken one looked identical.
            self.output_panel.stage_done(
                stage, texts, url, timed_out,
                blocked=payload.get("blocked") or "",
                exhausted=bool(payload.get("exhausted")),
                count=payload.get("count"),
                snippet=payload.get("snippet", ""),
                files=payload.get("files") or [],
                prism_note=payload.get("note") or "",
                missing=payload.get("missing") or "")
            if texts:
                snippet = (texts[0][:150] + "…") if len(texts[0]) > 150 else texts[0]
            elif timed_out:
                snippet = "still generating in the tool — open the link"
            else:
                snippet = "no response captured"
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": "\n\n---\n\n".join(texts), "url": url,
                "snippet": snippet, "ok": bool(texts), "timed_out": timed_out,
            })
            # Metering: which tool ran which stage. No prompt text, no output —
            # see licensing/meter.py for why that line is drawn hard.
            licensing.meter.record(
                "stage", tool=self._stage_agents.get(stage, ""), stage=stage,
                ok=bool(texts))
        elif kind == "stage_failover":
            # A tool could not finish and Prism is handing the step to another
            # one. Said out loud rather than done quietly: the customer is
            # about to wait several more minutes, and a screen that sits still
            # for that long without explaining itself reads as a hang.
            failed = payload.get("failed", "the tool")
            agent = payload.get("agent", "")
            why = ("has hit its usage limit" if payload.get("exhausted")
                   else "couldn't finish")
            self._stage_agents[stage] = agent
            self.statusBar().showMessage(
                i18n.t("{failed} {why} — trying {agent} instead…")
                .replace("{failed}", failed).replace("{why}", why)
                .replace("{agent}", agent), 15000)
            # NOT stage_started(): that built a second card and orphaned the
            # first in the timeline, where nothing could update it and the
            # problem counter no longer saw it. The card now holds RETRYING,
            # keeps its clock, and carries the engine's own reason instead of
            # one of two hardcoded phrases that vanished after 15 seconds.
            self.output_panel.stage_failover(
                stage, failed, agent, reason=payload.get("reason", ""),
                exhausted=bool(payload.get("exhausted")))
        elif kind == "stage_recovered":
            texts = payload.get("texts") or []
            url = payload.get("url", "")
            agent = payload.get("agent", "")
            # Says which tool actually finished it, and which one could not —
            # the record already kept `failed` for History and the screen
            # never showed it.
            self.output_panel.stage_recovered(
                stage, agent, failed=payload.get("failed", ""),
                texts=texts, url=url)
            # Replace the failed record rather than appending a second one, or
            # the completion popup lists the step twice — once failed, once
            # done — and the customer cannot tell which one they got.
            record = {
                "stage": stage, "agent": agent,
                "text": "\n\n---\n\n".join(texts), "url": url,
                "snippet": (texts[0][:150] + "…") if texts and len(texts[0]) > 150
                           else (texts[0] if texts else ""),
                "ok": True, "timed_out": False,
                # Kept for History: which tool was asked first, and why the
                # answer came from somewhere other than the plan said.
                "failover_from": payload.get("failed", ""),
            }
            for i, existing in enumerate(self._stage_results):
                if existing.get("stage") == stage and not existing.get("ok"):
                    self._stage_results[i] = record
                    break
            else:
                self._stage_results.append(record)
            licensing.meter.record("stage", tool=agent, stage=stage, ok=True)
            self.statusBar().showMessage(
                i18n.t("{agent} finished the {stage} step.")
                .replace("{agent}", agent).replace("{stage}", stage), 8000)
        elif kind == "stage_unrecovered":
            self.statusBar().showMessage(
                i18n.t("No other tool could finish the {stage} step either.")
                .replace("{stage}", stage), 10000)
            self.output_panel.stage_unrecovered(
                stage, payload.get("failed", ""), payload.get("reason", ""))
        # Three kinds the engine has always emitted and this handler has
        # always let fall straight through the if/elif chain in silence.
        # stage_skipped is the one that matters: automation.py added it
        # SPECIFICALLY so the GUI would stop dropping a step without saying
        # so, and the GUI went on dropping it without saying so.
        elif kind == "stage_skipped":
            self.output_panel.stage_skipped(
                stage, payload.get("agent", ""), payload.get("reason", ""))
        elif kind == "retry":
            self.output_panel.stage_retry(stage, payload.get("reason", ""))
        elif kind == "reel_scene":
            # Carries no "stage" key — it can only ever be the live one.
            self.output_panel.scene_progress(
                payload.get("index", 0), payload.get("total", 0))
        elif kind == "stage_error":
            error = payload.get("error", "")
            licensing.meter.record(
                "stage", tool=self._stage_agents.get(stage, ""), stage=stage,
                ok=False)
            # The engine hands back the tab it died on whenever there is one —
            # a slow tool often finishes server-side after we stopped waiting,
            # so the link is kept and offered even on a failed step.
            url = payload.get("url", "")
            self.output_panel.stage_error(stage, error, url)
            self._stage_results.append({
                "stage": stage, "agent": self._stage_agents.get(stage, "?"),
                "text": error, "url": url,
                "snippet": f"failed: {error[:120]}", "ok": False,
            })

    def _save_run(self, responses: dict | None = None, links: dict | None = None,
                  error: str = ""):
        """Persist the run to ~/.prism/runs, the same place and shape the CLI
        writes — it's what the History dialog reads, and until now only the
        CLI ever wrote there, so nothing done in the GUI was ever kept.

        Failures are swallowed to the status bar on purpose: the run itself
        succeeded, and a full disk shouldn't turn that into an error dialog.

        When this run is a follow-up, it updates the existing task record in-place,
        recording the follow-up request and outputs under the parent task's history
        so the task flow remains: First task -> Followup 1 -> Followup 2 -> etc.
        """
        import time
        if responses is None or links is None:
            # A failed run has no engine return value — rebuild what did land
            # from the per-stage events we collected on the way.
            responses = {r["stage"]: [r["text"]] for r in self._stage_results if r["ok"]}
            links = {r["stage"]: r["url"] for r in self._stage_results if r.get("url")}

        is_fu = bool(getattr(self, "_is_followup_run", False)
                     or getattr(self, "_followup_text", "").strip())
        sess = getattr(self, "_followup_session", None)
        target_path = getattr(self, "_current_run_file", None) or (sess.get("run_file") if sess else None)

        if is_fu and not target_path:
            cur_art = (sess.get("artifacts_dir") if sess else "") or CB.config.current_run_dir()
            if cur_art and os.path.isdir(cur_art):
                try:
                    me = identity.current()
                    rdir = workspace.runs_dir(me["mid"], self.cfg)
                    if os.path.isdir(rdir):
                        for n in sorted(os.listdir(rdir), reverse=True):
                            if n.startswith("run_") and n.endswith(".json"):
                                fp = os.path.join(rdir, n)
                                try:
                                    with open(fp, "r", encoding="utf-8") as rf:
                                        rd = json.load(rf) or {}
                                    if rd.get("artifacts") and os.path.normpath(rd.get("artifacts")) == os.path.normpath(cur_art):
                                        target_path = fp
                                        self._current_run_file = fp
                                        break
                                except Exception:
                                    pass
                except Exception:
                    pass

        if is_fu and target_path and os.path.isfile(target_path):
            try:
                with open(target_path, "r", encoding="utf-8") as f:
                    record = json.load(f) or {}
            except Exception:
                record = {}
            if record:
                followups = list(record.get("followups") or [])
                fu_text = getattr(self, "_followup_text", "").strip() or "Follow-up refinement"
                followups.append({
                    "index": len(followups) + 1,
                    "query": fu_text,
                    "timestamp": time.time(),
                    "responses": dict(responses or {}),
                    "links": dict(links or {}),
                    "agents": dict(self._stage_agents),
                    "durations": self.output_panel.stage_durations(),
                    "error": error,
                })
                record["followups"] = followups
                rec_resp = record.setdefault("responses", {})
                rec_resp.update(responses or {})
                rec_links = record.setdefault("links", {})
                rec_links.update(links or {})
                record.setdefault("agents", {}).update(self._stage_agents)
                record["updated_at"] = time.time()
                cur_art = CB.config.current_run_dir()
                if cur_art:
                    record["artifacts"] = cur_art
                if error:
                    record["latest_error"] = error
                try:
                    CB.config.save_run(record, path=target_path)
                    self._is_followup_run = False
                    self._followup_text = ""
                    return
                except Exception as e:
                    self.statusBar().showMessage(f"Couldn't update task history: {e}", 8000)

        record = {
            "query": getattr(self, "_last_query", ""),
            "routing": self.routing or {},
            "responses": responses or {},
            "links": links or {},
            # names, not dicts — matches what prism.py writes
            "attachments": [a["name"] for a in self.attachments],
            # not in the CLI's record: which tool actually ran each step, so
            # History can name them instead of showing bare stage keys
            "agents": dict(self._stage_agents),
            # How long each step actually took. The panel has timed every
            # stage all along and the number died with the widget — which is
            # why History can say what a run did but never how long any of it
            # took, and why "this one is slow" has never been answerable.
            "durations": self.output_panel.stage_durations(),
            "followups": [],
        }
        # Where this run's files went — one folder per run (config.begin_run)
        # — so a follow-up from History attaches THIS run's output, not
        # everything ever made under the same words.
        record["artifacts"] = CB.config.current_run_dir()
        # The planner's short name for the job — what History and Home show
        # instead of the request verbatim.
        record["title"] = ((self.routing or {}).get("_title")
                           or CB.config.current_run_title() or "")
        if error:
            record["error"] = error
        # Stamped with who ran it, so a run file is self-describing even if it
        # is later copied out of its folder — the manager's History shows a
        # name against the work rather than inferring one from the path.
        me = identity.current()
        record["member"] = {"mid": me["mid"], "name": me["name"],
                            "role": me["role"]}
        try:
            # Always the REAL member, never identity.viewing(): an admin
            # reading someone else's profile and then starting a run must file
            # that run under themselves, not under the person they were
            # looking at.
            path = CB.config.save_run(record, workspace.runs_dir(me["mid"], self.cfg))
            self._current_run_file = path
            if sess:
                sess["run_file"] = path
                sess["initial_query"] = record.get("query")
                sess["initial_title"] = record.get("title")
        except Exception as e:
            self.statusBar().showMessage(f"Couldn't save this run to history: {e}", 8000)

    # ── the task queue ───────────────────────────────────────────────────────
    def _record_task_run(self, failed: str = ""):
        """Bank the task that just ended, so its stages survive the reset at
        the top of the next run. This is the whole reason the queue works:
        _stage_results is emptied for every run, and without copying it out
        first, task 1's results would be gone before task 2 finished."""
        self._task_runs.append({
            "task": getattr(self, "_last_query", ""),
            "index": self._task_pos,
            "stages": list(self._stage_results),
            "error": failed,
        })

    def _more_tasks(self) -> bool:
        return (not self._queue_stopped
                and self._task_pos < len(self._task_queue))

    def _advance_queue(self):
        """Plan and run the next queued task."""
        if not self._more_tasks():
            self._finish_queue()
            return
        nxt = self._task_pos          # _task_pos is 1-based, so this is the next index
        self.statusBar().showMessage(
            f"Task {nxt} done — planning task {nxt + 1} of "
            f"{len(self._task_queue)}…", 5000)
        self._plan_task(nxt)

    def _finish_queue(self):
        """Every task is done (or the queue was cut short). Show one window
        covering all of them."""
        self._auto_run = False
        self.input_panel.clear_queue()
        groups = [g for g in self._task_runs if g["stages"] or g["error"]]
        if not groups:
            if not self._queue_stopped:
                QMessageBox.information(
                    self, "Finished",
                    "No step produced output — check the results above.")
            return
        # One task behaves exactly as before: a flat list, no task headings.
        if len(groups) == 1:
            CompletionDialog(groups[0]["stages"], self).exec()
        else:
            CompletionDialog(groups[0]["stages"], self, task_groups=groups).exec()

    def _on_run_done(self, responses: dict, links: dict):
        awake.release()
        stopped = bool(getattr(self, "_active_run", None)
                       and self._active_run.stopping())
        self._active_run = None
        self.agents_panel.set_run_enabled(True)
        self.input_panel.set_state("done")
        self._clear_active_run()
        self._set_stage("run")
        self._run_finished = True
        self.output_panel.set_finished(True)
        self.output_panel.set_running(False)
        licensing.report_usage(getattr(self, "_run_id", ""))
        self._save_run(responses, links)
        self._record_task_run()
        # Clear the input bar's attachment chips so they don't carry forward to
        # a new task or appear while the user browses other modules.  The actual
        # list (self.attachments) is kept: _offer_followup picks it up, and
        # _reset_for_new_task() clears it when the user starts something fresh.
        self.input_panel.set_context([])

        if stopped:
            # Stop means stop the lot. Pressing it to escape one bad task and
            # then watching four more start would be the opposite of what the
            # button says — but everything already finished is still shown.
            self._queue_stopped = True
            self.statusBar().showMessage(
                "Stopped — everything finished so far is saved to History.",
                8000)
            self._finish_queue()
            return

        if self._more_tasks():
            self._advance_queue()
            return

        if getattr(self, "_run_shortfall", None):
            # The last thing said about a run has to be true. "All done"
            # over a reel with no video, or a document request with no file,
            # is how the gap went unnoticed until someone opened the folder
            # (core/contract.py).
            self.statusBar().showMessage(
                i18n.t("Finished, but this run did not produce: {what}. "
                       "Saved to History.").format(what=self._shortfall_words()),
                20000)
        else:
            self.statusBar().showMessage("All done — saved to History.", 6000)
        self._finish_queue()
        self._offer_followup(responses, links)

    # ── post-completion follow-up ─────────────────────────────────────────
    def _offer_followup_for_dialog(self, query: str, responses: dict,
                                   stage_agents: dict, links: dict,
                                   artifacts_dir: str = ""):
        """Bridge an add-on dialog's finished run into the post-completion
        follow-up.

        Add-on dialogs (BOQ, and the same gap exists for Reel/Email/Gerber)
        run their own worker chains and never reach _on_run_done, so the
        "anything to change?" refinement the main workbench offers was
        invisible from inside them — you'd finish a BOQ and be offered nothing.
        This primes the same instance state a routed run leaves behind — the
        task label (so the follow-up's "what came back" resolves the file this
        run saved to Artifacts), the stage→agent map (so the note routes to the
        right step), and an empty routing (an add-on's stages are custom_stages,
        not a routed plan) — then hands off to the ordinary _offer_followup. The
        refinement then runs on the workbench and can itself be followed up,
        exactly like any other run's.
        """
        if not responses:
            return
        self._last_query = query
        self._stage_agents = dict(stage_agents or {})
        self.routing = {}
        # The refinement is its own small run, not a continuation of whatever
        # last happened on the workbench: clear the recap accumulators so its
        # completion window shows only the follow-up, not a stale earlier task.
        # The queue counters are deliberately left alone — after any completed
        # run they already read "no more tasks", which is what keeps the loop
        # offering a further follow-up instead of advancing a phantom queue.
        self._stage_results = []
        self._run_shortfall = []
        self._task_runs = []
        self._offer_followup(responses, links or {}, artifacts_dir=artifacts_dir)

    def _offer_followup(self, responses: dict, links: dict = None,
                        artifacts_dir: str = ""):
        """After a whole task finishes, offer a refinement. Prism reads the
        note, works out which step it is about, and sends it to THAT step's
        assigned agent (auto-routed) — resuming the SAME chat that step used,
        and folding in any new attachments. The re-done result comes back and
        this can offer another follow-up.

        Skipped silently when there is nothing to refine or no Groq key to
        route with — the follow-up is a bonus, never a blocker.
        """
        if not responses or not self.cfg.get("api_key"):
            return
        # One session per task, merged across follow-ups. A follow-up runs a
        # single stage, and its completion used to hand THAT stage's
        # responses and links here alone — so the second follow-up knew
        # nothing of the other stages, their tabs, or the reel, and there
        # was no third. The session keeps every stage's latest output and
        # every tab URL for as long as the task is the same one.
        query = getattr(self, "_last_query", "")
        sess = getattr(self, "_followup_session", None)
        if not sess or sess.get("query") != query:
            sess = {"query": query, "responses": {}, "links": {}, "agents": {}, "artifacts_dir": ""}
        if artifacts_dir:
            sess["artifacts_dir"] = artifacts_dir
        elif not sess.get("artifacts_dir"):
            sess["artifacts_dir"] = CB.config.current_run_dir()
        sess["responses"].update({k: v for k, v in responses.items() if v})
        sess["links"].update({k: v for k, v in (links or {}).items() if v})
        sess["agents"].update({k: v for k, v in self._stage_agents.items() if v})
        self._followup_session = sess
        responses, links = dict(sess["responses"]), dict(sess["links"])
        for s, a in sess["agents"].items():
            self._stage_agents.setdefault(s, a)
        self._followup_links = links

        # Anchor current run directory for any follow-up artifacts
        art_dir = sess.get("artifacts_dir") or artifacts_dir or CB.config.current_run_dir()
        if art_dir and os.path.isdir(art_dir):
            CB.config.continue_run(art_dir, task=query)

        # Gather what THIS task PRODUCED, up front. The engine saves every
        # stage's output (the BOQ PDF, the ChatGPT document, generated images)
        # into the task's Artifacts folder, keyed by the task. These files are
        # the REAL deliverable — an agentic tool leaves only messy process notes
        # in the chat — so the dialog SHOWS them as "what came back", and the
        # follow-up CARRIES them into the next step.
        # THIS run's folder — the one the engine opened for it — never the
        # task's whole history. (Filed by the task's words, a follow-up on
        # "make a reel…" once attached twelve files from four runs.)
        artifact_paths = []
        try:
            if art_dir and os.path.isdir(art_dir):
                all_art = [
                    os.path.join(art_dir, n) for n in sorted(os.listdir(art_dir))
                    if os.path.isfile(os.path.join(art_dir, n))
                    and n != CB.config.ABOUT_FILE]
                from dashboard_data import filter_active_artifacts
                artifact_paths = filter_active_artifacts(all_art)
        except Exception:                               # noqa: BLE001
            pass
        from dialogs.followup_dialog import FollowupDialog
        dlg = FollowupDialog(self._result_summary(responses), self,
                             artifacts=artifact_paths)
        dlg.exec()
        if not dlg.submitted():
            return
        self._followup_text = dlg.followup_text()
        self._followup_responses = responses
        # Attachments = files the person just added + the active artifacts this task
        # produced, so a follow-up step builds on the latest real deliverable.
        atts = []
        for p in list(dlg.file_paths()) + artifact_paths:
            if p and p not in {a.get("path") for a in atts}:
                try:
                    atts.append(CB.files.attach(p))
                except Exception:                       # noqa: BLE001
                    pass
        self._followup_attachments = atts
        # Explicit agent name WINS over auto-detect. "give it to Perplexity"
        # means the Perplexity step — not a guess, and not a silent fall-back
        # to "the last AI" when the Groq classify can't run. Only when no agent
        # is named do we ask the classifier what the note is about.
        low = self._followup_text.lower()
        named = next((s for s, agent in self._stage_agents.items()
                      if agent and s in responses and agent.lower() in low),
                     None)
        if named:
            self.statusBar().showMessage(
                i18n.t("Sending your follow-up to {agent}.").format(
                    agent=self._stage_agents[named]), 4000)
            self._on_followup_routed({"steps": [named]})
            return
        # Auto-route: which finished steps does this follow-up need, in what
        # order? A plan, not one step — "make a picture of the new truck and
        # put it in scene 3" is the image tool, then the design chat, then
        # the renderer. A task that filmed a reel offers the classifier two
        # engine-owned steps for that: `artwork` and `reel`.
        reel = self._studio_reel_in(links)
        info = [{"stage": s,
                 "agent": self._stage_agents.get(s, ""),
                 "summary": (texts[0][:160].replace("\n", " ") if texts else "")}
                for s, texts in responses.items()]
        self.statusBar().showMessage(
            i18n.t("Working out which steps your follow-up needs…"), 0)
        worker = FollowupRouteWorker(self._followup_text, info, self.cfg,
                                     reel=bool(reel and links.get("design")))
        worker.done.connect(self._on_followup_routed)
        worker.failed.connect(lambda _e: self._on_followup_routed({}))
        self._workers.append(worker)
        worker.start()

    def _resolve_stage_agent(self, stage: str) -> str:
        """Resolve which tool should run a stage in follow-up."""
        agent = (self._stage_agents.get(stage)
                 or (self.cfg.get("agents") or {}).get(stage))
        if agent:
            return agent
        cats = getattr(CB.agents, "CATEGORIES", {})
        if stage in cats and cats[stage].get("agents"):
            return cats[stage]["agents"][0]
        if stage == "audio":
            return "ElevenLabs"
        if stage == "content":
            return "ChatGPT"
        if stage == "presentation":
            return "Gamma.app"
        return "ChatGPT"

    def _on_followup_routed(self, plan: dict):
        """Carry out the classifier's plan.

        Ordinary steps re-run as one relay — each in the chat it answered
        in, each handed the one before's new output — exactly as a first
        run's stages are. When the plan reaches the reel, the Studio
        follow-up runs last: new pictures made first if asked for, the
        earlier steps' output handed to the design chat as what changed,
        then a re-film. An empty plan on a task that filmed a reel means
        the reel — a change to such a task almost always means the video —
        and otherwise the last step that ran, as before.
        """
        responses = getattr(self, "_followup_responses", {})
        if not responses:
            return
        links = getattr(self, "_followup_links", {}) or {}
        atts = getattr(self, "_followup_attachments", [])
        plan = plan if isinstance(plan, dict) else {}
        steps = [s for s in (plan.get("steps") or []) if isinstance(s, str)]
        reel = self._studio_reel_in(links)
        saved_studio = (reel[2].get("_studio") or {}) if reel else {}
        design_url = (links.get("design") or saved_studio.get("design_url") or "")
        can_reel = bool(reel and design_url)
        images = (plan.get("images") or "").strip() if "artwork" in steps else ""

        low_followup = getattr(self, "_followup_text", "").casefold()

        # Universal capability keywords: if the user explicitly asked for audio,
        # document/summary, or presentation, make sure the corresponding stage is included!
        wants_audio_explicit = any(term in low_followup for term in (
            "audio", "voice", "voiceover", "voice-over", "narration", "speech", "podcast"))
        wants_doc_explicit = any(term in low_followup for term in (
            "doc", "document", "docx", "pdf", "report", "summary", "summarize", "writeup", "write-up"))
        wants_slides_explicit = any(term in low_followup for term in (
            "slide", "deck", "presentation", "powerpoint", "ppt"))

        if wants_audio_explicit and "audio" not in steps:
            steps.append("audio")
        if wants_doc_explicit and "content" not in steps and "content" not in responses:
            steps.insert(0, "content")
        if wants_slides_explicit and "presentation" not in steps:
            steps.append("presentation")

        reel_copy_change = any(term in low_followup for term in (
            "script", "voice-over", "voiceover", "narration", "catchy",
            "ad copy", "advertising copy", "hook", "tagline", "slogan",
            "pro ad", "ad maker", "audio", "voice", "speech"))
        wants_reel = can_reel and (
            not steps or bool({"reel", "artwork", "design", "media"} & set(steps))
            or reel_copy_change or wants_audio_explicit)

        ordinary = [s for s in steps if s not in ("design", "media", "reel", "artwork")]

        if wants_reel:
            agent = (self._stage_agents.get("design")
                     or self._stage_agents.get("brains") or "ChatGPT")
            if ordinary:
                # The other steps first, in their own chats; what they
                # produce is what the design chat is then told has changed.
                maker = ((self.cfg.get("agents") or {}).get("visual")
                         or self._stage_agents.get("visual") or "ChatGPT")
                shown = {s: self._resolve_stage_agent(s) for s in ordinary}
                if images:
                    shown["artwork"] = maker
                shown.update({"design": agent, "media": "Prism Studio"})
                self._start_followup_run(
                    ordinary, atts, plan_agents=shown,
                    then=lambda r, l: self._continue_studio_followup(
                        r, l, reel, design_url, agent, atts, images))
            else:
                self._start_studio_followup(reel, design_url, agent,
                                            atts, images=images)
            return

        # Local footage reel: a script/copy change needs to regenerate voice
        # and re-render the video too — not just re-write the text.
        has_local_mp4 = any(
            isinstance(v, str) and v.lower().endswith(".mp4")
            and not CB.get_reel_edit().is_studio_spec({})
            for v in (links or {}).values())
        has_footage_mp4 = any(
            isinstance(v, str) and (v.lower().endswith(".mp4")
            or "client_reel" in os.path.basename(v))
            for v in (links or {}).values())
        has_audio_stage = "audio" in responses or "audio" in steps or wants_audio_explicit
        has_media_stage = "media" in responses or "reel" in steps
        if (reel_copy_change or wants_audio_explicit) and has_footage_mp4 and (has_audio_stage or has_media_stage):
            # Chain: content re-run → audio re-gen → media re-render
            content_steps = [s for s in (ordinary or [list(responses.keys())[0]])]
            if not content_steps:
                content_steps = ["content"]
            chain_steps = list(content_steps)
            plan_agents = {s: self._resolve_stage_agent(s) for s in chain_steps}
            if has_audio_stage and "audio" not in chain_steps:
                chain_steps.append("audio")
                plan_agents["audio"] = self._resolve_stage_agent("audio")
            if has_media_stage and "media" not in chain_steps:
                chain_steps.append("media")
                plan_agents["media"] = self._stage_agents.get("media", "Prism Studio")
            self.statusBar().showMessage(
                i18n.t("Rewriting script, then regenerating voice and video…"), 0)
            self._set_stage("run")
            self._start_followup_run(chain_steps, atts, plan_agents=plan_agents)
            return

        if not ordinary:
            ordinary = [list(responses.keys())[-1]]     # unsure → the last step
        plan_agents = {s: self._resolve_stage_agent(s) for s in ordinary}
        for s, a in plan_agents.items():
            self._stage_agents[s] = a
        self._set_stage("run")
        self._start_followup_run(ordinary, atts, plan_agents=plan_agents)

    def _followup_prompt(self, stage: str, responses: dict, first: bool) -> str:
        if stage == "audio":
            # Voice-over / audio agents must receive ONLY the spoken words/script,
            # never pipeline instructions, meta wrappers, or chat headers.
            try:
                auto = CB.get_automation()
                voice_fn = getattr(auto, "_voiceover_text", None)
            except Exception:
                voice_fn = None
            voice_sources = [
                t for ts in reversed(list(responses.values()))
                for t in (ts if isinstance(ts, list) else [ts])
                if str(t).strip()
            ]
            spoken = voice_fn(voice_sources) if voice_fn else ""
            if not spoken:
                user_req = getattr(self, "_followup_text", "").strip()
                extracted = voice_fn([user_req]) if voice_fn else ""
                spoken = extracted or user_req
            return spoken

        prior = "\n\n".join(responses.get(stage) or [])
        if not prior.strip():
            # If this stage didn't run previously (e.g. asking for a summary/document
            # or audio on a BOQ/Research deliverable), provide the prior deliverable summary!
            prior = self._result_summary(responses)
        # A finished answer can be an entire document, a long research dump or
        # an exported table. Sending it back verbatim makes the browser
        # composer fall back to slow character-by-character typing when fast
        # insertion refuses the payload. The UI then appears stuck at
        # "prompt 1/1" and the agent never receives the follow-up. Keep both
        # ends: the opening establishes the work and the ending normally holds
        # the final recommendation or deliverable.
        max_prior = 8_000
        if len(prior) > max_prior:
            head = 6_000
            prior = (prior[:head].rstrip()
                     + "\n\n[Earlier result shortened here for the chat]\n\n"
                     + prior[-(max_prior - head):].lstrip())
        att_note = ""
        if getattr(self, "_followup_attachments", None):
            names = [a.get("name") or os.path.basename(a.get("path", ""))
                     for a in self._followup_attachments if isinstance(a, dict) and a.get("path")]
            if names:
                att_note = (
                    f" The latest active deliverable file(s) are attached: "
                    f"{', '.join(names)}. Build upon and use these latest versions, not any earlier drafts."
                )
            else:
                att_note = " New file(s) are attached to this chat — use them."
        chain = ("" if first else
                 " The step before you has been redone for this change — its "
                 "new output is the context above; build on that, not on "
                 "your earlier version alone.")
        return (
            "THIS IS A FOLLOW-UP TO THE TASK ALREADY IN THIS CHAT.\n\n"
            f"The person now wants this change:\n{self._followup_text}\n\n"
            "Do the change now. Give the full updated result, not an outline "
            "or instructions for how to change it.\n\n"
            f"Your earlier result is included only as reference:\n\n{prior}"
            f"{att_note}{chain}")

    def _start_followup_run(self, stages: list, attachments: list,
                            plan_agents: dict = None, then=None):
        """Run the follow-up's steps — one, or a relay of several — reusing
        the run surface, so a follow-up shows and finishes like any other
        run (and can itself offer another follow-up when it completes).
        Each step reopens the SAME conversation it answered in, so it
        continues that chat with its full context instead of starting a
        fresh one. `then(responses, links)` continues a longer plan instead
        of finishing; `plan_agents` is the whole plan, for the timeline."""
        self._is_followup_run = True
        sess = getattr(self, "_followup_session", None)
        if not getattr(self, "_current_run_file", None) and sess and sess.get("run_file"):
            self._current_run_file = sess["run_file"]
        art_dir = (sess.get("artifacts_dir") if sess else "") or CB.config.current_run_dir()
        if art_dir and os.path.isdir(art_dir):
            CB.config.continue_run(art_dir, task=getattr(self, "_last_query", "") or self._followup_text)
        responses = getattr(self, "_followup_responses", {}) or {}
        links = getattr(self, "_followup_links", {}) or {}
        run_agents = {s: (plan_agents or {}).get(s) or self._resolve_stage_agent(s)
                      for s in stages}
        for s, a in run_agents.items():
            self._stage_agents[s] = a
        custom = [(s, run_agents[s], [self._followup_prompt(s, responses, i == 0)])
                  for i, s in enumerate(stages)]
        resume = {s: links[s] for s in stages if links.get(s)}
        cfg_for_run = dict(self.cfg)
        cfg_for_run["agents"] = {**self._stage_agents, **run_agents}
        # Bring the workbench's RUNNING view to the front. A follow-up often
        # starts while the person is looking at the Artifacts screen (checking
        # what came back) — without this the run proceeds on a hidden workbench
        # and there's no way back to it, the "it went off to a new task and I
        # can't get back" bug. The outer screen is forced to the workbench; the
        # inner stack shows RUNNING below.
        self._show_screen("workbench")
        self._set_stage("run")
        self.output_panel.set_plan(
            plan_agents or run_agents, followup=True,
            prior_responses=responses, prior_links=links,
            prior_agents=self._stage_agents)
        self.output_panel.set_task(self._followup_text)
        self.input_panel.set_state("running")
        self._run_finished = False
        self.output_panel.set_finished(False)
        self.output_panel.set_running(True)
        self.work_stack.setCurrentIndex(RUNNING)
        self._stage_results = []
        self._run_shortfall = []
        self._task_runs = []
        worker = AutomationWorker(
            self.routing, cfg_for_run, attachments, self._followup_text,
            custom_stages=custom, resume_urls=resume or None, followup=True,
            chatgpt_analysis=False, prior_responses=responses)
        awake.acquire()
        self._active_run = worker
        worker.stage_event.connect(self._on_stage_event)
        worker.done.connect(then if then is not None else self._on_run_done)
        worker.failed.connect(self._on_run_failed)
        self._workers.append(worker)
        worker.start()

    def _continue_studio_followup(self, responses: dict, links: dict, reel,
                                  design_url: str, agent: str, atts: list,
                                  images: str):
        """The second half of a plan that ends at the reel: the earlier
        steps have re-run, and their new output is what the design chat is
        told has changed. Their results are banked first — History keeps
        the whole follow-up, not just the film."""
        awake.release()
        self._active_run = None
        self._save_run(responses, links)
        sess = getattr(self, "_followup_session", None)
        if sess:
            sess["responses"].update({k: v for k, v in responses.items() if v})
            sess["links"].update({k: v for k, v in links.items() if v})
        self._followup_links = {**(getattr(self, "_followup_links", {}) or {}),
                                **{k: v for k, v in links.items() if v}}
        audio_path = (links or {}).get("audio")
        if audio_path and os.path.exists(audio_path):
            try:
                atts = list(atts) + [CB.files.attach(audio_path)]
            except Exception:
                atts = list(atts) + [{"path": audio_path, "name": os.path.basename(audio_path)}]
        context = "\n\n".join(
            f"[{s.upper()}]\n" + "\n\n".join(t for t in texts if t)
            for s, texts in responses.items() if texts)
        self._start_studio_followup(reel, design_url, agent, atts,
                                    images=images, context=context,
                                    fresh_panel=False)

    # ── a follow-up on a Studio reel ──────────────────────────────────────
    def _studio_reel_in(self, links: dict):
        """(mp4, spec path, spec) when this task filmed a Studio reel — the
        saved design beside the video is what a follow-up changes."""
        import json as _json

        # 1. Prefer explicit 'media' stage in links if present
        media_cand = (links or {}).get("media")
        candidates_urls = [media_cand] if media_cand else []
        candidates_urls.extend([v for v in (links or {}).values() if v != media_cand])

        for url in candidates_urls:
            if not (isinstance(url, str) and url.lower().endswith(".mp4")
                    and paths.is_local_result(url)):
                continue
            spec_path = url[:-4] + ".json"
            if not os.path.exists(spec_path):
                continue
            try:
                with open(spec_path, encoding="utf-8") as f:
                    spec = _json.load(f)
            except (OSError, ValueError):
                continue
            if CB.get_reel_edit().is_studio_spec(spec):
                return url, spec_path, spec

        # 2. Check the current task's artifacts directory for the latest reel & spec
        sess = getattr(self, "_followup_session", None)
        art_dir = (sess.get("artifacts_dir") if sess else "") or CB.config.current_run_dir()
        if art_dir and os.path.isdir(art_dir):
            try:
                mp4s = sorted(
                    [os.path.join(art_dir, f) for f in os.listdir(art_dir)
                     if f.lower().endswith(".mp4") and os.path.isfile(os.path.join(art_dir, f))],
                    key=lambda p: os.path.getmtime(p), reverse=True)
                for mp4 in mp4s:
                    spec_path = mp4[:-4] + ".json"
                    if os.path.isfile(spec_path):
                        try:
                            with open(spec_path, encoding="utf-8") as f:
                                spec = _json.load(f)
                            if CB.get_reel_edit().is_studio_spec(spec):
                                return mp4, spec_path, spec
                        except Exception:
                            pass
            except Exception:
                pass
        # An export failure has no media link, but its project was saved
        # before encoding. Recover only the exact design conversation; using
        # the newest reel globally could send a change to another client's job.
        design_url = str((links or {}).get("design") or "").strip().rstrip("/")
        if not design_url:
            return None
        import pathlib
        try:
            candidates = sorted(pathlib.Path(CB.config.RUNS_DIR).glob("reel_*.json"),
                                key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for candidate in candidates:
            try:
                with candidate.open(encoding="utf-8") as f:
                    spec = _json.load(f)
                if not isinstance(spec, dict):
                    continue
                saved_url = str((spec.get("_studio") or {}).get("design_url") or "")
                if saved_url.strip().rstrip("/") != design_url:
                    continue
                if CB.get_reel_edit().is_studio_spec(spec):
                    return str(candidate.with_suffix(".mp4")), str(candidate), spec
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return None

    def _start_studio_followup(self, reel, design_url: str, agent: str,
                               attachments: list, images: str = "",
                               context: str = "", fresh_panel: bool = True):
        """Ask for the change in the reel's own design conversation and
        re-film it — after making any picture asked for. Runs on the
        workbench like any other follow-up, and offers another when it
        finishes — with the new cut as the reel the next one changes.
        `fresh_panel` is False when this continues a longer plan whose
        earlier steps are already on the timeline."""
        _mp4, _spec_path, spec = reel
        run_agents = {"design": agent, "media": "Prism Studio"}
        if images:
            maker = ((self.cfg.get("agents") or {}).get("visual")
                     or self._stage_agents.get("visual") or "ChatGPT")
            run_agents = {"artwork": maker, **run_agents}
        self._show_screen("workbench")
        self._set_stage("run")
        if fresh_panel:
            responses = getattr(self, "_followup_responses", {}) or {}
            links = getattr(self, "_followup_links", {}) or {}
            self.output_panel.set_plan(
                run_agents, followup=True,
                prior_responses=responses, prior_links=links,
                prior_agents=self._stage_agents)
            self.output_panel.set_task(self._followup_text)
            self._stage_results = []
            self._run_shortfall = []
            self._task_runs = []
        self.input_panel.set_state("running")
        self._run_finished = False
        self.output_panel.set_finished(False)
        self.output_panel.set_running(True)
        self.work_stack.setCurrentIndex(RUNNING)
        self.statusBar().showMessage(
            i18n.t("Making the picture first…") if images else
            i18n.t("Reopening the reel's design conversation…"), 0)
        worker = StudioFollowupWorker(self.cfg, spec, agent, design_url,
                                      self._followup_text, attachments,
                                      images=images, context=context,
                                      task=getattr(self, "_last_query", ""),
                                      title=(self.routing or {}).get("_title", ""))
        awake.acquire()
        self._active_run = worker
        worker.stage_event.connect(self._on_stage_event)
        worker.progress.connect(lambda d, t: self.statusBar().showMessage(
            i18n.t("Filming the changed reel… {p}%").format(
                p=int(d / max(1, t) * 100))))
        worker.done.connect(self._on_studio_followup_done)
        worker.failed.connect(self._on_run_failed)
        self._workers.append(worker)
        worker.start()

    def _on_studio_followup_done(self, out: str, spec_path: str, note: str):
        try:
            saved = CB.config.save_artifact(out, self._last_query, kind="reel",
                                            task=self._last_query)
        except Exception:                               # noqa: BLE001
            saved = out
        if spec_path and os.path.isfile(spec_path):
            try:
                import shutil
                dest_json = os.path.splitext(saved)[0] + ".json"
                if os.path.abspath(spec_path) != os.path.abspath(dest_json):
                    shutil.copy2(spec_path, dest_json)
            except OSError:
                pass
        design_url = (getattr(self, "_followup_links", {}) or {}).get(
            "design", "")
        # Through the ordinary completion path — History, the completion
        # window, and the offer of another follow-up. `media` now points at
        # the new cut, so that is the reel the next follow-up changes.
        self._on_run_done({"design": [note], "media": [note]},
                          {"design": design_url, "media": saved or out})

    def _result_summary(self, responses: dict) -> str:
        """Recap for the follow-up dialog: the FINAL result first, then the
        earlier steps — each labelled by what it did, in the run's real
        execution order. Earlier this showed whichever step happened to be
        first non-empty, which surfaced the research step instead of the
        finished deliverable; and a task with several outputs must show them
        all, not just one."""
        from widgets.agents_panel import STAGE_COPY
        # `_stage_agents` is filled in execution order from stage_start events;
        # its last key is the final step. Fall back to the responses' own order.
        order = list(self._stage_agents.keys()) or list(responses.keys())
        # Any responded step not in that order (defensive) goes first-run-order.
        for s in responses:
            if s not in order:
                order.append(s)
        parts = []
        for stage in reversed(order):               # final step leads
            body = "\n\n".join(t for t in (responses.get(stage) or [])
                               if t and t.strip())
            if not body:
                continue
            title = (STAGE_COPY.get(stage) or (None, stage.title()))[1]
            clip = body[:900] + ("…" if len(body) > 900 else "")
            parts.append(f"▸ {title}\n{clip}")
        return "\n\n".join(parts)

    def _on_run_failed(self, error: str):
        awake.release()
        self._active_run = None
        self.agents_panel.set_run_enabled(True)
        self.output_panel.set_running(False)
        self.input_panel.set_state("planned")
        self._set_stage("plan")
        self._clear_active_run()
        # A failed run is still consumption — it drove browsers and spent Groq
        # tokens — and it is the more interesting half of the usage data.
        licensing.report_usage(getattr(self, "_run_id", ""))
        # Kept too — a run that broke halfway is exactly the one you want to
        # go back and read later.
        self._save_run(error=error)
        self._record_task_run(failed=error)

        # Tasks are independent, so one broken pipeline is not a reason to
        # abandon the four the customer queued behind it. Report it in the
        # status bar rather than a modal — a dialog per failure in a ten-task
        # queue would need ten dismissals before anything else could run.
        if self._more_tasks():
            self.statusBar().showMessage(
                f"Task {self._task_pos} failed ({error}) — carrying on.", 8000)
            self._advance_queue()
            return

        self._explain(error, "run")
        self._finish_queue()

    # ── wake word ─────────────────────────────────────────────────────────────
    def toggle_wakeword(self, on: bool):
        if on:
            if not self.cfg.get("api_key"):
                QMessageBox.warning(self, "Wake word", "Set your Groq API key in Setup first.")
                self.sidebar.set_listening(False)
                return
            # Packaged builds ship without PortAudio (it's a system library, not
            # a wheel), so say what's missing instead of failing silently.
            ok, why = wakeword.available()
            if not ok:
                QMessageBox.warning(self, "Wake word", why)
                self.sidebar.set_listening(False)
                return
            self._wake_listener = WakeWordListener(self.cfg)
            self._wake_listener.heard.connect(self._on_wake_heard)
            self._wake_listener.error.connect(
                lambda e: QMessageBox.warning(self, "Wake word", e))
            self._wake_listener.start()
            self.statusBar().showMessage('Listening for "Prism"…')
        elif self._wake_listener:
            _retire_listener(self._wake_listener)
            self._wake_listener = None
            self.statusBar().showMessage("Wake word off.", 3000)

    def _on_wake_heard(self):
        self.statusBar().showMessage('Heard "Prism" — starting a take…', 3000)
        if self._record_worker is None:
            self._toggle_mic()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "lumi_overlay"):
            self.lumi_overlay.reposition()

    def keyPressEvent(self, event):
        """Enter does what the screen's main button does.

        The task flow could only be moved on with the mouse: "Make a plan" and
        "Start the work" were buttons and nothing else. A key the focused widget
        did not use travels up to here, so this only ever sees an Enter that
        nobody typed into a box or pressed on a button. See _enter_pressed.
        """
        if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                and not event.isAutoRepeat()        # holding Enter must not repeat it
                and not (event.modifiers() & ~Qt.KeypadModifier)
                and self._enter_pressed()):
            event.accept()
            return
        super().keyPressEvent(event)

    def _enter_pressed(self) -> bool:
        """Act on a bare Enter on the New task screen; True when it did.

        Text boxes, drop-downs and lists keep their own Enter. A focused button
        is pressed, whichever it is, so Enter on Discard never starts the run.
        With nothing of the kind focused, Enter is the screen's next step: Start
        the work once there is a plan, Make a plan before that.
        """
        if self.screens.currentIndex() != WORKBENCH:
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox,
                              QAbstractItemView, QAbstractSpinBox)):
            return False
        if (isinstance(focus, QAbstractButton) and focus.isEnabled()
                and focus.isVisible()
                and focus not in (self.agents_panel.run_btn, self.input_panel.route_btn)):
            focus.click()
            return True
        run = self.agents_panel.run_btn
        if run.isVisible() and run.isEnabled():
            run.click()
            return True
        route = self.input_panel.route_btn
        if route.isVisible() and route.isEnabled():
            # Cancel is the same button while planning; Enter must not mean that.
            self.input_panel._submit_from_keyboard()
            return True
        return False

    def closeEvent(self, event):
        self._stop_reel_editor()
        worker = getattr(self, "_reel_edit_worker", None)
        if worker is not None and worker.isRunning():
            if not worker.wait(8000):
                worker.terminate()
                worker.wait(1000)
        if self._wake_listener:
            # Longer than the toggle case: the app is going away, so a brief
            # stall costs nothing, while a listener still running when the
            # process tears down is the abort itself.
            _retire_listener(self._wake_listener, wait_ms=8000)
            self._wake_listener = None
        # Anything metered but not yet sent — a run that ended just before the
        # window closed, or events buffered while the server was unreachable.
        licensing.report_usage(getattr(self, "_run_id", ""))
        # An unbalanced acquire (window closed mid-run) would otherwise leave
        # `caffeinate` alive after Prism has gone, and the machine would never
        # sleep again until reboot.
        awake.release_all()
        # The support assistant keeps its own worker — wound up here beside
        # everything else, or its thread aborts the teardown the same way.
        self.support_panel.shutdown()
        if getattr(self, "step_work", None) is not None:
            self.step_work.shutdown()
        if hasattr(self, "lumi_panel"):
            self.lumi_panel.shutdown()
        # Every worker still running has to be stopped and JOINED before the
        # process is allowed to tear down.
        #
        # Skipping this does not leak quietly — it aborts. Qt's ~QThread calls
        # qFatal() on a thread that is still running, and PySide destroys every
        # QThread during interpreter shutdown, so closing Prism mid-run ends in
        # "Python quit unexpectedly" with a macOS crash report. The user sees a
        # crash; the log's last line is a perfectly ordinary "Prism closed".
        #
        # Reported as exactly that: a Studio run was four seconds into a
        # ChatGPT stage when the window closed, and Prism aborted.
        self._retire_workers()
        diagnostics.write("INFO", "--- Prism closed ---")
        event.accept()

    # How long to wait for a worker to notice it should stop. A routed run is
    # inside a Selenium poll that can be several seconds wide, so a short wait
    # would time out and abort anyway; ten seconds covers the widest of them.
    _WORKER_WAIT_MS = 10_000

    def _retire_workers(self):
        """Ask every live worker to stop, then wait for it.

        Ordered stop-all-then-wait-all rather than stop-and-wait each: the
        waits then overlap, so three stuck workers cost ten seconds between
        them instead of thirty.
        """
        # The window's own list is not every worker there is: a panel such as
        # Leads starts its own enrichment, search and send workers, which
        # register only in the shared `workers._running` set. Retiring just
        # this list left those threads alive into teardown — the process
        # abort this method exists to prevent (review finding 3, 2026-10-01).
        import workers as _workers
        seen: set = set()
        live = []
        for w in [*self._workers, *list(_workers._running)]:
            if w is None or id(w) in seen:
                continue
            seen.add(id(w))
            if _is_running(w):
                live.append(w)
        if not live:
            return
        diagnostics.write("INFO", f"stopping {len(live)} worker(s) before exit")

        for worker in live:
            stop = getattr(worker, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:               # noqa: BLE001
                    pass    # a worker that cannot be asked still gets waited on

        for worker in live:
            try:
                if not worker.wait(self._WORKER_WAIT_MS):
                    # Out of options. terminate() is unsafe in general, but the
                    # alternative here is a guaranteed abort a moment later, and
                    # a killed thread in a process that is exiting anyway can
                    # corrupt nothing that outlives it.
                    diagnostics.write(
                        "WARN", f"{type(worker).__name__} did not stop in "
                                f"{self._WORKER_WAIT_MS}ms — terminating it")
                    worker.terminate()
                    worker.wait(2000)
            except RuntimeError:
                pass        # already gone; nothing to wait for
        self._workers.clear()

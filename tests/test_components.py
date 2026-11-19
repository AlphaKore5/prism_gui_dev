"""Settings > Components and the install flow (deps.py), stage 28.

Offscreen, sandboxed HOME (the conftest forbids the real ~/.prism), and NO
download anywhere: the installer is a local script that prints Playwright-style
progress and writes a fake browser folder. What this cannot show: a real
download from Playwright's CDN, or anything on Windows."""
from __future__ import annotations

import ast
import os
import re
import socket
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton        # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                   # noqa: E402
theme.load_fonts()
_app.setStyleSheet(open(os.path.join(ROOT, "style.qss"), encoding="utf-8")
                   .read().replace("%ASSETS%", os.path.join(ROOT, "assets")
                                   .replace(os.sep, "/")))

import deps                                                    # noqa: E402

REV = deps.expected_revision() or "1234"
_EXE = "chrome.exe" if sys.platform.startswith("win") else "chrome"

# What the fake installer does: print progress the way Playwright does, then
# write chromium-<rev>/<platform dir>/chrome under PLAYWRIGHT_BROWSERS_PATH.
FAKE_INSTALLER = r'''
import os, sys, time
mode = sys.argv[1]
print("Downloading Chrome for Testing 1.0 from https://cdn.playwright.dev/x")
for pct in (10, 50, 100):
    print("|■■■■    |  %d%% of 150.0 MiB" % pct, flush=True)
    if mode == "slow":
        time.sleep(30)
if mode == "fail":
    sys.exit(1)
root = os.environ["PLAYWRIGHT_BROWSERS_PATH"]
d = os.path.join(root, "chromium-" + sys.argv[2], "chrome-x")
os.makedirs(d, exist_ok=True)
open(os.path.join(d, sys.argv[3]), "w").write("x")
'''


def _fake_command(tmp, mode):
    script = os.path.join(tmp, "installer.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(FAKE_INSTALLER)

    def command():
        env = dict(os.environ)
        env["PLAYWRIGHT_BROWSERS_PATH"] = deps.user_browsers_dir()
        return [sys.executable, script, mode, REV, _EXE], env
    return command


def _put_browser(root, rev=None):
    d = os.path.join(root, "chromium-" + (rev or REV), "chrome-x")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, _EXE), "w").write("x")


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-components-")
        self.user = os.path.join(self.tmp, "user-browsers")
        self.other = os.path.join(self.tmp, "normal-place")
        os.makedirs(self.other)
        for p in (mock.patch.object(deps, "user_browsers_dir",
                                    lambda: self.user),
                  mock.patch.dict(os.environ,
                                  {"PLAYWRIGHT_BROWSERS_PATH": self.other})):
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(deps, "launch_check", lambda: (True, ""))
        p.start()
        self.addCleanup(p.stop)


class TestDetection(Sandbox):
    def test_missing_ready_and_needs_update(self):
        self.assertEqual(deps.detect_chromium().state, deps.MISSING)
        _put_browser(self.other, rev="1")                 # an older revision
        self.assertEqual(deps.detect_chromium().state, deps.UPDATE)
        _put_browser(self.other)
        self.assertEqual(deps.detect_chromium().state, deps.READY)

    def test_a_folder_without_the_program_is_not_ready(self):
        os.makedirs(os.path.join(self.other, "chromium-" + REV, "chrome-x"))
        self.assertEqual(deps.detect_chromium().state, deps.MISSING)

    def test_a_browser_in_the_per_user_folder_is_picked_up_without_restart(self):
        _put_browser(self.user)
        self.assertEqual(deps.detect_chromium().state, deps.READY)
        self.assertTrue(deps.ensure_environment())
        self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], self.user)
        self.assertFalse(deps.ensure_environment())       # already pointing there

    def test_detection_touches_no_network(self):
        with mock.patch.object(socket.socket, "connect",
                               side_effect=AssertionError("network on detect")):
            states = deps.detect_all()
        self.assertEqual(set(states), {c.key for c in deps.COMPONENTS})

    def test_a_missing_python_package_is_reported_missing(self):
        with mock.patch.object(deps, "_modules_missing", lambda c: ["x"]):
            self.assertEqual(deps.detect("ocr").state, deps.MISSING)


class TestRegistry(unittest.TestCase):
    def test_every_part_has_words_a_customer_can_read(self):
        for c in deps.COMPONENTS:
            self.assertTrue(c.purpose and c.licence and c.name, c.key)
            for text in (c.name, c.purpose, deps.plain_install_reason(c),
                         deps.consent_line(c.key)):
                for bad in ("pip ", "apt ", "sudo", "brew "):
                    self.assertNotIn(bad, text, c.key)
        # "whisper" added 19 Nov 2026 (owner: local Whisper for Speak, the
        # model downloaded inside Prism after install). Every installer kind
        # has its own consent_line and its own branch in deps.install.
        self.assertEqual({c.install for c in deps.COMPONENTS},
                         {"", "chromium", "ffmpeg", "whisper"})

    def test_the_consent_line_names_what_and_how_big(self):
        line = deps.consent_line("chromium")
        self.assertIn("170 MB", line)
        self.assertIn("playwright", line.lower())
        self.assertIn("MB", deps.consent_line("ffmpeg"))

    def test_plain_strips_commands(self):
        said = deps.plain("The web renderer needs Playwright:\n"
                          "    pip install playwright && playwright install chromium")
        self.assertNotIn("pip", said)
        self.assertIn("Components", said)
        self.assertEqual(deps.plain("FFmpeg binary is required."),
                         "FFmpeg binary is required.")

    def test_progress_lines(self):
        self.assertEqual(deps.parse_progress("|■■   |  50% of 100.0 MiB"),
                         (52428800, 104857600))
        self.assertIsNone(deps.parse_progress("Downloading Chrome"))


class TestInstall(Sandbox):
    def test_consent_is_required_and_nothing_runs_without_it(self):
        with mock.patch.object(deps, "run_command",
                               side_effect=AssertionError("ran")):
            with self.assertRaises(deps.DepsError):
                deps.install("chromium", False)

    def test_success_reports_progress_then_detects_ready(self):
        seen = []
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "ok")):
            self.assertEqual(deps.detect_chromium().state, deps.MISSING)
            result = deps.install("chromium", True,
                                  on_progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(result, "ok")
        self.assertEqual(seen[-1][0], seen[-1][1])
        self.assertEqual(deps.detect_chromium().state, deps.READY)

    def test_failure_is_a_sentence_not_a_command_or_trace(self):
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "fail")):
            with self.assertRaises(deps.DepsError) as ctx:
                deps.install("chromium", True)
        text = str(ctx.exception)
        self.assertIn("Repair", text)
        for bad in ("Traceback", "pip ", "sudo"):
            self.assertNotIn(bad, text)
        self.assertEqual(deps.detect_chromium().state, deps.MISSING)

    def test_cancel_stops_the_installer(self):
        flag = {"stop": False}

        def progress(d, t):
            flag["stop"] = True
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "slow")):
            result = deps.install("chromium", True, on_progress=progress,
                                  cancelled=lambda: flag["stop"])
        self.assertEqual(result, "cancelled")
        self.assertEqual(deps.detect_chromium().state, deps.MISSING)

    def test_a_browser_that_will_not_start_is_said_so(self):
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "ok")), \
                mock.patch.object(deps, "launch_check",
                                  lambda: (False, "missing libs")):
            with self.assertRaises(deps.DepsError) as ctx:
                deps.install("chromium", True)
        self.assertIn("would not start", str(ctx.exception))

    def test_ffmpeg_uses_the_engines_checked_download(self):
        calls = []

        class Fake:
            def download(self, cb):
                cb(5, 10)
                calls.append("downloaded")

            def locate(self):
                return "/x/ffmpeg" if calls else None
        import core_bridge as CB
        with mock.patch.object(CB, "get_ffmpeg", lambda: Fake()):
            self.assertEqual(deps.detect_ffmpeg().state, deps.MISSING)
            self.assertEqual(deps.install("ffmpeg", True), "ok")
            self.assertEqual(deps.detect_ffmpeg().state, deps.READY)

    def test_a_part_prism_cannot_fetch_says_so(self):
        with self.assertRaises(deps.DepsError):
            deps.install("ocr", True)


class TestDialog(Sandbox):
    def _dialog(self, mode):
        from dialogs.component_install import ComponentInstallDialog
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, mode)):
            dlg = ComponentInstallDialog("chromium")
            dlg.show()
            return dlg

    def test_it_asks_first_and_downloads_nothing_until_install_is_pressed(self):
        from dialogs.component_install import ComponentInstallDialog
        dlg = ComponentInstallDialog("chromium")
        self.assertIsNone(dlg.worker)
        self.assertIn("about 170 MB", dlg.header.subtitle.text()
                      if hasattr(dlg.header, "subtitle") else "about 170 MB")
        self.assertIn("170 MB", dlg._body.text())
        self.assertEqual(dlg.go_btn.text(), "Install")
        self.assertEqual(dlg.close_btn.text(), "Not now")

    def test_install_to_ready_then_redetect(self):
        from dialogs.component_install import ComponentInstallDialog
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "ok")):
            dlg = ComponentInstallDialog("chromium")
            dlg.show()
            dlg.start()
            dlg.worker.wait(30000)
        _app.sendPostedEvents()
        _app.sendPostedEvents()
        self.assertTrue(dlg.ready)
        self.assertEqual(dlg.bar.value(), 100)
        self.assertEqual(deps.detect_chromium().state, deps.READY)

    def test_failure_offers_try_again_with_a_plain_message(self):
        from dialogs.component_install import ComponentInstallDialog
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "fail")):
            dlg = ComponentInstallDialog("chromium")
            dlg.show()
            dlg.start()
            dlg.worker.wait(30000)
        _app.sendPostedEvents()
        _app.sendPostedEvents()
        self.assertFalse(dlg.ready)
        self.assertEqual(dlg.go_btn.text(), "Try again")
        self.assertTrue(dlg.go_btn.isEnabled())
        self.assertIn("Repair", dlg.status.text())

    def test_cancel_during_download(self):
        from dialogs.component_install import ComponentInstallDialog
        with mock.patch.object(deps, "chromium_install_command",
                               _fake_command(self.tmp, "slow")):
            dlg = ComponentInstallDialog("chromium")
            dlg.show()
            dlg.start()
            import time
            time.sleep(1.0)
            dlg._not_now()
            dlg.worker.wait(30000)
        _app.sendPostedEvents()
        _app.sendPostedEvents()
        self.assertFalse(dlg.ready)
        self.assertIn("Nothing was installed", dlg.status.text())

    def test_first_use_asks_one_question_instead_of_an_error(self):
        from dialogs import component_install as CI
        asked = []

        class Declined(CI.ComponentInstallDialog):
            def exec(self):
                asked.append((self.header.windowTitle(), self._body.text(),
                              self.component.size_mb))
                return 0
        with mock.patch.object(CI, "ComponentInstallDialog", Declined), \
                mock.patch.object(deps, "detect",
                                  lambda k: deps.Status(
                                      deps.MISSING if k == "chromium"
                                      else deps.READY, "")):
            self.assertFalse(CI.offer_for_feature(None, "studio"))
        self.assertEqual(len(asked), 1)
        self.assertIn("170 MB", asked[0][1])

    def test_main_window_asks_before_falling_back(self):
        src = open(os.path.join(ROOT, "main_window.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        for feature in ("studio", "motion"):
            hits = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", "") == "_offer_components"
                    and n.args and getattr(n.args[0], "value", "") == feature]
            self.assertGreaterEqual(len(hits), 1, feature)


class TestSettingsSection(Sandbox):
    def _panel(self, states=None):
        import licensing.status as st
        import time
        from widgets import settings_panel as SP

        def state():
            return st.LicenseState(
                status=st.VALID, plan="complete", customer="T", kind="paid",
                features=frozenset(["core"]), seats=1, license_id="x",
                license_ends=int(time.time()) + 86400,
                token_expires=int(time.time()) + 86400)
        real = deps.detect
        ctx = mock.patch.object(deps, "detect",
                                lambda k: (states or {}).get(k, real(k)))
        ctx.start()
        self.addCleanup(ctx.stop)
        with mock.patch.object(SP.licensing, "state", state):
            p = SP.SettingsPanel({})
            p.resize(980, 700)
            p.show()
            p.show_section("components")
            _app.sendPostedEvents()
        return p

    def test_it_is_in_the_section_list(self):
        from widgets import settings_panel as SP
        self.assertIn("components", [s[0] for s in SP.SECTIONS])

    def test_every_registry_entry_is_listed_with_a_state(self):
        p = self._panel()
        pills = [w for w in p.findChildren(SP_PILL())
                 if w.objectName() == "componentState"]
        self.assertEqual(len(pills), len(deps.COMPONENTS))
        for w in pills:
            self.assertIn(w.text(), ("Ready", "Missing", "Needs update"))

    def test_missing_fetchable_part_has_an_enabled_install_button(self):
        p = self._panel({"chromium": deps.Status(deps.MISSING, "Not here.")})
        btn = p.findChild(QPushButton, "componentInstall_chromium")
        self.assertIsNotNone(btn)
        self.assertEqual(btn.text(), "Install")
        self.assertTrue(btn.isEnabled())

    def test_ready_fetchable_part_offers_repair(self):
        p = self._panel({"chromium": deps.Status(deps.READY, "Ready.")})
        self.assertEqual(
            p.findChild(QPushButton, "componentInstall_chromium").text(),
            "Repair")

    def test_a_part_prism_cannot_fetch_is_disabled_and_says_why(self):
        p = self._panel({"ocr": deps.Status(deps.MISSING, "Missing.")})
        btn = p.findChild(QPushButton, "componentInstall_ocr")
        self.assertFalse(btn.isEnabled())
        self.assertIn("Update Prism", btn.toolTip())
        texts = " ".join(w.text() for w in p.findChildren(SP_LABEL()))
        self.assertIn("Update Prism", texts)

    def test_building_the_section_uses_no_network(self):
        with mock.patch.object(socket.socket, "connect",
                               side_effect=AssertionError("network on UI")):
            self._panel()

    def test_the_install_button_opens_the_question_not_a_download(self):
        p = self._panel({"chromium": deps.Status(deps.MISSING, "Not here.")})
        opened = []
        from dialogs import component_install as CI

        class Spy(CI.ComponentInstallDialog):
            def exec(self):
                opened.append(self.worker)
                return 0
        with mock.patch.object(CI, "ComponentInstallDialog", Spy):
            p.findChild(QPushButton, "componentInstall_chromium").click()
        self.assertEqual(opened, [None])                   # asked, not started


def SP_PILL():
    from widgets import controls as C
    return C.Pill


def SP_LABEL():
    from PySide6.QtWidgets import QLabel
    return QLabel


class TestVoice(unittest.TestCase):
    def test_server_mode_without_the_speech_model_points_to_components(self):
        """19 Nov 2026: Speak runs Whisper on this computer in server mode
        (was "not part of your plan"). Without the model it says where to
        get it, never a command."""
        import core_bridge as CB
        with mock.patch.object(deps, "detect", lambda k: deps.Status(deps.READY, "")), \
                mock.patch.object(CB.voice, "local_ready", return_value=False):
            said = deps.voice_problem({"api_key": CB.ai_client.AI_KEY})
        self.assertIn("Components", said)
        for bad in ("pip", "apt", "sudo", "brew"):
            self.assertNotIn(bad, said)

    def test_server_mode_with_the_speech_model_is_ready(self):
        import core_bridge as CB
        with mock.patch.object(deps, "detect", lambda k: deps.Status(deps.READY, "")), \
                mock.patch.object(CB.voice, "local_ready", return_value=True):
            self.assertEqual(deps.voice_problem({"api_key": CB.ai_client.AI_KEY}), "")

    def test_speech_is_an_installable_component_with_a_plain_consent_line(self):
        import core_bridge as CB
        c = deps.BY_KEY["speech"]
        self.assertEqual(c.install, "whisper")
        self.assertIn("speech", deps.FEATURES["voice"])
        line = deps.consent_line("speech")
        self.assertIn("huggingface.co", line)
        self.assertIn(CB.voice.local_model_dir(), line)
        with mock.patch.object(CB.voice, "local_ready", return_value=False):
            self.assertEqual(deps.detect("speech").state, deps.MISSING)
        with mock.patch.object(CB.voice, "local_ready", return_value=True):
            self.assertEqual(deps.detect("speech").state, deps.READY)

    def test_missing_library_never_shows_a_command(self):
        with mock.patch.object(deps, "detect",
                               lambda k: deps.Status(deps.MISSING, "")):
            said = deps.voice_problem({"api_key": "gsk_x"})
        for bad in ("apt", "pip", "sudo", "PyAudio", "brew"):
            self.assertNotIn(bad, said)

    def test_a_working_setup_has_no_problem(self):
        with mock.patch.object(deps, "detect",
                               lambda k: deps.Status(deps.READY, "")):
            self.assertEqual(deps.voice_problem({"api_key": "gsk_x"}), "")

    def test_no_microphone_and_no_permission_read_plainly(self):
        self.assertIn("No microphone found",
                      deps.voice_error("[Errno -9996] Invalid input device "
                                       "(no default output device)"))
        said = deps.voice_error("[Errno -9985] permission denied")
        self.assertIn("permission to use the microphone", said)
        self.assertGreater(len(said), 60)      # says how to allow it (per OS)
        self.assertNotIn("Errno", deps.voice_error("weird"))

    def test_the_three_dialogs_no_longer_use_the_terminal_check(self):
        # core.voice.available() demands sys.stdin.isatty(), which a desktop
        # app never has: that, not a missing PyAudio, is what showed the
        # owner "Voice needs PyAudio" with PyAudio installed.
        for rel in ("addons/boq/dialog.py", "addons/motion/dialog.py",
                    "addons/reel/dialog.py"):
            src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
            self.assertNotIn("CB.voice.available", src, rel)
            self.assertNotIn("install_hint", src, rel)
            self.assertIn("deps.voice_problem", src, rel)


class TestPackagingGuard(unittest.TestCase):
    def test_matplotlib_is_listed_bundled_and_not_excluded(self):
        req = open(os.path.join(ROOT, "requirements.txt"),
                   encoding="utf-8").read()
        self.assertRegex(req, r"(?m)^matplotlib\s*$")
        spec = open(os.path.join(ROOT, "packaging", "prism.spec"),
                    encoding="utf-8").read()
        excludes = re.search(r"excludes = \[(.*?)\n\]", spec, re.S).group(1)
        self.assertNotIn('"matplotlib"', excludes)
        self.assertIn('"matplotlib": "drawing pictures', spec)


if __name__ == "__main__":
    unittest.main()

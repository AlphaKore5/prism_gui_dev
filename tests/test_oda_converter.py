"""Stage 25: the DWG converter flow (detect, choose, install from Prism) and the shared
'Send to Prism AI' consent in BOQ. No real download, no installer launched, no real ~/.prism."""
from __future__ import annotations
import http.server, os, platform, sys, tempfile, threading, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s25-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QLabel, QFileDialog      # noqa: E402
_app = QApplication.instance() or QApplication([])

import core_bridge as CB                                              # noqa: E402
from addons.boq import converter_setup as CS                          # noqa: E402
from addons.boq import converter_dialog as CD                         # noqa: E402
from widgets import send_to_ai as S                                   # noqa: E402
from dialogs.send_consent import SendConsentDialog as SCD             # noqa: E402

boq = CB.get_boq()
MSI = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 5000


def _exe(*parts):
    path = os.path.join(*parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x")
    os.chmod(path, 0o755)
    return path


class _Env(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="prism-s25-")
        self._saved = {k: os.environ.get(k) for k in
                       (boq.ENV_CONVERTER, "PROGRAMFILES", "PROGRAMFILES(X86)",
                        "PROGRAMW6432", "LOCALAPPDATA", "HOME", "USERPROFILE")}
        os.environ.pop(boq.ENV_CONVERTER, None)
        # The shipped default is OFF (ODA's terms are unconfirmed); the install flow is tested as if on.
        p = mock.patch.object(CS, "INSTALL_FROM_PRISM", True)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ShippedDefault(unittest.TestCase):
    def test_install_from_prism_is_off_until_oda_allows_it(self):
        self.assertFalse(CS.INSTALL_FROM_PRISM)
        self.assertIsNone(CS.installer_url())


class Detection(_Env):
    def _windows(self):
        return mock.patch.object(boq.platform, "system", return_value="Windows")

    def test_windows_versioned_folder_in_program_files(self):
        pf = os.path.join(self.root, "Program Files")
        exe = _exe(pf, "ODA", "ODAFileConverter 26.2.0", "ODAFileConverter.exe")
        os.environ["PROGRAMFILES"] = pf
        with self._windows():
            self.assertIn(exe, boq._installed_converter_paths())

    def test_windows_x86_folder_and_newest_version_first(self):
        pf = os.path.join(self.root, "PF"); x86 = os.path.join(self.root, "PF86")
        old = _exe(pf, "ODA", "ODAFileConverter 9.0", "ODAFileConverter.exe")
        new = _exe(pf, "ODA", "ODAFileConverter 25.12.0", "ODAFileConverter.exe")
        only86 = _exe(x86, "ODA", "ODAFileConverter 27.1.0", "ODAFileConverter.exe")
        os.environ["PROGRAMFILES"], os.environ["PROGRAMFILES(X86)"] = pf, x86
        with self._windows():
            found = boq._installed_converter_paths()
        self.assertLess(found.index(new), found.index(old))
        self.assertIn(only86, found)

    def test_macos_default_app_location(self):
        with mock.patch.object(boq.platform, "system", return_value="Darwin"):
            found = boq._installed_converter_paths()
        self.assertIn("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter", found)

    @unittest.skipIf(sys.platform == "win32",
                     "simulates Linux on Windows: expanduser/joins use Windows rules there, so the paths cannot match")
    def test_linux_deb_paths_and_appimage_in_downloads(self):
        os.environ["HOME"] = self.root
        os.environ["USERPROFILE"] = self.root          # Windows' expanduser("~") reads this, not HOME
        app = _exe(self.root, "Downloads", "ODAFileConverter_QT6_lnxX64_11dll.AppImage")
        with mock.patch.object(boq.platform, "system", return_value="Linux"):
            found = boq._installed_converter_paths()
        self.assertIn("/usr/bin/ODAFileConverter", found)
        self.assertIn(app, found)

    def test_a_hand_picked_converter_is_remembered_and_used(self):
        exe = _exe(self.root, "somewhere", "ODAFileConverter.exe")
        cfg = {}
        with mock.patch.object(CB.config, "save") as save:
            self.assertTrue(CS.remember(cfg, exe))
        save.assert_called_once()
        self.assertEqual(cfg[CS.CONFIG_KEY], exe)
        os.environ.pop(boq.ENV_CONVERTER, None)           # a new run of the app
        self.assertEqual(CS.detect(cfg), exe)             # remembered path wins on its own

    def test_a_path_that_is_not_a_file_is_not_saved(self):
        cfg = {}
        with mock.patch.object(CB.config, "save") as save:
            self.assertFalse(CS.remember(cfg, os.path.join(self.root, "nope.exe")))
        save.assert_not_called()
        self.assertNotIn(CS.CONFIG_KEY, cfg)

    def test_the_engine_message_is_plain_and_the_marker_matches(self):
        with mock.patch.object(boq, "find_dwg_converter", return_value=None):
            with self.assertRaises(boq.NoConverterError) as c:
                boq.dwg_to_dxf(os.path.join(self.root, "a.dwg"))
        text = str(c.exception)
        self.assertTrue(CS.is_missing_message(text))
        for bad in ("/boq", "PATH", "re-run"):
            self.assertNotIn(bad, text)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/bad"):
            self.send_response(200)
            self.send_header("Content-Length", str(len(MSI) + 500))   # promises more than it sends
            self.end_headers()
            self.wfile.write(MSI)
        elif self.path.startswith("/missing"):
            self.send_error(404)
        elif self.path.startswith("/hop"):
            self.send_response(301)
            self.send_header("Location", "http://evil.invalid:1/x.msi")
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header("Content-Length", str(len(MSI)))
            self.end_headers()
            self.wfile.write(MSI)


class Download(_Env):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _worker(self, path):
        w = CS.DownloadWorker(f"{self.base}{path}?filename=ODA_test.msi",
                              hosts=("127.0.0.1",), schemes=("http",), min_bytes=100,
                              dest_dir=self.root)
        w.events = []
        w.progress.connect(lambda a, b: w.events.append(("p", a, b)))
        w.done.connect(lambda p: w.events.append(("done", p)))
        w.failed.connect(lambda m: w.events.append(("failed", m)))
        return w

    def test_good_download_reports_progress_and_saves(self):
        w = self._worker("/ok"); w.run()
        self.assertEqual(w.events[-1][0], "done")
        self.assertEqual(w.events[0][:1], ("p",))
        self.assertEqual(w.events[0][2], len(MSI))
        self.assertEqual(os.path.getsize(w.events[-1][1]), len(MSI))

    def test_short_download_fails_and_leaves_no_file(self):
        w = self._worker("/bad"); w.run()
        self.assertEqual(w.events[-1][0], "failed")
        self.assertFalse(os.path.exists(os.path.join(self.root, "ODA_test.msi")))

    def test_http_error_fails(self):
        w = self._worker("/missing"); w.run()
        self.assertEqual(w.events[-1][0], "failed")

    def test_redirect_to_another_host_is_refused(self):
        w = self._worker("/hop"); w.run()
        self.assertEqual(w.events[-1][0], "failed")
        self.assertIn("not allowed", w.events[-1][1])

    def test_an_address_outside_oda_is_refused_without_a_request(self):
        w = CS.DownloadWorker("https://example.com/x.msi")
        got = []
        w.failed.connect(got.append); w.run()
        self.assertTrue(got)

    def test_wrong_file_type_is_refused(self):
        class Plain(_Handler):
            def do_GET(self):
                self.send_response(200); self.send_header("Content-Length", "6000")
                self.end_headers(); self.wfile.write(b"z" * 6000)
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Plain)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        w = CS.DownloadWorker(f"http://127.0.0.1:{srv.server_port}/a?filename=a.msi",
                              hosts=("127.0.0.1",), schemes=("http",), min_bytes=100,
                              dest_dir=self.root)
        got = []
        w.failed.connect(got.append); w.run()
        self.assertIn("not an installer", got[0])

    def test_official_url_is_https_opendesign_only(self):
        for system, machine in (("Windows", "AMD64"), ("Darwin", "arm64"),
                                ("Darwin", "x86_64"), ("Linux", "x86_64")):
            with mock.patch.object(CS.platform, "system", return_value=system), \
                 mock.patch.object(CS.platform, "machine", return_value=machine):
                url = CS.installer_url()
            self.assertTrue(url.startswith("https://www.opendesign.com/guestfiles/get?filename="), url)
        with mock.patch.object(CS.platform, "system", return_value="Windows"), \
             mock.patch.object(CS.platform, "machine", return_value="ARM64"):
            self.assertIsNone(CS.installer_url())


class Dialog(_Env):
    def setUp(self):
        super().setUp()
        self.opened = []
        for name in ("open_url", "open_folder"):
            p = mock.patch.object(CD, name, side_effect=lambda x, n=name: self.opened.append((n, x)))
            p.start(); self.addCleanup(p.stop)
        self.cfg = {}
        # downloads come from the local fake server, never from ODA
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.shutdown)
        port = self.srv.server_port
        real = CS.DownloadWorker
        p = mock.patch.object(CS, "DownloadWorker", lambda url: real(
            f"http://127.0.0.1:{port}/ok?filename=ODA_test.msi", hosts=("127.0.0.1",),
            schemes=("http",), min_bytes=100, dest_dir=self.root))
        p.start(); self.addCleanup(p.stop)
        # run the "thread" inline so no event loop is needed
        p = mock.patch.object(real, "start", lambda self_: self_.run())
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(real, "isRunning", lambda self_: False)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(CS, "installer_url", return_value="https://www.opendesign.com/x")
        p.start(); self.addCleanup(p.stop)
        self.launched = []
        p = mock.patch.object(CS, "launch_installer",
                              side_effect=lambda path: self.launched.append(path) or None)
        p.start(); self.addCleanup(p.stop)
        self.found = [None]
        p = mock.patch.object(CS, "detect", side_effect=lambda cfg=None: self.found[0])
        p.start(); self.addCleanup(p.stop)

    def _dlg(self):
        d = CD.ConverterDialog(self.cfg)
        self.addCleanup(d.deleteLater)
        return d

    def test_wording_is_plain_and_offers_every_button(self):
        d = self._dlg()
        text = " ".join(l.text() for l in d.findChildren(QLabel))
        self.assertIn("free converter", text)
        for bad in ("/boq", "PATH", "OpenRouter", "re-run"):
            self.assertNotIn(bad, text)
        labels = {d.install_btn.text(), d.page_btn.text(), d.installed_btn.text(),
                  d.choose_btn.text(), d.dxf_btn.text()}
        self.assertEqual(labels, {"Install it from Prism", "Open the download page",
                                  "I installed it", "Choose the converter file…",
                                  "Use a DXF file instead"})

    def test_install_needs_the_terms_ticked_and_says_why(self):
        d = self._dlg()
        self.assertFalse(d.install_btn.isEnabled())
        self.assertIn("accept", d.install_btn.toolTip())
        d._install()                                    # even called directly: nothing happens
        self.assertEqual(self.launched, [])
        d.accept_terms.setChecked(True)
        self.assertTrue(d.install_btn.isEnabled())

    def test_download_then_launch_then_redetect_finishes_by_itself(self):
        d = self._dlg()
        d.accept_terms.setChecked(True)
        d._install()
        self.assertEqual(len(self.launched), 1)
        self.assertTrue(os.path.isfile(self.launched[0]))
        self.assertEqual(d.outcome, "")                 # installer still running
        d._poll()
        self.assertEqual(d.outcome, "")
        self.found[0] = "/c/ODAFileConverter.exe"
        d._poll()                                       # installer finished -> found
        self.assertEqual((d.outcome, d.converter), ("ready", "/c/ODAFileConverter.exe"))

    def test_linux_style_no_launch_shows_the_command_and_never_sudo_runs(self):
        d = self._dlg()
        d.accept_terms.setChecked(True)
        d._install()
        self.assertIn("sudo apt install", d.status.text())      # shown, not run
        self.assertEqual(self.opened[-1][0], "open_folder")

    def test_failed_download_falls_back_to_the_download_page(self):
        d = self._dlg()
        d._on_failed("boom")
        self.assertIn("Open the download page", d.status.text())
        self.assertEqual(self.launched, [])
        d._open_page()
        self.assertEqual(self.opened[-1], ("open_url", CS.PAGE_URL))

    def test_i_installed_it_redetects_without_restart(self):
        d = self._dlg()
        d._recheck()
        self.assertEqual(d.outcome, "")
        self.assertIn("still cannot find", d.status.text())
        self.found[0] = "/c/oda"
        d._recheck()
        self.assertEqual(d.outcome, "ready")

    def test_choosing_the_file_remembers_it(self):
        exe = _exe(self.root, "x", "ODAFileConverter.exe")
        d = self._dlg()
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(exe, "")), \
             mock.patch.object(CB.config, "save"):
            d._choose()
        self.assertEqual((d.outcome, self.cfg[CS.CONFIG_KEY]), ("ready", exe))

    def test_dxf_instead(self):
        d = self._dlg()
        d._use_dxf()
        self.assertEqual(d.outcome, "dxf")

    def test_boq_dialog_opens_it_on_the_missing_converter_error_and_remeasures(self):
        from addons.boq import dialog as BD
        d = BD.BoqDialog({"api_key": "k"}, [])
        self.addCleanup(d.deleteLater)
        with mock.patch.object(BD.converter_dialog, "ask_for_converter",
                               return_value="ready") as ask, \
             mock.patch.object(d, "_measure") as measure, \
             mock.patch.object(BD.QMessageBox, "warning") as warn:
            d._on_measure_failed(boq.NO_CONVERTER_TEXT + "\nmore")
        ask.assert_called_once(); measure.assert_called_once(); warn.assert_not_called()
        with mock.patch.object(BD.QMessageBox, "warning") as warn:
            d._on_measure_failed("some other error")
        warn.assert_called_once()


class SharedConsentInBoq(_Env):
    def setUp(self):
        super().setUp()
        S.reset_session()
        self.dwg = os.path.join(self.root, "GA plan.dwg")
        with open(self.dwg, "wb") as f:
            f.write(b"x" * 2048)

    def _boq(self, cfg):
        from addons.boq import dialog as BD
        d = BD.BoqDialog(cfg, [])
        self.addCleanup(d.deleteLater)
        d.cad_path = self.dwg
        return d

    def test_asked_once_then_remembered_for_the_session(self):
        d = self._boq({})
        with mock.patch.object(SCD, "exec", return_value=SCD.Accepted) as ex:
            self.assertTrue(d._drawing_consent())
            self.assertTrue(d._drawing_consent())
        ex.assert_called_once()

    def test_cancel_sends_nothing_and_shows_no_panel(self):
        d = self._boq({})
        with mock.patch.object(SCD, "exec", return_value=SCD.Rejected) as ex:
            self.assertFalse(d._drawing_consent())
            self.assertFalse(d._drawing_consent())
        self.assertEqual(ex.call_count, 2)
        self.assertIsNone(getattr(d, "_sending", None))

    def test_panel_shows_file_name_and_size_and_goes_when_busy_ends(self):
        d = self._boq({})
        with mock.patch.object(SCD, "exec", return_value=SCD.Accepted):
            d._drawing_consent()
        panel = d._sending
        self.assertEqual(panel.preview.name.text(), "GA plan.dwg")
        self.assertEqual(panel.preview.size.text(), "2 KB")
        d._set_busy(False, "")
        self.assertIsNone(d._sending)

    def test_consent_dialog_names_prism_ai_and_the_file(self):
        dlg = SCD(self.dwg, "drawing")
        text = " ".join(l.text() for l in dlg.findChildren(QLabel))
        self.assertIn("Prism AI", text)
        self.assertIn("GA plan.dwg", text)
        self.assertNotIn("OpenRouter", text)


if __name__ == "__main__":
    unittest.main()

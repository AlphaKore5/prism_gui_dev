"""Settings > Usage, against a fake of the server's GET /v1/ai/usage.

Real ai_client over real HTTP on 127.0.0.1, real UsagePanel and Settings page,
real worker thread. The only fake is the server, answering with exactly the
contract: balance_mc, credit_usd_micros, cycle{used_mc,allowance_mc,resets_at},
today{used_mc}, by_addon[], by_day[], events[], next.

Run on its own, fresh HOME:  python -m pytest tests/test_usage_panel.py
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-s22u-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME
os.environ.pop("PRISM_AI_DIRECT", None)

from PySide6.QtWidgets import QApplication, QLabel                  # noqa: E402
_app = QApplication.instance() or QApplication([])

import core_bridge                                                  # noqa: E402,F401
from core import ai_client                                          # noqa: E402
import licensing                                                    # noqa: E402
import ai_server                                                    # noqa: E402
from widgets import usage_panel as UP                               # noqa: E402
from widgets.usage_chip import UsageChip                            # noqa: E402
from widgets import usage_chip                                      # noqa: E402

MAIN = threading.main_thread()


def contract(**over) -> dict:
    now = int(time.time())
    d = {"balance_mc": 40_000, "credit_usd_micros": 10_000,
         "cycle": {"used_mc": 60_000, "allowance_mc": 100_000, "resets_at": now + 5 * 86400},
         "today": {"used_mc": 1_250},
         "by_addon": [{"addon": "boq", "used_mc": 50_000, "calls": 9},
                      {"addon": "core", "used_mc": 10_000, "calls": 30}],
         "by_day": [{"day": time.strftime("%Y-%m-%d", time.gmtime(now - (29 - i) * 86400)),
                     "used_mc": 1000 * i} for i in range(30)],
         "events": [{"ts": now - 60, "addon": "boq", "feature": "write", "role": "boq.agent_a",
                     "model_label": "Claude Sonnet", "used_mc": 1_250, "status": "ok", "run_id": "r1"},
                    {"ts": now - 600, "addon": "core", "feature": "planner", "role": "planner",
                     "model_label": "Llama", "used_mc": 0, "status": "refunded", "run_id": ""}],
         "next": None}
    d.update(over)
    return d


class FakeUsage:
    def __init__(self):
        self.calls = []
        self.status = 200
        self.body = contract()
        self.delay = 0.0
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                u = urlparse(self.path)
                outer.calls.append({"path": u.path, "q": {k: v[0] for k, v in parse_qs(u.query).items()},
                                    "headers": {k.lower(): v for k, v in self.headers.items()}})
                time.sleep(outer.delay)
                if u.path != "/v1/ai/usage" or outer.status == 404:
                    return self._send(404, {"detail": "Not Found"})
                self._send(outer.status, outer.body)

            def _send(self, status, obj):
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d" % self.http.server_address[1]
        threading.Thread(target=self.http.serve_forever, daemon=True).start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()


def _wait(cond, seconds=8):
    end = time.time() + seconds
    while time.time() < end:
        _app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def _texts(w):
    return [l.text() for l in w.findChildren(QLabel)]


class _Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeUsage()
        self._p = [mock.patch.object(licensing, "state", lambda: types.SimpleNamespace(license_id="LIC-T")),
                   mock.patch.object(licensing, "device_fingerprint", lambda: "fp-test-0123456789"),
                   mock.patch.object(licensing, "lease_bearer", lambda: "PRSMLv1.test-lease"),
                   mock.patch.object(licensing.client, "server_url", lambda: self.fake.url),
                   # the balance refresh the page asks for is a different route; not under test
                   mock.patch.object(ai_server, "refresh_async", lambda force=False: None)]
        for p in self._p:
            p.start()
        ai_server.install()
        ai_server._session.clear()
        self.panel = UP.UsagePanel()
        self.panel.show()

    def tearDown(self):
        for p in self._p:
            p.stop()
        ai_client.set_auth_provider(None)
        ai_client.set_usage_listener(None)
        usage_chip.set_provider(None)
        usage_chip.set_opener(None)
        self.panel.close()
        self.fake.close()

    def load(self):
        self.panel.refresh()
        self.assertTrue(_wait(lambda: self.panel._worker is None))


class ServerAnswer(_Base):
    def test_the_page_shows_balance_cycle_today_addons_chart_and_calls(self):
        self.load()
        t = " | ".join(_texts(self.panel))
        self.assertIn("40", t)                       # 40,000 mc = 40 credits left
        self.assertIn("60 of 100", t)                # this cycle used vs allowance
        self.assertIn("1.25", t)                     # today, and the recent call
        self.assertIn("Boq", t)
        self.assertIn("9 calls", t)
        self.assertIn("Claude Sonnet", t)
        self.assertIn("refunded", t)
        self.assertEqual(len(self.panel.chart.days), 30)
        self.assertEqual(self.panel.status.text(), "")
        c = self.fake.calls[0]
        self.assertEqual(c["path"], "/v1/ai/usage")
        self.assertEqual(c["q"]["license_id"], "LIC-T")
        self.assertEqual(c["q"]["device_fp"], "fp-test-0123456789")
        self.assertEqual(c["headers"]["authorization"], "Bearer PRSMLv1.test-lease")
        self.assertIn(c["headers"]["x-prism-channel"], ("dev", "prod"))

    def test_credits_are_milli_credits_over_a_thousand(self):
        self.assertEqual(UP.credits(40_000), "40")
        self.assertEqual(UP.credits(1_250), "1.25")
        self.assertEqual(UP.credits(0), "0")
        self.assertEqual(UP.credits(3), "<0.01")

    def test_chart_paints_without_error(self):
        from PySide6.QtGui import QImage
        self.load()
        img = QImage(300, 96, QImage.Format_ARGB32)
        self.panel.chart.resize(300, 96)
        self.panel.chart.render(img)
        self.assertFalse(img.isNull())

    def test_refresh_button_asks_again_and_is_disabled_with_a_reason_meanwhile(self):
        self.fake.delay = 0.3
        self.panel.refresh()
        self.assertFalse(self.panel.refresh_btn.isEnabled())
        self.assertTrue(self.panel.refresh_btn.toolTip())
        self.assertTrue(_wait(lambda: self.panel._worker is None))
        self.assertTrue(self.panel.refresh_btn.isEnabled())
        self.fake.delay = 0
        self.load()
        self.assertEqual(len(self.fake.calls), 2)

    def test_empty_account_says_no_ai_calls_yet(self):
        self.fake.body = contract(events=[], by_addon=[], by_day=[],
                                  cycle={"used_mc": 0, "allowance_mc": None, "resets_at": None},
                                  today={"used_mc": 0})
        self.load()
        self.assertIn("No AI calls yet", _texts(self.panel))

    def test_server_error_is_said_plainly_and_the_button_comes_back(self):
        self.fake.status = 500
        self.load()
        self.assertIn("Couldn't load your usage", self.panel.status.text())
        self.assertTrue(self.panel.refresh_btn.isEnabled())

    def test_unreachable_server(self):
        self.fake.close()
        self.load()
        self.assertIn("Couldn't load your usage", self.panel.status.text())
        self.fake = FakeUsage()                      # so tearDown has something to close


class OldServer(_Base):
    def test_404_falls_back_to_this_session_and_says_so(self):
        self.fake.status = 404
        ai_server._heard({"balance_mc": 39_000, "charged_mc": 1_000, "addon": "boq",
                          "feature": "write", "role": "boq.agent_a",
                          "model_label": "Claude Sonnet", "run_id": "r9", "ts": int(time.time())})
        self.load()
        self.assertEqual(self.panel.status.text(), "Showing this session only")
        t = " | ".join(_texts(self.panel))
        self.assertIn("Claude Sonnet", t)
        self.assertIn("Boq", t)
        self.assertTrue(self.panel.session_only)

    def test_404_with_nothing_heard_shows_the_empty_state(self):
        self.fake.status = 404
        self.load()
        self.assertEqual(self.panel.status.text(), "Showing this session only")
        self.assertIn("No AI calls yet", _texts(self.panel))

    def test_the_session_list_is_fed_by_the_usage_listener_from_a_real_call(self):
        seen = {}
        ai_client.set_transport(lambda path, body, bearer: seen.setdefault("r", {
            "text": "hi", "finish": "stop", "model": {"key": "m", "label": "Model M"},
            "usage": {"in": 1, "out": 1}, "charged_mc": 25, "balance_mc": 39_975}))
        try:
            ai_client.chat("planner", "hello", addon="core", feature="planner")
        finally:
            ai_client.set_transport(None)
        ev = ai_server.session_events()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["addon"], ev[0]["feature"], ev[0]["role"], ev[0]["model_label"],
                          ev[0]["used_mc"]), ("core", "planner", "planner", "Model M", 25))


class NoNetworkOnTheUiThread(_Base):
    def test_loading_and_drawing_the_page_never_connects_from_the_ui_thread(self):
        seen = []
        real = socket.socket.connect

        def spy(sock, addr):
            if threading.current_thread() is MAIN:
                seen.append(addr)
            return real(sock, addr)
        with mock.patch.object(socket.socket, "connect", spy):
            self.load()
            self.panel.show_data(contract())
            _app.processEvents()
        self.assertEqual(seen, [])
        self.assertTrue(self.fake.calls)              # but it did ask, from a worker

    def test_the_ask_runs_on_a_worker_thread(self):
        where = []
        real = ai_server.fetch_usage

        def spy(*a, **k):
            where.append(threading.current_thread())
            return real(*a, **k)
        with mock.patch.object(ai_server, "fetch_usage", spy):
            self.load()
        self.assertEqual(len(where), 1)
        self.assertIsNot(where[0], MAIN)


class Reachable(_Base):
    def test_settings_has_a_usage_section_that_loads(self):
        from widgets.settings_panel import SettingsPanel, SECTIONS
        self.assertIn("usage", [s[0] for s in SECTIONS])
        with mock.patch.object(SettingsPanel, "_licence", lambda self, col: None):
            sp = SettingsPanel({})
        sp.show_section("usage")
        _app.processEvents()
        self.assertTrue(_wait(lambda: sp.usage_panel._worker is None))
        self.assertIn("1.25", " | ".join(_texts(sp.usage_panel)))
        sp.close()

    def test_clicking_the_chip_opens_usage(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        opened = []
        usage_chip.set_opener(lambda: opened.append(1))
        chip = UsageChip(provider=lambda: usage_chip.Usage(credits_left=5))
        ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        chip.mousePressEvent(ev)
        self.assertEqual(opened, [1])

    def test_without_ai_through_the_server_it_says_so_and_asks_nothing(self):
        with mock.patch.object(ai_server, "active", return_value=False):
            self.panel.refresh()
        self.assertIn("Prism plan", self.panel.status.text())
        self.assertEqual(self.fake.calls, [])
        self.assertTrue(self.panel.refresh_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()

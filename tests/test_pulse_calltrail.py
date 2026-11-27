"""Pulse call trail: an error report says which web calls the app made last and where they went.

Pinned: only host and path leave (no port, user, query, fragment; ids blanked); the wrappers
never change a result or an exception; one call is noted once however often the trail is
installed; an error event carries the trail; and it carries the REAL flavour (it used to
say "complete" for every build).
"""
from __future__ import annotations

import http.server
import os
import sys
import threading
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pulse  # noqa: E402
from tests.test_pulse_client import Base  # noqa: E402


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        self.send_response(404 if self.path.startswith("/missing") else 200)
        self.end_headers()
        self.wfile.write(b"x")

    def log_message(self, *a):
        pass


class Trail(Base):
    def setUp(self):
        super().setUp()
        import requests.sessions
        import urllib.request
        self._saved = (requests.sessions.Session.request, urllib.request.OpenerDirector.open)

        def restore():
            requests.sessions.Session.request, urllib.request.OpenerDirector.open = self._saved
            pulse._trail_installed = False
            pulse._calls.clear()
        self.addCleanup(restore)
        pulse._trail_installed = False
        pulse._calls.clear()
        pulse.install_call_trail()

    def test_only_host_and_path_leave_and_ids_are_blanked(self):
        import time
        t = pulse._call_text("get", "https://me:pw@api.x.com:8443/v1/job/12345678/file?token=abc&k=v#frag",
                             200, time.perf_counter())
        self.assertTrue(t.startswith("GET api.x.com/v1/job/<id>/file -> 200 "), t)
        for leak in ("token", "abc", "me:pw", "8443", "12345678", "frag"):
            self.assertNotIn(leak, t)

    def test_a_requests_call_is_noted_and_its_result_is_untouched(self):
        import requests
        resp = requests.Response()
        resp.status_code = 502
        with mock.patch("requests.adapters.HTTPAdapter.send", return_value=resp):
            got = requests.Session().request("POST", "https://example.test/v1/ai/chat?key=secret")
        self.assertIs(resp, got)
        self.assertRegex(pulse.recent_calls()[-1], r"^POST example\.test/v1/ai/chat -> 502 \d+ms$")
        self.assertNotIn("secret", " ".join(pulse.recent_calls()))

    def test_a_failing_requests_call_is_noted_and_the_same_exception_is_raised(self):
        import requests
        with mock.patch("requests.adapters.HTTPAdapter.send", side_effect=requests.ConnectionError("down")):
            with self.assertRaises(requests.ConnectionError):
                requests.Session().request("GET", "https://example.test/ping")
        self.assertIn("-> ConnectionError", pulse.recent_calls()[-1])

    def test_urllib_calls_are_noted_with_their_status_and_errors_still_raise(self):
        import urllib.error
        import urllib.request
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        self.addCleanup(lambda: (srv.shutdown(), srv.server_close(), t.join(5)))
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        urllib.request.urlopen(base + "/ok", timeout=5).close()
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(base + "/missing", timeout=5)
        calls = pulse.recent_calls()
        self.assertRegex(calls[-2], r"^GET 127\.0\.0\.1/ok -> 200 ")
        self.assertRegex(calls[-1], r"^GET 127\.0\.0\.1/missing -> 404 ")

    def test_installing_twice_notes_a_call_once(self):
        import requests
        pulse.install_call_trail()
        resp = requests.Response()
        resp.status_code = 200
        with mock.patch("requests.adapters.HTTPAdapter.send", return_value=resp):
            requests.Session().request("GET", "https://example.test/a")
        self.assertEqual(1, len(pulse.recent_calls()))

    def test_the_ring_keeps_ten_and_a_report_sends_the_newest_eight(self):
        import time
        for i in range(15):
            pulse._note_call("GET", f"https://example.test/p{i}", 200, time.perf_counter())
        self.assertEqual(10, len(pulse._calls))
        self.assertEqual(8, len(pulse.recent_calls()))
        self.assertIn("/p14 ", pulse.recent_calls()[-1])

    def test_an_error_event_carries_the_trail_and_the_real_flavour(self):
        import time
        import flavour
        pulse._note_call("GET", "https://example.test/v1/lease", 503, time.perf_counter())
        try:
            raise KeyError("x")
        except KeyError:
            et, ev, tb = sys.exc_info()
        with mock.patch.object(flavour, "FLAVOUR", "sales"):
            pulse.error(et, ev, tb, addon="inquiry", screen="inbox")
        e = self.queued()[-1]
        self.assertEqual("sales", e["flavour"])
        self.assertTrue(any("example.test/v1/lease -> 503" in c for c in e["detail"]["calls"]), e["detail"])
        self.assertIn("frames", e["detail"])


if __name__ == "__main__":
    unittest.main()

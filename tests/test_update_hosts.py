"""Failover between update repositories.

The promise: any one repository can be down, stale, or serving damaged bytes,
and a client that can reach another still updates -- while nothing the update
key did not sign is ever installed, whichever host the bytes came from.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import updater                                           # noqa: E402
from test_updater_phase1 import Harness                  # noqa: E402

NEW = "org/prism"
OLD = "old/prism"


def _entry(path, content, mode=0):
    data = content.encode()
    return {"path": path, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(), "mode": mode}


class HostFailover(Harness):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(updater, "UPDATE_REPO", NEW)
        q = mock.patch.object(updater, "UPDATE_FALLBACK_REPOS", (OLD,))
        r = mock.patch.object(updater, "UPDATE_HOST",
                              f"https://github.com/{NEW}/releases/latest/download")
        for x in (p, q, r):
            x.start()
            self.addCleanup(x.stop)
        self.install_dir = tempfile.mkdtemp(prefix="prism-install-")

    def serve(self, table):
        """fetch() answering from {url: bytes | Exception}, recording calls."""
        self.calls = []

        def fetch(url, *, timeout):
            self.calls.append(url)
            got = table.get(url, ConnectionError(f"down: {url}"))
            if isinstance(got, Exception):
                raise got
            return got
        return fetch

    def test_repos_are_primary_then_fallbacks_without_duplicates(self):
        self.assertEqual(updater._repos(), [NEW, OLD])
        with mock.patch.object(updater, "UPDATE_FALLBACK_REPOS", (NEW, OLD, OLD)):
            self.assertEqual(updater._repos(), [NEW, OLD])

    def test_urls_name_the_repo_they_are_for(self):
        self.assertIn(f"/{OLD}/releases/latest/download/", updater._manifest_url(OLD))
        self.assertIn(f"/{OLD}/releases/download/", updater._file_url("2.0.0", "Prism", 1, OLD))
        self.assertIn(f"/{NEW}/", updater._manifest_url())

    def test_primary_down_manifest_comes_from_the_fallback(self):
        token = self._sign({"version": "2.0.0", "files": []})
        fetch = self.serve({updater._manifest_url(OLD): token.encode()})
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        self.assertEqual(check.version, "2.0.0")
        self.assertEqual(self.calls[0], updater._manifest_url(NEW))   # tried first

    def test_primary_answering_does_not_ask_the_fallback(self):
        token = self._sign({"version": "2.0.0", "files": []})
        fetch = self.serve({updater._manifest_url(NEW): token.encode()})
        updater.check_for_update(running="1.0.0", fetch=fetch)
        self.assertEqual(self.calls, [updater._manifest_url(NEW)])

    def test_stale_primary_does_not_hide_a_newer_fallback(self):
        stale = self._sign({"version": "1.0.0", "files": []})
        fresh = self._sign({"version": "2.0.0", "files": []})
        fetch = self.serve({updater._manifest_url(NEW): stale.encode(),
                            updater._manifest_url(OLD): fresh.encode()})
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        self.assertEqual(check.version, "2.0.0")

    def test_forged_primary_is_skipped_when_the_fallback_is_genuine(self):
        genuine = self._sign({"version": "2.0.0", "files": []})
        forged = genuine[:-6] + ("AAAAAA" if not genuine.endswith("AAAAAA") else "BBBBBB")
        fetch = self.serve({updater._manifest_url(NEW): forged.encode(),
                            updater._manifest_url(OLD): genuine.encode()})
        self.assertEqual(updater.check_for_update(running="1.0.0", fetch=fetch).version,
                         "2.0.0")

    def test_forged_everywhere_still_raises(self):
        genuine = self._sign({"version": "2.0.0", "files": []})
        forged = genuine[:-6] + ("AAAAAA" if not genuine.endswith("AAAAAA") else "BBBBBB")
        fetch = self.serve({updater._manifest_url(NEW): forged.encode(),
                            updater._manifest_url(OLD): forged.encode()})
        with self.assertRaises(updater.UpdateError):
            updater.check_for_update(running="1.0.0", fetch=fetch)

    def test_every_host_down_is_quietly_no_update(self):
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=self.serve({})))

    def test_nobody_has_anything_newer_is_no_update(self):
        token = self._sign({"version": "1.0.0", "files": []})
        fetch = self.serve({updater._manifest_url(NEW): token.encode(),
                            updater._manifest_url(OLD): token.encode()})
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))

    # ── files ──────────────────────────────────────────────────────────────
    def _stage(self, table, content="new-binary-contents"):
        entry = _entry("Prism", content, mode=0o111)
        token = self._sign({"version": "2.0.0", "files": [entry]})
        full = {updater._manifest_url(NEW): token.encode(), **table}
        fetch = self.serve(full)
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        return check, fetch

    def test_file_comes_from_the_fallback_when_the_primary_lacks_it(self):
        content = "new-binary-contents"
        check, fetch = self._stage({updater._file_url("2.0.0", "Prism", 1, OLD):
                                    content.encode()}, content)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)
        with open(os.path.join(staged.stage_dir, "Prism")) as f:
            self.assertEqual(f.read(), content)

    def test_damaged_bytes_from_the_primary_fall_through_to_the_fallback(self):
        content = "new-binary-contents"
        damaged = "NEW-BINARY-CONTENTS"                  # right size, wrong hash
        check, fetch = self._stage({
            updater._file_url("2.0.0", "Prism", 1, NEW): damaged.encode(),
            updater._file_url("2.0.0", "Prism", 1, OLD): content.encode()}, content)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)
        with open(os.path.join(staged.stage_dir, "Prism")) as f:
            self.assertEqual(f.read(), content)

    def test_truncated_bytes_from_the_primary_fall_through(self):
        content = "new-binary-contents"
        check, fetch = self._stage({
            updater._file_url("2.0.0", "Prism", 1, NEW): b"short",
            updater._file_url("2.0.0", "Prism", 1, OLD): content.encode()}, content)
        updater.stage_update(check, self.install_dir, fetch=fetch)

    def test_damaged_everywhere_fails_and_leaves_nothing_staged(self):
        content = "new-binary-contents"
        bad = "NEW-BINARY-CONTENTS".encode()
        check, fetch = self._stage({
            updater._file_url("2.0.0", "Prism", 1, NEW): bad,
            updater._file_url("2.0.0", "Prism", 1, OLD): bad}, content)
        with self.assertRaises(updater.UpdateError):
            updater.stage_update(check, self.install_dir, fetch=fetch)
        self.assertFalse(os.path.isdir(os.path.join(
            updater.stage_root(self.install_dir), "2.0.0")))

    def test_unreachable_everywhere_is_an_update_error_not_a_raw_exception(self):
        check, fetch = self._stage({}, "new-binary-contents")
        with self.assertRaises(updater.UpdateError):
            updater.stage_update(check, self.install_dir, fetch=fetch)


class FallbackListIsFixedAtBuildTime(unittest.TestCase):
    def test_default_is_a_literal_tuple_in_source(self):
        import inspect
        src = inspect.getsource(updater)
        line = [l for l in src.splitlines() if l.startswith("UPDATE_FALLBACK_REPOS")]
        self.assertTrue(line, "UPDATE_FALLBACK_REPOS must stay a module-level literal")
        for forbidden in ("environ", "getenv", "config", "load("):
            self.assertNotIn(forbidden, line[0])


if __name__ == "__main__":
    unittest.main()

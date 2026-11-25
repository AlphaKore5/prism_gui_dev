"""Tests for updater.py's Phase 1 engine — check_for_update() and
stage_update(). No network: `fetch` is injected everywhere update.py would
otherwise call `requests.get`, per update_manifest.py's and updater.py's own
design (the injection point exists specifically so this is testable without
a real host).

Covers the update-research-inapp-download.md §4 checklist end to end from
the CLIENT side: verify-before-fetch, size cap, hash verification, monotonic
version (no downgrade), and — the file-level-diff payoff the whole design
exists for — that only the files that actually changed get "downloaded".
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
import sample_jobs  # noqa: E402

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import apply_update
import flavour
import licensing
import paths
import update_manifest as UM
import updater
from licensing import device, keys


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub_hex = priv.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
    priv_hex = priv.private_bytes(
        _ser.Encoding.Raw, _ser.PrivateFormat.Raw, _ser.NoEncryption()).hex()
    return priv_hex, pub_hex


class Harness(unittest.TestCase):
    """Same shape as test_updater.py's Harness (temp ~/.prism, no keyring,
    no network) plus an update-signing keypair, since Phase 1 has its own,
    separate key from the licence one — see updater.py's module docstring."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-updater-p1-")
        self.priv_hex, self.pub_hex = _keypair()
        device.reset_cache()
        self.patches = [
            # licensing.user_dir() takes NO arguments in reality (it's a
            # zero-arg wrapper around paths.user_dir()) — return_value, not
            # a variadic side_effect, so a future accidental
            # licensing.user_dir("x") call fails here in tests exactly the
            # way it would for real, instead of a permissive mock quietly
            # accepting an argument the real function never could. A
            # variadic mock here is EXACTLY what let updater.updates_root()
            # ship calling licensing.user_dir("updates") — TypeError on
            # every real stage_update() call — with this whole test suite
            # green throughout.
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            # updates_root() calls paths.user_dir("updates") directly
            # (paths.user_dir IS the variadic one) — without mocking this
            # too, stage_update() in these tests was writing into this
            # machine's REAL ~/.prism/updates/, not the isolated temp dir
            # every other piece of state here uses. Caught by literally
            # finding those files after a test run, not by any assertion.
            mock.patch.object(paths, "user_dir",
                              side_effect=lambda *p: os.path.join(self.tmp, *p)),
            mock.patch.object(keys, "update_public_keys",
                              return_value={"u1": self.pub_hex}),
            mock.patch.object(licensing.secretstore, "_keyring", return_value=None),
            # The manifests signed here name no update channel, as complete's
            # never do; a flavour refuses those (tests/test_update_flavours.py).
            mock.patch.object(flavour, "FLAVOUR", "complete"),
        ]
        for p in self.patches:
            p.start()
        licensing.reload()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    def _sign(self, manifest: dict, **kw) -> str:
        return UM.sign(manifest, self.priv_hex, kid="u1", **kw)

    def _fake_fetch(self, responses: dict):
        """responses: {url: bytes}. Raises for anything not listed, so a
        test that forgot to stub a URL fails loudly instead of silently
        hitting the real network (there's no real network path here, but a
        KeyError is a much clearer failure than a hang)."""
        def fetch(url, *, timeout):
            if url not in responses:
                raise KeyError(f"unstubbed URL in test: {url}")
            return responses[url]
        return fetch


class CheckingForAnUpdate(Harness):
    def test_no_manifest_available_is_not_an_error(self):
        self.assertIsNone(updater.check_for_update(
            running="1.0.0", fetch=self._fake_fetch({})))

    def test_newer_manifest_is_offered(self):
        token = self._sign({"version": "2.0.0", "files": []})
        fetch = self._fake_fetch({updater._manifest_url(): token.encode("utf-8")})
        result = updater.check_for_update(running="1.0.0", fetch=fetch)
        self.assertIsNotNone(result)
        self.assertEqual(result.version, "2.0.0")

    def test_same_or_older_version_is_not_offered(self):
        token = self._sign({"version": "1.0.0", "files": []})
        fetch = self._fake_fetch({updater._manifest_url(): token.encode("utf-8")})
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))

    def test_tampered_manifest_raises_rather_than_silently_updating(self):
        token = self._sign({"version": "2.0.0", "files": []})
        forged = token[:-4] + "AAAA"  # corrupt the signature segment
        fetch = self._fake_fetch({updater._manifest_url(): forged.encode("utf-8")})
        with self.assertRaises(updater.UpdateError):
            updater.check_for_update(running="1.0.0", fetch=fetch)

    def test_downgrade_after_a_higher_version_was_already_seen_is_refused(self):
        # Simulate having already accepted 3.0.0 once (e.g. a previous
        # check+stage), then a manifest claiming 2.0.0 shows up — validly
        # signed, just stale. §4 requirement #4: monotonic version, no
        # replay-to-downgrade, even with a genuine signature.
        updater._record_seen_version("3.0.0")
        token = self._sign({"version": "2.0.0", "files": []})
        fetch = self._fake_fetch({updater._manifest_url(): token.encode("utf-8")})
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))


class StagingAnUpdate(Harness):
    def setUp(self):
        super().setUp()
        self.install_dir = os.path.join(self.tmp, "install")
        os.makedirs(self.install_dir)
        self._write(self.install_dir, "Prism", "old-binary-contents", executable=True)
        self._write(self.install_dir, "_internal/unchanged.dat", "same-in-both")
        self._write(self.install_dir, "_internal/removed-in-new.dat", "gone-soon")

    def _write(self, root: str, rel: str, content: str, executable: bool = False) -> None:
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        if executable:
            os.chmod(full, 0o755)

    def test_updates_root_does_not_crash(self):
        """The actual v1.4.0 incident: updates_root() called
        licensing.user_dir("updates") — a function that takes NO arguments
        — so stage_update() raised a plain TypeError on its very first
        line, every time, for every customer. UpdateWorker's blanket
        `except Exception` routed that into the same silent "just open the
        browser" fallback as an ordinary no-update-available result, so it
        shipped and went unnoticed until someone actually watched a real
        update attempt fail. paths.user_dir(*parts) is the variadic one;
        this pins updates_root() to keep using that, not licensing.user_dir."""
        root = updater.updates_root()
        self.assertEqual(root, os.path.join(self.tmp, "updates"))

    def _entry(self, path: str, content: str, mode: int = 0) -> dict:
        data = content.encode("utf-8")
        return {"path": path, "size": len(data),
               "sha256": hashlib.sha256(data).hexdigest(), "mode": mode}

    def test_only_changed_files_are_fetched(self):
        new_binary = "new-binary-contents-longer"
        unchanged_entry = self._entry("_internal/unchanged.dat", "same-in-both")
        changed_entry = self._entry("Prism", new_binary, mode=0o111)
        manifest_dict = {"version": "2.0.0",
                         "files": [unchanged_entry, changed_entry]}
        token = self._sign(manifest_dict)

        fetched_urls = []
        real_responses = {updater._manifest_url(): token.encode("utf-8"),
                          updater._file_url("2.0.0", "Prism"): new_binary.encode("utf-8")}

        def fetch(url, *, timeout):
            fetched_urls.append(url)
            return real_responses[url]

        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        self.assertIsNotNone(check)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)

        # The unchanged file's URL was never requested — this IS the size
        # win update-research-inapp-download.md §1/§3 is built around.
        self.assertNotIn(updater._file_url("2.0.0", "_internal/unchanged.dat"), fetched_urls)
        self.assertIn(updater._file_url("2.0.0", "Prism"), fetched_urls)

        with open(os.path.join(staged.stage_dir, "Prism")) as f:
            self.assertEqual(f.read(), new_binary)
        with open(os.path.join(staged.stage_dir, "_internal/unchanged.dat")) as f:
            self.assertEqual(f.read(), "same-in-both")
        # A file the new manifest doesn't list at all must not survive into
        # the staged tree, or an "update" could never actually remove
        # anything the old version shipped.
        self.assertFalse(os.path.exists(
            os.path.join(staged.stage_dir, "_internal/removed-in-new.dat")))

    def test_a_zero_byte_file_is_created_directly_never_fetched(self):
        """GitHub Releases refuses to host a zero-byte asset at all ('size
        must be greater than or equal to 1' — confirmed against the real
        API publishing 1.3.1, where a `py.typed` marker file broke the
        upload). There is nothing ambiguous about an empty file's content,
        so stage_update() must create it directly rather than ever asking
        _file_url() for it."""
        empty_entry = self._entry("_internal/py.typed", "")
        manifest_dict = {"version": "2.0.0", "files": [empty_entry]}
        token = self._sign(manifest_dict)

        def fetch(url, *, timeout):
            if url == updater._manifest_url():
                return token.encode("utf-8")
            raise AssertionError(f"should never fetch an empty file: {url}")

        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)
        staged_path = os.path.join(staged.stage_dir, "_internal/py.typed")
        self.assertTrue(os.path.isfile(staged_path))
        self.assertEqual(os.path.getsize(staged_path), 0)

    def test_download_size_mismatch_is_rejected(self):
        entry = self._entry("Prism", "expected-content")
        manifest_dict = {"version": "2.0.0", "files": [entry]}
        token = self._sign(manifest_dict)
        fetch = self._fake_fetch({
            updater._manifest_url(): token.encode("utf-8"),
            updater._file_url("2.0.0", "Prism"): b"short",  # wrong size on purpose
        })
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        with self.assertRaises(updater.UpdateError):
            updater.stage_update(check, self.install_dir, fetch=fetch)
        # A rejected stage must not leave a half-written directory behind.
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "updates", "2.0.0")))

    def test_download_hash_mismatch_is_rejected(self):
        entry = self._entry("Prism", "expected-content")
        manifest_dict = {"version": "2.0.0", "files": [entry]}
        token = self._sign(manifest_dict)
        wrong_but_same_size = "expected-CONTENT"  # same length, different bytes
        self.assertEqual(len(wrong_but_same_size), entry["size"])
        fetch = self._fake_fetch({
            updater._manifest_url(): token.encode("utf-8"),
            updater._file_url("2.0.0", "Prism"): wrong_but_same_size.encode("utf-8"),
        })
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        with self.assertRaises(updater.UpdateError):
            updater.stage_update(check, self.install_dir, fetch=fetch)

    def test_symlinks_are_recreated_not_downloaded(self):
        # Windows needs Administrator or Developer Mode for this.
        # Without either it is an environment fact, not a bug.
        why = sample_jobs.symlinks_unavailable()
        if why:
            self.skipTest(why)
        os.symlink("Prism", os.path.join(self.install_dir, "prism-link"))
        entry = {"path": "prism-link", "symlink": "Prism"}
        manifest_dict = {"version": "2.0.0", "files": [entry]}
        token = self._sign(manifest_dict)
        fetch = self._fake_fetch({updater._manifest_url(): token.encode("utf-8")})
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)
        link = os.path.join(staged.stage_dir, "prism-link")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "Prism")

    def test_staged_update_can_actually_be_applied(self):
        """The full pipeline, end to end: verify manifest -> diff -> stage ->
        hand off to apply_update.perform_swap directly (bypassing the
        detached-relaunch machinery, which test_apply_update.py already
        covers on its own) -> the installed tree is now the new version."""
        new_binary = "brand-new-prism-binary"
        entry = self._entry("Prism", new_binary, mode=0o111)
        manifest_dict = {"version": "2.0.0", "files": [entry]}
        token = self._sign(manifest_dict)
        fetch = self._fake_fetch({
            updater._manifest_url(): token.encode("utf-8"),
            updater._file_url("2.0.0", "Prism"): new_binary.encode("utf-8"),
        })
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        staged = updater.stage_update(check, self.install_dir, fetch=fetch)

        backup_dir = self.install_dir + ".old"
        apply_update.perform_swap(self.install_dir, staged.stage_dir, backup_dir)

        with open(os.path.join(self.install_dir, "Prism")) as f:
            self.assertEqual(f.read(), new_binary)
        # The old version is kept for exactly one more launch.
        with open(os.path.join(backup_dir, "Prism")) as f:
            self.assertEqual(f.read(), "old-binary-contents")

    def _staged_two(self):
        new_binary = "brand-new-prism-binary"
        entry = self._entry("Prism", new_binary, mode=0o111)
        token = self._sign({"version": "2.0.0", "files": [entry]})
        fetch = self._fake_fetch({
            updater._manifest_url(): token.encode("utf-8"),
            updater._file_url("2.0.0", "Prism"): new_binary.encode("utf-8"),
        })
        check = updater.check_for_update(running="1.0.0", fetch=fetch)
        return updater.stage_update(check, self.install_dir, fetch=fetch), fetch

    def test_downloading_a_version_is_not_the_same_as_having_run_it(self):
        """1.5.7. The version used to be recorded as accepted the moment it
        finished downloading. A swap that then failed left the machine on
        1.0.0 believing it already had 2.0.0 — so the next check said
        "nothing newer" and the GUI opened the download page instead: the
        "it takes me to GitHub instead of updating" report."""
        _staged, fetch = self._staged_two()
        # The swap failed; the machine is still on 1.0.0. Same update, offered again.
        self.assertIsNotNone(updater.check_for_update(running="1.0.0", fetch=fetch))
        # Only a launch of 2.0.0 makes it the version this machine has accepted.
        updater.note_installed("2.0.0")
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))

    def test_staging_happens_beside_the_install_so_the_swap_is_a_rename(self):
        staged, _fetch = self._staged_two()
        self.assertEqual(
            os.path.join(os.path.dirname(self.install_dir), ".prism-update-staging"),
            os.path.dirname(staged.stage_dir))

    def test_a_build_that_failed_its_first_launch_is_not_offered_again(self):
        """1.5.7. With the version recorded only once it has started, a
        build that crashed before its window and was rolled back would be
        offered, downloaded, swapped in and rolled back on every check. It
        stays refused after the one-time banner is dismissed."""
        _staged, fetch = self._staged_two()
        updater.note_rollback("2.0.0")
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))
        updater.acknowledge_rollback()
        self.assertIsNone(updater.check_for_update(running="1.0.0", fetch=fetch))


class StreamingSizeCap(unittest.TestCase):
    """_get()'s max_bytes cap is only meaningful on the real-network path
    (the `fetch` injection point used everywhere else in this file bypasses
    it entirely, by design) — so this exercises that path directly, with
    `requests` mocked rather than a real host, per
    update-research-inapp-download.md §4 requirement #3: a host that keeps
    sending past the manifest's declared size must be cut off DURING the
    read, not measured after buffering everything."""

    def test_oversized_stream_is_aborted_before_full_buffer(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock()
        fake_response.iter_content.return_value = iter(
            [b"x" * 100, b"y" * 100, b"z" * 100])  # 300 bytes total

        # _get() goes through one keep-alive Session (updater._http), so
        # the double stands in for the session, not for requests.get.
        session = mock.Mock(); session.get.return_value = fake_response
        with mock.patch.object(updater, "_http", return_value=session):
            get = session.get
            with self.assertRaises(updater.UpdateError):
                updater._get("https://example.invalid/file", timeout=5,
                             max_bytes=150)
            get.assert_called_once()
        # Aborted after the second chunk (200 > 150) — the third chunk is
        # still sitting unconsumed in the iterator, proving _get() never
        # pulled it (and never touched .content, which a full buffer of an
        # unbounded response would require).
        self.assertEqual(list(fake_response.iter_content.return_value),
                         [b"z" * 100])
        fake_response.close.assert_called_once()

    def test_stream_within_cap_returns_all_bytes(self):
        fake_response = mock.Mock()
        fake_response.raise_for_status = mock.Mock()
        fake_response.iter_content.return_value = iter([b"ab", b"cd"])

        session = mock.Mock(); session.get.return_value = fake_response
        with mock.patch.object(updater, "_http", return_value=session):
            data = updater._get("https://example.invalid/file", timeout=5,
                                max_bytes=10)
        self.assertEqual(data, b"abcd")


if __name__ == "__main__":
    unittest.main()

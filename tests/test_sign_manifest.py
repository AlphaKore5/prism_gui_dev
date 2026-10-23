"""devtools/sign_manifest.py — the downgrade guard, specifically.

The bug this pins: one release signs the SAME version three times over,
once per platform manifest (linux-x64, windows-x64, macos-arm64). The
original guard tracked one global "last signed version" regardless of
platform, so it signed linux-x64 1.4.0 fine and then refused windows-x64's
OWN first-ever 1.4.0 sign as "not newer than 1.4.0" — the version it had
itself just recorded, for a different file. Caught for real on the v1.4.0
release, before it could block macOS and Windows from ever shipping.

Every test here runs against a real subprocess invocation of the actual
script (not an import), with HOME/the working directory pointed at a fresh
temp dir each time, and the dev signing key (devtools/dev-signing-key.hex —
explicitly not a secret worth protecting, see its own module docstring) —
never the production key, never the real devtools/.last_signed_update_version*
tracker files this machine's real releases use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

GUI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGN_SCRIPT = os.path.join(GUI_DIR, "devtools", "sign_manifest.py")
DEV_KEY_PATH = os.path.join(GUI_DIR, "devtools", "dev-signing-key.hex")


def _dev_key() -> str | None:
    """The dev signing key, or None on a machine that does not have one.

    Read HERE rather than at module scope, and that is the whole point:
    dev-signing-key.hex is gitignored (see devtools/mint.py), so it does not
    exist on a fresh clone or on any CI runner. As a module-level
    `open(...)` this raised FileNotFoundError during pytest COLLECTION,
    which aborts the entire run — every other test file included, none of
    which has anything to do with signing.

    That is why the suite has never run in CI: not a failing test, a suite
    that could not start. A missing key must skip this file and nothing
    else.
    """
    try:
        with open(DEV_KEY_PATH, encoding="utf-8") as f:
            return f.read().strip().splitlines()[0]
    except (OSError, IndexError):
        return None


DEV_KEY = _dev_key()

# Named with the path in it, because the reason a machine skips these has a
# fix ("generate a dev key") and a silent 's' does not carry it.
_NO_KEY = f"no dev signing key at {DEV_KEY_PATH} — see devtools/mint.py"


@unittest.skipUnless(DEV_KEY, _NO_KEY)
class TheDowngradeGuardIsScopedPerPlatform(unittest.TestCase):
    """Runs the real script as a subprocess, with its own private copy of
    devtools/ (so its per-platform tracker files land in a temp dir, never
    touching this machine's real release history) and PYTHONPATH pointed
    at the real repo (so update_manifest/licensing import normally)."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="sign-manifest-test-")
        os.makedirs(os.path.join(self.work, "devtools"))
        with open(SIGN_SCRIPT, encoding="utf-8") as f:
            src = f.read()
        with open(os.path.join(self.work, "devtools", "sign_manifest.py"),
                 "w", encoding="utf-8") as f:
            f.write(src)

    def _manifest(self, name: str, version: str) -> str:
        path = os.path.join(self.work, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"version": version, "files": []}, f)
        return path

    def _sign(self, manifest_path: str, out_name: str):
        env = dict(os.environ)
        env["PYTHONPATH"] = GUI_DIR
        return subprocess.run(
            [sys.executable,
             os.path.join(self.work, "devtools", "sign_manifest.py"),
             manifest_path, "-o", os.path.join(self.work, out_name),
             "--key-hex", DEV_KEY, "--kid", "u1dev",
             "--allow-unpublished-key"],
            cwd=self.work, env=env, capture_output=True, text=True)

    def test_three_platforms_at_the_identical_version_all_succeed(self):
        for platform in ("linux-x64", "windows-x64", "macos-arm64"):
            m = self._manifest(f"manifest.{platform}.unsigned.json", "1.4.0")
            result = self._sign(m, f"manifest.{platform}.signed")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(
                os.path.join(self.work, f"manifest.{platform}.signed")))

    def test_a_real_downgrade_on_the_same_platform_is_still_refused(self):
        first = self._manifest("manifest.linux-x64.unsigned.json", "1.4.0")
        ok = self._sign(first, "manifest.linux-x64.signed")
        self.assertEqual(ok.returncode, 0, ok.stderr)

        older = self._manifest("manifest.linux-x64.older.json", "1.3.0")
        blocked = self._sign(older, "manifest.linux-x64.older.signed")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("not newer than", blocked.stderr)
        self.assertIn("linux-x64", blocked.stderr)
        self.assertFalse(os.path.exists(
            os.path.join(self.work, "manifest.linux-x64.older.signed")))

    def test_re_signing_the_exact_same_version_on_the_same_platform_is_refused(self):
        """Not a cross-platform case — signing linux-x64 1.4.0 twice in a
        row must still be refused. <= , not < : equal counts as "not
        newer.\""""
        m = self._manifest("manifest.linux-x64.unsigned.json", "1.4.0")
        first = self._sign(m, "manifest.linux-x64.signed")
        self.assertEqual(first.returncode, 0, first.stderr)

        again = self._sign(m, "manifest.linux-x64.signed.2")
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("not newer than", again.stderr)

    def test_tracker_files_are_one_per_platform_not_shared(self):
        for platform in ("linux-x64", "windows-x64"):
            m = self._manifest(f"manifest.{platform}.unsigned.json", "1.4.0")
            self._sign(m, f"manifest.{platform}.signed")
        tracker_dir = os.path.join(self.work, "devtools")
        trackers = sorted(n for n in os.listdir(tracker_dir)
                          if n.startswith(".last_signed_update_version"))
        self.assertEqual(
            trackers,
            [".last_signed_update_version.linux-x64",
             ".last_signed_update_version.windows-x64"])

    def test_a_genuinely_newer_version_on_the_same_platform_still_succeeds(self):
        m1 = self._manifest("manifest.linux-x64.unsigned.json", "1.4.0")
        self._sign(m1, "manifest.linux-x64.signed")
        m2 = self._manifest("manifest.linux-x64.v2.unsigned.json", "1.4.1")
        newer = self._sign(m2, "manifest.linux-x64.v2.signed")
        self.assertEqual(newer.returncode, 0, newer.stderr)


if __name__ == "__main__":
    unittest.main()

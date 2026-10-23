"""A released 1.6.10 must still update from manifests the new tooling signs.

This runs the ACTUAL 1.6.10 updater -- extracted from the v1.6.10 tag -- in a
separate interpreter against manifests carrying the new policy fields
(rollout, min_updater, revoked) and the new host layout. If this fails, the
change would strand every installed copy: they cannot be fixed remotely.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manifest as UM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "v1.6.10"
FILES = ["app_meta.py", "paths.py", "updater.py", "update_manifest.py",
         "apply_update.py", "licensing"]

# Runs inside the OLD tree. Prints one JSON line.
PROBE = r'''
import json, sys, os, tempfile
home = tempfile.mkdtemp()
os.environ["HOME"] = os.environ["USERPROFILE"] = home
import licensing, paths, updater, update_manifest
from unittest import mock
args = json.loads(sys.stdin.read())
keys = {"u1": args["pub"]}
out = {}
try:
    payload = update_manifest.verify(args["token"], public_keys=keys)
    out["verify"] = "ok"
    out["rollout"] = payload.get("rollout")
except Exception as e:
    out["verify"] = "FAILED: %r" % (e,)
def fetch(url, *, timeout):
    if url.endswith(".signed"):
        return args["token"].encode()
    raise KeyError(url)
with mock.patch.object(licensing.keys, "update_public_keys", return_value=keys), \
     mock.patch.object(licensing, "user_dir", return_value=home), \
     mock.patch.object(paths, "user_dir", side_effect=lambda *p: os.path.join(home, *p)):
    try:
        check = updater.check_for_update(running="1.6.10", fetch=fetch)
        out["offered"] = check.version if check else None
    except Exception as e:
        out["offered"] = "ERROR: %r" % (e,)
print(json.dumps(out))
'''


def _tag_exists() -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", TAG + "^{commit}"],
                          cwd=ROOT, capture_output=True).returncode == 0


@unittest.skipUnless(_tag_exists(), f"git tag {TAG} is not in this clone "
                     "(shallow checkout) -- run `git fetch --tags` to enable")
class Release_1_6_10_StillUpdates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = tempfile.mkdtemp(prefix="prism-1.6.10-")
        archive = subprocess.run(["git", "archive", TAG, *FILES], cwd=ROOT,
                                 capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", cls.old], input=archive, check=True)
        priv = Ed25519PrivateKey.generate()
        cls.pub = priv.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        cls.priv = priv.private_bytes(
            _ser.Encoding.Raw, _ser.PrivateFormat.Raw, _ser.NoEncryption()).hex()

    def run_old(self, manifest: dict) -> dict:
        token = UM.sign(manifest, self.priv, kid="u1")
        proc = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r)\n%s"
             % (self.old, PROBE)],
            input=json.dumps({"token": token, "pub": self.pub}),
            capture_output=True, text=True, cwd=self.old, timeout=120,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_plain_manifest_is_offered(self):
        got = self.run_old({"version": "1.6.11", "files": []})
        self.assertEqual(got["verify"], "ok")
        self.assertEqual(got["offered"], "1.6.11")

    def test_manifest_with_every_new_field_still_verifies_and_is_offered(self):
        got = self.run_old({"version": "1.6.11", "files": [],
                            "rollout": 5, "min_updater": 2,
                            "revoked": ["1.6.8"], "channel": "prod",
                            "mirrors": [{"kind": "static", "base": "https://x.example/p"}],
                            "needs": ["swap_v2"]})
        self.assertEqual(got["verify"], "ok")
        # 1.6.10 does not understand rollout, so it sees the release at once.
        # That is the known, accepted property of the bridge (docs/UPDATE-SYSTEM.md).
        self.assertEqual(got["offered"], "1.6.11")
        self.assertEqual(got["rollout"], 5)

    def test_old_client_is_not_confused_by_a_revoked_list_naming_itself(self):
        got = self.run_old({"version": "1.6.11", "files": [], "revoked": ["1.6.10"]})
        self.assertEqual(got["offered"], "1.6.11")


if __name__ == "__main__":
    unittest.main()

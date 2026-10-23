"""devtools/sign_manifest.py refuses a signing key no build would accept."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "devtools"))
sys.path.insert(0, ROOT)

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import sign_manifest as S
from licensing import keys


def fresh():
    k = Ed25519PrivateKey.generate()
    return k.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                           _ser.NoEncryption()).hex()


class KeyMatchesKid(unittest.TestCase):
    def test_the_command_refuses_a_mismatch_and_the_escape_is_explicit(self):
        import subprocess, tempfile, json
        work = tempfile.mkdtemp()
        man = os.path.join(work, "m.json")
        json.dump({"version": "9.9.9", "files": []}, open(man, "w"))
        base = [sys.executable, os.path.join(ROOT, "devtools", "sign_manifest.py"), man,
                "-o", os.path.join(work, "o"), "--key-hex", fresh(), "--allow-downgrade"]
        env = {**os.environ, "HOME": work, "USERPROFILE": work}
        refused = subprocess.run(base, capture_output=True, text=True, env=env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not the one published", refused.stderr)
        self.assertFalse(os.path.exists(os.path.join(work, "o")))
        allowed = subprocess.run(base + ["--allow-unpublished-key"],
                                 capture_output=True, text=True, env=env)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_a_random_key_is_refused_for_every_published_kid(self):
        for kid in {**keys.UPDATE_PRODUCTION, **keys.UPDATE_DEVELOPMENT}:
            with self.subTest(kid=kid), self.assertRaises(ValueError) as ctx:
                S.check_key_matches_kid(fresh(), kid)
            self.assertIn("not the one published", str(ctx.exception))

    def test_an_unknown_kid_is_refused(self):
        with self.assertRaises(ValueError):
            S.check_key_matches_kid(fresh(), "u99")

    def test_garbage_is_refused_with_a_clear_message(self):
        with self.assertRaises(ValueError):
            S.check_key_matches_kid("not-hex", "u1")

    def test_the_matching_key_is_accepted(self):
        """Against a temporary key table: the real private keys are not here."""
        from unittest import mock
        sec = fresh()
        pub = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sec)).public_key() \
            .public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        with mock.patch.dict(keys.UPDATE_DEVELOPMENT, {"udevT": pub}):
            S.check_key_matches_kid(sec, "udevT")

    def test_a_dev_key_is_not_accepted_for_the_prod_kid(self):
        from unittest import mock
        sec = fresh()
        pub = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(sec)).public_key() \
            .public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        with mock.patch.dict(keys.UPDATE_DEVELOPMENT, {"udevT": pub}):
            with self.assertRaises(ValueError):
                S.check_key_matches_kid(sec, "u1")

    def test_the_prod_and_dev_tables_share_no_key_id_and_no_key(self):
        self.assertFalse(set(keys.UPDATE_PRODUCTION) & set(keys.UPDATE_DEVELOPMENT))
        self.assertFalse(set(keys.UPDATE_PRODUCTION.values())
                         & set(keys.UPDATE_DEVELOPMENT.values()))

    def test_the_dev_key_on_disk_matches_the_published_public_half(self):
        path = os.path.expanduser("~/prism-keys/prism-update-dev-udev2.hex")
        if not os.path.exists(path):
            self.skipTest("the dev signing key is not on this machine")
        S.check_key_matches_kid(open(path).read().strip(), "udev2")


if __name__ == "__main__":
    unittest.main()

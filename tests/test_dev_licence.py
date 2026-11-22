"""The local dev licence (kid dev2) that devtools/run_flavour.sh mints.

What must hold (2026-11-23, when dev2 replaced a dev1 whose private key on
disk did not match it, so every minted token failed with bad_signature):

  · the production keys are exactly what they were;
  · a dev2 token verifies from source and is rejected by a frozen build;
  · mint.py signs only with a key whose public half matches the kid it
    names, so a mismatch fails at mint time and not inside the app;
  · the licence features of a flavour come from its add-on manifests;
  · no private key file is tracked by git.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

GUI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GUI)
sys.path.insert(0, os.path.join(GUI, "devtools"))

from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

import channel  # noqa: E402
import flavour  # noqa: E402
import mint  # noqa: E402
from licensing import keys, status as S, store, token as T  # noqa: E402


def _write_key(folder: str) -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    path = os.path.join(folder, "dev-signing-key.hex")
    with open(path, "w", encoding="utf-8") as f:
        f.write(private.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                                      _ser.NoEncryption()).hex())
    return path, mint.public_hex(private)


class ProductionKeysUntouched(unittest.TestCase):

    def test_production_licence_keys_are_pinned(self):
        self.assertEqual(keys.PRODUCTION, {
            "k1": "5c1133a2f92978d0b2813efa5e5405b84f9081a30d0d369d5ebe50645d5ba280"})

    def test_dev_kids_never_shadow_a_production_kid(self):
        self.assertFalse(set(keys.PRODUCTION) & set(keys.DEVELOPMENT))
        self.assertEqual(mint.DEV_KID, "dev2")
        self.assertIn(mint.DEV_KID, keys.DEVELOPMENT)


class MintSignsWithTheMatchingKid(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.key_path, self.pub = _write_key(self.tmp)

    def test_a_key_that_does_not_match_the_kid_is_refused(self):
        with mock.patch.object(mint, "KEY_PATH", self.key_path):
            with self.assertRaises(SystemExit) as ctx:
                mint.load_private("dev2")
        self.assertIn("not the private half", str(ctx.exception))

    def test_a_matching_key_signs_a_token_that_verifies_only_from_source(self):
        device_fp = "0123456789abcdef"
        with mock.patch.object(mint, "KEY_PATH", self.key_path), \
                mock.patch.dict(keys.DEVELOPMENT, {"dev2": self.pub}):
            private = mint.load_private("dev2")
            args = mock.Mock(now=0, days=30, ttl=30, kid="dev2",
                             license_id="lic_dev", customer="t", plan="dev",
                             kind="paid", features="core,reel", seats=1,
                             grace=0)
            raw = mint.sign(mint.build_claims(args, device_fp), private)
            claims = T.verify(raw, device_fp=device_fp,
                              public_keys=keys.public_keys())
            self.assertEqual(S.resolve(claims).status, S.VALID)
            with mock.patch.object(keys.paths, "is_frozen", return_value=True):
                with self.assertRaises(T.TokenError) as ctx:
                    T.verify(raw, device_fp=device_fp,
                             public_keys=keys.public_keys())
        self.assertEqual(ctx.exception.code, "unknown_key")


class FlavourFeatures(unittest.TestCase):

    def test_features_come_from_the_flavour_manifests(self):
        self.assertEqual(mint.flavour_features("studio"), ["core", "reel"])
        self.assertEqual(mint.flavour_features("sales"),
                         ["core", "email", "inbox", "leads", "marketing"])
        self.assertEqual(mint.flavour_features("engineering"),
                         ["core", "boq", "gerber", "step"])
        self.assertEqual(set(mint.flavour_features("complete")),
                         set(__import__("plans").FEATURES))

    def test_every_feature_named_is_a_real_licence_feature(self):
        import plans
        for name in flavour.FLAVOURS:
            for feat in mint.flavour_features(name):
                self.assertIn(feat, plans.FEATURES, f"{name}: {feat}")


class CmdFlavourWritesOnlyTheSandbox(unittest.TestCase):
    """mint.py flavour, run the way run_flavour.sh runs it, in a temp home."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.key_path, self.pub = _write_key(self.tmp)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        env = {k: v for k, v in os.environ.items()
               if k not in ("PRISM_HOME_ISOLATED", "PRISM_REAL_HOME")}
        env.update(HOME=self.home, USERPROFILE=self.home,
                   PRISM_HOME=os.path.join(self.home, ".prism-dev"))
        self.addCleanup(channel.remove_hook)
        patches = (mock.patch.dict(os.environ, env, clear=True),
                   mock.patch.object(mint, "KEY_PATH", self.key_path),
                   mock.patch.dict(keys.DEVELOPMENT, {"dev2": self.pub}))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run(self, name: str) -> str:
        out = []
        with mock.patch("builtins.print",
                        lambda *a, **k: out.append(" ".join(map(str, a)))
                        if "file" not in k else None):
            mint.cmd_flavour(mock.Mock(flavour=name, days=30))
        return out[-1]

    def test_mints_once_then_keeps_and_remints_for_new_features(self):
        self.assertEqual(self._run("studio"), "minted")
        user_dir = os.path.join(self.home, ".prism-dev", ".prism")
        self.assertTrue(os.path.isfile(store.path(user_dir)))
        self.assertEqual(self._run("studio"), "dev")
        # Same sandbox, a flavour that needs more: minted again.
        self.assertEqual(self._run("engineering"), "minted")
        claims = T.verify(store.load(user_dir)["token"],
                          device_fp=mint.device.fingerprint(user_dir)[0],
                          public_keys=keys.public_keys())
        self.assertEqual(claims["kid"], "dev2")
        self.assertEqual(claims["feat"], ["core", "boq", "gerber", "step"])


class NoPrivateKeyInGit(unittest.TestCase):

    def _git(self, *args):
        try:
            return subprocess.run(["git", "-C", GUI, *args], capture_output=True,
                                  text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            self.skipTest(f"git unavailable: {e}")

    def test_no_signing_key_file_is_tracked(self):
        listed = self._git("ls-files")
        if listed.returncode != 0:
            self.skipTest("not a git checkout")
        tracked = [p for p in listed.stdout.splitlines() if "signing-key" in p]
        self.assertEqual(tracked, [])
        ignored = self._git("check-ignore", "devtools/dev-signing-key.hex",
                            "devtools/dev-signing-key.hex.old-2026-11-23")
        self.assertEqual(len(ignored.stdout.split()), 2, ignored.stdout)

    def test_the_local_private_key_is_in_no_tracked_file(self):
        """Value never printed: only whether git grep found it."""
        path = (os.environ.get("PRISM_DEV_SIGNING_KEY")
                or os.path.join(GUI, "devtools", "dev-signing-key.hex"))
        if not os.path.isfile(path):
            self.skipTest("no local dev key in this checkout")
        with open(path, encoding="utf-8") as f:
            secret = f.read().strip()
        found = self._git("grep", "-q", "-F", "-i", secret)
        self.assertEqual(found.returncode, 1, "private key text is tracked")


if __name__ == "__main__":
    unittest.main()

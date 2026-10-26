"""devtools/release_all.py publishing the same release to a mirror repository.

`gh` is never run: every call is recorded. What matters is the ORDER (a client
that finds the manifest must find its files), that nothing is re-signed, and
that a mirror problem never makes the source release look failed."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "devtools"))
sys.path.insert(0, ROOT)

import release_all as R                                   # noqa: E402


class Mirror(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="mirror-")
        self.addCleanup(__import__("shutil").rmtree, self.work, True)
        self.plat = "linux-x64"
        self.signed = os.path.join(self.work, f"manifest.{self.plat}.signed")
        open(self.signed, "w").write("PRSMUv1.x.y")
        os.makedirs(os.path.join(self.work, f"update-assets-{self.plat}"))
        self.calls = []

    def fake_run(self, cmd, **kw):
        self.calls.append(("run", cmd))

    def mirror(self, *, release_exists=False, publish=None):
        def publish_assets(repo, tag, plat, signed, assets_dir):
            self.calls.append(("assets", repo, tag, plat, signed))
            if publish:
                publish(repo)
        with mock.patch.object(R, "run", side_effect=self.fake_run), \
             mock.patch.object(R, "_release_exists", return_value=release_exists), \
             mock.patch.object(R, "publish_assets", side_effect=publish_assets):
            R.mirror_platform("org/repo", "v1.6.11", self.work, self.plat, "old/repo")

    def kinds(self):
        out = []
        for c in self.calls:
            if c[0] == "assets":
                out.append("assets")
            else:
                out.append(" ".join(c[1][:3]))
        return out

    def test_assets_go_up_before_the_manifest(self):
        self.mirror()
        self.assertEqual(self.kinds(), ["gh release create", "assets", "gh release upload"])
        upload = self.calls[-1][1]
        self.assertIn("--clobber", upload)
        self.assertEqual(upload[-1], self.signed, "the manifest is the LAST thing sent")

    def test_the_same_signed_bytes_are_sent_nothing_is_re_signed(self):
        self.mirror()
        flat = " ".join(" ".join(c[1]) for c in self.calls if c[0] == "run")
        self.assertNotIn("sign_manifest", flat)
        self.assertEqual(self.calls[-1][1][-1], self.signed)

    def test_an_existing_mirror_release_is_not_created_again(self):
        self.mirror(release_exists=True)
        self.assertEqual(self.kinds(), ["assets", "gh release upload"])

    def test_the_mirror_release_is_a_normal_one_so_it_becomes_latest(self):
        self.mirror()
        create = self.calls[0][1]
        self.assertNotIn("--prerelease", create)
        self.assertEqual(create[create.index("--target") + 1], "main")

    def test_a_failed_asset_upload_means_the_manifest_is_never_published(self):
        def boom(repo):
            raise RuntimeError("files still missing")
        with self.assertRaises(RuntimeError):
            self.mirror(publish=boom)
        self.assertFalse(any(c[0] == "run" and "upload" in c[1] for c in self.calls),
                         "no manifest may go up if its files did not")

    def test_refuses_when_the_source_release_has_not_been_done(self):
        os.remove(self.signed)
        with self.assertRaises(RuntimeError):
            self.mirror()


class Main(unittest.TestCase):
    """The command: which repos, and what the exit code says."""

    def run_main(self, argv, *, platform_ok=True, mirror_ok=True):
        def do_platform(repo, tag, run_id, work, plat, matrix, force, kid="u1"):
            if not platform_ok:
                raise RuntimeError("source failed")

        def mirror(mirror_repo, tag, work, plat, src):
            if not mirror_ok:
                raise RuntimeError("mirror failed")
            self.mirrored.append((mirror_repo, plat))
        self.mirrored = []
        with mock.patch.object(R, "do_platform", side_effect=do_platform), \
             mock.patch.object(R, "mirror_platform", side_effect=mirror):
            return R.main(["v1.6.11", "123", "--work-dir", tempfile.mkdtemp(),
                           "--only", "linux-x64", *argv])

    def test_the_source_repo_stays_the_old_name_and_the_org_is_mirrored_by_default(self):
        self.assertEqual(R.DEFAULT_MIRRORS, ("AlphaKore5/prism_gui",))
        self.assertEqual(self.run_main([]), 0)
        self.assertEqual(self.mirrored, [("AlphaKore5/prism_gui", "linux-x64")])

    def test_no_mirror_publishes_the_source_only(self):
        self.assertEqual(self.run_main(["--no-mirror"]), 0)
        self.assertEqual(self.mirrored, [])

    def test_a_mirror_failure_is_exit_2_not_a_failed_release(self):
        self.assertEqual(self.run_main([], mirror_ok=False), 2)

    def test_a_source_failure_is_exit_1_and_nothing_is_mirrored(self):
        self.assertEqual(self.run_main([], platform_ok=False), 1)
        self.assertEqual(self.mirrored, [])

    def test_mirrors_can_be_chosen(self):
        self.run_main(["--mirror", "a/b", "--mirror", "c/d"])
        self.assertEqual([m for m, _ in self.mirrored], ["a/b", "c/d"])


class SourcePublishOrder(unittest.TestCase):
    """On the repository CI builds in, the signed manifest goes up AFTER every
    file it lists. Otherwise a computer that checks mid-publish is offered a
    version whose files are not there yet."""

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="order-")
        self.addCleanup(__import__("shutil").rmtree, self.work, True)
        self.plat = "linux-x64"
        self.signed = os.path.join(self.work, f"manifest.{self.plat}.signed")
        self.assets = os.path.join(self.work, f"update-assets-{self.plat}")
        os.makedirs(self.assets)
        open(os.path.join(self.assets, "f"), "w").write("x")
        self.calls = []

    def run_platform(self, *, on_release=False, publish_raises=False, force=False):
        def fake_run(cmd, **kw):
            self.calls.append(" ".join(str(c) for c in cmd[:3]) if cmd[0] != sys.executable else "sign")
            if cmd[0] == sys.executable:                 # the signing step writes the file
                open(self.signed, "w").write("PRSMUv1.x.y")

        def fake_publish(*a, **k):
            self.calls.append("assets")
            if publish_raises:
                raise RuntimeError("upload failed")

        with mock.patch.object(R, "run", side_effect=fake_run), \
             mock.patch.dict(os.environ, {"UPDATE_SIGNING_KEY_HEX": "00" * 32}), \
             mock.patch.object(R, "already_signed", return_value=on_release), \
             mock.patch.object(R, "publish_assets", side_effect=fake_publish):
            R.do_platform("old/repo", "v1.6.12", "1", self.work, self.plat, "ubuntu-22.04", force)

    def test_the_manifest_is_the_last_thing_sent(self):
        self.run_platform()
        self.assertIn("assets", self.calls)
        self.assertEqual("gh release upload", self.calls[-1])
        self.assertLess(self.calls.index("assets"), len(self.calls) - 1)

    def test_a_failed_file_upload_leaves_the_manifest_unpublished(self):
        with self.assertRaises(RuntimeError):
            self.run_platform(publish_raises=True)
        self.assertNotIn("gh release upload", self.calls)

    def test_a_rerun_after_a_partial_upload_reuses_the_signed_file_and_does_not_re_sign(self):
        open(self.signed, "w").write("PRSMUv1.signed.earlier")
        self.run_platform()
        self.assertNotIn("sign", self.calls)
        self.assertEqual("gh release upload", self.calls[-1])
        self.assertEqual("PRSMUv1.signed.earlier", open(self.signed).read())

    def test_a_manifest_already_on_the_release_is_not_sent_again(self):
        open(self.signed, "w").write("PRSMUv1.x.y")
        self.run_platform(on_release=True)
        self.assertNotIn("sign", self.calls)
        self.assertNotIn("gh release upload", self.calls)
        self.assertIn("assets", self.calls)


if __name__ == "__main__":
    unittest.main()


class Channels(unittest.TestCase):
    """--dev and prod can never be mixed by accident."""

    def test_default_is_prod_with_the_org_mirror_and_the_prod_key(self):
        self.assertEqual(R.resolve_channel(None, None, False, False),
                         ("HitarthTrivedi/prism_gui", ["AlphaKore5/prism_gui"], "u1"))

    def test_dev_uses_the_dev_repo_the_dev_key_and_no_mirror(self):
        self.assertEqual(R.resolve_channel(None, None, False, True),
                         (R.DEV_REPO, [], "udev2"))

    def test_dev_refuses_every_production_repository(self):
        for repo in R.PROD_REPOS:
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                R.resolve_channel(repo, None, False, True)

    def test_dev_refuses_a_mirror(self):
        with self.assertRaises(ValueError):
            R.resolve_channel(None, ["a/b"], False, True)

    def test_prod_refuses_the_dev_repository(self):
        for repo in (R.DEV_REPO, "someone/prism_gui_dev"):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                R.resolve_channel(repo, None, False, False)

    def test_no_mirror_still_works_for_prod(self):
        self.assertEqual(R.resolve_channel(None, None, True, False)[1], [])

    def test_main_rejects_a_mixed_up_command_before_touching_anything(self):
        with mock.patch.object(R, "do_platform") as do, \
             self.assertRaises(SystemExit):
            R.main(["v1.6.11", "1", "--repo", R.DEV_REPO])
        do.assert_not_called()

    def test_main_signs_dev_releases_with_the_dev_kid(self):
        seen = []
        with mock.patch.object(R, "do_platform",
                               side_effect=lambda *a: seen.append(a)), \
             mock.patch.object(R, "mirror_platform") as mirror:
            R.main(["v1.6.11", "1", "--dev", "--only", "linux-x64",
                    "--work-dir", tempfile.mkdtemp()])
        self.assertEqual(seen[0][0], R.DEV_REPO)
        self.assertEqual(seen[0][-1], "udev2")
        mirror.assert_not_called()


class DevManifestsAreReadWithTheDevKeys(unittest.TestCase):
    """release_all read every manifest with the production keys only, so the
    first dev publish signed fine and then could not read its own file list."""

    def setUp(self):
        from cryptography.hazmat.primitives import serialization as ser
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        import licensing.keys as K
        import update_manifest as UM
        k = Ed25519PrivateKey.generate()
        self.sec = k.private_bytes(ser.Encoding.Raw, ser.PrivateFormat.Raw,
                                   ser.NoEncryption()).hex()
        pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw).hex()
        patch = mock.patch.dict(K.UPDATE_DEVELOPMENT, {"udevT": pub})
        patch.start()
        self.addCleanup(patch.stop)
        self.UM, self.K = UM, K
        entry = {"path": "Prism", "size": 3, "sha256": "0" * 64, "mode": 0}
        token = UM.sign({"version": "1.0.0", "files": [entry]}, self.sec, kid="udevT")
        self.path = os.path.join(tempfile.mkdtemp(), "manifest.linux-x64.signed")
        open(self.path, "w").write(token)

    def test_keys_for_picks_one_table_never_both(self):
        self.assertEqual(R.keys_for("udevT"), self.K.UPDATE_DEVELOPMENT)
        self.assertEqual(R.keys_for("u1"), self.K.UPDATE_PRODUCTION)
        self.assertFalse(set(R.keys_for("udevT")) & set(R.keys_for("u1")))

    def test_a_dev_signed_manifest_is_readable_with_its_dev_kid(self):
        got = R.expected_flat_names(self.path, "linux-x64", "udevT")
        self.assertEqual(got, {1: {"linux-x64__Prism": "Prism"}})

    def test_the_same_file_is_refused_when_read_as_production(self):
        with self.assertRaises(self.UM.ManifestError):
            R.expected_flat_names(self.path, "linux-x64")      # default kid: u1

    def test_verify_upload_reads_it_the_same_way(self):
        import verify_upload as V
        self.assertEqual(V.expected_flat_names(self.path, "linux-x64", 1, "udevT"),
                         {"linux-x64__Prism": "Prism"})
        with self.assertRaises(self.UM.ManifestError):
            V.expected_flat_names(self.path, "linux-x64", 1)

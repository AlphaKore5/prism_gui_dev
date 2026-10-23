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
        def do_platform(repo, tag, run_id, work, plat, matrix, force):
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


if __name__ == "__main__":
    unittest.main()

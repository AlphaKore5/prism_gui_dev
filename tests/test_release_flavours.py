"""devtools/release_all.py releasing ONE FLAVOUR (dev only): v<version>-<flavour>.

`gh` is never run: every call is recorded. What matters is that
  - the update-asset releases are named from the VERSION (v2.0.0-assets-windows-x64-studio),
    exactly as updater._assets_release_tag() computes them, never from the release tag,
  - the manifest and assets carry the flavour's CHANNEL name,
  - `latest` can serve every channel (manifests carried over),
  - a flavour release can never be production, and is made at an exact commit,
  - a flavour's tag cannot start a Complete build in CI (it would attach Complete's
    installers to that flavour's release).
Complete's own flow is unchanged."""
from __future__ import annotations

import fnmatch
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "devtools"))
sys.path.insert(0, ROOT)

import flavour as FL                                      # noqa: E402
import release_all as R                                   # noqa: E402
import updater                                            # noqa: E402

SHA = "4ea2142" + "0" * 33


class Tags(unittest.TestCase):
    def test_a_flavour_release_tag_and_its_base_tag(self):
        self.assertEqual(R.flavour_tags("v2.0.0-studio", "studio"), ("v2.0.0-studio", "v2.0.0"))
        self.assertEqual(R.flavour_tags("v2.0.0-sales", "sales"), ("v2.0.0-sales", "v2.0.0"))
        self.assertEqual(R.flavour_tags("v1.8.9", "complete"), ("v1.8.9", "v1.8.9"))

    def test_a_tag_of_another_flavour_or_none_is_refused(self):
        for tag, flavour in (("v2.0.0", "studio"), ("v2.0.0-sales", "studio"),
                             ("2.0.0-studio", "studio"), ("v-studio", "studio")):
            with self.assertRaises(ValueError, msg=(tag, flavour)):
                R.flavour_tags(tag, flavour)

    def test_artifact_names_are_the_ones_build_yml_makes(self):
        self.assertEqual(R.artifact_names("windows-latest"),
                         ("prism-windows-latest", "update-assets-windows-latest"))
        self.assertEqual(R.artifact_names("windows-latest", "studio"),
                         ("prism-studio-windows-latest", "update-assets-studio-windows-latest"))

    def test_every_flavour_has_a_release_and_complete_does_not(self):
        self.assertEqual(set(R.FLAVOURS), set(FL.IDENTITY) - {"complete"})


class Recorder(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="relflav-")
        self.addCleanup(__import__("shutil").rmtree, self.work, True)
        self.calls = []
        env = mock.patch.dict(os.environ, {"UPDATE_SIGNING_KEY_HEX": "00" * 32})
        env.start()
        self.addCleanup(env.stop)

    def fake_run(self, cmd, **kw):
        self.calls.append(list(cmd))

    def gh(self):
        """The recorded `gh ...` calls, as strings."""
        return [" ".join(c) for c in self.calls if c and c[0] == "gh"]


class OnePlatform(Recorder):
    def release(self, tag, flavour, platform="windows-x64", os_name="windows-latest",
                signed_already=False):
        published = []
        with mock.patch.object(R, "run", side_effect=self.fake_run), \
             mock.patch.object(R, "already_signed", return_value=signed_already), \
             mock.patch.object(R, "publish_assets",
                               side_effect=lambda *a: published.append(a)):
            R.do_platform("org/dev", tag, "123", self.work, platform, os_name,
                          False, "udev2", flavour)
        return published

    def test_a_flavour_uses_its_channel_names_and_the_version_based_assets_tag(self):
        published = self.release("v2.0.0-studio", "studio")
        (repo, base, channel, signed, assets_dir, kid), = published
        self.assertEqual((repo, base, channel, kid), ("org/dev", "v2.0.0", "windows-x64-studio", "udev2"))
        self.assertTrue(signed.endswith("manifest.windows-x64-studio.signed"))
        calls = self.gh()
        self.assertIn("gh run download 123 -R org/dev -n update-assets-studio-windows-latest -D "
                      + assets_dir, calls)
        self.assertTrue(any(c.startswith("gh release download v2.0.0-studio -R org/dev -p "
                                         "manifest.windows-x64-studio.unsigned.json") for c in calls))
        # the signed manifest goes on the flavour's RELEASE, last
        self.assertTrue(calls[-1].startswith("gh release upload v2.0.0-studio -R org/dev --clobber"))
        self.assertTrue(calls[-1].endswith("manifest.windows-x64-studio.signed"))

    def test_the_assets_tag_is_exactly_what_the_updater_will_ask_for(self):
        published = self.release("v2.0.0-engineering", "engineering", "linux-x64", "ubuntu-22.04")
        _repo, base, channel, *_ = published[0]
        self.assertEqual(R._assets_tag(base, channel),
                         updater._assets_release_tag("2.0.0", channel))
        self.assertEqual(R._assets_tag(base, channel), "v2.0.0-assets-linux-x64-engineering")

    def test_complete_is_exactly_as_before(self):
        published = self.release("v1.8.9", "complete")
        (_repo, base, channel, signed, _dir, _kid), = published
        self.assertEqual((base, channel), ("v1.8.9", "windows-x64"))
        self.assertTrue(signed.endswith("manifest.windows-x64.signed"))
        self.assertIn("gh run download 123 -R org/dev -n update-assets-windows-latest -D "
                      + os.path.join(self.work, "update-assets-windows-x64"), self.gh())


class FlavourRelease(Recorder):
    def create(self, exists=False, preload=True):
        if preload:        # the installers already downloaded: no `gh run download`
            for plat in ("windows-x64-studio",):
                d = os.path.join(self.work, f"installers-{plat}")
                os.makedirs(d)
                for n in ("Prism-studio-2.0.0-windows-x64-setup.exe",
                          "manifest.windows-x64-studio.unsigned.json"):
                    open(os.path.join(d, n), "w").write("x")
        with mock.patch.object(R, "run", side_effect=self.fake_run), \
             mock.patch.object(R, "_release_exists", return_value=exists):
            R.create_flavour_release("org/dev", "v2.0.0-studio", "123", "studio", SHA,
                                     self.work, [("windows-x64", "windows-latest")])
        return self.gh()

    def test_created_at_the_commit_not_latest_then_the_installers_uploaded(self):
        calls = self.create()
        self.assertEqual(len(calls), 2)
        self.assertIn(f"--target {SHA}", calls[0])
        self.assertIn("--latest=false", calls[0])
        self.assertIn("Prism Studio 2.0.0", calls[0])
        self.assertTrue(calls[1].startswith("gh release upload v2.0.0-studio -R org/dev --clobber"))
        self.assertIn("Prism-studio-2.0.0-windows-x64-setup.exe", calls[1])
        self.assertIn("manifest.windows-x64-studio.unsigned.json", calls[1])

    def test_the_installers_come_from_the_flavours_own_artifact(self):
        def download(cmd, **kw):
            self.calls.append(list(cmd))
            if cmd[:3] == ["gh", "run", "download"]:        # what gh would leave behind
                dest = cmd[cmd.index("-D") + 1]
                os.makedirs(dest)
                open(os.path.join(dest, "Prism-studio-2.0.0-windows-x64-setup.exe"), "w").write("x")
        with mock.patch.object(R, "run", side_effect=download), \
             mock.patch.object(R, "_release_exists", return_value=True):
            R.create_flavour_release("org/dev", "v2.0.0-studio", "123", "studio", SHA,
                                     self.work, [("windows-x64", "windows-latest")])
        calls = self.gh()
        self.assertEqual(calls[0].split(" -D")[0], "gh run download 123 -R org/dev -n prism-studio-windows-latest")
        self.assertIn("Prism-studio-2.0.0-windows-x64-setup.exe", calls[1])

    def test_an_existing_release_is_not_created_again(self):
        self.assertFalse(any(c.startswith("gh release create") for c in self.create(exists=True)))


class Carry(Recorder):
    def test_every_other_release_manifests_land_on_this_one_and_never_itself(self):
        os.makedirs(os.path.join(self.work, "carried"))
        for n in ("manifest.windows-x64-sales.signed", "manifest.windows-x64.signed", "notes.txt"):
            open(os.path.join(self.work, "carried", n), "w").write("x")
        with mock.patch.object(R, "run", side_effect=self.fake_run):
            R.carry_signed_manifests("org/dev", "v2.0.0-studio",
                                     ["v2.0.0-sales", "v1.8.9", "v2.0.0-studio"], self.work)
        calls = self.gh()
        self.assertEqual([c.split(" -R")[0] for c in calls[:2]],
                         ["gh release download v2.0.0-sales", "gh release download v1.8.9"])
        self.assertTrue(all("-p manifest.*.signed" in c for c in calls[:2]))
        self.assertTrue(calls[2].startswith("gh release upload v2.0.0-studio -R org/dev --clobber"))
        self.assertIn("manifest.windows-x64-sales.signed", calls[2])
        self.assertNotIn("notes.txt", calls[2])


class Command(Recorder):
    """The command line: dev only, an exact commit, the right order."""
    def main(self, *args):
        with mock.patch.object(R, "run", side_effect=self.fake_run), \
             mock.patch.object(R, "create_flavour_release") as create, \
             mock.patch.object(R, "do_platform") as do, \
             mock.patch.object(R, "carry_signed_manifests") as carry:
            order = []
            create.side_effect = lambda *a, **k: order.append("create")
            do.side_effect = lambda *a, **k: order.append("platform:" + a[4])
            carry.side_effect = lambda *a, **k: order.append("carry")
            rc = R.main(["--work-dir", self.work, *args])
        return rc, order, self.gh()

    def test_a_flavour_release_is_dev_only(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.main("v2.0.0-studio", "123", "--flavour", "studio", "--target", SHA)

    def test_it_needs_the_full_commit_id(self):
        for bad in (None, "main", "4ea2142", "Z" * 40):
            args = ["v2.0.0-studio", "123", "--dev", "--flavour", "studio"]
            if bad:
                args += ["--target", bad]
            with self.assertRaises(SystemExit, msg=bad), mock.patch("sys.stderr"):
                self.main(*args)

    def test_the_tag_must_name_the_flavour(self):
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            self.main("v2.0.0", "123", "--dev", "--flavour", "studio", "--target", SHA)

    def test_release_first_then_each_platform_then_carry_then_latest(self):
        rc, order, gh = self.main("v2.0.0-studio", "123", "--dev", "--flavour", "studio",
                                  "--target", SHA, "--only", "windows-x64",
                                  "--carry-from", "v1.8.9", "--make-latest")
        self.assertEqual(rc, 0)
        self.assertEqual(order, ["create", "platform:windows-x64", "carry"])
        self.assertEqual(gh[-1], "gh release edit v2.0.0-studio -R AlphaKore5/prism_gui_dev --latest")

    def test_not_latest_unless_asked_and_never_after_a_failure(self):
        rc, order, gh = self.main("v2.0.0-studio", "123", "--dev", "--flavour", "studio",
                                  "--target", SHA, "--only", "windows-x64")
        self.assertFalse(any("--latest" in c and "edit" in c for c in gh))
        with mock.patch.object(R, "run"), mock.patch.object(R, "create_flavour_release"), \
             mock.patch.object(R, "do_platform", side_effect=RuntimeError("boom")), \
             mock.patch.object(R, "carry_signed_manifests") as carry:
            rc = R.main(["--work-dir", self.work, "v2.0.0-studio", "123", "--dev",
                         "--flavour", "studio", "--target", SHA, "--only", "windows-x64",
                         "--make-latest", "--carry-from", "v1.8.9"])
        self.assertEqual(rc, 1)
        carry.assert_not_called()


class CiTagFilter(unittest.TestCase):
    """GitHub reads build.yml at the TAGGED commit: a flavour tag that matched
    `v*` would run the Complete build and attach its installers to that
    flavour's release."""
    @staticmethod
    def triggers(tag: str, patterns: list[str]) -> bool:
        hit = False
        for pat in patterns:
            neg = pat.startswith("!")
            if fnmatch.fnmatchcase(tag, pat.lstrip("!")):
                hit = not neg
        return hit

    def patterns(self):
        import yaml
        with open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
            return yaml.safe_load(f)[True]["push"]["tags"]

    def test_a_plain_version_tag_builds_and_no_flavour_or_assets_tag_does(self):
        pats = self.patterns()
        self.assertTrue(self.triggers("v2.0.0", pats))
        self.assertTrue(self.triggers("v1.8.9", pats))
        for flavour in R.FLAVOURS:
            self.assertFalse(self.triggers(f"v2.0.0-{flavour}", pats), flavour)
            self.assertFalse(self.triggers(f"v2.0.0-assets-windows-x64-{flavour}", pats), flavour)
        self.assertFalse(self.triggers("v2.0.0-assets-linux-x64-3", pats))


if __name__ == "__main__":
    unittest.main()

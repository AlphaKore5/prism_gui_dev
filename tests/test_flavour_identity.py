"""Gate G2 data: per-flavour names, bundle ids and update channel names.

Only the DATA is tested (flavour.IDENTITY and flavour.update_channel). Nothing
reads it yet: app_meta, build.py, updater.py and CI are untouched, so no build
or release changes. What is NOT proven here: that an installer, .app, Start
menu entry, signature or in-app update swap works under these names.
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app_meta  # noqa: E402
import flavour  # noqa: E402

PLATFORMS = (("win32", "windows"), ("darwin", "macos"), ("linux", "linux"))
ARCHES = ("x64", "arm64")


class CompleteIsExactlyToday(unittest.TestCase):

    def test_names_and_bundle_id_equal_app_meta(self):
        ident = flavour.IDENTITY["complete"]
        self.assertEqual(ident["name"], app_meta.NAME)
        self.assertEqual(ident["bundle_id"], app_meta.BUNDLE_ID)
        self.assertEqual(ident["channel"], "")

    def test_update_channel_is_updaters_tag_on_every_os_and_arch(self):
        import updater
        for plat, _os in PLATFORMS:
            for arch in ARCHES:
                with self.subTest(platform=plat, arch=arch), \
                     mock.patch.object(sys, "platform", plat), \
                     mock.patch.object(updater, "_arch_tag", return_value=arch):
                    tag = updater.platform_tag()
                    self.assertEqual(flavour.update_channel(tag, "complete"), tag)


class FlavoursNeverCollide(unittest.TestCase):

    def test_every_field_is_distinct(self):
        for field in ("name", "display", "bundle_id", "channel"):
            values = [i[field] for i in flavour.IDENTITY.values()]
            self.assertEqual(len(set(values)), len(values), field)

    def test_table_covers_exactly_the_flavours(self):
        self.assertEqual(set(flavour.IDENTITY), set(flavour.FLAVOURS))

    def test_names_are_safe_for_folders_archives_and_bundle_ids(self):
        for f, i in flavour.IDENTITY.items():
            self.assertRegex(i["name"], r"^[A-Za-z][A-Za-z0-9-]*$", f)
            self.assertRegex(i["bundle_id"], r"^[a-z0-9]+(\.[a-z0-9]+)+$", f)
            self.assertRegex(i["channel"], r"^[a-z]*$", f)
            self.assertTrue(i["display"].startswith("Prism"), f)

    def test_archive_stems_differ(self):
        stems = {f"{i['name']}-{app_meta.VERSION}-windows-x64"
                 for i in flavour.IDENTITY.values()}
        self.assertEqual(len(stems), len(flavour.IDENTITY))

    def test_channels_differ_on_every_os_and_arch(self):
        """No two flavours, on any platform, share a manifest or asset tag; and
        no flavour's channel equals ANY complete channel, so a client that
        asks for today's name (every 1.6.10/1.6.11 and older install, which
        send no channel) is never served a flavour's manifest."""
        import updater
        complete_tags = set()
        flavour_tags = {}
        for plat, _os in PLATFORMS:
            for arch in ARCHES:
                with mock.patch.object(sys, "platform", plat), \
                     mock.patch.object(updater, "_arch_tag", return_value=arch):
                    base = updater.platform_tag()
                for f in flavour.FLAVOURS:
                    tag = flavour.update_channel(base, f)
                    if f == "complete":
                        complete_tags.add(tag)
                    else:
                        flavour_tags.setdefault(f, set()).add(tag)
                    self.assertTrue(
                        re.fullmatch(r"(windows|macos|linux)-(x64|arm64)(-app)?"
                                     r"(-[a-z]+)?", tag), tag)
        every = [t for ts in flavour_tags.values() for t in ts]
        self.assertEqual(len(every), len(set(every)))
        self.assertFalse(complete_tags & set(every))

    def test_macos_keeps_its_app_marker_before_the_flavour(self):
        self.assertEqual(flavour.update_channel("macos-arm64-app", "sales"),
                         "macos-arm64-app-sales")
        self.assertEqual(flavour.update_channel("windows-x64", "studio"),
                         "windows-x64-studio")

    def test_identity_follows_the_build_constant(self):
        with mock.patch.object(flavour, "FLAVOUR", "sales"):
            self.assertEqual(flavour.identity()["name"], "Prism-Sales")
        self.assertEqual(flavour.identity("complete")["name"], "Prism")

    def test_nothing_reads_the_table_yet(self):
        """G2 is data only. When something is wired to IDENTITY this test must
        change in the same commit, saying why."""
        for rel in ("app_meta.py", "updater.py", os.path.join("packaging", "build.py")):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                self.assertNotIn("IDENTITY", f.read(), rel)


if __name__ == "__main__":
    unittest.main()

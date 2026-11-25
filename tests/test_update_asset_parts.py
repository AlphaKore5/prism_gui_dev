"""A build too big for one GitHub release is hosted across several.

1.6.1's Windows build was 991 files, 9 under GitHub's 1000-assets-per-release
cap. 1.6.2's STEP engine (cadquery, OCP, vtk) took it to 1466 (Linux and macOS
1542) and CI failed on all three at "Generate the (unsigned) update manifest" —
the release could not be published at all. The files are now split: each names
its part in the signed manifest, part 1 stays at `<tag>-assets-<platform>`
where every older build and client look, and the rest continue in `-2`, `-3`.

These tests hold the whole chain together — the build assigns parts, the signed
manifest carries them, the updater fetches each file from the release that
holds it, and the release tool uploads each release exactly its own files —
and that a build small enough for one release is untouched.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "devtools"))

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import update_manifest as UM
import updater


def _keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key().public_bytes(_ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
    return priv.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                              _ser.NoEncryption()).hex(), pub


def _manifest(n_hosted: int, extra=()):
    """n_hosted real-looking files, path-sorted like update_manifest.build()."""
    files = [{"path": f"_internal/f{i:05d}.dat", "size": 10 + i,
              "sha256": hashlib.sha256(str(i).encode()).hexdigest(), "mode": 0}
             for i in range(n_hosted)]
    files += list(extra)
    files.sort(key=lambda f: f["path"])
    return {"version": "1.6.3", "files": files}


class AssigningParts(unittest.TestCase):

    def test_a_small_build_needs_one_release_and_carries_no_part_keys(self):
        m = _manifest(UM.ASSETS_PER_RELEASE)
        self.assertEqual(UM.assign_parts(m), 1)
        self.assertTrue(all("part" not in e for e in m["files"]))

    def test_one_file_past_a_release_starts_the_next(self):
        m = _manifest(UM.ASSETS_PER_RELEASE + 1)
        self.assertEqual(UM.assign_parts(m), 2)
        parts = [UM.part_of(e) for e in m["files"]]
        self.assertEqual(parts.count(1), UM.ASSETS_PER_RELEASE)
        self.assertEqual(parts[-1], 2)

    def test_the_1542_file_build_that_broke_1_6_2_fits_two_releases(self):
        m = _manifest(1542)
        self.assertEqual(UM.assign_parts(m), 2)
        per_part = {}
        for e in m["files"]:
            per_part[UM.part_of(e)] = per_part.get(UM.part_of(e), 0) + 1
        self.assertEqual(sum(per_part.values()), 1542)
        self.assertTrue(all(n <= 1000 for n in per_part.values()), per_part)

    def test_symlinks_and_empty_files_use_no_asset_and_no_part(self):
        extra = [{"path": "z/link", "symlink": "../x"},
                 {"path": "z/empty", "size": 0, "sha256": "e3b0", "mode": 0}]
        m = _manifest(UM.ASSETS_PER_RELEASE + 5, extra)
        self.assertEqual(UM.assign_parts(m), 2)
        for e in m["files"]:
            if not UM.is_hosted(e):
                self.assertNotIn("part", e, e["path"])

    def test_assigning_twice_gives_the_same_answer(self):
        m = _manifest(2000)
        UM.assign_parts(m)
        first = [dict(e) for e in m["files"]]
        UM.assign_parts(m)
        self.assertEqual(first, m["files"])

    def test_the_tag_tail_is_empty_for_part_one_and_numbered_after(self):
        self.assertEqual([UM.parts_suffix(p) for p in (1, 2, 3)], ["", "-2", "-3"])


class TheSignedManifestCarriesThem(unittest.TestCase):

    def setUp(self):
        self.priv, self.pub = _keypair()

    def _verify(self, manifest):
        token = UM.sign(manifest, self.priv, kid="u1")
        return UM.verify(token, public_keys={"u1": self.pub})

    def test_parts_survive_signing_and_verifying(self):
        m = _manifest(UM.ASSETS_PER_RELEASE + 3)
        UM.assign_parts(m)
        payload = self._verify(m)
        self.assertEqual({UM.part_of(e) for e in payload["files"]}, {1, 2})

    def test_a_part_that_is_not_a_plain_number_is_refused(self):
        for bad in (True, 0, 1, 10, "2", 2.0, None, [2]):
            m = _manifest(3)
            m["files"][0]["part"] = bad
            with self.assertRaises(UM.ManifestError, msg=repr(bad)) as ctx:
                self._verify(m)
            self.assertEqual(ctx.exception.code, "malformed")


class TheUpdaterFetchesEachFileFromItsOwnRelease(unittest.TestCase):

    def test_part_one_is_where_every_older_client_already_looks(self):
        self.assertEqual(updater._assets_release_tag("1.6.3", "windows-x64"),
                         "v1.6.3-assets-windows-x64")
        self.assertEqual(updater._assets_release_tag("1.6.3", "windows-x64", 1),
                         "v1.6.3-assets-windows-x64")

    def test_later_parts_continue_in_numbered_releases(self):
        self.assertEqual(updater._assets_release_tag("1.6.3", "windows-x64", 2),
                         "v1.6.3-assets-windows-x64-2")
        with mock.patch.object(updater, "update_channel", return_value="linux-x64"):
            one = updater._file_url("1.6.3", "_internal/a.dat")
            two = updater._file_url("1.6.3", "_internal/a.dat", 2)
        self.assertIn("/v1.6.3-assets-linux-x64/linux-x64__", one)
        self.assertIn("/v1.6.3-assets-linux-x64-2/linux-x64__", two)
        self.assertEqual(one.rsplit("/", 1)[1], two.rsplit("/", 1)[1])   # same file name, other release


class TheReleaseToolUploadsEachReleaseItsOwnFiles(unittest.TestCase):

    def setUp(self):
        import release_all
        import verify_upload
        self.RA, self.VU = release_all, verify_upload
        self.priv, self.pub = _keypair()
        self.tmp = tempfile.mkdtemp(prefix="prism-parts-")

    def _signed_file(self, manifest):
        path = os.path.join(self.tmp, "manifest.windows-x64.signed")
        with open(path, "w", encoding="utf-8") as f:
            f.write(UM.sign(manifest, self.priv, kid="u1"))
        return path

    def test_expected_names_are_grouped_by_the_release_that_holds_them(self):
        m = _manifest(UM.ASSETS_PER_RELEASE + 7,
                      [{"path": "z/link", "symlink": "../x"}])
        UM.assign_parts(m)
        path = self._signed_file(m)
        with mock.patch.object(self.RA.K, "UPDATE_PRODUCTION", {"u1": self.pub}):
            grouped = self.RA.expected_flat_names(path, "windows-x64")
        self.assertEqual(sorted(grouped), [1, 2])
        self.assertEqual(len(grouped[1]), UM.ASSETS_PER_RELEASE)
        self.assertEqual(len(grouped[2]), 7)
        self.assertEqual(set(grouped[1]) & set(grouped[2]), set())

    def test_a_small_build_is_a_single_group(self):
        m = _manifest(40)
        UM.assign_parts(m)
        with mock.patch.object(self.RA.K, "UPDATE_PRODUCTION", {"u1": self.pub}):
            grouped = self.RA.expected_flat_names(self._signed_file(m), "windows-x64")
        self.assertEqual(list(grouped), [1])

    def test_the_release_tag_per_part(self):
        self.assertEqual(self.RA._assets_tag("v1.6.3", "windows-x64"),
                         "v1.6.3-assets-windows-x64")
        self.assertEqual(self.RA._assets_tag("v1.6.3", "windows-x64", 2),
                         "v1.6.3-assets-windows-x64-2")

    def test_the_updater_and_the_release_tool_name_the_same_release(self):
        for part in (1, 2, 3):
            self.assertEqual(
                self.RA._assets_tag("v1.6.3", "linux-x64", part),
                updater._assets_release_tag("1.6.3", "linux-x64", part))

    def test_verify_upload_reads_the_part_off_the_tag_and_checks_only_it(self):
        m = _manifest(UM.ASSETS_PER_RELEASE + 4)
        UM.assign_parts(m)
        path = self._signed_file(m)
        with mock.patch.object(self.VU.K, "UPDATE_PRODUCTION", {"u1": self.pub}):
            first = self.VU.expected_flat_names(path, "windows-x64", self.VU.part_of_tag(
                "v1.6.3-assets-windows-x64"))
            second = self.VU.expected_flat_names(path, "windows-x64", self.VU.part_of_tag(
                "v1.6.3-assets-windows-x64-2"))
        self.assertEqual((len(first), len(second)), (UM.ASSETS_PER_RELEASE, 4))
        for tag, want in (("v1.6.3-assets-linux-x64", 1), ("v1.6.3-assets-macos-arm64-app", 1),
                          ("v1.6.3-assets-linux-x64-3", 3), ("v1.6.3", 1)):
            self.assertEqual(self.VU.part_of_tag(tag), want, tag)


class TheBuildToolSplitsInsteadOfFailing(unittest.TestCase):

    def test_a_bundle_over_the_old_cap_now_builds_and_says_how_many_releases(self):
        import io
        import json
        import contextlib
        import importlib.util
        root = tempfile.mkdtemp(prefix="prism-big-")
        for i in range(1100):                       # over the 1000 that failed 1.6.2
            with open(os.path.join(root, f"f{i:05d}.dat"), "wb") as f:
                f.write(b"x" * (i % 7 + 1))
        out = os.path.join(root, "..", f"manifest-{os.getpid()}.json")
        spec = importlib.util.spec_from_file_location(
            "pkg_manifest", os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "packaging", "manifest.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = mod.main([root, "1.6.3", "-o", out])
        self.assertEqual(code, 0)
        self.assertIn("2 release part(s)", buf.getvalue())
        with open(out, encoding="utf-8") as f:
            written = json.load(f)
        os.remove(out)
        self.assertEqual({UM.part_of(e) for e in written["files"]}, {1, 2})


if __name__ == "__main__":
    unittest.main()

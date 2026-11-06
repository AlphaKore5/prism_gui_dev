"""core/boq.py's bundled-dwg2dxf feature: a customer should never have to
install anything to convert a .dwg on an Apple Silicon Mac or 64-bit
Windows -- find_dwg_converter() installs Prism's own vendored copy on first
use. ODA File Converter, wherever already installed, must still win at every
stage: it reads the full DWG spec, dwg2dxf is a reverse-engineered reader
that can fail on newer/exotic DWG features (see
prism_terminal/core/vendor/dwg2dxf/README.md for a real example found while
building this).

Everything here is mocked subprocess/filesystem state -- no real binary is
executed, so this runs the same on every CI platform regardless of which
vendor copy (if any) matches it. The one thing that DOES touch the real
shipped files is the "vendor files exist and are the right shape" sanity
check at the bottom, and even that only ever reads bytes, never runs them.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB                                            # noqa: E402

boq = CB.get_boq()


class PlatformTagOnlyCoversMachinesWeActuallyShipFor(unittest.TestCase):
    def test_apple_silicon_mac(self):
        with mock.patch.object(boq.platform, "system", return_value="Darwin"), \
             mock.patch.object(boq.platform, "machine", return_value="arm64"):
            self.assertEqual(boq._dwg2dxf_platform_tag(), "macos-arm64")

    def test_64_bit_windows(self):
        with mock.patch.object(boq.platform, "system", return_value="Windows"), \
             mock.patch.object(boq.platform, "machine", return_value="AMD64"):
            self.assertEqual(boq._dwg2dxf_platform_tag(), "win64")

    def test_intel_mac_has_no_bundled_copy(self):
        # No official LibreDWG macOS binary exists for Intel at all -- see
        # the vendor README. Must fall through to PATH / a manual install,
        # not silently claim a tag that has no files behind it.
        with mock.patch.object(boq.platform, "system", return_value="Darwin"), \
             mock.patch.object(boq.platform, "machine", return_value="x86_64"):
            self.assertIsNone(boq._dwg2dxf_platform_tag())

    def test_linux_has_no_bundled_copy(self):
        with mock.patch.object(boq.platform, "system", return_value="Linux"), \
             mock.patch.object(boq.platform, "machine", return_value="x86_64"):
            self.assertIsNone(boq._dwg2dxf_platform_tag())

    def test_32_bit_windows_has_no_bundled_copy(self):
        with mock.patch.object(boq.platform, "system", return_value="Windows"), \
             mock.patch.object(boq.platform, "machine", return_value="x86"):
            self.assertIsNone(boq._dwg2dxf_platform_tag())


class EnsureBundledDwg2dxfInstallsIntoTheToolsDir(unittest.TestCase):
    """A fake vendor source and a fake tools dir, both in a temp folder --
    never touches ~/.prism/tools or the real vendored binaries."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vendor_root = os.path.join(self.tmp.name, "vendor_src")
        self.tools_root = os.path.join(self.tmp.name, "tools")
        # _HERE mocks core/boq.py's own directory, so the real layout is
        # _HERE/vendor/dwg2dxf/<tag>/ -- matching that exactly is the point.
        src_dir = os.path.join(self.vendor_root, "vendor", "dwg2dxf", "macos-arm64")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "dwg2dxf"), "wb") as f:
            f.write(b"fake-binary-contents")
        with open(os.path.join(src_dir, "libredwg.0.dylib"), "wb") as f:
            f.write(b"fake-dylib-contents-longer-than-the-exe")
        with open(os.path.join(src_dir, "README.md"), "w") as f:
            f.write("not meant to be copied")

        self._patches = [
            mock.patch.object(boq, "_HERE", self.vendor_root),
            mock.patch.object(boq.platform, "system", return_value="Darwin"),
            mock.patch.object(boq.platform, "machine", return_value="arm64"),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

        # boq.py does `from . import ffmpeg as _ffmpeg` inside the function.
        # Swapping sys.modules["core.ffmpeg"] wholesale only intercepts that
        # if core.ffmpeg was never imported before -- found live running
        # this file alongside others that import the real engine first:
        # Python's IMPORT_FROM reads the already-cached `ffmpeg` ATTRIBUTE
        # on the `core` package object before ever consulting sys.modules
        # again, so the swap silently stopped working and this test used
        # the real ~/.prism/tools. Patching tools_dir AS AN ATTRIBUTE on the
        # real module (whichever one is already loaded) has no such gap.
        from core import ffmpeg as _real_ffmpeg
        self._ffmpeg_patch = mock.patch.object(
            _real_ffmpeg, "tools_dir", return_value=self.tools_root)
        self._ffmpeg_patch.start()
        self.addCleanup(self._ffmpeg_patch.stop)

    def test_copies_every_file_except_the_readme_and_sets_exec_bit(self):
        boq._ensure_bundled_dwg2dxf()
        dst_dir = os.path.join(self.tools_root, "dwg2dxf", "macos-arm64")
        dst_exe = os.path.join(dst_dir, "dwg2dxf")
        self.assertTrue(os.path.isfile(dst_exe))
        self.assertTrue(os.path.isfile(os.path.join(dst_dir, "libredwg.0.dylib")))
        self.assertFalse(os.path.exists(os.path.join(dst_dir, "README.md")),
                          "the source offer doc has no business next to a "
                          "binary find_dwg_converter() might return as THE "
                          "converter path")
        # Unix-only check: this test always mocks the TARGET as macOS (see
        # setUp), but os.chmod/os.stat still go through the REAL host OS --
        # found on a real Windows CI runner, 1.7.0: Windows has no owner-
        # execute permission bit to set in the first place (a .exe there
        # runs regardless of chmod), so os.chmod(dst_exe, 0o755) is a no-op
        # and this assertion is checking a concept that does not exist on
        # that host, not a real bug a Windows customer would ever hit.
        if os.name == "posix":
            mode = os.stat(dst_exe).st_mode
            self.assertTrue(mode & 0o100, "the copied exe must be executable "
                             "even if PyInstaller's datas dropped the +x bit")

    def test_second_call_is_a_cheap_noop_not_a_recopy(self):
        boq._ensure_bundled_dwg2dxf()
        dst_exe = os.path.join(self.tools_root, "dwg2dxf", "macos-arm64", "dwg2dxf")
        first_mtime = os.stat(dst_exe).st_mtime_ns
        with mock.patch("shutil.copy2") as copy2:
            boq._ensure_bundled_dwg2dxf()
            copy2.assert_not_called()
        self.assertEqual(os.stat(dst_exe).st_mtime_ns, first_mtime)

    def test_unsupported_platform_does_nothing_and_never_raises(self):
        with mock.patch.object(boq.platform, "system", return_value="Linux"):
            boq._ensure_bundled_dwg2dxf()  # must not raise
        self.assertFalse(os.path.isdir(os.path.join(self.tools_root, "dwg2dxf")))


class FindDwgConverterPrefersOdaOverTheBundledFallback(unittest.TestCase):
    """The ordering is the whole point: a customer who installed ODA
    themselves must always get it, never Prism's own less-reliable
    fallback -- see the docstring this guards."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tools_root = os.path.join(self.tmp.name, "tools")
        os.makedirs(self.tools_root)
        # See the long comment in EnsureBundledDwg2dxfInstallsIntoTheToolsDir
        # .setUp() -- patching tools_dir as an attribute on the real,
        # already-imported module, not swapping sys.modules wholesale.
        from core import ffmpeg as _real_ffmpeg
        self._ffmpeg_patch = mock.patch.object(
            _real_ffmpeg, "tools_dir", return_value=self.tools_root)
        self._ffmpeg_patch.start()
        self.addCleanup(self._ffmpeg_patch.stop)
        os.environ.pop(boq.ENV_CONVERTER, None)

    def _touch(self, *parts):
        path = os.path.join(self.tools_root, *parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        os.chmod(path, 0o755)
        return path

    def test_oda_in_tools_dir_beats_dwg2dxf_in_tools_dir(self):
        self._touch("dwg2dxf")
        oda = self._touch("ODAFileConverter")
        with mock.patch.object(boq, "_ensure_bundled_dwg2dxf") as ensure, \
             mock.patch("shutil.which", return_value=None), \
             mock.patch.object(boq, "_installed_converter_paths", return_value=[]):
            found = boq.find_dwg_converter()
        self.assertEqual(found, oda)
        ensure.assert_not_called()

    def test_oda_on_path_beats_dwg2dxf_also_on_path(self):
        def which(name):
            return {"ODAFileConverter": "/usr/local/bin/ODAFileConverter",
                    "dwg2dxf": "/opt/homebrew/bin/dwg2dxf"}.get(name)
        with mock.patch.object(boq, "_ensure_bundled_dwg2dxf") as ensure, \
             mock.patch("shutil.which", side_effect=which), \
             mock.patch.object(boq, "_installed_converter_paths", return_value=[]):
            found = boq.find_dwg_converter()
        self.assertEqual(found, "/usr/local/bin/ODAFileConverter")
        ensure.assert_not_called()

    def test_bundled_dwg2dxf_only_tried_once_everything_else_came_up_empty(self):
        def fake_ensure():
            self._touch("dwg2dxf", "macos-arm64", "dwg2dxf")
        with mock.patch.object(boq, "_ensure_bundled_dwg2dxf",
                                side_effect=fake_ensure) as ensure, \
             mock.patch("shutil.which", return_value=None), \
             mock.patch.object(boq, "_installed_converter_paths", return_value=[]):
            found = boq.find_dwg_converter()
        ensure.assert_called_once()
        self.assertEqual(
            found, os.path.join(self.tools_root, "dwg2dxf", "macos-arm64", "dwg2dxf"))

    def test_nothing_anywhere_returns_none_not_a_crash(self):
        with mock.patch.object(boq, "_ensure_bundled_dwg2dxf"), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch.object(boq, "_installed_converter_paths", return_value=[]):
            self.assertIsNone(boq.find_dwg_converter())

    def test_explicit_env_override_beats_everything_including_oda(self):
        oda = self._touch("ODAFileConverter")
        override = self._touch("my_own_tool")
        with mock.patch.dict(os.environ, {boq.ENV_CONVERTER: override}), \
             mock.patch.object(boq, "_ensure_bundled_dwg2dxf") as ensure:
            found = boq.find_dwg_converter()
        self.assertEqual(found, override)
        self.assertNotEqual(found, oda)
        ensure.assert_not_called()


class VendoredFilesShipTheShapeTheInstallerExpects(unittest.TestCase):
    """Never executes the binaries (CI isn't guaranteed to be the matching
    platform/arch) -- just proves the files this feature depends on are
    actually in the repo, non-empty, and the Windows set is self-contained
    (every DLL dwg2dxf.exe needs sits right next to it, per the vendor
    README -- Windows' own DLL search order needs nothing else)."""

    VENDOR_ROOT = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "prism_terminal", "core", "vendor", "dwg2dxf")

    def test_macos_arm64_set(self):
        d = os.path.join(self.VENDOR_ROOT, "macos-arm64")
        for name in ("dwg2dxf", "libredwg.0.dylib"):
            path = os.path.join(d, name)
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreater(os.path.getsize(path), 0)

    def test_win64_set(self):
        d = os.path.join(self.VENDOR_ROOT, "win64")
        for name in ("dwg2dxf.exe", "libredwg-0.dll", "libiconv-2.dll",
                     "libpcre2-16-0.dll", "libpcre2-8-0.dll"):
            path = os.path.join(d, name)
            self.assertTrue(os.path.isfile(path), path)
            self.assertGreater(os.path.getsize(path), 0)

    def test_readme_documents_provenance_for_the_gpl_source_offer(self):
        readme = os.path.join(self.VENDOR_ROOT, "README.md")
        self.assertTrue(os.path.isfile(readme))
        with open(readme, encoding="utf-8") as f:
            text = f.read()
        self.assertIn("sha256", text.lower())
        self.assertIn("GPL", text)


if __name__ == "__main__":
    unittest.main()

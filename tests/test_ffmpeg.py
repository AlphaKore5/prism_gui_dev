"""Finding FFmpeg, and fetching it when a machine has none.

The bug behind this file is a shipped one: a Windows customer opened Reel and
was handed a codec install guide. Windows does not come with FFmpeg and nobody
installs it by accident, while every macOS developer has had it since the day
they ran `brew install ffmpeg` — so the gap is invisible from the inside and
fatal on the outside.

Two properties are defended here, and the second is the serious one:

  · **A Windows build finds FFmpeg without the internet.** It is bundled. The
    download exists for source runs and for a platform we have no wheel for;
    a customer should never meet it.

  · **Nothing unverified is ever executed.** The download is checked against
    the SHA-256 PyPI publishes for that exact file, before it is unpacked, let
    alone run. This is a product sold on keeping a company's data on its own
    machines; a blind binary fetch would make that claim untrue.

Only one test touches the network, and it is skipped unless PRISM_NET_TESTS is
set. The rest run against a fake index.
"""
from __future__ import annotations

import hashlib
import io
import os
import sys
import tempfile
import unittest
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import ffmpeg  # noqa: E402


def fake_wheel(*, member="imageio_ffmpeg/binaries/ffmpeg-linux64-v7.1",
               body=b"#!/bin/sh\necho ffmpeg version 7.1\n",
               licence=True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, body)
        if licence:
            archive.writestr("imageio_ffmpeg-0.6.0.dist-info/LICENSE",
                             "FFmpeg licence text")
    return buffer.getvalue()


class _Scratch(unittest.TestCase):
    """Every test gets its own tools directory — none of them may write into
    the developer's real ~/.prism."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="prism-ffmpeg-")
        self._real_tools = ffmpeg.tools_dir
        ffmpeg.tools_dir = lambda: self.dir

    def tearDown(self):
        ffmpeg.tools_dir = self._real_tools


# ── where it looks ────────────────────────────────────────────────────────────

class Resolution(_Scratch):

    def _exe(self, name: str | None = None) -> str:
        """A stand-in FFmpeg in the tools directory, named as this OS names it.

        The default used to be the literal "ffmpeg", which is the name on
        POSIX and NOT the name on Windows — `downloaded()` looks for
        `_exe_name()`, and `_install_from_wheel` writes `_exe_name()`, so
        a file called "ffmpeg" on Windows is one nothing would ever find.
        Two tests below therefore looked for a copy that could not be
        there, and Windows CI reported the product broken when it was the
        test that was wrong.
        """
        path = os.path.join(self.dir, name or ffmpeg._exe_name())
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        return path

    def test_the_env_override_wins(self):
        path = self._exe("custom")
        os.environ[ffmpeg.ENV_OVERRIDE] = path
        try:
            self.assertEqual(ffmpeg.from_env(), path)
            self.assertEqual(ffmpeg.locate(), path)
        finally:
            del os.environ[ffmpeg.ENV_OVERRIDE]

    def test_an_override_pointing_at_nothing_is_ignored(self):
        """A stale PRISM_FFMPEG in someone's shell profile must not break
        video for them — fall through to the ones that exist."""
        os.environ[ffmpeg.ENV_OVERRIDE] = "/no/such/ffmpeg"
        try:
            self.assertIsNone(ffmpeg.from_env())
        finally:
            del os.environ[ffmpeg.ENV_OVERRIDE]

    def test_a_directory_is_not_an_executable(self):
        os.environ[ffmpeg.ENV_OVERRIDE] = self.dir
        try:
            self.assertIsNone(ffmpeg.from_env())
        finally:
            del os.environ[ffmpeg.ENV_OVERRIDE]

    def test_a_downloaded_copy_is_found(self):
        path = self._exe()
        self.assertEqual(ffmpeg.downloaded(), path)

    @unittest.skipIf(sys.platform.startswith("win"),
                     "NTFS has no executable bit — os.access(X_OK) is True "
                     "for any file that exists, so there is no such state "
                     "to put a file into here")
    def test_a_non_executable_file_does_not_count(self):
        """A half-written download, or one antivirus stripped. Better to fall
        through and fetch it again than to hand FFmpeg's path to a subprocess
        that will fail with 'permission denied'.

        POSIX only, and that is a property of the filesystem rather than a
        gap: Windows has no bit to clear, so `_usable` cannot make this
        distinction there. It does not need to — `_install_from_wheel`
        writes to `.part` and `os.replace`s it, so a partial download never
        appears at the final path on any platform."""
        path = os.path.join(self.dir, ffmpeg._exe_name())
        with open(path, "w") as f:
            f.write("x")
        os.chmod(path, 0o644)
        self.assertIsNone(ffmpeg.downloaded())

    def test_the_bundled_copy_beats_the_system_one(self):
        """Deliberate: every customer then encodes with the same build, so a
        video that came out right here cannot come out wrong on theirs
        because their distribution shipped FFmpeg 4.2."""
        order = list(ffmpeg.locate.__code__.co_consts)
        source = _read("core/ffmpeg.py")
        body = source.split("def locate(")[1].split("def ")[0]
        self.assertLess(body.index("bundled"), body.index("on_path"))

    def test_nothing_anywhere_is_none_not_an_exception(self):
        """locate() is called from the self-test and from status screens. It
        has to be safe to ask when the answer is no."""
        real = (ffmpeg.from_env, ffmpeg.bundled, ffmpeg.on_path)
        ffmpeg.from_env = lambda: None
        ffmpeg.bundled = lambda: None
        ffmpeg.on_path = lambda: None
        try:
            self.assertIsNone(ffmpeg.locate())
            self.assertFalse(ffmpeg.is_available())
            self.assertEqual(ffmpeg.describe(), "not found")
        finally:
            ffmpeg.from_env, ffmpeg.bundled, ffmpeg.on_path = real

    def test_describe_names_which_one(self):
        self._exe()
        real = (ffmpeg.from_env, ffmpeg.bundled)
        ffmpeg.from_env = lambda: None
        ffmpeg.bundled = lambda: None
        try:
            self.assertIn("downloaded by Prism", ffmpeg.describe())
        finally:
            ffmpeg.from_env, ffmpeg.bundled = real


class PlatformTags(unittest.TestCase):
    """A wrong tag means a wheel for the wrong machine — which downloads
    happily and then will not run."""

    def _tag(self, platform_name, machine):
        real_platform, real_machine = sys.platform, ffmpeg.platform.machine
        ffmpeg.sys.platform = platform_name
        ffmpeg.platform.machine = lambda: machine
        try:
            return ffmpeg.platform_tag()
        finally:
            ffmpeg.sys.platform = real_platform
            ffmpeg.platform.machine = real_machine

    def test_every_platform_maps_to_a_real_wheel_tag(self):
        cases = {
            ("win32", "AMD64"): "win_amd64",
            ("win32", "x86"): "win32",
            # x64 FFmpeg runs through Windows' emulation on an ARM laptop, and
            # Python 3.12 reports ARM64 there even for an x64 Prism.
            ("win32", "ARM64"): "win_amd64",
            ("darwin", "arm64"): "macosx_11_0_arm64",
            ("darwin", "x86_64"): "macosx_10_9_x86_64",
            ("linux", "x86_64"): "manylinux2014_x86_64",
            ("linux", "aarch64"): "manylinux2014_aarch64",
        }
        for (platform_name, machine), expected in cases.items():
            self.assertEqual(self._tag(platform_name, machine), expected,
                             f"{platform_name}/{machine}")

    def test_this_machine_gets_a_tag(self):
        self.assertTrue(ffmpeg.platform_tag())


# ── choosing a wheel ──────────────────────────────────────────────────────────

INDEX = {
    "info": {"version": "0.6.0"},
    "releases": {"0.6.0": [
        {"filename": "imageio_ffmpeg-0.6.0-py3-none-win_amd64.whl",
         "url": "https://example.invalid/win.whl",
         "digests": {"sha256": "aa" * 32}},
        {"filename": "imageio_ffmpeg-0.6.0-py3-none-manylinux2014_x86_64.whl",
         "url": "https://example.invalid/linux.whl",
         "digests": {"sha256": "bb" * 32}},
        {"filename": "imageio_ffmpeg-0.6.0.tar.gz",
         "url": "https://example.invalid/sdist.tar.gz",
         "digests": {"sha256": "cc" * 32}},
    ]},
}


class ChoosingTheWheel(unittest.TestCase):

    def test_the_right_one_for_the_platform(self):
        url, digest, name = ffmpeg.wheel_for("win_amd64", INDEX)
        self.assertEqual(url, "https://example.invalid/win.whl")
        self.assertEqual(digest, "aa" * 32)
        self.assertIn("win_amd64", name)

    def test_the_source_tarball_is_never_chosen(self):
        """It contains no binary — it builds one, which needs a compiler."""
        _url, _digest, name = ffmpeg.wheel_for("manylinux2014_x86_64", INDEX)
        self.assertTrue(name.endswith(".whl"))

    def test_an_unsupported_platform_says_install_it_yourself(self):
        with self.assertRaises(ffmpeg.FFmpegError) as caught:
            ffmpeg.wheel_for("linux_riscv64", INDEX)
        self.assertIn("Install it the usual way", str(caught.exception))

    def test_a_wheel_with_no_published_digest_is_skipped(self):
        """No digest means no way to verify it, and unverifiable is the same
        as unusable here."""
        index = {"info": {"version": "1"}, "releases": {"1": [
            {"filename": "imageio_ffmpeg-1-py3-none-win_amd64.whl",
             "url": "u", "digests": {}}]}}
        with self.assertRaises(ffmpeg.FFmpegError):
            ffmpeg.wheel_for("win_amd64", index)


# ── the download ──────────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = {"content-length": str(len(body))}

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start:start + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeRequests:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url, **kw):
        return _FakeResponse(self.body)


class Downloading(_Scratch):

    def _run(self, body: bytes, digest: str | None = None):
        import requests as real_requests
        wheel = body
        expected = digest or hashlib.sha256(wheel).hexdigest()
        ffmpeg.wheel_for = lambda tag="", index=None: (
            "https://example.invalid/w.whl", expected, "w.whl")
        fake = _FakeRequests(wheel)
        sys.modules["requests"] = fake
        try:
            return ffmpeg.download()
        finally:
            sys.modules["requests"] = real_requests

    def setUp(self):
        super().setUp()
        self._real_wheel_for = ffmpeg.wheel_for

    def tearDown(self):
        ffmpeg.wheel_for = self._real_wheel_for
        super().tearDown()

    def test_a_good_download_installs_and_is_executable(self):
        path = self._run(fake_wheel())
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(os.access(path, os.X_OK), "not executable")
        self.assertEqual(os.path.basename(path), ffmpeg._exe_name())

    def test_the_licence_travels_with_the_binary(self):
        self._run(fake_wheel())
        self.assertTrue(os.path.exists(
            os.path.join(self.dir, "ffmpeg-LICENSE.txt")))

    def test_a_tampered_download_is_refused(self):
        """The whole reason the digest is checked. A wrong hash and a
        truncated transfer look identical here, and both must stop."""
        with self.assertRaises(ffmpeg.FFmpegError) as caught:
            self._run(fake_wheel(), digest="00" * 32)
        self.assertIn("damaged", str(caught.exception))

    def test_nothing_is_installed_when_the_digest_fails(self):
        try:
            self._run(fake_wheel(), digest="00" * 32)
        except ffmpeg.FFmpegError:
            pass
        self.assertIsNone(ffmpeg.downloaded(), "a bad download was installed")

    def test_the_wheel_is_not_left_behind(self):
        self._run(fake_wheel())
        leftovers = [n for n in os.listdir(self.dir)
                     if n.endswith((".whl", ".part"))]
        self.assertEqual(leftovers, [])

    def test_a_wheel_with_no_binary_is_refused(self):
        with self.assertRaises(ffmpeg.FFmpegError) as caught:
            self._run(fake_wheel(member="imageio_ffmpeg/__init__.py"))
        self.assertIn("did not contain", str(caught.exception))

    def test_a_zip_slip_member_is_not_written(self):
        """A zip may name '../../bin/sh'. This is the one place in Prism where
        an archive from the internet becomes a path."""
        with self.assertRaises(ffmpeg.FFmpegError):
            self._run(fake_wheel(
                member="imageio_ffmpeg/binaries/../../../ffmpeg-evil"))

    def test_progress_is_reported(self):
        seen = []
        import requests as real_requests
        body = fake_wheel(body=b"x" * (ffmpeg.CHUNK * 3))
        ffmpeg.wheel_for = lambda tag="", index=None: (
            "u", hashlib.sha256(body).hexdigest(), "w.whl")
        sys.modules["requests"] = _FakeRequests(body)
        try:
            ffmpeg.download(lambda done, total: seen.append((done, total)))
        finally:
            sys.modules["requests"] = real_requests
        self.assertTrue(len(seen) > 1, "no progress reported")
        self.assertEqual(seen[-1][0], len(body), "final count is wrong")

    def test_ensure_does_not_download_when_one_is_already_there(self):
        path = os.path.join(self.dir, ffmpeg._exe_name())
        with open(path, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(path, 0o755)
        ffmpeg.wheel_for = lambda tag="", index=None: (_ for _ in ()).throw(
            AssertionError("ensure() downloaded when it did not need to"))
        real = (ffmpeg.from_env, ffmpeg.bundled)
        ffmpeg.from_env = lambda: None
        ffmpeg.bundled = lambda: None
        try:
            self.assertEqual(ffmpeg.ensure(), path)
        finally:
            ffmpeg.from_env, ffmpeg.bundled = real


class ErrorsAreReadable(unittest.TestCase):
    """This runs in front of a customer who has never installed anything."""

    FORBIDDEN = ("sha256", "wheel", "traceback", "http", "urllib", "zipfile")

    def test_the_missing_message_offers_the_fix(self):
        low = ffmpeg.MISSING.lower()
        self.assertIn("prism can fetch it", low)
        for word in self.FORBIDDEN:
            self.assertNotIn(word, low, f"{word!r} reached the customer")

    def test_every_failure_message_is_plain(self):
        messages = []
        try:
            ffmpeg.wheel_for("nonesuch", INDEX)
        except ffmpeg.FFmpegError as e:
            messages.append(str(e))
        try:
            ffmpeg.wheel_for("win_amd64", {"info": {}, "releases": {}})
        except ffmpeg.FFmpegError as e:
            messages.append(str(e))
        self.assertTrue(messages)
        for message in messages:
            for word in self.FORBIDDEN:
                self.assertNotIn(word, message.lower(),
                                 f"{word!r} in: {message}")


class TheBuildShipsIt(unittest.TestCase):
    """The actual fix for the Windows customer. The download is the fallback;
    this is what means they never reach it."""

    def test_requirements_lists_it(self):
        with open(_repo("requirements.txt"), encoding="utf-8") as f:
            self.assertIn("imageio-ffmpeg", f.read())

    def test_the_spec_bundles_its_binary(self):
        """The executable is a data file inside the package. Without this the
        build ships the Python and not the program."""
        with open(_repo("packaging", "prism.spec"), encoding="utf-8") as f:
            spec = f.read()
        self.assertIn('collect_data_files("imageio_ffmpeg")', spec)

    def test_both_reel_modules_use_one_resolver(self):
        """They were separate copies of shutil.which, so there were two places
        to fix and only one of them got fixed.

        Checked by parsing rather than by searching the text: both modules
        still *describe* the old behaviour in a docstring, and a substring
        match cannot tell an explanation from a call.
        """
        import ast
        for module in ("core/reel.py", "core/reel_web.py"):
            source = _read(module)
            self.assertIn("ffmpeg_tool.locate()", source, module)
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call):
                    continue
                target = node.func
                looked_up = (isinstance(target, ast.Attribute)
                             and target.attr == "which")
                args = [a.value for a in node.args
                        if isinstance(a, ast.Constant)]
                self.assertFalse(looked_up and "ffmpeg" in args,
                                 f"{module} still resolves FFmpeg on its own")


class LiveIndex(unittest.TestCase):
    """Touches PyPI. Off unless PRISM_NET_TESTS is set, so an aeroplane or a
    locked-down CI runner does not report a failure that is not one."""

    @pytest.mark.allow_network
    @unittest.skipUnless(os.environ.get("PRISM_NET_TESTS"),
                         "set PRISM_NET_TESTS=1 to check against real PyPI")
    def test_there_is_a_wheel_for_this_machine(self):
        url, digest, name = ffmpeg.wheel_for()
        self.assertTrue(url.startswith("https://"))
        self.assertEqual(len(digest), 64)
        self.assertIn(ffmpeg.platform_tag(), name)


def _repo(*parts: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        *parts)


def _read(relative: str) -> str:
    with open(_repo("prism_terminal", relative), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    unittest.main()

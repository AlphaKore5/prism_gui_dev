"""The Mac build: GitHub's own standard runner, testers only, nothing waits for it.

Pins which machine it asks for (never a billed one), when it runs, that Windows
and Linux publish whether or not a Mac is available, that its unsigned result is
never swept into a release, and that the oldest macOS we promise is checked
against what was actually built, with a list of known exceptions that cannot grow
by itself.
"""
from __future__ import annotations

import contextlib
import io
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packaging"))

import check_macos_minos as minos  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
ENGINE = ROOT / "prism_terminal"
TARGET = "14.0"


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _machines(job):
    """Every machine a job can ask for, with its matrix filled in."""
    on = job["runs-on"]
    if isinstance(on, list):
        return on
    if on == "${{ matrix.os }}":
        m = job["strategy"]["matrix"]
        return list(m.get("os", [])) + [leg["os"] for leg in m.get("include", [])]
    return [on]


class TheMachineIsGithubsStandardMac(unittest.TestCase):

    def test_the_mac_jobs_ask_for_macos_15(self):
        self.assertEqual(_machines(_workflow("build.yml")["jobs"]["build-macos"]), ["macos-15"])
        self.assertEqual(_machines(_workflow("macos-pins.yml")["jobs"]["record"]), ["macos-15"])

    def test_no_workflow_asks_for_a_billed_or_a_private_machine(self):
        """-large and -xlarge macOS runners are billed even on a public
        repository; a self-hosted one would run strangers' pull requests."""
        for path in sorted(WORKFLOWS.glob("*.y*ml")):
            for name, job in _workflow(path.name)["jobs"].items():
                for machine in _machines(job):
                    self.assertNotRegex(machine, "large|self-hosted",
                                        f"{path.name}: {name}")

    def test_the_mac_jobs_get_no_write_token_and_no_secret(self):
        build = _workflow("build.yml")["jobs"]["build-macos"]
        pins = _workflow("macos-pins.yml")
        self.assertEqual(build["permissions"], {"contents": "read"})
        self.assertEqual(pins["permissions"], {"contents": "read"})
        self.assertNotIn("secrets.", str(build) + str(pins))

    def test_the_recorder_is_started_by_hand_only(self):
        wf = _workflow("macos-pins.yml")
        self.assertEqual(wf.get("on", wf.get(True)), {"workflow_dispatch": None})


class TheMacHoldsUpNothing(unittest.TestCase):

    def setUp(self):
        self.jobs = _workflow("build.yml")["jobs"]
        self.job = self.jobs["build-macos"]

    def test_nothing_waits_for_it_and_it_is_in_no_matrix(self):
        for name, job in self.jobs.items():
            needs = job.get("needs", [])
            self.assertNotIn("build-macos", [needs] if isinstance(needs, str) else needs, name)
        for name in ("tests", "build"):
            self.assertNotIn("mac", " ".join(_machines(self.jobs[name])), name)
        self.assertLessEqual(self.job["timeout-minutes"], 90)

    def test_it_runs_exactly_when_the_other_builds_do(self):
        self.assertEqual(self.job["if"], self.jobs["build"]["if"])
        self.assertEqual(self.job["needs"], self.jobs["build"]["needs"])

    def test_its_result_is_never_swept_into_a_release(self):
        import fnmatch
        pattern = [s for s in self.jobs["release"]["steps"]
                   if "download-artifact" in s.get("uses", "")][0]["with"]["pattern"]
        names = [s["with"]["name"] for s in self.job["steps"]
                 if "upload-artifact" in s.get("uses", "")]
        self.assertEqual(names, ["macos-testers-${{ env.PRISM_BUILD_FLAVOUR }}"])
        self.assertFalse(fnmatch.fnmatch(names[0], pattern))

    def test_the_flavour_reaches_it(self):
        """packaging/build.py reads the workflow's PRISM_BUILD_FLAVOUR."""
        self.assertNotIn("PRISM_BUILD_FLAVOUR", str(self.job.get("env", {})))
        for step in self.job["steps"]:
            self.assertNotIn("PRISM_BUILD_FLAVOUR", str(step.get("env", {})), step)
        self.assertIn("python packaging/build.py --clean", [s.get("run") for s in self.job["steps"]])

    def test_the_summary_says_unsigned_testers_and_dwg(self):
        run = [s for s in self.job["steps"] if s.get("name") == "Say what this build is"][0]["run"]
        self.assertIn("GITHUB_STEP_SUMMARY", run)
        for words in ("unsigned, for testers only", "Opening DWG files is expected to fail below macOS 26",
                      "Not published in any release"):
            self.assertIn(words, run)


class TheOldestMacosIsOneNumberAndIsChecked(unittest.TestCase):

    def setUp(self):
        self.job = _workflow("build.yml")["jobs"]["build-macos"]

    def test_the_workflows_and_the_app_say_the_same(self):
        self.assertEqual(self.job["env"]["MACOSX_DEPLOYMENT_TARGET"], TARGET)
        self.assertEqual(
            _workflow("macos-pins.yml")["jobs"]["record"]["env"]["MACOSX_DEPLOYMENT_TARGET"], TARGET)
        spec = (ROOT / "packaging" / "prism.spec").read_text(encoding="utf-8")
        self.assertIn(f'"LSMinimumSystemVersion": "{TARGET}"', spec)

    def test_the_check_runs_after_the_build_and_before_anything_is_uploaded(self):
        runs = [str(s.get("run", s.get("uses", ""))) for s in self.job["steps"]]

        def at(text):
            return [i for i, r in enumerate(runs) if text in r][0]
        self.assertLess(at("packaging/build.py"), at("packaging/smoke_test.py"))
        self.assertLess(at("packaging/smoke_test.py"), at("packaging/check_macos_minos.py"))
        self.assertLess(at("packaging/check_macos_minos.py"), at("actions/upload-artifact"))
        check = [s for s in self.job["steps"] if "check_macos_minos" in str(s.get("run"))][0]
        self.assertIn('dist/Prism.app "$MACOSX_DEPLOYMENT_TARGET"', check["run"])
        self.assertNotIn("continue-on-error", check)


def _macho(cmd=minos.LC_BUILD_VERSION, version=(13, 0, 0), platform=1, commands=True):
    packed = version[0] << 16 | version[1] << 8 | version[2]
    if not commands:
        body, count = b"", 0
    elif cmd == minos.LC_BUILD_VERSION:
        body, count = struct.pack("<IIIIII", cmd, 24, platform, packed, packed, 0), 1
    else:
        body, count = struct.pack("<IIII", cmd, 16, packed, packed), 1
    # an unrelated load command first, so the walk is exercised
    body = struct.pack("<IIQQ", 0x2A, 24, 0, 0) + body
    return struct.pack("<IIIIIIII", minos.MH_MAGIC_64, minos.CPU_ARM64, 0, 2,
                       count + 1, len(body), 0, 0) + body


def _fat(slices):
    head, body, at = struct.pack(">II", minos.FAT_MAGIC, len(slices)), b"", 4096
    for cpu, data in slices:
        head += struct.pack(">IIIII", cpu, 0, at + len(body), len(data), 0)
        body += data
    return head.ljust(at, b"\0") + body


class TheMinimumIsReadFromTheBinaries(unittest.TestCase):

    def _run(self, files, target="13.0"):
        with tempfile.TemporaryDirectory() as d:
            for name, data in files.items():
                path = Path(d, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = minos.main([d, target])
        return code, out.getvalue()

    def test_at_or_below_the_target_passes(self):
        code, out = self._run({"MacOS/Prism": _macho(), "a/b.so": _macho(version=(11, 0, 0)),
                               "readme.txt": b"hello", "empty": b""})
        self.assertEqual(code, 0, out)
        self.assertIn("2 Mac binaries", out)

    def test_one_newer_library_fails_and_is_named_with_its_version(self):
        code, out = self._run({"MacOS/Prism": _macho(), "a/new.dylib": _macho(version=(14, 2, 0))})
        self.assertEqual(code, 1)
        self.assertIn("needs macOS 14.2.0: " + os.path.join("a", "new.dylib"), out)
        self.assertIn("::error::1 file(s)", out)

    def test_a_point_release_above_the_target_counts(self):
        self.assertEqual(self._run({"x": _macho(version=(13, 1, 0))})[0], 1)
        self.assertEqual(self._run({"x": _macho(version=(13, 1, 0))}, "13.1")[0], 0)

    def test_the_older_load_command_is_read_too(self):
        data = _macho(cmd=minos.LC_VERSION_MIN_MACOSX, version=(15, 0, 0))
        self.assertEqual(self._run({"x": data})[0], 1)

    def test_a_universal_file_is_judged_by_its_apple_silicon_half(self):
        intel = 0x01000007
        new, old = _macho(version=(14, 0, 0)), _macho(version=(11, 0, 0))
        self.assertEqual(self._run({"x": _fat([(intel, new), (minos.CPU_ARM64, old)])})[0], 0)
        self.assertEqual(self._run({"x": _fat([(intel, old), (minos.CPU_ARM64, new)])})[0], 1)

    def test_an_ios_build_version_is_not_read_as_macos(self):
        code, out = self._run({"x": _macho(platform=2, version=(17, 0, 0))})
        self.assertEqual(code, 0)
        self.assertIn("no minimum recorded: x", out)

    def test_a_java_class_file_is_not_a_mac_binary(self):
        code, _ = self._run({"Prism": _macho(), "A.class": struct.pack(">IHH", 0xCAFEBABE, 0, 61) + b"x" * 64})
        self.assertEqual(code, 0)

    def test_nothing_found_is_not_a_pass(self):
        self.assertEqual(self._run({"readme.txt": b"no binaries here"})[0], 2)

    _DWG = "Contents/Frameworks/core/vendor/dwg2dxf/macos-arm64/"

    def test_a_known_exception_passes_and_is_reported_with_its_reason(self):
        code, out = self._run({"Prism": _macho(), self._DWG + "dwg2dxf": _macho(version=(26, 0, 0))})
        self.assertEqual(code, 0, out)
        self.assertIn("1 known exceptions", out)
        self.assertIn("KNOWN, needs macOS 26.0.0", out)
        self.assertIn("opening DWG files is expected to fail on older Macs", out)

    def test_a_known_exception_does_not_cover_a_higher_version_or_another_file(self):
        self.assertEqual(self._run({self._DWG + "dwg2dxf": _macho(version=(27, 0, 0))})[0], 1)
        self.assertEqual(self._run({self._DWG + "other.dylib": _macho(version=(26, 0, 0))})[0], 1)
        self.assertEqual(self._run({"Contents/Frameworks/libredwg.0.dylib":
                                    _macho(version=(26, 0, 0))})[0], 1)


class TheExceptionsCannotGrowSilently(unittest.TestCase):

    def test_the_list_is_exactly_these_two_files(self):
        d = "core/vendor/dwg2dxf/macos-arm64/"
        self.assertEqual({p: v for p, (v, _why) in minos.KNOWN.items()},
                         {d + "dwg2dxf": (26, 0, 0), d + "libredwg.0.dylib": (26, 0, 0)})
        notes = (ROOT / "RELEASE_ISSUES.md").read_text(encoding="utf-8")
        for path in minos.KNOWN:
            self.assertIn(path.rsplit("/", 1)[1], notes)

    @unittest.skipUnless((ENGINE / "core").is_dir(), "the engine submodule is not checked out")
    def test_the_engine_still_ships_those_files_with_that_minimum(self):
        """Red when the engine's converter is rebuilt: then take it off KNOWN."""
        for path, (allowed, _why) in minos.KNOWN.items():
            self.assertEqual(minos.minimum_macos(str(ENGINE / path)), (True, allowed), path)


@unittest.skipIf(sys.platform.startswith("win"), "a bash script that only runs on the Mac runner")
class ThePortAudioScript(unittest.TestCase):

    def test_it_parses(self):
        r = subprocess.run(["bash", "-n", str(ROOT / "packaging" / "macos_portaudio.sh")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class OurPythonsOpenSslIsLeftAlone(unittest.TestCase):
    """packaging/build.py swaps in Homebrew's OpenSSL for a Homebrew-linked
    Python only. A python.org Python carries its own."""

    def _run(self, own):
        import build
        with tempfile.TemporaryDirectory() as d:
            lib = Path(d, "python", "lib")
            lib.mkdir(parents=True)
            if own:
                (lib / "libssl.3.dylib").write_bytes(b"python.org")
            hit = Path(d, "Prism.app", "Contents", "Frameworks", "libssl.3.dylib")
            hit.parent.mkdir(parents=True)
            hit.write_bytes(b"bundled")
            brew = Path(d, "brew")
            brew.mkdir()
            real = __import__("glob").glob

            def fake(pattern, **kw):
                name = pattern.rsplit("/", 1)[-1]
                if pattern.startswith("/opt/homebrew"):
                    (brew / name).write_bytes(b"homebrew")
                    return [str(brew / name)]
                return real(pattern, **kw)
            with mock.patch.object(build, "IS_MAC", True), \
                    mock.patch.object(sys, "base_prefix", str(lib.parent)), \
                    mock.patch("glob.glob", fake), \
                    contextlib.redirect_stdout(io.StringIO()):
                build._fix_macos_cv2_openssl_collision(str(Path(d, "Prism.app")))
            return hit.read_bytes()

    def test_a_python_with_its_own_openssl_is_not_touched(self):
        self.assertEqual(self._run(own=True), b"bundled")

    def test_a_homebrew_python_still_gets_the_swap(self):
        self.assertEqual(self._run(own=False), b"homebrew")


if __name__ == "__main__":
    unittest.main()

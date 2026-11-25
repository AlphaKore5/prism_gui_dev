"""The Mac build runs on our own Mac, and never for a pull request.

The repository is public and that Mac is a machine somebody uses, so this pins
(docs/MAC_BUILD_RUNNER.md, part 1 says what it cannot pin): which jobs may ask
for the machine and on which events, that they get no write token and no signing
secret, that a Mac that is off never holds up the Windows and Linux release, and
that the oldest macOS we promise is checked against what was actually built.
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
LABELS = ["self-hosted", "macOS", "ARM64", "prism-mac"]
BUILD_IF = ("vars.PRISM_MAC_RUNNER == 'on' "
            "&& contains(fromJSON('[\"push\", \"schedule\", \"workflow_dispatch\"]'), github.event_name) "
            "&& (github.ref == 'refs/heads/main' || startsWith(github.ref, 'refs/tags/v'))")
RECORD_IF = "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"


def _workflow(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _hosted_by_us():
    """{(file, job): job} for every job in every workflow that can reach a
    self-hosted machine, or whose machine cannot be read off the file."""
    out = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        for name, job in _workflow(path.name)["jobs"].items():
            where = str(job.get("runs-on", ""))
            if any(w in where.lower() for w in ("self-hosted", "prism-mac", "group", "fromjson")):
                out[(path.name, name)] = job
    return out


class TheMacNeverRunsAPullRequest(unittest.TestCase):

    def test_only_the_two_known_jobs_can_ask_for_the_mac(self):
        self.assertEqual({("build.yml", "build-macos"), ("macos-pins.yml", "record")},
                         set(_hosted_by_us()))

    def test_they_ask_for_all_four_labels(self):
        for key, job in _hosted_by_us().items():
            self.assertEqual(job["runs-on"], LABELS, key)

    def test_the_events_are_listed_and_no_pull_request_is_among_them(self):
        jobs = _hosted_by_us()
        self.assertEqual(" ".join(jobs["build.yml", "build-macos"]["if"].split()), BUILD_IF)
        self.assertEqual(" ".join(jobs["macos-pins.yml", "record"]["if"].split()), RECORD_IF)
        wf = _workflow("macos-pins.yml")
        self.assertEqual(wf.get("on", wf.get(True)), {"workflow_dispatch": None})

    def test_the_first_step_refuses_a_pull_request_before_any_code_is_fetched(self):
        for key, job in _hosted_by_us().items():
            first = job["steps"][0]
            self.assertEqual(first["if"], "github.event_name == 'pull_request' "
                                          "|| github.event_name == 'pull_request_target'", key)
            self.assertIn("exit 1", first["run"])
            self.assertTrue(job["steps"][1]["uses"].startswith("actions/checkout@"), key)

    def test_the_other_jobs_matrices_hold_no_mac(self):
        for name in ("tests", "build"):
            matrix = _workflow("build.yml")["jobs"][name]["strategy"]["matrix"]
            self.assertNotIn("mac", str(matrix).lower(), name)

    def test_the_machine_gets_no_write_token_and_no_secret(self):
        for (file, name), job in _hosted_by_us().items():
            granted = job.get("permissions", _workflow(file).get("permissions"))
            self.assertEqual(granted, {"contents": "read"}, name)
            self.assertNotIn("secrets.", str(job), name)
            checkout = [s for s in job["steps"] if "actions/checkout" in s.get("uses", "")]
            self.assertEqual([s["with"]["persist-credentials"] for s in checkout], [False], name)

    def test_actionlint_knows_the_label(self):
        cfg = yaml.safe_load((ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8"))
        self.assertEqual(cfg["self-hosted-runner"]["labels"], ["prism-mac"])


class AMacThatIsOffHoldsUpNothing(unittest.TestCase):

    def setUp(self):
        self.jobs = _workflow("build.yml")["jobs"]

    def test_only_the_job_that_adds_the_mac_files_waits_for_it(self):
        waiting = {}
        for name, job in self.jobs.items():
            needs = job.get("needs", [])
            needs = [needs] if isinstance(needs, str) else needs
            if "build-macos" in needs:
                waiting[name] = needs
        self.assertEqual(waiting, {"release-macos": ["release", "build-macos"]})
        self.assertNotIn("needs", self.jobs["build-macos"])

    def test_a_running_job_is_cut_off(self):
        for key, job in _hosted_by_us().items():
            self.assertLessEqual(job["timeout-minutes"], 120, key)

    def test_the_mac_files_are_added_for_a_pushed_tag_only_from_githubs_machine(self):
        job = self.jobs["release-macos"]
        self.assertEqual(job["if"], self.jobs["release"]["if"])
        self.assertEqual(job["runs-on"], "ubuntu-latest")
        self.assertEqual(job["steps"][0]["with"]["name"], "prism-macos-14")
        self.assertIn("gh release upload", job["steps"][1]["run"])

    def test_the_artifacts_have_the_names_release_all_downloads(self):
        src = (ROOT / "devtools" / "release_all.py").read_text(encoding="utf-8")
        self.assertIn('("macos-arm64-app", "macos-14")', src)
        job = self.jobs["build-macos"]
        self.assertEqual(job["strategy"]["matrix"]["include"],
                         [{"os": "macos-14", "pins": "macos-arm64"}])
        uploads = [s["with"] for s in job["steps"] if "upload-artifact" in s.get("uses", "")]
        self.assertEqual([u["name"] for u in uploads[1:]], [
            "${{ env.PRISM_BUILD_FLAVOUR == 'complete' && format('prism-{0}', matrix.os) "
            "|| format('prism-{0}-{1}', env.PRISM_BUILD_FLAVOUR, matrix.os) }}",
            "update-assets-${{ matrix.os }}"])

    def test_a_build_that_failed_the_check_is_never_swept_into_a_release(self):
        failed = [s for s in self.jobs["build-macos"]["steps"]
                  if s.get("with", {}).get("name") == "not-for-release-macos"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["if"], "failure() && steps.minos.outcome == 'failure'")

    def test_a_flavour_build_never_feeds_the_update_channel(self):
        for step in self.jobs["build-macos"]["steps"]:
            text = str(step.get("run", "")) + str(step.get("with", {}).get("name", ""))
            if "manifest.py" in text or "update-assets" in text:
                self.assertEqual(step.get("if"), "env.PRISM_BUILD_FLAVOUR == 'complete'", step)


class TheOldestMacosIsOneNumberAndIsChecked(unittest.TestCase):

    def setUp(self):
        self.job = _workflow("build.yml")["jobs"]["build-macos"]

    def test_both_workflows_set_the_same_target(self):
        self.assertEqual(self.job["env"]["MACOSX_DEPLOYMENT_TARGET"], "13.0")
        self.assertEqual(
            _workflow("macos-pins.yml")["jobs"]["record"]["env"]["MACOSX_DEPLOYMENT_TARGET"], "13.0")

    def test_the_app_declares_the_same_number(self):
        spec = (ROOT / "packaging" / "prism.spec").read_text(encoding="utf-8")
        self.assertIn('"LSMinimumSystemVersion": os.environ.get("MACOSX_DEPLOYMENT_TARGET")', spec)

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


@unittest.skipIf(sys.platform.startswith("win"), "bash scripts that only ever run on the build Mac")
class TheScriptsOnTheMac(unittest.TestCase):

    def test_they_parse(self):
        for rel in ("packaging/macos_ci_setup.sh", "devtools/mac_runner_guard.sh"):
            r = subprocess.run(["bash", "-n", str(ROOT / rel)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def _guard(self, event, ref):
        env = {"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": event, "GITHUB_WORKFLOW_REF": ref}
        return subprocess.run(["bash", "-e", str(ROOT / "devtools" / "mac_runner_guard.sh")],
                              env=env, capture_output=True, text=True).returncode

    def test_the_guard_lets_our_own_builds_through(self):
        wf = "AlphaKore5/prism_gui_dev/.github/workflows/"
        for event, ref in (("push", "build.yml@refs/heads/main"),
                           ("push", "build.yml@refs/tags/v1.9.0"),
                           ("schedule", "build.yml@refs/heads/main"),
                           ("workflow_dispatch", "build.yml@refs/heads/main"),
                           ("workflow_dispatch", "macos-pins.yml@refs/heads/main")):
            self.assertEqual(self._guard(event, wf + ref), 0, (event, ref))

    def test_the_guard_refuses_everything_else(self):
        wf = "AlphaKore5/prism_gui_dev/.github/workflows/"
        for event, ref in (("pull_request", wf + "build.yml@refs/pull/9/merge"),
                           ("pull_request_target", wf + "build.yml@refs/heads/main"),
                           ("issue_comment", wf + "build.yml@refs/heads/main"),
                           ("push", wf + "evil.yml@refs/heads/main"),
                           ("push", wf + "build.yml@refs/heads/some-branch"),
                           ("workflow_dispatch", wf + "build.yml@refs/heads/some-branch"),
                           ("push", "someone/prism_gui_dev/.github/workflows/build.yml@refs/heads/main"),
                           ("push", ""), ("", "")):
            self.assertEqual(self._guard(event, ref), 1, (event, ref))

    def test_the_guard_names_the_jobs_the_workflows_really_have(self):
        text = (ROOT / "devtools" / "mac_runner_guard.sh").read_text(encoding="utf-8")
        for file, _job in _hosted_by_us():
            self.assertIn(f"/.github/workflows/{file}@", text)


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

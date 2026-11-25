"""The CI speed-up must not change what CI proves or what a tag publishes.

.github/workflows/build.yml shards the tests, caches pip downloads, cancels
superseded runs and builds installers on a pull request only when it touches
packaging. This pins, from the workflow file and the runner itself:

  * every test file runs in exactly one shard, on every platform, and the
    shard count agrees in all three places the workflow names it;
  * a shard's known failures, NEW FAILURES and crashes survive the merge, and
    a missing or duplicated shard fails the combined verdict;
  * a tag run is never cancelled and the release job still runs for a pushed
    v* tag only, needing the builds and every test shard;
  * Windows is in the test matrix and the tests run on every event;
  * the build job's condition, and which paths count as packaging.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path, PureWindowsPath

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "devtools"))

import ci_changes  # noqa: E402
import suite_runner  # noqa: E402

TEST_FILES = sorted((ROOT / "tests").glob("test_*.py"))


def _wf():
    with open(ROOT / ".github" / "workflows" / "build.yml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _shard_count(wf) -> int:
    shards = wf["jobs"]["tests"]["strategy"]["matrix"]["shard"]
    return len(shards)


class EveryTestFileRunsInExactlyOneShard(unittest.TestCase):

    def setUp(self):
        self.wf = _wf()
        self.n = _shard_count(self.wf)
        self.timings = suite_runner.load_timings()

    def test_the_shard_count_agrees_everywhere_the_workflow_names_it(self):
        self.assertEqual(self.wf["jobs"]["tests"]["strategy"]["matrix"]["shard"],
                         list(range(1, self.n + 1)))
        self.assertGreater(self.n, 1)
        steps = self.wf["jobs"]["tests"]["steps"]
        run = [s for s in steps if s.get("name") == "Run the test suite"][0]["run"]
        self.assertIn(f"--shard ${{{{ matrix.shard }}}}/{self.n}", run)
        self.assertIn("--summary-json", run)
        merge = [s for s in self.wf["jobs"]["tests-summary"]["steps"]
                 if "--merge" in str(s.get("run", ""))][0]["run"]
        self.assertIn(f"--shards {self.n}", merge)
        self.assertIn(f"{{{{ matrix.shard }}}}/{self.n}", self.wf["jobs"]["tests"]["name"])

    def test_the_runner_lists_each_file_once_across_the_shards(self):
        """`suite_runner.py --shard i/N --list`, as CI would run it here."""
        seen = []
        for i in range(1, self.n + 1):
            out = subprocess.run(
                [sys.executable, str(ROOT / "devtools" / "suite_runner.py"),
                 "--shard", f"{i}/{self.n}", "--list"],
                cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
            self.assertTrue(out, f"shard {i}/{self.n} is empty")
            seen += out
        self.assertEqual(sorted(seen), [f.name for f in TEST_FILES])

    def test_every_platform_splits_the_whole_suite_once(self):
        for platform in suite_runner.PLATFORMS:
            seen = []
            for i in range(1, self.n + 1):
                seen += [f.name for f in suite_runner.shard_files(
                    TEST_FILES, i, self.n, platform, self.timings)]
            self.assertEqual(sorted(seen), [f.name for f in TEST_FILES], platform)

    def test_the_split_ignores_the_order_files_are_found_in(self):
        shuffled = TEST_FILES[:]
        random.Random(7).shuffle(shuffled)
        for i in range(1, self.n + 1):
            self.assertEqual(
                suite_runner.shard_files(TEST_FILES, i, self.n, "windows", self.timings),
                suite_runner.shard_files(shuffled, i, self.n, "windows", self.timings))

    def test_no_shard_carries_more_than_its_share_plus_one_file(self):
        """The greedy split's guarantee, on the recorded Windows times."""
        t = self.timings["windows"]
        weights = [t.get(f.name, 1) for f in TEST_FILES]
        share = sum(weights) / self.n
        for i in range(1, self.n + 1):
            load = sum(t.get(f.name, 1) for f in suite_runner.shard_files(
                TEST_FILES, i, self.n, "windows", self.timings))
            self.assertLessEqual(load, share + max(weights), f"shard {i}")

    def test_the_timings_cover_most_of_the_suite_and_name_only_real_files(self):
        names = {f.name for f in TEST_FILES}
        for platform in ("windows", "linux"):
            recorded = set(self.timings[platform])
            self.assertLessEqual(recorded - names, set(),
                                 f"{platform}: timings for files that no longer exist")
            self.assertGreater(len(recorded & names), 0.8 * len(names), platform)

    def test_a_file_without_a_time_is_weighed_by_its_size(self):
        with tempfile.TemporaryDirectory() as d:
            big, small = Path(d, "test_big.py"), Path(d, "test_small.py")
            big.write_text("x" * 10_000)
            small.write_text("x" * 10)
            timed = Path(d, "test_timed.py")
            timed.write_text("x" * 100)
            timings = {"windows": {"test_timed.py": 1}}
            first = suite_runner.shard_files([small, timed, big], 1, 2, "windows", timings)
            self.assertEqual([f.name for f in first], ["test_big.py"])

    def test_timings_are_read_back_from_a_ci_log(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d, "job.log")
            log.write_text(
                "2026-11-23T15:22:24.1Z ok    test_a.py  16 tests, 0 failing  (12s)\n"
                "2026-11-23T15:22:25.1Z FAIL  test_b.py  3 tests, 1 failing  (40s)\n"
                "2026-11-23T15:22:26.1Z known test_c.py  3 tests, 1 failing  (7s)  (passed on retry after a crash)\n"
                "2026-11-23T15:22:27.1Z KNOWN  test_d.py  the process died before reporting (exit 3)  (9s)\n"
                "2026-11-23T15:22:28.1Z RETRY  test_d.py  first attempt: timed out after 480s\n"
                "      NEW   test_b.py::X::test_y  boom (3s)\n", encoding="utf-8")
            got = suite_runner.timings_from_logs([f"windows={log}"])
        self.assertEqual(got, {"windows": {"test_a.py": 12, "test_b.py": 40,
                                           "test_c.py": 7, "test_d.py": 9}})


PASSING = "def test_ok():\n    assert True\n"
FAILING = ("def test_ok():\n    assert True\n\n"
           "def test_known():\n    assert False, 'known one'\n\n"
           "def test_new():\n    assert False, 'a new one'\n")


class ShardResultsMergeIntoOneVerdict(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _run(self, *argv, known=frozenset()):
        out = io.StringIO()
        real = suite_runner.load_known
        suite_runner.load_known = lambda: set(known)
        try:
            with contextlib.redirect_stdout(out):
                rc = suite_runner.main(list(argv))
        finally:
            suite_runner.load_known = real
        return rc, out.getvalue()

    def _files(self, failing: bool):
        a = self.d / "test_alpha.py"
        b = self.d / "test_beta.py"
        a.write_text(PASSING)
        b.write_text(FAILING if failing else PASSING)
        return [str(a), str(b)]

    def _shards(self, files, known=frozenset()):
        out = self.d / "summaries"
        out.mkdir(exist_ok=True)
        results = []
        for i in (1, 2):
            rc, text = self._run(*files, "--shard", f"{i}/2",
                                 "--summary-json", str(out / f"s{i}.json"), known=known)
            results.append((rc, text))
        return out, results

    def test_a_clean_run_merges_green(self):
        files = self._files(failing=False)
        out, results = self._shards(files)
        self.assertEqual([rc for rc, _ in results], [0, 0])
        rc, text = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 0, text)
        self.assertIn("2 tests in 2 files", text)
        ran = [json.loads(p.read_text())["files"] for p in sorted(out.glob("*.json"))]
        self.assertEqual(sorted(sum(ran, [])), ["test_alpha.py", "test_beta.py"])

    def test_a_new_failure_in_one_shard_fails_it_and_the_merge_names_it(self):
        files = self._files(failing=True)
        known = {"test_beta.py::test_beta::test_known"}
        out, results = self._shards(files, known=known)
        bad = [text for rc, text in results if rc == 1]
        self.assertEqual(len(bad), 1, results)
        self.assertIn("NEW FAILURES", bad[0])
        self.assertIn("(shard ", bad[0])
        rc, text = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 1)
        new = text.split("NEW FAILURES:", 1)[1]
        self.assertIn("test_beta.py::test_beta::test_new", new)
        self.assertNotIn("test_known", new)          # the known one stays known

    def test_a_known_failure_alone_keeps_the_shard_green(self):
        files = self._files(failing=True)
        known = {"test_beta.py::test_beta::test_known", "test_beta.py::test_beta::test_new"}
        out, results = self._shards(files, known=known)
        self.assertEqual([rc for rc, _ in results], [0, 0])
        rc, text = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 0, text)

    def test_a_missing_shard_fails_the_merge(self):
        files = self._files(failing=False)
        out, _ = self._shards(files)
        (out / "s2.json").unlink()
        rc, text = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 1)
        self.assertIn("no summary from shard(s) 2/2", text)

    def test_a_file_in_two_shards_or_in_none_fails_the_merge(self):
        files = self._files(failing=False)
        out, _ = self._shards(files)
        s1, s2 = (json.loads((out / f"s{i}.json").read_text()) for i in (1, 2))
        s2["files"] = s1["files"]
        (out / "s2.json").write_text(json.dumps(s2))
        rc, text = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 1)
        self.assertIn("ran in more than one shard", text)
        self.assertIn("ran in no shard", text)

    def test_a_shard_that_exited_red_fails_the_merge_even_without_a_listed_failure(self):
        files = self._files(failing=False)
        out, _ = self._shards(files)
        s1 = json.loads((out / "s1.json").read_text())
        s1["exit"] = 1
        (out / "s1.json").write_text(json.dumps(s1))
        rc, _ = self._run(*files, "--merge", str(out), "--shards", "2")
        self.assertEqual(rc, 1)


class AFailureIdIsTheSameOnEveryOS(unittest.TestCase):
    """The junit classname pytest writes depends on where the file sits. On
    Windows CI a file outside the checkout (temp dir on C:, repo on D:) gave
    `test_beta.py::py::test_known`, so a listed failure in such a file never matched."""

    def key(self, classname, name="test_known", file=r"C:\Users\RUNNER~1\AppData\Local\Temp\tmp.a1\test_beta.py"):
        return suite_runner.case_key(PureWindowsPath(file), classname, name)

    def test_a_module_level_test_is_keyed_by_the_module(self):
        for classname in ("test_beta",
                          "tests.test_beta",
                          ".test_beta.py",                        # seen on Windows CI
                          "C:.Users.RUNNER~1.AppData.Local.Temp.tmp.a1.test_beta",
                          r"C:\Users\RUNNER~1\AppData\Local\Temp\tmp.a1\test_beta.py",
                          r"C:\Users\RUNNER~1\AppData\Local\Temp\tmp.a1\test_beta",
                          "C:/Users/runner/tmp.a1/test_beta.py",
                          ""):                                    # seen on Linux, outside rootdir
            self.assertEqual(self.key(classname), "test_beta.py::test_beta::test_known", classname)

    def test_a_test_in_a_class_is_keyed_by_the_class(self):
        for classname in ("tests.test_beta.TestThing",
                          r"D:\a\repo\tests\test_beta.TestThing",
                          ".test_beta.py.TestThing"):
            self.assertEqual(self.key(classname), "test_beta.py::TestThing::test_known", classname)

    def test_a_real_repo_file_keeps_its_id(self):
        self.assertEqual(suite_runner.case_key(Path("tests/test_x.py"), "tests.test_x.Cls", "test_y[a.b]"),
                         "test_x.py::Cls::test_y[a.b]")


class ATimedOutFileSaysWhereItWasStuck(unittest.TestCase):
    """test_gates.py on Windows (23 Nov 2026) printed every test passing and then
    sat until the 480 s file timeout. The runner threw the output and the
    watchdog's stack away, and a child holding the pipe could stall it too.
    These run real child processes (no shell, no /bin/sh), so they run on Windows too."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def run_hanging(self, body: str, timeout: int = 4):
        """Run a one-test file whose process then hangs; `body` runs after the test."""
        f = self.dir / "test_hang.py"
        f.write_text("def test_ok():\n    pass\n\n" + body, encoding="utf-8")
        t0 = time.monotonic()
        res = suite_runner.run_file(f, self.dir, 0, timeout)
        return res, time.monotonic() - t0

    @staticmethod
    def alive(pid: int) -> bool:
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True).stdout
            return str(pid) in out
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        try:                                    # a zombie is not running
            return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except OSError:
            return True

    def test_a_hang_after_the_tests_names_the_stage_and_keeps_the_output(self):
        done = self.dir / "test_hang.done.txt"
        body = ("import os, time\n"
                "def teardown_module(m):\n"
                "    open(os.environ['PRISM_FILE_DONE_LOG'], 'a').write('tests finished\\n')\n"
                "    time.sleep(600)\n")
        (cases, died, tail), secs = self.run_hanging(body)
        self.assertEqual(cases, [])
        self.assertIn("timed out after 4s", died)
        self.assertIn("the tests all finished", died)
        self.assertIn("'tests finished'", died)
        self.assertIn("runner killed it", died)
        self.assertLess(secs, 60)
        self.assertTrue(done.exists())

    def test_the_watchdog_stack_is_reported_when_the_process_still_did_not_end(self):
        body = ("import os, time\n"
                "def teardown_module(m):\n"
                "    open(%r, 'w').write('Thread 0x1 (most recent call first):\\n  File \"x.py\", line 9 in stuck_here\\n')\n"
                "    time.sleep(600)\n") % str(self.dir / "test_hang.hang.txt")
        (cases, died, tail), _ = self.run_hanging(body)
        self.assertIn("watchdog dumped every thread's stack", died)
        self.assertIn("stuck_here", tail)

    def test_a_child_holding_the_output_is_killed_with_the_process(self):
        pidfile = self.dir / "child.pid"
        body = ("import subprocess, sys, time\n"
                "def teardown_module(m):\n"
                "    c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
                "    open(%r, 'w').write(str(c.pid))\n"
                "    time.sleep(600)\n") % str(pidfile)
        (cases, died, tail), secs = self.run_hanging(body)
        self.assertIn("timed out after 4s", died)
        self.assertLess(secs, 60)                # a held pipe used to stall the runner
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 10
        while self.alive(pid) and time.monotonic() < deadline:
            time.sleep(0.2)
        self.assertFalse(self.alive(pid), "the grandchild survived the runner's kill")

    def test_a_file_that_finishes_leaves_its_stage_markers(self):
        """The real conftest writes both stages; a clean file is not reported as hung."""
        cases, died, _ = suite_runner.run_file(ROOT / "tests" / "test_repo_layout.py", self.dir, 0, 300)
        self.assertEqual(died, "")
        self.assertTrue(cases)
        stages = (self.dir / "test_repo_layout.done.txt").read_text(encoding="utf-8")
        self.assertIn("pytest session finished (exit status 0)", stages)
        self.assertIn("calling os._exit", stages)


class TagRunsAndReleasesAreUntouched(unittest.TestCase):

    def setUp(self):
        self.wf = _wf()
        self.on = self.wf.get("on", self.wf.get(True))

    def test_a_tag_run_is_never_cancelled_and_has_a_group_of_its_own(self):
        c = self.wf["concurrency"]
        self.assertEqual(c["cancel-in-progress"], "${{ !startsWith(github.ref, 'refs/tags/') }}")
        self.assertIn("startsWith(github.ref, 'refs/tags/') && github.run_id || github.ref",
                      c["group"])
        self.assertTrue(c["group"].startswith("${{ github.workflow }}-"))
        # the nightly run and different flavours never cancel each other
        self.assertIn("github.event_name", c["group"])
        self.assertIn("inputs.flavour", c["group"])
        for name, job in self.wf["jobs"].items():
            self.assertNotIn("concurrency", job, name)

    def test_the_release_job_runs_for_a_pushed_v_tag_only_after_builds_and_every_shard(self):
        rel = self.wf["jobs"]["release"]
        self.assertEqual(rel["if"],
                         "github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')")
        self.assertEqual(rel["needs"], ["build", "tests"])

    def test_tags_still_trigger_the_workflow_and_assets_tags_do_not(self):
        self.assertEqual(self.on["push"]["tags"], ["v*", "!v*-assets-*"])
        self.assertEqual(self.on["push"]["branches"], ["main", "master"])

    def test_nothing_the_release_needs_can_be_skipped_on_a_tag(self):
        """GitHub skips every job downstream of a skipped one. `changes` has no
        `if:` so it never is; `build` needs only it."""
        self.assertNotIn("if", self.wf["jobs"]["changes"])
        self.assertEqual(self.wf["jobs"]["build"]["needs"], "changes")
        self.assertNotIn("needs", self.wf["jobs"]["tests"])

    def test_test_results_are_never_swept_into_the_release(self):
        pattern = [s for s in self.wf["jobs"]["release"]["steps"]
                   if s.get("uses", "").startswith("actions/download-artifact")][0]["with"]["pattern"]
        self.assertEqual(pattern, "prism-*")
        uploads = [s["with"]["name"] for s in self.wf["jobs"]["tests"]["steps"]
                   if s.get("uses", "").startswith("actions/upload-artifact")]
        self.assertTrue(uploads)
        for name in uploads:
            self.assertFalse(name.startswith("prism-"), name)


class TestsRunEverywhereAndBuildsOnlyWhenNeeded(unittest.TestCase):

    def setUp(self):
        self.wf = _wf()
        self.on = self.wf.get("on", self.wf.get(True))

    def test_windows_is_in_the_test_matrix_and_the_tests_always_run(self):
        m = self.wf["jobs"]["tests"]["strategy"]["matrix"]
        self.assertIn("windows-latest", m["os"])
        self.assertIn("ubuntu-22.04", m["os"])
        self.assertFalse(self.wf["jobs"]["tests"]["strategy"]["fail-fast"])
        self.assertNotIn("if", self.wf["jobs"]["tests"])
        summary = self.wf["jobs"]["tests-summary"]
        self.assertEqual(summary["strategy"]["matrix"]["label"], ["Linux", "Windows"])
        self.assertEqual(summary["name"], "Tests · ${{ matrix.label }}")
        self.assertEqual(summary["if"], "${{ !cancelled() }}")
        self.assertEqual(summary["needs"], "tests")

    def test_pull_requests_and_the_nightly_run_trigger_the_workflow(self):
        self.assertIn("pull_request", self.on)
        self.assertTrue(self.on["schedule"][0]["cron"])
        self.assertIn("workflow_dispatch", self.on)

    def test_the_build_condition(self):
        cond = " ".join(self.wf["jobs"]["build"]["if"].split())
        self.assertEqual(cond, "!cancelled() && ( github.event_name != 'pull_request' "
                               "|| contains(github.event.pull_request.labels.*.name, 'build') "
                               "|| needs.changes.outputs.packaging != 'false' )")

    def test_the_change_check_runs_on_pull_requests_only_and_feeds_the_build(self):
        job = self.wf["jobs"]["changes"]
        self.assertEqual(job["outputs"]["packaging"], "${{ steps.diff.outputs.packaging }}")
        for step in job["steps"]:
            self.assertEqual(step.get("if"), "github.event_name == 'pull_request'", step)
        diff = [s for s in job["steps"] if s.get("id") == "diff"][0]
        self.assertIn("devtools/ci_changes.py HEAD^1 HEAD", diff["run"])
        self.assertIn('"$GITHUB_OUTPUT"', diff["run"])

    def test_which_paths_count_as_packaging(self):
        self.assertEqual(ci_changes.PATTERNS, (
            "packaging/**", "flavour.py", "requirements*", "constraints/**",
            ".github/workflows/**", "main.py", "addons/flavours/**", "prism_terminal"))
        build = ["packaging/prism.spec", "packaging/requirements-build.txt",
                 "packaging/windows/prism.iss", "packaging/windows/installer_check.py", "flavour.py",
                 "requirements.txt", "constraints/windows-x64.txt", ".github/workflows/build.yml",
                 "main.py", "addons/flavours/sales.py", "prism_terminal"]
        quiet = ["main_window.py", "tests/test_x.py", "addons/boq/panel.py", "docs/main.py",
                 "addons/flavour.py", "devtools/requirements.txt", "README.md", "packagingx/a",
                 "prism_terminal_notes.md"]
        self.assertEqual(ci_changes.touches_packaging(build), build)
        self.assertEqual(ci_changes.touches_packaging(quiet), [])

    def test_the_change_check_answers_from_git(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                       GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

            def git(*a):
                subprocess.run(["git", "-c", "commit.gpgsign=false", *a], cwd=d, env=env, check=True, capture_output=True)

            git("init", "-q")
            Path(d, "a.py").write_text("1")
            git("add", "a.py")
            git("commit", "-qm", "base")
            Path(d, "a.py").write_text("2")
            git("commit", "-qam", "code only")
            Path(d, "packaging").mkdir()
            Path(d, "packaging", "build.py").write_text("x")
            git("add", "packaging/build.py")
            git("commit", "-qm", "packaging")
            script = str(ROOT / "devtools" / "ci_changes.py")
            run = lambda *a: subprocess.run([sys.executable, script, *a], cwd=d,  # noqa: E731
                                            capture_output=True, text=True)
            self.assertEqual(run("HEAD~2", "HEAD~1").stdout.strip(), "packaging=false")
            self.assertEqual(run("HEAD~1", "HEAD").stdout.strip(), "packaging=true")
            self.assertNotEqual(run("nope", "HEAD").returncode, 0)   # build then runs anyway

    def test_pip_cache_follows_the_exact_pins(self):
        for job in ("tests", "build"):
            setup = [s for s in self.wf["jobs"][job]["steps"]
                     if s.get("uses", "").startswith("actions/setup-python")][0]["with"]
            self.assertEqual(setup["cache"], "pip")
            paths = setup["cache-dependency-path"].splitlines()
            self.assertEqual(paths, ["requirements.txt", "packaging/requirements-build.txt",
                                     "constraints/${{ matrix.pins }}.txt"], job)
            install = [s for s in self.wf["jobs"][job]["steps"]
                       if s.get("name") == "Install dependencies"][0]["run"]
            self.assertIn("pip install -r requirements.txt -c constraints/${{ matrix.pins }}.txt",
                          install)

    def test_the_scenario_checks_run_once_per_platform(self):
        step = [s for s in self.wf["jobs"]["tests"]["steps"]
                if s.get("name") == "Scenario checks"][0]
        self.assertEqual(step["if"], "matrix.shard == 1")
        self.assertIn(1, self.wf["jobs"]["tests"]["strategy"]["matrix"]["shard"])


class TheShardJobsUseTheRealRunner(unittest.TestCase):

    def test_the_workflow_flags_exist_in_the_runner(self):
        wf = _wf()
        runs = [s.get("run", "") for job in ("tests", "tests-summary")
                for s in wf["jobs"][job]["steps"]]
        flags = {f for r in runs if "suite_runner.py" in r for f in re.findall(r"--[\w-]+", r)}
        self.assertTrue({"--shard", "--summary-json", "--merge", "--shards"} <= flags, flags)
        out = subprocess.run([sys.executable, str(ROOT / "devtools" / "suite_runner.py"), "--help"],
                             capture_output=True, text=True, check=True).stdout
        for flag in flags:
            self.assertIn(flag, out, flag)


if __name__ == "__main__":
    unittest.main()

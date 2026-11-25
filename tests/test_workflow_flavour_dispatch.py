"""A manual (workflow_dispatch) build of one flavour must never publish.

Parses .github/workflows/build.yml and pins: the `flavour` input and its four
choices, that the flavour reaches the build and the tests, that the release job
runs on a pushed tag only (a dispatch started on a tag ref must not publish),
that nothing else in the workflow can publish, and that each flavour's update
manifest and per-file update assets are made under its own channel and stay
artifacts of the run. The manifest and flatten steps are run for real (POSIX).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import flavour  # noqa: E402

PUBLISHERS = ("softprops/action-gh-release", "gh release", "git push", "git tag",
              "twine", "scp ", "rsync", "aws s3", "wrangler", "curl -X POST",
              "license_server", "/admin", "ADMIN_TOKEN")   # nor the licence server


def _load():
    with open(os.path.join(ROOT, ".github", "workflows", "build.yml"),
              encoding="utf-8") as f:
        return yaml.safe_load(f)


def _step_text(step) -> str:
    """What a step executes (a step that only echoes is a message)."""
    run = str(step.get("run", ""))
    if run.lstrip().startswith("echo "):        # a message, not a command
        run = ""
    return " ".join((str(step.get("uses", "")), run))


class DispatchBuildsOneFlavourAndNeverPublishes(unittest.TestCase):

    def setUp(self):
        self.wf = _load()
        self.on = self.wf.get("on", self.wf.get(True))   # PyYAML reads `on:` as True

    def test_the_flavour_input_offers_the_four_flavours(self):
        inp = self.on["workflow_dispatch"]["inputs"]["flavour"]
        self.assertEqual(inp["type"], "choice")
        self.assertEqual(inp["options"], ["complete", "studio", "sales", "engineering"])
        self.assertEqual(sorted(inp["options"]), sorted(flavour.FLAVOURS))
        self.assertEqual(inp["default"], "complete")

    def test_the_flavour_reaches_the_build_and_defaults_to_complete(self):
        self.assertEqual(self.wf["env"]["PRISM_BUILD_FLAVOUR"],
                         "${{ inputs.flavour || 'complete' }}")
        steps = self.wf["jobs"]["tests"]["steps"]
        run = [s for s in steps if s.get("name") == "Run the test suite"][0]
        self.assertEqual(run["env"]["PRISM_TEST_FLAVOUR"], "${{ inputs.flavour }}")

    def test_the_release_job_runs_for_a_pushed_tag_only(self):
        cond = self.wf["jobs"]["release"]["if"]
        self.assertIn("github.event_name == 'push'", cond)
        self.assertIn("startsWith(github.ref, 'refs/tags/v')", cond)

    def test_only_the_release_job_can_publish_and_nothing_touches_the_licence_server(self):
        for name, job in self.wf["jobs"].items():
            if name == "release":
                continue
            for step in job["steps"]:
                text = _step_text(step)
                for needle in PUBLISHERS:
                    self.assertNotIn(needle, text,
                                     f"job {name!r}, step {step.get('name')!r}: {needle}")

    def test_every_job_that_runs_on_dispatch_is_gated_or_publishes_nothing(self):
        """tests has no `if:` and build's `if:` is true for every event that is
        not a pull request, so both run on dispatch; release is gated.

        Changed 2026-11-24 (CI speed-up): build used to have no `if:` either.
        It now skips pull requests that touch no packaging file
        (tests/test_workflow_speed.py pins the exact condition); a dispatch
        still always builds, which is what this test is about."""
        self.assertNotIn("if", self.wf["jobs"]["tests"])
        self.assertIn("github.event_name != 'pull_request'", self.wf["jobs"]["build"]["if"])
        self.assertIn("if", self.wf["jobs"]["release"])

    def test_update_assets_artifact_is_never_what_the_release_job_downloads(self):
        """Changed 2026-11-25: the manifest and the assets used to be made for
        the complete build only, so a flavour could never be updated. They are
        now made for every flavour, under its own channel name (the class below
        runs the steps). What must still hold: complete's artifact keeps its
        exact name (release_all.py downloads it by name), and no update-assets
        artifact, of any flavour, matches the release job's `prism-*`."""
        steps = self.wf["jobs"]["build"]["steps"]
        names = [s["with"]["name"] for s in steps
                 if s.get("uses", "").startswith("actions/upload-artifact")]
        assets = [n for n in names if "update-assets" in n]
        self.assertEqual(assets, [
            "${{ env.PRISM_BUILD_FLAVOUR == 'complete' && format('update-assets-{0}', matrix.os)"
            " || format('update-assets-{0}-{1}', env.PRISM_BUILD_FLAVOUR, matrix.os) }}"])
        self.assertEqual(len(names), 2)      # nothing else is uploaded by the build job
        self.assertFalse(any("prism-" in n for n in assets))

    def test_complete_keeps_its_artifact_name_and_flavours_get_their_own(self):
        steps = self.wf["jobs"]["build"]["steps"]
        names = [s["with"]["name"] for s in steps
                 if s.get("uses", "").startswith("actions/upload-artifact")]
        main = [n for n in names if "prism-" in n and "update-assets" not in n][0]
        self.assertIn("format('prism-{0}', matrix.os)", main)          # unchanged
        self.assertIn("format('prism-{0}-{1}', env.PRISM_BUILD_FLAVOUR, matrix.os)", main)
        # the release job downloads `prism-*`; it never runs on dispatch
        dl = [s for s in self.wf["jobs"]["release"]["steps"]
              if s.get("uses", "").startswith("actions/download-artifact")][0]
        self.assertEqual(dl["with"]["pattern"], "prism-*")

    def test_windows_stays_in_every_matrix(self):
        for job in ("tests", "build"):
            oses = [m["os"] for m in self.wf["jobs"][job]["strategy"]["matrix"]["include"]]
            self.assertIn("windows-latest", oses)


@unittest.skipIf(sys.platform == "win32",
                 "runs the workflow's bash steps against copied sources; the Windows "
                 "build job runs the real ones")
class EachFlavoursManifestAndAssetsAreItsOwn(unittest.TestCase):
    """The two workflow steps, run as bash runs them, on a small built tree."""

    def run_steps(self, flav: str) -> tuple[dict, list[str], str]:
        work = tempfile.mkdtemp(prefix="prism-wf-")
        self.addCleanup(shutil.rmtree, work, True)
        for name in ("app_meta.py", "channel.py", "flavour.py", "paths.py", "updater.py",
                     "update_manifest.py", "licensing", "packaging"):
            src, dst = os.path.join(ROOT, name), os.path.join(work, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, dst)
        os.makedirs(os.path.join(work, "dist", "Prism", "_internal"))
        for rel in ("dist/Prism/Prism", "dist/Prism/_internal/a.dat", "dist/Prism.tar.gz"):
            with open(os.path.join(work, rel), "w") as f:
                f.write(rel)
        shim = os.path.join(work, "bin")
        os.makedirs(shim)
        os.symlink(sys.executable, os.path.join(shim, "python"))
        env = {k: v for k, v in os.environ.items() if not k.startswith("PRISM_")}
        gh_env = os.path.join(work, "github_env")
        env.update(PRISM_BUILD_FLAVOUR=flav, GITHUB_ENV=gh_env, HOME=work,
                   PATH=shim + os.pathsep + env["PATH"])
        steps = {s.get("name"): s for s in _load()["jobs"]["build"]["steps"]}
        for name in ("Generate the (unsigned) update manifest",
                     "Flatten update assets for hosting"):
            self.assertNotIn("if", steps[name], name)
            done = subprocess.run(["bash", "-eo", "pipefail", "-c", steps[name]["run"]],
                                  cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            with open(gh_env) as f:
                env.update(line.strip().split("=", 1) for line in f if "=" in line)
        made = [n for n in os.listdir(os.path.join(work, "dist")) if n.startswith("manifest.")]
        self.assertEqual(len(made), 1)
        with open(os.path.join(work, "dist", made[0])) as f:
            manifest = json.load(f)
        return manifest, sorted(os.listdir(os.path.join(work, "dist", "update-assets"))), made[0]

    def test_complete_is_what_it_always_was(self):
        import updater
        tag = updater.platform_tag()
        manifest, assets, name = self.run_steps("complete")
        self.assertEqual(name, f"manifest.{tag}.unsigned.json")
        self.assertEqual(set(manifest), {"version", "files", "archive"})
        self.assertEqual(assets, [f"{tag}__Prism", f"{tag}___internal__a.dat"])

    def test_a_flavour_gets_its_channel_in_the_names_and_in_the_signed_content(self):
        import updater
        for flav in ("studio", "sales", "engineering"):
            channel = f"{updater.platform_tag()}-{flav}"
            manifest, assets, name = self.run_steps(flav)
            self.assertEqual(name, f"manifest.{channel}.unsigned.json")
            self.assertEqual(manifest["update_channel"], channel)
            self.assertEqual(set(manifest), {"version", "files", "archive", "update_channel"})
            self.assertEqual(assets, [f"{channel}__Prism", f"{channel}___internal__a.dat"])


class BuildStampsTheFlavour(unittest.TestCase):

    def setUp(self):
        import build
        self.build = build

    def test_patch_flavour_sets_the_constant_and_nothing_else(self):
        with open(os.path.join(ROOT, "flavour.py"), encoding="utf-8") as f:
            src = f.read()
        for name in flavour.FLAVOURS:
            out = self.build.patch_flavour(src, name)
            self.assertIn(f'FLAVOUR = "{name}"', out)
            if name == "complete":
                self.assertEqual(out, src)
            ns = {}
            exec(compile(out, "flavour.py", "exec"), ns)
            self.assertEqual(ns["FLAVOUR"], name)

    def test_patch_flavour_refuses_a_file_it_cannot_stamp(self):
        with self.assertRaises(SystemExit):
            self.build.patch_flavour("FLAVOUR = 'x'\n", "sales")

    def test_requested_flavour_defaults_to_complete_and_rejects_nonsense(self):
        old = os.environ.get("PRISM_BUILD_FLAVOUR")
        try:
            os.environ["PRISM_BUILD_FLAVOUR"] = ""
            self.assertEqual(self.build.requested_flavour(), "complete")
            os.environ["PRISM_BUILD_FLAVOUR"] = "Sales"
            self.assertEqual(self.build.requested_flavour(), "sales")
            os.environ["PRISM_BUILD_FLAVOUR"] = "pro"
            with self.assertRaises(SystemExit):
                self.build.requested_flavour()
        finally:
            if old is None:
                os.environ.pop("PRISM_BUILD_FLAVOUR", None)
            else:
                os.environ["PRISM_BUILD_FLAVOUR"] = old

    def test_the_repo_file_is_complete_and_the_archive_name_is_unchanged_for_it(self):
        # The FILE in the repo, not the module constant: tests/conftest.py sets
        # flavour.FLAVOUR from PRISM_TEST_FLAVOUR, so the constant says "sales"
        # in a Sales test run while the file on disk must still say complete.
        with open(os.path.join(ROOT, "flavour.py"), encoding="utf-8") as f:
            stamped = re.search(r'^FLAVOUR = "(\w+)"', f.read(), re.M).group(1)
        self.assertEqual(stamped, "complete")
        if self.build.FLAVOUR_BUILT == "complete":
            self.assertNotIn("complete", self.build.STEM)


if __name__ == "__main__":
    unittest.main()

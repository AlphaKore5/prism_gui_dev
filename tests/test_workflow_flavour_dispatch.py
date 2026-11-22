"""A manual (workflow_dispatch) build of one flavour must never publish.

Parses .github/workflows/build.yml and pins: the `flavour` input and its four
choices, that the flavour reaches the build and the tests, that the release job
runs on a pushed tag only (a dispatch started on a tag ref must not publish),
that nothing else in the workflow can publish, and that the update manifest and
per-file update assets are made for the complete build only.
"""
from __future__ import annotations

import os
import re
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
        """tests and build have no `if:` (they run on dispatch); release does."""
        for name in ("tests", "build"):
            self.assertNotIn("if", self.wf["jobs"][name], name)
        self.assertIn("if", self.wf["jobs"]["release"])

    def test_update_manifest_and_assets_are_for_the_complete_build_only(self):
        steps = self.wf["jobs"]["build"]["steps"]
        gate = "env.PRISM_BUILD_FLAVOUR == 'complete'"
        for step in steps:
            text = _step_text(step) + str(step.get("with", ""))
            if "manifest.py" in text or "flatten_update_assets" in text \
                    or str(step.get("with", {}).get("name", "")).startswith("update-assets"):
                self.assertEqual(step.get("if"), gate, step.get("name") or step)

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
        self.assertEqual(flavour.FLAVOUR, "complete")
        if self.build.FLAVOUR_BUILT == "complete":
            self.assertNotIn("complete", self.build.STEM)


if __name__ == "__main__":
    unittest.main()

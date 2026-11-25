"""Every build installs exact library versions, and the files that say which
are complete.

Until 1.8.9 nothing was pinned: 163 MB of a 207 MB update was libraries that
changed on their own. constraints/README.md has the story. This guards the
three ways it quietly comes back: a CI job that installs without `-c`, a
platform with no file, and a new requirement that nobody pinned.
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


# macOS joins as soon as its file is committed.
_PLATFORMS = {p: s for p, s in (("linux-x64", "linux"), ("windows-x64", "win32"),
                                ("macos-arm64", "darwin"))
              if p != "macos-arm64" or os.path.isfile(os.path.join(ROOT, "constraints", p + ".txt"))}


def _pins(platform):
    out = {}
    for line in _read(f"constraints/{platform}.txt").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.\-]+)==([0-9][^\s;]*)", line)
        assert m, f"{platform}.txt: not an exact pin: {line!r}"
        out[m.group(1).lower().replace("_", "-")] = m.group(2)
    return out


def _direct(sys_platform):
    from packaging.requirements import Requirement
    names = []
    for line in _read("requirements.txt").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        req = Requirement(line)
        if req.marker and not req.marker.evaluate({"sys_platform": sys_platform,
                                                    "python_version": "3.12"}):
            continue
        names.append(req.name.lower().replace("_", "-"))
    return names


class TheBuildInstallsExactVersions(unittest.TestCase):
    def test_every_ci_install_of_requirements_uses_the_platform_file(self):
        wf = _read(".github/workflows/build.yml")
        installs = [l.strip() for l in wf.splitlines()
                    if re.search(r"pip install -r (requirements\.txt|packaging/requirements-build\.txt)", l)]
        self.assertGreaterEqual(len(installs), 3, installs)
        for line in installs:
            self.assertIn("-c constraints/${{ matrix.pins }}.txt", line,
                          "installs without the constraints file: " + line)

    def test_every_matrix_leg_names_a_file_that_exists(self):
        wf = _read(".github/workflows/build.yml")
        legs = set(re.findall(r"^\s+pins:\s*(\S+)", wf, re.M))
        self.assertEqual({"linux-x64", "windows-x64", "macos-arm64"}, legs)
        # macOS: recorded by macos-pins.yml. Until then: the next test.
        for leg in legs - {"macos-arm64"}:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "constraints", leg + ".txt")), leg)

    @unittest.skipIf(os.name == "nt", "runs the Mac job's bash step")
    def test_without_its_file_a_mac_test_build_warns_and_a_tag_stops(self):
        import subprocess
        import tempfile

        import yaml
        steps = yaml.safe_load(_read(".github/workflows/build.yml"))["jobs"]["build-macos"]["steps"]
        names = [s.get("name") for s in steps]
        step = steps[names.index("The macOS pin file")]
        self.assertNotIn("if", step)
        self.assertLess(names.index("The macOS pin file"), names.index("Install dependencies"))
        run = step["run"].replace("${{ matrix.pins }}", "macos-arm64")
        for ref, has_file, code, said in (("branch", False, 0, "::warning::NOT PINNED"),
                                          ("tag", False, 1, "::error::"),
                                          ("branch", True, 0, ""), ("tag", True, 0, "")):
            with tempfile.TemporaryDirectory() as d:
                os.mkdir(os.path.join(d, "constraints"))
                pins = os.path.join(d, "constraints", "macos-arm64.txt")
                if has_file:
                    with open(pins, "w") as f:
                        f.write("a==1\n")
                r = subprocess.run(["bash", "-e", "-c", run], cwd=d, capture_output=True, text=True,
                                   env={"PATH": os.environ["PATH"], "GITHUB_REF_TYPE": ref})
                self.assertEqual(r.returncode, code, (ref, has_file, r.stdout))
                self.assertIn(said, r.stdout)
                if not said:
                    self.assertEqual(r.stdout, "")
                if has_file:
                    with open(pins) as f:
                        self.assertEqual(f.read(), "a==1\n")

    def test_only_the_recording_workflow_installs_unpinned(self):
        wf = _read(".github/workflows/macos-pins.yml")
        self.assertIn("pip install -r requirements.txt -r packaging/requirements-build.txt\n", wf)

    def test_every_line_is_an_exact_pin(self):
        for plat in _PLATFORMS:
            self.assertGreater(len(_pins(plat)), 100, plat)

    def test_every_direct_requirement_is_pinned(self):
        for plat, sysp in _PLATFORMS.items():
            pins = _pins(plat)
            missing = [n for n in _direct(sysp) if n not in pins]
            self.assertEqual([], missing,
                             f"{plat}: requirements.txt gained {missing}; add their exact versions "
                             "to constraints/ in the same commit (README.md says how)")


if __name__ == "__main__":
    unittest.main()

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
        # macOS: recorded on our own Mac (macos-pins.yml). Until it is, the Mac
        # build job stops before it installs anything: the next test.
        for leg in legs - {"macos-arm64"}:
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "constraints", leg + ".txt")), leg)

    def test_the_mac_build_stops_when_its_file_is_missing(self):
        import yaml
        steps = yaml.safe_load(_read(".github/workflows/build.yml"))["jobs"]["build-macos"]["steps"]
        names = [s.get("name") for s in steps]
        check = steps[names.index("The macOS pin file must exist")]
        self.assertIn('[ ! -f "constraints/${{ matrix.pins }}.txt" ]', check["run"])
        self.assertIn("exit 1", check["run"])
        self.assertNotIn("if", check)
        self.assertLess(names.index("The macOS pin file must exist"),
                        names.index("Install dependencies"))

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

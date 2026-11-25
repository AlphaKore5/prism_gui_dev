"""The Windows installer (packaging/windows/prism.iss) installs per user, keeps
the person's data, and stays compatible with the in-app updater.

Static checks of the script and of how packaging/build.py calls Inno Setup.
What only the Windows build job proves (packaging/windows/installer_check.py):
that it compiles, installs, runs, survives an update swap and uninstalls.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
import uuid
from unittest import mock

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))
sys.path.insert(0, os.path.join(ROOT, "packaging", "windows"))

import app_meta  # noqa: E402
import build  # noqa: E402
import flavour  # noqa: E402
import installer_check  # noqa: E402

ISS = os.path.join(ROOT, "packaging", "windows", "prism.iss")

# Never change one: Windows files an install under its AppId, so a changed id
# installs a second copy beside the first instead of upgrading it.
APP_IDS = {
    "complete": "A9F3B880-46D3-441D-B7E4-E95A8DEDC8C6",
    "studio": "164D1A89-98DC-4F3C-9897-28AF43848731",
    "sales": "441C6F76-B957-4AA6-B807-D8A9D63E3F8D",
    "engineering": "05646D25-6DF8-4ECA-8DBA-8F69EA686059",
}


def _text() -> str:
    with open(ISS, encoding="utf-8") as f:
        return f.read()


def _code_lines() -> list[str]:
    """Lines that are not comments or blank."""
    return [ln.strip() for ln in _text().splitlines()
            if ln.strip() and not ln.strip().startswith(";")]


def _section(name: str) -> list[str]:
    out, inside = [], False
    for ln in _code_lines():
        if ln.startswith("["):
            inside = ln == f"[{name}]"
            continue
        if inside:
            out.append(ln)
    return out


def _setup() -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in _section("Setup"))


def _entries(name: str) -> list[dict[str, str]]:
    """`Type: x; Name: "y"` lines as dicts."""
    rows = []
    for ln in _section(name):
        rows.append({k.strip(): v.strip().strip('"')
                     for k, v in (part.split(":", 1) for part in ln.split(";"))})
    return rows


class InstallsPerUser(unittest.TestCase):

    def test_never_asks_for_admin_and_cannot_be_switched_to_it(self):
        s = _setup()
        self.assertEqual(s["PrivilegesRequired"], "lowest")
        self.assertNotIn("PrivilegesRequiredOverridesAllowed", s)

    def test_installs_into_local_app_data_programs(self):
        s = _setup()
        self.assertEqual(s["DefaultDirName"], r"{localappdata}\Programs\{#AppDirName}")
        self.assertEqual(s["DisableDirPage"], "yes")

    def test_no_machine_wide_location_anywhere(self):
        code = "\n".join(_code_lines()).lower()
        for const in ("{pf}", "{pf32}", "{pf64}", "{commonpf}", "{commonpf32}", "{commonpf64}",
                      "{autopf}", "{commonappdata}", "{commonprograms}", "{commondesktop}",
                      "{win}", "{sys}", "hklm"):
            self.assertNotIn(const, code, const)

    def test_the_uninstaller_lives_outside_the_program_folder(self):
        """An in-app update replaces the program folder with the manifest's files
        only; an uninstaller inside it would be gone after the first update."""
        d = _setup()["UninstallFilesDir"]
        self.assertTrue(d.startswith(r"{localappdata}\Programs" + "\\"), d)
        self.assertNotIn("{app}", d)
        self.assertNotEqual(d, _setup()["DefaultDirName"])


class CompressesHard(unittest.TestCase):

    def test_lzma2_ultra64_solid(self):
        s = _setup()
        self.assertEqual(s["Compression"], "lzma2/ultra64")
        self.assertEqual(s["SolidCompression"], "yes")
        self.assertEqual(s["LZMAUseSeparateProcess"], "yes")


class OneStableAppIdPerFlavour(unittest.TestCase):

    def test_the_ids_are_the_pinned_ones_for_exactly_the_flavours(self):
        self.assertEqual(installer_check.app_guids(_text()), APP_IDS)
        self.assertEqual(set(APP_IDS), set(flavour.FLAVOURS))

    def test_ids_are_distinct_guids_and_the_setup_uses_them(self):
        for f, guid in APP_IDS.items():
            self.assertEqual(str(uuid.UUID(guid)).upper(), guid, f)
        self.assertEqual(len(set(APP_IDS.values())), len(APP_IDS))
        self.assertEqual(_setup()["AppId"], "{#AppGuid}")
        self.assertIn("#error Unknown Flavour", _text())


class KeepsThePersonsData(unittest.TestCase):

    def test_uninstall_deletes_only_prisms_own_program_entries(self):
        allowed = {
            ("filesandordirs", r"{app}\_internal"),
            ("files", r"{app}\.prism_update_pending"),
            ("dirifempty", "{app}"),
            ("filesandordirs", "{app}.old"),
            ("filesandordirs", "{app}.failed-update"),
            ("dirifempty", r"{localappdata}\Programs\.prism-update-staging"),
        }
        rows = {(r["Type"], r["Name"]) for r in _entries("UninstallDelete")}
        self.assertEqual(rows, allowed)
        # the program folder itself goes only once it is empty
        self.assertNotIn(("filesandordirs", "{app}"), rows)

    def test_the_data_folder_is_never_named(self):
        code = "\n".join(_code_lines()).lower()
        for name in ("{userprofile}", "{%userprofile", "{userappdata}", "{localappdata}\\.prism",
                     "\\.prism\\", "{%home"):
            self.assertNotIn(name, code, name)
        prism_names = set(re.findall(r"\.prism[\w.-]*", code))
        self.assertLessEqual(prism_names, {".prism_update_pending", ".prism-update-staging"})

    def test_install_clears_only_the_old_program_tree(self):
        self.assertEqual([(r["Type"], r["Name"]) for r in _entries("InstallDelete")],
                         [("filesandordirs", r"{app}\_internal")])


class NothingElseIsAdded(unittest.TestCase):

    def test_no_autostart_file_associations_or_registry(self):
        sections = {ln for ln in _code_lines() if ln.startswith("[")}
        self.assertEqual(sections, {"[Setup]", "[Tasks]", "[InstallDelete]", "[Files]",
                                    "[Icons]", "[UninstallDelete]"})
        self.assertNotIn("ChangesAssociations", _setup())
        self.assertNotIn("{userstartup}", _text().lower())

    def test_start_menu_and_an_optional_desktop_icon(self):
        icons = _entries("Icons")
        self.assertEqual([i["Name"] for i in icons],
                         [r"{autoprograms}\{#AppName}", r"{autodesktop}\{#AppName}"])
        self.assertEqual(icons[1]["Tasks"], "desktopicon")
        self.assertEqual(_entries("Tasks")[0]["Flags"], "unchecked")


class VersionAndNamesComeFromTheApp(unittest.TestCase):

    def test_no_version_is_written_in_the_script(self):
        self.assertEqual(_setup()["AppVersion"], "{#AppVersion}")
        code = "\n".join(ln for ln in _code_lines() if not ln.startswith("#define AppGuid"))
        self.assertIsNone(re.search(r"\b\d+\.\d+\.\d+\b", code))
        self.assertIn("#ifndef AppVersion", _text())

    def test_build_passes_every_value_the_script_uses(self):
        args = build.iscc_args(os.path.join(build.DIST, app_meta.NAME))
        self.assertEqual(args[-1], ISS)
        defines = dict(a[2:].split("=", 1) for a in args[:-1])
        used = set(re.findall(r"\{#(\w+)\}", _text())) - {"AppGuid"}
        self.assertEqual(used | {"Flavour"}, set(defines))
        self.assertEqual(defines["AppVersion"], app_meta.VERSION)
        self.assertEqual(defines["Flavour"], build.FLAVOUR_BUILT)
        self.assertEqual(defines["OutputBase"], f"{build.STEM}-setup")
        self.assertEqual(defines["AppExeName"], f"{app_meta.NAME}.exe")

    def test_each_flavour_gets_its_own_folder_and_name(self):
        for f in flavour.FLAVOURS:
            with mock.patch.object(build, "FLAVOUR_BUILT", f):
                defines = dict(a[2:].split("=", 1) for a in build.iscc_args("x")[:-1])
            self.assertEqual(defines["AppDirName"], flavour.IDENTITY[f]["name"], f)
            self.assertEqual(defines["AppName"], flavour.IDENTITY[f]["display"], f)
        self.assertEqual(flavour.IDENTITY["complete"]["name"], "Prism")


class BuildStep(unittest.TestCase):

    def test_without_iscc_the_zip_stands_alone(self):
        with mock.patch.dict(os.environ, {"PRISM_ISCC": ""}), \
                mock.patch.object(build.shutil, "which", return_value=None), \
                mock.patch.object(build, "run") as run:
            self.assertEqual(build.build_windows_installer("x"), [])
        run.assert_not_called()

    def test_a_named_iscc_that_is_missing_fails_the_build(self):
        with mock.patch.dict(os.environ, {"PRISM_ISCC": os.path.join(ROOT, "no-such-iscc.exe")}):
            with self.assertRaises(SystemExit):
                build.build_windows_installer("x")

    def test_the_setup_exe_is_named_like_the_zip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            iscc = os.path.join(d, "ISCC.exe")
            open(iscc, "w").close()

            def fake_run(cmd, **_kw):
                self.assertEqual(cmd[0], iscc)
                with open(os.path.join(d, f"{build.STEM}-setup.exe"), "wb") as f:
                    f.write(b"x" * 10)

            env = {"PRISM_ISCC": iscc, "GITHUB_STEP_SUMMARY": os.path.join(d, "summary.md")}
            with mock.patch.dict(os.environ, env), mock.patch.object(build, "DIST", d), \
                    mock.patch.object(build, "run", side_effect=fake_run):
                made = build.build_windows_installer("x")
            self.assertEqual(made, [os.path.join(d, f"{build.STEM}-setup.exe")])
            self.assertTrue(os.path.basename(made[0]).startswith(
                f"{app_meta.NAME}-" if build.FLAVOUR_BUILT == "complete" else
                f"{app_meta.NAME}-{build.FLAVOUR_BUILT}-"))
            with open(env["GITHUB_STEP_SUMMARY"], encoding="utf-8") as f:
                self.assertIn("installer:", f.read())


class TheWorkflowBuildsAndChecksIt(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
            self.steps = yaml.safe_load(f)["jobs"]["build"]["steps"]

    def _step(self, name):
        return [s for s in self.steps if s.get("name") == name][0]

    def test_inno_setup_is_pinned_before_the_build(self):
        names = [s.get("name") for s in self.steps]
        pin = self._step("Pin Inno Setup (Windows)")
        self.assertEqual(pin["if"], "runner.os == 'Windows'")
        self.assertIn("$want = '6.7.1'", pin["run"])
        self.assertIn("--version=$want", pin["run"])
        self.assertIn("PRISM_ISCC=", pin["run"])
        self.assertLess(names.index("Pin Inno Setup (Windows)"), names.index("Build"))

    def test_the_installer_is_checked_after_the_smoke_test_and_uploaded_with_the_zip(self):
        names = [s.get("name") for s in self.steps]
        check = self._step("Install, self-test and uninstall the Windows installer")
        self.assertEqual(check["if"], "runner.os == 'Windows'")
        self.assertIn("packaging/windows/installer_check.py", check["run"])
        self.assertLess(names.index("Smoke-test the bundle"), names.index(check["name"]))
        upload = [s for s in self.steps if s.get("uses", "").startswith("actions/upload-artifact")
                  and "prism-" in str(s["with"]["name"])][0]
        paths = upload["with"]["path"].split()
        self.assertIn("dist/*-setup.exe", paths)
        self.assertIn("dist/*.zip", paths)

    def test_the_update_manifest_still_records_the_zip_not_the_setup(self):
        manifest = self._step("Generate the (unsigned) update manifest")["run"]
        self.assertIn("ARCHIVE=$(ls dist/*.tar.gz dist/*.zip dist/*.dmg", manifest)
        self.assertNotIn("setup", manifest)


class TheCheckScript(unittest.TestCase):

    def test_refuses_outside_a_windows_github_runner(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        p = subprocess.run([sys.executable, os.path.join(ROOT, "packaging", "windows",
                                                         "installer_check.py")],
                           env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("GitHub Actions runner only", p.stderr)

    def test_smoke_test_takes_the_installed_exe(self):
        import smoke_test
        missing = os.path.join(ROOT, "no-such-folder", "Prism.exe")
        with self.assertRaises(SystemExit) as e:
            smoke_test.main(missing)
        self.assertIn(missing, str(e.exception))


if __name__ == "__main__":
    unittest.main()

"""uninstall.py: the owner asked for an Uninstall button with two choices, the
program only, or everything. Deleting is the one thing here where a mistake
costs real data, so the rules are tested hard and the helper script is run for
real, on throwaway folders, to prove what disappears and what survives."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import channel  # noqa: E402
import uninstall as U  # noqa: E402


class Rooms(unittest.TestCase):
    """A fake machine: an install folder, a home with Prism's data, made files,
    and neighbours that must never be touched."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uninstall-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        self.home = os.path.join(t, "home", "someone")
        self.apps = os.path.join(t, "Apps")
        self.install = os.path.join(self.apps, "Prism")
        self.exe = os.path.join(self.install, "Prism")
        self.data = os.path.join(self.home, ".prism")
        self.artifacts = os.path.join(self.home, "Desktop", "Prism Artifacts")
        self.chosen = os.path.join(self.home, "Documents")            # a folder the person picked
        for d in (self.install, self.data, self.artifacts, self.chosen,
                  os.path.join(self.apps, "OtherApp"), os.path.join(self.home, "Pictures")):
            os.makedirs(d)
        for f in (self.exe, os.path.join(self.data, "config.json"), os.path.join(self.data, "license.json"),
                  os.path.join(self.artifacts, "deck.pptx"), os.path.join(self.chosen, "taxes.pdf"),
                  os.path.join(self.apps, "OtherApp", "other.exe"), os.path.join(self.home, "Pictures", "me.jpg")):
            open(f, "w").write("x")

    def plan(self, scope, **kw):
        return U.build_plan(scope, frozen=True, executable=self.exe, data_dir=self.data,
                            home=self.home, platform="darwin", **kw)

    def alive(self, *paths):
        return [os.path.exists(p) for p in paths]


class WhatMayBeRemoved(unittest.TestCase):
    def test_roots_homes_and_their_parents_are_refused(self):
        home = os.path.abspath(os.path.expanduser("~"))
        for bad in ("/", os.path.dirname(home), home, "/home", "relative/path", "", None):
            with self.subTest(path=bad):
                self.assertTrue(U.refuse_reason(bad), f"{bad!r} must be refused")

    def test_paths_unsafe_to_put_in_a_script_are_refused(self):
        for bad in ('/tmp/a"b/c', "/tmp/a\nb/c", "/tmp/a\0b/c"):
            self.assertTrue(U.refuse_reason(bad))

    def test_an_ordinary_folder_deep_enough_is_allowed(self):
        self.assertEqual("", U.refuse_reason("/tmp/some/Prism"))


class Planning(Rooms):
    def test_it_refuses_to_run_from_source(self):
        with self.assertRaises(U.Refused) as ctx:
            U.build_plan(U.SCOPE_APP, frozen=False)
        self.assertIn("source", str(ctx.exception))

    def test_the_program_only_never_lists_data_or_files(self):
        plan = self.plan(U.SCOPE_APP)
        self.assertEqual(plan.app_dir, self.install)
        self.assertEqual((plan.data_dirs, plan.output_dirs), ([], []))

    def test_everything_adds_prisms_own_data_and_nothing_made_for_the_person(self):
        plan = self.plan(U.SCOPE_ALL)
        self.assertEqual(plan.data_dirs, [self.data])
        self.assertEqual(plan.output_dirs, [], "made files stay unless asked for")

    def test_made_files_only_when_asked_and_only_folders_named_prism(self):
        plan = self.plan(U.SCOPE_ALL, include_outputs=True,
                         output_candidates=[self.artifacts, self.chosen])
        self.assertEqual(plan.output_dirs, [self.artifacts])
        skipped = dict(plan.skipped)
        self.assertIn(self.chosen, skipped)
        self.assertIn("Prism", skipped[self.chosen])

    def test_a_data_folder_that_is_not_prisms_is_refused(self):
        with self.assertRaises(U.Refused):
            U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, data_dir=self.chosen,
                         home=self.home, platform="darwin")

    def test_a_dev_build_removes_its_whole_data_folder(self):
        dev = os.path.join(self.home, channel.DEV_HOME_NAME)
        os.makedirs(os.path.join(dev, ".prism"))
        old = os.environ.get("PRISM_HOME_ISOLATED")
        os.environ["PRISM_HOME_ISOLATED"] = dev
        self.addCleanup(lambda: os.environ.pop("PRISM_HOME_ISOLATED", None) if old is None
                        else os.environ.__setitem__("PRISM_HOME_ISOLATED", old))
        plan = U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, home=self.home, platform="darwin")
        self.assertEqual(plan.data_dirs, [dev])

    def test_a_mac_app_bundle_is_removed_as_a_whole(self):
        bundle = os.path.join(self.apps, "Prism.app")
        macos = os.path.join(bundle, "Contents", "MacOS")
        os.makedirs(macos)
        exe = os.path.join(macos, "Prism")
        open(exe, "w").write("x")
        plan = U.build_plan(U.SCOPE_APP, frozen=True, executable=exe, home=self.home, platform="darwin")
        self.assertEqual(plan.app_dir, bundle)

    def test_the_linux_launcher_entries_are_found_and_listed(self):
        for folder, name in U.LINUX_LAUNCHER_FILES:
            path = os.path.join(folder.replace("~", self.home, 1), name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write("x")
        plan = U.build_plan(U.SCOPE_APP, frozen=True, executable=self.exe, home=self.home, platform="linux")
        self.assertEqual(len(plan.extra_files), len(U.LINUX_LAUNCHER_FILES))


class TheScripts(Rooms):
    def test_the_script_names_exactly_the_plan_and_nothing_else(self):
        plan = self.plan(U.SCOPE_ALL, include_outputs=True, output_candidates=[self.artifacts])
        text = U.posix_script(plan, 4242, "/tmp/log")
        rm_lines = [l for l in text.splitlines() if l.startswith("rm -rf")]
        self.assertEqual(len(rm_lines), 1)
        for path in (self.artifacts, self.data, self.install):
            self.assertIn(path, rm_lines[0])
        for keep in (self.chosen, self.home, self.apps, os.path.join(self.apps, "OtherApp")):
            self.assertNotIn(f" {keep} ", f" {rm_lines[0]} ")

    def test_paths_with_spaces_and_quotes_stay_one_argument(self):
        weird = os.path.join(self.tmp, "my Prism 'beta'")
        os.makedirs(weird)
        plan = U.Plan(U.SCOPE_APP, app_dir=weird)
        text = U.posix_script(plan, 1, "/tmp/log")
        self.assertEqual(subprocess.run(["/bin/sh", "-n", "-c", text.split("\n", 1)[1]]).returncode, 0)

    def test_the_windows_script_waits_retries_escapes_and_removes_itself(self):
        plan = U.Plan(U.SCOPE_ALL, app_dir=r"C:\Apps\Prism 100%", data_dirs=[r"C:\Users\a\.prism"])
        text = U.windows_script(plan, 777, r"C:\Temp\log.txt")
        self.assertIn('tasklist /FI "PID eq 777"', text)
        self.assertIn('rmdir /s /q "C:\\Apps\\Prism 100%%"', text, "% must be doubled in a batch file")
        self.assertIn('rmdir /s /q "C:\\Users\\a\\.prism"', text)
        self.assertIn("LSS 5", text, "removal is retried")
        self.assertIn('del "%~f0"', text)
        self.assertNotIn("\n", text.replace("\r\n", ""), "batch files need CRLF")


@unittest.skipIf(sys.platform == "win32", "runs the POSIX helper")
class ReallyRunningTheHelper(Rooms):
    def run_helper(self, plan):
        folder = os.path.join(self.tmp, "scripts")
        os.makedirs(folder)
        started = []
        # pid 2**22+7 is not a live process, so the helper does not wait.
        script = U.start(plan, pid=4194311, script_dir=folder, runner=lambda argv, **kw: started.append(argv))
        subprocess.run(started[0], check=True, timeout=30)
        return script, os.path.join(folder, "prism-uninstall.log")

    def test_the_program_only_removes_the_program_and_nothing_else(self):
        script, log = self.run_helper(self.plan(U.SCOPE_APP))
        self.assertEqual(self.alive(self.install, self.data, self.artifacts, self.chosen,
                                    os.path.join(self.apps, "OtherApp"), self.home), [False, True, True, True, True, True])
        self.assertFalse(os.path.exists(script), "the helper removes itself")
        self.assertTrue(os.path.exists(log))

    def test_everything_removes_program_and_data_but_not_made_files_or_neighbours(self):
        self.run_helper(self.plan(U.SCOPE_ALL))
        self.assertEqual(self.alive(self.install, self.data, self.artifacts, self.chosen,
                                    os.path.join(self.apps, "OtherApp"), os.path.join(self.home, "Pictures")),
                         [False, False, True, True, True, True])

    def test_everything_and_made_files_removes_prisms_folders_but_never_a_folder_the_person_chose(self):
        plan = self.plan(U.SCOPE_ALL, include_outputs=True, output_candidates=[self.artifacts, self.chosen])
        self.run_helper(plan)
        self.assertEqual(self.alive(self.install, self.data, self.artifacts, self.chosen,
                                    os.path.join(self.chosen, "taxes.pdf")), [False, False, False, True, True])

    def test_start_refuses_a_plan_that_names_a_dangerous_folder(self):
        for bad in (U.Plan(U.SCOPE_APP, app_dir=os.path.dirname(os.path.abspath(os.path.expanduser('~')))),
                    U.Plan(U.SCOPE_APP, app_dir=self.install, data_dirs=["/"])):
            with self.assertRaises(U.Refused):
                U.start(bad, pid=1, script_dir=self.tmp, runner=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()

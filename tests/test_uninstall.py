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

    def test_uninstall_prism_is_the_program_only_even_when_prisms_folders_exist(self):
        plan = self.plan(U.SCOPE_APP, output_candidates=[self.artifacts])
        self.assertEqual(plan.app_dir, self.install)
        self.assertEqual((plan.data_dirs, plan.output_dirs), ([], []))

    def test_everything_is_the_program_the_data_with_logs_and_the_folders_prism_created(self):
        os.makedirs(os.path.join(self.data, "logs"))
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts])
        self.assertEqual(plan.data_dirs, [self.data], "logs live inside the data folder")
        self.assertEqual(plan.output_dirs, [self.artifacts])

    def test_only_folders_prism_created_go_never_one_the_person_chose(self):
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts, self.chosen])
        self.assertEqual(plan.output_dirs, [self.artifacts])
        skipped = dict(plan.skipped)
        self.assertIn(self.chosen, skipped)
        self.assertIn("Prism", skipped[self.chosen])

    def test_the_teams_shared_workspace_is_never_removed_even_if_named_prism(self):
        shared = os.path.join(self.home, "Prism Team")
        os.makedirs(shared)
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts, shared], protect=[shared])
        self.assertNotIn(shared, plan.output_dirs)
        self.assertIn("shared workspace", dict(plan.skipped)[shared])

    def test_a_folder_inside_the_data_folder_is_not_listed_twice(self):
        inside = os.path.join(self.data, "Prism Inner")
        os.makedirs(inside)
        plan = self.plan(U.SCOPE_ALL, output_candidates=[inside])
        self.assertEqual(plan.output_dirs, [])

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


class TheListOfPrismsFolders(unittest.TestCase):
    """prism_folders() is the one list of places Prism writes made files."""

    def test_settings_choices_and_usual_places_are_all_listed_and_the_workspace_protected(self):
        import types
        from unittest import mock
        engine = types.SimpleNamespace(ARTIFACTS_DIR="/x/Desktop/Prism Artifacts", FALLBACK_ARTIFACTS_DIR="/x/Prism Artifacts")
        cfg = {"gerber_out_dir": "/work/Prism Gerber 2026", "email": {"folder": "/mail/Prism Email"},
               "inquiry": {"folder": "/inq/Prism Inquiries"}, "workspace_root": "/shared/Prism Team"}
        with mock.patch.dict(os.environ, {"PRISM_REAL_HOME": "/x"}):
            found, protected = U.prism_folders(cfg, engine)
        for expected in ("/x/Desktop/Prism Artifacts", "/x/Prism Artifacts", "/work/Prism Gerber 2026",
                         "/x/Desktop/Prism Gerber", "/x/Desktop/Prism Step", "/mail/Prism Email", "/x/Prism Email",
                         "/inq/Prism Inquiries", "/x/Prism Inquiries", "/x/Documents/Prism Leads"):
            self.assertIn(os.path.abspath(expected), found, expected)
        self.assertEqual(len(found), len(set(found)), "no duplicates")
        self.assertEqual(protected, [os.path.abspath("/shared/Prism Team")])


class TheProgramFolderMustBePrismsAlone(Rooms):
    """Found in review (2026-10-28): "the folder holding the executable" could be the Desktop, if
    someone copied Prism's files straight onto it. Then Uninstall would have deleted the Desktop."""

    def test_a_folder_shared_with_the_persons_files_is_refused_and_says_what_to_delete(self):
        open(os.path.join(self.install, "taxes.pdf"), "w").write("x")
        os.makedirs(os.path.join(self.install, "_internal"))
        with self.assertRaises(U.Refused) as ctx:
            self.plan(U.SCOPE_APP)
        message = str(ctx.exception)
        self.assertIn("taxes.pdf", message)
        self.assertIn("_internal", message)

    def test_a_real_program_folder_is_accepted_with_its_linux_extras(self):
        os.makedirs(os.path.join(self.install, "_internal"))
        for name in ("install.sh", "in.alphakore.prism.desktop", "in.alphakore.prism.png", ".prism_update_pending"):
            open(os.path.join(self.install, name), "w").write("x")
        self.assertEqual(self.plan(U.SCOPE_APP).app_dir, self.install)

    def test_the_updaters_leftovers_beside_the_program_are_included(self):
        old = self.install + ".old"
        staging = os.path.join(self.apps, ".prism-update-staging")
        marker = self.install + ".prism_update_pending"
        os.makedirs(old); os.makedirs(staging); open(marker, "w").write("1.6.13")
        plan = self.plan(U.SCOPE_APP)
        self.assertEqual(sorted(plan.leftovers), sorted([old, staging]))
        self.assertIn(marker, plan.extra_files)

    def test_the_helper_never_runs_from_inside_the_program_folder(self):
        seen = {}
        U.start(self.plan(U.SCOPE_APP), pid=1, script_dir=os.path.join(self.tmp),
                runner=lambda argv, **kw: seen.update(kw))
        self.assertEqual(seen["cwd"], self.tmp)
        self.assertFalse(seen["cwd"].startswith(self.install))


class TheScripts(Rooms):
    def test_the_script_names_exactly_the_plan_and_nothing_else(self):
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts])
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

    def test_the_windows_script_deletes_leftover_files_too(self):
        plan = U.Plan(U.SCOPE_APP, app_dir=r"C:\Apps\Prism", leftovers=[r"C:\Apps\Prism.old"],
                      extra_files=[r"C:\Apps\Prism.prism_update_pending"])
        text = U.windows_script(plan, 7, r"C:\Temp\log.txt")
        self.assertIn('rmdir /s /q "C:\\Apps\\Prism.old"', text)
        self.assertIn('del /f /q "C:\\Apps\\Prism.prism_update_pending"', text)

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

    def test_everything_removes_prisms_things_and_nothing_else(self):
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts, self.chosen])
        self.run_helper(plan)
        self.assertEqual(self.alive(self.install, self.data, self.artifacts,
                                    self.chosen, os.path.join(self.chosen, "taxes.pdf"),
                                    os.path.join(self.apps, "OtherApp"), os.path.join(self.home, "Pictures")),
                         [False, False, False, True, True, True, True])

    def test_the_updaters_leftovers_are_really_removed_and_neighbours_survive(self):
        old = self.install + ".old"
        staging = os.path.join(self.apps, ".prism-update-staging")
        os.makedirs(old); os.makedirs(staging)
        self.run_helper(self.plan(U.SCOPE_APP))
        self.assertEqual(self.alive(self.install, old, staging, os.path.join(self.apps, "OtherApp"), self.data),
                         [False, False, False, True, True])

    def test_start_refuses_a_plan_that_names_a_dangerous_folder(self):
        for bad in (U.Plan(U.SCOPE_APP, app_dir=os.path.dirname(os.path.abspath(os.path.expanduser('~')))),
                    U.Plan(U.SCOPE_APP, app_dir=self.install, data_dirs=["/"])):
            with self.assertRaises(U.Refused):
                U.start(bad, pid=1, script_dir=self.tmp, runner=lambda *a, **k: None)


if __name__ == "__main__":
    unittest.main()

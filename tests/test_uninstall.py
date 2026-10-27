"""uninstall.py: the owner asked for an Uninstall button with two choices, the
program only, or everything. Deleting is the one thing here where a mistake
costs real data, so the rules are tested hard and the helper script is run for
real, on throwaway folders, to prove what disappears and what survives."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import channel  # noqa: E402
import uninstall as U  # noqa: E402
from licensing import secretstore  # noqa: E402

#: Every forget_key() the code under test makes. An "everything" plan removes the
#: licence key from the credential store; a test must never remove the real one.
FORGOTTEN = []
_keyring_guard = None


def setUpModule():
    global _keyring_guard
    from unittest import mock
    _keyring_guard = mock.patch.object(secretstore, "forget_key", lambda: FORGOTTEN.append(1))
    _keyring_guard.start()


def tearDownModule():
    _keyring_guard.stop()


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
    """prism_folders(): Prism's own folders, the person's choices, and the workspace."""

    def folders(self, cfg, engine):
        from unittest import mock
        with mock.patch.dict(os.environ, {"PRISM_REAL_HOME": "/x"}):
            return U.prism_folders(cfg, engine)

    def test_prisms_own_places_and_the_persons_choices_are_kept_apart(self):
        import types
        engine = types.SimpleNamespace(ARTIFACTS_DIR="/x/Desktop/Prism Artifacts", FALLBACK_ARTIFACTS_DIR="/x/Prism Artifacts")
        cfg = {"gerber_out_dir": "/work/Prism Gerber 2026", "email": {"folder": "/mail/Prism Email"},
               "inquiry": {"folder": "/inq/Prism Inquiries"}, "workspace_root": " /shared/Prism Team "}
        own, chosen, protected = self.folders(cfg, engine)
        for expected in ("/x/Desktop/Prism Artifacts", "/x/Prism Artifacts", "/x/Desktop/Prism Gerber",
                         "/x/Desktop/Prism Step", "/x/Prism Email", "/x/Prism Inquiries", "/x/Documents/Prism Leads"):
            self.assertIn(os.path.abspath(expected), own, expected)
        self.assertEqual(sorted(chosen), sorted(os.path.abspath(p) for p in
                                                ("/work/Prism Gerber 2026", "/mail/Prism Email", "/inq/Prism Inquiries")))
        self.assertEqual(len(own), len(set(own)), "no duplicates")
        self.assertEqual(protected, [os.path.abspath("/shared/Prism Team")], "spaces around the setting ignored")

    def test_a_choice_that_is_the_usual_place_counts_as_prisms_own(self):
        import types
        engine = types.SimpleNamespace(ARTIFACTS_DIR="/x/Desktop/Prism Artifacts", FALLBACK_ARTIFACTS_DIR="")
        own, chosen, _ = self.folders({"email": {"folder": "/x/Prism Email"}}, engine)
        self.assertIn(os.path.abspath("/x/Prism Email"), own)
        self.assertEqual(chosen, [])

    def test_after_a_choice_the_engines_own_folder_is_still_prisms_and_the_choice_is_the_persons(self):
        import types
        engine = types.SimpleNamespace(ARTIFACTS_DIR="/mine/Prism Photos", FALLBACK_ARTIFACTS_DIR="",
                                       PRISM_DEFAULT_ARTIFACTS_DIR="/x/OneDrive/Desktop/Prism Artifacts")
        own, chosen, _ = self.folders({"artifacts_dir": "/mine/Prism Photos"}, engine)
        self.assertIn(os.path.abspath("/x/OneDrive/Desktop/Prism Artifacts"), own)
        self.assertNotIn(os.path.abspath("/mine/Prism Photos"), own)
        self.assertIn(os.path.abspath("/mine/Prism Photos"), chosen)


class WhatEverythingNeverTakes(Rooms):
    """Found in review (2026-10-28). "Everything" means what Prism stored, and only that."""

    def test_a_folder_the_person_chose_is_never_removed_even_when_named_prism(self):
        photos = os.path.join(self.home, "Prism Photos")
        os.makedirs(photos)
        open(os.path.join(photos, "wedding.jpg"), "w").write("x")
        plan = self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts], chosen=[photos])
        self.assertEqual(plan.output_dirs, [self.artifacts])
        self.assertIn("you chose this folder", dict(plan.skipped)[photos])

    def test_the_workspace_is_recognised_through_a_link(self):
        shared = os.path.join(self.home, "Prism Team")
        os.makedirs(shared)
        link = os.path.join(self.home, "Prism Team link")
        os.symlink(shared, link, target_is_directory=True)
        plan = self.plan(U.SCOPE_ALL, output_candidates=[link], protect=[shared])
        self.assertEqual(plan.output_dirs, [])
        self.assertIn("shared workspace", dict(plan.skipped)[link])

    def test_a_workspace_inside_the_data_folder_stops_everything(self):
        inside = os.path.join(self.data, "workspace")
        os.makedirs(inside)
        with self.assertRaises(U.Refused) as ctx:
            self.plan(U.SCOPE_ALL, protect=[inside])
        self.assertIn("shared workspace", str(ctx.exception))

    def test_a_prism_folder_holding_the_data_folder_is_reported_not_silently_dropped(self):
        holder = os.path.join(self.tmp, "home", "Prism Everything")
        data = os.path.join(holder, ".prism")
        os.makedirs(data)
        plan = U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, data_dir=data, home=self.home,
                            platform="darwin", output_candidates=[holder])
        self.assertIn("data folder", dict(plan.skipped)[holder])

    def test_the_saved_licence_key_is_removed_only_by_everything_and_only_once_the_helper_runs(self):
        everything = self.plan(U.SCOPE_ALL)
        self.assertTrue(everything.forget_licence)
        self.assertIn("credential store", " ".join(what for what, _ in U.describe(everything)))
        self.assertFalse(self.plan(U.SCOPE_APP).forget_licence)
        calls = []

        def broken_runner(*a, **k):
            raise OSError("cannot start")
        with self.assertRaises(OSError):
            U.start(everything, pid=1, script_dir=self.tmp, runner=broken_runner, forget=lambda: calls.append(1))
        self.assertEqual(calls, [], "if the helper never started, Prism stays and keeps its key")
        U.start(everything, pid=1, script_dir=self.tmp, runner=lambda *a, **k: None, forget=lambda: calls.append(1))
        self.assertEqual(calls, [1])


class ADevelopmentBuild(Rooms):
    """A dev build's "~" is its own data folder (channel.py). Found in review: that made
    "everything" refuse ("that is the user's home folder"), and once fixed it would have
    removed the normal Prism's folders and saved key, which this build shares."""

    def setUp(self):
        super().setUp()
        self.dev = os.path.join(self.home, channel.DEV_HOME_NAME)
        os.makedirs(os.path.join(self.dev, ".prism"))
        channel._install_hook(self.dev)
        self.addCleanup(channel.remove_hook)
        from unittest import mock
        patcher = mock.patch.dict(os.environ, {"PRISM_HOME_ISOLATED": self.dev})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_everything_removes_the_dev_data_folder_with_the_hook_installed(self):
        self.assertEqual(os.path.expanduser("~"), self.dev, "the real dev-build hook is in place")
        plan = U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, home=self.home, platform="darwin")
        self.assertEqual(plan.data_dirs, [self.dev])

    def test_it_leaves_the_shared_folders_and_the_saved_key_to_the_normal_prism(self):
        plan = U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, home=self.home, platform="darwin",
                            output_candidates=[self.artifacts])
        self.assertEqual(plan.output_dirs, [])
        self.assertIn("development build", dict(plan.skipped)[self.artifacts])
        self.assertFalse(plan.forget_licence)


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

    @unittest.skipIf(sys.platform == "win32", "checks the POSIX helper with /bin/sh")
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
        self.assertIn('tasklist.exe /FI "PID eq 777"', text)
        self.assertEqual(text.split("\r\n")[1], "chcp 65001 >nul", "a non-English user name must survive")
        for tool in ("tasklist", "find", "ping"):
            self.assertNotIn(f" {tool} ", f" {text} ", f"{tool} must be called by its full Windows path")
        self.assertIn('rmdir /s /q "C:\\Apps\\Prism 100%%"', text, "% must be doubled in a batch file")
        self.assertIn('rmdir /s /q "C:\\Users\\a\\.prism"', text)
        self.assertIn("LSS 5", text, "removal is retried")
        self.assertIn('del "%~f0"', text)
        self.assertNotIn("\n", text.replace("\r\n", ""), "batch files need CRLF")
        lines = text.split("\r\n")
        give_up = lines.index("if not errorlevel 1 goto stillrunning")
        self.assertLess(give_up, min(i for i, l in enumerate(lines) if "rmdir" in l),
                        "the still-running check comes before any removal")


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

    def test_nothing_is_removed_while_prism_is_still_running(self):
        folder = os.path.join(self.tmp, "scripts")
        os.makedirs(folder)
        started = []
        prism = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(prism.kill)
        U.start(self.plan(U.SCOPE_ALL, output_candidates=[self.artifacts]), pid=prism.pid, script_dir=folder,
                wait=1, runner=lambda argv, **kw: started.append(argv), forget=lambda: None)
        subprocess.run(started[0], timeout=30)
        self.assertEqual(self.alive(self.install, self.data, self.artifacts), [True, True, True])
        with open(os.path.join(folder, "prism-uninstall.log")) as f:
            self.assertIn("still running", f.read())

    def test_start_refuses_a_plan_that_names_a_dangerous_folder(self):
        for bad in (U.Plan(U.SCOPE_APP, app_dir=os.path.dirname(os.path.abspath(os.path.expanduser('~')))),
                    U.Plan(U.SCOPE_APP, app_dir=self.install, data_dirs=["/"])):
            with self.assertRaises(U.Refused):
                U.start(bad, pid=1, script_dir=self.tmp, runner=lambda *a, **k: None)


@unittest.skipUnless(sys.platform == "win32", "runs the real Windows helper")
class ReallyRunningTheWindowsHelper(unittest.TestCase):
    """ISS-016: the batch file had only ever been read, never run. This runs it
    the way the app does (start() with its real flags), on throwaway folders
    whose names carry a space, a % and a non-English letter, while a stand-in
    for Prism is still running, so the wait is real too."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uninstall-win-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        t = self.tmp
        self.home = os.path.join(t, "Users", "Jos\u00e9")
        self.install = os.path.join(t, "Apps", "Prism 100% \u00e9t\u00e9")
        self.exe = os.path.join(self.install, "Prism.exe")
        self.data = os.path.join(self.home, ".prism")
        self.artifacts = os.path.join(self.home, "Desktop", "Prism Artifacts")
        self.chosen = os.path.join(self.home, "Documents")
        self.neighbour = os.path.join(t, "Apps", "OtherApp")
        for d in (os.path.join(self.install, "_internal"), self.data, self.artifacts, self.chosen, self.neighbour):
            os.makedirs(d)
        for f in (self.exe, os.path.join(self.install, "_internal", "python312.dll"),
                  os.path.join(self.data, "config.json"), os.path.join(self.artifacts, "deck.pptx"),
                  os.path.join(self.chosen, "taxes.pdf"), os.path.join(self.neighbour, "other.exe")):
            open(f, "w").write("x")

    def run_for_real(self, scope, **kw):
        plan = U.build_plan(scope, frozen=True, executable=self.exe, data_dir=self.data,
                            home=self.home, platform="win32", **kw)
        scripts = os.path.join(self.tmp, "scripts")
        os.makedirs(scripts)
        prism = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(4)"])
        self.addCleanup(prism.kill)
        script = U.start(plan, pid=prism.pid, script_dir=scripts, forget=lambda: None)
        log = os.path.join(scripts, "prism-uninstall.log")
        time.sleep(2)                                   # the helper is up and polling by now
        self.assertTrue(prism.poll() is None and os.path.isdir(self.install),
                        "nothing may go while Prism is still running")
        prism.wait(timeout=30)
        for _ in range(240):
            if os.path.exists(log) and not os.path.exists(script):
                break
            time.sleep(0.5)
        self.assertTrue(os.path.exists(log), "the helper finished and wrote its log")
        self.assertFalse(os.path.exists(script), "the helper removed itself")

    def test_prism_only_removes_the_program_and_nothing_else(self):
        self.run_for_real(U.SCOPE_APP)
        self.assertEqual([os.path.exists(p) for p in (self.install, self.data, self.artifacts,
                                                       self.chosen, self.neighbour)],
                         [False, True, True, True, True])

    def test_nothing_is_removed_if_prism_is_still_running_when_the_wait_ends(self):
        plan = U.build_plan(U.SCOPE_ALL, frozen=True, executable=self.exe, data_dir=self.data,
                            home=self.home, platform="win32", output_candidates=[self.artifacts])
        scripts = os.path.join(self.tmp, "scripts")
        os.makedirs(scripts)
        prism = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(prism.kill)
        script = U.start(plan, pid=prism.pid, script_dir=scripts, wait=2, forget=lambda: None)
        log = os.path.join(scripts, "prism-uninstall.log")
        for _ in range(120):
            if os.path.exists(log) and not os.path.exists(script):
                break
            time.sleep(0.5)
        with open(log, encoding="utf-8", errors="replace") as f:
            self.assertIn("still running", f.read())
        self.assertEqual([os.path.exists(p) for p in (self.install, self.data, self.artifacts)], [True, True, True])

    def test_everything_removes_prisms_things_and_spares_the_rest(self):
        self.run_for_real(U.SCOPE_ALL, output_candidates=[self.artifacts, self.chosen])
        self.assertEqual([os.path.exists(p) for p in (self.install, self.data, self.artifacts,
                                                       os.path.join(self.chosen, "taxes.pdf"), self.neighbour)],
                         [False, False, False, True, True])


if __name__ == "__main__":
    unittest.main()

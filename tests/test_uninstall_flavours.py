"""What Settings > Uninstall of one flavour removes while others are installed.

A PROBE, NOT A RULE (2026-11-25). It records, by running the real plan and the
real helper script on a throwaway home, what happens today, including what the
owner may not want: "everything" from one flavour takes the data the other
flavours use. Nothing was changed. When the owner decides what should happen,
change uninstall.py and the assertions marked FINDING together.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flavour  # noqa: E402
import uninstall as U  # noqa: E402

REMOVED = "studio"


class OneOfFourIsRemoved(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="uninstall-flavours-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home", "someone")
        self.programs = os.path.join(self.tmp, "Local", "Programs")
        self.install = {f: os.path.join(self.programs, i["name"])
                        for f, i in flavour.IDENTITY.items()}
        for f, d in self.install.items():
            self.put(os.path.join(d, "Prism.exe"))
            self.put(os.path.join(d, "_internal", "x.dll"))
            self.put(os.path.join(d + "-uninstall", "unins000.exe"))        # prism.iss
        # an update each flavour has downloaded and left waiting for a restart
        self.staging = os.path.join(self.programs, ".prism-update-staging")
        for f in flavour.FLAVOURS:
            self.put(os.path.join(self.staging, "2.0.0" + flavour.file_suffix(f), "Prism.exe"))
        self.data = os.path.join(self.home, ".prism")
        for rel in ("license.json", "config.json", "device_id", "runs/boq-run.json",
                    "chrome_profile/Cookies",
                    *(f"update_state{flavour.file_suffix(f)}.json" for f in flavour.FLAVOURS)):
            self.put(os.path.join(self.data, *rel.split("/")))
        self.made = {"Desktop/Prism Artifacts": "studio", "Desktop/Prism Step": "engineering",
                     "Desktop/Prism Gerber": "engineering", "Prism Email": "sales",
                     "Prism Inquiries": "sales", "Documents/Prism Leads": "sales"}
        for rel in self.made:
            self.put(os.path.join(self.home, *rel.split("/"), "work.pdf"))
        self.put(os.path.join(self.home, "Documents", "taxes.pdf"))
        self.forgotten: list[int] = []

    def put(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("x")

    def plan(self, scope: str, platform: str = "win32") -> U.Plan:
        with mock.patch.dict(os.environ, {"PRISM_REAL_HOME": self.home}):
            own, chosen, protect = U.prism_folders({})
            return U.build_plan(scope, frozen=True, data_dir=self.data, home=self.home,
                                executable=os.path.join(self.install[REMOVED], "Prism.exe"),
                                platform=platform, output_candidates=own, chosen=chosen,
                                protect=protect)

    def remove(self, scope: str) -> U.Plan:
        """Run the real helper (POSIX) for a Prism that has already exited."""
        plan = self.plan(scope)
        for path in plan.everything():          # never outside the throwaway folder
            self.assertTrue(path.startswith(self.tmp + os.sep), path)
        gone = subprocess.Popen([sys.executable, "-c", ""])
        gone.wait()
        started = []
        U.start(plan, pid=gone.pid, script_dir=self.tmp, forget=lambda: self.forgotten.append(1),
                runner=lambda argv, **kw: started.append(argv))
        subprocess.run(started[0], check=True, timeout=60)
        return plan

    def others(self) -> list[str]:
        return [f for f in flavour.FLAVOURS if f != REMOVED]

    def test_app_scope_plan(self):
        plan = self.plan(U.SCOPE_APP)
        self.assertEqual(plan.app_dir, self.install[REMOVED])
        self.assertEqual((plan.data_dirs, plan.output_dirs, plan.forget_licence), ([], [], False))
        # FINDING: the staging folder is shared, so the others' waiting updates go too.
        self.assertEqual(plan.leftovers, [self.staging])

    def test_all_scope_plan(self):
        plan = self.plan(U.SCOPE_ALL)
        self.assertEqual(plan.app_dir, self.install[REMOVED])
        # FINDING: all of this is shared with the flavours that stay.
        self.assertEqual(plan.data_dirs, [self.data])
        self.assertTrue(plan.forget_licence)
        self.assertEqual({os.path.relpath(d, self.home).replace(os.sep, "/")
                          for d in plan.output_dirs}, set(self.made))
        self.assertEqual(plan.leftovers, [self.staging])
        # FINDING: nothing the person is shown names the other installed apps.
        told = " ".join(what for what, _path in U.describe(plan)) \
            + " ".join(why for _path, why in plan.skipped)
        for f in self.others():
            if f != "complete":                    # its name is just "Prism"
                self.assertNotIn(flavour.IDENTITY[f]["display"], told)

    def test_neither_scope_knows_the_windows_installer(self):
        """FINDING: after Setup, Settings > Uninstall removes the program folder
        but not the Start-menu shortcut, the "Installed apps" entry or the
        uninstaller beside it."""
        for scope in (U.SCOPE_APP, U.SCOPE_ALL):
            self.assertNotIn(self.install[REMOVED] + "-uninstall", self.plan(scope).everything())

    @unittest.skipIf(sys.platform == "win32", "runs the POSIX helper; the Windows one is ISS-016")
    def test_app_scope_really_leaves_the_others_and_all_data(self):
        self.remove(U.SCOPE_APP)
        self.assertFalse(os.path.exists(self.install[REMOVED]))
        for f in self.others():
            self.assertTrue(os.path.isfile(os.path.join(self.install[f], "Prism.exe")), f)
        self.assertTrue(os.path.isfile(os.path.join(self.data, "license.json")))
        for rel in self.made:
            self.assertTrue(os.path.isfile(os.path.join(self.home, *rel.split("/"), "work.pdf")), rel)
        self.assertEqual(self.forgotten, [])
        self.assertFalse(os.path.exists(self.staging))                    # FINDING (above)

    @unittest.skipIf(sys.platform == "win32", "runs the POSIX helper; the Windows one is ISS-016")
    def test_all_scope_really_takes_the_data_the_others_use(self):
        self.remove(U.SCOPE_ALL)
        self.assertFalse(os.path.exists(self.install[REMOVED]))
        for f in self.others():                    # their programs stay ...
            self.assertTrue(os.path.isfile(os.path.join(self.install[f], "Prism.exe")), f)
        # FINDING: ... without their licence, settings, history, browser logins,
        # or the files Sales and Engineering made, although Studio was removed.
        self.assertFalse(os.path.exists(self.data))
        self.assertEqual(self.forgotten, [1])
        for rel in self.made:
            self.assertFalse(os.path.exists(os.path.join(self.home, *rel.split("/"))), rel)
        self.assertTrue(os.path.isfile(os.path.join(self.home, "Documents", "taxes.pdf")))


if __name__ == "__main__":
    unittest.main()

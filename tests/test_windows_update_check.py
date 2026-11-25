"""packaging/windows/update_check.py does what it says, per flavour.

In the Windows build job it updates a really installed Prism. Here it updates a
small stand-in program folder with the same code paths (real processes, real
HTTP, real swap), so a mistake in the check itself shows before CI. What only
the Windows job proves: the installed .exe, its baked flavour, apply.bat.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging", "windows"))

import flavour  # noqa: E402
import update_check  # noqa: E402

# What main.py does around an update: the swap helper, then the first start.
APP = """#!/bin/sh
exec "{python}" -B - "$@" <<'PY'
import os, sys
sys.path.insert(0, {root!r})
import apply_update
exe = {exe!r}
if sys.argv[1:2] == ["--prism-apply-update"]:
    pid, install, staged, backup = sys.argv[2:6]
    sys.exit(apply_update.perform_apply_and_relaunch(int(pid), install, staged, backup, [exe]))
install = os.path.dirname(exe)
apply_update.check_and_rollback_if_pending(install, install + ".old")
PY
"""


@unittest.skipIf(sys.platform == "win32",
                 "the stand-in app is a /bin/sh script; the Windows build job runs "
                 "update_check.py against the installed Prism.exe")
class TheCheckUpdatesAStandInOfEachFlavour(unittest.TestCase):

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="prism-update-check-")
        self.addCleanup(shutil.rmtree, self.work, True)

    def install(self, name: str) -> tuple[str, str]:
        d = os.path.join(self.work, "Programs", flavour.identity(name)["name"])
        os.makedirs(os.path.join(d, "_internal"))
        exe = os.path.join(d, "Prism")
        with open(exe, "w") as f:
            f.write(APP.format(python=sys.executable, root=ROOT, exe=exe))
        os.chmod(exe, 0o755)
        for rel, text in (("style.qss", "QWidget {}\n"), ("same.dat", "unchanged\n")):
            with open(os.path.join(d, "_internal", rel), "w") as f:
                f.write(text)
        return d, exe

    def run_check(self, name: str, install: str, exe: str) -> tuple[list[str], str]:
        work = os.path.join(self.work, f"work-{name}")
        home = os.path.join(self.work, "home")           # shared, as flavours share it
        os.makedirs(work)
        os.makedirs(home, exist_ok=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith("PRISM_")}
        env.update(HOME=home, USERPROFILE=home, PYTHONDONTWRITEBYTECODE="1")
        asked = update_check.run(install, exe, flavour_name=name, work=work,
                                 frozen=False, env=env)
        return asked, home

    def test_every_flavour_updates_itself_and_leaves_the_others_alone(self):
        installs = {name: self.install(name) for name in flavour.FLAVOURS}
        untouched = {}
        for name, (d, exe) in installs.items():
            asked, home = self.run_check(name, d, exe)
            channel = asked[0].split("manifest.")[1].split(".signed")[0]
            self.assertTrue(channel.endswith("" if name == "complete" else f"-{name}"), channel)
            self.assertTrue(os.path.isfile(os.path.join(d, "_internal", "added-by-an-update.txt")))
            self.assertTrue(os.path.isfile(os.path.join(
                home, ".prism", f"update_state{flavour.file_suffix(name)}.json")))
            self.assertFalse(os.path.exists(d + ".old"))
            untouched[name] = os.path.getmtime(os.path.join(d, "_internal", "style.qss"))
            for done, stamp in untouched.items():
                self.assertEqual(os.path.getmtime(os.path.join(
                    installs[done][0], "_internal", "style.qss")), stamp, (name, done))

    def test_it_fails_when_nothing_is_swapped_in(self):
        d, exe = self.install("sales")
        with open(exe, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")               # a helper that does nothing
        real, update_check._wait_until = update_check._wait_until, lambda done, _s: done()
        self.addCleanup(setattr, update_check, "_wait_until", real)
        with self.assertRaisesRegex(SystemExit, "not swapped in"):
            self.run_check("sales", d, exe)


class NothingShippedCanBePointedAtIt(unittest.TestCase):

    def test_the_override_exists_only_in_the_test_process(self):
        """The check patches the key and the host in its own process. The app
        has no way to be told either (the owner's rule)."""
        for rel in ("updater.py", "update_manifest.py", "apply_update.py", "flavour.py",
                    os.path.join("licensing", "keys.py")):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertNotIn("127.0.0.1:", text, rel)
            self.assertNotIn("update_check", text, rel)

    def test_it_is_not_bundled(self):
        with open(os.path.join(ROOT, "packaging", "prism.spec"), encoding="utf-8") as f:
            self.assertNotIn("update_check", f.read())


if __name__ == "__main__":
    unittest.main()

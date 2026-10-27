"""channel.isolate_home — a dev build, or a source run asked for it, must never
share a data folder with the developer's real ~/.prism, AND must leave the
operating system's idea of the user's folders alone.

The second half is the lesson of RELEASE_ISSUES.md ISS-009: setting HOME and
USERPROFILE (what this module used to do) also moved Windows' Downloads,
Documents and Desktop for the whole process, so file pickers on dev builds lost
them. The hook now replaces Python's expanduser only.

Most tests use a private dict and the pure helper, so nothing global changes.
The ones that install the hook run in a child process."""
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import channel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class IsolateHomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.real = os.path.join(self.tmp.name, "real")
        os.makedirs(self.real)

    def env(self, **extra):
        return {"HOME": self.real, "USERPROFILE": self.real, **extra}

    def test_prod_source_run_without_prism_home_changes_nothing(self):
        env = self.env()
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertEqual(channel.isolate_home(env), "")
        self.assertNotIn("PRISM_HOME_ISOLATED", env)

    def test_prism_home_redirects_a_source_run(self):
        target = os.path.join(self.tmp.name, "sandbox")
        env = self.env(PRISM_HOME=target)
        with mock.patch.object(channel, "CHANNEL", "prod"), \
             mock.patch.object(channel, "_frozen", return_value=False):
            self.assertEqual(channel.isolate_home(env), target)
        self.assertEqual(env["PRISM_HOME_ISOLATED"], target)
        self.assertTrue(os.path.isdir(target))

    def test_the_environment_the_system_reads_is_never_changed(self):
        # ISS-009: HOME and USERPROFILE stay what they were, for every kind of run.
        for chan, frozen, extra in (("dev", True, {}), ("dev", False, {}),
                                    ("prod", False, {"PRISM_HOME": os.path.join(self.tmp.name, "s")})):
            with self.subTest(channel=chan, frozen=frozen, extra=bool(extra)):
                env = self.env(**extra)
                with mock.patch.object(channel, "CHANNEL", chan), \
                     mock.patch.object(channel, "_frozen", return_value=frozen):
                    channel.isolate_home(env)
                self.assertEqual(env["HOME"], self.real)
                self.assertEqual(env["USERPROFILE"], self.real)

    def test_frozen_prod_build_ignores_prism_home(self):
        target = os.path.join(self.tmp.name, "sandbox")
        env = self.env(PRISM_HOME=target)
        with mock.patch.object(channel, "CHANNEL", "prod"), \
             mock.patch.object(channel, "_frozen", return_value=True):
            self.assertEqual(channel.isolate_home(env), "")
        self.assertFalse(os.path.exists(target))

    def test_dev_build_gets_its_own_data_folder_by_default(self):
        env = self.env()
        with mock.patch.object(channel, "CHANNEL", "dev"):
            got = channel.isolate_home(env)
        self.assertEqual(got, os.path.join(self.real, channel.DEV_HOME_NAME))
        self.assertEqual(env["PRISM_HOME_ISOLATED"], got)
        self.assertEqual(env["PRISM_REAL_HOME"], self.real)

    def test_dev_build_honours_prism_home_even_when_frozen(self):
        target = os.path.join(self.tmp.name, "testrig")
        env = self.env(PRISM_HOME=target)
        with mock.patch.object(channel, "CHANNEL", "dev"), \
             mock.patch.object(channel, "_frozen", return_value=True):
            self.assertEqual(channel.isolate_home(env), target)

    def test_relative_prism_home_is_refused(self):
        env = self.env(PRISM_HOME="relative/path")
        with mock.patch.object(channel, "CHANNEL", "dev"):
            with self.assertRaises(ValueError):
                channel.isolate_home(env)

    def test_isolation_is_idempotent_and_never_forgets_the_real_home(self):
        env = self.env()
        with mock.patch.object(channel, "CHANNEL", "dev"):
            first = channel.isolate_home(env)
            second = channel.isolate_home(env)
        self.assertEqual(first, second)
        self.assertEqual(env["PRISM_REAL_HOME"], self.real,
                         "a second call must not take the data folder for the real home")
        self.assertEqual(channel.real_home(env), self.real)

    def test_shipped_default_is_prod(self):
        # The line the build rewrites for dev builds must ship as "prod".
        import importlib
        self.assertEqual(importlib.reload(channel).CHANNEL, "prod")


class TheExpanduserHook(unittest.TestCase):
    """The pure function the hook installs."""

    def setUp(self):
        self.f = channel._make_expanduser(lambda p: "REAL:" + str(p), "/data/home")

    def test_tilde_and_paths_under_it_go_to_the_data_home(self):
        self.assertEqual(self.f("~"), "/data/home")
        self.assertEqual(self.f("~/.prism"), "/data/home/.prism")
        self.assertEqual(self.f("~\\.prism"), "/data/home\\.prism")

    def test_everything_else_is_left_to_the_real_function(self):
        for p in ("~someone", "relative", "/abs/path", "C:\\x"):
            self.assertEqual(self.f(p), "REAL:" + p)

    def test_bytes_paths_follow_the_same_rule(self):
        self.assertEqual(self.f(b"~/x"), b"/data/home/x")


class WhatARealDevBuildSees(unittest.TestCase):
    """The hook in a real process: Python paths move, the environment does not."""

    SCRIPT = r'''
import os, sys, json, importlib
sys.path.insert(0, sys.argv[1])
import channel
channel.CHANNEL = "dev"
before = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE")}
home = channel.isolate_home()
import pathlib
open(os.path.join(sys.argv[2], "latched.py"), "w").write(
    "import os\nPATH = os.path.join(os.path.expanduser('~'), '.prism', 'config.json')\n")
sys.path.insert(0, sys.argv[2])
import latched
out = {
  "env_unchanged": before == {k: os.environ.get(k) for k in before},
  "home": home,
  "expanduser": os.path.expanduser("~"),
  "path_home": str(pathlib.Path.home()),
  "latched_at_import": latched.PATH,
  "call_time": os.path.join(os.path.expanduser("~"), ".prism", "x"),
  "real_home": channel.real_home(),
  "second_call": channel.isolate_home(),
}
print(json.dumps(out))
'''

    def test_python_paths_move_and_the_environment_does_not(self):
        import json
        with tempfile.TemporaryDirectory() as real, tempfile.TemporaryDirectory() as scratch:
            env = {k: v for k, v in os.environ.items()
                   if k not in ("PRISM_HOME", "PRISM_HOME_ISOLATED", "PRISM_REAL_HOME")}
            env.update(HOME=real, USERPROFILE=real)
            run = subprocess.run([sys.executable, "-I", "-B", "-c", self.SCRIPT, ROOT, scratch],
                                 capture_output=True, text=True, env=env, cwd=scratch)
            self.assertEqual(run.returncode, 0, run.stderr)
            got = json.loads(run.stdout.strip().splitlines()[-1])
            dev = os.path.join(real, channel.DEV_HOME_NAME)
            self.assertTrue(got["env_unchanged"], "HOME/USERPROFILE must not change")
            self.assertEqual(got["home"], dev)
            self.assertEqual(got["expanduser"], dev)
            self.assertEqual(got["path_home"], dev)
            self.assertEqual(got["latched_at_import"], os.path.join(dev, ".prism", "config.json"),
                             "a path computed at import time (the engine does this) must land in the dev folder")
            self.assertEqual(got["call_time"], os.path.join(dev, ".prism", "x"))
            self.assertEqual(got["real_home"], real, "pickers must be able to find the user's real folders")
            self.assertEqual(got["second_call"], dev)


class LicenceRequestsSayWhichChannel(unittest.TestCase):
    """The licence server hands a dev build the dev version numbers only if the
    build says it is dev. A prod build says so too, so the header is never
    absent from a build that can send it."""

    def sent_headers(self, which):
        from licensing import client
        seen = {}

        class Reply:
            status_code = 200
            def json(self):
                return {}

        def fake_post(url, json=None, headers=None, timeout=None):
            seen.update(headers or {})
            return Reply()

        with mock.patch.object(channel, "CHANNEL", which), \
             mock.patch("requests.post", fake_post):
            try:
                client._post("/v1/lease", {}, app_version="1.6.12")
            except Exception:                        # the reply is a stub; only the request matters
                pass
        return seen

    def test_a_dev_build_says_dev(self):
        self.assertEqual(self.sent_headers("dev").get("X-Prism-Channel"), "dev")

    def test_a_prod_build_says_prod(self):
        self.assertEqual(self.sent_headers("prod").get("X-Prism-Channel"), "prod")


if __name__ == "__main__":
    unittest.main()

"""channel.isolate_home — a dev build, or a source run asked for it, must never
share a home with the developer's real ~/.prism. Everything runs against a
private dict and a temp folder; the real environment is not touched."""
import os
import tempfile
import unittest
from unittest import mock

import channel


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
        self.assertEqual(env["HOME"], self.real)

    def test_prism_home_redirects_a_source_run(self):
        target = os.path.join(self.tmp.name, "sandbox")
        env = self.env(PRISM_HOME=target)
        with mock.patch.object(channel, "CHANNEL", "prod"), \
             mock.patch.object(channel, "_frozen", return_value=False):
            self.assertEqual(channel.isolate_home(env), target)
        self.assertEqual(env["HOME"], target)
        self.assertEqual(env["USERPROFILE"], target)
        self.assertTrue(os.path.isdir(target))

    def test_frozen_prod_build_ignores_prism_home(self):
        target = os.path.join(self.tmp.name, "sandbox")
        env = self.env(PRISM_HOME=target)
        with mock.patch.object(channel, "CHANNEL", "prod"), \
             mock.patch.object(channel, "_frozen", return_value=True):
            self.assertEqual(channel.isolate_home(env), "")
        self.assertEqual(env["HOME"], self.real)
        self.assertFalse(os.path.exists(target))

    def test_dev_build_gets_its_own_home_by_default(self):
        env = self.env()
        with mock.patch.object(channel, "CHANNEL", "dev"):
            got = channel.isolate_home(env)
        self.assertEqual(got, os.path.join(self.real, channel.DEV_HOME_NAME))
        self.assertEqual(env["HOME"], got)
        self.assertNotEqual(env["HOME"], self.real)

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

    def test_isolation_is_idempotent(self):
        # A second call (or a child process that inherited the environment)
        # must not nest another folder inside the dev home.
        env = self.env()
        with mock.patch.object(channel, "CHANNEL", "dev"):
            first = channel.isolate_home(env)
            second = channel.isolate_home(env)
        self.assertEqual(first, second)
        self.assertEqual(env["HOME"], first)

    def test_shipped_default_is_prod(self):
        # The line the build rewrites for dev builds must ship as "prod".
        import importlib
        self.assertEqual(importlib.reload(channel).CHANNEL, "prod")


if __name__ == "__main__":
    unittest.main()

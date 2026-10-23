"""Where a shipped Prism looks for its own updates.

These two strings are compiled into every binary ever released, and there is
no override of any kind -- not an environment variable, not a config file,
and deliberately not anything the licence server can say. `updater.py` states
the reason: "never overridable at runtime in a frozen build, and never a
value taken from a server response". A server that can redirect the update
channel is a server that can be made to ship a different program.

That makes them the most consequential constants in the repository, and
until this file **no test asserted either value**. tests/test_updater.py
checks only that `download_url()` agrees with `app_meta.DOWNLOAD_URL` -- so
both could be wrong together and the suite would stay green.

What being wrong costs
──────────────────────
Nothing visible, which is the problem. A 404 from the wrong repository is
caught by `except Exception: return None` in `_fetch_manifest` (the comment
there reads "no network is routine"), which `check_for_update()` returns as
"no update available", which `workers.py` turns into the `none` signal,
which `main_window` handles by opening `download_url()` in a browser -- the
same wrong repository's releases page.

So: no in-app error, no log line, nothing reported anywhere. Every installed
copy silently stops updating, and the first person to find out is a customer
who eventually notices they are several versions behind. There is no way to
fix it from the server afterwards, because the fix would have to already be
in the binary that is asking.

Why this is not paranoia about a value nobody edits
───────────────────────────────────────────────────
The add-ons restructure moved 13 files and rewrote imports across ~40 more.
A rename pass that touched `updater.py`'s string, or a well-meant
find-and-replace of the repository name during a fork or a transfer, would
change it, and every other test in this suite would still pass.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_meta                                         # noqa: E402
import updater                                          # noqa: E402

# The repository that hosts the releases every shipped build fetches from.
# Changing this is a decision about the product, not a refactor: see the
# module docstring, and docs/architecture/09-boundaries.md §5.
REPO = "AlphaKore5/prism_gui"
# Every build up to 1.6.10 reads this one and nothing else. It must stay a real
# repository, listed as a fallback, for as long as any of them are installed.
OLD_REPO = "HitarthTrivedi/prism_gui"


class TheUpdateChannelPointsAtTheRealRepository(unittest.TestCase):

    def test_the_updater_names_the_release_repository(self):
        self.assertEqual(
            updater.UPDATE_REPO, REPO,
            "updater.UPDATE_REPO no longer points at the repository that "
            "hosts Prism's releases. This value is compiled into every "
            "shipped binary and cannot be corrected from the server; a wrong "
            "one makes every installed copy stop updating with no error "
            "anywhere. If the repository really did move, read this file's "
            "docstring first -- keeping the old one alive is part of it.")

    def test_the_old_repository_stays_listed_as_a_fallback(self):
        self.assertIn(OLD_REPO, updater.UPDATE_FALLBACK_REPOS,
                      "builds before 1.6.11 only ever ask the old repository; "
                      "dropping it from the fallback list strands nobody today "
                      "but removes the way back if the organisation repo fails")
        self.assertEqual(updater._repos()[0], REPO)

    def test_the_browser_fallback_names_it_too(self):
        """`app_meta.DOWNLOAD_URL` is where the Download button goes when the
        in-app update cannot proceed. If the updater is broken AND this points
        somewhere dead, the customer's last route out is a 404."""
        self.assertIn(REPO, app_meta.DOWNLOAD_URL)

    def test_the_two_agree(self):
        self.assertIn(updater.UPDATE_REPO, app_meta.DOWNLOAD_URL,
                      "the updater fetches from one repository and the "
                      "Download button sends people to another")

    def test_the_host_is_built_from_the_repo_and_is_https(self):
        self.assertTrue(updater.UPDATE_HOST.startswith("https://"),
                        "update assets must not be fetched over plain HTTP")
        self.assertIn(updater.UPDATE_REPO, updater.UPDATE_HOST)
        self.assertTrue(updater.UPDATE_HOST.endswith("/releases/latest/download"),
                        "GitHub's releases/latest/download path is what makes "
                        "the newest published release the one a client sees")


class NothingCanRedirectTheUpdateChannelAtRuntime(unittest.TestCase):
    """The security property, asserted rather than trusted.

    `licensing/` may tell a client that a newer version EXISTS -- that is
    what `latest_version` and `min_supported_version` are for -- but it must
    never influence where the bytes come from.
    """

    def test_no_environment_variable_overrides_the_repository(self):
        import importlib
        for name in ("PRISM_UPDATE_REPO", "PRISM_UPDATE_HOST",
                     "PRISM_UPDATE_URL", "UPDATE_REPO"):
            with self.subTest(variable=name):
                os.environ[name] = "someone-else/not-prism"
                self.addCleanup(os.environ.pop, name, None)
                importlib.reload(updater)
                self.assertEqual(
                    updater.UPDATE_REPO, REPO,
                    "%s changed where a shipped Prism fetches updates from. "
                    "The update channel is fixed at build time on purpose: "
                    "anything that can redirect it can ship a different "
                    "program to every customer." % name)
        importlib.reload(updater)

    def test_the_module_does_not_read_the_repository_from_anywhere(self):
        """A belt-and-braces source check. The constant must be a literal,
        not derived from config, the environment, or a response."""
        import inspect
        source = inspect.getsource(updater)
        head = source.split("UPDATE_HOST", 1)[0]
        for forbidden in ("os.environ", "getenv", "config.load", "requests"):
            self.assertNotIn(
                forbidden, head.split("UPDATE_REPO")[-1],
                "UPDATE_REPO appears to be computed from %r rather than "
                "being a compile-time literal" % forbidden)


if __name__ == "__main__":
    unittest.main()

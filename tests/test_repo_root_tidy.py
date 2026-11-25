"""The repo root only grows on purpose.

On 2026-11-25 the root held four stray PNGs, five one-off Qt/PDF experiments
named test_*.py (outside tests/, so pytest never ran them), a folder of their
screenshots and a 15 MB promo-video project -- none of it product, build or
test, and none of it referenced by anything. They were removed, and this test
keeps the root from filling up again.

It reads what git tracks, so an untracked scratch file on your own machine
(a .venv, build/, a screenshot) never fails it -- only one you commit does.
"""
from __future__ import annotations

import os
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ROOT_FILES = {
    # dotfiles
    ".gitignore", ".gitmodules",
    # the build contract surface (CONTRIBUTING.md rule 8; test_repo_layout.py)
    "main.py", "app_meta.py", "updater.py", "apply_update.py",
    "update_manifest.py", "paths.py", "core_bridge.py",
    # shipped or loaded at runtime
    "style.qss", "TERMS_OF_USE.md", "PRIVACY_POLICY.md", "NOTICE",
    # build and test configuration
    "requirements.txt", "pytest.ini", "skills-lock.json", "run-prism.sh",
    # app modules that still live at the root
    "ai_server.py", "awake.py", "channel.py", "chatlog.py", "cloud.py",
    "dashboard_data.py", "deps.py", "deps_worker.py", "dev_import.py",
    "diagnostics.py", "docexport.py", "email_config.py", "entitlement_copy.py",
    "favorites.py", "festivals.py", "flavour.py", "friendly.py", "gui_gc.py",
    "i18n.py", "identity.py", "inquiry_config.py", "main_window.py",
    "output_folders.py", "plans.py", "pulse.py", "roles.py", "send_ledger.py",
    "support_kb.py", "theme.py", "uninstall.py", "viewer.py", "viewer_data.py",
    "wakeword.py", "workers.py", "workspace.py",
    # docs
    "README.md", "GETTING_STARTED.md", "RUNNING.md", "BUILD.md", "SHIPPING.md",
    "RELEASING-UPDATES.md", "RELEASE_ISSUES.md", "CONTRIBUTING.md",
    "OWNERS.md", "CLAUDE.md", "AGENTS.md", "LICENSING.md", "SIGNALS.md",
    "CHANGES.md", "KNOWN_ISSUES.md", "BUGS.md", "BOQ-CHANGES-TODO.md",
    "improvement.md",
}

ROOT_FOLDERS = {
    ".codex", ".github", "addons", "assets", "constraints", "devtools",
    "dialogs", "docs", "examples", "hvac_takeoff", "integrations", "lang",
    "licensing", "packaging", "preview", "prism_terminal", "prospector",
    "tests", "widgets",
}

HOW_TO_ADD = (
    "\n\nWhere it should go instead:\n"
    "  * a test                  -> tests/test_<name>.py (pytest only collects tests/)\n"
    "  * an add-on's code        -> addons/<key>/\n"
    "  * a shell widget / dialog -> widgets/ or dialogs/\n"
    "  * a developer script      -> devtools/\n"
    "  * a doc                   -> docs/\n"
    "  * screenshots, renders, scratch output -> nowhere; keep them out of git\n"
    "If it genuinely belongs at the root (the build or the app loads it from "
    "there), add its name to ROOT_FILES or ROOT_FOLDERS in "
    "tests/test_repo_root_tidy.py in the same commit, and say why in the "
    "commit message so review sees the decision.")


def _tracked_top_level():
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise unittest.SkipTest(f"not a git checkout ({exc}); nothing to compare")
    files, folders = set(), set()
    for path in filter(None, out.split("\0")):
        head, sep, _ = path.partition("/")
        # A submodule is listed as one bare path; it is a folder all the same.
        if sep or os.path.isdir(os.path.join(ROOT, head)):
            folders.add(head)
        else:
            files.add(head)
    return files, folders


class TheRepoRootOnlyGrowsOnPurpose(unittest.TestCase):

    def setUp(self):
        self.files, self.folders = _tracked_top_level()

    def test_no_unlisted_file_at_the_root(self):
        extra = sorted(self.files - ROOT_FILES)
        self.assertEqual(
            extra, [],
            "New file(s) at the repo root: %s" % ", ".join(extra) + HOW_TO_ADD)

    def test_no_unlisted_top_level_folder(self):
        extra = sorted(self.folders - ROOT_FOLDERS)
        self.assertEqual(
            extra, [],
            "New top-level folder(s): %s" % ", ".join(extra) + HOW_TO_ADD)


if __name__ == "__main__":
    unittest.main()

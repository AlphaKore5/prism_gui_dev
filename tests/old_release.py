"""Is the git tag we call "the released 1.6.10" actually that release?

Two tests run the real v1.6.10 updater (test_update_compat_1_6_10.py and
test_e2e_update.py). They are only worth anything if the tag holds the OLD code.
The dev repository carries its own tag named v1.6.10 that points at current
code (a dev release of that version number); extracting it would make the
"old client" the new one and the tests vacuous -- they first ran in CI exactly
that way, on 2026-10-23. So the tag is trusted by CONTENT, not by name.
"""
from __future__ import annotations

import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "v1.6.10"
#: Present in the code written after 1.6.10, absent from the release.
NEW_CODE_MARKERS = ("UPDATE_FALLBACK_REPOS", "UPDATER_LEVEL", "import channel")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def skip_reason(tag: str = TAG) -> str:
    """"" when the tag is the genuine old release; otherwise why to skip."""
    if _git("rev-parse", "--verify", "-q", tag + "^{commit}").returncode != 0:
        return f"git tag {tag} is not in this clone -- `git fetch --tags`"
    for name in ("updater.py", "licensing/keys.py"):
        shown = _git("show", f"{tag}:{name}")
        if shown.returncode != 0:
            return f"{tag} has no {name}"
        for marker in NEW_CODE_MARKERS:
            if marker in shown.stdout:
                return (f"git tag {tag} here holds current code ({marker!r} is in "
                        f"{name}), not the released 1.6.10 -- this repository's "
                        "tag is a dev release, so the old-client tests are skipped")
    return ""

#!/usr/bin/env python3
"""Does a pull request touch anything that decides how the installers are built?

    python3 devtools/ci_changes.py HEAD^1 HEAD     # prints packaging=true|false

.github/workflows/build.yml runs this on pull requests only and builds the
installers when it says true (or when the PR carries the `build` label).
Pushes to main, tags, manual runs and the nightly run always build. If this
script fails, the workflow builds anyway: a wrong "false" is the only answer
that can hide a broken build, so it is never the fallback.
"""
from __future__ import annotations

import subprocess
import sys
from fnmatch import fnmatch

# A folder ("x/**") matches everything under it; anything else is one file
# name at the repository root.
PATTERNS = (
    "packaging/**",
    "flavour.py",
    "requirements*",
    "constraints/**",
    ".github/workflows/**",
    "main.py",
    "addons/flavours/**",
)


def touches_packaging(paths: list[str]) -> list[str]:
    """The paths (repo-relative, `/`-separated) that make a build necessary."""
    hits = []
    for path in paths:
        for pat in PATTERNS:
            if pat.endswith("/**"):
                if path.startswith(pat[:-2]):
                    hits.append(path)
                    break
            elif "/" not in path and fnmatch(path, pat):
                hits.append(path)
                break
    return hits


def main(argv: list[str]) -> int:
    base, head = argv
    out = subprocess.run(["git", "diff", "--name-only", base, head],
                         capture_output=True, text=True, check=True).stdout
    hits = touches_packaging([p for p in out.splitlines() if p])
    for p in hits:
        print(f"needs a build: {p}", file=sys.stderr)
    print(f"packaging={'true' if hits else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""E6c: which test files cannot run in the flavour under test.

A test file that imports an add-on the flavour does not contain (module level
or inside a function) tests a tool that build does not ship. Such a file is
SKIPPED, with the reason, never deleted: the complete build runs every file.
Files that already adapt to the flavour (they mention `flavour` or
`needs_addon`) are kept: they assert the add-on's absence themselves.

Pure functions over source text, so tests/test_flavour_skip.py can prove them.
"""
from __future__ import annotations

import ast

import flavour


def absent_addons_imported(source: str, flav: str) -> list[str]:
    """Add-on keys `source` imports that `flav` does not contain (sorted)."""
    absent = set(flavour.ADDONS_BY_FLAVOUR["complete"]) \
        - set(flavour.ADDONS_BY_FLAVOUR[flav])
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            mods = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            mods = [node.module] + [node.module + "." + a.name
                                    for a in node.names]
        else:
            continue
        for m in mods:
            parts = m.split(".")
            if parts[0] == "addons" and len(parts) > 1 and parts[1] in absent:
                found.add(parts[1])
    return sorted(found)


def skip_reason(source: str, flav: str) -> str:
    """Why this file is skipped under `flav`, or "" to run it."""
    if flav == "complete" or "flavour" in source or "needs_addon" in source:
        return ""
    gone = absent_addons_imported(source, flav)
    if not gone:
        return ""
    return ("not part of the %s build: imports the %s add-on"
            % (flav, ", ".join(gone)))

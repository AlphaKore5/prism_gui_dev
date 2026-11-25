#!/usr/bin/env python3
"""Flatten a built app directory into individually-named files for hosting
as GitHub Release assets.

    python3 packaging/flatten_update_assets.py dist/Prism dist/update-assets linux-x64

Run by file path, same reasoning as packaging/manifest.py's own docstring
(packaging/ collides with the installed `packaging` library under `-m`).

Names each output file `<platform_tag>__<relative path with / as __>`,
exactly what updater.py's `_file_url()` builds when it goes to fetch one —
this is the CI-side half of that naming scheme, and the two must never drift
apart independently. The platform prefix exists because build.yml's `release`
job publishes Linux, Windows and macOS to the SAME GitHub Release: without
it, three platforms' builds would each have a file at, say,
`_internal/base_library.zip` — same flattened name, different bytes — and
whichever OS's CI job uploaded last would silently clobber the other two's
copy on the release.

Symlinks are skipped: they carry no bytes worth hosting, and the manifest's
own `symlink` entry (update_manifest.build()) is everything updater.py needs
to recreate one during stage_update() — nothing to download.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manifest  # noqa: E402


def flatten(root_dir: str, out_dir: str, platform_tag: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    for dirpath, _dirnames, filenames in os.walk(root_dir):
        for name in filenames:
            full = os.path.join(dirpath, name)
            if os.path.islink(full):
                continue
            if os.path.getsize(full) == 0:
                # GitHub Releases refuses zero-byte assets outright
                # ("size must be greater than or equal to 1" — confirmed
                # against the real API). updater.stage_update() already
                # knows to create an empty file directly instead of
                # fetching one, so there's nothing for this flattened
                # asset to do except fail every upload that includes it.
                continue
            rel = os.path.relpath(full, root_dir).replace(os.sep, "/")
            # update_manifest.flat_name(), not an inline f-string — see its
            # own docstring. A build over a deeply-nested tree (Chromium's
            # macOS Framework bundle, in the one case that's actually hit
            # this) needs the identical long-name fallback updater.py's
            # _file_url() computes at fetch time, or the two would name the
            # same file differently and every such download would 404.
            flat = update_manifest.flat_name(platform_tag, rel)
            shutil.copy2(full, os.path.join(out_dir, flat))
            count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root_dir", help="Built app directory, e.g. dist/Prism")
    p.add_argument("out_dir", help="Where to write the flattened copies")
    p.add_argument("platform_tag", help="e.g. linux-x64, or windows-x64-studio "
                                        "for a flavour — must match "
                                        "updater.update_channel() in the "
                                        "build that will fetch these")
    args = p.parse_args(argv)

    if not os.path.isdir(args.root_dir):
        p.error(f"{args.root_dir!r} is not a directory")

    count = flatten(args.root_dir, args.out_dir, args.platform_tag)
    print(f"Flattened {count} files for {args.platform_tag} -> {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

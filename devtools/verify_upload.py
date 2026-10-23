#!/usr/bin/env python3
"""Verify every flattened update-asset a signed manifest calls for is
actually on the release, and upload whatever's missing — in small batches,
re-verified after each one, so a single dropped connection can't silently
wipe out hundreds of files the way one giant `gh release upload` call did
on the very first v1.4.0 attempt (863/966 linux-x64 files, 806/863
macos-arm64 files never made it, and gh still exited 0).

    python3 devtools/verify_upload.py v1.4.0 linux-x64 \
        /path/to/update-assets-linux-x64 manifest.linux-x64.signed

`gh release view --json assets` (and the "get a release" API it calls) is
NOT trustworthy for this on a release with hundreds of assets — it silently
truncated to a wrong-but-plausible-looking count during this same incident.
The only reliable listing is the dedicated, explicitly paginated assets
endpoint, which is what `_list_assets` below uses.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

# Windows consoles are cp1252 and cannot encode the characters below — see
# packaging/build.py for the CI failure that found this. Degrade, don't die.
#
# Under __main__ only: at import time sys.stdout belongs to the importer,
# not to us. devtools/mint.py is imported by five test files, so at module
# level this block would re-encode pytest's own capture stream as a side
# effect of collecting a test — a script reaching into its caller's I/O.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manifest as UM  # noqa: E402
import licensing.keys as K  # noqa: E402

BATCH_SIZE = 40


def _release_id(repo: str, tag: str) -> int:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/tags/{tag}", "-q", ".id"],
        check=True, capture_output=True, text=True).stdout.strip()
    return int(out)


def _list_assets(repo: str, release_id: int) -> set[str]:
    """The full, real asset list — explicitly paginated. Never use
    `gh release view --json assets` for this; it does not reliably return
    everything once a release has hundreds of assets."""
    out = subprocess.run(
        ["gh", "api", "--paginate",
         f"repos/{repo}/releases/{release_id}/assets?per_page=100",
         "-q", ".[].name"],
        check=True, capture_output=True, text=True).stdout
    return {line for line in out.splitlines() if line}


def expected_flat_names(manifest_path: str, platform_tag: str,
                        part: int = 1, kid: str = "u1") -> dict[str, str]:
    """{flat_name: local_relative_path} for every file of release `part` that
    needs an uploaded asset — matches flatten_update_assets.py's own skip
    rules: no symlinks (recreated from the manifest's own `symlink` field),
    no zero-byte files (GitHub refuses to host them; updater.py creates them
    directly). A build too big for one release is hosted across several
    (update_manifest.assign_parts); this checks one of them."""
    token = open(manifest_path, encoding="utf-8").read().strip()
    payload = UM.verify(token, public_keys=dict(
        K.UPDATE_DEVELOPMENT if kid in K.UPDATE_DEVELOPMENT else K.UPDATE_PRODUCTION))
    out = {}
    for entry in payload["files"]:
        if UM.is_hosted(entry) and UM.part_of(entry) == part:
            out[UM.flat_name(platform_tag, entry["path"])] = entry["path"]
    return out


def part_of_tag(tag: str) -> int:
    """Which part an assets-release tag is: `v1.6.3-assets-windows-x64` is
    part 1, `v1.6.3-assets-windows-x64-2` part 2."""
    m = re.search(r"-assets-.*-(\d+)$", tag)
    return int(m.group(1)) if m else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("tag")
    p.add_argument("platform_tag")
    p.add_argument("assets_dir", help="Local update-assets-<platform> "
                                      "directory (flattened filenames)")
    p.add_argument("manifest_path", help="That platform's SIGNED manifest")
    p.add_argument("--repo", default="HitarthTrivedi/prism_gui")
    p.add_argument("--kid", default="u1",
                   help="Key id the manifest was signed with (udev2 for a dev release)")
    args = p.parse_args(argv)

    release_id = _release_id(args.repo, args.tag)
    part = part_of_tag(args.tag)
    expected = expected_flat_names(args.manifest_path, args.platform_tag, part, args.kid)
    print(f"{args.platform_tag}: manifest expects {len(expected)} assets "
          f"on {args.tag} (part {part})")

    actual = _list_assets(args.repo, release_id)
    missing = sorted(name for name in expected if name not in actual)
    print(f"{args.platform_tag}: {len(missing)} missing on the release "
         f"right now")
    if not missing:
        print(f"{args.platform_tag}: nothing to do")
        return 0

    not_local = [n for n in missing
                if not os.path.exists(os.path.join(args.assets_dir, n))]
    if not_local:
        print(f"WARNING: {len(not_local)} missing files aren't in "
             f"{args.assets_dir} either — re-download the CI artifact "
             f"first. First few: {not_local[:5]}", file=sys.stderr)
        missing = [n for n in missing if n not in not_local]

    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        paths = [os.path.join(args.assets_dir, n) for n in batch]
        print(f"uploading batch {i // BATCH_SIZE + 1} "
             f"({len(batch)} files, {i + len(batch)}/{len(missing)})…")
        subprocess.run(
            ["gh", "release", "upload", args.tag, "-R", args.repo,
             "--clobber"] + paths, check=True)

    actual_after = _list_assets(args.repo, release_id)
    still_missing = sorted(name for name in expected if name not in actual_after)
    if still_missing:
        print(f"✗ {args.platform_tag}: STILL missing {len(still_missing)} "
             f"after retry: {still_missing[:10]}", file=sys.stderr)
        return 1
    print(f"✓ {args.platform_tag}: all {len(expected)} expected assets "
         f"confirmed present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

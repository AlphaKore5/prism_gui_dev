#!/usr/bin/env python3
"""Sign an update manifest — release-machine tool, not CI, not a build step.

    python3 devtools/sign_manifest.py dist/manifest.json -o dist/manifest.signed \
        --key-hex "$UPDATE_SIGNING_KEY_HEX"

Deliberately a human running this by hand from a private key that lives
nowhere near CI or the licence server — see licensing/keys.py's
UPDATE_PRODUCTION comment for the whole reasoning
(update-research-inapp-download.md §5.2 requirement #2). The key never
appears as a literal in this file or anywhere else in the repo; it must be
supplied at run time via --key-hex or the UPDATE_SIGNING_KEY_HEX environment
variable, on whatever offline machine holds it.

Refuses to sign a version that is not strictly newer than the last version
this tool has signed, on this machine, for this manifest's PLATFORM — one
tracker file per platform tag (devtools/.last_signed_update_version.<tag>,
gitignored, tag read off the manifest's own filename), because one release
signs the identical version three times over, once per platform manifest,
and a single shared tracker refused the second and third of those as
"downgrades" of the first. The property this guard actually protects — a
release engineer can't accidentally re-sign an OLDER manifest for a
platform that already shipped a newer one — is the same "no accidental
downgrade" contract update_manifest.verify()'s expiry/monotonic checks give
the CLIENT side; it's just now scoped correctly.

NOT SHIPPED. devtools/ is absent from packaging/prism.spec (see build.py's
own comment: "devtools/ is NOT here, and must never be").
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import update_manifest  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# The OLD single global tracker (pre-2026-08-31). Every release signs the
# SAME version three times — once per platform manifest — and this file
# couldn't tell "the same platform's manifest, an older version" (a real
# downgrade, correctly refused) apart from "a different platform's
# manifest, the version I just signed a minute ago" (completely normal,
# wrongly refused). The first real multi-platform release hit exactly that:
# linux-x64 signed 1.4.0 fine, then windows-x64's signing attempt for the
# SAME 1.4.0 was refused as "not newer than 1.4.0" — the version this very
# tool had just recorded, for a different platform's manifest.
_LEGACY_LAST_SIGNED_PATH = os.path.join(HERE, ".last_signed_update_version")


def _tracker_key(manifest_path: str) -> str:
    """Which downgrade-history "lane" this manifest belongs to — the
    platform tag, read off the filename packaging/manifest.py already
    names it with (`manifest.<platform_tag>.unsigned.json`). Falls back to
    the whole basename for anything that doesn't match, which only ever
    makes the guard MORE precise (a distinct key per distinct filename),
    never less — it still catches a genuine same-file downgrade, and it
    can never wrongly conflate two different files the way one global file
    did."""
    name = os.path.basename(manifest_path)
    m = re.match(r"manifest\.([^.]+)\.", name)
    return m.group(1) if m else name


def _last_signed_path(manifest_path: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", _tracker_key(manifest_path))
    return os.path.join(HERE, f".last_signed_update_version.{safe}")


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in v.strip().split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _last_signed_version(manifest_path: str) -> str:
    # Deliberately NOT falling back to the old global _LEGACY_LAST_SIGNED_PATH
    # here: that file can't say which PLATFORM last wrote it, so treating its
    # value as "the last version signed for THIS platform" would silently
    # reintroduce the exact bug this file exists to fix — attributing one
    # platform's signing history to a different platform's manifest. A
    # machine upgrading to per-platform tracking starts every platform with
    # a clean slate instead: a one-time, one-machine relaxation of the
    # downgrade guard (each platform's very next sign can't be caught as a
    # downgrade, having no prior record to compare against), which is a far
    # smaller risk than the guard wrongly refusing a legitimate release.
    try:
        with open(_last_signed_path(manifest_path), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _record_signed_version(manifest_path: str, version: str) -> None:
    with open(_last_signed_path(manifest_path), "w", encoding="utf-8") as f:
        f.write(version)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("manifest_path", help="Unsigned manifest JSON from packaging/manifest.py")
    p.add_argument("-o", "--output", required=True, help="Where to write the signed PRSMUv1 token")
    p.add_argument("--key-hex", default=os.environ.get("UPDATE_SIGNING_KEY_HEX", ""),
                   help="Ed25519 private key, hex. Prefer the env var over the flag "
                        "so it never lands in shell history.")
    p.add_argument("--kid", default="u1", help="Key id this signature claims (default: u1, "
                                               "the production update key's id)")
    p.add_argument("--validity-days", type=int, default=update_manifest.DEFAULT_VALIDITY_DAYS)
    p.add_argument("--allow-downgrade", action="store_true",
                   help="Bypass the monotonic-version check. For test fixtures only — "
                        "never pass this when signing a real release.")
    p.add_argument("--rollout", type=int, default=None,
                   help="Offer automatically to this percent of devices (0-100). "
                        "Omit for everyone. Clients built before 1.6.11 ignore it.")
    p.add_argument("--min-updater", type=int, default=None,
                   help="Oldest updater level that may install this release.")
    p.add_argument("--revoke", action="append", default=[], metavar="VERSION",
                   help="Withdraw a version (repeatable): clients stop offering it.")
    args = p.parse_args(argv)

    if not args.key_hex:
        p.error("no signing key: pass --key-hex or set UPDATE_SIGNING_KEY_HEX")

    with open(args.manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    version = manifest.get("version", "")
    if not version:
        p.error("manifest has no 'version' field")

    last = _last_signed_version(args.manifest_path)
    if last and not args.allow_downgrade and _version_tuple(version) <= _version_tuple(last):
        p.error(f"refusing to sign {version!r}: not newer than the last version this "
                f"machine signed for {_tracker_key(args.manifest_path)!r} ({last!r}). "
                f"Pass --allow-downgrade only for test fixtures, never for a real "
                f"release.")

    if args.rollout is not None:
        manifest["rollout"] = args.rollout
    if args.min_updater is not None:
        manifest["min_updater"] = args.min_updater
    if args.revoke:
        manifest["revoked"] = sorted(set(manifest.get("revoked", [])) | set(args.revoke))
    try:
        update_manifest.check_policy(manifest)
    except update_manifest.ManifestError as e:
        p.error(str(e))

    token = update_manifest.sign(manifest, args.key_hex, kid=args.kid,
                                 validity_days=args.validity_days)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(token)

    if not args.allow_downgrade:
        _record_signed_version(args.manifest_path, version)

    print(f"Signed manifest for {version} (kid={args.kid}) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

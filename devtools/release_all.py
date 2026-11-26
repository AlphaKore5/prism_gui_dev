#!/usr/bin/env python3
"""Sign and publish every platform's update manifest for one release, in
one run — release-machine tool, not CI, not a build step.

    UPDATE_SIGNING_KEY_HEX=... python3 devtools/release_all.py v1.4.0 33447658517

The `run_id` is the CI run that built the tag — `gh run list --limit 5`
shows it, or `gh run list --workflow "Build desktop apps" -b <tag> -L 1`.

This is the loop RELEASING-UPDATES.md's "Every release" section describes,
run once per platform instead of copy-pasted by hand three times: download
that platform's unsigned manifest and flattened update-assets from the CI
run, sign the manifest, upload both. devtools/sign_manifest.py is still the
thing that actually signs — this script never touches the key beyond
handing it to that subprocess exactly the way it already accepts it
(--key-hex, defaulting to the environment variable), and never prints or
logs it.

Deliberately NOT shipped (devtools/ is absent from packaging/prism.spec —
see build.py's own comment) and deliberately still a human running it on
their own offline signing machine: this automates the repetitive mechanics,
not the trust decision. Signing a platform for the first time needs
UPDATE_SIGNING_KEY_HEX already in this shell's environment — the script
refuses outright, with a specific "which platform, why" error, right at
the point it would actually need it, and never accepts it as a
command-line argument (a CLI arg is visible to anyone who can list
processes on the machine; an inherited environment variable isn't). A
platform whose signed manifest already exists on the release needs no key
at all — re-running this to finish an interrupted asset upload, or to add
a platform's release-assets structure after the fact, works without it.

TWO releases per version, not one — this is the real structural fix from
the v1.4.0 incident, not just a convenience wrapper:

  <tag>                    the human-facing release: archives, unsigned
                            manifests (from CI), signed manifests (from
                            here). updater.py's _manifest_url() reads this
                            one via "latest/download" — unchanged.
  <tag>-assets-<platform>  ONE per platform, holding that platform's ~1000
                            flattened per-file update assets. Created
                            --prerelease so it can never become GitHub's
                            "latest" release out from under the real one.
                            updater.py's _file_url() reads these via an
                            explicit tag, never "latest".

Why: GitHub caps a release at 1000 assets. Three platforms' flattened
files sharing the tag release with the manifests and archives blew past
that on the very first real 3-platform release (linux-x64 alone needs 966
once Playwright's Chromium is in the bundle) — 863 of those files silently
never made it onto the release at all, `gh release upload` still exited 0,
and nobody noticed until an actual update attempt was watched fail.

Uploads happen in small batches (BATCH_SIZE files per `gh release upload`
call), each one followed by re-listing what the release ACTUALLY has —
via the paginated assets API, never `gh release view --json assets`, which
silently returns an incomplete list once a release has hundreds of assets
(confirmed against the real API; this is exactly how those 863 missing
files went undetected the first time). Any file still missing after all
batches gets one more individual retry pass. This is slow — real, not a
bug in this script — but a dropped connection now costs at most one batch,
not the other 90% of a thousand-file upload silently vanishing.

Idempotent per platform: skips one whose assets-release already has every
file the signed manifest calls for, so a run that fails partway through
can just be re-run. Pass --force to redo a platform anyway.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time

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
import flavour as FL  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
BATCH_SIZE = 40

# platform_tag (what manifests, .signed files and assets-releases are
# named) -> the .github/workflows/build.yml matrix's `os` value (what its
# `update-assets-<os>` workflow artifact is actually named). Mirrors that
# workflow's `strategy.matrix.include` — update this table if that matrix
# ever changes runner images.
# Order is the release order: Windows first (the platform whose installs have
# the least slack when an update is skipped), then Linux, then macOS.
PLATFORMS = [
    ("windows-x64", "windows-latest"),
    ("linux-x64", "ubuntu-22.04"),
    # `-app`: the bundle-layout channel (updater.platform_tag()). The plain
    # `macos-arm64` name is retired — see the comment there for why a 1.4.0
    # Mac must never find a manifest under it.
    ("macos-arm64-app", "macos-14"),
]


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("»", " ".join(cmd))
    return subprocess.run(cmd, check=True, **kw)


def _version_from_tag(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


#: The flavours that get their own release (Complete is the unchanged flow).
FLAVOURS = ("studio", "sales", "engineering")


def flavour_tags(tag: str, flavour: str = "complete") -> tuple[str, str]:
    """(release tag, base tag). The release tag is the human-facing release
    (`v2.0.0-studio`: installers, the signed manifest). The base tag is
    `v<version>`: the update-asset releases are named from it
    (`v2.0.0-assets-windows-x64-studio`), because that is the name
    updater._assets_release_tag() computes from the VERSION alone. Building
    them from the release tag would put every update file where no client
    looks. Complete: both are the tag, as always."""
    if flavour == "complete":
        return tag, tag
    suffix = "-" + FL.identity(flavour)["channel"]
    if not tag.startswith("v") or not tag.endswith(suffix) or len(tag) <= len(suffix) + 1:
        raise ValueError(f"a {flavour} release tag looks like v<version>{suffix}, not {tag!r}")
    return tag, tag[:-len(suffix)]


def artifact_names(matrix_os: str, flavour: str = "complete") -> tuple[str, str]:
    """(installers artifact, update-assets artifact) of a CI run, named as
    build.yml names them: `prism-<os>` for Complete, `prism-<flavour>-<os>`."""
    mid = "" if flavour == "complete" else f"{flavour}-"
    return f"prism-{mid}{matrix_os}", f"update-assets-{mid}{matrix_os}"


def _assets_tag(tag: str, platform_tag: str, part: int = 1) -> str:
    """Part 1 is `<tag>-assets-<platform>` — where every older build and
    client look; a build too big for one release (GitHub allows 1000 assets
    each) continues in `-2`, `-3`, … — see update_manifest.assign_parts."""
    return f"{tag}-assets-{platform_tag}{UM.parts_suffix(part)}"


def _release_exists(repo: str, tag: str) -> bool:
    return subprocess.run(
        ["gh", "release", "view", tag, "-R", repo],
        capture_output=True).returncode == 0


def _release_id(repo: str, tag: str) -> int:
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/tags/{tag}", "-q", ".id"],
        check=True, capture_output=True, text=True).stdout.strip()
    return int(out)


def _list_assets(repo: str, release_id: int) -> set[str]:
    """The full, real asset list — explicitly paginated. NEVER use
    `gh release view --json assets` for this: it silently returns an
    incomplete list once a release has hundreds of assets, which is
    exactly how 863 missing linux-x64 files went unnoticed the first
    time this shipped."""
    out = subprocess.run(
        ["gh", "api", "--paginate",
         f"repos/{repo}/releases/{release_id}/assets?per_page=100",
         "-q", ".[].name"],
        check=True, capture_output=True, text=True).stdout
    return {line for line in out.splitlines() if line}


def already_signed(repo: str, tag: str, platform_tag: str) -> bool:
    out = subprocess.run(
        ["gh", "release", "view", tag, "-R", repo, "--json", "assets", "-q",
         f'[.assets[] | select(.name=="manifest.{platform_tag}.signed")] '
         f'| length'],
        check=True, capture_output=True, text=True).stdout.strip()
    return out != "0"


def keys_for(kid: str) -> dict[str, str]:
    """The public keys a manifest signed with `kid` is verified against: the
    development table for a dev key id, the production table otherwise. Never
    both, so a dev-signed file cannot pass for a production release."""
    return dict(K.UPDATE_DEVELOPMENT if kid in K.UPDATE_DEVELOPMENT
                else K.UPDATE_PRODUCTION)


def expected_flat_names(manifest_path: str, platform_tag: str,
                        kid: str = "u1") -> dict[int, dict[str, str]]:
    """{part: {flat_name: manifest path}} for every file needing an uploaded
    asset — matches flatten_update_assets.py's own skip rules: no
    symlinks (recreated from the manifest's own `symlink` field), no
    zero-byte files (GitHub refuses to host them; updater.py creates
    them directly). Grouped by the release each file belongs to — the
    signed manifest's own `part` for it (1 when it names none)."""
    token = open(manifest_path, encoding="utf-8").read().strip()
    payload = UM.verify(token, public_keys=keys_for(kid))
    out: dict[int, dict[str, str]] = {}
    for e in payload["files"]:
        if UM.is_hosted(e):
            out.setdefault(UM.part_of(e), {})[
                UM.flat_name(platform_tag, e["path"])] = e["path"]
    return out


def upload_missing(repo: str, assets_tag: str, assets_dir: str,
                   expected: dict[str, str]) -> list[str]:
    """Uploads whatever `expected` names aren't already on the
    assets-release, in small batches, verified after each. Returns
    whatever is STILL missing after one full pass plus a retry — should
    be empty; a non-empty result means something is wrong beyond a
    transient network blip and wants a human look, not another retry
    loop."""
    release_id = _release_id(repo, assets_tag)
    actual = _list_assets(repo, release_id)
    missing = sorted(n for n in expected if n not in actual)
    if not missing:
        print(f"  {assets_tag}: all {len(expected)} expected assets "
             f"already present")
        return []

    not_local = [n for n in missing
                if not os.path.exists(os.path.join(assets_dir, n))]
    if not_local:
        print(f"  WARNING: {len(not_local)} missing files aren't in "
             f"{assets_dir} either. First few: {not_local[:5]}",
             file=sys.stderr)
    missing = [n for n in missing if n not in not_local]

    for attempt in (1, 2):
        if not missing:
            break
        for i in range(0, len(missing), BATCH_SIZE):
            batch = missing[i:i + BATCH_SIZE]
            paths = [os.path.join(assets_dir, n) for n in batch]
            print(f"  uploading batch {i // BATCH_SIZE + 1} "
                 f"({len(batch)} files, {i + len(batch)}/{len(missing)}, "
                 f"attempt {attempt})…")
            subprocess.run(
                ["gh", "release", "upload", assets_tag, "-R", repo,
                 "--clobber"] + paths, check=True)
        actual = _list_assets(repo, release_id)
        missing = sorted(n for n in expected
                         if n not in actual and n not in not_local)

    return missing + not_local


def do_platform(repo: str, tag: str, run_id: str, work: str,
                platform_tag: str, matrix_os: str, force: bool,
                kid: str = "u1", flavour: str = "complete",
                sign_only: bool = False) -> None:
    # A flavour's manifest, signed file and assets are named for its CHANNEL
    # (windows-x64-studio), and its update-asset releases for the VERSION
    # (flavour_tags), not for the release tag.
    _, base = flavour_tags(tag, flavour)
    version = _version_from_tag(base)
    platform_tag = FL.update_channel(platform_tag, flavour)
    unsigned = os.path.join(work, f"manifest.{platform_tag}.unsigned.json")
    signed = os.path.join(work, f"manifest.{platform_tag}.signed")
    assets_dir = os.path.join(work, f"update-assets-{platform_tag}")
    if sign_only:
        pass        # signing needs the small manifest only, never the update files
    elif not os.path.isdir(assets_dir) or not os.listdir(assets_dir):
        run(["gh", "run", "download", run_id, "-R", repo,
            "-n", artifact_names(matrix_os, flavour)[1], "-D", assets_dir])
    else:
        print(f"  {assets_dir} already downloaded, reusing local files")

    # The signed manifest is published LAST, after every file it lists. A
    # client that finds the manifest then never finds its files missing: before
    # this order, a customer who pressed "Check for updates" mid-publish was
    # offered a version whose files were still going up, and failed. The
    # organisation mirror always did it this way (mirror_platform).
    on_release = (not force) and already_signed(repo, tag, platform_tag)
    if on_release:
        # sign_manifest.py's downgrade guard would refuse to re-sign this
        # SAME version — correctly; that is not a bug to route around here.
        # Reuse what's already on the release instead of trying to redo it,
        # so a re-run only picks up where a previous partial run actually
        # left off (asset upload), not "sign this version again".
        print(f"  manifest.{platform_tag}.signed already on {tag} — "
             f"reusing it, checking assets only")
        if not os.path.exists(signed):
            run(["gh", "release", "download", tag, "-R", repo,
                "-p", f"manifest.{platform_tag}.signed",
                "-D", work, "--clobber"])
    elif not force and os.path.isfile(signed):
        # Signed by an earlier run that stopped while uploading files, so the
        # manifest is not on the release yet. Signing again would be refused
        # (same version) and is not needed: send the bytes already signed.
        print(f"  manifest.{platform_tag}.signed signed by an earlier run — "
             f"reusing it; files first, then the manifest")
    else:
        run(["gh", "release", "download", tag, "-R", repo,
            "-p", f"manifest.{platform_tag}.unsigned.json",
            "-D", work, "--clobber"])
        if not os.environ.get("UPDATE_SIGNING_KEY_HEX"):
            raise RuntimeError(
                "UPDATE_SIGNING_KEY_HEX is not set in this shell, and "
                f"{platform_tag} actually needs signing (no valid "
                f".signed manifest to reuse) — set it there before "
                f"running this, never as a command-line argument.")
        # No --key-hex here: sign_manifest.py already defaults it to
        # the UPDATE_SIGNING_KEY_HEX environment variable just confirmed
        # above. Passing it explicitly here would work identically but put
        # it on THIS process's command line for no benefit.
        extra = ["--allow-downgrade"] if force else []
        run([sys.executable, os.path.join(HERE, "sign_manifest.py"),
            unsigned, "-o", signed, "--kid", kid] + extra)

    if sign_only:
        # The signed manifest goes up now, ahead of its files: safe because a
        # flavour release is not "latest" (updater.py reads latest/download),
        # so no client can find it until `finish` has uploaded the files and
        # made it latest.
        if not on_release:
            run(["gh", "release", "upload", tag, "-R", repo, "--clobber", signed])
        return
    publish_assets(repo, base, platform_tag, signed, assets_dir, kid)
    if not on_release:
        # The signed manifest goes on the MAIN release — updater.py's
        # _manifest_url() reads it from there via "latest/download". Last.
        run(["gh", "release", "upload", tag, "-R", repo, "--clobber", signed])


def publish_assets(repo: str, tag: str, platform_tag: str, signed: str,
                   assets_dir: str, kid: str = "u1") -> None:
    """Create the per-platform assets release(s) in `repo` and upload every
    file the signed manifest expects, confirming each part is complete."""
    version = _version_from_tag(tag)
    expected_by_part = expected_flat_names(signed, platform_tag, kid)
    parts = max(expected_by_part, default=1)
    for part in range(1, parts + 1):
        expected = expected_by_part.get(part, {})
        assets_tag = _assets_tag(tag, platform_tag, part)
        of = f", part {part} of {parts}" if parts > 1 else ""
        if not _release_exists(repo, assets_tag):
            run(["gh", "release", "create", assets_tag, "-R", repo,
                "--prerelease",
                "--title", f"{tag} update assets — {platform_tag}{of}",
                "--notes", f"Per-file update assets for {tag}, "
                          f"{platform_tag} only{of}. Not for direct "
                          f"download — see {tag} for the actual "
                          f"installers. Fetched by Prism's in-app updater; "
                          f"--prerelease so it never becomes GitHub's "
                          f"\"latest\" release."])
        still_missing = upload_missing(repo, assets_tag, assets_dir, expected)
        if still_missing:
            raise RuntimeError(
                f"{platform_tag}: {len(still_missing)} files still missing "
                f"from {assets_tag} after upload + retry: "
                f"{still_missing[:10]}")
        print(f"  {assets_tag}: confirmed all {len(expected)} files present "
             f"(version {version})")


#: Repositories that carry a copy of every release besides the one CI builds
#: in. Builds from 1.6.11 on ask the first of these, then the repo above; builds
#: up to 1.6.10 ask only the repo CI builds in (the old name), so BOTH must
#: always be published. The old one is never deleted, renamed or reused.
DEFAULT_MIRRORS = ("AlphaKore5/prism_gui",)

#: The DEV channel: its own repository, its own signing key id (udev2), no
#: mirror. A dev build trusts only that key and asks only that repository, so a
#: dev release can never reach a customer and a prod release can never reach a
#: dev machine. See docs/UPDATE-SYSTEM.md.
DEV_REPO = "AlphaKore5/prism_gui_dev"
DEV_KID = "udev2"
PROD_REPOS = ("HitarthTrivedi/prism_gui", "AlphaKore5/prism_gui")


def resolve_channel(repo: str | None, mirrors: list[str] | None,
                    no_mirror: bool, dev: bool) -> tuple[str, list[str], str]:
    """(source repo, mirror repos, signing kid) for this run, or ValueError.

    The point is to make the dev/prod mix-up impossible rather than unlikely:
    --dev signs with the dev key id and refuses a prod repository, and a run
    without --dev refuses the dev repository.
    """
    if dev:
        repo = repo or DEV_REPO
        if repo in PROD_REPOS:
            raise ValueError(f"--dev refuses the production repository {repo!r}")
        if mirrors:
            raise ValueError("--dev has no mirror")
        return repo, [], DEV_KID
    repo = repo or PROD_REPOS[0]
    if repo == DEV_REPO or repo.endswith("_dev"):
        raise ValueError(f"{repo!r} is the dev repository: add --dev (it signs "
                         "with the dev key), or name a production repository")
    return repo, ([] if no_mirror else list(mirrors or DEFAULT_MIRRORS)), "u1"


def mirror_platform(mirror: str, tag: str, work: str, platform_tag: str,
                    source_repo: str) -> None:
    """Copy one platform's SIGNED manifest and per-file assets to `mirror`.

    Nothing is re-signed: the manifest is byte-for-byte the one already on the
    source release, so both repositories serve identical bytes (which is what
    makes a client able to fall from one to the other). Order matters here and
    is the reverse of the source repo's: the assets go up first and the
    manifest LAST, so a client that finds the manifest never then finds its
    files missing.
    """
    signed = os.path.join(work, f"manifest.{platform_tag}.signed")
    assets_dir = os.path.join(work, f"update-assets-{platform_tag}")
    if not os.path.isfile(signed) or not os.path.isdir(assets_dir):
        raise RuntimeError(f"nothing to mirror for {platform_tag}: run the "
                           f"source release first (missing {signed} or {assets_dir})")
    if not _release_exists(mirror, tag):
        run(["gh", "release", "create", tag, "-R", mirror, "--target", "main",
             "--title", tag,
             "--notes", f"Update files for {tag}, mirrored from {source_repo}. "
                        f"Installers are on {source_repo}."])
    publish_assets(mirror, tag, platform_tag, signed, assets_dir)
    run(["gh", "release", "upload", tag, "-R", mirror, "--clobber", signed])


FLAVOUR_NOTES = """{display} {version}, a DEV build for testers (repository {repo}).

- The installers are unsigned: Windows SmartScreen warns on first launch (More info, Run anyway).
- It needs a licence key that includes this build's add-ons.
- A dev build starts empty and keeps its data in its own folder.
- Built from commit {target}.
"""


def create_flavour_release(repo: str, tag: str, run_id: str, flavour: str,
                           target: str, work: str,
                           platforms: list[tuple[str, str]]) -> None:
    """The human-facing release of one flavour: its installers and its unsigned
    manifests, from the manual CI run that built (and tested) them. Created
    NOT as "latest" (--make-latest decides that, once, at the end), at the
    commit `target`, so the tag is the commit that was built."""
    version = _version_from_tag(flavour_tags(tag, flavour)[1])
    files: list[str] = []
    for platform_tag, matrix_os in platforms:
        dest = os.path.join(work, f"installers-{FL.update_channel(platform_tag, flavour)}")
        if not (os.path.isdir(dest) and os.listdir(dest)):
            run(["gh", "run", "download", run_id, "-R", repo,
                 "-n", artifact_names(matrix_os, flavour)[0], "-D", dest])
        files += sorted(os.path.join(dest, n) for n in os.listdir(dest))
    if not _release_exists(repo, tag):
        run(["gh", "release", "create", tag, "-R", repo, "--target", target,
             "--title", f"{FL.identity(flavour)['display']} {version}",
             "--notes", FLAVOUR_NOTES.format(
                 display=FL.identity(flavour)["display"], version=version,
                 repo=repo, target=target[:7]),
             "--latest=false"])
    upload_one_by_one(repo, tag, files)


def _asset_sizes(repo: str, tag: str) -> dict:
    """{asset name: size in bytes} of what `tag` already holds."""
    out = subprocess.run(
        ["gh", "release", "view", tag, "-R", repo, "--json", "assets",
         "--jq", ".assets[]|[.name,.size]|@tsv"],
        capture_output=True, text=True, check=True).stdout
    return {n: int(sz) for n, sz in (ln.split("\t") for ln in out.splitlines() if ln)}


def upload_one_by_one(repo: str, tag: str, files: list[str], tries: int = 4) -> None:
    """Upload each file on its own, again if it times out, never one that is
    already there at the same size. All of a flavour's installers in ONE
    `gh release upload` share the uplink and starve each other: the first
    attempt (v2.0.0-studio, 26 Nov 2026) died with "HTTP 408: Upload body timed
    out due to inactivity" after ~2.3 GB, and nothing was resumable."""
    have = _asset_sizes(repo, tag)
    for path in files:
        if have.get(os.path.basename(path)) == os.path.getsize(path):
            continue
        for attempt in range(1, tries + 1):
            try:
                run(["gh", "release", "upload", tag, "-R", repo, "--clobber", path])
                break
            except subprocess.CalledProcessError:
                if attempt == tries:
                    raise
                time.sleep(5 * attempt)


def carry_signed_manifests(repo: str, tag: str, from_tags: list[str],
                           work: str, keep: frozenset = frozenset()) -> None:
    """Put the signed manifests of other releases on `tag` as well.

    updater.py reads releases/latest/download/manifest.<channel>.signed, and
    a repository has ONE latest release. With one release per flavour, the
    latest one must therefore carry every channel's signed manifest, or the
    other flavours (and the complete Prism's 1.8.x clients) find no manifest
    and never see an update. Byte-for-byte copies: nothing is re-signed.

    `keep` names the signed files THIS run just made (its own channels). An
    older release of the same flavour carries an older manifest under the very
    same name; copying it over would put 2.0.0 back as the newest version."""
    dest = os.path.join(work, "carried")
    os.makedirs(dest, exist_ok=True)
    for src in from_tags:
        if src == tag:
            continue
        run(["gh", "release", "download", src, "-R", repo,
             "-p", "manifest.*.signed", "-D", dest, "--clobber"])
    carried = sorted(n for n in os.listdir(dest)
                     if n.endswith(".signed") and n not in keep)
    if carried:
        run(["gh", "release", "upload", tag, "-R", repo, "--clobber"]
            + [os.path.join(dest, n) for n in carried])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("tag", help="Release tag, e.g. v1.4.0")
    p.add_argument("run_id", help="The CI run id that built this tag")
    p.add_argument("--dev", action="store_true",
                   help=f"Publish the DEV channel: repo {DEV_REPO}, signed "
                        f"with key id {DEV_KID}, no mirror. Never mixes with prod.")
    p.add_argument("--repo", default=None,
                   help="The repository CI built the tag in. Stays the OLD "
                        "name: every build up to 1.6.10 reads only this one.")
    p.add_argument("--mirror", action="append", metavar="OWNER/REPO",
                   help="Also publish to this repository (repeatable). "
                        f"Default: {', '.join(DEFAULT_MIRRORS)}")
    p.add_argument("--no-mirror", action="store_true",
                   help="Publish to --repo only. Builds from 1.6.11 then "
                        "reach the organisation repo's fallback only.")
    p.add_argument("--work-dir", default=None,
                   help="Where to download/sign into (default: a fresh "
                        "temp dir, left in place so a failure can be "
                        "inspected or resumed by hand)")
    p.add_argument("--force", action="store_true",
                   help="Re-sign and re-upload a platform even if the "
                        "release already has its .signed manifest")
    p.add_argument("--only", action="append", metavar="PLATFORM",
                   choices=[t for t, _ in PLATFORMS],
                   help="Release just this platform (repeatable), in the "
                        "order given — e.g. --only windows-x64 to do Windows "
                        "first. Default: every platform, in table order")
    p.add_argument("--flavour", choices=FLAVOURS, default="complete",
                   help="Release one flavour build (dev only): tag v<ver>-<flavour>, "
                        "installers from the manual CI run, update files under its "
                        "own channel. Default: the complete Prism, as always.")
    p.add_argument("--target", default=None, metavar="SHA",
                   help="--flavour: the full commit id the run built; the release "
                        "tag is created at it")
    p.add_argument("--carry-from", action="append", metavar="TAG", default=[],
                   help="Also put every signed manifest of release TAG on this "
                        "release (repeatable): `latest` serves them all")
    p.add_argument("--stage", choices=("all", "open", "sign", "finish"), default="all",
                   help="--flavour only. all: everything on this machine (default). "
                        "open (CI): create the release, upload installers and "
                        "unsigned manifests. sign (your PC, needs the key): sign and "
                        "upload the manifests, nothing big. finish (CI, no key): "
                        "upload the update files, carry manifests, set latest.")
    p.add_argument("--make-latest", action="store_true",
                   help="Make this release GitHub's \"latest\" once it is complete")
    args = p.parse_args(argv)
    if args.flavour != "complete":
        if not args.dev:
            p.error("--flavour is dev only for now: flavour releases are not "
                    "built for production")
        if not args.target or len(args.target) != 40 or \
                any(c not in "0123456789abcdef" for c in args.target):
            p.error("--flavour needs --target <the full 40-character commit id>")
        try:
            flavour_tags(args.tag, args.flavour)
        except ValueError as e:
            p.error(str(e))
    if args.stage != "all" and args.flavour == "complete":
        p.error("--stage is for --flavour releases")
    try:
        args.repo, mirrors, kid = resolve_channel(
            args.repo, args.mirror, args.no_mirror, args.dev)
    except ValueError as e:
        p.error(str(e))

    # No upfront "key must be set" check: a platform whose signed manifest
    # already exists (the common re-run case — everything but a genuinely
    # new version) needs no key at all, only a human running this on their
    # signing machine has any business setting it, and do_platform() below
    # raises a clear, specific error the one time it's actually needed —
    # signing a platform for the first time — rather than this function
    # guessing upfront whether any platform will need it.

    work = args.work_dir or tempfile.mkdtemp(prefix="prism-release-")
    os.makedirs(work, exist_ok=True)
    print(f"Working directory: {work}\n")

    done, failed = [], []
    table = dict(PLATFORMS)
    wanted = ([(t, table[t]) for t in args.only] if args.only else PLATFORMS)
    if args.flavour != "complete" and args.stage in ("all", "open"):
        create_flavour_release(args.repo, args.tag, args.run_id, args.flavour,
                               args.target, work, wanted)
    if args.stage == "open":
        return 0
    for platform_tag, matrix_os in wanted:
        print(f"── {platform_tag} " + "─" * max(1, 40 - len(platform_tag)))
        try:
            do_platform(args.repo, args.tag, args.run_id, work,
                       platform_tag, matrix_os, args.force, kid,
                       **({} if args.flavour == "complete"
                          else {"flavour": args.flavour,
                                **({"sign_only": True} if args.stage == "sign" else {})}))
            done.append(platform_tag)
            print(f"✓ {platform_tag} done\n")
        except (subprocess.CalledProcessError, RuntimeError) as e:
            print(f"✗ {platform_tag} failed: {e}\n", file=sys.stderr)
            failed.append(platform_tag)

    if args.stage == "sign":
        print(f"signed and uploaded: {done or '(none)'}  failed: {failed or '(none)'}")
        return 1 if failed else 0
    if done and not failed and args.carry_from:
        carry_signed_manifests(
            args.repo, args.tag, args.carry_from, work,
            frozenset(f"manifest.{FL.update_channel(t, args.flavour)}.signed"
                      for t, _ in wanted))
    if done and not failed and args.make_latest:
        run(["gh", "release", "edit", args.tag, "-R", args.repo, "--latest"])

    mirror_failed = []
    for mirror in mirrors:
        for platform_tag in done:       # only what the source release completed
            print(f"── mirror {mirror}: {platform_tag} " + "─" * 10)
            try:
                mirror_platform(mirror, args.tag, work, platform_tag, args.repo)
                print(f"✓ {mirror} {platform_tag} done\n")
            except (subprocess.CalledProcessError, RuntimeError) as e:
                print(f"✗ {mirror} {platform_tag} failed: {e}\n", file=sys.stderr)
                mirror_failed.append(f"{mirror}:{platform_tag}")

    print("── summary " + "─" * 30)
    print(f"done:   {done or '(none)'}")
    print(f"failed: {failed or '(none)'}")
    if mirrors:
        print(f"mirror: {mirrors}  failed: {mirror_failed or '(none)'}")
    if failed:
        print(f"\nRe-run the same command to retry — work is kept at {work}")
        return 1
    if mirror_failed:
        print("\nThe source release is complete; the mirror is not. Builds "
              "from 1.6.11 fall back to the source repo meanwhile. Re-run the "
              "same command to finish the mirror.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

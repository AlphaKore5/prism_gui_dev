"""Public keys that licence tokens are verified against.

Public keys are not secrets — publishing them is harmless. The matching private
keys live only in the licence server's secret store, and nowhere else, ever.

Rotation: tokens carry a `kid`, and this module holds a map rather than a
single key, so a new signing key can be introduced while tokens signed with the
old one still verify. The order is always:

    1. ship a build containing BOTH public keys
    2. wait until customers have updated
    3. only then start signing with the new kid

Signing with a kid that shipped builds do not know locks out every customer who
has not updated, which is the failure this map exists to prevent.
"""
from __future__ import annotations

import channel
import paths

# Production keys. Signed tokens issued by api.alphakore.in verify against
# these, in every build.
PRODUCTION: dict[str, str] = {
    "k1": "5c1133a2f92978d0b2813efa5e5405b84f9081a30d0d369d5ebe50645d5ba280",
}

# Development and staging keys.
#
# These are trusted ONLY when running from source. A frozen build ignores them
# completely — see public_keys() below. That is not belt-and-braces: the dev
# private key lives in a working tree and gets copied around, so a release
# build that honoured it would ship a universal skeleton key for the whole
# product. The exclusion is the only thing making it safe for this to exist.
DEVELOPMENT: dict[str, str] = {
    "dev1": "4d9841e8c8d8f133c6789f0afa1eab2b7eac395e94404d0a662c68622880dbb0",
}


def public_keys() -> dict[str, str]:
    """The keys this build will accept tokens from."""
    if paths.is_frozen():
        return dict(PRODUCTION)
    return {**PRODUCTION, **DEVELOPMENT}


# ── update-manifest keys (see update_manifest.py) ──────────────────────────
#
# A SEPARATE key pair from the licence keys above, on purpose — this is
# update-research-inapp-download.md §5.2 requirement #2, the single most
# important property of the whole in-app-update design. The licence signing
# key (`k1`'s private half) lives in the licence server's environment
# (Render), which is reachable by anything that can reach or compromise that
# server. A key that can make every customer's Prism download-and-swap-in
# new files must NOT be that key, or a license-server compromise becomes a
# supply-chain compromise. UPDATE_PRODUCTION's private half must be generated
# offline, on a machine that never runs the licence server or a CI job that
# can also cut a release, and stored the way `prod-signing-key.hex` is stored
# today (password manager + a sealed paper copy) — never pasted into Render,
# never into a CI secret.
#
# UPDATE_PRODUCTION is intentionally EMPTY. Filling it in is a one-time human
# ceremony (generate the pair, sign nothing with it from any networked
# machine, publish only the public half here), not something to do from a
# coding session. Until it holds a real key, no frozen build can verify any
# manifest — see update_public_keys() below — which is the correct default
# posture: a build that can't verify a manifest simply can't self-update, the
# same fail-closed behaviour public_keys() already gives an unknown `kid`.
UPDATE_PRODUCTION: dict[str, str] = {
    # Generated offline 2026-08-30. The matching private half lives only in
    # the release engineer's password manager — it must never appear in this
    # repo, in a CI secret, or in Render's environment.
    "u1": "49f27ccbfba0e52b62f1244ba63c2a54bf81fa3ff13d9d88be802dbc68496d4e",
}

# Development update-signing key (kid udev2). Trusted ONLY by a frozen DEV
# build (channel.CHANNEL == "dev") and by source runs; a prod build does not
# contain it. Unlike its predecessor (udev1, whose private half was a test
# fixture in a working tree), the private half of udev2 is kept like a real
# key -- outside the repo, never in a prod build's trust list -- because a
# dev-trusting binary that ever reached a customer would accept whatever it
# signs. Do not add this to UPDATE_PRODUCTION, and do not ship a dev build.
UPDATE_DEVELOPMENT: dict[str, str] = {
    "udev2": "0b059146aae977b638e59e24b6fea80296eb49ccfc412b312e303847f91e0506",
}


def update_public_keys() -> dict[str, str]:
    """The keys this build will accept an update manifest from. Same
    frozen/dev split as public_keys(), and the same fail-closed shape: an
    empty UPDATE_PRODUCTION means a frozen build accepts no manifest at all
    until a real production key is generated and published here.

    A frozen DEV-channel build (channel.CHANNEL, set only by the build) trusts
    the development key and NOTHING else, and a frozen prod build trusts the
    production key and nothing else. Neither can be updated from the other's
    manifests. The one thing that makes a dev-trusting binary safe is that it
    is never shipped to a customer: tests/test_channel_keys.py pins the repo's
    CHANNEL to "prod", and packaging/build.py only flips it for an explicit
    PRISM_CHANNEL=dev build."""
    if paths.is_frozen():
        if channel.is_dev():
            return dict(UPDATE_DEVELOPMENT)
        return dict(UPDATE_PRODUCTION)
    return {**UPDATE_PRODUCTION, **UPDATE_DEVELOPMENT}

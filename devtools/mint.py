#!/usr/bin/env python3
"""Mint licence keys and tokens — development and test only.

This is the licence server's signing logic, living here until the backend
exists. It moves to the server repo unchanged; the client must never gain the
ability to mint anything.

NOT SHIPPED. devtools/ is absent from packaging/prism.spec, so nothing here can
reach a build. It also holds a private signing key, which is why
devtools/dev-signing-key.hex is gitignored — the key it signs with is only
trusted when Prism runs from source (see licensing/keys.py).

    python3 devtools/mint.py keygen
    python3 devtools/mint.py key
    python3 devtools/mint.py token --days 10 --features core,boq
    python3 devtools/mint.py vector
    python3 devtools/mint.py flavour --flavour sales    # run_flavour.sh calls this
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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

from cryptography.hazmat.primitives import serialization as _ser
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from licensing import device, keyformat, lease as L, token as T
import workspace as W

HERE = os.path.dirname(os.path.abspath(__file__))
# PRISM_DEV_SIGNING_KEY lets a git worktree use the one key file kept in the
# main checkout (devtools/run_flavour.sh sets it) instead of a second copy.
KEY_PATH = (os.environ.get("PRISM_DEV_SIGNING_KEY")
            or os.path.join(HERE, "dev-signing-key.hex"))
# The DEVELOPMENT kid in licensing/keys.py whose public half matches
# KEY_PATH. Signing under any other kid produces a token every build rejects
# (bad_signature), which is what happened with dev1.
DEV_KID = "dev2"
VECTOR_PATH = os.path.join(os.path.dirname(HERE), "licensing", "testdata",
                           "vector.json")
DAY = 86400


def load_private(kid: str | None = None) -> Ed25519PrivateKey:
    """The dev private key. With `kid`, also refuse unless its public half is
    the one licensing/keys.py holds for that kid, so a mismatch fails here
    and not as bad_signature inside the app."""
    with open(KEY_PATH, "r", encoding="utf-8") as f:
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(f.read().strip()))
    if kid is not None:
        from licensing import keys
        if keys.DEVELOPMENT.get(kid) != public_hex(private):
            raise SystemExit(
                f"mint: {KEY_PATH} is not the private half of DEVELOPMENT "
                f"kid {kid!r} in licensing/keys.py, so the app would reject "
                f"the token. Sign with --kid {DEV_KID}.")
    return private


def public_hex(private: Ed25519PrivateKey) -> str:
    return private.public_key().public_bytes(
        _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()


def sign(claims: dict, private: Ed25519PrivateKey) -> str:
    """Produce a token. Uses licensing.token's own helpers on purpose: signer
    and verifier sharing one encoder is what stops the two drifting apart."""
    payload_b64 = T.b64u_encode(
        json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = private.sign(T.signing_input(payload_b64))
    return f"{T.PREFIX}.{payload_b64}.{T.b64u_encode(signature)}"


def parse_features(raw: str) -> list[str]:
    """--features, split and CHECKED against what the app actually gates on.

    Two names look obvious and are wrong, and both padlock something in
    front of a customer:

      · **BOM is gated on `boq`.** There is no "bom" feature — BOQ & BOM is
        one add-on, and main_window._open_bom() calls _authorized_then("boq",
        …). So `--features core,bom` names a key the app never checks, and
        BOM stays padlocked.
      · **Email inquiry automation is gated on `inbox`.** `email` is a DIFFERENT
        row — the draft-and-send screen. Minting `email` and expecting the
        automation screen to open gets a padlock.

    Both are invisible until the moment someone clicks, which on demo day is
    in front of the person being sold to. A typo should fail here, at mint
    time, in front of a developer who can retype it.
    """
    import plans

    wanted = [f.strip() for f in raw.split(",") if f.strip()]
    unknown = [f for f in wanted if f not in plans.FEATURES]
    if unknown:
        known = ", ".join(sorted(plans.FEATURES))
        hint = ""
        if "bom" in unknown:
            hint += "\n  BOQ & BOM is one add-on: use 'boq'. There is no 'bom' feature."
        if "email" in unknown:      # defensive: 'email' is real, but pair it
            hint += "\n  Email inquiry automation needs 'inbox'; 'email' is the draft screen."
        raise SystemExit(
            f"unknown feature(s): {', '.join(unknown)}\n"
            f"  known features: {known}{hint}")
    # 'email' IS a real feature, so the check above cannot catch the commonest
    # mistake of all — asking for it and expecting Email AUTOMATION.
    if "email" in wanted and "inbox" not in wanted:
        print("mint: note — 'email' is the draft-and-send screen. Email "
              "AUTOMATION needs 'inbox', which is not in this licence.",
              file=sys.stderr)

    # The other half of the same trap: a feature that IS declared and that
    # nothing actually gates on. 'bom' was the live example until it was
    # dropped from plans.FEATURES (BOQ & BOM is one add-on on 'boq'). Nothing
    # is ungated today; the check stays for the next key somebody declares
    # before the gate exists.
    #
    # Computed from the source rather than listed here, so it cannot go stale
    # the moment somebody adds a gate — the entire point being that a
    # hardcoded list is how the first two traps survived.
    for name in sorted(set(wanted) & _ungated_features()):
        print(f"mint: note — nothing in Prism is gated on {name!r}, so this "
              "flag unlocks nothing. Check which feature the screen you mean "
              "actually asks for.", file=sys.stderr)
    return wanted


def _ungated_features() -> set:
    """Declared in plans.FEATURES, but nothing calls _authorized_then on it.

    'core' is excluded: it is the base entitlement and is legitimately never
    gated on directly.
    """
    import re
    import plans

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(here, "main_window.py"), encoding="utf-8") as f:
            gated = set(re.findall(r'_authorized_then\(\s*"([a-z]+)"', f.read()))
    except OSError:
        return set()
    if not gated:                       # the regex stopped matching — say
        return set()                    # nothing rather than warn on everything
    return {f for f in plans.FEATURES if f not in gated} - {"core"}


def build_claims(args, device_fp: str) -> dict:
    now = int(args.now or time.time())
    license_end = now + args.days * DAY
    # A token never outlives the licence: the last one of a 10-day trial
    # expires on day 10, not seven days after it was issued.
    token_exp = min(now + args.ttl * DAY, license_end)
    return {
        "kid": args.kid,
        "sub": args.license_id,
        "cust": args.customer,
        "plan": args.plan,
        "kind": args.kind,
        "feat": parse_features(args.features),
        "seats": args.seats,
        "dev": device_fp,
        "iat": now,
        "nbf": now,
        "exp": token_exp,
        "lend": license_end,
        # Trials get no grace: day 10 means day 10, which is the date in the
        # email we sent. Grace absorbs a late bank transfer on a paid account.
        "grace": 0 if args.kind == "trial" else args.grace,
    }


def cmd_keygen(args) -> int:
    if os.path.exists(KEY_PATH) and not args.force:
        print(f"{KEY_PATH} already exists. Pass --force to replace it "
              "(every token signed with the old key stops verifying).")
        return 1
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(_ser.Encoding.Raw, _ser.PrivateFormat.Raw,
                                _ser.NoEncryption()).hex()
    with open(KEY_PATH, "w", encoding="utf-8") as f:
        f.write(raw)
    os.chmod(KEY_PATH, 0o600)
    print(f"private key → {KEY_PATH}")
    print(f"public key  → {public_hex(private)}")
    print("\nPaste the public key into licensing/keys.py under DEVELOPMENT.")
    return 0


def cmd_key(args) -> int:
    for _ in range(args.count):
        print(keyformat.generate())
    return 0


def cmd_token(args) -> int:
    private = load_private(args.kid)
    device_fp = args.device or device.fingerprint(
        os.path.join(os.path.expanduser("~"), ".prism"))[0]
    claims = build_claims(args, device_fp)
    print(sign(claims, private))
    if args.verbose:
        print(json.dumps(claims, indent=2), file=sys.stderr)
    return 0


def cmd_install(args) -> int:
    """Mint a token and write it straight into ~/.prism/license.json, so a dev
    build behaves as though it had been activated."""
    from licensing import store

    private = load_private(args.kid)
    user_dir = os.path.join(os.path.expanduser("~"), ".prism")
    device_fp = device.fingerprint(user_dir)[0]
    claims = build_claims(args, device_fp)
    data = store.load(user_dir)
    data["token"] = sign(claims, private)
    data["license_id"] = args.license_id
    store.save(user_dir, data)
    store.touch_clock(user_dir)
    print(f"Installed a {args.days}-day {args.kind} licence for "
          f"{claims['feat']} → {store.path(user_dir)}")
    return 0


def flavour_features(name: str) -> list[str]:
    """`core` plus the licence feature of every add-on in flavour `name`.

    Read from addons/flavours/<name>.py, the modules the registry loads, so
    it cannot drift from what that flavour contains. Feature keys are not
    add-on keys (inquiry rides `inbox`, whatsapp `marketing`, motion `reel`,
    bom `boq`); the manifests are where that mapping lives.
    """
    import importlib

    import flavour as F

    if name not in F.FLAVOURS:
        raise SystemExit(f"unknown flavour {name!r}. Known: {', '.join(F.FLAVOURS)}")
    module = importlib.import_module(f"addons.flavours.{name}")
    return ["core", *sorted({m.feature for m in module.MANIFESTS if m.feature} - {"core"})]


def cmd_flavour(args) -> int:
    """For devtools/run_flavour.sh: make sure this sandbox holds a licence for
    flavour `--flavour`, minting a dev one only if it does not.

    Run it with the launcher's HOME and PRISM_HOME: isolate_home() then gives
    the same licence folder and device fingerprint the app will use. Prints
    ONE word on stdout for the script:

      minted  a new dev licence was written
      dev     a dev-key licence already covers this flavour; left alone
      real    a licence signed by a PRODUCTION key is here; left alone
    """
    import channel
    import paths
    from licensing import keys, store, status as S

    channel.isolate_home()
    user_dir = paths.user_dir()
    wanted = flavour_features(args.flavour)
    device_fp = device.fingerprint(user_dir)[0]
    data = store.load(user_dir)
    raw = (data.get("token") or "").strip()
    if raw:
        try:
            claims = T.verify(raw, device_fp=device_fp,
                              public_keys=keys.public_keys())
        except T.TokenError:
            claims = None
        if claims is not None and claims.get("kid") not in keys.DEVELOPMENT:
            print("real")
            return 0
        if (claims is not None
                and S.resolve(claims).status == S.VALID
                and set(wanted) <= set(claims.get("feat") or ())
                and not S.clock_rolled_back(int(data.get("last_seen_utc") or 0))):
            print("dev")
            return 0

    private = load_private(DEV_KID)
    mint_args = argparse.Namespace(
        now=0, days=args.days, ttl=args.days, kid=DEV_KID,
        license_id="lic_dev", customer=f"Dev Build ({args.flavour})",
        plan="dev", kind="paid", features=",".join(wanted), seats=1, grace=0)
    claims = build_claims(mint_args, device_fp)
    data["token"] = sign(claims, private)
    data["license_id"] = mint_args.license_id
    store.save(user_dir, data)
    store.touch_clock(user_dir)
    print(f"mint: {args.days}-day dev licence ({DEV_KID}) for "
          f"{', '.join(claims['feat'])} -> {store.path(user_dir)}", file=sys.stderr)
    print("minted")
    return 0


def sign_lease(claims: dict, private: Ed25519PrivateKey) -> str:
    """Produce an authorisation lease. Uses licensing.lease's own helpers, for
    the same reason sign() uses licensing.token's: one encoder shared by the
    signer and the verifier is what stops the two drifting apart."""
    payload_b64 = L.encode_payload(claims)
    signature = private.sign(L.signing_input(payload_b64))
    return f"{L.PREFIX}.{payload_b64}.{T.b64u_encode(signature)}"


def cmd_lease(args) -> int:
    """Mint an authorisation lease, and optionally install it.

    The licence server does this in production (app/signing.py issue_lease).
    This exists so the client half can be exercised without running uvicorn —
    and so a dev build can be put into a specific lease STATE (fresh, in
    grace, stale) on purpose, which is the only practical way to look at the
    offline behaviour with your own eyes.

        python3 devtools/mint.py lease --license-id lic_dev --install
        python3 devtools/mint.py lease --license-id lic_dev --ttl -60 --install
    """
    from licensing import authorization as A
    from licensing import store

    private = load_private(args.kid)
    user_dir = os.path.join(os.path.expanduser("~"), ".prism")
    device_fp = args.device or device.fingerprint(user_dir)[0]
    now = int(args.now or time.time())
    claims = L.build_claims(
        kid=args.kid, license_id=args.license_id, device_fp=device_fp,
        scope=[s.strip() for s in args.scopes.split(",") if s.strip()],
        features=parse_features(args.features),
        metered=args.metered, jti=args.jti, now=now, ttl=args.ttl,
        offline=args.offline)
    lease_str = sign_lease(claims, private)

    if args.install:
        A.remember(user_dir, lease_str, now=now)
        print(f"Installed a lease for {claims['scope']} → "
              f"{A.path(user_dir)}")
    else:
        print(lease_str)
    if args.verbose:
        print(json.dumps(claims, indent=2), file=sys.stderr)
    return 0


def cmd_vector(args) -> int:
    """Regenerate the committed test vector.

    The vector is the one thing proving the signer and the verifier agree, on
    every platform and in a frozen build. Regenerating it invalidates that
    proof, so only do it when the token or lease format itself changes.

    It covers BOTH credentials. A build where token verification survived
    freezing but lease verification did not would open perfectly and then
    refuse every protected operation — which looks exactly like a revoked
    licence, and would be diagnosed as one.
    """
    private = Ed25519PrivateKey.generate()
    claims = {
        "kid": "vector", "sub": "lic_vector", "cust": "Vector Test Ltd",
        "plan": "business", "kind": "paid",
        "feat": ["core", "boq", "email"], "seats": 5,
        "dev": "0123456789abcdef",
        "iat": 1750000000, "nbf": 1750000000,
        "exp": 1750604800, "lend": 1781536000, "grace": 3,
        "pk": "", "petag": "",
    }
    lease_claims = L.build_claims(
        kid="vector", license_id="lic_vector", device_fp=claims["dev"],
        scope=["core", "workflow", "boq"],
        features=["core", "boq", "email"], metered=False,
        jti="lse_vector0001", now=1750000000, ttl=1800, offline=3600)
    vector = {
        "_comment": "Committed test vector. Signer and verifier must agree on "
                    "these exact bytes. Regenerate only if the token or lease "
                    "format changes — see devtools/mint.py vector.",
        "public_key": public_hex(private),
        "device_fp": claims["dev"],
        "token": sign(claims, private),
        "claims": claims,
        "lease": sign_lease(lease_claims, private),
        "lease_claims": lease_claims,
    }
    os.makedirs(os.path.dirname(VECTOR_PATH), exist_ok=True)
    with open(VECTOR_PATH, "w", encoding="utf-8") as f:
        json.dump(vector, f, indent=2)
        f.write("\n")
    print(f"wrote {VECTOR_PATH}")
    return 0


def cmd_designation(args) -> int:
    """Mint the second key: the one that says which job a member does.

    Signed with the same private key as the licence token but under its own
    version prefix, so a designation key can never be replayed as a licence or
    the other way round. See licensing/designation.py for the verifier.

    The member id defaults to role+name, which is also the name of their
    folder in the workspace — so `ls members/` reads as an org chart.

        python3 devtools/mint.py designation \\
            --license-id lic_8842 --role sales --name "Ravi Patel"
    """
    import roles as R
    from licensing import designation as D

    if not R.get(args.role):
        print(f"unknown role {args.role!r}. Known: {', '.join(R.ORDER)}",
              file=sys.stderr)
        return 2

    private = load_private(args.kid)
    mid = args.mid or W.member_id(args.role, args.name)
    claims = D.build_claims(org=args.license_id, mid=mid, role=args.role,
                            name=args.name, kid=args.kid,
                            now=int(args.now or time.time()))
    payload_b64 = D.encode_payload(claims)
    signature = private.sign(D.signing_input(payload_b64))
    key = f"{D.PREFIX}.{payload_b64}.{T.b64u_encode(signature)}"

    print(key)
    print(f"\n  {args.name or '(no name)'} — {R.label(args.role)}\n"
          f"  member id : {mid}\n"
          f"  licence   : {args.license_id}\n"
          f"  folder    : members/{mid}/", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keygen").add_argument("--force", action="store_true")

    key_parser = sub.add_parser("key", help="generate licence key(s)")
    key_parser.add_argument("--count", type=int, default=1)

    for name, help_text in (("token", "print a signed token"),
                            ("install", "write one into ~/.prism")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--days", type=int, default=10, help="licence length")
        p.add_argument("--ttl", type=int, default=7, help="token lifetime, days")
        p.add_argument("--features", default="core,boq,email,reel")
        p.add_argument("--kind", default="trial", choices=["trial", "paid"])
        p.add_argument("--plan", default="trial")
        p.add_argument("--customer", default="Dev Build")
        p.add_argument("--license-id", default="lic_dev")
        p.add_argument("--seats", type=int, default=1)
        p.add_argument("--grace", type=int, default=3)
        p.add_argument("--kid", default=DEV_KID)
        p.add_argument("--now", type=int, default=0)
        p.add_argument("--device", default="")
        p.add_argument("--verbose", action="store_true")

    lease_parser = sub.add_parser(
        "lease", help="mint an authorisation lease (and optionally install it)")
    lease_parser.add_argument("--license-id", default="lic_dev")
    lease_parser.add_argument("--scopes", default="core,workflow,boq,email,reel")
    lease_parser.add_argument("--features", default="core,boq,email,reel")
    lease_parser.add_argument("--metered", action="store_true",
                              help="mark the licence as quota'd, so the client "
                                   "goes to the server for plan actions")
    # Negative values are the point of this being adjustable: --ttl -60 mints a
    # lease that expired a minute ago, which is how the GRACE path gets looked
    # at without waiting half an hour for one to lapse.
    lease_parser.add_argument("--ttl", type=int, default=1800,
                              help="seconds until expiry (negative = already "
                                   "expired, for testing GRACE and STALE)")
    lease_parser.add_argument("--offline", type=int, default=3600,
                              help="offline grace after expiry, seconds")
    lease_parser.add_argument("--jti", default="lse_dev00000001")
    lease_parser.add_argument("--kid", default=DEV_KID)
    lease_parser.add_argument("--now", type=int, default=0)
    lease_parser.add_argument("--device", default="")
    lease_parser.add_argument("--install", action="store_true",
                              help="write it into ~/.prism/authorization.json")
    lease_parser.add_argument("--verbose", action="store_true")

    des = sub.add_parser("designation",
                         help="mint a member's designation key")
    des.add_argument("--license-id", required=True,
                     help="the company licence this key belongs to")
    des.add_argument("--role", required=True, help="a key from roles.ROLES")
    des.add_argument("--name", default="", help="the person's name")
    des.add_argument("--mid", default="",
                     help="member id / folder name (default: role-name)")
    des.add_argument("--kid", default=DEV_KID)
    des.add_argument("--now", type=int, default=0)

    fl = sub.add_parser("flavour", help="ensure this sandbox has a dev licence "
                                        "for a flavour (devtools/run_flavour.sh)")
    fl.add_argument("--flavour", required=True)
    fl.add_argument("--days", type=int, default=30)

    sub.add_parser("vector", help="regenerate the committed test vector")

    args = parser.parse_args()
    return {
        "keygen": cmd_keygen, "key": cmd_key, "token": cmd_token,
        "install": cmd_install, "vector": cmd_vector,
        "designation": cmd_designation, "lease": cmd_lease,
        "flavour": cmd_flavour,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())

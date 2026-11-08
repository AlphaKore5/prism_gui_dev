"""Roles, designation keys, and who is allowed to read whose work.

Two things are being defended here, and they are not equally strong — the
tests are grouped so the difference stays visible.

  The role itself is CRYPTOGRAPHIC. It arrives in a signed designation key and
  cannot be changed by editing a file, retyping a key, or taking someone
  else's key and rewriting the role inside it. Those are the Forgery tests,
  and they are the real guarantee.

  The folder split is POLICY. workspace.readable_members() is the one function
  that decides who sees what, and every screen goes through it. Prism will not
  show a member another member's work — but if the workspace is on a share
  their laptop can reach, the filesystem still will. The Visibility tests pin
  the policy; they are not claiming an OS-level boundary.

Qt is not needed here: none of this is UI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey)

import roles as R  # noqa: E402
import theme  # noqa: E402
import workspace as W  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))
from core import agents as A  # noqa: E402
from licensing import designation as D, token as T  # noqa: E402
from licensing.token import TokenError  # noqa: E402

ORG = "lic_demo"


class Signing:
    """A throwaway signing key, and the minting half of designation.py."""

    def __init__(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        self.keys = {"t1": self.public}

    def mint(self, role: str, name: str, org: str = ORG, kid: str = "t1") -> str:
        claims = D.build_claims(org=org, mid=W.member_id(role, name),
                                role=role, name=name, kid=kid,
                                now=int(time.time()))
        payload = D.encode_payload(claims)
        signature = self.private.sign(D.signing_input(payload))
        return f"{D.PREFIX}.{payload}.{T.b64u_encode(signature)}"


class Keys(unittest.TestCase):
    def setUp(self):
        self.signer = Signing()

    def test_a_minted_key_verifies_and_carries_the_job(self):
        key = self.signer.mint("sales", "Ravi Patel")
        claims = D.verify(key, org=ORG, public_keys=self.signer.keys)
        self.assertEqual(claims["role"], "sales")
        self.assertEqual(claims["name"], "Ravi Patel")
        self.assertEqual(claims["mid"], "sales-ravi-patel")

    def test_the_member_id_is_the_folder_name(self):
        """Minting and the roster derive the id the same way, so nobody has to
        copy an id between the key we issue and the team list."""
        key = self.signer.mint("marketing", "Nita Shah")
        claims = D.verify(key, org=ORG, public_keys=self.signer.keys)
        self.assertEqual(claims["mid"], W.member_id("marketing", "Nita Shah"))

    def test_shape_check_does_not_need_the_signing_key(self):
        self.assertTrue(D.looks_like_one(self.signer.mint("sales", "R")))
        self.assertFalse(D.looks_like_one("PRSM-4K2XA-9WQ7M-3TYRB-8HNVE"))


class Forgery(unittest.TestCase):
    """The guarantee. Each of these is a way somebody might try to give
    themselves a role they were not issued."""

    def setUp(self):
        self.signer = Signing()
        self.key = self.signer.mint("sales", "Ravi Patel")

    def _repack(self, key: str, **changes) -> str:
        """Rewrite the payload, keep the original signature — the obvious
        attack, and the one a hex editor makes easy."""
        _prefix, payload, signature = key.split(".")
        claims = json.loads(D.b64u_decode(payload))
        claims.update(changes)
        return f"{D.PREFIX}.{D.encode_payload(claims)}.{signature}"

    def test_promoting_yourself_to_manager_fails(self):
        with self.assertRaises(TokenError) as caught:
            D.verify(self._repack(self.key, role="manager"),
                     org=ORG, public_keys=self.signer.keys)
        self.assertEqual(caught.exception.code, "bad_signature")

    def test_pointing_yourself_at_another_folder_fails(self):
        with self.assertRaises(TokenError):
            D.verify(self._repack(self.key, mid="owner-the-boss"),
                     org=ORG, public_keys=self.signer.keys)

    def test_another_companys_key_fails(self):
        with self.assertRaises(TokenError) as caught:
            D.verify(self.key, org="lic_someone_else",
                     public_keys=self.signer.keys)
        self.assertEqual(caught.exception.code, "wrong_org")

    def test_a_key_signed_by_someone_else_fails(self):
        other = Signing()
        with self.assertRaises(TokenError):
            D.verify(other.mint("owner", "Impostor"), org=ORG,
                     public_keys=self.signer.keys)

    def test_a_designation_key_cannot_be_replayed_as_a_licence(self):
        """Both are Ed25519 over a base64 payload. The version prefix is
        inside the signed bytes precisely so one cannot stand in for the
        other."""
        with self.assertRaises(TokenError) as caught:
            T.verify(self.key, device_fp="anything",
                     public_keys=self.signer.keys)
        self.assertEqual(caught.exception.code, "version")

    def test_a_licence_token_cannot_be_used_as_a_designation_key(self):
        payload = T.b64u_encode(b'{"kid":"t1","role":"owner"}')
        licence = (f"{T.PREFIX}.{payload}."
                   f"{T.b64u_encode(self.signer.private.sign(T.signing_input(payload)))}")
        with self.assertRaises(TokenError):
            D.verify(licence, org=ORG, public_keys=self.signer.keys)

    def test_rubbish_is_rejected_without_raising_anything_else(self):
        for junk in ("", "not a key", "PRSD1.", "PRSD1.a.b", "PRSD1.!!!.???"):
            with self.assertRaises(TokenError):
                D.verify(junk, org=ORG, public_keys=self.signer.keys)


class Visibility(unittest.TestCase):
    """The access rule, in the one function every screen has to ask."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-ws-")
        self.cfg = {"workspace_root": self.tmp}
        W.save_team([
            {"mid": "owner-anil", "name": "Anil", "role": "owner"},
            {"mid": "sales-ravi", "name": "Ravi", "role": "sales"},
            {"mid": "marketing-nita", "name": "Nita", "role": "marketing"},
        ], self.cfg)

    def _who(self, mid, role):
        return {"mid": mid, "name": "", "role": role, "org": ORG,
                "admin": R.is_admin(role)}

    def test_a_working_member_sees_only_themselves(self):
        visible = W.readable_members(self.cfg, self._who("sales-ravi", "sales"))
        self.assertEqual([m["mid"] for m in visible], ["sales-ravi"])

    def test_a_working_member_cannot_read_a_colleague(self):
        me = self._who("sales-ravi", "sales")
        self.assertFalse(W.may_read(self.cfg, me, "marketing-nita"))
        self.assertTrue(W.may_read(self.cfg, me, "sales-ravi"))

    def test_an_admin_sees_the_whole_team(self):
        visible = W.readable_members(self.cfg, self._who("owner-anil", "owner"))
        self.assertEqual({m["mid"] for m in visible},
                         {"owner-anil", "sales-ravi", "marketing-nita"})

    def test_an_admin_sees_themselves_first(self):
        """History opens on the admin's own work, not on whoever sorts first."""
        visible = W.readable_members(self.cfg,
                                     self._who("owner-anil", "owner"))
        self.assertEqual(visible[0]["mid"], "owner-anil")
        self.assertTrue(visible[0]["is_self"])

    def test_a_manager_is_an_admin_too(self):
        visible = W.readable_members(self.cfg,
                                     self._who("owner-anil", "manager"))
        self.assertGreater(len(visible), 1)

    def test_an_admin_sees_a_folder_the_roster_forgot(self):
        """The folder is the fact; the roster is only the description. A
        member whose entry was never added must not become invisible."""
        os.makedirs(os.path.join(self.tmp, "members", "ops-stray", "runs"))
        visible = W.readable_members(self.cfg,
                                     self._who("owner-anil", "owner"))
        self.assertIn("ops-stray", {m["mid"] for m in visible})

    def test_a_personal_copy_sees_one_folder(self):
        visible = W.readable_members(self.cfg, W.SOLO and
                                     {"mid": W.SOLO, "role": "", "admin": False})
        self.assertEqual([m["mid"] for m in visible], [W.SOLO])


class Folders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-ws-")
        self.cfg = {"workspace_root": self.tmp}
        # runs_dir() falls back to ~/.prism/runs when a member's own folder has
        # no run records yet (the upgrade path). On a machine that has used
        # Prism that is the developer's REAL history, so "a member gets their
        # own folder" failed everywhere except CI. Point the fallback at an
        # empty home.
        empty_home = tempfile.mkdtemp(prefix="prism-home-")
        patch = mock.patch.object(
            W.paths, "user_dir",
            side_effect=lambda *p: os.path.join(empty_home, ".prism", *p))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_personal_copy_keeps_using_the_old_runs_folder(self):
        """The upgrade path. An existing customer opening History after this
        change must find their runs where they left them, not an empty list."""
        with mock.patch.object(W.paths, "user_dir",
                               side_effect=lambda *p: os.path.join("/home/x/.prism", *p)):
            # os.path.join, not a literal: the mock builds the path with
            # os.path.join, so on Windows it comes back with backslashes and a
            # hardcoded "/home/x/.prism/runs" can never match. The assertion is
            # about WHICH folder, not which separator.
            self.assertEqual(W.runs_dir(W.SOLO, {}),
                             os.path.join("/home/x/.prism", "runs"))

    def test_a_member_gets_their_own_runs_folder(self):
        got = W.runs_dir("sales-ravi", self.cfg)
        self.assertEqual(got, os.path.join(self.tmp, "members", "sales-ravi",
                                           "runs"))

    def test_two_members_never_share_a_folder(self):
        self.assertNotEqual(W.runs_dir("sales-ravi", self.cfg),
                            W.runs_dir("marketing-nita", self.cfg))

    def test_ensure_member_creates_what_a_run_needs(self):
        W.ensure_member("sales-ravi", self.cfg)
        for sub in ("runs", "files"):
            self.assertTrue(os.path.isdir(
                os.path.join(self.tmp, "members", "sales-ravi", sub)))
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, W.COMPANY_DIR)))

    def test_the_roster_survives_a_round_trip(self):
        W.save_team([{"mid": "sales-ravi", "name": "Ravi", "role": "sales"}],
                    self.cfg)
        self.assertEqual(W.load_team(self.cfg),
                         [{"mid": "sales-ravi", "name": "Ravi",
                           "role": "sales"}])

    def test_a_corrupt_roster_reads_as_empty_not_as_a_crash(self):
        with open(W.team_path(self.cfg), "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        self.assertEqual(W.load_team(self.cfg), [])

    def test_upsert_replaces_rather_than_duplicating(self):
        W.upsert_member(self.cfg, "sales-ravi", "Ravi", "sales")
        W.upsert_member(self.cfg, "sales-ravi", "Ravi Patel", "sales")
        team = W.load_team(self.cfg)
        self.assertEqual(len(team), 1)
        self.assertEqual(team[0]["name"], "Ravi Patel")

    def test_a_shared_looking_root_is_recognised(self):
        """Only used to word the UI honestly — a member should be told when
        their work lands somewhere the manager can read."""
        self.assertTrue(W.is_shared(
            {"workspace_root": "/Users/x/Google Drive/My Drive/Prism"}))
        self.assertFalse(W.is_shared({"workspace_root": self.tmp}))

    def test_member_ids_are_folder_safe(self):
        for name in ("Ravi Patel", "R&D / Ops", "../../etc/passwd", "  "):
            mid = W.member_id("sales", name)
            self.assertNotIn("/", mid)
            self.assertNotIn("\\", mid)
            self.assertNotIn("..", mid)


class RoleTable(unittest.TestCase):
    def test_exactly_the_admin_roles_are_admin(self):
        self.assertEqual({r.key for r in R.ordered() if r.admin},
                         {"owner", "manager"})

    def test_every_ordered_role_exists(self):
        for key in R.ORDER:
            self.assertIn(key, R.ROLES)

    def test_every_role_has_a_distinct_colour(self):
        hues = [r.hue for r in R.ordered()]
        self.assertEqual(len(hues), len(set(hues)))

    def test_no_role_reuses_prisms_own_blue(self):
        """A role that looked exactly like a personal copy would defeat the
        point of colouring them at all."""
        for role in R.ordered():
            self.assertNotEqual(role.hue, R.GENERAL_HUE)

    def test_recolouring_never_changes_contrast(self):
        """Only the hue moves. If lightness drifted, some role would end up
        with unreadable text somewhere and nobody would find it."""
        import colorsys

        def lightness(value):
            value = value.lstrip("#")
            r, g, b = (int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))
            return colorsys.rgb_to_hls(r, g, b)[1]

        for role in R.ordered():
            for original, replaced in theme.role_palette(role.hue).items():
                self.assertAlmostEqual(lightness(original), lightness(replaced),
                                       places=6)

    def test_an_unknown_role_falls_back_to_prisms_own_colour(self):
        self.assertEqual(R.hue("chief vibes officer"), R.GENERAL_HUE)
        self.assertEqual(R.hue(""), R.GENERAL_HUE)
        self.assertFalse(R.is_admin("chief vibes officer"))

    def test_the_stylesheet_swap_leaves_the_neutrals_alone(self):
        """Roles change the accent, not the whole design. The canvas, the
        greys and the error red are shared and must not move."""
        # theme.ACCENT, not a literal: hardcoding the brand hex here meant
        # that changing the accent broke this test rather than the thing it
        # guards, which is the swap leaving NEUTRALS alone.
        qss = ("QWidget { background: #f2f2f3; color: #1d1f20; }"
               f"#primaryBtn {{ background: {theme.ACCENT}; }}"
               "#err { color: #fdeeee; }")
        out = theme.role_stylesheet(qss, 142)
        self.assertIn("#f2f2f3", out)
        self.assertIn("#1d1f20", out)
        self.assertIn("#fdeeee", out)
        self.assertNotIn(theme.ACCENT, out)

    def test_prisms_own_hue_is_a_no_op(self):
        qss = f"#primaryBtn {{ background: {theme.ACCENT}; }}"
        self.assertEqual(theme.role_stylesheet(qss, R.GENERAL_HUE), qss)

    def test_default_agents_only_covers_the_roles_stages(self):
        catalogue = {"research": {"agents": ["Perplexity", "ChatGPT"]},
                     "leads": {"agents": ["Apollo"]},
                     "development": {"agents": ["Claude"]}}
        picked = R.default_agents("sales", catalogue)
        self.assertEqual(picked.get("leads"), "Apollo")
        # Sales does not build software, so it must not be handed a coder.
        self.assertNotIn("development", picked)

    def test_only_marketing_gets_the_whole_visual_chain(self):
        """The claim each role's stage list is making. Marketing ships
        artwork; nobody else does."""
        for role in R.ordered():
            if role.key == "marketing":
                self.assertIn("visual", role.stages)
            else:
                self.assertNotIn("media", role.stages)

    def test_a_fresh_marketing_member_defaults_to_prism_image(self):
        """Against the REAL catalogue, not a fake one: marketing is the
        role with "visual" in its stages, so a brand-new member's first
        picked tool for it must be Prism Image (FLUX 3 Klein) — the
        owner's own "default and first choice" instruction, 2026-11-07 —
        not ChatGPT or any browser tool."""
        picked = R.default_agents("marketing", A.CATEGORIES)
        self.assertEqual(picked.get("visual"), "Prism Image")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""A flavour build updates from its own channel only, and never as another one.

Before 2026-11-25 updater.py built every URL from platform_tag() alone, so a
Studio app asked for the complete Prism's manifest and, being offered a newer
version, would have replaced itself with Complete. These run the real updater
and manifest code (no network: `fetch` is injected, keys are throwaway):

  * which URLs each build asks for, literally, and that complete's are the ones
    it always used;
  * which manifests it accepts, whatever name they are served under;
  * that two flavours sharing ~/.prism and the folder beside their program
    folders cannot pick up each other's staged update or update history.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import apply_update                                       # noqa: E402
import flavour                                            # noqa: E402
import update_manifest as UM                              # noqa: E402
import updater                                            # noqa: E402
from test_updater_phase1 import Harness                   # noqa: E402

REAL = [f for f in flavour.FLAVOURS if f != "complete"]
WIN = "windows-x64"
GITHUB = "https://github.com/AlphaKore5/prism_gui/releases"
OLD_REPO = "HitarthTrivedi/prism_gui"


def built_as(name: str):
    """This process as a build of flavour `name` (the constant build.py bakes)."""
    return mock.patch.object(flavour, "FLAVOUR", name)


def _entry(path: str, data: bytes) -> dict:
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "mode": 0}


def manifest_for(name: str, version: str, files=(), tag: str = WIN) -> dict:
    """What packaging/manifest.py writes for a build of that flavour."""
    m = {"version": version, "files": list(files)}
    if name != "complete":
        m["update_channel"] = flavour.update_channel(tag, name)
    return m


class OnWindows(Harness):
    """The phase 1 harness (temp ~/.prism, throwaway keys) as a Windows client."""

    def setUp(self):
        super().setUp()
        p = mock.patch.object(updater, "platform_tag", return_value=WIN)
        p.start()
        self.addCleanup(p.stop)
        self.asked: list[str] = []

    def serve(self, table: dict):
        def fetch(url, *, timeout):
            self.asked.append(url)
            if url not in table:
                raise ConnectionError(url)
            return table[url]
        return fetch


class EachBuildAsksForItsOwnFiles(OnWindows):

    def test_completes_urls_are_byte_for_byte_todays(self):
        with built_as("complete"):
            self.assertEqual(updater._manifest_url(),
                             f"{GITHUB}/latest/download/manifest.windows-x64.signed")
            self.assertEqual(
                updater._file_url("1.8.10", "_internal/a.dat"),
                f"{GITHUB}/download/v1.8.10-assets-windows-x64/windows-x64___internal__a.dat")
            self.assertEqual(
                updater._file_url("1.8.10", "_internal/a.dat", 2, OLD_REPO),
                f"https://github.com/{OLD_REPO}/releases/download/"
                "v1.8.10-assets-windows-x64-2/windows-x64___internal__a.dat")

    def test_a_flavours_urls_name_the_flavour_everywhere(self):
        for name in REAL:
            ch = f"windows-x64-{name}"
            with self.subTest(flavour=name), built_as(name):
                self.assertEqual(updater._manifest_url(),
                                 f"{GITHUB}/latest/download/manifest.{ch}.signed")
                self.assertEqual(updater._manifest_url(OLD_REPO),
                                 f"https://github.com/{OLD_REPO}/releases/latest/download/"
                                 f"manifest.{ch}.signed")
                self.assertEqual(updater._file_url("1.8.10", "Prism.exe"),
                                 f"{GITHUB}/download/v1.8.10-assets-{ch}/{ch}__Prism.exe")
                self.assertEqual(updater._file_url("1.8.10", "Prism.exe", 2),
                                 f"{GITHUB}/download/v1.8.10-assets-{ch}-2/{ch}__Prism.exe")

    def test_the_assets_part_number_never_reads_as_another_channel(self):
        tags = {updater._assets_release_tag("1.8.10", flavour.update_channel(WIN, f), part)
                for f in flavour.FLAVOURS for part in range(1, UM.MAX_ASSET_PARTS + 1)}
        self.assertEqual(len(tags), len(flavour.FLAVOURS) * UM.MAX_ASSET_PARTS)

    def test_outcome_reports_keep_the_platform_the_licence_server_accepts(self):
        """Its `platform` field is at most 24 characters: a channel name there
        (macos-arm64-app-engineering) would be rejected and the report dropped."""
        for name in flavour.FLAVOURS:
            with built_as(name):
                updater.note_outcome("ok", "1.8.10")
                entry = updater._load()["outbox"][-1]
            self.assertEqual(entry["platform"], WIN)

    def test_the_signing_tool_keeps_one_downgrade_history_per_channel(self):
        sys.path.insert(0, os.path.join(ROOT, "devtools"))
        import sign_manifest
        lanes = {sign_manifest._tracker_key(f"manifest.{flavour.update_channel(WIN, f)}.unsigned.json")
                 for f in flavour.FLAVOURS}
        self.assertEqual(lanes, {WIN} | {f"{WIN}-{f}" for f in REAL})


class OnlyItsOwnManifestIsAccepted(OnWindows):

    def offer(self, build: str, manifest: dict):
        """`manifest`, genuinely signed, served under `build`'s own name."""
        with built_as(build):
            table = {updater._manifest_url(): self._sign(manifest).encode()}
            return updater.check_for_update(running="1.0.0", fetch=self.serve(table))

    def test_every_build_against_every_other_builds_manifest(self):
        for build in flavour.FLAVOURS:
            for other in flavour.FLAVOURS:
                with self.subTest(build=build, manifest=other):
                    m = manifest_for(other, "2.0.0")
                    if build == other:
                        self.assertEqual(self.offer(build, m).version, "2.0.0")
                    else:
                        with self.assertRaisesRegex(updater.UpdateError, "different Prism build"):
                            self.offer(build, m)

    def test_a_flavour_refuses_its_own_name_on_another_platform(self):
        for build in REAL:
            with self.assertRaises(updater.UpdateError):
                self.offer(build, manifest_for(build, "2.0.0", tag="linux-x64"))

    def test_a_flavour_refuses_an_empty_or_odd_channel(self):
        for bad in (None, "", 3, ["windows-x64-studio"], "windows-x64", "WINDOWS-X64-STUDIO"):
            with self.assertRaises(updater.UpdateError, msg=repr(bad)):
                self.offer("studio", {"version": "2.0.0", "files": [], "update_channel": bad})

    def test_complete_accepts_its_own_name_if_a_manifest_ever_carries_it(self):
        m = {"version": "2.0.0", "files": [], "update_channel": WIN}
        self.assertEqual(self.offer("complete", m).version, "2.0.0")
        with self.assertRaises(updater.UpdateError):
            self.offer("complete", {"version": "2.0.0", "files": [], "update_channel": None})

    def test_a_flavour_never_asks_for_completes_manifest_even_when_its_own_is_missing(self):
        with built_as("complete"):
            completes = {updater._manifest_url(r): self._sign(manifest_for("complete", "2.0.0")).encode()
                         for r in updater._repos()}
        for build in REAL:
            self.asked.clear()
            with built_as(build):
                self.assertIsNone(updater.check_for_update(
                    running="1.0.0", fetch=self.serve(completes)))
            self.assertEqual(len(self.asked), len(updater._repos()))
            for url in self.asked:
                self.assertTrue(url.endswith(f"/manifest.windows-x64-{build}.signed"), url)

    def test_a_wrong_manifest_on_one_host_does_not_stop_the_right_one_on_the_next(self):
        for build in flavour.FLAVOURS:
            wrong = "studio" if build != "studio" else "complete"
            with self.subTest(build=build), built_as(build):
                first, second = updater._repos()
                table = {updater._manifest_url(first): self._sign(manifest_for(wrong, "3.0.0")).encode(),
                         updater._manifest_url(second): self._sign(manifest_for(build, "2.0.0")).encode()}
                got = updater.check_for_update(running="1.0.0", fetch=self.serve(table))
                self.assertEqual(got.version, "2.0.0")

    def test_another_builds_manifest_cannot_withdraw_this_ones_version(self):
        """A refused manifest's `revoked` list is not believed either."""
        with built_as("studio"):
            first, second = updater._repos()
            bad = {**manifest_for("complete", "3.0.0"), "revoked": ["2.0.0"]}
            table = {updater._manifest_url(first): self._sign(bad).encode(),
                     updater._manifest_url(second): self._sign(manifest_for("studio", "2.0.0")).encode()}
            with mock.patch.object(updater, "_revoked_seen", set()) as seen:
                updater.check_for_update(running="1.0.0", fetch=self.serve(table))
                self.assertEqual(seen, set())


class FlavoursInstalledSideBySideStaySeparate(OnWindows):
    """They share ~/.prism (self.tmp) and the folder their installs sit in."""

    def setUp(self):
        super().setUp()
        self.programs = tempfile.mkdtemp(prefix="prism-programs-")
        self.addCleanup(shutil.rmtree, self.programs, True)

    def install(self, build: str) -> str:
        d = os.path.join(self.programs, flavour.identity(build)["name"])
        os.makedirs(d, exist_ok=True)
        return d

    def stage(self, build: str, version: str = "2.0.0"):
        """A whole quiet update of `build`, left waiting for the restart."""
        data = f"{build} {version}".encode()
        m = manifest_for(build, version, [_entry("Prism.exe", data)])
        with built_as(build), mock.patch.object(updater, "install_dir",
                                                return_value=self.install(build)):
            table = {updater._manifest_url(): self._sign(m).encode(),
                     updater._file_url(version, "Prism.exe"): data}
            with mock.patch.object(updater.app_meta, "VERSION", "1.0.0"):
                return updater.auto_stage(fetch=self.serve(table))

    def test_each_waits_with_its_own_update_of_the_same_version(self):
        staged = {f: self.stage(f) for f in flavour.FLAVOURS}
        self.assertEqual(len({s.stage_dir for s in staged.values()}), len(flavour.FLAVOURS))
        for f, s in staged.items():
            with self.subTest(flavour=f), built_as(f):
                ready = updater.ready_update(running="1.0.0")
                self.assertEqual(ready.stage_dir, s.stage_dir)
                with open(os.path.join(ready.stage_dir, "Prism.exe")) as fh:
                    self.assertEqual(fh.read(), f"{f} 2.0.0")

    def test_completes_names_are_todays(self):
        s = self.stage("complete")
        self.assertEqual(s.stage_dir, os.path.join(self.programs, ".prism-update-staging", "2.0.0"))
        with built_as("complete"):
            self.assertEqual(os.path.basename(updater.state_path()), "update_state.json")

    def test_a_stage_of_another_flavour_is_never_applied_even_if_the_state_names_it(self):
        """What one shared update_state.json did: Studio's waiting update in
        Complete's hands (and the reverse)."""
        for build, other in (("complete", "studio"), ("studio", "complete"), ("sales", "engineering")):
            theirs = self.stage(other, "2.1.0")
            with self.subTest(build=build, stage=other), built_as(build):
                updater._save({**updater._load(), "ready": {"version": theirs.version,
                                                            "stage_dir": theirs.stage_dir}})
                self.assertIsNone(updater.ready_update(running="1.0.0"))

    def test_one_flavours_history_does_not_hold_back_another(self):
        with built_as("complete"):
            updater.note_installed("2.0.0")          # Complete updated first
            updater.note_rollback("2.1.0")           # and 2.1.0 failed for Complete
            updater.dismiss("2.0.0")
        for version in ("2.0.0", "2.1.0"):
            with built_as("studio"):
                table = {updater._manifest_url(): self._sign(manifest_for("studio", version)).encode()}
                got = updater.check_for_update(running="1.0.0", fetch=self.serve(table))
                self.assertEqual(got.version, version)
                self.assertFalse(updater.dismissed("2.0.0"))

    def test_the_state_files_are_per_flavour(self):
        names = set()
        for f in flavour.FLAVOURS:
            with built_as(f):
                updater.note_installed("2.0.0")
                names.add(os.path.basename(updater.state_path()))
                self.assertTrue(os.path.isfile(updater.state_path()))
        self.assertEqual(names, {"update_state.json", "update_state-studio.json",
                                 "update_state-sales.json", "update_state-engineering.json"})

    def test_the_windows_helper_scripts_are_per_flavour(self):
        helper = os.path.join(self.tmp, "updates")
        names = {}
        with mock.patch.object(apply_update, "_windows_helper_dir", return_value=helper):
            for f in flavour.FLAVOURS:
                with built_as(f):
                    d = self.install(f)
                    names[f] = os.path.basename(apply_update.write_windows_helper(
                        4242, d, d + "-staged", d + ".old", os.path.join(d, "Prism.exe")))
            self.assertEqual(names["complete"], "apply.bat")
            for f in flavour.FLAVOURS:
                with open(os.path.join(helper, names[f]), encoding="utf-8") as fh:
                    self.assertIn(os.path.join(self.install(f), "Prism.exe"), fh.read(), f)


class ManifestToolWritesTheChannel(unittest.TestCase):

    def run_tool(self, *extra) -> dict:
        sys.path.insert(0, os.path.join(ROOT, "packaging"))
        import manifest
        work = tempfile.mkdtemp(prefix="prism-manifest-")
        self.addCleanup(shutil.rmtree, work, True)
        tree = os.path.join(work, "Prism")
        os.makedirs(tree)
        with open(os.path.join(tree, "Prism.exe"), "w") as f:
            f.write("x")
        out = os.path.join(work, "m.json")
        self.assertEqual(manifest.main([tree, "2.0.0", "-o", out, *extra]), 0)
        with open(out) as f:
            return json.load(f)

    def test_only_when_asked(self):
        self.assertEqual(set(self.run_tool()), {"version", "files"})
        m = self.run_tool("--update-channel", "windows-x64-sales")
        self.assertEqual(m["update_channel"], "windows-x64-sales")

    def test_the_signature_covers_it(self):
        from test_updater_phase1 import _keypair
        priv, pub = _keypair()
        token = UM.sign(manifest_for("sales", "2.0.0"), priv, kid="u1")
        payload = UM.verify(token, public_keys={"u1": pub})
        self.assertEqual(payload["update_channel"], "windows-x64-sales")
        head, body, sig = token.split(".")
        forged = json.loads(UM.b64u_decode(body))
        forged["update_channel"] = "windows-x64"
        body = UM.b64u_encode(json.dumps(forged, sort_keys=True).encode())
        with self.assertRaises(UM.ManifestError) as got:
            UM.verify(".".join((head, body, sig)), public_keys={"u1": pub})
        self.assertEqual(got.exception.code, "bad_signature")


if __name__ == "__main__":
    unittest.main()

"""prism.spec leaves out what Prism never reads (step 1 clean-up, 2026-11-24).

Measured on the 1.8.9 Windows build: two OpenCV video plugins (69 MB, from
two OpenCV versions sharing one cv2/ folder), 611 Google API discovery
documents (114 MB) for the one API Prism uses, and the macOS DWG converter
(22 MB) inside a Windows build. This proves, WITHOUT a PyInstaller build:

  * one OpenCV: opencv-python and opencv-python-headless are held to the same
    version, and no OpenCV video plugin is collected;
  * only the discovery documents of APIs the code builds are kept;
  * each platform collects only its own dwg2dxf, at the path core/boq.py
    reads in a frozen build, and Linux collects none.

The spec runs in a subprocess with PyInstaller's classes replaced by
recorders (as in test_spec_flavours.py) and sys.platform set to the platform
being built. Analysis() is fed hook-style entries (what hook-cv2 and
hook-googleapiclient.model add) so the post-Analysis filter is what is
tested. Whether the trimmed app still works is main._trimmed_bundle_checks(),
run inside the real build by packaging/smoke_test.py; the tests at the bottom
run the same checks from source.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

ENGINE = os.path.join(ROOT, "prism_terminal")
VENDOR = os.path.join(ENGINE, "core", "vendor", "dwg2dxf")

# Packages the spec imports in try/except; made unimportable so a spec run
# under another platform's sys.platform does not load real native modules.
_ABSENT = ("cadquery", "OCP", "playwright", "imageio_ffmpeg", "keyring",
           "google_auth_oauthlib", "googleapiclient", "audioop", "audioop_lts")

_DRIVER = r"""
import json, os, sys, types, importlib.util
sys.path.insert(0, {root!r})
import app_meta, flavour, licensing.keys, addons.registry   # before the switch
for n in {absent!r}:
    sys.modules[n] = None
hooks = types.ModuleType("PyInstaller.utils.hooks")
hooks.collect_data_files = lambda pkg, *a, **k: []
hooks.collect_submodules = lambda pkg, *a, **k: []
hooks.collect_all = lambda pkg, *a, **k: ([], [], [])
for n in ("PyInstaller", "PyInstaller.utils"):
    sys.modules[n] = types.ModuleType(n)
sys.modules["PyInstaller.utils.hooks"] = hooks
importlib.util.find_spec = lambda name, *a, **k: True    # every package "installed"
sys.platform = {plat!r}

S = {sep!r}
HOOKED_DATAS = [
    ("googleapiclient%sdiscovery_cache%sdocuments%s%s" % (S, S, S, n), "/src/" + n, "DATA")
    for n in ("drive.v3.json", "drive.v2.json", "gmail.v1.json", "sheets.v4.json")]
HOOKED_BINARIES = [
    ("cv2%scv2.pyd" % S, "/src/cv2.pyd", "BINARY"),
    ("cv2%sopencv_videoio_ffmpeg4110_64.dll" % S, "/src/a.dll", "BINARY"),
    ("cv2%sopencv_videoio_ffmpeg510_64.dll" % S, "/src/b.dll", "BINARY"),
    ("opencv_python.libs%slibavcodec.so" % S, "/src/libavcodec.so", "BINARY")]
seen, out = {{}}, {{}}
class A:
    def __init__(self, *args, **kw):
        seen.update(kw)
        self.datas = list(HOOKED_DATAS)
        self.binaries = list(HOOKED_BINARIES)
        self.pure, self.zipped_data, self.scripts = [], [], []
class Collect:
    def __init__(self, exe, binaries, datas, *a, **k):
        out["binaries"] = [t[0] for t in binaries]
        out["datas"] = [t[0] for t in datas]
class Stub:
    def __init__(self, *a, **k): pass
g = {{"SPEC": os.path.join({root!r}, "packaging", "prism.spec"),
     "Analysis": A, "PYZ": Stub, "EXE": Stub, "COLLECT": Collect, "BUNDLE": Stub,
     "__name__": "spec"}}
os.environ["PRISM_UNLICENSED_TEST_BUILD"] = "1"
exec(compile(open(g["SPEC"], encoding="utf-8").read(), g["SPEC"], "exec"), g)
out["inputs"] = [[s, d] for s, d in seen["datas"]]
print(json.dumps(out))
"""


def _spec(plat):
    sep = "\\" if plat == "win32" else "/"
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home,
                   QT_QPA_PLATFORM="offscreen")
        r = subprocess.run(
            [sys.executable, "-c", _DRIVER.format(
                root=ROOT, plat=plat, sep=sep, absent=list(_ABSENT))],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _norm(p):
    return p.replace("\\", "/")


_VENDOR_THERE = os.path.isdir(VENDOR)


class OneOpenCV(unittest.TestCase):
    """rapidocr-onnxruntime needs opencv-python, rapidocr opencv-python-headless;
    both write cv2/, so they must be the same version or the build is a mix."""

    def _pins(self, plat):
        pins = {}
        with open(os.path.join(ROOT, "constraints", plat + ".txt"), encoding="utf-8") as f:
            for line in f:
                m = re.fullmatch(r"(opencv[\w.\-]*)==(\S+)", line.strip())
                if m:
                    pins[m.group(1).lower().replace("_", "-")] = m.group(2)
        return pins

    def test_both_opencv_packages_are_pinned_to_one_version(self):
        for plat in ("linux-x64", "windows-x64"):
            with self.subTest(platform=plat):
                pins = self._pins(plat)
                self.assertEqual(set(pins), {"opencv-python", "opencv-python-headless"}, pins)
                self.assertEqual(len(set(pins.values())), 1, pins)
                # below 4.12: the macOS arm64 bundle could not load 4.14/5.0
                major, minor = (int(x) for x in pins["opencv-python"].split(".")[:2])
                self.assertLess((major, minor), (4, 12), pins)

    def test_requirements_hold_both_to_the_same_bound(self):
        with open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8") as f:
            lines = [l.split("#")[0].strip() for l in f]
        self.assertIn("opencv-python>=4.5,<4.12", lines)
        self.assertIn("opencv-python-headless>=4.5,<4.12", lines)

    def test_no_opencv_video_plugin_is_collected(self):
        for plat in ("win32", "linux", "darwin"):
            with self.subTest(platform=plat):
                out = _spec(plat)
                bins = [_norm(b) for b in out["binaries"]]
                self.assertIn("cv2/cv2.pyd", bins)            # OpenCV itself stays
                self.assertIn("opencv_python.libs/libavcodec.so", bins)
                self.assertEqual([b for b in bins if "opencv_videoio_ffmpeg" in b], [])

    def test_nothing_prism_runs_uses_opencv_video_io(self):
        # The plugin is loaded only by VideoCapture/VideoWriter.
        hits = []
        for folder, dirs, files in os.walk(ROOT):      # GUI and prism_terminal
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "tests", "__pycache__")]
            for n in files:
                if n.endswith(".py"):
                    p = os.path.join(folder, n)
                    with open(p, encoding="utf-8", errors="replace") as f:
                        if re.search(r"\bcv2\.(VideoCapture|VideoWriter)\b", f.read()):
                            hits.append(os.path.relpath(p, ROOT))
        self.assertEqual(hits, [])


class OnlyTheUsedDiscoveryDocuments(unittest.TestCase):

    def test_only_drive_v3_is_kept(self):
        out = _spec("linux")
        docs = [d for d in map(_norm, out["datas"]) if "discovery_cache/documents/" in d]
        self.assertEqual(docs, ["googleapiclient/discovery_cache/documents/drive.v3.json"])

    def test_every_api_the_code_builds_has_its_document_kept(self):
        with open(os.path.join(ROOT, "packaging", "prism.spec"), encoding="utf-8") as f:
            kept = re.search(r"_KEEP_DISCOVERY_DOCS = \(([^)]*)\)", f.read()).group(1)
        kept = set(re.findall(r'"([^"]+)"', kept))
        built = set()
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", ".venv", "tests", "__pycache__")]
            for n in files:
                if not n.endswith(".py"):
                    continue
                with open(os.path.join(folder, n), encoding="utf-8", errors="replace") as f:
                    src = f.read()
                if "googleapiclient" not in src:
                    continue
                for api, ver in re.findall(r'\bbuild\(\s*"(\w+)",\s*"(\w+)"', src):
                    built.add(f"{api}.{ver}.json")
        self.assertEqual(built, {"drive.v3.json"})      # integrations/gdrive.py
        self.assertLessEqual(built, kept)


@unittest.skipUnless(_VENDOR_THERE, "prism_terminal submodule not checked out")
class EachPlatformItsOwnDwg2dxf(unittest.TestCase):

    def _vendor(self, out):
        return [(_norm(os.path.relpath(s, ENGINE)) if s.startswith(ENGINE) else s,
                 _norm(d)) for s, d in out["inputs"] if "dwg2dxf" in s or "dwg2dxf" in d]

    def test_windows_ships_win64_only_where_core_boq_looks(self):
        self.assertEqual(sorted(self._vendor(_spec("win32"))), [
            ("core/vendor/dwg2dxf/README.md", "core/vendor/dwg2dxf"),
            ("core/vendor/dwg2dxf/win64", "core/vendor/dwg2dxf/win64")])

    def test_macos_ships_macos_arm64_only(self):
        self.assertEqual(sorted(self._vendor(_spec("darwin"))), [
            ("core/vendor/dwg2dxf/README.md", "core/vendor/dwg2dxf"),
            ("core/vendor/dwg2dxf/macos-arm64", "core/vendor/dwg2dxf/macos-arm64")])

    def test_linux_ships_none(self):
        # core.boq has no bundled converter for Linux (_dwg2dxf_platform_tag).
        self.assertEqual(self._vendor(_spec("linux")), [])

    def test_the_vendor_folders_are_the_ones_core_boq_names(self):
        # If the engine adds a platform, the spec's table must learn it.
        self.assertEqual(sorted(d for d in os.listdir(VENDOR)
                                if os.path.isdir(os.path.join(VENDOR, d))),
                         ["macos-arm64", "win64"])
        import core_bridge as CB
        boq = CB.get_boq()
        for system, machine, tag in (("Windows", "AMD64", "win64"),
                                     ("Darwin", "arm64", "macos-arm64"),
                                     ("Linux", "x86_64", None)):
            with mock.patch.object(boq.platform, "system", return_value=system), \
                 mock.patch.object(boq.platform, "machine", return_value=machine):
                self.assertEqual(boq._dwg2dxf_platform_tag(), tag)


class TheFrozenChecksFromSource(unittest.TestCase):
    """main._trimmed_bundle_checks() is fatal in the frozen self-test; here it
    runs from source, under the suite's network guard."""

    def _checks(self):
        import main
        return dict((n.split(" — ")[0], (n, ok)) for n, ok in main._trimmed_bundle_checks())

    def test_drive_client_builds_without_the_network(self):
        name, ok = self._checks()["Google Drive client from its bundled discovery document"]
        self.assertTrue(ok, name)

    def test_opencv_does_the_ocr_image_operations(self):
        import main
        checks = main._trimmed_bundle_checks()
        cv = [(n, ok) for n, ok in checks if n.startswith("OpenCV")]
        self.assertEqual(len(cv), 1, checks)
        # The image operations must not be what fails; a developer venv with
        # two OpenCV versions fails the version half, which is the point.
        self.assertNotIn("Error", cv[0][0], cv)

    def test_opencv_check_fails_on_two_versions(self):
        import importlib.metadata as md
        import main
        fake = [mock.Mock(metadata={"Name": "opencv-python"}, version="4.11.0.86"),
                mock.Mock(metadata={"Name": "opencv-python-headless"}, version="5.1.0.95")]
        with mock.patch.object(md, "distributions", return_value=fake):
            cv = [c for c in main._trimmed_bundle_checks() if c[0].startswith("OpenCV")]
        self.assertFalse(cv[0][1], cv)
        fake[1].version = "4.11.0.86"
        with mock.patch.object(md, "distributions", return_value=fake):
            cv = [c for c in main._trimmed_bundle_checks() if c[0].startswith("OpenCV")]
        self.assertTrue(cv[0][1], cv)

    @unittest.skipUnless(_VENDOR_THERE, "prism_terminal submodule not checked out")
    def test_dwg_converter_found_for_each_bundled_platform(self):
        import core_bridge as CB
        import main
        boq = CB.get_boq()
        for tag in ("win64", "macos-arm64"):
            with mock.patch.object(boq, "_dwg2dxf_platform_tag", return_value=tag):
                got = [c for c in main._trimmed_bundle_checks() if "DWG" in c[0]]
            self.assertEqual(got, [(f"DWG converter bundled ({tag})", True)])
        with mock.patch.object(boq, "_dwg2dxf_platform_tag", return_value=None):
            self.assertFalse([c for c in main._trimmed_bundle_checks() if "DWG" in c[0]])


if __name__ == "__main__":
    unittest.main()

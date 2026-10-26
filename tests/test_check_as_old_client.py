"""devtools/check_as_old_client.py: does it tell the truth about whether a real
1.6.10 install would take a release? It runs the v1.6.10 updater code against a
local GitHub-shaped server (the same one the end-to-end tests use), so each way a
release can be invisible to 1.6.10 is reproduced and must be reported as a FAIL,
and a good release must PASS."""
from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "devtools"))
import e2e_update_harness as H                                  # noqa: E402
import check_as_old_client as C                                  # noqa: E402

_SKIP = H.skip_reason()


def run_tool(server, pub, *extra, repo=H.FALLBACK):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = C.main(["--repo", repo, "--platform", H.updater.platform_tag(),
                       "--trust", "test", "--test-pub", pub,
                       "--github-base", f"http://127.0.0.1:{server.port}", "--samples", "2", *extra])
    return code, buf.getvalue()


@unittest.skipIf(bool(_SKIP), _SKIP)
class WouldARealOldClientTakeIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sec, cls.pub = H.keypair()

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="oldclient-")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.server = H.FakeGitHub()
        self.addCleanup(self.server.stop)

    def release(self, version="1.6.12", **kw):
        return H.Release(self.work, version, H.ROOT, sec=self.sec, pub=self.pub, **kw)

    def test_a_release_in_the_repository_1_6_10_reads_passes(self):
        self.server.publish(self.release(), repos=(H.FALLBACK,))
        code, out = run_tool(self.server, self.pub, "--expect-version", "1.6.12")
        self.assertEqual(0, code, out)
        self.assertIn("PASS", out)
        self.assertIn("would be offered 1.6.12", out)

    def test_a_release_only_in_the_organisation_repository_is_invisible(self):
        self.server.publish(self.release(), repos=(H.PRIMARY,))
        code, out = run_tool(self.server, self.pub)
        self.assertEqual(1, code, out)
        self.assertIn("FAIL", out)
        self.assertIn("nothing to offer", out)

    def test_a_manifest_signed_with_another_key_is_refused(self):
        self.server.publish(self.release(), repos=(H.FALLBACK,))
        other_sec, other_pub = H.keypair()
        code, out = run_tool(self.server, other_pub)
        self.assertEqual(1, code, out)
        self.assertIn("FAIL", out)

    def test_a_tampered_manifest_is_refused(self):
        self.server.publish(self.release(), repos=(H.FALLBACK,))
        self.server.fault(H.FALLBACK, "forge")
        code, out = run_tool(self.server, self.pub)
        self.assertEqual(1, code, out)
        self.assertIn("FAIL", out)

    def test_a_file_whose_hash_does_not_match_is_reported(self):
        rel = self.release()
        self.server.publish(rel, repos=(H.FALLBACK,))
        name = sorted(os.listdir(rel.assets_dir))[0]
        self.server.fault(H.FALLBACK, "corrupt", name)
        code, out = run_tool(self.server, self.pub, "--samples", "50")
        self.assertEqual(1, code, out)
        self.assertIn("wrong size or hash", out)

    def test_a_version_that_is_not_newer_is_not_offered(self):
        self.server.publish(self.release("1.6.10"), repos=(H.FALLBACK,))
        code, out = run_tool(self.server, self.pub)
        self.assertEqual(1, code, out)
        self.assertIn("nothing to offer", out)

    def test_the_wrong_version_is_caught(self):
        self.server.publish(self.release("1.6.12"), repos=(H.FALLBACK,))
        code, out = run_tool(self.server, self.pub, "--expect-version", "1.6.13")
        self.assertEqual(1, code, out)
        self.assertIn("expected 1.6.13", out)

    def test_policy_fields_1_6_10_ignores_do_not_break_it(self):
        self.server.publish(self.release(policy={"rollout": 5, "min_updater": 2}),
                            repos=(H.FALLBACK,))
        code, out = run_tool(self.server, self.pub)
        self.assertEqual(0, code, out)
        self.assertIn("policy fields it ignores", out)


class Guardrails(unittest.TestCase):
    def test_it_refuses_a_dev_key_against_the_production_repository(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = C.main(["--trust", "dev"])
        self.assertEqual(2, code)
        self.assertIn("production keys only", buf.getvalue())


if __name__ == "__main__":
    unittest.main()

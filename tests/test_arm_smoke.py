"""devtools/arm_smoke.py is what the Windows-on-ARM job runs; keep it honest.

Runs its BOQ and Email groups for real (fake IMAP/SMTP server on 127.0.0.1,
generated DXF, made-up credentials) in a child process with its own sandbox
HOME, and checks the workflow file is wired to it.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ArmSmoke(unittest.TestCase):
    def test_boq_and_email_groups_pass_and_none_is_skipped_silently(self):
        out = tempfile.mkdtemp(prefix="prism-armsmoke-test-")
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "devtools", "arm_smoke.py"),
                            "--only", "boq,email", "--out", out],
                           env=env, capture_output=True, text=True, timeout=240)
        self.assertEqual(p.returncode, 0, (p.stdout + p.stderr)[-3000:])
        with open(os.path.join(out, "results.json"), encoding="utf-8") as f:
            results = json.load(f)["results"]
        by = {(r["group"], r["name"]): r["status"] for r in results}
        self.assertGreaterEqual(sum(1 for s in by.values() if s == "PASS"), 11, by)
        # only the DWG check may skip here (no sample given), and it says so
        skipped = [k for k, s in by.items() if s == "SKIP"]
        self.assertEqual([k[1] for k in skipped],
                         ["DWG converted by the bundled dwg2dxf, then measured"], skipped)

    def test_workflow_runs_on_the_arm_runner_and_calls_the_smoke(self):
        with open(os.path.join(ROOT, ".github", "workflows", "arm.yml"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("runs-on: windows-11-arm", text)
        self.assertIn("devtools/arm_smoke.py", text)
        self.assertIn("PRISM_SELFTEST", text + open(os.path.join(ROOT, "packaging", "smoke_test.py"),
                                                    encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()

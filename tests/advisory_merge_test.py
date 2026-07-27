"""End-to-end guard for the strict four-piece advisory merge workflow."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AdvisoryMergeTest(unittest.TestCase):
    def test_merge_preserves_gating_and_status_is_truthful(self):
        with tempfile.TemporaryDirectory() as reports:
            env = dict(os.environ, DATAVAL_REPORT_DIR=reports,
                       PYTHONDONTWRITEBYTECODE="1")
            generated = subprocess.run(
                [sys.executable, os.path.join(ROOT, "run.py")], cwd=ROOT,
                env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, generated.returncode,
                             generated.stdout + generated.stderr)

            pending = subprocess.run(
                [sys.executable, os.path.join(ROOT, "merge_advisory.py"), "--status"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(1, pending.returncode)

            before = {}
            for name in ("order", "subscription"):
                report_path = os.path.join(reports, f"{name}.report.json")
                with open(report_path, encoding="utf-8") as handle:
                    before[name] = json.load(handle)["gating_zone"]["findings"]
                with open(os.path.join(reports, f"{name}.advisory_result.json"),
                          "w", encoding="utf-8") as handle:
                    json.dump({"naming_semantic": [], "concept": [], "skills": {}},
                              handle, ensure_ascii=False)

            merged = subprocess.run(
                [sys.executable, os.path.join(ROOT, "merge_advisory.py")], cwd=ROOT,
                env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, merged.returncode, merged.stdout + merged.stderr)
            for name in ("order", "subscription"):
                with open(os.path.join(reports, f"{name}.report.json"),
                          encoding="utf-8") as handle:
                    payload = json.load(handle)
                self.assertEqual(before[name], payload["gating_zone"]["findings"])
                self.assertTrue(payload["meta"]["advisory_merged"])

            complete = subprocess.run(
                [sys.executable, os.path.join(ROOT, "merge_advisory.py"), "--status"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, complete.returncode,
                             complete.stdout + complete.stderr)


if __name__ == "__main__":
    unittest.main()

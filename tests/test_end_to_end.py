import asyncio
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from canarynet.cli import init
from canarynet.common import load_config, read_json, write_json
from canarynet.engine import check
from canarynet.report import junit, markdown

FIXTURE = Path(__file__).parent / "fixtures/adversarial_server.py"


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        init(self.root)
        self.path = self.root / "canarynet.json"

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, baseline="baseline", candidate="breaking"):
        config = read_json(self.path)
        config["baseline"]["command"][-1] = baseline
        config["candidate"]["command"][-1] = candidate
        write_json(self.path, config)
        return asyncio.run(check(load_config(self.path), allow_exec=True))

    def test_breaking_behavior_same_schema(self):
        report = self.execute()
        self.assertEqual(report["counts"]["regression"], 2)
        self.assertEqual(report["counts"]["compatible"], 2)
        self.assertEqual(report["surfaceChanges"], [])
        self.assertEqual(report["exitCode"], 1)
        self.assertEqual(report["observedContractPassRate"], 0.5)
        self.assertEqual(report["coverage"]["uncoveredBaselineTools"], ["health"])
        self.assertEqual(report["consumers"]["synthetic-cart"]["regression"], 2)
        self.assertEqual(report["consumers"]["synthetic-inventory"]["compatible"], 2)

    def test_compatible_candidate(self):
        report = self.execute(candidate="compatible")
        self.assertEqual(report["exitCode"], 0)
        self.assertEqual(report["counts"]["compatible"], 4)

    def test_existing_failures_are_not_new_regressions(self):
        report = self.execute(baseline="breaking", candidate="breaking")
        self.assertEqual(report["counts"]["regression"], 0)
        self.assertEqual(report["counts"]["baseline_failure"], 2)
        self.assertEqual(report["excludedCases"], 2)
        self.assertEqual(report["exitCode"], 2)

    def test_improvements(self):
        report = self.execute(baseline="breaking", candidate="compatible")
        self.assertEqual(report["counts"]["improvement"], 2)
        self.assertEqual(report["exitCode"], 0)

    def test_new_required_argument_is_breaking_for_existing_cases(self):
        report = self.execute(candidate="schema-break")
        self.assertEqual(report["counts"]["regression"], 2)
        self.assertTrue(report["surfaceChanges"])
        self.assertEqual(report["cases"][0]["samples"]["candidate"][0]["issues"][0]["code"], "input_required")

    def test_removed_tool(self):
        report = self.execute(candidate="removed-tool")
        self.assertEqual(report["exitCode"], 1)
        self.assertIn("tool_removed", [change["kind"] for change in report["surfaceChanges"]])

    def test_output_schema_validation(self):
        report = self.execute(candidate="output-invalid")
        self.assertEqual(report["counts"]["regression"], 2)
        codes = [p["code"] for p in report["cases"][0]["samples"]["candidate"][0]["issues"]]
        self.assertIn("server_output_type", codes)

    def test_changed_description_is_review_not_silent_pass(self):
        report = self.execute(candidate="review")
        self.assertEqual(report["counts"]["compatible"], 4)
        self.assertEqual(report["exitCode"], 2)

    def test_launch_failure_is_inconclusive_not_removal(self):
        config = read_json(self.path)
        config["candidate"]["command"] = ["/definitely-not-a-real-program-canarynet"]
        write_json(self.path, config)
        report = asyncio.run(check(load_config(self.path), allow_exec=True))
        self.assertEqual(report["counts"]["inconclusive"], 4)
        self.assertEqual(report["eligibleCases"], 0)
        self.assertIsNone(report["observedContractPassRate"])
        self.assertEqual(report["surfaceChanges"], [])
        self.assertEqual(report["exitCode"], 2)

    def test_rpc_failure_excludes_sensitive_message(self):
        config = read_json(self.path)
        config["candidate"]["command"] = ["{python}", str(FIXTURE), "rpc-error"]
        config["baseline"]["command"] = ["{python}", str(FIXTURE), "normal"]
        config["allowTools"] = ["echo"]
        config["contracts"] = ["contracts/echo.json"]
        write_json(self.root / "contracts/echo.json", {"version": 1, "consumer": "synthetic-echo", "cases": [
            {"id": "echo", "tool": "echo", "arguments": {"token": "SECRET_INPUT"}, "expect": {"isError": False}}
        ]})
        write_json(self.path, config)
        report = asyncio.run(check(load_config(self.path), allow_exec=True))
        self.assertEqual(report["exitCode"], 1)
        serialized = json.dumps(report) + markdown(report) + junit(report)
        for secret in ("SECRET_REMOTE_ERROR", "SECRET_INPUT", "not-inherited"):
            self.assertNotIn(secret, serialized)

    def test_catalog_change_makes_whole_round_inconclusive(self):
        config = read_json(self.path)
        config["baseline"]["command"] = ["{python}", str(FIXTURE), "normal"]
        config["candidate"]["command"] = ["{python}", str(FIXTURE), "catalog-change"]
        config["allowTools"] = ["echo"]
        config["contracts"] = ["contracts/echo.json"]
        write_json(self.root / "contracts/echo.json", {"version": 1, "consumer": "synthetic-echo", "cases": [
            {"id": "echo", "tool": "echo", "arguments": {}, "expect": {"isError": False}}
        ]})
        write_json(self.path, config)
        report = asyncio.run(check(load_config(self.path), allow_exec=True))
        self.assertEqual(report["counts"]["inconclusive"], 1)
        self.assertEqual(report["exitCode"], 2)

    def test_report_formats_and_payload_minimization(self):
        report = self.execute()
        text = markdown(report)
        self.assertIn("synthetic-cart", text)
        suite = ET.fromstring(junit(report))
        self.assertEqual(suite.attrib["failures"], "2")
        self.assertEqual(suite.attrib["tests"], "4")
        for excluded in ("arguments", "Synthetic record not found", "DEMO-1", "UNKNOWN"):
            self.assertNotIn(excluded, json.dumps(report))

    def test_cli_reports_correct_exit_codes(self):
        process = subprocess.run([sys.executable, "-m", "canarynet", "check", "-c", str(self.path), "--allow-exec", "--output", str(self.root / "reports"), "--json"], capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 1, process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual(report["exitCode"], 1)
        self.assertEqual(read_json(self.root / "reports/report.json")["runId"], report["runId"])
        self.assertTrue((self.root / "reports/report.md").exists())
        self.assertTrue((self.root / "reports/junit.xml").exists())

    def test_cli_blocks_execution_and_writes_no_report(self):
        process = subprocess.run([sys.executable, "-m", "canarynet", "check", "-c", str(self.path), "--output", str(self.root / "reports")], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 2)
        self.assertFalse((self.root / "reports").exists())

    def test_cli_snapshot_and_diff(self):
        files = []
        for side in ("baseline", "candidate"):
            path = self.root / f"{side}.json"
            process = subprocess.run([sys.executable, "-m", "canarynet", "snapshot", "-c", str(self.path), "--side", side, "--allow-exec", "--output", str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            files.append(str(path))
        process = subprocess.run([sys.executable, "-m", "canarynet", "diff", *files], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0)
        self.assertEqual(json.loads(process.stdout)["changes"], [])
        changed = read_json(Path(files[0]))
        changed["tools"].pop("add")
        write_json(Path(files[0]), changed)
        process = subprocess.run([sys.executable, "-m", "canarynet", "diff", *files], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 2)


if __name__ == "__main__":
    unittest.main()

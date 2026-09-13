"""Payload-minimized JSON, Markdown, and JUnit report writers."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import write_json, write_text


def clean(value: object) -> str:
    # Artifact labels are untrusted: prevent terminal escapes and Markdown/HTML injection.
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", str(value))
    return text.replace("[", "\\[").replace("]", "\\]").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|").replace("`", "'")


def markdown(report: dict) -> str:
    lines = ["# CanaryNet compatibility report", "", f"**Gate: {report['gate'].upper()}**", "",
             report["scope"], "", f"Cases: {report['totalCases']}; eligible: {report['eligibleCases']}; excluded: {report['excludedCases']}.",
             "", "| Consumer | Case | Tool | Outcome |", "|---|---|---|---|"]
    for row in report["cases"]:
        lines.append("| " + " | ".join(clean(row[k]) for k in ("consumer", "case", "tool", "status")) + " |")
    lines += ["", "## Findings", ""]
    for row in report["cases"]:
        if row["status"] in ("compatible", "improvement"):
            continue
        lines.append(f"### {clean(row['consumer'])} / {clean(row['case'])}: {row['status']}")
        for side, samples in row["samples"].items():
            seen = set()
            for sample in samples:
                for problem in sample["issues"]:
                    detail = (problem["code"], problem["path"])
                    if detail not in seen:
                        lines.append(f"- {side}: {clean(detail[0])} at `{clean(detail[1]) or '(root)'}`")
                        seen.add(detail)
    for change in report["surfaceChanges"]:
        lines.append(f"- Surface {change['severity']}: {clean(change['tool'])}, {change['kind']}, {clean(change.get('field', ''))}")
    for problem in report["runIssues"]:
        lines.append(f"- Run: {clean(problem)}")
    lines += ["", "## Interpretation", "",
              "A pass covers only these assertions. Two or more passing repetitions are not a statistical reliability claim.",
              "Baseline failures, unstable samples, and inconclusive runs are excluded from the observed pass-rate denominator.",
              "Schema/description drift needs review; this is not a general schema-compatibility proof.",
              "Timing includes validation overhead and is diagnostic only, not a latency benchmark.",
              "Arguments, returned payloads, environment values, server stderr, and remote error text are not included.", ""]
    return "\n".join(lines)


def junit(report: dict) -> str:
    entries = []
    for row in report["cases"]:
        test = ET.Element("testcase", {"classname": row["consumer"], "name": row["case"]})
        if row["status"] == "regression":
            ET.SubElement(test, "failure", {"type": "regression", "message": "Baseline passed; candidate violated the consumer contract"})
        elif row["status"] in ("baseline_failure", "unstable", "inconclusive"):
            ET.SubElement(test, "error", {"type": row["status"], "message": "Compatibility was not established"})
        entries.append(test)
    for index, change in enumerate(report["surfaceChanges"]):
        if change["severity"] == "info":
            continue
        test = ET.Element("testcase", {"classname": "canarynet.surface", "name": f"change-{index}"})
        ET.SubElement(test, "failure" if change["severity"] == "breaking" else "error",
                      {"type": change["kind"], "message": "Tool surface changed; inspect JSON/Markdown report"})
        entries.append(test)
    for index, _ in enumerate(report["runIssues"]):
        test = ET.Element("testcase", {"classname": "canarynet.run", "name": f"issue-{index}"})
        ET.SubElement(test, "error", {"type": "inconclusive", "message": "Catalog varied across repetitions"})
        entries.append(test)
    suite = ET.Element("testsuite", {"name": "CanaryNet", "tests": str(len(entries)),
                                   "failures": str(sum(e.find("failure") is not None for e in entries)),
                                   "errors": str(sum(e.find("error") is not None for e in entries)), "skipped": "0"})
    suite.extend(entries)
    return ET.tostring(suite, encoding="unicode", xml_declaration=True) + "\n"


def save_report(report: dict, directory: Path) -> None:
    write_json(directory / "report.json", report)
    write_text(directory / "report.md", markdown(report))
    write_text(directory / "junit.xml", junit(report))

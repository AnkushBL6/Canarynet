"""Execute real local calls against two versions and classify measured evidence."""
from __future__ import annotations

import platform
import statistics
import time
import uuid
from datetime import datetime, timezone

from . import __version__
from .common import CanaryError, canonical, digest, pointer, same_json
from .schema import SchemaOracle
from .transport import RpcError, StdioClient, TransportError

STATUSES = ("compatible", "regression", "baseline_failure", "improvement", "unstable", "inconclusive")


def surface_diff(before: dict[str, dict], after: dict[str, dict]) -> list[dict]:
    """Conservative drift, NOT a general JSON Schema subsumption proof."""
    changes = []
    for name in sorted(before.keys() | after.keys()):
        if name not in before:
            changes.append({"tool": name, "kind": "tool_added", "severity": "info"})
        elif name not in after:
            changes.append({"tool": name, "kind": "tool_removed", "severity": "breaking"})
        else:
            for field in sorted(before[name].keys() | after[name].keys()):
                if field == "name":
                    continue
                if (field in before[name]) != (field in after[name]) or not same_json(before[name].get(field), after[name].get(field)):
                    changes.append({"tool": name, "kind": "definition_changed", "field": field, "severity": "review"})
    return changes


def classify(baseline: list[dict], candidate: list[dict]) -> str:
    if not baseline or not candidate or len(baseline) != len(candidate):
        return "inconclusive"
    if any(item["state"] == "error" for item in baseline + candidate):
        return "inconclusive"
    for samples in (baseline, candidate):
        signatures = {canonical([item["state"], item.get("issues", [])]) for item in samples}
        if len(signatures) != 1:
            return "unstable"
    before, after = baseline[0]["state"], candidate[0]["state"]
    return {("pass", "pass"): "compatible", ("pass", "fail"): "regression",
            ("fail", "pass"): "improvement", ("fail", "fail"): "baseline_failure"}.get((before, after), "inconclusive")


def issue(code: str, path: str = "") -> dict:
    return {"code": code, "path": path}


def _valid_result(result: dict) -> bool:
    if not isinstance(result.get("content"), list):
        return False
    if "isError" in result and type(result["isError"]) is not bool:
        return False
    if "structuredContent" in result and not isinstance(result["structuredContent"], dict):
        return False
    for block in result["content"]:
        if not isinstance(block, dict) or not isinstance(block.get("type"), str):
            return False
        if block["type"] == "text" and not isinstance(block.get("text"), str):
            return False
    return True


async def _case(client: StdioClient, tools: dict, case: dict, oracle: SchemaOracle) -> dict:
    started = time.monotonic()
    problems = []
    try:
        tool = tools.get(case["tool"])
        if tool is None:
            return {"state": "fail", "issues": [issue("tool_missing")], "durationMs": 0.0}
        execution = tool.get("execution", {})
        if isinstance(execution, dict) and execution.get("taskSupport") == "required":
            raise CanaryError("task_required_tool_not_supported")
        invalid_input = oracle.validate(tool["inputSchema"], case["arguments"])
        if invalid_input:
            return {"state": "fail", "issues": [issue("input_" + p["code"], p["path"]) for p in invalid_input], "durationMs": 0.0}
        try:
            result = await client.request("tools/call", {"name": case["tool"], "arguments": case["arguments"]})
        except RpcError as exc:
            return {"state": "fail", "issues": [issue(f"rpc_error_{exc.code}")], "durationMs": round((time.monotonic() - started) * 1000, 3)}
        if not _valid_result(result):
            problems.append(issue("invalid_tool_result"))
        else:
            actual_error = result.get("isError", False)
            if actual_error != case["expect"]["isError"]:
                problems.append(issue("unexpected_isError", "/isError"))
            if "outputSchema" in tool and not actual_error:
                if "structuredContent" not in result:
                    problems.append(issue("missing_structured_content", "/structuredContent"))
                else:
                    problems += [issue("server_output_" + p["code"], p["path"]) for p in oracle.validate(tool["outputSchema"], result["structuredContent"])]
            expectation = case["expect"]
            if "resultSchema" in expectation:
                problems += [issue("consumer_" + p["code"], p["path"]) for p in oracle.validate(expectation["resultSchema"], result)]
            for path, expected in expectation.get("equals", {}).items():
                found, actual = pointer(result, path)
                if not found:
                    problems.append(issue("consumer_path_missing", path))
                elif not same_json(actual, expected):
                    problems.append(issue("consumer_value_mismatch", path))
        if client.catalog_changed:
            raise TransportError("catalog_changed_during_session")
        return {"state": "fail" if problems else "pass", "issues": problems,
                "durationMs": round((time.monotonic() - started) * 1000, 3)}
    except TransportError:
        raise
    except CanaryError as exc:
        return {"state": "error", "issues": [issue(str(exc))], "durationMs": 0.0}


async def _round(server: dict, cases: list[dict], timeout: float, oracle: SchemaOracle) -> dict:
    samples: list[dict] = []
    tools: dict = {}
    info: dict = {}
    problem = None
    try:
        async with StdioClient(server, timeout) as client:
            info = {"protocolVersion": client.info["protocolVersion"], "serverInfoSha256": digest(client.info["serverInfo"])}
            tools = await client.tools()
            for tool in tools.values():
                oracle.validate(tool["inputSchema"], check_only=True)
                if "outputSchema" in tool:
                    oracle.validate(tool["outputSchema"], check_only=True)
            for case in cases:
                samples.append(await _case(client, tools, case, oracle))
            final_tools = await client.tools()
            if client.catalog_changed or digest(final_tools) != digest(tools):
                raise TransportError("catalog_changed_during_session")
    except (CanaryError, OSError, TimeoutError) as exc:
        problem = str(exc) if isinstance(exc, CanaryError) else "server_start_or_io_failed"
    if problem:
        # A broken session invalidates its whole round, not merely the final call.
        samples = [{"state": "error", "issues": [issue(problem)], "durationMs": 0.0} for _ in cases]
    return {"samples": samples, "tools": tools, "info": info, "error": problem}


def _gate(rows: list[dict], changes: list[dict], run_issues: list[str]) -> tuple[str, int]:
    if any(row["status"] == "regression" for row in rows) or any(c["severity"] == "breaking" for c in changes):
        return "fail", 1
    if (run_issues or any(row["status"] in ("baseline_failure", "inconclusive", "unstable") for row in rows)
            or any(c["severity"] == "review" for c in changes)):
        return "review", 2
    return "pass", 0


async def check(config: dict, *, allow_exec: bool = False) -> dict:
    if not allow_exec:
        raise CanaryError("Execution requires --allow-exec; use only reviewed commands and disposable test data")
    cases = config["cases"]
    rounds: dict[str, list] = {"baseline": [], "candidate": []}
    with SchemaOracle() as oracle:
        for case in cases:
            if "resultSchema" in case["expect"]:
                oracle.validate(case["expect"]["resultSchema"], check_only=True)
        for repetition in range(config["repetitions"]):
            # Each repetition uses a fresh process; call order within a consumer suite is stable.
            for side in (("baseline", "candidate") if repetition % 2 == 0 else ("candidate", "baseline")):
                rounds[side].append(await _round(config[side], cases, config["timeoutSeconds"], oracle))
    run_issues = []
    for side in rounds:
        fingerprints = {digest(result["tools"]) for result in rounds[side]}
        if len(fingerprints) != 1:
            run_issues.append(side + "_catalog_varies_between_repetitions")
    rows = []
    for index, case in enumerate(cases):
        samples = {side: [result["samples"][index] for result in rounds[side]] for side in rounds}
        row = {"consumer": case["consumer"], "case": case["id"], "tool": case["tool"],
               "status": classify(samples["baseline"], samples["candidate"]), "samples": samples}
        row["medianDurationMs"] = {side: round(statistics.median(s["durationMs"] for s in samples[side]), 3) for side in samples}
        rows.append(row)
    # Only compare complete catalogs; a connection failure is not evidence of tool removal.
    first_baseline, first_candidate = rounds["baseline"][0], rounds["candidate"][0]
    changes = (surface_diff(first_baseline["tools"], first_candidate["tools"])
               if not first_baseline["error"] and not first_candidate["error"] else [])
    gate, exit_code = _gate(rows, changes, run_issues)
    counts = {status: sum(row["status"] == status for row in rows) for status in STATUSES}
    eligible = counts["compatible"] + counts["regression"]
    baseline_tools = set(first_baseline["tools"])
    tested = {case["tool"] for case in cases}
    consumers = {}
    for row in rows:
        consumers.setdefault(row["consumer"], {status: 0 for status in STATUSES})[row["status"]] += 1
    return {
        "reportVersion": 1, "canarynetVersion": __version__, "runId": str(uuid.uuid4()),
        "createdAt": datetime.now(timezone.utc).isoformat(), "gate": gate, "exitCode": exit_code,
        "scope": "Only the supplied consumer cases and observed tool catalogs; not an ecosystem estimate",
        "counts": counts, "totalCases": len(rows), "eligibleCases": eligible,
        "excludedCases": len(rows) - eligible,
        "observedContractPassRate": counts["compatible"] / eligible if eligible else None,
        "coverage": {"baselineToolCount": len(baseline_tools), "declaredTestedTools": sorted(tested),
                     "uncoveredBaselineTools": sorted(baseline_tools - tested)},
        "consumers": consumers, "cases": rows, "surfaceChanges": changes, "runIssues": run_issues,
        "evidence": {"configSha256": config["configSha256"], "contracts": config["evidence"],
                     "python": platform.python_version(), "platform": platform.system(),
                     "repetitions": config["repetitions"],
                     "servers": {side: {"commandSha256": digest(config[side]["command"]),
                                        "declaredRevision": config[side].get("revision"),
                                        "observations": [{**r["info"], "catalogSha256": digest(r["tools"])} for r in rounds[side]]}
                                 for side in rounds}},
    }


async def snapshot(config: dict, side: str, *, allow_exec: bool = False) -> dict:
    if not allow_exec:
        raise CanaryError("Execution requires --allow-exec")
    async with StdioClient(config[side], config["timeoutSeconds"]) as client:
        tools = await client.tools()
        if client.catalog_changed:
            raise CanaryError("catalog_changed_during_snapshot")
        return {"snapshotVersion": 1, "protocolVersion": client.info["protocolVersion"],
                "tools": tools, "catalogSha256": digest(tools)}

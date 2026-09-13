"""Bounded JSON, explicit configuration, and deterministic identifiers."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

MAX_BYTES = 1_048_576
MAX_DEPTH = 64


class CanaryError(Exception):
    """A safe, payload-free diagnostic."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CanaryError("Duplicate JSON object key; input is ambiguous")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise CanaryError("Non-finite JSON numbers are not supported")


def bounded(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise CanaryError("JSON nesting exceeds the limit")
    if isinstance(value, dict):
        for child in value.values():
            bounded(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            bounded(child, depth + 1)
    elif isinstance(value, float) and not math.isfinite(value):
        raise CanaryError("Non-finite JSON numbers are not supported")


def loads(text: str | bytes) -> Any:
    if len(text.encode() if isinstance(text, str) else text) > MAX_BYTES:
        raise CanaryError("JSON exceeds the 1 MiB limit")
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        bounded(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise CanaryError("Invalid or excessively nested JSON") from exc


def read_json(path: Path) -> Any:
    try:
        with path.open("rb") as stream:
            return loads(stream.read(MAX_BYTES + 1))
    except OSError as exc:
        raise CanaryError("Cannot read a required JSON file") from exc


def write_text(path: Path, text: str) -> None:
    """Write with restrictive permissions and an atomic, same-directory rename."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise CanaryError("Refusing to overwrite a symlink")
    fd, temporary = tempfile.mkstemp(prefix=".canary-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, indent=2, ensure_ascii=True, allow_nan=False) + "\n")


def identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}", value):
        raise CanaryError(f"{label} must be a safe identifier of 1-128 characters")
    return value


def fields(value: Any, allowed: set[str], required: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise CanaryError(f"Invalid, missing, or unknown fields in {label}")
    return value


def number(value: Any, low: float, high: float, label: str, integer: bool = False) -> Any:
    if (type(value) not in (int, float) or not math.isfinite(value)
            or not low <= value <= high or (integer and type(value) is not int)):
        raise CanaryError(f"{label} is outside its supported range")
    return value


def pointer(value: Any, path: str) -> tuple[bool, Any]:
    """RFC 6901 lookup: distinguish a missing value from a present null."""
    if path == "":
        return True, value
    if not isinstance(path, str) or not path.startswith("/") or re.search(r"~(?![01])", path):
        raise CanaryError("Invalid JSON Pointer")
    for part in path[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part) and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def same_json(left: Any, right: Any) -> bool:
    """JSON numeric equality without Python's True == 1 ambiguity."""
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


def load_config(path: Path) -> dict:
    root = path.resolve().parent
    config = fields(read_json(path),
                    {"version", "baseline", "candidate", "contracts", "allowTools", "timeoutSeconds", "repetitions"},
                    {"version", "baseline", "candidate", "contracts", "allowTools"}, "configuration")
    if type(config["version"]) is not int or config["version"] != 1:
        raise CanaryError("Unsupported configuration version")
    config = dict(config)
    for side in ("baseline", "candidate"):
        server = fields(config[side], {"command", "cwd", "envAllow", "revision"}, {"command"}, side)
        command = server["command"]
        if not isinstance(command, list) or not command or len(command) > 64 or any(
            not isinstance(arg, str) or not arg or "\x00" in arg or len(arg) > 8192 for arg in command
        ):
            raise CanaryError("Server command must be a nonempty argument array; shell strings are not supported")
        env_allow = server.get("envAllow", [])
        if not isinstance(env_allow, list) or any(
            not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) for name in env_allow
        ):
            raise CanaryError("envAllow must contain environment variable names, never values")
        cwd = server.get("cwd", ".")
        if not isinstance(cwd, str):
            raise CanaryError("Server cwd must be a path string")
        cwd_path = (root / cwd).resolve()
        if not cwd_path.is_dir():
            raise CanaryError("Server working directory does not exist")
        if "revision" in server:
            identifier(server["revision"], "Declared revision")
        config[side] = {**server, "cwd": str(cwd_path), "envAllow": env_allow}
    allow = config["allowTools"]
    if not isinstance(allow, list) or not allow or any(not isinstance(x, str) for x in allow) or len(set(allow)) != len(allow):
        raise CanaryError("allowTools must be a nonempty, unique list")
    for name in allow:
        identifier(name, "Allowed tool")
    patterns = config["contracts"]
    if not isinstance(patterns, list) or not patterns or any(not isinstance(p, str) for p in patterns):
        raise CanaryError("contracts must be a nonempty list of relative glob patterns")
    paths: set[Path] = set()
    for pattern in patterns:
        if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise CanaryError("Contract paths must remain within the configuration directory")
        matches = list(root.glob(pattern))
        if not matches:
            raise CanaryError("A contract pattern matched no files")
        for match in matches:
            if not match.resolve().is_relative_to(root) or not match.is_file() or match.suffix != ".json":
                raise CanaryError("Contract files must be JSON files inside the configuration directory")
            paths.add(match.resolve())
    if len(paths) > 100:
        raise CanaryError("At most 100 contract files are supported")
    cases, identities, evidence = [], set(), []
    for contract_path in sorted(paths):
        contract = fields(read_json(contract_path), {"version", "consumer", "cases"}, {"version", "consumer", "cases"}, "contract")
        if type(contract["version"]) is not int or contract["version"] != 1:
            raise CanaryError("Unsupported contract version")
        consumer = identifier(contract["consumer"], "Consumer")
        if not isinstance(contract["cases"], list) or not contract["cases"]:
            raise CanaryError("Each contract must contain cases")
        evidence.append({"consumer": consumer, "sha256": digest(contract)})
        for raw_case in contract["cases"]:
            case = fields(raw_case, {"id", "tool", "arguments", "expect"}, {"id", "tool", "arguments", "expect"}, "case")
            case_id = identifier(case["id"], "Case id")
            identifier(case["tool"], "Tool")
            identity = (consumer, case_id)
            if identity in identities:
                raise CanaryError("Duplicate consumer/case identity")
            identities.add(identity)
            if case["tool"] not in allow or not isinstance(case["arguments"], dict):
                raise CanaryError("Every case must use an allowlisted tool and object arguments")
            expect = fields(case["expect"], {"isError", "resultSchema", "equals"}, {"isError"}, "expectation")
            if type(expect["isError"]) is not bool:
                raise CanaryError("expect.isError must be an explicit boolean")
            if "resultSchema" in expect and not isinstance(expect["resultSchema"], (dict, bool)):
                raise CanaryError("resultSchema must be a JSON Schema")
            equals = expect.get("equals", {})
            if not isinstance(equals, dict):
                raise CanaryError("expect.equals must map JSON Pointers to expected values")
            for key in equals:
                pointer({}, key)
            cases.append({**case, "consumer": consumer})
    if not 1 <= len(cases) <= 500:
        raise CanaryError("A run must contain between 1 and 500 cases")
    config["timeoutSeconds"] = number(config.get("timeoutSeconds", 5), 0.1, 120, "timeoutSeconds")
    config["repetitions"] = number(config.get("repetitions", 2), 2, 5, "repetitions", integer=True)
    config["cases"], config["evidence"] = cases, evidence
    config["configSha256"] = digest(read_json(path))
    return config

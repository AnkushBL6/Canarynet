"""CLI entry points; external execution always requires explicit acknowledgement."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from importlib.resources import files
from pathlib import Path

from . import __version__
from .common import CanaryError, digest, fields, load_config, read_json, write_json
from .engine import check, snapshot, surface_diff
from .report import save_report


def init(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    destination = [directory / name for name in ("canarynet.json", "server.py", "contracts")]
    if any(path.exists() or path.is_symlink() for path in destination):
        raise CanaryError("Initialization would overwrite existing files; choose an empty directory")
    source = files("canarynet").joinpath("demo")
    for item in source.iterdir():
        if item.name.startswith("__") or item.name.endswith(".pyc"):
            continue
        if item.is_dir():
            (directory / item.name).mkdir()
            for child in item.iterdir():
                if child.name.endswith(".json"):
                    (directory / item.name / child.name).write_bytes(child.read_bytes())
        else:
            (directory / item.name).write_bytes(item.read_bytes())


def _snapshot_file(path: Path) -> dict:
    data = fields(read_json(path), {"snapshotVersion", "protocolVersion", "tools", "catalogSha256"},
                  {"snapshotVersion", "protocolVersion", "tools", "catalogSha256"}, "snapshot")
    if type(data["snapshotVersion"]) is not int or data["snapshotVersion"] != 1 or not isinstance(data["tools"], dict):
        raise CanaryError("Invalid snapshot")
    if digest(data["tools"]) != data["catalogSha256"]:
        raise CanaryError("Snapshot integrity check failed")
    for name, tool in data["tools"].items():
        if not isinstance(tool, dict) or tool.get("name") != name or not isinstance(tool.get("inputSchema"), dict):
            raise CanaryError("Invalid snapshot tool definition")
    return data["tools"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="canarynet", description="Know which supplied consumer contracts break before you ship.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    initialize = commands.add_parser("init", help="Create a synthetic, offline demo without overwriting existing files")
    initialize.add_argument("directory", nargs="?", default="canarynet-demo", type=Path)
    verify = commands.add_parser("check", help="Run consumer contracts against baseline and candidate")
    capture = commands.add_parser("snapshot", help="Explicitly export a tool catalog; schemas may contain sensitive metadata")
    validate = commands.add_parser("validate", help="Validate configuration and contract structure without launching servers")
    for command in (verify, capture, validate):
        command.add_argument("--config", "-c", type=Path, default=Path("canarynet.json"))
    for command in (verify, capture):
        command.add_argument("--allow-exec", action="store_true", help="Acknowledge commands run with your OS permissions; not a sandbox")
    verify.add_argument("--output", type=Path, default=Path(".canarynet/reports/latest"))
    verify.add_argument("--json", action="store_true", help="Print the payload-minimized report as JSON")
    capture.add_argument("--side", choices=("baseline", "candidate"), required=True)
    capture.add_argument("--output", type=Path, required=True)
    compare = commands.add_parser("diff", help="Conservatively compare two saved catalogs; does not execute servers")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init(args.directory)
            print("Synthetic demo created. The default candidate intentionally breaks a contract.")
            return 0
        if args.command == "diff":
            changes = surface_diff(_snapshot_file(args.baseline), _snapshot_file(args.candidate))
            print(json.dumps({"changes": changes, "scope": "Surface drift only; changed schemas require review"}, indent=2))
            return 1 if any(c["severity"] == "breaking" for c in changes) else 2 if any(c["severity"] == "review" for c in changes) else 0
        config = load_config(args.config)
        if args.command == "validate":
            print(f"Configuration structure valid: {len(config['cases'])} cases. No servers executed; schemas are validated during check.")
            return 0
        if not args.allow_exec:
            raise CanaryError("Execution blocked: supply --allow-exec only after reviewing commands and using disposable test data")
        print("Executing explicitly configured programs. This is not a sandbox; use test credentials only.", file=sys.stderr)
        if args.command == "snapshot":
            result = asyncio.run(snapshot(config, args.side, allow_exec=True))
            write_json(args.output, result)
            print("Catalog saved. Review schemas and descriptions before sharing this snapshot.")
            return 0
        report = asyncio.run(check(config, allow_exec=True))
        save_report(report, args.output)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"CanaryNet {report['gate'].upper()} | {report['totalCases']} consumer cases")
            print(" | ".join(f"{key}: {value}" for key, value in report["counts"].items() if value))
            print(f"Eligible: {report['eligibleCases']}; excluded: {report['excludedCases']}; surface changes: {len(report['surfaceChanges'])}")
            print("Reports: report.json, report.md, junit.xml in the requested output directory")
        return report["exitCode"]
    except (CanaryError, OSError, ValueError, TypeError) as exc:
        # Do not echo file contents, credentials in paths, subprocess messages, or validation payloads.
        message = str(exc) if isinstance(exc, CanaryError) else "Local configuration, file, or process operation failed"
        print(f"CanaryNet error: {message}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("CanaryNet cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

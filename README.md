# CanaryNet

**Know which consumer contracts break before you ship.**

An experimental, local-first MCP compatibility runner. It executes the same explicit consumer cases against a baseline and a candidate, and separates new regressions from baseline failures, improvements, unstable observations, and inconclusive runs.

This is a working alpha CLI, **not a hosted compatibility network**. There are no invented downstream users, ecosystem health scores, or claims of market exclusivity.

## Try a real, offline demo

Python 3.11+ is required. From this repository:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .
canarynet init demo
canarynet check --config demo/canarynet.json --allow-exec --output .canarynet/demo-report
```

The final command **intentionally exits 1**. The synthetic candidate returns the wrong sum while keeping its schemas unchanged. Two cart cases regress; two inventory cases remain compatible. An unused `health` tool is explicitly reported as uncovered.

Reports: `.canarynet/demo-report/report.json`, `report.md`, and `junit.xml`. These contain outcomes and diagnostic paths, not arguments, response payloads, secrets, or server stderr. Metadata such as tool/consumer names can still be sensitive; review artifacts before sharing.

To see a passing run, change the candidate command's final argument from `breaking` to `compatible` in `demo/canarynet.json`, then run the same command again. `schema-break`, `removed-tool`, `output-invalid`, and `review` demonstrate other outcomes.

## Why consumer contracts?

A schema can remain identical while a server starts returning a different value. CanaryNet checks explicitly declared consumer expectations, not merely whether two schema files differ. Conversely, one passing fixture does **not** prove every possible input remains compatible.

```json
{
  "version": 1,
  "consumer": "checkout-service",
  "cases": [{
    "id": "cart-total",
    "tool": "add",
    "arguments": {"a": 2, "b": 3},
    "expect": {"isError": false, "equals": {"/structuredContent/sum": 5}}
  }]
}
```

This is an illustrative contract, not a real customer. `expect.isError` is mandatory. `equals` uses JSON Pointers into the complete tool result. `resultSchema` optionally validates the complete tool result using JSON Schema 2020-12. The server's advertised input and successful structured-output schemas are also validated.

## Configure your own test servers

```json
{
  "version": 1,
  "baseline": {"command": ["{python}", "baseline/server.py"], "envAllow": ["TEST_API_TOKEN"]},
  "candidate": {"command": ["{python}", "candidate/server.py"], "envAllow": ["TEST_API_TOKEN"]},
  "contracts": ["contracts/*.json"],
  "allowTools": ["lookup_order"],
  "timeoutSeconds": 5,
  "repetitions": 2
}
```

Supply your own files; the paths above are illustrative. Commands are argument arrays, never implicitly evaluated by a shell. `{python}` resolves to the interpreter running CanaryNet. Working directories are relative to the configuration file. Contract files must remain within that directory. `envAllow` names variables to inherit; it must not contain secret values.

**Executing a server is executing arbitrary code with your OS permissions.** `--allow-exec` is acknowledgement, not isolation. Review both commands and all contract cases. Use disposable test environments and test credentials. Repetition can repeat side effects, even when an MCP tool advertises a read-only hint. CanaryNet does not treat annotations as authorization.

## Commands

```bash
canarynet validate --config demo/canarynet.json
canarynet snapshot -c demo/canarynet.json --side baseline --allow-exec --output baseline.json
canarynet snapshot -c demo/canarynet.json --side candidate --allow-exec --output candidate.json
canarynet diff baseline.json candidate.json
```

`validate` checks configuration/contract structure without starting servers; schemas are validated during `check`. Snapshots deliberately export the full tool definitions and may contain sensitive metadata. Unlike normal reports, they are **not payload-minimized**.

## Gate semantics

| Exit | Meaning |
|---|---|
| `0` | Supplied assertions passed, or improved from a failing baseline, with no blocking surface drift. |
| `1` | A stable baseline-passing case fails against the candidate, or an observed tool was removed. |
| `2` | Invalid configuration, unreviewed surface drift, baseline failure, unstable observations, or inconclusive execution. Never a silent pass. |
| `130` | Cancelled by the operator. |

A fresh server process is used for each side and repetition. Cases execute sequentially in deterministic contract-file/case order. Baseline/candidate order alternates across repetitions. External services are **not** reset by process restart. There are no hidden retries of tool calls.

The observed pass-rate denominator includes only baseline-passing cases with stable, conclusive candidate observations. Exclusions and uncovered tools remain visible. This is **not an ecosystem percentage** or a statistical confidence estimate.

## Explicit support boundary

Implemented: local **stdio**, initialized-session tool discovery/calls through **MCP 2025-11-25**, plus listed earlier negotiated revisions; paginated discovery; consumer assertions; bounded schema validation; JSON/Markdown/JUnit reports; CLI and a repository-local composite GitHub Action.

**Not implemented:** MCP 2026-07-28 stateless protocol, Streamable HTTP, OAuth, roots/sampling/elicitation execution, task workflows, passive traffic recording, state binding between calls, hosted GitHub App, private-cloud storage, public compatibility registry, ecosystem scheduling, or sandboxing. Unknown protocol revisions are rejected. The current protocol and official SDK have evolved; this alpha does not claim full current-protocol conformance. See [architecture and decisions](docs/ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md).

JSON Schema defaults to 2020-12; other explicitly declared dialects and nonlocal references are rejected. Local references, combinators, patterns, constraints, and boolean consumer schemas are supported through `jsonschema`. Validation runs in a separate deadline-bounded process. `format` remains an annotation, not an asserted semantic check.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

The optional independent SDK interoperability test runs when `mcp>=1.28,<2` is installed. CI installs that maintained SDK line explicitly to verify the implemented initialized-session protocol. A skipped SDK test is not interoperability evidence. See [verification](docs/VERIFICATION.md).

## License and release status

No license has been selected by the repository owner yet. Public visibility is not an open-source license. License selection is a release-blocking owner decision; this alpha does not grant a blanket redistribution license. The package name has not been reserved or published on PyPI, and no `v1` GitHub Action tag is claimed.

# Architecture and decision record

Status: experimental alpha. Date: 2026-09-13.

## Confirmed brief versus implementation decisions

Confirmed by the owner: build CanaryNet in the public `AnkushBL6/Canarynet` repository; avoid assumptions. The earlier discussion proposed pre-release compatibility testing for MCP tools and downstream agents. It did not establish a backend stack, hosting vendor, license, confirmed demand, production consumers, or a validated competitor-free market.

This implementation makes reversible engineering choices, not claims that those choices were owner requirements: Python 3.11+, a local CLI, JSON manifests, no service database, and a strictly scoped stdio tool adapter. No cloud account, paid service, package publication, license grant, public data ingestion, or production credentials are required or created.

## Data flow

```text
reviewed JSON configuration + consumer-owned cases
                |
       structural validation
                |
    explicit --allow-exec acknowledgement
                |
    baseline and candidate local processes
    fresh process per side and repetition
                |
    initialize -> list tools -> validate input -> call tools
                |
    server output schema + consumer assertions
                |
    repeat / classify / identify uncovered tools
                |
    local JSON + Markdown + JUnit artifacts
```

The source tree separates bounded JSON/config handling, process/JSON-RPC transport, schema validation, compatibility classification, report serialization, and CLI operations. The same engine is called by the CLI and repository-local GitHub Action.

## The unit of evidence

A consumer manifest has a stable consumer identifier and case identifiers. Each case identifies one tool, literal arguments, an explicit expected `isError` boolean, and optional JSON Pointer equality assertions or a JSON Schema for the complete result.

These are consumer-selected tool calls, **not arbitrary end-to-end autonomous-agent runs**. Calls are sequential, but values from one call are not bound into subsequent calls. Multi-step data binding, fixture lifecycle hooks, independent consumer repositories, and full agent trajectories are separate future work.

A result is a measured observation for those arguments and assertions. It is not a proof of general behavioral equivalence. Names and revisions provided in configuration are declarations, not independently verified artifact identities. Command digests identify configuration strings; they do not hash every executable, dependency, container layer, or external service.

## Classification truth table

| Stable baseline | Stable candidate | Classification |
|---|---|---|
| Pass | Pass | compatible |
| Pass | Fail | regression |
| Fail | Pass | improvement |
| Fail | Fail | baseline_failure |
| Outcome/issue signature varies | Either | unstable |
| Execution/schema/protocol cannot be established | Either | inconclusive |

Execution errors take priority over unstable classification. A failure on both versions is not attributed to the release: the baseline is unhealthy, and the root causes can differ. Unsupported schemas, RPC framing failures, timeouts, process failures, partial sessions, and changing catalogs are not passes. A well-formed JSON-RPC tool error is an observed failed call; its message/data are suppressed.

There are at least two and at most five configured repetitions. Each gets fresh baseline/candidate processes; baseline/candidate order alternates. There are no automatic tool-call retries. External state is not reset. This does not statistically certify determinism, causal attribution, or latency regressions.

## Surface drift is separate from consumer evidence

Tool removal is an observed surface break. New tools are informational. Changed input/output schemas, descriptions, annotations, and other definition metadata need review. Even an apparently additive schema edit is not silently declared globally safe. General JSON Schema containment is not implemented. No blanket compatibility claim is inferred from a diff or from one fixture.

Discovery supports pagination with a 100-page limit, duplicate/cyclic-cursor detection, and a 1,000-tool limit. Catalog changes are checked across repetitions and around the executed case sequence. Uncovered baseline tools remain in reports, not counted as passing tests.

## Protocol boundary and rationale

This first adapter deliberately implements the initialized-session stdio tool subset through **2025-11-25**, including negotiation to 2025-06-18, 2025-03-26, and 2024-11-05. It does not implement the 2026-07-28 stateless revision. Unknown revisions fail closed. It handles basic server pings and rejects unsupported server-initiated operations rather than executing sampling, roots, or elicitation.

The official Python SDK now has a newer stable major release and the MCP specification has changed substantially. Full current-protocol support must therefore be its own independently tested adapter milestone, not a claim retrofitted onto an older handshake. The old adapter's independent interoperability test uses the maintained official SDK v1 line. This boundary is prominently stated rather than hidden behind an unqualified MCP-support badge.

The local build environment could not access package registries and did not have the official MCP SDK installed. That limitation is why independent SDK verification is delegated to an explicitly configured CI job and is not claimed from local fixture-only tests. The core was locally exercised against actual subprocesses with an independently written adversarial wire fixture.

## Schema validation

`jsonschema` and `referencing` validate 2020-12 schemas in a separate process. Startup has its own deadline; each validation has a three-second deadline. A worker timeout, invalid schema, unsupported dialect, or unresolved reference is an inconclusive/error outcome. Nonlocal `$ref` and `$dynamicRef` are prohibited. The reference registry refuses retrieval; CanaryNet never fetches an external schema. Local references and ordinary JSON Schema constraints are supported. `format` is not asserted.

JSON inputs/messages are bounded to 1 MiB and 64 nesting levels. The schema worker protects the runner from validation hangs (including catastrophic regular expressions); it is not a complete OS security sandbox. There are maximum file/case/repetition counts and per-request deadlines, but no claim of a complete global CPU/memory/egress policy.

## Sources reviewed

- MCP 2025-11-25 lifecycle: https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- MCP 2025-11-25 transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP 2025-11-25 tools: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
- Current 2026-07-28 tools: https://modelcontextprotocol.io/specification/2026-07-28/server/tools
- Official Python SDK, including current v2 and maintained v1 guidance: https://github.com/modelcontextprotocol/python-sdk
- Offline reference handling: https://python-jsonschema.readthedocs.io/en/stable/referencing/
- Existing MCP schema-drift/regression product: https://specmatic.io/updates/testing-mcp-servers-how-specmatic-mcp-auto-test-catches-schema-drift-and-automates-regression/

MCP regression/schema-drift testing already has competitors. The proposed distinction is consumer-owned evidence and, later, opt-in downstream impact aggregation. Network effects, demand, pricing, and commercial defensibility remain hypotheses to validate, not facts supplied by Product Hunt vote counts.

# Roadmap: evidence before ecosystem claims

This is an ordered engineering backlog, not a promised timeline.

## Milestone 0 — local consumer-contract alpha (this change)

CLI, explicit configuration/allowlists, real stdio subprocess execution, repeated baseline/candidate observations, consumer-level outcomes, conservative catalog drift, bounded offline schema validation, local JSON/Markdown/JUnit reports, synthetic demos, adversarial tests, repository-local composite Action, and CI.

Acceptance: same-schema behavior regression fails; compatible candidate passes; unhealthy baseline does not become a new regression; failed/partial sessions never pass; unknown protocol/schema cannot silently pass; raw payloads/secrets are omitted from normal reports; package and documented commands execute.

## Milestone 1 — protocol coverage and independent evidence

1. Implement a separate current MCP 2026-07-28 adapter using the official SDK and verify stateless semantics against independent servers. Keep old and new revision tests separate.
2. Implement Streamable HTTP with protocol-appropriate semantics, SSE handling, auth boundaries, redirects/SSRF policy, and credential-scoped discovery.
3. Add full tool-result conformance fixtures, multi-step consumer workflows with explicit bindings, setup/teardown contracts, and deterministic handling of nonportable schemas.
4. Run real consenting independent consumer/server fixtures, not only synthetic demos. Record exact source and dependency revisions.

Release gate: independent current-protocol interoperability, supported OS matrix, security review of execution/credential paths, and an owner-selected license.

## Milestone 2 — useful contributor workflow

Explicit recording with redaction and capture consent; reviewed baseline update commands; reproducible server artifact identifiers; JUnit/check annotations; pinned reusable Action release; schema-policy acknowledgements with audit history; bounded repeated-run statistics instead of single-sample latency alerts.

Use the CLI/action with a small number of consenting tool maintainers and downstream users. Ask whether it caught release-impacting failures, whether the baseline was credible, and whether CI setup cost was justified. Do not declare product-market fit from launch votes or sign-ups alone.

## Milestone 3 — opt-in compatibility network

A separately reviewed GitHub App, signed minimal result envelopes, consumer enrollment and revocation, private/public visibility rules, fixture retention and deletion, abuse controls, result provenance, rate limits, isolated execution, and an explicit trust model for public claims.

Default: execution stays on consumer-controlled runners. Public upload must be opt-in. Do not upload payloads, clone and run arbitrary repositories, or infer consent from repository visibility. A hosted service must not accept arbitrary user commands on trusted shared workers.

## Milestone 4 — hosted product and launch

Tenant isolation, billing decisions, data-processing/retention policies, observed release-impact dashboards, owner-approved branding/domain/license, and narrowly described real customer evidence. Do not show fake ecosystem weather or extrapolate sample coverage to the entire MCP ecosystem.

## Owner decisions still open

License; desired hosting provider and budget; whether the first design partners are MCP providers or consuming teams; scope of public result sharing; eventual package/Action release names; private security contact. None is silently selected by this alpha implementation.

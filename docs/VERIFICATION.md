# Verification record

Local verification for the initial 0.1.0a1 implementation, prepared 2026-09-13.

## Observed results

- **59 test methods collected: 58 passed, 1 skipped.** Core/config/schema/transport tests ran as one 44-test group; end-to-end tests ran in three nonoverlapping 5-test groups.
- The skipped test is independent interoperability with the official MCP Python SDK. The SDK is not installed locally and the environment cannot reach package registries. It is not counted as a pass.
- Runtime: Linux, Python 3.13.5, jsonschema 4.26.0, referencing 0.37.0.
- Editable installation succeeded with `pip install --no-build-isolation --no-deps -e .` using dependencies already present in the environment.
- A distributable wheel built successfully with `pip wheel --no-build-isolation --no-deps .`.
- `compileall`, the installed `canarynet --version`, demo initialization, structural validation, report generation, snapshot export, and snapshot comparison were exercised.
- The real subprocess demo produced exactly **2 regressions and 2 compatible cases**, with no schema changes. Its CLI exit code was 1, intentionally. The unused `health` tool was reported as uncovered.
- The compatible candidate, unhealthy baseline, improvements, changed schema, removed tool, invalid output, catalog mutation, startup failure, and blocked-execution cases were exercised.

## Adversarial checks

Malformed JSON, duplicate keys, nonfinite values, oversized/deep JSON, invalid response IDs, incomplete frames, invalid error objects, unsupported protocol revisions, missing capabilities, duplicate tools, cursor cycles, noisy stderr, timeout and child cleanup paths, unsolicited sampling requests, server pings, explicit environment inheritance, payload suppression, schema reference restrictions, invalid schemas, and a catastrophic-regex validation deadline.

Testing exposed two important fixes before this record: separating validator startup from per-validation deadlines, and ensuring an error on either side overrides unstable classification. Post-case catalog checks and strict response/framing checks were also added.

## Verification boundaries

The GitHub workflow is configured for Python 3.11, 3.12, and 3.13 and installs the official maintained SDK v1 line for its independent interoperability test. **This local record does not claim those remote runs passed.** Read the actual commit's workflow result before treating that matrix as verified.

No Windows/macOS run, current MCP 2026-07-28 interoperability, Streamable HTTP/OAuth test, real customer integration, sandbox penetration test, performance benchmark, hosted deployment, or ecosystem-scale test is claimed. The source/demo is synthetic but its local subprocess execution and reported arithmetic assertions are real.

The test suite checks a bounded client subset; it is not proof of complete MCP conformance or general schema containment. No automated tests establish market demand, novelty, pricing, or product-market fit.

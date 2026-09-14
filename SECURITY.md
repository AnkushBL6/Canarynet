# Security boundary

CanaryNet is an experimental local test runner, **not a sandbox** and not a security scanner.

## Before running

Review configuration, command arrays, contract inputs, and every configured tool. Use isolated, disposable development or CI environments with test credentials. Starting a server executes arbitrary code with your OS permissions before tool allowlisting can constrain calls. That code can access local files and the network. An allowlist and a minimal child environment do not remove those permissions.

`--allow-exec` is required by the CLI and check engine. Commands do not implicitly use a shell, but explicitly selecting a shell executable still executes that shell. Cases repeat; there is no transactional rollback, external-state reset, idempotency guarantee, or automatic side-effect detection. Tool annotations are untrusted hints, not execution authorization.

## Implemented boundaries

- Only explicitly configured subprocesses and allowlisted tool calls are used.
- Most parent environment variables are not forwarded; additional names require `envAllow`. PATH and basic locale/temp/platform variables remain available. Test credentials can still be read by the launched program through other OS mechanisms.
- Server stderr and remote error message/data are discarded rather than included in reports.
- Normal reports do not serialize arguments or returned payloads. They include consumer/tool/case identifiers, diagnostic paths, hashes, and timing; that metadata may still be sensitive.
- Snapshot export is explicit and includes schemas/descriptions. Review snapshots before sharing.
- JSON byte/depth caps, message/page/tool/case limits, request deadlines, and process cleanup bound common failure modes.
- POSIX subprocess groups receive cleanup signals; other operating systems are not independently verified.
- Schema validation runs in a separate deadline-bounded process. Nonlocal references and network retrieval are prohibited.
- CI uses read-only repository permissions, does not persist checkout credentials, and does not use `pull_request_target` or upload reports automatically.

## Not solved yet

There is no container/VM sandbox, network egress policy, resource quota system, authenticated hosted control plane, secret-scanner guarantee, signed result attestation, OAuth flow, or tenant isolation. Treat baseline/candidate commands as untrusted code and provide isolation externally. Do not run unknown downstream repositories on trusted runners with production secrets.

Do not publish secrets or exploit-sensitive details in public issues. A dedicated private vulnerability-reporting channel has not yet been configured by the owner; use GitHub private reporting only after that capability is enabled. No email address is invented here.

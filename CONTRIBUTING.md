# Contributing

This is an experimental project and the owner has not selected a license. Resolve licensing before inviting unrestricted external reuse or accepting contributions under an implied license.

Use Python 3.11+. Install with `python -m pip install -e .` and run `python -m unittest discover -s tests -v`. To include the independent SDK test, also install `mcp>=1.28,<2`.

Changes to classification require truth-table tests. Changes to transport require timeout, malformed-message, pagination, and independent SDK tests. Keep report tests that ensure arguments, outputs, environment values, and server error text are absent. Every new protocol version needs an explicit support claim backed by independent interoperability tests.

Do not weaken inconclusive results to passes, fabricate consumer counts, make performance/security claims from synthetic fixtures, or add telemetry/upload without an explicit privacy decision. Keep credentials out of fixtures and commits.

# ADR 0008: Authenticated local developer MCP for the Back Office helper

- Status: Accepted
- Date: 2026-10-19
- Extends: ADR 0006 and ADR 0007 for local development only.

## Context

The installed Tau SDK does not compose declared application MCP tools or a delegated
requester in local mode. The helper therefore loaded its casework skill but could
not perform the local case workflow. The user explicitly selected a local developer
connection with isolated test data for verification.

## Decision

Opt in with `BACKOFFICE_LOCAL_MCP_ENABLED=true`, the exact loopback
`BACKOFFICE_API_ORIGIN` and `BACKOFFICE_LOCAL_SOURCE_UID`. The local-stack launcher
passes its verified API configuration to the helper. Both Tau exclusion flags stay
true and the helper binds to loopback. Hosted markers, assertion mode, non-loopback
origins, paths, credentials in URLs and missing source pins reject this adapter.

The project extension registers only the existing application wrapper names,
`backoffice_api__list_tools` and `backoffice_api__call_tool`, using the installed
SDK MCP client for protocol validation, transport, deadlines and result projection.
The ordinary approved-tool allowlist and reviewed discovery contract still apply;
the adapter rechecks the catalog before each business call.

Before each call, verify the saved Main Sequence developer login, compare that UID
with the loopback API's verified `/me`, and verify `/healthz` reports the pinned local
SQLite source. Pin the developer to the conversation; changing login or database
blocks further calls. The API gateway retains ownership of credentials and verifies
identity through Main Sequence. The adapter never handles a token, chooses an actor
from business inputs, accesses storage/parser services or exposes an HTTP tool.
Business authorization and reconciliation remain in the shared API services.

This is explicit developer authority, not delegated requester authority. Do not
fabricate `current_requester()`, turn proofs or platform leases. Hosted sessions
retain their existing requester requirement and platform-resolved application
access. The SDK still owns inference, session/task state, persistence, cancellation
and provider credential hydration. Connection failures redact exception text, close
sessions and never replay an uncertain mutation automatically.

## Verification

Test refusal of hosted settings, arbitrary URLs, different API identity, inactive
login, changed source and changed developer. Preserve discovery gating, extra-tool
filtering, failure redaction and one-attempt mutation behavior. Test the ordinary
hosted policy and both exclusion flags unchanged.

The live local smoke test must use the actual model and extension: create cases via
MCP, allocate ready example sources, inspect retained acceptance/evaluations and ask
for current missing requirements. Validate results independently through the API.
Original bytes still enter through the supported upload API. A successful local test
makes no claim about hosted deployment, requester delegation or production readiness.

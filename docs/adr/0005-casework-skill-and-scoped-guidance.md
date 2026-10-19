# ADR 0005: Casework guidance within the read-only helper boundary

- Status: Accepted; read-only business scope superseded by [ADR 0006](0006-case-building-mcp-workflow.md). The scoped guidance-read decision remains in force.
- Date: 2026-10-19
- Extends: [ADR 0004](0004-explicit-business-cases.md) and the helper boundary in
  [ADR 0001](0001-back-office-helper-mcp-and-document-processing.md).

## Context

The explicit Case ontology needs agent guidance for analysis and case construction.
The API supports case creation, evidence linking and evaluation, but the deployed
helper intentionally exposes only ten read-only MCP queries. Its legacy assignment
projection also omits canonical CaseType and reviewer membership. A prompt must not
claim capabilities or observations that these tools cannot supply.

The installed SDK supplies a skill-scoped `read` when base tools are excluded.
The existing project hook blocked even that tool, so a discoverable skill alone
would not make its guidance usable by the helper.

## Decision

Ship `backoffice-casework` under `.tau/skills/`, register it in the source agent card
and route relevant requests to it from `.tau/SYSTEM.md`. Keep its ontology and
case-building references inside the skill directory so the SDK can read them.

The skill analyzes accessible cases and prepares a concrete case-creation or
completion plan with a UI handoff. It describes the existing operator workflow
from subject and typed case through selected evidence, revision review and Back
Office evaluation. It clearly separates verified values from proposed or unavailable
metadata. It does not turn HTTP endpoints into agent tools or infer live case types
and reviewer memberships from the limited legacy responses.

Permit `read` for exactly the release-owned files enumerated in `SKILL_FILES`:
the casework entrypoint, its two references and the existing helper entrypoint.
Resolve paths and reject symlink escapes, arbitrary files within a skill folder,
other development skills and general workspace reads. The SDK's skill reader remains
in place; no replacement filesystem tool is registered. Static guidance reads may
occur without requester/discovery because they contain no business data. They do
not change the verified-requester or discovery requirements for MCP calls.

Preserve both Tau exclusion flags, the ten-tool business allowlist, pinned MCP
contract, API authorization, and SDK-owned task/session controls. Do not grant
MetaTables, bucket, parser, direct HTTP or arbitrary staff-management access.

## Consequences and validation

The helper can explain and plan the same workflow for loans and account opening,
keeping subjects, requesters and staff reviewers separate. Persisting that plan
still requires the existing UI or a separately implemented and reviewed mutation
release. Approval text cannot enable missing capabilities.

The candidate contract gate checks all four guidance files are packaged. Focused
tests load the skill with the installed Tau loader and execute the real SDK reader
through the actual project hooks. They verify allowed guidance, denied filesystem
paths and symlink escapes, unchanged discovery/requester requirements, and denied
case-write tool names. Existing agent/MCP tests continue to cover the business
boundary. These checks prove loading and enforcement, not model behavior or hosted
production readiness; no live model or delegated hosted smoke test is claimed.

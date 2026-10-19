# ADR 0006: Execute case building through the shared Back Office MCP services

- Status: Accepted
- Date: 2026-10-19
- Extends: [ADR 0004](0004-explicit-business-cases.md).
- Supersedes: the read-only business scope of [ADR 0005](0005-casework-skill-and-scoped-guidance.md); its guidance-file read boundary remains in force.

## Context

The initial helper could analyze a legacy assignment projection and prepare a UI
handoff. The user has now authorized case MCP tools so the agent can actually build
cases. The canonical model and shared business services already support that work.
The old MCP wording incorrectly equated a person with a case, and review guidance
did not distinguish automatically accepted revisions from those requiring staff review.

## Decision

Expose approved MCP operations as adapters to the same services used by REST and
the static site. Canonical case reads expose CaseType, subject, exact Document Set
version, selected evidence, current workspace, staff memberships and evaluations.
Subject creation, typed case creation, same-subject evidence linking, the requester's
own reviewer membership, existing-source extraction and evaluation execution/retry
use existing authorization,
optimistic revisions, durable operation keys, audit events and shared processing jobs.

A Person remains a business subject with potentially many cases. A Case is a separate
instance of a CaseType pinned to a permitted Document Set version. Neither record is
the verified requester or a staff reviewer. Membership does not grant access, accept
a document or approve a business case. Loans and account opening share all these
operations; there is no loan-specific agent, pipeline or parser decision path.

The agent skill and system instructions are updated together with the MCP tool
catalog, reviewed input/output contracts and truthful side-effect annotations.
The tool policy must distinguish read-only queries from mutations rather than
requiring every approved tool to claim read-only behavior. Keep both Tau exclusion
flags, verified-requester enforcement, filtered/validated discovery and the fixed
guidance-file read exception. No direct database, bucket, parser or HTTP access is
added to the helper. SDK authentication, delegation and task/session controls remain
SDK-owned. Runtime discovery validates the SDK-projected input schemas and read-only
annotations; the offline release gate also checks output schemas and all annotations.

Read permission is not write permission. An analysis-only request remains read-only.
For a user-authorized build/completion workflow, the agent performs supported actions
after resolving subject, intent and permitted policy choice. It does not infer a new
case from an ambiguous reference, silently upgrade policies, reuse another subject's
documents, overwrite membership with a stale revision or retry uncertain mutations
with fresh operation keys. It distinguishes returned results, queued work and failures.

Respect effective acceptance from the backend. A revision already accepted by the
configured automatic parsing policy does not require staff re-review solely because
acceptance was automatic. The classification threshold, canonical validation, source
and extraction-evidence guards remain backend decisions. Review/renewal may still be
required by current state or policy. Document acceptance and complete requirements
do not approve a loan, open an account or close a case.

## Capability and release boundary

The [MCP catalog](../mcp.md) is authoritative for exact supported tool names, argument
schemas, mutations and recovery behavior. The skill provides the same catalog's
case-building sequence, with explicit handoffs for unsupported work. New source bytes
must not be invented from document text or chat attachments; only supported input
transports can persist evidence. The MCP helper may process an existing ready,
subject-owned source and explicitly link its resulting document. This does not add
chat-file uploads or automatic unknown-subject/case allocation. Generic durable-intent
inspection/resume is not exposed; uncertain responses permit identical command replay,
while unresolved locked/interrupted work receives a recovery handoff. Arbitrary staff assignment, manual review/edits and
case approval/closure remain outside this case-building slice.

Ship the API, reviewed pinned MCP contract and helper instructions as one coordinated
release. A helper connected to an incompatible catalog must fail discovery instead
of falling back to unreviewed tools. Never regenerate the pinned contract at deployment
time. Local validation and a successful push do not establish hosted readiness.

## Verification

Validate API/MCP parity, requester isolation, CaseType-policy bindings, same-subject
links, concurrency/idempotency and job dispatch/recovery through focused tests.
Validate the helper against the reviewed catalog, including correct mutation
annotations and denied unsupported routes. Load the skill through the installed Tau
loader and retain the SDK reader boundary tests. These are executable contract and
integration checks; model behavior and hosted delegation require separate verification.

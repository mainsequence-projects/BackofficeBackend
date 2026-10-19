# Back Office MCP case workflow

The business API exposes 35 tools at `POST /mcp`: 25 queries and ten scoped
mutations. They call the same application services as REST. The authenticated
Streamable HTTP server is stateless and returns structured JSON. Deployment declares
`mcp_enabled: true`; that declaration does not establish hosted readiness.

A **Person** is the business subject and can have multiple **Cases**. A Case has an
explicit CaseType and one exact permitted Document Set version. The verified caller
and staff reviewers are separate identities. Legacy assignment UIDs are the same
case UIDs; assignment responses remain compatibility projections.

## Authorization and release boundary

Delegated calls use the verified requester's permissions, never the workload's
broader permissions. Inputs cannot select an actor. Every subject-specific service
enforces ownership/reviewer access; inaccessible and nonexistent records both return
404. Taking reviewer responsibility requires reviewer permission and does not grant
access. Only the caller's own membership can be changed.

The helper retains both Tau exclusion flags, the explicit business-tool allowlist,
verified-requester enforcement and the exact guidance-file read exception. It has
no direct database, bucket, parser or HTTP tools. No manual review, document edits,
parsing-policy changes, arbitrary staff assignment, case approval or closure is
exposed. Source bytes enter through the existing authenticated UI/REST upload routes;
a chat attachment or filename is not a persisted source UID.

## Query catalog

| Tool | Arguments | REST equivalent |
| --- | --- | --- |
| `get_current_user` | None | `GET /me` (requester UID and reviewer capability) |
| `search_persons` | `search`, `limit`, `offset` | `GET /persons` |
| `get_person` | `person_uid` | `GET /persons/{uid}` |
| `get_person_schema` | None | `GET /person-schema` |
| `list_document_sets` | `search`, `limit`, `offset` | `GET /document-sets` |
| `get_document_set` | `key`, `version` | `GET /document-sets/{key}/versions/{version}` |
| `list_person_assignments` | `person_uid`, `limit`, `offset` | `GET /persons/{uid}/assignments` |
| `get_assignment` | `assignment_uid` | `GET /assignments/{uid}` |
| `get_document_set_status` | `assignment_uid` (case UID) | `GET /cases/{uid}/status` |
| `get_missing_requirements` | `assignment_uid` (case UID) | `GET /cases/{uid}/missing-requirements` |
| `list_case_types` | None | `GET /case-types` |
| `list_cases` | `search`, `responsibility`, `set_key`, `case_type_key`, `limit`, `offset` | `GET /cases` |
| `list_person_cases` | `person_uid`, `limit`, `offset` | `GET /persons/{uid}/cases` |
| `get_case` | `case_uid` | `GET /cases/{uid}` |
| `get_case_workspace` | `case_uid` | `GET /cases/{uid}/workspace` |
| `get_case_reviewers` | `case_uid` | `GET /cases/{uid}/reviewers` |
| `list_person_documents` | `person_uid`, `limit`, `offset` | `GET /persons/{uid}/documents` |
| `list_person_sources` | `person_uid`, `limit`, `offset` | `GET /persons/{uid}/sources` |
| `get_document` | `document_uid`, optional `revision` | `GET /documents/{uid}` or `/revisions/{revision}` |
| `get_document_extraction_evidence` | `document_uid`, `revision` | `GET /documents/{uid}/revisions/{revision}/extraction-evidence` |
| `list_case_evaluations` | `case_uid`, `limit`, `offset` | `GET /cases/{uid}/evaluations` |
| `get_evaluation` | `evaluation_uid` | `GET /evaluations/{uid}` |
| `get_processing_run` | `run_uid` | `GET /processing-runs/{uid}` |

Search is a literal case-insensitive substring, maximum 100 characters. Pagination
defaults to 50 items, except `list_cases` (10, maximum 20) and
`list_case_evaluations` (20). Other limits are 1–100; offsets start at zero. Follow
`has_more` and `total_items`; pages are not snapshots. `responsibility` is `all`,
`mine` or `unassigned`. Case types return permitted published policy versions;
exact policy reads and creation never silently select a newer version.

## Mutation catalog and request envelopes

Every mutation takes a nested `command` object with a caller-generated UUID
`operation_key`. Unknown command fields are rejected. Case revision/version fields
use strict integers; membership uses a strict boolean. UUIDs use JSON strings.
Reference profiles retain the canonical field validation from `get_person_schema`.

| Tool | Additional command fields | Other top-level arguments | REST equivalent |
| --- | --- | --- | --- |
| `create_person` | `profile` | None | `POST /persons` |
| `create_case` | `subject_uid`, `case_type_key`, `document_set_key`, `document_set_version` | None | `POST /cases` |
| `link_case_documents` | `case_uid`, `expected_revision`, `document_uids` | None | `PUT /cases/{uid}/documents` |
| `set_my_case_membership` | `case_uid`, `expected_revision`, `assigned` | None | `PUT /cases/{uid}/reviewers/me` |
| `evaluate_case` | `case_uid`, `expected_revision` | None | `POST /cases/{uid}/evaluations` |
| `process_source_document` | None | `source_uid` | `POST /source-documents/{uid}/process` |
| `retry_processing_run` | None | `run_uid` | `POST /processing-runs/{uid}/retry` |

`expected_revision` for links/evaluation is the loaded case revision, minimum 1.
For membership it is `get_case_reviewers.my_revision`, minimum 0, and `assigned`
is true to take responsibility or false to leave it. Link requests contain the
**full existing membership plus additions**, with distinct same-subject document
UIDs. Removal is unsupported. Creating, linking or evaluating does not accept a
document or approve the business case.

Example MCP arguments for creating an account-opening case (replace UUIDs and
choose a permitted policy version returned by `list_case_types`):

```json
{
  "command": {
    "operation_key": "00000000-0000-0000-0000-000000000001",
    "subject_uid": "00000000-0000-0000-0000-000000000002",
    "case_type_key": "account_opening",
    "document_set_key": "new_account_requirements",
    "document_set_version": 3
  }
}
```

## Building and assessing a case

1. Resolve the subject and existing cases; ask when identity or intended case is
   ambiguous. Create a subject only with supplied reference facts and authorized intent.
2. Read case types and exact policy. Create the case with its subject, explicit type
   and permitted version. A document upload never creates a case implicitly.
3. Read the workspace and selected documents. For new originals, use the UI or
   authenticated multipart `POST /source-documents/bucket-uploads` first. Process
   the returned ready subject-owned `source_uid`, then poll `get_processing_run`.
   The backend owns bucket access, classification, canonical extraction, evidence
   validation and per-type classification-confidence acceptance thresholds.
4. Inspect completed document UID, ownership, revision, evidence and acceptance.
   Preserve automatic acceptance. `needs_review` requires the staff workflow;
   incomplete/failed processing is not usable completed evidence. Explicitly append
   selected documents to the intended case using its current revision.
5. Optionally take/leave your own responsibility if authorized and a reviewer.
   Membership changes do not change the case evidence revision.
6. Call `evaluate_case`. Synchronous policies return an evaluation UID. Policies
   requiring comparisons may return `processing_run_uid`; poll until completed,
   then read the returned evaluation UID. A queued request is not a completed evaluation.
7. Read current status/missing requirements and the saved evaluation's `stale` flag.
   Report accepted alternatives, required counts, applicability, missing reference
   facts and review needs. Complete requirements do not approve a loan, open an
   account or close the case.

Current status/missing queries make no writes. They assess only explicitly linked
evidence against the pinned policy using the server UTC date. They return revisions,
policy key/version, assessment timestamp, counts, findings and next actions. Only
`satisfied` and `not_applicable` are omitted from the missing view. Optional findings
remain present; `mandatory` identifies which affect completion. Unknown applicability
has null counts. `diagnostics_complete: false` means primary blockers, not all defects.
`pending_review` is not a missing upload; alternatives are choices, not cumulative demands.
Retained evaluations are separate from fresh assessments and are never overwritten.

## Recovery and annotations

After an uncertain response, replay the **same tool and identical arguments with the
same operation key**. Changed command bodies or case targets with the same key
return 409. Case-bound evaluation commands survive asynchronous worker restoration;
legacy evaluation intents remain supported. Do not switch between REST and MCP
mutation envelopes during an uncertain retry. New business actions need new keys.
On stale revision, re-read and reconcile intent before submitting a new action.

The original process request identifies one durable run. Replaying may enqueue another
Job; worker claims and durable stage checkpoints protect execution. Use
`retry_processing_run` with its own operation key for deliberate recovery, then poll.
Completed runs remain completed. `needs_input` returns a reason requiring correction;
changed comparison inputs require a fresh evaluation, not blind retries. A dispatch
failure can return a retained run plus `dispatch_error`; inspect it and retry without
inventing a successful result. Generic interrupted-operation inspection/resume is not
an MCP tool: replay a known original command, otherwise hand off to UI/API recovery.

Query annotations are read-only, non-destructive, idempotent and closed-world.
All seven mutations advertise `readOnlyHint: false`. Membership is conservatively
marked destructive because it can remove responsibility. Extraction, evaluation and
processing retry advertise open-world and non-idempotent scheduling; other mutations
advertise idempotency through their durable command keys. Annotations describe effects;
they never grant permission.

Tau validates the approved tools' input schemas and `readOnly` flags in the installed
SDK's discovery projection. The offline release gate checks all pinned input/output
schemas and annotations. Unsupported tools are filtered; missing/drifted approved
tools block calls. Pin reviewed contracts in source, never regenerate at deployment.

## Errors and verification

Business/storage failures return `isError: true` with `structuredContent.error`
containing `status`, `detail`, and `retryable`. A retryable flag is not permission to
blindly replay a stale request. Argument validation uses SDK tool errors; unexpected
exceptions are sanitized by the SDK. Authentication/Origin rejection happens before
execution. `GET /mcp` and session deletion are unsupported. MCP clients initialize,
discover and then call tools; the body limit is 1 MiB, unsuitable for original uploads.

`tests/api/test_mcp_queries.py` checks authenticated transport, query/REST parity,
no query writes, pagination and delegated-requester isolation.
`tests/api/test_mcp_cases.py` checks case creation, strict commands, same-subject links,
revisions, target-bound idempotency, self-only responsibility, extraction/retry,
threshold acceptance, comparison workers and evaluation reads over disposable SQLite.
External bucket/parser/Job calls in these tests are controlled fixtures, not live
hosted verification. `tests/agent` exercises Tau hooks, discovery and guidance access.
Run `python -m scripts.check_agent_contract` before release.

The read-only `python -m scripts.verify_mcp_queries` verifier can compare available
records through an already configured local MetaTables runtime and SDK login. It
creates no fixtures. Hosted delegation, migration/role readiness and deployment of
the parser contract required by the backend remain separate release checks.

See [ADR 0006](adr/0006-case-building-mcp-workflow.md) and [case guidance](cases.md).


## Automatic allocation (ADR 0007)

| Tool | Arguments | REST equivalent |
| --- | --- | --- |
| `list_document_intakes` | `limit=20`, `offset=0` | `GET /document-intakes` |
| `get_document_allocation` | `allocation_uid`, target `limit=20`, `offset=0` | `GET /document-allocations/{uid}` |
| `allocate_document` | `command={operation_key, intake_uid}` OR `command={operation_key, source_uid}` | `POST /document-allocations` |
| `resolve_document_allocation` | `allocation_uid`, `command={operation_key, subject_uid, expected_revision}` | `POST /document-allocations/{uid}/resolve` |
| `retry_document_allocation` | `allocation_uid`, `command={operation_key}` | `POST /document-allocations/{uid}/retry` |

The three commands are mutations that can dispatch external processing, with the
same strict Pydantic validation and requester isolation as REST. Intake upload is
multipart through the Drop files screen/API; these tools do not accept original
bytes, local paths, URLs or chat attachment text. An intake starts processing on
upload. The allocation service resolves its Person, applies per-type acceptance,
links to all eligible cases and evaluates each case. Only uncertain subject
identity requires a user selection. Explicit single-case work uses the existing
case tools instead of automatic allocation.

Each requester sees only their own intakes. Background workers refresh requester
directory facts and cap reviewer rights at those available at submission. Target
results are paginated (`targets_has_more`, `targets_offset`, `target_count`); reads
do not dispatch jobs. Preserve operation keys after uncertain responses. Resolving
requires the observed allocation revision and cannot override conflicting identity.
Failures retain extraction and individual case outcomes; retry does not duplicate
successful links. See [the allocation API](document-allocation.md) for limitations,
identity evidence, queue behavior and deployment prerequisites.

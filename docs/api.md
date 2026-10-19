# Back Office business API

The implemented API is `api/app/main.py`. Interactive OpenAPI documentation is at
`/docs` on the API origin; through the local Vite proxy use `/api/openapi.json`
for the machine-readable contract. The frontend's `/docs/` is its separate user guide.
All persistence goes through the installed Main Sequence MetaTables client and
bound SQLAlchemy statements. The application never opens a database connection.

## Identity and case access

Main Sequence verifies every request. Delegated calls act for the SDK-verified
requester; ordinary calls act for the verified caller. Browser parameters and
identity headers cannot choose an actor. A person record is a business profile,
not an authentication principal.

The trusted creator owns a case. Its people, documents, raw sources, assignments,
evaluations and history share that access boundary. Other users receive 404.
Reviewers can access all cases. Reviewer permission comes from a signed Organization
admin fact, a server-configured comma-separated `BACKOFFICE_REVIEWER_UIDS`, or
membership in a configured `BACKOFFICE_REVIEWER_TEAM_UIDS`. Team checks use the
SDK's verified identity. An empty configuration grants no additional reviewer role.
Only reviewers can accept or reject a submitted document. API workload MetaTables
roles and this business permission are separate checks.

Migration `backoffice_0002` adds nullable `created_by` ownership without rewriting
`backoffice_0001`. Historical rows lacking ownership are reviewer-only. New people
always record the verified creator and an immutable first profile revision.

## Endpoints

All UIDs and operation keys are UUIDs. Each body rejects unknown attributes.

| Action | Endpoint | Contract |
| --- | --- | --- |
| API identity | `GET /`, `GET /me` | Verified `user_uid`, `can_review`; root also identifies the API. |
| Assistant discovery | `GET /assistant/context` | Authenticated `{ environmentUid, agentUid }` for the deployed Back Office helper in the API's own branch and Environment. |
| Readiness | `GET /readyz` | Verifies the ownership migration and explicitly published catalog; never runs setup. |
| Document types | `GET /document-types` | Thirteen exact document/schema versions, shared by all document-set workflows. |
| Form schemas | `GET /document-types/{type}/schema?version=1`, `GET /person-schema` | Canonical/draft document schemas or editable reference-profile schema, preserving field descriptions. |
| Document sets | `GET /document-sets?search=&limit=50&offset=0` | Paginated published requirement definitions; literal key/name search. |
| Exact document set | `GET /document-sets/{key}/versions/{version}` | Exact published definition; no fallback to the latest version. |
| People | `GET /persons?search=&limit=50&offset=0`, `POST /persons` | Authorized search and creation. Create body: `operation_key`, `profile`. |
| Person | `GET /persons/{uid}`, `PUT /persons/{uid}` | Replacement reference profile; update adds `expected_revision`. |
| Assignments | `GET /persons/{uid}/assignments`, `POST /persons/{uid}/document-sets` | Assign exact `document_set_key` and `document_set_version` with an `operation_key`. |
| Live assignment status | `GET /assignments/{uid}/status` | Fresh assessment with pinned policy, input revisions, counts, alternatives and next actions; no writes. |
| Missing requirements | `GET /assignments/{uid}/missing-requirements` | Outstanding projection of the same live assessment, including optional requirements and primary blocking reasons. |
| Assignment detail | `GET /assignments/{uid}` | Pinned policy version, assignment revision, selected `document_uids`. |
| Assignment evidence | `PUT /assignments/{uid}/documents` | `operation_key`, `expected_revision`, complete selected `document_uids`. Version one permits adding membership; removal is explicitly rejected. |
| Documents | `GET /persons/{uid}/documents`, `POST /persons/{uid}/documents` | Create with `operation_key`, `document_type`, `schema_version`, draft `payload`, `raw_document_refs`. |
| Document detail | `GET /documents/{uid}` | Latest revision and its payload, source references, submission status, effective review and derived acceptance. |
| Save a draft | `PATCH /documents/{uid}/draft`, `POST /documents/{uid}/revisions` | `operation_key`, `expected_revision`, replacement `payload`, replacement `raw_document_refs`. Every save appends a new revision. |
| Submit | `POST /documents/{uid}/submit` | `operation_key`, `expected_revision`; complete canonical validation and at least one ready owned raw source are required. |
| Reviews | `GET /documents/{uid}/reviews`, `POST /documents/{uid}/reviews` | Review body includes `operation_key`, `expected_revision`, `expected_decision_sequence` (initially zero), `decision`, `reason`. |
| Revisions | `GET /documents/{uid}/revisions` | Immutable historical submitted attributes and retained drafts. |
| Exact retained revision | `GET /documents/{uid}/revisions/{revision}` | Exact historical attributes, status and raw sources, with that revision's effective review and logical document/person metadata. Returns 404 for unknown revisions and inaccessible cases; independent of history-list limits. |
| Start an upload | `POST /source-documents/uploads` | `operation_key`, `person_uid`, `filename`, `media_type`, `byte_count`, `content_sha256`; returns `uid`, `chunk_bytes`. |
| Write a chunk | `PUT /source-documents/uploads/{uid}/chunks/{index}` | `content_base64`; identical retries succeed, differing replacements fail. |
| Resume an upload | `GET /source-documents/{uid}` | Manifest and `received_chunks` so the client sends only missing indices. |
| Finalize upload | `POST /source-documents/uploads/{uid}/finalize` | `operation_key`; verifies all ordered chunks, sizes, checksums and media signature. |
| Person's sources | `GET /persons/{uid}/sources` | Bounded manifest list without source bytes. |
| Download | `GET /source-documents/{uid}/content` or `GET /source-documents/{uid}/chunks/{index}` | Ready owned sources only. Embedded clients reconstruct bounded chunks and verify the checksum. |
| Evaluate | `POST /assignments/{uid}/evaluations` | `operation_key`, `expected_revision`; freezes exact inputs and evaluates synchronously. |
| Evaluation history | `GET /assignments/{uid}/evaluations` | Persisted summaries, newest first. |
| Evaluation result | `GET /evaluations/{uid}` | Summary, reason-coded findings, exact frozen inputs and live `stale` indicator. |
| Audit history | `GET /persons/{uid}/history` | Trusted actor, action, time, correlation and record references. |
| Inspect operation | `GET /operations/{operation_key}` | Original actor only; durable status and recorded result, without internal mutation plans. |
| Resume operation | `POST /operations/{operation_key}/resume` | Original actor only; resumes the server's already validated durable plan and rechecks current review permission. |

People, per-person documents, sources, assignments, evaluation history and audit
pages accept `limit` (1–100) and `offset` and return `items`,
`total_items`, `limit`, `offset`, `has_more`. SQL counts use the same authorization
and search predicates as the page. Revision/history lists are bounded; collection
pages are not transaction snapshots. The forms catalog and policy catalog are code-owned.

## Submission, review and concurrency

Draft payloads can be incomplete; saving creates a new numbered revision instead
of changing historical content. Submission validates the exact canonical schema,
checks source readiness and ownership, freezes the revision, then advances the
submitted revision pointer. A review must target the current submitted revision.
No client can set `accepted` or supply its own reviewer identity. Creating a new
draft shows pending acceptance and makes earlier evaluations stale; the earlier
submitted revision and its decisions remain in history.

Findings can open `/documents/{uid}/revisions/{revision}` to inspect their retained
attributes and sources. This read-only route retrieves the exact revision directly
and its highest review sequence, even when newer history exceeds the paginated
revision or review lists. It never substitutes the latest revision. Document-level
metadata, including `person_uid` and the current submitted pointer, remains present.

Profile, assignment, document and review updates carry the version observed by
the editor. Stale versions return 409. Review decisions also compare their latest
sequence. A second human's decision cannot be silently replaced.

Every command has a client-generated `operation_key`. Preserve the complete command
and key until the outcome is known. Identical retries return the recorded result;
reusing a key with different content or actor returns 409. Cross-table changes use
an application intent and a per-person control row in the existing processing-run
MetaTable. The server persists its validated write plan before changing business
rows, and executes each step idempotently. Concurrent operations and reads of a
case with unfinished writes return 409 rather than exposing an intermediate case.
A timeout leaves the original intent available for replay. The operation endpoints
can inspect or resume that intent after a process restart. If failure occurred
before the plan was persisted, retry the original command. Locks are not discarded
on a timer, and a new operation key is not a recovery mechanism.

This is a recoverable sequence of governed calls, not a transaction across HTTP
requests. Direct writes outside the business service can violate its lifecycle
rules and require explicit recovery. Each request pins its selected MetaTables
DataSource, so a runtime switch cannot redirect a later step to another database.

## Upload limits

Supported sources are PDF, PNG, JPEG and UTF-8 plain text. Each file is at most
10 MiB; each decoded chunk is at most 256 KiB. All non-final chunks must have that
exact size. Request bodies are bounded at 1 MiB before JSON parsing. Display
filenames never become filesystem paths. Content responses are attachments with
`nosniff`, no-store caching and a restrictive content policy.

The source stays uploading until its complete size, ordered chunk indices, each
chunk checksum, complete SHA-256 and media signature pass. Ready sources and
accepted chunks cannot be overwritten. Reassembly reads bounded batches through
MetaTables; a browser can download individual chunks to stay within the delegated
transport's response budget. Failed validation leaves the upload unfinalized.

Requests disconnected before the complete body arrives end with an internal 499
response, without invoking a business handler or producing an ASGI error traceback.
Completed requests retain the same body limits and validation.

## Assistant discovery

The API resolves the helper from the Main Sequence SDK's current repository branch
and Organization Environment, using the repository-owned Agent Card name. It checks
both scope identifiers and requires exactly one Agent with a deployed runtime.
The response includes identifiers only; no credentials or runtime URL is returned.
Browser-selected Environment or Agent parameters do not affect discovery.

Missing configuration, missing deployment and ambiguous Agents return explicit 503
errors. Platform authorization failures retain their 401/403 status. Discovery never
selects another branch or Environment to work around an unavailable helper. Loopback
development uses the local Tau source through `/__agent__` directly.

## Reconciliation behavior

The evaluator uses the assignment's pinned policy and server UTC calendar date.
It checks conditional applicability, required evidence counts, accepted alternatives,
submission and review state, policy-required fields, permanent/fixed-term validity,
freshness, names, reference birth dates, addresses and available employment status.
Unknown reference values produce `needs_information`. Duplicate source content
and duplicate reporting periods do not increase a requirement's count.

Results use `satisfied`, `missing`, `failed`, `pending_review`, `needs_information`,
`not_applicable`, with stable reason codes and exact document/review references.
The completion count includes mandatory requirements whose applicability is still
unknown, so unknown conditions cannot produce a completed case. Inputs include the
person revision, policy definition, assignment membership, document revisions,
effective reviews, source hashes, evaluator version and evaluation date. Changes
to any of these make the stored result stale without rewriting it.

The authored onboarding policy is explicitly illustrative. The service does not
perform OCR, validate document authenticity or MRZ check digits, infer source-of-funds
legitimacy, or make a legal onboarding decision. Human reviews and approved policy
choices remain explicit. Ten read-only [MCP query tools](mcp.md) now share these services. Tau, extraction
and mutation MCP adapters remain separate work.

Live status reads compare two input collections and reject intervening changes with
409 `assessment_inputs_changed_retry_query`. Findings expose the primary blocker per
requirement (`diagnostics_complete: false`), not an exhaustive defect list. The missing
view excludes satisfied/non-applicable requirements; pending review is distinct from
missing evidence. See [MCP query semantics](mcp.md) for the shared result contract.

## Setup, deployment and verification

The current dependency and copied skill bundle use MetaTables 0.1.49. The
[namespace workflow](namespace-workflow.md) records verified automatic creation,
repeat migration behavior and the separate human workload grants.

The explicit local launcher migrates the verified local SQLite runtime and calls
`publish_catalog()` before starting the API. The hosted migration Job does the
same through `scripts/migrate_backoffice.py`. Imports, readiness and API startup
perform no migrations or catalog publication.

`.mainsequence/workflows/backoffice.yaml` declares `backoffice_api` and the
`migrate-backoffice` Job, with `image → migrate → deploy_api` dependencies and
MetaTables branch reader access. It was validated against the registered backend
branch's current workflow API 3.0.0 template with no errors or warnings. Namespace
roles follow the installed MetaTables guidance: first migration creates an absent
namespace and gives the Job editor; its manager grants the API workload data_writer
and an appropriate human/Team owner. Existing namespaces need an editor grant for
the migration Job. Reviewer configuration is separate. No hosted migration is run
from a developer process.

Validation includes 79 offline backend tests, physical migration up/down/repeat
checks, lost-response recovery, ownership/reviewer denial, stale versions, uploads
and HTTP business workflows. `scripts/verify_local_api.py` additionally passed
against the actual installed MetaTables 0.1.48 API using isolated local SQLite:
four multi-chunk-capable source uploads, submission, review, a complete onboarding
evaluation, persistence reads, and stale detection after a new draft. This does
not establish hosted engine or deployment behavior.

With an explicitly isolated local stack and a server-configured test reviewer:

```bash
uv run python -m scripts.verify_local_api --base-url http://127.0.0.1:15174/api
```

The verifier rejects non-loopback targets and checks actual Local/SQLite runtime
state before creating identifiable test cases. It retains fixtures in that local
test runtime. Never run it against a hosted API or the developer's ordinary data
without selecting the intended test runtime first.

## Per-document-type parsing acceptance

See [ADR 0003](adr/0003-document-parsing-workflow-and-classification-policy.md).
The score is **classification confidence for the exact document revision**, expressed
in percent (`60` means 60%), not the percentage of attributes extracted. Policies
are stored as immutable revisions in `backoffice.parsing_policy`; outcomes and the
applied policy are retained in `backoffice.parsing_result`.

Only verified organization administrators can use these settings endpoints:

- `GET /admin/parsing-settings?document_type=passport`: read the current passport policy.
- `PUT /admin/parsing-settings`: publish a new policy revision for the specified type.

```json
{
  "operation_key": "01192945-ae88-4e72-a95e-8bcbecc6aa27",
  "document_type": "passport",
  "expected_revision": 0,
  "automatic_acceptance_enabled": true,
  "acceptance_threshold_percent": "60.00"
}
```

The response includes `document_type`, `score_kind: "classification_confidence"`,
`revision`, `automatic_acceptance_enabled`, `acceptance_threshold_percent`,
`changed_by`, and `changed_at`. Percentages serialize as decimal strings. Revisions
are independent per type: changing passports does not modify bank statements.
No policy is created by reading; an unconfigured type returns revision zero,
automatic acceptance disabled, and a null threshold. There is no global fallback.
To disable acceptance, publish a new revision with `automatic_acceptance_enabled: false`.
Configuration affects future completion decisions; historical outcomes retain their
original policy. Reuse the same operation key and body after an uncertain response;
stale revisions or changed input under the same key return 409.

`POST /documents/{uid}/parsing-results` is available only to organization administrators
or the explicitly configured trusted processing identities in
`BACKOFFICE_PARSING_PROCESSOR_UIDS` (comma-separated Main Sequence User UIDs).
The score endpoint is not an ordinary browser or MCP helper capability.

```json
{
  "operation_key": "b5ff3d19-1526-43f6-9004-1b2d7437d371",
  "expected_revision": 1,
  "parsing_score_percent": "60.00",
  "extractor": "classification-provider/version"
}
```

The backend derives the policy type from the document, never from a completion
request. It validates canonical attributes and finalized sources belonging to the
same person. A valid document with an enabled type policy and score at or above its
threshold is submitted and automatically accepted, with a revision-bound review.
Missing/disabled policy, missing or low score, missing evidence or incomplete attributes
produce `needs_review`; invalid ownership/source state is an error. A complete document
may be submitted while awaiting review. Existing reviews cannot be overwritten by a
new parsing completion. `accepted` still does not imply all document-set requirements
are satisfied.

The result includes `document_type`, `score_kind`, `decision`, `reason_code`,
`policy_revision`, and `review_uid`. Document reads expose `parsing_result` with the
recorded score and threshold; historical revision reads retain their original result.
New parsing results on a later revision require a separate operation. A recorded
incomplete result is not silently re-scored after a threshold change.

Provider adapters convert 0–1 probabilities to percentages exactly once using
`services.parsing_confidence.confidence_percent`, rounding downward to 0.01% rather
than promoting a below-threshold score. Explicit type selection does not imply a
score. The page aggregator requires the ingested source manifest and derives one
score only for pages of the same supported type.

Migrations `backoffice_0003` and `backoffice_0004` add the policy/result tables and
per-type policy scope. Legacy global rows remain historical only. Hosted migrations
run through the existing deployment migration Job. The policy and completion service is now used by the
[bucket-backed extraction workflow](document-processing.md).

## Actual extraction workflow

[Bucket-backed extraction](document-processing.md) implements multipart upload, durable
Job dispatch, strict ParsingMotor requests, canonical validation and automatic acceptance.
Use `POST /document-processing`, then poll `GET /document-processing/{uid}`.
The parsing endpoints will be deployed separately by the parser owner.

### Revision extraction evidence

`GET /documents/{uid}/revisions/{revision}/extraction-evidence` returns the authorized
revision's retained parser observations and field candidates, or `evidence: null`
for manual/legacy revisions. It uses the same case ownership and unfinished-operation
guard as document reads. See [evidence persistence](document-processing.md#version-2-evidence-persistence).

### Comparison-enabled evaluations

For policies with comparison rules, `POST /assignments/{uid}/evaluations` returns
HTTP 202 and `processing_run_uid`. Poll `GET /processing-runs/{uid}`, then read
`evaluation.uid` through `GET /evaluations/{uid}`. Transient failures retry through
`POST /processing-runs/{uid}/retry`. Policies without comparisons retain HTTP 201.
See [comparison lifecycle and citations](document-comparisons.md).

### Case queue, workspace and staff responsibility

`GET /review-queue` returns a bounded, authorized page of document-set cases with
subject identity, active staff memberships, current Back Office findings and a
workflow state. Query parameters: `search`, `set_key`, `responsibility` (`all`,
`mine`, `unassigned`), `limit` (1–20, default 10), and `offset`. Counts derived from
returned items are page-local; `total_items` covers the filtered accessible cases.
Loans and new accounts use these same queries and policy evaluator.

`GET /assignments/{uid}/workspace` returns the case's subject, pinned policy,
linked current document revisions, source-page/field-evidence summaries, current
findings, latest retained evaluation with its stale flag, active reviewer
memberships, and the latest 20 subject-wide audit events. Full extraction evidence
is loaded separately for the selected revision. The read rejects concurrent input
changes and never substitutes stale comparisons into current findings.

`GET /assignments/{uid}/reviewers` returns active staff memberships, the caller's
membership revision (including inactive membership), and `assigned_to_me`.
`PUT /assignments/{uid}/reviewers/me` takes an operation key, `expected_revision`
(zero for a new membership), and boolean `assigned`. Only an authorized reviewer
can take or leave their own responsibility. Several reviewers can be active at
once. This initial interface does not assign other staff or query a staff directory.

A case subject is a business Person record; a reviewer is a verified Main Sequence
User UID. These identifiers never share a foreign-key relationship. Reviewer names
come from verified request identity, not submitted document data. Membership uses
its own optimistic revision, the existing durable mutation/audit mechanism, and
migration `backoffice_0007`; it does not alter case evidence revisions, invalidate
an evaluation, grant read/review permissions, or record approval. No new helper
MCP tools were added.

Local verification: `python -m scripts.verify_casework --source-uid <verified-local-uid>`
exercises both policies through the local MetaTables API. A fresh process can
read retained memberships using `--verify-case-uid <case-uid>`. The script refuses
hosted or unexpected sources and uses only synthetic subjects.

# Back Office MCP queries

The business API serves ten read-only tools at `POST /mcp` through the installed
Main Sequence authenticated Streamable HTTP integration. The server is stateless
and returns JSON responses. The deployment workflow declares `mcp_enabled: true`;
this declaration alone does not establish a deployed release or connected agent.

The caller must use the same verified identity as the REST API. Delegated requests
use the verified requester, including that requester's reviewer permissions. A
workload's broader privileges never replace the requester's case access. Client
arguments cannot choose an actor. All case queries enforce ownership/reviewer access;
inaccessible and nonexistent cases both return 404. The installed SDK checks MCP
Origin admission. No reviewer, upload, extraction or case-write tools are registered
in this first slice.

## Available tools

| Tool | Arguments | REST equivalent |
| --- | --- | --- |
| `get_current_user` | None | `GET /me` |
| `search_persons` | `search`, `limit`, `offset` | `GET /persons` |
| `get_person` | `person_uid` | `GET /persons/{uid}` |
| `get_person_schema` | None | `GET /person-schema` |
| `list_document_sets` | `search`, `limit`, `offset` | `GET /document-sets` |
| `get_document_set` | `key`, `version` | `GET /document-sets/{key}/versions/{version}` |
| `list_person_assignments` | `person_uid`, `limit`, `offset` | `GET /persons/{uid}/assignments` |
| `get_assignment` | `assignment_uid` | `GET /assignments/{uid}` |
| `get_document_set_status` | `assignment_uid` | `GET /assignments/{uid}/status` |
| `get_missing_requirements` | `assignment_uid` | `GET /assignments/{uid}/missing-requirements` |

Search text is a literal case-insensitive substring (maximum 100 characters).
Person search covers name/external reference; document-set search covers key/name.
Pagination defaults to `limit=50`, `offset=0`; limits are 1–100. Page results contain
`items`, `total_items`, `limit`, `offset`, and `has_more`. Follow pages rather than
assuming the first page is complete. Pages are not transaction snapshots.
Document-set lists show published versions; exact retrieval never falls back to a
newer version. `tools/list` advertises input/output schemas and read-only,
non-destructive, idempotent annotations.

## Asking what is missing

1. Find the person through `search_persons`; resolve ambiguous matches with the user.
2. Read `list_person_assignments`. If empty, explain that no requirement set is
   assigned. If several apply, identify the requested assignment or report each
   separately.
3. Call `get_missing_requirements(assignment_uid)` for a fresh assessment. Use
   `get_document_set_status` when satisfied/non-applicable requirements are also needed.
4. Explain each returned reason and next action with its document/revision/review
   references. Alternatives are choices, not a requirement to provide every type.

These calls use the pinned policy and server UTC evaluation date, assess only
explicitly selected assignment documents, and do not save an evaluation or mutate
any business record. Results include person/assignment revisions, policy key/version,
evaluator version, assessment timestamp, summary and requirement findings. Findings
include applicability, mandatory status, accepted alternatives and date rules,
qualifying/required counts, shortfall, referenced fields/evidence, and next action.
Counts are null when applicability is unknown or false. Outstanding findings include
optional requirements; `mandatory` identifies which affect completion.

`pending_review` means evidence exists and needs review. `needs_information` can mean
unknown applicability, missing fields, or a draft needing submission. `failed` retains
the evaluator's reason, such as expiration, duplicate evidence or a name mismatch.
Only `satisfied` and `not_applicable` are excluded from the missing-requirements view.
`diagnostics_complete: false` makes explicit that the evaluator reports the primary
blocker per requirement rather than every possible defect.

The service collects inputs twice and checks case-lock admission. If inputs changed,
retry the read after `assessment_inputs_changed_retry_query` (409). Retained historical
evaluations remain separate and are not overwritten by these queries.

## Errors and transport

Expected business/storage tool failures return `isError: true` with
`structuredContent.error` containing `status`, `detail`, and `retryable`. MCP argument
validation failures use the SDK's standard tool error. Unexpected exceptions are
sanitized by the SDK. Authentication/Origin rejection occurs at HTTP admission
before tool execution. `GET /mcp` and session deletion are unsupported in the stateless
profile. Normal MCP clients should negotiate with `initialize`, then discover/call tools.

Example call after initialization (placeholder UUID must be replaced):

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_missing_requirements",
    "arguments": {"assignment_uid": "00000000-0000-0000-0000-000000000000"}
  }
}
```

## Verification

`tests/api/test_mcp_queries.py` exercises the actual MCP HTTP transport and SDK identity
middleware with a stubbed identity verifier and disposable relational SQLite storage.
It checks all ten tools against REST, absence of query writes, tool discovery,
pagination, authorization/Origin errors, delegated requester isolation, exact policy
versions, unknown applicability, concurrent changes, and primary requirement reasons.
These tests do not verify deployed platform assertion signing or hosted database roles.

For read-only integration through the actual installed MetaTables client/API and
existing SDK login:

```bash
.venv/bin/python -m scripts.verify_mcp_queries
```

The verifier requires a ready local SQLite runtime, published catalog and an accessible
assignment among the first ten people. It makes no fixture writes, checks all ten tools
against REST, and rechecks the runtime DataSource afterward. Pass `--seed` to create one clearly
labeled local person and assignment when no accessible fixture exists; these two
setup commands are retained for inspection, while the MCP queries remain read-only. It uses in-process HTTP
for the business API and the running local MetaTables service for actual storage.

See [ADR 0001](adr/0001-back-office-helper-mcp-and-document-processing.md) for the full
planned catalog and later upload/classification/extraction work.

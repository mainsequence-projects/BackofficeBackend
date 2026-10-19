# Main Sequence integration and documentation contracts

This is the backend integration plan. It complements the
[project plan](project-plan.md) and [document catalog](document-catalog.md).
The [foundation guide](foundation.md) records implemented contracts and the tested
package pair. Resource bindings and deployment workflows still need verification
against the selected Environment before delivery.

## Package and resource boundaries

| Package or resource | Responsibility |
| --- | --- |
| `mainsequence` | Platform identity, CodeRepository context, Jobs, releases, and supported recorded inference. |
| `mainsequence-metatable` / `metatables` | Managed table definitions, application migration provider, catalog metadata, governed reads/writes. |
| `ms-tau-sdk` / `ms_tau_sdk` | Tau runtime, authenticated agent transports, session lifecycle, and platform integration. |
| Pydantic | Domain/request/response schemas and validation. |
| FastAPI plus the selected MCP library | Business REST and MCP adapters. |
| `@dev-mainsequence/command-center-sdk` | Frontend shell, views, controls, theme, and embedded API transport. |
| `@dev-mainsequence/command-center-ai` | Frontend conversations with Main Sequence Agents. |

The tested foundation uses `mainsequence[mcp]==9.0.29` with
`mainsequence-metatable==0.1.47`, locked in `uv.lock`. The published MetaTables
package fails to import against SDK `9.0.30` because `ShareableObjectMixin` was
removed; keep this compatible pair until an upgrade passes the contract suite.
The agent milestone will add and verify `ms-tau-sdk`. Hosted API compatibility
is a separate deployment check.

## MetaTables persistence

Application table models follow `PlatformManagedMetaTable` from `metatables` and
the platform's documented declarative model convention. Operational documents and
people are managed records. Optional future aggregate metrics may use time-index
tables without changing the operational storage model.

Each table supplies a stable namespace/identifier, purpose, labels, explicit
physical name, primary key, relationships, and column metadata. In the current
model convention, field labels/descriptions are recorded in column `info`; table
metadata uses `__metatable_namespace__`, `__metatable_identifier__`,
`__metatable_description__`, and `__metatable_labels__`.

Repositories use the governed public client operations, including compiled,
parameterized operations through `MetaTable.execute_operation` where appropriate.
Resolve the selected runtime through the Main Sequence/MetaTables context. Do not
hardcode a catalog UID or infer data isolation from the Git branch alone. Separate
Environments need the correct configured MetaTables runtime/DataSource bindings.

Use stable operation IDs for mutations and explicit expected revisions for reviews
and corrections. Paginate reads. Record staged/finalized state when an operation
spans multiple calls. Retry an ambiguous mutation only after checking its recorded
state; do not assume a timeout means that no write occurred.

### Migration and ownership lifecycle

Own the provider under `src.backoffice.migrations:migration`, with a unique
application-prefixed version table. The deployment workflow's migration Job calls
`upgrade_application` for that provider from the candidate application image.
The API and agent deploy steps depend on successful migration. Migrations are an
explicit deployment operation; application startup does not execute them.

In each Environment, a human creates the application namespace and becomes its
`owner`. Grant the migration Job workload `editor` and row-writing workloads
`data_writer`. A Team is an optional way to group principals, not a prerequisite.
Resources also need the platform `reader` policy on the MetaTables branch to
discover its release. Record namespace, workload, runtime and release bindings
using non-secret identifiers. This follows the deployment guidance bundled with
MetaTables `0.1.47`, including workflow API `3.0.0`.

Applied migrations remain immutable. Use additive changes while the previous
release can still serve requests. A deployment rollback does not roll back table
schemas; schema recovery is an explicit, documented operation.

## API and MCP contracts

The API entry point stays at `api/app/main.py` and retains Main Sequence's request
identity integration. REST and MCP call the same services, enforce the same case
access and reviewer permissions, and return compatible typed business results.
MCP mounted on the business app must retain verified caller identity through the
actual transport; test this path explicitly.

All endpoints and tool names below are proposed application interfaces, not built-in
Main Sequence operations.

| Operation | REST interface | MCP tool |
| --- | --- | --- |
| Discover types | `GET /document-types` | `list_document_types` |
| Retrieve canonical/draft form contract | `GET /document-types/{type}/schema` | `get_document_schema` |
| Create/read a person | `POST /persons`, `GET /persons/{uid}` | `create_person`, `get_person` |
| Start an upload | `POST /source-documents/uploads` | `start_document_upload` |
| Upload/finalize bounded source content | Chunk and finalize routes under `/source-documents/uploads/{uid}` | Typed upload/finalize adapters only if the agent actually needs them |
| Register a document using ready source UIDs | `POST /persons/{uid}/documents` | `register_document` |
| Update draft attributes | `PATCH /documents/{uid}/draft` | `update_document_draft` |
| Submit a revision | `POST /documents/{uid}/revisions` | `submit_document_revision` |
| Read available sets | `GET /document-sets` | `list_document_sets` |
| Assign a set version | `POST /persons/{uid}/document-sets` | `assign_document_set` |
| Evaluate an assignment | `POST /assignments/{uid}/evaluations` | `evaluate_document_set` |
| Read findings | `GET /evaluations/{uid}` | `get_reconciliation_report` |
| Review an exact revision | `POST /documents/{uid}/reviews` | `review_document`, restricted to authorized reviewer use |
| Start/read processing | `POST /documents/{uid}/processing`, `GET /processing-runs/{uid}` | `start_document_processing`, `get_processing_status` |

The default reconciliation agent's tool surface omits the reviewer mutation. A
future reviewer-assistant use case must explicitly implement its permissions and
review interaction before exposing it.

Document each operation's purpose, input/output schemas, mutation effects,
permissions, idempotency, revision handling, error/reason codes, examples, and
long-running behavior. Generate references from actual schemas and tool catalogs.
Forms consume an envelope with canonical schema, draft schema, selected version,
read-only fields, UI hints, and assignment-specific requiredness.

## Tau agent contract

The planned service module is deliberately small:

```python
from ms_tau_sdk import create_app

app = create_app()
```

The agent owns its dedicated `api/tau/main.py` entry point. Export the app returned
by the SDK so its installed request-identity declaration remains visible to the
platform launcher. The SDK owns agent authentication, transport, leases,
cancellation, and session persistence.

The backend repository also owns:

- `.agents/agent_card.json`: truthful agent name, purpose, version, implemented
  skills and supported response kinds.
- `.agents/skills/backoffice/`: focused executable workflow instructions, including
  inputs, outputs, tool schemas, side effects, completion criteria, and escalation.
- `.tau/SYSTEM.md`: document-reconciliation behavior, evidence standards, handling
  of missing information, and allowed workflow boundaries.
- `.tau/prompts/`: reusable task instructions where useful.
- `.tau/extensions/`: thin adapters only when the project needs behavior that its
  MCP application does not already provide.

The workflow declares `kind: harness_agent` and the business API in
`spec.mcp_applications` by resource key. The business API declares MCP support.
Main Sequence resolves the target release; the agent does not embed guessed URLs
or release UIDs. Verify the registered tool catalog against the selected Tau version.

Choose provider, model, and thinking configuration through the authorized platform
catalog. The repository owns behavior; Main Sequence owns provider access and
credential delivery. Frontend clients never receive model-provider credentials.

User-scoped tools use verified Main Sequence requester delegation where configured.
Workload-scoped processing uses its workload identity and explicit grants. A client
supplied person UID selects a business record, not an authentication identity.
Refused delegation must not silently fall back to broader workload access.

Documented application skills and the source card must reflect implemented tools.
Planning this structure does not advertise an unimplemented agent as ready. Test
session resume/cancellation, authorization failures, evidence references, schema
errors, missing source data, and prompt-like text embedded in a raw document.

## Processing and recorded inference

Jobs process source references with bounded memory and execution time. Persist a
processing intent before starting a Job and link its JobRun UID when known. A lost
start response is reconciled by operation identity before submitting another run.
Job completion writes a new proposal/evaluation; it does not overwrite reviewed
document revisions.

Where structured extraction uses `InferenceClient`, use the Main Sequence provider
catalog, recorded request identity, and Pydantic-derived response schema. The
reviewed contract takes bounded text/JSON: extract/OCR the source first. Preserve
request and conversation UIDs, and validate completed output before persisting it.
Tau remains the agent runtime; direct extraction is an application operation.

Do not rely on a proposed Tau batch API: the inspected integration guidance marks
that capability as pending. Use the supported service/agent execution path and
ordinary Main Sequence Jobs for implemented processing capabilities.

## Delivery resources

| Backend workflow resource | Purpose | Dependency |
| --- | --- | --- |
| Migration Job | Apply application metatable provider and refresh catalog metadata | Candidate image |
| Processing/evaluation Jobs | Extract source text and evaluate bounded batches | Compatible table schema and workload access |
| Business FastAPI release | REST, MCP, schema forms, and authorized source access | Successful migration |
| Tau Harness Agent release | Reconciliation conversations using business MCP | Successful migration and available business API |

The frontend workflow declares the Static Site and its Environment-specific API
bindings. Validate current workflow shapes with Main Sequence before deployment.
Never copy source or release identifiers from unrelated example projects. Observe
DeploymentRun success and actual API/agent readiness separately from build success.

## Documentation completion contract

| Surface | Required documentation | Authority |
| --- | --- | --- |
| Pydantic fields | Meaning, title, type, requiredness, constraints, examples, source expectations | Model metadata |
| Document type | Purpose, fields, evidence, review rules, complete/draft/invalid examples | Model plus rule implementation |
| MetaTable | Purpose, namespace, identity, relationships, ownership, columns and lifecycle | Registered model metadata |
| Requirement policy | Alternatives, conditions, counts, freshness, reuse and version behavior | Versioned policy code |
| REST/MCP | Schemas, access, side effects, errors, idempotency and examples | Implemented adapters and contracts |
| Agent workflow | Executable tools, inputs, evidence, side effects, completion and escalation | Implemented skills and runtime catalog |
| Main Sequence operations | Setup, ownership, migration, release, processing failures, recovery | Verified runtime procedure |
| Frontend feature | Navigation, task steps, visible states, expected results, recovery | Implemented UI and browser verification |

CI should check recursive field descriptions, metatable descriptions/columns,
schema-reference consistency, current generated references, valid agent skill
paths, and documentation links. Test actual workflow invariants rather than merely
asserting the contents of a plan.

## Evidence and implementation checks

The plan uses the local Main Sequence SDK tutorial's managed-table, migration,
identity, MCP, and `harness_agent` examples; the local MetaTables project's
`docs/client/define-and-migrate-tables.md` and `docs/client/query-and-mutate.md`;
the tutorial's versioned Tau integration/customization guidance; and the frontend's
installed Command Center skill bundle. The package's published overview also
describes the workspace-owned runtime boundary:
[Main Sequence Tau SDK](https://pypi.org/project/ms-tau-sdk/).

Before implementation depends on live resources, verify the current Environment's
MetaTables release/runtime, package compatibility, namespace roles and optional Team grants,
provider catalog, and source-file size limits. Main Sequence sign-in and the saved
project MCP's tool discovery were verified on 2026-10-19. Live platform discovery
also returned MetaTables releases in Production and development. Runner commands
need access to the saved macOS Keychain session; a sandboxed invocation without
that access can report no session. The Back Office project's exact release/runtime
bindings and grants still require verification before implementation uses them.

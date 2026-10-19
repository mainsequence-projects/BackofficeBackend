# Main Sequence document reconciliation project plan

Status: accepted product design. The Pydantic contracts, example requirement set,
16 MetaTable declarations, and initial migration are now implemented in code.
See the [foundation guide](foundation.md) for verification and current limits.
Business services, deployed tables, REST/MCP operations, and the Tau agent remain planned.

The platform evaluates whether a person has the documents required by an assigned
document set. Every result must identify the applicable requirement, the submitted
document revisions, and any missing information or inconsistency. All identifiers,
models, field descriptions, interfaces, and documentation use English.

## Platform architecture

| Concern | Main Sequence implementation | Owning project |
| --- | --- | --- |
| Document contracts | Pydantic models and generated JSON Schema | Backend |
| Business records and evidence | Governed Main Sequence MetaTables | Backend |
| Raw documents | MetaTable source manifests and bounded content chunks for the initial implementation | Backend |
| REST and MCP | Main Sequence FastAPI ResourceRelease with MCP enabled | Backend |
| Agent runtime | `ms-tau-sdk` deployed as a `harness_agent` ResourceRelease | Backend |
| Background processing | Main Sequence Jobs and JobRuns | Backend |
| Identity and access | Main Sequence request identity, workload Users, Teams, and resource grants | Both |
| Provider configuration | Main Sequence provider catalog and credential management | Backend |
| User application | `@dev-mainsequence/command-center-sdk` Static Site | Frontend |
| Agent conversation | `@dev-mainsequence/command-center-ai` | Frontend |
| Delivery | CodeRepository workflows, deployment runs, and versioned releases | Both |

The two existing CodeRepositories remain the project boundaries. The backend owns
both the business API and the agent, deployed as distinct resources from its image.
The agent calls the business API's MCP tools, which invoke the same services as REST.
Those services validate Pydantic contracts and use MetaTables for persistence.

```text
Main Sequence Command Center
  ├── Back Office Static Site ── delegated API transport ── Back Office API
  └── Command Center AI ── Main Sequence AgentSession ── Tau Harness Agent
                                                       │
                                              Back Office MCP tools
                                                       │
                                              Application services
                                                       │
                                            Main Sequence MetaTables
                                                       ▲
                                         Main Sequence processing Jobs
```

## Shared domain

| Model | Responsibility |
| --- | --- |
| Document payloads | The ten concrete document models in the field catalog. |
| `DocumentInstance` | A person's logical document and its current revision. |
| `DocumentRevision` | Immutable source references, schema version, and submitted attributes. Drafts can be edited before submission. |
| `DocumentReview` | An explicit acceptance or rejection of one revision, with actor, time, and reason. |
| `DocumentSet` | A reusable, versioned collection of requirements and alternatives. |
| `DocumentRequirement` | Applicability, required document alternatives, minimum counts, freshness, and additional required fields. |
| `Person` | Reference information against which documents are reconciled. |
| `PersonDocumentSet` | A person's assignment to a pinned document-set version. |
| `ReconciliationReport` | An evaluation against exact person, assignment, policy, and document revisions. |

Document payloads are a discriminated union keyed by `document_type`. The API and
MCP expose typed payloads. Pydantic is the authority for validation and form metadata;
the MetaTable declarations describe persistence and catalog metadata.

A document's `accepted` flag is read-only and derived from the latest effective
review of that exact revision. `pending`, `accepted`, and `rejected` remain distinct
review states. Processing states are separate. Editing reviewed content creates a
new revision requiring review. Previously accepted documents can fail a later
evaluation because they have expired or the requirements have changed.

Separate these kinds of requiredness:

1. The canonical document schema requires a field for a completed payload.
2. A requirement may require additional fields for one document alternative.
3. A document set may require one alternative, several distinct documents, or a
   conditional group of documents.

Draft extraction can remain incomplete. Derive draft contracts from the canonical
models so descriptions and types remain consistent. Validate the completed payload
and applicable policy before acceptance. Store unreadable or invalid extraction as
evidence/findings; do not fabricate field values.

## Initial document set

`NewAccountRequirements` is an instance of `DocumentSet`, with key
`new_account_requirements` and an immutable published version. These initial rules
are configurable product policy, not universal account-opening requirements.

| Requirement key | Alternatives | Initial behavior |
| --- | --- | --- |
| `identity` | Passport or National Identity Card | One accepted, currently valid identity document. |
| `address` | Utility Bill or Bank Statement | One accepted source with a matching address and configured maximum age. A bank statement without an address cannot satisfy this requirement. |
| `employment_income` | Payslips | The example requires three distinct reporting periods when employment status is employed; duplicate files do not increase the count. Monthly continuity is a future reconciliation rule. |
| `employment_contract` | Employment Contract | The example requires contract support for employed applicants. |
| `residency` | Residence Permit | Required when the configured residency condition applies. |
| `source_of_funds` | Source-of-Funds Evidence with linked supporting records | Required when the policy requests substantiation of declared funds. |
| `customer_questionnaire` | KYC Questionnaire | One complete, accepted submission. |

Unknown applicability produces a finding requiring information. A new policy
version affects new assignments; existing assignments stay pinned until an explicit
migration is recorded. One document may satisfy multiple requirements only where
the policy permits reuse.

## MetaTable layout

Use the application namespace `backoffice`, stable identifiers, explicit
application-prefixed physical names, and an application-owned migration provider.
Each table has a description and labels; every column has a label and description.
These logical table names are implemented in the [table dictionary](metatable-dictionary.md);
deployment will resolve their actual catalog bindings.

| MetaTable | Contents and key constraint |
| --- | --- |
| `person` | Person UID, current reference profile, profile revision, timestamps. |
| `person_revision` | Immutable reference profiles, unique by person UID and revision. |
| `document_schema` | Published generated schema, document type, version, and content hash. |
| `document_set_version` | Set key, version, requirement definition, schema references, publication status. |
| `person_document_set` | Assignment UID, person UID, pinned set version, assignment revision. |
| `assignment_document` | Assignment membership and document reference; no duplicate membership. |
| `document` | Logical document UID, person UID, type, and current revision reference. |
| `document_revision` | Versioned typed payload, schema version, source references, processing state. |
| `document_review` | Append-only decisions for a specific revision and decision idempotency key. |
| `raw_document` | Immutable source UID, filename, media type, byte count, checksum, upload state, chunk count. |
| `raw_document_chunk` | Source UID, chunk index, bounded encoded content, chunk checksum; unique by source and index. |
| `field_evidence` | Revision UID, field path, source UID, page, excerpt/location, extraction provenance. |
| `reconciliation_evaluation` | Input revision snapshot, policy version, evaluation time, summary and completion state. |
| `reconciliation_finding` | Evaluation UID, requirement key, field paths, document references, reason code, explanation. |
| `processing_run` | Processing intent, operation key, state, retries, and Main Sequence JobRun/session/request references. |
| `audit_event` | Business action, trusted actor, affected record/revision, time, and correlation ID. |

Store typed document attributes as versioned serialized payloads; validate every
write and read against the recorded schema version. Promote fields to indexed
columns only when actual list/filter requirements justify them. Publish field-level
metadata through `document_schema` and the generated catalog so JSON payload fields
remain discoverable. Keep immutable historical schemas available for old revisions.

### Raw documents

The initial storage design stays entirely within MetaTables: a source manifest and
bounded, ordered base64 content chunks. The application implements upload,
finalization, and authorized streaming download over these records. This is an
application design, not a claimed built-in MetaTables attachment API.

Choose and test file/chunk limits against the selected runtime's row and request
limits; account for base64 expansion. Verify total size, chunk completeness, and
whole-file checksum before setting a source to `ready`. Only ready, immutable
sources can be submitted or extracted. Resume an upload with the same operation
identity, and handle abandoned uploads through an explicit cleanup policy.

`raw_document_refs` hold source UIDs and optional page ranges. They never depend on
an expiring download URL. Every document has at least one raw source; a questionnaire
completed in the application retains a generated submission snapshot. The first
implementation milestone benchmarks this approach at the agreed maximum file size.
If the deployed Main Sequence platform exposes a more suitable governed file
resource, verify its contract and replace the adapter while preserving these UIDs.

## Reconciliation behavior

The service loads a pinned policy and input revisions, determines applicable
requirements, selects qualifying evidence, checks completeness/acceptance/validity,
and compares identity, address, income, periods, and declared funds.

Return `satisfied`, `missing`, `failed`, `pending_review`, `needs_information`, or
`not_applicable` per requirement. Return stable reason codes such as
`MISSING_DOCUMENT`, `REQUIRED_FIELD_MISSING`, `DOCUMENT_EXPIRED`, `ADDRESS_MISMATCH`,
`INCOME_PERIOD_MISMATCH`, and `APPLICABILITY_UNKNOWN` with evidence references.

Completion means all applicable mandatory requirements are satisfied. Comparisons
normalize values for matching while preserving original values. Income checks
explicitly account for period, currency, and gross/net basis. MRZ checks verify
format/check digits and consistency, not document authenticity.

Retain every evaluation. Input or policy changes mark the previous result as stale
and trigger or offer a fresh evaluation. Concurrent review/edit operations require
the expected revision; reject stale decisions. Finalize multi-record operations
only after their dependent writes succeed, using idempotency and resumable state;
do not assume independent MetaTable calls form a transaction.

## Agent and processing

The backend owns one repository-backed reconciliation agent using `ms-tau-sdk`.
Its dedicated ASGI entry point exports the app returned by `create_app()`. It is a
separate `harness_agent` resource from the business FastAPI app.

Agent workflows: explain requirements; classify a submitted document; propose typed
attributes with evidence; request missing information; invoke evaluation; explain
findings. Persist extraction proposals through the business MCP tools. The agent's
conversation is managed by Main Sequence/Tau; business results are in MetaTables.

Document acceptance is an explicit reviewer action in the first release. Agent
prompts and source text cannot grant reviewer privileges. Source documents are
evidence, never instructions to change tools or access. Restrict exposed tools to
the required workflows and enforce permissions in services independently of prompts.

Main Sequence Jobs handle bounded source text extraction/OCR and bulk evaluation.
Any OCR library executes inside the Main Sequence workload. Structured model
extraction may use Main Sequence recorded inference after text extraction when the
chosen SDK/runtime supports it; provider/model selection comes from the platform.
The reviewed inference contract accepts text/JSON, so file/image submission is not
assumed. Tau supplies the interactive agent; do not assume a job-hosted Tau batch
helper exists without checking the pinned package.

## Backend folder scaffolding

This is the full target structure. See the foundation guide for the smaller tree
implemented in this milestone; the API entry point and `data_nodes` remain starter code.

```text
backofficebackend/
├── README.md
├── AGENTS.md
├── .mainsequence/workflows/backoffice.yaml
├── .agents/agent_card.json
├── .agents/skills/backoffice/
│   ├── explain-requirements/SKILL.md
│   ├── extract-document/SKILL.md
│   └── reconcile-person/SKILL.md
├── .tau/
│   ├── SYSTEM.md
│   ├── prompts/
│   └── extensions/                 # Only when MCP cannot supply a needed adapter
├── api/
│   ├── app/
│   │   ├── main.py                 # Main Sequence business API entry point
│   │   ├── dependencies.py
│   │   ├── routes/
│   │   └── mcp/{server.py,tools.py}
│   └── tau/main.py                 # Exports ms_tau_sdk.create_app()
├── src/
│   ├── data_nodes/
│   └── backoffice/
│       ├── models/
│       │   ├── common.py
│       │   ├── person.py
│       │   ├── document.py
│       │   ├── document_set.py
│       │   ├── assignment.py
│       │   ├── evaluation.py
│       │   └── documents/          # One module for each of the ten document types
│       ├── schemas/{registry.py,drafts.py,forms.py}
│       ├── tables/                # PlatformManagedMetaTable declarations
│       ├── migrations/            # Main Sequence MetaTables migration provider
│       ├── repositories/          # Governed MetaTable reads and writes
│       ├── services/              # Shared REST/MCP business operations
│       ├── policies/new_account_requirements.py
│       ├── rules/{identity.py,address.py,income.py,validity.py}
│       ├── source_documents/      # Upload, chunking, finalization, download
│       ├── extraction/            # Text extraction, proposals, provenance
│       └── jobs/                  # Processing and evaluation job logic
├── scripts/{migrate_backoffice.py,extract_document.py,evaluate_assignments.py}
├── tests/{models,metatables,reconciliation,api,mcp,agent,fixtures}/
├── docs/
│   ├── project-plan.md
│   ├── document-catalog.md
│   ├── platform-contracts.md
│   ├── generated/                 # Generated schema, table, API and tool references
│   └── operations/                # Implemented setup, deployment and recovery procedures
└── pyproject.toml                 # Plus dependency lock generated during implementation
```

The backend dependency plan includes explicit, compatible pins for `mainsequence`,
`mainsequence-metatable`, `ms-tau-sdk`, Pydantic, the MCP server library, and FastAPI.
The foundation pins `mainsequence[mcp]==9.0.29` and `mainsequence-metatable==0.1.47`,
with a committed `uv.lock`. The agent milestone will add a compatible `ms-tau-sdk`
version and verify its runtime contract. Refresh managed guidance when changing
package versions.

## Delivery milestones and required documentation

| Milestone | Backend deliverable | Frontend deliverable | Evidence and documentation |
| --- | --- | --- | --- |
| 1. Contracts | Ten Pydantic models, shared types, registry, draft handling, versioned requirements | Form-schema contract and sample form rendering | Generated field catalog; requiredness and schema-version tests. |
| 2. MetaTables | Documented tables, migration provider/Job, source upload/finalization, repositories | Person and document lists, upload progress and preview | Table dictionary; source-storage benchmark; migration repeatability and upload recovery tests. |
| 3. Reconciliation | Assignments, reviews, revision-aware evaluation and findings | Requirement checklist, corrections, explicit review actions | Worked onboarding example; stale-review, expiry, duplicate-period and mismatch tests. |
| 4. REST and MCP | Shared service contracts, authenticated tools, processing Jobs | Command Center resources and delegated transport | API/tool catalog, permissions matrix, parity and authorization tests. |
| 5. Tau agent | Agent card, implemented skills, `.tau` behavior, `harness_agent` workflow | Command Center AI conversation and case context | Agent operations guide; loaded-tool, session and evidence tests. |
| 6. Platform delivery | Ordered migration/API/agent workflow and operational runbooks | Static Site workflow and complete user guide | Exact-environment binding checks, deployment observations, combined app/docs browser verification. |

Documentation is part of each milestone's completion criteria, not a final cleanup
task. Engineering plans describe proposed behavior; generated references and user
guides describe implemented behavior. Every feature change updates its model
descriptions, metatable metadata, API/MCP reference, workflow examples, and affected
user-guide page in the same change.

The first integrated acceptance scenario is: create a person, assign
`NewAccountRequirements`, upload source documents through Main Sequence, extract or
enter attributes, accept revisions as a reviewer, and receive an evidence-backed
report of satisfied and outstanding requirements. The same outcome must be available
through the UI and authorized agent tools.

## Supporting plans

- [Document catalog](document-catalog.md): every initial field and its intended meaning.
- [Platform contracts](platform-contracts.md): persistence, interfaces, Tau, permissions, and delivery.
- The companion frontend's `engineering/project-plan.md`: screens, schema forms, chat, and documentation delivery.

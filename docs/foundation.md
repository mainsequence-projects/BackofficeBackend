# Document and MetaTable foundation

The backend implements document contracts, managed storage definitions, business
REST services, upload finalization and reconciliation. The Tau agent and MCP
adapters remain separate milestones. See [API contracts](api.md) for implemented
operations and local verification; hosted activation is a separate delivery step.

## Implemented folders

```text
src/backoffice/
  models/                  # Person, assignment, review, shared types and policies
    documents/             # All ten canonical document payloads
  schemas/                 # Version registry, recursive drafts and form-schema envelope
  policies/                # Example NewAccountRequirements definition
  tables/                  # Sixteen Main Sequence MetaTable definitions
  migrations/              # Provider, Main Sequence Alembic environment and frozen revision
  services/                # Business commands, governed storage, reviews and evaluation
scripts/
  export_contracts.py      # Deterministic schemas and documentation generation
  migrate_backoffice.py    # Explicit Main Sequence Job entry point
schemas/
  documents/<type>/v1.json # Canonical/draft schema pairs and content checksums
  document_sets/           # Example versioned requirement policy
tests/
  fixtures/documents/      # Synthetic complete examples for all ten types
  models/                  # Completion, draft, review and policy validation
  metatables/              # Registration contracts, migration and physical constraints
docs/
  model-reference.md       # Generated field definitions
  metatable-dictionary.md  # Generated columns, relationships and constraints
```

## Pydantic contracts

Use the canonical class for a complete payload, or the registry when the type is
chosen dynamically. `document_type` selects the discriminated union. The registry
rejects unsupported types and versions; it never silently substitutes a version.

```python
from src.backoffice.models.documents import Passport
from src.backoffice.schemas.catalog import document_schema
from src.backoffice.schemas.drafts import complete_draft, get_draft_model

passport = Passport(
    full_name="Alex Morgan",
    date_of_birth="1990-03-12",
    passport_number="000123456",
    nationality="Example nationality",
    issuing_country="Example Republic",
    expiration_date="2034-01-09",
)
form = document_schema("passport", version=1)
draft = get_draft_model("passport")(passport_number="000123456")
# Only submit when this succeeds; incomplete drafts raise ValidationError.
submitted = complete_draft("passport", passport.model_dump())
```

Every field has an English title and description. JSON Schema consumers must
resolve local `$ref`/`$defs` entries, nullable unions, arrays, and `const` values.
The canonical schema's `required` array describes completion; draft fields are
nullable and optional. Policy `required_fields` adds workflow-specific requirements.
A draft preserves leaf validation and recursively permits incomplete objects, but
complete-model validators run only during promotion.

Implemented validators cover date ordering, fixed-term expiry, permanent validity,
salary frequency/basis, balance and payslip currencies, nonnegative expected KYC
flows, timezone-aware questionnaire/review times, source page ranges, bounding boxes,
and exact revision matching for reviews. Unknown keys and non-finite numbers are
rejected. Identifiers preserve leading zeros and source text preserves whitespace.
Currency/country codes enforce their code shape; reference-data membership checks
are separate. Decimal amounts serialize as strings.

JSON Schema does not encode every cross-field validator. Server-side canonical
validation remains mandatory even when a generated form validates locally. The
[synthetic examples](../tests/fixtures/documents/) cover every document type.
MRZ checksums, authenticity, comparisons with person information, expiry on an
evaluation date, and income continuity remain evaluator work.

`DocumentInstance` is a completed revision/result envelope requiring at least one
`RawDocumentRef`. Its `accepted` and `review_status` properties are computed from
`latest_review` for the same document and revision. Clients cannot supply these
computed fields. A service must load reviews from trusted persistence; this result
model is not an authorized review-write API. Persist the base envelope with
`model_dump(mode="json", exclude_computed_fields=True)`.

`PersonDocumentSet` represents assignment to a pinned `DocumentSet` version.
`new_account_requirements()` returns a fresh illustrative policy with identity and
address alternatives, three distinct payslip periods, conditional contract and
residence-permit requirements, funds evidence, and a questionnaire. Its 90-day
address age and evidence choices require business approval before publication.
Missing condition inputs produce needs-information findings in the implemented
evaluator. This policy is explicitly illustrative and does not establish legal KYC compliance.

## Main Sequence table contracts

The [table dictionary](metatable-dictionary.md) lists every authored table, column,
key and relationship. Models inherit `metatables.PlatformManagedMetaTable` and use
Main Sequence naming conventions. The explicit provider registry owns these
sixteen tables plus its migration-version table. There is no application database
URL, ORM session factory, or independent storage service.

Physical constraints enforce unique revisions, published schema references,
same-person assignment membership and field evidence, state values, positive
counts, source chunk bounds, review sequence and idempotency uniqueness. Raw bytes
are represented by manifests and ordered base64 chunks with a provisional 256 KiB
decoded chunk ceiling and a 10 MiB source ceiling. The implemented service verifies
ordered chunk content and reassembles it through bounded MetaTables reads.

The implemented services enforce immutable submitted content, append-only reviews and
history, authorization, source readiness/ownership inside JSON references, complete
payload validation, pointer advancement, and recoverable multi-call operations.
SQL relationships alone cannot enforce those JSON or lifecycle rules. The service
uses durable operation plans and case control rows to recover cross-table writes.

Person/document revision pointers deliberately have no circular foreign key. The
service must write and validate the historical row before advancing the pointer,
using an expected revision and recoverable operation state. Evaluation snapshots
retain exact inputs even if assignment membership later changes.

## Dependency and guidance evidence

The tested pair is `mainsequence[mcp]==9.0.29` and
`mainsequence-metatable==0.1.49`. Exact transitive dependencies are in `uv.lock`.
MetaTables `0.1.49` imports `ShareableObjectMixin`, absent from SDK `9.0.30`;
dependency resolution alone does not establish import compatibility. Upgrade the
pair together and rerun tests before changing these pins.

The current implementation passes 79 backend tests. Real local API verification
also passes with MetaTables 0.1.48, including source uploads, exact-revision
acceptance, completed reconciliation and subsequent stale detection. See the
[API verification record](api.md#setup-deployment-and-verification) for scope.

The dependency and copied client skills are now pinned to 0.1.49. Fresh automatic
namespace creation and repeated registration were verified with that release; see
[namespace workflow](namespace-workflow.md). Historical business API verification
above used 0.1.48. The skill bundle is refreshed with the supported
`metatables copy-metatables-skills --path .` command.

Authoring follows `metatables migrations scaffold --help` and the guidance shipped
with the installed MetaTables package under
`metatables/_client_skills/metatables-migrations/references/docs/client/`:

- `define-and-migrate-tables.md`
- `deploy-application-migrations.md`
- `local-storage.md`

These are Main Sequence's application migration contracts. The provider is
`src.backoffice.migrations:migration`; its version table is
`backoffice__alembic_version`, and its first revision is `backoffice_0001`.
The frozen initial revision contains explicit DDL and does not import live models.
Additive revision `backoffice_0002` records trusted case ownership.

## Validation and migration lifecycle

Run the commands in the [README](../README.md). Tests build real MetaTables
registration requests, execute the provider's Alembic environment in a disposable
SQLite database, upgrade twice without losing data, compare the schema with the
models, downgrade, and upgrade again. They exercise foreign-key, unique and check
constraints. HTTP requests are blocked during tests. This verifies authored contracts, migration mechanics and business HTTP behavior.
Separate real API integration checks verify local catalog/transport behavior; hosted
authentication, workload roles and engine behavior require deployment verification.

For local API integration, follow the installed MetaTables local-development
guidance: select the shared laptop runtime, inspect
`metatables --local runtime status`, and verify local mode, SQLite dialect, the
intended DataSource and ready bootstrap state before applying this provider.
Do not switch to a hosted runtime to work around a local failure.

The companion static site now includes a VS Code launcher for the full local
stack. It uses this repository's `scripts/local_metatables.py` to start the installed
MetaTables local worker, explicitly runs local migrations, and serves the real API
through `scripts/local_api.py`. `scripts/developer_session.py` connects SDK clients
to the renewing CLI session for the pinned package pair. The static site's
`engineering/local-development.md` documents setup, process ownership and verification.

Hosted migration is a Main Sequence deployment Job running
[scripts/migrate_backoffice.py](../scripts/migrate_backoffice.py) from the candidate
image. It calls `upgrade_application` explicitly. Do not run this entry point from
a developer machine against a hosted environment. Application startup never
migrates. The implemented workflow gates API rollout on migration success; the
future agent deployment must depend on that same migration step.

Before that deployment milestone:

1. Discover the selected Environment's MetaTables runtime and check existing
   `backoffice` bindings before claiming the namespace or publishing definitions.
2. The first migration creates an absent namespace and grants the migration Job
   `editor`. A person who manages the Job then grants row-writing workloads
   `data_writer` and grants themselves or a Team `owner`. If the namespace already
   exists, its owner must grant the Job `editor`. A Team is optional.
3. Declare platform `reader` access to the MetaTables branch on consuming resources.
4. Validate the workflow against the branch's current template. The installed
   guidance uses workflow API `3.0.0`: prepare the candidate image, run migration,
   then deploy resources that depend on its successful completion.
5. Verify client/API compatibility, catalog registration, workload access and repeat
   migration behavior in that Environment.

The deployment workflow is now authored and validated. Hosted activation is a
separate operation; the explicit Job publishes the authored schemas and policy. Keep applied revisions immutable; later changes
require new revisions. A release rollback does not undo schema changes; any
downgrade requires an explicit data-preservation plan.

## Evidence dates, freshness, and renewal

`created_at` is the server timestamp for the logical document. The document API
also exposes `revision_created_at` and `submitted_at` for the requested revision;
a draft has no submission timestamp. Review time belongs to the exact revision's
latest review. None of these timestamps substitutes for a printed evidence date.

Each requirement still contains alternative `DocumentOption` values. Configure
exactly one of `max_age_days` or `max_age_months` together with `freshness_field`.
That path may refer to a calendar date or an aware datetime such as questionnaire
`completed_at`; datetime freshness uses the UTC calendar date. The age limit is
inclusive. Missing dates require information; future dates and stale evidence
cannot qualify.

`renewal_interval_months` separately requires periodic action. `renewal_basis`
selects `reviewed_at` (repeat acceptance review) or `submitted_at` (submit and
review a new revision). Renewal is due on the anniversary, not the following day.
Calendar months clamp to the last day of shorter months, so August 31 plus six
months reaches February 28/29. Re-review changes the review renewal deadline but
never the underlying evidence age or expiration date.

The catalog publisher retains the exact immutable version 1 JSON and additionally
publishes version 2: six-month address and questionnaire freshness and six-month
identity review renewal. Assignments explicitly select a published version and
never migrate silently. These remain illustrative business policy choices.

`GET /assignments/{uid}/status` computes current findings without writing an audit
evaluation. Each evidence reference includes `dates` with freshness, expiration,
renewal and next-action dates; `due_status` uses a 30-day advance reminder window.
The frontend refreshes these results on open/focus and every minute while open.
There is no background notification delivery. Persisted evaluations retain their
original input and deadlines; the evaluator version is now `2`, so earlier
snapshots correctly report as stale when read with the new evaluator.

This change uses existing timestamps and JSON policy/evaluation columns; no table
migration or timestamp backfill is required. The deployment migration job must run
its existing catalog-publication step to make version 2 available before rollout.

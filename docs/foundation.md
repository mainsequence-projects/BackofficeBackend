# Document and MetaTable foundation

This milestone implements contracts and authored storage definitions. No hosted
tables have been created by this implementation. The application still needs its
business services, API/MCP operations, upload finalization, evaluator and Tau agent.

## Implemented folders

```text
src/backoffice/
  models/                  # Person, assignment, review, shared types and policies
    documents/             # All ten canonical document payloads
  schemas/                 # Version registry, recursive drafts and form-schema envelope
  policies/                # Example NewAccountRequirements definition
  tables/                  # Sixteen Main Sequence MetaTable definitions
  migrations/              # Provider, Main Sequence Alembic environment and frozen revision
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
Missing condition inputs will require information in the future evaluator. This
function defines requirements; it does not yet evaluate them or establish legal KYC compliance.

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
decoded chunk ceiling. Upload/reassembly and runtime size benchmarking are pending.

Services still must enforce immutable submitted content, append-only reviews and
history, authorization, source readiness/ownership inside JSON references, complete
payload validation, pointer advancement, and recoverable multi-call operations.
SQL relationships cannot enforce those JSON or lifecycle rules. Table definitions
alone are not a production reconciliation service.

Person/document revision pointers deliberately have no circular foreign key. The
service must write and validate the historical row before advancing the pointer,
using an expected revision and recoverable operation state. Evaluation snapshots
retain exact inputs even if assignment membership later changes.

## Dependency and guidance evidence

The tested pair is `mainsequence[mcp]==9.0.29` and
`mainsequence-metatable==0.1.47`. Exact transitive dependencies are in `uv.lock`.
MetaTables `0.1.47` imports `ShareableObjectMixin`, absent from SDK `9.0.30`;
dependency resolution alone does not establish import compatibility. Upgrade the
pair together and rerun tests before changing these pins.

Authoring follows `metatables migrations scaffold --help` and the guidance shipped
with the installed MetaTables package under
`metatables/_client_skills/metatables-migrations/references/docs/client/`:

- `define-and-migrate-tables.md`
- `deploy-application-migrations.md`
- `local-storage.md`

These are Main Sequence's application migration contracts. The provider is
`src.backoffice.migrations:migration`; its version table is
`backoffice__alembic_version`, and its first revision is `backoffice_0001`.
The frozen revision contains explicit DDL and does not import live models.

## Validation and migration lifecycle

Run the commands in the [README](../README.md). Tests build real MetaTables
registration requests, execute the provider's Alembic environment in a disposable
SQLite database, upgrade twice without losing data, compare the schema with the
models, downgrade, and upgrade again. They exercise foreign-key, unique and check
constraints. HTTP requests are blocked during tests. This verifies authored
contracts and migration mechanics, not hosted authentication, catalog registration,
permissions, or API transport.

For local API integration, follow the installed MetaTables local-development
guidance: select the shared laptop runtime, inspect
`metatables --local runtime status`, and verify local mode, SQLite dialect, the
intended DataSource and ready bootstrap state before applying this provider.
Do not switch to a hosted runtime to work around a local failure.

Hosted migration is a Main Sequence deployment Job running
[scripts/migrate_backoffice.py](../scripts/migrate_backoffice.py) from the candidate
image. It calls `upgrade_application` explicitly. Do not run this entry point from
a developer machine against a hosted environment. Application startup never
migrates. A future workflow must gate API and agent rollout on migration success.

Before that deployment milestone:

1. Discover the selected Environment's MetaTables runtime and check existing
   `backoffice` bindings before claiming the namespace or publishing definitions.
2. Have a human create the namespace and hold `owner`; grant the migration workload
   `editor` and row-writing workloads `data_writer`. A Team is optional.
3. Declare platform `reader` access to the MetaTables branch on consuming resources.
4. Validate the workflow against the branch's current template. The installed
   guidance uses workflow API `3.0.0`: prepare the candidate image, run migration,
   then deploy resources that depend on its successful completion.
5. Verify client/API compatibility, catalog registration, workload access and repeat
   migration behavior in that Environment.

No deployment workflow is activated in this foundation commit. Hosted registration
and seed publication are deferred. Keep applied revisions immutable; later changes
require new revisions. A release rollback does not undo schema changes; any
downgrade requires an explicit data-preservation plan.

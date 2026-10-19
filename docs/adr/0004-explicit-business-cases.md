# ADR 0004: Explicit business cases pinned to versioned Document Sets

- Status: Accepted
- Date: 2026-10-19

## Context

A requirement assignment already linked a subject to an exact Document Set version,
selected evidence, evaluations and staff memberships. Treating that assignment as
an implicit case left its business purpose dependent on a policy name. A loan and
an account opening need explicit identities as business cases while sharing the
same extraction, evidence, review and evaluation engine.

## Decision

Introduce `Case` and `CaseType` as canonical domain contracts. A Case has a subject
Person, a CaseType, and a composite foreign key to the exact Document Set
`(set_key, version)`. `CaseTypeDocumentSetRecord` declares which policy versions are
permitted for each type. A second composite foreign key on the Case enforces that
association. API creation requires all three references explicitly and permits
only published Document Sets. A case can exist before any evidence is uploaded.

Initial type keys are `account_opening`, `new_loan` and `document_review`. These are
business categories, not separate execution paths. Types do not contain rules or
tolerances. Those remain in the pinned, versioned Document Set and Back Office
evaluator. Parser endpoints return classification, typed extraction and cited
comparisons; they do not decide case outcomes.

Promote the existing assignment table in place with the canonical `CaseRecord`
class. Retain its physical name `backoffice__person_document_set` and registered
identifier `backoffice.person_document_set`. Retain the import alias
`PersonDocumentSetRecord`, assignment-oriented internal foreign-key names and
existing HTTP endpoints for compatibility. This avoids splitting identity,
rebuilding all downstream references, or invalidating durable operation plans.
Canonical APIs use `/cases`, `/case-types` and `/persons/{uid}/cases`.

A subject is the person represented in the documents. Staff responsibility uses
separate CaseReviewer memberships referencing verified platform user identities.
Membership grants neither access nor approval. The existing subject ownership
boundary and concurrency controls are unchanged. Document review decisions remain
attached to exact document revisions, so the same reviewed document can be used
by multiple cases of that subject.

## Migration and rollout

Additive migration `backoffice_0008` creates types and permitted associations for
all existing policy versions, including retired versions. It backfills the type
of every existing assignment without changing its UID, revision, timestamps,
subject, policy version or evidence membership:

| Existing Document Set family | CaseType |
| --- | --- |
| `new_account_requirements` | `account_opening` |
| `loan_requirements` | `new_loan` |
| Other historical families | `document_review` |

The last mapping preserves custom historical sets without guessing their business
meaning. New policy families must explicitly declare their CaseType association
in the application catalog. Mapping a historical custom set to a more specific
type later requires an intentional data migration.

`case_type_key` is temporarily nullable in storage for rolling releases and
pre-migration durable insert intents that omit the new column. All new API writes
set it; canonical reads resolve older null rows through the legacy mapping.
The direct Document Set foreign key remains mandatory even for those rows.
Typed rows also enforce the permitted-type association in the database. A future
contract migration may enforce NOT NULL after old writers and retained intents
have drained; this release does not claim that constraint.

Run the existing deployment migration Job before publishing the new API/catalog,
then publish the frontend. Do not run hosted migrations from a developer session.
The old frontend and assignment endpoints remain supported. Downgrade refuses to
drop case metadata while any cases exist; use a forward repair if needed.

Legacy assignment projections intentionally exclude the new metadata. Historical
evaluation snapshots and comparison input fingerprints remain unchanged. Merely
migrating a case or changing reviewer responsibility must not stale a comparison.
The helper's pinned MCP tools and read-only release boundary remain unchanged.

## Consequences and scope

The dashboard can display and filter by business case type independently of policy
names, and creation selects only permitted policy versions. Both initial business
processes use the same workspace, evidence links, asynchronous comparison jobs,
Back Office decisions and retained reports.

This release does not add case-level approval, closure, arbitrary staff assignment,
multi-subject case roles, or automatic policy-version upgrades. `Checks satisfied`
remains an evidence outcome, not loan/account approval. The database's historical
assignment name is a deliberate compatibility detail, not a second case model.

## Verification

Migration tests cover custom, loan and account policies, retained retired versions,
unchanged IDs/revisions/membership, foreign-key rejection and repeat upgrades.
API tests cover explicit creation, permitted versions, access boundaries, legacy
compatibility and identical evaluation inputs. Browser checks cover type filtering,
creation, selection reset, shared review and reports for both workflows.

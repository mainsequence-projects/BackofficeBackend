# One document engine, multiple versioned policies

Loans, account opening and subsequent document sets share the same document
registry, schema-derived drafts, source ownership, processing Job, submission,
revision-specific reviews, assignment membership and reconciliation service.
There are no loan-specific API routes, review records, acceptance services or
processing workers. A document can support multiple assignments; a review remains
bound to its document revision rather than to a product.

## Phase-one scope

The common registry adds schema version 1 of:

| Type | Facts | Distinct from |
| --- | --- | --- |
| `loan_contract` | Borrower, lender, contract reference/date, principal, declared monthly net income, source document-list text | `employment_contract` |
| `employer_confirmation` | Employee, employer, issue date, employment dates, monthly net income and its stated basis/period | An employment contract or payslip |
| `tax_clearance_certificate` | Taxpayer, issuing authority, issue date, original statement, reported arrears meaning/amount | `tax_return` |

The models validate structural facts, not creditworthiness or cross-document
consistency. Missing debt amounts stay null. A certificate reporting arrears is a
valid extraction; its business significance belongs to Back Office evaluation.
Original identifiers, currency and decimal precision are retained. The contract's
printed document list is untrusted source content and cannot waive requirements.

`policies.catalog.document_set_catalog()` supplies both catalog publication and
readiness. It includes the unchanged `new_account_requirements` versions 1 and 2
and `loan_requirements` version 1. All use `DocumentSet`/`DocumentRequirement` and
the existing evaluator. Each function returns a fresh definition. Published
versions and old canonical/draft schema pairs are not rewritten.

The loan policy is illustrative evidence coverage for a salaried applicant:
contract, valid identity, recent statement/payslip, address evidence, recent
employer confirmation and tax-authority certificate. Existing alternatives and
document reuse apply. Its 30/90-day limits are examples requiring business approval.
Its summary includes a policy notice: requirement completion is not income
consistency, tax clearance or lending approval. This original policy has no cross-document checks;
finding-level decisions and a final case approval are distinct from this evidence policy.

No new database tables or migration revision are required for these additions.
The existing explicit catalog-publication step in the migration Job publishes
the new schemas and policy; readiness requires all catalog policies. Startup does
not publish. Existing acceptance settings are unchanged; new types default to
review when no per-type acceptance policy is configured.

## Parser evidence contract v2

`processing/evidence_contracts.py` defines opt-in contracts for the same
`/classify_json` and `/extract_typed_json` operations. Reviewable JSON Schemas are
generated under `schemas/processing/v2/` by `scripts.export_contracts`.

New runs pin v2 and persist its evidence with the document revision. Existing unversioned
runs retain v1 through the same worker. Deploy parser v2 before rolling out the Back Office
worker; local implementation and tests do not establish deployed support.

| Contract | Additional information |
| --- | --- |
| `ClassifyRequestV2` | Required `contract_version: 2`; the same caller-supplied type catalog |
| `ClassificationResponseV2` | Source hashes and physical pages, printed pagination, upright rotation, source-local group hints and boundary observations, usage |
| `ExtractRequestV2` | Required `contract_version: 2`; canonical/draft schema pair and checksum, requested reader mode, optional ordered physical-page selection for one logical document |
| `ExtractionResponseV2` | Draft attributes, schema diagnostics, original-page manifest, normalization version, field evidence and provider usage |

Field evidence uses RFC 6901 JSON Pointers into the returned attributes, including
array indices. Each reader candidate supplies its actual model, normalized value,
optional raw text/confidence and source locations. Non-null candidates require a
citation. Page references must belong to the response manifest. A selected reader
must exist and its candidate must equal the corresponding draft attribute.
Unresolved readings may leave the attribute null while retaining the candidates.

Reader agreement is exact agreement after the documented extraction normalization;
it has no financial tolerance, severity, review decision or acceptance threshold.
`single_reader`, `agree`, `disagree` and `missing` describe observations only.
Confidence is the provider-reported score for a reading, never classification
confidence relabelled as field accuracy. Missing scores/boxes remain null.

Bounding boxes are normalized `[left, top, right, bottom]` coordinates on the rendered
page after the recorded clockwise rotation. The current vision reader supplies page-level
citations with null boxes and extraction confidence.
Physical source page numbers survive selection/reordering; printed pagination
and `group_hint` are observations, not document membership or ownership decisions.
If complete field evidence is claimed, every non-null attribute leaf except the
document discriminator must have evidence. This measures citation coverage, not
accuracy or completeness of the underlying document.

All response envelopes forbid extra fields, including `accepted`, business
`checks`, `rules_version`, `recommended_next_step`, `missing_documents` and
`reviewer`. Typed attributes must also pass the caller's pinned draft schema in
the shared worker; arbitrary JSON is not an authorization channel. Source/hash
and schema/request binding remain worker responsibilities, independent of the
response's self-consistency validation.

The generic `/compare_documents_json` operation now supplies cited cross-document
observations. Back Office applies comparison rules and tolerances through the same
versioned policy and evaluation engine. Loan v2 and account v3 opt into this stage;
existing versions remain unchanged. See [cited comparisons](document-comparisons.md).
Package grouping and dashboard consumers remain subsequent phases.

## Verification

Tests exercise the new models through existing schema/draft and HTTP lifecycles,
shared identity reviews across loan/account assignments, stale evaluations,
historical policy checksums, v1 isolation, and invalid/misbound v2 evidence.
The helper's release contract moves to version 2 solely to add the three document
types to four read-only output enums; tools, input schemas, permissions and both
Tau exclusion flags remain unchanged. The snapshot is updated during development,
never regenerated at deployment.

Run the locked environment's tests, `python -m scripts.export_contracts --check`,
and `python -m scripts.check_agent_contract`. Local tests do not establish hosted
catalog publication or deployed parser v2 support.

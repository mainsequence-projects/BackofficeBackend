# Cited comparisons in the shared document engine

Loans, new accounts and other document sets use the same `DocumentSet.comparisons`
policy model, processing Job, lease/retry lifecycle, evaluation records and findings.
There is no product-specific comparison endpoint, worker or review database.

## Ownership

ParsingMotor's `POST /compare_documents_json` receives selected extracted facts,
exact document revisions, schema/evidence checksums, physical-page citations and
factual comparison topics. It returns observed comparability, semantic relationships
and uncertainty. Code copies the cited values and source references from the request;
the model cannot manufacture or rewrite them. The response is bound to a SHA-256 of
the normalized request and must cover every requested pair exactly once.

Back Office retains the rule key, operator, mandatory/applicability flags, thresholds,
status, completion counts and next action. None of these policy fields is sent to the
parser. Provider explanations are observations, never executable instructions or
approval authority. The endpoint analyzes supplied extraction evidence; it does not
fetch original files or claim to have independently verified the source pages.

## Versioned rules

`ComparisonRule` selects two canonical document types and object field paths, optional
unit fields and required contextual fields. Every applicable distinct document pair
is evaluated, rather than arbitrarily selecting the first document. A missing field,
missing citation, unreviewed document or changed evidence checksum cannot pass.
Documents must be explicitly assigned to the same case and have an accepted submitted
revision. Legacy/manual revisions without cited extraction remain unresolved; citations
are not copied from an earlier revision or fabricated from an upload reference.

Back Office supports these operators after the parser establishes comparability:

- `exact`: compare canonical JSON values, without normalization or tolerance.
- `numeric`: Decimal arithmetic with `abs(left - right) <= max(absolute_tolerance,
  abs(left) * relative_tolerance_basis_points / 10000)`. Zero baseline uses absolute
  tolerance. Units must match when unit fields are configured; there is no currency
  conversion. Non-finite or out-of-range numeric inputs require more information.
- `semantic`: apply the policy's equality requirement to the parser's observed
  equivalent/different relationship. Uncertainty requires review.

Unknown or incompatible comparison bases require review even when numbers happen to
match. An applicable mandatory failed, missing or unresolved comparison prevents
`summary.complete`. This is evidence-check completion, never loan or account approval.

New opt-in catalog versions are `loan_requirements` v2 (declared versus employer-stated
monthly net income) and `new_account_requirements` v3 (holder-name consistency when
both identity types are supplied). They are illustrative policies, including the loan
example's zero numeric tolerance. Existing loan v1 and account v1/v2 definitions and
assignments remain unchanged. Actual bank thresholds and coverage need to be authored
as approved immutable policy versions before production use.

## API and durable execution

`POST /assignments/{uid}/evaluations` retains synchronous HTTP 201 behavior for policies
without comparisons. For comparison-enabled policies it records a frozen intent and
returns HTTP 202 with `processing_run_uid`, `status`, `stage` and `assignment_uid`.
The existing Main Sequence Job consumes that run UID and selects the comparison stage
using `kind: document.compare`; extraction remains `kind: document.extract`.

Poll `GET /processing-runs/{uid}`. Completion exposes `evaluation.uid`; retrieve the
retained result through the existing `GET /evaluations/{uid}`. Its input snapshot
contains the exact comparison response and policy; findings cite document revisions,
field pointers, values and source pages. Duplicate evaluation requests with the same
operation key return the retained result once completed.

Provider calls hold no person/case lock. The worker checkpoints validated observations
before finalization. The shared mutation service checks the frozen inputs again under
the case lock before recording the evaluation and findings. An intervening document,
review, person, membership or date change yields `needs_input` with
`comparison_inputs_changed_start_new_evaluation`; request a new evaluation operation.
Later changes mark an existing retained evaluation stale. Lost writes resume the same
durable intent without rerunning the comparison provider.

Use `POST /processing-runs/{uid}/retry` with an operation key for transient failures.
The existing `/document-processing/{uid}` status/retry paths remain aliases. Case
ownership, reviewer access and trusted processor checks apply throughout. Read-only
status and MCP queries never invoke the parser or schedule work: they reuse the latest
matching retained observations, otherwise reporting pending comparison evidence.

## Limits and rollout

A parser request carries 2–20 documents, up to 100 cited facts per document, 1–50 pairs
and at most 512 KiB of normalized JSON. Comparisons use the existing parser credentials
and bounded HTTPS adapter. No new credential, bucket access or helper tool is added.

This phase needs no new physical migration: processing runs and evaluations already
store immutable JSON snapshots. It depends on the prior extraction-evidence migration
`backoffice_0006`. Deploy the parser endpoint first, then the Back Office API/worker and
matching helper release. The existing migration Job publishes the two new catalog
versions. Helper contract v3 changes only the output schemas of `list_document_sets`
and `get_document_set`; all ten tools, inputs, annotations, requester checks and Tau
exclusion flags are preserved. Contracts are checked during development, never
regenerated during deployment.

Local verification uses `scripts.verify_document_comparisons --source-uid <verified-local-uid>`
with controlled providers through the real MetaTables API. Add
`--verify-evaluation-uid <uid>` to check retained citations and request bindings from a
fresh process. These checks establish local persistence, not live model quality or
hosted readiness. Dashboard rendering, finding-specific human overrides and signed
protocol generation are not implemented by this phase.

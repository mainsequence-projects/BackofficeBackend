# Automatic document allocation

The static-site **Drop files** page (`/drop-files`) accepts multiple PDFs, PNGs or
JPEGs. Each file has an independent durable intake, extraction and allocation run.
The current per-file limits are 15 MiB and 20 pages. Two files upload concurrently;
server processing continues after acknowledged uploads even if the browser closes.
A browser refresh restores the authenticated queue, not original file bytes.

The service identifies the Person across the requester's accessible records, then
links the same document to every eligible case for that Person. It uses the case's
pinned Document Set and the shared evaluator to check useful evidence, dates,
alternatives, applicability, counts and duplicate reporting periods. Existing
pending review is not a demand for another copy. Pending evidence is assessed for
potential coverage using the same field, date and duplicate-period checks; it can
cover part of a multi-document requirement without hiding the remaining shortfall.
Rejected evidence is not automatically added to new cases. Each linked case receives a full
retained evaluation and configured comparisons. This never approves or closes a case.

## API

| Method and path | Request | Result |
| --- | --- | --- |
| `GET /document-intakes/config` | None | Supported formats, bytes/pages and upload concurrency |
| `POST /document-intakes` | Multipart `file`, UUID `operation_key` | 202: private intake/run UID; upload automatically schedules allocation |
| `GET /document-intakes` | `limit` 1–100 (default 20), `offset` >= 0 | Requester's queue with status, stage and references |
| `POST /document-allocations` | JSON `operation_key` and exactly one of `intake_uid` or `source_uid` | 202: starts/reschedules the referenced work |
| `GET /document-allocations/{uid}` | Target `limit` 1–100 (default 20), `offset` >= 0 | Status and paginated per-case results |
| `POST /document-allocations/{uid}/resolve` | JSON `operation_key`, `subject_uid`, strict integer `expected_revision` | 202: resolve uncertain identity and resume |
| `POST /document-allocations/{uid}/retry` | JSON UUID `operation_key` | 202: retry recoverable stages; successful outcomes remain |

All commands reject unknown fields. Identity, schema, threshold and acceptance are
server-owned. MIME signatures and checksums are checked before ingestion. No request
accepts a filesystem path or arbitrary URL. Incomplete uploads need the same file
and operation key again. A durable intake uses one `document.allocate` processing
record; its intake UID and allocation UID are intentionally identical. General
operation-resume APIs cannot execute allocation records.

Reuse the identical command/key after an uncertain response. A resolution is a
separate command tied to the observed allocation revision. `needs_input` with
`resolution_required=true` means the requester must choose an accessible Person;
conflicting identity evidence is rejected. Mixed-document packets must be split
into individual documents. A failed file does not block other files.

`targets` includes per-case status, requirement keys, evaluation UID and summary.
Follow `targets_has_more` and `targets_offset`; `target_count` is the frozen target
count. An unallocated result retains the extracted document for its resolved Person.
A partially completed run reports failed targets; retry preserves successful links.
Both ordinary and comparison evaluations check that the retained snapshot is current.
Case changes during execution cause bounded reevaluation or an explicit retry result.
If the document revision changes before a new link, allocation stops for that target;
review the changed document and start a new allocation instead of silently linking it.

## Identity and authorization

Matching version 1 requires a unique normalized exact holder-name match supported
by cited extraction evidence plus a matching cited birth date or complete address
(street, city, postal code and country). Name-only matches and missing/disagreeing
identity evidence require user selection. These rules locate evidence; they are not
an identity-authentication or document-authenticity assertion. Extracted claims
never overwrite the reference Person profile. Joint-holder or otherwise ambiguous
matches remain unresolved until user input. A ready source's existing owner remains
a constraint, and contradictory claims are not silently assigned elsewhere.

Intakes are private to the verified initiating requester, including for other
reviewers. Background execution refreshes the requester's active directory facts
and reviewer/team permissions. Rights cannot exceed those at submission. Directory
failure stops allocation; the processor's broader rights never become search rights.
Every target is reauthorized before mutation, and source/document ownership is
preserved. Existing immutable content can reuse a subject's existing document;
multiple conflicting document candidates require review.

Discovery currently bounds a complete scan at 10,000 accessible subjects, 500 cases
for one subject and 500 documents for deduplication. Exceeding a bound produces an
explicit limit error, never an incomplete claim of allocation to all cases.

## Persistence and release

Reuse the existing ProcessingRun MetaTable for independent intake and durable
request receipts, with fenced worker leases and immutable input snapshots. Normal
source/document binding still uses the shared audited mutation service and strict
same-subject constraints. No new migration or nullable source owner is needed.
Target plans and evaluation commands are checkpointed before mutations, allowing
lost-response recovery. Intake artifacts and audit data are retained under the
existing private-bucket retention policy; this feature does not automatically
purge originals or introduce a separate retention schedule.

Deploy the API, worker, reviewed 35-tool helper contract and static site together.
The processing workload must read current requester directory facts and the managed
bucket and must have the existing MetaTables access. Its parser must support the v2
classification and typed-extraction envelopes plus the comparison endpoint used by
pinned policies. The deployed parser at commit `6fd21155a633` passed real v2
classification and typed extraction on 2026-10-19. Hosted Job execution and live
comparison policies remain separate release checks.

The explicit local developer API uses `scripts.local_processing.LocalProcessing`
for both REST and MCP. It runs two local workers against the pinned SQLite source,
recovers pending or expired work and preserves the normal worker leases. Local
records must never be dispatched to a hosted Job. The production API still uses
the configured Main Sequence Job dispatcher. Keep the local stack running for
background processing; closing its browser tab does not stop its workers.

The worker saves `classifying` and `extracting` before the respective provider
calls. Drop files shows queued versus running work, a stage tracker, last update,
classification confidence and review reasons. Dispatch failures persist across
refreshes and offer retry. A completed allocation is distinct from accepted evidence.

Verification: `tests/api/test_document_allocation.py`,
`tests/api/test_mcp_allocations.py`, and frontend `node tests/drop-files.mjs`.
`python -m scripts.verify_document_allocation --source-uid <verified-local-uid>`
checks the installed MetaTables client/API with synthetic private fixtures and a
live directory lookup. Supply `--run-uid` in a fresh process to verify retained
results. The script refuses an unexpected or non-local SQLite runtime.

For a real bucket/parser run use `python -m scripts.verify_live_allocation` with
`--expected-source-uid`, `--subject-uid`, repeated `--case-uid` arguments and
`--file` pointing to a synthetic example. It uploads through the actual local API,
polls the real background worker, verifies all case links/current evaluations and
checks downloaded source bytes against the input. `--run-uid` verifies retained
results without another upload. No parser or bucket fixture is substituted.


### Continuation-page grouping

Free-text grouping hints can identify an issuer on one page and an account on
another. Differing hints no longer split a document when every subsequent physical
page explicitly continues it and available printed page numbers/counts agree.
Additional starts, unknown continuation, page-number resets/gaps or conflicting
printed totals still require grouping. The grouping decision uses retained classification observations when a worker
resumes. Existing `needs_input` runs retain the normal resolution/re-upload boundary.

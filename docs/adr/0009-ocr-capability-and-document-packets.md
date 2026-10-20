# ADR 0009: Explicit OCR capability and extraction of subject-owned packets

Status: Accepted

## Context

The owner defines folder 01 as a canonical passing account-opening example.
Account-opening v7 already requires its six document types. The live workflow
nevertheless withheld every document: Textract Queries returned partial names,
misassigned identifiers and dates, and no readings for arrays. A blanket reader
agreement gate therefore prevented valid vision extractions from meeting the
existing acceptance policy. The combined PDF also stopped at document grouping.

The owner authorized an explicit OCR feature flag, a rerun of only this case in
the existing main database, and no edits to originals or manual acceptance.

## Decision

Expose `BACKOFFICE_EXTRACTION_OCR_ENABLED=false` for deployments where OCR is
unavailable or unsupported. This selects ParsingMotor's existing vision-only
strategy. `true` selects independent readers. Omission preserves the current
default; malformed or conflicting configuration fails before dispatch.

Pin the strategy before processing. Retries and packet children inherit it.
Never automatically switch to a weaker strategy in response to a disagreement.
Old evidence remains immutable; a deliberately reconfigured rerun produces new
extraction evidence. Genuine classification confidence, per-type thresholds,
canonical validation, source hashes and field citations remain mandatory.
Independent-reader runs retain their existing disagreement gates.

For subject-owned source processing, partition a packet only when the classifier
provides explicit starts and consistent continuations. Reject unknown types,
ambiguous boundaries and incomplete or contradictory pagination. Process each
contiguous group through the same durable extraction and acceptance services,
using the unchanged original and its physical `page_selection`. Keep original
source UIDs, hashes and page ranges in evidence. Classification confidence is
aggregated separately for each logical document.

An isolated single page with an unknown boundary can be a group when its discovered
type differs from both neighbors, the preceding group's printed pagination closes
that document, and the next page explicitly starts a different document. Record
this basis without rewriting the classifier's observations. Type changes alone
do not justify grouping.

Parent and child identities are deterministic. Retry resumes the same children
and checkpoints; it cannot duplicate documents already persisted. Parent responses
expose group statuses and resulting documents. Global local-worker recovery skips
packet children because the parent owns their scheduling.

The case caller links the produced documents to the intended case through the
existing authorized API. Existing evidence and evaluations are retained. Packet
processing does not allocate evidence to unrelated cases, approve a case, fabricate
a subject, or use expected-results files as extraction input. Unbound intake
packets continue to require subject/grouping resolution.

## Verification

Regression checks cover OCR configuration and pinning, page grouping, unknown and
incomplete packets, immutable source bytes, original page references, automatic
acceptance, out-of-range provider responses, and retry without duplicate evidence.
The live folder-01 run must use `/Users/jose/.local/share/metatables/metatables.sqlite`,
retain its existing subject and case, and verify hashes of all original files.
Success requires six satisfied account-opening requirements and zero outstanding
requirements. This is evidence completeness, not account approval.

The live rerun on 2026-10-20 met that criterion in the existing main database:
seven individual PDFs and seven groups from the combined PDF were automatically
accepted, with classification scores of 95–99% against the unchanged 80% policies.
The case evaluation reported six satisfied requirements and zero outstanding
requirements. File hashes before and after the run were identical. OCR was
explicitly disabled; no manual acceptance was used. Previous runs and case evidence
were retained. This verifies the local workflow with the deployed parser, not a
hosted Back Office deployment.

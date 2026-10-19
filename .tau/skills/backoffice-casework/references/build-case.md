# Build a case using the shared engine

Use this workflow to prepare a concrete plan for an authorized operator. It describes
the existing application workflow; it does not grant the helper mutation tools.

## Establish the case before assembling evidence

- Resolve the intended subject's UID and reference. If the subject does not yet
  exist, mark subject creation as an outstanding UI step; never invent a UID.
- Establish the business purpose. A new loan proposes `new_loan`; opening an account
  proposes `account_opening`. If unclear, ask for the intended process. Neither
  purpose implies a separate document pipeline.
- Inspect existing cases through `list_person_assignments`. An explicit request for
  a new case may create another case of the same type; do not silently reuse or
  replace one. If the user means “finish the existing case,” resolve its exact UID.
- Read published policy candidates using `list_document_sets` and `get_document_set`.
  Preserve an existing case's pinned version. For a new case, propose an exact version
  only with its key, version and reason; do not assume newest means appropriate.
  The helper cannot inspect CaseType bindings. Mark the proposed pairing unverified
  until the UI's type-specific list confirms it. No published candidate means a
  policy-owner handoff, not permission to invent requirements.

Prepare a concise case brief with these fields when useful:

| Field | Source / treatment |
| --- | --- |
| Existing case UID or new-case intent | Verified assignment or explicit user request. |
| Subject UID and name/reference | Resolved business Person; creation needed if unavailable. |
| CaseType key | User-requested purpose, or canonical metadata if an authorized interface supplies it. Current MCP cannot confirm stored type. |
| Document Set key and version | Exact existing pin, or clearly proposed published candidate. |
| Permitted type/policy binding | Unavailable to current MCP; confirm in the creation UI. |
| Evidence actions | Existing case findings, or prospective policy requirements. Do not call prospective requirements a completed assessment. |
| Staff handoff | Requested responsible team/person as user intent; actual memberships unavailable to current MCP. |
| Remaining steps | Identity/policy questions, creation, evidence processing/linking, review and evaluation as applicable. |

Do not populate empty-case fields with fabricated documents, reviewer identities,
evaluation IDs, timestamps, citations or operation keys. Do not turn optional evidence
into mandatory evidence or demand every alternative. Unknown applicability requires
reference information; it is not automatically a missing document.

## Operator execution and verification

1. **Create the case.** In **Cases → New case**, select the subject, Case type and
   permitted Document Set version. Alternatively use **Subjects → Requirements →
   Create case** for an existing subject. The API behind this UI is `POST /cases`
   with `operation_key`, `subject_uid`, `case_type_key`, `document_set_key` and
   `document_set_version`. The returned UID identifies the new case. An empty case
   is valid; creation does not prove evidence completeness.
2. **Collect and process evidence.** Use the normal subject document workflow for
   uploads and processing, whichever case type was selected. Extracted claims retain
   their sources and typed schema. Do not claim that pasted text or a chat attachment
   has been uploaded, processed or persisted as business evidence.
3. **Select evidence for this case.** Link appropriate same-subject documents in the
   case's Requirements/workspace flow. Uploading a document for the subject does
   not automatically select it for every case. Preserve existing membership when
   adding documents; removal is unsupported in the current interface.
4. **Have authorized staff review.** Inspect the exact document revisions and their
   sources. Acceptance/rejection belongs to an authorized review action with its
   reason, not to this helper's narrative. Staff use **Assign to me** or **Leave
   case** for their own responsibility; this interface cannot assign arbitrary staff.
   Several authorized reviewers may join without becoming subjects.
5. **Run the shared evaluation.** Use **Run checks** or **Evaluate requirements**.
   `POST /cases/{uid}/evaluations` returns a retained result for synchronous policies
   or a processing-run reference for comparison policies. A queued run is not a
   completed assessment. On completion, inspect current findings and the retained
   report. A failed run or stale inputs requires the UI's recovery/fresh evaluation
   path; do not reinterpret it as successful checks.
6. **Report actual state.** Re-read live status through the approved MCP queries
   once the operator supplies the case UID. Distinguish actions proposed from
   actions performed. Satisfied evidence requirements do not approve the loan,
   open the account, close the case or create a signed protocol.

Mutation clients retain the same operation key after an uncertain response and use
observed revisions for conflict checks. They must not create duplicates by issuing
fresh keys blindly. This helper has no mutation client: explain the UI recovery
path rather than simulating a retry through an unapproved tool.

## Applying this to the two initial processes

- **New loan:** propose `new_loan`; select a permitted loan Document Set version.
  Income/identity comparisons, if required, come from that version's rules and
  existing evidence. Do not infer an income tolerance or credit decision yourself.
- **Account opening:** propose `account_opening`; select a permitted account-opening
  Document Set version. Identity/address/funds requirements and comparisons come
  from that version. Do not treat evidence completion as account approval.

For both, follow exactly the same subject → case → pinned policy → selected evidence
→ revision review → Back Office evaluation workflow. Keep separate case IDs and
pins even when the same subject or reviewed document is reused.

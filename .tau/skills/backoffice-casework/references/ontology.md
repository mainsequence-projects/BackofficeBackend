# Case ontology and what this helper can observe

| Object | Relationship and invariant |
| --- | --- |
| Case | One business process instance with a stable UID, one subject, one CaseType, and one exact Document Set version. It can exist with no documents. |
| CaseType | Business purpose: `new_loan`, `account_opening`, or `document_review`. The type does not contain a separate engine or its own inferred rules. |
| Document Set version | `(key, version)` is the Case's mandatory composite foreign key. It defines requirements, alternatives, comparison rules and tolerances. Publishing a new version does not move existing cases. |
| Permitted type/policy association | Declares which exact Document Set versions a CaseType may use. A second composite foreign key enforces that choice. A matching display name is not proof of this association. |
| Person / subject | The business person whose reference profile and document claims are assessed. One subject may have several loan and account-opening cases. |
| Document / revision | A subject-owned logical document with retained revisions and source/extraction evidence. A case selects documents of the same subject. Several cases may reuse a document. |
| Review decision | Attaches to an exact document revision. A later revision does not inherit acceptance. A case's selected evidence and effective reviews determine its findings. |
| CaseReviewer | Staff responsibility referencing a verified platform user. Several reviewers may join a case. Membership grants neither access nor acceptance and does not change evaluation inputs. |
| Evaluation | Retained assessment of frozen profile, policy, selected evidence, review and comparison inputs. Changes can make it stale; current status is a separate read. |

Keep three identities separate: the subject represented in the evidence, the verified
requester whose permissions govern this conversation, and staff reviewers responsible
for the case. `get_current_user.can_review` is a permission fact, not evidence that
that user is assigned to the case. Do not put a staff UID in `subject_uid`, infer
reviewers from document signatures, or claim a reviewer list from a case owner.

The current Case model has one subject. Do not invent co-applicant or guarantor
roles, combine different people's evidence into one case, or label a second subject
as a reviewer. Explain the missing multi-subject capability if it matters.

## Compatibility projection

Assignments were promoted in place; these refer to the same persisted identity:

| Read-only MCP field | Canonical Case meaning |
| --- | --- |
| `uid` / `assignment_uid` | `Case.uid` |
| `person_uid` | `Case.subject_uid` |
| `set_key` | `Case.document_set_key` |
| `set_version` | `Case.document_set_version` |
| `revision` | Case evidence-membership revision |
| `document_uids` | Explicitly selected logical documents |

The legacy projection deliberately omits `case_type_key` and staff memberships to
preserve existing contracts and historical evaluation snapshots. Report those fields
as unavailable through the current helper, not absent in the actual Case model.
Although the migration maps known loan/account policy families to business types,
that migration rule is not a substitute for reading authoritative live metadata.
A proposed case type can come from the user's stated intent; label it as proposed.

## Shared responsibility boundary

Back Office owns source storage, canonical typed documents, case links, authorization,
versioned requirements, tolerances, status and review decisions. The parser's
classification and typed-extraction endpoints supply claims and evidence;
`/compare_documents_json` supplies cited observations and uncertainty. A parser's
“equivalent” observation or high OCR confidence does not decide policy satisfaction.

The same Back Office engine evaluates loan and account-opening cases. The case type
selects permitted policies; requirements select relevant evidence and comparisons.
Never invent a loan-only parser workflow or hard-code financial tolerances in prose.
The current helper consumes the resulting findings; it cannot call these endpoints.

# Case ontology and identity

| Object | Relationship and invariant |
| --- | --- |
| Case | One business process instance with a stable UID, one subject, one CaseType, and one exact Document Set version. It can exist with no documents. |
| CaseType | Business purpose: `new_loan`, `account_opening`, or `document_review`. The type does not contain a separate engine or its own inferred rules. |
| Document Set version | `(key, version)` is the Case's mandatory composite foreign key. It defines requirements, alternatives, comparison rules and tolerances. Publishing a new version does not move existing cases. |
| Permitted type/policy association | Declares which exact Document Set versions a CaseType may use. A second composite foreign key enforces that choice. A matching display name is not proof of this association. |
| Person / subject | The business person whose reference profile and document claims are assessed. One subject may have several loan and account-opening cases. A person is not itself a case. |
| Document / revision | A subject-owned logical document with retained revisions and source/extraction evidence. A case selects documents of the same subject. Several cases may reuse a document. |
| Review decision | Attaches to an exact document revision. The backend can record policy-controlled automatic acceptance, or authorized staff can review it. A later revision does not inherit acceptance. |
| CaseReviewer | Staff responsibility referencing a verified platform user. Several reviewers may join a case. Membership grants neither access nor acceptance and does not change evaluation inputs. |
| Evaluation | Retained assessment of frozen profile, policy, selected evidence, review and comparison inputs. Changes can make it stale; current status is a separate read. |

Keep three identities separate: the subject represented in the evidence, the verified
requester whose permissions govern this conversation, and staff reviewers responsible
for the case. `get_current_user.can_review` is a permission fact, not evidence that
that user is assigned to the case. Do not put a staff UID in `subject_uid`, infer
reviewers from document signatures, or claim a reviewer list from a subject owner.
Self-membership actions affect the verified requester, not the agent workload or an
arbitrary person named in the prompt. Read actual memberships to report responsibility.

The current Case model has one subject. Do not invent co-applicant or guarantor
roles, combine different people's evidence into one case, or label a second subject
as a reviewer. Explain the missing multi-subject capability if it matters.

## Canonical and compatibility views

Read canonical case details for `subject_uid`, `case_type_key`, `document_set_key`,
`document_set_version`, `revision` and selected `document_uids`. Read the CaseType
catalog to verify permitted published policy versions and reviewer tools for actual
memberships. Distinguish returned metadata from the user's proposed choices.

Assignments were promoted in place; these refer to the same persisted identity:

| Legacy MCP field | Canonical Case meaning |
| --- | --- |
| `uid` / `assignment_uid` | `Case.uid` |
| `person_uid` | `Case.subject_uid` |
| `set_key` | `Case.document_set_key` |
| `set_version` | `Case.document_set_version` |
| `revision` | Case evidence-membership revision |
| `document_uids` | Explicitly selected logical documents |

Legacy assignment responses deliberately omit `case_type_key` and reviewer
memberships. Use the canonical tools instead of inferring those fields from policy
names or ownership. If the connected release lacks a needed canonical tool, report
that capability as unavailable; do not pretend the object lacks those relationships.

## Shared responsibility boundary and acceptance

Back Office owns source storage, canonical typed documents, case links, authorization,
versioned requirements, tolerances, status and review decisions. The parser supplies
classification, typed claims, evidence and cited comparison observations. Its
“equivalent” observation or high confidence does not itself decide satisfaction.

The backend can automatically accept a particular revision when its configured
per-document-type policy permits it and all guards pass: valid attributes, ready
owned sources, acceptable extraction evidence and sufficient **classification
confidence**. This is not the same as OCR field confidence or extraction accuracy.
Use the returned effective acceptance/parsing decision and reason; do not recreate
these thresholds in the skill or override them from a score alone.

Do not require manual review again solely because an already accepted revision was
accepted automatically. Review is needed when the effective state or current findings
require it, including unresolved evidence, a changed revision, rejection or a
policy-driven renewal. Accepted documents may still fail cross-document consistency,
freshness, completeness or other case requirements. Document acceptance is not case
approval, loan approval or account opening.

The same Back Office engine evaluates all CaseTypes. The selected policy determines
requirements and comparisons. Never invent a loan-only parser workflow or hard-code
financial tolerances. The agent invokes supported Back Office tools, not the parser
or storage directly, and explains the engine's resulting findings.

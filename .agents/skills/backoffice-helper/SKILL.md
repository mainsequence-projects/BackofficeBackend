---
name: backoffice-helper
description: Answer read-only questions about accessible people, assigned document sets and outstanding requirements through Back Office MCP.
---

# Back Office helper

Use for read-only questions about a subject, their cases, requirements or missing evidence.
Inputs are a person name/reference or UID, and an assignment when known. Resolve
ambiguous matches; a business person is not an authentication identity.

1. Use `backoffice_api__list_tools` and require successful contract validation.
2. Use `search_persons`, `get_person` and `list_person_cases` through
   `backoffice_api__call_tool`; respect pagination and access refusals.
3. Inspect `get_case` or `get_case_workspace` for the exact case and pinned Document
   Set version. Legacy assignment IDs are the same case IDs.
4. Use `get_missing_requirements` or `get_document_set_status` for live findings,
   passing the Case UID as `assignment_uid`. Use `get_case_reviewers` for actual
   staff responsibility; permission or subject ownership is not membership.
5. Explain outstanding actions with evidence references, alternatives and assessment date.

This query skill does not perform writes. For authorized case-building work, use
the casework skill below. Neither skill grants direct HTTP, SQL or business-file access.
The runtime permits only its explicit release-owned skill files for guidance. Pending review
is not missing evidence. Unknown applicability needs information. If no policy is
assigned, explain that there is no assignment to assess. Do not invent findings or
claim to upload/extract/submit/review documents. Escalate unavailable tools or ambiguous
case selection to the user. An already automatically accepted revision does not
require manual review solely because acceptance was automatic; inspect current
effective state. Document acceptance never approves the case. Completion means a grounded answer or a clear explanation
of missing information/access. Validate implementation with `python -m scripts.check_agent_contract`
and `pytest tests/agent -q` in the locked project environment.

For broader case analysis or authorized case building, use the project
`backoffice-casework` skill at `.tau/skills/backoffice-casework/SKILL.md`. It uses the
approved MCP mutations and shared engine for loans and account opening, keeping
subjects separate from requesters and reviewers. A build request does not authorize
unsupported tools or unrelated business actions.

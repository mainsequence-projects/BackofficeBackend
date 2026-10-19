---
name: backoffice-helper
description: Answer read-only questions about accessible people, assigned document sets and outstanding requirements through Back Office MCP.
---

# Back Office helper

Use when the user asks about a person's case, assigned requirements or missing evidence.
Inputs are a person name/reference or UID, and an assignment when known. Resolve
ambiguous matches; a business person is not an authentication identity.

1. Use `backoffice_api__list_tools` and require successful contract validation.
2. Use `search_persons`, `get_person` and `list_person_assignments` through
   `backoffice_api__call_tool`; respect pagination and access refusals.
3. Inspect the exact assignment and pinned document-set version.
4. Use `get_missing_requirements` or `get_document_set_status` for live findings.
5. Explain outstanding actions with evidence references, alternatives and assessment date.

No writes, direct HTTP, SQL or business-file access are authorized by this skill.
The runtime permits only its explicit release-owned skill files for guidance. Pending review
is not missing evidence. Unknown applicability needs information. If no policy is
assigned, explain that there is no assignment to assess. Do not invent findings or
claim to upload/extract/submit/review documents. Escalate unavailable tools or ambiguous
case selection to the user. Completion means a grounded answer or a clear explanation
of missing information/access. Validate implementation with `python -m scripts.check_agent_contract`
and `pytest tests/agent -q` in the locked project environment.

For broader case analysis or a case-building plan, use the project
`backoffice-casework` skill at `.tau/skills/backoffice-casework/SKILL.md`.
Legacy assignment IDs are canonical case IDs; the current MCP projection cannot
confirm stored CaseType or staff membership. Do not infer either from a policy name
or the subject's owner.

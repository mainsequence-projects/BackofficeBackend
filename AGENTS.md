# Repository instructions

Every Git commit created or amended by Codex must contain exactly one trailing
`Co-authored-by: Codex <codex@openai.com>` line separated from the body by a blank
line. Preserve configured author/committer identities and other co-author trailers.

## CodeRepository-Specific Instructions

This repository owns the Back Office API and its separately deployed Tau helper.
The deployed helper analyzes and builds cases through approved Back Office MCP
operations. Loans and account opening use one engine; business subjects remain
separate from verified requesters and staff reviewers. Its workflows are documented
in `.agents/skills/backoffice-helper/SKILL.md`,
`.tau/skills/backoffice-casework/SKILL.md` and `.tau/SYSTEM.md`.
These deployed-agent restrictions do not prohibit coding agents from implementing
and testing repository changes authorized by the user.

Keep business authorization and reconciliation in the shared API services. Do not
add direct database, HTTP, bucket or classifier access to the helper. Preserve the
two Tau exclusion flags, the business allowlist and verified-requester requirement.
Resolve ambiguous cases with the user; surface unavailable data or access rather
than invent findings. Approved mutations create subjects/cases, process existing
ready subject-owned sources, append case evidence, change only the requester's own
reviewer membership, run/retry evaluations, and automatically allocate persisted
intakes or sources to all eligible cases with user resolution of uncertain subjects.
Original bytes enter through the Drop files screen/API; direct chat uploads, manual
document edits/reviews, arbitrary staff assignment and case approval/closure remain
outside this agent release. The SDK retains ownership of session and task controls.

Validate agent changes with `python -m scripts.check_agent_contract` and
`pytest tests/agent tests/api/test_mcp_queries.py -q` in the locked environment.
Do not regenerate pinned contracts at deployment time. Hosted verification and
remaining release gates are recorded in `docs/agent.md`; local tests do not establish
production readiness. The project owner resolves provider access and deployment
authorization issues.

# Back Office helper agent

The dedicated `api/tau/main.py` exports the app returned by `ms-tau-sdk==2.0.18`.
It disables coding tools and the central Main Sequence MCP with explicit settings;
the deployment workflow declares the same flags. The SDK owns authentication,
requester delegation, model credentials, session lifecycle and health endpoints.

## Business tools

The agent binds to `backoffice_api` through `spec.mcp_applications`. Tau exposes
`backoffice_api__list_tools` and `backoffice_api__call_tool`. The project extension
in `.tau/extensions/backoffice_policy/extension.py` adds hooks, not new tools.

The hooks require a verified requester and restrict business operations to the ten
person/document-set/status queries in `src/backoffice_agent/policy.py`. Discovery
must match the pinned input contracts and read-only annotations. Extra server tools
are removed from the discovery result and cannot be called by guessing their names.
Failed discovery blocks subsequent queries. Skill reads and other application/resource
wrappers are blocked. SDK task input/authorization controls remain SDK-owned.

The SDK still lists its retained native controls; the restriction is enforced before
execution rather than pretending its native catalog contains ten direct query tools.
Extensions are trusted project code, not a Python sandbox. Changing the extension or
the allowlist changes this application's authority and requires review.

The agent does not upload, extract, assign, edit, submit or review documents. User
answers are based on live MCP findings, pinned set versions and evidence references.

## Deployment

The existing production-scoped workflow now orders:

`image → migrate → deploy_api → agent_contract → agent_image → deploy_agent`

The contract Job runs `scripts/check_agent_contract.py` against the candidate API
catalog without querying business storage. It verifies the pinned input/output
schemas, annotations and required artifacts. The agent image is prepared separately
because its deployable entry point differs; the workflow supplies the same source
event. The agent receives reader access to the API resource, no MetaTables branch
grant, and declares `acts_for_requester: true`. Platform authorization must permit
that declaration; the application does not grant itself delegation authority.

Provider/model defaults are `openai-codex`, `gpt-5.5`, `medium`, following the existing
SDK tutorial setup. Availability for this Environment and its session principals
has not been verified. Credentials are supplied by the platform, never committed.

The contract Job is an **offline candidate check**, not a live deployed MCP check.
The platform's deployment readiness and the per-session MCP discovery check cover
different stages. Before treating the first hosted release as verified, validate the
workflow with the target platform, confirm provider access and requester delegation,
inspect both DeploymentRuns, and exercise actual agent-to-MCP queries with two
authorized fixture identities to check isolation. Check session resumption and the
effective runtime catalog. No hosted rollout or traffic-promotion/rollback test is
claimed by the local tests. The ADR's predeployment live smoke gate and automated
postdeployment rollback remain follow-up integration work.

## Local verification

Use the locked environment:

```sh
uv sync --locked
uv run python -m scripts.check_agent_contract
uv run pytest tests/agent tests/api/test_mcp_queries.py -q
```

The policy tests use fake requester identities and native Tau hook types; they make
no model calls and do not seed cases. Local Tau mode has no hosted requester binding,
so this business policy deliberately refuses workload fallback there. Test actual
delegated conversations through the hosted runtime, with approved fixture access.

`src/backoffice_agent/mcp_contract.json` is release-owned. A deliberate API contract
change requires reviewing the corresponding tool behavior and updating that snapshot
and its SHA-256 together. Do not regenerate it automatically during deployment, which
would accept unreviewed drift. The snapshot is included as package data.

The source card and repository-owned helper skill are under `.agents/`. Managed
development skills were synchronized explicitly from the pinned SDK; no startup
path changes those instructions.

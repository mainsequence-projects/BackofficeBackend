# Back Office helper agent

The dedicated `api/tau/main.py` exports the app returned by `ms-tau-sdk==2.0.19`.
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

Provider/model defaults are `openai-codex`, `gpt-5.6-luna`, `medium`, matching the
local launcher. Existing sessions retain their selected model; changing a default
does not update them. Use the SDK's session-model selection to change an existing
local conversation while preserving its history. Availability for the hosted
Environment and its session principals must be verified separately. Credentials
are supplied by the platform, never committed.

With SDK 2.0.18–2.0.19 and Tau 0.4.2, replayed conversation history can override the
bootstrap's selected model in the inference engine. `src/backoffice_agent/runtime.py`
uses the SDK's services factory and Tau's public model setter to align the idle
engine with the model authorized by the SDK bootstrap before a turn. It retains
conversation history and the SDK's authentication, provider control and persistence.
Recheck this compatibility guard when upgrading the SDK.

The contract Job is an **offline candidate check**, not a live deployed MCP check.
The platform's deployment readiness and the per-session MCP discovery check cover
different stages. Before treating the first hosted release as verified, validate the
workflow with the target platform, confirm provider access and requester delegation,
inspect both DeploymentRuns, and exercise actual agent-to-MCP queries with two
authorized fixture identities to check isolation. Check session resumption and the
effective runtime catalog. No hosted rollout or traffic-promotion/rollback test is
claimed by the local tests. The ADR's predeployment live smoke gate and automated
postdeployment rollback remain follow-up integration work.

## Chat file support

The published SDK 2.0.19 still converts chat input to text before starting a turn.
Its chat request parser ignores file parts, and a file-only message has no usable
prompt. The SDK exposes no attachment upload route. Command Center SDK 0.5.18
and Command Center AI 0.0.15 are also the latest published frontend versions
checked on 2026-10-19; the AI conversation contract excludes attachments.
Assistant file input therefore awaits compatible package releases. Business
document processing is a separate API capability and does not add chat attachments
or expand this helper's read-only tool permissions.

## Local verification

Use the locked environment:

```sh
uv sync --locked
uv run python -m scripts.check_agent_contract
uv run pytest tests/agent tests/api/test_mcp_queries.py -q
```

The 2026-10-19 SDK 2.0.19 upgrade passed the ten-tool contract check and all 27
focused tests. An isolated loopback runtime also returned a real GPT-5.6 Luna
reply, retained its conversation across a process restart, and answered a second
turn in that same conversation. Both replies were present in SDK history afterward.
This verifies local chat and persistence, not file attachments or hosted delegation.

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

The comparison implementation advances the reviewed MCP snapshot to version 3. Only
`list_document_sets` and `get_document_set` output schemas gain comparison-policy
metadata. Tool inputs, all ten tools, read-only annotations, verified-requester
checks and the two Tau exclusion flags remain unchanged. The helper cannot trigger
comparisons; status queries reuse retained observations and otherwise report them
as pending. Publish this pinned snapshot with the matching API release.

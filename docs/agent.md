# Back Office helper agent

The dedicated `api/tau/main.py` exports the app returned by `ms-tau-sdk==2.0.20`.
It disables coding tools and the central Main Sequence MCP with explicit settings;
the deployment workflow declares the same flags. The SDK owns authentication,
requester delegation, model credentials, session lifecycle and health endpoints.

## Business tools

The agent binds to `backoffice_api` through `spec.mcp_applications`. Tau exposes
`backoffice_api__list_tools` and `backoffice_api__call_tool`. The project extension
in `.tau/extensions/backoffice_policy/extension.py` adds hooks, not new tools.

The hooks require a verified requester and restrict business operations to the
reviewed MCP catalog in `src/backoffice_agent/policy.py`. Runtime discovery validates
the SDK-projected input schemas and read-only annotations against the release-owned snapshot. The offline release gate also validates output
schemas and all side-effect annotations. Extra server
tools are filtered out and cannot be called by guessing their names. Failed
discovery blocks subsequent calls. Other application/resource wrappers are blocked.
Skill reads permit only the four release-owned guidance files in `SKILL_FILES`;
arbitrary workspace and development-skill reads remain blocked. SDK task/session
controls retain SDK ownership.

Canonical case tools read actual CaseType, subject, pinned Document Set, selected
evidence, workspace, reviewer membership and evaluation state. The approved mutation
slice creates subjects and cases, links same-subject documents, changes only the
requester's own reviewer membership, processes existing ready subject-owned sources
and starts/retries shared extraction or evaluation runs. The
[API MCP catalog](mcp.md) describes the exact supported tools and their arguments,
including processing capability boundaries. The helper never calls the database,
bucket or parser directly. It cannot assign arbitrary staff, manually edit/review
documents, approve loans/accounts or close cases.

The SDK still lists its retained native controls; restriction is enforced before
execution. Extensions are trusted project code, not a Python sandbox. Changing the
extension or allowlist changes authority and requires review. This release's case
mutations were explicitly authorized; the skill does not grant extra permissions.

The subject is the person represented in the evidence, not the requester or a staff
reviewer. Back Office may automatically accept a revision under the configured
per-type classification policy and validation guards. Such revisions do not require
staff re-review merely because acceptance was automatic. Effective state and current
requirements may still demand review or renewal. Acceptance is not case approval.

## Deployment

The existing production-scoped workflow now orders:

`image → migrate → deploy_api → agent_contract → agent_image → deploy_agent`

Both the API and helper agent declare `min_scale: 1` and `max_scale: 5`.
One warm replica of each avoids idle scale-to-zero startup delays, accepting the
ongoing compute cost of those two instances. The floor applies after a successful
workflow deployment; it does not bypass platform scheduling, readiness or runtime
admission, or guarantee uninterrupted service during failures.

The contract Job runs `scripts/check_agent_contract.py` against the candidate API
catalog without querying business storage. It verifies the pinned input/output
schemas, annotations and required artifacts. The agent image is prepared separately
because its deployable entry point differs; the workflow supplies the same source
event. The agent receives a viewer API-resource grant (which includes invocation),
no MetaTables branch grant, and declares `acts_for_requester: true`. Back Office
still enforces business permissions for every operation. Platform authorization
must permit that declaration; the application does not grant itself delegation authority.

Provider/model defaults are `openai-codex`, `gpt-5.6-luna`, `medium`, matching the
local launcher. Existing sessions retain their selected model; changing a default
does not update them. Use the SDK's session-model selection to change an existing
local conversation while preserving its history. Availability for the hosted
Environment and its session principals must be verified separately. Credentials
are supplied by the platform, never committed.

With SDK 2.0.18–2.0.20 and Tau 0.4.2, replayed conversation history can override the
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

## Command Center icon

The helper uses the approved **Casekeeper** folder character from
[`assets/agents/casekeeper`](../assets/agents/casekeeper/README.md). The
`backoffice_helper` resource in `.mainsequence/workflows/backoffice.yaml`
declares its idle icon with preserved colors and pixelated scaling, plus four
named poses. Command Center selects `thinking`, `working` and `error` from
the run state; the `backoffice_api` application rule selects `casework` while
that application's tools run. The rule covers the application, not individual
business operations.

These are static PNG poses that switch with activity, not looping animations.
The platform reads the assets from the exact deployment event's repository
commit and publishes them through its authenticated agent icon projection.
They are presentation assets, not Agent Card metadata or runtime tools.
The next deployment must include the workflow and all five PNGs in its source
commit. Local validation does not establish that a hosted icon is already live.

## Chat file support

The published SDK 2.0.20 still converts chat input to text before starting a turn.
Its chat request parser ignores file parts, and a file-only message has no usable
prompt. The SDK exposes no attachment upload route. Command Center SDK 0.5.18
and Command Center AI 0.0.16 are the latest published frontend versions checked
on 2026-10-19. AI 0.0.16 ships the proposed attachment ADR 018 as documentation
only; its changelog explicitly says no attachment feature ships.
Assistant file input therefore awaits compatible package releases. Business
document processing is a separate API capability and does not add chat attachments
or supply the helper with an original-byte upload tool. The helper can process an
existing ready subject-owned source through its approved MCP tool, or automatically
allocate a persisted intake/source with the ADR 0007 tools. The static-site Drop files
screen supplies the authenticated original-byte intake transport.

The local 2.0.20/0.0.16 check used the actual SDK Vite proxy and live runtime.
A synthetic file-only chat payload returned HTTP 400 with
`Request does not contain a user message`. A text-plus-file payload reached the
model without its file content: the reply was `NO ATTACHMENT CONTENT`, and SDK
history did not contain the synthetic file token. The real browser composer had
no file input. These are capability failures, not successful uploads.

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

The subsequent 2.0.20 upgrade on the same date passed the ten-tool contract check
and all 27 focused tests again. The upgraded local frontend rendered a real
GPT-5.6 Luna reply through the SDK proxy. File-input failures are recorded above.

The policy tests use fake requester identities and native Tau hook types; they make
no model calls and do not seed cases. Local Tau mode has no hosted requester binding.
The explicitly enabled developer connection below verifies the developer instead;
it does not fabricate a requester or change hosted delegation. Test actual hosted
delegation through the hosted runtime, with approved fixture access.

`src/backoffice_agent/mcp_contract.json` is release-owned. A deliberate API contract
change requires reviewing the corresponding tool behavior and updating that snapshot
and its SHA-256 together. Do not regenerate it automatically during deployment, which
would accept unreviewed drift. The snapshot is included as package data.

The source card and repository-owned helper skill are under `.agents/`. Managed
development skills were synchronized explicitly from the pinned SDK; no startup
path changes those instructions.

The earlier comparison-only release used snapshot version 3 with ten read-only
queries: it added comparison metadata to Document Set output schemas and reused
retained observations. The case-building release supersedes that business scope
with canonical reads and approved mutations, including comparison execution. Ship
its reviewed snapshot with the matching API and helper; preserve verified-requester
checks and both Tau exclusion flags.


## Case analysis and case-building skill

The runtime skill is [.tau/skills/backoffice-casework/SKILL.md](../.tau/skills/backoffice-casework/SKILL.md),
with self-contained ontology and case-building references. The source agent card
advertises it and `.tau/SYSTEM.md` routes case requests to it. The installed Tau skill
loader discovers it normally. The SDK retains its scoped reader; the project hook
permits only the exact release-owned guidance files. The candidate contract Job
checks those files are present.

The skill uses one subject → typed case → pinned policy → selected evidence →
effective revision acceptance → evaluation workflow for loans and account opening.
It uses canonical tools for actual case metadata and membership; legacy assignments
still refer to the same case IDs. Analysis-only requests stay read-only. Authorized
case-building requests use supported mutations with durable operation keys and
observed revisions; ambiguities are resolved before dependent writes.

The initial plan-only boundary in [ADR 0005](adr/0005-casework-skill-and-scoped-guidance.md)
is superseded for business operations by
[ADR 0006](adr/0006-case-building-mcp-workflow.md). The exact-file guidance exception
remains. Unsupported source transport and manual-review actions receive explicit
UI handoffs; planned, performed, queued and blocked work remain distinct.

`tests/agent/test_casework_skill.py` exercises real Tau discovery and SDK skill reads
through the project hooks, including rejected paths and symlink escapes. Agent/MCP
tests cover requester/discovery requirements and the reviewed capability contract.
These tests use no model inference and do not establish hosted readiness. Keep the
runtime references aligned with [the ontology](cases.md) and the MCP catalog as they
evolve together.


## Authenticated local developer MCP

The local stack explicitly enables `BACKOFFICE_LOCAL_MCP_ENABLED=true` and passes
`BACKOFFICE_API_ORIGIN` and `BACKOFFICE_LOCAL_SOURCE_UID` from its verified API
preparation. It retains both Tau tool-exclusion flags and binds the helper to
loopback. Manual launches must provide those same settings.

The project extension registers only `backoffice_api__list_tools` and
`backoffice_api__call_tool` in this mode. It uses the installed SDK's MCP client,
protocol handling, timeout metadata and result projection. Before every call it
verifies the saved Main Sequence developer login, matches `/me` against that UID,
and verifies `/healthz` is the exact pinned local SQLite source. A login/source
change, unavailable identity, catalog drift or remote API origin blocks business
calls. Each connection closes after its operation; uncertain mutations are never
automatically replayed. No token, arbitrary HTTP tool or database access is exposed
to the model. The existing loopback API gateway owns credential renewal and request
identity verification.

This is an explicit single-developer local authority path authorized for development,
not SDK requester delegation. Hosted markers or assertion mode reject the local
adapter. Hosted sessions continue to require `current_requester()` and the platform's
application declaration and access checks. Never enable the local adapter in a
hosted deployment. SDK health's `mcp_connected` describes the excluded central MCP;
local business wrappers appear in `project_tool_count` after a session loads.

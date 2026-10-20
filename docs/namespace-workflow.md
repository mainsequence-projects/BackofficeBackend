# Back Office namespace and deployment workflow

The application uses one MetaTables namespace, `backoffice`. All eighteen business
tables and the provider's Alembic registry explicitly declare it. The physical
`backoffice__*` names and `backoffice__alembic_version` remain stable.

This procedure follows the installed MetaTables 0.1.49
[migration skill](../.agents/skills/metatables/metatables-migrations/SKILL.md) and its
[deployment guide](../.agents/skills/metatables/metatables-migrations/references/docs/client/deploy-application-migrations.md).

## Repository implementation

`.mainsequence/workflows/backoffice.yaml` uses workflow API 3.0.0 and the graph
`image → migrate → deploy_api`. The candidate image supplies the migration Job
and API. Both resources declare platform `reader` access to the MetaTables branch.
`scripts/migrate_backoffice.py` calls `upgrade_application` before publishing the
schema/policy catalog; a migration exception stops the Job and prevents rollout.
Neither importing nor starting the API performs migrations or role grants.

When registration encounters an absent namespace, MetaTables creates it. A local
human migration gives that human `owner`. A hosted migration Job receives `editor`
and is recorded as the namespace's creating workload. No administrator or manual
namespace creation is required for the normal first deployment. A namespace that
already exists is never silently taken over or recreated.

## Per-Environment access after resource creation

The workflow creates workload Users before its execution steps. After the first
migration creates the namespace, someone who manages the migration Job manages its
namespace access. That person performs these actions in the target Environment:

1. Grant the API workload `data_writer`, which permits row operations without
   giving it schema or sharing authority.
2. Grant themselves or an approved Team `owner`, so the namespace retains an owner
   if the migration Job and its workload identity are later recreated.
3. For an existing namespace, have its owner grant the migration Job `editor`
   before retrying a refused migration.

Managing the creating Job gives permission-management authority; it does not give
access to the namespace's data until a role is granted. A recreated Job has a new
workload User, so a direct grant must be updated. An approved Team can hold roles
and include workload Users to reduce repeated grants. A Team is optional.

Use the namespace Access panel and find workloads by their Job or release name.
Alternatively, use the public Python client from an authorized **human** session.
First resolve the exact Job and API ResourceRelease in the intended Environment,
then use their backend-returned `workload_user_uid`. A release UID, Job UID or
business-person UID is not the workload's User UID.

```python
from mainsequence.client import User
from metatables import Namespace

# api_release and migration_job are the verified platform resources for this
# deployment. Resolve them through the SDK using backend-returned public UIDs.
api_user_uid = api_release.workload_user_uid
migration_user_uid = migration_job.workload_user_uid
if not api_user_uid or not migration_user_uid:
    raise RuntimeError("The platform has not supplied both workload identities")

namespace = next(n for n in Namespace.filter(search="backoffice") if n.name == "backoffice")
namespace.grant_role(str(api_user_uid), "data_writer")
namespace.grant_role(str(User.get_authenticated_user_details().uid), "owner")
```

For an approved owner Team, replace the human owner grant with
`namespace.grant_role(team_uid, "owner", principal_kind="team")`. When the namespace
already exists and the migration was refused, its owner grants
`namespace.grant_role(str(migration_user_uid), "editor")` and reruns the deployment Job.
Do not replace an existing stronger grant with a weaker one unnecessarily.

These are operator actions after resolving the actual target resources, not Job
code or automatic API startup behavior. MetaTables refuses role changes by
workload identities. A fresh hosted client process must not call
`configure_local_client()` or inherit a local `METATABLES_API_URL`; verify the
hosted runtime and Environment before making a grant. No hosted grants have been
applied by this dependency update, and no hosted migration has been run from a
developer process.

An API that lacks the role remains unable to read/write tables. After the correct
grant, its next request succeeds without redeployment. Reviewer permission is a
separate business configuration; a MetaTables grant does not make someone a
Back Office reviewer.

## Failure and recovery

`namespace_access_required` means the namespace exists and the migration caller
cannot create tables there. Use the error's caller UID and owner/manager details
to obtain `editor`, then rerun the same Job. Preserve the namespace and physical
table names. An older namespace from before namespace owners were implemented may
need a one-time owner assignment by an Organization admin.

`namespace_required` means a workload attempted registration outside a namespace;
keep every provider model, including the migration registry, scoped to `backoffice`.
`table_not_editable` is resolved by the appropriate table/namespace grant, not by
changing identifiers or running the Job as an admin. The installed client version
does not itself upgrade a separately deployed MetaTables API; verify the target
API supports this namespace lifecycle before deployment.

## Verification and skill refresh

The offline suite verifies all 17 registration requests use `backoffice`, every
consumer deployment depends on the migration Job, resources declare MetaTables
reader access, migration failure prevents catalog publication, and the Job
contains no namespace creation or role-grant calls. It also checks that the copied
skill bundle exactly matches the installed client and its version sentinel.

A fresh isolated MetaTables 0.1.49 local runtime was tested without any preliminary
namespace creation: the provider created `backoffice`, the human creator received
`owner`, all 17 table bindings used the verified local DataSource, and a repeated
upgrade retained the same namespace identity and migration head `backoffice_0002`.
This verifies the local registration lifecycle. Hosted workload grants and rollout
are checked separately after the real resources exist.

After changing the dependency, refresh its five project skills explicitly:

```bash
uv sync --locked
uv run metatables copy-metatables-skills --path .
uv run pytest -q
```

The managed namespace is `.agents/skills/metatables/`, with version recorded in
`PINNED_FROM.txt`. Keep application-owned instructions outside that namespace;
the supported refresh replaces only the MetaTables bundle.

## Migration Job completion

The migration Job finishes only after both `upgrade_application` and
`publish_catalog` succeed. The MetaTables runner's final timing message covers
table migration and finalization; it is not the Job's completion signal.

Catalog publication reads the authored identities once per catalog table and
checks every stored immutable definition. Existing timestamps are preserved.
Missing records still use atomic insert-if-absent with read-back. Repeating an
unchanged publication takes four governed reads instead of two reads for each
of the 53 authored records. Deployment remains gated on the Job's `SUCCEEDED`
status.

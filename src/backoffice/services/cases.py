"""Canonical cases; compatibility assignments delegate to the same persistence engine."""

from uuid import UUID

from ..models.case import Case
from ..policies.case_types import legacy_case_type
from ..tables.cases import CaseTypeDocumentSetRecord, CaseTypeRecord
from .application import SETS, A, fail, stable

TYPES = CaseTypeRecord.__table__
BINDINGS = CaseTypeDocumentSetRecord.__table__


def type_key(row):
    # Nullable only to keep old releases and durable pre-migration intents writable.
    return row.get("case_type_key") or legacy_case_type(row["set_key"])


def types(app):
    rows = app.db.rows(TYPES, limit=101, order=TYPES.c.name.asc())
    if len(rows) > 100:
        fail(409, "case_type_catalog_limit_exceeded")
    result = []
    for row in rows:
        bindings = app.db.rows(BINDINGS, BINDINGS.c.case_type_key == row["key"], limit=501)
        if len(bindings) > 500:
            fail(409, "case_type_policy_catalog_limit_exceeded")
        policies = []
        for binding in bindings:
            policy = app.required(SETS, set_key=binding["set_key"], version=binding["set_version"])
            if policy["status"] == "published":
                policies.append(
                    {
                        "key": policy["set_key"],
                        "version": policy["version"],
                        "name": policy["definition"]["name"],
                    }
                )
        result.append({**row, "document_sets": policies})
    return {"items": result}


def detail(app, uid):
    assignment = app.assignment(uid)
    row = app.required(A, uid=uid)
    result = Case(
        uid=uid,
        subject_uid=assignment["person_uid"],
        case_type_key=type_key(row),
        document_set_key=assignment["set_key"],
        document_set_version=assignment["set_version"],
        revision=assignment["revision"],
        document_uids=assignment["document_uids"],
        created_at=assignment["created_at"],
        updated_at=assignment["updated_at"],
    ).model_dump(mode="json")
    return {**result, "case_type": app.required(TYPES, key=result["case_type_key"])}


def create(app, subject_uid, command, *, legacy=False):
    app.case(subject_uid, reading=False)
    policy = app.db.one(
        SETS, set_key=command.document_set_key, version=command.document_set_version
    )
    if policy is None or policy["status"] != "published":
        fail(404, "document_set_version_not_found")
    key = legacy_case_type(policy["set_key"]) if legacy else command.case_type_key
    if not app.db.one(TYPES, key=key):
        fail(422, "case_type_not_found")
    if not app.db.one(
        BINDINGS, case_type_key=key, set_key=policy["set_key"], set_version=policy["version"]
    ):
        fail(422, "document_set_not_permitted_for_case_type")

    def build(op, now):
        # Same UUID derivation as historical assignment creation; no second case identity.
        uid = stable(op, "assignment")
        return [
            app.ensure_step(
                A,
                {
                    "uid": uid,
                    "person_uid": str(subject_uid),
                    "case_type_key": key,
                    "set_key": policy["set_key"],
                    "set_version": policy["version"],
                    "revision": 1,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        ], {"uid": uid, "revision": 1}

    return app.mutate(
        subject_uid, command, "assignment.created" if legacy else "case.created", build
    )


def list_for_subject(app, uid, limit=50, offset=0):
    app.case(uid)
    page = app.db.page(
        A,
        A.c.person_uid == UUID(str(uid)),
        limit=limit,
        offset=offset,
        order=(A.c.created_at.desc(), A.c.uid.asc()),
    )
    page["items"] = [detail(app, r["uid"]) for r in page["items"]]
    return page

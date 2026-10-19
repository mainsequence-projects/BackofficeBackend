"""Case-centred read models and staff responsibility on the shared document engine."""

from collections import Counter
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from ..tables.reviewers import CaseReviewerRecord
from .application import AUDIT, EV, A, P, canonical, fail

MEMBERS = CaseReviewerRecord.__table__


def reviewers(app, uid):
    app.assignment(uid)
    rows = app.db.rows(MEMBERS, MEMBERS.c.assignment_uid == UUID(str(uid)), limit=201)
    if len(rows) > 200:
        fail(409, "case_reviewer_history_limit_exceeded")
    own = next((r for r in rows if r["reviewer_uid"] == app.actor), None)
    return {
        "items": [r for r in rows if r["active"]],
        "my_revision": own["revision"] if own else 0,
        "assigned_to_me": bool(own and own["active"]),
    }


def set_my_membership(app, uid, command):
    if hasattr(command, "case_uid") and str(command.case_uid) != str(uid):
        fail(422, "case_command_target_mismatch")
    if not app.reviewer:
        fail(403, "reviewer_role_required")
    assignment = app.assignment(uid, reading=False)

    def build(op, now):
        keys = {"assignment_uid": str(uid), "reviewer_uid": app.actor}
        old = app.db.one(MEMBERS, **keys)
        revision = old["revision"] if old else 0
        if revision != command.expected_revision:
            fail(409, "stale_reviewer_membership")
        if old is None and app.db.count(MEMBERS, MEMBERS.c.assignment_uid == UUID(str(uid))) >= 200:
            fail(409, "case_reviewer_history_limit_exceeded")
        values = dict(
            active=command.assigned,
            revision=revision + 1,
            display_name=app.actor_display_name,
            updated_at=now,
        )
        step = (
            app.step(MEMBERS, values, keys=keys, expected={"revision": revision})
            if old
            else app.ensure_step(MEMBERS, {**keys, **values})
        )
        return [step], {"uid": str(uid), "reviewer_uid": app.actor, **values}

    return app.mutate(assignment["person_uid"], command, "case.reviewer_changed", build)


def lane(status):
    if status["summary"]["complete"]:
        return "checks_satisfied"
    findings = [f for f in status["findings"] if f.get("mandatory", True)]
    if any(f["status"] == "failed" for f in findings):
        return "discrepancy"
    if any(f["status"] in {"missing", "needs_information"} for f in findings):
        return "missing_evidence"
    if any(f["status"] == "pending_review" for f in findings):
        return "review_required"
    # An inconsistent assessment is not evidence that a human decision is needed.
    return "updating"


def queue(app, search="", responsibility="all", set_key="", limit=10, offset=0, case_type_key=""):
    from sqlalchemy import and_

    from ..policies.case_types import DOCUMENT_SET_CASE_TYPES
    from .cases import TYPES, type_key

    # Correlated SQL keeps access and pagination in the same governed query.
    person_filters = [P.c.uid == A.c.person_uid]
    if not app.reviewer:
        person_filters.append(P.c.created_by == UUID(app.actor))
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        person_filters.append(
            or_(
                P.c.profile["full_name"].as_string().ilike(f"%{escaped}%", escape="\\"),
                P.c.profile["external_reference"].as_string().ilike(f"%{escaped}%", escape="\\"),
            )
        )
    conditions = [exists(select(1).select_from(P).where(*person_filters))]
    if case_type_key:
        # Include rows created by an old deployment during an additive rollout.
        legacy_keys = [k for k, v in DOCUMENT_SET_CASE_TYPES.items() if v == case_type_key]
        legacy_condition = (
            A.c.set_key.in_(legacy_keys)
            if case_type_key != "document_review"
            else A.c.set_key.not_in(list(DOCUMENT_SET_CASE_TYPES))
        )
        conditions.append(
            or_(
                A.c.case_type_key == case_type_key,
                and_(A.c.case_type_key.is_(None), legacy_condition),
            )
        )
    if set_key:
        conditions.append(A.c.set_key == set_key)
    member = (
        select(1)
        .select_from(MEMBERS)
        .where(MEMBERS.c.assignment_uid == A.c.uid, MEMBERS.c.active.is_(True))
    )
    if responsibility == "mine":
        conditions.append(exists(member.where(MEMBERS.c.reviewer_uid == UUID(app.actor))))
    elif responsibility == "unassigned":
        conditions.append(~exists(member))
    page = app.db.page(
        A, *conditions, limit=limit, offset=offset, order=(A.c.updated_at.desc(), A.c.uid.asc())
    )
    items = []
    for assignment in page["items"]:
        uid = assignment["uid"]
        case_type = app.required(TYPES, key=type_key(assignment))
        try:
            subject = app.case(assignment["person_uid"])["profile"]
            status = app.current_status(uid)
            details = app.assignment(uid)
            memberships = reviewers(app, uid)
            counts = dict(Counter(f["status"] for f in status["findings"]))
            outstanding = [
                f for f in status["findings"] if f["status"] not in {"satisfied", "not_applicable"}
            ]
            latest = app.db.rows(
                EV, EV.c.assignment_uid == UUID(uid), limit=1, order=EV.c.created_at.desc()
            )
            items.append(
                {
                    **assignment,
                    "case_type_key": case_type["key"],
                    "case_type": case_type,
                    "subject": {
                        "uid": subject["uid"],
                        "full_name": subject.get("full_name"),
                        "external_reference": subject.get("external_reference"),
                    },
                    "reviewers": memberships["items"],
                    "document_count": len(details["document_uids"]),
                    "finding_counts": counts,
                    "workflow_state": lane(status),
                    "summary": status["summary"],
                    "top_finding": min(
                        outstanding,
                        key=lambda f: (
                            not f.get("mandatory", True),
                            {
                                "failed": 0,
                                "missing": 1,
                                "needs_information": 1,
                                "pending_review": 2,
                            }.get(f["status"], 3),
                        ),
                    )
                    if outstanding
                    else None,
                    "latest_evaluated_at": latest[0]["created_at"] if latest else None,
                    "assessed_at": status["assessed_at"],
                }
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            items.append(
                {
                    **assignment,
                    "case_type_key": case_type["key"],
                    "case_type": case_type,
                    "workflow_state": "updating",
                    "error_code": exc.detail,
                    "subject": None,
                    "reviewers": [],
                    "finding_counts": {},
                    "summary": {},
                }
            )
    return {
        **page,
        "items": items,
        "scope": "Current page of accessible cases; status counts are page-local.",
    }


def workspace(app, uid):
    from .cases import detail

    case = detail(app, uid)
    frozen = app.evaluation_input(uid)
    status = app.current_status(uid)
    latest = app.db.rows(
        EV, EV.c.assignment_uid == UUID(str(uid)), limit=1, order=EV.c.created_at.desc()
    )
    evaluation = app.evaluation(latest[0]["uid"]) if latest else None
    docs = []
    pages = set()
    for document in frozen["documents"]:
        evidence = document.get("extraction_evidence")
        if evidence is None:
            from .application import DR

            evidence = app.required(
                DR, document_uid=document["uid"], revision=document["revision"]
            ).get("extraction_evidence")
        extraction = (evidence or {}).get("extraction", {})
        page_refs = [
            {**p, "source_uid": evidence["source_mapping"][p["source_file"]]}
            for p in extraction.get("pages", [])
        ]
        pages.update((p["source_uid"], p["page"]) for p in page_refs)
        docs.append(
            {
                **{k: v for k, v in document.items() if k != "extraction_evidence"},
                "evidence_summary": {
                    "pages": page_refs,
                    "field_count": len(extraction.get("field_evidence", [])),
                    "has_evidence": bool(evidence),
                    "run_uid": (evidence or {}).get("run_uid"),
                },
            }
        )
    history = app.db.page(
        AUDIT,
        AUDIT.c.resource_uid == UUID(frozen["person"]["uid"]),
        limit=20,
        order=AUDIT.c.occurred_at.desc(),
    )
    membership = reviewers(app, uid)
    app.case(frozen["person"]["uid"])
    if case["revision"] != frozen["assignment"]["revision"] or canonical(frozen) != canonical(
        app.evaluation_input(uid)
    ):
        fail(409, "assessment_inputs_changed_retry_query")
    return {
        "case": case,
        "assignment": frozen["assignment"],
        "subject": frozen["person"],
        "policy": frozen["policy"],
        "documents": docs,
        "status": status,
        "workflow_state": lane(status),
        "reviewers": membership,
        "latest_evaluation": evaluation,
        "subject_history": history,
        "page_count": len(pages),
        "page_count_complete": all(d["evidence_summary"]["has_evidence"] for d in docs),
    }

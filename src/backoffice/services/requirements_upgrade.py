"""Explicit audited upgrade; original revisions and evaluations remain immutable."""

from uuid import UUID

from ..schemas.drafts import get_draft_model
from ..schemas.registry import get_document_model
from ..schemas.scope import document_facts
from ..tables.evidence import FieldEvidenceRecord
from .application import DR, RV, SETS, A, D, fail, stable
from .contracts import CompleteParsing
from .parsing import RESULT, percent

# Frozen release targets, never derived from a growing registry.
DOCUMENT_TARGETS = dict.fromkeys(
    (
        "bank_statement",
        "tax_clearance_certificate",
        "residence_permit",
        "utility_bill",
        "payslip",
        "loan_contract",
        "employer_confirmation",
        "kyc_questionnaire",
    ),
    2,
) | {"national_identity_card": 3, "passport": 2}
POLICY_TARGETS = {"new_account_requirements": 7, "loan_requirements": 5}
FIELDS = FieldEvidenceRecord.__table__


def upgrade(app, subject_uid, command):
    if not app.organization_admin:
        fail(403, "organization_admin_required")

    def build(op, now):
        documents = app.db.rows(D, D.c.person_uid == subject_uid, limit=501)
        cases = app.db.rows(A, A.c.person_uid == subject_uid, limit=501)
        if len(documents) > 500 or len(cases) > 500:
            fail(409, "requirements_upgrade_subject_limit_exceeded")
        steps, upgraded, changed_cases, rechecks = [], [], [], []
        for document in documents:
            old = app.document(document["uid"], reading=False)
            target = DOCUMENT_TARGETS.get(old["document_type"])
            if target is None or old["schema_version"] > target:
                continue
            payload = document_facts(old["payload"])
            if old["schema_version"] == target and payload == old["payload"]:
                continue
            model = get_document_model if old["status"] == "submitted" else get_draft_model
            model(old["document_type"], target).model_validate(payload)
            original = app.required(DR, document_uid=old["uid"], revision=old["revision"])
            revision = old["revision"] + 1
            revision_uid = stable(op, f"revision:{old['uid']}")
            steps.append(
                app.ensure_step(
                    DR,
                    {
                        **original,
                        "uid": revision_uid,
                        "revision": revision,
                        "schema_version": target,
                        "payload": payload,
                        "created_by": app.actor,
                        "created_at": now,
                    },
                )
            )
            # Observations keep their original schema hash: no new extraction is claimed.
            fields = app.db.rows(FIELDS, FIELDS.c.revision_uid == UUID(original["uid"]), limit=501)
            if len(fields) > 500:
                fail(409, "requirements_upgrade_evidence_limit_exceeded")
            for field in fields:
                steps.append(
                    app.ensure_step(
                        FIELDS,
                        {
                            **field,
                            "uid": stable(op, f"field:{field['uid']}"),
                            "revision_uid": revision_uid,
                        },
                    )
                )
            review = old["latest_review"]
            review_uid = None
            if review:
                review_uid = stable(op, f"review:{old['uid']}")
                steps.append(
                    app.ensure_step(
                        RV,
                        {
                            **review,
                            "uid": review_uid,
                            "revision": revision,
                            "decision_sequence": 1,
                            "operation_key": stable(op, f"document:{old['uid']}"),
                            "reason": f"Unchanged evidence: carried forward review {review['uid']} from revision {old['revision']} for the happy-case schema upgrade. Original reason: {review['reason']}",
                        },
                    )
                )
            parsed = app.db.one(RESULT, document_uid=old["uid"], revision=old["revision"])
            if parsed and review:
                steps.append(
                    app.ensure_step(
                        RESULT,
                        {
                            **parsed,
                            "uid": stable(op, f"parsing:{old['uid']}"),
                            "revision": revision,
                            "operation_key": stable(op, f"document:{old['uid']}"),
                            "review_uid": review_uid if parsed["review_uid"] else None,
                        },
                    )
                )
            elif parsed:
                rechecks.append(
                    {
                        "document_uid": old["uid"],
                        "expected_revision": revision,
                        "parsing_score_percent": percent(parsed["score_basis_points"]),
                        "extractor": parsed["extractor"],
                    }
                )
            steps.append(
                app.step(
                    D,
                    {
                        "updated_at": now,
                        "current_revision": revision
                        if old["status"] == "submitted"
                        else old["current_revision"],
                    },
                    keys={"uid": old["uid"]},
                    expected={"updated_at": old["updated_at"]},
                )
            )
            upgraded.append(
                {
                    "uid": old["uid"],
                    "from_revision": old["revision"],
                    "revision": revision,
                    "schema_version": target,
                }
            )
        for case in cases:
            target = POLICY_TARGETS.get(case["set_key"])
            if target is None or case["set_version"] >= target:
                continue
            policy = app.required(SETS, set_key=case["set_key"], version=target)
            if policy["status"] != "published":
                fail(409, "requirements_upgrade_policy_not_published")
            steps.append(
                app.step(
                    A,
                    {
                        "set_version": target,
                        "revision": case["revision"] + 1,
                        "updated_at": now,
                    },
                    keys={"uid": case["uid"]},
                    expected={"revision": case["revision"]},
                )
            )
            changed_cases.append(
                {
                    "uid": case["uid"],
                    "from_version": case["set_version"],
                    "version": target,
                    "revision": case["revision"] + 1,
                }
            )
        return steps, {
            "uid": str(subject_uid),
            "documents": upgraded,
            "cases": changed_cases,
            "parsing_rechecks": rechecks,
        }

    result = app.mutate(subject_uid, command, "admin.happy_case_requirements_upgraded", build)
    # Reuse trusted saved classification scores, never invent scores or acceptances.
    # Each replay has its own durable key, so interruption is safely resumable.
    for recheck in result["parsing_rechecks"]:
        uid = recheck["document_uid"]
        app.complete_parsing(
            uid,
            CompleteParsing(
                operation_key=stable(command.operation_key, f"recheck:{uid}"),
                **{key: value for key, value in recheck.items() if key != "document_uid"},
            ),
        )
    return result

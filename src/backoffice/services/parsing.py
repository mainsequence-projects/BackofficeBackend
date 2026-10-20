"""Admin policy and trusted parsing completion; no classifier calls or helper tools."""

from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from ..schemas.registry import get_document_model
from ..tables.evidence import FieldEvidenceRecord
from ..tables.parsing import ParsingPolicyRecord, ParsingResultRecord
from .application import DR, RUN, RV, D, fail, stable
from .contracts import Command, CompleteParsing

POLICY = ParsingPolicyRecord.__table__
RESULT = ParsingResultRecord.__table__
SETTINGS_SCOPE = str(uuid5(NAMESPACE_URL, "backoffice:document-parsing-settings"))
DEFAULT_ACCEPTANCE_THRESHOLD = Decimal("80.00")


def percent(points):
    return format(Decimal(points) / 100, ".2f") if points is not None else None


def policy_view(row, document_type):
    return {
        "document_type": document_type,
        "score_kind": "classification_confidence",
        "revision": row["revision"] if row else 0,
        "automatic_acceptance_enabled": bool(row["automatic_acceptance_enabled"]) if row else True,
        "acceptance_threshold_percent": percent(row["threshold_basis_points"])
        if row
        else str(DEFAULT_ACCEPTANCE_THRESHOLD),
        "changed_by": row["changed_by"] if row else None,
        "changed_at": row["created_at"] if row else None,
    }


def settings_scope(document_type):
    return stable(SETTINGS_SCOPE, document_type)


def current_policy(app, document_type, *, reading=True):
    get_document_model(document_type)
    if reading and app.db.one(RUN, uid=stable(settings_scope(document_type), "case-lock")):
        fail(409, "parsing_settings_change_in_progress")
    rows = app.db.rows(
        POLICY, POLICY.c.document_type == document_type, limit=1, order=POLICY.c.revision.desc()
    )
    return rows[0] if rows else None


def settings(app, document_type):
    if not app.organization_admin:
        fail(403, "organization_admin_required")
    return policy_view(current_policy(app, document_type), document_type)


def ensure_default_policy(app, document_type, operation_key):
    """Persist the default before use, under the same lock as administrator edits.

    Retry identity comes from the parsing command. Explicit per-type settings win;
    defaults never replace them. Results always retain an actual policy revision.
    """
    command = Command(operation_key=stable(operation_key, f"default-policy:{document_type}"))
    scope = settings_scope(document_type)
    lock = app.db.one(RUN, uid=stable(scope, "case-lock"))
    resuming = lock and lock["input_snapshot"].get("operation") == str(command.operation_key)
    if not resuming and current_policy(app, document_type) is not None:
        return

    def build(op, now):
        previous = current_policy(app, document_type, reading=False)
        if previous is not None:
            return [], {"policy_uid": previous["uid"]}
        row = {
            "uid": stable(op, "parsing-policy"),
            "settings_key": f"document_parsing:{document_type}",
            "document_type": document_type,
            "revision": 1,
            "automatic_acceptance_enabled": True,
            "threshold_basis_points": int(DEFAULT_ACCEPTANCE_THRESHOLD * 100),
            "changed_by": app.actor,
            "created_at": now,
            "operation_key": op,
        }
        return [app.ensure_step(POLICY, row)], {"policy_uid": row["uid"]}

    app.mutate(
        scope,
        command,
        "settings.parsing_default_initialized",
        build,
        create=True,
        resource_type="settings",
    )


def update_settings(app, command):
    if not app.organization_admin:
        fail(403, "organization_admin_required")

    def build(op, now):
        previous = current_policy(app, command.document_type, reading=False)
        revision = previous["revision"] if previous else 0
        if command.expected_revision != revision:
            fail(409, "stale_parsing_settings_revision")
        row = {
            "uid": stable(op, "parsing-policy"),
            "settings_key": f"document_parsing:{command.document_type}",
            "document_type": command.document_type,
            "revision": revision + 1,
            "automatic_acceptance_enabled": command.automatic_acceptance_enabled,
            "threshold_basis_points": int(command.acceptance_threshold_percent * 100)
            if command.acceptance_threshold_percent is not None
            else None,
            "changed_by": app.actor,
            "created_at": now,
            "operation_key": op,
        }
        return [app.ensure_step(POLICY, row)], policy_view(row, command.document_type)

    return app.mutate(
        settings_scope(command.document_type),
        command,
        "admin.parsing_settings_changed",
        build,
        create=True,
        resource_type="settings",
    )


def result_view(app, document_uid, revision):
    row = app.db.one(RESULT, document_uid=document_uid, revision=revision)
    if row is None:
        return None
    policy = app.db.one(POLICY, uid=row["policy_uid"]) if row["policy_uid"] else None
    return {
        "document_type": app.required(D, uid=document_uid)["document_type"],
        "score_kind": "classification_confidence",
        "policy_document_type": policy["document_type"] if policy else None,
        "uid": row["uid"],
        "revision": row["revision"],
        "parsing_score_percent": percent(row["score_basis_points"]),
        "decision": row["decision"],
        "reason_code": row["reason_code"],
        "policy_revision": policy["revision"] if policy else 0,
        "acceptance_threshold_percent": percent(policy["threshold_basis_points"])
        if policy
        else None,
        "extractor": row["extractor"],
        "processed_at": row["created_at"],
        "review_uid": row["review_uid"],
    }


def reapply_policy(app, uid, command):
    """Recheck retained scores without changing facts, reviews or case policies."""
    if not app.organization_admin:
        fail(403, "organization_admin_required")
    document = app.document(uid, reading=False)

    def build(op, now):
        current = app.document(uid, reading=False)
        if current["revision"] != command.expected_revision:
            fail(409, "stale_document_revision")
        result = {"document_uid": str(uid), "revision": current["revision"]}
        if current["latest_review"]:
            return [], {**result, "outcome": "skipped_reviewed"}
        parsed = app.db.one(RESULT, document_uid=uid, revision=current["revision"])
        if parsed is None or parsed["score_basis_points"] is None:
            return [], {**result, "outcome": "skipped_score_missing"}
        policy = current_policy(app, current["document_type"])
        if policy and parsed["policy_uid"] == policy["uid"]:
            return [], {**result, "outcome": "skipped_current_policy"}
        original = app.required(DR, document_uid=uid, revision=current["revision"])
        revision = current["revision"] + 1
        revision_uid = stable(op, "policy-recheck-revision")
        steps = [
            app.ensure_step(
                DR,
                {
                    **original,
                    "uid": revision_uid,
                    "revision": revision,
                    "created_by": app.actor,
                    "created_at": now,
                },
            )
        ]
        # Carry the original observations and schema hashes; no new extraction is claimed.
        fields = FieldEvidenceRecord.__table__
        observations = app.db.rows(
            fields, fields.c.revision_uid == UUID(original["uid"]), limit=501
        )
        if len(observations) > 500:
            fail(409, "parsing_policy_recheck_evidence_limit_exceeded")
        for field in observations:
            steps.append(
                app.ensure_step(
                    fields,
                    {
                        **field,
                        "uid": stable(op, f"field:{field['uid']}"),
                        "revision_uid": revision_uid,
                    },
                )
            )
        steps.append(
            app.step(
                D,
                {
                    "updated_at": now,
                    "current_revision": revision
                    if current["status"] == "submitted"
                    else current["current_revision"],
                },
                keys={"uid": str(uid)},
                expected={"updated_at": current["updated_at"]},
            )
        )
        return steps, {
            "document_uid": str(uid),
            "revision": revision,
            "from_revision": current["revision"],
            "outcome": "rechecked",
            "parsing_score_percent": percent(parsed["score_basis_points"]),
            "extractor": parsed["extractor"],
        }

    result = app.mutate(document["person_uid"], command, "admin.parsing_policy_reapplied", build)
    if result["outcome"] != "rechecked":
        return result
    # Independent durable intent makes a lost response between these steps resumable.
    parsing = complete(
        app,
        uid,
        CompleteParsing(
            operation_key=stable(command.operation_key, "complete-policy-recheck"),
            expected_revision=result["revision"],
            parsing_score_percent=result["parsing_score_percent"],
            extractor=result["extractor"],
        ),
    )
    return {**result, "parsing_result": parsing}


def complete(app, uid, command):
    if not (app.organization_admin or app.parsing_processor):
        fail(403, "parsing_processor_required")
    document = app.document(uid, reading=False, processing=True)
    ensure_default_policy(app, document["document_type"], command.operation_key)

    def build(op, now):
        current = app.document(uid, reading=False, processing=True)
        if current["revision"] != command.expected_revision:
            fail(409, "stale_document_revision")
        if current["latest_review"]:
            fail(409, "parsing_cannot_overwrite_review")
        if app.db.one(RESULT, document_uid=uid, revision=current["revision"]):
            fail(409, "parsing_result_already_recorded")
        policy = current_policy(app, current["document_type"])
        score = (
            int(command.parsing_score_percent * 100)
            if command.parsing_score_percent is not None
            else None
        )
        threshold = policy["threshold_basis_points"] if policy else None
        valid = True
        try:
            get_document_model(current["document_type"], current["schema_version"]).model_validate(
                current["payload"]
            )
        except ValidationError:
            valid = False
        sources = bool(current["raw_document_refs"])
        if sources:
            # Ownership and ready-state failures are errors, never trusted score approvals.
            app.validate_refs(current["person_uid"], current["raw_document_refs"])
        from .extraction_evidence import review_reason

        revision_row = app.required(DR, document_uid=uid, revision=current["revision"])
        evidence_reason = review_reason(revision_row.get("extraction_evidence"))
        reason = (
            "invalid_document_attributes"
            if not valid
            else "source_evidence_required"
            if not sources
            else evidence_reason
            if evidence_reason
            else "parsing_policy_missing"
            if not policy
            else "automatic_acceptance_disabled"
            if not policy["automatic_acceptance_enabled"]
            else "parsing_score_missing"
            if score is None
            else "parsing_score_below_threshold"
            if score < threshold
            else "parsing_score_meets_threshold"
        )
        accepted = reason == "parsing_score_meets_threshold"
        steps = []
        if valid and sources and current["status"] == "draft":
            steps += [
                app.step(
                    DR,
                    {"status": "submitted", "submitted_at": now},
                    keys={"document_uid": str(uid), "revision": current["revision"]},
                    expected={"status": "draft"},
                ),
                app.step(
                    D,
                    {"current_revision": current["revision"], "updated_at": now},
                    keys={"uid": str(uid)},
                    expected={
                        "current_revision": current["current_revision"],
                        "updated_at": current["updated_at"],
                    },
                ),
            ]
        review_uid = stable(op, "automatic-review") if accepted else None
        if accepted:
            steps.append(
                app.ensure_step(
                    RV,
                    {
                        "uid": review_uid,
                        "document_uid": str(uid),
                        "revision": current["revision"],
                        "decision_sequence": 1,
                        "decision": "accepted",
                        "reason": f"Automatically accepted: classification confidence {percent(score)}% meets the {percent(threshold)}% threshold for {current['document_type']} in parsing policy revision {policy['revision']}; document attributes and source evidence passed validation.",
                        "reviewed_by": app.actor,
                        "reviewed_at": now,
                        "operation_key": op,
                    },
                )
            )
        row = {
            "uid": stable(op, "parsing-result"),
            "document_uid": str(uid),
            "revision": current["revision"],
            "score_basis_points": score,
            "policy_uid": policy["uid"] if policy else None,
            "decision": "accepted" if accepted else "needs_review",
            "reason_code": reason,
            "review_uid": review_uid,
            "extractor": command.extractor,
            "processed_by": app.actor,
            "operation_key": op,
            "created_at": now,
        }
        steps.append(app.ensure_step(RESULT, row))
        return steps, {
            "document_type": current["document_type"],
            "score_kind": "classification_confidence",
            "uid": row["uid"],
            "document_uid": str(uid),
            "revision": current["revision"],
            "decision": row["decision"],
            "reason_code": reason,
            "policy_revision": policy["revision"] if policy else 0,
            "review_uid": review_uid,
        }

    return app.mutate(
        document["person_uid"], command, "document.parsing_completed", build, processing=True
    )

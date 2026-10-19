"""Private, subject-independent intake and durable allocation using the shared case engine.

ProcessingRun already has the required independent identity, immutable inputs and
fenced checkpoints. No nullable subject or parallel document table is introduced.
"""

import hashlib
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from mainsequence.client import User
from pydantic import ValidationError
from sqlalchemy import or_, update

from ..schemas.registry import DOCUMENT_MODELS
from ..services.application import RAW, RUN, SCHEMA, A, Application, D, canonical, fail, stable
from ..services.contracts import EvaluateCase, LinkCaseDocuments
from ..services.reconciliation import normalized, reconcile
from ..services.storage import typed
from .adapters import MainSequenceBucket, MainSequenceDispatcher, ProcessingError, inspect_source
from .allocation_contracts import BindIntake
from .workflow import LEASE_SECONDS, Worker, configured_reader_mode

KIND = "document.allocate"
MAX_SUBJECTS = 10000
MAX_CASES = 500


def now():
    return datetime.now(UTC).isoformat()


def record(uid, kind, inputs, result=None, status="pending"):
    stamp = now()
    return dict(
        uid=str(uid),
        operation_key=str(uid),
        kind=kind,
        input_snapshot=inputs,
        result=result or {},
        status=status,
        attempt_count=0,
        job_run_uid=None,
        agent_session_uid=None,
        inference_request_uid=None,
        created_at=stamp,
        updated_at=stamp,
        lease_token=None,
        lease_expires_at=None,
    )


def request_receipt(app, command, action, target):
    """Bind every external retry key to its actor, complete command and target."""
    inputs = dict(
        actor_uid=app.actor,
        action=action,
        target=str(target),
        command=command.model_dump(mode="json"),
    )
    row = app.db.ensure(
        RUN,
        record(
            command.operation_key, "allocation.request", inputs, {"uid": str(target)}, "completed"
        ),
    )
    if row["kind"] != "allocation.request" or row["input_snapshot"] != inputs:
        fail(409, "operation_key_reused_with_different_request")


def schemas(app):
    result = {}
    for kind, version in DOCUMENT_MODELS:
        if kind in result and result[kind]["version"] >= version:
            continue
        result[kind] = app.required(SCHEMA, document_type=kind, version=version)
    return result


def get(app, uid):
    row = app.required(RUN, uid=uid)
    # An intake is private to its initiating requester, including before binding.
    if row["kind"] != KIND or row["input_snapshot"]["actor_uid"] != app.actor:
        fail(404, "allocation_not_found")
    return row


def view(app, row, limit=20, offset=0):
    r, inputs = row["result"], row["input_snapshot"]
    candidates = []
    for candidate in r.get("candidates", []):
        try:
            app.case(candidate["uid"])
            candidates.append(candidate)
        except HTTPException:
            pass
    allowed = True
    if r.get("subject_uid"):
        try:
            app.case(r["subject_uid"])
        except HTTPException:
            allowed = False
    targets = r.get("targets", []) if allowed else []
    return dict(
        uid=row["uid"],
        intake_uid=row["uid"],
        filename=inputs["source"]["filename"],
        status=row["status"],
        stage=r.get("stage", "uploading"),
        revision=r.get("revision", 1),
        error_code=r.get("error_code") if allowed else "subject_access_changed",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        document_type=(r.get("classification_summary") or {}).get("document_type"),
        classification_confidence_percent=(r.get("classification_summary") or {}).get(
            "classification_confidence_percent"
        ),
        subject_uid=r.get("subject_uid") if allowed else None,
        candidates=candidates,
        document=r.get("document") if allowed else None,
        completion=r.get("completion") if allowed else None,
        targets=[
            {k: v for k, v in t.items() if k not in {"link_command", "evaluation_command"}}
            for t in targets[offset : offset + limit]
        ],
        targets_has_more=offset + limit < len(targets),
        targets_offset=offset,
        target_count=len(targets),
        resolution_required=row["status"] == "needs_input" and r.get("stage") == "resolving_person",
    )


def listing(app, limit=20, offset=0):
    page = app.db.page(
        RUN,
        RUN.c.kind == KIND,
        RUN.c.input_snapshot["actor_uid"].as_string() == app.actor,
        limit=limit,
        offset=offset,
        order=(RUN.c.created_at.desc(), RUN.c.uid.asc()),
    )
    page["items"] = [view(app, row) for row in page["items"]]
    return page


def dispatch(app, row, dispatcher=None):
    if row["status"] in {"completed", "needs_input", "cancelled"}:
        return view(app, row)
    try:
        job = (dispatcher or MainSequenceDispatcher()).dispatch(row["uid"])
        if job:
            app.db.change(RUN, {"uid": row["uid"]}, {"job_run_uid": str(UUID(job))})
    except (ProcessingError, ValueError):
        return {**view(app, row), "dispatch_error": "processing_dispatch_unavailable"}
    return view(app, get(app, row["uid"]))


def upload(app, command, content, *, bucket=None, dispatcher=None):
    if (
        len(content) != command.byte_count
        or hashlib.sha256(content).hexdigest() != command.content_sha256
    ):
        fail(422, "source_checksum_mismatch")
    inspect_source(content, command.media_type)
    uid = stable(command.operation_key, "intake")
    request_receipt(app, command, "upload", uid)
    bucket = bucket or app.bucket or MainSequenceBucket()
    source = dict(
        uid=uid,
        filename=command.filename,
        media_type=command.media_type,
        byte_count=command.byte_count,
        content_sha256=command.content_sha256,
    )
    row = app.db.one(RUN, uid=uid)
    if row is None:
        reader = configured_reader_mode()
        if reader not in {"single", "independent_readers"}:
            fail(503, "invalid_extraction_reader_configuration")
        row = app.db.ensure(
            RUN,
            record(
                uid,
                KIND,
                dict(
                    actor_uid=app.actor,
                    reviewer_at_start=app.reviewer,
                    source=source,
                    schemas=schemas(app),
                    parser_contract_version=2,
                    reader_mode=reader,
                ),
                {"stage": "uploading", "revision": 1},
                "needs_input",
            ),
        )
    row = get(app, uid)
    if "source_object" not in row["result"]:
        reference = bucket.put(source, content)
        values = dict(
            result={
                **row["result"],
                "source_object": reference,
                "stage": "uploaded",
                "revision": 2,
            },
            status="pending",
            updated_at=now(),
        )
        row = app.db.change(
            RUN,
            {"uid": uid},
            values,
            expected={"status": "needs_input", "updated_at": row["updated_at"]},
        )
    return dispatch(app, row, dispatcher)


def start(app, command, dispatcher=None):
    if command.intake_uid:
        row = get(app, command.intake_uid)
        request_receipt(app, command, "allocate", row["uid"])
        if "source_object" not in row["result"]:
            fail(409, "intake_upload_incomplete_reselect_file")
    else:
        source = app.source(command.source_uid)
        if source["status"] != "ready":
            fail(409, "source_not_ready")
        if source["media_type"] not in {"application/pdf", "image/png", "image/jpeg"}:
            fail(422, "unsupported_processing_media_type")
        uid = stable(command.operation_key, "allocation")
        request_receipt(app, command, "allocate", uid)
        row = app.db.one(RUN, uid=uid)
        if row is None:
            row = app.db.ensure(
                RUN,
                record(
                    uid,
                    KIND,
                    dict(
                        actor_uid=app.actor,
                        reviewer_at_start=app.reviewer,
                        source=source,
                        schemas=schemas(app),
                        parser_contract_version=2,
                        reader_mode=configured_reader_mode(),
                        existing_source_uid=source["uid"],
                    ),
                    {"stage": "uploaded", "revision": 1},
                ),
            )
        row = get(app, uid)
    return dispatch(app, row, dispatcher)


def retry(app, uid, command, dispatcher=None):
    row = get(app, uid)
    if row["result"].get("stage") == "uploading":
        fail(409, "intake_upload_incomplete_reselect_file")
    request_receipt(app, command, "retry", uid)
    return dispatch(app, row, dispatcher)


def resolve(app, uid, command, dispatcher=None):
    row = get(app, uid)
    app.case(command.subject_uid)
    r = row["result"]
    if r.get("resolution_operation") == str(command.operation_key):
        request_receipt(app, command, "resolve", uid)
        return dispatch(app, row, dispatcher)
    if row["status"] != "needs_input" or r.get("stage") != "resolving_person":
        fail(409, "allocation_not_awaiting_person")
    if command.expected_revision != r.get("revision", 1):
        fail(409, "stale_allocation_revision")
    profile = app.case(command.subject_uid)["profile"]
    _, _, conflicts = identity_match(r["extraction"], profile)
    if conflicts:
        fail(422, "selected_person_conflicts_with_document")
    request_receipt(app, command, "resolve", uid)
    changed = app.db.change(
        RUN,
        {"uid": uid},
        dict(
            status="pending",
            updated_at=now(),
            result={
                **r,
                "resolved_subject_uid": str(command.subject_uid),
                "resolution_operation": str(command.operation_key),
                "revision": r.get("revision", 1) + 1,
                "error_code": None,
            },
        ),
        expected={"status": "needs_input", "updated_at": row["updated_at"]},
    )
    if changed["result"].get("resolution_operation") != str(command.operation_key):
        fail(409, "stale_allocation_revision")
    return dispatch(app, changed, dispatcher)


def requester_app(worker, row):
    """Refresh directory facts; never let a privileged Job expand a requester's scope."""
    uid = row["input_snapshot"]["actor_uid"]
    try:
        user = User.get_by_uid(uid)
        if str(user.uid) != uid or user.is_active is not True or user.blocked_access is True:
            raise ProcessingError("allocation_requester_unavailable")
        reviewers = {
            value.strip()
            for value in os.environ.get("BACKOFFICE_REVIEWER_UIDS", "").split(",")
            if value.strip()
        }
        teams = {
            value.strip()
            for value in os.environ.get("BACKOFFICE_REVIEWER_TEAM_UIDS", "").split(",")
            if value.strip()
        }
        reviewer = (
            user.is_organization_admin is True
            or uid in reviewers
            or bool(teams & {str(t) for t in user.active_team_uids or []})
        )
        reviewer = reviewer and row["input_snapshot"]["reviewer_at_start"]
        return Application(uid, reviewer=reviewer, store=worker.app.db)
    except ProcessingError:
        raise
    except Exception:
        raise ProcessingError("allocation_requester_unavailable") from None


def identity_match(extraction, person):
    """Version 1: unique cited exact name + DOB or full address; name alone is advisory."""
    payload = extraction["attributes"]
    names = [
        (k, payload[k])
        for k in (
            "full_name",
            "employee_name",
            "taxpayer_name",
            "owner_name",
            "account_holder_name",
        )
        if payload.get(k)
    ]
    names += [
        (f"account_holders/{i}", name)
        for i, name in enumerate(payload.get("account_holders") or [])
    ]
    reference = person.get("full_name") or " ".join(
        filter(None, [person.get("given_names"), person.get("last_name")])
    )
    matches = [
        (key, name)
        for key, name in names
        if reference and normalized(name) == normalized(reference)
    ]
    conflicts = bool(names and reference and not matches)
    dob = payload.get("date_of_birth")
    if dob and person.get("date_of_birth") and dob != person["date_of_birth"]:
        conflicts = True
    evidence = {f["pointer"]: f for f in extraction.get("field_evidence", [])}

    def cited(pointer):
        field = evidence.get("/" + pointer, {})
        return field.get("agreement") not in {"disagree", "missing"} and any(
            c.get("reader_id") == field.get("selected_reader_id") and c.get("locations")
            for c in field.get("candidates", [])
        )

    strong = bool(
        matches
        and any(cited(k) for k, _ in matches)
        and dob
        and dob == person.get("date_of_birth")
        and cited("date_of_birth")
    )
    for address_key in ("service_address", "holder_address"):
        address, reference_address = (
            payload.get(address_key) or {},
            person.get("residential_address") or {},
        )
        keys = ("address_line_1", "city", "postal_code", "country_code")
        if address and reference_address:
            if any(
                address.get(k)
                and reference_address.get(k)
                and normalized(address[k]) != normalized(reference_address[k])
                for k in keys
            ):
                conflicts = True
            strong |= bool(
                matches
                and any(cited(k) for k, _ in matches)
                and all(
                    address.get(k)
                    and reference_address.get(k)
                    and normalized(address[k]) == normalized(reference_address[k])
                    and cited(f"{address_key}/{k}")
                    for k in keys
                )
            )
    return bool(matches), bool(strong and not conflicts), conflicts


def find_subject(app, result):
    candidates, strong = [], []
    for offset in range(0, MAX_SUBJECTS, 100):
        page = app.list_people("", 100, offset)
        for person in page["items"]:
            match, certain, conflict = identity_match(result["extraction"], person)
            if match and not conflict:
                candidates.append(
                    {
                        "uid": person["uid"],
                        "full_name": person.get("full_name"),
                        "revision": person["revision"],
                        "corroborated": certain,
                    }
                )
                if certain:
                    strong.append(person["uid"])
        if not page["has_more"]:
            return (
                (strong[0] if len(strong) == 1 and len(candidates) == 1 else None),
                candidates[:100],
                None,
            )
    return None, candidates[:100], "subject_scan_limit_reached"


def policy_document(app, uid):
    document = app.document(uid)
    document["source_hashes"] = sorted(
        {
            app.source(ref["raw_document_uid"])["content_sha256"]
            for ref in document["raw_document_refs"]
        }
    )
    return document


def eligible(app, case_uid, document):
    snapshot = app.evaluation_input(case_uid)
    if document["uid"] in snapshot["assignment"]["document_uids"]:
        return [], "already_linked"
    if document["review_status"] == "rejected":
        return [], "document_rejected"
    # Test the evidence's potential fit without manufacturing an effective review.
    # Pending evidence can cover some, but not necessarily all, required periods/counts.
    # Assess it under the same dates, fields and deduplication rules as the new candidate.
    hypothetical = deepcopy(snapshot)
    for existing in hypothetical["documents"]:
        if existing["review_status"] != "rejected":
            existing.update(status="submitted", accepted=True, review_status="accepted")
    current, _ = reconcile(hypothetical, diagnostics=True)
    candidate = deepcopy(document)
    candidate.update(status="submitted", accepted=True, review_status="accepted")
    hypothetical["documents"].append(candidate)
    after, _ = reconcile(hypothetical, diagnostics=True)
    keys = [
        b["requirement_key"]
        for a, b in zip(current, after, strict=True)
        if a["status"] not in {"satisfied", "not_applicable"}
        and ((b["qualifying_count"] or 0) > (a["qualifying_count"] or 0))
    ]
    return keys, "useful_evidence" if keys else "no_eligible_requirement"


def source_and_child(app, worker, row, result, subject):
    inputs = row["input_snapshot"]
    source = inputs["source"]
    # Subject/content identity deduplicates repeated uploads across allocation runs.
    binding_key = stable(subject, "intake:" + source["content_sha256"])
    child_uid = stable(binding_key, "extraction")
    source_uid = inputs.get("existing_source_uid") or stable(binding_key, "source")

    def build(op, stamp):
        steps = []
        if not inputs.get("existing_source_uid"):
            steps.append(
                app.ensure_step(
                    RAW,
                    dict(
                        uid=source_uid,
                        person_uid=subject,
                        operation_key=op,
                        filename=source["filename"],
                        media_type=source["media_type"],
                        byte_count=source["byte_count"],
                        content_sha256=source["content_sha256"],
                        storage_kind="bucket",
                        bucket_name=result["source_object"]["bucket_name"],
                        artifact_uid=result["source_object"]["artifact_uid"],
                        chunk_count=0,
                        status="ready",
                        created_at=stamp,
                        finalized_at=stamp,
                    ),
                )
            )
        child = record(
            child_uid,
            "document.extract",
            dict(
                actor_uid=app.actor,
                person_uid=subject,
                source_uid=source_uid,
                source_sha256=source["content_sha256"],
                parser_contract_version=2,
                reader_mode=inputs["reader_mode"],
                schemas=inputs["schemas"],
            ),
            {
                k: result[k]
                for k in ("source_object", "classification", "classification_summary", "extraction")
            },
        )
        steps.append(app.ensure_step(RUN, child))
        return steps, {"uid": child_uid, "source_uid": source_uid}

    # The binding mutation must have a stable actor too: a second requester may reuse
    # the completed document but cannot replay another requester's intent.
    existing = app.db.one(RUN, uid=child_uid)
    binding = app.db.one(RUN, uid=binding_key)
    if binding and binding["input_snapshot"].get("actor_uid") == app.actor:
        app.resume(binding_key)
        existing = app.db.one(RUN, uid=child_uid)
    elif binding and binding["status"] != "completed":
        fail(409, "intake_binding_in_progress")
    if existing is None:
        # Prefer a pre-existing normal source/document from the same immutable bytes.
        # Never create a second logical document merely because intake is a new entry point.
        sources = app.db.rows(
            RAW,
            RAW.c.person_uid == UUID(subject),
            RAW.c.content_sha256 == source["content_sha256"],
            limit=501,
        )
        source_ids = {s["uid"] for s in sources}
        docs = app.db.rows(D, D.c.person_uid == UUID(subject), limit=501)
        if len(sources) > 500 or len(docs) > 500:
            raise ProcessingError("document_deduplication_scan_limit_reached")
        matches = []
        for saved in docs:
            doc = app.document(saved["uid"], reading=False)
            refs = doc["raw_document_refs"]
            if (
                len(refs) == 1
                and refs[0]["raw_document_uid"] in source_ids
                and not refs[0].get("first_page")
                and not refs[0].get("last_page")
                and doc["document_type"] == result["classification_summary"]["document_type"]
            ):
                matches.append(doc)
        if len(matches) > 1:
            raise ProcessingError("duplicate_document_candidates_need_review")
        if matches:
            doc = matches[0]
            return {
                "status": "completed",
                "document": {"uid": doc["uid"], "revision": doc["revision"]},
                "completion": {
                    "decision": "accepted"
                    if doc["accepted"]
                    else "rejected"
                    if doc["review_status"] == "rejected"
                    else "needs_review",
                    "reason_code": "existing_revision_reused",
                },
            }
        outcome = app.mutate(
            subject,
            BindIntake(
                operation_key=binding_key,
                subject_uid=subject,
                content_sha256=source["content_sha256"],
            ),
            "document.intake_bound",
            build,
        )
    else:
        outcome = {"uid": child_uid, "source_uid": existing["input_snapshot"]["source_uid"]}
        source_check = app.source(outcome["source_uid"], reading=False)
        if (
            source_check["person_uid"] != subject
            or source_check["content_sha256"] != source["content_sha256"]
        ):
            fail(409, "intake_binding_conflict")
    child_result = Worker(worker.app, parser=worker.parser, bucket=worker.bucket).run(
        outcome["uid"]
    )
    if child_result["status"] != "completed":
        raise ProcessingError(child_result.get("error_code") or "extraction_completion_pending")
    return child_result


def checkpoint(worker, row, result, status="running"):
    result["revision"] = result.get("revision", 1) + 1
    return worker.save(row, result, status)


def run(worker, uid):
    app = worker.app
    row = app.required(RUN, uid=uid)
    if row["status"] in {"completed", "needs_input", "cancelled"}:
        return {"uid": row["uid"], "status": row["status"], "stage": row["result"].get("stage")}
    stamp = worker.clock()
    app.db.execute(
        update(RUN)
        .where(
            RUN.c.uid == UUID(str(uid)),
            RUN.c.status.in_(["pending", "failed", "running"]),
            or_(RUN.c.lease_token.is_(None), RUN.c.lease_expires_at <= stamp),
        )
        .values(
            **typed(
                RUN,
                dict(
                    status="running",
                    lease_token=worker.token,
                    lease_expires_at=stamp + timedelta(seconds=LEASE_SECONDS),
                    updated_at=stamp,
                    attempt_count=RUN.c.attempt_count + 1,
                ),
            )
        ),
        "update",
    )
    row = app.required(RUN, uid=uid)
    if row["lease_token"] != worker.token:
        return {"uid": row["uid"], "status": row["status"], "stage": row["result"].get("stage")}
    result = deepcopy(row["result"])
    result.pop("error_code", None)
    try:
        caller = requester_app(worker, row)
        inputs, source = row["input_snapshot"], row["input_snapshot"]["source"]
        if "source_object" not in result:
            # Existing legacy source can be moved to the managed bucket without changing ownership.
            existing = caller.source(inputs["existing_source_uid"])
            result["source_object"] = (
                dict(artifact_uid=existing["artifact_uid"], bucket_name=existing["bucket_name"])
                if existing["storage_kind"] == "bucket"
                else worker.bucket.put(existing, caller.source_bytes(existing))
            )
            row = checkpoint(worker, row, result)
        content = worker.bucket.read(result["source_object"], source)
        row, result = worker.parse_source(row, result, source, content)
        if row["status"] == "needs_input":
            return view(caller, row)
        subject = (
            result.get("subject_uid")
            or result.get("resolved_subject_uid")
            or source.get("person_uid")
        )
        if subject is None:
            subject, candidates, reason = find_subject(caller, result)
            result["candidates"] = candidates
            if subject is None:
                result.update(
                    stage="resolving_person", error_code=reason or "person_identity_uncertain"
                )
                return view(caller, checkpoint(worker, row, result, "needs_input"))
        profile = caller.case(subject, reading=False)["profile"]
        _, strong, conflict = identity_match(result["extraction"], profile)
        if conflict or (
            not strong and not result.get("resolved_subject_uid") and not source.get("person_uid")
        ):
            if result.get("document"):
                result.update(stage="bound_identity_conflict", error_code="person_identity_changed")
                return view(caller, checkpoint(worker, row, result, "needs_input"))
            result.update(stage="resolving_person", error_code="person_identity_changed")
            result.pop("subject_uid", None)
            return view(caller, checkpoint(worker, row, result, "needs_input"))
        result["subject_uid"] = str(subject)
        result["subject_revision"] = profile["revision"]
        row = checkpoint(worker, row, result)
        if "document" not in result:
            worker.assert_claim(uid)
            completed = source_and_child(caller, worker, row, result, subject)
            result.update(
                document=completed["document"],
                completion=completed["completion"],
                stage="allocating",
            )
            row = checkpoint(worker, row, result)
        if "targets" not in result:
            document = policy_document(caller, result["document"]["uid"])
            cases = caller.db.rows(
                A, A.c.person_uid == UUID(subject), limit=MAX_CASES + 1, order=A.c.uid.asc()
            )
            if len(cases) > MAX_CASES:
                raise ProcessingError("case_scan_limit_reached")
            result["targets"] = []
            for case in cases:
                keys, reason = eligible(caller, case["uid"], document)
                if keys or reason == "already_linked":
                    result["targets"].append(
                        dict(case_uid=case["uid"], requirement_keys=keys, status="pending")
                    )
            row = checkpoint(worker, row, result)
        for target in result["targets"]:
            if target["status"] in {"completed", "skipped"}:
                continue
            try:
                caller = requester_app(worker, row)
                caller.case(subject, reading=False)
                worker.assert_claim(uid)
                if target.get("link_command") and caller.db.one(
                    RUN, uid=target["link_command"]["operation_key"]
                ):
                    caller.set_documents(
                        target["case_uid"], LinkCaseDocuments.model_validate(target["link_command"])
                    )
                if target.get("evaluation_command"):
                    caller.evaluate(
                        target["case_uid"],
                        EvaluateCase.model_validate(target["evaluation_command"]),
                        dispatcher=InlineDispatcher(worker),
                    )
                for _attempt in range(3):
                    case = caller.assignment(target["case_uid"])
                    if result["document"]["uid"] in case["document_uids"]:
                        break
                    document = policy_document(caller, result["document"]["uid"])
                    if document["revision"] != result["document"]["revision"]:
                        raise ProcessingError("document_revision_changed_review_required")
                    keys, reason = eligible(caller, case["uid"], document)
                    if not keys:
                        target.update(status="skipped", reason=reason)
                        break
                    body = target.get("link_command") or dict(
                        operation_key=stable(uid, f"link:{case['uid']}:{case['revision']}"),
                        case_uid=case["uid"],
                        expected_revision=case["revision"],
                        document_uids=[*case["document_uids"], result["document"]["uid"]],
                    )
                    target["link_command"] = body
                    row = checkpoint(worker, row, result)
                    try:
                        caller.set_documents(case["uid"], LinkCaseDocuments.model_validate(body))
                    except HTTPException as exc:
                        if exc.detail == "stale_assignment_revision":
                            target.pop("link_command", None)
                            continue
                        raise
                    break
                if target["status"] == "skipped":
                    row = checkpoint(worker, row, result)
                    continue
                case = caller.assignment(target["case_uid"])
                if result["document"]["uid"] not in case["document_uids"]:
                    raise ProcessingError("case_changed_retry_allocation")
                target["status"] = "evaluating"
                result["stage"] = "evaluating"
                row = checkpoint(worker, row, result)
                # Each case gets a full evaluation, including its configured comparisons.
                for _attempt in range(3):
                    snapshot = caller.evaluation_input(case["uid"])
                    fingerprint = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
                    eval_command = EvaluateCase(
                        operation_key=stable(uid, f"evaluate:{case['uid']}:{fingerprint}"),
                        case_uid=case["uid"],
                        expected_revision=snapshot["assignment"]["revision"],
                    )
                    target["evaluation_command"] = eval_command.model_dump(mode="json")
                    row = checkpoint(worker, row, result)
                    answer = caller.evaluate(
                        case["uid"], eval_command, dispatcher=InlineDispatcher(worker)
                    )
                    if answer.get("processing_run_uid"):
                        child = Worker(app, parser=worker.parser, bucket=worker.bucket).run(
                            answer["processing_run_uid"]
                        )
                        if child["status"] != "completed":
                            if child["status"] == "needs_input":
                                continue
                            raise ProcessingError(
                                child.get("error_code") or "case_evaluation_pending"
                            )
                        answer = child["evaluation"]
                    evaluation = caller.evaluation(answer["uid"])
                    if not evaluation["stale"]:
                        target.update(
                            status="completed",
                            evaluation_uid=answer["uid"],
                            summary=evaluation["summary"],
                            error_code=None,
                        )
                        break
                else:
                    raise ProcessingError("case_changed_retry_evaluation")
            except Exception as exc:
                target.update(status="failed", error_code=error_code(exc))
            row = checkpoint(worker, row, result)
        failed = any(t["status"] == "failed" for t in result["targets"])
        result["stage"] = (
            "partially_completed"
            if failed
            else ("completed" if result["targets"] else "unallocated")
        )
        return view(caller, checkpoint(worker, row, result, "failed" if failed else "completed"))
    except Exception as exc:
        result["error_code"] = error_code(exc)
        row = checkpoint(worker, row, result, "failed")
        return {
            "uid": row["uid"],
            "status": "failed",
            "stage": result.get("stage"),
            "error_code": result["error_code"],
        }


class InlineDispatcher:
    """Already inside the durable Job: execute comparisons with its fenced worker."""

    def __init__(self, worker):
        self.worker = worker

    def dispatch(self, uid):
        Worker(self.worker.app, parser=self.worker.parser, bucket=self.worker.bucket).run(uid)
        return None


def error_code(exc):
    if isinstance(exc, ProcessingError):
        return exc.code
    if isinstance(exc, ValidationError):
        return "parser_contract_invalid"
    if isinstance(exc, HTTPException):
        return "allocation_business_conflict"
    return "allocation_unavailable"

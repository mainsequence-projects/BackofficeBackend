"""Revision-aware workflows persisted exclusively through Main Sequence MetaTables.

A durable per-person intent serializes multi-request changes. Readers refuse a case
with an unfinished intent. The identical operation resumes its recorded plan after
an uncertain response; no in-memory lock or process-local database is authoritative.
"""

import base64
import binascii
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import delete, select

from ..models.person import Person
from ..policies import document_set_catalog, policy_definition
from ..schemas.drafts import get_draft_model
from ..schemas.registry import DOCUMENT_MODELS, get_document_model
from ..tables.documents import DocumentRecord, DocumentReviewRecord, DocumentRevisionRecord
from ..tables.evidence import MAX_CHUNK_BYTES, RawDocumentChunkRecord, RawDocumentRecord
from ..tables.operations import (
    AuditEventRecord,
    ProcessingRunRecord,
    ReconciliationEvaluationRecord,
    ReconciliationFindingRecord,
)
from ..tables.person import PersonRecord, PersonRevisionRecord
from ..tables.requirements import (
    AssignmentDocumentRecord,
    CaseRecord,
    DocumentSchemaRecord,
    DocumentSetVersionRecord,
)
from .storage import TABLES, Storage, wire

P, PH = PersonRecord.__table__, PersonRevisionRecord.__table__
D, DR, RV = (
    DocumentRecord.__table__,
    DocumentRevisionRecord.__table__,
    DocumentReviewRecord.__table__,
)
RAW, CHUNK = RawDocumentRecord.__table__, RawDocumentChunkRecord.__table__
A, AD = CaseRecord.__table__, AssignmentDocumentRecord.__table__
RUN, AUDIT = ProcessingRunRecord.__table__, AuditEventRecord.__table__
EV, FIND = ReconciliationEvaluationRecord.__table__, ReconciliationFindingRecord.__table__
SETS, SCHEMA = DocumentSetVersionRecord.__table__, DocumentSchemaRecord.__table__


def fail(status, code):
    raise HTTPException(status, detail=code)


def stable(key, name):
    return str(uuid5(UUID(str(key)), name))


def canonical(value):
    return json.dumps(wire(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Application:
    def __init__(
        self,
        actor_uid,
        reviewer=False,
        store=None,
        *,
        organization_admin=False,
        parsing_processor=False,
        bucket=None,
        actor_display_name=None,
    ):
        self.actor = str(UUID(str(actor_uid)))
        self.actor_display_name = actor_display_name[:240] if actor_display_name else None
        self.organization_admin = organization_admin is True
        self.parsing_processor = parsing_processor is True
        self.reviewer = reviewer or self.organization_admin
        self.db = store or Storage()
        self.bucket = bucket

    def required(self, table, **keys):
        row = self.db.one(table, **keys)
        if row is None:
            fail(404, "record_not_found")
        return row

    def case(self, person_uid, *, reading=True, processing=False):
        person = self.required(P, uid=person_uid)
        if (
            not (self.reviewer or processing and self.parsing_processor)
            and person.get("created_by") != self.actor
        ):
            fail(404, "record_not_found")
        if reading and self.db.one(RUN, uid=stable(person_uid, "case-lock")):
            fail(409, "case_operation_in_progress_retry_original_request")
        return person

    def list_people(self, search, limit, offset):
        from sqlalchemy import or_

        conditions = []
        if not self.reviewer:
            conditions.append(P.c.created_by == UUID(self.actor))
        # Search the explicit profile fields through a bounded reference-profile
        # projection; JSON extraction is compiled by SQLAlchemy for each dialect.
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                or_(
                    P.c.profile["full_name"].as_string().ilike(f"%{escaped}%", escape="\\"),
                    P.c.profile["external_reference"]
                    .as_string()
                    .ilike(f"%{escaped}%", escape="\\"),
                )
            )
        page = self.db.page(P, *conditions, limit=limit, offset=offset, order=P.c.created_at.desc())
        page["items"] = [row["profile"] for row in page["items"]]
        return page

    def list_document_sets(self, search="", limit=50, offset=0):
        conditions = [SETS.c.status == "published"]
        if search:
            from sqlalchemy import or_

            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(
                or_(
                    SETS.c.set_key.ilike(f"%{escaped}%", escape="\\"),
                    SETS.c.definition["name"].as_string().ilike(f"%{escaped}%", escape="\\"),
                )
            )
        page = self.db.page(
            SETS,
            *conditions,
            limit=limit,
            offset=offset,
            order=(SETS.c.set_key.asc(), SETS.c.version.desc()),
        )
        page["items"] = [row["definition"] for row in page["items"]]
        return page

    def document_set(self, key, version):
        policy = self.db.one(SETS, set_key=key, version=version)
        if policy is None or policy["status"] != "published":
            fail(404, "document_set_version_not_found")
        return policy["definition"]

    def list_documents(self, person_uid, limit=50, offset=0):
        self.case(person_uid)
        page = self.db.page(
            D,
            D.c.person_uid == UUID(str(person_uid)),
            limit=limit,
            offset=offset,
            order=D.c.created_at.desc(),
        )
        page["items"] = [self.document(row["uid"]) for row in page["items"]]
        return page

    def list_sources(self, person_uid, limit=50, offset=0):
        self.case(person_uid)
        return self.db.page(
            RAW,
            RAW.c.person_uid == UUID(str(person_uid)),
            limit=limit,
            offset=offset,
            order=RAW.c.created_at.desc(),
        )

    def list_evaluations(self, case_uid, limit=20, offset=0):
        self.assignment(case_uid)
        return self.db.page(
            EV,
            EV.c.assignment_uid == UUID(str(case_uid)),
            limit=limit,
            offset=offset,
            order=EV.c.created_at.desc(),
        )

    def list_assignments(self, person_uid, limit=50, offset=0):
        self.case(person_uid)
        page = self.db.page(
            A,
            A.c.person_uid == UUID(str(person_uid)),
            limit=limit,
            offset=offset,
            order=(A.c.created_at.desc(), A.c.uid.asc()),
        )

        for row in page["items"]:
            row.pop("case_type_key", None)
        return page

    def step(self, table, values, *, keys=None, expected=None):
        return {
            "table": table.name,
            "values": wire(values),
            "keys": wire(keys),
            "expected": wire(expected),
        }

    def ensure_step(self, table, values):
        return self.step(table, values)

    def mutate(
        self,
        person_uid,
        command,
        kind,
        builder,
        *,
        create=False,
        resource_type="person",
        processing=False,
    ):
        if not create:
            self.case(person_uid, reading=False, processing=processing)
        operation = str(command.operation_key)
        signature = hashlib.sha256(
            canonical(
                {
                    "kind": kind,
                    "actor": self.actor,
                    "person_uid": str(person_uid),
                    "command": command.model_dump(mode="json"),
                }
            ).encode()
        ).hexdigest()
        existing = self.db.one(RUN, uid=operation)
        if existing and existing["input_snapshot"].get("signature") != signature:
            fail(409, "operation_key_reused_with_different_request")
        lock_uid = stable(person_uid, "case-lock")
        now = datetime.now(UTC).isoformat()
        run_base = {
            "kind": kind,
            "status": "pending",
            "attempt_count": 0,
            "job_run_uid": None,
            "agent_session_uid": None,
            "inference_request_uid": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
        }
        if existing and existing["status"] == "completed":
            self.release_lock(lock_uid, operation)
            return existing["result"]
        lock = self.db.ensure(
            RUN,
            {
                **run_base,
                "uid": lock_uid,
                "operation_key": lock_uid,
                "kind": "case_lock",
                "input_snapshot": {"operation": operation, "signature": signature},
            },
        )
        if lock["input_snapshot"] != {"operation": operation, "signature": signature}:
            fail(409, "case_operation_in_progress_retry_original_request")
        if existing is None:
            try:
                steps, result = builder(operation, now)
            except Exception:
                self.release_lock(lock_uid, operation)
                raise
            event = {
                "uid": stable(operation, "audit"),
                "actor_uid": self.actor,
                "action": kind,
                "resource_type": resource_type,
                "resource_uid": str(person_uid),
                "revision": None,
                "occurred_at": now,
                "correlation_uid": operation,
                "details": {"result_uid": result.get("uid")},
            }
            steps.append(self.ensure_step(AUDIT, event))
            existing = self.db.ensure(
                RUN,
                {
                    **run_base,
                    "uid": operation,
                    "operation_key": operation,
                    "input_snapshot": {
                        "signature": signature,
                        "steps": steps,
                        "actor_uid": self.actor,
                        "person_uid": str(person_uid),
                    },
                    "result": result,
                },
            )
            if existing["input_snapshot"].get("signature") != signature:
                fail(409, "operation_key_reused_with_different_request")
        return self.finish(existing, lock_uid, operation, now)

    def finish(self, existing, lock_uid, operation, now):
        for step in existing["input_snapshot"]["steps"]:
            table = TABLES[step["table"]]
            if step["keys"] is None:
                actual = self.db.ensure(table, step["values"])
            else:
                actual = self.db.change(table, step["keys"], step["values"], step["expected"])
            if actual is None or any(actual.get(k) != v for k, v in step["values"].items()):
                fail(409, "mutation_requires_recovery_retry_original_request")
        self.db.change(RUN, {"uid": operation}, {"status": "completed", "updated_at": now})
        self.release_lock(lock_uid, operation)
        return existing["result"]

    def operation(self, uid):
        row = self.required(RUN, uid=uid)
        snapshot = row["input_snapshot"]
        if snapshot.get("actor_uid") != self.actor:
            fail(404, "record_not_found")
        if row["kind"] in {
            "document.extract",
            "document.compare",
            "document.allocate",
            "allocation.request",
        }:
            fail(409, "use_document_processing_endpoint")
        if row["kind"].startswith("admin.") and not self.organization_admin:
            fail(403, "organization_admin_required")
        if row["kind"] == "document.parsing_completed" and not (
            self.organization_admin or self.parsing_processor
        ):
            fail(403, "parsing_processor_required")
        if row["kind"] in {"document.reviewed", "case.reviewer_changed"} and not self.reviewer:
            fail(403, "reviewer_role_required")
        if self.db.one(P, uid=snapshot["person_uid"]):
            self.case(
                snapshot["person_uid"],
                reading=False,
                processing=row["kind"] == "document.parsing_completed",
            )
        return row

    def resume(self, uid):
        row = self.operation(uid)
        snapshot = row["input_snapshot"]
        lock_uid = stable(snapshot["person_uid"], "case-lock")
        if row["status"] == "completed":
            self.release_lock(lock_uid, str(uid))
            return row["result"]
        expected = {"operation": str(uid), "signature": snapshot["signature"]}
        lock = self.db.ensure(
            RUN,
            {
                **row,
                "uid": lock_uid,
                "operation_key": lock_uid,
                "kind": "case_lock",
                "status": "pending",
                "input_snapshot": expected,
                "result": None,
            },
        )
        if lock["input_snapshot"] != expected:
            fail(409, "another_case_operation_is_in_progress")
        return self.finish(row, lock_uid, str(uid), datetime.now(UTC).isoformat())

    def release_lock(self, lock_uid, operation):
        lock = self.db.one(RUN, uid=lock_uid)
        if lock and lock["input_snapshot"].get("operation") == operation:
            self.db.execute(
                delete(RUN).where(
                    RUN.c.uid == UUID(lock_uid),
                    RUN.c.input_snapshot["operation"].as_string() == operation,
                ),
                "delete",
            )

    def create_person(self, command):
        uid = stable(command.operation_key, "person")

        def build(op, now):
            profile = Person(uid=uid, revision=1, **command.profile.model_dump()).model_dump(
                mode="json"
            )
            return [
                self.ensure_step(
                    P,
                    {
                        "uid": uid,
                        "created_at": now,
                        "updated_at": now,
                        "current_revision": 1,
                        "created_by": self.actor,
                        "profile": profile,
                    },
                ),
                self.ensure_step(
                    PH,
                    {
                        "uid": stable(op, "profile"),
                        "person_uid": uid,
                        "revision": 1,
                        "profile": profile,
                        "recorded_by": self.actor,
                        "recorded_at": now,
                    },
                ),
            ], {"uid": uid, "revision": 1}

        return self.mutate(uid, command, "person.created", build, create=True)

    def update_person(self, uid, command):
        def build(op, now):
            row = self.case(uid, reading=False)
            if row["current_revision"] != command.expected_revision:
                fail(409, "stale_person_revision")
            revision = row["current_revision"] + 1
            profile = Person(uid=uid, revision=revision, **command.profile.model_dump()).model_dump(
                mode="json"
            )
            return [
                self.ensure_step(
                    PH,
                    {
                        "uid": stable(op, "profile"),
                        "person_uid": str(uid),
                        "revision": revision,
                        "profile": profile,
                        "recorded_by": self.actor,
                        "recorded_at": now,
                    },
                ),
                self.step(
                    P,
                    {"current_revision": revision, "profile": profile, "updated_at": now},
                    keys={"uid": str(uid)},
                    expected={"current_revision": command.expected_revision},
                ),
            ], {"uid": str(uid), "revision": revision}

        return self.mutate(uid, command, "person.updated", build)

    def catalog_steps(self, now):
        from ..policies.case_types import CASE_TYPES, DOCUMENT_SET_CASE_TYPES
        from .cases import BINDINGS, TYPES

        steps = [self.ensure_step(TYPES, row) for row in CASE_TYPES]
        for (kind, version), model in DOCUMENT_MODELS.items():
            pair = {
                "canonical_schema": model.model_json_schema(),
                "draft_schema": get_draft_model(kind, version).model_json_schema(),
            }
            steps.append(
                self.ensure_step(
                    SCHEMA,
                    {
                        "document_type": kind,
                        "version": version,
                        **pair,
                        "content_sha256": hashlib.sha256(canonical(pair).encode()).hexdigest(),
                        "created_at": now,
                    },
                )
            )
        for policy in document_set_catalog():
            steps.append(
                self.ensure_step(
                    SETS,
                    {
                        "set_key": policy.key,
                        "version": policy.version,
                        "definition": policy_definition(policy),
                        "status": "published",
                        "published_at": now,
                        "created_at": now,
                    },
                )
            )
        for policy in document_set_catalog():
            # No name inference: each authored policy family has an explicit business type.
            steps.append(
                self.ensure_step(
                    BINDINGS,
                    {
                        "case_type_key": DOCUMENT_SET_CASE_TYPES[policy.key],
                        "set_key": policy.key,
                        "set_version": policy.version,
                    },
                )
            )
        # Existing immutable catalog definitions retain their original timestamps.
        for step in steps:
            table = TABLES[step["table"]]
            keys = {col.name: step["values"][col.name] for col in table.primary_key}
            existing = self.db.one(table, **keys)
            if existing:
                for field in ("created_at", "published_at"):
                    if field in existing:
                        step["values"][field] = existing[field]
        return steps

    def assign(self, uid, command):
        from .cases import create

        return create(self, uid, command, legacy=True)

    def assignment(self, uid, *, reading=True, processing=False):
        row = self.required(A, uid=uid)
        self.case(row["person_uid"], reading=reading, processing=processing)
        members = self.db.rows(AD, AD.c.assignment_uid == UUID(str(uid)), limit=201)
        if len(members) > 200:
            fail(409, "assignment_document_limit_exceeded")
        # Preserve the legacy projection and frozen evaluation identity exactly.
        row.pop("case_type_key", None)
        return {**row, "document_uids": [x["document_uid"] for x in members]}

    def set_documents(self, uid, command):
        if hasattr(command, "case_uid") and str(command.case_uid) != str(uid):
            fail(422, "case_command_target_mismatch")
        assignment = self.assignment(uid, reading=False)

        def build(op, now):
            current = self.assignment(uid, reading=False)
            if current["revision"] != command.expected_revision:
                fail(409, "stale_assignment_revision")
            documents = [str(x) for x in command.document_uids]
            if len(documents) != len(set(documents)):
                fail(422, "duplicate_document_uid")
            # Membership is append-only in v1; replacement/removal needs a history stream.
            if not set(current["document_uids"]) <= set(documents):
                fail(422, "document_removal_not_supported")
            for doc in documents:
                if self.required(D, uid=doc)["person_uid"] != current["person_uid"]:
                    fail(422, "document_belongs_to_another_person")
            revision = current["revision"] + 1
            steps = [
                self.ensure_step(
                    AD,
                    {
                        "assignment_uid": str(uid),
                        "document_uid": doc,
                        "person_uid": current["person_uid"],
                    },
                )
                for doc in documents
            ]
            steps.append(
                self.step(
                    A,
                    {"revision": revision, "updated_at": now},
                    keys={"uid": str(uid)},
                    expected={"revision": current["revision"]},
                )
            )
            return steps, {"uid": str(uid), "revision": revision}

        return self.mutate(assignment["person_uid"], command, "assignment.documents_added", build)

    def source(self, uid, *, reading=True, processing=False):
        row = self.required(RAW, uid=uid)
        self.case(row["person_uid"], reading=reading, processing=processing)
        return row

    def upload(self, command):
        def build(op, now):
            uid = stable(op, "source")
            return [
                self.ensure_step(
                    RAW,
                    {
                        "uid": uid,
                        "person_uid": str(command.person_uid),
                        "operation_key": op,
                        "filename": command.filename,
                        "media_type": command.media_type,
                        "byte_count": command.byte_count,
                        "content_sha256": command.content_sha256,
                        "chunk_count": (command.byte_count + MAX_CHUNK_BYTES - 1)
                        // MAX_CHUNK_BYTES,
                        "status": "uploading",
                        "created_at": now,
                        "finalized_at": None,
                    },
                )
            ], {"uid": uid, "chunk_bytes": MAX_CHUNK_BYTES}

        return self.mutate(command.person_uid, command, "source.upload_started", build)

    def upload_status(self, uid):
        source = self.source(uid)
        result = self.db.execute(
            select(CHUNK.c.chunk_index)
            .where(CHUNK.c.raw_document_uid == UUID(str(uid)))
            .order_by(CHUNK.c.chunk_index)
            .limit(41)
        )
        return {
            **source,
            "received_chunks": [x["chunk_index"] for x in result["rows"]],
            "chunk_bytes": MAX_CHUNK_BYTES,
        }

    def put_chunk(self, uid, index, command):
        source = self.source(uid)
        if not 0 <= index < source["chunk_count"]:
            fail(422, "chunk_index_out_of_range")
        try:
            content = base64.b64decode(command.content_base64, validate=True)
        except (ValueError, binascii.Error):
            fail(422, "invalid_base64")
        expected_size = min(MAX_CHUNK_BYTES, source["byte_count"] - index * MAX_CHUNK_BYTES)
        if len(content) != expected_size:
            fail(422, "incorrect_chunk_size")
        values = {
            "raw_document_uid": str(uid),
            "chunk_index": index,
            "content_base64": command.content_base64,
            "byte_count": len(content),
            "content_sha256": hashlib.sha256(content).hexdigest(),
        }
        existing = self.db.one(CHUNK, raw_document_uid=uid, chunk_index=index)
        if existing is None:
            if source["status"] != "uploading":
                fail(409, "source_is_immutable")
            existing = self.db.ensure(CHUNK, values)
        if any(existing[k] != v for k, v in values.items()):
            fail(409, "chunk_already_contains_different_content")
        return {"chunk_index": index, "byte_count": len(content)}

    def source_bytes(self, source):
        if source.get("storage_kind") == "bucket":
            from ..processing.adapters import MainSequenceBucket

            return (self.bucket or MainSequenceBucket()).read(source, source)
        chunks = []
        for offset in range(0, source["chunk_count"], 4):
            batch = self.db.rows(
                CHUNK,
                CHUNK.c.raw_document_uid == UUID(source["uid"]),
                limit=4,
                offset=offset,
                order=CHUNK.c.chunk_index,
            )
            for chunk in batch:
                if chunk["chunk_index"] != len(chunks):
                    fail(409, "upload_incomplete")
                decoded = base64.b64decode(chunk["content_base64"], validate=True)
                if (
                    len(decoded) != chunk["byte_count"]
                    or hashlib.sha256(decoded).hexdigest() != chunk["content_sha256"]
                ):
                    fail(422, "chunk_checksum_mismatch")
                chunks.append(decoded)
        if len(chunks) != source["chunk_count"]:
            fail(409, "upload_incomplete")
        content = b"".join(chunks)
        if (
            len(content) != source["byte_count"]
            or hashlib.sha256(content).hexdigest() != source["content_sha256"]
        ):
            fail(422, "source_checksum_mismatch")
        valid = {
            "application/pdf": content.startswith(b"%PDF-"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "text/plain": b"\0" not in content,
        }
        if not valid.get(source["media_type"], False):
            fail(422, "source_media_type_mismatch")
        if source["media_type"] == "text/plain":
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                fail(422, "text_source_must_be_utf8")
        return content

    def finalize(self, uid, command):
        source = self.source(uid, reading=False)

        def build(op, now):
            current = self.source(uid, reading=False)
            self.source_bytes(current)
            return [
                self.step(
                    RAW,
                    {"status": "ready", "finalized_at": current["finalized_at"] or now},
                    keys={"uid": str(uid)},
                )
            ], {"uid": str(uid), "status": "ready"}

        return self.mutate(source["person_uid"], command, "source.finalized", build)

    def validate_refs(self, person_uid, refs):
        refs = wire(refs)
        uids = [str(x["raw_document_uid"]) for x in refs]
        if len(uids) != len(set(uids)):
            fail(422, "duplicate_source_reference")
        for uid in uids:
            source = self.required(RAW, uid=uid)
            if source["person_uid"] != str(person_uid) or source["status"] != "ready":
                fail(422, "source_must_be_ready_and_owned_by_person")
        return refs

    def document(self, uid, *, reading=True, revision_number=None, processing=False):
        row = self.required(D, uid=uid)
        self.case(row["person_uid"], reading=reading, processing=processing)
        if revision_number is None:
            revisions = self.db.rows(
                DR, DR.c.document_uid == UUID(str(uid)), limit=1, order=DR.c.revision.desc()
            )
            revision = revisions[0] if revisions else None
        else:
            if not 1 <= revision_number <= 2**31 - 1:
                fail(404, "record_not_found")
            revision = self.required(DR, document_uid=uid, revision=revision_number)
        reviews = (
            self.db.rows(
                RV,
                RV.c.document_uid == UUID(str(uid)),
                RV.c.revision == revision["revision"],
                limit=1,
                order=RV.c.decision_sequence.desc(),
            )
            if revision
            else []
        )
        review = reviews[0] if reviews else None
        from .parsing import result_view

        return {
            **row,
            "parsing_result": result_view(self, uid, revision["revision"]) if revision else None,
            "revision": revision["revision"] if revision else 0,
            "revision_created_at": revision["created_at"] if revision else None,
            "submitted_at": revision["submitted_at"] if revision else None,
            "schema_version": revision["schema_version"] if revision else 1,
            "status": revision["status"] if revision else "draft",
            "payload": revision["payload"] if revision else {},
            "raw_document_refs": revision["raw_document_refs"] if revision else [],
            "latest_review": review,
            "accepted": bool(review and review["decision"] == "accepted"),
            "review_status": review["decision"] if review else "pending",
        }

    def create_document(self, person_uid, command, *, processing=False, extraction_evidence=None):
        if processing and not (self.parsing_processor or self.organization_admin):
            fail(403, "parsing_processor_required")
        if extraction_evidence is not None and not processing:
            fail(403, "parsing_processor_required")
        if command.payload.get("document_type", command.document_type) != command.document_type:
            fail(422, "document_type_cannot_change")
        model = get_draft_model(command.document_type, command.schema_version)
        payload = model.model_validate(
            {**command.payload, "document_type": command.document_type}
        ).model_dump(mode="json", exclude_unset=True)
        if processing:
            from .source_references import bind_portrait_source

            payload = bind_portrait_source(
                payload, [ref.model_dump(mode="json") for ref in command.raw_document_refs]
            )

        def build(op, now):
            uid = stable(op, "document")
            refs = self.validate_refs(person_uid, command.raw_document_refs)
            from .extraction_evidence import evidence_steps

            snapshot, field_steps = evidence_steps(
                self, extraction_evidence, person_uid, command, op, now, refs
            )
            return [
                self.ensure_step(
                    D,
                    {
                        "uid": uid,
                        "person_uid": str(person_uid),
                        "document_type": command.document_type,
                        "current_revision": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ),
                self.ensure_step(
                    DR,
                    {
                        "uid": stable(op, "revision"),
                        "document_uid": uid,
                        "person_uid": str(person_uid),
                        "document_type": command.document_type,
                        "revision": 1,
                        "schema_version": command.schema_version,
                        "payload": payload,
                        "extraction_evidence": snapshot,
                        "raw_document_refs": refs,
                        "status": "draft",
                        "created_by": self.actor,
                        "created_at": now,
                        "submitted_at": None,
                    },
                ),
            ] + field_steps, {"uid": uid, "revision": 1}

        return self.mutate(person_uid, command, "document.created", build, processing=processing)

    def save_draft(self, uid, command):
        document = self.document(uid, reading=False)

        def build(op, now):
            current = self.document(uid, reading=False)
            if current["revision"] != command.expected_revision:
                fail(409, "stale_document_revision")
            if (
                command.payload.get("document_type", current["document_type"])
                != current["document_type"]
            ):
                fail(422, "document_type_cannot_change")
            payload = (
                get_draft_model(current["document_type"], current["schema_version"])
                .model_validate({**command.payload, "document_type": current["document_type"]})
                .model_dump(mode="json", exclude_unset=True)
            )
            refs = self.validate_refs(current["person_uid"], command.raw_document_refs)
            revision = current["revision"] + 1
            return [
                self.ensure_step(
                    DR,
                    {
                        "uid": stable(op, "revision"),
                        "document_uid": str(uid),
                        "person_uid": current["person_uid"],
                        "document_type": current["document_type"],
                        "revision": revision,
                        "schema_version": current["schema_version"],
                        "payload": payload,
                        "raw_document_refs": refs,
                        "status": "draft",
                        "created_by": self.actor,
                        "created_at": now,
                        "submitted_at": None,
                    },
                ),
                self.step(
                    D,
                    {"updated_at": now},
                    keys={"uid": str(uid)},
                    expected={"updated_at": current["updated_at"]},
                ),
            ], {"uid": str(uid), "revision": revision}

        return self.mutate(document["person_uid"], command, "document.draft_saved", build)

    def submit(self, uid, command):
        document = self.document(uid, reading=False)

        def build(op, now):
            current = self.document(uid, reading=False)
            if current["revision"] != command.expected_revision or current["status"] != "draft":
                fail(409, "stale_or_already_submitted_revision")
            get_document_model(current["document_type"], current["schema_version"]).model_validate(
                current["payload"]
            )
            if not current["raw_document_refs"]:
                fail(422, "raw_source_required")
            self.validate_refs(current["person_uid"], current["raw_document_refs"])
            return [
                self.step(
                    DR,
                    {"status": "submitted", "submitted_at": now},
                    keys={"document_uid": str(uid), "revision": current["revision"]},
                    expected={"status": "draft"},
                ),
                self.step(
                    D,
                    {"current_revision": current["revision"], "updated_at": now},
                    keys={"uid": str(uid)},
                    expected={
                        "current_revision": current["current_revision"],
                        "updated_at": current["updated_at"],
                    },
                ),
            ], {"uid": str(uid), "revision": current["revision"], "status": "submitted"}

        return self.mutate(document["person_uid"], command, "document.submitted", build)

    def parsing_settings(self, document_type):
        from .parsing import settings

        return settings(self, document_type)

    def update_parsing_settings(self, command):
        from .parsing import update_settings

        return update_settings(self, command)

    def complete_parsing(self, uid, command):
        from .parsing import complete

        return complete(self, uid, command)

    def review(self, uid, command):
        if not self.reviewer:
            fail(403, "reviewer_role_required")
        document = self.document(uid, reading=False)

        def build(op, now):
            current = self.document(uid, reading=False)
            if current["revision"] != command.expected_revision or current["status"] != "submitted":
                fail(409, "review_requires_current_submitted_revision")
            sequence = (current["latest_review"] or {}).get("decision_sequence", 0)
            if sequence != command.expected_decision_sequence:
                fail(409, "stale_review_decision")
            review_uid = stable(op, "review")
            return [
                self.ensure_step(
                    RV,
                    {
                        "uid": review_uid,
                        "document_uid": str(uid),
                        "revision": current["revision"],
                        "decision_sequence": sequence + 1,
                        "decision": command.decision,
                        "reason": command.reason,
                        "reviewed_by": self.actor,
                        "reviewed_at": now,
                        "operation_key": op,
                    },
                )
            ], {
                "uid": review_uid,
                "document_uid": str(uid),
                "revision": current["revision"],
                "decision_sequence": sequence + 1,
            }

        return self.mutate(document["person_uid"], command, "document.reviewed", build)

    def evaluation_input(self, assignment_uid, *, processing=False):
        assignment = self.assignment(assignment_uid, reading=False, processing=processing)
        person = self.case(assignment["person_uid"], reading=False, processing=processing)[
            "profile"
        ]
        policy = self.required(
            SETS, set_key=assignment["set_key"], version=assignment["set_version"]
        )["definition"]
        documents = [
            self.document(uid, reading=False, processing=processing)
            for uid in sorted(assignment["document_uids"])
        ]
        for document in documents:
            if policy.get("comparisons"):
                revision = self.required(
                    DR, document_uid=document["uid"], revision=document["revision"]
                )
                document["extraction_evidence"] = revision.get("extraction_evidence")
            document["source_hashes"] = sorted(
                {
                    self.required(RAW, uid=ref["raw_document_uid"])["content_sha256"]
                    for ref in document["raw_document_refs"]
                }
            )
        return {
            "person": person,
            "assignment": assignment,
            "policy": policy,
            "documents": documents,
            "evaluation_date": datetime.now(UTC).date().isoformat(),
            "evaluator_version": "3" if policy.get("comparisons") else "2",
        }

    def current_status(self, uid):
        """Reevaluate a stable snapshot without writing a retained evaluation."""
        from .queries import AssignmentStatus
        from .reconciliation import reconcile

        assignment = self.assignment(uid)
        snapshot = self.evaluation_input(uid)
        input_identity = canonical(snapshot)
        if snapshot["policy"].get("comparisons"):
            previous = self.db.rows(
                EV, EV.c.assignment_uid == UUID(str(uid)), limit=1, order=EV.c.created_at.desc()
            )
            if previous:
                retained = previous[0]["input_snapshot"]
                if (
                    canonical({k: v for k, v in retained.items() if k != "comparison_result"})
                    == input_identity
                ):
                    snapshot["comparison_result"] = retained.get("comparison_result")
        findings, summary = reconcile(snapshot, diagnostics=True)
        # Revision/review/source inputs are immutable or monotonically versioned.
        # Two equal collections plus lock admission detect an intervening mutation.
        self.case(assignment["person_uid"])
        if input_identity != canonical(self.evaluation_input(uid)):
            fail(409, "assessment_inputs_changed_retry_query")
        self.case(assignment["person_uid"])
        return AssignmentStatus(
            person_uid=assignment["person_uid"],
            person_revision=snapshot["person"]["revision"],
            assignment_uid=str(uid),
            assignment_revision=snapshot["assignment"]["revision"],
            set_key=snapshot["assignment"]["set_key"],
            set_version=snapshot["assignment"]["set_version"],
            evaluator_version=snapshot["evaluator_version"],
            assessed_at=datetime.now(UTC),
            findings=findings,
            summary=summary,
            scope="Only documents explicitly linked to this assignment; all requirements included.",
        ).model_dump(mode="json")

    def missing_requirements(self, uid):
        from .queries import MissingRequirements

        status = self.current_status(uid)
        findings = status["findings"]
        outstanding = [x for x in findings if x["status"] not in {"satisfied", "not_applicable"}]
        return MissingRequirements(
            **{
                **status,
                "findings": outstanding,
                "scope": "Only documents explicitly linked to this assignment; outstanding requirements only, including optional requirements.",
            },
            total_requirements=len(findings),
            outstanding_requirements=len(outstanding),
        ).model_dump(mode="json")

    def evaluate(self, uid, command, *, dispatcher=None, processing=False, comparison_run=None):
        from .reconciliation import reconcile

        if hasattr(command, "case_uid") and str(command.case_uid) != str(uid):
            fail(422, "case_command_target_mismatch")
        if processing and not (self.parsing_processor or self.organization_admin):
            fail(403, "parsing_processor_required")
        if comparison_run is not None and not processing:
            fail(403, "parsing_processor_required")
        assignment = self.assignment(uid, reading=False, processing=processing)
        policy = self.required(
            SETS, set_key=assignment["set_key"], version=assignment["set_version"]
        )["definition"]
        if policy.get("comparisons") and comparison_run is None:
            from ..processing.comparisons import start

            return start(self, uid, command, dispatcher)

        def build(op, now):
            snapshot = self.evaluation_input(uid, processing=processing)
            if comparison_run is not None:
                run = self.required(RUN, uid=comparison_run)
                if (
                    run["kind"] != "document.compare"
                    or run["input_snapshot"]["assignment_uid"] != str(uid)
                    or run["input_snapshot"]["evaluation_command"]
                    != command.model_dump(mode="json")
                    or run["result"].get("executor_uid") != self.actor
                ):
                    fail(422, "comparison_run_identity_mismatch")
                if canonical(snapshot) != canonical(run["input_snapshot"]["evaluation_input"]):
                    fail(409, "comparison_inputs_changed_start_new_evaluation")
                snapshot["comparison_result"] = run["result"].get("comparison_response")
            if snapshot["assignment"]["revision"] != command.expected_revision:
                fail(409, "stale_assignment_revision")
            findings, summary = reconcile(snapshot)
            evaluation_uid = stable(op, "evaluation")
            row = {
                "uid": evaluation_uid,
                "assignment_uid": str(uid),
                "person_uid": assignment["person_uid"],
                "person_revision": snapshot["person"]["revision"],
                "assignment_revision": snapshot["assignment"]["revision"],
                "set_key": assignment["set_key"],
                "set_version": assignment["set_version"],
                "input_snapshot": snapshot,
                "status": "completed",
                "summary": summary,
                "operation_key": op,
                "created_at": now,
                "completed_at": now,
            }
            return [
                self.ensure_step(EV, row),
                *[
                    self.ensure_step(
                        FIND,
                        {
                            "uid": stable(op, f"finding:{i}"),
                            "evaluation_uid": evaluation_uid,
                            **finding,
                        },
                    )
                    for i, finding in enumerate(findings)
                ],
            ], {"uid": evaluation_uid, "summary": summary}

        return self.mutate(
            assignment["person_uid"], command, "assignment.evaluated", build, processing=processing
        )

    def evaluation(self, uid):
        row = self.required(EV, uid=uid)
        self.case(row["person_uid"])
        current = self.evaluation_input(row["assignment_uid"])
        row["stale"] = canonical(current) != canonical(
            {k: v for k, v in row["input_snapshot"].items() if k != "comparison_result"}
        )
        row["findings"] = self.db.rows(FIND, FIND.c.evaluation_uid == UUID(str(uid)), limit=100)
        return row


def publish_catalog(store=None):
    """Explicit migration-Job bootstrap of immutable authored forms and policy."""
    service = Application(UUID(int=0), store=store)
    for step in service.catalog_steps(datetime.now(UTC).isoformat()):
        actual = service.db.ensure(TABLES[step["table"]], step["values"])
        if any(actual.get(key) != value for key, value in step["values"].items()):
            raise RuntimeError("Published catalog differs from the authored immutable contract")

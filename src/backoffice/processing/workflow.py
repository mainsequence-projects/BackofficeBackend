"""Durable extraction stages. External I/O never holds a person mutation lock."""

import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, ValidationError
from sqlalchemy import or_, update

from ..schemas.drafts import get_draft_model
from ..schemas.registry import DOCUMENT_MODELS
from ..services.application import RAW, RUN, SCHEMA, fail, stable
from ..services.contracts import Command, CompleteParsing, CreateDocument, StartUpload
from ..services.parsing_confidence import document_classification
from ..services.storage import typed
from .classification_hints import classifier_description
from .adapters import (
    MainSequenceBucket,
    MainSequenceDispatcher,
    ParsingMotor,
    ProcessingError,
    inspect_source,
)
from .contracts import (
    MAX_BYTES,
    Candidate,
    ClassificationResponse,
    ClassifyRequest,
    ExtractionResponse,
    ExtractRequest,
    ParserFile,
)
from .evidence_contracts import (
    ClassificationResponseV2,
    ClassifyRequestV2,
    ExtractionResponseV2,
    ExtractRequestV2,
)

KIND = "document.extract"
LEASE_SECONDS = 1800  # Longer than the bounded 1200-second Job; expired workers are fenced.


class ProcessCommand(Command):
    source_uid: UUID


class RetryCommand(Command):
    run_uid: UUID


class BucketUpload(StartUpload):
    # Keep the existing chunk-upload contract's 10 MiB limit unchanged.
    byte_count: int = Field(gt=0, le=MAX_BYTES)


def upload(app, command, content, bucket=None):
    app.case(command.person_uid, reading=False)
    if (
        len(content) != command.byte_count
        or hashlib.sha256(content).hexdigest() != command.content_sha256
    ):
        fail(422, "source_checksum_mismatch")
    inspect_source(content, command.media_type)
    bucket = bucket or app.bucket or MainSequenceBucket()

    def build(op, now):
        uid = stable(op, "source")
        row = dict(
            uid=uid,
            person_uid=str(command.person_uid),
            operation_key=op,
            filename=command.filename,
            media_type=command.media_type,
            byte_count=command.byte_count,
            content_sha256=command.content_sha256,
            storage_kind="bucket",
            bucket_name=bucket.name,
            artifact_uid=None,
            chunk_count=0,
            status="uploading",
            created_at=now,
            finalized_at=None,
        )
        return [app.ensure_step(RAW, row)], {"uid": uid}

    created = app.mutate(command.person_uid, command, "source.bucket_upload_started", build)
    source = app.source(created["uid"], reading=False)
    if source["status"] == "ready":
        # The source write can survive a lost response while finalization still
        # owns the case lock. Always replay that intent before returning ready.
        reference = {"artifact_uid": source["artifact_uid"]}
    else:
        if source["bucket_name"] != bucket.name:
            fail(409, "upload_bucket_configuration_changed")
        reference = bucket.put(source, content)

    def finalize(op, now):
        return [
            app.step(
                RAW,
                {"artifact_uid": reference["artifact_uid"], "status": "ready", "finalized_at": now},
                keys={"uid": source["uid"]},
                expected={"status": "uploading"},
            )
        ], {"uid": source["uid"], "status": "ready"}

    return app.mutate(
        command.person_uid,
        Command(operation_key=stable(command.operation_key, "bucket-finalize")),
        "source.bucket_finalized",
        finalize,
    )


def get_run(app, uid):
    row = app.required(RUN, uid=uid)
    if row["kind"] not in {KIND, "document.compare"}:
        fail(404, "processing_run_not_found")
    app.case(row["input_snapshot"]["person_uid"], reading=False)
    if row["input_snapshot"]["actor_uid"] != app.actor and not app.reviewer:
        fail(404, "processing_run_not_found")
    return row


def view(row):
    result = row["result"] or {}
    if row["kind"] == "document.compare":
        return {
            "uid": row["uid"],
            "kind": row["kind"],
            "assignment_uid": row["input_snapshot"]["assignment_uid"],
            "status": row["status"],
            "stage": result.get("stage", "pending"),
            "attempt_count": row["attempt_count"],
            "error_code": result.get("error_code"),
            "evaluation": result.get("evaluation"),
        }
    confidence = result.get("classification_summary") or {}
    return {
        "uid": row["uid"],
        "source_uid": row["input_snapshot"]["source_uid"],
        "status": row["status"],
        "stage": result.get("stage", "pending"),
        "attempt_count": row["attempt_count"],
        "error_code": result.get("error_code"),
        "document_type": confidence.get("document_type"),
        "classification_confidence_percent": confidence.get("classification_confidence_percent"),
        "document": result.get("document"),
        "completion": result.get("completion"),
    }


def dispatch(app, row, dispatcher=None):
    if row["status"] in {"completed", "needs_input"}:
        return view(row)
    try:
        job_uid = (dispatcher or MainSequenceDispatcher()).dispatch(row["uid"])
        if job_uid:
            # Scheduling may deliver more than once after a lost response. Worker claims dedupe it.
            app.db.change(RUN, {"uid": row["uid"]}, {"job_run_uid": str(UUID(job_uid))})
    except (ProcessingError, ValueError):
        return {**view(row), "dispatch_error": "processing_dispatch_unavailable"}
    return view(app.required(RUN, uid=row["uid"]))


def start(app, source_uid, command, dispatcher=None):
    source = app.source(source_uid, reading=False)
    if source["status"] != "ready":
        fail(409, "source_not_ready")
    if source["media_type"] not in {"application/pdf", "image/png", "image/jpeg"}:
        fail(422, "unsupported_processing_media_type")

    def build(op, now):
        reader_mode = configured_reader_mode()
        if reader_mode not in {"single", "independent_readers"}:
            fail(503, "invalid_extraction_reader_configuration")
        schemas = {}
        # Pin the full published canonical/draft pair before any provider is called.
        for kind, version in DOCUMENT_MODELS:
            if kind in schemas and schemas[kind]["version"] >= version:
                continue
            schema = app.required(SCHEMA, document_type=kind, version=version)
            schemas[kind] = {
                k: schema[k]
                for k in (
                    "document_type",
                    "version",
                    "canonical_schema",
                    "draft_schema",
                    "content_sha256",
                )
            }
        uid = stable(op, "extraction")
        row = dict(
            uid=uid,
            operation_key=uid,
            kind=KIND,
            status="pending",
            attempt_count=0,
            job_run_uid=None,
            agent_session_uid=None,
            inference_request_uid=None,
            created_at=now,
            updated_at=now,
            lease_token=None,
            lease_expires_at=None,
            input_snapshot={
                "actor_uid": app.actor,
                "person_uid": source["person_uid"],
                "source_uid": source["uid"],
                "source_sha256": source["content_sha256"],
                "parser_contract_version": 2,
                "reader_mode": reader_mode,
                "schemas": schemas,
            },
            result={"stage": "pending"},
        )
        return [app.ensure_step(RUN, row)], {"uid": uid}

    outcome = app.mutate(
        source["person_uid"],
        ProcessCommand(operation_key=command.operation_key, source_uid=source_uid),
        "document.processing_requested",
        build,
    )
    return dispatch(app, get_run(app, outcome["uid"]), dispatcher)


def retry(app, uid, command, dispatcher=None):
    row = get_run(app, uid)
    if row["status"] == "needs_input":
        fail(
            409,
            "comparison_inputs_changed_start_new_evaluation"
            if row["kind"] == "document.compare"
            else "processing_requires_a_single_supported_document",
        )
    # Authorization above is case-scoped. Serialize the retry audit on the run,
    # not the case: a crashed worker may still own a recoverable business intent
    # and must be dispatchable to finish that exact intent and release its lock.
    app.mutate(
        row["uid"],
        RetryCommand(operation_key=command.operation_key, run_uid=uid),
        "document.processing_retried",
        lambda op, now: ([], {"uid": row["uid"]}),
        create=True,
        resource_type="processing_run",
    )
    return dispatch(app, row, dispatcher)


def validate_pages(pages, source, filename, page_count):
    actual = [(p.source_file, p.page) for p in pages]
    expected = {(filename, page) for page in range(1, page_count + 1)}
    if (
        len(actual) != len(set(actual))
        or set(actual) != expected
        or any(p.source_sha256 != source["content_sha256"] for p in pages)
    ):
        raise ProcessingError("parser_source_manifest_mismatch")
    return expected


# The parser pairs a vision reader with Textract (own confidence and boxes, a different failure
# mode); one reader is the development fallback. Override with BACKOFFICE_EXTRACTION_READER_MODE.
DEFAULT_READER_MODE = "independent_readers"


def configured_reader_mode() -> str:
    return os.environ.get("BACKOFFICE_EXTRACTION_READER_MODE", DEFAULT_READER_MODE)


def validate_reader_strategy(response, snapshot):
    if (
        snapshot.get("parser_contract_version") == 2
        and snapshot.get("reader_mode") == "independent_readers"
    ):
        if any(
            len(field.candidates) < 2 or len({c.model for c in field.candidates}) < 2
            for field in response.field_evidence
        ):
            raise ProcessingError("parser_reader_strategy_mismatch")


class Worker:
    def __init__(self, app, *, parser=None, bucket=None, clock=None):
        if not (app.parsing_processor or app.organization_admin):
            fail(403, "parsing_processor_required")
        self.app = app
        self.parser = parser or ParsingMotor()
        self.bucket = bucket or app.bucket or MainSequenceBucket()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.token = str(uuid4())

    def save(self, row, result, status="running"):
        now = self.clock()
        values = {
            "result": result,
            "status": status,
            "updated_at": now.isoformat(),
            "lease_expires_at": (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
            if status == "running"
            else None,
            "lease_token": self.token if status == "running" else None,
        }
        self.app.db.execute(
            update(RUN)
            .where(
                RUN.c.uid == UUID(row["uid"]),
                RUN.c.lease_token == UUID(self.token),
                RUN.c.status == "running",
                RUN.c.lease_expires_at > now,
            )
            .values(**typed(RUN, values)),
            "update",
        )
        actual = self.app.db.one(RUN, uid=row["uid"])
        if actual is None or any(actual.get(k) != v for k, v in values.items()):
            raise ProcessingError("processing_lease_lost")
        return actual

    def assert_claim(self, uid):
        row = self.app.required(RUN, uid=uid)
        if (
            row["lease_token"] != self.token
            or row["status"] != "running"
            or datetime.fromisoformat(row["lease_expires_at"]) <= self.clock()
        ):
            raise ProcessingError("processing_lease_lost")

    def parse_source(self, row, result, source, content):
        """Parse a verified original before or after subject binding, retaining checkpoints."""
        count = inspect_source(content, source["media_type"])
        suffix = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}[
            source["media_type"]
        ]
        filename = f"source-{source['uid']}.{suffix}"
        file = ParserFile(filename=filename, content_base64=base64.b64encode(content).decode())
        schemas = row["input_snapshot"]["schemas"]
        version = row["input_snapshot"].get("parser_contract_version", 1)
        if version not in (1, 2):
            raise ProcessingError("unsupported_parser_contract_version")
        classify_request = ClassifyRequestV2 if version == 2 else ClassifyRequest
        extract_request = ExtractRequestV2 if version == 2 else ExtractRequest
        classify_response = ClassificationResponseV2 if version == 2 else ClassificationResponse
        extract_response = ExtractionResponseV2 if version == 2 else ExtractionResponse
        version_args = {"contract_version": 2} if version == 2 else {}
        if "classification" not in result:
            result["stage"] = "classifying"
            row = self.save(row, result)
            response = self.parser.classify(
                classify_request(
                    **version_args,
                    files=[file],
                    document_types=[
                        Candidate(
                            document_type=k,
                            description=classifier_description(k, v["canonical_schema"]),
                        )
                        for k, v in schemas.items()
                    ],
                )
            )
            response = classify_response.model_validate(response)
            expected = validate_pages(response.pages, source, filename, count)
            classified = document_classification(
                [p.model_dump() for p in response.pages], expected_pages=expected
            )
            result.update(
                classification=response.model_dump(mode="json"),
                classification_summary=classified.model_dump(mode="json"),
                stage="classified",
            )
            row = self.save(row, result)
        # Checkpoint recovery revalidates retained responses before using their observations.
        retained_classification = classify_response.model_validate(result["classification"])
        if version == 2 and (
            sum(p.boundary == "starts_document" for p in retained_classification.pages) > 1
            or len({p.group_hint for p in retained_classification.pages if p.group_hint}) > 1
        ):
            result["error_code"] = "multiple_documents_require_grouping"
            return self.save(row, result, "needs_input"), result
        classification = result["classification_summary"]
        kind = classification["document_type"]
        if kind is None or kind not in schemas:
            result["error_code"] = classification["reason_code"]
            return self.save(row, result, "needs_input"), result
        schema = schemas[kind]
        if "extraction" not in result:
            result["stage"] = "extracting"
            row = self.save(row, result)
            response = self.parser.extract(
                extract_request(
                    **(
                        {
                            **version_args,
                            "reader_mode": row["input_snapshot"].get("reader_mode", "single"),
                        }
                        if version == 2
                        else {}
                    ),
                    files=[file],
                    document_type=kind,
                    schema_version=schema["version"],
                    schema_hash=schema["content_sha256"],
                    canonical_schema=schema["canonical_schema"],
                    output_schema=schema["draft_schema"],
                )
            )
            response = extract_response.model_validate(response)
            validate_pages(response.pages, source, filename, count)
            if (response.document_type, response.schema_version, response.schema_hash) != (
                kind,
                schema["version"],
                schema["content_sha256"],
            ):
                raise ProcessingError("parser_schema_identity_mismatch")
            if {p.page: p.page_sha256 for p in response.pages} != {
                p["page"]: p["page_sha256"] for p in result["classification"]["pages"]
            }:
                raise ProcessingError("parser_page_content_mismatch")
            if response.attributes.get("document_type", kind) != kind:
                raise ProcessingError("parser_attribute_type_mismatch")
            get_draft_model(kind, schema["version"]).model_validate(
                {**response.attributes, "document_type": kind}
            )
            validate_reader_strategy(response, row["input_snapshot"])
            result.update(extraction=response.model_dump(mode="json"), stage="extracted")
            row = self.save(row, result)
        retained_extraction = extract_response.model_validate(result["extraction"])
        validate_reader_strategy(retained_extraction, row["input_snapshot"])
        return row, result

    def run(self, uid):
        app = self.app
        row = app.required(RUN, uid=uid)
        if row["kind"] == "document.allocate":
            from .allocation import run

            return run(self, uid)
        if row["kind"] not in {KIND, "document.compare"}:
            fail(404, "processing_run_not_found")
        app.case(row["input_snapshot"]["person_uid"], reading=False, processing=True)
        if row["status"] in {"completed", "needs_input", "cancelled"}:
            return view(row)
        now = self.clock()
        app.db.execute(
            update(RUN)
            .where(
                RUN.c.uid == UUID(str(uid)),
                RUN.c.status.in_(["pending", "failed", "running"]),
                or_(RUN.c.lease_token.is_(None), RUN.c.lease_expires_at <= now),
            )
            .values(
                status="running",
                lease_token=UUID(self.token),
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
                attempt_count=RUN.c.attempt_count + 1,
                updated_at=now,
            ),
            "update",
        )
        row = app.required(RUN, uid=uid)
        if row["lease_token"] != self.token:
            return view(row)
        result = dict(row["result"] or {})
        result.pop("error_code", None)
        if result.get("executor_uid", app.actor) != app.actor:
            return view(
                self.save(row, {**result, "error_code": "processing_executor_changed"}, "failed")
            )
        result["executor_uid"] = app.actor
        try:
            row = self.save(row, result)
            if row["kind"] == "document.compare":
                from .comparisons import run

                return run(self, row, result)
            source = app.source(row["input_snapshot"]["source_uid"], reading=False, processing=True)
            if (
                source["status"] != "ready"
                or source["content_sha256"] != row["input_snapshot"]["source_sha256"]
            ):
                raise ProcessingError("processing_source_changed")
            if "source_object" not in result:
                if source.get("storage_kind") == "bucket":
                    reference = {
                        "artifact_uid": source["artifact_uid"],
                        "bucket_name": source["bucket_name"],
                    }
                else:
                    reference = self.bucket.put(source, app.source_bytes(source))
                result.update(source_object=reference, stage="uploaded")
                row = self.save(row, result)
            content = self.bucket.read(result["source_object"], source)
            row, result = self.parse_source(row, result, source, content)
            if row["status"] == "needs_input":
                return view(row)
            classification = result["classification_summary"]
            kind = classification["document_type"]
            schema = row["input_snapshot"]["schemas"][kind]
            version = row["input_snapshot"].get("parser_contract_version", 1)
            if "document" not in result:
                self.assert_claim(uid)
                result["document"] = app.create_document(
                    source["person_uid"],
                    CreateDocument(
                        operation_key=stable(uid, "draft"),
                        document_type=kind,
                        schema_version=schema["version"],
                        payload=result["extraction"]["attributes"],
                        raw_document_refs=[{"raw_document_uid": source["uid"]}],
                    ),
                    processing=True,
                    extraction_evidence={
                        "run_uid": str(uid),
                        "classification": result["classification"],
                        "extraction": result["extraction"],
                    }
                    if version == 2
                    else None,
                )
                result["stage"] = "persisted"
                row = self.save(row, result)
            if "completion" not in result:
                self.assert_claim(uid)
                result["completion"] = app.complete_parsing(
                    result["document"]["uid"],
                    CompleteParsing(
                        operation_key=stable(uid, "acceptance"),
                        expected_revision=result["document"]["revision"],
                        parsing_score_percent=classification["classification_confidence_percent"],
                        extractor=result["extraction"]["model"][:120],
                    ),
                )
                result["stage"] = "completed"
            return view(self.save(row, result, "completed"))
        except Exception as error:
            if isinstance(error, ProcessingError):
                code = error.code
            elif isinstance(error, ValidationError):
                code = "parser_contract_invalid"
            elif isinstance(error, HTTPException):
                code = "processing_business_conflict"
            else:
                code = "processing_unavailable"
            result["error_code"] = code
            # Save only provider responses already validated above; never persist exception text.
            return view(self.save(row, result, "failed"))


def upload_and_start(app, command, content, *, bucket=None, dispatcher=None):
    source = upload(app, command, content, bucket)
    return start(
        app,
        source["uid"],
        Command(operation_key=stable(command.operation_key, "process")),
        dispatcher,
    )

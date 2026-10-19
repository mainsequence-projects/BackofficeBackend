"""Full HTTP -> private bucket -> parser -> canonical revision -> acceptance flow."""

import base64
import hashlib
import io
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from PIL import Image

from api.app.main import processing_bucket, processing_dispatcher
from src.backoffice.processing import workflow
from src.backoffice.processing.adapters import ProcessingError
from src.backoffice.processing.contracts import ClassificationResponse, ExtractionResponse
from src.backoffice.processing.evidence_contracts import (
    ClassificationResponseV2,
    ExtractionResponseV2,
)
from src.backoffice.services.application import RAW, RUN, Application, D
from src.backoffice.services.contracts import Command
from src.backoffice.tables.parsing import ParsingResultRecord
from tests.api.test_parsing_admin import policy
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person


class Bucket:
    name = "backoffice-documents"

    def __init__(self):
        self.files = {}
        self.calls = 0
        self.lose_response = False

    def put(self, source, content):
        self.calls += 1
        uid = source["uid"]
        assert self.files.get(uid, content) == content
        self.files[uid] = content
        if self.lose_response:
            self.lose_response = False
            raise ProcessingError("bucket_upload_unavailable")
        return {"artifact_uid": uid, "bucket_name": self.name}

    def read(self, reference, source):
        content = self.files[reference["artifact_uid"]]
        if hashlib.sha256(content).hexdigest() != source["content_sha256"]:
            raise ProcessingError("bucket_checksum_mismatch")
        return content


class Dispatcher:
    def __init__(self):
        self.calls = []
        self.fail = False

    def dispatch(self, uid):
        self.calls.append(uid)
        if self.fail:
            raise ProcessingError("processing_dispatch_unavailable")
        return str(uuid4())


class Parser:
    def __init__(self, payload, confidence=0.6, kind="passport"):
        self.payload, self.confidence, self.kind = payload, confidence, kind
        self.classifications, self.extractions = [], []
        self.bad_hash = False
        self.bad_source = False
        self.fail_extraction = False

    def pages(self, request):
        file = request.files[0]
        return [
            {
                "source_file": file.filename,
                "page": 1,
                "source_sha256": "0" * 64
                if self.bad_source
                else hashlib.sha256(base64.b64decode(file.content_base64)).hexdigest(),
                "page_sha256": "1" * 64,
            }
        ]

    def classify(self, request):
        self.classifications.append(request)
        response = (
            ClassificationResponseV2
            if getattr(request, "contract_version", 1) == 2
            else ClassificationResponse
        )
        return response(
            **({"contract_version": 2} if response is ClassificationResponseV2 else {}),
            pages=[
                {
                    **self.pages(request)[0],
                    "document_type": self.kind,
                    "confidence": self.confidence,
                    "reason": "fixture",
                    "model": "classifier-v1",
                    "cache_hit": False,
                }
            ],
        )

    def extract(self, request):
        self.extractions.append(request)
        if self.fail_extraction:
            raise RuntimeError("API-KEY-private-unsafe-provider-text")
        response = (
            ExtractionResponseV2
            if getattr(request, "contract_version", 1) == 2
            else ExtractionResponse
        )
        extra = {}
        if response is ExtractionResponseV2:
            from tests.services.test_extraction_persistence import fixture_evidence

            extra = fixture_evidence(self.payload, request.files[0].filename)
            if request.reader_mode == "independent_readers":
                for field in extra["field_evidence"]:
                    field["candidates"].append(
                        {
                            **field["candidates"][0],
                            "reader_id": "secondary",
                            "model": "second-fixture",
                        }
                    )
                    if field["agreement"] == "single_reader":
                        field["agreement"] = "agree"
        return response(
            **extra,
            document_type=request.document_type,
            schema_version=request.schema_version,
            schema_hash="0" * 64 if self.bad_hash else request.schema_hash,
            status="draft",
            attributes=self.payload,
            canonical_schema_valid=True,
            canonical_schema_errors=[],
            pages=self.pages(request),
            model="extractor-v1",
            cache_hit=False,
        )


def png():
    stream = io.BytesIO()
    Image.new("RGB", (4, 4), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def flow(business, document_fixture):
    client, current, store = business
    bucket, dispatcher = Bucket(), Dispatcher()
    client.app.dependency_overrides[processing_bucket] = lambda: bucket
    client.app.dependency_overrides[processing_dispatcher] = lambda: dispatcher
    current[0].bucket = bucket
    person = make_person(client)
    parser = Parser(document_fixture("passport"))
    return client, current, store, bucket, dispatcher, person, parser


def upload(client, person, key=None, content=None):
    return client.post(
        "/document-processing",
        data={"person_uid": person, "operation_key": str(key or uuid4())},
        files={"file": ("../../original.png", content or png(), "image/png")},
    )


def worker(current, bucket, parser, store):
    # Separate trusted processor identity, not the uploading person's authority.
    app = Application(
        "00000000-0000-0000-0000-000000000123", parsing_processor=True, store=store, bucket=bucket
    )
    return workflow.Worker(app, parser=parser, bucket=bucket)


@pytest.mark.parametrize("score,decision", [(0.6, "accepted"), (0.59999, "needs_review")])
def test_entire_workflow_uses_canonical_schemas_and_per_type_policy(flow, score, decision):
    client, current, store, bucket, dispatcher, person, parser = flow
    policy(client, current, "60", document_type="passport")
    parser.confidence = score
    response = upload(client, person)
    assert response.status_code == 202, response.text
    run = response.json()
    result = worker(current, bucket, parser, store).run(run["uid"])
    assert result["status"] == "completed", result
    assert result["completion"]["decision"] == decision
    source = store.one(RAW, uid=run["source_uid"])
    assert source["storage_kind"] == "bucket" and source["chunk_count"] == 0
    assert client.get(f"/source-documents/{source['uid']}/content").content == png()
    request = parser.extractions[0]
    schema = store.one(workflow.SCHEMA, document_type="passport", version=1)
    assert request.canonical_schema == schema["canonical_schema"]
    assert request.output_schema == schema["draft_schema"]
    assert request.schema_hash == schema["content_sha256"]
    assert "$defs" in request.canonical_schema
    assert {candidate.document_type for candidate in parser.classifications[0].document_types} == {
        kind for kind, _ in workflow.DOCUMENT_MODELS
    }
    assert dispatcher.calls == [run["uid"]]
    assert worker(current, bucket, parser, store).run(run["uid"])["status"] == "completed"
    assert (
        len(parser.extractions) == store.count(D) == store.count(ParsingResultRecord.__table__) == 1
    )
    assert client.post(f"/operations/{run['uid']}/resume").status_code == 409


def test_provider_failure_is_sanitized_and_retry_skips_classification(flow):
    client, current, store, bucket, dispatcher, person, parser = flow
    parser.fail_extraction = True
    uid = upload(client, person).json()["uid"]
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "failed" and result["error_code"] == "processing_unavailable"
    assert "private" not in str(store.one(RUN, uid=uid))
    parser.fail_extraction = False
    assert client.post(f"/document-processing/{uid}/retry", json=command()).status_code == 202
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert len(parser.classifications) == 1 and len(parser.extractions) == 2


@pytest.mark.parametrize("bad", ["bad_hash", "bad_source"])
def test_provider_identity_mismatch_never_persists_document(flow, bad):
    client, current, store, bucket, _, person, parser = flow
    setattr(parser, bad, True)
    uid = upload(client, person).json()["uid"]
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "failed"
    assert store.count(D) == 0


def test_unclassified_document_needs_input_without_extraction(flow):
    client, current, store, bucket, _, person, parser = flow
    parser.kind = None
    uid = upload(client, person).json()["uid"]
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "needs_input" and parser.extractions == []
    assert client.post(f"/document-processing/{uid}/retry", json=command()).status_code == 409


def test_incomplete_attributes_never_auto_accept_even_at_full_confidence(flow):
    client, current, store, bucket, _, person, parser = flow
    policy(client, current, "0", document_type="passport")
    parser.payload = {"document_type": "passport"}
    parser.confidence = 1.0
    uid = upload(client, person).json()["uid"]
    result = worker(current, bucket, parser, store).run(uid)
    assert result["completion"]["decision"] == "needs_review"
    assert result["completion"]["reason_code"] == "invalid_document_attributes"


def test_lost_bucket_response_and_duplicate_request_recover_one_source(flow):
    client, _, store, bucket, _, person, _ = flow
    key = uuid4()
    bucket.lose_response = True
    assert upload(client, person, key).status_code == 503
    first = upload(client, person, key)
    assert first.status_code == 202
    assert upload(client, person, key).json()["uid"] == first.json()["uid"]
    assert store.count(RAW) == len(bucket.files) == 1
    altered = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(altered, format="PNG")
    assert upload(client, person, key, altered.getvalue()).status_code == 409


def test_lost_draft_response_reuses_provider_result_and_exact_revision(flow, monkeypatch):
    client, current, store, bucket, _, person, parser = flow
    instance = worker(current, bucket, parser, store)
    original = instance.app.create_document

    def lose(*args, **kwargs):
        original(*args, **kwargs)
        raise TimeoutError("lost response")

    monkeypatch.setattr(instance.app, "create_document", lose)
    uid = upload(client, person).json()["uid"]
    assert instance.run(uid)["status"] == "failed"
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert len(parser.classifications) == len(parser.extractions) == store.count(D) == 1


def test_retry_dispatches_worker_with_unfinished_document_mutation(flow, monkeypatch):
    client, current, store, bucket, dispatcher, person, parser = flow
    uid = upload(client, person).json()["uid"]
    original = store.ensure
    failed_once = False

    def lose(table, values):
        nonlocal failed_once
        saved = original(table, values)
        if table is D and not failed_once:
            failed_once = True
            raise TimeoutError("lost draft write response")
        return saved

    monkeypatch.setattr(store, "ensure", lose)
    assert worker(current, bucket, parser, store).run(uid)["status"] == "failed"
    assert store.one(RUN, uid=workflow.stable(person, "case-lock")) is not None
    response = client.post(f"/document-processing/{uid}/retry", json=command())
    assert response.status_code == 202, response.text
    assert dispatcher.calls == [uid, uid]
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert store.one(RUN, uid=workflow.stable(person, "case-lock")) is None
    assert len(parser.classifications) == len(parser.extractions) == store.count(D) == 1


def test_worker_claim_prevents_duplicate_execution_and_expired_claim_recovers(flow):
    client, current, store, bucket, _, person, parser = flow
    uid = upload(client, person).json()["uid"]
    token = str(uuid4())
    store.change(
        RUN,
        {"uid": uid},
        {
            "status": "running",
            "lease_token": token,
            "lease_expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        },
    )
    instance = worker(current, bucket, parser, store)
    assert instance.run(uid)["status"] == "running" and parser.classifications == []
    store.change(
        RUN,
        {"uid": uid},
        {"lease_expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()},
    )
    assert instance.run(uid)["status"] == "completed"
    with pytest.raises(ProcessingError, match="lease_lost"):
        instance.save(store.one(RUN, uid=uid), {"stage": "stale"})


def test_expired_worker_cannot_save_late_provider_response(flow, monkeypatch):
    client, current, store, bucket, _, person, parser = flow
    uid = upload(client, person).json()["uid"]
    instance = worker(current, bucket, parser, store)
    now = datetime.now(UTC)
    instance.clock = lambda: now
    original = parser.classify

    def delayed(request):
        nonlocal now
        response = original(request)
        now += timedelta(seconds=workflow.LEASE_SECONDS + 1)
        return response

    monkeypatch.setattr(parser, "classify", delayed)
    with pytest.raises(ProcessingError, match="lease_lost"):
        instance.run(uid)
    saved = store.one(RUN, uid=uid)
    assert saved["result"]["stage"] == "uploaded"
    assert "classification" not in saved["result"]
    assert parser.extractions == [] and store.count(D) == 0


def test_unauthorized_user_cannot_upload_read_retry_or_report_worker_results(flow):
    client, current, store, bucket, _, person, parser = flow
    uid = upload(client, person).json()["uid"]
    current[0] = Application(uuid4(), store=store, bucket=bucket)
    assert upload(client, person).status_code == 404
    assert client.get(f"/document-processing/{uid}").status_code == 404
    assert client.get(f"/operations/{uid}").status_code == 404
    assert client.post(f"/document-processing/{uid}/retry", json=command()).status_code == 404
    with pytest.raises(HTTPException):
        workflow.Worker(current[0], parser=parser, bucket=bucket)


def test_unavailable_dispatch_preserves_recoverable_intent(flow):
    client, _, store, _, dispatcher, person, _ = flow
    dispatcher.fail = True
    result = upload(client, person).json()
    assert result["dispatch_error"] == "processing_dispatch_unavailable"
    assert store.one(RUN, uid=result["uid"])["status"] == "pending"


def test_process_operation_cannot_be_reused_for_another_source(flow):
    client, current, _, _, dispatcher, person, _ = flow
    first = upload(client, person).json()["source_uid"]
    second = upload(client, person).json()["source_uid"]
    key = Command(operation_key=uuid4())
    workflow.start(current[0], first, key, dispatcher)
    with pytest.raises(HTTPException) as error:
        workflow.start(current[0], second, key, dispatcher)
    assert error.value.status_code == 409


def test_legacy_chunk_source_is_copied_to_bucket_before_classification(flow):
    from tests.api.test_workflows import source

    client, current, store, bucket, _, person, parser = flow
    uid = source(client, person, content=png(), media_type="image/png")
    response = client.post(f"/source-documents/{uid}/process", json=command())
    assert response.status_code == 202
    result = worker(current, bucket, parser, store).run(response.json()["uid"])
    assert result["status"] == "completed"
    assert bucket.calls == 1
    assert store.one(RAW, uid=uid)["storage_kind"] == "chunks"
    assert client.get(f"/source-documents/{uid}/content").content == png()


def test_mixed_page_document_needs_input_without_extraction(flow, monkeypatch):
    from pypdf import PdfWriter

    client, current, store, bucket, _, person, parser = flow
    writer, buffer = PdfWriter(), io.BytesIO()
    for _ in range(2):
        writer.add_blank_page(width=100, height=100)
    writer.write(buffer)
    response = client.post(
        "/document-processing",
        data={"person_uid": person, "operation_key": str(uuid4())},
        files={"file": ("packet.pdf", buffer.getvalue(), "application/pdf")},
    )
    assert response.status_code == 202
    original = parser.classify

    def mixed(request):
        first = original(request).pages[0]
        response = (
            ClassificationResponseV2
            if getattr(request, "contract_version", 1) == 2
            else ClassificationResponse
        )
        return response(
            **({"contract_version": 2} if response is ClassificationResponseV2 else {}),
            pages=[first, first.model_copy(update={"page": 2, "document_type": "bank_statement"})],
        )

    monkeypatch.setattr(parser, "classify", mixed)
    result = worker(current, bucket, parser, store).run(response.json()["uid"])
    assert result["status"] == "needs_input" and parser.extractions == []
    assert store.count(D) == 0


def test_lost_finalization_response_replays_intent_and_releases_case_lock(flow, monkeypatch):
    client, _, store, _, _, person, _ = flow
    key = uuid4()
    original = store.change
    lost = [False]

    def change(table, keys, values, expected=None):
        row = original(table, keys, values, expected)
        if table is RAW and values.get("status") == "ready" and not lost[0]:
            lost[0] = True
            raise TimeoutError("lost finalization response")
        return row

    monkeypatch.setattr(store, "change", change)
    with pytest.raises(TimeoutError):
        upload(client, person, key)
    response = upload(client, person, key)
    assert response.status_code == 202, response.text
    assert client.get(f"/persons/{person}").status_code == 200
    assert store.count(RAW) == 1

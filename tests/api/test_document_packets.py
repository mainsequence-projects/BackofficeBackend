"""Real API/worker paths: immutable packets, original pages and pinned OCR capability."""

import base64
import hashlib
import io
from uuid import uuid4

from pypdf import PdfWriter

from src.backoffice.processing.evidence_contracts import (
    ClassificationResponseV2,
    ExtractionResponseV2,
)
from src.backoffice.services.application import DR, RUN, D
from tests.api.test_document_processing import (
    Parser,
    worker,
)
from tests.api.test_document_processing import (
    flow as flow,
)
from tests.api.test_parsing_admin import policy
from tests.api.test_workflows import business as business
from tests.services.test_extraction_persistence import fixture_evidence


def packet():
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class PacketParser(Parser):
    def __init__(self, fixture):
        super().__init__(fixture("passport"))
        self.payloads = {kind: fixture(kind) for kind in ("passport", "bank_statement")}
        self.fail_bank = False
        self.bad_selection = False

    def pages(self, request):
        file = request.files[0]
        return [
            {
                "source_file": file.filename,
                "page": n,
                "source_sha256": hashlib.sha256(base64.b64decode(file.content_base64)).hexdigest(),
                "page_sha256": str(n) * 64,
            }
            for n in (getattr(request, "page_selection", None) or [1, 2, 3])
        ]

    def classify(self, request):
        self.classifications.append(request)
        return ClassificationResponseV2(
            contract_version=2,
            pages=[
                {
                    **p,
                    "document_type": "passport" if p["page"] == 1 else "bank_statement",
                    "confidence": 0.98,
                    "reason": "source fixture",
                    "model": "fixture",
                    "cache_hit": False,
                    "boundary": "continues_document" if p["page"] == 3 else "starts_document",
                    "printed_page_number": 2 if p["page"] == 3 else 1,
                    "printed_page_count": 1 if p["page"] == 1 else 2,
                }
                for p in self.pages(request)
            ],
        )

    def extract(self, request):
        if request.document_type == "bank_statement" and self.fail_bank:
            raise RuntimeError("temporary parser failure")
        self.payload = self.payloads[request.document_type]
        self.extractions.append(request)
        evidence = fixture_evidence(self.payload, request.files[0].filename)
        for field in evidence["field_evidence"]:
            for candidate in field["candidates"]:
                for location in candidate["locations"]:
                    location["page"] = request.page_selection[0]
        response = ExtractionResponseV2(
            **evidence,
            document_type=request.document_type,
            schema_version=request.schema_version,
            schema_hash=request.schema_hash,
            status="draft",
            attributes=self.payload,
            canonical_schema_valid=True,
            canonical_schema_errors=[],
            pages=self.pages(request),
            model="extractor-fixture",
            cache_hit=False,
        )
        if self.bad_selection:
            response.pages[0].page = 20
            for field in response.field_evidence:
                for candidate in field.candidates:
                    for location in candidate.locations:
                        location.page = 20
        return response


def start_packet(flow, monkeypatch):
    client, current, _, _, _, person, _ = flow
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_OCR_ENABLED", "false")
    monkeypatch.delenv("BACKOFFICE_EXTRACTION_READER_MODE", raising=False)
    for kind in ("passport", "bank_statement"):
        policy(client, current, "80", document_type=kind)
    content = packet()
    response = client.post(
        "/document-processing",
        data={"person_uid": person, "operation_key": str(uuid4())},
        files={"file": ("arbitrary.pdf", content, "application/pdf")},
    )
    assert response.status_code == 202, response.text
    return response.json()["uid"], content


def test_packet_groups_keep_original_bytes_pages_and_acceptance(
    flow, monkeypatch, document_fixture
):
    client, current, store, bucket, _, _, _ = flow
    uid, original = start_packet(flow, monkeypatch)
    parser = PacketParser(document_fixture)
    # Changing settings after dispatch must not change this run or any child.
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_OCR_ENABLED", "true")
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    assert len(result["documents"]) == 2
    assert [r.page_selection for r in parser.extractions] == [[1], [2, 3]]
    assert all(r.reader_mode == "single" for r in parser.extractions)
    assert list(bucket.files.values()) == [original]
    for group, pages in zip(result["groups"], ([1], [2, 3]), strict=True):
        doc = client.get(f"/documents/{group['document']['uid']}").json()
        assert doc["accepted"] is True
        assert doc["raw_document_refs"][0]["first_page"] == pages[0]
        assert doc["raw_document_refs"][0]["last_page"] == pages[-1]
        evidence = client.get(f"/documents/{doc['uid']}/revisions/1/extraction-evidence").json()[
            "evidence"
        ]
        assert [p["page"] for p in evidence["extraction"]["pages"]] == pages
        assert (
            evidence["extraction"]["pages"][0]["source_sha256"]
            == hashlib.sha256(original).hexdigest()
        )
    assert worker(current, bucket, parser, store).run(uid) == result
    assert len(parser.classifications) == 1
    assert store.count(D) == 2


def test_packet_retry_resumes_child_without_duplicate_documents(
    flow, monkeypatch, document_fixture
):
    _, current, store, bucket, _, _, _ = flow
    uid, _ = start_packet(flow, monkeypatch)
    parser = PacketParser(document_fixture)
    parser.fail_bank = True
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "failed"
    assert store.count(D) == 1
    parser.fail_bank = False
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    assert store.count(D) == store.count(DR) == 2
    assert len(parser.classifications) == 1
    assert store.one(RUN, uid=uid)["input_snapshot"]["reader_mode"] == "single"


def test_packet_rejects_extraction_outside_selected_source_pages(
    flow, monkeypatch, document_fixture
):
    _, current, store, bucket, _, _, _ = flow
    uid, _ = start_packet(flow, monkeypatch)
    parser = PacketParser(document_fixture)
    parser.bad_selection = True
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "failed"
    assert result["error_code"] == "parser_source_manifest_mismatch"
    assert store.count(D) == 0


def test_packet_with_unsupported_group_creates_no_partial_documents(
    flow, monkeypatch, document_fixture
):
    _, current, store, bucket, _, _, _ = flow
    uid, _ = start_packet(flow, monkeypatch)
    parser = PacketParser(document_fixture)
    classify = parser.classify

    def unsupported(request):
        response = classify(request)
        response.pages[-1].document_type = "unsupported_type"
        response.pages[-1].boundary = "starts_document"
        response.pages[-1].printed_page_number = 1
        response.pages[-1].printed_page_count = 1
        response.pages[1].printed_page_count = 1
        return response

    parser.classify = unsupported
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "needs_input"
    assert result["error_code"] == "multiple_documents_require_grouping"
    assert store.count(D) == 0
    assert parser.extractions == []

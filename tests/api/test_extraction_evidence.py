"""One revision-bound evidence path for account, loan and ordinary document reviews."""

import hashlib
from uuid import uuid4

import pytest

from src.backoffice.processing.evidence_contracts import ExtractionResponseV2
from src.backoffice.services.application import DR, RUN, Application, canonical
from src.backoffice.tables.evidence import FieldEvidenceRecord
from tests.api.test_document_processing import Parser, upload, worker
from tests.api.test_document_processing import flow as flow
from tests.api.test_parsing_admin import policy
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command

FIELD = FieldEvidenceRecord.__table__


@pytest.mark.parametrize(
    "kind", ["passport", "loan_contract", "employer_confirmation", "bank_statement"]
)
def test_shared_worker_retains_exact_revision_and_authorized_evidence(flow, document_fixture, kind):
    client, current, store, bucket, _, person, _ = flow
    parser = Parser(document_fixture(kind), kind=kind)
    run = upload(client, person).json()
    result = worker(current, bucket, parser, store).run(run["uid"])
    assert result["status"] == "completed", result
    document_uid = result["document"]["uid"]
    path = f"/documents/{document_uid}/revisions/1/extraction-evidence"
    response = client.get(path)
    assert response.status_code == 200
    evidence = response.json()["evidence"]
    assert evidence["run_uid"] == run["uid"]
    assert evidence["extraction"]["attributes"] == parser.payload
    assert evidence["classification"]["contract_version"] == 2
    assert list(evidence["source_mapping"].values()) == [run["source_uid"]]
    digest = evidence.pop("content_sha256")
    assert hashlib.sha256(canonical(evidence).encode()).hexdigest() == digest
    fields = store.rows(FIELD)
    assert fields and all(row["person_uid"] == person for row in fields)
    assert all(row["provenance"]["evidence_sha256"] == digest for row in fields)
    assert all(row["provenance"]["confidence"] is None for row in fields)
    assert worker(current, bucket, parser, store).run(run["uid"])["status"] == "completed"
    assert store.count(FIELD) == len(fields)
    owner = current[0]
    current[0] = Application(uuid4(), store=store)
    assert client.get(path).status_code == 404
    current[0] = owner
    doc = client.get(f"/documents/{document_uid}").json()
    changed = client.patch(
        f"/documents/{document_uid}/draft",
        json=command(
            expected_revision=1,
            payload=doc["payload"],
            raw_document_refs=doc["raw_document_refs"],
        ),
    )
    assert changed.status_code == 200, changed.text
    assert client.get(path).json()["evidence"]["content_sha256"] == digest
    assert (
        client.get(f"/documents/{document_uid}/revisions/2/extraction-evidence").json()["evidence"]
        is None
    )
    assert (
        client.get(f"/documents/{document_uid}/revisions/99/extraction-evidence").status_code == 404
    )


@pytest.mark.parametrize(
    "mode,reason",
    [
        ("disagree", "extraction_readers_disagree"),
        ("incomplete", "extraction_evidence_incomplete"),
        ("reader_missing", "extraction_reader_missing"),
    ],
)
def test_back_office_blocks_automatic_acceptance_from_extraction_observations(
    flow, mode, reason, monkeypatch
):
    # Single-reader observations: pin the mode the default now overrides.
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "single")
    client, current, store, bucket, _, person, original = flow
    policy(client, current, "60", document_type="passport")

    class Observations(Parser):
        def extract(self, request):
            data = super().extract(request).model_dump()
            field = next(f for f in data["field_evidence"] if f["pointer"] == "/full_name")
            if mode == "incomplete":
                data["evidence_complete"] = False
            else:
                field["candidates"].append(
                    {
                        **field["candidates"][0],
                        "reader_id": "second",
                        "value": "Another reading" if mode == "disagree" else None,
                    }
                )
                field["agreement"] = "disagree" if mode == "disagree" else "single_reader"
            return ExtractionResponseV2.model_validate(data)

    parser = Observations(original.payload)
    result = worker(current, bucket, parser, store).run(upload(client, person).json()["uid"])
    assert result["status"] == "completed", result
    assert result["completion"]["decision"] == "needs_review"
    assert result["completion"]["reason_code"] == reason


def test_lost_field_write_resumes_same_durable_intent_without_duplicate_evidence(flow, monkeypatch):
    client, current, store, bucket, _, person, parser = flow
    original = store.ensure
    failed = False

    def lose(table, values):
        nonlocal failed
        result = original(table, values)
        if table is FIELD and not failed:
            failed = True
            raise TimeoutError("lost evidence response")
        return result

    monkeypatch.setattr(store, "ensure", lose)
    uid = upload(client, person).json()["uid"]
    assert worker(current, bucket, parser, store).run(uid)["status"] == "failed"
    assert store.one(RUN, uid=uid)["result"].get("document") is None
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    revision = store.one(DR, document_uid=result["document"]["uid"], revision=1)
    expected = sum(
        len(c["locations"])
        for f in revision["extraction_evidence"]["extraction"]["field_evidence"]
        for c in f["candidates"]
    )
    assert store.count(FIELD) == expected
    assert len(parser.classifications) == len(parser.extractions) == 1


def test_existing_unversioned_run_uses_v1_without_fabricating_provenance(flow):
    client, current, store, bucket, _, person, parser = flow
    uid = upload(client, person).json()["uid"]
    snapshot = store.one(RUN, uid=uid)["input_snapshot"]
    snapshot.pop("parser_contract_version")
    store.change(RUN, {"uid": uid}, {"input_snapshot": snapshot})
    result = worker(current, bucket, parser, store).run(uid)
    assert result["status"] == "completed", result
    assert not hasattr(parser.extractions[0], "contract_version")
    revision = store.one(DR, document_uid=result["document"]["uid"], revision=1)
    assert revision["extraction_evidence"] is None
    assert store.count(FIELD) == 0


def test_v2_run_rejects_v1_response_without_downgrading(flow):
    client, current, store, bucket, _, person, original = flow

    class OldParser(Parser):
        def classify(self, request):
            from src.backoffice.processing.contracts import ClassifyRequest

            return super().classify(
                ClassifyRequest.model_validate(request.model_dump(exclude={"contract_version"}))
            )

    parser = OldParser(original.payload)
    result = worker(current, bucket, parser, store).run(upload(client, person).json()["uid"])
    assert result["error_code"] == "parser_contract_invalid"
    assert store.count(DR) == 0 and not parser.extractions


def test_reader_strategy_is_pinned_before_dispatch_and_retries(flow, monkeypatch):
    client, current, store, bucket, _, person, parser = flow
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "independent_readers")
    uid = upload(client, person).json()["uid"]
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "single")
    parser.fail_extraction = True
    assert worker(current, bucket, parser, store).run(uid)["status"] == "failed"
    parser.fail_extraction = False
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert all(r.reader_mode == "independent_readers" for r in parser.extractions)


def test_missing_requested_reader_is_retryable_without_persisting_invalid_checkpoint(
    flow, monkeypatch
):
    client, current, store, bucket, _, person, parser = flow
    monkeypatch.setenv("BACKOFFICE_EXTRACTION_READER_MODE", "independent_readers")
    original = parser.extract
    broken = True

    def respond(request):
        response = original(request)
        if broken:
            data = response.model_dump()
            for field in data["field_evidence"]:
                field["candidates"] = field["candidates"][:1]
                if field["agreement"] == "agree":
                    field["agreement"] = "single_reader"
            return ExtractionResponseV2.model_validate(data)
        return response

    monkeypatch.setattr(parser, "extract", respond)
    uid = upload(client, person).json()["uid"]
    result = worker(current, bucket, parser, store).run(uid)
    assert result["error_code"] == "parser_reader_strategy_mismatch"
    assert "extraction" not in store.one(RUN, uid=uid)["result"]
    assert store.count(DR) == 0
    broken = False
    assert worker(current, bucket, parser, store).run(uid)["status"] == "completed"
    assert len(parser.extractions) == 2

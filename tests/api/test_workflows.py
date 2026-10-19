"""HTTP workflows against real relational constraints, plus durable retry recovery."""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from api.app.main import app, application
from src.backoffice.services.application import RUN, Application, publish_catalog
from src.backoffice.services.storage import Storage
from src.backoffice.tables import Base


class SQLStorage(Storage):
    def __init__(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        event.listen(self.engine, "connect", lambda db, _: db.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.engine)
        self.fail_after_write = None
        publish_catalog(self)

    def execute(self, statement, operation="select"):
        with self.engine.begin() as connection:
            result = connection.execute(statement)
            rows = [dict(row) for row in result.mappings()] if result.returns_rows else []
            response = {
                "rows": rows,
                "row_count": len(rows) if operation == "select" else result.rowcount,
            }
        if operation != "select" and self.fail_after_write:
            self.fail_after_write -= 1
            if self.fail_after_write == 0:
                self.fail_after_write = None
                raise TimeoutError("Response lost after database commit")
        return response


@pytest.fixture
def business():
    store = SQLStorage()
    owner = Application(uuid4(), store=store)
    current = [owner]
    test_app = FastAPI()
    test_app.include_router(app.router)
    test_app.exception_handlers.update(app.exception_handlers)
    test_app.dependency_overrides[application] = lambda: current[0]
    with TestClient(test_app, raise_server_exceptions=True) as client:
        yield client, current, store
    store.engine.dispose()


def command(**values):
    return {"operation_key": str(uuid4()), **values}


def post(client, path, **values):
    response = client.post(path, json=command(**values))
    assert response.status_code in (200, 201), response.text
    return response.json()


def make_person(client, **values):
    profile = {
        "full_name": "Alex Morgan",
        "date_of_birth": "1990-03-12",
        "employment_status": "retired",
        "residency_permit_required": False,
        "residential_address": {
            "address_line_1": "14 Example Street",
            "city": "Prague",
            "postal_code": "11000",
            "country_code": "CZ",
        },
        **values,
    }
    return post(client, "/persons", profile=profile)["uid"]


def source(client, person, content=b"Printed evidence", media_type="text/plain"):
    upload = post(
        client,
        "/source-documents/uploads",
        person_uid=person,
        filename="evidence.txt",
        media_type=media_type,
        byte_count=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
    response = client.put(
        f"/source-documents/uploads/{upload['uid']}/chunks/0",
        json={"content_base64": base64.b64encode(content).decode()},
    )
    assert response.status_code == 200, response.text
    post(client, f"/source-documents/uploads/{upload['uid']}/finalize")
    return upload["uid"]


def document(client, person, kind, payload, content=None):
    raw = source(client, person, content or json.dumps(payload).encode())
    doc = post(
        client,
        f"/persons/{person}/documents",
        document_type=kind,
        payload=payload,
        raw_document_refs=[{"raw_document_uid": raw}],
    )
    post(client, f"/documents/{doc['uid']}/submit", expected_revision=1)
    return doc["uid"]


def test_complete_case_roundtrip_revision_review_and_staleness(business, document_fixture):
    client, current, store = business
    current[0].reviewer = True
    person = make_person(client)
    assignment = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )
    docs = []
    for kind in (
        "national_identity_card",
        "utility_bill",
        "source_of_funds_evidence",
        "kyc_questionnaire",
    ):
        payload = document_fixture(kind)
        if kind == "utility_bill":
            payload["issue_date"] = datetime.now(UTC).date().isoformat()
        if kind == "kyc_questionnaire":
            payload["employment_status"] = "retired"
        doc = document(client, person, kind, payload)
        post(
            client,
            f"/documents/{doc}/reviews",
            expected_revision=1,
            expected_decision_sequence=0,
            decision="accepted",
            reason="Compared attributes with the raw evidence",
        )
        docs.append(doc)
    response = client.put(
        f"/assignments/{assignment['uid']}/documents",
        json=command(expected_revision=1, document_uids=docs),
    )
    assert response.status_code == 200, response.text
    report = post(client, f"/assignments/{assignment['uid']}/evaluations", expected_revision=2)
    evaluation = client.get(f"/evaluations/{report['uid']}").json()
    assert evaluation["summary"]["complete"] is True, evaluation["findings"]
    assert evaluation["stale"] is False
    current[0] = Application(current[0].actor, reviewer=True, store=store)
    assert client.get(f"/persons/{person}").json()["full_name"] == "Alex Morgan"
    first = client.get(f"/documents/{docs[0]}").json()
    saved = client.patch(
        f"/documents/{docs[0]}/draft",
        json=command(
            expected_revision=1,
            payload=first["payload"],
            raw_document_refs=first["raw_document_refs"],
        ),
    )
    assert saved.status_code == 200, saved.text
    assert client.get(f"/documents/{docs[0]}").json()["accepted"] is False
    assert client.get(f"/evaluations/{report['uid']}").json()["stale"] is True
    stale_review = client.post(
        f"/documents/{docs[0]}/reviews",
        json=command(
            expected_revision=1,
            expected_decision_sequence=1,
            decision="accepted",
            reason="Old revision",
        ),
    )
    assert stale_review.status_code == 409


def test_ownership_and_review_permissions(business, document_fixture):
    client, current, store = business
    owner = current[0]
    person = make_person(client)
    doc = document(client, person, "passport", document_fixture("passport"))
    assert (
        client.post(
            f"/documents/{doc}/reviews",
            json=command(
                expected_revision=1,
                expected_decision_sequence=0,
                decision="accepted",
                reason="No permission",
            ),
        ).status_code
        == 403
    )
    current[0] = Application(uuid4(), store=store)
    assert client.get("/persons").json()["items"] == []
    for path in (f"/persons/{person}", f"/documents/{doc}", f"/persons/{person}/history"):
        assert client.get(path).status_code == 404
    current[0] = owner
    assert (
        client.post(
            f"/persons/{person}/documents", json=command(document_type="passport", accepted=True)
        ).status_code
        == 422
    )


def test_incomplete_draft_requires_source_and_canonical_data(business):
    client, _, _ = business
    person = make_person(client)
    draft = post(
        client,
        f"/persons/{person}/documents",
        document_type="passport",
        payload={"full_name": "Alex Morgan"},
    )
    assert (
        client.post(
            f"/documents/{draft['uid']}/submit", json=command(expected_revision=1)
        ).status_code
        == 422
    )
    assert client.get(f"/documents/{draft['uid']}").json()["status"] == "draft"
    assert client.get("/document-types/passport/schema?version=99").status_code == 422
    assert len(client.get("/document-types").json()["items"]) == 10
    assert client.get("/person-schema").json()["properties"]["full_name"]["description"]


def test_upload_integrity_immutable_chunks_and_cross_person_source(business):
    client, _, _ = business
    person = make_person(client)
    content = b"the real file"
    upload = post(
        client,
        "/source-documents/uploads",
        person_uid=person,
        filename="file.txt",
        media_type="text/plain",
        byte_count=len(content),
        content_sha256=hashlib.sha256(content).hexdigest(),
    )
    uid = upload["uid"]
    assert (
        client.post(f"/source-documents/uploads/{uid}/finalize", json=command()).status_code == 409
    )
    path = f"/source-documents/uploads/{uid}/chunks/0"
    assert client.put(path, json={"content_base64": "!!!!"}).status_code == 422
    body = {"content_base64": base64.b64encode(content).decode()}
    assert client.put(path, json=body).status_code == 200
    assert client.put(path, json=body).status_code == 200
    assert (
        client.put(
            path, json={"content_base64": base64.b64encode(b"fake content!").decode()}
        ).status_code
        == 409
    )
    post(client, f"/source-documents/uploads/{uid}/finalize")
    assert client.get(f"/source-documents/{uid}/content").content == content
    assert client.get(f"/source-documents/{uid}").json()["received_chunks"] == [0]
    other = make_person(client)
    assert (
        client.post(
            f"/persons/{other}/documents",
            json=command(document_type="passport", raw_document_refs=[{"raw_document_uid": uid}]),
        ).status_code
        == 422
    )


def test_idempotency_and_lost_response_recovery(business):
    client, current, store = business
    body = command(profile={"full_name": "Durable case"})
    # Fail after parent row was committed but before its response was received.
    store.fail_after_write = 3
    with pytest.raises(TimeoutError):
        client.post("/persons", json=body)
    pending = store.rows(RUN, RUN.c.kind == "person.created")
    assert len(pending) == 1
    uid = pending[0]["result"]["uid"]
    assert client.get(f"/persons/{uid}").status_code == 409
    current[0] = Application(current[0].actor, store=store)
    resumed = client.post("/persons", json=body)
    assert resumed.status_code == 201, resumed.text
    assert client.post("/persons", json=body).json() == resumed.json()
    assert len(client.get("/persons").json()["items"]) == 1
    assert (
        client.post(
            "/persons", json={**body, "profile": {"full_name": "Changed request"}}
        ).status_code
        == 409
    )


def test_stale_profile_and_assignment_updates(business):
    client, _, _ = business
    person = make_person(client)
    body = command(expected_revision=1, profile={"full_name": "Alex Morgan"})
    assert client.put(f"/persons/{person}", json=body).status_code == 200
    assert (
        client.put(
            f"/persons/{person}", json=command(expected_revision=1, profile={"full_name": "Stale"})
        ).status_code
        == 409
    )
    assignment = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )
    assert (
        client.put(
            f"/assignments/{assignment['uid']}/documents",
            json=command(expected_revision=1, document_uids=[]),
        ).status_code
        == 200
    )
    assert (
        client.put(
            f"/assignments/{assignment['uid']}/documents",
            json=command(expected_revision=1, document_uids=[]),
        ).status_code
        == 409
    )


def test_pending_expired_mismatch_and_unknown_applicability(business, document_fixture):
    client, current, _ = business
    current[0].reviewer = True
    person = make_person(client, residency_permit_required=None)
    assignment = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=1,
    )
    payload = document_fixture("passport")
    payload["mrz_lines"] = ["Source MRZ"]
    payload["expiration_date"] = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    doc = document(client, person, "passport", payload)
    client.put(
        f"/assignments/{assignment['uid']}/documents",
        json=command(expected_revision=1, document_uids=[doc]),
    )
    report = post(client, f"/assignments/{assignment['uid']}/evaluations", expected_revision=2)
    findings = client.get(f"/evaluations/{report['uid']}").json()["findings"]
    assert (
        next(x for x in findings if x["requirement_key"] == "identity")["status"]
        == "pending_review"
    )
    assert (
        next(x for x in findings if x["requirement_key"] == "residency")["reason_code"]
        == "APPLICABILITY_UNKNOWN"
    )
    post(
        client,
        f"/documents/{doc}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision="accepted",
        reason="Source checked",
    )
    report = post(client, f"/assignments/{assignment['uid']}/evaluations", expected_revision=2)
    findings = client.get(f"/evaluations/{report['uid']}").json()["findings"]
    assert (
        next(x for x in findings if x["requirement_key"] == "identity")["reason_code"]
        == "DOCUMENT_EXPIRED"
    )


def test_pagination_counts_and_literal_search(business):
    client, _, _ = business
    make_person(client, full_name="First Customer")
    make_person(client, full_name="Second Customer")
    make_person(client, full_name="100% Literal")
    page = client.get("/persons?limit=1&offset=1").json()
    assert page["total_items"] == 3
    assert len(page["items"]) == 1
    assert page["has_more"] is True
    literal = client.get("/persons", params={"search": "%"}).json()
    assert literal["total_items"] == 1
    assert literal["items"][0]["full_name"] == "100% Literal"


def test_multichunk_resume_and_complete_download(business):
    from src.backoffice.tables.evidence import MAX_CHUNK_BYTES

    client, _, _ = business
    person = make_person(client)
    data = b"a" * MAX_CHUNK_BYTES + b"b" * 17
    upload = post(
        client,
        "/source-documents/uploads",
        person_uid=person,
        filename="larger.txt",
        media_type="text/plain",
        byte_count=len(data),
        content_sha256=hashlib.sha256(data).hexdigest(),
    )
    uid = upload["uid"]
    # Chunks may arrive in any order; finalization requires the full sequence.
    for index in (1, 0):
        chunk = data[index * MAX_CHUNK_BYTES : (index + 1) * MAX_CHUNK_BYTES]
        assert (
            client.put(
                f"/source-documents/uploads/{uid}/chunks/{index}",
                json={"content_base64": base64.b64encode(chunk).decode()},
            ).status_code
            == 200
        )
    assert client.get(f"/source-documents/{uid}").json()["received_chunks"] == [0, 1]
    post(client, f"/source-documents/uploads/{uid}/finalize")
    assert client.get(f"/source-documents/{uid}/content").content == data
    assert (
        base64.b64decode(client.get(f"/source-documents/{uid}/chunks/1").json()["content_base64"])
        == b"b" * 17
    )


def test_real_application_requires_verified_identity():
    # No dependency override: the installed Main Sequence middleware rejects an
    # unauthenticated request before any business route can read storage.
    with TestClient(app) as client:
        response = client.get("/persons")
    assert response.status_code in (401, 403)


def test_operation_recovery_requires_original_actor(business):
    client, current, store = business
    original = current[0]
    body = command(profile={"full_name": "Recovered via API"})
    store.fail_after_write = 3
    with pytest.raises(TimeoutError):
        client.post("/persons", json=body)
    operation_key = body["operation_key"]
    assert client.get(f"/operations/{operation_key}").json()["status"] == "pending"
    current[0] = Application(uuid4(), reviewer=True, store=store)
    assert client.get(f"/operations/{operation_key}").status_code == 404
    assert client.post(f"/operations/{operation_key}/resume").status_code == 404
    current[0] = original
    resumed = client.post(f"/operations/{operation_key}/resume")
    assert resumed.status_code == 200, resumed.text
    assert client.get(f"/operations/{operation_key}").json()["status"] == "completed"
    assert client.post(f"/operations/{operation_key}/resume").json() == resumed.json()
    assert (
        client.get(f"/persons/{resumed.json()['uid']}").json()["full_name"] == "Recovered via API"
    )


def test_late_worker_cannot_rewind_a_newer_submission(business, document_fixture):
    from fastapi import HTTPException

    from src.backoffice.services.application import D, stable

    client, current, store = business
    person = make_person(client)
    raw = source(client, person)
    doc = post(
        client,
        f"/persons/{person}/documents",
        document_type="passport",
        payload=document_fixture("passport"),
        raw_document_refs=[{"raw_document_uid": raw}],
    )
    first_command = command(expected_revision=1)
    assert client.post(f"/documents/{doc['uid']}/submit", json=first_command).status_code == 200
    late_worker_plan = store.one(RUN, uid=first_command["operation_key"])
    first = client.get(f"/documents/{doc['uid']}").json()
    assert (
        client.patch(
            f"/documents/{doc['uid']}/draft",
            json=command(
                expected_revision=1,
                payload=first["payload"],
                raw_document_refs=first["raw_document_refs"],
            ),
        ).status_code
        == 200
    )
    post(client, f"/documents/{doc['uid']}/submit", expected_revision=2)
    # Simulate a second worker that loaded the first intent before its peer
    # completed it, then resumed only after a newer submission was committed.
    with pytest.raises(HTTPException) as error:
        current[0].finish(
            late_worker_plan,
            stable(person, "case-lock"),
            first_command["operation_key"],
            datetime.now(UTC).isoformat(),
        )
    assert error.value.status_code == 409
    assert store.one(D, uid=doc["uid"])["current_revision"] == 2
    # The public idempotent retry still returns the original recorded outcome.
    assert (
        client.post(f"/documents/{doc['uid']}/submit", json=first_command).json()["revision"] == 1
    )


def test_exact_revision_keeps_accepted_attributes_and_sources_after_a_new_draft(
    business, document_fixture
):
    client, current, _ = business
    current[0].reviewer = True
    person = make_person(client)
    payload = document_fixture("passport")
    uid = document(client, person, "passport", payload)
    review = post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision="accepted",
        reason="Verified retained revision",
    )
    original = client.get(f"/documents/{uid}").json()
    replacement_source = source(client, person, b"Corrected source for a later draft")
    response = client.patch(
        f"/documents/{uid}/draft",
        json=command(
            expected_revision=1,
            payload={**payload, "passport_number": "CORRECTED-002"},
            raw_document_refs=[{"raw_document_uid": replacement_source}],
        ),
    )
    assert response.status_code == 200, response.text
    retained = client.get(f"/documents/{uid}/revisions/1")
    assert retained.status_code == 200, retained.text
    retained = retained.json()
    assert retained["uid"] == uid
    assert retained["person_uid"] == person
    assert retained["document_type"] == "passport"
    assert retained["schema_version"] == 1
    assert retained["revision"] == 1 and retained["status"] == "submitted"
    assert retained["payload"] == original["payload"]
    assert retained["raw_document_refs"] == original["raw_document_refs"]
    assert retained["accepted"] is True and retained["review_status"] == "accepted"
    assert retained["latest_review"]["uid"] == review["uid"]
    latest = client.get(f"/documents/{uid}").json()
    assert latest["revision"] == 2 and latest["accepted"] is False
    assert latest["payload"]["passport_number"] == "CORRECTED-002"
    exact_draft = client.get(f"/documents/{uid}/revisions/2").json()
    assert exact_draft["status"] == "draft" and exact_draft["latest_review"] is None


def test_exact_revision_is_not_limited_by_revision_or_review_list_pages(business, document_fixture):
    from src.backoffice.services.application import DR, RV, D

    client, current, store = business
    current[0].reviewer = True
    person = make_person(client)
    uid = document(client, person, "passport", document_fixture("passport"))
    # Two decisions on the retained revision verify the effective sequence.
    post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision="rejected",
        reason="Initial decision",
    )
    effective = post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=1,
        decision="accepted",
        reason="Corrected review decision",
    )
    original = store.one(DR, document_uid=uid, revision=1)
    now = datetime.now(UTC)
    # Keep the API scenario small, then seed valid retained history beyond both
    # collection limits using the same real table constraints as normal writes.
    for number in range(2, 62):
        at = (now + timedelta(seconds=number)).isoformat()
        store.ensure(
            DR,
            {
                **original,
                "uid": str(uuid4()),
                "revision": number,
                "created_at": at,
                "submitted_at": at,
            },
        )
        for sequence in (1, 2):
            store.ensure(
                RV,
                {
                    "uid": str(uuid4()),
                    "document_uid": uid,
                    "revision": number,
                    "decision_sequence": sequence,
                    "decision": "rejected",
                    "reviewed_by": current[0].actor,
                    "reviewed_at": at,
                    "reason": "Later revision history fixture",
                    "operation_key": str(uuid4()),
                },
            )
    store.change(D, {"uid": uid}, {"current_revision": 61})
    assert all(
        row["revision"] != 1 for row in client.get(f"/documents/{uid}/revisions").json()["items"]
    )
    assert all(
        row["revision"] != 1 for row in client.get(f"/documents/{uid}/reviews").json()["items"]
    )
    retained = client.get(f"/documents/{uid}/revisions/1")
    assert retained.status_code == 200, retained.text
    assert retained.json()["accepted"] is True
    assert retained.json()["latest_review"]["uid"] == effective["uid"]
    assert retained.json()["latest_review"]["decision_sequence"] == 2
    assert retained.json()["current_revision"] == 61


def test_exact_revision_denies_foreign_cases_and_unknown_revisions(business, document_fixture):
    client, current, store = business
    person = make_person(client)
    uid = document(client, person, "passport", document_fixture("passport"))
    for number in (0, -1, 99, 2**63):
        assert client.get(f"/documents/{uid}/revisions/{number}").status_code == 404
    assert client.get(f"/documents/{uuid4()}/revisions/1").status_code == 404
    current[0] = Application(uuid4(), store=store)
    assert client.get(f"/documents/{uid}/revisions/1").status_code == 404
    assert client.get(f"/documents/{uid}/revisions/99").status_code == 404

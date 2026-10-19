"""Subject-independent intake, real durable workers and multi-case allocation on SQLite."""

from uuid import uuid4

import pytest

from api.app.main import processing_bucket, processing_dispatcher
from src.backoffice.processing import allocation, workflow
from src.backoffice.services.application import EV, RAW, RUN, Application, D
from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png
from tests.api.test_parsing_admin import policy
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post


@pytest.fixture
def intake(business, document_fixture, monkeypatch):
    client, current, store = business
    bucket, dispatcher = Bucket(), Dispatcher()
    client.app.dependency_overrides[processing_bucket] = lambda: bucket
    client.app.dependency_overrides[processing_dispatcher] = lambda: dispatcher
    payload = document_fixture("passport")
    payload["mrz_lines"] = ["EXAMPLE"]
    parser = Parser(payload)
    owner = current[0]
    monkeypatch.setattr(
        allocation,
        "requester_app",
        lambda worker, row: Application(
            row["input_snapshot"]["actor_uid"], reviewer=owner.reviewer, store=store
        ),
    )
    processor = Application(uuid4(), parsing_processor=True, store=store, bucket=bucket)

    def run(uid):
        return workflow.Worker(processor, parser=parser, bucket=bucket).run(uid)

    return client, current, store, bucket, dispatcher, parser, run


def upload(client, key=None):
    response = client.post(
        "/document-intakes",
        data={"operation_key": str(key or uuid4())},
        files={"file": ("passport.png", png(), "image/png")},
    )
    assert response.status_code == 202, response.text
    return response.json()


def build(client, person, kind="account_opening", version=1):
    return post(
        client,
        "/cases",
        subject_uid=person,
        case_type_key=kind,
        document_set_key="loan_requirements" if kind == "new_loan" else "new_account_requirements",
        document_set_version=version,
    )["uid"]


def test_drop_identifies_person_allocates_all_cases_and_evaluates(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    cases = {build(client, person), build(client, person, "new_loan")}
    policy(client, current, "60", document_type="passport")
    key = uuid4()
    started = upload(client, key)
    assert store.count(RAW) == store.count(D) == 0
    assert upload(client, key)["uid"] == started["uid"]
    result = run(started["uid"])
    assert result["status"] == "completed", result
    assert result["subject_uid"] == person
    assert result["completion"]["decision"] == "accepted"
    assert {t["case_uid"] for t in result["targets"]} == cases
    assert all(t["status"] == "completed" for t in result["targets"]), result
    assert store.count(EV) == 2
    assert store.count(D) == store.count(RAW) == 1
    for uid in cases:
        assert client.get(f"/cases/{uid}").json()["document_uids"] == [result["document"]["uid"]]
    assert len(parser.extractions) == len(parser.classifications) == 1
    assert parser.extractions[0].canonical_schema["required"]
    result = client.get("/document-allocations/" + started["uid"]).json()
    assert result["target_count"] == 2
    assert client.get("/document-intakes").json()["total_items"] == 1


def test_uncertain_identity_pauses_then_resumes_same_extraction(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    one = make_person(client)
    two = make_person(client)
    case = build(client, two, "new_loan")
    uid = upload(client)["uid"]
    result = run(uid)
    assert result["status"] == "needs_input", result
    assert {p["uid"] for p in result["candidates"]} == {one, two}
    assert store.count(D) == 0
    body = command(subject_uid=two, expected_revision=result["revision"])
    assert (
        client.post(
            f"/document-allocations/{uid}/resolve", json={**body, "expected_revision": 999}
        ).status_code
        == 409
    )
    response = client.post(f"/document-allocations/{uid}/resolve", json=body)
    assert response.status_code == 202, response.text
    assert client.post(f"/document-allocations/{uid}/resolve", json=body).status_code == 202
    result = run(uid)
    assert result["status"] == "completed", result
    assert result["targets"][0]["case_uid"] == case
    assert result["completion"]["decision"] == "needs_review"
    assert len(parser.classifications) == len(parser.extractions) == 1


def test_duplicate_bytes_reuse_document_and_do_not_inflate_links(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    first = run(upload(client)["uid"])
    assert first["status"] == "completed", first
    second = run(upload(client)["uid"])
    assert second["status"] == "completed", second
    assert second["document"] == first["document"]
    assert store.count(D) == store.count(RAW) == 1
    assert client.get(f"/cases/{case}").json()["document_uids"] == [first["document"]["uid"]]


def test_private_queue_and_conflicting_person_resolution(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client, full_name="Someone Else")
    uid = upload(client)["uid"]
    result = run(uid)
    assert result["status"] == "needs_input"
    assert (
        client.post(
            f"/document-allocations/{uid}/resolve",
            json=command(subject_uid=person, expected_revision=result["revision"]),
        ).status_code
        == 422
    )
    current[0] = Application(uuid4(), organization_admin=True, store=store)
    assert client.get(f"/document-allocations/{uid}").status_code == 404
    assert client.get("/document-intakes").json()["total_items"] == 0
    assert client.post(f"/document-allocations/{uid}/retry", json=command()).status_code == 404


def test_strict_inputs_and_invalid_upload(intake):
    client, *_ = intake
    for body in (
        command(),
        command(intake_uid=str(uuid4()), source_uid=str(uuid4())),
        command(intake_uid=str(uuid4()), actor_uid=str(uuid4())),
    ):
        assert client.post("/document-allocations", json=body).status_code == 422
    response = client.post(
        "/document-intakes",
        data={"operation_key": str(uuid4())},
        files={"file": ("bad.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422

    for fields in (
        {"operation_key": str(uuid4()), "subject_uid": str(uuid4())},
        {"operation_key": [str(uuid4()), str(uuid4())]},
    ):
        response = client.post(
            "/document-intakes",
            data=fields,
            files={"file": ("passport.png", png(), "image/png")},
        )
        assert response.status_code == 422, response.text


def test_partial_case_failure_retries_without_relink_or_reextraction(intake, monkeypatch):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    cases = [build(client, person, "new_loan"), build(client, person, "new_loan")]
    original = Application.evaluate
    failing = [True]

    def evaluate(self, uid, *args, **kwargs):
        if str(uid) == cases[0] and failing[0]:
            raise RuntimeError("private-provider-secret")
        return original(self, uid, *args, **kwargs)

    monkeypatch.setattr(Application, "evaluate", evaluate)
    uid = upload(client)["uid"]
    first = run(uid)
    assert first["status"] == "failed", first
    assert {t["status"] for t in first["targets"]} == {"failed", "completed"}
    assert "private-provider" not in str(store.one(RUN, uid=uid))
    failing[0] = False
    assert client.post(f"/document-allocations/{uid}/retry", json=command()).status_code == 202
    second = run(uid)
    assert second["status"] == "completed", second
    assert store.count(EV) == 2
    assert len(parser.extractions) == store.count(D) == 1
    assert all(client.get(f"/cases/{c}").json()["revision"] == 2 for c in cases)


def test_lost_link_response_recovers_durable_intent(intake, monkeypatch):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    original = Application.set_documents
    interrupted = [False]

    def lose(self, uid, cmd):
        if not interrupted[0]:
            interrupted[0] = True
            store.fail_after_write = 3
        return original(self, uid, cmd)

    monkeypatch.setattr(Application, "set_documents", lose)
    uid = upload(client)["uid"]
    first = run(uid)
    assert first["status"] == "failed", first
    second = run(uid)
    assert second["status"] == "completed", second
    assert client.get(f"/cases/{case}").json()["revision"] == 2
    assert store.count(EV) == 1


def test_existing_source_and_comparison_policy_use_same_engine(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan", 2)
    # Comparison policy with one document still evaluates all requirements and retains a run.
    uid = upload(client)["uid"]
    first = run(uid)
    assert first["status"] == "completed", first
    assert first["targets"][0]["case_uid"] == case
    source = store.rows(RAW)[0]
    response = client.post("/document-allocations", json=command(source_uid=source["uid"]))
    assert response.status_code == 202, response.text
    second = run(response.json()["uid"])
    assert second["status"] == "completed", second
    assert first["document"] == second["document"]
    assert store.count(D) == 1


def test_expired_document_is_not_allocated_and_name_only_requires_input(intake):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    parser.payload["expiration_date"] = "2025-01-01"
    first = run(upload(client)["uid"])
    assert first["status"] == "completed" and first["stage"] == "unallocated", first
    assert client.get(f"/cases/{case}").json()["document_uids"] == []
    parser.payload.pop("date_of_birth")
    second = run(upload(client)["uid"])
    assert second["status"] == "needs_input", second


def test_existing_normal_extraction_is_reused_without_duplicate_document(intake):
    from tests.api.test_document_processing import upload as upload_for_person

    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    response = upload_for_person(client, person)
    assert response.status_code == 202, response.text
    extracted = run(response.json()["uid"])
    assert extracted["status"] == "completed", extracted
    result = run(upload(client)["uid"])
    assert result["status"] == "completed", result
    assert result["document"] == extracted["document"]
    assert result["completion"]["reason_code"] == "existing_revision_reused"
    assert store.count(D) == store.count(RAW) == 1
    assert client.get(f"/cases/{case}").json()["document_uids"] == [extracted["document"]["uid"]]


def test_pending_evidence_does_not_hide_count_shortfall_or_allow_duplicates(intake):
    from copy import deepcopy
    from types import SimpleNamespace

    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    first = run(upload(client)["uid"])
    assert first["completion"]["decision"] == "needs_review"
    snapshot = current[0].evaluation_input(case)
    requirement = next(
        r
        for r in snapshot["policy"]["requirements"]
        if any(o["document_type"] == "passport" for o in r["options"])
    )
    snapshot["policy"]["requirements"] = [requirement]
    requirement["min_count"] = 2
    candidate = deepcopy(snapshot["documents"][0])
    candidate.update(uid=str(uuid4()), source_hashes=["2" * 64])
    service = SimpleNamespace(evaluation_input=lambda uid: snapshot)
    assert allocation.eligible(service, case, candidate)[0] == [requirement["key"]]
    # An identical source cannot count as a second document, even before either review.
    duplicate = {**candidate, "source_hashes": snapshot["documents"][0]["source_hashes"]}
    assert allocation.eligible(service, case, duplicate)[0] == []
    assert allocation.eligible(service, case, {**candidate, "review_status": "rejected"})[0] == []
    requirement["min_count"] = 1
    assert allocation.eligible(service, case, candidate)[0] == []
    assert snapshot["documents"][0]["accepted"] is False


def test_document_changed_after_planning_is_not_silently_linked(intake, monkeypatch):
    client, current, store, bucket, dispatcher, parser, run = intake
    person = make_person(client)
    case = build(client, person, "new_loan")
    original = allocation.eligible
    changed = []

    def concurrent_edit(app, case_uid, document):
        outcome = original(app, case_uid, document)
        if not changed:
            uid = document["uid"]
            saved = client.get(f"/documents/{uid}").json()
            response = client.patch(
                f"/documents/{uid}/draft",
                json=command(
                    expected_revision=saved["revision"],
                    payload={**saved["payload"], "passport_number": "CORRECTED-002"},
                    raw_document_refs=saved["raw_document_refs"],
                ),
            )
            assert response.status_code == 200, response.text
            changed.append(uid)
        return outcome

    monkeypatch.setattr(allocation, "eligible", concurrent_edit)
    result = run(upload(client)["uid"])
    assert changed
    assert result["status"] == "failed", result
    assert result["targets"][0]["error_code"] == "document_revision_changed_review_required"
    assert client.get(f"/cases/{case}").json()["document_uids"] == []
    assert store.count(EV) == 0


def test_requester_directory_refresh_fails_closed_and_never_expands_role(intake, monkeypatch):
    from importlib import reload
    from types import SimpleNamespace

    client, current, store, bucket, dispatcher, parser, run = intake
    # Use the production resolver, not the fixture's directory stand-in.
    original = reload(allocation).requester_app
    uid = upload(client)["uid"]
    row = store.one(RUN, uid=uid)
    worker = workflow.Worker(
        Application(uuid4(), organization_admin=True, store=store), parser=parser, bucket=bucket
    )
    monkeypatch.setattr(
        allocation.User,
        "get_by_uid",
        lambda uid: SimpleNamespace(
            uid=uid,
            is_active=True,
            blocked_access=False,
            is_organization_admin=True,
            active_team_uids=[],
        ),
    )
    resolved = original(worker, row)
    assert resolved.actor == current[0].actor and not resolved.reviewer
    monkeypatch.setattr(
        allocation.User, "get_by_uid", lambda uid: SimpleNamespace(uid=uid, is_active=False)
    )
    with pytest.raises(allocation.ProcessingError):
        original(worker, row)

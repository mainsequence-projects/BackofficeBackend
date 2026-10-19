"""Explicit business cases reuse the existing authorized evidence engine."""

from uuid import UUID, uuid4

import pytest

from src.backoffice.services.application import A, Application
from tests.api.test_document_processing import flow as flow
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person


@pytest.mark.parametrize(
    "kind,policy",
    [("new_loan", "loan_requirements"), ("account_opening", "new_account_requirements")],
)
def test_explicit_case_is_pinned_and_shares_legacy_engine(business, kind, policy):
    client, current, _ = business
    subject = make_person(client)
    body = command(
        subject_uid=subject, case_type_key=kind, document_set_key=policy, document_set_version=1
    )
    response = client.post("/cases", json=body)
    assert response.status_code == 201, response.text
    uid = response.json()["uid"]
    assert client.post("/cases", json=body).json() == response.json()
    detail = client.get(f"/cases/{uid}").json()
    assert detail["subject_uid"] == subject
    assert detail["case_type_key"] == kind == detail["case_type"]["key"]
    assert detail["document_set_key"] == policy and detail["document_set_version"] == 1
    assert detail["document_uids"] == []
    legacy = client.get(f"/assignments/{uid}").json()
    assert legacy["uid"] == uid and "case_type_key" not in legacy
    assert legacy["set_version"] == 1
    assert client.get(f"/persons/{subject}/cases").json()["items"] == [detail]
    assert client.get(f"/cases?case_type_key={kind}").json()["total_items"] == 1
    assert client.get("/cases?case_type_key=unknown").json()["total_items"] == 0
    snapshot = current[0].evaluation_input(uid)
    assert client.get(f"/cases/{uid}/workspace").json()["case"] == detail
    for suffix in ("status", "missing-requirements", "reviewers", "evaluations"):
        canonical = client.get(f"/cases/{uid}/{suffix}").json()
        compatible = client.get(f"/assignments/{uid}/{suffix}").json()
        for value in (canonical, compatible):
            value.pop("assessed_at", None)
        assert canonical == compatible

    evaluated = client.post(f"/cases/{uid}/evaluations", json=command(expected_revision=1))
    assert evaluated.status_code == 201, evaluated.text
    assert len(client.get(f"/assignments/{uid}/evaluations").json()["items"]) == 1
    assert current[0].evaluation_input(uid) == snapshot


def test_case_type_and_exact_policy_are_required_and_authorized(business):
    client, current, store = business
    subject = make_person(client)
    body = command(
        subject_uid=subject, document_set_key="loan_requirements", document_set_version=1
    )
    assert client.post("/cases", json=body).status_code == 422
    body["case_type_key"] = "account_opening"
    invalid = client.post("/cases", json=body)
    assert invalid.status_code == 422 and "not_permitted" in invalid.text
    body["case_type_key"] = "new_loan"
    body["document_set_version"] = 999
    assert client.post("/cases", json=body).status_code == 404
    body["document_set_version"] = 1
    created = client.post("/cases", json=body).json()["uid"]
    current[0] = Application(uuid4(), store=store)
    assert client.get(f"/cases/{created}").status_code == 404
    assert client.get(f"/persons/{subject}/cases").status_code == 404
    assert client.post("/cases", json={**body, "operation_key": str(uuid4())}).status_code == 404
    assert client.get("/cases").json()["total_items"] == 0


def test_legacy_rollout_null_type_is_resolved_without_changing_inputs(business):
    client, current, store = business
    subject = make_person(client)
    created = client.post(
        f"/persons/{subject}/document-sets",
        json=command(document_set_key="loan_requirements", document_set_version=1),
    ).json()
    uid = created["uid"]
    snapshot = current[0].evaluation_input(uid)
    assert store.one(A, uid=uid)["case_type_key"] == "new_loan"
    store.execute(
        A.update().where(A.c.uid == UUID(uid)).values(case_type_key=None), operation="update"
    )
    assert client.get(f"/cases/{uid}").json()["case_type_key"] == "new_loan"
    assert client.get("/cases?case_type_key=new_loan").json()["total_items"] == 1
    assert current[0].evaluation_input(uid) == snapshot
    assert "case_type_key" not in client.get(f"/persons/{subject}/assignments").json()["items"][0]


def test_case_type_catalog_limits_creation_to_explicit_published_bindings(business):
    client, _, _ = business
    types = {t["key"]: t for t in client.get("/case-types").json()["items"]}
    assert set(types) == {"new_loan", "account_opening", "document_review"}
    for key, policy in (
        ("new_loan", "loan_requirements"),
        ("account_opening", "new_account_requirements"),
    ):
        assert types[key]["document_sets"]
        assert {p["key"] for p in types[key]["document_sets"]} == {policy}


@pytest.mark.parametrize("product,kind", [("loan", "new_loan"), ("account", "account_opening")])
def test_explicit_cases_use_shared_cited_comparison_worker(flow, document_fixture, product, kind):
    from tests.api.test_document_comparisons import ComparisonParser, prepare
    from tests.api.test_document_processing import worker

    client, current, store, bucket, dispatcher, subject, _ = flow
    legacy_uid, docs = prepare(flow, document_fixture, product)
    old = client.get(f"/assignments/{legacy_uid}").json()
    result = client.post(
        "/cases",
        json=command(
            subject_uid=subject,
            case_type_key=kind,
            document_set_key=old["set_key"],
            document_set_version=old["set_version"],
        ),
    )
    assert result.status_code == 201
    uid = result.json()["uid"]
    assert (
        client.put(
            f"/cases/{uid}/documents", json=command(expected_revision=1, document_uids=docs)
        ).status_code
        == 200
    )
    started = client.post(f"/cases/{uid}/evaluations", json=command(expected_revision=2))
    assert started.status_code == 202, started.text
    run = started.json()["processing_run_uid"]
    assert dispatcher.calls[-1] == run
    parser = ComparisonParser()
    completed = worker(current, bucket, parser, store).run(run)
    assert completed["status"] == "completed"
    view = client.get(f"/cases/{uid}/workspace").json()
    assert view["case"]["case_type_key"] == kind
    assert not view["latest_evaluation"]["stale"]
    assert any(
        r.get("citations")
        for f in view["latest_evaluation"]["findings"]
        for r in f["document_references"]
    )
    assert len(parser.calls) == 1

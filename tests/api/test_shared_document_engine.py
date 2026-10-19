"""Loan and account assignments share processing contracts, reviews and evaluation."""

from datetime import UTC, datetime

import pytest

from src.backoffice.services.application import SETS, publish_catalog
from tests.api.test_document_processing import Parser, upload, worker
from tests.api.test_document_processing import flow as flow
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, document, make_person, post


def test_readiness_requires_every_catalog_policy_and_publication_is_repeatable(business):
    client, _, store = business
    assert client.get("/readyz").status_code == 200
    publish_catalog(store)
    store.change(SETS, {"set_key": "loan_requirements", "version": 1}, {"status": "draft"})
    assert client.get("/readyz").status_code == 503


@pytest.mark.parametrize(
    "kind,requirement",
    [
        ("loan_contract", "loan_contract"),
        ("employer_confirmation", "employer_confirmation"),
        ("tax_clearance_certificate", "tax_certificate"),
    ],
)
def test_new_types_use_the_same_submission_review_and_staleness_rules(
    business, document_fixture, kind, requirement
):
    client, current, _ = business
    current[0].reviewer = True
    person = make_person(client)
    assignment = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="loan_requirements",
        document_set_version=1,
    )
    payload = document_fixture(kind)
    payload["issue_date"] = datetime.now(UTC).date().isoformat()
    uid = document(client, person, kind, payload)
    assert (
        client.put(
            f"/assignments/{assignment['uid']}/documents",
            json=command(expected_revision=1, document_uids=[uid]),
        ).status_code
        == 200
    )

    def finding():
        result = client.get(f"/assignments/{assignment['uid']}/status").json()
        return next(f for f in result["findings"] if f["requirement_key"] == requirement)

    assert finding()["status"] == "pending_review"
    decision = command(
        expected_revision=1,
        expected_decision_sequence=0,
        decision="accepted",
        reason="Compared with source",
    )
    assert client.post(f"/documents/{uid}/reviews", json=decision).status_code == 201
    assert finding()["status"] == "satisfied"
    report = post(client, f"/assignments/{assignment['uid']}/evaluations", expected_revision=2)
    evaluation = client.get(f"/evaluations/{report['uid']}").json()
    assert not evaluation["stale"]
    assert not evaluation["summary"]["complete"]  # Printed contract list cannot waive requirements.
    assert "not credit approval" in evaluation["summary"]["policy_notice"]
    doc = client.get(f"/documents/{uid}").json()
    response = client.patch(
        f"/documents/{uid}/draft",
        json=command(
            expected_revision=1, payload=payload, raw_document_refs=doc["raw_document_refs"]
        ),
    )
    assert response.status_code == 200, response.text
    assert client.get(f"/evaluations/{report['uid']}").json()["stale"]
    assert client.get(f"/documents/{uid}/revisions/1").json()["accepted"]
    assert not client.get(f"/documents/{uid}").json()["accepted"]


def test_one_reviewed_identity_can_support_loan_and_account_assignments(business, document_fixture):
    client, current, _ = business
    current[0].reviewer = True
    person = make_person(client)
    identity = document(
        client, person, "national_identity_card", document_fixture("national_identity_card")
    )
    assignments = [
        post(
            client, f"/persons/{person}/document-sets", document_set_key=key, document_set_version=1
        )
        for key in ("new_account_requirements", "loan_requirements")
    ]
    for assignment in assignments:
        response = client.put(
            f"/assignments/{assignment['uid']}/documents",
            json=command(expected_revision=1, document_uids=[identity]),
        )
        assert response.status_code == 200
    review = post(
        client,
        f"/documents/{identity}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision="accepted",
        reason="Same identity evidence for both assignments",
    )
    for assignment in assignments:
        result = client.get(f"/assignments/{assignment['uid']}/status").json()
        finding = next(f for f in result["findings"] if f["requirement_key"] == "identity")
        assert finding["status"] == "satisfied"
        assert finding["document_references"][0]["review_uid"] == review["uid"]


@pytest.mark.parametrize(
    "kind", ["loan_contract", "employer_confirmation", "tax_clearance_certificate"]
)
def test_new_types_use_the_existing_worker_and_default_eighty_percent_policy(flow, document_fixture, kind):
    client, current, store, bucket, _, _, _ = flow
    person = make_person(client)
    parser = Parser(document_fixture(kind), kind=kind)
    response = upload(client, person)
    assert response.status_code == 202, response.text
    result = worker(current, bucket, parser, store).run(response.json()["uid"])
    assert result["status"] == "completed", result
    assert result["completion"]["decision"] == "needs_review"
    assert result["completion"]["reason_code"] == "parsing_score_below_threshold"
    request = parser.extractions[0]
    assert request.document_type == kind
    assert request.contract_version == 2  # Same evidence path as account documents.
    doc = client.get(f"/documents/{result['document']['uid']}").json()
    assert doc["status"] == "submitted" and not doc["accepted"]

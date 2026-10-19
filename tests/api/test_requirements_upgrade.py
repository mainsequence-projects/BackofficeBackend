"""Existing evidence adopts relaxed contracts without losing reviews or history."""

import pytest

from src.backoffice.services.application import DR, RV
from src.backoffice.services.casework import lane
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, document, make_person, post, source


def upgrade(client, person, body=None):
    response = client.post(
        f"/admin/persons/{person}/happy-case-requirements", json=body or command()
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
def test_upgrade_preserves_evidence_reviews_and_history(business, document_fixture, decision):
    client, current, store = business
    current[0].organization_admin = current[0].reviewer = True
    person = make_person(client)
    case = post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="loan_requirements",
        document_set_version=3,
    )
    uid = document(
        client, person, "national_identity_card", document_fixture("national_identity_card")
    )
    post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=0,
        decision=decision,
        reason="Reviewed original source",
    )
    original = store.one(DR, document_uid=uid, revision=1)
    original_review = store.rows(RV)[0]
    body = command()
    result = upgrade(client, person, body)
    assert upgrade(client, person, body) == result
    latest = client.get(f"/documents/{uid}").json()
    assert latest["schema_version"] == 2
    assert latest["revision"] == 2
    assert latest["payload"] == original["payload"]
    assert latest["raw_document_refs"] == original["raw_document_refs"]
    assert latest["status"] == "submitted"
    assert latest["latest_review"]["decision"] == decision
    assert latest["latest_review"]["reviewed_by"] == original_review["reviewed_by"]
    assert original_review["uid"] in latest["latest_review"]["reason"]
    assert store.one(DR, document_uid=uid, revision=1) == original
    assert client.get(f"/cases/{case['uid']}").json()["document_set_version"] == 4
    again = upgrade(client, person)
    assert again["documents"] == again["cases"] == []


def test_upgrade_rechecks_trusted_score_under_relaxed_contract(business):
    client, current, _ = business
    current[0].organization_admin = current[0].reviewer = True
    person = make_person(client)
    payload = {
        "document_type": "national_identity_card",
        "full_name": "Alex Morgan",
        "date_of_birth": "1990-03-12",
        "identity_number": "ID-123",
        "expiration_date": "2035-01-01",
    }
    uid = post(
        client,
        f"/persons/{person}/documents",
        document_type="national_identity_card",
        schema_version=1,
        payload=payload,
        raw_document_refs=[{"raw_document_uid": source(client, person)}],
    )["uid"]
    response = client.put(
        "/admin/parsing-settings",
        json=command(
            document_type="national_identity_card",
            expected_revision=0,
            automatic_acceptance_enabled=True,
            acceptance_threshold_percent="90",
        ),
    )
    assert response.status_code == 200, response.text
    prior = post(
        client,
        f"/documents/{uid}/parsing-results",
        expected_revision=1,
        parsing_score_percent="99",
        extractor="trusted-test",
    )
    assert prior["reason_code"] == "invalid_document_attributes"
    body = command()
    result = upgrade(client, person, body)
    assert upgrade(client, person, body) == result
    latest = client.get(f"/documents/{uid}").json()
    assert latest["payload"] == payload
    assert latest["schema_version"] == 2
    assert latest["accepted"] is True
    assert latest["parsing_result"]["reason_code"] == "parsing_score_meets_threshold"
    assert "issue_date" not in latest["payload"]


def test_upgrade_is_admin_only_and_does_not_accept_manual_drafts(business):
    client, current, _ = business
    person = make_person(client)
    path = f"/admin/persons/{person}/happy-case-requirements"
    assert client.post(path, json=command()).status_code == 403
    current[0].organization_admin = True
    uid = post(
        client,
        f"/persons/{person}/documents",
        document_type="national_identity_card",
        payload={"full_name": "Alex Morgan"},
        raw_document_refs=[],
    )["uid"]
    upgrade(client, person)
    latest = client.get(f"/documents/{uid}").json()
    assert latest["schema_version"] == 2
    assert latest["status"] == "draft"
    assert latest["accepted"] is False


def test_optional_findings_do_not_make_a_complete_case_incomplete():
    assert (
        lane(
            {
                "summary": {"complete": True},
                "findings": [
                    {"mandatory": False, "status": "missing"},
                    {"mandatory": True, "status": "satisfied"},
                ],
            }
        )
        == "checks_satisfied"
    )
    assert (
        lane(
            {
                "summary": {"complete": False},
                "findings": [
                    {"mandatory": False, "status": "missing"},
                    {"mandatory": True, "status": "pending_review"},
                ],
            }
        )
        == "review_required"
    )


def test_multiple_accepted_documents_keep_distinct_review_and_parsing_keys(
    business, document_fixture
):
    client, current, _ = business
    current[0].organization_admin = current[0].reviewer = True
    person = make_person(client)
    response = client.put(
        "/admin/parsing-settings",
        json=command(
            document_type="national_identity_card",
            expected_revision=0,
            automatic_acceptance_enabled=True,
            acceptance_threshold_percent="90",
        ),
    )
    assert response.status_code == 200
    uids = []
    for index in range(2):
        uid = post(
            client,
            f"/persons/{person}/documents",
            document_type="national_identity_card",
            payload=document_fixture("national_identity_card"),
            raw_document_refs=[{"raw_document_uid": source(client, person, str(index).encode())}],
        )["uid"]
        post(
            client,
            f"/documents/{uid}/parsing-results",
            expected_revision=1,
            parsing_score_percent="99",
            extractor="trusted-test",
        )
        uids.append(uid)
    upgrade(client, person)
    for uid in uids:
        row = client.get(f"/documents/{uid}").json()
        assert row["accepted"] is True
        assert row["revision"] == 2
        assert row["parsing_result"]["parsing_score_percent"] == "99.00"

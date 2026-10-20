"""Manual review records a decision; writing a justification is optional."""

import pytest

from src.backoffice.models.document import DocumentReview
from src.backoffice.services.application import RV
from src.backoffice.services.contracts import ReviewDocument
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, document, make_person


@pytest.mark.parametrize("decision", ["accepted", "rejected"])
@pytest.mark.parametrize(
    "comments,expected",
    [
        ({}, ""),
        ({"comments": ""}, ""),
        ({"comments": "Source checked."}, "Source checked."),
        ({"reason": "Legacy client comment."}, "Legacy client comment."),
    ],
)
def test_review_comments_are_optional_and_legacy_clients_still_work(
    business, document_fixture, decision, comments, expected
):
    client, current, store = business
    current[0].reviewer = True
    person = make_person(client)
    uid = document(client, person, "passport", document_fixture("passport"))
    body = command(expected_revision=1, expected_decision_sequence=0, decision=decision, **comments)
    path = f"/documents/{uid}/reviews"
    response = client.post(path, json=body)
    assert response.status_code == 201, response.text
    assert client.post(path, json=body).json() == response.json()
    assert store.count(RV) == 1
    latest = client.get(f"/documents/{uid}").json()
    assert latest["review_status"] == decision
    assert latest["accepted"] is (decision == "accepted")
    assert latest["latest_review"]["reason"] == expected
    review = DocumentReview.model_validate(
        {
            key: value
            for key, value in latest["latest_review"].items()
            if key in DocumentReview.model_fields
        }
    )
    assert review.reason == expected


def test_optional_comments_do_not_grant_reviewer_permission(business, document_fixture):
    client, _, store = business
    person = make_person(client)
    uid = document(client, person, "passport", document_fixture("passport"))
    response = client.post(
        f"/documents/{uid}/reviews",
        json=command(expected_revision=1, expected_decision_sequence=0, decision="accepted"),
    )
    assert response.status_code == 403
    assert store.count(RV) == 0


def test_review_contract_describes_optional_comments():
    schema = ReviewDocument.model_json_schema()
    assert "comments" in schema["properties"]
    assert "comments" not in schema["required"]
    assert schema["properties"]["comments"]["title"] == "Review comments"

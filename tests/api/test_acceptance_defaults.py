"""Automatic acceptance defaults are effective, versioned and recoverable."""

import pytest

from src.backoffice.services.parsing import POLICY
from tests.api.test_parsing_admin import complete, draft, policy
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post, source


def test_all_document_types_read_on_at_eighty_without_writing(business):
    client, current, store = business
    current[0].organization_admin = True
    kinds = {row["document_type"] for row in client.get("/document-types").json()["items"]}
    assert len(kinds) == 13
    for kind in kinds:
        settings = client.get(f"/admin/parsing-settings?document_type={kind}").json()
        assert settings["automatic_acceptance_enabled"] is True
        assert settings["acceptance_threshold_percent"] == "80.00"
        assert settings["revision"] == 0
    assert store.count(POLICY) == 0


@pytest.mark.parametrize(
    "score,accepted", [("80", True), ("79.99", False), ("100", True), (None, False)]
)
def test_default_threshold_is_used_and_saved_in_the_decision(
    business, document_fixture, score, accepted
):
    client, current, store = business
    # Trusted processors can initialize the built-in default, without receiving
    # permission to change administrator settings.
    current[0].parsing_processor = True
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    result = complete(client, uid, score)
    assert result.status_code == 201, result.text
    saved = client.get(f"/documents/{uid}").json()
    assert saved["accepted"] is accepted
    assert saved["parsing_result"]["policy_revision"] == 1
    assert saved["parsing_result"]["acceptance_threshold_percent"] == "80.00"
    assert store.count(POLICY) == 1
    assert (
        client.get("/admin/parsing-settings?document_type=national_identity_card").status_code
        == 403
    )


@pytest.mark.parametrize("enabled,threshold", [(False, None), (True, "95")])
def test_explicit_overrides_are_not_replaced_by_defaults(
    business, document_fixture, enabled, threshold
):
    client, current, store = business
    policy(client, current, threshold, enabled=enabled)
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    assert complete(client, uid, "80").json()["decision"] == "needs_review"
    assert store.count(POLICY) == 1


@pytest.mark.parametrize("fail_after", [1, 2, 3, 4])
def test_default_initialization_recovers_after_lost_write_responses(
    business, document_fixture, fail_after
):
    client, current, store = business
    current[0].organization_admin = True
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    body = command(expected_revision=1, parsing_score_percent="80", extractor="fixture")
    store.fail_after_write = fail_after
    with pytest.raises(TimeoutError):
        client.post(f"/documents/{uid}/parsing-results", json=body)
    response = client.post(f"/documents/{uid}/parsing-results", json=body)
    assert response.status_code == 201, response.text
    assert client.post(f"/documents/{uid}/parsing-results", json=body).json() == response.json()
    assert client.get(f"/documents/{uid}").json()["accepted"] is True
    assert store.count(POLICY) == 1


def test_default_policy_does_not_accept_incomplete_or_sourceless_documents(business):
    client, current, _ = business
    current[0].organization_admin = True
    person = make_person(client)
    uid = post(client, f"/persons/{person}/documents", document_type="passport", payload={})["uid"]
    response = complete(client, uid, "100")
    assert response.json()["decision"] == "needs_review"
    assert response.json()["reason_code"] == "invalid_document_attributes"

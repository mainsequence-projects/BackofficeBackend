"""Real API/storage checks for admin policy and trusted score-based decisions."""

from uuid import uuid4

import pytest

from src.backoffice.services.application import Application
from src.backoffice.tables.parsing import ParsingPolicyRecord, ParsingResultRecord
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, document, make_person, post, source


def admin(current):
    current[0].organization_admin = True
    current[0].reviewer = True


def policy(
    client,
    current,
    threshold="95.00",
    enabled=True,
    revision=0,
    document_type="national_identity_card",
):
    admin(current)
    response = client.put(
        "/admin/parsing-settings",
        json=command(
            document_type=document_type,
            expected_revision=revision,
            automatic_acceptance_enabled=enabled,
            acceptance_threshold_percent=threshold,
        ),
    )
    assert response.status_code == 200, response.text
    return response.json()


def draft(client, person, payload, raw=None):
    return post(
        client,
        f"/persons/{person}/documents",
        document_type="national_identity_card",
        payload=payload,
        raw_document_refs=[{"raw_document_uid": raw}] if raw else [],
    )["uid"]


def complete(client, uid, score, **extra):
    return client.post(
        f"/documents/{uid}/parsing-results",
        json=command(
            expected_revision=1,
            parsing_score_percent=score,
            extractor="fixture-parser-v1",
            **extra,
        ),
    )


def test_admin_is_not_inferred_from_reviewer_and_all_routes_deny(business):
    client, current, _ = business
    current[0].reviewer = True
    assert client.get("/me").json()["is_organization_admin"] is False
    assert (
        client.get("/admin/parsing-settings?document_type=national_identity_card").status_code
        == 403
    )
    assert (
        client.put(
            "/admin/parsing-settings",
            json=command(
                document_type="national_identity_card",
                expected_revision=0,
                automatic_acceptance_enabled=True,
                acceptance_threshold_percent="95",
            ),
        ).status_code
        == 403
    )
    assert complete(client, uuid4(), "100").status_code == 403


def test_settings_are_versioned_idempotent_and_never_retroactive(business):
    client, current, store = business
    admin(current)
    assert (
        client.get("/admin/parsing-settings?document_type=national_identity_card").json()[
            "revision"
        ]
        == 0
    )
    payload = command(
        document_type="national_identity_card",
        expected_revision=0,
        automatic_acceptance_enabled=True,
        acceptance_threshold_percent="95.25",
    )
    saved = client.put("/admin/parsing-settings", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["acceptance_threshold_percent"] == "95.25"
    assert client.put("/admin/parsing-settings", json=payload).json() == saved.json()
    assert store.count(ParsingPolicyRecord.__table__) == 1
    assert (
        client.put(
            "/admin/parsing-settings",
            json=command(
                document_type="national_identity_card",
                expected_revision=0,
                automatic_acceptance_enabled=False,
            ),
        ).status_code
        == 409
    )
    policy(client, current, "99", revision=1)
    assert store.count(ParsingPolicyRecord.__table__) == 2
    assert client.put("/admin/parsing-settings", json=payload).json() == saved.json()
    assert (
        client.get("/admin/parsing-settings?document_type=national_identity_card").json()[
            "revision"
        ]
        == 2
    )


@pytest.mark.parametrize("threshold", [None, "-1", "100.01", "95.001", "NaN", "Infinity", True])
def test_invalid_enabled_thresholds_are_rejected(business, threshold):
    client, current, _ = business
    admin(current)
    response = client.put(
        "/admin/parsing-settings",
        json=command(
            document_type="national_identity_card",
            expected_revision=0,
            automatic_acceptance_enabled=True,
            acceptance_threshold_percent=threshold,
        ),
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "score,accepted", [("95", True), ("94.99", False), ("100", True), ("0", False), (None, False)]
)
def test_threshold_applies_to_exact_revision_and_retains_policy(
    business, document_fixture, score, accepted
):
    client, current, store = business
    policy(client, current)
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    response = complete(client, uid, score)
    assert response.status_code == 201, response.text
    assert response.json()["decision"] == ("accepted" if accepted else "needs_review")
    doc = client.get(f"/documents/{uid}").json()
    assert doc["status"] == "submitted"
    assert doc["accepted"] is accepted
    assert doc["parsing_result"]["policy_revision"] == 1
    assert doc["parsing_result"]["acceptance_threshold_percent"] == "95.00"
    assert store.count(ParsingResultRecord.__table__) == 1
    policy(client, current, "100", revision=1)
    retained = client.get(f"/documents/{uid}/revisions/1").json()
    assert retained["accepted"] is accepted
    assert retained["parsing_result"]["policy_revision"] == 1


@pytest.mark.parametrize("missing", ["payload", "source"])
def test_high_score_cannot_bypass_document_validation(business, document_fixture, missing):
    client, current, _ = business
    policy(client, current)
    person = make_person(client)
    uid = draft(
        client,
        person,
        {} if missing == "payload" else document_fixture("national_identity_card"),
        None if missing == "source" else source(client, person),
    )
    response = complete(client, uid, "100")
    assert response.status_code == 201, response.text
    doc = client.get(f"/documents/{uid}").json()
    assert doc["accepted"] is False
    assert doc["status"] == "draft"
    assert doc["parsing_result"]["decision"] == "needs_review"


def test_processing_role_is_separate_and_cannot_rewrite_human_reviews(business, document_fixture):
    client, current, store = business
    policy(client, current)
    person = make_person(client)
    uid = document(
        client, person, "national_identity_card", document_fixture("national_identity_card")
    )
    original = current[0]
    current[0] = Application(uuid4(), store=store, parsing_processor=True)
    assert (
        client.get("/admin/parsing-settings?document_type=national_identity_card").status_code
        == 403
    )
    response = complete(client, uid, "95")
    assert response.status_code == 201, response.text
    current[0] = original
    post(
        client,
        f"/documents/{uid}/reviews",
        expected_revision=1,
        expected_decision_sequence=1,
        decision="rejected",
        reason="Human source inspection",
    )
    assert client.get(f"/documents/{uid}").json()["accepted"] is False
    assert complete(client, uid, "100").status_code == 409


def test_stale_revision_and_duplicate_results_cannot_accept_a_different_revision(
    business, document_fixture
):
    client, current, _ = business
    policy(client, current)
    person = make_person(client)
    raw = source(client, person)
    payload = document_fixture("national_identity_card")
    uid = draft(client, person, payload, raw)
    body = command(expected_revision=1, parsing_score_percent="95", extractor="fixture-parser-v1")
    first = client.post(f"/documents/{uid}/parsing-results", json=body)
    assert first.status_code == 201
    assert client.post(f"/documents/{uid}/parsing-results", json=body).json() == first.json()
    post(
        client,
        f"/documents/{uid}/revisions",
        expected_revision=1,
        payload=payload,
        raw_document_refs=[{"raw_document_uid": raw}],
    )
    assert complete(client, uid, "100").status_code == 409
    assert client.get(f"/documents/{uid}").json()["accepted"] is False


def test_default_policy_accepts_and_lost_admin_cannot_resume_settings(business, document_fixture):
    client, current, store = business
    admin(current)
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    assert complete(client, uid, "100").json()["decision"] == "accepted"
    payload = command(
        document_type="national_identity_card",
        expected_revision=1,
        automatic_acceptance_enabled=True,
        acceptance_threshold_percent="95",
    )
    store.fail_after_write = 2
    with pytest.raises(TimeoutError):
        client.put("/admin/parsing-settings", json=payload)
    current[0].organization_admin = False
    assert client.post(f"/operations/{payload['operation_key']}/resume").status_code == 403
    current[0].organization_admin = True
    assert client.put("/admin/parsing-settings", json=payload).status_code == 200


def test_passport_and_bank_statement_have_independent_thresholds(business, document_fixture):
    client, current, store = business
    passport_policy = policy(client, current, "60", document_type="passport")
    bank_policy = policy(client, current, "90", document_type="bank_statement")
    assert passport_policy["revision"] == bank_policy["revision"] == 1
    assert passport_policy["document_type"] == "passport"
    assert passport_policy["score_kind"] == "classification_confidence"
    person = make_person(client)
    for kind, accepted in [("passport", True), ("bank_statement", False)]:
        uid = post(
            client,
            f"/persons/{person}/documents",
            document_type=kind,
            payload=document_fixture(kind),
            raw_document_refs=[{"raw_document_uid": source(client, person)}],
        )["uid"]
        response = complete(client, uid, "60")
        assert response.status_code == 201, response.text
        assert response.json()["decision"] == ("accepted" if accepted else "needs_review")
        record = client.get(f"/documents/{uid}").json()
        assert record["accepted"] is accepted
        assert record["parsing_result"]["policy_document_type"] == kind
        assert record["parsing_result"]["document_type"] == kind
    policy(client, current, "80", revision=1, document_type="passport")
    assert client.get("/admin/parsing-settings?document_type=passport").json()["revision"] == 2
    assert (
        client.get("/admin/parsing-settings?document_type=bank_statement").json()["revision"] == 1
    )
    assert store.count(ParsingPolicyRecord.__table__) == 3


def test_other_type_and_legacy_global_policies_never_authorize_acceptance(
    business, document_fixture
):
    from datetime import UTC, datetime

    client, current, store = business
    policy(client, current, "0", document_type="passport")
    store.ensure(
        ParsingPolicyRecord.__table__,
        {
            "uid": str(uuid4()),
            "created_at": datetime.now(UTC).isoformat(),
            "settings_key": "document_parsing",
            "document_type": None,
            "revision": 100,
            "automatic_acceptance_enabled": True,
            "threshold_basis_points": 0,
            "changed_by": current[0].actor,
            "operation_key": str(uuid4()),
        },
    )
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    response = complete(client, uid, "79.99")
    assert response.json()["decision"] == "needs_review"
    assert response.json()["reason_code"] == "parsing_score_below_threshold"
    settings = client.get("/admin/parsing-settings?document_type=national_identity_card").json()
    assert settings["revision"] == 1 and settings["automatic_acceptance_enabled"] is True
    assert settings["acceptance_threshold_percent"] == "80.00"


@pytest.mark.parametrize(
    "enabled,score,expected",
    [(False, "100", "needs_review"), (True, None, "needs_review"), (True, "0", "accepted")],
)
def test_zero_cutoff_and_disabled_policies(business, document_fixture, enabled, score, expected):
    client, current, _ = business
    policy(client, current, "0", enabled=enabled)
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    result = complete(client, uid, score)
    assert result.status_code == 201
    assert result.json()["decision"] == expected


def test_settings_requires_supported_explicit_type_and_replay_cannot_change_type(business):
    client, current, _ = business
    admin(current)
    assert client.get("/admin/parsing-settings").status_code == 422
    assert client.get("/admin/parsing-settings?document_type=unknown").status_code == 422
    body = command(
        expected_revision=0, automatic_acceptance_enabled=True, acceptance_threshold_percent="60"
    )
    assert client.put("/admin/parsing-settings", json=body).status_code == 422
    assert (
        client.put("/admin/parsing-settings", json={**body, "document_type": "unknown"}).status_code
        == 422
    )
    body["document_type"] = "passport"
    saved = client.put("/admin/parsing-settings", json=body)
    assert saved.status_code == 200
    assert (
        client.put(
            "/admin/parsing-settings", json={**body, "document_type": "bank_statement"}
        ).status_code
        == 409
    )


@pytest.mark.parametrize("score", ["NaN", "Infinity", True, "100.01", "-1", "59.999"])
def test_completion_rejects_invalid_score_instead_of_rounding_up(business, document_fixture, score):
    client, current, _ = business
    policy(client, current, "60")
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    assert complete(client, uid, score).status_code == 422
    assert client.get(f"/documents/{uid}").json()["accepted"] is False


def test_recovery_uses_frozen_policy_even_after_type_policy_changed(business, document_fixture):
    client, current, store = business
    policy(client, current, "60")
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    body = command(expected_revision=1, parsing_score_percent="60", extractor="classifier-v1")
    store.fail_after_write = 3  # intent and applied submission survive a lost response
    with pytest.raises(TimeoutError):
        client.post(f"/documents/{uid}/parsing-results", json=body)
    policy(client, current, "90", revision=1)
    result = client.post(f"/documents/{uid}/parsing-results", json=body)
    assert result.status_code == 201, result.text
    assert result.json()["decision"] == "accepted"
    assert result.json()["policy_revision"] == 1
    saved = client.get(f"/documents/{uid}").json()["parsing_result"]
    assert saved["acceptance_threshold_percent"] == "60.00"
    assert store.count(ParsingResultRecord.__table__) == 1


def test_completion_cannot_select_a_more_permissive_document_type(business, document_fixture):
    client, current, _ = business
    policy(client, current, "60", document_type="passport")
    person = make_person(client)
    uid = draft(client, person, document_fixture("national_identity_card"), source(client, person))
    assert complete(client, uid, "100", document_type="passport").status_code == 422


@pytest.mark.parametrize("revision", [True, "1", 1.0])
def test_policy_and_completion_require_integer_revisions(business, revision):
    client, current, _ = business
    admin(current)
    body = command(
        document_type="passport",
        expected_revision=revision,
        automatic_acceptance_enabled=True,
        acceptance_threshold_percent="60",
    )
    assert client.put("/admin/parsing-settings", json=body).status_code == 422
    assert (
        client.post(
            f"/documents/{uuid4()}/parsing-results",
            json=command(
                expected_revision=revision, parsing_score_percent="60", extractor="fixture"
            ),
        ).status_code
        == 422
    )

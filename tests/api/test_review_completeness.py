"""Incomplete evidence never becomes a human-decision finding merely because it is unreviewed."""

from copy import deepcopy
from datetime import date
from uuid import uuid4

import pytest

from src.backoffice.models.document_set import DocumentOption, DocumentSet
from src.backoffice.services.casework import lane
from src.backoffice.services.comparisons import plan
from src.backoffice.services.reconciliation import assess, reconcile
from tests.api.test_workflows import business as business
from tests.api.test_workflows import command, make_person, post, source

TODAY = date(2026, 10, 19)


def test_unknown_assessment_does_not_claim_a_human_decision_is_needed():
    assert lane({"summary": {"complete": False}, "findings": []}) == "updating"


def evidence(document_fixture, **changes):
    payload = document_fixture("bank_statement")
    return {
        "uid": str(uuid4()),
        "revision": 1,
        "schema_version": 2,
        "document_type": "bank_statement",
        "status": "submitted",
        "accepted": False,
        "review_status": "pending",
        "latest_review": None,
        "source_hashes": [str(uuid4())],
        "submitted_at": "2026-10-19T10:00:00Z",
        "payload": payload,
        "parsing_result": {
            "reason_code": "parsing_score_below_threshold",
            "parsing_score_percent": "65.00",
            "acceptance_threshold_percent": "80.00",
        },
        **changes,
    }


def profile(document):
    return {
        "full_name": document["payload"]["account_holders"][0],
        "residential_address": document["payload"].get("holder_address"),
    }


def policy(min_count=1, **requirement):
    return DocumentSet.model_validate(
        {
            "key": "review_completeness",
            "version": 1,
            "name": "Review completeness",
            "description": "Verify complete evidence before a decision.",
            "requirements": [
                {
                    "key": "address",
                    "description": "Proof of address.",
                    "min_count": min_count,
                    "options": [
                        {
                            "document_type": "bank_statement",
                            "schema_version": 2,
                            "required_fields": ["holder_address.city"],
                        }
                    ],
                    **requirement,
                }
            ],
        }
    ).model_dump(mode="json")


def evaluate(document, definition=None, documents=None):
    return reconcile(
        {
            "policy": definition or policy(),
            "person": profile(document),
            "documents": documents or [document],
            "evaluation_date": TODAY.isoformat(),
        },
        diagnostics=True,
    )


@pytest.mark.parametrize("value", [None, "", "   "])
@pytest.mark.parametrize("accepted", [False, True])
def test_additional_missing_field_precedes_acceptance(document_fixture, value, accepted):
    doc = evidence(document_fixture, accepted=accepted)
    doc["payload"]["holder_address"]["city"] = value
    findings, _ = evaluate(doc)
    assert findings[0]["status"] == "needs_information"
    assert findings[0]["reason_code"] == "REQUIRED_FIELD_MISSING"
    assert findings[0]["field_paths"] == ["holder_address.city"]
    assert "holder address › city" in findings[0]["explanation"]


def test_canonical_missing_fields_precede_review_and_submission(document_fixture):
    doc = evidence(document_fixture)
    del doc["payload"]["account_identifier"]
    option = DocumentOption(document_type="bank_statement", schema_version=2)
    for state in ("draft", "submitted"):
        doc["status"] = state
        result = assess(doc, option, profile(doc), TODAY)
        assert result == ("needs_information", "REQUIRED_FIELD_MISSING", ["account_identifier"])


def test_validity_reference_and_period_checks_precede_review(document_fixture):
    doc = evidence(document_fixture)
    valid = DocumentOption(document_type="bank_statement", schema_version=2)
    assert assess(doc, valid, {}, TODAY)[1] == "REFERENCE_NAME_MISSING"
    doc["payload"]["statement_period"] = None
    assert assess(doc, valid, profile(doc), TODAY, "statement_period")[0] == "needs_information"


def test_first_review_is_not_blocked_by_absent_previous_review_date(document_fixture):
    doc = evidence(document_fixture)
    option = DocumentOption(
        document_type="bank_statement",
        schema_version=2,
        renewal_interval_months=6,
        renewal_basis="reviewed_at",
    )
    assert assess(doc, option, profile(doc), TODAY)[0] == "pending_review"


@pytest.mark.parametrize(
    "reason,status,text",
    [
        ("parsing_score_below_threshold", "pending_review", "65.00%, below the recorded 80.00%"),
        ("parsing_score_missing", "pending_review", "did not supply a classification confidence"),
        ("automatic_acceptance_disabled", "pending_review", "disabled when this revision"),
        ("parsing_policy_missing", "pending_review", "No automatic acceptance policy was recorded"),
        ("extraction_readers_disagree", "pending_review", "readers disagree"),
        ("extraction_reader_missing", "needs_information", "reader's result is missing"),
        ("extraction_evidence_incomplete", "needs_information", "complete source citations"),
    ],
)
def test_exact_recorded_acceptance_reason(document_fixture, reason, status, text):
    doc = evidence(document_fixture)
    doc["parsing_result"]["reason_code"] = reason
    findings, summary = evaluate(doc)
    assert findings[0]["status"] == status
    assert findings[0]["reason_code"] == reason.upper()
    assert text in findings[0]["explanation"]
    assert lane({"summary": summary, "findings": findings}) == (
        "review_required" if status == "pending_review" else "missing_evidence"
    )


def test_missing_document_count_precedes_pending_decisions(document_fixture):
    doc = evidence(document_fixture)
    findings, _ = evaluate(doc, policy(3))
    assert findings[0]["status"] == "missing"
    assert findings[0]["reason_code"] == "INSUFFICIENT_DISTINCT_DOCUMENTS"
    docs = [doc, evidence(document_fixture), evidence(document_fixture)]
    findings, _ = evaluate(doc, policy(3), docs)
    assert findings[0]["status"] == "pending_review"
    docs[1]["source_hashes"] = docs[0]["source_hashes"]
    findings, _ = evaluate(doc, policy(3), docs)
    assert findings[0]["status"] == "failed"
    assert findings[0]["reason_code"] == "DUPLICATE_EVIDENCE_OR_PERIOD"


def test_comparison_missing_fields_precede_document_review(document_fixture):
    doc = evidence(document_fixture)
    doc["payload"]["holder_address"]["city"] = None
    second = evidence(document_fixture)
    definition = policy()
    selector = {
        "document_type": "bank_statement",
        "schema_version": 2,
        "field": "holder_address.city",
    }
    definition["comparisons"] = [
        {
            "key": "compare_addresses",
            "description": "Compare cities",
            "topic": "City",
            "operator": "exact",
            "left": selector,
            "right": selector,
        }
    ]
    _, bindings = plan({"policy": definition, "documents": [doc, second]})
    assert ("needs_information", "COMPARISON_FIELD_MISSING") in bindings[0]["blockers"]
    assert not any(status == "pending_review" for status, _ in bindings[0]["blockers"])


def test_real_api_preserves_missing_then_exact_review_reason_and_retained_result(
    business, document_fixture
):
    client, current, _ = business
    current[0].organization_admin = current[0].reviewer = True
    person = make_person(client)
    definition = policy()
    post(client, "/admin/document-sets", definition=definition, case_type_keys=["document_review"])
    payload = document_fixture("bank_statement")
    payload["holder_address"] = None
    raw = source(client, person)
    uid = post(
        client,
        f"/persons/{person}/documents",
        document_type="bank_statement",
        schema_version=2,
        payload=payload,
        raw_document_refs=[{"raw_document_uid": raw}],
    )["uid"]
    post(client, f"/documents/{uid}/submit", expected_revision=1)
    case = post(
        client,
        "/cases",
        subject_uid=person,
        case_type_key="document_review",
        document_set_key=definition["key"],
        document_set_version=1,
    )["uid"]
    response = client.put(
        f"/assignments/{case}/documents", json=command(expected_revision=1, document_uids=[uid])
    )
    assert response.status_code == 200
    view = client.get(f"/assignments/{case}/workspace").json()
    assert view["workflow_state"] == "missing_evidence"
    assert view["status"]["findings"][0]["reason_code"] == "REQUIRED_FIELD_MISSING"
    retained = post(client, f"/assignments/{case}/evaluations", expected_revision=2)
    snapshot = deepcopy(client.get(f"/evaluations/{retained['uid']}").json())
    payload["holder_address"] = document_fixture("bank_statement")["holder_address"]
    saved = client.patch(
        f"/documents/{uid}/draft",
        json=command(
            expected_revision=1, payload=payload, raw_document_refs=[{"raw_document_uid": raw}]
        ),
    )
    assert saved.status_code == 200
    post(client, f"/documents/{uid}/submit", expected_revision=2)
    post(
        client,
        f"/documents/{uid}/parsing-results",
        expected_revision=2,
        parsing_score_percent="65.00",
        extractor="completeness-test",
    )
    view = client.get(f"/assignments/{case}/workspace").json()
    assert view["workflow_state"] == "review_required"
    finding = view["status"]["findings"][0]
    assert finding["reason_code"] == "PARSING_SCORE_BELOW_THRESHOLD"
    assert "65.00%, below the recorded 80.00%" in finding["explanation"]
    assert view["documents"][0]["review_requirement"]["status"] == "pending_review"
    queue = client.get("/review-queue").json()["items"][0]
    assert queue["top_finding"]["explanation"] == finding["explanation"]
    historical = client.get(f"/evaluations/{retained['uid']}").json()
    assert historical["findings"] == snapshot["findings"]
    assert historical["input_snapshot"] == snapshot["input_snapshot"]
    assert historical["stale"] is True

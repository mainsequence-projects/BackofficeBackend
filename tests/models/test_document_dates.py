"""Calendar boundaries, recurring reviews, and evidence age are independent."""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.backoffice.models.document_set import DocumentOption, DocumentRequirement, DocumentSet
from src.backoffice.services.document_dates import add_months, calendar_date, document_dates
from src.backoffice.services.reconciliation import assess, reconcile


def evidence(**changes):
    return {
        "uid": str(uuid4()),
        "revision": 1,
        "schema_version": 1,
        "document_type": "passport",
        "status": "submitted",
        "accepted": True,
        "review_status": "accepted",
        "latest_review": {"uid": str(uuid4()), "reviewed_at": "2026-08-31T10:00:00Z"},
        "submitted_at": "2026-08-31T09:00:00Z",
        "source_hashes": [str(uuid4())],
        "payload": {"issue_date": "2026-08-31", "expiration_date": "2030-01-01"},
        **changes,
    }


@pytest.mark.parametrize(
    "start, months, expected",
    [
        ("2026-08-31", 6, "2027-02-28"),
        ("2023-08-31", 6, "2024-02-29"),
        ("2024-02-29", 12, "2025-02-28"),
        ("2026-10-19", 6, "2027-04-19"),
    ],
)
def test_calendar_months(start, months, expected):
    assert add_months(date.fromisoformat(start), months).isoformat() == expected


def test_freshness_inclusive_and_renewal_due_on_anniversary():
    doc = evidence()
    fresh = DocumentOption(document_type="passport", max_age_months=6, freshness_field="issue_date")
    renewal = DocumentOption(document_type="passport", renewal_interval_months=6)
    assert assess(doc, fresh, {}, date(2027, 2, 28))[0] == "satisfied"
    assert assess(doc, fresh, {}, date(2027, 3, 1))[1] == "DOCUMENT_OUTSIDE_FRESHNESS_WINDOW"
    assert assess(doc, renewal, {}, date(2027, 2, 27))[0] == "satisfied"
    assert assess(doc, renewal, {}, date(2027, 2, 28))[1] == "DOCUMENT_RENEWAL_DUE"
    dates = document_dates(doc, fresh, date(2027, 2, 28))
    assert dates["fresh_until"] == "2027-02-28"
    assert dates["action_due_on"] == "2027-03-01"
    assert dates["due_status"] == "due_soon"


def test_datetime_freshness_uses_utc_date():
    option = DocumentOption(
        document_type="kyc_questionnaire", max_age_months=6, freshness_field="completed_at"
    )
    doc = evidence(payload={"completed_at": "2026-08-31T23:30:00-02:00"})
    assert document_dates(doc, option, date(2027, 3, 1))["freshness_date"] == "2026-09-01"
    assert assess(doc, option, {}, date(2027, 3, 1))[0] == "satisfied"
    assert assess(doc, option, {}, date(2027, 3, 2))[1] == "DOCUMENT_OUTSIDE_FRESHNESS_WINDOW"
    with pytest.raises(ValueError, match="timezone"):
        calendar_date("2026-08-31T23:30:00")


def test_rereview_does_not_refresh_old_evidence_or_submission():
    doc = evidence()
    doc["latest_review"]["reviewed_at"] = "2027-03-01T10:00:00Z"
    review = DocumentOption(document_type="passport", renewal_interval_months=6)
    assert document_dates(doc, review, date(2027, 3, 1))["renewal_due_on"] == "2027-09-01"
    fresh = DocumentOption(
        document_type="passport",
        max_age_months=6,
        freshness_field="issue_date",
        renewal_interval_months=6,
    )
    assert assess(doc, fresh, {}, date(2027, 3, 1))[1] == "DOCUMENT_OUTSIDE_FRESHNESS_WINDOW"
    submit = DocumentOption(
        document_type="passport", renewal_interval_months=6, renewal_basis="submitted_at"
    )
    assert assess(doc, submit, {}, date(2027, 3, 1))[1] == "DOCUMENT_RENEWAL_DUE"
    doc["submitted_at"] = "2027-03-01T09:00:00Z"
    assert assess(doc, submit, {}, date(2027, 3, 1))[0] == "satisfied"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_age_months": 6},
        {"freshness_field": "issue_date"},
        {"max_age_months": 6, "max_age_days": 180, "freshness_field": "issue_date"},
        {"max_age_months": 0, "freshness_field": "issue_date"},
        {"renewal_interval_months": 0},
        {"renewal_basis": "submitted_at"},
        {"renewal_interval_months": 6, "renewal_basis": "created_at"},
    ],
)
def test_invalid_rules(kwargs):
    with pytest.raises(ValidationError):
        DocumentOption(document_type="passport", **kwargs)


def test_missing_future_dates_and_expiration():
    option = DocumentOption(
        document_type="passport", max_age_days=180, freshness_field="issue_date"
    )
    assert assess(evidence(payload={}), option, {}, date(2026, 9, 1))[1] == "FRESHNESS_DATE_MISSING"
    assert (
        assess(evidence(), option, {}, date(2026, 8, 30))[1] == "DOCUMENT_OUTSIDE_FRESHNESS_WINDOW"
    )
    renew = DocumentOption(document_type="passport", renewal_interval_months=6)
    assert (
        assess(evidence(latest_review=None), renew, {}, date(2026, 9, 1))[1]
        == "RENEWAL_DATE_MISSING"
    )
    assert assess(evidence(), renew, {}, date(2026, 8, 30))[1] == "RENEWAL_DATE_IN_FUTURE"
    valid = DocumentOption(
        document_type="passport", require_unexpired=True, renewal_interval_months=6
    )
    doc = evidence(payload={"expiration_date": "2026-09-01"})
    assert assess(doc, valid, {}, date(2026, 9, 1))[0] == "satisfied"
    assert assess(doc, valid, {}, date(2026, 9, 2))[1] == "DOCUMENT_EXPIRED"
    assert document_dates(doc, valid, date(2026, 9, 2))["action"] == "replace_evidence"


def test_alternative_can_satisfy_requirement_when_another_is_due():
    policy = DocumentSet(
        key="example",
        version=1,
        name="Example",
        description="Identity alternatives",
        requirements=[
            DocumentRequirement(
                key="identity",
                description="One identity document",
                options=[
                    DocumentOption(document_type="passport", renewal_interval_months=6),
                    DocumentOption(document_type="national_identity_card", require_unexpired=True),
                ],
            )
        ],
    )
    expired_review = evidence()
    national_id = evidence(
        document_type="national_identity_card", payload={"validity_type": "permanent"}
    )
    findings, summary = reconcile(
        {
            "policy": policy.model_dump(),
            "person": {},
            "evaluation_date": "2027-03-01",
            "documents": [expired_review, national_id],
        }
    )
    assert summary["complete"] is True
    assert [ref["document_uid"] for ref in findings[0]["document_references"]] == [
        national_id["uid"]
    ]

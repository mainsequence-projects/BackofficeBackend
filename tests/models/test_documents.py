"""Canonical completion, recursive drafts, exact values, and review isolation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.backoffice.models.assignment import PersonDocumentSet
from src.backoffice.models.common import DatePeriod, EvidenceRegion, Money, PostalAddress
from src.backoffice.models.document import DocumentInstance, DocumentReview, RawDocumentRef
from src.backoffice.models.document_set import DocumentSet
from src.backoffice.models.person import Person
from src.backoffice.schemas.catalog import DocumentSchema, document_schema
from src.backoffice.schemas.drafts import complete_draft, get_draft_model
from src.backoffice.schemas.registry import DOCUMENT_ADAPTER, DOCUMENT_MODELS, get_document_model


@pytest.mark.parametrize("kind,version", DOCUMENT_MODELS)
def test_complete_round_trip_and_missing_required_fields(kind, version, document_fixture):
    payload = document_fixture(kind)
    model = get_document_model(kind, version)
    parsed = DOCUMENT_ADAPTER.validate_python(payload)
    assert type(parsed) is model
    assert DOCUMENT_ADAPTER.validate_json(parsed.model_dump_json()) == parsed
    for name, field in model.model_fields.items():
        if field.is_required():
            incomplete = {key: value for key, value in payload.items() if key != name}
            with pytest.raises(ValidationError):
                model.model_validate(incomplete)
            get_draft_model(kind, version).model_validate(incomplete)


@pytest.mark.parametrize("kind,version", DOCUMENT_MODELS)
def test_draft_requires_completion_and_preserves_metadata(kind, version):
    canonical = get_document_model(kind, version)
    draft = get_draft_model(kind, version)
    assert draft().document_type == kind
    with pytest.raises(ValidationError):
        complete_draft(kind, draft().model_dump(), version)
    for name, field in canonical.model_fields.items():
        assert draft.model_fields[name].description == field.description
        assert draft.model_fields[name].title == field.title
    with pytest.raises(ValidationError):
        draft.model_validate({"unknown_field": "value"})


def test_partial_nested_fields_keep_leaf_validation():
    draft = get_draft_model("bank_statement")
    instance = draft.model_validate(
        {
            "statement_period": {"start_date": "2026-09-01"},
            "transactions": [{"amount": {"currency": "EUR"}}],
        }
    )
    assert instance.statement_period.end_date is None
    assert instance.transactions[0].amount.amount is None
    for payload in (
        {"statement_period": {"start_date": "not-a-date"}},
        {"transactions": [{"amount": {"currency": "EURO"}}]},
        {"account_holders": []},
    ):
        with pytest.raises(ValidationError):
            draft.model_validate(payload)


def test_cross_field_rules_are_deferred_until_completion(document_fixture):
    payload = document_fixture("payslip")
    payload["net_pay"]["currency"] = "USD"
    get_draft_model("payslip").model_validate(payload)
    with pytest.raises(ValidationError, match="currency"):
        complete_draft("payslip", payload)


def test_source_values_and_decimal_precision_are_preserved(document_fixture):
    passport = get_document_model("passport").model_validate(document_fixture("passport"))
    assert passport.passport_number == "000123456"
    amount = Money(amount="123456789012345678.123456789", currency="EUR")
    assert amount.model_dump(mode="json")["amount"] == "123456789012345678.123456789"
    assert PostalAddress(address_line_1="  As printed  ").address_line_1 == "  As printed  "
    for number in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            Money(amount=number, currency="EUR")
    with pytest.raises(ValidationError):
        PostalAddress(address_line_1="   ")


def test_validity_chronology_and_employment_conditions(document_fixture):
    identity = document_fixture("national_identity_card")
    identity["validity_type"] = "fixed_term"
    with pytest.raises(ValidationError, match="expiration_date is required"):
        complete_draft("national_identity_card", identity)
    identity.update(validity_type="permanent", expiration_date="2030-01-01")
    with pytest.raises(ValidationError, match="permanent"):
        complete_draft("national_identity_card", identity)
    passport = document_fixture("passport")
    passport["expiration_date"] = "2020-01-01"
    with pytest.raises(ValidationError, match="expiration_date"):
        complete_draft("passport", passport)
    passport.update(issue_date=None, date_of_birth="2035-01-01")
    with pytest.raises(ValidationError, match="date_of_birth"):
        complete_draft("passport", passport)
    contract = document_fixture("employment_contract")
    contract["employment_type"] = "fixed-term"
    with pytest.raises(ValidationError, match="end_date"):
        complete_draft("employment_contract", contract)
    contract.update(end_date="2027-01-01", salary_frequency=None)
    with pytest.raises(ValidationError, match="salary_frequency"):
        complete_draft("employment_contract", contract)
    with pytest.raises(ValidationError):
        DatePeriod(start_date="2026-10-01", end_date="2026-09-01")


def test_bank_balance_currency_and_nonnegative_expected_flows(document_fixture):
    statement = document_fixture("bank_statement")
    statement["opening_balance"]["currency"] = "USD"
    with pytest.raises(ValidationError, match="currency"):
        complete_draft("bank_statement", statement)
    questionnaire = document_fixture("kyc_questionnaire")
    questionnaire["expected_monthly_inflow"]["amount"] = "-1"
    with pytest.raises(ValidationError):
        complete_draft("kyc_questionnaire", questionnaire)
    questionnaire["expected_monthly_inflow"]["amount"] = "1"
    questionnaire["completed_at"] = "2026-09-01T09:00:00"
    with pytest.raises(ValidationError):
        complete_draft("kyc_questionnaire", questionnaire)


def test_source_page_ranges_and_regions():
    source = uuid4()
    for data in (
        {"first_page": 1},
        {"first_page": 2, "last_page": 1},
        {"first_page": 0, "last_page": 1},
    ):
        with pytest.raises(ValidationError):
            RawDocumentRef(raw_document_uid=source, **data)
    for box in ([0, 0, 0, 1], [0, 0, 1.1, 1], [0, 0, 1], [0, float("nan"), 1, 1]):
        with pytest.raises(ValidationError):
            EvidenceRegion(raw_document_uid=source, page_number=1, bounding_box=box)


def test_acceptance_is_derived_from_exact_revision(document_fixture):
    uid = uuid4()
    payload = dict(
        uid=uid,
        person_uid=uuid4(),
        revision=1,
        data=document_fixture("passport"),
        raw_document_refs=[{"raw_document_uid": uuid4()}],
    )
    pending = DocumentInstance(**payload)
    assert pending.accepted is False and pending.review_status == "pending"
    review = dict(
        uid=uuid4(),
        document_uid=uid,
        revision=1,
        decision="accepted",
        reviewed_by=uuid4(),
        reviewed_at="2026-10-01T08:00:00Z",
        reason="Source checked.",
    )
    accepted = DocumentInstance(**payload, latest_review=review)
    assert accepted.model_dump()["accepted"] is True
    review["decision"] = "rejected"
    assert DocumentInstance(**payload, latest_review=review).review_status == "rejected"
    for stale in (dict(review, revision=2), dict(review, document_uid=uuid4())):
        with pytest.raises(ValidationError, match="latest_review"):
            DocumentInstance(**payload, latest_review=stale)
    with pytest.raises(ValidationError):
        DocumentInstance(**payload, accepted=True)
    with pytest.raises(ValidationError):
        DocumentInstance(**dict(payload, raw_document_refs=[]))
    schema = DocumentInstance.model_json_schema(mode="serialization")
    assert schema["properties"]["accepted"]["readOnly"] is True


def assert_described(schema, definitions=None):
    definitions = definitions if definitions is not None else schema.get("$defs", {})
    if isinstance(schema, dict):
        for name, field in schema.get("properties", {}).items():
            referenced = definitions.get(field.get("$ref", "").rsplit("/", 1)[-1], {})
            assert field.get("title") or referenced.get("title"), name
            assert len(field.get("description", "")) >= 15, name
        for value in schema.values():
            assert_described(value, definitions)
    elif isinstance(schema, list):
        for value in schema:
            assert_described(value, definitions)


def test_all_nested_fields_have_form_descriptions():
    for kind, version in DOCUMENT_MODELS:
        contract = document_schema(kind, version)
        assert_described(contract.canonical_schema)
        assert_described(contract.draft_schema)
    for model in (
        Person,
        PersonDocumentSet,
        DocumentSet,
        DocumentInstance,
        DocumentReview,
        DocumentSchema,
    ):
        assert_described(model.model_json_schema(mode="serialization"))


def test_unknown_type_or_version_never_falls_back():
    for kind, version in (("passport", 2), ("unknown_document", 1)):
        with pytest.raises(ValueError):
            get_document_model(kind, version)
        with pytest.raises(ValueError):
            get_draft_model(kind, version)

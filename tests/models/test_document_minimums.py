"""Reviewed minimum source facts for every document, independent of model metadata."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.backoffice.models.document import DocumentInstance
from src.backoffice.models.document_set import DocumentOption
from src.backoffice.policies import loan_requirements, new_account_requirements
from src.backoffice.schemas.catalog import document_schema
from src.backoffice.schemas.drafts import complete_draft
from src.backoffice.schemas.registry import LATEST_DOCUMENT_VERSIONS, get_document_model
from src.backoffice.services.reconciliation import assess

# Deliberately explicit: changing a model's required array must not silently change
# the examples that demonstrate which source facts are sufficient.
MINIMUM_FIELDS = {
    "national_identity_card": "full_name date_of_birth identity_number",
    "passport": "full_name date_of_birth passport_number nationality issuing_country expiration_date",
    "residence_permit": "full_name permit_number issuing_country validity_type",
    "utility_bill": "account_holder_name service_address provider_name issue_date",
    "bank_statement": "account_holders account_identifier statement_period",
    "employment_contract": "employee_name employer employment_type start_date",
    "payslip": "employee_name employer pay_period net_pay",
    "tax_return": "taxpayer_name tax_jurisdiction tax_period declared_income",
    "source_of_funds_evidence": "owner_name source_type amount explanation",
    "kyc_questionnaire": "full_name employment_status account_purpose expected_monthly_inflow source_of_funds",
    "loan_contract": "full_name issue_date lender_name loan_amount",
    "employer_confirmation": "employee_name employer issue_date monthly_net_income",
    "tax_clearance_certificate": "taxpayer_name issuing_authority issue_date arrears_statement",
}


def minimum_payload(kind, document_fixture):
    source = document_fixture(kind)
    payload = {key: source[key] for key in MINIMUM_FIELDS[kind].split()}
    payload["document_type"] = kind
    if "validity_type" in payload:
        payload["validity_type"] = "permanent"
    return payload


@pytest.mark.parametrize("kind", MINIMUM_FIELDS)
def test_minimum_source_facts_complete_and_round_trip(kind, document_fixture):
    version = LATEST_DOCUMENT_VERSIONS[kind]
    payload = minimum_payload(kind, document_fixture)
    parsed = complete_draft(kind, payload, version)
    assert get_document_model(kind, version).model_validate_json(parsed.model_dump_json()) == parsed
    schema = document_schema(kind, version).canonical_schema
    assert set(schema["required"]) == set(MINIMUM_FIELDS[kind].split())
    # Both omitted keys and explicit nulls occur in real extraction responses.
    optional = set(schema["properties"]) - set(schema["required"]) - {"document_type"}
    with_nulls = {**payload, **dict.fromkeys(optional)}
    assert complete_draft(kind, with_nulls, version) == parsed


def test_catalog_audit_covers_every_document_type():
    assert set(MINIMUM_FIELDS) == set(LATEST_DOCUMENT_VERSIONS)


@pytest.mark.parametrize("kind", [k for k, v in LATEST_DOCUMENT_VERSIONS.items() if v == 2])
def test_relaxations_are_versioned_and_old_contracts_stay_required(kind, document_fixture):
    payload = minimum_payload(kind, document_fixture)
    with pytest.raises(ValidationError):
        complete_draft(kind, payload, 1)
    complete_draft(kind, payload, 2)


def test_payslip_without_gross_keeps_net_and_deduction_currency_checks(document_fixture):
    payload = minimum_payload("payslip", document_fixture)
    payload["deductions"] = {"amount": "12.00", "currency": "USD"}
    assert payload["net_pay"]["currency"] != "USD"
    with pytest.raises(ValidationError, match="pay currency"):
        complete_draft("payslip", payload, 2)
    payload["deductions"]["currency"] = payload["net_pay"]["currency"]
    assert complete_draft("payslip", payload, 2).gross_pay is None
    payload["gross_pay"] = {"amount": "1234.00", "currency": "USD"}
    with pytest.raises(ValidationError, match="same currency"):
        complete_draft("payslip", payload, 2)


@pytest.mark.parametrize("field", ["expected_monthly_inflow", "expected_monthly_outflow"])
def test_questionnaire_flows_still_cannot_be_negative(field, document_fixture):
    payload = minimum_payload("kyc_questionnaire", document_fixture)
    payload[field] = {"amount": "-1", "currency": "EUR"}
    with pytest.raises(ValidationError, match="negative"):
        complete_draft("kyc_questionnaire", payload, 2)


@pytest.mark.parametrize("kind", ["national_identity_card", "residence_permit"])
def test_no_issue_date_needed_but_fixed_term_still_requires_expiry(kind, document_fixture):
    payload = minimum_payload(kind, document_fixture)
    version = LATEST_DOCUMENT_VERSIONS[kind]
    payload.update(validity_type="fixed_term", expiration_date="2030-01-01")
    assert complete_draft(kind, payload, version).issue_date is None
    del payload["expiration_date"]
    with pytest.raises(ValidationError, match="expiration_date is required"):
        complete_draft(kind, payload, version)


def test_undated_questionnaire_does_not_satisfy_freshness_policy(document_fixture):
    from datetime import date

    payload = complete_draft(
        "kyc_questionnaire", minimum_payload("kyc_questionnaire", document_fixture), 2
    ).model_dump(mode="json")
    option = next(
        r.options[0]
        for r in new_account_requirements(4).requirements
        if r.key == "customer_questionnaire"
    )
    assert assess(
        {"status": "submitted", "review_status": "accepted", "accepted": True, "payload": payload},
        option,
        {"full_name": payload["full_name"]},
        date(2026, 10, 19),
    ) == ("needs_information", "FRESHNESS_DATE_MISSING", ["completed_at"])


def test_new_policies_pin_current_versions_and_keep_existing_business_checks():
    for policy in (new_account_requirements(5), loan_requirements(4)):
        for requirement in policy.requirements:
            for option in requirement.options:
                assert option.schema_version == LATEST_DOCUMENT_VERSIONS[option.document_type]
        for comparison in policy.comparisons:
            for selector in (comparison.left, comparison.right):
                assert selector.schema_version == LATEST_DOCUMENT_VERSIONS[selector.document_type]
    loan = loan_requirements(4)
    option = next(r.options[0] for r in loan.requirements if r.key == "loan_contract")
    assert option.required_fields == ["declared_monthly_net_income"]
    # Workflows can explicitly require a newly optional source detail.
    DocumentOption(document_type="utility_bill", schema_version=2, required_fields=["utility_type"])


def test_envelope_validates_its_exact_version(document_fixture):
    payload = dict(
        uid=uuid4(),
        person_uid=uuid4(),
        revision=1,
        created_at="2026-10-19T08:00:00Z",
        revision_created_at="2026-10-19T08:00:00Z",
        submitted_at="2026-10-19T08:00:00Z",
        raw_document_refs=[{"raw_document_uid": uuid4()}],
        data=minimum_payload("payslip", document_fixture),
        schema_version=2,
    )
    current = DocumentInstance(**payload)
    assert current.data.gross_pay is None
    assert (
        DocumentInstance.model_validate_json(current.model_dump_json(exclude_computed_fields=True))
        == current
    )
    original = get_document_model("payslip", 1).model_validate(document_fixture("payslip"))
    assert DocumentInstance(**{**payload, "data": original, "schema_version": 1}).data == original
    with pytest.raises(ValidationError):
        DocumentInstance(**{**payload, "schema_version": 1})
    with pytest.raises(ValidationError, match="Unknown document schema"):
        DocumentInstance(**{**payload, "data": document_fixture("passport")})


def test_historical_policies_match_their_preserved_snapshots():
    from src.backoffice.policies import policy_definition

    root = Path(__file__).resolve().parents[2] / "schemas/document_sets"
    for policy in (
        *(new_account_requirements(v) for v in (1, 2, 3)),
        *(loan_requirements(v) for v in (1, 2)),
    ):
        expected = json.loads((root / f"{policy.key}.v{policy.version}.json").read_text())
        assert policy_definition(policy) == expected

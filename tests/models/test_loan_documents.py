"""Loan facts and policies use the existing contracts without changing old versions."""

import hashlib
import json

import pytest
from pydantic import ValidationError

from src.backoffice.policies import document_set_catalog, loan_requirements, policy_definition
from src.backoffice.schemas.drafts import complete_draft, get_draft_model
from src.backoffice.schemas.registry import get_document_model


def test_loan_facts_preserve_precision_and_do_not_interpret_requirements(document_fixture):
    payload = document_fixture("loan_contract")
    payload["loan_amount"]["amount"] = "600000.123456789"
    loan = complete_draft("loan_contract", payload)
    assert loan.loan_amount.model_dump(mode="json")["amount"] == "600000.123456789"
    assert loan.contract_number == "00042"
    assert loan.required_documents_as_printed == ["No additional evidence requested"]
    assert len(loan_requirements().requirements) == 7
    for forbidden in ("accepted", "recommended_next_step", "checks"):
        with pytest.raises(ValidationError):
            complete_draft("loan_contract", {**payload, forbidden: True})


def test_employment_chronology_is_structural_and_drafts_remain_partial(document_fixture):
    payload = document_fixture("employer_confirmation")
    payload["employment_end_date"] = "2018-01-01"
    get_draft_model("employer_confirmation").model_validate(payload)
    with pytest.raises(ValidationError, match="employment_end_date"):
        complete_draft("employer_confirmation", payload)
    draft = get_draft_model("employer_confirmation").model_validate(
        {"monthly_net_income": {"currency": "CZK"}}
    )
    assert draft.monthly_net_income.amount is None


@pytest.mark.parametrize("statement", ["no_arrears", "arrears_reported", "not_stated"])
def test_tax_statement_is_not_a_clearance_decision(statement, document_fixture):
    payload = document_fixture("tax_clearance_certificate")
    payload["arrears_statement"] = statement
    certificate = complete_draft("tax_clearance_certificate", payload)
    assert certificate.arrears_statement == statement
    assert certificate.arrears_amount is None
    assert not hasattr(certificate, "accepted")


def test_catalog_versions_are_fresh_and_historical_definitions_unchanged():
    expected = {
        1: "ab9450970cc5d2ef720822c58bd25589a010693a73f0a52299f4306abcb60488",
        2: "8a3a3e7397e6def0d271146add64192a778bbced8a3bdcf05fdebe9147ba776b",
    }
    catalog = document_set_catalog()
    for policy in catalog:
        if policy.key == "new_account_requirements" and policy.version in expected:
            encoded = (json.dumps(policy_definition(policy), indent=2) + "\n").encode()
            assert hashlib.sha256(encoded).hexdigest() == expected[policy.version]
        for requirement in policy.requirements:
            for option in requirement.options:
                get_document_model(option.document_type, option.schema_version)
    loan = loan_requirements()
    loan.requirements.clear()
    assert len(loan_requirements().requirements) == 7
    with pytest.raises(ValueError, match="Unknown"):
        loan_requirements(3)

"""Requirement configuration rejects stale or impossible schema references."""

import pytest
from pydantic import ValidationError

from src.backoffice.models.document_set import (
    DocumentOption,
    DocumentRequirement,
    RequirementCondition,
)
from src.backoffice.policies import new_account_requirements


def test_example_has_alternatives_conditionality_and_pinned_versions():
    policy = new_account_requirements()
    identity = next(item for item in policy.requirements if item.key == "identity")
    assert {option.document_type for option in identity.options} == {
        "passport",
        "national_identity_card",
    }
    income = next(item for item in policy.requirements if item.key == "employment_income")
    assert income.min_count == 3 and income.distinct_period_field == "pay_period"
    assert income.condition.equals == "employed"
    policy.requirements.clear()
    assert new_account_requirements().requirements


@pytest.mark.parametrize(
    "kwargs",
    [
        {"schema_version": 2},
        {"required_fields": ["imaginary"]},
        {"required_fields": ["full_name", "full_name"]},
        {"max_age_days": 30},
        {"freshness_field": "issue_date"},
        {"max_age_days": 30, "freshness_field": "full_name"},
    ],
)
def test_invalid_policy_paths_and_age_pairs(kwargs):
    with pytest.raises(ValidationError):
        DocumentOption(document_type="passport", **kwargs)


def test_nested_field_path_and_date_path_are_supported():
    option = DocumentOption(
        document_type="bank_statement",
        required_fields=["holder_address.city"],
        max_age_days=90,
        freshness_field="statement_period.end_date",
    )
    assert option.required_fields == ["holder_address.city"]
    with pytest.raises(ValidationError):
        DocumentOption(document_type="bank_statement", required_fields=["holder_address.imaginary"])


def test_duplicate_requirements_alternatives_and_nonperiod_fields_are_rejected():
    policy = new_account_requirements().model_dump()
    policy["requirements"].append(policy["requirements"][0])
    with pytest.raises(ValidationError):
        type(new_account_requirements()).model_validate(policy)
    option = DocumentOption(document_type="passport")
    for options, period in (([option, option], None), ([option], "full_name")):
        with pytest.raises(ValidationError):
            DocumentRequirement(
                key="identity",
                description="Identity evidence",
                options=options,
                distinct_period_field=period,
            )


def test_conditions_use_the_profile_field_type():
    for field, value in (
        ("employment_status", True),
        ("residency_permit_required", "yes"),
        ("residency_permit_required", 1),
    ):
        with pytest.raises(ValidationError):
            RequirementCondition(field=field, equals=value)


def test_validity_rule_requires_a_document_with_an_expiration_field():
    with pytest.raises(ValidationError, match="expiration_date"):
        DocumentOption(document_type="payslip", require_unexpired=True)

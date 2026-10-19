"""Business tolerances and outcomes are deterministic and never sent to the parser."""

from decimal import Decimal

import pytest

from src.backoffice.models.comparison import ComparisonRule, ComparisonSelector
from src.backoffice.processing.comparison_contracts import CitedFact, ComparisonObservation
from src.backoffice.services.comparisons import decide


def rule(**kwargs):
    return ComparisonRule(
        key="income",
        description="Compare income",
        topic="Monthly net income",
        left=ComparisonSelector(
            document_type="loan_contract", field="declared_monthly_net_income.amount"
        ),
        right=ComparisonSelector(
            document_type="employer_confirmation", field="monthly_net_income.amount"
        ),
        operator="numeric",
        **kwargs,
    )


def observation(left, right, **kwargs):
    citation = {
        "source_id": "source",
        "source_sha256": "a" * 64,
        "page": 1,
        "page_sha256": "b" * 64,
    }
    return ComparisonObservation(
        key="pair",
        comparability="comparable",
        relationship="equivalent",
        explanation="Reader observed values",
        left=CitedFact(
            document_id="left", revision=1, pointer="/value", value=left, citations=[citation]
        ),
        right=CitedFact(
            document_id="right", revision=1, pointer="/value", value=right, citations=[citation]
        ),
        **kwargs,
    )


@pytest.mark.parametrize(
    "left,right,tolerance,expected",
    [
        ("100", "101", 100, "satisfied"),
        ("100", "101.00000001", 100, "failed"),
        ("0", "0.01", 10000, "failed"),
        ("0", "0", 0, "satisfied"),
        ("56000", "41000", 100, "failed"),
        (True, "1", 0, "needs_information"),
        ("NaN", "1", 0, "needs_information"),
        ("Infinity", "1", 0, "needs_information"),
        ("1e1000000000", "1", 0, "needs_information"),
    ],
)
def test_numeric_tolerance_does_not_trust_model_relationship(left, right, tolerance, expected):
    assert (
        decide(rule(relative_tolerance_basis_points=tolerance), observation(left, right))[0]
        == expected
    )


def test_zero_baseline_uses_explicit_absolute_tolerance():
    assert (
        decide(rule(absolute_tolerance=Decimal("0.01")), observation("0", "0.01"))[0] == "satisfied"
    )


def test_unknown_basis_never_passes_even_when_values_equal():
    observed = observation("100", "100").model_copy(update={"comparability": "uncertain"})
    assert decide(rule(), observed) == ("pending_review", "COMPARISON_BASIS_UNRESOLVED")


def test_non_numeric_rules_cannot_have_hidden_tolerances():
    with pytest.raises(ValueError, match="tolerances"):
        ComparisonRule.model_validate(
            {**rule().model_dump(), "operator": "semantic", "absolute_tolerance": "1"}
        )

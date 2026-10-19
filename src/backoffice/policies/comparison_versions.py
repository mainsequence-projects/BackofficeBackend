"""Opt-in illustrative policy versions using the same comparison evaluator."""

from ..models.comparison import ComparisonRule, ComparisonSelector
from ..models.document_set import DocumentSet


def with_comparisons(policy: DocumentSet) -> DocumentSet:
    definition = policy.model_dump()
    definition["version"] += 1
    if policy.key == "loan_requirements":
        rules = [
            ComparisonRule(
                key="monthly_net_income_consistency",
                description="Declared and employer-confirmed monthly net income must describe the same basis and match exactly; zero tolerance is illustrative and not credit approval.",
                topic="Monthly net income of the same employee, period and income basis",
                left=ComparisonSelector(
                    document_type="loan_contract",
                    field="declared_monthly_net_income.amount",
                    unit_field="declared_monthly_net_income.currency",
                    context_fields=["full_name"],
                ),
                right=ComparisonSelector(
                    document_type="employer_confirmation",
                    field="monthly_net_income.amount",
                    unit_field="monthly_net_income.currency",
                    context_fields=["employee_name", "income_basis"],
                ),
                operator="numeric",
            )
        ]
    else:
        rules = [
            ComparisonRule(
                key="identity_name_consistency",
                description="When both passport and national identity card are supplied, their holder names must refer to the same person; uncertainty requires review.",
                topic="Identity document holder's full name and birth date",
                left=ComparisonSelector(
                    document_type="passport", field="full_name", context_fields=["date_of_birth"]
                ),
                right=ComparisonSelector(
                    document_type="national_identity_card",
                    field="full_name",
                    context_fields=["date_of_birth"],
                ),
                operator="semantic",
                when_both_present=True,
            )
        ]
    definition["comparisons"] = [r.model_dump() for r in rules]
    definition["description"] = (
        "Illustrative evidence policy with cited cross-document comparisons. Completion means "
        "only that the versioned evidence checks passed, never account-opening or credit approval. "
        "Thresholds and coverage require business approval before production use."
    )
    return DocumentSet.model_validate(definition)

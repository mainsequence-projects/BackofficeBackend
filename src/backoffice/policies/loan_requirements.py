"""Illustrative salaried-loan evidence policy for the shared requirement engine."""

from ..models.document_set import DocumentOption, DocumentRequirement, DocumentSet


def loan_requirements(version: int = 1) -> DocumentSet:
    """Fresh immutable-version definition; no separate loan review or evaluator."""
    if version == 2:
        from .comparison_versions import with_comparisons

        return with_comparisons(loan_requirements(1))
    if version != 1:
        raise ValueError("Unknown loan requirements policy version")
    return DocumentSet(
        key="loan_requirements",
        version=1,
        name="Loan document requirements",
        description=(
            "Illustrative salaried-loan evidence coverage policy. Completion means only that "
            "the assigned evidence requirements are satisfied, not credit approval, income "
            "consistency or tax clearance. Cross-document loan checks are not implemented in "
            "this version. Age limits and coverage require business approval before use."
        ),
        allow_document_reuse=True,
        requirements=[
            DocumentRequirement(
                key="loan_contract",
                description="One accepted loan contract stating the principal and declared monthly net income.",
                options=[
                    DocumentOption(
                        document_type="loan_contract",
                        required_fields=["declared_monthly_net_income"],
                    )
                ],
            ),
            DocumentRequirement(
                key="identity",
                description="One accepted identity document with established current validity.",
                options=[
                    DocumentOption(document_type="national_identity_card", require_unexpired=True),
                    DocumentOption(document_type="passport", require_unexpired=True),
                ],
            ),
            DocumentRequirement(
                key="bank_statement",
                description="One accepted bank statement with a reporting period ending within 90 days.",
                options=[
                    DocumentOption(
                        document_type="bank_statement",
                        max_age_days=90,
                        freshness_field="statement_period.end_date",
                    )
                ],
            ),
            DocumentRequirement(
                key="employment_income",
                description="One accepted payslip covering a reporting period ending within 90 days.",
                distinct_period_field="pay_period",
                options=[
                    DocumentOption(
                        document_type="payslip",
                        max_age_days=90,
                        freshness_field="pay_period.end_date",
                    )
                ],
            ),
            DocumentRequirement(
                key="address",
                description="Accepted address evidence dated within 90 days and matching the reference profile.",
                options=[
                    DocumentOption(
                        document_type="utility_bill", max_age_days=90, freshness_field="issue_date"
                    ),
                    DocumentOption(
                        document_type="bank_statement",
                        required_fields=["holder_address"],
                        max_age_days=90,
                        freshness_field="statement_period.end_date",
                    ),
                ],
            ),
            DocumentRequirement(
                key="employer_confirmation",
                description="One accepted employer confirmation issued within 30 days; income comparison is a separate check.",
                options=[
                    DocumentOption(
                        document_type="employer_confirmation",
                        max_age_days=30,
                        freshness_field="issue_date",
                    )
                ],
            ),
            DocumentRequirement(
                key="tax_certificate",
                description="One accepted tax-authority certificate issued within 30 days; presence does not establish absence of arrears.",
                options=[
                    DocumentOption(
                        document_type="tax_clearance_certificate",
                        max_age_days=30,
                        freshness_field="issue_date",
                    )
                ],
            ),
        ],
    )

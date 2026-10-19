"""Illustrative onboarding policy, requiring business approval before publication."""

from ..models.document_set import (
    DocumentOption,
    DocumentRequirement,
    DocumentSet,
    RequirementCondition,
)


def new_account_requirements() -> DocumentSet:
    """Return a fresh policy instance, never a shared mutable singleton."""
    employed = RequirementCondition(field="employment_status", equals="employed")
    return DocumentSet(
        key="new_account_requirements",
        version=1,
        name="New account requirements",
        description="Illustrative account-opening evidence policy; age limits and income coverage must be approved for the business before publication.",
        allow_document_reuse=True,
        requirements=[
            DocumentRequirement(
                key="identity",
                description="One accepted identity document with established current validity.",
                options=[
                    DocumentOption(document_type="national_identity_card", require_unexpired=True),
                    DocumentOption(
                        document_type="passport",
                        require_unexpired=True,
                        required_fields=["mrz_lines"],
                    ),
                ],
            ),
            DocumentRequirement(
                key="address",
                description="One accepted source with a matching address dated within 90 days of evaluation.",
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
                key="employment_income",
                description="For employed applicants, three accepted payslips covering distinct reporting periods.",
                condition=employed,
                min_count=3,
                distinct_period_field="pay_period",
                options=[DocumentOption(document_type="payslip")],
            ),
            DocumentRequirement(
                key="employment_contract",
                description="For employed applicants, an accepted contract supporting employer and employment status.",
                condition=employed,
                options=[DocumentOption(document_type="employment_contract")],
            ),
            DocumentRequirement(
                key="residency",
                description="An accepted current permit when the person's reference profile says a permit is required.",
                condition=RequirementCondition(field="residency_permit_required", equals=True),
                options=[DocumentOption(document_type="residence_permit", require_unexpired=True)],
            ),
            DocumentRequirement(
                key="source_of_funds",
                description="Accepted evidence explaining the origin of the funds.",
                options=[DocumentOption(document_type="source_of_funds_evidence")],
            ),
            DocumentRequirement(
                key="customer_questionnaire",
                description="One complete accepted customer questionnaire.",
                options=[DocumentOption(document_type="kyc_questionnaire")],
            ),
        ],
    )

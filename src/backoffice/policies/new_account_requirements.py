"""Versioned account-opening policies; v7 contains the owner's six-document checklist."""

from ..models.document_set import (
    DocumentOption,
    DocumentRequirement,
    DocumentSet,
    RequirementCondition,
)


def new_account_requirements(version: int = 1) -> DocumentSet:
    """Return a fresh policy instance, never a shared mutable singleton."""
    if version == 7:
        # Dataset/business names map to the existing canonical document models.
        # Keep this checklist independent of the historical illustrative rules.
        documents = (
            ("id_card", "national_identity_card", 3, "ID card"),
            ("bank_statement", "bank_statement", 2, "Bank statement"),
            ("payslip", "payslip", 2, "Payslip"),
            ("proof_of_address", "utility_bill", 2, "Proof of address"),
            ("employer_confirmation", "employer_confirmation", 2, "Employer confirmation"),
            ("tax_or_debt_certificate", "tax_clearance_certificate", 2, "Tax or debt certificate"),
        )
        return DocumentSet(
            key="new_account_requirements",
            version=7,
            name="New account requirements",
            description=(
                "Account opening requires one accepted document of each of these six types: "
                "ID card, bank statement, payslip, proof of address, employer confirmation, "
                "and tax or debt certificate. Completion establishes evidence coverage, "
                "not account-opening approval."
            ),
            allow_document_reuse=True,
            requirements=[
                DocumentRequirement(
                    key=key,
                    description=f"One accepted {label.lower()}.",
                    options=[DocumentOption(document_type=kind, schema_version=schema)],
                )
                for key, kind, schema, label in documents
            ],
        )
    if version in (4, 5, 6):
        from .current_documents import with_current_documents

        return with_current_documents(new_account_requirements(version - 1))
    if version == 3:
        from .comparison_versions import with_comparisons

        return with_comparisons(new_account_requirements(2))
    if version not in (1, 2):
        raise ValueError("Unknown new-account policy version")
    employed = RequirementCondition(field="employment_status", equals="employed")
    policy = DocumentSet(
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

    if version == 2:
        definition = policy.model_dump()
        definition["version"] = 2
        definition["description"] = (
            "Illustrative account-opening policy with six-calendar-month address and questionnaire freshness, and identity review renewal every six calendar months."
        )
        for requirement in definition["requirements"]:
            if requirement["key"] == "identity":
                requirement["description"] = (
                    "One currently valid accepted identity document, reviewed again every six calendar months."
                )
                for option in requirement["options"]:
                    option["renewal_interval_months"] = 6
            elif requirement["key"] == "address":
                requirement["description"] = (
                    "One accepted source with a matching address dated within six calendar months of evaluation."
                )
                for option in requirement["options"]:
                    option["max_age_days"] = None
                    option["max_age_months"] = 6
            elif requirement["key"] == "customer_questionnaire":
                requirement["description"] = (
                    "One complete accepted questionnaire completed within six calendar months of evaluation."
                )
                requirement["options"][0].update(max_age_months=6, freshness_field="completed_at")
        return DocumentSet.model_validate(definition)
    return policy


def policy_definition(policy: DocumentSet) -> dict:
    """Preserve the exact already-published v1 JSON when adding optional rules."""
    definition = policy.model_dump(mode="json")
    if not policy.comparisons:
        definition.pop("comparisons", None)
    if policy.version == 1:
        for requirement in definition["requirements"]:
            for option in requirement["options"]:
                for key in ("max_age_months", "renewal_interval_months", "renewal_basis"):
                    option.pop(key)
    return definition

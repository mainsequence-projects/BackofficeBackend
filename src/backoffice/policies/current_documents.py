"""Explicit document pins for each immutable policy version.

Never derive these pins from the document registry: adding a schema must not
change a policy that has already been published or assigned to a case.
"""

from ..models.document_set import DocumentSet

DOCUMENT_VERSIONS = {
    ("new_account_requirements", 4): {
        "national_identity_card": 1,
        "passport": 1,
        "utility_bill": 2,
        "bank_statement": 1,
        "payslip": 2,
        "employment_contract": 1,
        "residence_permit": 2,
        "source_of_funds_evidence": 1,
        "kyc_questionnaire": 2,
    },
    ("loan_requirements", 3): {
        "loan_contract": 2,
        "national_identity_card": 1,
        "passport": 1,
        "bank_statement": 1,
        "payslip": 2,
        "utility_bill": 2,
        "employer_confirmation": 2,
        "tax_clearance_certificate": 1,
    },
    ("new_account_requirements", 5): {
        "national_identity_card": 2,
        "passport": 1,
        "utility_bill": 2,
        "bank_statement": 2,
        "payslip": 2,
        "employment_contract": 1,
        "residence_permit": 2,
        "source_of_funds_evidence": 1,
        "kyc_questionnaire": 2,
    },
    ("loan_requirements", 4): {
        "loan_contract": 2,
        "national_identity_card": 2,
        "passport": 1,
        "bank_statement": 2,
        "payslip": 2,
        "utility_bill": 2,
        "employer_confirmation": 2,
        "tax_clearance_certificate": 2,
    },
    ("new_account_requirements", 6): {
        "national_identity_card": 3,
        "passport": 2,
        "utility_bill": 2,
        "bank_statement": 2,
        "payslip": 2,
        "employment_contract": 1,
        "residence_permit": 2,
        "source_of_funds_evidence": 1,
        "kyc_questionnaire": 2,
    },
    ("loan_requirements", 5): {
        "loan_contract": 2,
        "national_identity_card": 3,
        "passport": 2,
        "bank_statement": 2,
        "payslip": 2,
        "utility_bill": 2,
        "employer_confirmation": 2,
        "tax_clearance_certificate": 2,
    },
}


def with_current_documents(policy: DocumentSet) -> DocumentSet:
    """Build the next declared policy version using its frozen schema references."""
    definition = policy.model_dump()
    definition["version"] += 1
    versions = DOCUMENT_VERSIONS[(policy.key, definition["version"])]
    for requirement in definition["requirements"]:
        for option in requirement["options"]:
            option["schema_version"] = versions[option["document_type"]]
    for comparison in definition["comparisons"]:
        for side in ("left", "right"):
            selector = comparison[side]
            selector["schema_version"] = versions[selector["document_type"]]
    return DocumentSet.model_validate(definition)

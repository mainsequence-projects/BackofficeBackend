"""Explicit business processes, independent of the shared evaluation implementation."""

CASE_TYPES = (
    {
        "key": "account_opening",
        "name": "Account opening",
        "description": "Prepare and review the evidence required to open an account.",
    },
    {
        "key": "new_loan",
        "name": "New loan",
        "description": "Prepare and review the evidence required for a new loan application.",
    },
    {
        "key": "document_review",
        "name": "Document review",
        "description": "Review evidence against a published requirement set, including preserved legacy cases.",
    },
)
# New authored policy families must explicitly declare their business purpose.
DOCUMENT_SET_CASE_TYPES = {
    "new_account_requirements": "account_opening",
    "loan_requirements": "new_loan",
}


def legacy_case_type(set_key):
    """Compatibility for historical rows/intents only, never canonical case creation."""
    return DOCUMENT_SET_CASE_TYPES.get(set_key, "document_review")

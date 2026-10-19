"""Loan contract facts, processed by the ordinary document lifecycle."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, Money, NonEmptyStr, PostalAddress


class LoanContract(DocumentModel):
    """Transcribed loan terms; no credit decision or requirement policy."""

    document_type: Literal["loan_contract"] = Field(
        default="loan_contract",
        title="Document type",
        description="Identifies this payload as a loan contract, not an employment contract.",
    )
    full_name: NonEmptyStr = Field(
        title="Borrower name",
        description="Borrower's complete name exactly as printed in the contract.",
    )
    borrower_identifier: NonEmptyStr | None = Field(
        default=None,
        title="Borrower identifier",
        description="Borrower identifier as printed, preserving leading zeros and formatting; no validity claim.",
    )
    contract_number: NonEmptyStr = Field(
        title="Contract number",
        description="Contract reference exactly as printed, preserving leading zeros.",
    )
    issue_date: date = Field(
        title="Contract date",
        description="Date stated for the contract, as YYYY-MM-DD; not the upload date.",
    )
    lender_name: NonEmptyStr = Field(
        title="Lender name",
        description="Name of the lender explicitly identified in the contract.",
    )
    loan_amount: Money = Field(
        title="Loan amount",
        description="Principal amount and currency stated in the contract; not declared income.",
    )
    declared_monthly_net_income: Money | None = Field(
        default=None,
        title="Declared monthly net income",
        description="Monthly income after deductions explicitly declared in the contract; null if only gross or unspecified income is given.",
    )
    borrower_address: PostalAddress | None = Field(
        default=None,
        title="Borrower address",
        description="Borrower address as stated in the contract; null when absent.",
    )
    required_documents_as_printed: list[NonEmptyStr] | None = Field(
        default=None,
        title="Document list as printed",
        description="Document requirements transcribed from the contract as source text; never an executable policy or authority to waive assigned requirements.",
    )

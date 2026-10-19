"""Bank Statement canonical document contract."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..common import (
    BankTransaction,
    CurrencyCode,
    DatePeriod,
    DocumentModel,
    Money,
    NonEmptyStr,
    PostalAddress,
)


class BankStatement(DocumentModel):
    """Structured facts from a bank statement."""

    document_type: Literal["bank_statement"] = Field(
        default="bank_statement",
        title="Document type",
        description="Identifies this payload as bank statement.",
    )
    account_holders: list[NonEmptyStr] = Field(
        min_length=1,
        title="Account holders",
        description="One or more account-holder names exactly as printed, including joint holders.",
    )
    bank_name: NonEmptyStr = Field(
        title="Bank name", description="Institution issuing the statement."
    )
    account_identifier: NonEmptyStr = Field(
        title="Account identifier",
        description="Printed account number or IBAN; retain masking and leading zeros.",
    )
    holder_address: PostalAddress | None = Field(
        default=None,
        title="Holder address",
        description="Account-holder address printed on the statement.",
    )
    statement_period: DatePeriod = Field(
        title="Statement period", description="Inclusive reporting period covered by the statement."
    )
    issue_date: date | None = Field(
        default=None,
        title="Issue date",
        description="Statement issue date, if separately stated from the period end.",
    )
    currency: CurrencyCode = Field(
        title="Currency", description="ISO three-letter currency of the statement account."
    )
    opening_balance: Money | None = Field(
        default=None,
        title="Opening balance",
        description="Account balance at the beginning of the stated reporting period.",
    )
    closing_balance: Money | None = Field(
        default=None,
        title="Closing balance",
        description="Account balance at the end of the stated reporting period.",
    )
    transactions: list[BankTransaction] | None = Field(
        default=None,
        title="Transactions",
        description="Transcribed transactions; null means not extracted, while an empty list requires evidence of no transactions.",
    )

    @model_validator(mode="after")
    def balance_currencies(self) -> Self:
        for balance in (self.opening_balance, self.closing_balance):
            if balance is not None and balance.currency != self.currency:
                raise ValueError("balance currency must match statement currency")
        return self

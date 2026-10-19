"""Employer confirmation facts; review and comparison belong to shared services."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..common import DatePeriod, DocumentModel, Employer, Money, NonEmptyStr


class EmployerConfirmation(DocumentModel):
    """Employment and income stated by an employer, distinct from an employment contract."""

    document_type: Literal["employer_confirmation"] = Field(
        default="employer_confirmation",
        title="Document type",
        description="Identifies this payload as an employer's employment and income confirmation.",
    )
    employee_name: NonEmptyStr = Field(
        title="Employee name",
        description="Employee's complete name exactly as printed in the confirmation.",
    )
    employee_identifier: NonEmptyStr | None = Field(
        default=None,
        title="Employee identifier",
        description="Employee identifier as printed, preserving leading zeros and formatting.",
    )
    employer: Employer = Field(
        title="Employer",
        description="Employer identity explicitly stated in the confirmation.",
    )
    issue_date: date = Field(
        title="Issue date",
        description="Date the employer issued the confirmation, as YYYY-MM-DD.",
    )
    employment_start_date: date | None = Field(
        default=None,
        title="Employment start date",
        description="Employment start date explicitly stated by the employer.",
    )
    employment_end_date: date | None = Field(
        default=None,
        title="Employment end date",
        description="Employment end date if stated; absence does not imply indefinite employment.",
    )
    contract_term_as_printed: NonEmptyStr | None = Field(
        default=None,
        title="Contract term",
        description="Employment term wording exactly as printed; null when not stated.",
    )
    position: NonEmptyStr | None = Field(
        default=None,
        title="Position",
        description="Employee's position or occupation exactly as stated by the employer.",
    )
    monthly_net_income: Money = Field(
        title="Monthly net income",
        description="Monthly income after deductions explicitly stated by the employer, in its printed currency.",
    )
    income_basis: Literal["single_month", "monthly_average", "not_stated"] = Field(
        title="Income basis",
        description="Whether the source describes one month or an average monthly amount; use not_stated when it does not establish the basis.",
    )
    income_period: DatePeriod | None = Field(
        default=None,
        title="Income reference period",
        description="Period to which the reported income or monthly average relates, only when explicitly stated.",
    )

    @model_validator(mode="after")
    def employment_dates(self) -> Self:
        if (
            self.employment_start_date
            and self.employment_end_date
            and self.employment_end_date < self.employment_start_date
        ):
            raise ValueError("employment_end_date must not precede employment_start_date")
        return self

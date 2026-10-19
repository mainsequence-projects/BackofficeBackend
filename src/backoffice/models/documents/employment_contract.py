"""Employment Contract canonical document contract."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..common import DocumentModel, Employer, Money, NonEmptyStr


class EmploymentContract(DocumentModel):
    """Structured facts from a employment contract."""

    document_type: Literal["employment_contract"] = Field(
        default="employment_contract",
        title="Document type",
        description="Identifies this payload as employment contract.",
    )
    employee_name: NonEmptyStr = Field(
        title="Employee name", description="Employee's complete name as stated in the contract."
    )
    employer: Employer = Field(
        title="Employer",
        description="Employer identity and optional registration/address details stated in the contract.",
    )
    job_title: NonEmptyStr | None = Field(
        default=None, title="Job title", description="Position or occupation named in the contract."
    )
    employment_type: NonEmptyStr = Field(
        title="Employment type",
        description="Employment arrangement stated by the contract, such as permanent or fixed-term.",
    )
    start_date: date = Field(title="Start date", description="Contractual employment start date.")
    end_date: date | None = Field(
        default=None,
        title="End date",
        description="Contractual end date when a fixed term is stated.",
    )
    salary: Money | None = Field(
        default=None,
        title="Salary",
        description="Contractual salary amount in the stated currency and frequency.",
    )
    salary_frequency: NonEmptyStr | None = Field(
        default=None,
        title="Salary frequency",
        description="Period the salary covers, such as hourly, monthly, or annually; required when salary is supplied.",
    )
    salary_basis: Literal["gross", "net", "unspecified"] | None = Field(
        default=None,
        title="Salary basis",
        description="Whether the stated salary is gross or net; required when salary is supplied.",
    )
    signed_date: date | None = Field(
        default=None, title="Signed date", description="Signature date stated in the contract."
    )

    @model_validator(mode="after")
    def employment_terms(self) -> Self:
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if (
            self.employment_type.lower().replace("-", "_").replace(" ", "_") == "fixed_term"
            and self.end_date is None
        ):
            raise ValueError("end_date is required for fixed-term employment")
        if self.salary is not None:
            if self.salary_frequency is None or self.salary_basis is None:
                raise ValueError("salary_frequency and salary_basis are required with salary")
        elif self.salary_frequency is not None or self.salary_basis is not None:
            raise ValueError("salary is required with salary_frequency or salary_basis")
        return self

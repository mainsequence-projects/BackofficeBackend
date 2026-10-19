"""Tax Return canonical document contract."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DatePeriod, DocumentModel, Money, NonEmptyStr


class TaxReturn(DocumentModel):
    """Structured facts from a tax return."""

    document_type: Literal["tax_return"] = Field(
        default="tax_return",
        title="Document type",
        description="Identifies this payload as tax return.",
    )
    taxpayer_name: NonEmptyStr = Field(
        title="Taxpayer name", description="Taxpayer's full name exactly as stated in the return."
    )
    tax_identifier: NonEmptyStr | None = Field(
        default=None,
        title="Tax identifier",
        description="Taxpayer identifier as printed, retaining masking and leading zeros.",
    )
    tax_jurisdiction: NonEmptyStr = Field(
        title="Tax jurisdiction",
        description="Tax authority or jurisdiction to which the return relates.",
    )
    tax_period: DatePeriod = Field(
        title="Tax period", description="Inclusive fiscal period covered by the return."
    )
    declared_income: Money = Field(
        title="Declared income",
        description="Total income declared for the stated period and currency.",
    )
    taxable_income: Money | None = Field(
        default=None,
        title="Taxable income",
        description="Income subject to taxation as stated by the return.",
    )
    economic_activity: NonEmptyStr | None = Field(
        default=None,
        title="Economic activity",
        description="Occupation, business activity, or category explicitly declared in the return.",
    )
    filing_date: date | None = Field(
        default=None,
        title="Filing date",
        description="Date of submission when established by the source.",
    )
    filing_reference: NonEmptyStr | None = Field(
        default=None,
        title="Filing reference",
        description="Authority-issued submission/acknowledgment reference, when supplied.",
    )

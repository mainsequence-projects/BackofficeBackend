"""Utility Bill canonical document contract."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DatePeriod, DocumentModel, Money, NonEmptyStr, PostalAddress


class UtilityBill(DocumentModel):
    """Structured facts from a utility bill."""

    document_type: Literal["utility_bill"] = Field(
        default="utility_bill",
        title="Document type",
        description="Identifies this payload as utility bill.",
    )
    account_holder_name: NonEmptyStr = Field(
        title="Account holder name",
        description="Customer or account-holder name printed on the bill.",
    )
    service_address: PostalAddress = Field(
        title="Service address",
        description="Address where the utility service is supplied, distinguished from a mailing address.",
    )
    provider_name: NonEmptyStr = Field(
        title="Provider name", description="Utility provider's name as printed."
    )
    utility_type: NonEmptyStr = Field(
        title="Utility type",
        description="Type of service stated by the bill, such as electricity, water, gas, or telecommunications.",
    )
    issue_date: date = Field(
        title="Issue date", description="Bill issue date used for the document-age check."
    )
    billing_period: DatePeriod | None = Field(
        default=None,
        title="Billing period",
        description="Service period covered by the bill, when printed.",
    )
    account_number: NonEmptyStr | None = Field(
        default=None,
        title="Account number",
        description="Provider's customer/account identifier, preserving leading zeros.",
    )
    total_due: Money | None = Field(
        default=None,
        title="Total due",
        description="Total amount due as printed, if needed by the configured workflow.",
    )

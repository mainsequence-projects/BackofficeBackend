"""Reusable documented fields; source text is preserved without normalization."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class ContractModel(BaseModel):
    """Reject unknown fields and non-finite numbers at every contract boundary."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class PostalAddress(ContractModel):
    """An address as printed; policy decides which local components are necessary."""

    address_line_1: NonEmptyStr = Field(
        title="Address line 1",
        description="Primary street, building, or locality line exactly as stated by the source.",
    )
    address_line_2: NonEmptyStr | None = Field(
        default=None,
        title="Address line 2",
        description="Additional unit, floor, building, or locality information; null when absent.",
    )
    city: NonEmptyStr | None = Field(
        default=None,
        title="City",
        description="City or locality named in the address; null when absent.",
    )
    region: NonEmptyStr | None = Field(
        default=None,
        title="Region",
        description="State, province, or administrative region named in the address; null when absent.",
    )
    postal_code: NonEmptyStr | None = Field(
        default=None,
        title="Postal code",
        description="Postal code as printed, preserving letters, spaces, and leading zeros; null when absent.",
    )
    country_code: CountryCode | None = Field(
        default=None,
        title="Country code",
        description="ISO two-letter country code established by the source or verified reference; null when unknown.",
    )


class Money(ContractModel):
    """Exact monetary value; JSON serializes the amount as a decimal string."""

    amount: Decimal = Field(
        title="Amount",
        description="Monetary amount in the associated currency, preserving source precision and sign.",
    )
    currency: CurrencyCode = Field(
        title="Currency", description="ISO three-letter currency code for the monetary amount."
    )


class DatePeriod(ContractModel):
    """Inclusive calendar interval."""

    start_date: date = Field(
        title="Start date",
        description="First calendar date included in the reporting or payment period, as YYYY-MM-DD.",
    )
    end_date: date = Field(
        title="End date",
        description="Last calendar date included in the period, as YYYY-MM-DD; must not precede the start date.",
    )

    @model_validator(mode="after")
    def ordered_dates(self) -> Self:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class Employer(ContractModel):
    """Employer identity stated in a document."""

    name: NonEmptyStr = Field(
        title="Employer name", description="Employer's legal or trading name exactly as printed."
    )
    registration_number: NonEmptyStr | None = Field(
        default=None,
        title="Registration number",
        description="Employer registration identifier as printed, preserving formatting and leading zeros; null when absent.",
    )
    address: PostalAddress | None = Field(
        default=None,
        title="Employer address",
        description="Employer address stated in the document; null when absent.",
    )


class BankTransaction(ContractModel):
    """A transcribed bank entry, not a claim of complete statement coverage."""

    booking_date: date = Field(
        title="Booking date",
        description="Date the bank records the transaction in the statement, as YYYY-MM-DD.",
    )
    value_date: date | None = Field(
        default=None,
        title="Value date",
        description="Printed transaction value date; null when not stated separately.",
    )
    amount: Money = Field(
        title="Transaction amount",
        description="Signed amount: positive is credit and negative is debit from the account holder's perspective.",
    )
    description: NonEmptyStr | None = Field(
        default=None,
        title="Transaction description",
        description="Transaction narrative exactly as printed; null when absent.",
    )
    counterparty_name: NonEmptyStr | None = Field(
        default=None,
        title="Counterparty name",
        description="Named payer or payee explicitly identified by the statement; null when absent.",
    )


class EvidenceRegion(ContractModel):
    """A location within one immutable raw source."""

    raw_document_uid: UUID = Field(
        title="Source document UID",
        description="UID of the immutable source document containing this evidence.",
    )
    page_number: int = Field(
        gt=0, title="Page number", description="One-based page number in the source document."
    )
    bounding_box: list[Annotated[float, Field(ge=0, le=1)]] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        title="Bounding box",
        description="Normalized [left, top, right, bottom] coordinates on the upright page; null when only the page is known.",
    )

    @model_validator(mode="after")
    def ordered_coordinates(self) -> Self:
        if self.bounding_box is not None:
            left, top, right, bottom = self.bounding_box
            if left >= right or top >= bottom:
                raise ValueError("bounding_box must have positive width and height")
        return self


class DocumentModel(ContractModel):
    """Base for completed document payloads; lifecycle metadata is in the envelope."""

    @model_validator(mode="after")
    def chronological_dates(self) -> Self:
        issue = getattr(self, "issue_date", None)
        expiry = getattr(self, "expiration_date", None)
        birth = getattr(self, "date_of_birth", None)
        if issue and expiry and expiry < issue:
            raise ValueError("expiration_date must not precede issue_date")
        if birth and issue and birth > issue:
            raise ValueError("date_of_birth must not follow issue_date")
        if birth and expiry and birth > expiry:
            raise ValueError("date_of_birth must not follow expiration_date")
        validity = getattr(self, "validity_type", None)
        if validity == "fixed_term" and expiry is None:
            raise ValueError("expiration_date is required for fixed_term validity")
        if validity == "permanent" and expiry is not None:
            raise ValueError("permanent validity cannot have an expiration_date")
        return self

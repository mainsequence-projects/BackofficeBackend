"""Residence Permit canonical document contract."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, NonEmptyStr


class ResidencePermit(DocumentModel):
    """Structured facts from a residence permit."""

    document_type: Literal["residence_permit"] = Field(
        default="residence_permit",
        title="Document type",
        description="Identifies this payload as residence permit.",
    )
    full_name: NonEmptyStr = Field(
        title="Full name", description="Permit holder's complete name exactly as printed."
    )
    date_of_birth: date | None = Field(
        default=None,
        title="Date of birth",
        description="Holder's printed date of birth, if present.",
    )
    permit_number: NonEmptyStr = Field(
        title="Permit number", description="Residence-permit identifier exactly as printed."
    )
    issuing_country: NonEmptyStr = Field(
        title="Issuing country",
        description="Country or authority that issued the residence permit.",
    )
    permit_type: NonEmptyStr = Field(
        title="Permit type",
        description="Printed permit category or class without inferring additional entitlements.",
    )
    residency_status: NonEmptyStr | None = Field(
        default=None,
        title="Residency status",
        description="Residency status explicitly stated by the source.",
    )
    issue_date: date | None = Field(
        default=None, title="Issue date", description="Printed permit issue date."
    )
    validity_type: Literal["fixed_term", "permanent", "unknown"] = Field(
        title="Validity type",
        description="Validity stated by the document; unknown when the source does not establish it.",
    )
    expiration_date: date | None = Field(
        default=None,
        title="Expiration date",
        description="Printed expiry date; required for fixed-term validity.",
    )
    conditions: list[NonEmptyStr] | None = Field(
        default=None,
        title="Conditions",
        description="Restrictions or conditions transcribed from the permit.",
    )

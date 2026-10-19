"""National Identity Card canonical document contract."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, EvidenceRegion, NonEmptyStr


class NationalIdentityCard(DocumentModel):
    """Structured facts from a national identity card."""

    document_type: Literal["national_identity_card"] = Field(
        default="national_identity_card",
        title="Document type",
        description="Identifies this payload as national identity card.",
    )
    full_name: NonEmptyStr = Field(
        title="Full name", description="Holder's complete name exactly as printed on the card."
    )
    given_names: NonEmptyStr | None = Field(
        default=None,
        title="Given names",
        description="All given names in their printed order when identified separately.",
    )
    last_name: NonEmptyStr | None = Field(
        default=None,
        title="Last name",
        description="Surname or family name when identified separately on the card.",
    )
    date_of_birth: date = Field(
        title="Date of birth", description="Holder's printed date of birth, entered as YYYY-MM-DD."
    )
    identity_number: NonEmptyStr = Field(
        title="Identity number",
        description="Identity identifier printed on the card, preserving letters and leading zeros.",
    )
    issuing_country: NonEmptyStr = Field(
        title="Issuing country", description="Country or issuing authority identified on the card."
    )
    issue_date: date | None = Field(
        default=None, title="Issue date", description="Date the card was issued, if printed."
    )
    validity_type: Literal["fixed_term", "permanent", "unknown"] = Field(
        title="Validity type",
        description="Whether the source states a fixed expiry, permanent validity, or does not establish validity.",
    )
    expiration_date: date | None = Field(
        default=None,
        title="Expiration date",
        description="Printed expiry date; required when validity is fixed-term.",
    )
    portrait_reference: EvidenceRegion | None = Field(
        default=None,
        title="Portrait reference",
        description="Location of the holder's portrait in the source document.",
    )

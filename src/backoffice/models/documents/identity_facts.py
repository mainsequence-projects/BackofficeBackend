"""Text identity facts for product V1; portrait and face comparison belong to V2.

Published earlier schemas remain available for historical revisions. These schema
version numbers are independent of the product's V1/V2 delivery scope.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, NonEmptyStr


class NationalIdentityCardV3(DocumentModel):
    """Identity-card facts without portrait collection or biometric requirements."""

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
    issuing_country: NonEmptyStr | None = Field(
        default=None,
        title="Issuing country",
        description="Country or issuing authority when explicitly extracted from the source; absent from the happy-case field contract and never guessed from a person's address.",
    )
    issue_date: date | None = Field(
        default=None, title="Issue date", description="Date the card was issued, if printed."
    )
    validity_type: Literal["fixed_term", "permanent", "unknown"] | None = Field(
        default=None,
        title="Validity type",
        description="Explicit validity classification when available; null means not classified, never permanent. A printed expiry can establish validity without this metadata.",
    )
    expiration_date: date | None = Field(
        default=None,
        title="Expiration date",
        description="Printed expiry date; required when validity is fixed-term.",
    )


class PassportV2(DocumentModel):
    """Passport facts without portrait collection or biometric requirements."""

    document_type: Literal["passport"] = Field(
        default="passport",
        title="Document type",
        description="Identifies this payload as passport.",
    )
    full_name: NonEmptyStr = Field(
        title="Full name",
        description="Holder's complete name exactly as printed in the visual inspection zone.",
    )
    given_names: NonEmptyStr | None = Field(
        default=None,
        title="Given names",
        description="All given names in their printed order, if separately identified.",
    )
    last_name: NonEmptyStr | None = Field(
        default=None,
        title="Last name",
        description="Printed surname or family name, if separately identified.",
    )
    date_of_birth: date = Field(
        title="Date of birth", description="Holder's printed date of birth, entered as YYYY-MM-DD."
    )
    passport_number: NonEmptyStr = Field(
        title="Passport number",
        description="Passport identifier exactly as printed, preserving letters and leading zeros.",
    )
    nationality: NonEmptyStr = Field(
        title="Nationality",
        description="Nationality exactly as stated by the passport; retain the original value.",
    )
    issuing_country: NonEmptyStr = Field(
        title="Issuing country",
        description="Country or issuing authority identified on the passport.",
    )
    issue_date: date | None = Field(
        default=None, title="Issue date", description="Date the passport was issued, if printed."
    )
    expiration_date: date = Field(
        title="Expiration date", description="Printed passport expiry date, entered as YYYY-MM-DD."
    )
    mrz_lines: list[NonEmptyStr] | None = Field(
        default=None,
        min_length=1,
        title="Mrz lines",
        description="MRZ lines in printed order, preserving every character including `<` fillers.",
    )

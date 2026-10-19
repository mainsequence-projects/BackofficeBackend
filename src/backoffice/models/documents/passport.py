"""Passport canonical document contract."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, EvidenceRegion, NonEmptyStr


class Passport(DocumentModel):
    """Structured facts from a passport."""

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
    portrait_reference: EvidenceRegion | None = Field(
        default=None,
        title="Portrait reference",
        description="Location of the holder's portrait in the passport source.",
    )

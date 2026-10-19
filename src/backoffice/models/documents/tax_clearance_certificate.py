"""Tax-authority certificate facts; not a tax return or a clearance decision."""

from datetime import date
from typing import Literal

from pydantic import Field

from ..common import DocumentModel, Money, NonEmptyStr


class TaxClearanceCertificate(DocumentModel):
    """Preserve the authority's statement, including reported arrears or uncertainty."""

    document_type: Literal["tax_clearance_certificate"] = Field(
        default="tax_clearance_certificate",
        title="Document type",
        description="Identifies a tax-authority arrears or clearance certificate, distinct from a tax return.",
    )
    taxpayer_name: NonEmptyStr = Field(
        title="Taxpayer name",
        description="Taxpayer's complete name exactly as printed on the certificate.",
    )
    tax_identifier: NonEmptyStr | None = Field(
        default=None,
        title="Tax identifier",
        description="Taxpayer identifier as printed, preserving leading zeros and formatting.",
    )
    issuing_authority: NonEmptyStr = Field(
        title="Issuing authority",
        description="Tax authority explicitly identified as issuing the certificate.",
    )
    certificate_number: NonEmptyStr | None = Field(
        default=None,
        title="Certificate number",
        description="Authority-issued certificate reference exactly as printed, if present.",
    )
    issue_date: date = Field(
        title="Issue date",
        description="Date the tax authority issued the certificate, as YYYY-MM-DD.",
    )
    as_of_date: date | None = Field(
        default=None,
        title="Statement date",
        description="Date to which the arrears statement applies, if separately printed.",
    )
    arrears_statement: Literal["no_arrears", "arrears_reported", "not_stated"] = Field(
        title="Authority's arrears statement",
        description="Meaning explicitly stated by the authority; not_stated means no interpretable claim, not zero debt or clearance.",
    )
    statement_as_printed: NonEmptyStr = Field(
        title="Statement as printed",
        description="Source wording supporting the authority's statement, without a Back Office decision.",
    )
    arrears_amount: Money | None = Field(
        default=None,
        title="Reported arrears amount",
        description="Amount and currency explicitly printed; null is unknown, never inferred as zero from a clearance statement.",
    )

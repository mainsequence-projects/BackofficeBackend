"""Source-of-Funds Evidence canonical document contract."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from ..common import DocumentModel, Money, NonEmptyStr


class SourceOfFundsEvidence(DocumentModel):
    """Structured facts from a source-of-funds evidence."""

    document_type: Literal["source_of_funds_evidence"] = Field(
        default="source_of_funds_evidence",
        title="Document type",
        description="Identifies this payload as source-of-funds evidence.",
    )
    owner_name: NonEmptyStr = Field(
        title="Owner name",
        description="Person or entity identified as the owner or recipient of the funds.",
    )
    source_type: NonEmptyStr = Field(
        title="Source type",
        description="Stated origin category, such as salary, savings, asset sale, inheritance, gift, business income, or other.",
    )
    amount: Money = Field(
        title="Amount", description="Amount whose source is being explained, with its currency."
    )
    event_date: date | None = Field(
        default=None,
        title="Event date",
        description="Date of the originating event or transfer, when stated.",
    )
    originator_name: NonEmptyStr | None = Field(
        default=None,
        title="Originator name",
        description="Named payer, donor, seller, estate, or other originating party.",
    )
    explanation: NonEmptyStr = Field(
        title="Explanation",
        description="Factual explanation connecting the originating event to the funds being assessed.",
    )
    supporting_document_ids: list[UUID] | None = Field(
        default=None,
        title="Supporting document ids",
        description="Linked evidence documents supporting the explanation; required for policies that request substantiation.",
    )

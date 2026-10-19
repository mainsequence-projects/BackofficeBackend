"""Source references and revision-specific review results."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, computed_field, model_validator

from ..schemas.registry import DocumentPayload
from .common import ContractModel, NonEmptyStr


class RawDocumentRef(ContractModel):
    raw_document_uid: UUID = Field(
        title="Source UID",
        description="Stable UID of a ready immutable raw source stored through Main Sequence MetaTables.",
    )
    first_page: int | None = Field(
        default=None,
        ge=1,
        title="First page",
        description="First included source page, one-based; null uses the entire source.",
    )
    last_page: int | None = Field(
        default=None,
        ge=1,
        title="Last page",
        description="Last included source page, one-based and inclusive; null uses the entire source.",
    )

    @model_validator(mode="after")
    def valid_page_range(self) -> Self:
        if (self.first_page is None) != (self.last_page is None):
            raise ValueError("first_page and last_page must be supplied together")
        if self.first_page is not None and self.last_page < self.first_page:
            raise ValueError("last_page must not precede first_page")
        return self


class DocumentReview(ContractModel):
    uid: UUID = Field(title="Review UID", description="Stable UID of the recorded review decision.")
    document_uid: UUID = Field(
        title="Document UID", description="Logical document that the reviewed revision belongs to."
    )
    revision: int = Field(
        ge=1,
        title="Reviewed revision",
        description="Exact document revision evaluated by the reviewer.",
    )
    decision: Literal["accepted", "rejected"] = Field(
        title="Decision",
        description="Explicit reviewer decision; pending means no effective review exists.",
    )
    reviewed_by: UUID = Field(
        title="Reviewer UID",
        description="Trusted Main Sequence User UID recorded by the review service.",
    )
    reviewed_at: AwareDatetime = Field(
        title="Review time",
        description="Timezone-aware instant when the review decision was recorded.",
    )
    reason: NonEmptyStr = Field(
        title="Review reason", description="Reviewer's explanation of the acceptance or rejection."
    )


class DocumentInstance(ContractModel):
    uid: UUID = Field(
        title="Document UID", description="Stable UID of the person's logical document."
    )
    person_uid: UUID = Field(
        title="Person UID", description="Business person to whom this document belongs."
    )
    revision: int = Field(
        ge=1,
        title="Revision",
        description="Positive revision of the immutable submitted attributes and source references.",
    )
    created_at: AwareDatetime = Field(
        title="Document recorded at",
        description="Server-recorded instant when the logical document was first created; not the evidence issue date.",
    )
    revision_created_at: AwareDatetime = Field(
        title="Revision recorded at",
        description="Server-recorded instant when this exact revision was created.",
    )
    submitted_at: AwareDatetime = Field(
        title="Revision submitted at",
        description="Server-recorded instant when this completed revision became immutable.",
    )
    schema_version: Literal[1] = Field(
        default=1,
        title="Schema version",
        description="Exact document contract version used by this revision.",
    )
    data: DocumentPayload = Field(
        title="Document attributes",
        description="Completed typed document attributes selected by document_type.",
    )
    raw_document_refs: list[RawDocumentRef] = Field(
        min_length=1,
        title="Raw documents",
        description="References to immutable ready source documents, including front/back images or a questionnaire snapshot.",
    )
    latest_review: DocumentReview | None = Field(
        default=None,
        title="Latest review",
        description="Effective review for this exact revision; null means pending review.",
    )

    @model_validator(mode="after")
    def review_targets_this_revision(self) -> Self:
        review = self.latest_review
        if review and (review.document_uid != self.uid or review.revision != self.revision):
            raise ValueError("latest_review must target this document and revision")
        return self

    @computed_field(
        description="Read-only review state of this revision; pending when no effective decision exists."
    )
    @property
    def review_status(self) -> Literal["pending", "accepted", "rejected"]:
        return self.latest_review.decision if self.latest_review else "pending"

    @computed_field(
        description="Read-only acceptance flag derived from the effective review of this exact revision."
    )
    @property
    def accepted(self) -> bool:
        return self.review_status == "accepted"

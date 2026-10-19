"""Assign an immutable requirement version to a person."""

from typing import Self
from uuid import UUID

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr


class PersonDocumentSet(ContractModel):
    uid: UUID = Field(
        title="Assignment UID",
        description="Stable identifier of this person's document-set assignment.",
    )
    person_uid: UUID = Field(
        title="Person UID",
        description="Business person whose documents are evaluated for this assignment.",
    )
    document_set_key: NonEmptyStr = Field(
        title="Document set",
        description="Stable identifier of the reusable requirement definition.",
    )
    document_set_version: int = Field(
        ge=1,
        title="Pinned set version",
        description="Exact published version assigned to this person; newer definitions do not silently replace it.",
    )
    revision: int = Field(
        default=1,
        ge=1,
        title="Assignment revision",
        description="Revision used to detect concurrent assignment changes.",
    )
    document_uids: list[UUID] = Field(
        default_factory=list,
        title="Submitted documents",
        description="Distinct logical documents linked to this assignment; ownership is checked by the application service.",
    )

    @model_validator(mode="after")
    def unique_documents(self) -> Self:
        if len(self.document_uids) != len(set(self.document_uids)):
            raise ValueError("document_uids must not contain duplicates")
        return self

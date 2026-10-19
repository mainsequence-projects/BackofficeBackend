"""Business cases are independent of their supplied evidence and assigned staff."""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from .common import ContractModel, NonEmptyStr


class CaseType(ContractModel):
    key: NonEmptyStr = Field(
        description="Stable business process key, for example account_opening or new_loan."
    )
    name: NonEmptyStr = Field(description="Human-readable business process name.")
    description: NonEmptyStr = Field(
        description="Business purpose; evidence rules live in the linked Document Set version."
    )


class Case(ContractModel):
    uid: UUID = Field(
        description="Stable case UID; migrated cases preserve their original assignment UID."
    )
    subject_uid: UUID = Field(
        description="Business Person UID whose evidence is assessed; never a staff identity."
    )
    case_type_key: NonEmptyStr = Field(
        description="Explicit business process governing which Document Set versions may be selected."
    )
    document_set_key: NonEmptyStr = Field(
        description="Foreign-key part identifying the pinned requirement policy."
    )
    document_set_version: int = Field(
        ge=1, description="Foreign-key part identifying the exact published policy version."
    )
    revision: int = Field(
        ge=1, description="Case evidence-membership revision used to reject stale writes."
    )
    created_at: datetime = Field(
        description="UTC instant when the case was created, retained during migration."
    )
    updated_at: datetime = Field(
        description="UTC instant of the latest case evidence-membership change."
    )
    document_uids: list[UUID] = Field(
        default_factory=list,
        description="Selected logical documents belonging to this subject; empty when a case is first opened.",
    )

    @model_validator(mode="after")
    def distinct_documents(self):
        if len(set(self.document_uids)) != len(self.document_uids):
            raise ValueError("document_uids must be distinct")
        return self

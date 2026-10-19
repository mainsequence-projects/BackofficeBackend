"""Validated API commands; identities and acceptance are always server-owned."""

from typing import Any, Literal
from uuid import UUID

from pydantic import Field, create_model

from ..models.common import ContractModel, NonEmptyStr
from ..models.document import RawDocumentRef
from ..models.person import Person
from ..schemas.registry import DocumentType
from ..tables.evidence import MAX_CHUNK_BASE64_LENGTH


class Command(ContractModel):
    operation_key: UUID = Field(
        description="Client-generated idempotency UUID. Reuse it with the identical request after an uncertain response."
    )


# Preserve the canonical profile field descriptions and validation in API forms.
PersonInput = create_model(
    "PersonInput",
    __base__=ContractModel,
    **{
        key: (field.annotation, field)
        for key, field in Person.model_fields.items()
        if key not in {"uid", "revision"}
    },
)


class CreatePerson(Command):
    profile: PersonInput = Field(
        description="Reference attributes, distinct from claims in uploaded documents."
    )


class UpdatePerson(CreatePerson):
    expected_revision: int = Field(
        ge=1, description="Profile revision the editor loaded; stale writes return 409."
    )


class AssignSet(Command):
    document_set_key: NonEmptyStr = Field(description="Exact authored policy key.")
    document_set_version: int = Field(ge=1, description="Exact immutable policy version to assign.")


class AssignmentDocuments(Command):
    expected_revision: int = Field(ge=1, description="Assignment revision loaded by the editor.")
    document_uids: list[UUID] = Field(
        max_length=200, description="Distinct documents owned by the assignment's person."
    )


class CreateDocument(Command):
    document_type: DocumentType = Field(
        description="Type selecting the canonical and draft schemas."
    )
    schema_version: int = Field(default=1, ge=1, description="Exact document schema version.")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Partial draft attributes; canonical validation runs at submission.",
    )
    raw_document_refs: list[RawDocumentRef] = Field(
        default_factory=list, max_length=20, description="Ready raw evidence owned by this person."
    )


class SaveDraft(Command):
    expected_revision: int = Field(
        ge=1, description="Latest document revision loaded by the editor."
    )
    payload: dict[str, Any] = Field(
        description="Replacement draft attributes. Saving creates a new revision."
    )
    raw_document_refs: list[RawDocumentRef] = Field(
        max_length=20, description="Replacement source references owned by this person."
    )


class SubmitDocument(Command):
    expected_revision: int = Field(
        ge=1, description="Exact latest draft revision to submit and freeze."
    )


class ReviewDocument(SubmitDocument):
    expected_decision_sequence: int = Field(
        ge=0, description="Latest review sequence observed, zero when no decision exists."
    )
    decision: Literal["accepted", "rejected"] = Field(
        description="Explicit decision for the submitted revision."
    )
    reason: NonEmptyStr = Field(
        max_length=4000, description="Reviewer explanation retained with the decision."
    )


class StartUpload(Command):
    person_uid: UUID = Field(description="Person owning the raw evidence.")
    filename: NonEmptyStr = Field(
        max_length=255, description="Display filename only, never a filesystem path."
    )
    media_type: Literal["application/pdf", "image/png", "image/jpeg", "text/plain"] = Field(
        description="Supported source format; file signatures are checked at finalization."
    )
    byte_count: int = Field(
        gt=0, le=10 * 1024 * 1024, description="Exact source size, up to 10 MiB."
    )
    content_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="SHA-256 of the complete decoded file."
    )


class UploadChunk(ContractModel):
    content_base64: str = Field(
        min_length=4,
        max_length=MAX_CHUNK_BASE64_LENGTH,
        description="Strict base64 of up to 256 KiB. An existing chunk is immutable and may be retried identically.",
    )


class Evaluate(Command):
    expected_revision: int = Field(
        ge=1,
        description="Assignment revision to evaluate; evaluation date is the server's UTC calendar date.",
    )

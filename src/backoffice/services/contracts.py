"""Validated API commands; identities and acceptance are always server-owned."""

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictInt, create_model, model_validator

from ..models.common import ContractModel, NonEmptyStr
from ..models.document import RawDocumentRef
from ..models.person import Person
from ..schemas.registry import DocumentType
from ..tables.evidence import MAX_CHUNK_BASE64_LENGTH


class Command(ContractModel):
    operation_key: UUID = Field(
        description="Client-generated idempotency UUID. Reuse it with the identical request after an uncertain response."
    )


class UpdateParsingPolicy(Command):
    document_type: DocumentType = Field(
        description="Canonical document type whose classification acceptance policy is being changed."
    )
    expected_revision: StrictInt = Field(
        ge=0,
        description="Revision for this document type loaded by the administrator; zero means unconfigured.",
    )
    automatic_acceptance_enabled: StrictBool = Field(
        description="Enable automatic acceptance for qualifying valid document revisions."
    )
    acceptance_threshold_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Inclusive classification confidence cutoff in percent from 0 to 100, with at most two decimal places; 60 means 60 percent.",
    )

    @model_validator(mode="after")
    def configured_threshold(self):
        if self.automatic_acceptance_enabled and self.acceptance_threshold_percent is None:
            raise ValueError(
                "An acceptance threshold is required when automatic acceptance is enabled."
            )
        return self


class CompleteParsing(Command):
    expected_revision: StrictInt = Field(
        ge=1, description="Exact latest document revision scored by the trusted processor."
    )
    parsing_score_percent: Decimal | None = Field(
        default=None,
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Trusted classification confidence for this exact document revision, in percent from 0 to 100; absent scores always require review. This is not extraction completeness or attribute accuracy.",
    )
    extractor: NonEmptyStr = Field(
        max_length=120, description="Extractor identifier and version retained with the score."
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


class SetMyCaseMembership(Command):
    expected_revision: StrictInt = Field(
        ge=0, description="Loaded staff membership revision, or zero when never assigned."
    )
    assigned: StrictBool = Field(
        description="Take or leave responsibility as the verified staff caller; does not grant permissions."
    )


class CreateCase(AssignSet):
    subject_uid: UUID = Field(
        description="Existing business Person UID; never a staff reviewer UID."
    )
    case_type_key: str = Field(
        min_length=1,
        max_length=80,
        description="Explicit business process key whose permitted document-set versions constrain this case.",
    )


class BuildCase(CreateCase):
    """Strict case creation for the agent's scoped workflow."""

    document_set_version: StrictInt = Field(ge=1, description="Exact published policy version.")


class LinkCaseDocuments(AssignmentDocuments):
    case_uid: UUID = Field(description="Case whose append-only evidence membership is changed.")
    expected_revision: StrictInt = Field(ge=1, description="Loaded case revision.")


class EvaluateCase(Evaluate):
    case_uid: UUID = Field(
        description="Case to evaluate; retained in the durable operation intent."
    )
    expected_revision: StrictInt = Field(ge=1, description="Loaded case revision.")


class SetMyCaseResponsibility(SetMyCaseMembership):
    case_uid: UUID = Field(description="Case to take or leave as the verified staff caller.")

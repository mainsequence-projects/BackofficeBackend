"""Logical documents, submitted revisions, and append-only review decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Created, Identified, info


class DocumentRecord(Identified, Created, Base):
    __tablename__ = "backoffice__document"
    __metatable_identifier__ = "backoffice.document"
    __metatable_description__ = "One logical document owned by one business person, with a stable document type and an optional pointer to its current submitted revision."
    __metatable_labels__ = ("backoffice", "document", "person")
    __table_args__ = (
        UniqueConstraint("uid", "person_uid"),
        UniqueConstraint("uid", "person_uid", "document_type"),
        CheckConstraint(
            "current_revision IS NULL OR current_revision >= 1", name="positive_revision"
        ),
    )

    person_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__person.uid"),
        index=True,
        info=info("Person UID", "Business person who owns this document."),
    )
    document_type: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Document type",
            "Stable discriminator shared by every revision of this logical document.",
        ),
    )
    current_revision: Mapped[int | None] = mapped_column(
        Integer,
        info=info(
            "Current revision",
            "Current submitted revision number; absent before first submission. The service verifies the target before advancing it.",
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Updated at", "UTC instant of the latest logical-document change."),
    )


class DocumentRevisionRecord(Identified, Created, Base):
    __tablename__ = "backoffice__document_revision"
    __metatable_identifier__ = "backoffice.document_revision"
    __metatable_description__ = "One document attribute revision with an exact schema version and immutable raw-source references. Drafts may change; submitted content is immutable and requires its own review."
    __metatable_labels__ = ("backoffice", "document", "history")
    __table_args__ = (
        UniqueConstraint("document_uid", "revision"),
        UniqueConstraint("uid", "person_uid"),
        ForeignKeyConstraint(
            ["document_uid", "person_uid", "document_type"],
            [
                "backoffice__document.uid",
                "backoffice__document.person_uid",
                "backoffice__document.document_type",
            ],
        ),
        ForeignKeyConstraint(
            ["document_type", "schema_version"],
            ["backoffice__document_schema.document_type", "backoffice__document_schema.version"],
        ),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint("status IN ('draft', 'submitted')", name="allowed_status"),
        CheckConstraint(
            "(status = 'draft' AND submitted_at IS NULL) OR (status = 'submitted' AND submitted_at IS NOT NULL)",
            name="submission_time",
        ),
    )

    document_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Document UID", "Logical document containing this revision.")
    )
    person_uid: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Person UID",
            "Owner inherited from the logical document, used to enforce evidence ownership.",
        ),
    )
    document_type: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Document type", "Discriminator selecting the document contract for this revision."
        ),
    )
    revision: Mapped[int] = mapped_column(
        Integer, info=info("Revision", "Positive revision unique within the logical document.")
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        info=info("Schema version", "Published contract version used to validate attributes."),
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Attributes",
            "Draft or canonical document attributes validated against the recorded schema version before writing.",
        ),
    )
    extraction_evidence: Mapped[dict | None] = mapped_column(
        JSON,
        info=info(
            "Extraction evidence",
            "Immutable parser observations, reader candidates and source mapping for this exact revision; absent for manual or legacy revisions.",
        ),
    )
    raw_document_refs: Mapped[list] = mapped_column(
        JSON,
        info=info(
            "Raw sources",
            "Serialized RawDocumentRef values containing source UIDs and optional page ranges; the service checks readiness and ownership on submission.",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Submission status",
            "Draft permits edits; submitted freezes the payload and source references.",
        ),
    )
    created_by: Mapped[UUID] = mapped_column(
        Uuid, info=info("Created by", "Trusted Main Sequence User UID that created this revision.")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        info=info(
            "Submitted at",
            "UTC instant when canonical validation completed and the revision became immutable.",
        ),
    )


class DocumentReviewRecord(Identified, Base):
    __tablename__ = "backoffice__document_review"
    __metatable_identifier__ = "backoffice.document_review"
    __metatable_description__ = "One append-only acceptance or rejection decision for an exact submitted document revision. Operation identity prevents duplicate decisions on retries."
    __metatable_labels__ = ("backoffice", "document", "review")
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_uid", "revision"],
            [
                "backoffice__document_revision.document_uid",
                "backoffice__document_revision.revision",
            ],
        ),
        UniqueConstraint("operation_key"),
        UniqueConstraint("document_uid", "revision", "decision_sequence"),
        CheckConstraint("decision IN ('accepted', 'rejected')", name="allowed_decision"),
        CheckConstraint("decision_sequence >= 1", name="positive_sequence"),
    )

    document_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Document UID", "Logical document whose exact revision was reviewed.")
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info("Reviewed revision", "Immutable submitted revision evaluated by the reviewer."),
    )
    decision_sequence: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Decision sequence",
            "Monotonically increasing order within the reviewed revision; the greatest sequence is effective.",
        ),
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Decision",
            "Explicit acceptance or rejection; absence of a decision means pending review.",
        ),
    )
    reviewed_by: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Reviewed by", "Trusted Main Sequence User UID authorized to make this decision."
        ),
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Reviewed at", "UTC instant when the decision was recorded."),
    )
    reason: Mapped[str] = mapped_column(
        Text, info=info("Reason", "Reviewer's explanation of the decision.")
    )
    operation_key: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Operation key",
            "Stable idempotency UUID reused for retries of this exact review request.",
        ),
    )

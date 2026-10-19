"""Published document contracts, policies, and person assignments."""

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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Created, Identified, info


class DocumentSchemaRecord(Created, Base):
    __tablename__ = "backoffice__document_schema"
    __metatable_identifier__ = "backoffice.document_schema"
    __metatable_description__ = "One immutable published contract version for one document type, with canonical and draft JSON Schemas for validation and form generation."
    __metatable_labels__ = ("backoffice", "schema", "forms")
    __table_args__ = (
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
    )

    document_type: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
        info=info(
            "Document type", "Stable discriminator of the document contract, for example passport."
        ),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        info=info(
            "Schema version", "Immutable positive schema version pinned by submitted revisions."
        ),
    )
    canonical_schema: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Canonical schema",
            "Generated JSON Schema for complete document attributes, including field titles and descriptions.",
        ),
    )
    draft_schema: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Draft schema",
            "Generated JSON Schema for incomplete extraction or editing with the same field metadata.",
        ),
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        info=info(
            "Content checksum",
            "SHA-256 of the canonical JSON encoding of the canonical and draft schema pair.",
        ),
    )


class DocumentSetVersionRecord(Created, Base):
    __tablename__ = "backoffice__document_set_version"
    __metatable_identifier__ = "backoffice.document_set_version"
    __metatable_description__ = "One named requirement-policy version defining accepted alternatives, conditional requirements, counts and freshness rules. Published definitions are immutable."
    __metatable_labels__ = ("backoffice", "requirements", "policy")
    __table_args__ = (
        CheckConstraint("version >= 1", name="positive_version"),
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="allowed_status"),
        CheckConstraint("status = 'draft' OR published_at IS NOT NULL", name="publication_time"),
    )

    set_key: Mapped[str] = mapped_column(
        String(120),
        primary_key=True,
        info=info("Set key", "Stable reusable requirement-set identifier."),
    )
    version: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        info=info("Set version", "Immutable positive version selected by person assignments."),
    )
    definition: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Definition",
            "Validated serialized DocumentSet contract with exact schema references and requirements.",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Publication status",
            "Draft, published, or retired; retired versions remain available to existing assignments.",
        ),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        info=info(
            "Published at",
            "UTC publication instant; absent until the definition is first published.",
        ),
    )


class PersonDocumentSetRecord(Identified, Created, Base):
    __tablename__ = "backoffice__person_document_set"
    __metatable_identifier__ = "backoffice.person_document_set"
    __metatable_description__ = "One person's assignment to an exact requirement-policy version. The assignment revision changes when its selected documents or policy version change."
    __metatable_labels__ = ("backoffice", "person", "requirements")
    __table_args__ = (
        ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
        ),
        UniqueConstraint("uid", "person_uid"),
        CheckConstraint("revision >= 1", name="positive_revision"),
    )

    person_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__person.uid"),
        index=True,
        info=info(
            "Person UID", "Business person being evaluated against the assigned requirements."
        ),
    )
    set_key: Mapped[str] = mapped_column(
        String(120), info=info("Set key", "Stable identifier of the assigned requirement set.")
    )
    set_version: Mapped[int] = mapped_column(
        Integer,
        info=info("Set version", "Exact requirement-set version pinned to this assignment."),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Assignment revision",
            "Positive revision used to reject stale assignment updates and evaluations.",
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Updated at", "UTC instant of the latest assignment change."),
    )


class AssignmentDocumentRecord(Base):
    __tablename__ = "backoffice__assignment_document"
    __metatable_identifier__ = "backoffice.assignment_document"
    __metatable_description__ = "One document selected for one person's requirement assignment. Composite references enforce that both belong to the same person."
    __metatable_labels__ = ("backoffice", "requirements", "document")
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_uid", "person_uid"],
            ["backoffice__person_document_set.uid", "backoffice__person_document_set.person_uid"],
        ),
        ForeignKeyConstraint(
            ["document_uid", "person_uid"],
            ["backoffice__document.uid", "backoffice__document.person_uid"],
        ),
    )

    assignment_uid: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        info=info("Assignment UID", "Requirement assignment to which the document is attached."),
    )
    document_uid: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        info=info(
            "Document UID", "Logical document selected as evidence; one membership per assignment."
        ),
    )
    person_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Person UID", "Common owner of the assignment and the selected document.")
    )

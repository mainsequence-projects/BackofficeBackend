"""Raw source manifests, bounded content chunks, and extraction provenance."""

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

# Conservative initial ceiling; upload support must benchmark the selected runtime.
MAX_CHUNK_BYTES = 262_144
MAX_CHUNK_BASE64_LENGTH = 4 * ((MAX_CHUNK_BYTES + 2) // 3)


class RawDocumentRecord(Identified, Created, Base):
    __tablename__ = "backoffice__raw_document"
    __metatable_identifier__ = "backoffice.raw_document"
    __metatable_description__ = "One source-file upload manifest owned by a business person. Finalization verifies ordered chunks, total bytes and checksum before the source becomes ready and immutable."
    __metatable_labels__ = ("backoffice", "source", "upload")
    __table_args__ = (
        UniqueConstraint("uid", "person_uid"),
        UniqueConstraint("operation_key"),
        CheckConstraint("byte_count > 0", name="positive_size"),
        CheckConstraint("chunk_count > 0", name="positive_chunks"),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
        CheckConstraint("status IN ('uploading', 'ready', 'failed')", name="allowed_status"),
        CheckConstraint("status != 'ready' OR finalized_at IS NOT NULL", name="finalization_time"),
    )

    person_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__person.uid"),
        index=True,
        info=info("Person UID", "Business person authorized to use this raw source as evidence."),
    )
    operation_key: Mapped[UUID] = mapped_column(
        Uuid,
        info=info("Operation key", "Upload idempotency UUID reused when resuming the same upload."),
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        info=info("Filename", "Original display filename; never used as a filesystem path."),
    )
    media_type: Mapped[str] = mapped_column(
        String(120),
        info=info("Media type", "Validated source media type, for example application/pdf."),
    )
    byte_count: Mapped[int] = mapped_column(
        Integer, info=info("Byte count", "Expected decoded file size verified during finalization.")
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        info=info("File checksum", "Lowercase hexadecimal SHA-256 of the complete decoded source."),
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer,
        info=info("Chunk count", "Expected number of consecutive chunks starting at index zero."),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Upload status",
            "Uploading, ready, or failed; only ready sources may support submitted revisions.",
        ),
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        info=info("Finalized at", "UTC instant at which all source-integrity checks succeeded."),
    )


class RawDocumentChunkRecord(Base):
    __tablename__ = "backoffice__raw_document_chunk"
    __metatable_identifier__ = "backoffice.raw_document_chunk"
    __metatable_description__ = "One bounded base64 content chunk at a zero-based position in a raw source upload. The source and index uniquely identify resumable chunk writes."
    __metatable_labels__ = ("backoffice", "source", "content")
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="nonnegative_index"),
        CheckConstraint(
            f"byte_count > 0 AND byte_count <= {MAX_CHUNK_BYTES}", name="bounded_bytes"
        ),
        CheckConstraint(
            f"length(content_base64) <= {MAX_CHUNK_BASE64_LENGTH}", name="bounded_content"
        ),
        CheckConstraint("length(content_sha256) = 64", name="sha256_length"),
    )

    raw_document_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__raw_document.uid"),
        primary_key=True,
        info=info("Source UID", "Raw source whose ordered content includes this chunk."),
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        info=info("Chunk index", "Zero-based consecutive position in the decoded file."),
    )
    content_base64: Mapped[str] = mapped_column(
        Text,
        info=info(
            "Encoded content",
            "Base64-encoded source bytes, validated and decoded by the upload service.",
        ),
    )
    byte_count: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Byte count", "Decoded chunk length, at most 262144 bytes in this schema version."
        ),
    )
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        info=info("Chunk checksum", "Lowercase hexadecimal SHA-256 of this chunk's decoded bytes."),
    )


class FieldEvidenceRecord(Identified, Created, Base):
    __tablename__ = "backoffice__field_evidence"
    __metatable_identifier__ = "backoffice.field_evidence"
    __metatable_description__ = "One extraction or reviewer evidence location for one document-revision field, with source page, optional excerpt and extraction provenance."
    __metatable_labels__ = ("backoffice", "evidence", "provenance")
    __table_args__ = (
        ForeignKeyConstraint(
            ["revision_uid", "person_uid"],
            ["backoffice__document_revision.uid", "backoffice__document_revision.person_uid"],
        ),
        ForeignKeyConstraint(
            ["raw_document_uid", "person_uid"],
            ["backoffice__raw_document.uid", "backoffice__raw_document.person_uid"],
        ),
        CheckConstraint("page_number >= 1", name="positive_page"),
    )

    revision_uid: Mapped[UUID] = mapped_column(
        Uuid,
        index=True,
        info=info("Revision UID", "Exact document attribute revision supported by this evidence."),
    )
    person_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Person UID", "Common owner of the revision and raw source.")
    )
    field_path: Mapped[str] = mapped_column(
        String(240),
        info=info(
            "Field path",
            "Validated document field path, including an index when identifying an array element.",
        ),
    )
    raw_document_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Source UID", "Immutable raw source containing the evidence.")
    )
    page_number: Mapped[int] = mapped_column(
        Integer, info=info("Page number", "One-based page number within the source.")
    )
    bounding_box: Mapped[list | None] = mapped_column(
        JSON,
        info=info(
            "Bounding box",
            "Optional normalized left, top, right and bottom page coordinates validated by EvidenceRegion.",
        ),
    )
    excerpt: Mapped[str | None] = mapped_column(
        Text,
        info=info(
            "Source excerpt",
            "Literal source text supporting the field; absent when only a visual region is available.",
        ),
    )
    provenance: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Provenance",
            "Extractor version and available processing, inference, or reviewer identifiers; source text is evidence, never instructions.",
        ),
    )

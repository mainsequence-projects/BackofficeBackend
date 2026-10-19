"""Versioned parsing policy and immutable, revision-specific parsing decisions."""

from uuid import UUID

from metatables import schema_table_name
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Created, Identified, info


class ParsingPolicyRecord(Identified, Created, Base):
    __tablename__ = schema_table_name("backoffice", "parsing_policy")
    __metatable_identifier__ = "backoffice.parsing_policy"
    __metatable_description__ = "One immutable classification confidence policy revision per document type. Organization administrators configure percentage thresholds for automatic acceptance of complete documents; prior policies remain available for decision provenance."
    __metatable_labels__ = ("document-processing", "configuration", "history")
    __table_args__ = (
        UniqueConstraint("settings_key", "revision"),
        UniqueConstraint("document_type", "revision"),
        UniqueConstraint("operation_key"),
        CheckConstraint("revision >= 1", name="positive_revision"),
        CheckConstraint(
            "threshold_basis_points IS NULL OR threshold_basis_points BETWEEN 0 AND 10000",
            name="threshold_range",
        ),
        CheckConstraint(
            "NOT automatic_acceptance_enabled OR threshold_basis_points IS NOT NULL",
            name="enabled_requires_threshold",
        ),
    )
    document_type: Mapped[str | None] = mapped_column(
        String(80),
        info=info(
            "Document type",
            "Canonical document discriminator; null identifies legacy global policies retained only for historical provenance.",
        ),
    )
    settings_key: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Settings key",
            "Stable policy scope, document_parsing followed by a colon and canonical type; the legacy document_parsing key is historical only.",
        ),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Policy revision",
            "Increasing policy revision within one document type; each saved version is immutable.",
        ),
    )
    automatic_acceptance_enabled: Mapped[bool] = mapped_column(
        Boolean,
        info=info(
            "Automatic acceptance",
            "Whether qualifying complete document revisions may be accepted automatically.",
        ),
    )
    threshold_basis_points: Mapped[int | None] = mapped_column(
        Integer,
        info=info(
            "Acceptance threshold",
            "Minimum classification confidence in basis points from 0 to 10000; 9500 means 95 percent, and null means unconfigured.",
        ),
    )
    changed_by: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Changed by",
            "Verified Main Sequence organization administrator User UID that saved this policy revision.",
        ),
    )
    operation_key: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Operation key",
            "Stable request UUID retained to resume the same settings change without creating another revision.",
        ),
    )


class ParsingResultRecord(Identified, Created, Base):
    __tablename__ = schema_table_name("backoffice", "parsing_result")
    __metatable_identifier__ = "backoffice.parsing_result"
    __metatable_description__ = "One immutable classification confidence decision for an exact document revision, reported by an authorized processor. It retains the applied policy and any automatic acceptance decision so score-based approvals can be audited after settings change."
    __metatable_labels__ = ("document-processing", "confidence", "history")
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_uid", "revision"],
            [
                "backoffice__document_revision.document_uid",
                "backoffice__document_revision.revision",
            ],
        ),
        UniqueConstraint("document_uid", "revision"),
        UniqueConstraint("operation_key"),
        CheckConstraint(
            "score_basis_points IS NULL OR score_basis_points BETWEEN 0 AND 10000",
            name="score_range",
        ),
        CheckConstraint("decision IN ('accepted', 'needs_review')", name="allowed_decision"),
        CheckConstraint(
            "(decision = 'accepted' AND review_uid IS NOT NULL) OR (decision = 'needs_review' AND review_uid IS NULL)",
            name="acceptance_reference",
        ),
    )
    document_uid: Mapped[UUID] = mapped_column(
        Uuid,
        info=info("Document UID", "Logical document whose exact parsed revision was evaluated."),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Document revision",
            "Exact document attribute revision to which the parsing score applies.",
        ),
    )
    score_basis_points: Mapped[int | None] = mapped_column(
        Integer,
        info=info(
            "Parsing score",
            "Classification confidence in basis points from 0 to 10000; null means the processor supplied no score and review is required.",
        ),
    )
    policy_uid: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("backoffice__parsing_policy.uid"),
        info=info(
            "Policy UID",
            "Immutable settings revision applied at completion; null means the unconfigured, review-only default.",
        ),
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Parsing decision",
            "Accepted when all automatic approval checks pass, otherwise needs_review.",
        ),
    )
    reason_code: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Decision reason",
            "Stable explanation of the confidence threshold, disabled policy, missing score, invalid attributes, or missing source decision.",
        ),
    )
    review_uid: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("backoffice__document_review.uid"),
        info=info(
            "Automatic review UID",
            "Exact acceptance decision created by this parsing result; null when human review is needed.",
        ),
    )
    extractor: Mapped[str] = mapped_column(
        String(120),
        info=info(
            "Extractor version",
            "Processor-reported extractor identifier and version, retained as provenance rather than executable instructions.",
        ),
    )
    processed_by: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Processed by",
            "Verified processor or organization administrator User UID that recorded this result.",
        ),
    )
    operation_key: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Operation key",
            "Stable completion request UUID that prevents duplicated parsing or acceptance decisions after retries.",
        ),
    )

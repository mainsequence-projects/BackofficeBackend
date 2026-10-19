"""Reproducible evaluation snapshots, processing intents, and business audit."""

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


class ReconciliationEvaluationRecord(Identified, Created, Base):
    __tablename__ = "backoffice__reconciliation_evaluation"
    __metatable_identifier__ = "backoffice.reconciliation_evaluation"
    __metatable_description__ = "One evaluation of an assignment against frozen person, policy and document inputs. A completed evaluation remains reproducible after later edits or reviews."
    __metatable_labels__ = ("backoffice", "reconciliation", "history")
    __table_args__ = (
        ForeignKeyConstraint(
            ["assignment_uid", "person_uid"],
            ["backoffice__person_document_set.uid", "backoffice__person_document_set.person_uid"],
        ),
        ForeignKeyConstraint(
            ["person_uid", "person_revision"],
            ["backoffice__person_revision.person_uid", "backoffice__person_revision.revision"],
        ),
        ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
        ),
        UniqueConstraint("operation_key"),
        CheckConstraint("assignment_revision >= 1", name="positive_revision"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')", name="allowed_status"
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'failed') OR completed_at IS NOT NULL",
            name="completion_time",
        ),
    )

    assignment_uid: Mapped[UUID] = mapped_column(
        Uuid,
        index=True,
        info=info("Assignment UID", "Person requirement assignment evaluated by this run."),
    )
    person_uid: Mapped[UUID] = mapped_column(
        Uuid, info=info("Person UID", "Business person whose document coverage was evaluated.")
    )
    person_revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Person revision", "Exact historical reference-profile revision used for comparisons."
        ),
    )
    assignment_revision: Mapped[int] = mapped_column(
        Integer,
        info=info("Assignment revision", "Assignment revision captured when evaluation started."),
    )
    set_key: Mapped[str] = mapped_column(
        String(120),
        info=info("Set key", "Requirement-policy identifier selected in the frozen input."),
    )
    set_version: Mapped[int] = mapped_column(
        Integer, info=info("Set version", "Exact immutable requirement-policy version evaluated.")
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Input snapshot",
            "Immutable assignment membership, document revision and effective review identifiers, evaluation date, and evaluator version.",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        info=info(
            "Evaluation status",
            "Pending, running, completed, or failed; a partial evaluation never means requirements are satisfied.",
        ),
    )
    summary: Mapped[dict | None] = mapped_column(
        JSON,
        info=info(
            "Result summary",
            "Typed completion result and requirement counts, present only when available.",
        ),
    )
    operation_key: Mapped[UUID] = mapped_column(
        Uuid, info=info("Operation key", "Stable idempotency UUID for this evaluation request.")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        info=info("Completed at", "UTC instant when evaluation finished or failed."),
    )


class ReconciliationFindingRecord(Identified, Base):
    __tablename__ = "backoffice__reconciliation_finding"
    __metatable_identifier__ = "backoffice.reconciliation_finding"
    __metatable_description__ = "One explained requirement result within an evaluation, with stable reason code and exact field, revision and evidence references."
    __metatable_labels__ = ("backoffice", "reconciliation", "finding")
    __table_args__ = (
        CheckConstraint(
            "status IN ('satisfied', 'missing', 'failed', 'pending_review', 'needs_information', 'not_applicable')",
            name="allowed_status",
        ),
    )

    evaluation_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__reconciliation_evaluation.uid"),
        index=True,
        info=info("Evaluation UID", "Evaluation that produced this finding."),
    )
    requirement_key: Mapped[str] = mapped_column(
        String(120),
        info=info(
            "Requirement key", "Requirement within the pinned policy to which the finding applies."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(24),
        info=info(
            "Finding status",
            "Satisfied, missing, failed, pending_review, needs_information, or not_applicable.",
        ),
    )
    reason_code: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Reason code",
            "Stable machine-readable explanation, for example REQUIRED_FIELD_MISSING.",
        ),
    )
    explanation: Mapped[str] = mapped_column(
        Text,
        info=info("Explanation", "English explanation grounded in the frozen inputs and evidence."),
    )
    field_paths: Mapped[list] = mapped_column(
        JSON,
        info=info("Field paths", "Document or reference-profile paths involved in the finding."),
    )
    document_references: Mapped[list] = mapped_column(
        JSON,
        info=info(
            "Document references",
            "Exact document, revision and evidence UIDs supporting the finding.",
        ),
    )


class ProcessingRunRecord(Identified, Created, Base):
    __tablename__ = "backoffice__processing_run"
    __metatable_identifier__ = "backoffice.processing_run"
    __metatable_description__ = "One durable processing intent recorded before scheduling Main Sequence work, with retry identity, execution references and recoverable completion state."
    __metatable_labels__ = ("backoffice", "processing", "job")
    __table_args__ = (
        UniqueConstraint("operation_key"),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempts"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="allowed_status",
        ),
    )

    operation_key: Mapped[UUID] = mapped_column(
        Uuid,
        info=info("Operation key", "Stable idempotency UUID reused across scheduling retries."),
    )
    kind: Mapped[str] = mapped_column(
        String(80),
        info=info(
            "Processing kind",
            "Application operation such as extract_document or evaluate_assignment.",
        ),
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Input snapshot",
            "Immutable validated source and revision references plus operation parameters.",
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        info=info("Processing status", "Pending, running, completed, failed, or cancelled."),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, info=info("Attempt count", "Number of execution attempts started for this intent.")
    )
    job_run_uid: Mapped[UUID | None] = mapped_column(
        Uuid,
        info=info(
            "Job run UID", "Main Sequence JobRun UID when a background job has been scheduled."
        ),
    )
    agent_session_uid: Mapped[UUID | None] = mapped_column(
        Uuid,
        info=info(
            "Agent session UID",
            "Main Sequence Tau session UID when agent work is associated with the intent.",
        ),
    )
    inference_request_uid: Mapped[UUID | None] = mapped_column(
        Uuid,
        info=info(
            "Inference request UID", "Recorded Main Sequence inference request UID when applicable."
        ),
    )
    result: Mapped[dict | None] = mapped_column(
        JSON,
        info=info(
            "Result",
            "Validated result references or a structured failure, without raw provider credentials.",
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Updated at", "UTC instant of the latest processing-state change."),
    )


class AuditEventRecord(Identified, Base):
    __tablename__ = "backoffice__audit_event"
    __metatable_identifier__ = "backoffice.audit_event"
    __metatable_description__ = "One append-only business audit event with trusted actor, affected resource and revision, correlation identity and bounded event details."
    __metatable_labels__ = ("backoffice", "audit", "history")

    actor_uid: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Actor UID", "Verified Main Sequence human or workload User responsible for the action."
        ),
    )
    action: Mapped[str] = mapped_column(
        String(120),
        info=info("Action", "Stable application action name, for example document.reviewed."),
    )
    resource_type: Mapped[str] = mapped_column(
        String(80), info=info("Resource type", "Business resource kind affected by the action.")
    )
    resource_uid: Mapped[UUID] = mapped_column(
        Uuid, index=True, info=info("Resource UID", "Stable UID of the affected business resource.")
    )
    revision: Mapped[int | None] = mapped_column(
        Integer,
        info=info("Revision", "Affected revision when the action targets a versioned resource."),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Occurred at", "UTC instant when the trusted service recorded the action."),
    )
    correlation_uid: Mapped[UUID] = mapped_column(
        Uuid,
        index=True,
        info=info(
            "Correlation UID", "Request or workflow UUID used to trace related business actions."
        ),
    )
    details: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Event details",
            "Bounded structured action metadata; prefer record references over copies of sensitive document content.",
        ),
    )

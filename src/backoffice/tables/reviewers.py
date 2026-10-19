"""Staff responsibility for a case, separate from the business subject and evidence."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, info


class CaseReviewerRecord(Base):
    __tablename__ = "backoffice__case_reviewer"
    __metatable_identifier__ = "backoffice.case_reviewer"
    __metatable_description__ = "One staff user's responsibility for a document case. Authorized reviewers take or leave assignments independently; inactive memberships preserve the latest state without changing customer evidence or approval permissions."
    __metatable_labels__ = ("casework", "reviewers", "responsibility")
    __table_args__ = (CheckConstraint("revision >= 1", name="positive_revision"),)

    assignment_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__person_document_set.uid"),
        primary_key=True,
        info=info(
            "Case UID", "Requirement assignment whose document case the staff member reviews."
        ),
    )
    reviewer_uid: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        info=info(
            "Reviewer UID", "Main Sequence staff User UID, never the business subject's Person UID."
        ),
    )
    display_name: Mapped[str | None] = mapped_column(
        String(240),
        info=info(
            "Reviewer name",
            "Verified staff display name recorded on the latest change; null when unavailable.",
        ),
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        index=True,
        info=info(
            "Assigned", "True while this staff user has accepted responsibility for the case."
        ),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Membership revision",
            "Positive revision used to reject stale changes to this staff membership.",
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info(
            "Updated at", "UTC instant when the staff user last took or left responsibility."
        ),
    )

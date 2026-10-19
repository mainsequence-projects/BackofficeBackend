"""Person reference profiles and their immutable history."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, Created, Identified, info


class PersonRecord(Identified, Created, Base):
    __tablename__ = "backoffice__person"
    __metatable_identifier__ = "backoffice.person"
    __metatable_description__ = "One business person with the current reference profile used to compare submitted document attributes. Historical profiles remain available for reproducible evaluations."
    __metatable_labels__ = ("backoffice", "person", "reference")
    __table_args__ = (CheckConstraint("current_revision >= 1", name="positive_revision"),)

    current_revision: Mapped[int] = mapped_column(
        Integer,
        info=info(
            "Current revision",
            "Positive reference-profile revision; the service advances this after recording its historical snapshot.",
        ),
    )
    profile: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Reference profile",
            "Serialized Person contract containing the current verified reference attributes.",
        ),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Updated at", "UTC instant of the latest reference-profile change."),
    )


class PersonRevisionRecord(Identified, Base):
    __tablename__ = "backoffice__person_revision"
    __metatable_identifier__ = "backoffice.person_revision"
    __metatable_description__ = "One immutable reference-profile revision for one business person, including the trusted actor and recording time."
    __metatable_labels__ = ("backoffice", "person", "history")
    __table_args__ = (
        UniqueConstraint("person_uid", "revision"),
        CheckConstraint("revision >= 1", name="positive_revision"),
    )

    person_uid: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("backoffice__person.uid"),
        info=info("Person UID", "Business person whose reference profile was recorded."),
    )
    revision: Mapped[int] = mapped_column(
        Integer,
        info=info("Revision", "Positive, monotonically increasing revision for this person."),
    )
    profile: Mapped[dict] = mapped_column(
        JSON,
        info=info(
            "Reference profile", "Immutable serialized Person contract captured at this revision."
        ),
    )
    recorded_by: Mapped[UUID] = mapped_column(
        Uuid,
        info=info(
            "Recorded by", "Trusted Main Sequence User UID that performed the profile change."
        ),
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Recorded at", "UTC instant when the revision was recorded."),
    )

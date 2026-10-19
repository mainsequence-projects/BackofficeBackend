"""Main Sequence table authoring metadata; this module never opens a database."""

from datetime import datetime
from uuid import UUID

from metatables import PlatformManagedMetaTable, sqlalchemy_naming_convention
from sqlalchemy import DateTime, MetaData, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def info(label: str, description: str) -> dict[str, str]:
    return {"label": label, "description": description}


class Base(PlatformManagedMetaTable, DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())
    __metatable_namespace__ = "backoffice"


class Identified:
    uid: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        info=info("UID", "Stable application-generated UUID identifying this record."),
    )


class Created:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        info=info("Created at", "UTC instant when the service first recorded this record."),
    )

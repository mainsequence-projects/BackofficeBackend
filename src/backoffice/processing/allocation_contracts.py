"""Commands for private intake and automatic allocation; caller identity is server-owned."""

from typing import Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from ..services.contracts import Command
from .contracts import MAX_BYTES


class IntakeUpload(Command):
    filename: str = Field(min_length=1, max_length=255)
    media_type: Literal["application/pdf", "image/png", "image/jpeg"]
    byte_count: StrictInt = Field(gt=0, le=MAX_BYTES)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class AllocateDocument(Command):
    intake_uid: UUID | None = None
    source_uid: UUID | None = None

    @model_validator(mode="after")
    def one_input(self):
        if (self.intake_uid is None) == (self.source_uid is None):
            raise ValueError("Provide exactly one intake_uid or source_uid")
        return self


class ResolveAllocation(Command):
    subject_uid: UUID
    expected_revision: StrictInt = Field(ge=1)


class BindIntake(Command):
    subject_uid: UUID
    content_sha256: str

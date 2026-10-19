"""Reference profile used for reconciliation; document claims never overwrite it implicitly."""

from datetime import date
from uuid import UUID

from pydantic import Field

from .common import ContractModel, NonEmptyStr, PostalAddress


class Person(ContractModel):
    uid: UUID = Field(
        title="Person UID",
        description="Stable business-person UID; this is not a Main Sequence authentication identity.",
    )
    revision: int = Field(
        default=1,
        ge=1,
        title="Profile revision",
        description="Positive revision of the person's reference profile.",
    )
    external_reference: NonEmptyStr | None = Field(
        default=None,
        title="External reference",
        description="Optional customer identifier in the originating business system.",
    )
    full_name: NonEmptyStr | None = Field(
        default=None,
        title="Full name",
        description="Verified reference name; null while the person's profile is incomplete.",
    )
    given_names: NonEmptyStr | None = Field(
        default=None,
        title="Given names",
        description="Reference given names when separately known; null otherwise.",
    )
    last_name: NonEmptyStr | None = Field(
        default=None,
        title="Last name",
        description="Reference surname or family name when applicable; null otherwise.",
    )
    date_of_birth: date | None = Field(
        default=None,
        title="Date of birth",
        description="Verified reference date of birth; null when unknown.",
    )
    nationalities: list[NonEmptyStr] | None = Field(
        default=None,
        title="Nationalities",
        description="Declared or verified nationalities; null when not yet recorded.",
    )
    residential_address: PostalAddress | None = Field(
        default=None,
        title="Residential address",
        description="Reference residential address used for comparison; null when unknown.",
    )
    employment_status: NonEmptyStr | None = Field(
        default=None,
        title="Employment status",
        description="Reference employment category, such as employed or self_employed; null when unknown.",
    )
    residency_permit_required: bool | None = Field(
        default=None,
        title="Residence permit required",
        description="Case-specific determination of whether residence-permit evidence is required; null until determined.",
    )

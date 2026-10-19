"""Versioned requirement definitions with alternatives and explicit conditionality."""

from typing import Literal, Self

from pydantic import Field, StrictBool, StrictStr, model_validator

from ..schemas.registry import DocumentType, get_document_model, resolve_field_schema
from .common import ContractModel, NonEmptyStr


class RequirementCondition(ContractModel):
    field: Literal["employment_status", "residency_permit_required"] = Field(
        title="Reference field",
        description="Person reference field evaluated for applicability; a missing value leaves applicability unknown.",
    )
    equals: StrictStr | StrictBool = Field(
        title="Expected value",
        description="Exact reference value that makes the requirement applicable.",
    )

    @model_validator(mode="after")
    def compatible_condition(self) -> Self:
        expected = bool if self.field == "residency_permit_required" else str
        if type(self.equals) is not expected:
            raise ValueError(f"equals must be {expected.__name__} for {self.field}")
        return self


class DocumentOption(ContractModel):
    document_type: DocumentType = Field(
        title="Document type",
        description="One supported type of evidence that may satisfy the requirement.",
    )
    schema_version: int = Field(
        default=1,
        ge=1,
        title="Schema version",
        description="Exact document schema version accepted by this option.",
    )
    required_fields: list[NonEmptyStr] = Field(
        default_factory=list,
        title="Additional required fields",
        description="Additional non-null field paths required by this workflow, for example mrz_lines or holder_address.city.",
    )
    require_unexpired: bool = Field(
        default=False,
        title="Require current validity",
        description="Whether the evaluator must establish document validity on the evaluation date.",
    )
    max_age_days: int | None = Field(
        default=None,
        ge=0,
        title="Maximum age",
        description="Maximum age in whole calendar days from the freshness field; null means no age limit.",
    )
    freshness_field: NonEmptyStr | None = Field(
        default=None,
        title="Freshness date field",
        description="Document date or timezone-aware datetime path used to measure age, such as issue_date or completed_at; datetime values use their UTC calendar date.",
    )
    max_age_months: int | None = Field(
        default=None,
        ge=1,
        le=1200,
        title="Maximum age in calendar months",
        description="Maximum evidence age in calendar months from the freshness field; month ends clamp to the last day. Mutually exclusive with max_age_days.",
    )
    renewal_interval_months: int | None = Field(
        default=None,
        ge=1,
        le=1200,
        title="Renewal interval in calendar months",
        description="Recurring renewal interval; evidence stops qualifying on the anniversary of the selected renewal basis. Null disables periodic renewal.",
    )
    renewal_basis: Literal["reviewed_at", "submitted_at"] = Field(
        default="reviewed_at",
        title="Renewal measured from",
        description="Use reviewed_at for a repeat review of the accepted revision, or submitted_at for a new submitted revision. Upload time never resets evidence age.",
    )

    @model_validator(mode="after")
    def valid_schema_references(self) -> Self:
        model = get_document_model(self.document_type, self.schema_version)
        if self.require_unexpired and "expiration_date" not in model.model_fields:
            raise ValueError("require_unexpired needs a document with an expiration_date field")
        if len(self.required_fields) != len(set(self.required_fields)):
            raise ValueError("required_fields must be unique")
        for path in self.required_fields:
            resolve_field_schema(model, path)
        if self.max_age_days is not None and self.max_age_months is not None:
            raise ValueError("Choose max_age_days or max_age_months, not both")
        has_age = self.max_age_days is not None or self.max_age_months is not None
        if has_age != (self.freshness_field is not None):
            raise ValueError("A maximum age and freshness_field must be supplied together")
        if self.renewal_basis != "reviewed_at" and self.renewal_interval_months is None:
            raise ValueError("renewal_basis requires renewal_interval_months")
        if self.freshness_field:
            field = resolve_field_schema(model, self.freshness_field)
            choices = field.get("anyOf", [field])
            if not any(item.get("format") in ("date", "date-time") for item in choices):
                raise ValueError("freshness_field must identify a date or datetime")
        return self


class DocumentRequirement(ContractModel):
    key: NonEmptyStr = Field(
        title="Requirement key",
        description="Stable requirement identifier within the document-set version.",
    )
    description: NonEmptyStr = Field(
        title="Requirement description",
        description="English explanation of the evidence needed and why it is required.",
    )
    options: list[DocumentOption] = Field(
        min_length=1,
        title="Accepted alternatives",
        description="Evidence alternatives; qualifying documents from these alternatives satisfy this requirement.",
    )
    mandatory: bool = Field(
        default=True,
        title="Mandatory",
        description="Whether this requirement must be satisfied when applicable.",
    )
    min_count: int = Field(
        default=1,
        ge=1,
        title="Minimum document count",
        description="Minimum number of distinct qualifying documents; duplicate uploads never increase the count.",
    )
    distinct_period_field: NonEmptyStr | None = Field(
        default=None,
        title="Distinct reporting period",
        description="Period field used to require distinct reporting periods; null means no period grouping.",
    )
    condition: RequirementCondition | None = Field(
        default=None,
        title="Applicability condition",
        description="Condition on the person profile; null means the requirement always applies.",
    )

    @model_validator(mode="after")
    def unique_options_and_periods(self) -> Self:
        keys = [(option.document_type, option.schema_version) for option in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError("document options must be unique")
        if self.distinct_period_field:
            for option in self.options:
                model = get_document_model(option.document_type, option.schema_version)
                resolve_field_schema(model, f"{self.distinct_period_field}.start_date")
                resolve_field_schema(model, f"{self.distinct_period_field}.end_date")
        return self


class DocumentSet(ContractModel):
    key: NonEmptyStr = Field(
        title="Set key",
        description="Stable reusable document-set identifier, such as new_account_requirements.",
    )
    version: int = Field(
        ge=1,
        title="Set version",
        description="Published immutable version pinned by a person's assignment.",
    )
    name: NonEmptyStr = Field(
        title="Name", description="Readable English name for this document set."
    )
    description: NonEmptyStr = Field(
        title="Description",
        description="Business purpose and coverage of this version's requirements.",
    )
    allow_document_reuse: bool = Field(
        default=True,
        title="Allow document reuse",
        description="Whether the same qualifying document may satisfy more than one requirement; duplicates within a requirement never increase its count.",
    )
    requirements: list[DocumentRequirement] = Field(
        min_length=1,
        title="Requirements",
        description="Named requirements that are evaluated independently for each assigned person.",
    )

    @model_validator(mode="after")
    def unique_requirement_keys(self) -> Self:
        keys = [requirement.key for requirement in self.requirements]
        if len(keys) != len(set(keys)):
            raise ValueError("requirement keys must be unique")
        return self

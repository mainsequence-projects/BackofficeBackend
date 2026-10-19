"""Versioned cross-document business policy, owned exclusively by Back Office."""

from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, model_validator

from ..schemas.registry import DocumentType, get_document_model, resolve_field_schema
from .common import ContractModel


class ComparisonSelector(ContractModel):
    document_type: DocumentType = Field(
        description="Document type selected from this assignment only."
    )
    schema_version: int = Field(default=1, ge=1, description="Exact canonical schema version.")
    field: str = Field(
        min_length=1,
        max_length=240,
        description="Canonical object field path to compare, such as net_pay.amount.",
    )
    unit_field: str | None = Field(
        default=None,
        description="Field identifying the currency or unit; both sides must agree exactly.",
    )
    context_fields: list[str] = Field(
        default_factory=list,
        max_length=8,
        description="Additional cited fields needed to interpret period, basis or entity; missing context leaves comparison unresolved.",
    )

    @model_validator(mode="after")
    def valid_fields(self) -> Self:
        model = get_document_model(self.document_type, self.schema_version)
        for path in [
            self.field,
            *self.context_fields,
            *([self.unit_field] if self.unit_field else []),
        ]:
            resolve_field_schema(model, path)
        if len(set(self.context_fields)) != len(self.context_fields):
            raise ValueError("duplicate comparison context field")
        return self


class ComparisonRule(ContractModel):
    key: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Stable comparison rule key, unique alongside requirement keys.",
    )
    description: str = Field(
        min_length=1,
        max_length=1000,
        description="Business explanation retained in the finding; never sent to the parser.",
    )
    topic: str = Field(
        min_length=1,
        max_length=500,
        description="Factual concept the parser should compare, without rules or thresholds.",
    )
    left: ComparisonSelector = Field(
        description="Left document/field selector; the numeric relative tolerance uses this value as its baseline."
    )
    right: ComparisonSelector = Field(description="Right document/field selector.")
    operator: Literal["exact", "numeric", "semantic"] = Field(
        description="Back Office operator applied only after cited comparability has been established."
    )
    mandatory: bool = Field(
        default=True,
        description="Whether an applicable unresolved or failed comparison blocks requirement completion.",
    )
    when_both_present: bool = Field(
        default=False,
        description="When true, absent document types make this rule inapplicable; missing fields in present documents still block it.",
    )
    absolute_tolerance: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=24,
        decimal_places=8,
        description="Nonnegative allowed absolute difference, in the compared unit; numeric rules only.",
    )
    relative_tolerance_basis_points: int = Field(
        default=0,
        ge=0,
        le=10000,
        description="Allowed relative difference in basis points of the absolute left value; numeric rules only. Zero baseline uses absolute tolerance only.",
    )

    @model_validator(mode="after")
    def valid_operator(self) -> Self:
        if self.operator != "numeric" and (
            self.absolute_tolerance or self.relative_tolerance_basis_points
        ):
            raise ValueError("tolerances apply only to numeric comparisons")
        if bool(self.left.unit_field) != bool(self.right.unit_field):
            raise ValueError("unit fields must be specified on both sides")
        return self

"""Typed read responses shared by HTTP and MCP; no writes or model inference."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ..models.common import ContractModel
from ..models.document_set import DocumentOption


class Page[T](ContractModel):
    items: list[T] = Field(description="Items in this bounded page.")
    total_items: int = Field(
        description="Total records matching the same access and search filters."
    )
    limit: int = Field(description="Maximum records requested for this page.")
    offset: int = Field(description="Zero-based start of this page.")
    has_more: bool = Field(description="Whether more matching records follow this page.")


class CurrentUser(ContractModel):
    user_uid: UUID = Field(
        description="Verified effective caller; a delegated call reports its requester."
    )
    can_review: bool = Field(description="Whether the effective caller has reviewer permission.")


class AssignmentSummary(ContractModel):
    uid: UUID = Field(description="Stable assignment identifier.")
    person_uid: UUID = Field(description="Business person whose case owns this record.")
    set_key: str = Field(description="Stable key of the pinned requirement policy.")
    set_version: int = Field(
        description="Exact immutable policy version; never implicitly upgraded."
    )
    revision: int = Field(description="Current assignment revision.")
    created_at: datetime = Field(description="UTC creation timestamp.")
    updated_at: datetime = Field(description="UTC timestamp of the latest assignment change.")


class AssignmentDetail(AssignmentSummary):
    document_uids: list[UUID] = Field(
        description="Document identifiers explicitly selected for this assignment."
    )


class RequirementFinding(ContractModel):
    requirement_key: str = Field(description="Stable requirement key within the pinned policy.")
    status: Literal[
        "satisfied", "missing", "failed", "pending_review", "needs_information", "not_applicable"
    ] = Field(
        description="Deterministic state; pending review and missing evidence remain distinct."
    )
    reason_code: str = Field(description="Evaluator reason for the primary requirement finding.")
    explanation: str = Field(
        description="Policy description and explanation of the primary finding."
    )
    field_paths: list[str] = Field(
        description="Document or reference-profile paths implicated by the finding."
    )
    document_references: list[dict[str, Any]] = Field(
        description="Exact document/revision/review references and relevant policy dates."
    )
    mandatory: bool = Field(description="Whether this applicable requirement affects completion.")
    applicable: bool | None = Field(
        description="Resolved applicability; null means the profile lacks necessary information."
    )
    alternatives: list[DocumentOption] = Field(
        description="Accepted evidence choices and their field/date constraints."
    )
    required_count: int = Field(
        description="Minimum distinct qualifying documents required by the policy."
    )
    qualifying_count: int | None = Field(
        description="Distinct qualifying evidence count; null when applicability is unknown or false."
    )
    shortfall: int | None = Field(
        description="Additional qualifying evidence needed; null when applicability is unknown or false."
    )
    next_action: str = Field(
        description="Suggested action grounded in the primary evaluator reason."
    )


class AssignmentStatus(ContractModel):
    person_uid: UUID = Field(description="Business person whose case owns this record.")
    person_revision: int = Field(description="Reference-profile revision used in this assessment.")
    assignment_uid: UUID = Field(description="Assignment assessed by this response.")
    assignment_revision: int = Field(
        description="Selected-evidence assignment revision used in this assessment."
    )
    set_key: str = Field(description="Stable key of the pinned requirement policy.")
    set_version: int = Field(
        description="Exact immutable policy version; never implicitly upgraded."
    )
    evaluator_version: str = Field(description="Version of deterministic evaluation logic used.")
    assessed_at: datetime = Field(
        description="UTC timestamp when the input consistency check completed."
    )
    summary: dict[str, Any] = Field(
        description="Completion counts, evaluation date, policy notice and next action date."
    )
    findings: list[RequirementFinding] = Field(
        description="Requirement findings within the explicitly stated scope."
    )
    scope: str = Field(description="Only explicitly selected assignment documents are assessed.")
    diagnostics_complete: bool = Field(
        default=False, description="False: findings expose the primary blocker per requirement."
    )


class MissingRequirements(AssignmentStatus):
    total_requirements: int = Field(
        description="Total requirements in the pinned policy, including satisfied and optional ones."
    )
    outstanding_requirements: int = Field(
        description="Number of returned unresolved requirements, including optional ones."
    )

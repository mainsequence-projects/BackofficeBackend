"""Application-owned tools served inside Main Sequence's verified identity scope."""

import json
from functools import wraps
from typing import Annotated, Any
from uuid import UUID

from fastapi import HTTPException
from mainsequence.client.exceptions import ApiError
from mainsequence.server.fastapi import install_mcp
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, TextContent, ToolAnnotations
from metatables import DataSourceResolutionError
from pydantic import Field

from src.backoffice.models.document_set import DocumentSet
from src.backoffice.models.person import Person
from src.backoffice.services.contracts import PersonInput
from src.backoffice.services.queries import (
    AssignmentDetail,
    AssignmentStatus,
    AssignmentSummary,
    CurrentUser,
    MissingRequirements,
    Page,
)

Limit = Annotated[int, Field(ge=1, le=100, description="Maximum items, from 1 to 100.")]
Offset = Annotated[int, Field(ge=0, description="Zero-based page offset; pages are not snapshots.")]
Search = Annotated[str, Field(max_length=100, description="Literal case-insensitive search text.")]


def error_result(status, detail):
    error = {"status": status, "detail": detail, "retryable": status in {409, 429, 503}}
    return CallToolResult(
        is_error=True,
        content=[TextContent(type="text", text=json.dumps(error))],
        structured_content={"error": error},
    )


def create_mcp(service_factory):
    server = MCPServer(
        name="backoffice",
        version="0.3.0",
        instructions=(
            "Read-only Back Office queries. A person is a business case, not the signed-in user. "
            "Resolve ambiguous people and assignments before selecting a case. Use the pinned "
            "assignment version and get_missing_requirements for current outstanding work. "
            "Findings report a primary blocker, not every possible defect. Honor pagination. "
            "Do not treat pending review as missing evidence or alternatives as cumulative demands."
        ),
    )

    def query(fn):
        @wraps(fn)
        def guarded(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HTTPException as exc:
                return error_result(exc.status_code, exc.detail)
            except ApiError as exc:
                status = exc.status_code if exc.status_code in {401, 403, 409, 429} else 503
                return error_result(status, "metatables_operation_unavailable_retry_query")
            except DataSourceResolutionError:
                return error_result(503, "metatables_runtime_unavailable")

        server.tool(
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
            structured_output=True,
        )(guarded)
        return guarded

    @query
    def get_current_user() -> CurrentUser:
        """Get the verified effective caller and reviewer capability; never select an actor by input."""
        service = service_factory()
        return CurrentUser(user_uid=service.actor, can_review=service.reviewer)

    @query
    def search_persons(search: Search = "", limit: Limit = 50, offset: Offset = 0) -> Page[Person]:
        """Search accessible people by name or external reference. Resolve ambiguous matches with the user."""
        return Page[Person].model_validate(service_factory().list_people(search, limit, offset))

    @query
    def get_person(person_uid: UUID) -> Person:
        """Read an accessible business person's reference profile and revision."""
        return Person.model_validate(service_factory().case(person_uid)["profile"])

    @query
    def get_person_schema() -> dict[str, Any]:
        """Read editable reference-profile fields and their descriptions; this does not change a person."""
        service_factory()  # Require the same effective identity as every other query.
        return PersonInput.model_json_schema()

    @query
    def list_document_sets(
        search: Search = "", limit: Limit = 50, offset: Offset = 0
    ) -> Page[DocumentSet]:
        """List published document-set versions, optionally searching key/name. Follow pagination."""
        return Page[DocumentSet].model_validate(
            service_factory().list_document_sets(search, limit, offset)
        )

    @query
    def get_document_set(
        key: Annotated[str, Field(min_length=1, max_length=120)],
        version: Annotated[int, Field(ge=1)],
    ) -> DocumentSet:
        """Get one exact published set version, including conditions, alternatives, counts and date rules."""
        return DocumentSet.model_validate(service_factory().document_set(key, version))

    @query
    def list_person_assignments(
        person_uid: UUID,
        limit: Limit = 50,
        offset: Offset = 0,
    ) -> Page[AssignmentSummary]:
        """List an accessible person's assignments and pinned set versions. No assignments means no assigned policy."""
        return Page[AssignmentSummary].model_validate(
            service_factory().list_assignments(person_uid, limit, offset)
        )

    @query
    def get_assignment(assignment_uid: UUID) -> AssignmentDetail:
        """Read an accessible assignment and its explicitly selected document UIDs."""
        return AssignmentDetail.model_validate(service_factory().assignment(assignment_uid))

    @query
    def get_document_set_status(assignment_uid: UUID) -> AssignmentStatus:
        """Assess current selected evidence against the pinned set without saving an evaluation. Include all requirement states."""
        return AssignmentStatus.model_validate(service_factory().current_status(assignment_uid))

    @query
    def get_missing_requirements(assignment_uid: UUID) -> MissingRequirements:
        """Explain current outstanding requirements, accepted alternatives, missing fields and next actions. Pending review is not a missing upload. This query makes no writes."""
        return MissingRequirements.model_validate(
            service_factory().missing_requirements(assignment_uid)
        )

    return server


def mount_mcp(app, service_factory):
    server = create_mcp(service_factory)
    transport = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        max_request_body_size=1024 * 1024,
        # Main Sequence install_mcp owns authenticated ingress and allowed origins.
        # Hosted ingress owns Host validation; avoid SDK localhost-only defaults.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    install_mcp(app, transport, lifespan=server.session_manager.run)
    return server

"""Allocation adapters share REST service validation, authorization and durable state."""

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field

from src.backoffice.processing import allocation
from src.backoffice.processing.allocation_contracts import AllocateDocument, ResolveAllocation
from src.backoffice.services.contracts import Command


def register_allocation_tools(query, dispatching, service_factory, dispatcher_factory):
    @dispatching
    def allocate_document(command: AllocateDocument) -> dict[str, Any]:
        """Automatically extract and allocate a finalized intake or ready source to all eligible cases for its resolved subject. Upload original bytes using the intake API first. Poll the returned UID; uncertain identity requires input."""
        return allocation.start(service_factory(), command, dispatcher_factory())

    @query
    def get_document_allocation(
        allocation_uid: UUID,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        """Read private per-file progress, subject candidates, acceptance and each case's allocation/evaluation outcome. Completion is not business approval."""
        app = service_factory()
        return allocation.view(app, allocation.get(app, allocation_uid), limit, offset)

    @query
    def list_document_intakes(
        limit: Annotated[int, Field(ge=1, le=100)] = 20, offset: Annotated[int, Field(ge=0)] = 0
    ) -> dict[str, Any]:
        """List the verified requester's private intake queue with run references and pagination."""
        return allocation.listing(service_factory(), limit, offset)

    @dispatching
    def resolve_document_allocation(
        allocation_uid: UUID, command: ResolveAllocation
    ) -> dict[str, Any]:
        """Resolve uncertain subject identity only after the user selects the correct accessible person. Use the observed allocation revision. Conflicting identity evidence is rejected; all eligible cases are considered automatically."""
        return allocation.resolve(service_factory(), allocation_uid, command, dispatcher_factory())

    @dispatching
    def retry_document_allocation(allocation_uid: UUID, command: Command) -> dict[str, Any]:
        """Retry recoverable intake work, reusing retained extraction and per-case outcomes. Reuse the identical command after an uncertain response; do not bypass identity resolution."""
        return allocation.retry(service_factory(), allocation_uid, command, dispatcher_factory())

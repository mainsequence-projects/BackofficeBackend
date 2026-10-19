"""Application-owned tools served inside Main Sequence's verified identity scope."""

import json
from functools import wraps
from typing import Annotated, Any, Literal
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
from src.backoffice.processing import workflow
from src.backoffice.processing.adapters import MainSequenceDispatcher
from src.backoffice.services import cases, casework
from src.backoffice.services.contracts import (
    BuildCase,
    Command,
    CreatePerson,
    EvaluateCase,
    LinkCaseDocuments,
    PersonInput,
    SetMyCaseResponsibility,
)
from src.backoffice.services.extraction_evidence import evidence_view
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


def create_mcp(service_factory, dispatcher_factory=MainSequenceDispatcher):
    server = MCPServer(
        name="backoffice",
        version="0.4.0",
        instructions=(
            "A Person is a business subject with potentially multiple Cases. The verified requester "
            "and staff reviewers are separate identities. Resolve ambiguous subjects and cases. "
            "Use approved mutations only for the user's requested workflow. Use the pinned "
            "assignment version and get_missing_requirements for current outstanding work. "
            "Findings report a primary blocker, not every possible defect. Honor pagination. "
            "Do not treat pending review as missing evidence or alternatives as cumulative demands."
        ),
    )

    def register(fn, *, read_only=True, destructive=False, external=False, idempotent=True):
        @wraps(fn)
        def guarded(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except HTTPException as exc:
                return error_result(exc.status_code, exc.detail)
            except ApiError as exc:
                status = exc.status_code if exc.status_code in {401, 403, 409, 429} else 503
                return error_result(status, "metatables_operation_unavailable")
            except DataSourceResolutionError:
                return error_result(503, "metatables_runtime_unavailable")

        server.tool(
            annotations=ToolAnnotations(
                read_only_hint=read_only,
                destructive_hint=destructive,
                idempotent_hint=idempotent,
                open_world_hint=external,
            ),
            structured_output=True,
        )(guarded)
        return guarded

    def query(fn):
        return register(fn)

    def mutation(fn):
        return register(fn, read_only=False)

    def dispatching(fn):
        # Replaying the request may schedule another Job; worker claims fence execution.
        return register(fn, read_only=False, external=True, idempotent=False)

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

    @query
    def list_case_types() -> dict[str, Any]:
        """List case types and their permitted published policy keys/versions. Never infer a policy binding."""
        return cases.types(service_factory())

    @query
    def list_cases(
        search: Search = "",
        responsibility: Literal["all", "mine", "unassigned"] = "all",
        set_key: Annotated[str, Field(max_length=120)] = "",
        case_type_key: Annotated[str, Field(max_length=80)] = "",
        limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 10,
        offset: Offset = 0,
    ) -> dict[str, Any]:
        """List accessible cases with current lanes and filters. Reviewer membership never grants access."""
        return casework.queue(
            service_factory(), search, responsibility, set_key, limit, offset, case_type_key
        )

    @query
    def list_person_cases(
        person_uid: UUID, limit: Limit = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """List a subject's cases and pinned policies; distinguish multiple cases before acting."""
        return cases.list_for_subject(service_factory(), person_uid, limit, offset)

    @query
    def get_case(case_uid: UUID) -> dict[str, Any]:
        """Read canonical case identity, subject, type, revision, pinned policy and linked document UIDs."""
        return cases.detail(service_factory(), case_uid)

    @query
    def get_case_workspace(case_uid: UUID) -> dict[str, Any]:
        """Read a coherent case workspace with evidence, reviewers, findings and retained evaluation."""
        return casework.workspace(service_factory(), case_uid)

    @query
    def get_case_reviewers(case_uid: UUID) -> dict[str, Any]:
        """Read responsibility and my_revision for self-membership updates, distinct from case revision."""
        return casework.reviewers(service_factory(), case_uid)

    @query
    def list_person_documents(
        person_uid: UUID, limit: Limit = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """List subject-owned documents before choosing evidence to link; documents are not automatically case members."""
        return service_factory().list_documents(person_uid, limit, offset)

    @query
    def list_person_sources(
        person_uid: UUID, limit: Limit = 50, offset: Offset = 0
    ) -> dict[str, Any]:
        """List persisted original source metadata. A chat attachment is not an uploaded source."""
        return service_factory().list_sources(person_uid, limit, offset)

    @query
    def get_document(
        document_uid: UUID, revision: Annotated[int, Field(strict=True, ge=1)] | None = None
    ) -> dict[str, Any]:
        """Read latest or exact document revision and backend acceptance state. Never overwrite automatic acceptance."""
        return service_factory().document(document_uid, revision_number=revision)

    @query
    def get_document_extraction_evidence(
        document_uid: UUID, revision: Annotated[int, Field(strict=True, ge=1)]
    ) -> dict[str, Any]:
        """Read retained extraction provenance and evidence for an exact document revision."""
        return evidence_view(service_factory(), document_uid, revision)

    @query
    def list_case_evaluations(
        case_uid: UUID, limit: Limit = 20, offset: Offset = 0
    ) -> dict[str, Any]:
        """List retained evaluations of this case; use get_evaluation to check findings and current staleness."""
        return service_factory().list_evaluations(case_uid, limit, offset)

    @query
    def get_evaluation(evaluation_uid: UUID) -> dict[str, Any]:
        """Read saved findings and staleness. Satisfied requirements do not approve or close a case."""
        return service_factory().evaluation(evaluation_uid)

    @query
    def get_processing_run(run_uid: UUID) -> dict[str, Any]:
        """Read extraction/comparison stage and bounded results. Pending or failed runs are not completed evidence."""
        return workflow.view(workflow.get_run(service_factory(), run_uid))

    @mutation
    def create_person(command: CreatePerson) -> dict[str, Any]:
        """Create a subject using user-supplied reference facts after resolving possible duplicates. Reuse the operation key only for the identical request."""
        return service_factory().create_person(command)

    @mutation
    def create_case(command: BuildCase) -> dict[str, Any]:
        """Create a case for an existing subject, explicit case type and permitted exact policy version. Does not approve the case."""
        return cases.create(service_factory(), command.subject_uid, command)

    @mutation
    def link_case_documents(command: LinkCaseDocuments) -> dict[str, Any]:
        """Append same-subject evidence using the full current membership plus new UIDs and the observed case revision. Removal is unsupported."""
        return service_factory().set_documents(command.case_uid, command)

    def set_my_case_membership(command: SetMyCaseResponsibility) -> dict[str, Any]:
        """Take/leave responsibility as the verified reviewer only. expected_revision is my_revision from get_case_reviewers; assigned is boolean. Does not grant access."""
        return casework.set_my_membership(service_factory(), command.case_uid, command)

    register(set_my_case_membership, read_only=False, destructive=True)

    @dispatching
    def evaluate_case(command: EvaluateCase) -> dict[str, Any]:
        """Save an evaluation or queue comparison work for the exact case revision. Poll processing_run_uid if returned, then read the evaluation; never equate completion with approval."""
        return service_factory().evaluate(
            command.case_uid, command, dispatcher=dispatcher_factory()
        )

    @dispatching
    def process_source_document(source_uid: UUID, command: Command) -> dict[str, Any]:
        """Queue extraction of an existing ready owned source uploaded through UI/API. Poll its run, inspect acceptance, then explicitly link resulting evidence to the case."""
        return workflow.start(service_factory(), source_uid, command, dispatcher_factory())

    @dispatching
    def retry_processing_run(run_uid: UUID, command: Command) -> dict[str, Any]:
        """Retry an authorized extraction/comparison run under backend recovery rules; never invent a replacement run or operation key after an uncertain response."""
        return workflow.retry(service_factory(), run_uid, command, dispatcher_factory())

    from api.app.mcp.allocation_tools import register_allocation_tools

    register_allocation_tools(query, dispatching, service_factory, dispatcher_factory)

    return server


def mount_mcp(app, service_factory, dispatcher_factory=MainSequenceDispatcher):
    server = create_mcp(service_factory, dispatcher_factory)
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

"""Authenticated Back Office REST API; all storage uses Main Sequence MetaTables."""

import hashlib
import logging
import os
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse, Response
from mainsequence.client import User
from mainsequence.client.exceptions import ApiError
from mainsequence.server.fastapi import install_request_identity
from metatables import DataSourceResolutionError
from pydantic import ValidationError
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from api.app.assistant import AssistantContext, resolve_assistant_context
from src.backoffice.models.document_set import DocumentSet
from src.backoffice.policies import document_set_catalog
from src.backoffice.processing import workflow as processing
from src.backoffice.processing.adapters import (
    MainSequenceBucket,
    MainSequenceDispatcher,
    ProcessingError,
)
from src.backoffice.processing.contracts import MAX_BYTES
from src.backoffice.schemas.drafts import get_draft_model
from src.backoffice.schemas.registry import DOCUMENT_MODELS, DocumentType, get_document_model
from src.backoffice.services.application import (
    AUDIT,
    DR,
    EV,
    RAW,
    RV,
    SCHEMA,
    SETS,
    Application,
    D,
    P,
)
from src.backoffice.services.contracts import (
    AssignmentDocuments,
    AssignSet,
    Command,
    CompleteParsing,
    CreateDocument,
    CreatePerson,
    Evaluate,
    ReviewDocument,
    SaveDraft,
    SetMyCaseMembership,
    StartUpload,
    SubmitDocument,
    UpdateParsingPolicy,
    UpdatePerson,
    UploadChunk,
)
from src.backoffice.services.queries import (
    AssignmentDetail,
    AssignmentStatus,
    AssignmentSummary,
    MissingRequirements,
    Page,
)
from src.backoffice.tables.evidence import MAX_CHUNK_BYTES

logger = logging.getLogger(__name__)
router = APIRouter()


def application(request: Request = None):
    # Requester is verified by Main Sequence for delegated application calls.
    identity = User.get_requester() or User.get_logged_user()
    if identity is None:
        raise HTTPException(401, "verified_identity_required")
    reviewers = {
        x.strip() for x in os.environ.get("BACKOFFICE_REVIEWER_UIDS", "").split(",") if x.strip()
    }
    teams = [
        x.strip()
        for x in os.environ.get("BACKOFFICE_REVIEWER_TEAM_UIDS", "").split(",")
        if x.strip()
    ]
    reviewer = identity.is_organization_admin or identity.uid in reviewers
    # Local SDK identities intentionally omit organization facts. The loopback
    # gateway may attach a freshly verified directory fact for this exact UID.
    local_admin_uid = (
        getattr(request.state, "backoffice_local_admin_uid", None) if request else None
    )
    organization_admin = identity.is_organization_admin is True or local_admin_uid == identity.uid
    processors = {
        x.strip()
        for x in os.environ.get("BACKOFFICE_PARSING_PROCESSOR_UIDS", "").split(",")
        if x.strip()
    }
    if teams and not reviewer:
        reviewer = identity.in_teams(teams)
    return Application(
        identity.uid,
        actor_display_name=getattr(identity, "username", None),
        reviewer=bool(reviewer),
        organization_admin=organization_admin,
        parsing_processor=identity.uid in processors,
    )


Service = Depends(application)


async def validation_error(request: Request, error: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": error.errors(include_input=False, include_context=False, include_url=False)
        },
    )


async def invalid_contract(request: Request, error: ValueError):
    return JSONResponse(status_code=422, content={"detail": "invalid_contract_or_schema_version"})


async def processing_error(request: Request, error: ProcessingError):
    return JSONResponse(
        status_code=422
        if error.code.startswith(("source_", "invalid_source", "encrypted_", "unsupported_"))
        else 503,
        content={"detail": error.code},
    )


async def platform_error(request: Request, error: ApiError):
    status = error.status_code if error.status_code in (401, 403, 409, 429) else 503
    return JSONResponse(
        status_code=status,
        content={"detail": "metatables_operation_unavailable_retry_same_operation_key"},
    )


async def unavailable_source(request: Request, error: DataSourceResolutionError):
    return JSONResponse(status_code=503, content={"detail": "metatables_runtime_unavailable"})


async def request_controls(request: Request, call_next):
    # Bound bodies before JSON validation, including chunked HTTP requests.
    body = bytearray()
    limit = (
        16 * 1024 * 1024
        if request.url.path in {"/document-processing", "/source-documents/bucket-uploads"}
        else 1024 * 1024
    )
    try:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": "request_body_too_large"
                        if limit > 1024 * 1024
                        else "request_exceeds_one_mib"
                    },
                )
    except ClientDisconnect:
        # Navigation/AbortController can close a request before its body arrives.
        # No business handler has run, and a vanished client is not a server error.
        return Response(
            status_code=499,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    request._body = bytes(body)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@router.get("/")
def root(service: Application = Service):
    return {
        "name": "Back Office",
        "version": "0.3.0",
        "user_uid": service.actor,
        "can_review": service.reviewer,
    }


@router.get("/me")
def me(service: Application = Service):
    return {
        "user_uid": service.actor,
        "can_review": service.reviewer,
        "is_organization_admin": service.organization_admin,
    }


@router.get("/assistant/context", response_model=AssistantContext)
def assistant_context(service: Application = Service):
    """Discover this API's deployed helper after verifying the request identity."""
    return resolve_assistant_context()


@router.get("/admin/parsing-settings")
def parsing_settings(document_type: DocumentType, service: Application = Service):
    return service.parsing_settings(document_type)


@router.put("/admin/parsing-settings")
def save_parsing_settings(command: UpdateParsingPolicy, service: Application = Service):
    return service.update_parsing_settings(command)


@router.post("/documents/{uid}/parsing-results", status_code=201)
def complete_parsing(uid: UUID, command: CompleteParsing, service: Application = Service):
    return service.complete_parsing(uid, command)


@router.get("/readyz")
def ready(service: Application = Service):
    # No migrations or catalog publication on startup/readiness.
    service.db.execute(select(P.c.created_by).limit(1))
    published = [
        service.db.one(SETS, set_key=policy.key, version=policy.version)
        for policy in document_set_catalog()
    ]
    if any(not row or row["status"] != "published" for row in published) or service.db.count(
        SCHEMA
    ) < len(DOCUMENT_MODELS):
        raise HTTPException(503, "application_catalog_not_initialized_run_migration_job")
    return {"status": "ready", "user_uid": service.actor, "can_review": service.reviewer}


@router.get("/document-types")
def document_types(service: Application = Service):
    return {
        "items": [
            {
                "document_type": kind,
                "schema_version": version,
                "name": model.__name__,
                "description": model.__doc__,
            }
            for (kind, version), model in DOCUMENT_MODELS.items()
        ]
    }


@router.get("/document-types/{kind}/schema")
def document_schema(kind: str, version: int = 1, service: Application = Service):
    model = get_document_model(kind, version)
    return {
        "document_type": kind,
        "schema_version": version,
        "canonical_schema": model.model_json_schema(),
        "draft_schema": get_draft_model(kind, version).model_json_schema(),
    }


@router.get("/person-schema")
def person_schema(service: Application = Service):
    from src.backoffice.services.contracts import PersonInput

    return PersonInput.model_json_schema()


@router.get("/document-sets", response_model=Page[DocumentSet])
def document_sets(
    search: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    return service.list_document_sets(search, limit, offset)


@router.get("/document-sets/{key}/versions/{version}", response_model=DocumentSet)
def document_set(
    key: str,
    version: int = Path(ge=1),
    service: Application = Service,
):
    return service.document_set(key, version)


@router.get("/persons")
def people(
    search: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    return service.list_people(search, limit, offset)


@router.get("/review-queue")
def review_queue(
    search: str = Query("", max_length=100),
    responsibility: str = Query("all", pattern="^(all|mine|unassigned)$"),
    set_key: str = Query("", max_length=120),
    limit: int = Query(10, ge=1, le=20),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    from src.backoffice.services.casework import queue

    return queue(service, search, responsibility, set_key, limit, offset)


@router.get("/assignments/{uid}/workspace")
def review_workspace(uid: UUID, service: Application = Service):
    from src.backoffice.services.casework import workspace

    return workspace(service, uid)


@router.get("/assignments/{uid}/reviewers")
def case_reviewers(uid: UUID, service: Application = Service):
    from src.backoffice.services.casework import reviewers

    return reviewers(service, uid)


@router.put("/assignments/{uid}/reviewers/me")
def my_case_membership(uid: UUID, command: SetMyCaseMembership, service: Application = Service):
    from src.backoffice.services.casework import set_my_membership

    return set_my_membership(service, uid, command)


@router.post("/persons", status_code=201)
def create_person(command: CreatePerson, service: Application = Service):
    return service.create_person(command)


@router.get("/persons/{uid}")
def person(uid: UUID, service: Application = Service):
    return service.case(uid)["profile"]


@router.put("/persons/{uid}")
def update_person(uid: UUID, command: UpdatePerson, service: Application = Service):
    return service.update_person(uid, command)


@router.get("/persons/{uid}/assignments", response_model=Page[AssignmentSummary])
def assignments(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    return service.list_assignments(uid, limit, offset)


@router.post("/persons/{uid}/document-sets", status_code=201)
def assign(uid: UUID, command: AssignSet, service: Application = Service):
    return service.assign(uid, command)


@router.get("/assignments/{uid}", response_model=AssignmentDetail)
def assignment(uid: UUID, service: Application = Service):
    return service.assignment(uid)


@router.get("/assignments/{uid}/status", response_model=AssignmentStatus)
def current_status(uid: UUID, service: Application = Service):
    return service.current_status(uid)


@router.get("/assignments/{uid}/missing-requirements", response_model=MissingRequirements)
def missing_requirements(uid: UUID, service: Application = Service):
    return service.missing_requirements(uid)


@router.put("/assignments/{uid}/documents")
def assignment_documents(uid: UUID, command: AssignmentDocuments, service: Application = Service):
    return service.set_documents(uid, command)


@router.get("/persons/{uid}/documents")
def documents(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.case(uid)
    page = service.db.page(
        D, D.c.person_uid == uid, limit=limit, offset=offset, order=D.c.created_at.desc()
    )
    page["items"] = [service.document(row["uid"]) for row in page["items"]]
    return page


@router.post("/persons/{uid}/documents", status_code=201)
def create_document(uid: UUID, command: CreateDocument, service: Application = Service):
    return service.create_document(uid, command)


@router.get("/documents/{uid}")
def document(uid: UUID, service: Application = Service):
    return service.document(uid)


@router.get("/documents/{uid}/revisions")
def revisions(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.document(uid)
    return {
        "items": service.db.rows(
            DR, DR.c.document_uid == uid, limit=limit, offset=offset, order=DR.c.revision.desc()
        )
    }


@router.get("/documents/{uid}/revisions/{revision}/extraction-evidence")
def extraction_evidence(uid: UUID, revision: int, service: Application = Service):
    from src.backoffice.services.extraction_evidence import evidence_view

    return evidence_view(service, uid, revision)


@router.get("/documents/{uid}/revisions/{revision}")
def document_revision(uid: UUID, revision: int, service: Application = Service):
    return service.document(uid, revision_number=revision)


@router.patch("/documents/{uid}/draft")
@router.post("/documents/{uid}/revisions", status_code=201)
def save_draft(uid: UUID, command: SaveDraft, service: Application = Service):
    return service.save_draft(uid, command)


@router.post("/documents/{uid}/submit")
def submit(uid: UUID, command: SubmitDocument, service: Application = Service):
    return service.submit(uid, command)


@router.get("/documents/{uid}/reviews")
def reviews(uid: UUID, service: Application = Service):
    service.document(uid)
    return {
        "items": service.db.rows(
            RV, RV.c.document_uid == uid, limit=100, order=RV.c.reviewed_at.desc()
        )
    }


@router.post("/documents/{uid}/reviews", status_code=201)
def review(uid: UUID, command: ReviewDocument, service: Application = Service):
    return service.review(uid, command)


def processing_bucket():
    return MainSequenceBucket()


def processing_dispatcher():
    return MainSequenceDispatcher()


BucketService = Depends(processing_bucket)
DispatcherService = Depends(processing_dispatcher)


@router.post("/document-processing", status_code=202)
async def upload_and_process(
    person_uid: Annotated[UUID, Form()],
    operation_key: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    service: Application = Service,
    bucket=BucketService,
    dispatcher=DispatcherService,
):
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(service.case, person_uid, reading=False)
    try:
        content = await file.read(MAX_BYTES + 1)
        command = processing.BucketUpload(
            operation_key=operation_key,
            person_uid=person_uid,
            filename=file.filename or "document",
            media_type=file.content_type,
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        return await run_in_threadpool(
            processing.upload_and_start,
            service,
            command,
            content,
            bucket=bucket,
            dispatcher=dispatcher,
        )
    finally:
        await file.close()


@router.post("/source-documents/bucket-uploads", status_code=201)
async def upload_bucket_source(
    person_uid: Annotated[UUID, Form()],
    operation_key: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    service: Application = Service,
    bucket=BucketService,
):
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(service.case, person_uid, reading=False)
    try:
        content = await file.read(MAX_BYTES + 1)
        command = processing.BucketUpload(
            operation_key=operation_key,
            person_uid=person_uid,
            filename=file.filename or "document",
            media_type=file.content_type,
            byte_count=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
        )
        return await run_in_threadpool(processing.upload, service, command, content, bucket)
    finally:
        await file.close()


@router.post("/source-documents/{uid}/process", status_code=202)
def process_source(
    uid: UUID,
    command: Command,
    service: Application = Service,
    dispatcher=DispatcherService,
):
    return processing.start(service, uid, command, dispatcher)


@router.get("/processing-runs/{uid}")
@router.get("/document-processing/{uid}")
def processing_status(uid: UUID, service: Application = Service):
    return processing.view(processing.get_run(service, uid))


@router.post("/processing-runs/{uid}/retry", status_code=202)
@router.post("/document-processing/{uid}/retry", status_code=202)
def retry_processing(
    uid: UUID,
    command: Command,
    service: Application = Service,
    dispatcher=DispatcherService,
):
    return processing.retry(service, uid, command, dispatcher)


@router.post("/source-documents/uploads", status_code=201)
def start_upload(command: StartUpload, service: Application = Service):
    return service.upload(command)


@router.get("/persons/{uid}/sources")
def sources(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.case(uid)
    return service.db.page(
        RAW, RAW.c.person_uid == uid, limit=limit, offset=offset, order=RAW.c.created_at.desc()
    )


@router.get("/source-documents/{uid}")
def source(uid: UUID, service: Application = Service):
    return service.upload_status(uid)


@router.put("/source-documents/uploads/{uid}/chunks/{index}")
def upload_chunk(uid: UUID, index: int, command: UploadChunk, service: Application = Service):
    return service.put_chunk(uid, index, command)


@router.post("/source-documents/uploads/{uid}/finalize")
def finalize_upload(uid: UUID, command: Command, service: Application = Service):
    return service.finalize(uid, command)


@router.get("/source-documents/{uid}/content")
def content(uid: UUID, service: Application = Service):
    row = service.source(uid)
    if row["status"] != "ready":
        raise HTTPException(409, "source_not_ready")
    # Serve as a bounded attachment. Embedded delegated responses have an 8 MiB
    # wire budget, so the UI downloads individual chunks for larger sources.
    return Response(
        service.source_bytes(row),
        media_type=row["media_type"],
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row["filename"]),
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/source-documents/{uid}/chunks/{index}")
def download_chunk(uid: UUID, index: int, service: Application = Service):
    row = service.source(uid)
    if row["status"] != "ready" or not 0 <= index < row["chunk_count"]:
        raise HTTPException(404, "ready_chunk_not_found")
    from src.backoffice.services.application import CHUNK

    chunk = service.required(CHUNK, raw_document_uid=uid, chunk_index=index)
    return {
        "content_base64": chunk["content_base64"],
        "content_sha256": chunk["content_sha256"],
        "chunk_index": index,
        "chunk_bytes": MAX_CHUNK_BYTES,
    }


@router.post(
    "/assignments/{uid}/evaluations",
    status_code=201,
    responses={202: {"description": "Comparison evaluation queued on the shared processing Job"}},
)
def evaluate(
    uid: UUID, command: Evaluate, service: Application = Service, dispatcher=DispatcherService
):
    result = service.evaluate(uid, command, dispatcher=dispatcher)
    return (
        JSONResponse(status_code=202, content=result) if "processing_run_uid" in result else result
    )


@router.get("/assignments/{uid}/evaluations")
def evaluations(
    uid: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.assignment(uid)
    return service.db.page(
        EV, EV.c.assignment_uid == uid, limit=limit, offset=offset, order=EV.c.created_at.desc()
    )


@router.get("/evaluations/{uid}")
def evaluation(uid: UUID, service: Application = Service):
    return service.evaluation(uid)


@router.get("/persons/{uid}/history")
def history(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.case(uid)
    return service.db.page(
        AUDIT,
        AUDIT.c.resource_uid == uid,
        limit=limit,
        offset=offset,
        order=AUDIT.c.occurred_at.desc(),
    )


@router.get("/operations/{uid}")
def operation(uid: UUID, service: Application = Service):
    row = service.operation(uid)
    return {
        key: row[key] for key in ("uid", "kind", "status", "result", "created_at", "updated_at")
    }


@router.post("/operations/{uid}/resume")
def resume_operation(uid: UUID, service: Application = Service):
    return service.resume(uid)


def create_app():
    """Each application owns a fresh MCP transport and its single-use lifespan."""
    from api.app.mcp.server import mount_mcp

    application_app = FastAPI(
        title="Back Office document reconciliation",
        version="0.3.0",
        description="Authenticated business REST API and read-only Back Office MCP queries.",
    )
    install_request_identity(application_app)
    application_app.include_router(router)
    application_app.add_exception_handler(ValidationError, validation_error)
    application_app.add_exception_handler(ValueError, invalid_contract)
    application_app.add_exception_handler(ApiError, platform_error)
    application_app.add_exception_handler(ProcessingError, processing_error)
    application_app.add_exception_handler(DataSourceResolutionError, unavailable_source)
    application_app.middleware("http")(request_controls)
    mount_mcp(application_app, application)
    return application_app


app = create_app()

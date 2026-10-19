"""Authenticated Back Office REST API; all storage uses Main Sequence MetaTables."""

import logging
import os
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from mainsequence.client import User
from mainsequence.client.exceptions import ApiError
from mainsequence.server.fastapi import install_request_identity
from metatables import DataSourceResolutionError
from pydantic import ValidationError
from sqlalchemy import select

from src.backoffice.policies.new_account_requirements import new_account_requirements
from src.backoffice.schemas.drafts import get_draft_model
from src.backoffice.schemas.registry import DOCUMENT_MODELS, get_document_model
from src.backoffice.services.application import (
    AUDIT,
    DR,
    EV,
    RAW,
    RV,
    SCHEMA,
    SETS,
    A,
    Application,
    D,
    P,
)
from src.backoffice.services.contracts import (
    AssignmentDocuments,
    AssignSet,
    Command,
    CreateDocument,
    CreatePerson,
    Evaluate,
    ReviewDocument,
    SaveDraft,
    StartUpload,
    SubmitDocument,
    UpdatePerson,
    UploadChunk,
)
from src.backoffice.tables.evidence import MAX_CHUNK_BYTES

logger = logging.getLogger(__name__)
app = FastAPI(
    title="Back Office document reconciliation",
    version="0.2.0",
    description="People, evidence, versioned reviews and reproducible document requirement evaluations on Main Sequence MetaTables.",
)
install_request_identity(app)


def application():
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
    if teams and not reviewer:
        reviewer = identity.in_teams(teams)
    return Application(identity.uid, reviewer=bool(reviewer))


Service = Depends(application)


@app.exception_handler(ValidationError)
async def validation_error(request: Request, error: ValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": error.errors(include_input=False, include_context=False, include_url=False)
        },
    )


@app.exception_handler(ValueError)
async def invalid_contract(request: Request, error: ValueError):
    return JSONResponse(status_code=422, content={"detail": "invalid_contract_or_schema_version"})


@app.exception_handler(ApiError)
async def platform_error(request: Request, error: ApiError):
    status = error.status_code if error.status_code in (401, 403, 409, 429) else 503
    return JSONResponse(
        status_code=status,
        content={"detail": "metatables_operation_unavailable_retry_same_operation_key"},
    )


@app.exception_handler(DataSourceResolutionError)
async def unavailable_source(request: Request, error: DataSourceResolutionError):
    return JSONResponse(status_code=503, content={"detail": "metatables_runtime_unavailable"})


@app.middleware("http")
async def request_controls(request: Request, call_next):
    # Bound bodies before JSON validation, including chunked HTTP requests.
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            return JSONResponse(status_code=413, content={"detail": "request_exceeds_one_mib"})
    request._body = bytes(body)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
def root(service: Application = Service):
    return {
        "name": "Back Office",
        "version": app.version,
        "user_uid": service.actor,
        "can_review": service.reviewer,
    }


@app.get("/me")
def me(service: Application = Service):
    return {"user_uid": service.actor, "can_review": service.reviewer}


@app.get("/readyz")
def ready(service: Application = Service):
    # No migrations or catalog publication on startup/readiness.
    service.db.execute(select(P.c.created_by).limit(1))
    policy = new_account_requirements()
    published = service.db.one(SETS, set_key=policy.key, version=policy.version)
    if (
        not published
        or published["status"] != "published"
        or service.db.count(SCHEMA) < len(DOCUMENT_MODELS)
    ):
        raise HTTPException(503, "application_catalog_not_initialized_run_migration_job")
    return {"status": "ready", "user_uid": service.actor, "can_review": service.reviewer}


@app.get("/document-types")
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


@app.get("/document-types/{kind}/schema")
def document_schema(kind: str, version: int = 1, service: Application = Service):
    model = get_document_model(kind, version)
    return {
        "document_type": kind,
        "schema_version": version,
        "canonical_schema": model.model_json_schema(),
        "draft_schema": get_draft_model(kind, version).model_json_schema(),
    }


@app.get("/person-schema")
def person_schema(service: Application = Service):
    from src.backoffice.services.contracts import PersonInput

    return PersonInput.model_json_schema()


@app.get("/document-sets")
def document_sets(service: Application = Service):
    return {"items": [new_account_requirements().model_dump(mode="json")]}


@app.get("/persons")
def people(
    search: str = Query("", max_length=100),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    return service.list_people(search, limit, offset)


@app.post("/persons", status_code=201)
def create_person(command: CreatePerson, service: Application = Service):
    return service.create_person(command)


@app.get("/persons/{uid}")
def person(uid: UUID, service: Application = Service):
    return service.case(uid)["profile"]


@app.put("/persons/{uid}")
def update_person(uid: UUID, command: UpdatePerson, service: Application = Service):
    return service.update_person(uid, command)


@app.get("/persons/{uid}/assignments")
def assignments(
    uid: UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: Application = Service,
):
    service.case(uid)
    return service.db.page(
        A, A.c.person_uid == uid, limit=limit, offset=offset, order=A.c.created_at.desc()
    )


@app.post("/persons/{uid}/document-sets", status_code=201)
def assign(uid: UUID, command: AssignSet, service: Application = Service):
    return service.assign(uid, command)


@app.get("/assignments/{uid}")
def assignment(uid: UUID, service: Application = Service):
    return service.assignment(uid)


@app.put("/assignments/{uid}/documents")
def assignment_documents(uid: UUID, command: AssignmentDocuments, service: Application = Service):
    return service.set_documents(uid, command)


@app.get("/persons/{uid}/documents")
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


@app.post("/persons/{uid}/documents", status_code=201)
def create_document(uid: UUID, command: CreateDocument, service: Application = Service):
    return service.create_document(uid, command)


@app.get("/documents/{uid}")
def document(uid: UUID, service: Application = Service):
    return service.document(uid)


@app.get("/documents/{uid}/revisions")
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


@app.patch("/documents/{uid}/draft")
@app.post("/documents/{uid}/revisions", status_code=201)
def save_draft(uid: UUID, command: SaveDraft, service: Application = Service):
    return service.save_draft(uid, command)


@app.post("/documents/{uid}/submit")
def submit(uid: UUID, command: SubmitDocument, service: Application = Service):
    return service.submit(uid, command)


@app.get("/documents/{uid}/reviews")
def reviews(uid: UUID, service: Application = Service):
    service.document(uid)
    return {
        "items": service.db.rows(
            RV, RV.c.document_uid == uid, limit=100, order=RV.c.reviewed_at.desc()
        )
    }


@app.post("/documents/{uid}/reviews", status_code=201)
def review(uid: UUID, command: ReviewDocument, service: Application = Service):
    return service.review(uid, command)


@app.post("/source-documents/uploads", status_code=201)
def start_upload(command: StartUpload, service: Application = Service):
    return service.upload(command)


@app.get("/persons/{uid}/sources")
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


@app.get("/source-documents/{uid}")
def source(uid: UUID, service: Application = Service):
    return service.upload_status(uid)


@app.put("/source-documents/uploads/{uid}/chunks/{index}")
def upload_chunk(uid: UUID, index: int, command: UploadChunk, service: Application = Service):
    return service.put_chunk(uid, index, command)


@app.post("/source-documents/uploads/{uid}/finalize")
def finalize_upload(uid: UUID, command: Command, service: Application = Service):
    return service.finalize(uid, command)


@app.get("/source-documents/{uid}/content")
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


@app.get("/source-documents/{uid}/chunks/{index}")
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


@app.post("/assignments/{uid}/evaluations", status_code=201)
def evaluate(uid: UUID, command: Evaluate, service: Application = Service):
    return service.evaluate(uid, command)


@app.get("/assignments/{uid}/evaluations")
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


@app.get("/evaluations/{uid}")
def evaluation(uid: UUID, service: Application = Service):
    return service.evaluation(uid)


@app.get("/persons/{uid}/history")
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


@app.get("/operations/{uid}")
def operation(uid: UUID, service: Application = Service):
    row = service.operation(uid)
    return {
        key: row[key] for key in ("uid", "kind", "status", "result", "created_at", "updated_at")
    }


@app.post("/operations/{uid}/resume")
def resume_operation(uid: UUID, service: Application = Service):
    return service.resume(uid)

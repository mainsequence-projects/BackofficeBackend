"""REST adapters for shared durable intake/allocation services."""

import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from src.backoffice.processing import allocation
from src.backoffice.processing.allocation_contracts import (
    AllocateDocument,
    IntakeUpload,
    ResolveAllocation,
)
from src.backoffice.processing.contracts import MAX_BYTES, MAX_PAGES
from src.backoffice.services.contracts import Command


def router_for(service_factory, bucket_factory, dispatcher_factory):
    router = APIRouter()
    service = Depends(service_factory)
    bucket = Depends(bucket_factory)
    dispatcher = Depends(dispatcher_factory)

    @router.get("/document-intakes/config")
    def limits(app=service):
        return dict(
            max_bytes=MAX_BYTES,
            max_pages=MAX_PAGES,
            media_types=["application/pdf", "image/png", "image/jpeg"],
            upload_concurrency=2,
        )

    @router.get("/document-intakes")
    def list_intakes(
        limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), app=service
    ):
        return allocation.listing(app, limit, offset)

    @router.post("/document-intakes", status_code=202)
    async def upload(
        request: Request,
        operation_key: Annotated[UUID, Form()],
        file: Annotated[UploadFile, File()],
        app=service,
        objects=bucket,
        jobs=dispatcher,
    ):
        try:
            form = await request.form()
            if set(form) != {"file", "operation_key"} or any(
                len(form.getlist(key)) != 1 for key in form
            ):
                raise HTTPException(422, "unexpected_or_repeated_intake_field")
            content = await file.read(MAX_BYTES + 1)
            command = IntakeUpload(
                operation_key=operation_key,
                filename=file.filename or "document",
                media_type=file.content_type,
                byte_count=len(content),
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
            return await run_in_threadpool(
                allocation.upload, app, command, content, bucket=objects, dispatcher=jobs
            )
        finally:
            await file.close()

    @router.post("/document-allocations", status_code=202)
    def start(command: AllocateDocument, app=service, jobs=dispatcher):
        return allocation.start(app, command, jobs)

    @router.get("/document-allocations/{uid}")
    def status(
        uid: UUID, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), app=service
    ):
        return allocation.view(app, allocation.get(app, uid), limit, offset)

    @router.post("/document-allocations/{uid}/resolve", status_code=202)
    def resolve(uid: UUID, command: ResolveAllocation, app=service, jobs=dispatcher):
        return allocation.resolve(app, uid, command, jobs)

    @router.post("/document-allocations/{uid}/retry", status_code=202)
    def retry(uid: UUID, command: Command, app=service, jobs=dispatcher):
        return allocation.retry(app, uid, command, jobs)

    return router

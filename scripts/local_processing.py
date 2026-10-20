"""Bounded local workers for the verified development database, never hosted Jobs."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from mainsequence.client import User
from metatables import get_runtime_status
from sqlalchemy import and_, or_

from scripts.local_api import require_local_runtime
from src.backoffice.processing.adapters import ProcessingError
from src.backoffice.processing.workflow import Worker
from src.backoffice.services.application import RUN, Application

logger = logging.getLogger(__name__)


class LocalProcessing:
    def __init__(self, source_uid):
        self.source_uid = source_uid
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="document-worker")
        self.lock = Lock()
        self.futures = {}
        self.closed = False

    def application(self):
        if require_local_runtime(get_runtime_status()) != self.source_uid:
            raise ProcessingError("local_processing_source_changed")
        user = User.get_authenticated_user_details()
        if user.is_active is not True or user.blocked_access is True:
            raise ProcessingError("allocation_requester_unavailable")
        # This role is confined to the verified local developer runtime. The allocation
        # worker separately refreshes the original requester's business authorization.
        return Application(user.uid, parsing_processor=True)

    def execute(self, uid):
        try:
            result = Worker(self.application()).run(uid)
            logger.info("Local document run %s: %s", uid, result["status"])
        except Exception:
            # No document payload, credentials or provider exception text in logs.
            logger.error(
                "Local document run %s could not execute; retry after checking runtime", uid
            )

    def dispatch(self, uid):
        uid = str(UUID(str(uid)))
        with self.lock:
            if self.closed:
                raise ProcessingError("processing_dispatch_unavailable")
            if uid in self.futures and not self.futures[uid].done():
                return None
            self.futures = {k: f for k, f in self.futures.items() if not f.done()}
            if len(self.futures) >= 20:
                # Durable pending rows are picked up by the recovery loop.
                return None
            self.futures[uid] = self.executor.submit(self.execute, uid)
        return None

    def recover(self):
        app = self.application()
        rows = app.db.rows(
            RUN,
            RUN.c.kind.in_(["document.allocate", "document.extract", "document.compare"]),
            or_(
                RUN.c.status == "pending",
                and_(RUN.c.status == "running", RUN.c.lease_expires_at <= datetime.now(UTC)),
            ),
            limit=20,
            order=RUN.c.created_at.asc(),
        )
        for row in rows:
            if row["input_snapshot"].get("parent_allocation_uid") or row["input_snapshot"].get(
                "parent_packet_uid"
            ):
                continue  # The parent's fenced worker resumes its inline extraction.
            self.dispatch(row["uid"])

    async def supervise(self):
        while True:
            try:
                await asyncio.to_thread(self.recover)
            except Exception:
                logger.error("Local processing recovery unavailable; will retry")
            await asyncio.sleep(5)

    def close(self):
        with self.lock:
            self.closed = True
        self.executor.shutdown(wait=True, cancel_futures=True)

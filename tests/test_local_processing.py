"""Local dispatch uses the pinned runtime and recovers durable work without hosted Jobs."""

from threading import Event
from uuid import uuid4

import pytest

from scripts import local_processing
from src.backoffice.processing.allocation import record
from src.backoffice.services.application import RUN
from tests.api.test_workflows import business as business


def test_dispatch_is_bounded_and_deduplicates_active_run():
    pool = local_processing.LocalProcessing(str(uuid4()))
    entered, release = Event(), Event()
    calls = []

    def execute(uid):
        calls.append(uid)
        entered.set()
        assert release.wait(5)

    pool.execute = execute
    uid = str(uuid4())
    try:
        pool.dispatch(uid)
        assert entered.wait(5)
        pool.dispatch(uid)
        assert calls == [uid]
    finally:
        release.set()
        pool.close()
    with pytest.raises(local_processing.ProcessingError):
        pool.dispatch(uid)


def test_recovery_selects_pending_roots_not_failed_runs_or_inline_children(business):
    _, current, store = business
    pending, failed, child = [str(uuid4()) for _ in range(3)]
    store.ensure(RUN, record(pending, "document.allocate", {}))
    store.ensure(RUN, record(failed, "document.allocate", {}, status="failed"))
    store.ensure(RUN, record(child, "document.extract", {"parent_allocation_uid": pending}))
    pool = local_processing.LocalProcessing(str(uuid4()))
    pool.application = lambda: current[0]
    dispatched = []
    pool.dispatch = dispatched.append
    try:
        pool.recover()
        assert dispatched == [pending]
    finally:
        pool.close()


def test_local_source_change_blocks_worker_before_directory_or_document_access(monkeypatch):
    pool = local_processing.LocalProcessing(str(uuid4()))
    monkeypatch.setattr(local_processing, "get_runtime_status", lambda: {"local_mode": False})
    monkeypatch.setattr(
        local_processing.User,
        "get_authenticated_user_details",
        lambda: pytest.fail("Must reject storage before touching identity or documents"),
    )
    try:
        with pytest.raises(RuntimeError, match="local MetaTables"):
            pool.application()
    finally:
        pool.close()

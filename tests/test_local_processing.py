"""Local dispatch uses the pinned runtime and recovers durable work without hosted Jobs."""

from threading import Event
from types import SimpleNamespace
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


@pytest.fixture
def identity_pool(business, monkeypatch):
    _, current, store = business
    source_uid = str(uuid4())
    pool = local_processing.LocalProcessing(source_uid)
    state = SimpleNamespace(
        user=SimpleNamespace(uid=current[0].actor, is_active=True, blocked_access=False),
        directory_calls=0,
        runtime_calls=0,
    )

    def runtime():
        state.runtime_calls += 1
        return {
            "local_mode": True,
            "dialect": "sqlite",
            "data_source": {"uid": source_uid, "class_type": "sqlite"},
            "bootstrap": {"active": True, "status": "ready"},
        }

    def directory():
        state.directory_calls += 1
        if isinstance(state.user, Exception):
            raise state.user
        return state.user

    application = local_processing.Application
    monkeypatch.setattr(local_processing, "get_runtime_status", runtime)
    monkeypatch.setattr(local_processing.User, "get_authenticated_user_details", directory)
    monkeypatch.setattr(
        local_processing, "Application", lambda uid, **kw: application(uid, store=store, **kw)
    )
    try:
        yield pool, state, store
    finally:
        pool.close()


def test_idle_recovery_caches_identity_but_keeps_checking_pinned_storage(identity_pool):
    pool, state, _ = identity_pool
    for _ in range(120):
        pool.recover()
    assert state.directory_calls == 1
    assert state.runtime_calls == 120


def test_each_dispatched_run_refreshes_identity_without_idle_polling(identity_pool, monkeypatch):
    pool, state, _ = identity_pool
    actors = []

    def worker(app):
        actors.append(app.actor)
        assert app.parsing_processor is True
        return SimpleNamespace(run=lambda uid: {"status": "completed"})

    monkeypatch.setattr(local_processing, "Worker", worker)
    pool.recover()
    for _ in range(2):
        uid = str(uuid4())
        pool.dispatch(uid)
        pool.futures[uid].result(timeout=5)
        pool.recover()
    assert actors == [state.user.uid, state.user.uid]
    assert state.directory_calls == 3  # One cold lookup, then one per real run.


@pytest.mark.parametrize("unavailable", ["inactive", "blocked", "directory_error"])
def test_work_never_uses_cached_identity_after_failed_refresh(
    identity_pool, monkeypatch, caplog, unavailable
):
    pool, state, _ = identity_pool
    pool.recover()
    if unavailable == "directory_error":
        state.user = RuntimeError("private directory failure")
    elif unavailable == "inactive":
        state.user.is_active = False
    else:
        state.user.blocked_access = True
    monkeypatch.setattr(
        local_processing, "Worker", lambda app: pytest.fail("Unauthorized work must not start")
    )
    pool.execute(str(uuid4()))
    assert state.directory_calls == 2
    assert pool.identity_uid is None
    assert "private directory failure" not in caplog.text
    # Recover only after the saved session resolves a currently active identity.
    state.user = SimpleNamespace(uid=str(uuid4()), is_active=True, blocked_access=False)
    pool.recover()
    assert state.directory_calls == 3
    assert pool.identity_uid == state.user.uid


def test_failed_recovery_invalidates_cache_before_retry(identity_pool, monkeypatch):
    pool, state, store = identity_pool
    pool.recover()

    def unavailable(*args, **kwargs):
        raise TimeoutError("Local API unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(store, "rows", unavailable)
        with pytest.raises(TimeoutError):
            pool.recover()
    pool.recover()
    pool.recover()
    assert state.directory_calls == 2


@pytest.mark.parametrize("raises", [False, True])
def test_failed_worker_invalidates_cache_before_recovery(identity_pool, monkeypatch, raises):
    pool, state, _ = identity_pool
    pool.recover()

    def run(uid):
        if raises:
            raise TimeoutError("worker unavailable")
        return {"status": "failed"}

    monkeypatch.setattr(local_processing, "Worker", lambda app: SimpleNamespace(run=run))
    pool.execute(str(uuid4()))
    pool.recover()
    pool.recover()
    assert state.directory_calls == 3

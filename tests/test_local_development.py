"""Local identity, storage selection, and browser isolation without real credentials."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from scripts import developer_session, local_api

API = "http://127.0.0.1:28641"
SITE = "http://127.0.0.1:5174"
SOURCE = str(uuid4())


def ready_state():
    return {
        "local_mode": True,
        "dialect": "sqlite",
        "data_source": {"uid": SOURCE, "class_type": "sqlite"},
        "bootstrap": {"active": True, "status": "ready"},
    }


@pytest.mark.parametrize(
    "change",
    [
        {"local_mode": False},
        {"dialect": "other"},
        {"data_source": None},
        {"data_source_error": "unavailable"},
        {"bootstrap": {"active": False, "status": "migration_required"}},
    ],
)
def test_storage_selection_fails_before_application_writes(change):
    state = ready_state() | change
    with pytest.raises(RuntimeError):
        local_api.require_local_runtime(state)


def test_uninitialized_runtime_must_still_identify_a_local_sqlite_candidate():
    candidate = {
        "local_mode": True,
        "bootstrap": {"status": "migration_required", "candidate": {"class_type": "sqlite"}},
    }
    assert local_api.require_local_runtime(candidate, ready=False) is None
    candidate["bootstrap"]["candidate"]["class_type"] = "other"
    with pytest.raises(RuntimeError):
        local_api.require_local_runtime(candidate, ready=False)


def test_cli_session_provider_owns_renewal_even_after_tokens_enter_environment(monkeypatch):
    monkeypatch.setattr(
        developer_session, "current_access_token", lambda: ("synthetic-token", None)
    )
    renewals = []
    monkeypatch.setattr(developer_session, "refresh_access", lambda: renewals.append(True))
    monkeypatch.setattr(developer_session.loaders, "provider", None)
    developer_session.configure_developer_session()
    provider = developer_session.loaders.provider
    monkeypatch.setenv("MAINSEQUENCE_AUTH_MODE", "jwt")
    monkeypatch.setenv("MAINSEQUENCE_ACCESS_TOKEN", "synthetic-token")
    assert developer_session.loaders.refresh_headers()["Authorization"] == "Bearer synthetic-token"
    assert developer_session.loaders.provider is provider
    developer_session.loaders.refresh_headers(force=True)
    assert renewals == [True]


def gateway(app):
    return local_api.LocalDeveloperGateway(app, api_origin=API, site_origin=SITE, source_uid=SOURCE)


def test_developer_credential_stays_server_side_and_actual_api_verifies_it(monkeypatch):
    from mainsequence.server import fastapi as sdk_identity

    from api.app.main import create_app

    uid = str(uuid4())
    monkeypatch.setattr(
        local_api.User,
        "get_authenticated_user_details",
        lambda: SimpleNamespace(uid=uid, is_organization_admin=False),
    )
    monkeypatch.setenv("MAINSEQUENCE_ENDPOINT", "http://platform.invalid")
    monkeypatch.setattr(
        local_api,
        "get_authorization_headers",
        lambda: {"Authorization": "Bearer synthetic-server-token"},
    )

    def verify(url, *, headers, **kwargs):
        assert url == "http://platform.invalid/api/v1/users/me/"
        assert headers["Authorization"] == "Bearer synthetic-server-token"
        return SimpleNamespace(status_code=200, json=lambda: {"uid": uid, "username": "developer"})

    monkeypatch.setattr(sdk_identity.requests, "get", verify)
    with TestClient(gateway(create_app()), base_url=API, client=("127.0.0.1", 49000)) as client:
        response = client.get(
            "/",
            headers={
                "Origin": SITE,
                "Authorization": "Bearer untrusted-browser-token",
                "X-User-Id": "untrusted",
                "X-User-UID": str(uuid4()),
            },
        )
    assert response.status_code == 200
    assert response.json()["user_uid"] == uid
    assert "token" not in response.text


def test_missing_developer_session_returns_unavailable_without_raw_errors(monkeypatch):
    def unavailable():
        raise RuntimeError("synthetic credential detail must stay private")

    app = Starlette()

    monkeypatch.setattr(local_api, "get_authorization_headers", unavailable)
    with TestClient(gateway(app), base_url=API, client=("127.0.0.1", 49000)) as client:
        response = client.get("/")
    assert response.status_code == 503
    assert response.json() == {"detail": "identity_unavailable"}


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://foreign.invalid"},
        {"Host": "foreign.invalid"},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_foreign_browser_requests_never_receive_a_developer_credential(headers, monkeypatch):
    def credentials():
        raise AssertionError("Must reject before looking up credentials")

    app = Starlette()

    monkeypatch.setattr(local_api, "get_authorization_headers", credentials)
    with TestClient(gateway(app), base_url=API, client=("127.0.0.1", 49000)) as client:
        assert client.get("/", headers=headers).status_code == 403


def test_health_reports_the_selected_source_and_rejects_changes(monkeypatch):
    app = Starlette()

    state = ready_state()
    monkeypatch.setattr(local_api, "get_runtime_status", lambda: deepcopy(state))
    with TestClient(gateway(app), base_url=API, client=("127.0.0.1", 49000)) as client:
        assert client.get("/healthz").json()["metatables"]["data_source_uid"] == SOURCE
        state["data_source"]["uid"] = str(uuid4())
        assert client.get("/healthz").status_code == 503


def test_developer_gateway_refuses_hosted_startup(monkeypatch):
    monkeypatch.setenv("APP_NAME", "hosted-app")
    with pytest.raises(RuntimeError, match="hosted"):
        local_api.create_app()


@pytest.mark.parametrize("delegated", [False, True])
def test_local_admin_fact_only_applies_to_verified_effective_identity(monkeypatch, delegated):
    from starlette.requests import Request

    from api.app.main import application

    developer_uid, requester_uid = str(uuid4()), str(uuid4())
    developer = SimpleNamespace(uid=developer_uid, is_organization_admin=False)
    requester = SimpleNamespace(uid=requester_uid, is_organization_admin=False)
    monkeypatch.delenv("BACKOFFICE_REVIEWER_TEAM_UIDS", raising=False)
    monkeypatch.setattr(local_api.User, "get_logged_user", lambda: developer)
    monkeypatch.setattr(local_api.User, "get_requester", lambda: requester if delegated else None)
    request = Request(
        {
            "type": "http",
            "state": {"backoffice_local_admin_uid": developer_uid},
            "headers": [(b"x-organization-admin", b"true")],
        }
    )
    service = application(request)
    assert service.actor == (requester_uid if delegated else developer_uid)
    assert service.organization_admin is (not delegated)
    request.scope["state"].clear()
    assert application(request).organization_admin is False


def test_gateway_refreshes_admin_permission_and_fails_closed(monkeypatch):
    from mainsequence.server import fastapi as sdk_identity

    from api.app.main import create_app

    uid = str(uuid4())
    allowed = [True]
    monkeypatch.setenv("MAINSEQUENCE_ENDPOINT", "http://platform.invalid")
    monkeypatch.setattr(
        local_api, "get_authorization_headers", lambda: {"Authorization": "Bearer synthetic"}
    )
    monkeypatch.setattr(
        sdk_identity.requests,
        "get",
        lambda *args, **kwargs: SimpleNamespace(status_code=200, json=lambda: {"uid": uid}),
    )

    def directory():
        if allowed[0] is None:
            raise RuntimeError("private directory failure")
        return SimpleNamespace(uid=uid, is_organization_admin=allowed[0])

    monkeypatch.setattr(local_api.User, "get_authenticated_user_details", directory)
    with TestClient(gateway(create_app()), base_url=API, client=("127.0.0.1", 49000)) as client:
        assert client.get("/me").json()["is_organization_admin"] is True
        allowed[0] = False
        assert (
            client.get("/me", headers={"X-Organization-Admin": "true"}).json()[
                "is_organization_admin"
            ]
            is False
        )
        assert client.get("/admin/parsing-settings?document_type=passport").status_code == 403
        allowed[0] = None
        response = client.get("/me")
        assert response.status_code == 503
        assert response.json() == {"detail": "organization_permissions_unavailable"}

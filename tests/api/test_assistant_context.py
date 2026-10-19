"""Agent discovery follows the API's branch/Environment and fails explicitly."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mainsequence.client.exceptions import ApiError
from mainsequence.code_repository_context import CodeRepositoryContextError

from api.app import assistant
from api.app.main import application, create_app, router


@pytest.fixture
def discovery(monkeypatch):
    environment, branch, agent = (str(uuid4()) for _ in range(3))
    context = SimpleNamespace(
        status="resolved",
        code_repository_branch_uid=branch,
        organization_environment_uid=environment,
    )
    helper = SimpleNamespace(
        uid=agent,
        code_repository_branch_uid=branch,
        organization_environment_uid=environment,
        runtime_release_uid=str(uuid4()),
    )
    monkeypatch.setattr(assistant, "get_code_repository_context", lambda: context)
    lookup = Mock(return_value=[helper])
    monkeypatch.setattr(assistant.Agent, "filter", lookup)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[application] = lambda: SimpleNamespace(actor=str(uuid4()))
    with TestClient(app) as client:
        yield client, context, helper, lookup


def test_returns_current_deployed_helper_and_ignores_browser_environment(discovery):
    client, context, helper, lookup = discovery
    response = client.get("/assistant/context", params={"environmentUid": str(uuid4())})
    assert response.status_code == 200
    assert response.json() == {
        "environmentUid": context.organization_environment_uid,
        "agentUid": helper.uid,
    }
    lookup.assert_called_once_with(name="Back Office Helper", timeout=(3.05, 10))
    # A recreated Agent is discovered again; no UID is cached or compiled into the app.
    helper.uid = str(uuid4())
    assert client.get("/assistant/context").json()["agentUid"] == helper.uid


@pytest.mark.parametrize("field", ["code_repository_branch_uid", "organization_environment_uid"])
def test_does_not_select_an_identically_named_agent_in_another_scope(discovery, field):
    client, _, helper, _ = discovery
    setattr(helper, field, str(uuid4()))
    response = client.get("/assistant/context")
    assert response.status_code == 503
    assert response.json()["detail"] == "assistant_agent_not_deployed"


def test_missing_ambiguous_or_undeployed_agent_is_explicit(discovery):
    client, _, helper, lookup = discovery
    for matches, detail in [
        ([], "assistant_agent_not_deployed"),
        ([helper, helper], "assistant_agent_ambiguous"),
    ]:
        lookup.return_value = matches
        response = client.get("/assistant/context")
        assert response.status_code == 503
        assert response.json()["detail"] == detail
    lookup.return_value = [helper]
    helper.runtime_release_uid = None
    assert client.get("/assistant/context").status_code == 503


def test_missing_environment_never_queries_other_environments(discovery):
    client, context, _, lookup = discovery
    context.organization_environment_uid = None
    assert client.get("/assistant/context").status_code == 503
    lookup.assert_not_called()


def test_context_resolution_failure_is_handled(discovery, monkeypatch):
    client, _, _, lookup = discovery
    monkeypatch.setattr(
        assistant,
        "get_code_repository_context",
        Mock(side_effect=CodeRepositoryContextError("Context unavailable")),
    )
    response = client.get("/assistant/context")
    assert response.status_code == 503
    assert response.json()["detail"] == "assistant_environment_unavailable"
    lookup.assert_not_called()


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_platform_refusal_and_outage_do_not_expose_raw_error_or_fall_back(discovery, status):
    client, _, _, lookup = discovery
    lookup.side_effect = ApiError(
        "Sensitive upstream detail", response=SimpleNamespace(status_code=status)
    )
    response = client.get("/assistant/context")
    assert response.status_code == (status if status in {401, 403, 429} else 503)
    assert response.json()["detail"] == "assistant_discovery_unavailable"
    assert "Sensitive" not in response.text
    assert lookup.call_count == 1


def test_real_endpoint_requires_verified_identity(monkeypatch):
    lookup = Mock(side_effect=AssertionError("Unauthenticated discovery must not run"))
    monkeypatch.setattr(assistant.Agent, "filter", lookup)
    with TestClient(create_app()) as client:
        assert client.get("/assistant/context").status_code in {401, 403}
    lookup.assert_not_called()

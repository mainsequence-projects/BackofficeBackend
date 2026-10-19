"""Real MCP HTTP transport, SDK identity and REST parity over disposable SQLite."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from mainsequence.server import fastapi as sdk_identity
from test_workflows import SQLStorage, make_person, post

from api.app import main
from src.backoffice.services.application import Application, P
from src.backoffice.services.contracts import AssignSet, CreatePerson
from src.backoffice.services.reconciliation import reconcile
from src.backoffice_agent.policy import ALLOWED_TOOLS, READ_TOOLS

HEADERS = {"Accept": "application/json, text/event-stream"}


def rpc(client, method, params=None, **kwargs):
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        **kwargs,
    )


def tool(client, name, arguments=None, **kwargs):
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments or {}}, **kwargs)
    assert response.status_code == 200, response.text
    return response.json()["result"]


@pytest.fixture
def mcp_client(monkeypatch):
    store = SQLStorage()
    owner = str(uuid4())
    monkeypatch.setenv("MAINSEQUENCE_CALLER_AUTH_MODE", "local")
    monkeypatch.setenv("MAINSEQUENCE_ENDPOINT", "http://identity.invalid")
    monkeypatch.setenv("BACKOFFICE_REVIEWER_UIDS", "")
    monkeypatch.setenv("BACKOFFICE_REVIEWER_TEAM_UIDS", "")

    def identity(url, *, headers, **kwargs):
        token = headers["Authorization"].removeprefix("Bearer ")
        return SimpleNamespace(status_code=200, json=lambda: {"uid": token})

    monkeypatch.setattr(sdk_identity.requests, "get", identity)
    monkeypatch.setattr(
        main,
        "Application",
        lambda uid, reviewer=False, **permissions: Application(uid, reviewer, store, **permissions),
    )
    with TestClient(
        main.create_app(), headers={**HEADERS, "Authorization": f"Bearer {owner}"}
    ) as client:
        yield client, store, owner
    store.engine.dispose()


def assignment(client, person, version=1):
    return post(
        client,
        f"/persons/{person}/document-sets",
        document_set_key="new_account_requirements",
        document_set_version=version,
    )["uid"]


def test_discovery_and_parity_without_query_writes(mcp_client):
    client, store, owner = mcp_client
    person = make_person(client)
    uid = assignment(client, person)
    initialized = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "backoffice-test", "version": "1"},
        },
    )
    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "backoffice"
    catalog = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in catalog} == ALLOWED_TOOLS
    assert all(t["annotations"]["readOnlyHint"] is (t["name"] in READ_TOOLS) for t in catalog)
    assert all(t.get("outputSchema") for t in catalog)
    assert "review_document" not in {t["name"] for t in catalog}
    original = store.execute

    def read_only(statement, operation="select"):
        assert operation == "select", "Query attempted a write"
        return original(statement, operation)

    store.execute = read_only
    cases = [
        ("get_current_user", {}, "/me"),
        ("search_persons", {"search": "Alex", "limit": 1}, "/persons?search=Alex&limit=1"),
        ("get_person", {"person_uid": person}, f"/persons/{person}"),
        ("get_person_schema", {}, "/person-schema"),
        ("list_document_sets", {"limit": 1}, "/document-sets?limit=1"),
        (
            "get_document_set",
            {"key": "new_account_requirements", "version": 1},
            "/document-sets/new_account_requirements/versions/1",
        ),
        ("list_person_assignments", {"person_uid": person}, f"/persons/{person}/assignments"),
        ("get_assignment", {"assignment_uid": uid}, f"/assignments/{uid}"),
        ("get_document_set_status", {"assignment_uid": uid}, f"/assignments/{uid}/status"),
        (
            "get_missing_requirements",
            {"assignment_uid": uid},
            f"/assignments/{uid}/missing-requirements",
        ),
    ]
    cases += [
        ("list_case_types", {}, "/case-types"),
        ("list_cases", {}, "/cases"),
        ("list_person_cases", {"person_uid": person}, f"/persons/{person}/cases"),
        ("get_case", {"case_uid": uid}, f"/cases/{uid}"),
        ("get_case_workspace", {"case_uid": uid}, f"/cases/{uid}/workspace"),
        ("get_case_reviewers", {"case_uid": uid}, f"/cases/{uid}/reviewers"),
        ("list_person_documents", {"person_uid": person}, f"/persons/{person}/documents"),
        ("list_person_sources", {"person_uid": person}, f"/persons/{person}/sources"),
        ("list_case_evaluations", {"case_uid": uid}, f"/cases/{uid}/evaluations"),
    ]

    def without_assessment_clock(value):
        if isinstance(value, dict):
            return {k: without_assessment_clock(v) for k, v in value.items() if k != "assessed_at"}
        if isinstance(value, list):
            return [without_assessment_clock(v) for v in value]
        return value

    for name, arguments, path in cases:
        result = tool(client, name, arguments)
        assert not result.get("isError"), result
        actual = result["structuredContent"]
        expected = client.get(path).json()
        if name == "get_current_user":
            # REST adds the Admin navigation fact; the helper's pinned read
            # contract deliberately retains its original two fields.
            assert expected.pop("is_organization_admin") is False
        actual.pop("assessed_at", None)
        expected.pop("assessed_at", None)
        assert without_assessment_clock(actual) == without_assessment_clock(expected), name
    sets = tool(client, "list_document_sets", {"limit": 1})["structuredContent"]
    assert sets["has_more"] and sets["total_items"] == 5
    assert (sets["items"][0]["key"], sets["items"][0]["version"]) == ("loan_requirements", 2)
    accounts = tool(client, "list_document_sets", {"search": "new_account_requirements"})[
        "structuredContent"
    ]
    assert [item["version"] for item in accounts["items"]] == [3, 2, 1]
    assert tool(client, "list_document_sets", {"search": "%"})["structuredContent"]["items"] == []


def test_identity_isolation_denial_and_validation(mcp_client):
    client, _, owner = mcp_client
    person = make_person(client)
    uid = assignment(client, person)
    stranger = {**HEADERS, "Authorization": f"Bearer {uuid4()}"}
    assert tool(client, "search_persons", headers=stranger)["structuredContent"]["total_items"] == 0
    for name, arguments in [
        ("get_person", {"person_uid": person}),
        ("list_person_assignments", {"person_uid": person}),
        ("get_assignment", {"assignment_uid": uid}),
        ("get_missing_requirements", {"assignment_uid": uid}),
    ]:
        result = tool(client, name, arguments, headers=stranger)
        assert result["isError"]
        assert result["structuredContent"]["error"]["status"] == 404
    for arguments in [{"limit": 101}, {"offset": -1}]:
        assert tool(client, "search_persons", arguments)["isError"]
    assert tool(client, "get_person", {"person_uid": "bad-uid"})["isError"]
    missing_version = tool(
        client, "get_document_set", {"key": "new_account_requirements", "version": 999}
    )
    assert missing_version["structuredContent"]["error"]["status"] == 404
    assert rpc(client, "tools/list", headers={**HEADERS, "Authorization": ""}).status_code == 401
    assert (
        rpc(client, "tools/list", headers={**HEADERS, "Origin": "https://evil.invalid"}).status_code
        == 403
    )
    assert client.get("/mcp").status_code == 405
    # A supplied user header cannot override the verified bearer caller.
    assert (
        rpc(client, "tools/list", headers={**HEADERS, "X-User-Uid": str(uuid4())}).status_code
        == 401
    )


def test_live_missing_contract_and_concurrent_revision(mcp_client, monkeypatch):
    client, _, _ = mcp_client
    person = make_person(client, employment_status=None, residency_permit_required=None)
    uid = assignment(client, person)
    assignment(client, person, version=2)
    result = tool(client, "get_missing_requirements", {"assignment_uid": uid})["structuredContent"]
    assert result["set_version"] == 1
    assert result["person_uid"] == person
    assert result["diagnostics_complete"] is False
    assert all(x["status"] not in {"satisfied", "not_applicable"} for x in result["findings"])
    identity = next(x for x in result["findings"] if x["requirement_key"] == "identity")
    assert identity["shortfall"] == 1 and identity["qualifying_count"] == 0
    assert {x["document_type"] for x in identity["alternatives"]} == {
        "passport",
        "national_identity_card",
    }
    unknown = [x for x in result["findings"] if x["reason_code"] == "APPLICABILITY_UNKNOWN"]
    assert unknown and all(x["shortfall"] is None and x["applicable"] is None for x in unknown)
    original = Application.evaluation_input
    calls = []

    def changing(self, uid):
        snapshot = original(self, uid)
        calls.append(True)
        if len(calls) == 2:
            snapshot["person"]["revision"] += 1
        return snapshot

    monkeypatch.setattr(Application, "evaluation_input", changing)
    result = tool(client, "get_missing_requirements", {"assignment_uid": uid})
    assert result["isError"]
    assert result["structuredContent"]["error"] == {
        "status": 409,
        "detail": "assessment_inputs_changed_retry_query",
        "retryable": True,
    }


def test_delegated_transport_uses_requester_not_admin_workload(monkeypatch):
    store = SQLStorage()
    owner, workload, stranger = uuid4(), uuid4(), uuid4()
    service = Application(owner, store=store)
    person = service.create_person(
        CreatePerson(operation_key=uuid4(), profile={"full_name": "Private"})
    )["uid"]
    uid = service.assign(
        person,
        AssignSet(
            operation_key=uuid4(),
            document_set_key="new_account_requirements",
            document_set_version=1,
        ),
    )["uid"]
    requester = SimpleNamespace(user_uid=owner, is_organization_admin=False)

    def verify(assertion):
        if assertion != "verified-test-proof":
            raise sdk_identity.InvalidCallerAssertion("Invalid proof")
        return SimpleNamespace(
            user_uid=workload,
            is_organization_admin=True,
            release_uid=uuid4(),
            environment_uid=uuid4(),
            _requester=requester,
        )

    monkeypatch.setenv("MAINSEQUENCE_CALLER_AUTH_MODE", "assertion")
    monkeypatch.setenv("BACKOFFICE_REVIEWER_UIDS", "")
    monkeypatch.setenv("BACKOFFICE_REVIEWER_TEAM_UIDS", "")
    monkeypatch.setattr(
        sdk_identity.CallerAssertionVerifier,
        "from_environment",
        lambda: SimpleNamespace(verify=verify),
    )
    monkeypatch.setattr(
        main,
        "Application",
        lambda uid, reviewer=False, **permissions: Application(uid, reviewer, store, **permissions),
    )
    with TestClient(
        main.create_app(),
        headers={**HEADERS, "X-Mainsequence-Caller-Assertion": "verified-test-proof"},
    ) as client:
        assert tool(client, "get_current_user")["structuredContent"] == {
            "user_uid": str(owner),
            "can_review": False,
        }
        assert not tool(client, "get_missing_requirements", {"assignment_uid": uid}).get("isError")
        created = tool(
            client,
            "create_person",
            {
                "command": {
                    "operation_key": str(uuid4()),
                    "profile": {"full_name": "Delegated Subject"},
                }
            },
        )["structuredContent"]["uid"]
        assert store.one(P, uid=created)["created_by"] == str(owner)
        assert (
            tool(
                client,
                "set_my_case_membership",
                {
                    "command": {
                        "operation_key": str(uuid4()),
                        "case_uid": uid,
                        "expected_revision": 0,
                        "assigned": True,
                    }
                },
            )["structuredContent"]["error"]["status"]
            == 403
        )
        requester.user_uid = stranger
        assert (
            tool(client, "get_missing_requirements", {"assignment_uid": uid})["structuredContent"][
                "error"
            ]["status"]
            == 404
        )
    store.engine.dispose()


@pytest.mark.parametrize(
    "state,code,qualifying",
    [
        ("pending_review", "REVIEW_REQUIRED", 0),
        ("needs_information", "DRAFT_NOT_SUBMITTED", 0),
        ("failed", "DOCUMENT_EXPIRED", 0),
        ("satisfied", "REQUIREMENT_SATISFIED", 1),
    ],
)
def test_diagnostics_preserve_review_draft_expiry_and_counts(state, code, qualifying):
    from src.backoffice.policies.new_account_requirements import new_account_requirements

    policy = new_account_requirements(1).model_dump(mode="json")
    policy["requirements"] = [x for x in policy["requirements"] if x["key"] == "identity"]
    doc = {
        "uid": str(uuid4()),
        "revision": 1,
        "document_type": "passport",
        "schema_version": 1,
        "status": "draft" if code == "DRAFT_NOT_SUBMITTED" else "submitted",
        "accepted": code != "REVIEW_REQUIRED",
        "review_status": "pending" if code == "REVIEW_REQUIRED" else "accepted",
        "latest_review": None,
        "source_hashes": ["source-hash"],
        "payload": {
            "expiration_date": "2020-01-01" if code == "DOCUMENT_EXPIRED" else "2030-01-01",
            "mrz_lines": ["EXAMPLE"],
        },
    }
    snapshot = {"policy": policy, "person": {}, "documents": [doc], "evaluation_date": "2026-10-19"}
    findings, _ = reconcile(deepcopy(snapshot), diagnostics=True)
    finding = findings[0]
    assert (finding["status"], finding["reason_code"], finding["qualifying_count"]) == (
        state,
        code,
        qualifying,
    )
    assert finding["shortfall"] == 1 - qualifying
    # Saved evaluation rows retain their existing shape.
    retained, _ = reconcile(snapshot)
    assert "next_action" not in retained[0]


def test_duplicate_sources_do_not_inflate_qualifying_count():
    from src.backoffice.policies.new_account_requirements import new_account_requirements

    policy = new_account_requirements(1).model_dump(mode="json")
    policy["requirements"] = [x for x in policy["requirements"] if x["key"] == "identity"]
    policy["requirements"][0]["min_count"] = 2
    doc = {
        "uid": str(uuid4()),
        "revision": 1,
        "document_type": "passport",
        "schema_version": 1,
        "status": "submitted",
        "accepted": True,
        "review_status": "accepted",
        "latest_review": None,
        "source_hashes": ["same-original-file"],
        "payload": {"expiration_date": "2030-01-01", "mrz_lines": ["EXAMPLE"]},
    }
    findings, _ = reconcile(
        {
            "policy": policy,
            "person": {},
            "documents": [doc, {**doc, "uid": str(uuid4())}],
            "evaluation_date": "2026-10-19",
        },
        diagnostics=True,
    )
    assert findings[0]["qualifying_count"] == 1
    assert findings[0]["shortfall"] == 1
    assert findings[0]["reason_code"] == "DUPLICATE_EVIDENCE_OR_PERIOD"

"""Actual authenticated MCP transport for allocation and requester isolation."""

from uuid import uuid4

from api.app import main
from src.backoffice.processing import allocation, workflow
from src.backoffice.services.application import Application
from tests.api.test_document_processing import Bucket, Dispatcher, Parser, png
from tests.api.test_mcp_queries import HEADERS, tool
from tests.api.test_mcp_queries import mcp_client as mcp_client
from tests.api.test_workflows import command, make_person


def test_allocation_tools_share_rest_and_resolve_for_requester(
    mcp_client, monkeypatch, document_fixture
):
    client, store, owner = mcp_client
    bucket, dispatcher = Bucket(), Dispatcher()
    client.app.dependency_overrides[main.processing_bucket] = lambda: bucket
    monkeypatch.setattr(main, "MainSequenceDispatcher", lambda: dispatcher)
    monkeypatch.setattr(
        allocation, "requester_app", lambda worker, row: Application(owner, store=store)
    )
    person = make_person(client)
    make_person(client)
    response = client.post(
        "/document-intakes",
        data={"operation_key": str(uuid4())},
        files={"file": ("identity.png", png(), "image/png")},
    )
    assert response.status_code == 202, response.text
    uid = response.json()["uid"]
    args = {"command": command(intake_uid=uid)}
    result = tool(client, "allocate_document", args)
    assert not result.get("isError"), result
    assert result["structuredContent"]["uid"] == uid
    worker = workflow.Worker(
        Application(uuid4(), parsing_processor=True, store=store),
        bucket=bucket,
        parser=Parser(document_fixture("passport")),
    )
    assert worker.run(uid)["status"] == "needs_input"
    actual = tool(client, "get_document_allocation", {"allocation_uid": uid})["structuredContent"]
    assert actual == client.get(f"/document-allocations/{uid}").json()
    assert (
        tool(client, "list_document_intakes")["structuredContent"]
        == client.get("/document-intakes").json()
    )
    body = command(subject_uid=person, expected_revision=actual["revision"])
    assert tool(
        client,
        "resolve_document_allocation",
        {"allocation_uid": uid, "command": {**body, "expected_revision": str(actual["revision"])}},
    )["isError"]
    resolved = tool(client, "resolve_document_allocation", {"allocation_uid": uid, "command": body})
    assert not resolved.get("isError"), resolved
    assert worker.run(uid)["status"] == "completed"
    assert not tool(
        client, "retry_document_allocation", {"allocation_uid": uid, "command": command()}
    ).get("isError")
    stranger = {**HEADERS, "Authorization": f"Bearer {uuid4()}"}
    assert (
        tool(client, "list_document_intakes", headers=stranger)["structuredContent"]["total_items"]
        == 0
    )
    for name, args in [
        ("get_document_allocation", {"allocation_uid": uid}),
        ("allocate_document", {"command": command(intake_uid=uid)}),
        ("resolve_document_allocation", {"allocation_uid": uid, "command": body}),
        ("retry_document_allocation", {"allocation_uid": uid, "command": command()}),
    ]:
        failure = tool(client, name, args, headers=stranger)
        assert failure["structuredContent"]["error"]["status"] == 404, failure
    assert tool(client, "allocate_document", {"command": command(intake_uid=uid, actor_uid=owner)})[
        "isError"
    ]

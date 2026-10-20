"""Explicit developer authority is confined to the verified local API and source."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from mcp import types
from tau_coding.extensions.api import ToolCallHookEvent

from src.backoffice_agent import local_mcp
from src.backoffice_agent.policy import load_contract

UID, SOURCE = str(uuid4()), str(uuid4())
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        "BACKOFFICE_LOCAL_MCP_ENABLED": "true",
        "TAU_LOCAL_MODE": "true",
        "TAU_EXCLUDE_BASE_TOOLS": "true",
        "TAU_EXCLUDE_MAINSEQUENCE_MCP": "true",
        "MAINSEQUENCE_TAU_HOST": "127.0.0.1",
        "BACKOFFICE_API_ORIGIN": "http://127.0.0.1:28649",
        "BACKOFFICE_LOCAL_SOURCE_UID": SOURCE,
    }.items():
        monkeypatch.setenv(key, value)
    for key in (
        "APP_NAME",
        "FASTAPI_PUBLIC_BASE_URL",
        "MAINSEQUENCE_CALLER_ASSERTION_ISSUER",
        "MAINSEQUENCE_CALLER_ASSERTION_JWKS_URL",
        "MAINSEQUENCE_CALLER_AUTH_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(local_mcp, "developer_uid", lambda: UID)
    api = {"user_uid": UID, "data_source_uid": SOURCE, "local_mode": True, "status": 200}
    original = httpx.AsyncClient

    def handle(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/me":
            return httpx.Response(api["status"], json={"user_uid": api["user_uid"]})
        assert request.url.path == "/healthz"
        return httpx.Response(
            200,
            json={
                "metatables": {
                    "local_mode": api["local_mode"],
                    "dialect": "sqlite",
                    "data_source_uid": api["data_source_uid"],
                }
            },
        )

    def client(*args, **kwargs):
        return original(*args, **kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(local_mcp.httpx, "AsyncClient", client)
    return api


@pytest.mark.parametrize(
    "key,value",
    [
        ("APP_NAME", "hosted"),
        ("FASTAPI_PUBLIC_BASE_URL", "https://app.example"),
        ("MAINSEQUENCE_CALLER_AUTH_MODE", "assertion"),
        ("TAU_LOCAL_MODE", "false"),
        ("TAU_EXCLUDE_BASE_TOOLS", "false"),
        ("TAU_EXCLUDE_MAINSEQUENCE_MCP", "false"),
        ("MAINSEQUENCE_TAU_HOST", "0.0.0.0"),
        ("BACKOFFICE_API_ORIGIN", "https://app.example"),
        ("BACKOFFICE_API_ORIGIN", "http://localhost:1234"),
        ("BACKOFFICE_API_ORIGIN", "http://127.0.0.1:1234/mcp"),
        ("BACKOFFICE_API_ORIGIN", "http://user:pass@127.0.0.1:1234"),
        ("BACKOFFICE_API_ORIGIN", "http://127.0.0.1:1234?target=remote"),
    ],
)
def test_developer_mode_cannot_be_enabled_for_hosted_or_arbitrary_origins(
    configured, monkeypatch, key, value
):
    monkeypatch.setenv(key, value)
    with pytest.raises(ValueError):
        local_mcp.LocalMCP.from_environment()


def test_disabled_adapter_does_not_change_hosted_behavior(monkeypatch):
    monkeypatch.delenv("BACKOFFICE_LOCAL_MCP_ENABLED", raising=False)
    assert local_mcp.LocalMCP.from_environment() is None


@pytest.mark.parametrize("change", ["user", "source", "hosted", "expired", "switched_login"])
def test_identity_source_and_login_changes_fail_before_mcp_calls(configured, monkeypatch, change):
    bridge = local_mcp.LocalMCP.from_environment()
    asyncio.run(bridge.verify())
    assert bridge.principal_uid == UID
    if change == "user":
        configured["user_uid"] = str(uuid4())
    elif change == "source":
        configured["data_source_uid"] = str(uuid4())
    elif change == "hosted":
        configured["local_mode"] = False
    elif change == "expired":
        configured["status"] = 401
    else:
        new_uid = str(uuid4())
        configured["user_uid"] = new_uid
        monkeypatch.setattr(local_mcp, "developer_uid", lambda: new_uid)
    with pytest.raises((local_mcp.LocalMCPUnavailable, httpx.HTTPStatusError)):
        asyncio.run(bridge.verify())


def test_actual_extension_registers_only_two_local_wrappers_and_keeps_discovery_gate(
    configured, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "local_policy_test", ROOT / ".tau/extensions/backoffice_policy/extension.py"
    )
    extension = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extension)
    monkeypatch.setattr(extension, "current_requester", lambda: None)
    hooks, tools = {}, []
    extension.setup(
        SimpleNamespace(on=lambda n, h: hooks.setdefault(n, h), register_tool=tools.append)
    )
    assert {t.name for t in tools} == {"backoffice_api__list_tools", "backoffice_api__call_tool"}
    call = ToolCallHookEvent("backoffice_api__call_tool", {"tool": "create_case"})
    assert asyncio.run(hooks["tool_call"](call, None)).block  # Not discovered yet.
    listing = ToolCallHookEvent("backoffice_api__list_tools", {})
    assert not asyncio.run(hooks["tool_call"](listing, None)).block
    # Verification never fabricates a platform turn requester.
    assert extension.current_requester() is None
    configured["data_source_uid"] = str(uuid4())
    assert asyncio.run(hooks["tool_call"](listing, None)).block


def test_native_mcp_adapter_checks_contract_closes_sessions_and_never_replays_mutations(
    configured, monkeypatch
):
    calls, closed = [], []
    catalog = [
        types.Tool(
            name=name,
            input_schema=spec["inputSchema"],
            annotations=types.ToolAnnotations.model_validate(spec["annotations"]),
        )
        for name, spec in load_contract()["tools"].items()
    ]

    class Client:
        tools = catalog
        fail = False

        async def call_tool(self, name, arguments, **kwargs):
            calls.append(name)
            if self.fail:
                raise TimeoutError("private provider credentials")
            return types.CallToolResult(content=[types.TextContent(type="text", text="verified")])

        async def aclose(self):
            closed.append(True)

    client = Client()

    async def connect(self):
        await self.verify()
        return client

    monkeypatch.setattr(local_mcp.LocalMCP, "connect", connect)
    bridge = local_mcp.LocalMCP.from_environment()
    listing, caller = bridge.tools()
    result = asyncio.run(listing.execute("list", {}))
    assert not result.details["is_error"]
    assert len(json.loads(result.content[0].text.split("\n", 1)[1])) == 35
    client.fail = True
    result = asyncio.run(
        caller.execute("write", {"tool": "create_case", "arguments": {"command": {}}})
    )
    assert result.details["is_error"] and "private" not in result.content[0].text
    assert calls == ["create_case"] and len(closed) == 2
    client.tools = []
    asyncio.run(caller.execute("drift", {"tool": "create_case", "arguments": {}}))
    assert calls == ["create_case"]  # No write on drifted catalog.


@pytest.mark.parametrize("active,blocked", [(False, False), (True, True)])
def test_inactive_or_blocked_developer_cannot_supply_authority(monkeypatch, active, blocked):
    from mainsequence.client import User

    from scripts import developer_session

    monkeypatch.setattr(developer_session, "configure_developer_session", lambda: None)
    monkeypatch.setattr(
        User,
        "get_authenticated_user_details",
        lambda: SimpleNamespace(
            uid=UID,
            is_active=active,
            blocked_access=blocked,
        ),
    )
    with pytest.raises(local_mcp.LocalMCPUnavailable):
        local_mcp.developer_uid()

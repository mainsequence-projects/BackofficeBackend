"""Agent boundaries exercised with native Tau hooks and actual MCP discovery."""

import asyncio
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from tau_agent.messages import TextContent
from tau_agent.tools import AgentToolResult
from tau_coding.extensions.api import ToolCallHookEvent, ToolResultHookEvent

from scripts.check_agent_contract import candidate_contract
from src.backoffice_agent.policy import (
    ALLOWED_TOOLS,
    APPLICATION,
    call_denial,
    load_contract,
    validate_catalog,
)

ROOT = Path(__file__).resolve().parents[2]


def entries():
    return [
        {
            "name": name,
            "inputSchema": spec["inputSchema"],
            "readOnly": spec["annotations"]["readOnlyHint"],
        }
        for name, spec in load_contract()["tools"].items()
    ]


def test_actual_api_catalog_matches_versioned_contract():
    assert asyncio.run(candidate_contract()) == load_contract()["tools"]


def test_catalog_filters_extra_tools_and_refuses_missing_mutable_or_changed_tools():
    extra = {"name": "delete_person", "inputSchema": {}, "readOnly": False}
    assert len(validate_catalog(entries() + [extra])) == len(ALLOWED_TOOLS)
    for change in ("missing", "mutable", "schema", "duplicate"):
        modified = deepcopy(entries())
        if change == "missing":
            modified.pop()
        elif change == "mutable":
            modified[0]["readOnly"] = not modified[0]["readOnly"]
        elif change == "schema":
            modified[0]["inputSchema"] = {}
        else:
            modified.append(modified[0])
        with pytest.raises(ValueError):
            validate_catalog(modified)


@pytest.mark.parametrize(
    "name",
    [
        "bash",
        "read",
        "write",
        "edit",
        "http_request",
        "mainsequence__call_tool",
        "other_api__call_tool",
        "backoffice_api__read_resource",
    ],
)
def test_non_business_routes_cannot_execute(name):
    assert call_denial(name, {}, requester_present=True, catalog_verified=True)


@pytest.mark.parametrize(
    "business_tool", ["get_person", "create_case", "evaluate_case", "process_source_document"]
)
def test_requester_and_discovery_required_even_for_known_query(business_tool):
    args = {"tool": business_tool, "arguments": {"person_uid": "arbitrary"}}
    name = f"{APPLICATION}__call_tool"
    assert call_denial(name, args, requester_present=False, catalog_verified=True)
    assert call_denial(name, args, requester_present=True, catalog_verified=False)
    assert call_denial(
        name, {"tool": "review_document"}, requester_present=True, catalog_verified=True
    )
    assert call_denial(name, {"tool": []}, requester_present=True, catalog_verified=True)
    assert call_denial(name, args, requester_present=True, catalog_verified=True) is None


def test_native_hook_discovery_then_call_and_failed_rediscovery(monkeypatch):
    path = ROOT / ".tau/extensions/backoffice_policy/extension.py"
    spec = importlib.util.spec_from_file_location("backoffice_policy_test", path)
    extension = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extension)
    requester = [object()]
    monkeypatch.setattr(extension, "current_requester", lambda: requester[0])
    hooks = {}
    extension.setup(SimpleNamespace(on=lambda name, handler: hooks.setdefault(name, handler)))
    call = ToolCallHookEvent(f"{APPLICATION}__call_tool", {"tool": "get_person"})
    assert hooks["tool_call"](call, None).block
    listing = ToolCallHookEvent(f"{APPLICATION}__list_tools", {})
    assert not hooks["tool_call"](listing, None).block
    result = AgentToolResult(
        content=[
            TextContent(
                text="SDK introduction\n"
                + json.dumps(
                    entries() + [{"name": "delete_person", "inputSchema": {}, "readOnly": False}]
                )
            )
        ],
        details={"is_error": False},
    )
    event = ToolResultHookEvent(listing.tool_name, {}, result)
    filtered = hooks["tool_result"](event, None)
    assert set(filtered.details["tools"]) == ALLOWED_TOOLS
    assert "delete_person" not in filtered.content
    assert not hooks["tool_call"](call, None).block
    requester[0] = None
    assert hooks["tool_call"](call, None).block
    requester[0] = object()
    hooks["tool_call"](listing, None)
    result.content = [TextContent(text="malformed catalog")]
    assert hooks["tool_result"](event, None).details["is_error"]
    assert hooks["tool_call"](call, None).block
    # SDK task controls do not grant data access and retain SDK authorization checks.
    assert not hooks["tool_call"](ToolCallHookEvent("task_request_input", {}), None).block


def test_entrypoint_excludes_default_tools_and_retains_identity(monkeypatch):
    monkeypatch.setenv("TAU_EXCLUDE_BASE_TOOLS", "false")
    monkeypatch.setenv("TAU_EXCLUDE_MAINSEQUENCE_MCP", "false")
    from api.tau.main import app

    assert app.state.mainsequence_request_identity["installed"]
    # The SDK stores resolved settings on startup; constructor behavior is also
    # tested directly without creating a session or requesting credentials.
    from ms_tau_sdk import TauSDKSettings

    settings = TauSDKSettings(exclude_base_tools=True, exclude_mainsequence_mcp=True)
    assert settings.exclude_base_tools and settings.exclude_mainsequence_mcp


def test_release_dependency_graph_and_restricted_resource_grants():
    workflow = yaml.safe_load((ROOT / ".mainsequence/workflows/backoffice.yaml").read_text())
    resources = {item["key"]: item for item in workflow["resources"]}
    agent = resources["backoffice_helper"]
    assert agent["acts_for_requester"] is True
    assert agent["access"] == {"resources": [{"key": "backoffice_api", "policy": "viewer"}]}
    assert agent["spec"]["mcp_applications"] == [{"resource": "backoffice_api"}]
    assert {x["name"]: x["value"] for x in agent["spec"]["env_vars"]} == {
        "TAU_EXCLUDE_BASE_TOOLS": "true",
        "TAU_EXCLUDE_MAINSEQUENCE_MCP": "true",
    }
    steps = workflow["execution"]["steps"]
    assert steps["deploy_api"]["needs"] == ["migrate"]
    assert not steps["agent_image"].get("needs")
    assert steps["deploy_agent"]["needs"] == ["deploy_api", "agent_image"]
    assert steps["deploy_agent"]["image_from"] == "agent_image"
    assert resources["extract-backoffice-document"]["spec"]["automatic_redeployment"]["enabled"]
    card = json.loads((ROOT / ".agents/agent_card.json").read_text())
    assert all((ROOT / skill["path"]).is_file() for skill in card["skills"])


def test_tau_loads_policy_and_blocks_execution_before_tool_body(tmp_path):
    from tau_agent.tools import AgentTool
    from tau_ai.fake import FakeProvider
    from tau_coding import CodingSession, CodingSessionConfig
    from tau_coding.resources import TauResourcePaths

    class MemoryStorage:
        async def read_all(self):
            return []

        async def append(self, entry):
            pass

    async def run():
        executed = []

        async def forbidden(tool_call_id, arguments, signal=None, on_update=None):
            executed.append(True)
            return AgentToolResult(content=[TextContent(text="should not execute")])

        session = await CodingSession.load(
            CodingSessionConfig(
                provider=FakeProvider([]),
                provider_name="fake",
                model="fake-model",
                storage=MemoryStorage(),
                cwd=ROOT,
                tools=[
                    AgentTool(
                        name="bash",
                        label="Forbidden",
                        description="Must be blocked",
                        parameters={"type": "object", "properties": {}},
                        execute_fn=forbidden,
                    )
                ],
                resource_paths=TauResourcePaths(root=tmp_path / "tau", cwd=ROOT, agents_root=None),
                project_extensions_enabled=True,
                trust_override="approve",
                defer_authoritative_writes=True,
            )
        )
        try:
            assert "backoffice_policy" in session.extension_names
            assert not any(d.severity == "error" for d in session.extension_runtime.diagnostics)
            result = await session.tools[0].execute("blocked-call", {})
            assert not executed
            assert "Back Office" in result.content[0].text
        finally:
            await session.aclose()

    asyncio.run(run())

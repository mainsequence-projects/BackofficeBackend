"""Enforce the business allowlist using supported Tau hooks, without adding tools."""

import json
from pathlib import Path

from ms_tau_sdk import current_requester
from tau_coding.extensions.api import ToolCallHookResult, ToolResultHookResult

from src.backoffice_agent.local_mcp import LocalMCP
from src.backoffice_agent.policy import APPLICATION, call_denial, load_contract, validate_catalog


def setup(tau):
    contract = load_contract()
    project_root = Path(__file__).resolve().parents[3]
    verified = False
    local = LocalMCP.from_environment()
    if local is not None:
        for tool in local.tools():
            tau.register_tool(tool)

    async def local_before_call(event):
        nonlocal verified
        try:
            await local.verify()
        except Exception:
            verified = False
            return ToolCallHookResult(
                block=True,
                reason="The authenticated local developer, API identity or pinned SQLite source could not be verified.",
            )
        return decision(event, requester_present=True)

    def before_call(event, context):
        if local is not None and event.tool_name in {
            f"{APPLICATION}__list_tools",
            f"{APPLICATION}__call_tool",
        }:
            return local_before_call(event)
        return decision(event, requester_present=current_requester() is not None)

    def decision(event, *, requester_present):
        nonlocal verified
        denial = call_denial(
            event.tool_name,
            event.arguments,
            requester_present=requester_present,
            catalog_verified=verified,
            project_root=project_root,
        )
        if event.tool_name == f"{APPLICATION}__list_tools":
            verified = False
        return ToolCallHookResult(block=denial is not None, reason=denial)

    def after_result(event, context):
        nonlocal verified
        if event.tool_name != f"{APPLICATION}__list_tools":
            return None
        verified = False
        try:
            if event.result.details.get("is_error"):
                raise ValueError("MCP discovery failed")
            # The pinned SDK projects list_tools as a text introduction followed by JSON.
            text = event.result.content[0].text
            entries = json.loads(text.split("\n", 1)[1])
            selected = validate_catalog(entries, contract)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return ToolResultHookResult(
                content="Back Office MCP discovery or contract verification failed. Business tools are blocked.",
                details={"is_error": True, "failure": "mcp_contract_unavailable"},
            )
        verified = True
        return ToolResultHookResult(
            content=json.dumps(selected, sort_keys=True),
            details={
                "application": APPLICATION,
                "is_error": False,
                "tools": [entry["name"] for entry in selected],
                "contract_sha256": contract["sha256"],
            },
        )

    tau.on("tool_call", before_call)
    tau.on("tool_result", after_result)

"""Enforce the business allowlist using supported Tau hooks, without adding tools."""

import json

from ms_tau_sdk import current_requester
from tau_coding.extensions.api import ToolCallHookResult, ToolResultHookResult

from src.backoffice_agent.policy import APPLICATION, call_denial, load_contract, validate_catalog


def setup(tau):
    contract = load_contract()
    verified = False

    def before_call(event, context):
        nonlocal verified
        denial = call_denial(
            event.tool_name,
            event.arguments,
            requester_present=current_requester() is not None,
            catalog_verified=verified,
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
                content="Back Office MCP discovery or contract verification failed. Queries are blocked.",
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

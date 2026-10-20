"""Explicit local developer MCP transport; hosted delegation remains SDK-owned.

The loopback API verifies the saved developer login. This adapter verifies that
same login and the pinned SQLite source before every call. It never supplies a
requester, handles a token, or exposes HTTP as a model-facing tool.
"""

import asyncio
import json
import os
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import httpx2
import structlog
from ms_tau_sdk.backend.mcp import MCPConnectionClient
from ms_tau_sdk.tools.mcp_connection import declared_timeout, mcp_tool_result
from tau_agent.messages import TextContent
from tau_agent.tools import AgentTool, AgentToolResult

from .policy import ALLOWED_TOOLS, APPLICATION, validate_catalog

logger = structlog.get_logger(__name__)


class LocalMCPUnavailable(PermissionError):
    """The explicit developer boundary could not be verified."""


def developer_uid():
    from mainsequence.client import User

    from scripts.developer_session import configure_developer_session

    configure_developer_session()
    user = User.get_authenticated_user_details()
    if user.is_active is not True or user.blocked_access is True:
        raise LocalMCPUnavailable("The developer login is unavailable.")
    return str(UUID(str(user.uid)))


@dataclass
class LocalMCP:
    origin: str
    source_uid: str
    principal_uid: str | None = None

    @classmethod
    def from_environment(cls):
        if os.environ.get("BACKOFFICE_LOCAL_MCP_ENABLED", "false").lower() != "true":
            return None
        if (
            any(
                os.environ.get(key)
                for key in (
                    "APP_NAME",
                    "FASTAPI_PUBLIC_BASE_URL",
                    "MAINSEQUENCE_CALLER_ASSERTION_ISSUER",
                    "MAINSEQUENCE_CALLER_ASSERTION_JWKS_URL",
                )
            )
            or os.environ.get("MAINSEQUENCE_CALLER_AUTH_MODE") == "assertion"
            or any(
                os.environ.get(key, "").lower() != "true"
                for key in (
                    "TAU_LOCAL_MODE",
                    "TAU_EXCLUDE_BASE_TOOLS",
                    "TAU_EXCLUDE_MAINSEQUENCE_MCP",
                )
            )
            or os.environ.get("MAINSEQUENCE_TAU_HOST") not in {"127.0.0.1", "::1"}
        ):
            raise ValueError("Local MCP requires the restricted loopback developer runtime.")
        origin = os.environ.get("BACKOFFICE_API_ORIGIN", "")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or not parsed.port
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Local MCP requires an exact loopback API origin with a port.")
        return cls(origin, str(UUID(os.environ["BACKOFFICE_LOCAL_SOURCE_UID"])))

    async def verify(self):
        uid = await asyncio.to_thread(developer_uid)
        async with httpx.AsyncClient(timeout=15, follow_redirects=False, trust_env=False) as client:
            health = await client.get(self.origin + "/healthz")
            health.raise_for_status()
            identity = await client.get(self.origin + "/me")
            identity.raise_for_status()
        if health.json().get("metatables") != {
            "local_mode": True,
            "dialect": "sqlite",
            "data_source_uid": self.source_uid,
        }:
            raise LocalMCPUnavailable("The local API's test database changed.")
        if identity.json().get("user_uid") != uid or self.principal_uid not in {None, uid}:
            raise LocalMCPUnavailable(
                "The local API and this conversation have different developers."
            )
        self.principal_uid = uid

    async def connect(self):
        await self.verify()
        return await MCPConnectionClient(
            name=APPLICATION,
            display_name="Back Office local developer API",
            url=self.origin + "/mcp",
            auth=None,
            timeout=httpx2.Timeout(60, connect=10),
            read_timeout_seconds=60,
            read_concurrency=1,
            mode="auto",
        ).open()

    def tools(self):
        def failed():
            return AgentToolResult(
                content=[
                    TextContent(
                        text="The authenticated local Back Office MCP connection is unavailable. Recheck the developer login, API identity and pinned test database."
                    )
                ],
                details={"is_error": True, "failure": "local_mcp_unavailable"},
            )

        async def list_tools(tool_call_id, arguments, signal=None, on_update=None):
            if signal is not None and signal.is_cancelled():
                return failed()
            try:
                client = await self.connect()
                try:
                    entries = [
                        {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema,
                            "readOnly": t.annotations.read_only_hint if t.annotations else None,
                        }
                        for t in client.tools
                    ]
                    entries = validate_catalog(entries)
                finally:
                    await client.aclose()
            except Exception as exc:
                logger.warning(
                    "backoffice.local_mcp.failed",
                    operation="list_tools",
                    error_type=type(exc).__name__,
                )
                return failed()
            return AgentToolResult(
                content=[
                    TextContent(
                        text="Authenticated local Back Office tools.\n" + json.dumps(entries)
                    )
                ],
                details={"is_error": False, "application": APPLICATION},
            )

        async def call_tool(tool_call_id, arguments, signal=None, on_update=None):
            name, inputs = arguments.get("tool"), arguments.get("arguments", {})
            if (
                not isinstance(name, str)
                or name not in ALLOWED_TOOLS
                or not isinstance(inputs, dict)
            ):
                return failed()
            if signal is not None and signal.is_cancelled():
                return failed()
            try:
                client = await self.connect()
                try:
                    # Recheck drift after discovery; never send a mutation to an unreviewed API.
                    validate_catalog(
                        [
                            {
                                "name": t.name,
                                "inputSchema": t.input_schema,
                                "readOnly": t.annotations.read_only_hint if t.annotations else None,
                            }
                            for t in client.tools
                        ]
                    )
                    tool = next(t for t in client.tools if t.name == name)
                    timeout = (
                        declared_timeout(tool, invalid_event="backoffice.local.invalid_timeout")
                        or 120
                    )
                    result = await client.call_tool(name, inputs, timeout_seconds=timeout)
                finally:
                    await client.aclose()
            except Exception as exc:
                logger.warning(
                    "backoffice.local_mcp.failed",
                    operation="call_tool",
                    error_type=type(exc).__name__,
                )
                # SDK owns cancellation and protocol validation; never replay uncertain writes.
                return failed()
            return mcp_tool_result(canonical_name=name, result=result, display_name=APPLICATION)

        return [
            AgentTool(
                name=f"{APPLICATION}__list_tools",
                label="List Back Office tools",
                description="Discover the authenticated local Back Office API tools before doing case work.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                execute_fn=list_tools,
            ),
            AgentTool(
                name=f"{APPLICATION}__call_tool",
                label="Call a Back Office tool",
                description="Call one discovered and approved Back Office tool for the verified local developer.",
                parameters={
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool"],
                    "additionalProperties": False,
                },
                execute_fn=call_tool,
            ),
        ]

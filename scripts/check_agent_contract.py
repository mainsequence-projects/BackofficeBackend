"""Offline release gate: compare candidate API MCP contracts with the pinned agent."""

import asyncio
import json
from pathlib import Path

from api.app.mcp.server import create_mcp
from src.backoffice_agent.policy import ALLOWED_TOOLS, SKILL_FILES, digest, load_contract


async def candidate_contract():
    def no_business_calls():
        raise RuntimeError("Contract discovery must not query business storage")

    tools = await create_mcp(no_business_calls).list_tools()
    return {
        tool.name: {
            "inputSchema": tool.input_schema,
            "outputSchema": tool.output_schema,
            "annotations": tool.annotations.model_dump(mode="json", by_alias=True),
        }
        for tool in tools
        if tool.name in ALLOWED_TOOLS
    }


def main():
    actual = asyncio.run(candidate_contract())
    expected = load_contract()
    if actual != expected["tools"]:
        raise SystemExit(
            "Back Office API/agent MCP contract mismatch; review and version the contract."
        )
    # Verify packaged runtime policy is present before an automatic deployment.
    root = Path(__file__).resolve().parents[1]
    for path in (
        ".tau/SYSTEM.md",
        ".tau/extensions/backoffice_policy/extension.py",
        ".agents/agent_card.json",
        "api/tau/main.py",
        *SKILL_FILES,
    ):
        if not (root / path).is_file():
            raise SystemExit(f"Missing agent artifact: {path}")
    print(json.dumps({"status": "passed", "tools": len(actual), "sha256": digest(actual)}))


if __name__ == "__main__":
    main()

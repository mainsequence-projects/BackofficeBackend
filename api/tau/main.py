"""SDK-owned runtime with coding tools and platform MCP disabled by construction."""

from ms_tau_sdk import TauSDKSettings, create_app

# Explicit constructor values also protect local launches from unsafe flag overrides.
app = create_app(TauSDKSettings(exclude_base_tools=True, exclude_mainsequence_mcp=True))

"""Versioned, read-only application MCP boundary for Tau's native hooks."""

import hashlib
import json
from pathlib import Path

APPLICATION = "backoffice_api"
ALLOWED_TOOLS = frozenset(
    {
        "get_current_user",
        "search_persons",
        "get_person",
        "get_person_schema",
        "list_document_sets",
        "get_document_set",
        "list_person_assignments",
        "get_assignment",
        "get_document_set_status",
        "get_missing_requirements",
    }
)
TASK_CONTROLS = frozenset({"task_request_input", "task_request_authorization"})
CONTRACT_PATH = Path(__file__).with_name("mcp_contract.json")
SKILL_FILES = (
    ".agents/skills/backoffice-helper/SKILL.md",
    ".tau/skills/backoffice-casework/SKILL.md",
    ".tau/skills/backoffice-casework/references/ontology.md",
    ".tau/skills/backoffice-casework/references/build-case.md",
)


def approved_skill_read(arguments, project_root):
    """Permit only release-owned guidance, never arbitrary discovered skill files."""
    path = arguments.get("path")
    if not isinstance(path, str) or not path or project_root is None:
        return False
    try:
        root = Path(project_root).resolve(strict=True)
        resolved = (root / path).resolve(strict=True)
        # Do not resolve the allowlist itself: symlinks out of these exact paths fail closed.
        return resolved in {root / relative for relative in SKILL_FILES} and resolved.is_file()
    except (OSError, RuntimeError, ValueError):
        return False


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_contract():
    contract = json.loads(CONTRACT_PATH.read_text())
    if set(contract["tools"]) != ALLOWED_TOOLS:
        raise ValueError("Agent contract does not match the approved tool allowlist")
    if digest(contract["tools"]) != contract["sha256"]:
        raise ValueError("Agent contract checksum mismatch")
    return contract


def validate_catalog(entries, contract=None):
    """Accept extra server tools without exposing them; reject drift in approved tools."""
    expected = (contract or load_contract())["tools"]
    selected = {}
    for entry in entries:
        name = entry.get("name")
        if name not in ALLOWED_TOOLS:
            continue
        if name in selected:
            raise ValueError("Duplicate approved MCP tool")
        if entry.get("readOnly") is not True:
            raise ValueError("Approved MCP tool is not declared read-only")
        if entry.get("inputSchema") != expected[name]["inputSchema"]:
            raise ValueError("Approved MCP input contract changed")
        selected[name] = entry
    if set(selected) != ALLOWED_TOOLS:
        raise ValueError("Required Back Office MCP tools are unavailable")
    return [selected[name] for name in sorted(selected)]


def call_denial(name, arguments, *, requester_present, catalog_verified, project_root=None):
    if name in TASK_CONTROLS:
        return None
    if name == "read" and approved_skill_read(arguments, project_root):
        # Static guidance contains no business data and does not authorize MCP calls.
        return None
    if name not in {f"{APPLICATION}__list_tools", f"{APPLICATION}__call_tool"}:
        return "Only the Back Office MCP query tools are available for business work."
    if not requester_present:
        return "A verified requester is required; workload-identity fallback is disabled."
    if name.endswith("__call_tool"):
        tool = arguments.get("tool")
        if not isinstance(tool, str) or tool not in ALLOWED_TOOLS:
            return "This business tool is outside the Back Office helper's read-only allowlist."
        if not catalog_verified:
            return "List the Back Office MCP tools successfully before calling a query."
    return None

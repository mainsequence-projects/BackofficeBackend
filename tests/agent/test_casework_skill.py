"""Load the shipped skill through Tau while keeping all business boundaries intact."""

import asyncio
from pathlib import Path

import pytest
from ms_tau_sdk.tools.skill_read import create_skill_read_tool
from tau_ai.fake import FakeProvider
from tau_coding import CodingSession, CodingSessionConfig
from tau_coding.resources import TauResourcePaths
from tau_coding.skills import load_skills

from src.backoffice_agent.policy import SKILL_FILES, approved_skill_read, call_denial

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("relative", SKILL_FILES)
def test_only_shipped_guidance_is_allowed_even_before_business_discovery(relative):
    for path in (relative, str(ROOT / relative)):
        assert (
            call_denial(
                "read",
                {"path": path},
                requester_present=False,
                catalog_verified=False,
                project_root=ROOT,
            )
            is None
        )
    # Learning the workflow cannot confer requester authority or bypass discovery.
    for requester, discovered in ((False, True), (True, False)):
        assert call_denial(
            "backoffice_api__call_tool",
            {"tool": "get_assignment"},
            requester_present=requester,
            catalog_verified=discovered,
            project_root=ROOT,
        )
    for name in ("create_case", "evaluate_case", "assign_reviewer"):
        assert call_denial(
            "backoffice_api__call_tool",
            {"tool": name},
            requester_present=True,
            catalog_verified=True,
            project_root=ROOT,
        )


@pytest.mark.parametrize(
    "path",
    [
        None,
        [],
        "",
        ".env",
        "docs/cases.md",
        ".tau/SYSTEM.md",
        ".tau/extensions/backoffice_policy/extension.py",
        ".tau/skills/backoffice-casework/../../../.env",
        ".agents/skills/ms_tau_sdk/tau_project_customization/SKILL.md",
        "https://example.com/SKILL.md",
    ],
)
def test_read_cannot_expand_into_workspace_or_development_skills(path):
    assert call_denial(
        "read",
        {"path": path},
        requester_present=True,
        catalog_verified=True,
        project_root=ROOT,
    )


def test_symlinks_cannot_turn_an_approved_skill_path_into_a_secret(tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("not agent guidance")
    project = tmp_path / "project"
    skill = project / SKILL_FILES[1]
    skill.parent.mkdir(parents=True)
    skill.symlink_to(outside)
    assert not approved_skill_read({"path": SKILL_FILES[1]}, project)
    skill.unlink()
    skill.write_text("approved guidance")
    assert approved_skill_read({"path": SKILL_FILES[1]}, project)
    # Extra files inside the skill folder do not inherit permission.
    extra = skill.parent / "private.txt"
    extra.write_text("not shipped guidance")
    assert not approved_skill_read({"path": str(extra)}, project)


def test_installed_tau_discovers_skill_and_sdk_read_runs_through_project_hooks(tmp_path):
    paths = TauResourcePaths(root=tmp_path / "tau", cwd=ROOT, agents_root=None)
    skills = load_skills(paths)
    skill = next(s for s in skills if s.name == "backoffice-casework")
    assert skill.path == ROOT / ".tau/skills/backoffice-casework/SKILL.md"
    assert not skill.disable_model_invocation

    class MemoryStorage:
        async def read_all(self):
            return []

        async def append(self, entry):
            pass

    async def run():
        reader = create_skill_read_tool(cwd=ROOT, skills=lambda: skills)
        session = await CodingSession.load(
            CodingSessionConfig(
                provider=FakeProvider([]),
                provider_name="fake",
                model="fake-model",
                storage=MemoryStorage(),
                cwd=ROOT,
                tools=[reader],
                resource_paths=paths,
                project_extensions_enabled=True,
                trust_override="approve",
                defer_authoritative_writes=True,
            )
        )
        try:
            assert "backoffice_policy" in session.extension_names
            assert not any(d.severity == "error" for d in session.extension_runtime.diagnostics)
            tool = next(t for t in session.tools if t.name == "read")
            for relative in SKILL_FILES:
                result = await tool.execute("skill-read", {"path": relative})
                # Real SDK reader returns file contents rather than a policy denial.
                assert (ROOT / relative).read_text().splitlines()[-1] in result.content[0].text
            for relative in (
                ".env",
                "docs/cases.md",
                ".agents/skills/ms_tau_sdk/tau_project_customization/SKILL.md",
            ):
                result = await tool.execute("blocked-read", {"path": relative})
                assert "Only the Back Office MCP query tools" in result.content[0].text
        finally:
            await session.aclose()

    asyncio.run(run())

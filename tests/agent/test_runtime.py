"""Regression for an authorized selection disagreeing with replayed Tau history."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from ms_tau_sdk.errors import BackendConflictError, ConfigurationError
from ms_tau_sdk.runtime.manager import SessionRuntimeManager
from tau_agent.messages import AssistantMessage
from tau_agent.session import ModelChangeEntry
from tau_ai.events import AssistantDoneEvent
from tau_ai.fake import FakeProvider
from tau_coding import CodingSession, CodingSessionConfig
from tau_coding.paths import TauPaths
from tau_coding.resources import TauResourcePaths

from src.backoffice_agent.runtime import SelectedModelRuntime


def test_resumed_history_cannot_override_the_authorized_model(tmp_path, monkeypatch):
    class MemoryStorage:
        def __init__(self):
            self.entries = [ModelChangeEntry(model="gpt-5.5", provider="openai-codex")]

        async def read_all(self):
            return self.entries.copy()

        async def append(self, entry):
            self.entries.append(entry)

    async def run():
        storage = MemoryStorage()
        original = storage.entries.copy()
        provider = FakeProvider(
            [[AssistantDoneEvent(reason="stop", message=AssistantMessage(content="OK"))]]
        )
        session = await CodingSession.load(
            CodingSessionConfig(
                provider=provider,
                provider_name="openai-codex",
                model="gpt-5.6-luna",
                storage=storage,
                cwd=tmp_path,
                tools=[],
                resource_paths=TauResourcePaths(
                    root=tmp_path / "tau",
                    cwd=tmp_path,
                    agents_root=None,
                    paths=TauPaths(home=tmp_path / "tau", agents_home=tmp_path / "agents"),
                ),
                trust_override="approve",
                defer_authoritative_writes=True,
            )
        )
        try:
            assert session.model == "gpt-5.5"  # The actual pinned Tau replay defect.
            runtime = SimpleNamespace(
                coding_session=session,
                provider_name="openai-codex",
                model="gpt-5.6-luna",
                lock=asyncio.Lock(),
            )
            monkeypatch.setattr(SessionRuntimeManager, "get", AsyncMock(return_value=runtime))
            manager = object.__new__(SelectedModelRuntime)
            assert await manager.get("existing-session") is runtime
            assert session.model == "gpt-5.6-luna"
            assert storage.entries[: len(original)] == original
            async for _ in session.prompt("Reply briefly without tools."):
                pass
            assert provider.calls and provider.calls[0][0] == "gpt-5.6-luna"
        finally:
            await session.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,working", [("different-provider", False), ("openai-codex", True)]
)
def test_provider_mismatch_and_working_session_are_not_overridden(monkeypatch, provider, working):
    engine = SimpleNamespace(
        provider_name=provider, model="gpt-5.5", is_running=working, set_model=Mock()
    )
    runtime = SimpleNamespace(
        coding_session=engine,
        provider_name="openai-codex",
        model="gpt-5.6-luna",
        lock=asyncio.Lock(),
    )
    monkeypatch.setattr(SessionRuntimeManager, "get", AsyncMock(return_value=runtime))
    manager = object.__new__(SelectedModelRuntime)
    error = ConfigurationError if provider != "openai-codex" else BackendConflictError
    with pytest.raises(error):
        asyncio.run(manager.get("existing-session"))
    engine.set_model.assert_not_called()

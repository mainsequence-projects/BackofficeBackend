"""Discover the intended helper in the API's SDK-resolved branch and Environment."""

import json
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from mainsequence.client.agent_runtime_models import Agent
from mainsequence.client.exceptions import ApiError
from mainsequence.code_repository_context import (
    CodeRepositoryContextError,
    get_code_repository_context,
)
from pydantic import BaseModel, Field

AGENT_CARD = Path(__file__).resolve().parents[2] / ".agents/agent_card.json"


class AssistantContext(BaseModel):
    environmentUid: UUID = Field(
        description="The Back Office API's own Organization Environment UID."
    )
    agentUid: UUID = Field(
        description="The deployed Back Office helper Agent in this API's branch and Environment."
    )


def resolve_assistant_context() -> AssistantContext:
    try:
        context = get_code_repository_context()
        if (
            context.status != "resolved"
            or not context.code_repository_branch_uid
            or not context.organization_environment_uid
        ):
            raise HTTPException(503, "assistant_environment_unavailable")
        branch_uid = str(UUID(str(context.code_repository_branch_uid)))
        environment_uid = str(UUID(str(context.organization_environment_uid)))
        name = json.loads(AGENT_CARD.read_text())["name"]
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(503, "assistant_configuration_unavailable")
        # The SDK scopes this read to the process Environment. Check the owning
        # branch as well, since another branch can publish an identically named Agent.
        agents = [
            agent
            for agent in Agent.filter(name=name, timeout=(3.05, 10))
            if agent.code_repository_branch_uid == branch_uid
            and agent.organization_environment_uid == environment_uid
        ]
        if not agents:
            raise HTTPException(503, "assistant_agent_not_deployed")
        if len(agents) != 1:
            raise HTTPException(503, "assistant_agent_ambiguous")
        agent = agents[0]
        if not agent.runtime_release_uid:
            raise HTTPException(503, "assistant_agent_not_deployed")
        return AssistantContext(environmentUid=environment_uid, agentUid=UUID(str(agent.uid)))
    except CodeRepositoryContextError as error:
        raise HTTPException(503, "assistant_environment_unavailable") from error
    except ApiError as error:
        status = error.status_code if error.status_code in {401, 403, 429} else 503
        raise HTTPException(status, "assistant_discovery_unavailable") from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, "assistant_configuration_unavailable") from error

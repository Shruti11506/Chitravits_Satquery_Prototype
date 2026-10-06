"""Boundary between the input layer and the SatQuery agent.

The agent consumes exactly one type, :class:`~satquery.input.schemas.UserQuery`,
and returns an :class:`AgentResponse`. The orchestrator built in the next phase
(tool registry, VQA, grounding, change detection, optical+SAR, GIS) implements
:class:`Agent`; nothing in the input layer changes when it is swapped in.
"""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from satquery.input.schemas import UserQuery


class AgentStatus(StrEnum):
    RECEIVED = "received"  # accepted, not processed (placeholder behaviour)
    COMPLETED = "completed"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"


class AgentResponse(BaseModel):
    query_id: str
    session_id: str
    status: AgentStatus
    message: str
    data: dict[str, Any] = Field(
        default_factory=dict, description="Agent-specific payload (answers, evidence, ...)."
    )


class Agent(ABC):
    name: ClassVar[str]

    @abstractmethod
    async def process(self, user_query: UserQuery) -> AgentResponse:
        """Handle one normalised user query."""


class PlaceholderAgent(Agent):
    """Stand-in until the real orchestrator exists: acknowledges the query, runs no tools."""

    name = "placeholder"

    async def process(self, user_query: UserQuery) -> AgentResponse:
        return AgentResponse(
            query_id=user_query.query_id,
            session_id=user_query.session_id,
            status=AgentStatus.RECEIVED,
            message="UserQuery successfully normalized and is ready for the SatQuery agent.",
        )

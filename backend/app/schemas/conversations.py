"""Pydantic schemas for the conversations resource.

A conversation is what the sidebar lists. Its title is independent of any
uploaded file: it starts as "New Chat" and is only ever set from the user's
first meaningful query (title_source "auto") or an explicit rename ("user").
"""
from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.imagery import ImageryOut
from app.schemas.jobs import JobOut

DEFAULT_CONVERSATION_TITLE = "New Chat"


class TitleSource(str, Enum):
    DEFAULT = "default"  # still "New Chat"; eligible for one automatic title
    AUTO = "auto"  # generated from the first meaningful query; never regenerated
    USER = "user"  # manually renamed; never overwritten automatically


class ConversationOut(BaseModel):
    id: UUID
    title: str
    title_source: TitleSource
    # The project this chat belongs to (migration 0008); null for ordinary chats.
    project_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConversationCreate(BaseModel):
    """Optional body of POST /conversations: start the chat inside a project."""

    project_id: UUID | None = None


class ConversationRename(BaseModel):
    # Emptiness/whitespace is checked in the service so it maps to INVALID_TITLE.
    title: str = Field(..., max_length=120)


class ConversationDetail(ConversationOut):
    imagery: list[ImageryOut]
    jobs: list[JobOut]


class ConversationDeleteResponse(BaseModel):
    id: UUID
    status: str = "deleted"

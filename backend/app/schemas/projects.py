"""Pydantic schemas for projects: workspaces grouping chats, knowledge files and instructions.

Every count and date here is computed from database rows (see project_service);
nothing is stored as a denormalised counter that could drift.
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.conversations import ConversationOut


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Emptiness/whitespace is checked in the service so it maps to INVALID_PROJECT_NAME.
    name: str = Field(..., max_length=120)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    custom_instructions: str | None = Field(default=None, max_length=8000)


class ProjectUpdate(BaseModel):
    """Only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    icon: str | None = Field(default=None, max_length=16)
    color: str | None = Field(default=None, max_length=16)
    custom_instructions: str | None = Field(default=None, max_length=8000)


class ProjectOut(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    custom_instructions: str | None = None
    has_custom_instructions: bool = False
    # Started chats in this project (same rule as the sidebar: an upload or a query).
    chat_count: int = 0
    # Knowledge files uploaded to the project + images uploaded in its chats.
    file_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProjectFileOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    mime_type: str | None = None
    file_size: int | None = None
    created_at: datetime | None = None
    url: str | None = Field(default=None, description="Freshly signed download URL (1 hour).")


class ProjectChatUpload(BaseModel):
    """An image uploaded in one of the project's chats (counted in file_count)."""

    imagery_id: UUID
    conversation_id: UUID
    conversation_title: str | None = None
    name: str
    file_size: int | None = None
    created_at: datetime | None = None


class ProjectDetail(ProjectOut):
    conversations: list[ConversationOut]
    files: list[ProjectFileOut]
    chat_uploads: list[ProjectChatUpload]


class ProjectDeleteResponse(BaseModel):
    id: UUID
    status: str = "deleted"

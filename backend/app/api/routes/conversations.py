"""Conversation endpoints -- what the sidebar lists.

Titles never come from uploaded filenames; see conversation_service.
"""
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.schemas.common import ApiResponse
from app.schemas.conversations import (
    ConversationCreate,
    ConversationDeleteResponse,
    ConversationDetail,
    ConversationOut,
    ConversationRename,
)
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.post(
    "",
    response_model=ApiResponse[ConversationOut],
    status_code=status.HTTP_201_CREATED,
    summary='Create a conversation titled "New Chat"',
)
def create_conversation(payload: ConversationCreate | None = None) -> ApiResponse[ConversationOut]:
    project_id = str(payload.project_id) if payload and payload.project_id else None
    return ApiResponse.ok(ConversationOut(**conversation_service.create_conversation(project_id)))


@router.get(
    "",
    response_model=ApiResponse[list[ConversationOut]],
    summary="List conversations, most recently active first",
)
def list_conversations(
    limit: int = Query(default=100, ge=1, le=200),
) -> ApiResponse[list[ConversationOut]]:
    rows = conversation_service.list_conversations(limit=limit)
    return ApiResponse.ok([ConversationOut(**row) for row in rows])


@router.get(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationDetail],
    summary="Get a conversation with its uploads and queries (oldest first)",
)
def get_conversation(conversation_id: UUID) -> ApiResponse[ConversationDetail]:
    return ApiResponse.ok(
        ConversationDetail(**conversation_service.get_conversation_detail(str(conversation_id)))
    )


@router.patch(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationOut],
    summary="Rename a conversation (marks the title as user-defined)",
)
def rename_conversation(
    conversation_id: UUID, payload: ConversationRename
) -> ApiResponse[ConversationOut]:
    row = conversation_service.rename_conversation(str(conversation_id), payload.title)
    return ApiResponse.ok(ConversationOut(**row))


@router.post(
    "/{conversation_id}/title",
    response_model=ApiResponse[ConversationOut],
    summary="Generate the automatic title from the first meaningful query (runs once)",
)
def generate_title(conversation_id: UUID) -> ApiResponse[ConversationOut]:
    return ApiResponse.ok(
        ConversationOut(**conversation_service.generate_title(str(conversation_id)))
    )


@router.delete(
    "/{conversation_id}",
    response_model=ApiResponse[ConversationDeleteResponse],
    summary="Delete a conversation with its queries and uploaded files",
)
def delete_conversation(conversation_id: UUID) -> ApiResponse[ConversationDeleteResponse]:
    conversation_service.delete_conversation(str(conversation_id))
    return ApiResponse.ok(ConversationDeleteResponse(id=conversation_id))

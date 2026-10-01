"""Request schema for POST /reports (the downloadable analysis report)."""
from uuid import UUID

from pydantic import BaseModel, Field


class ReportRequest(BaseModel):
    # Exactly one target: a conversation, or (for a legacy pre-conversation
    # chat) the image its queries ran on. Checked in report_service.
    conversation_id: UUID | None = None
    imagery_id: UUID | None = None
    # Name of the model attached in the workspace -- a browser-only setting,
    # shown as metadata only; it never supplies results.
    attached_model: str | None = Field(default=None, max_length=120)

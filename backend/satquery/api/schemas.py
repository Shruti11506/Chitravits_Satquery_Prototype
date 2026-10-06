"""HTTP request/response models for the versioned input API.

These describe the *wire* format. They are converted into a transport-neutral
``RawQueryInput`` and then normalised into ``UserQuery``; the agent never sees
these models.
"""

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from satquery.agent.interface import AgentResponse
from satquery.input.schemas import AttachmentRef, LanguageCode, Metadata, SessionId, UserQuery


class VoicePayload(BaseModel):
    """Inline audio for JSON clients (e.g. a browser MediaRecorder clip). Max 30 s."""

    model_config = ConfigDict(extra="forbid")

    audio_base64: str = Field(
        min_length=1,
        description="Base64-encoded audio. A data-URI prefix such as "
        "'data:audio/webm;codecs=opus;base64,' is accepted.",
    )
    content_type: str | None = Field(default=None, max_length=100, examples=["audio/wav"])
    filename: str | None = Field(default=None, max_length=255)


class QueryFields(BaseModel):
    """Fields shared by the JSON and multipart transports."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None,
        description="Typed query. Provide either text or voice.",
        examples=["What changed between these two satellite images?"],
    )
    language: LanguageCode | None = Field(
        default=None,
        description="ISO 639 code ('en', 'hi', 'mr', ...). For voice, omit to let STT auto-detect; "
        "for text, omitted means the server default.",
    )
    session_id: SessionId | None = Field(
        default=None, description="Conversation id. Omit on the first turn to have one generated."
    )
    attachments: list[AttachmentRef] = Field(
        default_factory=list,
        validation_alias=AliasChoices("attachments", "images"),
        description="References to stored imagery (alias: 'images'). Never raw raster data.",
    )
    metadata: Metadata = Field(default_factory=dict)

    @field_validator("attachments", "metadata", mode="before")
    @classmethod
    def _null_is_empty(cls, value: Any, info: Any) -> Any:
        if value is None:
            return [] if info.field_name == "attachments" else {}
        return value


class QueryRequest(QueryFields):
    """JSON body of ``POST /api/v1/query``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "text": "What changed between these images?",
                    "voice": None,
                    "images": [],
                    "language": "en",
                    "session_id": "abc123",
                }
            ]
        },
    )

    voice: VoicePayload | None = None


class QueryResponse(BaseModel):
    request_id: str | None = Field(description="Echo of the X-Request-ID header for tracing.")
    user_query: UserQuery = Field(description="The normalised query handed to the agent.")
    agent: AgentResponse


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str
    type: str | None = None


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody

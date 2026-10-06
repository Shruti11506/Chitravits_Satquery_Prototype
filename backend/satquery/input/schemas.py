"""The normalised ``UserQuery`` contract between the input layer and the agent.

``UserQuery`` is the *only* thing the agent receives. It is transport-neutral
(JSON vs multipart) and modality-neutral: a voice request has already been
transcribed into ``query`` by the time it gets here. ``input_type`` and
``provenance`` are informational (auditing, confidence handling) and the agent
must not need them to answer a question.

Large satellite rasters are never embedded: ``attachments`` holds references
(IDs / storage URIs) that later phases resolve through the storage layer.
"""

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, field_validator

from satquery.core.languages import normalize_language_code
from satquery.input.validators import (
    ATTACHMENT_ID_PATTERN,
    SENSOR_TYPE_PATTERN,
    parse_acquisition_time,
    validate_attachment_uri,
    validate_metadata,
    validate_session_id,
)

USER_QUERY_SCHEMA_VERSION = "1.0"

LanguageCode = Annotated[
    str,
    AfterValidator(normalize_language_code),
    Field(description="ISO 639 language code, e.g. 'en', 'hi', 'mr'. Regional tags like 'hi-IN' are accepted."),
]
SessionId = Annotated[
    str,
    AfterValidator(validate_session_id),
    Field(description="3-64 chars of letters, digits, '_' or '-'.", examples=["session_123"]),
]
Metadata = Annotated[
    dict[str, Any],
    AfterValidator(validate_metadata),
    Field(description="Free-form JSON object (max 32 keys, 8 KiB)."),
]


class InputType(StrEnum):
    """How the user expressed the query. Extensible for future modalities."""

    TEXT = "text"
    VOICE = "voice"


class LanguageSource(StrEnum):
    USER = "user"  # given explicitly in the request
    DETECTED = "detected"  # reported by speech-to-text
    DEFAULT = "default"  # server default (SATQUERY_DEFAULT_LANGUAGE)


class AttachmentKind(StrEnum):
    IMAGE = "image"  # optical / SAR / multispectral scene or tile
    VECTOR = "vector"  # e.g. an AOI polygon
    OTHER = "other"


class ImageModality(StrEnum):
    OPTICAL = "optical"
    MULTISPECTRAL = "multispectral"
    HYPERSPECTRAL = "hyperspectral"
    SAR = "sar"
    THERMAL = "thermal"
    ELEVATION = "elevation"
    OTHER = "other"


class TemporalRole(StrEnum):
    """Position of an image in a temporal comparison (e.g. change detection)."""

    BEFORE = "before"
    AFTER = "after"
    REFERENCE = "reference"


class AttachmentRef(BaseModel):
    """A reference to a stored file (typically a satellite scene), not the file itself."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "img_001",
                    "kind": "image",
                    "type": "sentinel-2",
                    "modality": "optical",
                    "timestamp": "2026-09-01",
                    "role": "before",
                    "uri": "s3://satquery-scenes/S2A_MSIL2A_20260901.tif",
                }
            ]
        },
    )

    id: str = Field(
        pattern=ATTACHMENT_ID_PATTERN,
        description="Storage-layer identifier of the uploaded/registered file.",
    )
    kind: AttachmentKind = AttachmentKind.IMAGE
    type: str | None = Field(
        default=None,
        pattern=SENSOR_TYPE_PATTERN,
        description="Sensor or product, lower-case, e.g. 'sentinel-1', 'sentinel-2', 'landsat-9'.",
    )
    modality: ImageModality | None = None
    timestamp: Annotated[date | datetime, BeforeValidator(parse_acquisition_time)] | None = Field(
        default=None, description="Acquisition date or datetime (ISO 8601)."
    )
    role: TemporalRole | None = None
    uri: Annotated[str, Field(max_length=2048), AfterValidator(validate_attachment_uri)] | None = Field(
        default=None,
        description="Optional storage location (s3://, gs://, az://, https://, satquery://).",
    )
    metadata: Metadata = Field(default_factory=dict)

    @field_validator("type", mode="before")
    @classmethod
    def _lowercase_type(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


class TranscriptionInfo(BaseModel):
    """How a voice query was transcribed. ``is_mock=true`` means no real STT API was called."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model: str | None = None
    is_mock: bool
    request_id: str | None = None
    language_probability: float | None = None
    audio_format: str | None = None
    audio_duration_seconds: float | None = None
    audio_size_bytes: int


class InputProvenance(BaseModel):
    """Where the normalised fields came from (for auditing; not needed to answer the query)."""

    model_config = ConfigDict(frozen=True)

    language_source: LanguageSource
    session_generated: bool = Field(description="True if the server created a new session_id.")
    transcription: TranscriptionInfo | None = None


class UserQuery(BaseModel):
    """The normalised request handed to the SatQuery agent."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        json_schema_extra={
            "examples": [
                {
                    "schema_version": "1.0",
                    "query_id": "q_3f2a9c0e8b1d4e6f9a7b5c3d1e0f2a4b",
                    "query": "What changed between these two satellite images?",
                    "input_type": "voice",
                    "language": "en",
                    "session_id": "session_123",
                    "attachments": [
                        {"id": "img_001", "type": "sentinel-2", "modality": "optical",
                         "timestamp": "2026-03-01", "role": "before"},
                        {"id": "img_002", "type": "sentinel-2", "modality": "optical",
                         "timestamp": "2026-09-01", "role": "after"},
                    ],
                    "metadata": {"aoi_name": "Pune"},
                    "provenance": {
                        "language_source": "detected",
                        "session_generated": False,
                        "transcription": {
                            "provider": "sarvam", "model": "saaras:v3", "is_mock": False,
                            "request_id": "20260923_abc", "language_probability": 0.98,
                            "audio_format": "wav", "audio_duration_seconds": 3.2,
                            "audio_size_bytes": 102444,
                        },
                    },
                    "received_at": "2026-09-23T10:15:00Z",
                }
            ]
        },
    )

    schema_version: Literal["1.0"] = USER_QUERY_SCHEMA_VERSION
    query_id: str = Field(default_factory=lambda: f"q_{uuid4().hex}")
    query: str = Field(min_length=1, description="Normalised query text the agent processes.")
    input_type: InputType
    language: LanguageCode
    session_id: SessionId
    attachments: tuple[AttachmentRef, ...] = ()
    metadata: Metadata = Field(default_factory=dict)
    provenance: InputProvenance
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("query")
    @classmethod
    def _query_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("attachments")
    @classmethod
    def _unique_attachment_ids(cls, value: tuple[AttachmentRef, ...]) -> tuple[AttachmentRef, ...]:
        seen: set[str] = set()
        for attachment in value:
            if attachment.id in seen:
                raise ValueError(f"duplicate attachment id '{attachment.id}'")
            seen.add(attachment.id)
        return value

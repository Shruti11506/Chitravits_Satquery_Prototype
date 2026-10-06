"""OpenAPI documentation for the dual-content-type ``POST /api/v1/query`` endpoint.

The endpoint parses its body manually (JSON *or* multipart), so FastAPI cannot
infer the request schema; it is declared here and registered as a component.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from satquery.api.schemas import ErrorResponse, QueryRequest

_REF_TEMPLATE = "#/components/schemas/{model}"

_MULTIPART_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Typed query. Provide either text or voice."},
        "voice": {
            "type": "string",
            "format": "binary",
            "description": "Audio clip under 30 s (wav, mp3, aac, aiff, ogg/opus, flac, m4a, webm, amr, wma).",
        },
        "language": {
            "type": "string",
            "description": "ISO 639 code ('en', 'hi', 'mr', ...). Omit for voice to auto-detect.",
        },
        "session_id": {"type": "string", "description": "Conversation id; omit to generate one."},
        "attachments": {
            "type": "string",
            "description": "JSON array of attachment references (alias field name: 'images').",
            "examples": ['[{"id": "img_001", "type": "sentinel-2", "modality": "optical"}]'],
        },
        "metadata": {"type": "string", "description": "JSON object of extra metadata."},
    },
}

_JSON_EXAMPLES: dict[str, Any] = {
    "text": {
        "summary": "Text query",
        "value": {
            "text": "What changed between these images?",
            "voice": None,
            "images": [],
            "language": "en",
            "session_id": "abc123",
        },
    },
    "text_with_images": {
        "summary": "Text query with a Sentinel-2 temporal pair",
        "value": {
            "text": "What changed between these two satellite images?",
            "session_id": "session_123",
            "attachments": [
                {"id": "img_001", "type": "sentinel-2", "modality": "optical",
                 "timestamp": "2026-03-01", "role": "before"},
                {"id": "img_002", "type": "sentinel-2", "modality": "optical",
                 "timestamp": "2026-09-01", "role": "after"},
            ],
        },
    },
    "voice_base64": {
        "summary": "Voice query as inline base64 (replace with real audio)",
        "value": {
            "voice": {"audio_base64": "UklGRi4AAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQoAAAAAAAAAAAAAAAAAAA==",
                      "content_type": "audio/wav"},
            "session_id": "session_123",
            "attachments": [{"id": "img_001", "type": "sentinel-1", "modality": "sar"}],
        },
    },
}

QUERY_OPENAPI_EXTRA: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "Send JSON for text (or inline base64 voice), or multipart/form-data "
        "to upload an audio file. Exactly one of `text` or `voice` is required.",
        "content": {
            "application/json": {
                "schema": {"$ref": _REF_TEMPLATE.format(model="QueryRequest")},
                "examples": _JSON_EXAMPLES,
            },
            "multipart/form-data": {"schema": _MULTIPART_SCHEMA},
        },
    }
}

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Body is not valid JSON / multipart, or is empty."},
    413: {"model": ErrorResponse, "description": "Request body or audio exceeds size limits."},
    415: {"model": ErrorResponse, "description": "Unsupported Content-Type or audio format."},
    422: {"model": ErrorResponse, "description": "Invalid input (missing/empty text or voice, "
          "bad language, session id, attachments, audio too long, empty transcript, ...)."},
    429: {"model": ErrorResponse, "description": "Speech provider rate limit/quota exceeded."},
    502: {"model": ErrorResponse, "description": "Speech provider failed or rejected credentials."},
    503: {"model": ErrorResponse, "description": "Speech-to-text not configured or unreachable."},
    504: {"model": ErrorResponse, "description": "Speech provider timed out."},
}


def install_openapi(app: FastAPI) -> None:
    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        request_schema = QueryRequest.model_json_schema(ref_template=_REF_TEMPLATE)
        for name, definition in request_schema.pop("$defs", {}).items():
            components.setdefault(name, definition)
        components["QueryRequest"] = request_schema
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

"""Parse ``POST /api/v1/query`` bodies (JSON or multipart) into a ``RawQueryInput``.

This is the only place that knows about HTTP content types. Everything it
returns is transport-neutral.
"""

import base64
import binascii
import json
import re
from typing import Any

from fastapi import Request
from pydantic import BaseModel, ValidationError
from starlette.datastructures import FormData, UploadFile

from satquery.api.schemas import QueryFields, QueryRequest, VoicePayload
from satquery.core.errors import (
    InputValidationError,
    MalformedRequestError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    validation_error_from_pydantic,
)
from satquery.input.normalizer import RawQueryInput
from satquery.speech.base import AudioInput

_FORM_TEXT_FIELDS = ("text", "language", "session_id")
_FORM_JSON_FIELDS: dict[str, type] = {"attachments": list, "images": list, "metadata": dict}
_FORM_FIELDS = frozenset({*_FORM_TEXT_FIELDS, *_FORM_JSON_FIELDS, "voice"})

_DATA_URI_PREFIX = re.compile(r"^data:([\w.+-]+/[\w.+-]+)?(?:;[\w.+-]+=[\w.+-]+)*;base64,", re.IGNORECASE)


async def parse_query_request(request: Request, *, max_audio_bytes: int) -> RawQueryInput:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type == "application/json" or media_type.endswith("+json"):
        return await _parse_json(request, max_audio_bytes)
    if media_type == "multipart/form-data":
        return await _parse_multipart(request, max_audio_bytes)
    raise UnsupportedMediaTypeError(
        f"Unsupported Content-Type '{media_type or '(none)'}'; "
        "use application/json or multipart/form-data."
    )


async def _parse_json(request: Request, max_audio_bytes: int) -> RawQueryInput:
    body = await request.body()
    if not body.strip():
        raise MalformedRequestError("The request body is empty.", code="empty_body")
    try:
        payload = json.loads(body)
    except ValueError:
        raise MalformedRequestError("The request body is not valid JSON.", code="invalid_json") from None
    if not isinstance(payload, dict):
        raise InputValidationError("The request body must be a JSON object.")

    parsed = _validate(QueryRequest, payload)
    audio = _decode_voice(parsed.voice, max_audio_bytes) if parsed.voice is not None else None
    return _to_raw(parsed, audio)


async def _parse_multipart(request: Request, max_audio_bytes: int) -> RawQueryInput:
    async with request.form(max_files=1, max_fields=len(_FORM_FIELDS)) as form:
        _check_form_keys(form)

        fields: dict[str, Any] = {}
        for name in _FORM_TEXT_FIELDS:
            value = _single_str_field(form, name)
            # Blank optional fields are how HTML forms and Swagger UI say "not provided".
            if value is not None and (value != "" or name == "text"):
                fields[name] = value
        for name, expected in _FORM_JSON_FIELDS.items():
            value = _single_str_field(form, name)
            if value:
                fields[name] = _decode_json_field(name, value, expected)

        audio = await _read_upload(form.get("voice"), max_audio_bytes)
        parsed = _validate(QueryFields, fields)
    return _to_raw(parsed, audio)


def _validate[M: BaseModel](model: type[M], data: dict[str, Any]) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise validation_error_from_pydantic(exc) from None


def _to_raw(fields: QueryFields, audio: AudioInput | None) -> RawQueryInput:
    return RawQueryInput(
        text=fields.text,
        audio=audio,
        language=fields.language,
        session_id=fields.session_id,
        attachments=tuple(fields.attachments),
        metadata=fields.metadata,
    )


def _decode_voice(voice: VoicePayload, max_audio_bytes: int) -> AudioInput:
    encoded = "".join(voice.audio_base64.split())
    content_type = voice.content_type
    if match := _DATA_URI_PREFIX.match(encoded):
        encoded = encoded[match.end():]
        content_type = content_type or match.group(1)

    # Check before decoding so oversized payloads are never materialised.
    if len(encoded) > 4 * ((max_audio_bytes + 2) // 3):
        raise PayloadTooLargeError(
            f"Audio exceeds the maximum of {max_audio_bytes} bytes.", code="audio_too_large"
        )
    try:
        data = base64.b64decode(encoded, validate=True)
    except binascii.Error:
        raise InputValidationError(
            "voice.audio_base64 is not valid base64.",
            code="invalid_base64",
            field="voice.audio_base64",
        ) from None
    return AudioInput(data=data, filename=voice.filename, content_type=content_type)


def _check_form_keys(form: FormData) -> None:
    unknown = sorted(set(form.keys()) - _FORM_FIELDS)
    if unknown:
        raise InputValidationError(
            f"Unknown form field(s): {', '.join(unknown)}.",
            details=[
                {"field": name, "message": "Extra inputs are not permitted", "type": "extra_forbidden"}
                for name in unknown
            ],
        )
    for name in set(form.keys()):
        if len(form.getlist(name)) > 1:
            raise InputValidationError(f"Form field '{name}' was sent more than once.", field=name)


def _single_str_field(form: FormData, name: str) -> str | None:
    value = form.get(name)
    if value is None or isinstance(value, str):
        return value
    raise InputValidationError(f"'{name}' must be a plain form field, not a file.", field=name)


def _decode_json_field(name: str, raw: str, expected: type) -> Any:
    try:
        value = json.loads(raw)
    except ValueError:
        raise InputValidationError(f"'{name}' must be a JSON-encoded {expected.__name__}.", field=name) from None
    if not isinstance(value, expected):
        kind = "array" if expected is list else "object"
        raise InputValidationError(f"'{name}' must be a JSON {kind}.", field=name)
    return value


async def _read_upload(value: UploadFile | str | None, max_audio_bytes: int) -> AudioInput | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        raise InputValidationError("'voice' must be an uploaded audio file.", field="voice")

    data = await value.read(max_audio_bytes + 1)
    if not data and not value.filename:
        return None  # an HTML file input left empty
    if len(data) > max_audio_bytes:
        raise PayloadTooLargeError(
            f"Audio exceeds the maximum of {max_audio_bytes} bytes.", code="audio_too_large"
        )
    return AudioInput(data=data, filename=value.filename, content_type=value.content_type)

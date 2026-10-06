"""Error hierarchy shared across SatQuery layers.

Every error the API is allowed to surface derives from :class:`SatQueryError`.
Each carries a stable machine-readable ``code`` (clients branch on this, never on
the message) and the HTTP status the API layer maps it to. Layers raise these
errors; only ``satquery.api`` turns them into HTTP responses.
"""

from typing import Any

from pydantic import ValidationError


class SatQueryError(Exception):
    """Base class for all expected, client-presentable SatQuery errors."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: list[dict[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details: list[dict[str, Any]] = details or []
        self.headers: dict[str, str] = headers or {}


class InputValidationError(SatQueryError):
    """The request is well-formed but its content is invalid (HTTP 422)."""

    code = "validation_error"
    http_status = 422

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        field: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        if details is None:
            details = [{"field": field, "message": message, "type": code or self.code}]
        super().__init__(message, code=code, details=details)


class MalformedRequestError(SatQueryError):
    """The request body could not be parsed at all (HTTP 400)."""

    code = "malformed_request"
    http_status = 400


class UnsupportedMediaTypeError(SatQueryError):
    """The request or uploaded file uses a media type we do not accept (HTTP 415)."""

    code = "unsupported_media_type"
    http_status = 415


class PayloadTooLargeError(SatQueryError):
    """The request body or an uploaded file exceeds configured limits (HTTP 413)."""

    code = "payload_too_large"
    http_status = 413


def _clean_pydantic_message(message: str) -> str:
    # Custom validators raise ValueError; pydantic prefixes those with "Value error, ".
    return message.removeprefix("Value error, ")


def validation_error_from_pydantic(
    exc: ValidationError, *, loc_prefix: tuple[str, ...] = ()
) -> InputValidationError:
    """Convert a pydantic ``ValidationError`` into an :class:`InputValidationError`.

    Input values are deliberately excluded from the details so that rejected
    payloads (e.g. base64 audio or free text) are never echoed back.
    """
    details: list[dict[str, Any]] = []
    for err in exc.errors(include_url=False, include_input=False, include_context=False):
        loc = ".".join(str(part) for part in (*loc_prefix, *err["loc"]))
        details.append(
            {
                "field": loc or None,
                "message": _clean_pydantic_message(err["msg"]),
                "type": err["type"],
            }
        )
    if len(details) == 1:
        only = details[0]
        message = f"{only['field']}: {only['message']}" if only["field"] else only["message"]
    else:
        message = f"Request validation failed with {len(details)} errors."
    return InputValidationError(message, details=details)

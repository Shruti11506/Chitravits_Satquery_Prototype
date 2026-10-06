"""Maps every error to the uniform ``{"error": {...}}`` response body."""

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from satquery.api.schemas import ErrorBody, ErrorDetail, ErrorResponse
from satquery.core.errors import SatQueryError

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    400: "malformed_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def error_content(
    code: str,
    message: str,
    *,
    details: list[dict[str, Any]] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    body = ErrorBody(
        code=code,
        message=message,
        details=[ErrorDetail(**d) for d in details or []],
        request_id=request_id,
    )
    return ErrorResponse(error=body).model_dump(mode="json")


async def _handle_satquery_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SatQueryError)
    log = logger.warning if exc.http_status >= 500 else logger.info
    log("%s %s -> %d %s", request.method, request.url.path, exc.http_status, exc.code)
    return JSONResponse(
        status_code=exc.http_status,
        content=error_content(
            exc.code, exc.message, details=exc.details, request_id=get_request_id(request)
        ),
        headers=exc.headers or None,
    )


async def _handle_request_validation(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {
            "field": ".".join(str(p) for p in err.get("loc", ())) or None,
            "message": str(err.get("msg", "")).removeprefix("Value error, "),
            "type": err.get("type"),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_content(
            "validation_error",
            "Request validation failed.",
            details=details,
            request_id=get_request_id(request),
        ),
    )


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    status = exc.status_code
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(status).phrase
    return JSONResponse(
        status_code=status,
        content=error_content(
            _HTTP_ERROR_CODES.get(status, "http_error"),
            message,
            request_id=get_request_id(request),
        ),
        headers=getattr(exc, "headers", None),
    )


async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=error_content(
            "internal_error", "An unexpected error occurred.", request_id=get_request_id(request)
        ),
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(SatQueryError, _handle_satquery_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)

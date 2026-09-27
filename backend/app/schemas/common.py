"""Shared response envelope and error types used by every route."""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    # Optional, structured extra context beyond one message -- e.g. the
    # change-detection gate (analysis_service.py) attaches the full list of
    # failed checks plus a T1/T2 summary here. None for every other error;
    # existing frontend error handling that only reads code/message is
    # unaffected by this addition.
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None

    @classmethod
    def ok(cls, data: T | None = None) -> "ApiResponse[T]":
        return cls(success=True, data=data, error=None)

    @classmethod
    def fail(cls, code: str, message: str, details: dict[str, Any] | None = None) -> "ApiResponse[None]":
        return cls(success=False, data=None, error=ErrorDetail(code=code, message=message, details=details))


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int


class PaginatedData(BaseModel, Generic[T]):
    items: list[T]
    pagination: PaginationMeta

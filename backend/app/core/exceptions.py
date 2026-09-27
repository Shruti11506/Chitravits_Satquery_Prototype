"""Domain-level exceptions mapped to HTTP responses in main.py.

Services raise these instead of HTTPException so they stay decoupled from
FastAPI/HTTP concerns; the route layer (or the global handler) translates
them into the standard ApiResponse error envelope.
"""
from typing import Any


class ApiError(Exception):
    def __init__(self, *, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        # Optional structured payload beyond one message -- see
        # schemas/common.py::ErrorDetail.details. None for most errors.
        self.details = details
        super().__init__(message)


class NotFoundError(ApiError):
    def __init__(self, code: str, message: str):
        super().__init__(status_code=404, code=code, message=message)


class ValidationAppError(ApiError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(status_code=422, code=code, message=message, details=details)


class SupabaseError(ApiError):
    def __init__(self, message: str):
        super().__init__(status_code=500, code="SUPABASE_ERROR", message=message)


class StorageError(ApiError):
    def __init__(self, message: str, code: str = "STORAGE_ERROR"):
        super().__init__(status_code=500, code=code, message=message)


class SupabaseNotConfiguredError(ApiError):
    """backend/.env lacks usable Supabase credentials -- a setup problem, not an outage."""

    def __init__(self, message: str):
        super().__init__(status_code=503, code="SUPABASE_NOT_CONFIGURED", message=message)


class SchemaNotMigratedError(ApiError):
    """A table/function the code needs doesn't exist yet (manual migration pending)."""

    def __init__(self, message: str):
        super().__init__(status_code=503, code="SCHEMA_NOT_MIGRATED", message=message)

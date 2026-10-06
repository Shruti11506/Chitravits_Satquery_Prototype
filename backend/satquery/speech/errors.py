"""Errors raised by speech-to-text services.

Messages are safe to show to API clients: they never include credentials,
request headers or raw audio.
"""

from typing import Any

from satquery.core.errors import SatQueryError


class SpeechServiceError(SatQueryError):
    """Base class: transcription could not be completed."""

    code = "speech_error"
    http_status = 502


class SpeechNotConfiguredError(SpeechServiceError):
    """The speech provider is missing required configuration (e.g. API key)."""

    code = "speech_not_configured"
    http_status = 503


class SpeechAuthenticationError(SpeechServiceError):
    """The provider rejected our credentials. A server-side problem, not the client's."""

    code = "speech_provider_auth_failed"
    http_status = 502


class SpeechTimeoutError(SpeechServiceError):
    code = "speech_timeout"
    http_status = 504


class SpeechProviderUnavailableError(SpeechServiceError):
    """The provider could not be reached (DNS, connection refused, TLS, ...)."""

    code = "speech_provider_unavailable"
    http_status = 503


class SpeechProviderError(SpeechServiceError):
    """The provider failed or returned something we could not interpret."""

    code = "speech_provider_error"
    http_status = 502


class SpeechRateLimitError(SpeechServiceError):
    """The provider's rate limit or quota was exceeded."""

    code = "speech_rate_limited"
    http_status = 429

    def __init__(
        self,
        message: str,
        *,
        retry_after: int | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        super().__init__(message, details=details, headers=headers)
        self.retry_after = retry_after


class SpeechRequestRejectedError(SpeechServiceError):
    """The provider refused the request, typically because of the audio (format, length, corruption)."""

    code = "speech_request_rejected"
    http_status = 422


class EmptyTranscriptError(SpeechServiceError):
    """Transcription succeeded but produced no usable text (silence, noise)."""

    code = "empty_transcript"
    http_status = 422

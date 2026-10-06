"""Sarvam AI speech-to-text adapter.

API contract (https://docs.sarvam.ai/api-reference-docs/speech-to-text/transcribe):

    POST {SARVAM_BASE_URL}/speech-to-text      multipart/form-data
    header  api-subscription-key: <key>
    fields  file, model, language_code ("hi-IN", ... or "unknown" to auto-detect), [mode]
    200  -> {"request_id", "transcript", "language_code", "language_probability", ...}
    4xx/5xx -> {"error": {"message", "code", "request_id"}}

The synchronous endpoint accepts clips under 30 seconds.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from satquery.config.settings import SarvamSettings
from satquery.core.languages import normalize_language_code
from satquery.speech.base import AudioInput, SpeechService, Transcript
from satquery.speech.errors import (
    EmptyTranscriptError,
    SpeechAuthenticationError,
    SpeechNotConfiguredError,
    SpeechProviderError,
    SpeechProviderUnavailableError,
    SpeechRateLimitError,
    SpeechRequestRejectedError,
    SpeechTimeoutError,
)

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_MAX_PROVIDER_MESSAGE_CHARS = 300

# SatQuery uses ISO 639 "or" for Odia; Sarvam uses "od".
_ISO_TO_SARVAM = {"or": "od"}


def to_sarvam_language_code(language: str | None) -> str:
    """Map a SatQuery ISO code to Sarvam's ``language_code`` form field."""
    if language is None:
        return "unknown"
    return f"{_ISO_TO_SARVAM.get(language, language)}-IN"


def from_sarvam_language_code(code: object) -> str | None:
    """Map Sarvam's BCP-47 ``language_code`` back to a SatQuery ISO code, if supported."""
    if not isinstance(code, str) or not code.strip():
        return None
    try:
        return normalize_language_code(code)
    except ValueError:
        return None


class SarvamSpeechService(SpeechService):
    provider = "sarvam"
    is_mock = False

    def __init__(self, settings: SarvamSettings, *, client: httpx.AsyncClient | None = None) -> None:
        """
        Args:
            settings: Sarvam configuration; the API key is read from here, never hard-coded.
            client: Optional pre-built HTTP client (used by tests to inject a mock transport).
                When omitted, the service creates and owns its own client.
        """
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return self._settings.api_key is not None

    @property
    def endpoint(self) -> str:
        return self._settings.base_url.rstrip("/") + "/" + self._settings.stt_path.lstrip("/")

    def describe(self) -> dict[str, Any]:
        return {**super().describe(), "model": self._settings.stt_model}

    async def transcribe(self, audio: AudioInput, *, language: str | None = None) -> Transcript:
        if self._settings.api_key is None:
            raise SpeechNotConfiguredError(
                "Voice input is unavailable: the Sarvam speech-to-text API key "
                "(SARVAM_API_KEY) is not configured on the server."
            )
        api_key = self._settings.api_key.get_secret_value()

        form: dict[str, str] = {
            "model": self._settings.stt_model,
            "language_code": to_sarvam_language_code(language),
        }
        if self._settings.stt_mode:
            form["mode"] = self._settings.stt_mode

        # Never forward the client's filename to a third party; derive one from the sniffed format.
        fmt = audio.format
        filename = f"audio.{fmt.extension}" if fmt else "audio"
        mime = fmt.mime_type if fmt else (audio.content_type or "application/octet-stream")
        files = {"file": (filename, audio.data, mime)}

        response = await self._post_with_retries(form, files, api_key)
        return self._parse_response(response, api_key=api_key, requested_language=language)

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"User-Agent": "satquery-input-layer"})
        return self._client

    async def _post_with_retries(
        self, form: dict[str, str], files: dict[str, Any], api_key: str
    ) -> httpx.Response:
        client = self._get_client()
        attempts = self._settings.max_retries + 1
        headers = {"api-subscription-key": api_key, "Accept": "application/json"}

        for attempt in range(1, attempts + 1):
            is_last = attempt == attempts
            started = time.perf_counter()
            try:
                response = await client.post(
                    self.endpoint,
                    data=form,
                    files=files,
                    headers=headers,
                    timeout=self._settings.timeout_seconds,
                )
            except httpx.TimeoutException as exc:
                # A read timeout means Sarvam may still be working; retrying would only double latency.
                retryable = isinstance(exc, httpx.ConnectTimeout)
                logger.warning(
                    "Sarvam STT timed out (attempt %d/%d, %s)", attempt, attempts, type(exc).__name__
                )
                if is_last or not retryable:
                    raise SpeechTimeoutError(
                        f"Sarvam speech-to-text did not respond within "
                        f"{self._settings.timeout_seconds:g} seconds."
                    ) from None
            except httpx.TransportError as exc:
                logger.warning(
                    "Sarvam STT unreachable (attempt %d/%d, %s)", attempt, attempts, type(exc).__name__
                )
                if is_last:
                    raise SpeechProviderUnavailableError(
                        "Could not reach the Sarvam speech-to-text service."
                    ) from None
            else:
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "Sarvam STT responded status=%d in %.0f ms (attempt %d/%d)",
                    response.status_code,
                    elapsed_ms,
                    attempt,
                    attempts,
                )
                if response.status_code not in _RETRYABLE_STATUS or is_last:
                    return response

            await asyncio.sleep(self._settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        raise AssertionError("unreachable")  # pragma: no cover

    def _parse_response(
        self, response: httpx.Response, *, api_key: str, requested_language: str | None
    ) -> Transcript:
        status = response.status_code
        if status == 200:
            return self._parse_success(response, requested_language)

        provider_code, provider_message = _extract_error(response)
        safe_message = _redact(provider_message, api_key)
        details = [{"field": None, "message": safe_message, "type": f"sarvam.{provider_code}"}]
        logger.warning("Sarvam STT error status=%d code=%s", status, provider_code)

        if status in (401, 403):
            raise SpeechAuthenticationError(
                "Sarvam rejected the server's speech-to-text credentials.", details=details
            )
        if status == 429:
            raise SpeechRateLimitError(
                "Sarvam speech-to-text rate limit or quota exceeded; please retry later.",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
                details=details,
            )
        if status in (400, 413, 415, 422):
            raise SpeechRequestRejectedError(
                f"Sarvam could not process the audio: {safe_message}", details=details
            )
        raise SpeechProviderError(
            f"Sarvam speech-to-text failed (HTTP {status}).", details=details
        )

    def _parse_success(self, response: httpx.Response, requested_language: str | None) -> Transcript:
        try:
            payload = response.json()
        except ValueError:
            raise SpeechProviderError("Sarvam returned a response that is not valid JSON.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("transcript"), str):
            raise SpeechProviderError("Sarvam returned a response without a transcript.")

        text: str = payload["transcript"]
        if not text.strip():
            raise EmptyTranscriptError("No speech could be recognised in the audio.")

        if self._settings.stt_mode == "translate":
            language = "en"  # Sarvam translate mode always yields English text.
        else:
            language = from_sarvam_language_code(payload.get("language_code")) or requested_language

        probability = payload.get("language_probability")
        request_id = payload.get("request_id")
        return Transcript(
            text=text,
            language=language,
            provider=self.provider,
            model=self._settings.stt_model,
            is_mock=False,
            request_id=request_id if isinstance(request_id, str) else None,
            language_probability=float(probability) if isinstance(probability, int | float) else None,
        )


def _extract_error(response: httpx.Response) -> tuple[str, str]:
    """Best-effort extraction of Sarvam's ``{"error": {"code", "message"}}`` body."""
    code, message = "unknown_error", f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return code, text or message
    if isinstance(payload, dict):
        error = payload.get("error", payload)
        if isinstance(error, dict):
            code = str(error.get("code") or code)
            message = str(error.get("message") or error.get("detail") or message)
        elif isinstance(error, str):
            message = error
    return code, message


def _redact(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "[REDACTED]")
    if len(text) > _MAX_PROVIDER_MESSAGE_CHARS:
        text = text[:_MAX_PROVIDER_MESSAGE_CHARS] + "..."
    return text


def _parse_retry_after(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(float(value)))
    except ValueError:
        return None

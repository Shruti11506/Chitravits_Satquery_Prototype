"""Typed async HTTP client for the EarthMind inference service.

This is the only module on the agent side that knows the EarthMind wire format
or speaks HTTP to it. It maps every failure mode to a stable
:class:`EarthMindClientError` code so the tool/graph never sees raw ``httpx``
exceptions, stack traces, or the service's internal detail.

The request/response shapes mirror ``earthmind_service.schemas`` by value (the
two packages are separate deployables and must not import each other).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_INFER_PATH = "/v1/earthmind/infer"


class EarthMindClientError(Exception):
    """A structured, client-safe failure talking to the EarthMind service."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class EarthMindInference:
    """Parsed successful response from the service."""

    task: str
    answer: str
    confidence: float | None
    model: str
    device: str | None
    backend: str | None
    latency_ms: int | None
    timings_ms: dict[str, int]


# Map the service's HTTP status / error code to an agent-facing code.
_STATUS_TO_CODE = {
    422: "EARTHMIND_BAD_REQUEST",
    503: "EARTHMIND_UNAVAILABLE",
    500: "EARTHMIND_INFERENCE_FAILED",
}


class EarthMindClient:
    def __init__(self, *, base_url: str, timeout: float = 60.0, connect_timeout: float = 5.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def infer(self, *, query: str, image_bytes: bytes, task: str,
                    image_format: str | None = None, metadata: dict | None = None) -> EarthMindInference:
        payload = {
            "query": query,
            "image": base64.b64encode(image_bytes).decode("ascii"),
            "task": task,
            "metadata": metadata or {},
        }
        if image_format:
            payload["image_format"] = image_format

        try:
            resp = await self._client.post(_INFER_PATH, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise EarthMindClientError(
                "EARTHMIND_UNAVAILABLE", "EarthMind inference service is unavailable."
            ) from None
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.TimeoutException):
            raise EarthMindClientError(
                "EARTHMIND_TIMEOUT", "The EarthMind inference request timed out."
            ) from None
        except httpx.HTTPError:
            raise EarthMindClientError(
                "EARTHMIND_UNAVAILABLE", "Could not reach the EarthMind inference service."
            ) from None

        if resp.status_code >= 400:
            raise self._error_from_response(resp)
        return self._parse_success(resp)

    def _error_from_response(self, resp: httpx.Response) -> EarthMindClientError:
        code = _STATUS_TO_CODE.get(resp.status_code, "EARTHMIND_ERROR")
        message = "The EarthMind service reported an error."
        try:
            body = resp.json()
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                # Prefer the service's own stable code (e.g. UNSUPPORTED_IMAGE_FORMAT).
                code = str(err.get("code") or code)
                message = str(err.get("message") or message)
        except ValueError:
            pass
        return EarthMindClientError(code, message)

    def _parse_success(self, resp: httpx.Response) -> EarthMindInference:
        try:
            body = resp.json()
        except ValueError:
            raise EarthMindClientError(
                "EARTHMIND_BAD_RESPONSE", "The EarthMind service returned a malformed response."
            ) from None
        if not isinstance(body, dict) or "answer" not in body:
            raise EarthMindClientError(
                "EARTHMIND_BAD_RESPONSE", "The EarthMind response was missing required fields."
            )
        timings = body.get("timings_ms") or {}
        return EarthMindInference(
            task=str(body.get("task", "")),
            answer=str(body["answer"]),
            confidence=body.get("confidence"),
            model=str(body.get("model", "")),
            device=body.get("device"),
            backend=body.get("backend"),
            latency_ms=body.get("latency_ms"),
            timings_ms=timings if isinstance(timings, dict) else {},
        )

"""Async HTTP client for the MCD-Mamba change-detection service.

All network failures map to ``MCDMambaClientError`` so the graph node
never sees raw httpx exceptions.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


class MCDMambaClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class MCDMambaInference:
    summary: str
    change_regions: list[dict]
    change_area_ha: float | None
    change_fraction: float | None
    confidence: float | None
    model: str
    device: str | None
    backend: str | None
    latency_ms: int | None
    timings_ms: dict[str, int] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    # Artifacts the model wrote (e.g. a rendered change map). Populated by the
    # remote wrapper adapter; empty for the native JSON protocol.
    output_files: list = field(default_factory=list)


class MCDMambaClient:
    """Thin async client wrapping the MCD-Mamba inference service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8002",
        timeout: float = 120.0,
        connect_timeout: float = 5.0,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._owned = client is None
        if client is not None:
            self._http = client
        else:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=connect_timeout),
                base_url=self._base_url,
            )

    async def infer(
        self,
        before_image_bytes: bytes,
        after_image_bytes: bytes,
        query: str,
        task: str = "change_detection",
        image_format: str | None = None,
        metadata: dict | None = None,
    ) -> MCDMambaInference:
        payload: dict = {
            "before_image": base64.b64encode(before_image_bytes).decode(),
            "after_image": base64.b64encode(after_image_bytes).decode(),
            "query": query,
            "task": task,
            "metadata": metadata or {},
        }
        if image_format:
            payload["image_format"] = image_format

        try:
            resp = await self._http.post(
                f"{self._base_url}/v1/mamba/infer",
                json=payload,
            )
        except httpx.TimeoutException:
            raise MCDMambaClientError("MAMBA_TIMEOUT", "MCD-Mamba service timed out.")
        except httpx.ConnectError:
            raise MCDMambaClientError("MAMBA_UNAVAILABLE", "Cannot reach MCD-Mamba service.")
        except httpx.RequestError as exc:
            raise MCDMambaClientError("MAMBA_REQUEST_ERROR", str(exc))

        if resp.status_code != 200:
            try:
                detail = resp.json().get("detail", resp.text)
            except Exception:
                detail = resp.text
            raise MCDMambaClientError(
                f"MAMBA_HTTP_{resp.status_code}",
                f"MCD-Mamba service returned {resp.status_code}: {detail}",
            )

        try:
            body = resp.json()
        except Exception as exc:
            raise MCDMambaClientError("MAMBA_INVALID_RESPONSE", f"Cannot parse response: {exc}")

        if not body.get("success", True):
            raise MCDMambaClientError("MAMBA_INFERENCE_FAILED", body.get("summary", "Inference failed."))

        return MCDMambaInference(
            summary=body["summary"],
            change_regions=body.get("change_regions", []),
            change_area_ha=body.get("change_area_ha"),
            change_fraction=body.get("change_fraction"),
            confidence=body.get("confidence"),
            model=body.get("model", "MCD-Mamba"),
            device=body.get("device"),
            backend=body.get("backend"),
            latency_ms=body.get("latency_ms"),
            timings_ms=body.get("timings_ms") or {},
            metadata=body.get("metadata") or {},
        )

    async def aclose(self) -> None:
        if self._owned:
            await self._http.aclose()

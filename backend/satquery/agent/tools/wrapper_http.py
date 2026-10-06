"""Shared HTTP plumbing for the remote model *wrapper* APIs.

The three model wrappers (EarthMind, MCD-Mamba, GeoGround) are separate FastAPI
deployments that share one wire convention:

* ``GET  /health``   -> JSON describing the loaded model
* ``POST /predict``  -> ``multipart/form-data`` with image file part(s) + scalar
  form fields, returning JSON

This module owns that convention in one place: multipart assembly, optional
bearer/API-key authentication, timeouts, and the mapping of every failure mode
onto a stable, client-safe error code. Each service's adapter subclasses
:class:`WrapperClient` and only translates its own request/response payload.

Two rules this module enforces for the whole agent:

* **No hard-coded endpoints.** ``base_url`` and the two paths are always
  injected by configuration, so a ``*.trycloudflare.com`` tunnel can be
  swapped for ``*.satquery.online`` without a code change.
* **No credential leakage.** The key is held as a plain string used only to
  build a request header. It is never logged, never echoed into an error
  message, and :meth:`describe` redacts it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Upper bound on how much of a remote error body we quote back to the caller.
_MAX_DETAIL_CHARS = 300


class WrapperApiError(Exception):
    """A structured, client-safe failure talking to a remote wrapper API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ServiceHealth:
    """Outcome of one ``GET /health`` probe."""

    service: str
    ok: bool
    url: str
    status_code: int | None = None
    latency_ms: int | None = None
    model: str | None = None
    device: str | None = None
    detail: dict | None = None
    error_code: str | None = None
    error: str | None = None

    @property
    def verdict(self) -> str:
        return "PASS" if self.ok else "FAIL"


# --- image sniffing --------------------------------------------------------
# The wrappers open uploads with PIL/rasterio, which key off the file
# extension for some drivers (notably GeoTIFF). Derive both from the magic
# bytes rather than trusting a caller-supplied name.

_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"II*\x00", "tif", "image/tiff"),
    (b"MM\x00*", "tif", "image/tiff"),
    (b"II+\x00", "tif", "image/tiff"),   # BigTIFF
    (b"MM\x00+", "tif", "image/tiff"),
    (b"BM", "bmp", "image/bmp"),
    (b"GIF8", "gif", "image/gif"),
)

_ALLOWED_HINTS = {
    "png": ("png", "image/png"),
    "jpg": ("jpg", "image/jpeg"),
    "jpeg": ("jpg", "image/jpeg"),
    "tif": ("tif", "image/tiff"),
    "tiff": ("tif", "image/tiff"),
    "webp": ("webp", "image/webp"),
    "bmp": ("bmp", "image/bmp"),
    "jp2": ("jp2", "image/jp2"),
}


def sniff_image(data: bytes, *, hint: str | None = None) -> tuple[str, str]:
    """Return ``(extension, mime_type)`` for raster ``data``.

    Magic bytes win; ``hint`` (e.g. the attachment URI's suffix) is the
    fallback for containers we do not sniff, such as WEBP and JPEG 2000.
    """
    for magic, ext, mime in _MAGIC:
        if data.startswith(magic):
            return ext, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if hint:
        mapped = _ALLOWED_HINTS.get(hint.lstrip(".").lower())
        if mapped:
            return mapped
    return "bin", "application/octet-stream"


def image_part(data: bytes, *, name: str, hint: str | None = None) -> tuple[str, bytes, str]:
    """Build one ``httpx`` multipart file tuple for a raster payload."""
    ext, mime = sniff_image(data, hint=hint)
    return (f"{name}.{ext}", data, mime)


def form_value(value: object) -> str:
    """Render a scalar as a multipart form field the wrappers' parsers accept."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class WrapperClient:
    """Base adapter for a remote wrapper API.

    Subclasses keep the payload translation; everything transport-shaped lives
    here so all three services fail in the same, auditable way.
    """

    def __init__(
        self,
        *,
        service: str,
        code_prefix: str,
        base_url: str,
        timeout: float = 180.0,
        connect_timeout: float = 10.0,
        api_key: str | None = None,
        api_key_header: str = "Authorization",
        auth_scheme: str | None = "Bearer",
        health_path: str = "/health",
        predict_path: str = "/predict",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not base_url or not base_url.strip():
            raise ValueError(f"{service}: base_url is required (set it from configuration).")
        self.service = service
        self._prefix = code_prefix.rstrip("_")
        self._base_url = base_url.rstrip("/")
        self._health_path = health_path if health_path.startswith("/") else f"/{health_path}"
        self._predict_path = predict_path if predict_path.startswith("/") else f"/{predict_path}"
        self._api_key = (api_key or "").strip() or None
        self._api_key_header = api_key_header
        self._auth_scheme = (auth_scheme or "").strip() or None
        self._owns_client = client is None
        self._http = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=connect_timeout),
            follow_redirects=True,
        )

    # --- introspection -----------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def requires_auth(self) -> bool:
        return self._api_key is not None

    def describe(self) -> dict:
        """Config summary safe to log or return over HTTP (never the key itself)."""
        return {
            "service": self.service,
            "base_url": self._base_url,
            "health_path": self._health_path,
            "predict_path": self._predict_path,
            "authenticated": self.requires_auth,
        }

    def output_url(self, path_or_name: str | None) -> str | None:
        """Absolute URL for an artifact the wrapper wrote under ``/outputs``."""
        if not path_or_name:
            return None
        if path_or_name.startswith(("http://", "https://")):
            return path_or_name
        suffix = path_or_name if path_or_name.startswith("/") else f"/outputs/{path_or_name}"
        return f"{self._base_url}{suffix}"

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    # --- requests ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if self._api_key is None:
            return {}
        value = f"{self._auth_scheme} {self._api_key}" if self._auth_scheme else self._api_key
        return {self._api_key_header: value}

    def _code(self, suffix: str) -> str:
        return f"{self._prefix}_{suffix}"

    async def health(self) -> ServiceHealth:
        """Probe ``GET /health``. Never raises; the result carries the verdict."""
        import time

        url = f"{self._base_url}{self._health_path}"
        t0 = time.perf_counter()
        try:
            resp = await self._http.get(self._health_path, headers=self._headers())
        except WrapperApiError:  # pragma: no cover - defensive
            raise
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not raise
            err = self._transport_error(exc)
            return ServiceHealth(
                service=self.service, ok=False, url=url,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                error_code=err.code, error=err.message,
            )

        latency_ms = int((time.perf_counter() - t0) * 1000)
        if resp.status_code >= 400:
            err = self._error_from_response(resp)
            return ServiceHealth(
                service=self.service, ok=False, url=url, status_code=resp.status_code,
                latency_ms=latency_ms, error_code=err.code, error=err.message,
            )
        try:
            body = resp.json()
        except ValueError:
            return ServiceHealth(
                service=self.service, ok=False, url=url, status_code=resp.status_code,
                latency_ms=latency_ms, error_code=self._code("BAD_RESPONSE"),
                error="The health endpoint did not return JSON.",
            )
        if not isinstance(body, dict):
            body = {"status": body}
        status_ok = str(body.get("status", "")).lower() in {"ok", "healthy", "ready", "up", "true"}
        return ServiceHealth(
            service=self.service,
            ok=status_ok,
            url=url,
            status_code=resp.status_code,
            latency_ms=latency_ms,
            model=body.get("model"),
            device=body.get("device"),
            detail=body,
            error_code=None if status_ok else self._code("UNHEALTHY"),
            error=None if status_ok else f"The service reported status {body.get('status')!r}.",
        )

    async def post_predict(
        self,
        *,
        files: dict[str, tuple[str, bytes, str]],
        data: dict[str, str] | None = None,
    ) -> dict:
        """POST the multipart inference request and return the parsed JSON body."""
        try:
            resp = await self._http.post(
                self._predict_path,
                files=files,
                data=data or {},
                headers=self._headers(),
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a stable code below
            raise self._transport_error(exc) from None

        if resp.status_code >= 400:
            raise self._error_from_response(resp)

        try:
            body = resp.json()
        except ValueError:
            raise WrapperApiError(
                self._code("BAD_RESPONSE"),
                f"The {self.service} service returned a non-JSON response.",
            ) from None
        if not isinstance(body, dict):
            raise WrapperApiError(
                self._code("BAD_RESPONSE"),
                f"The {self.service} service returned an unexpected response shape.",
            )

        status = str(body.get("status", "success")).lower()
        if status not in {"success", "ok", "completed"}:
            raise WrapperApiError(
                self._code("INFERENCE_FAILED"),
                self._detail(body) or f"The {self.service} model reported status {status!r}.",
            )
        return body

    # --- error mapping -----------------------------------------------------

    def _transport_error(self, exc: Exception) -> WrapperApiError:
        if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
            return WrapperApiError(
                self._code("UNAVAILABLE"),
                f"The {self.service} API is unreachable at its configured URL.",
            )
        if isinstance(exc, httpx.TimeoutException):
            return WrapperApiError(
                self._code("TIMEOUT"),
                f"The {self.service} API did not respond within the configured timeout.",
            )
        if isinstance(exc, httpx.HTTPError):
            return WrapperApiError(
                self._code("UNAVAILABLE"),
                f"Could not reach the {self.service} API.",
            )
        logger.exception("%s: unexpected transport failure", self.service)
        return WrapperApiError(
            self._code("REQUEST_ERROR"),
            f"An unexpected error occurred calling the {self.service} API.",
        )

    def _error_from_response(self, resp: httpx.Response) -> WrapperApiError:
        suffix = {
            400: "BAD_REQUEST",
            401: "AUTH_FAILED",
            403: "AUTH_FAILED",
            404: "NOT_FOUND",
            413: "IMAGE_TOO_LARGE",
            415: "UNSUPPORTED_FORMAT",
            422: "BAD_REQUEST",
            429: "RATE_LIMITED",
            502: "UNAVAILABLE",
            503: "UNAVAILABLE",
            504: "TIMEOUT",
        }.get(resp.status_code, "INFERENCE_FAILED" if resp.status_code >= 500 else "ERROR")

        base = {
            "AUTH_FAILED": f"The {self.service} API rejected the configured credentials.",
            "BAD_REQUEST": f"The {self.service} API rejected the request payload.",
            "NOT_FOUND": f"The {self.service} API endpoint was not found at its configured path.",
            "RATE_LIMITED": f"The {self.service} API is rate limiting requests.",
            "TIMEOUT": f"The {self.service} API timed out upstream.",
            "UNAVAILABLE": f"The {self.service} API is temporarily unavailable.",
            "IMAGE_TOO_LARGE": f"The image was rejected by the {self.service} API as too large.",
            "UNSUPPORTED_FORMAT": f"The {self.service} API does not support this image format.",
        }.get(suffix, f"The {self.service} API reported an error (HTTP {resp.status_code}).")

        detail = None
        try:
            detail = self._detail(resp.json())
        except ValueError:
            detail = self._redact(resp.text)
        message = f"{base} {detail}".strip() if detail else base
        return WrapperApiError(self._code(suffix), message)

    def _detail(self, body: object) -> str | None:
        """Extract a short, redacted human detail from a remote error body."""
        if isinstance(body, dict):
            for key in ("detail", "message", "error", "summary"):
                value = body.get(key)
                if isinstance(value, str) and value.strip():
                    return self._redact(value)
                if isinstance(value, list) and value:
                    # FastAPI validation errors: [{loc, msg, type}, ...]
                    msgs = [
                        str(item.get("msg")) for item in value
                        if isinstance(item, dict) and item.get("msg")
                    ]
                    if msgs:
                        return self._redact("; ".join(msgs))
                if isinstance(value, dict):
                    nested = value.get("message") or value.get("detail")
                    if isinstance(nested, str) and nested.strip():
                        return self._redact(nested)
        elif isinstance(body, str) and body.strip():
            return self._redact(body)
        return None

    def _redact(self, text: str) -> str:
        """Trim a remote message and strip anything that echoes our credential."""
        clean = re.sub(r"\s+", " ", text).strip()
        if self._api_key:
            clean = clean.replace(self._api_key, "[REDACTED]")
        if len(clean) > _MAX_DETAIL_CHARS:
            clean = clean[:_MAX_DETAIL_CHARS].rstrip() + "…"
        return clean

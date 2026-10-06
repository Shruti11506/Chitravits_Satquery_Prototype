"""Resolve an ``AttachmentRef`` to raw image bytes.

The input layer keeps attachments as *references* (ids / storage URIs), never raw
rasters. To actually run EarthMind, the agent must fetch the bytes. This resolver
bridges that gap for the schemes we can honestly support today:

* absolute or root-relative local file paths
* ``file://`` URIs
* ``http(s)://`` URLs (when enabled)
* ``satquery://<id>`` -> looked up under ``attachment_root`` by id (dev convenience)

Cloud object stores (``s3://``, ``gs://``, ``az://``) are intentionally NOT
fetched: there is no storage layer yet. They raise a clear, structured error
instead of pretending to resolve.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from satquery.input.schemas import AttachmentRef

# Cap on how many bytes we will pull for one attachment (defensive; the service
# enforces its own, usually smaller, limit too).
_MAX_FETCH_BYTES = 16 * 1024 * 1024
_UNSUPPORTED_SCHEMES = {"s3", "gs", "gcs", "az", "azure", "abfs"}


class AttachmentResolutionError(Exception):
    """Raised when an attachment cannot be turned into image bytes. Carries a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ResolvedImage:
    data: bytes
    source_hint: str  # for logging only, e.g. "file" / "http"


class AttachmentResolver:
    def __init__(self, *, root: str | None = None, allow_http: bool = True,
                 client: httpx.AsyncClient | None = None) -> None:
        self._root = Path(root).expanduser().resolve() if root else None
        self._allow_http = allow_http
        self._client = client  # optional shared client; created per-fetch if absent

    async def resolve(self, attachment: AttachmentRef) -> ResolvedImage:
        target = attachment.uri or attachment.id
        parsed = urlparse(target)
        scheme = parsed.scheme.lower()

        if scheme in _UNSUPPORTED_SCHEMES:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE",
                f"Attachments stored in '{scheme}://' cannot be fetched yet: the storage layer "
                "is not implemented. Provide a local path or an http(s) URL for now.",
            )
        if scheme in ("http", "https"):
            return await self._fetch_http(target)
        if scheme == "file":
            return self._read_file(Path(unquote(parsed.path)))
        if scheme == "satquery":
            return self._read_satquery(parsed)
        if scheme in ("", None) or (len(scheme) == 1):  # bare path (Windows drive letters have len-1 scheme)
            return self._read_file(Path(target))
        raise AttachmentResolutionError(
            "ATTACHMENT_UNRESOLVABLE", f"Unsupported attachment location scheme '{scheme}'."
        )

    # --- local files -------------------------------------------------------
    def _read_file(self, path: Path) -> ResolvedImage:
        resolved = (self._root / path if self._root and not path.is_absolute() else path)
        resolved = resolved.expanduser().resolve()
        # If a root is configured, refuse to escape it (path-traversal guard).
        if self._root is not None and self._root not in resolved.parents and resolved != self._root:
            if not str(resolved).startswith(str(self._root)):
                raise AttachmentResolutionError(
                    "ATTACHMENT_UNRESOLVABLE", "The attachment path is outside the allowed root."
                )
        if not resolved.is_file():
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND", "The referenced attachment file was not found."
            )
        data = resolved.read_bytes()
        self._check_size(len(data))
        return ResolvedImage(data=data, source_hint="file")

    def _read_satquery(self, parsed) -> ResolvedImage:
        if self._root is None:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE",
                "satquery:// references require a configured attachment root (SATQUERY_ATTACHMENT_ROOT).",
            )
        ident = (parsed.netloc or parsed.path.lstrip("/")).strip()
        if not ident:
            raise AttachmentResolutionError("ATTACHMENT_UNRESOLVABLE", "Empty satquery:// reference.")
        # Match "<id>" or "<id>.<ext>" directly under the root.
        matches = sorted(p for p in self._root.glob(f"{ident}*") if p.is_file())
        if not matches:
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND", f"No stored attachment matches id '{ident}'."
            )
        data = matches[0].read_bytes()
        self._check_size(len(data))
        return ResolvedImage(data=data, source_hint="satquery")

    # --- remote ------------------------------------------------------------
    async def _fetch_http(self, url: str) -> ResolvedImage:
        if not self._allow_http:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE", "Fetching attachments over http(s) is disabled."
            )
        self._reject_internal_host(url)
        try:
            if self._client is not None:
                resp = await self._client.get(url)
            else:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    resp = await client.get(url)
        except httpx.HTTPError:
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND", "The attachment URL could not be retrieved."
            ) from None
        if resp.status_code >= 400:
            raise AttachmentResolutionError(
                "ATTACHMENT_NOT_FOUND", f"The attachment URL returned status {resp.status_code}."
            )
        data = resp.content
        self._check_size(len(data))
        return ResolvedImage(data=data, source_hint="http")

    @staticmethod
    def _reject_internal_host(url: str) -> None:
        """Block obvious SSRF targets. Attachment URLs come from clients, not us."""
        host = (urlparse(url).hostname or "").lower()
        if host in {"localhost", "metadata.google.internal", "169.254.169.254"}:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE", "The attachment host is not allowed."
            )
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return  # a hostname, not a literal IP
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise AttachmentResolutionError(
                "ATTACHMENT_UNRESOLVABLE", "The attachment host is not allowed."
            )

    @staticmethod
    def _check_size(size: int) -> None:
        if size == 0:
            raise AttachmentResolutionError("INVALID_IMAGE", "The attachment is empty.")
        if size > _MAX_FETCH_BYTES:
            raise AttachmentResolutionError(
                "INVALID_IMAGE", f"The attachment exceeds {_MAX_FETCH_BYTES} bytes."
            )

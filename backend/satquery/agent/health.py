"""Connectivity checks for the three remote model services.

Probes each configured service's health endpoint concurrently and reports a
PASS/FAIL verdict per service. Used by:

* ``scripts/check_model_apis.py`` — operator-facing CLI smoke test
* ``GET /api/v1/models/health``   — the backend's own readiness view

Credentials are never echoed: the report carries the base URL, the service's
own ``model``/``device`` fields and a stable error code, never the API key. A
service that is not configured is reported as ``skipped``, not as a failure, so
a deployment that intentionally runs without GeoGround does not look broken.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from satquery.agent.tools.factory import build_model_clients
from satquery.agent.tools.wrapper_http import ServiceHealth
from satquery.config.settings import Settings

logger = logging.getLogger(__name__)

# Display name per client key, in the order operators expect to read them.
SERVICE_LABELS: dict[str, str] = {
    "earthmind": "EarthMind",
    "mcd_mamba": "MCD-Mamba",
    "geoground": "GeoGround",
}


@dataclass
class ServiceCheck:
    """One service's connectivity verdict."""

    name: str
    label: str
    status: str                      # "pass" | "fail" | "skipped"
    url: str | None = None
    protocol: str | None = None
    authenticated: bool = False
    latency_ms: int | None = None
    model: str | None = None
    device: str | None = None
    error_code: str | None = None
    error: str | None = None
    detail: dict | None = None

    @property
    def verdict(self) -> str:
        return {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[self.status]

    def to_dict(self) -> dict:
        return {
            "service": self.label,
            "status": self.status,
            "url": self.url,
            "protocol": self.protocol,
            "authenticated": self.authenticated,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "device": self.device,
            "error_code": self.error_code,
            "error": self.error,
            "detail": self.detail,
        }


@dataclass
class ConnectivityReport:
    """The full result of probing every model service."""

    checks: list[ServiceCheck] = field(default_factory=list)

    @property
    def all_pass(self) -> bool:
        return all(c.status != "fail" for c in self.checks)

    @property
    def any_available(self) -> bool:
        return any(c.status == "pass" for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "status": "ok" if self.all_pass else "degraded",
            "services": [c.to_dict() for c in self.checks],
        }

    def render(self) -> str:
        """Human-readable PASS/FAIL lines for a terminal."""
        lines = []
        width = max((len(c.label) for c in self.checks), default=10)
        for c in self.checks:
            line = f"{c.label:<{width}} : {c.verdict}"
            if c.status == "pass":
                bits = [b for b in (c.model, c.device) if b]
                line += f"  ({', '.join(bits)}, {c.latency_ms} ms)" if bits else f"  ({c.latency_ms} ms)"
            elif c.status == "fail":
                line += f"  [{c.error_code}] {c.error or ''}".rstrip()
            else:
                line += "  (not configured)"
            lines.append(line)
        return "\n".join(lines)


def _skipped(name: str, settings: Settings) -> ServiceCheck:
    cfg = getattr(settings, name)
    return ServiceCheck(
        name=name,
        label=SERVICE_LABELS[name],
        status="skipped",
        url=cfg.api_url or None,
        protocol=cfg.api_protocol.value,
    )


async def check_model_services(
    settings: Settings,
    *,
    clients: dict | None = None,
) -> ConnectivityReport:
    """Probe every configured model service concurrently.

    Pass ``clients`` to reuse the agent's own live clients; otherwise temporary
    ones are built from ``settings`` and closed before returning.
    """
    owned = clients is None
    clients = clients if clients is not None else build_model_clients(settings)

    probes: list[tuple[str, object]] = []
    report = ConnectivityReport()
    for name in SERVICE_LABELS:
        client = clients.get(name)
        if client is None or not hasattr(client, "health"):
            # Either unconfigured, or the native-protocol client, which has no
            # health probe of its own. Report honestly rather than guessing.
            report.checks.append(_skipped(name, settings))
            continue
        probes.append((name, client))

    if probes:
        results = await asyncio.gather(
            *(client.health() for _name, client in probes),
            return_exceptions=True,
        )
        for (name, client), result in zip(probes, results):
            report.checks.append(_to_check(name, client, result, settings))

    # Keep the declared service order regardless of which were probed.
    order = list(SERVICE_LABELS)
    report.checks.sort(key=lambda c: order.index(c.name))

    if owned:
        for client in clients.values():
            if client is not None and hasattr(client, "aclose"):
                try:
                    await client.aclose()
                except Exception:  # noqa: BLE001 - closing must not mask the report
                    logger.debug("Failed to close a probe client", exc_info=True)
    return report


def _to_check(name: str, client, result, settings: Settings) -> ServiceCheck:
    cfg = getattr(settings, name)
    base = {
        "name": name,
        "label": SERVICE_LABELS[name],
        "url": getattr(client, "base_url", cfg.api_url),
        "protocol": cfg.api_protocol.value,
        "authenticated": bool(getattr(client, "requires_auth", False)),
    }
    if isinstance(result, BaseException):
        logger.warning("%s health probe raised: %s", SERVICE_LABELS[name], type(result).__name__)
        return ServiceCheck(
            **base, status="fail", error_code="HEALTH_PROBE_FAILED",
            error="The health probe failed unexpectedly.",
        )
    assert isinstance(result, ServiceHealth)
    return ServiceCheck(
        **base,
        status="pass" if result.ok else "fail",
        latency_ms=result.latency_ms,
        model=result.model,
        device=result.device,
        error_code=result.error_code,
        error=result.error,
        detail=result.detail,
    )

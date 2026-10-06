"""Build the model-service clients the agent's tools call.

One place decides, from configuration alone, which adapter speaks to each of
the three model services:

* ``api_protocol = "wrapper"`` -> the deployed remote wrapper API
  (``POST /predict``, multipart) — the production path.
* ``api_protocol = "native"``  -> this repository's in-tree FastAPI service
  (``POST /v1/.../infer``, JSON) — local development against the stub backends.

Nothing above this layer knows which protocol is in use: both adapters per
service expose the same ``infer(...)`` signature and return the same result
dataclass. Swapping a ``trycloudflare.com`` tunnel for an
``earthmind.satquery.online`` subdomain is a change to ``EARTHMIND_API_URL``,
not to any code.

A service that is disabled, or has no URL configured, yields ``None``. The
graph turns that into a tool the planner is simply not offered, so queries
needing it get an honest "not available" instead of a misroute.
"""

from __future__ import annotations

import logging

from satquery.config.settings import ModelApiProtocol, Settings

logger = logging.getLogger(__name__)


def build_earthmind_client(settings: Settings, *, http_client=None):
    """Return the EarthMind client for the configured protocol, or ``None``."""
    cfg = settings.earthmind
    if not settings.earthmind_available:
        logger.info("EarthMind client not built: service disabled or no URL configured.")
        return None

    if cfg.api_protocol is ModelApiProtocol.NATIVE:
        from satquery.agent.tools.earthmind_client import EarthMindClient

        return EarthMindClient(
            base_url=cfg.api_url,
            timeout=cfg.timeout,
            connect_timeout=cfg.connect_timeout,
            client=http_client,
        )

    from satquery.agent.tools.earthmind_remote_client import RemoteEarthMindClient

    return RemoteEarthMindClient(
        base_url=cfg.api_url,
        timeout=cfg.timeout,
        connect_timeout=cfg.connect_timeout,
        api_key=cfg.key(),
        api_key_header=cfg.api_key_header,
        auth_scheme=cfg.api_auth_scheme,
        health_path=cfg.health_path,
        predict_path=cfg.predict_path,
        model_name=cfg.model,
        client=http_client,
    )


def build_mcd_mamba_client(settings: Settings, *, http_client=None):
    """Return the MCD-Mamba client for the configured protocol, or ``None``."""
    cfg = settings.mcd_mamba
    if not settings.mcd_mamba_available:
        logger.info("MCD-Mamba client not built: service disabled or no URL configured.")
        return None

    if cfg.api_protocol is ModelApiProtocol.NATIVE:
        from satquery.agent.tools.mcd_mamba_client import MCDMambaClient

        return MCDMambaClient(
            base_url=cfg.api_url,
            timeout=cfg.timeout,
            connect_timeout=cfg.connect_timeout,
            client=http_client,
        )

    from satquery.agent.tools.mcd_mamba_remote_client import RemoteMCDMambaClient

    return RemoteMCDMambaClient(
        base_url=cfg.api_url,
        timeout=cfg.timeout,
        connect_timeout=cfg.connect_timeout,
        api_key=cfg.key(),
        api_key_header=cfg.api_key_header,
        auth_scheme=cfg.api_auth_scheme,
        health_path=cfg.health_path,
        predict_path=cfg.predict_path,
        patch_size=cfg.patch_size,
        return_probabilities=cfg.return_probabilities,
        include_base64=cfg.include_output_base64,
        model_name=cfg.model,
        client=http_client,
    )


def build_geoground_client(settings: Settings, *, http_client=None):
    """Return the GeoGround client, or ``None`` when it is not configured.

    Grounding has no in-tree native service, so this is always the wrapper
    adapter.
    """
    cfg = settings.geoground
    if not settings.geoground_available:
        logger.info("GeoGround client not built: service disabled or no URL configured.")
        return None

    from satquery.agent.tools.geoground_client import GeoGroundClient

    return GeoGroundClient(
        base_url=cfg.api_url,
        timeout=cfg.timeout,
        connect_timeout=cfg.connect_timeout,
        api_key=cfg.key(),
        api_key_header=cfg.api_key_header,
        auth_scheme=cfg.api_auth_scheme,
        health_path=cfg.health_path,
        predict_path=cfg.predict_path,
        max_points=cfg.max_points,
        generate_caption=cfg.generate_caption,
        include_base64=cfg.include_output_base64,
        model_name=cfg.model,
        client=http_client,
    )


def build_model_clients(settings: Settings, *, http_client=None) -> dict:
    """Build all three model clients at once: ``{name: client_or_None}``."""
    return {
        "earthmind": build_earthmind_client(settings, http_client=http_client),
        "mcd_mamba": build_mcd_mamba_client(settings, http_client=http_client),
        "geoground": build_geoground_client(settings, http_client=http_client),
    }

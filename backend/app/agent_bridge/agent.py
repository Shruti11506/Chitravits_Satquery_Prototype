"""Constructs and caches the one SatQueryAgent the backend shares across jobs.

The agent binds an EarthMind client, an optional MCD-Mamba client, and the
Supabase attachment resolver. It is created lazily on first use (inside the
running event loop) so its httpx clients bind to that loop.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from app.agent_bridge.resolver import SupabaseAttachmentResolver
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class AgentUnavailableError(RuntimeError):
    """The SatQuery agent could not be constructed (import or config failure)."""


def _agent_settings(settings):
    """Map the backend's ``AGENT_*`` config onto the agent's own Settings.

    The agent chooses adapters, timeouts, auth and endpoint paths from its own
    ``satquery.config.settings.Settings``. We seed only the fields the backend
    owns (URLs, protocol, keys, enable flags), so the temporary Cloudflare URLs
    and the permanent ``*.satquery.online`` subdomains are both just values of
    ``AGENT_*_URL`` — no code change to swap them.
    """
    from satquery.config.settings import (
        EarthMindClientSettings,
        GeoGroundClientSettings,
        MCDMambaClientSettings,
        Settings,
    )

    protocol = (settings.AGENT_MODEL_PROTOCOL or "wrapper").strip().lower()
    return Settings(
        _env_file=None,
        earthmind=EarthMindClientSettings(
            _env_file=None, api_url=settings.AGENT_EARTHMIND_URL,
            api_protocol=protocol, api_key=settings.AGENT_EARTHMIND_API_KEY or None,
        ),
        mcd_mamba=MCDMambaClientSettings(
            _env_file=None, api_url=settings.AGENT_MCD_MAMBA_URL,
            api_protocol=protocol, api_key=settings.AGENT_MCD_MAMBA_API_KEY or None,
        ),
        geoground=GeoGroundClientSettings(
            _env_file=None, api_url=settings.AGENT_GEOGROUND_URL,
            api_key=settings.AGENT_GEOGROUND_API_KEY or None,
        ),
        earthmind_enabled=True,
        mcd_mamba_enabled=settings.AGENT_MCD_MAMBA_ENABLED,
        geoground_enabled=settings.AGENT_GEOGROUND_ENABLED,
    )


@lru_cache
def get_agent():
    """Return the shared SatQueryAgent, building it on first call.

    Raises AgentUnavailableError if the sibling ``satquery`` package is not
    importable -- the caller turns that into an honest job failure.
    """
    settings = get_settings()
    try:
        from satquery.agent.langgraph_agent import SatQueryAgent
        from satquery.agent.tools.factory import build_model_clients
    except Exception as exc:  # noqa: BLE001
        raise AgentUnavailableError(
            "The 'satquery' agent package is not importable. Install it into this "
            "backend's environment (pip install -e ../../Agent). Original error: "
            f"{exc}"
        ) from exc

    clients = build_model_clients(_agent_settings(settings))
    earthmind = clients["earthmind"]
    if earthmind is None:
        raise AgentUnavailableError(
            "EarthMind is required but not configured. Set AGENT_EARTHMIND_URL."
        )

    resolver = SupabaseAttachmentResolver()
    logger.info(
        "SatQuery agent constructed (protocol=%s, earthmind=%s, mcd_mamba=%s, geoground=%s)",
        settings.AGENT_MODEL_PROTOCOL,
        settings.AGENT_EARTHMIND_URL,
        settings.AGENT_MCD_MAMBA_URL if clients["mcd_mamba"] else "disabled",
        settings.AGENT_GEOGROUND_URL if clients["geoground"] else "disabled",
    )
    return SatQueryAgent(
        earthmind, resolver,
        mcd_mamba_client=clients["mcd_mamba"],
        geoground_client=clients["geoground"],
    )

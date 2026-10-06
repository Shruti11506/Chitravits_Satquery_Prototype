"""Operational endpoints: health, model-service connectivity, and languages."""

from typing import Any

from fastapi import APIRouter

from satquery import __version__
from satquery.agent.health import check_model_services
from satquery.api.dependencies import AgentDep, SettingsDep, SpeechServiceDep
from satquery.core.languages import SUPPORTED_LANGUAGES
from satquery.tools.registry import TOOL_REGISTRY, capability_card

router = APIRouter(tags=["system"])


@router.get("/health", summary="Service health and active speech-to-text mode")
async def health(settings: SettingsDep, speech: SpeechServiceDep, agent: AgentDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "environment": settings.environment,
        "speech": speech.describe(),
        "agent": agent.name,
    }


@router.get(
    "/models/health",
    summary="Connectivity to the remote model services (EarthMind, MCD-Mamba, GeoGround)",
    description=(
        "Probes each configured model service's health endpoint and reports "
        "PASS/FAIL per service. Credentials are never returned — only the base "
        "URL, whether authentication is configured, and the model/device the "
        "service itself reports."
    ),
)
async def models_health(settings: SettingsDep, agent: AgentDep) -> dict[str, Any]:
    # Reuse the running agent's own clients when it has them, so the probe
    # exercises exactly the configuration the agent will use.
    clients = getattr(agent, "model_clients", None)
    report = await check_model_services(settings, clients=clients)
    return report.to_dict()


@router.get(
    "/tools",
    summary="The tool registry: declared capabilities, input requirements and permitted parameters",
)
async def tools() -> dict[str, Any]:
    return {"tools": [capability_card(name) for name in TOOL_REGISTRY]}


@router.get("/languages", summary="Languages accepted in the 'language' field")
async def languages(settings: SettingsDep) -> dict[str, Any]:
    return {
        "default": settings.default_language,
        "languages": [{"code": code, "name": name} for code, name in SUPPORTED_LANGUAGES.items()],
    }

"""Application factory.

Run locally with:

    uvicorn satquery.main:create_app --factory --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from satquery import __version__
from satquery.agent.interface import Agent, PlaceholderAgent
from satquery.api import API_V1_PREFIX, api_router
from satquery.api.errors import install_exception_handlers
from satquery.api.middleware import REQUEST_ID_HEADER, BodySizeLimitMiddleware, RequestIdMiddleware
from satquery.api.openapi import install_openapi
from satquery.config.settings import AgentBackend, Settings, get_settings
from satquery.input.normalizer import InputNormalizer, NormalizerConfig
from satquery.speech.base import SpeechService
from satquery.speech.factory import build_speech_service

_DESCRIPTION = """
SatQuery AI input layer (Phase 1).

Accepts **text** or **voice** queries plus references to satellite imagery,
transcribes voice with Sarvam AI speech-to-text, and normalises everything into
a single `UserQuery` that is handed to the agent. The agent is currently a
placeholder that acknowledges receipt.
"""


def create_app(
    settings: Settings | None = None,
    *,
    speech_service: SpeechService | None = None,
    agent: Agent | None = None,
) -> FastAPI:
    """Build the FastAPI app. Services can be injected for tests."""
    settings = settings or get_settings()
    _configure_logging(settings.log_level)

    speech = speech_service or build_speech_service(settings)
    active_agent = agent or _build_default_agent(settings)
    normalizer = InputNormalizer(
        speech,
        NormalizerConfig(
            default_language=settings.default_language,
            max_query_chars=settings.max_query_chars,
            max_audio_bytes=settings.max_audio_bytes,
            max_audio_seconds=settings.max_audio_seconds,
            max_attachments=settings.max_attachments,
        ),
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await speech.aclose()
        aclose = getattr(active_agent, "aclose", None)
        if callable(aclose):
            await aclose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=_DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.speech_service = speech
    app.state.normalizer = normalizer
    app.state.agent = active_agent

    install_exception_handlers(app)
    # Last added runs first: CORS -> request id -> body limit -> app.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.effective_max_request_bytes)
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )

    app.include_router(api_router, prefix=API_V1_PREFIX)
    install_openapi(app)
    return app


def _build_default_agent(settings: Settings) -> Agent:
    """Pick the agent implementation from settings when one is not injected."""
    if settings.agent_backend is AgentBackend.PLACEHOLDER:
        return PlaceholderAgent()
    # Imported lazily so tests injecting their own agent never pull in the graph.
    from satquery.agent.langgraph_agent import build_satquery_agent

    return build_satquery_agent(settings)


def _configure_logging(level: str) -> None:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("satquery").setLevel(level.upper())

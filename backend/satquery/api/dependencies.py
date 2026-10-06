"""FastAPI dependencies. Services are built once in ``create_app`` and stored on ``app.state``."""

from typing import Annotated

from fastapi import Depends, Request

from satquery.agent.interface import Agent
from satquery.config.settings import Settings
from satquery.input.normalizer import InputNormalizer
from satquery.speech.base import SpeechService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_speech_service(request: Request) -> SpeechService:
    return request.app.state.speech_service


def get_normalizer(request: Request) -> InputNormalizer:
    return request.app.state.normalizer


def get_agent(request: Request) -> Agent:
    return request.app.state.agent


SettingsDep = Annotated[Settings, Depends(get_settings)]
SpeechServiceDep = Annotated[SpeechService, Depends(get_speech_service)]
NormalizerDep = Annotated[InputNormalizer, Depends(get_normalizer)]
AgentDep = Annotated[Agent, Depends(get_agent)]

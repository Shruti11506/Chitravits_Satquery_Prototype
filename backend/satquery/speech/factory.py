"""Builds the configured :class:`SpeechService`.

There is deliberately no silent fallback from Sarvam to the mock: if Sarvam is
selected but not configured, voice requests fail with ``speech_not_configured``
rather than returning a fabricated transcript. Mock mode must be chosen
explicitly with ``SATQUERY_SPEECH_PROVIDER=mock``.
"""

import logging

from satquery.config.settings import Settings, SpeechProvider
from satquery.speech.base import SpeechService
from satquery.speech.mock import MockSpeechService
from satquery.speech.sarvam import SarvamSpeechService

logger = logging.getLogger(__name__)


def build_speech_service(settings: Settings) -> SpeechService:
    if settings.speech_provider is SpeechProvider.MOCK:
        logger.warning(
            "Speech-to-text is in MOCK mode: Sarvam is NOT called and every voice request "
            "returns the fixed transcript %r (flagged is_mock=true).",
            settings.mock_transcript,
        )
        return MockSpeechService(transcript=settings.mock_transcript, language=settings.mock_language)

    service = SarvamSpeechService(settings.sarvam)
    if service.is_configured:
        logger.info("Speech-to-text: Sarvam (%s, model=%s)", service.endpoint, settings.sarvam.stt_model)
    else:
        logger.warning(
            "SARVAM_API_KEY is not set: text queries work, but voice queries will fail with "
            "'speech_not_configured'. Set SATQUERY_SPEECH_PROVIDER=mock to develop without Sarvam."
        )
    return service

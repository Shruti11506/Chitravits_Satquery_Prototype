"""Speech-to-text services behind a provider-neutral interface."""

from satquery.speech.base import AudioFormat, AudioInput, SpeechService, Transcript
from satquery.speech.factory import build_speech_service
from satquery.speech.mock import MockSpeechService
from satquery.speech.sarvam import SarvamSpeechService

__all__ = [
    "AudioFormat",
    "AudioInput",
    "MockSpeechService",
    "SarvamSpeechService",
    "SpeechService",
    "Transcript",
    "build_speech_service",
]

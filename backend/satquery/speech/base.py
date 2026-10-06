"""Speech-to-text abstraction.

The input layer depends only on :class:`SpeechService`; concrete providers
(Sarvam, mock, future on-prem models) are interchangeable behind it.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


class AudioFormat(StrEnum):
    """Audio container formats accepted for voice input (detected from file content)."""

    WAV = "wav"
    MP3 = "mp3"
    AAC = "aac"
    AIFF = "aiff"
    OGG = "ogg"  # includes Ogg/Opus
    FLAC = "flac"
    MP4 = "mp4"  # includes M4A
    WEBM = "webm"
    AMR = "amr"
    WMA = "wma"

    @property
    def mime_type(self) -> str:
        return _MIME_TYPES[self]

    @property
    def extension(self) -> str:
        return "m4a" if self is AudioFormat.MP4 else self.value


_MIME_TYPES: dict[AudioFormat, str] = {
    AudioFormat.WAV: "audio/wav",
    AudioFormat.MP3: "audio/mpeg",
    AudioFormat.AAC: "audio/aac",
    AudioFormat.AIFF: "audio/aiff",
    AudioFormat.OGG: "audio/ogg",
    AudioFormat.FLAC: "audio/flac",
    AudioFormat.MP4: "audio/mp4",
    AudioFormat.WEBM: "audio/webm",
    AudioFormat.AMR: "audio/amr",
    AudioFormat.WMA: "audio/x-ms-wma",
}


@dataclass(frozen=True, slots=True)
class AudioInput:
    """An audio clip plus what the client told us about it.

    ``format`` and ``duration_seconds`` are filled in by input validation
    (from the bytes themselves, not the client's claims).
    """

    data: bytes = field(repr=False)
    filename: str | None = None
    content_type: str | None = None
    format: AudioFormat | None = None
    duration_seconds: float | None = None

    @property
    def size_bytes(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class Transcript:
    """Result of a speech-to-text call.

    ``language`` is the SatQuery ISO code of the transcript text, or ``None`` if
    the provider did not report a language we support.
    """

    text: str
    language: str | None
    provider: str
    model: str | None
    is_mock: bool
    request_id: str | None = None
    language_probability: float | None = None


class SpeechService(ABC):
    """Converts an audio clip into text."""

    provider: ClassVar[str]
    is_mock: ClassVar[bool] = False

    @property
    def is_configured(self) -> bool:
        """Whether the service has what it needs (e.g. credentials) to transcribe."""
        return True

    @abstractmethod
    async def transcribe(self, audio: AudioInput, *, language: str | None = None) -> Transcript:
        """Transcribe ``audio``.

        ``language`` is a SatQuery ISO code hint; ``None`` asks the provider to
        auto-detect. Implementations raise ``SpeechServiceError`` subclasses on
        failure and never return a fabricated transcript.
        """

    async def aclose(self) -> None:
        """Release network resources. Safe to call more than once."""

    def describe(self) -> dict[str, Any]:
        """Non-secret summary for health checks and logs."""
        return {
            "provider": self.provider,
            "mode": "mock" if self.is_mock else "live",
            "configured": self.is_configured,
        }

"""Mock speech-to-text for local development and tests.

This service never contacts any external API. Every transcript it produces is
flagged ``is_mock=True`` / ``provider="mock"`` and that flag is carried through
to ``UserQuery.provenance.transcription`` so mock output can never be mistaken
for a real Sarvam result.
"""

import uuid

from satquery.speech.base import AudioInput, SpeechService, Transcript


class MockSpeechService(SpeechService):
    provider = "mock"
    is_mock = True

    def __init__(
        self,
        transcript: str = "What changed between these two satellite images?",
        language: str | None = "en",
        *,
        error: Exception | None = None,
    ) -> None:
        """
        Args:
            transcript: Text returned for every clip.
            language: Language reported when the caller gives no hint.
            error: If set, raised from ``transcribe`` to simulate provider failures.
        """
        self._transcript = transcript
        self._language = language
        self._error = error
        self.calls: list[tuple[AudioInput, str | None]] = []

    async def transcribe(self, audio: AudioInput, *, language: str | None = None) -> Transcript:
        self.calls.append((audio, language))
        if self._error is not None:
            raise self._error
        return Transcript(
            text=self._transcript,
            language=language or self._language,
            provider=self.provider,
            model="mock-stt",
            is_mock=True,
            request_id=f"mock_{uuid.uuid4().hex[:12]}",
        )

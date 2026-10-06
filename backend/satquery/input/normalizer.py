"""Input normaliser: turns text-or-voice requests into a single ``UserQuery``.

    RawQueryInput (from any transport)
        -> validate modality (exactly one of text / voice)
        -> text:  clean
           voice: validate audio -> SpeechService.transcribe -> clean transcript
        -> resolve language and session
        -> UserQuery (validated, immutable)

Nothing downstream of this module knows whether the user typed or spoke.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from satquery.core.errors import InputValidationError, validation_error_from_pydantic
from satquery.core.languages import normalize_language_code
from satquery.input.schemas import (
    AttachmentRef,
    InputProvenance,
    InputType,
    LanguageSource,
    TranscriptionInfo,
    UserQuery,
)
from satquery.input.validators import clean_text, generate_session_id, validate_audio
from satquery.speech.base import AudioInput, SpeechService, Transcript
from satquery.speech.errors import EmptyTranscriptError

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RawQueryInput:
    """A parsed but not yet normalised request, independent of HTTP transport.

    Field-level shape checks (language code, session id format, attachment
    schema) have already been applied by the transport's request model.
    """

    text: str | None = None
    audio: AudioInput | None = None
    language: str | None = None
    session_id: str | None = None
    attachments: Sequence[AttachmentRef] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormalizerConfig:
    default_language: str = "en"
    max_query_chars: int = 2000
    max_audio_bytes: int = 10 * 1024 * 1024
    max_audio_seconds: float = 30.0
    max_attachments: int = 16


class InputNormalizer:
    def __init__(self, speech_service: SpeechService, config: NormalizerConfig | None = None) -> None:
        self._speech = speech_service
        self._config = config or NormalizerConfig()

    async def normalize(self, raw: RawQueryInput) -> UserQuery:
        input_type = self._resolve_input_type(raw)
        self._check_attachment_count(raw.attachments)

        transcription: TranscriptionInfo | None = None
        detected_language: str | None = None
        if input_type is InputType.TEXT:
            assert raw.text is not None
            query = self._normalize_text(raw.text)
        else:
            assert raw.audio is not None
            audio = validate_audio(
                raw.audio,
                max_bytes=self._config.max_audio_bytes,
                max_seconds=self._config.max_audio_seconds,
            )
            transcript = await self._speech.transcribe(audio, language=raw.language)
            query = self._normalize_transcript(transcript)
            detected_language = _supported_or_none(transcript.language)
            transcription = TranscriptionInfo(
                provider=transcript.provider,
                model=transcript.model,
                is_mock=transcript.is_mock,
                request_id=transcript.request_id,
                language_probability=transcript.language_probability,
                audio_format=audio.format.value if audio.format else None,
                audio_duration_seconds=audio.duration_seconds,
                audio_size_bytes=audio.size_bytes,
            )

        language, language_source = self._resolve_language(raw.language, detected_language)
        session_generated = raw.session_id is None
        session_id = raw.session_id or generate_session_id()

        try:
            user_query = UserQuery(
                query=query,
                input_type=input_type,
                language=language,
                session_id=session_id,
                attachments=tuple(raw.attachments),
                metadata=dict(raw.metadata),
                provenance=InputProvenance(
                    language_source=language_source,
                    session_generated=session_generated,
                    transcription=transcription,
                ),
            )
        except ValidationError as exc:
            raise validation_error_from_pydantic(exc) from None

        logger.info(
            "Normalised query %s: input_type=%s language=%s(%s) session=%s chars=%d attachments=%d%s",
            user_query.query_id,
            input_type.value,
            language,
            language_source.value,
            session_id,
            len(query),
            len(user_query.attachments),
            " [MOCK STT]" if transcription and transcription.is_mock else "",
        )
        return user_query

    @staticmethod
    def _resolve_input_type(raw: RawQueryInput) -> InputType:
        has_voice = raw.audio is not None
        has_text = raw.text is not None and (bool(raw.text.strip()) or not has_voice)
        # Blank text alongside a voice clip is treated as absent (common with HTML forms).
        if has_text and has_voice:
            raise InputValidationError(
                "Provide either 'text' or 'voice', not both.", code="ambiguous_input"
            )
        if has_voice:
            return InputType.VOICE
        if has_text:
            return InputType.TEXT
        raise InputValidationError(
            "The request must include either 'text' or 'voice'.", code="missing_input"
        )

    def _check_attachment_count(self, attachments: Sequence[AttachmentRef]) -> None:
        if len(attachments) > self._config.max_attachments:
            raise InputValidationError(
                f"At most {self._config.max_attachments} attachments are allowed per query.",
                code="too_many_attachments",
                field="attachments",
            )

    def _normalize_text(self, text: str) -> str:
        query = clean_text(text)
        if not query:
            raise InputValidationError("'text' must not be empty.", code="empty_text", field="text")
        self._check_length(query, field="text")
        return query

    def _normalize_transcript(self, transcript: Transcript) -> str:
        query = clean_text(transcript.text)
        if not query:
            raise EmptyTranscriptError("No speech could be recognised in the audio.")
        self._check_length(query, field="voice")
        return query

    def _check_length(self, query: str, *, field: str) -> None:
        if len(query) > self._config.max_query_chars:
            raise InputValidationError(
                f"The query is {len(query)} characters; the maximum is {self._config.max_query_chars}.",
                code="query_too_long",
                field=field,
            )

    def _resolve_language(
        self, requested: str | None, detected: str | None
    ) -> tuple[str, LanguageSource]:
        if requested is not None:
            return requested, LanguageSource.USER
        if detected is not None:
            return detected, LanguageSource.DETECTED
        return self._config.default_language, LanguageSource.DEFAULT


def _supported_or_none(language: str | None) -> str | None:
    if language is None:
        return None
    try:
        return normalize_language_code(language)
    except ValueError:
        return None

"""Validation and cleaning primitives for the input layer.

Two kinds of helpers live here:

* Field validators used inside pydantic models (``validate_session_id``,
  ``validate_attachment_uri``, ``validate_metadata``) raise ``ValueError`` so
  pydantic reports them with the offending field.
* Normalizer-level checks (``validate_audio``) raise ``SatQueryError``
  subclasses with specific error codes.
"""

import io
import json
import re
import struct
import unicodedata
import uuid
import wave
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from satquery.core.errors import InputValidationError, PayloadTooLargeError, UnsupportedMediaTypeError
from satquery.speech.base import AudioFormat, AudioInput

# --- session ---------------------------------------------------------------

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,63}")


def validate_session_id(value: str) -> str:
    if not _SESSION_ID.fullmatch(value):
        raise ValueError(
            "session_id must be 3-64 characters of letters, digits, '_' or '-', "
            "starting with a letter or digit"
        )
    return value


def generate_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


# --- text ------------------------------------------------------------------

# C0/C1 control characters except tab/newline/CR (which are whitespace and collapsed anyway).
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean_text(text: str) -> str:
    """Unicode-normalise (NFC), drop control characters and collapse whitespace.

    Zero-width joiners (U+200C/U+200D) are preserved: they are meaningful in
    Indic scripts.
    """
    text = unicodedata.normalize("NFC", text)
    text = _CONTROL_CHARS.sub(" ", text)
    return " ".join(text.split())


# --- attachments -----------------------------------------------------------

ATTACHMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
SENSOR_TYPE_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,63}$"

# Object-storage / HTTP references only. "data:" (inline payloads) and "file:"
# (server-local paths) are rejected on purpose.
ALLOWED_URI_SCHEMES = frozenset({"s3", "gs", "az", "abfs", "https", "http", "satquery"})


def parse_acquisition_time(value: object) -> date | datetime:
    """Parse an ISO 8601 date or datetime, keeping date-only values as ``date``."""
    if isinstance(value, date):  # includes datetime
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text) if len(text) == 10 else datetime.fromisoformat(text)
        except ValueError:
            pass
    raise ValueError(
        "timestamp must be an ISO 8601 date (2026-09-01) or datetime (2026-09-01T10:00:00Z)"
    )


def validate_attachment_uri(value: str) -> str:
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_URI_SCHEMES:
        raise ValueError(
            f"uri scheme '{scheme or '(none)'}' is not allowed; use one of "
            f"{', '.join(sorted(ALLOWED_URI_SCHEMES))}. Attachments must reference stored "
            "files, not carry inline data or local paths"
        )
    if not (parts.netloc or parts.path.strip("/")):
        raise ValueError("uri has no location")
    return value


# --- metadata --------------------------------------------------------------

MAX_METADATA_KEYS = 32
MAX_METADATA_KEY_CHARS = 64
MAX_METADATA_BYTES = 8 * 1024


def validate_metadata(value: dict[str, Any]) -> dict[str, Any]:
    if len(value) > MAX_METADATA_KEYS:
        raise ValueError(f"metadata may contain at most {MAX_METADATA_KEYS} keys")
    for key in value:
        if not key or len(key) > MAX_METADATA_KEY_CHARS:
            raise ValueError(f"metadata keys must be 1-{MAX_METADATA_KEY_CHARS} characters")
    size = len(json.dumps(value, ensure_ascii=False, default=str).encode())
    if size > MAX_METADATA_BYTES:
        raise ValueError(
            f"metadata is too large ({size} bytes, max {MAX_METADATA_BYTES}); "
            "large data belongs in stored files referenced from attachments"
        )
    return value


# --- audio -----------------------------------------------------------------

_WMA_ASF_GUID = bytes.fromhex("3026b2758e66cf11")


def sniff_audio_format(data: bytes) -> AudioFormat | None:
    """Identify the audio container from its magic bytes (client-declared types are not trusted)."""
    head = data[:16]
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return AudioFormat.WAV
    if head[:4] == b"FORM" and head[8:12] in (b"AIFF", b"AIFC"):
        return AudioFormat.AIFF
    if head[:4] == b"OggS":
        return AudioFormat.OGG
    if head[:4] == b"fLaC":
        return AudioFormat.FLAC
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return AudioFormat.WEBM
    if head[4:8] == b"ftyp":
        return AudioFormat.MP4
    if head[:5] == b"#!AMR":
        return AudioFormat.AMR
    if head[:8] == _WMA_ASF_GUID:
        return AudioFormat.WMA
    if head[:3] == b"ID3":
        return AudioFormat.MP3
    if len(head) >= 2 and head[0] == 0xFF:
        if head[1] & 0xF6 == 0xF0:  # ADTS sync word, layer bits 00
            return AudioFormat.AAC
        if head[1] & 0xE0 == 0xE0:  # MPEG audio frame sync
            return AudioFormat.MP3
    return None


def _wav_duration_seconds(data: bytes) -> float | None:
    """Duration of a PCM WAV clip, or ``None`` for WAV encodings the stdlib cannot read."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
    except (EOFError, struct.error):
        raise InputValidationError(
            "The WAV audio is truncated or corrupt.", code="invalid_audio", field="voice"
        ) from None
    except wave.Error as exc:
        if str(exc).startswith("unknown format"):
            return None  # e.g. IEEE float / mu-law WAV: valid, but we leave checks to the provider
        raise InputValidationError(
            "The WAV audio is malformed.", code="invalid_audio", field="voice"
        ) from None
    if rate <= 0:
        raise InputValidationError(
            "The WAV audio has an invalid sample rate.", code="invalid_audio", field="voice"
        )
    if frames == 0:
        raise InputValidationError(
            "The audio contains no samples.", code="empty_audio", field="voice"
        )
    return frames / rate


def validate_audio(audio: AudioInput, *, max_bytes: int, max_seconds: float) -> AudioInput:
    """Check an uploaded clip and return it annotated with its sniffed format and duration."""
    if audio.size_bytes == 0:
        raise InputValidationError("The uploaded audio is empty.", code="empty_audio", field="voice")
    if audio.size_bytes > max_bytes:
        raise PayloadTooLargeError(
            f"Audio is {audio.size_bytes} bytes; the maximum is {max_bytes} bytes.",
            code="audio_too_large",
        )

    fmt = sniff_audio_format(audio.data)
    if fmt is None:
        supported = ", ".join(f.value for f in AudioFormat)
        message = f"Unsupported or unrecognised audio format. Supported formats: {supported}."
        raise UnsupportedMediaTypeError(
            message,
            code="unsupported_audio_format",
            details=[{"field": "voice", "message": message, "type": "unsupported_audio_format"}],
        )

    duration = _wav_duration_seconds(audio.data) if fmt is AudioFormat.WAV else None
    if duration is not None and duration > max_seconds:
        raise InputValidationError(
            f"Audio is {duration:.1f} s long; the maximum is {max_seconds:g} s.",
            code="audio_too_long",
            field="voice",
        )
    return replace(audio, format=fmt, duration_seconds=duration)

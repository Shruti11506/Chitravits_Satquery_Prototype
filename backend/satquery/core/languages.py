"""Language codes supported by SatQuery.

SatQuery identifies languages internally by their ISO 639 base code (``en``,
``hi``, ``mr``, ...). Regional BCP-47 tags such as ``hi-IN`` are accepted on
input and reduced to the base code. Provider-specific codes (e.g. Sarvam's
``od-IN`` for Odia) are mapped inside each provider adapter, never here.

The supported set is English plus the Indian languages covered by Sarvam STT.
"""

import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

SUPPORTED_LANGUAGES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "en": "English",
        "hi": "Hindi",
        "bn": "Bengali",
        "gu": "Gujarati",
        "kn": "Kannada",
        "ml": "Malayalam",
        "mr": "Marathi",
        "or": "Odia",
        "pa": "Punjabi",
        "ta": "Tamil",
        "te": "Telugu",
        "as": "Assamese",
        "ur": "Urdu",
        "ne": "Nepali",
        "kok": "Konkani",
        "ks": "Kashmiri",
        "sd": "Sindhi",
        "sa": "Sanskrit",
        "sat": "Santali",
        "mni": "Manipuri",
        "brx": "Bodo",
        "mai": "Maithili",
        "doi": "Dogri",
    }
)

# Non-standard codes seen in the wild, mapped to the ISO code we use.
_ALIASES: Final[Mapping[str, str]] = MappingProxyType({"od": "or"})

_LANGUAGE_TAG = re.compile(r"([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]{1,8})*")


def normalize_language_code(value: str) -> str:
    """Return the supported ISO 639 base code for ``value``.

    Accepts ``"hi"``, ``"HI"``, ``"hi-IN"``, ``"hi_IN"`` and returns ``"hi"``.
    Raises ``ValueError`` for malformed or unsupported codes.
    """
    match = _LANGUAGE_TAG.fullmatch(value.strip())
    if match is None:
        raise ValueError(
            f"'{value}' is not a valid language code; "
            "expected an ISO 639 code such as 'en', 'hi' or 'mr'"
        )
    base = match.group(1).lower()
    base = _ALIASES.get(base, base)
    if base not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"language '{value}' is not supported; "
            f"supported codes: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return base

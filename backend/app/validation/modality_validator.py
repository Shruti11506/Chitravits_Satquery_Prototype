"""Modality / Sensor Compatibility (task brief section 5).

Determines what kind of image this is -- "rgb", "optical", "multispectral",
"sar", or "unknown" -- and never from the filename. In order of trust:

1. An explicit `modality_hint` on the request (the caller states it).
2. The raster's own band names/colour-interpretation (real structure).
3. `sensor`/`source` -- structured metadata columns filled in at upload
   time (a form field the user typed a sensor name into), which is
   "uploaded metadata" in the brief's sense, NOT the filename. Only
   consulted for the cases band structure alone couldn't resolve, and only
   against a small, explicit term list -- never a fuzzy guess.

If none of that identifies a modality a required workflow needs,
`detect_modality` returns "unknown" rather than guessing, and
`modality_issues` rejects with MODALITY_MISMATCH (brief section 5: "If
modality cannot be reliably established when it is required, return a
validation error instead of guessing").
"""
from __future__ import annotations

import re

from app.validation.band_validator import detect_named_bands
from app.validation.errors import MODALITY_MISMATCH, ValidationIssue
from app.validation.raster_validator import PILLOW_EXTENSIONS
from app.validation.schemas import Modality, RasterFacts

_SAR_TERMS = re.compile(r"\b(sar|radar|sentinel[- ]?1|s1[ab]?|grd|slc|risat|iceye|capella|terrasar)\b", re.IGNORECASE)
_OPTICAL_TERMS = re.compile(
    r"\b(optical|rgb|sentinel[- ]?2|s2[ab]?|msi|landsat|cartosat|worldview|pleiades|planetscope)\b", re.IGNORECASE
)

_SAR_BANDS = frozenset({"vv", "vh", "hh", "hv"})
_MULTISPECTRAL_BANDS = frozenset({"nir", "swir1", "swir2"})


def detect_modality(facts: RasterFacts, *, extension: str, sensor: str | None, source: str | None, hint: str | None) -> Modality:
    if hint:
        return hint

    detected_bands = detect_named_bands(facts)
    if detected_bands.keys() & _SAR_BANDS:
        return "sar"
    if detected_bands.keys() & _MULTISPECTRAL_BANDS:
        return "multispectral"
    if facts.band_count and facts.band_count > 3:
        return "multispectral"
    if {"red", "green", "blue"} <= detected_bands.keys():
        return "rgb"
    if extension in PILLOW_EXTENSIONS:
        return "rgb"  # a decoded JPEG/PNG pixel buffer is RGB by construction

    # Structural signal alone is exhausted; fall back to explicit,
    # user-entered sensor metadata or dataset tags for ambiguous cases
    tags_text = " ".join(facts.tags.values()) if getattr(facts, "tags", None) else ""
    metadata_text = " ".join(filter(None, (sensor, source, tags_text)))
    if metadata_text:
        if facts.band_count and facts.band_count <= 2 and _SAR_TERMS.search(metadata_text):
            return "sar"
        if facts.band_count and facts.band_count <= 3 and _OPTICAL_TERMS.search(metadata_text):
            return "optical"
        if facts.band_count and facts.band_count > 3 and _OPTICAL_TERMS.search(metadata_text):
            return "multispectral"

    return "unknown"


def modality_issues(
    detected: Modality, allowed: list[str] | dict[str, list[str]] | None, *, role: str, workflow_label: str, input_label: str
) -> list[ValidationIssue]:
    if allowed is None:
        return []
    candidates = allowed.get(role) if isinstance(allowed, dict) else allowed
    if candidates is None or detected in candidates:
        return []

    if detected == "unknown":
        message = (
            f"{workflow_label} requires imagery of type {_join(candidates)}, but this image's modality "
            "could not be determined from its metadata. Supply it explicitly (modality_hint)."
        )
    else:
        message = f"{workflow_label} requires imagery of type {_join(candidates)}; this image is '{detected}'."
    return [ValidationIssue.of(MODALITY_MISMATCH, message, input=input_label)]


def _join(values: list[str]) -> str:
    return " or ".join(f"'{v}'" for v in values)

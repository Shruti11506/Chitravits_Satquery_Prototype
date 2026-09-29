"""Sensor identification for the four sensors SatQuery supports:
Sentinel-1 (SAR), Sentinel-2 (MSI), Cartosat (optical PAN/MX) and RISAT (SAR).

`identify_sensor` answers "which sensor produced this file?" from real
evidence only, and records WHICH evidence decided it. In priority order:

1. `db_sensor` / `db_source` -- the `imagery.sensor` / `imagery.source`
   columns (the upload form's `sensor` / `source` fields).
2. `tiff_tag` -- the raster's own dataset tags (e.g. SPACECRAFT_NAME).
3. `band_metadata` -- band descriptions / per-band tags that NAME a sensor.
4. `filename` -- product-ID patterns (S1A_IW_GRDH_..., S2B_MSIL2A_...,
   LC08_...) and sensor names in the filename.
5. `band_naming` -- the one band-naming convention unique to a single
   sensor: a band described as "B8A" exists only on Sentinel-2.

The filename is evidence for the SENSOR only. It never decides a band's
identity or an image's modality directly -- `band_validator` and
`modality_validator` read those from the raster's own structure, and use the
sensor only to pick which sensor-specific band table applies.

Outcomes: `supported` (one of the four families), `unsupported` (a sensor
was recognised but is outside this scope, e.g. Landsat -- UNSUPPORTED_SENSOR)
or `unknown` (no evidence -- UNKNOWN_SENSOR, but only for workflows that
need sensor-specific interpretation; see `WorkflowRequirements.
requires_known_sensor` / `ChangeDetectionRequirements.require_known_sensor`).

Deliberately small and table-driven: this is not a universal satellite
catalogue, and no wavelength-based interpretation is attempted.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.validation.schemas import RasterFacts


class SensorFamily(str, Enum):
    SENTINEL_1 = "sentinel-1"
    SENTINEL_2 = "sentinel-2"
    CARTOSAT = "cartosat"
    RISAT = "risat"


SensorStatus = Literal["supported", "unsupported", "unknown"]
SAR_FAMILIES = frozenset({SensorFamily.SENTINEL_1, SensorFamily.RISAT})


@dataclass(frozen=True)
class SensorIdentification:
    status: SensorStatus
    family: SensorFamily | None = None
    product: str | None = None  # e.g. "S2 L2A", "S1 GRD", "Cartosat MX"
    source: str | None = None  # which evidence decided it (see module docstring)
    raw_value: str | None = None  # the text that matched

    @property
    def label(self) -> str:
        if self.family is not None:
            return self.family.value
        if self.status == "unsupported":
            return self.raw_value or "unsupported sensor"
        return "unknown"

    @property
    def is_supported(self) -> bool:
        return self.status == "supported"


UNKNOWN_SENSOR_ID = SensorIdentification(status="unknown")

# ---- evidence patterns ----------------------------------------------------------
# Free-text patterns run on NORMALISED text: lower-case, every run of
# non-alphanumerics collapsed to one space ("Sentinel-2A" -> "sentinel 2a",
# "S1A_IW_GRDH" -> "s1a iw grdh"), so \b works across _ - . separators.

_SUPPORTED_TEXT_PATTERNS: tuple[tuple[SensorFamily, re.Pattern], ...] = (
    (SensorFamily.SENTINEL_1, re.compile(r"\bsentinel ?1[a-d]?\b|\bs1[a-d]\b")),
    (SensorFamily.SENTINEL_2, re.compile(r"\bsentinel ?2[a-d]?\b|\bs2[a-d]\b|\bmsil[12][ac]\b|\bs2msi[12][ac]\b")),
    # TODO(team): confirm the RISAT / Cartosat naming our data actually uses.
    (SensorFamily.RISAT, re.compile(r"\brisat ?(1a|1b|2br1|2b|1|2)?\b|\beos ?04\b")),
    (SensorFamily.CARTOSAT, re.compile(r"\bcartosat ?(1|2|2a|2b|2c|2d|2e|2f|3|3a|3b)?\b|\bc2s\b|\bc3\b")),
)

# Recognised, but outside the supported scope -> UNSUPPORTED_SENSOR. Extend
# as needed; a sensor absent from both lists is simply "unknown".
_UNSUPPORTED_TEXT_PATTERN = re.compile(
    r"\b(landsat ?\d*|sentinel ?3[ab]?|planetscope|planet ?scope|skysat|dove|worldview ?\d*|"
    r"pleiades|spot ?[1-7]|iceye|capella|terrasar ?x?|tandem ?x|cosmo ?skymed|alos ?\d*|palsar ?\d*|"
    r"radarsat ?\d*|modis|resourcesat ?\d*|gaofen ?\d*|kompsat ?\d*|superview ?\d*|nisar)\b"
)

# Filename product-ID patterns (run on the lower-cased basename, NOT normalised).
_SUPPORTED_FILENAME_PATTERNS: tuple[tuple[SensorFamily, re.Pattern], ...] = (
    (SensorFamily.SENTINEL_1, re.compile(r"^s1[a-d]_(iw|ew|sm|wv)_")),
    (SensorFamily.SENTINEL_2, re.compile(r"^s2[a-d]_msil[12][ac]_")),
    # Sentinel-2 single-band granule file, e.g. T43PGQ_20240101T050211_B04_10m.tif
    (SensorFamily.SENTINEL_2, re.compile(r"^t\d{2}[a-z]{3}_\d{8}t\d{6}_b(0[1-9]|1[0-2]|8a)")),
)
_UNSUPPORTED_FILENAME_PATTERN = re.compile(r"^l[coetm]0[1-9]_")  # Landsat product IDs, e.g. LC08_L2SP_...

_TAG_KEYS_FIRST = (
    "SPACECRAFT_NAME", "SPACECRAFT", "SATELLITE", "SATELLITE_NAME", "MISSION", "MISSION_ID",
    "PLATFORM", "SENSOR", "SENSOR_ID", "INSTRUMENT", "PRODUCT_TYPE", "PRODUCT_ID", "TIFFTAG_IMAGEDESCRIPTION",
)


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _product(family: SensorFamily, text: str) -> str | None:
    """Product label, only when the matched text states it -- never assumed."""
    norm = _normalise(text)
    if family == SensorFamily.SENTINEL_2:
        if re.search(r"\bmsil1c\b|\bs2msi1c\b|\bl1c\b", norm):
            return "S2 L1C"
        if re.search(r"\bmsil2a\b|\bs2msi2a\b|\bl2a\b", norm):
            return "S2 L2A"
    elif family == SensorFamily.SENTINEL_1:
        if re.search(r"\bgrd[hmf]?\b", norm):
            return "S1 GRD"
        if re.search(r"\bslc\b", norm):
            return "S1 SLC"
    elif family == SensorFamily.CARTOSAT:
        # TODO(team): confirm Cartosat product naming (PAN / MX) from real product metadata.
        if re.search(r"\bpan\b|\bpanchromatic\b", norm):
            return "Cartosat PAN"
        if re.search(r"\bmx\b|\bmss\b|\bmultispectral\b", norm):
            return "Cartosat MX"
    return None


def _match_text(text: str | None, source: str) -> SensorIdentification | None:
    if not text:
        return None
    norm = _normalise(text)
    if not norm:
        return None
    for family, pattern in _SUPPORTED_TEXT_PATTERNS:
        match = pattern.search(norm)
        if match:
            return SensorIdentification("supported", family, _product(family, text), source, match.group(0))
    match = _UNSUPPORTED_TEXT_PATTERN.search(norm)
    if match:
        return SensorIdentification("unsupported", None, None, source, match.group(0))
    return None


def _match_filename(filename: str | None) -> SensorIdentification | None:
    if not filename:
        return None
    base = os.path.basename(filename).lower()
    for family, pattern in _SUPPORTED_FILENAME_PATTERNS:
        match = pattern.search(base)
        if match:
            return SensorIdentification("supported", family, _product(family, base), "filename", match.group(0))
    match = _UNSUPPORTED_FILENAME_PATTERN.search(base)
    if match:
        return SensorIdentification("unsupported", None, None, "filename", match.group(0).rstrip("_"))
    return _match_text(base.rsplit(".", 1)[0], "filename")


def _match_tags(facts: RasterFacts | None) -> SensorIdentification | None:
    tags = (facts.tags if facts else None) or {}
    if not tags:
        return None
    upper = {str(key).upper(): value for key, value in tags.items()}
    ordered = [upper[key] for key in _TAG_KEYS_FIRST if key in upper]
    ordered += [value for key, value in upper.items() if key not in _TAG_KEYS_FIRST]
    for value in ordered:
        found = _match_text(str(value), "tiff_tag")
        if found:
            return found
    return None


def _match_band_metadata(facts: RasterFacts | None) -> SensorIdentification | None:
    if facts is None:
        return None
    texts = [d for d in facts.band_descriptions if d]
    for btags in facts.band_tags or []:
        texts.extend(str(v) for v in (btags or {}).values())
    for text in texts:
        found = _match_text(text, "band_metadata")
        if found:
            return found
    return None


def _match_band_naming(facts: RasterFacts | None) -> SensorIdentification | None:
    """"B8A" (Sentinel-2's narrow-NIR band) is a band ID no other mission
    uses, so a band described exactly that way is Sentinel-2 evidence.
    Plain B-numbers (B4, B08, ...) are NOT: Landsat reuses them for
    different bands (Landsat 8 B8 = panchromatic, Sentinel-2 B8 = NIR)."""
    if facts is None:
        return None
    for description in facts.band_descriptions:
        if description and description.strip().lower() in ("b8a", "b08a"):
            return SensorIdentification("supported", SensorFamily.SENTINEL_2, None, "band_naming", description.strip())
    return None


def identify_sensor(
    *,
    sensor: str | None = None,
    source: str | None = None,
    filename: str | None = None,
    facts: RasterFacts | None = None,
) -> SensorIdentification:
    """See the module docstring. Never raises; no evidence -> `unknown`.

    A modality hint is deliberately NOT an input: "sar" says nothing about
    whether the image came from Sentinel-1, RISAT or ICEYE."""
    for found in (
        _match_text(sensor, "db_sensor"),
        _match_text(source, "db_source"),
        _match_tags(facts),
        _match_band_metadata(facts),
        _match_filename(filename),
        _match_band_naming(facts),
    ):
        if found is not None:
            return found
    return UNKNOWN_SENSOR_ID

"""Resolve which raster band supplies NIR / RED / GREEN / SWIR / ….

Deterministic index tools need to know *which band index* is NIR, Red, etc.
That is resolved in priority order (Tools.docx §9 band compatibility):

1. Explicit band designations on the DataProfile ("B04 (Red…)" → RED), or an
   explicit polarization ("VV"/"VH").
2. A conventional band order for common Sentinel-1/2 stacks, keyed on band count.

If a required band cannot be resolved, ``require`` raises ``MissingBandError``
with a message naming what was needed and what was available — never a silent
wrong-band computation (spec §51).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Logical band name -> the Sentinel-2 designation that canonically supplies it.
LOGICAL_TO_S2 = {
    "BLUE": "B02", "GREEN": "B03", "RED": "B04",
    "REDEDGE1": "B05", "REDEDGE2": "B06", "REDEDGE3": "B07",
    "NIR": "B08", "NARROW_NIR": "B8A",
    "SWIR1": "B11", "SWIR2": "B12",
}
# Reverse: designation -> logical name.
S2_TO_LOGICAL = {v: k for k, v in LOGICAL_TO_S2.items()}
# Common aliases callers may use.
_ALIASES = {"SWIR": "SWIR1", "B8": "B08", "B8A": "B8A"}

# Conventional band orders (1-based index -> designation) by band count.
# Optical stacks are the usual Sentinel-2 subsets; full 12/13-band L1C/L2A order.
_CONVENTIONS: dict[int, list[str]] = {
    3: ["B04", "B03", "B02"],                                  # RGB
    4: ["B02", "B03", "B04", "B08"],                           # 10 m stack
    6: ["B02", "B03", "B04", "B08", "B11", "B12"],             # + SWIR
    10: ["B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B11", "B12"],
    12: ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B11", "B12"],
    13: ["B01", "B02", "B03", "B04", "B05", "B06", "B07", "B08", "B8A", "B09", "B10", "B11", "B12"],
}

_DESIG_RE = re.compile(r"\b(B0?\d{1,2}A?)\b", re.IGNORECASE)


class MissingBandError(Exception):
    """A required band could not be resolved from the raster."""

    def __init__(self, required: list[str], available: list[str], tool: str = "") -> None:
        self.code = "MISSING_BAND"
        self.required = required
        self.available = available
        need = ", ".join(required)
        have = ", ".join(available) if available else "(unlabelled bands)"
        prefix = f"{tool} requires " if tool else "Requires "
        super().__init__(f"{prefix}{need}. Available bands: {have}.")


def _norm_designation(text: str | None) -> str | None:
    """Extract a canonical designation like 'B04' or 'B8A' from a label."""
    if not text:
        return None
    m = _DESIG_RE.search(text)
    if not m:
        return None
    token = m.group(1).upper()
    if token.endswith("A"):
        return token if token == "B8A" else token  # B8A special-case
    # Zero-pad single-digit ("B8" -> "B08").
    num = token[1:]
    return f"B{int(num):02d}"


@dataclass
class BandResolver:
    """Maps logical/designation band names to 1-based raster band indices."""

    designation_to_index: dict[str, int]        # "B04" -> 3
    polarization_to_index: dict[str, int]        # "VV" -> 1
    band_count: int

    @classmethod
    def from_profile(cls, profile) -> "BandResolver":
        """Build from a DataProfile's BandInfo list, falling back to convention."""
        desig: dict[str, int] = {}
        polar: dict[str, int] = {}
        for b in profile.bands:
            d = _norm_designation(b.designation)
            if d:
                desig.setdefault(d, b.band_index)
            if getattr(b, "polarization", None):
                polar.setdefault(b.polarization.upper(), b.band_index)
        count = profile.band_count or len(profile.bands)
        if not desig and count in _CONVENTIONS:
            desig = {d: i + 1 for i, d in enumerate(_CONVENTIONS[count])}
        return cls(desig, polar, count)

    @classmethod
    def from_band_count(cls, band_count: int) -> "BandResolver":
        conv = _CONVENTIONS.get(band_count, {})
        desig = {d: i + 1 for i, d in enumerate(conv)}
        return cls(desig, {}, band_count)

    # -- resolution ------------------------------------------------------

    def index_of(self, name: str) -> int | None:
        """Resolve a logical name / designation / polarization to a band index."""
        key = _ALIASES.get(name.upper(), name.upper())
        # Polarization (SAR)
        if key in self.polarization_to_index:
            return self.polarization_to_index[key]
        # Logical name -> designation
        if key in LOGICAL_TO_S2:
            key = LOGICAL_TO_S2[key]
        # Designation
        d = _norm_designation(key) or key
        return self.designation_to_index.get(d)

    def require(self, names: list[str], tool: str = "") -> dict[str, int]:
        """Resolve all names or raise MissingBandError naming the gaps."""
        resolved: dict[str, int] = {}
        missing: list[str] = []
        for n in names:
            idx = self.index_of(n)
            if idx is None:
                missing.append(n)
            else:
                resolved[n] = idx
        if missing:
            available = sorted(self.designation_to_index) + sorted(self.polarization_to_index)
            raise MissingBandError(missing, available, tool)
        return resolved

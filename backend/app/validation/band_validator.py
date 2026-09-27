"""Band / Channel Compatibility (task brief section 6).

Band identity comes ONLY from the raster's own band descriptions/colour
interpretation -- never from a filename, and never guessed when a TIFF
carries no band names at all (an unnamed band stays "unidentified": a
workflow that requires a specific band then rejects it as BAND_MISSING
rather than assuming which band it might be).

`positional_band_issues` is what enforces "VV -> VV and VH -> VH": for a
multi-image workflow that requires the SAME band at every position (e.g.
SAR change detection), an image that has a *different*, identifiable band
instead of the required one is a BAND_MISMATCH (it IS SAR, just the wrong
polarization) -- an image with no identifiable band at all is BAND_MISSING
(nothing to compare).
"""
from __future__ import annotations

from app.validation.errors import BAND_MISMATCH, BAND_MISSING, ValidationIssue
from app.validation.schemas import RasterFacts

# canonical band name -> the tokens (band description / colour-interp name,
# case-insensitive, exact match) that identify it. Extend this table to
# recognise more bands; nothing elsewhere needs to change.
BAND_ALIASES: dict[str, tuple[str, ...]] = {
    "red": ("red", "r", "b4", "b04"),
    "green": ("green", "g", "b3", "b03"),
    "blue": ("blue", "b", "b2", "b02"),
    "nir": ("nir", "near-infrared", "near infrared", "b8", "b08", "b8a", "b08a"),
    "swir1": ("swir1", "swir-1", "swir 1", "b11"),
    "swir2": ("swir2", "swir-2", "swir 2", "b12"),
    "vv": ("vv",),
    "vh": ("vh",),
    "hh": ("hh",),
    "hv": ("hv",),
}
# Bands that are structurally "the same kind of thing" as one another, used
# only to phrase BAND_MISMATCH sensibly (e.g. VH present where VV is
# required is a polarization mismatch, worth naming as such).
_FAMILIES: tuple[frozenset[str], ...] = (
    frozenset({"vv", "vh", "hh", "hv"}),
    frozenset({"red", "green", "blue", "nir", "swir1", "swir2"}),
)

_COLOR_INTERP_ALIAS = {"red": "red", "green": "green", "blue": "blue"}


def detect_named_bands(facts: RasterFacts) -> dict[str, int]:
    """canonical band name -> 1-based band index, for every band this
    raster's own metadata identifies. Never invents a name for an
    undescribed band."""
    found: dict[str, int] = {}

    for index, description in enumerate(facts.band_descriptions, start=1):
        token = (description or "").strip().lower()
        if not token:
            continue
        for canonical, aliases in BAND_ALIASES.items():
            if token in aliases and canonical not in found:
                found[canonical] = index

    # Fallback for red/green/blue via GDAL's own colour-interpretation tag
    # (real GeoTIFF RGB rasters usually carry this even with no band names) --
    # the same technique raster_service._pick_bands() uses for previews.
    for index, interp in enumerate(facts.color_interpretation, start=1):
        canonical = _COLOR_INTERP_ALIAS.get(interp.lower())
        if canonical and canonical not in found:
            found[canonical] = index

    return found


def _family_of(band: str) -> frozenset[str] | None:
    return next((family for family in _FAMILIES if band in family), None)


def missing_band_issues(
    facts: RasterFacts, required: list[str], *, input_label: str
) -> tuple[list[ValidationIssue], dict[str, int]]:
    """BAND_MISSING for each band in `required` this image doesn't have.
    Returns the issues plus the full set of bands the image DOES have, so a
    caller doing cross-image comparison doesn't need to re-detect them."""
    detected = detect_named_bands(facts)
    issues = [
        ValidationIssue.of(
            BAND_MISSING, f"Required band '{band}' was not found in this image.", input=input_label
        )
        for band in required
        if band not in detected
    ]
    return issues, detected


def positional_band_issues(
    images: list[tuple[str, RasterFacts]], required_bands: list[list[str]], *, workflow_label: str
) -> list[ValidationIssue]:
    """`required_bands[i]` = the bands image `images[i]` must have. When every
    position requires the exact same single band (the VV<->VV / VH<->VH
    rule), a position missing it gets BAND_MISMATCH -- naming what it has
    instead -- if it has a same-family band, else the plain BAND_MISSING."""
    issues: list[ValidationIssue] = []
    same_band_everywhere = (
        len(required_bands) > 1
        and all(len(req) == 1 for req in required_bands)
        and len({req[0] for req in required_bands}) == 1
    )
    required_single = required_bands[0][0] if same_band_everywhere else None

    for (label, facts), required in zip(images, required_bands):
        band_issues, detected = missing_band_issues(facts, required, input_label=label)
        if not band_issues:
            continue
        if same_band_everywhere and required_single not in detected:
            family = _family_of(required_single)
            mismatch = next((b for b in detected if family and b in family), None)
            if mismatch:
                issues.append(ValidationIssue.of(
                    BAND_MISMATCH,
                    f"{workflow_label} requires '{required_single.upper()}' input for every image; "
                    f"{label} provides '{mismatch.upper()}' instead.",
                    input=label,
                ))
                continue
        issues.extend(band_issues)
    return issues

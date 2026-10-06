"""Evidence validation (spec §34).

Lightweight, real-time checks — not benchmark metrics. Each check returns
PASS / WARNING / FAIL with a human-readable reason, and an item's overall
status is the worst of its checks. The checks follow the compatibility (§9)
and geospatial-correctness (§15) perspectives in Tools.docx:

- geospatial : does a spatial evidence item carry a CRS/extent?
- modality   : does a SAR/optical evidence item match its source modality?
- band       : were the bands a spectral index needs actually present?
- temporal   : does a change/temporal item have two comparable dates?
- spatial    : does the evidence fall within the requested AOI (when given)?
- consistency: do items that measure the same thing agree? (cross-item)
"""

from __future__ import annotations

from satquery.evidence.schemas import (
    EvidenceItem,
    EvidenceType,
    ValidationCheck,
    ValidationStatus,
)
from satquery.preprocessor.schemas import AOIContext

# Bands each spectral index requires (Sentinel-2 designations), from Tools.docx §5/§13–21.
_INDEX_BANDS: dict[str, list[str]] = {
    "ndvi": ["B08", "B04"],
    "ndwi": ["B03", "B08"],
    "mndwi": ["B03", "B11"],
    "ndmi": ["B08", "B11"],
    "ndbi": ["B11", "B08"],
    "nbr": ["B08", "B12"],
    "savi": ["B08", "B04"],
    "evi": ["B08", "B04", "B02"],
    "bai": ["B08", "B04"],
}

_SPATIAL_TYPES = frozenset({
    EvidenceType.CHANGE_MASK, EvidenceType.SEGMENTATION_MASK, EvidenceType.GROUNDING_BOX,
    EvidenceType.SPECTRAL_INDEX, EvidenceType.SAR_FEATURE, EvidenceType.SAR_OTSU,
    EvidenceType.WATER_MASK, EvidenceType.COORDINATES,
})
_SAR_TYPES = frozenset({EvidenceType.SAR_FEATURE, EvidenceType.SAR_OTSU})
_OPTICAL_MODALITIES = frozenset({"optical", "multispectral", "ms"})
_TEMPORAL_TYPES = frozenset({EvidenceType.CHANGE_MASK, EvidenceType.TEMPORAL_METADATA})


def _check_geospatial(item: EvidenceItem) -> ValidationCheck | None:
    if item.type not in _SPATIAL_TYPES:
        return None
    if item.provenance.crs:
        return ValidationCheck(name="geospatial", status=ValidationStatus.PASS,
                               detail=f"georeferenced ({item.provenance.crs})")
    return ValidationCheck(
        name="geospatial", status=ValidationStatus.WARNING,
        detail="Geographic coordinates unavailable: source has no CRS metadata.",
    )


def _check_modality(item: EvidenceItem) -> ValidationCheck | None:
    modality = (item.provenance.sensor_modality or "").lower()
    if item.type in _SAR_TYPES:
        if not modality:
            return ValidationCheck(name="modality", status=ValidationStatus.WARNING,
                                   detail="SAR evidence but source modality unknown.")
        if modality != "sar":
            return ValidationCheck(name="modality", status=ValidationStatus.FAIL,
                                   detail=f"SAR evidence derived from '{modality}' source.")
        return ValidationCheck(name="modality", status=ValidationStatus.PASS, detail="SAR source")
    if item.type is EvidenceType.SPECTRAL_INDEX:
        if not modality:
            return ValidationCheck(name="modality", status=ValidationStatus.WARNING,
                                   detail="Optical index but source modality unknown.")
        if modality not in _OPTICAL_MODALITIES:
            return ValidationCheck(name="modality", status=ValidationStatus.FAIL,
                                   detail=f"Optical index derived from '{modality}' source.")
        return ValidationCheck(name="modality", status=ValidationStatus.PASS, detail="optical source")
    return None


def _check_bands(item: EvidenceItem) -> ValidationCheck | None:
    if item.type is not EvidenceType.SPECTRAL_INDEX or not item.subtype:
        return None
    needed = _INDEX_BANDS.get(item.subtype.lower())
    if not needed:
        return None
    available = {b.upper() for b in item.provenance.source_bands}
    if not available:
        return ValidationCheck(name="band", status=ValidationStatus.WARNING,
                               detail=f"Cannot verify bands; {item.subtype.upper()} needs {needed}.")
    missing = [b for b in needed if b.upper() not in available]
    if missing:
        return ValidationCheck(
            name="band", status=ValidationStatus.FAIL,
            detail=f"{item.subtype.upper()} requires {needed}; missing {missing}.",
        )
    return ValidationCheck(name="band", status=ValidationStatus.PASS,
                           detail=f"bands present ({needed})")


def _check_temporal(item: EvidenceItem) -> ValidationCheck | None:
    if item.type not in _TEMPORAL_TYPES:
        return None
    dates = [d for d in item.provenance.acquisition_dates if d]
    if len(set(dates)) >= 2:
        return ValidationCheck(name="temporal", status=ValidationStatus.PASS,
                               detail=f"two dated observations ({sorted(set(dates))})")
    return ValidationCheck(
        name="temporal", status=ValidationStatus.WARNING,
        detail="Change evidence without two distinct acquisition dates.",
    )


def _bounds_intersect(a: list[float], b: list[float]) -> bool:
    # a, b as [west, south, east, north]
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _check_spatial(item: EvidenceItem, aoi_contexts: list[AOIContext]) -> ValidationCheck | None:
    if item.type not in _SPATIAL_TYPES:
        return None
    aois = [a for a in aoi_contexts if a.wgs84_bounds and len(a.wgs84_bounds) == 4]
    if not aois or not item.provenance.spatial_extent:
        return None  # nothing to check against
    ext = item.provenance.spatial_extent
    if any(_bounds_intersect(ext, a.wgs84_bounds) for a in aois):
        return ValidationCheck(name="spatial", status=ValidationStatus.PASS,
                               detail="evidence overlaps requested AOI")
    return ValidationCheck(name="spatial", status=ValidationStatus.WARNING,
                           detail="Evidence extent does not overlap the requested AOI.")


def validate_item(item: EvidenceItem, aoi_contexts: list[AOIContext]) -> EvidenceItem:
    """Attach validation checks to one evidence item and set its overall status."""
    checks = [
        _check_geospatial(item),
        _check_modality(item),
        _check_bands(item),
        _check_temporal(item),
        _check_spatial(item, aoi_contexts),
    ]
    item.checks = [c for c in checks if c is not None]
    return item.recompute_status()


def cross_validate(items: list[EvidenceItem]) -> list[str]:
    """Consistency across items (spec §34): do independent items corroborate?

    Returns human-readable conflict notes and appends a 'consistency' check to
    the items involved. Today this compares the sign of directional change
    measurements (e.g. water/vegetation increase vs decrease) reported by
    different tools.
    """
    conflicts: list[str] = []

    # Group directional change measurements by the quantity name.
    directional: dict[str, list[tuple[str, float]]] = {}
    for item in items:
        for m in item.measurements:
            if m.name in ("change_area", "change_fraction", "ndvi_change", "water_area_change"):
                directional.setdefault(m.name, []).append((item.id, m.value))

    for name, pairs in directional.items():
        signs = {(1 if v > 0 else -1 if v < 0 else 0) for _id, v in pairs}
        if len({s for s in signs if s != 0}) > 1:
            note = f"Conflicting direction for '{name}' across evidence: {pairs}"
            conflicts.append(note)
            involved = {pid for pid, _ in pairs}
            for item in items:
                if item.id in involved:
                    item.checks.append(ValidationCheck(
                        name="consistency", status=ValidationStatus.WARNING, detail=note))
                    item.recompute_status()

    return conflicts

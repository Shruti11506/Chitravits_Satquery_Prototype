"""Change Detection Input Validation: is this T1/T2 pair a compatible input
for bi-temporal change detection?

`validate_change_detection_inputs` is the ONE entry point, and it answers
nothing else -- no change map, no registration, no resampling, no model
call. See the package docstring in `__init__.py` for the shared scope
boundary this module inherits.

Runs the checks in a STRICT order and STOPS at the first one that fails --
unlike the generic `app.validation.service.validate_images`, which collects
every applicable issue. The order (readable -> distinct images -> supported
format -> MODALITY -> format family -> aspect ratio -> exact dimensions ->
bands -> geospatial) matches the *later* of the two Change Detection Input
Validation briefs this module was built against, which is explicit that
modality is the earliest cross-image comparison (right after metadata
extraction) -- checked BEFORE the format-family check below, precisely so
the reported bug (T1 = plain RGB JPEG, T2 = Sentinel-2 multispectral
GeoTIFF) comes back as MODALITY_MISMATCH, the code that brief requires,
rather than FILE_FORMAT_MISMATCH pre-empting it. That later brief's own
step order has no separate "format family" slot at all -- section 10 there
is prose, not a numbered step -- so this module keeps it as its own
follow-up check (`require_matching_format`), placed right after modality
rather than before it.

One further documented departure, needed for the checks to compose
sensibly: CRS equality and per-image geospatial completeness (transform/
bounds present) are run in the opposite order from a first read of either
brief's list -- an image's own CRS/transform/bounds must be complete
before it even makes sense to ask whether T1's CRS equals T2's; checking
equality first could report CRS_MISMATCH against a CRS that doesn't
really exist.

"T1 and T2 are expected to differ": nothing here ever compares pixel
content. The only identity check is that T1 and T2 are not the exact same
stored image (NOT_DISTINCT_OBSERVATIONS) -- that's "you didn't upload two
observations at all", not a content comparison.
"""
from __future__ import annotations

from app.validation import band_validator, dimension_validator, modality_validator
from app.validation.errors import (
    BAND_MISMATCH,
    FILE_CORRUPTED,
    FILE_FORMAT_MISMATCH,
    IMAGE_TYPE_MISMATCH,
    MODALITY_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    UNKNOWN_MODALITY,
    UNSUPPORTED_FORMAT,
)
from app.validation.geospatial_validator import crs_match_issue, geospatial_issues
from app.validation.raster_validator import TIFF_EXTENSIONS
from app.validation.schemas import (
    ChangeDetectionImageMetadata,
    ChangeDetectionIssue,
    ChangeDetectionRequirements,
    ChangeDetectionValidationResult,
)

_SAR_BANDS = frozenset({"vv", "vh", "hh", "hv"})
_MODALITY_LABELS = {
    "optical": "Optical", "rgb": "RGB", "multispectral": "Multispectral",
    "sar": "SAR", "optical_sar": "Optical+SAR", "unknown": "Unknown",
}


def _modality_label(modality: str) -> str:
    return _MODALITY_LABELS.get(modality, modality)


def _detect(image: ChangeDetectionImageMetadata) -> str:
    return modality_validator.detect_modality(
        image.facts, extension=image.extension, sensor=image.sensor, source=image.source, hint=image.modality_hint
    )


def validate_change_detection_inputs(
    t1_metadata: ChangeDetectionImageMetadata,
    t2_metadata: ChangeDetectionImageMetadata,
    workflow_requirements: ChangeDetectionRequirements,
) -> ChangeDetectionValidationResult:
    t1, t2 = t1_metadata, t2_metadata

    # 1. Both files readable?
    unreadable = [
        ChangeDetectionIssue.of(FILE_CORRUPTED, f"{image.label} could not be read: {image.facts.error}", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if image.facts.error
    ]
    if unreadable:
        return ChangeDetectionValidationResult(valid=False, status="REJECT", errors=unreadable)

    checks = {
        "format": True,
        "dimensions": True,
        "aspect_ratio": True,
        "band_count": True,
        "dtype": True,
        "crs": True,
        "transform": True,
    }

    # Distinct images check -- not literally the same stored image
    if t1.imagery_id and t2.imagery_id and t1.imagery_id == t2.imagery_id:
        return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[ChangeDetectionIssue.of(
            NOT_DISTINCT_OBSERVATIONS,
            "T1 and T2 must be two different uploaded images; the same image was submitted for both.",
            t1=t1.label, t2=t2.label,
        )])

    # 2. Supported format?
    missing_format = [
        ChangeDetectionIssue.of(UNSUPPORTED_FORMAT, f"{image.label}'s format could not be determined.", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if not image.facts.format
    ]
    if missing_format:
        checks["format"] = False
        return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=missing_format)

    # 3. Modality Compatibility Check (KNOWN INCOMPATIBILITY)
    # UNKNOWN + UNKNOWN is NOT automatically invalid -- continue deeper structural validation.
    # Only reject here if BOTH modalities are KNOWN and genuinely incompatible (e.g. RGB vs SAR).
    modality_1, modality_2 = _detect(t1), _detect(t2)
    if modality_1 != "unknown" and modality_2 != "unknown" and modality_1 != modality_2:
        return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[ChangeDetectionIssue.of(
            IMAGE_TYPE_MISMATCH,
            f"{t1.label} and {t2.label} have incompatible image types for change detection.",
            t1=_modality_label(modality_1), t2=_modality_label(modality_2),
        )])

    # 4. Format family match between T1 and T2 (TIFF vs image)
    if workflow_requirements.require_matching_format:
        family_1 = "tiff" if t1.extension in TIFF_EXTENSIONS else "image"
        family_2 = "tiff" if t2.extension in TIFF_EXTENSIONS else "image"
        if family_1 != family_2:
            checks["format"] = False
            return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[ChangeDetectionIssue.of(
                FILE_FORMAT_MISMATCH,
                f"{t1.label} is {t1.facts.format} but {t2.label} is {t2.facts.format}. "
                "This workflow requires both images to be the same raster format.",
                t1=t1.facts.format, t2=t2.facts.format,
            )])

    # 5. Compatible aspect ratio?
    ratio_issue = dimension_validator.aspect_ratio_issue(
        t1.facts, t2.facts, tolerance=workflow_requirements.aspect_ratio_tolerance, t1_label=t1.label, t2_label=t2.label
    )
    if ratio_issue:
        checks["aspect_ratio"] = False
        return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[ratio_issue])

    # 6. Compatible (exact) dimensions?
    if workflow_requirements.require_exact_dimensions:
        dim_issue = dimension_validator.exact_dimension_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if dim_issue:
            checks["dimensions"] = False
            return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[dim_issue])

    # 7. Band count compatibility
    if t1.facts.band_count is not None and t2.facts.band_count is not None:
        if t1.facts.band_count != t2.facts.band_count:
            checks["band_count"] = False
            return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[ChangeDetectionIssue.of(
                BAND_MISMATCH,
                f"{t1.label} has {t1.facts.band_count} band(s) but {t2.label} has {t2.facts.band_count} band(s). "
                "Change detection requires compatible band counts.",
                t1=f"{t1.facts.band_count} band(s)",
                t2=f"{t2.facts.band_count} band(s)",
            )])

    # 8. Band/channel structure -- SAR gets strict polarization matching (VV<->VV / VH<->VH);
    # other modalities get a general named bands check if names are present.
    t1_sar_bands = band_validator.detect_named_bands(t1.facts).keys() & _SAR_BANDS
    t2_sar_bands = band_validator.detect_named_bands(t2.facts).keys() & _SAR_BANDS
    is_sar_check = modality_1 == "sar" or modality_2 == "sar" or bool(t1_sar_bands or t2_sar_bands)
    band_issue = _sar_band_issue(t1, t2) if is_sar_check else _general_band_issue(t1, t2)
    if band_issue:
        checks["band_count"] = False
        return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[band_issue])

    # 9. Geospatial completeness (per image), then CRS equality (cross-image).
    if workflow_requirements.require_geospatial and t1.extension in TIFF_EXTENSIONS:
        geo_issues = []
        for image, key in ((t1, "t1"), (t2, "t2")):
            geo_issues.extend(
                ChangeDetectionIssue.of(issue.code, f"{image.label}: {issue.message}", **{key: image.label})
                for issue in geospatial_issues(image.facts, input_label=image.label, required=True, extension=image.extension)
            )
        if geo_issues:
            checks["crs"] = False
            checks["transform"] = False
            return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=geo_issues)

        crs_issue = crs_match_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if crs_issue:
            checks["crs"] = False
            crs_issue = ChangeDetectionIssue.of(crs_issue.code, crs_issue.message, t1=t1.facts.crs, t2=t2.facts.crs)
            return ChangeDetectionValidationResult(valid=False, status="REJECT", checks=checks, errors=[crs_issue])

    # 10. VALID.
    confidence = "exact" if (modality_1 != "unknown" and modality_2 != "unknown") else "structural"
    return ChangeDetectionValidationResult(valid=True, status="VALID", confidence=confidence, checks=checks, errors=[])


def _general_band_issue(t1: ChangeDetectionImageMetadata, t2: ChangeDetectionImageMetadata) -> ChangeDetectionIssue | None:
    """T1 and T2 must offer the same named bands (e.g. both Red+NIR) when named bands
    are present in both images. If neither image has named bands, structural validation passes."""
    bands_1, bands_2 = set(band_validator.detect_named_bands(t1.facts)), set(band_validator.detect_named_bands(t2.facts))
    if not bands_1 and not bands_2:
        return None
    if bands_1 != bands_2:
        return ChangeDetectionIssue.of(
            BAND_MISMATCH,
            f"{t1.label} and {t2.label} must have the same band/channel structure.",
            t1=_band_list(bands_1), t2=_band_list(bands_2),
        )
    return None


def _sar_band_issue(t1: ChangeDetectionImageMetadata, t2: ChangeDetectionImageMetadata) -> ChangeDetectionIssue | None:
    """SAR rule: VV -> VV, VH -> VH, never a mix. If either image's polarization
    can't be identified at all, it's flagged as unidentified."""
    band_1 = next(iter(band_validator.detect_named_bands(t1.facts).keys() & _SAR_BANDS), None)
    band_2 = next(iter(band_validator.detect_named_bands(t2.facts).keys() & _SAR_BANDS), None)
    if band_1 is None or band_2 is None or band_1 != band_2:
        val1 = band_1.upper() if band_1 else "unidentified"
        val2 = band_2.upper() if band_2 else "unidentified"
        if band_1 and band_2 and band_1 != band_2:
            msg = f"SAR band mismatch: {t1.label} = {val1}, {t2.label} = {val2}. SAR change detection requires identical polarization."
        else:
            msg = f"SAR change detection requires the same polarization for {t1.label} and {t2.label} (VV -> VV, VH -> VH) -- never a mix."
        return ChangeDetectionIssue.of(
            BAND_MISMATCH,
            msg,
            t1=val1,
            t2=val2,
        )
    return None


def _band_list(bands: set[str]) -> str:
    return "+".join(sorted(bands)) if bands else "none identified"

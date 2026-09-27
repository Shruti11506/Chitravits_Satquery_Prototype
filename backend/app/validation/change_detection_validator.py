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

    # 2. Both files readable?
    unreadable = [
        ChangeDetectionIssue.of(FILE_CORRUPTED, f"{image.label} could not be read: {image.facts.error}", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if image.facts.error
    ]
    if unreadable:
        return ChangeDetectionValidationResult(valid=False, errors=unreadable)

    # Not literally the same stored image -- see module docstring.
    if t1.imagery_id and t2.imagery_id and t1.imagery_id == t2.imagery_id:
        return ChangeDetectionValidationResult(valid=False, errors=[ChangeDetectionIssue.of(
            NOT_DISTINCT_OBSERVATIONS,
            "T1 and T2 must be two different uploaded images; the same image was submitted for both.",
            t1=t1.label, t2=t2.label,
        )])

    # 3. Supported format? (defensive -- file_validator already rejects an
    # unsupported extension before this function is ever reached with real data)
    missing_format = [
        ChangeDetectionIssue.of(UNSUPPORTED_FORMAT, f"{image.label}'s format could not be determined.", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if not image.facts.format
    ]
    if missing_format:
        return ChangeDetectionValidationResult(valid=False, errors=missing_format)

    # 6/7. Determine modality/image type, T1 modality == T2 modality? -- run
    # BEFORE the format-family check below (see this module's docstring):
    # this section's own bug report insists a JPEG/RGB image against a
    # Sentinel-2 multispectral GeoTIFF returns MODALITY_MISMATCH, and step 7
    # sits right after metadata extraction in the brief's own order (section
    # 11) -- ahead of any format-family nuance, which isn't a numbered step
    # in that order at all (it's this module's own addition, from an earlier
    # brief -- section 10 below).
    modality_1, modality_2 = _detect(t1), _detect(t2)
    if modality_1 == "unknown" or modality_2 == "unknown":
        return ChangeDetectionValidationResult(valid=False, errors=[ChangeDetectionIssue.of(
            UNKNOWN_MODALITY,
            "Unable to determine the image type required for change detection."
            + (" One or both could not be determined; supply modality_hint explicitly." if "unknown" in (modality_1, modality_2) else ""),
            t1=_modality_label(modality_1), t2=_modality_label(modality_2),
        )])
    if modality_1 != modality_2:
        return ChangeDetectionValidationResult(valid=False, errors=[ChangeDetectionIssue.of(
            IMAGE_TYPE_MISMATCH,
            f"{t1.label} and {t2.label} have incompatible image types for change detection.",
            t1=_modality_label(modality_1), t2=_modality_label(modality_2),
        )])

    # Matching raster format between T1 and T2 (section 10) -- ONE "plain
    # image" family (JPEG/PNG, interchangeable for this check -- neither is
    # ever georeferenced) vs the TIFF/GeoTIFF family. A TIFF without a CRS
    # still counts as TIFF-family here; that distinction is the geospatial
    # step's job below, not this one's.
    if workflow_requirements.require_matching_format:
        family_1 = "tiff" if t1.extension in TIFF_EXTENSIONS else "image"
        family_2 = "tiff" if t2.extension in TIFF_EXTENSIONS else "image"
        if family_1 != family_2:
            return ChangeDetectionValidationResult(valid=False, errors=[ChangeDetectionIssue.of(
                FILE_FORMAT_MISMATCH,
                f"{t1.label} is {t1.facts.format} but {t2.label} is {t2.facts.format}. "
                "This workflow requires both images to be the same raster format.",
                t1=t1.facts.format, t2=t2.facts.format,
            )])

    # 6. Compatible aspect ratio?
    ratio_issue = dimension_validator.aspect_ratio_issue(
        t1.facts, t2.facts, tolerance=workflow_requirements.aspect_ratio_tolerance, t1_label=t1.label, t2_label=t2.label
    )
    if ratio_issue:
        return ChangeDetectionValidationResult(valid=False, errors=[ratio_issue])

    # 7. Compatible (exact) dimensions?
    if workflow_requirements.require_exact_dimensions:
        dim_issue = dimension_validator.exact_dimension_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if dim_issue:
            return ChangeDetectionValidationResult(valid=False, errors=[dim_issue])

    # 8/9. Band/channel structure -- SAR gets the strict VV<->VV / VH<->VH
    # rule; every other modality gets a general "same detected bands" check.
    band_issue = _sar_band_issue(t1, t2) if modality_1 == "sar" else _general_band_issue(t1, t2)
    if band_issue:
        return ChangeDetectionValidationResult(valid=False, errors=[band_issue])

    # 10/11. Geospatial completeness (per image), then CRS equality (cross-image).
    # Only meaningful for a TIFF-family pair -- a plain JPEG/PNG pair was
    # never expected to carry geospatial metadata (section 4/9: "JPEG/PNG
    # should be treated as non-georeferenced by default"), so two otherwise-
    # compatible JPEGs must not be rejected just for lacking a CRS neither
    # side ever claimed to have. By this point modality and (when enabled)
    # format-family already agree, so checking either extension is
    # equivalent to checking both.
    if workflow_requirements.require_geospatial and t1.extension in TIFF_EXTENSIONS:
        geo_issues = []
        for image, key in ((t1, "t1"), (t2, "t2")):
            geo_issues.extend(
                ChangeDetectionIssue.of(issue.code, f"{image.label}: {issue.message}", **{key: image.label})
                for issue in geospatial_issues(image.facts, input_label=image.label, required=True, extension=image.extension)
            )
        if geo_issues:
            return ChangeDetectionValidationResult(valid=False, errors=geo_issues)

        crs_issue = crs_match_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if crs_issue:
            crs_issue = ChangeDetectionIssue.of(crs_issue.code, crs_issue.message, t1=t1.facts.crs, t2=t2.facts.crs)
            return ChangeDetectionValidationResult(valid=False, errors=[crs_issue])

    # 12. VALID.
    return ChangeDetectionValidationResult(valid=True, errors=[])


def _general_band_issue(t1: ChangeDetectionImageMetadata, t2: ChangeDetectionImageMetadata) -> ChangeDetectionIssue | None:
    """Section 5: T1 and T2 must offer the same named bands (e.g. both
    Red+NIR). Only compares bands this raster's own metadata actually
    identifies -- an image with no named bands at all (common for a plain
    optical/RGB scene) has nothing to compare, so this passes rather than
    guessing; SAR's stricter single-band rule is `_sar_band_issue` below."""
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
    """Section 6, the mandatory rule: VV -> VV, VH -> VH, never VV+VH. If
    either image's polarization can't be identified at all, this does NOT
    silently pass -- an unconfirmed pair is never treated as valid."""
    band_1 = next(iter(band_validator.detect_named_bands(t1.facts).keys() & _SAR_BANDS), None)
    band_2 = next(iter(band_validator.detect_named_bands(t2.facts).keys() & _SAR_BANDS), None)
    if band_1 is None or band_2 is None or band_1 != band_2:
        return ChangeDetectionIssue.of(
            BAND_MISMATCH,
            f"SAR change detection requires the same polarization for {t1.label} and {t2.label} "
            f"(VV -> VV, VH -> VH) -- never a mix.",
            t1=band_1.upper() if band_1 else "unidentified",
            t2=band_2.upper() if band_2 else "unidentified",
        )
    return None


def _band_list(bands: set[str]) -> str:
    return "+".join(sorted(bands)) if bands else "none identified"

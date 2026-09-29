"""Change Detection Input Validation: is this T1/T2 pair a compatible input
for bi-temporal change detection?

`validate_change_detection_inputs` is the ONE entry point, and it answers
nothing else -- no change map, no registration, no resampling, no model
call. See the package docstring in `__init__.py` for the shared scope
boundary this module inherits.

Runs the checks in a STRICT order and STOPS at the first one that fails --
unlike the generic `app.validation.service.validate_images`, which collects
every applicable issue:

    readable -> distinct -> supported format -> SENSOR -> MODALITY ->
    format family -> aspect ratio -> exact dimensions -> band count ->
    band identity / compatibility (SAR: polarisation sets) -> geospatial
    (T1, T2, then CRS) -> dtype

Modality is the earliest cross-image comparison, checked BEFORE the
format-family check, so the reported bug (T1 = plain RGB JPEG, T2 =
Sentinel-2 multispectral GeoTIFF) comes back as a modality error rather
than FILE_FORMAT_MISMATCH pre-empting it. dtype runs last so a structural
problem (e.g. a missing CRS) is reported before a data-type difference.

Error codes: two KNOWN but different modalities is IMAGE_TYPE_MISMATCH (the
code this module has always emitted; the frontend reads it). A
`modality_hint` that contradicts an image's own metadata is
MODALITY_MISMATCH. A T1/T2 polarisation difference stays BAND_MISMATCH;
POLARIZATION_MISMATCH is reserved for an explicitly configured polarisation
requirement (`expected_sar_polarizations`, `sar_polarization_policy=
"single_required"`).

Geospatial: each image is validated on its own (so a JPEG/PNG fails as
"T1" or "T2" specifically, whichever it is), then CRSs are compared. It
runs when `require_geospatial`, or -- with `geospatial_when_present`, the
chat profile -- when either image actually carries a CRS.

Every check is recorded in `check_details` as pass / fail / skipped;
`checks` (bool) lists only the checks that actually ran.

"T1 and T2 are expected to differ": nothing here ever compares pixel
content. The only identity check is that T1 and T2 are not the exact same
stored image (NOT_DISTINCT_OBSERVATIONS).
"""
from __future__ import annotations

from app.validation import band_validator, dimension_validator, modality_validator
from app.validation.errors import (
    BAND_MISMATCH,
    DTYPE_MISMATCH,
    FILE_CORRUPTED,
    FILE_FORMAT_MISMATCH,
    IMAGE_TYPE_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    POLARIZATION_MISMATCH,
    UNKNOWN_SENSOR,
    UNSUPPORTED_FORMAT,
    UNSUPPORTED_SENSOR,
)
from app.validation.geospatial_validator import crs_match_issue, geospatial_issues
from app.validation.raster_validator import TIFF_EXTENSIONS
from app.validation.schemas import (
    ChangeDetectionImageMetadata,
    ChangeDetectionIssue,
    ChangeDetectionRequirements,
    ChangeDetectionValidationResult,
    CheckDetail,
)
from app.validation.sensors import SensorIdentification, identify_sensor

_MODALITY_LABELS = {
    "optical": "Optical", "rgb": "RGB", "multispectral": "Multispectral",
    "sar": "SAR", "optical_sar": "Optical+SAR", "unknown": "Unknown",
}
# Every check this validator can report, in the order it runs.
CHECK_ORDER = (
    "format", "sensor", "modality", "aspect_ratio", "dimensions", "band_count",
    "band_identity", "band_compatibility", "geospatial_t1", "geospatial_t2", "crs", "dtype",
)


def _modality_label(modality: str) -> str:
    return _MODALITY_LABELS.get(modality, modality)


def sensor_of(image: ChangeDetectionImageMetadata) -> SensorIdentification:
    return identify_sensor(sensor=image.sensor, source=image.source, filename=image.filename, facts=image.facts)


def modality_of(image: ChangeDetectionImageMetadata, sensor: SensorIdentification | None = None):
    return modality_validator.infer_modality(
        image.facts, extension=image.extension, sensor_id=sensor or sensor_of(image), hint=image.modality_hint
    )


class _Run:
    """Accumulates check outcomes, and builds the result."""

    def __init__(self) -> None:
        self.details: dict[str, CheckDetail] = {}
        self.ordered_bands: dict[str, list[str]] | None = None

    def record(self, name: str, status: str, detail: str | None = None) -> None:
        self.details[name] = CheckDetail(status=status, detail=detail)

    def _result(self, **kwargs) -> ChangeDetectionValidationResult:
        details = dict(self.details)
        for name in CHECK_ORDER:
            details.setdefault(name, CheckDetail(status="skipped", detail="not reached"))
        details = {name: details[name] for name in CHECK_ORDER}
        checks = {name: d.status == "pass" for name, d in details.items() if d.status != "skipped"}
        return ChangeDetectionValidationResult(
            checks=checks, check_details=details, ordered_bands=self.ordered_bands, **kwargs
        )

    def reject(self, *issues: ChangeDetectionIssue) -> ChangeDetectionValidationResult:
        return self._result(valid=False, status="REJECT", errors=list(issues))

    def valid(self, confidence: str) -> ChangeDetectionValidationResult:
        return self._result(valid=True, status="VALID", confidence=confidence, errors=[])


def validate_change_detection_inputs(
    t1_metadata: ChangeDetectionImageMetadata,
    t2_metadata: ChangeDetectionImageMetadata,
    workflow_requirements: ChangeDetectionRequirements,
) -> ChangeDetectionValidationResult:
    t1, t2 = t1_metadata, t2_metadata
    req = workflow_requirements
    run = _Run()

    # 1. Both files readable?
    unreadable = [
        ChangeDetectionIssue.of(FILE_CORRUPTED, f"{image.label} could not be read: {image.facts.error}", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if image.facts.error
    ]
    if unreadable:
        return run.reject(*unreadable)

    # 2. Distinct images -- not literally the same stored image.
    if t1.imagery_id and t2.imagery_id and t1.imagery_id == t2.imagery_id:
        return run.reject(ChangeDetectionIssue.of(
            NOT_DISTINCT_OBSERVATIONS,
            "T1 and T2 must be two different uploaded images; the same image was submitted for both.",
            t1=t1.label, t2=t2.label,
        ))

    # 3. Supported format?
    missing_format = [
        ChangeDetectionIssue.of(UNSUPPORTED_FORMAT, f"{image.label}'s format could not be determined.", **{key: image.label})
        for image, key in ((t1, "t1"), (t2, "t2")) if not image.facts.format
    ]
    if missing_format:
        run.record("format", "fail", "format could not be determined")
        return run.reject(*missing_format)

    # 4. Sensor (sensors.py).
    sensor_1, sensor_2 = sensor_of(t1), sensor_of(t2)
    sensor_detail = (
        f"T1={sensor_1.label} ({sensor_1.source or 'no evidence'}), T2={sensor_2.label} ({sensor_2.source or 'no evidence'})"
    )
    if req.reject_unsupported_sensor:
        unsupported = [(image, sensor) for image, sensor in ((t1, sensor_1), (t2, sensor_2)) if sensor.status == "unsupported"]
        if unsupported:
            run.record("sensor", "fail", sensor_detail)
            image, sensor = unsupported[0]
            return run.reject(ChangeDetectionIssue.of(
                UNSUPPORTED_SENSOR,
                f"{image.label} is from '{sensor.raw_value}', which is not a supported sensor. "
                "Supported: Sentinel-1, Sentinel-2, Cartosat, RISAT.",
                t1=sensor_1.label, t2=sensor_2.label,
            ))
    if req.require_known_sensor:
        unknown = [image for image, sensor in ((t1, sensor_1), (t2, sensor_2)) if not sensor.is_supported]
        if unknown:
            run.record("sensor", "fail", sensor_detail)
            return run.reject(ChangeDetectionIssue.of(
                UNKNOWN_SENSOR,
                f"The sensor of {' and '.join(image.label for image in unknown)} could not be identified from its "
                "metadata or filename. This workflow requires Sentinel-1, Sentinel-2, Cartosat or RISAT imagery.",
                t1=sensor_1.label, t2=sensor_2.label,
            ))
    if sensor_1.is_supported and sensor_2.is_supported:
        run.record("sensor", "pass", sensor_detail)
    else:
        run.record("sensor", "skipped", sensor_detail + "; a known sensor is not required by this profile")

    # 5. Modality: each image's hint against its own evidence, then T1 vs T2.
    decision_1, decision_2 = modality_of(t1, sensor_1), modality_of(t2, sensor_2)
    for image, decision, key in ((t1, decision_1, "t1"), (t2, decision_2, "t2")):
        conflict = modality_validator.hint_conflict_issue(decision, input_label=image.label)
        if conflict:
            run.record("modality", "fail", f"{image.label}: hint '{decision.hint}' vs evidence '{decision.evidence}'")
            return run.reject(ChangeDetectionIssue.of(
                conflict.code, f"{image.label}: {conflict.message}",
                **{key: f"hint {_modality_label(decision.hint)} / evidence {_modality_label(decision.evidence)}"},
            ))
    modality_1, modality_2 = decision_1.modality, decision_2.modality
    modality_detail = f"{modality_1} ({decision_1.source}) / {modality_2} ({decision_2.source})"
    if modality_1 != "unknown" and modality_2 != "unknown":
        if modality_1 != modality_2:
            run.record("modality", "fail", modality_detail)
            return run.reject(ChangeDetectionIssue.of(
                IMAGE_TYPE_MISMATCH,
                f"{t1.label} and {t2.label} have incompatible image types for change detection.",
                t1=_modality_label(modality_1), t2=_modality_label(modality_2),
            ))
        run.record("modality", "pass", modality_detail)
    else:
        # UNKNOWN is not automatically invalid -- structural checks continue.
        run.record("modality", "skipped", modality_detail + "; not determinable, structural checks continue")

    # 6. Format family match between T1 and T2 (TIFF vs image).
    if req.require_matching_format:
        family_1 = "tiff" if t1.extension in TIFF_EXTENSIONS else "image"
        family_2 = "tiff" if t2.extension in TIFF_EXTENSIONS else "image"
        if family_1 != family_2:
            run.record("format", "fail", f"{t1.facts.format} / {t2.facts.format}")
            return run.reject(ChangeDetectionIssue.of(
                FILE_FORMAT_MISMATCH,
                f"{t1.label} is {t1.facts.format} but {t2.label} is {t2.facts.format}. "
                "This workflow requires both images to be the same raster format.",
                t1=t1.facts.format, t2=t2.facts.format,
            ))
        run.record("format", "pass", f"{t1.facts.format} / {t2.facts.format}")
    else:
        run.record("format", "pass", f"{t1.facts.format} / {t2.facts.format}; matching format family not required")

    # 7. Compatible aspect ratio?
    if req.aspect_ratio_tolerance is None:
        run.record("aspect_ratio", "skipped", "disabled")
    else:
        ratio_issue = dimension_validator.aspect_ratio_issue(
            t1.facts, t2.facts, tolerance=req.aspect_ratio_tolerance, t1_label=t1.label, t2_label=t2.label
        )
        if ratio_issue:
            run.record("aspect_ratio", "fail", f"{ratio_issue.t1} / {ratio_issue.t2}")
            return run.reject(ratio_issue)
        run.record("aspect_ratio", "pass", f"within tolerance {req.aspect_ratio_tolerance}")

    # 8. Compatible (exact) dimensions?
    size_detail = f"{t1.facts.width}x{t1.facts.height} / {t2.facts.width}x{t2.facts.height}"
    if req.require_exact_dimensions:
        dim_issue = dimension_validator.exact_dimension_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if dim_issue:
            run.record("dimensions", "fail", size_detail)
            return run.reject(dim_issue)
        run.record("dimensions", "pass", size_detail)
    else:
        run.record("dimensions", "skipped", f"{size_detail}; exact dimensions not required")

    # 9. Band count compatibility.
    count_1, count_2 = t1.facts.band_count, t2.facts.band_count
    if count_1 is not None and count_2 is not None:
        if count_1 != count_2:
            run.record("band_count", "fail", f"{count_1} / {count_2}")
            return run.reject(ChangeDetectionIssue.of(
                BAND_MISMATCH,
                f"{t1.label} has {count_1} band(s) but {t2.label} has {count_2} band(s). "
                "Change detection requires compatible band counts.",
                t1=f"{count_1} band(s)", t2=f"{count_2} band(s)",
            ))
        run.record("band_count", "pass", f"{count_1} / {count_2}")
    else:
        run.record("band_count", "skipped", "band count unavailable")

    # 10. Band identity + compatibility. SAR: polarisation sets; else named bands.
    bands_1 = band_validator.detect_named_bands(t1.facts, sensor_1)
    bands_2 = band_validator.detect_named_bands(t2.facts, sensor_2)
    pols_1, pols_2 = band_validator.sar_polarizations(bands_1), band_validator.sar_polarizations(bands_2)
    is_sar = modality_1 == "sar" or modality_2 == "sar" or bool(pols_1 or pols_2)
    band_issue = (
        _sar_band_issue(run, t1, t2, pols_1, pols_2, req) if is_sar
        else _general_band_issue(run, t1, t2, bands_1, bands_2, sensor_1, sensor_2)
    )
    if band_issue:
        return run.reject(band_issue)

    # 11. Geospatial: each image on its own, then CRS equality.
    any_georeferenced = t1.facts.crs is not None or t2.facts.crs is not None
    if req.require_geospatial or (req.geospatial_when_present and any_georeferenced):
        geo_issues = []
        for image, key in ((t1, "t1"), (t2, "t2")):
            issues = geospatial_issues(image.facts, input_label=image.label, required=True, extension=image.extension)
            if issues:
                run.record(f"geospatial_{key}", "fail", issues[0].code)
                geo_issues.extend(
                    ChangeDetectionIssue.of(issue.code, f"{image.label}: {issue.message}", **{key: image.label})
                    for issue in issues
                )
            else:
                run.record(f"geospatial_{key}", "pass", image.facts.crs)
        if geo_issues:
            return run.reject(*geo_issues)

        crs_issue = crs_match_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if crs_issue:
            run.record("crs", "fail", f"{t1.facts.crs} / {t2.facts.crs}")
            return run.reject(ChangeDetectionIssue.of(crs_issue.code, crs_issue.message, t1=t1.facts.crs, t2=t2.facts.crs))
        run.record("crs", "pass", t1.facts.crs)
    else:
        reason = "not required" if not req.geospatial_when_present else "neither image is georeferenced"
        for name in ("geospatial_t1", "geospatial_t2", "crs"):
            run.record(name, "skipped", reason)

    # 12. dtype -- T1/T2 compatibility only; no per-sensor allowlist (TODO(team)).
    dtype_1, dtype_2 = _dtype_signature(t1), _dtype_signature(t2)
    if not req.require_matching_dtype:
        run.record("dtype", "skipped", "matching dtype not required")
    elif not dtype_1 or not dtype_2:
        run.record("dtype", "skipped", "dtype unavailable")
    elif dtype_1 != dtype_2:
        run.record("dtype", "fail", f"{dtype_1} / {dtype_2}")
        return run.reject(ChangeDetectionIssue.of(
            DTYPE_MISMATCH,
            f"{t1.label} stores {dtype_1} pixels but {t2.label} stores {dtype_2}. "
            "Change detection requires both images to use the same pixel data type.",
            t1=dtype_1, t2=dtype_2,
        ))
    else:
        run.record("dtype", "pass", f"{dtype_1} / {dtype_2}")

    # 13. VALID.
    confidence = "exact" if (modality_1 != "unknown" and modality_2 != "unknown") else "structural"
    return run.valid(confidence)


def _dtype_signature(image: ChangeDetectionImageMetadata) -> str | None:
    dtypes = sorted({str(d) for d in image.facts.dtypes if d})
    return "+".join(dtypes) if dtypes else None


def _general_band_issue(
    run: _Run,
    t1: ChangeDetectionImageMetadata,
    t2: ChangeDetectionImageMetadata,
    bands_1: dict[str, int],
    bands_2: dict[str, int],
    sensor_1: SensorIdentification,
    sensor_2: SensorIdentification,
) -> ChangeDetectionIssue | None:
    """T1 and T2 must offer the same identified bands (e.g. both Red+NIR). If
    neither has identified bands but BOTH carry band names, the raw names are
    compared literally (no interpretation). Nothing named -> structural pass."""
    ordered_1, ordered_2 = band_validator.ordered_bands(bands_1), band_validator.ordered_bands(bands_2)
    if bands_1 or bands_2:
        run.ordered_bands = {"t1": ordered_1, "t2": ordered_2}
        run.record("band_identity", "pass", f"T1 {ordered_1 or 'none identified'}; T2 {ordered_2 or 'none identified'}")
        if set(bands_1) != set(bands_2):
            run.record("band_compatibility", "fail", "identified band sets differ")
            return ChangeDetectionIssue.of(
                BAND_MISMATCH,
                f"{t1.label} and {t2.label} must have the same band/channel structure.",
                t1=_band_list(set(bands_1)), t2=_band_list(set(bands_2)),
            )
        run.record("band_compatibility", "pass", "identified band sets equal")
        return None

    raw_1 = band_validator.unrecognised_band_names(t1.facts, sensor_1)
    raw_2 = band_validator.unrecognised_band_names(t2.facts, sensor_2)
    run.record("band_identity", "skipped", "no band could be identified (unknown sensor or undescribed bands)")
    if raw_1 and raw_2:
        if [name.lower() for name in raw_1] != [name.lower() for name in raw_2]:
            run.record("band_compatibility", "fail", "raw band names differ")
            return ChangeDetectionIssue.of(
                BAND_MISMATCH,
                f"{t1.label} and {t2.label} must have the same band/channel structure.",
                t1="+".join(raw_1), t2="+".join(raw_2),
            )
        run.record("band_compatibility", "pass", "raw band names equal (not interpreted)")
    else:
        run.record("band_compatibility", "skipped", "no band names to compare")
    return None


def _sar_band_issue(
    run: _Run,
    t1: ChangeDetectionImageMetadata,
    t2: ChangeDetectionImageMetadata,
    pols_1: list[str],
    pols_2: list[str],
    req: ChangeDetectionRequirements,
) -> ChangeDetectionIssue | None:
    """SAR rule: compare polarisation SETS (VV <-> VV, VV+VH <-> VV+VH), never
    one arbitrarily picked band. Unidentifiable polarisation is flagged."""
    val_1 = "+".join(p.upper() for p in pols_1) or "unidentified"
    val_2 = "+".join(p.upper() for p in pols_2) or "unidentified"
    run.ordered_bands = {"t1": pols_1, "t2": pols_2}

    # Identity: both images must have identifiable polarisations.
    if not pols_1 or not pols_2:
        run.record("band_identity", "fail", f"T1 {val_1}; T2 {val_2}")
        return ChangeDetectionIssue.of(
            BAND_MISMATCH,
            f"SAR change detection requires the same polarization for {t1.label} and {t2.label} "
            "(VV -> VV, VH -> VH) -- never a mix.",
            t1=val_1, t2=val_2,
        )
    run.record("band_identity", "pass", f"T1 {pols_1}; T2 {pols_2}")

    # Explicitly configured requirements first -- they're the more specific error.
    if req.sar_polarization_policy == "single_required":
        for image, pols, key in ((t1, pols_1, "t1"), (t2, pols_2, "t2")):
            if len(pols) != 1:
                run.record("band_compatibility", "fail", f"{image.label} has {len(pols)} polarisations (single_required)")
                return ChangeDetectionIssue.of(
                    POLARIZATION_MISMATCH,
                    f"{image.label} carries several polarisations ({'+'.join(p.upper() for p in pols)}); this workflow "
                    "needs exactly one per image. Choose which polarisation to use.",
                    **{key: "+".join(p.upper() for p in pols)},
                )
    if req.expected_sar_polarizations is not None:
        expected = [p for p in band_validator.SAR_POLARIZATIONS if p in {e.lower() for e in req.expected_sar_polarizations}]
        for image, pols, key in ((t1, pols_1, "t1"), (t2, pols_2, "t2")):
            if pols != expected:
                expected_label = "+".join(p.upper() for p in expected)
                run.record("band_compatibility", "fail", f"{image.label} {pols} != expected {expected}")
                return ChangeDetectionIssue.of(
                    POLARIZATION_MISMATCH,
                    f"{image.label} provides {'+'.join(p.upper() for p in pols)}, but this workflow requires "
                    f"{expected_label} polarisation.",
                    **{key: "+".join(p.upper() for p in pols)},
                )

    if pols_1 != pols_2:  # both lists are in canonical order, so this is a set comparison
        run.record("band_compatibility", "fail", f"polarisation sets differ ({req.sar_polarization_policy})")
        return ChangeDetectionIssue.of(
            BAND_MISMATCH,
            f"SAR band mismatch: {t1.label} = {val_1}, {t2.label} = {val_2}. "
            "SAR change detection requires identical polarization.",
            t1=val_1, t2=val_2,
        )
    run.record("band_compatibility", "pass", f"polarisation sets equal ({req.sar_polarization_policy})")
    return None


def _band_list(bands: set[str]) -> str:
    return "+".join(sorted(bands)) if bands else "none identified"

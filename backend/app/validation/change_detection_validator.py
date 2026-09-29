"""Change Detection Input Validation: is this T1/T2 pair a compatible input
for bi-temporal change detection?

`validate_change_detection_inputs` is the ONE entry point, and it answers
nothing else -- no change map, no registration, no resampling, no model
call. See the package docstring in `__init__.py` for the shared scope
boundary this module inherits.

Runs the checks in a STRICT order and STOPS at the first one that fails --
unlike the generic `app.validation.service.validate_images`, which collects
every applicable issue:

    file T1 / T2 -> distinct images -> sensor -> modality -> format family
    -> aspect ratio -> exact dimensions -> band count -> bands (optical
    only) -> geospatial (T1, T2, then CRS) -> dtype

* **File** checks (file_validator.py) say which image failed.
* **Distinct images**: the same stored id, the same Storage object, the same
  file bytes (SHA-256) or the same decoded pixels (pixel SHA-256, only when
  the shapes and dtypes match) are all NOT_DISTINCT_OBSERVATIONS. Only
  EXACT matches are rejected -- a real pair over a stable area can look
  almost identical. Digests stored at upload (`imagery.metadata`) are used
  when present; otherwise the file is read once to compute them.
* **Modality**: two known, incompatible modalities (optical/multispectral
  vs SAR vs RGB) are MODALITY_MISMATCH. `IMAGE_TYPE_MISMATCH` is no longer
  emitted (deprecated; the frontend still recognises it).
* **Bands**: Sentinel-2 / Cartosat pairs must have the same identified
  bands. Sentinel-1 / RISAT get NO band or polarisation validation (scope):
  only the band count is compared, and the channels go to the model in the
  file's own order (reported in `ordered_bands`).
* **Geospatial**: each image on its own (a JPEG/PNG fails as T1 or T2
  specifically), then the CRS. Runs when `require_geospatial`, or -- with
  `geospatial_when_present`, the chat profile -- when either image has a CRS.
* The **aspect-ratio / exact-dimension** gates are off by default
  (`ChangeDetectionRequirements`); the chat profile turns them on.

Every check is recorded in `check_details` as pass / fail / skipped;
`checks` (bool) lists only the checks that actually ran.
"""
from __future__ import annotations

from app.validation import band_validator, dimension_validator, file_validator, modality_validator
from app.validation.errors import (
    BAND_MISMATCH,
    DTYPE_MISMATCH,
    FILE_FORMAT_MISMATCH,
    MODALITY_MISMATCH,
    NOT_DISTINCT_OBSERVATIONS,
    SAME_ACQUISITION_TIME,
    UNKNOWN_SENSOR,
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
# Known modalities that may still be paired with each other (besides equal ones).
_COMPATIBLE_MODALITIES = (frozenset({"optical", "multispectral"}),)
# Every check this validator can report, in the order it runs.
CHECK_ORDER = (
    "file_t1", "file_t2", "distinct_images", "sensor", "modality", "format", "aspect_ratio", "dimensions",
    "band_count", "band_identity", "band_compatibility", "geospatial_t1", "geospatial_t2", "crs", "dtype",
)


def _modality_label(modality: str) -> str:
    return _MODALITY_LABELS.get(modality, modality)


def _compatible(modality_1: str, modality_2: str) -> bool:
    return modality_1 == modality_2 or any({modality_1, modality_2} <= group for group in _COMPATIBLE_MODALITIES)


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
        self.warnings: list[ChangeDetectionIssue] = []

    def record(self, name: str, status: str, detail: str | None = None) -> None:
        self.details[name] = CheckDetail(status=status, detail=detail)

    def _result(self, **kwargs) -> ChangeDetectionValidationResult:
        details = {name: self.details.get(name, CheckDetail(status="skipped", detail="not reached")) for name in CHECK_ORDER}
        checks = {name: d.status == "pass" for name, d in details.items() if d.status != "skipped"}
        return ChangeDetectionValidationResult(
            checks=checks, check_details=details, ordered_bands=self.ordered_bands, warnings=self.warnings, **kwargs
        )

    def reject(self, *issues: ChangeDetectionIssue) -> ChangeDetectionValidationResult:
        return self._result(valid=False, status="REJECT", errors=list(issues))

    def valid(self, confidence: str) -> ChangeDetectionValidationResult:
        return self._result(valid=True, status="VALID", confidence=confidence, errors=[])


# ---- file content & digests (lazy: read at most once, only when needed) ------------


def _content(image: ChangeDetectionImageMetadata) -> bytes | None:
    if image.content is None and image.content_loader is not None:
        loader, image.content_loader = image.content_loader, None
        try:
            image.content = loader()
        except Exception:  # noqa: BLE001 - an unavailable file just can't be compared
            image.content = None
    return image.content


def _sha256(image: ChangeDetectionImageMetadata) -> str | None:
    if image.sha256 is None:
        content = _content(image)
        if content is not None:
            image.sha256 = file_validator.sha256_of(content)
    return image.sha256


def _pixel_sha256(image: ChangeDetectionImageMetadata) -> str | None:
    if image.pixel_sha256 is None:
        content = _content(image)
        if content is not None:
            image.pixel_sha256 = file_validator.pixel_sha256(content, image.filename or f"image{image.extension}")
    return image.pixel_sha256


def _same_shape(t1: ChangeDetectionImageMetadata, t2: ChangeDetectionImageMetadata) -> bool:
    f1, f2 = t1.facts, t2.facts
    return (f1.width, f1.height, f1.band_count, list(f1.dtypes)) == (f2.width, f2.height, f2.band_count, list(f2.dtypes))


def _file_issues(image: ChangeDetectionImageMetadata, key: str) -> list[ChangeDetectionIssue]:
    """file_validator's checks for one side: byte-level ones when its bytes
    are at hand, the structural ones (readable, dimensions, bands, dtype) always."""
    if image.content is not None:
        issues = file_validator.validate_file(
            image.filename or f"image{image.extension}", image.content, image.content_type,
            input_label=image.label, compute_digests=False,
        ).issues
    else:
        issues = file_validator.facts_issues(image.facts, input_label=image.label)
    return [ChangeDetectionIssue.of(issue.code, f"{image.label}: {issue.message}", **{key: image.label}) for issue in issues]


def validate_change_detection_inputs(
    t1_metadata: ChangeDetectionImageMetadata,
    t2_metadata: ChangeDetectionImageMetadata,
    workflow_requirements: ChangeDetectionRequirements,
) -> ChangeDetectionValidationResult:
    t1, t2 = t1_metadata, t2_metadata
    req = workflow_requirements
    run = _Run()

    # 1. File validation, T1 then T2 -- each error names its image.
    for image, key in ((t1, "t1"), (t2, "t2")):
        issues = _file_issues(image, key)
        if issues:
            run.record(f"file_{key}", "fail", issues[0].code)
            return run.reject(*issues)
        run.record(f"file_{key}", "pass", f"{image.facts.format}, {image.facts.width}x{image.facts.height}, "
                                          f"{image.facts.band_count} band(s)")

    # 2. Distinct images: cheapest evidence first, exact matches only.
    reason, compared = None, []
    if t1.imagery_id and t2.imagery_id and t1.imagery_id == t2.imagery_id:
        reason = "same id"
    elif t1.storage_path and t2.storage_path and t1.storage_path == t2.storage_path:
        reason = "same file"
    else:
        sha_1, sha_2 = _sha256(t1), _sha256(t2)
        if sha_1 and sha_2:
            compared.append("content hashes")
            if sha_1 == sha_2:
                reason = "identical content"
        if reason is None and _same_shape(t1, t2):
            pixels_1, pixels_2 = _pixel_sha256(t1), _pixel_sha256(t2)
            if pixels_1 and pixels_2:
                compared.append("pixels")
                if pixels_1 == pixels_2:
                    reason = "identical pixels"
    if reason:
        run.record("distinct_images", "fail", reason)
        return run.reject(ChangeDetectionIssue.of(
            NOT_DISTINCT_OBSERVATIONS,
            f"T1 and T2 are the same image ({reason}). Change detection needs two different acquisitions.",
            t1=t1.label, t2=t2.label,
        ))
    run.record("distinct_images", "pass", f"different {' and '.join(compared)}" if compared
               else "different images (content not available to compare)")

    # 3. Sensor (sensors.py).
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
    _same_acquisition_warning(run, t1, t2, sensor_1, sensor_2)

    # 4. Modality: each image's hint against its own evidence, then T1 vs T2.
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
        if not _compatible(modality_1, modality_2):
            run.record("modality", "fail", modality_detail)
            return run.reject(ChangeDetectionIssue.of(
                MODALITY_MISMATCH,
                f"{t1.label} and {t2.label} have incompatible image types for change detection.",
                t1=_modality_label(modality_1), t2=_modality_label(modality_2),
            ))
        run.record("modality", "pass", modality_detail)
    else:
        # UNKNOWN is not automatically invalid -- structural checks continue.
        run.record("modality", "skipped", modality_detail + "; not determinable, structural checks continue")

    # 5. Format family match between T1 and T2 (TIFF vs image).
    format_detail = f"{t1.facts.format} / {t2.facts.format}"
    if req.require_matching_format:
        family_1 = "tiff" if t1.extension in TIFF_EXTENSIONS else "image"
        family_2 = "tiff" if t2.extension in TIFF_EXTENSIONS else "image"
        if family_1 != family_2:
            run.record("format", "fail", format_detail)
            return run.reject(ChangeDetectionIssue.of(
                FILE_FORMAT_MISMATCH,
                f"{t1.label} is {t1.facts.format} but {t2.label} is {t2.facts.format}. "
                "This workflow requires both images to be the same raster format.",
                t1=t1.facts.format, t2=t2.facts.format,
            ))
        run.record("format", "pass", format_detail)
    else:
        run.record("format", "skipped", format_detail + "; matching format family not required")

    # 6. Aspect ratio (deferred gate).
    if req.aspect_ratio_tolerance is None:
        run.record("aspect_ratio", "skipped", "deferred")
    else:
        ratio_issue = dimension_validator.aspect_ratio_issue(
            t1.facts, t2.facts, tolerance=req.aspect_ratio_tolerance, t1_label=t1.label, t2_label=t2.label
        )
        if ratio_issue:
            run.record("aspect_ratio", "fail", f"{ratio_issue.t1} / {ratio_issue.t2}")
            return run.reject(ratio_issue)
        run.record("aspect_ratio", "pass", f"within tolerance {req.aspect_ratio_tolerance}")

    # 7. Exact dimensions (deferred gate).
    size_detail = f"{t1.facts.width}x{t1.facts.height} / {t2.facts.width}x{t2.facts.height}"
    if req.require_exact_dimensions:
        dim_issue = dimension_validator.exact_dimension_issue(t1.facts, t2.facts, t1_label=t1.label, t2_label=t2.label)
        if dim_issue:
            run.record("dimensions", "fail", size_detail)
            return run.reject(dim_issue)
        run.record("dimensions", "pass", size_detail)
    else:
        run.record("dimensions", "skipped", f"deferred ({size_detail})")

    # 8. Band count (the only band check SAR pairs get).
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

    # 9. Bands -- optical only; SAR gets no band/polarisation validation.
    bands_1 = band_validator.detect_named_bands(t1.facts, sensor_1)
    bands_2 = band_validator.detect_named_bands(t2.facts, sensor_2)
    if modality_1 == "sar" or modality_2 == "sar":
        run.ordered_bands = {"t1": band_validator.ordered_bands(bands_1), "t2": band_validator.ordered_bands(bands_2)}
        run.record("band_identity", "skipped", "no band validation for SAR (Sentinel-1 / RISAT)")
        run.record("band_compatibility", "skipped", "no band validation for SAR; channels are passed in file order")
    else:
        band_issue = _optical_band_issue(run, t1, t2, bands_1, bands_2, sensor_1, sensor_2)
        if band_issue:
            return run.reject(band_issue)

    # 10. Geospatial: each image on its own, then CRS equality.
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

    # 11. dtype -- T1/T2 must match; the supported set was checked in step 1.
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

    # 12. VALID.
    confidence = "exact" if (modality_1 != "unknown" and modality_2 != "unknown") else "structural"
    return run.valid(confidence)


def _same_acquisition_warning(run, t1, t2, sensor_1, sensor_2) -> None:
    """A warning, never an error: same sensor AND same acquisition datetime
    usually means the same scene twice -- but only when both dates are known."""
    if (
        t1.acquisition_date and t2.acquisition_date and str(t1.acquisition_date) == str(t2.acquisition_date)
        and sensor_1.is_supported and sensor_1.family == sensor_2.family
    ):
        run.warnings.append(ChangeDetectionIssue.of(
            SAME_ACQUISITION_TIME,
            f"T1 and T2 have the same sensor ({sensor_1.label}) and the same acquisition time; "
            "check they really are two different acquisitions.",
            t1=str(t1.acquisition_date), t2=str(t2.acquisition_date),
        ))


def _dtype_signature(image: ChangeDetectionImageMetadata) -> str | None:
    dtypes = sorted({str(d) for d in image.facts.dtypes if d})
    return "+".join(dtypes) if dtypes else None


def _optical_band_issue(
    run: _Run,
    t1: ChangeDetectionImageMetadata,
    t2: ChangeDetectionImageMetadata,
    bands_1: dict[str, int],
    bands_2: dict[str, int],
    sensor_1: SensorIdentification,
    sensor_2: SensorIdentification,
) -> ChangeDetectionIssue | None:
    """Sentinel-2 / Cartosat (and any self-describing names): T1 and T2 must
    have the same identified band set. If neither has identified bands but
    BOTH carry band names, the raw names are compared literally (no
    interpretation). Nothing named -> structural pass."""
    for image, sensor, key in ((t1, sensor_1, "t1"), (t2, sensor_2, "t2")):
        duplicates = band_validator.duplicate_bands(image.facts, sensor)
        if duplicates:
            run.record("band_identity", "fail", f"{image.label} repeats {duplicates}")
            return ChangeDetectionIssue.of(
                BAND_MISMATCH, f"{image.label} contains the same band more than once ({', '.join(duplicates)}).",
                **{key: "+".join(duplicates)},
            )

    ordered_1, ordered_2 = band_validator.ordered_bands(bands_1), band_validator.ordered_bands(bands_2)
    if bands_1 or bands_2:
        run.ordered_bands = {"t1": ordered_1, "t2": ordered_2}
        source_1 = band_validator.band_identification_source(t1.facts, sensor_1) or "none"
        source_2 = band_validator.band_identification_source(t2.facts, sensor_2) or "none"
        run.record("band_identity", "pass",
                   f"T1 {ordered_1 or 'none identified'} ({source_1}); T2 {ordered_2 or 'none identified'} ({source_2})")
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


def _band_list(bands: set[str]) -> str:
    return "+".join(sorted(bands)) if bands else "none identified"

"""The Input Validation gate (task brief section 1 / section 13's pipeline).

`validate_images` is the one entry point: FastAPI route -> here -> file
validator -> raster/image metadata extractor -> geospatial validator ->
modality validator -> band validator -> workflow compatibility validator ->
AOI validator -> resource-limit validator -> `ValidationResult`.

This module (and everything it imports under `app/validation/`) never
touches Supabase, LangGraph, or any model -- it operates purely on
`ImageInput`s handed to it. Turning an `imagery_id` into an `ImageInput` is
`imagery_service.build_validation_image()`'s job; see that function's
docstring for the Storage integration.

Answers ONLY "is this input valid for the requested workflow" -- never runs,
scores, or fabricates an analysis result. See the package docstring in
`__init__.py`.
"""
from __future__ import annotations

import logging
import uuid

from app.validation import aoi_validator, band_validator, file_validator, modality_validator, raster_validator, workflow_validator
from app.validation.errors import IMAGE_UNAVAILABLE, UNSUPPORTED_FORMAT, ValidationIssue
from app.validation.limits import check_band_count, check_dimensions, check_image_count, current_limits
from app.validation.raster_validator import extension_of
from app.validation.schemas import ImageInput, RasterFacts, ValidatedImageInfo, ValidationResult

logger = logging.getLogger(__name__)


def validate_images(
    *, workflow: str, images: list[ImageInput], aoi: dict | None = None, request_id: str | None = None
) -> ValidationResult:
    request_id = request_id or uuid.uuid4().hex[:12]
    # Filenames/ids only -- never file contents, never Supabase credentials.
    logger.info(
        "validation started id=%s workflow=%s images=%s",
        request_id, workflow, [i.imagery_id or i.filename for i in images],
    )

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    inputs: list[ValidatedImageInfo] = []
    limits = current_limits()

    count_issue = check_image_count(len(images), limits)
    if count_issue:
        errors.append(count_issue)

    wf = workflow_validator.get_workflow(workflow)
    if wf is None:
        errors.append(workflow_validator.unknown_workflow_issue(workflow))
        logger.info("validation rejected id=%s reason=unknown_workflow", request_id)
        return ValidationResult.build(errors, warnings, inputs)

    facts_list = [_inspect(image, limits, errors) for image in images]
    inputs.extend(_describe(image, facts) for image, facts in zip(images, facts_list))

    struct_issues = workflow_validator.structural_issues(wf, images)
    errors.extend(struct_issues)

    # Compatibility (bands/modality/geospatial/AOI) only makes sense once the
    # request shape is right AND every file actually opened -- otherwise
    # this would just pile confusing secondary errors on top of the real one.
    if not struct_issues and not any(f.error for f in facts_list):
        errors.extend(workflow_validator.compatibility_issues(wf, images, facts_list, aoi_present=aoi is not None))
        if aoi is not None:
            errors.extend(_aoi_issues(aoi, images, facts_list))

    logger.info(
        "validation %s id=%s workflow=%s error_count=%d",
        "rejected" if errors else "passed", request_id, workflow, len(errors),
    )
    return ValidationResult.build(errors, warnings, inputs)


def _inspect(image: ImageInput, limits, errors: list[ValidationIssue]) -> RasterFacts:
    """Runs the file + raster/image validators for one image, appending any
    issues to `errors`, and returns its RasterFacts either way."""
    label = image.imagery_id or image.filename
    logger.info("inspecting file input=%s filename=%s", label, image.filename)

    if image.known_properties is None and image.content is None:
        # Nothing to inspect at all -- an unresolved imagery_id or a Storage
        # object that no longer exists (imagery_service.build_validation_image).
        # Checked before format_issues so a placeholder filename never
        # produces a confusing, unrelated UNSUPPORTED_FORMAT on top of this.
        facts = RasterFacts(error="No file content was available to inspect.")
        errors.append(ValidationIssue.of(IMAGE_UNAVAILABLE, facts.error, input=label))
        return facts

    format_issues = file_validator.format_issues(image)
    errors.extend(format_issues)
    if any(issue.code == UNSUPPORTED_FORMAT for issue in format_issues):
        # Already rejected for its extension -- don't also try (and fail) to
        # open it, which would just add a redundant FILE_CORRUPTED on top.
        return RasterFacts(error="Unsupported format.")

    if image.known_properties is not None:
        facts = raster_validator.facts_from_known_properties(image.known_properties)
    else:
        facts = raster_validator.extract_from_bytes(image.content, image.filename)

    errors.extend(raster_validator.structure_issues(facts, input_label=label))
    if facts.error:
        return facts

    logger.info(
        "metadata extracted input=%s format=%s width=%s height=%s bands=%s georeferenced=%s",
        label, facts.format, facts.width, facts.height, facts.band_count, facts.georeferenced,
    )

    dim_issue = check_dimensions(facts.width, facts.height, input_label=label, limits=limits)
    if dim_issue:
        errors.append(dim_issue)
    band_limit_issue = check_band_count(facts.band_count, input_label=label, limits=limits)
    if band_limit_issue:
        errors.append(band_limit_issue)

    return facts


def _describe(image: ImageInput, facts: RasterFacts) -> ValidatedImageInfo:
    detected_bands: list[str] = []
    modality = "unknown"
    if not facts.error:
        detected_bands = sorted(band_validator.detect_named_bands(facts))
        modality = modality_validator.detect_modality(
            facts, extension=extension_of(image.filename), sensor=image.sensor, source=image.source, hint=image.modality_hint
        )
    return ValidatedImageInfo(
        imagery_id=image.imagery_id,
        role=image.role,
        filename=image.filename,
        format=facts.format,
        width=facts.width,
        height=facts.height,
        bands=facts.band_count,
        dtype=facts.dtypes[0] if facts.dtypes else None,
        crs=facts.crs,
        georeferenced=facts.georeferenced,
        modality=modality,
        detected_bands=detected_bands,
    )


def _aoi_issues(aoi: dict, images: list[ImageInput], facts_list: list[RasterFacts]) -> list[ValidationIssue]:
    geom, issue = aoi_validator.parse_aoi(aoi)
    if issue:
        return [issue]
    labeled = [(image.imagery_id or image.filename, facts) for image, facts in zip(images, facts_list)]
    return aoi_validator.intersection_issues(geom, labeled)

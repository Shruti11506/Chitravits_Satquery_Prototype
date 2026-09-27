"""Input Validation endpoints.

Thin by design: everything that decides VALID/REJECT lives in
`app/validation/` (storage-agnostic, independently tested); these routes
only resolve `imagery_id`(s) to already-uploaded images
(`imagery_service.build_validation_image`, which reuses the existing
upload/Storage flow -- see its docstring) and hand the result to the
matching validator.

Never a 4xx/5xx for a REJECT verdict: submitting bad input to evaluate is a
successful use of these endpoints, so the envelope's `success` stays true
and the verdict is `data.status`/`data.valid` -- the same reasoning
`/health` uses for an unhealthy check. A malformed REQUEST body (missing
`workflow`, not a UUID, etc.) still gets FastAPI's normal 422.
"""
from fastapi import APIRouter

from app.schemas.common import ApiResponse
from app.services import imagery_service
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.schemas import (
    ChangeDetectionRequest,
    ChangeDetectionRequirements,
    ChangeDetectionResponse,
    ValidationRequest,
    ValidationResult,
)
from app.validation.service import validate_images

router = APIRouter(prefix="/validation", tags=["Input Validation"])


@router.post(
    "/validate",
    response_model=ApiResponse[ValidationResult],
    summary="Check whether already-uploaded images are valid input for a requested workflow",
)
def validate(payload: ValidationRequest) -> ApiResponse[ValidationResult]:
    images = [
        imagery_service.build_validation_image(
            str(image_ref.imagery_id), role=image_ref.role, modality_hint=image_ref.modality_hint
        )
        for image_ref in payload.images
    ]
    aoi = payload.aoi.model_dump() if payload.aoi else None
    result = validate_images(workflow=payload.workflow, images=images, aoi=aoi)
    return ApiResponse.ok(result)


@router.post(
    "/change-detection",
    response_model=ApiResponse[ChangeDetectionResponse],
    summary="Strict T1/T2 compatibility check for bi-temporal change detection (no change detection is run)",
)
def validate_change_detection(payload: ChangeDetectionRequest) -> ApiResponse[ChangeDetectionResponse]:
    t1 = imagery_service.build_change_detection_metadata(str(payload.t1_imagery_id), "T1")
    t2 = imagery_service.build_change_detection_metadata(str(payload.t2_imagery_id), "T2")

    defaults = ChangeDetectionRequirements()
    requirements = ChangeDetectionRequirements(
        aspect_ratio_tolerance=payload.aspect_ratio_tolerance if payload.aspect_ratio_tolerance is not None else defaults.aspect_ratio_tolerance,
        require_exact_dimensions=payload.require_exact_dimensions if payload.require_exact_dimensions is not None else defaults.require_exact_dimensions,
        require_matching_format=payload.require_matching_format if payload.require_matching_format is not None else defaults.require_matching_format,
        require_geospatial=payload.require_geospatial if payload.require_geospatial is not None else defaults.require_geospatial,
    )

    result = validate_change_detection_inputs(t1, t2, requirements)
    response = ChangeDetectionResponse(
        status="VALID" if result.valid else "REJECT",
        valid=result.valid,
        t1=imagery_service.change_detection_image_summary(t1),
        t2=imagery_service.change_detection_image_summary(t2),
        errors=result.errors,
        warnings=result.warnings,
    )
    return ApiResponse.ok(response)

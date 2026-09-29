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
    # payload.aoi is accepted for backward compatibility and ignored (AOI validation removed).
    result = validate_images(workflow=payload.workflow, images=images)
    return ApiResponse.ok(result)


@router.post(
    "/change-detection",
    response_model=ApiResponse[ChangeDetectionResponse],
    summary="Strict T1/T2 compatibility check for bi-temporal change detection (no change detection is run)",
)
def validate_change_detection(payload: ChangeDetectionRequest) -> ApiResponse[ChangeDetectionResponse]:
    t1 = imagery_service.build_change_detection_metadata(str(payload.t1_imagery_id), "T1")
    t2 = imagery_service.build_change_detection_metadata(str(payload.t2_imagery_id), "T2")

    # Default profile "chat" = the same CHAT_GATE_REQUIREMENTS `POST /analysis`
    # applies (the frontend calls this endpoint after every pair upload);
    # "profile": "strict" opts into STRICT_REQUIREMENTS. Field overrides on top.
    result = validate_change_detection_inputs(t1, t2, payload.requirements())
    first_error = result.errors[0] if result.errors else None
    response = ChangeDetectionResponse(
        status="VALID" if result.valid else "REJECT",
        valid=result.valid,
        confidence=result.confidence,
        checks=result.checks,
        check_details=result.check_details,
        ordered_bands=result.ordered_bands,
        t1=imagery_service.change_detection_image_summary(t1),
        t2=imagery_service.change_detection_image_summary(t2),
        errors=result.errors,
        warnings=result.warnings,
        error_code=first_error.code if first_error else None,
        message=first_error.message if first_error else None,
    )
    return ApiResponse.ok(response)

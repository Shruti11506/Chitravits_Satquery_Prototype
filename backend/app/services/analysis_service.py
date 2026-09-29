"""Business logic for creating analysis requests.

IMPORTANT: This service performs NO AI inference. It validates that the
referenced imagery exists and that the query is non-empty, then records an
analysis_jobs row so the API has a stable contract for a future AI/agentic
layer to consume. See CLAUDE.md.

**Change Detection Input Validation gate**: any request that references a
`comparison_imagery_id` (a T1/T2 pair) is checked with
`app.validation.change_detection_validator` BEFORE a job is created --
regardless of `analysis_type` (the frontend always sends
"general_analysis" today; a pair is a pair either way). An incompatible
pair (e.g. a JPEG/RGB scene as T1 against a Sentinel-2 multispectral
GeoTIFF as T2) never reaches `job_service.create_job`: no row, no queue, no
downstream model call. See `app/validation/__init__.py` for what that
validator does and does not do.
"""
from app.core.exceptions import ValidationAppError
from app.schemas.analysis import AnalysisCreate
from app.services import conversation_service, imagery_service, job_service
from app.validation.change_detection_validator import validate_change_detection_inputs
from app.validation.schemas import CHAT_GATE_REQUIREMENTS


def create_analysis(payload: AnalysisCreate) -> dict:
    if not payload.query or not payload.query.strip():
        raise ValidationAppError("INVALID_QUERY", "Query cannot be empty.")

    # Raises NotFoundError(IMAGE_NOT_FOUND) if the imagery doesn't exist.
    imagery_service.get_imagery(str(payload.imagery_id))

    comparison_imagery_id = str(payload.comparison_imagery_id) if payload.comparison_imagery_id else None
    if payload.analysis_type in ("change_detection", "change_vqa") and not comparison_imagery_id:
        raise ValidationAppError("IMAGE_COUNT_MISMATCH", "Change detection requires two images (T1 reference and T2 comparison).")

    if comparison_imagery_id:
        if comparison_imagery_id == str(payload.imagery_id):
            raise ValidationAppError("INVALID_IMAGE_PAIR", "An image pair needs two different images.")
        imagery_service.get_imagery(comparison_imagery_id)
        _reject_incompatible_pair(str(payload.imagery_id), comparison_imagery_id)

    conversation_id = str(payload.conversation_id) if payload.conversation_id else None
    if conversation_id:
        # Raises NotFoundError(CONVERSATION_NOT_FOUND) before any row is written.
        conversation_service.get_conversation(conversation_id)

    job = job_service.create_job(
        imagery_id=payload.imagery_id,
        analysis_type=payload.analysis_type,
        query=payload.query.strip(),
        conversation_id=conversation_id,
        comparison_imagery_id=comparison_imagery_id,
    )
    if conversation_id:
        conversation_service.touch(conversation_id)
    return job


def _reject_incompatible_pair(imagery_id: str, comparison_imagery_id: str) -> None:
    """Runs the same strict, order-stopping compatibility check as
    `POST /validation/change-detection`, with the same default chat profile
    (`CHAT_GATE_REQUIREMENTS`: identical dimensions, matching raster format
    and dtype; sensor evidence optional; geospatial checks only when an
    image is actually georeferenced, so plain JPEG/PNG pairs still work).
    Raises ValidationAppError
    (422) on the FIRST failing check, with the full failure list plus a
    T1/T2 summary attached as `error.details` for the frontend to render
    the rich "Invalid Input" message without a second round trip."""
    t1 = imagery_service.build_change_detection_metadata(imagery_id, "T1")
    t2 = imagery_service.build_change_detection_metadata(comparison_imagery_id, "T2")

    result = validate_change_detection_inputs(t1, t2, CHAT_GATE_REQUIREMENTS)
    if result.valid:
        return

    first = result.errors[0]
    raise ValidationAppError(
        first.code,
        first.message,
        details={
            "valid": False,
            "status": "REJECTED",
            "workflow": "change_detection",
            "error_code": first.code,
            "message": first.message,
            "details": {
                "t1": first.t1,
                "t2": first.t2,
            },
            "errors": [issue.model_dump() for issue in result.errors],
            "t1": _summary_dict(imagery_service.change_detection_image_summary(t1)),
            "t2": _summary_dict(imagery_service.change_detection_image_summary(t2)),
        },
    )


def _summary_dict(summary) -> dict | None:
    return summary.model_dump() if summary else None

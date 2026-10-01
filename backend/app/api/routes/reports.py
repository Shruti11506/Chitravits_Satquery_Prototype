from fastapi import APIRouter
from fastapi.responses import Response

from app.schemas.reports import ReportRequest
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.post(
    "",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}, "description": "The PDF report"}},
    summary="Generate the PDF analysis report of a conversation (or a legacy chat's image)",
)
def create_report(payload: ReportRequest) -> Response:
    # Errors still use the JSON envelope (raised as ApiError subclasses);
    # only a successful report is a binary download.
    filename, pdf = report_service.build_report(
        conversation_id=str(payload.conversation_id) if payload.conversation_id else None,
        imagery_id=str(payload.imagery_id) if payload.imagery_id else None,
        attached_model=(payload.attached_model or "").strip() or None,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

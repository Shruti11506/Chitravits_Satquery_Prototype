"""Imagery metadata + upload endpoints.

Registers and retrieves satellite imagery. `POST /imagery/upload` is the
real upload path the frontend uses (multipart file -> Supabase Storage ->
imagery metadata row); `POST /imagery` remains for metadata-only registration
when a file has already been placed in Storage some other way.
"""
import json
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.exceptions import ValidationAppError
from app.db.supabase import get_supabase
from app.schemas.common import ApiResponse, PaginatedData, PaginationMeta
from app.schemas.imagery import (
    ImageryCreate,
    ImageryCreateResponse,
    ImageryDeleteResponse,
    ImageryOut,
    ImageryPairUploadResponse,
    ImageryUploadResponse,
)
from app.services import conversation_service, imagery_service, raster_service, storage_service
from app.validation import file_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imagery", tags=["Imagery"])


@router.post(
    "",
    response_model=ApiResponse[ImageryCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Register satellite imagery metadata (no file upload)",
)
def create_imagery(payload: ImageryCreate) -> ApiResponse[ImageryCreateResponse]:
    row = imagery_service.create_imagery(payload)
    return ApiResponse.ok(ImageryCreateResponse(id=row["id"], name=row["name"]))


@router.post(
    "/upload",
    response_model=ApiResponse[ImageryUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload a satellite image to Supabase Storage and register its metadata",
)
async def upload_imagery(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    source: str | None = Form(default=None),
    sensor: str | None = Form(default=None),
    acquisition_date: datetime | None = Form(default=None),
    metadata: str | None = Form(default=None, description="JSON object, as a string"),
    conversation_id: UUID | None = Form(
        default=None,
        description="Conversation this upload belongs to. Never changes the conversation's title.",
    ),
) -> ApiResponse[ImageryUploadResponse]:
    parsed_metadata = None
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise ValidationAppError("INVALID_METADATA", "metadata must be valid JSON.") from exc
        if not isinstance(parsed_metadata, dict):
            raise ValidationAppError("INVALID_METADATA", "metadata must be a JSON object.")

    if conversation_id:
        # Checked before touching Storage so a bad id can't orphan an uploaded file.
        conversation_service.get_conversation(str(conversation_id))

    content = await file.read()
    resolved_content_type = storage_service.validate_upload(
        filename=file.filename or "", content_type=file.content_type, size=len(content)
    )
    # Every file-level check (magic bytes, MIME, readable, dimensions, dtype)
    # plus the SHA-256 digests stored in metadata -- before anything is stored.
    checked = await run_in_threadpool(file_validator.validate_file, file.filename, content, file.content_type)
    if not checked.valid:
        raise ValidationAppError(checked.issues[0].code, checked.issues[0].message)

    storage_path = storage_service.build_storage_path(file.filename)
    settings = get_settings()
    client = get_supabase()

    logger.info(
        "Received upload: filename=%s content_type=%s size=%d bytes",
        file.filename,
        resolved_content_type,
        len(content),
    )

    # TIFF/GeoTIFF: real thumbnail + georeference read from the file, before
    # anything is stored, in a worker thread (CPU-bound). None when it can't be
    # parsed -- the upload then proceeds exactly as for any other file.
    raster = None
    if imagery_service.has_raster_source(storage_path):
        raster = await run_in_threadpool(raster_service.extract, content)

    # If this raises, no database record is created -- see storage_service.upload_file.
    storage_service.upload_file(client, storage_path, content, resolved_content_type)

    # The preview is a separate object next to the untouched original, stored
    # before the row so the row records it (preview_path / preview_status).
    preview = imagery_service.store_preview(client, storage_path, raster) if raster else None

    try:
        row = imagery_service.create_imagery_from_upload(
            name=name or file.filename,
            original_filename=file.filename,
            bucket=settings.SUPABASE_STORAGE_BUCKET,
            storage_path=storage_path,
            mime_type=resolved_content_type,
            file_size=len(content),
            source=source,
            sensor=sensor,
            acquisition_date=acquisition_date,
            metadata=parsed_metadata,
            conversation_id=str(conversation_id) if conversation_id else None,
            raster=raster,
            preview=preview,
            digests=checked.digests(),
        )
    except Exception:
        # No row -> don't leave the objects this request stored behind.
        imagery_service.discard_uploaded(client, [storage_path, (preview or {}).get("preview_path")])
        raise
    if conversation_id:
        conversation_service.touch(str(conversation_id))

    thumbnail_url = imagery_service.resolve_thumbnail_url(client, row)

    return ApiResponse.ok(
        ImageryUploadResponse(
            id=row["id"],
            name=row["name"],
            original_filename=row["original_filename"],
            bucket=row["bucket"],
            storage_path=row["storage_path"],
            mime_type=row["mime_type"],
            file_size=row["file_size"],
            conversation_id=row.get("conversation_id"),
            thumbnail_url=thumbnail_url,
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            bbox=row.get("bbox"),
            cloud_cover=row.get("cloud_cover"),
            preview_path=row.get("preview_path"),
            preview_status=row.get("preview_status"),
            raster=(row.get("metadata") or {}).get("raster"),
        )
    )


def _pair_image_response(row: dict, thumbnail_url: str | None) -> ImageryUploadResponse:
    fields = {key: row.get(key) for key in ImageryUploadResponse.model_fields if key in row and key != "raster"}
    return ImageryUploadResponse(
        **fields,
        thumbnail_url=thumbnail_url,
        raster=(row.get("metadata") or {}).get("raster"),
    )


@router.post(
    "/pair",
    response_model=ApiResponse[ImageryPairUploadResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Upload an image pair (Image 1 = reference, Image 2 = comparison) as two stored images",
)
async def upload_imagery_pair(
    image_1: UploadFile | None = File(default=None, description="Image 1 -- reference image"),
    image_2: UploadFile | None = File(default=None, description="Image 2 -- comparison image"),
    conversation_id: UUID | None = Form(
        default=None,
        description="Conversation both images belong to. Never changes the conversation's title.",
    ),
) -> ApiResponse[ImageryPairUploadResponse]:
    # Everything is validated before anything is stored, so a bad Image 2
    # can never leave Image 1 behind.
    if image_1 is None or image_2 is None:
        raise ValidationAppError("IMAGE_PAIR_INCOMPLETE", "Please upload both images.")
    if conversation_id:
        conversation_service.get_conversation(str(conversation_id))

    images: list[imagery_service.PairImage] = []
    for label, upload in (("Image 1", image_1), ("Image 2", image_2)):
        content = await upload.read()
        try:
            content_type = storage_service.validate_upload(
                filename=upload.filename or "", content_type=upload.content_type, size=len(content)
            )
        except ValidationAppError as exc:
            raise ValidationAppError(exc.code, f"{label}: {exc.message}") from exc
        checked = await run_in_threadpool(file_validator.validate_file, upload.filename, content, upload.content_type)
        if not checked.valid:
            raise ValidationAppError(checked.issues[0].code, f"{label}: {checked.issues[0].message}")
        images.append(imagery_service.PairImage(
            filename=upload.filename, content=content, content_type=content_type, digests=checked.digests()
        ))

    logger.info(
        "Received image pair: %s (%d bytes) + %s (%d bytes)",
        images[0].filename, len(images[0].content), images[1].filename, len(images[1].content),
    )

    # Same TIFF/GeoTIFF handling as single uploads, per image.
    for image in images:
        if imagery_service.has_raster_source(image.filename):
            image.raster = await run_in_threadpool(raster_service.extract, image.content)

    pair_id, rows, thumbnails = await run_in_threadpool(
        imagery_service.store_image_pair, images, str(conversation_id) if conversation_id else None
    )
    if conversation_id:
        conversation_service.touch(str(conversation_id))

    return ApiResponse.ok(
        ImageryPairUploadResponse(
            pair_id=pair_id,
            image_1=_pair_image_response(rows[0], thumbnails[0]),
            image_2=_pair_image_response(rows[1], thumbnails[1]),
        )
    )


@router.get(
    "",
    response_model=ApiResponse[PaginatedData[ImageryOut]],
    summary="List registered imagery",
)
def list_imagery(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[PaginatedData[ImageryOut]]:
    items, total = imagery_service.list_imagery(page=page, page_size=page_size)
    return ApiResponse.ok(
        PaginatedData(
            items=[ImageryOut(**item) for item in items],
            pagination=PaginationMeta(page=page, page_size=page_size, total=total),
        )
    )


@router.get(
    "/{imagery_id}",
    response_model=ApiResponse[ImageryOut],
    summary="Get imagery metadata by id, with a freshly-resolved access URL",
)
def get_imagery(imagery_id: UUID) -> ApiResponse[ImageryOut]:
    row = imagery_service.get_imagery_with_url(str(imagery_id))
    return ApiResponse.ok(ImageryOut(**row))


@router.delete(
    "/{imagery_id}",
    response_model=ApiResponse[ImageryDeleteResponse],
    summary="Delete an imagery record and its Storage object",
)
def delete_imagery(imagery_id: UUID) -> ApiResponse[ImageryDeleteResponse]:
    imagery_service.delete_imagery(str(imagery_id))
    return ApiResponse.ok(ImageryDeleteResponse(id=imagery_id))

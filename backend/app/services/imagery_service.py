"""Business logic for the imagery resource. No route or HTTP concerns here."""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, SchemaNotMigratedError, StorageError, SupabaseError
from app.db.supabase import get_supabase
from app.schemas.imagery import ImageryCreate
from app.services import raster_service, storage_service

logger = logging.getLogger(__name__)

TABLE = "imagery"

# imagery.preview_status (migration 0007). NULL = no preview attempted yet
# (non-TIFF rows always stay NULL: the browser shows the original).
PREVIEW_READY = "ready"
PREVIEW_FAILED = "failed"


def create_imagery(payload: ImageryCreate) -> dict:
    client = get_supabase()
    row = payload.model_dump(mode="json", exclude_none=True)

    try:
        response = client.table(TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001 - translate any client/network failure
        logger.exception("Supabase insert failed for imagery")
        raise SupabaseError("Failed to register imagery.") from exc

    if not response.data:
        raise SupabaseError("Imagery insert returned no data.")

    return response.data[0]


def create_imagery_from_upload(
    *,
    name: str,
    original_filename: str,
    bucket: str,
    storage_path: str,
    mime_type: str,
    file_size: int,
    source: str | None,
    sensor: str | None,
    acquisition_date: datetime | None,
    metadata: dict[str, Any] | None,
    conversation_id: str | None = None,
    raster: raster_service.RasterInfo | None = None,
    preview: dict[str, Any] | None = None,
) -> dict:
    """Insert the imagery metadata row after a successful Storage upload.

    Must only be called once storage_service.upload_file() has succeeded --
    this never uploads anything itself, it only persists metadata.
    `preview` is store_preview()'s result for a TIFF (preview_path/status).
    """
    client = get_supabase()
    row = build_upload_row(
        name=name,
        original_filename=original_filename,
        bucket=bucket,
        storage_path=storage_path,
        mime_type=mime_type,
        file_size=file_size,
        source=source,
        sensor=sensor,
        acquisition_date=acquisition_date,
        metadata=metadata,
        conversation_id=conversation_id,
        raster=raster,
    )
    if preview:
        row.update(preview)

    try:
        response = client.table(TABLE).insert(row).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for uploaded imagery %s/%s", bucket, storage_path)
        if preview and getattr(exc, "code", None) in _MISSING_COLUMN_CODES:
            raise SchemaNotMigratedError(PREVIEW_MIGRATION_HINT) from exc
        raise SupabaseError("Image uploaded to Storage but failed to save its metadata.") from exc

    if not response.data:
        raise SupabaseError("Imagery insert returned no data.")

    created = response.data[0]
    logger.info("Database record created for imagery id=%s", created.get("id"))
    return created


def build_upload_row(
    *,
    name: str,
    original_filename: str,
    bucket: str,
    storage_path: str,
    mime_type: str,
    file_size: int,
    source: str | None = None,
    sensor: str | None = None,
    acquisition_date: datetime | None = None,
    metadata: dict[str, Any] | None = None,
    conversation_id: str | None = None,
    raster: raster_service.RasterInfo | None = None,
) -> dict[str, Any]:
    """The imagery row for a stored upload -- shared by single and pair uploads."""
    row: dict[str, Any] = {
        "name": name,
        "original_filename": original_filename,
        "bucket": bucket,
        "storage_path": storage_path,
        "mime_type": mime_type,
        "file_size": file_size,
        "source": source,
        "sensor": sensor,
        "acquisition_date": acquisition_date.isoformat() if acquisition_date else None,
        "metadata": metadata,
    }
    if conversation_id:
        row["conversation_id"] = conversation_id
    if raster:
        # Only what the file itself carries; absent values stay NULL.
        for column in ("latitude", "longitude", "bbox", "cloud_cover"):
            value = getattr(raster, column)
            if value is not None:
                row[column] = value
        row["metadata"] = {**(metadata or {}), "raster": raster_metadata(raster)}
    return row


def raster_metadata(raster: raster_service.RasterInfo) -> dict[str, Any]:
    """What the TIFF is and how its preview was made -- stored in imagery.metadata["raster"]."""
    return {
        "properties": raster.properties,
        "preview": raster.preview,
        "preview_error": raster.preview_error,
    }


PREVIEW_MIGRATION_HINT = (
    "TIFF previews are not set up yet: apply "
    "backend/supabase/migrations/0007_imagery_previews.sql in the Supabase SQL editor."
)


def store_preview(client, storage_path: str, raster: raster_service.RasterInfo | None) -> dict[str, Any]:
    """Store a TIFF's rendered preview next to the original -> the row's preview fields.

    The original is never touched. A preview that couldn't be rendered or
    stored gives preview_status "failed" (the reason is kept in
    raster.preview_error); the upload itself still succeeds.
    """
    if raster is None or not raster.thumbnail_png:
        return {"preview_path": None, "preview_status": PREVIEW_FAILED}
    preview_path = raster_service.thumbnail_path_for(storage_path)
    try:
        storage_service.upload_file(client, preview_path, raster.thumbnail_png, "image/png", upsert=True)
    except Exception:  # noqa: BLE001
        logger.warning("Preview upload failed for %s; the original is stored and unaffected", storage_path)
        raster.preview_error = raster.preview_error or "The preview was generated but could not be stored."
        return {"preview_path": None, "preview_status": PREVIEW_FAILED}
    return {"preview_path": preview_path, "preview_status": PREVIEW_READY}


PAIR_MIGRATION_HINT = (
    "Image pairs are not set up yet: apply "
    "backend/supabase/migrations/0006_image_pairs.sql in the Supabase SQL editor."
)
# Missing column on insert (PGRST204) or in a filter/select (42703).
_MISSING_COLUMN_CODES = {"PGRST204", "42703"}


@dataclass
class PairImage:
    """One validated file of an image pair, ready to store."""

    filename: str
    content: bytes
    content_type: str
    raster: raster_service.RasterInfo | None = None


def discard_uploaded(client, storage_paths: list[str | None]) -> None:
    """Compensating cleanup for objects THIS request just uploaded -- never anything else."""
    for path in filter(None, storage_paths):
        try:
            storage_service.delete_file(client, path)
        except StorageError:
            logger.error("Could not remove %s after a failed pair upload -- orphaned file.", path)


def store_image_pair(images: list[PairImage], conversation_id: str | None = None) -> tuple[str, list[dict], list[str | None]]:
    """Store both images of a pair: two Storage objects, then both rows in ONE insert.

    All-or-nothing for the pair: if Image 2's upload or the insert fails, the
    objects this request uploaded are removed again, so there is never a
    half-stored pair (a single PostgREST insert of both rows is one statement,
    so the rows land together or not at all). Thumbnails are best-effort and
    come last, exactly as for single uploads.

    Returns (pair_id, [row 1, row 2], [thumbnail url 1, thumbnail url 2]).
    """
    if len(images) != 2:
        raise ValueError("An image pair has exactly two images.")

    client = get_supabase()
    bucket = get_settings().SUPABASE_STORAGE_BUCKET
    pair_id = str(uuid.uuid4())
    paths = [storage_service.build_storage_path(image.filename) for image in images]

    uploaded: list[str] = []
    try:
        for image, path in zip(images, paths):
            storage_service.upload_file(client, path, image.content, image.content_type)
            uploaded.append(path)
    except Exception:
        discard_uploaded(client, uploaded)
        raise

    previews = [store_preview(client, path, image.raster) if image.raster else None for image, path in zip(images, paths)]
    uploaded += [preview["preview_path"] for preview in previews if preview]

    rows = []
    for position, (image, path, preview) in enumerate(zip(images, paths, previews), start=1):
        row = build_upload_row(
            name=image.filename,
            original_filename=image.filename,
            bucket=bucket,
            storage_path=path,
            mime_type=image.content_type,
            file_size=len(image.content),
            conversation_id=conversation_id,
            raster=image.raster,
        )
        row["pair_id"] = pair_id
        row["pair_position"] = position
        if preview:
            row.update(preview)
        rows.append(row)

    try:
        response = client.table(TABLE).insert(rows).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase insert failed for image pair %s", pair_id)
        discard_uploaded(client, uploaded)
        if getattr(exc, "code", None) in _MISSING_COLUMN_CODES:
            missing_preview = "preview" in str(getattr(exc, "message", exc))
            raise SchemaNotMigratedError(PREVIEW_MIGRATION_HINT if missing_preview else PAIR_MIGRATION_HINT) from exc
        raise SupabaseError("Failed to save the image pair; the uploaded files were removed.") from exc

    created = sorted(response.data or [], key=lambda r: r.get("pair_position") or 0)
    if len(created) != 2:
        raise SupabaseError("Image pair insert returned unexpected data.")
    logger.info("Image pair %s stored: %s + %s", pair_id, created[0]["id"], created[1]["id"])

    thumbnails = [resolve_thumbnail_url(client, row) for row in created]
    return pair_id, created, thumbnails


def list_imagery(page: int, page_size: int) -> tuple[list[dict], int]:
    client = get_supabase()
    start = (page - 1) * page_size
    end = start + page_size - 1

    try:
        response = (
            client.table(TABLE)
            .select("*", count="exact")
            .order("created_at", desc=True)
            .range(start, end)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase list failed for imagery")
        raise SupabaseError("Failed to list imagery.") from exc

    rows = []
    for r in (response.data or []):
        row = dict(r)
        row["url"] = storage_service.resolve_url(client, row.get("storage_path"), missing_ok=True)
        row["thumbnail_url"] = resolve_thumbnail_url(client, row)
        rows.append(row)

    return rows, response.count or 0


def get_imagery(imagery_id: str) -> dict:
    client = get_supabase()

    try:
        response = client.table(TABLE).select("*").eq("id", imagery_id).maybe_single().execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase get failed for imagery %s", imagery_id)
        raise SupabaseError("Failed to fetch imagery.") from exc

    if not response or not response.data:
        raise NotFoundError("IMAGE_NOT_FOUND", f"Imagery '{imagery_id}' was not found.")

    return response.data


def has_raster_source(storage_path: str | None) -> bool:
    """TIFF uploads are the only ones that ever get a generated thumbnail."""
    return bool(storage_path) and storage_service.get_extension(storage_path) in storage_service.RASTER_EXTENSIONS


def resolve_thumbnail_url(client, row: dict) -> str | None:
    """Signed URL of a TIFF row's stored preview, or None when it has none.

    Uses the recorded preview_path. A TIFF row that has never had a preview
    attempted (stored before previews were recorded, or by a backend without
    the preview pipeline) gets one generated ONCE here, and the outcome is
    written back to the row -- so it is never regenerated on later opens.
    Updates `row` in place with any preview fields it fills.
    """
    storage_path = row.get("storage_path")
    if not has_raster_source(storage_path):
        return None
    if "preview_status" not in row:
        # Migration 0007 not applied: previews are only found at their conventional path.
        return storage_service.resolve_url(client, raster_service.thumbnail_path_for(storage_path), missing_ok=True)
    if row.get("preview_status") is None and row.get("id"):
        row.update(ensure_preview(client, row))
    if not row.get("preview_path"):
        return None
    return storage_service.resolve_url(client, row["preview_path"], missing_ok=True)


def ensure_preview(client, row: dict) -> dict[str, Any]:
    """One-time preview (and georeference) for an older TIFF row -> the fields it changed.

    Reuses a preview already sitting at the conventional path; otherwise reads
    the ORIGINAL from Storage (read-only), renders it and stores the preview.
    A transient Storage error records nothing, so the next open tries again.
    """
    storage_path = row["storage_path"]
    preview_path = raster_service.thumbnail_path_for(storage_path)
    if storage_service.object_exists(client, preview_path):
        changes: dict[str, Any] = {"preview_path": preview_path, "preview_status": PREVIEW_READY}
    else:
        try:
            content = storage_service.download_file(client, storage_path)
        except StorageError:
            if storage_service.object_exists(client, storage_path):
                return {}  # transient: leave it unrecorded and retry on the next open
            raster = raster_service.RasterInfo(
                thumbnail_png=None, preview_error="The original file is missing from Storage."
            )
        else:
            raster = raster_service.extract(content)
        changes = store_preview(client, storage_path, raster)
        changes["metadata"] = {**(row.get("metadata") or {}), "raster": raster_metadata(raster)}
        for column in ("latitude", "longitude", "bbox", "cloud_cover"):
            value = getattr(raster, column)
            if row.get(column) is None and value is not None:
                changes[column] = value

    try:
        client.table(TABLE).update(changes).eq("id", row["id"]).execute()
        logger.info("Recorded preview for imagery %s: %s", row["id"], changes["preview_status"])
    except Exception:  # noqa: BLE001 - still shown this time; recorded on a later open
        logger.exception("Could not record the preview for imagery %s", row["id"])
    return changes


def get_imagery_with_url(imagery_id: str) -> dict:
    row = get_imagery(imagery_id)
    client = get_supabase()
    row = dict(row)
    row["url"] = storage_service.resolve_url(client, row.get("storage_path"))
    row["thumbnail_url"] = resolve_thumbnail_url(client, row)
    return row


def delete_imagery(imagery_id: str) -> None:
    # Confirms existence first so callers get a proper 404 instead of a silent no-op.
    row = get_imagery(imagery_id)

    client = get_supabase()
    storage_path = row.get("storage_path")

    # DB delete runs FIRST, deliberately -- not storage-first. imagery.id has
    # an incoming FK from analysis_jobs.imagery_id, so the DB delete can fail
    # (e.g. a job still references this image) for reasons having nothing to
    # do with Storage. Deleting the Storage object before confirming the DB
    # delete would succeed risks exactly the orphaned-record state the spec
    # warns against: a DB row whose storage_path points at a file that's
    # already gone. Running the DB delete first means a blocked delete (FK
    # violation, etc.) leaves both sides untouched and consistent.
    try:
        client.table(TABLE).delete().eq("id", imagery_id).execute()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase delete failed for imagery %s", imagery_id)
        raise SupabaseError("Failed to delete imagery.") from exc

    if storage_path:
        try:
            storage_service.delete_file(client, storage_path)
        except StorageError:
            # The DB record is already gone at this point -- the Storage
            # object is now orphaned. There is no distributed transaction
            # across Postgres and Storage to roll back with, so this is
            # logged loudly for manual cleanup rather than silently retried.
            logger.error(
                "Imagery record %s was deleted but its Storage object %s/%s could NOT be "
                "deleted -- orphaned file, needs manual cleanup.",
                imagery_id,
                get_settings().SUPABASE_STORAGE_BUCKET,
                storage_path,
            )
            raise

        if has_raster_source(storage_path):
            try:
                storage_service.delete_file(client, raster_service.thumbnail_path_for(storage_path))
            except StorageError:
                logger.error("Thumbnail for deleted imagery %s could not be removed -- orphaned file.", imagery_id)

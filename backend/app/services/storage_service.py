"""Supabase Storage helpers -- the only module that talks to `client.storage`.

Scope: upload/delete objects in the existing `Satquery` bucket (see
app/core/config.py) and resolve an accessible URL for an object, respecting
whatever public/private configuration the bucket already has. This module
never creates or modifies buckets.
"""
import logging
import uuid

from app.core.config import get_settings
from app.core.exceptions import StorageError, ValidationAppError

logger = logging.getLogger(__name__)

IMAGERY_PREFIX = "imagery"
RESULTS_PREFIX = "results"
EVIDENCE_PREFIX = "evidence"
EXPORTS_PREFIX = "exports"

# Preview-friendly image formats vs. remote-sensing raster formats -- both
# accepted, kept separate only so callers/logs can tell which kind a file is.
PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
RASTER_EXTENSIONS = {".tif", ".tiff"}
ALLOWED_EXTENSIONS = PREVIEW_EXTENSIONS | RASTER_EXTENSIONS

CONTENT_TYPE_BY_EXTENSION = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

# Short-lived: only used to let the frontend display an already-uploaded
# image, re-resolved on every GET rather than stored permanently.
SIGNED_URL_TTL_SECONDS = 3600


def get_extension(filename: str) -> str:
    if "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def validate_upload(filename: str, content_type: str | None, size: int) -> str:
    """Validate an incoming upload; returns the resolved content type or raises."""
    if not filename or not filename.strip():
        raise ValidationAppError("MISSING_FILENAME", "The uploaded file must have a filename.")

    extension = get_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationAppError(
            "UNSUPPORTED_FILE_TYPE",
            "Supported formats are JPG, JPEG, PNG, WEBP, TIF and TIFF.",
        )

    settings = get_settings()
    if size <= 0:
        raise ValidationAppError("EMPTY_FILE", "The uploaded file is empty.")
    if size > settings.max_upload_size_bytes:
        raise ValidationAppError(
            "FILE_TOO_LARGE",
            f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB upload limit.",
        )

    resolved_content_type = CONTENT_TYPE_BY_EXTENSION[extension]
    if content_type and content_type not in ("application/octet-stream", ""):
        # Trust the extension over a generic/mismatched browser content-type,
        # but keep whatever specific type the client sent if it's plausible.
        if content_type.startswith("image/"):
            resolved_content_type = content_type

    return resolved_content_type


PROJECTS_PREFIX = "projects"

# Project knowledge files: AOI vectors, reference rasters, briefs, tables --
# what the Projects "Knowledge Files" tab invites, and nothing executable.
PROJECT_FILE_CONTENT_TYPES = {
    ".geojson": "application/geo+json",
    ".json": "application/json",
    ".kml": "application/vnd.google-earth.kml+xml",
    ".kmz": "application/vnd.google-earth.kmz",
    ".gpkg": "application/geopackage+sqlite3",
    ".shp": "application/octet-stream",
    ".shx": "application/octet-stream",
    ".dbf": "application/octet-stream",
    ".prj": "text/plain",
    ".zip": "application/zip",
    ".pdf": "application/pdf",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    **CONTENT_TYPE_BY_EXTENSION,  # images and TIFF/GeoTIFF rasters
}


def validate_project_file(filename: str, size: int) -> str:
    """Validate a project knowledge file; returns its content type or raises."""
    if not filename or not filename.strip():
        raise ValidationAppError("MISSING_FILENAME", "The uploaded file must have a filename.")
    content_type = PROJECT_FILE_CONTENT_TYPES.get(get_extension(filename))
    if content_type is None:
        raise ValidationAppError(
            "UNSUPPORTED_FILE_TYPE",
            "Supported project files: GeoJSON, KML/KMZ, GeoPackage, shapefile parts or ZIP, "
            "PDF, CSV, TXT/MD, TIFF/GeoTIFF, PNG, JPEG and WEBP.",
        )
    settings = get_settings()
    if size <= 0:
        raise ValidationAppError("EMPTY_FILE", "The uploaded file is empty.")
    if size > settings.max_upload_size_bytes:
        raise ValidationAppError("FILE_TOO_LARGE", f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB upload limit.")
    return content_type


def build_storage_path(filename: str, prefix: str = IMAGERY_PREFIX) -> str:
    unique_id = str(uuid.uuid4())
    safe_filename = filename.strip().replace("/", "_")
    return f"{prefix}/{unique_id}/{safe_filename}"


def upload_file(client, storage_path: str, content: bytes, content_type: str, upsert: bool = False) -> None:
    """Upload bytes to the configured bucket. Raises StorageError on any failure.

    upsert: overwrite an existing object -- only for generated previews, which
    two concurrent requests may both write; never for user originals.
    """
    settings = get_settings()
    bucket = settings.SUPABASE_STORAGE_BUCKET

    logger.info(
        "Uploading to Supabase Storage: bucket=%s path=%s size=%d content_type=%s",
        bucket,
        storage_path,
        len(content),
        content_type,
    )

    try:
        result = client.storage.from_(bucket).upload(
            storage_path,
            content,
            {"content-type": content_type, **({"upsert": "true"} if upsert else {})},
        )
    except Exception as exc:  # noqa: BLE001 - translate any client/network failure
        logger.exception("Supabase Storage upload raised for %s/%s", bucket, storage_path)

        # Our own pre-check in validate_upload() already rejects anything over
        # MAX_UPLOAD_SIZE_MB before this point, but if the project's actual
        # Supabase-side limit is *lower* than our configured value (e.g. our
        # setting is stale), Supabase itself will reject the upload -- surface
        # that distinctly as FILE_TOO_LARGE instead of a generic failure.
        status = str(getattr(exc, "status", "")).lower()
        message = str(getattr(exc, "message", "")).lower()
        if "413" in status or "exceeded" in message or "maximum allowed size" in message or "too large" in message:
            # Same FILE_TOO_LARGE code as the pre-upload size check in
            # validate_upload() -- same 422, regardless of which layer caught
            # it, so callers don't need to special-case where it came from.
            raise ValidationAppError(
                "FILE_TOO_LARGE",
                f"File exceeds Supabase's configured upload limit ({settings.MAX_UPLOAD_SIZE_MB} MB or less).",
            ) from exc

        raise StorageError(
            "Failed to upload the image to Supabase Storage.", code="STORAGE_UPLOAD_FAILED"
        ) from exc

    # supabase-py raises on HTTP error responses, but double-check for the
    # dict-shaped error some client versions return instead of raising.
    if isinstance(result, dict) and result.get("error"):
        logger.error("Supabase Storage upload returned an error: %s", result["error"])
        raise StorageError(
            "Failed to upload the image to Supabase Storage.", code="STORAGE_UPLOAD_FAILED"
        )

    logger.info("Upload succeeded: bucket=%s path=%s", bucket, storage_path)


def download_file(client, storage_path: str) -> bytes:
    """Read an object's bytes. Raises StorageError on any failure."""
    settings = get_settings()
    try:
        return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).download(storage_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supabase Storage download failed for %s", storage_path)
        raise StorageError("Failed to read the file from Supabase Storage.", code="STORAGE_DOWNLOAD_FAILED") from exc


def object_exists(client, storage_path: str) -> bool:
    """Whether an object exists (lists its folder; no download)."""
    settings = get_settings()
    folder, name = storage_path.rsplit("/", 1)
    try:
        entries = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).list(folder, {"search": name})
    except Exception:  # noqa: BLE001
        logger.warning("Supabase Storage list failed for %s", folder)
        return False
    return any((entry or {}).get("name") == name for entry in entries or [])


def delete_file(client, storage_path: str) -> None:
    """Delete an object from the configured bucket. Raises StorageError on failure."""
    settings = get_settings()
    bucket = settings.SUPABASE_STORAGE_BUCKET

    try:
        result = client.storage.from_(bucket).remove([storage_path])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supabase Storage delete raised for %s/%s", bucket, storage_path)
        raise StorageError("Failed to delete the image from Supabase Storage.") from exc

    if isinstance(result, dict) and result.get("error"):
        logger.error("Supabase Storage delete returned an error: %s", result["error"])
        raise StorageError("Failed to delete the image from Supabase Storage.")

    logger.info("Delete succeeded: bucket=%s path=%s", bucket, storage_path)


def is_bucket_public(client) -> bool:
    settings = get_settings()
    bucket_info = client.storage.get_bucket(settings.SUPABASE_STORAGE_BUCKET)
    if isinstance(bucket_info, dict):
        return bool(bucket_info.get("public"))
    return bool(getattr(bucket_info, "public", False))


def resolve_url(client, storage_path: str | None, missing_ok: bool = False) -> str | None:
    """Resolve an accessible URL for an object, respecting bucket privacy.

    Returns None if storage_path is empty or resolution fails -- callers
    should treat this as optional, not a guarantee the object is reachable.
    missing_ok: the object may legitimately not exist (e.g. a TIFF whose
    thumbnail couldn't be generated), so a failure isn't logged as an error.
    """
    if not storage_path:
        return None

    settings = get_settings()
    bucket = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET)

    try:
        if is_bucket_public(client):
            result = bucket.get_public_url(storage_path)
            return result if isinstance(result, str) else result.get("publicUrl") if result else None

        result = bucket.create_signed_url(storage_path, SIGNED_URL_TTL_SECONDS)
        if isinstance(result, dict):
            return result.get("signedURL") or result.get("signed_url")
        return getattr(result, "signed_url", None)
    except Exception:  # noqa: BLE001 - URL resolution is best-effort
        if missing_ok:
            logger.debug("No object to resolve a URL for at %s", storage_path)
        else:
            logger.exception("Failed to resolve URL for %s/%s", bucket, storage_path)
        return None

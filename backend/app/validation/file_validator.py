"""File validation -- the ONE place every file-level check lives.

`validate_file` runs at upload (`api/routes/imagery.py`, single and pair)
and again whenever a stored image is used (`service.py`'s pipeline, the
change-detection validator via `imagery_service`), so a bad file already in
Storage is caught too:

    empty -> size -> extension -> magic bytes -> declared MIME ->
    readable (Pillow / rasterio header) -> dimensions / pixel ceiling ->
    band count -> dtype

It also returns two SHA-256 digests, stored in `imagery.metadata` at upload
(no new column): `sha256` of the file bytes, and `pixel_sha256` of the
decoded pixels (shape + dtype + every pixel, read in row strips so a large
raster is never held in memory at once) -- what change detection uses to
spot the same image uploaded twice, even re-saved with different metadata.

JPEG/PNG/WebP are non-georeferenced by policy; no CRS is required here.
Geospatial checks belong to the workflows that need them.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field

from app.core.config import get_settings
from app.validation.errors import (
    EMPTY_FILE,
    FILE_CORRUPTED,
    FILE_TOO_LARGE,
    FILE_TYPE_MISMATCH,
    INVALID_DIMENSIONS,
    UNSUPPORTED_DTYPE,
    UNSUPPORTED_FILE_TYPE,
    ValidationIssue,
)
from app.validation.raster_validator import SUPPORTED_EXTENSIONS, TIFF_EXTENSIONS, extension_of, extract_from_bytes
from app.validation.schemas import ImageInput, RasterFacts

logger = logging.getLogger(__name__)

SUPPORTED_DTYPES = frozenset({"uint8", "uint16", "int16", "float32"})

# extension -> detected file kind
_KIND_BY_EXTENSION = {
    ".tif": "tiff", ".tiff": "tiff", ".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png", ".webp": "webp",
}
# declared MIME -> file kind. Generic / missing types say nothing and are ignored.
_KIND_BY_MIME = {
    "image/tiff": "tiff", "image/tif": "tiff", "image/x-tiff": "tiff", "image/geotiff": "tiff",
    "image/jpeg": "jpeg", "image/jpg": "jpeg", "image/pjpeg": "jpeg",
    "image/png": "png", "image/webp": "webp",
}
_UNINFORMATIVE_MIMES = {"", "application/octet-stream", "binary/octet-stream"}
_STRIP_ROWS = 256  # rows read per strip when hashing TIFF pixels
_CHUNK = 1 << 20


def sniff_kind(content: bytes) -> str | None:
    """File kind from its magic bytes. TIFF incl. BigTIFF, both byte orders."""
    head = content[:12]
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
        return "tiff"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def sha256_of(content: bytes) -> str:
    """SHA-256 of the bytes, fed in 1 MB chunks (no second copy of the file)."""
    digest = hashlib.sha256()
    view = memoryview(content)
    for start in range(0, len(view), _CHUNK):
        digest.update(view[start:start + _CHUNK])
    return digest.hexdigest()


def pixel_sha256(content: bytes, filename: str) -> str | None:
    """SHA-256 of the decoded pixels, prefixed with shape and dtype, so two
    files with identical pixels but different metadata / compression /
    tiling hash the same. None when the file can't be decoded."""
    try:
        if extension_of(filename) in TIFF_EXTENSIONS:
            return _tiff_pixel_sha256(content)
        return _pillow_pixel_sha256(content)
    except Exception:  # noqa: BLE001 - an undecodable file simply has no pixel digest
        logger.info("Could not compute a pixel digest for %s", filename)
        return None


def _tiff_pixel_sha256(content: bytes) -> str:
    import numpy as np
    from rasterio.io import MemoryFile
    from rasterio.windows import Window

    with MemoryFile(content) as mem, mem.open() as src:
        digest = hashlib.sha256(f"tiff:{src.width}x{src.height}x{src.count}:{','.join(src.dtypes)}".encode())
        for row in range(0, src.height, _STRIP_ROWS):
            strip = src.read(window=Window(0, row, src.width, min(_STRIP_ROWS, src.height - row)))
            digest.update(np.ascontiguousarray(strip).tobytes())
        return digest.hexdigest()


def _pillow_pixel_sha256(content: bytes) -> str:
    from PIL import Image

    with Image.open(io.BytesIO(content)) as img:
        img.load()
        digest = hashlib.sha256(f"image:{img.width}x{img.height}:{img.mode}".encode())
        digest.update(img.tobytes())
        return digest.hexdigest()


@dataclass
class FileValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    kind: str | None = None  # "tiff" | "jpeg" | "png" | "webp", from the magic bytes
    facts: RasterFacts | None = None
    sha256: str | None = None
    pixel_sha256: str | None = None

    @property
    def valid(self) -> bool:
        return not self.issues

    def digests(self) -> dict[str, str]:
        """What upload stores in imagery.metadata."""
        return {key: value for key, value in (("sha256", self.sha256), ("pixel_sha256", self.pixel_sha256)) if value}


def validate_file(
    filename: str,
    content: bytes,
    declared_mime: str | None = None,
    *,
    input_label: str | None = None,
    compute_digests: bool = True,
) -> FileValidationResult:
    """Every file-level check, in order; stops at the first failure."""
    label = input_label or filename
    result = FileValidationResult()

    def fail(code: str, message: str) -> FileValidationResult:
        result.issues.append(ValidationIssue.of(code, message, input=label))
        return result

    if not content:
        return fail(EMPTY_FILE, "The file is empty.")
    size_issue = size_limit_issue(len(content), input_label=label)
    if size_issue:
        result.issues.append(size_issue)
        return result

    extension = extension_of(filename)
    if extension not in SUPPORTED_EXTENSIONS:
        return fail(
            UNSUPPORTED_FILE_TYPE,
            f"'{extension or filename}' is not supported. Supported formats: TIF, TIFF, JPG, JPEG, PNG, WEBP.",
        )

    result.kind = sniff_kind(content)
    expected = _KIND_BY_EXTENSION[extension]
    if result.kind != expected:
        found = result.kind.upper() if result.kind else "an unrecognised format"
        return fail(FILE_TYPE_MISMATCH, f"The file is named {extension} but its content is {found}.")

    mime = (declared_mime or "").split(";")[0].strip().lower()
    if mime not in _UNINFORMATIVE_MIMES and _KIND_BY_MIME.get(mime) != result.kind:
        return fail(FILE_TYPE_MISMATCH, f"The declared type '{mime}' does not match the file's content ({result.kind.upper()}).")

    result.facts = extract_from_bytes(content, filename)
    for issue in facts_issues(result.facts, input_label=label):
        result.issues.append(issue)
        return result

    if compute_digests:
        result.sha256 = sha256_of(content)
        result.pixel_sha256 = pixel_sha256(content, filename)
        if result.pixel_sha256 is None:
            # The header parsed, but reading every pixel failed: truncated or corrupt data.
            return fail(FILE_CORRUPTED, "The file's pixel data could not be read (truncated or corrupt).")
    return result


def size_limit_issue(size_bytes: int | None, *, input_label: str) -> ValidationIssue | None:
    settings = get_settings()
    if size_bytes is not None and size_bytes > settings.max_upload_size_bytes:
        return ValidationIssue.of(
            FILE_TOO_LARGE, f"File is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.", input=input_label
        )
    return None


def facts_issues(facts: RasterFacts, *, input_label: str) -> list[ValidationIssue]:
    """The checks that need only the file's structure -- also used for a
    stored TIFF whose structure was recorded at upload (no re-download)."""
    if facts.error:
        return [ValidationIssue.of(facts.error_code or FILE_CORRUPTED, facts.error, input=input_label)]
    if not facts.width or not facts.height or facts.width <= 0 or facts.height <= 0:
        return [ValidationIssue.of(INVALID_DIMENSIONS, "The image has zero or invalid width/height.", input=input_label)]
    max_pixels = get_settings().VALIDATION_MAX_PIXELS
    if facts.width * facts.height > max_pixels:
        return [ValidationIssue.of(
            INVALID_DIMENSIONS,
            f"The image is {facts.width}x{facts.height} px, above the {max_pixels:,}-pixel limit.",
            input=input_label,
        )]
    if not facts.band_count or facts.band_count < 1:
        return [ValidationIssue.of(INVALID_DIMENSIONS, "The image has no bands.", input=input_label)]
    unsupported = sorted({d for d in facts.dtypes if d not in SUPPORTED_DTYPES})
    if unsupported:
        return [ValidationIssue.of(
            UNSUPPORTED_DTYPE,
            f"Pixel data type {', '.join(unsupported)} is not supported (supported: {', '.join(sorted(SUPPORTED_DTYPES))}).",
            input=input_label,
        )]
    return []


def format_issues(image: ImageInput) -> list[ValidationIssue]:
    """The byte-level checks for `service.py`'s pipeline (which opens the file
    itself afterwards): empty, size, extension, magic bytes, MIME. A stored
    TIFF passed as `known_properties` (no bytes) gets only the checks that
    don't need bytes."""
    label = image.imagery_id or image.filename
    extension = extension_of(image.filename)
    if extension not in SUPPORTED_EXTENSIONS:
        return [ValidationIssue.of(
            UNSUPPORTED_FILE_TYPE,
            f"'{extension or image.filename}' is not supported. Supported formats: TIF, TIFF, JPG, JPEG, PNG, WEBP.",
            input=label,
        )]
    if image.content is None:
        size_issue = size_limit_issue(image.size_bytes, input_label=label)
        return [size_issue] if size_issue else []
    result = validate_file(
        image.filename, image.content, image.content_type, input_label=label, compute_digests=False
    )
    # Readability / dimensions / dtype are reported by the pipeline's own
    # structure pass; keep only the byte-level findings here.
    return [issue for issue in result.issues if issue.code not in (FILE_CORRUPTED, INVALID_DIMENSIONS, UNSUPPORTED_DTYPE)]

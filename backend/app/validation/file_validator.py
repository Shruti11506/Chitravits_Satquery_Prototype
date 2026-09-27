"""File-level checks (task brief section 2): extension, declared content
type, and size -- everything that can be decided WITHOUT opening the file.

Actually opening the file (readability/corruption) is `raster_validator`'s
job (`extract_from_bytes` + `structure_issues`): the brief lists corruption
under both "file format" and "raster structure", but this module doesn't
duplicate that parse -- `service.py` runs it once and both concerns are
covered from that one pass.
"""
from __future__ import annotations

from app.validation.errors import FILE_CORRUPTED, UNSUPPORTED_FORMAT, ValidationIssue
from app.validation.limits import check_file_size
from app.validation.raster_validator import SUPPORTED_EXTENSIONS, extension_of
from app.validation.schemas import ImageInput

# What each supported extension's bytes should start with, when a signature
# is cheap and reliable to check -- catches "renamed .exe to .jpg" before
# ever handing it to Pillow/rasterio. JPEG/PNG have fixed magic bytes; TIFF
# has two (little/big-endian), and a GeoTIFF is still a plain TIFF at the
# byte level, so no separate signature is needed for it.
_MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".tif": (b"II*\x00", b"MM\x00*"),
    ".tiff": (b"II*\x00", b"MM\x00*"),
}


def format_issues(image: ImageInput) -> list[ValidationIssue]:
    """UNSUPPORTED_FORMAT / FILE_TOO_LARGE only. Empty means: proceed to
    actually opening the file (raster_validator)."""
    label = image.imagery_id or image.filename
    issues: list[ValidationIssue] = []

    extension = extension_of(image.filename)
    if extension not in SUPPORTED_EXTENSIONS:
        issues.append(ValidationIssue.of(
            UNSUPPORTED_FORMAT,
            f"'{extension or image.filename}' is not supported. Supported formats: "
            "TIF, TIFF, JPG, JPEG, PNG.",
            input=label,
        ))
        return issues  # nothing else to check against an extension we don't recognize

    if image.content is not None:
        signature = _MAGIC_BYTES.get(extension)
        if signature and not image.content.startswith(signature):
            issues.append(ValidationIssue.of(
                FILE_CORRUPTED,
                f"The file's content does not match a {extension} file (bad signature).",
                input=label,
            ))
            # Deliberately not `return` here: a bad signature IS corruption,
            # which raster_validator would also catch on open -- but failing
            # fast here skips an expensive, doomed rasterio/Pillow open.
            return issues

    size = image.size_bytes if image.size_bytes is not None else (len(image.content) if image.content is not None else None)
    size_issue = check_file_size(size, input_label=label)
    if size_issue:
        issues.append(size_issue)

    return issues

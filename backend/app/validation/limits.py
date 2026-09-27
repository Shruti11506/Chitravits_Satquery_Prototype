"""Configurable resource limits for Input Validation.

File-size uses the app's existing `MAX_UPLOAD_SIZE_MB` (the same ceiling
already enforced at upload, in `storage_service.validate_upload`) rather
than a second, possibly-drifting setting. The raster-specific limits below
are new and only meaningful here, so they get their own settings
(`core/config.py`) and `.env.example` entries.
"""
from dataclasses import dataclass

from app.core.config import get_settings
from app.validation.errors import FILE_TOO_LARGE, RESOURCE_LIMIT_EXCEEDED, ValidationIssue


@dataclass(frozen=True)
class Limits:
    max_file_size_bytes: int
    max_image_width: int
    max_image_height: int
    max_bands: int
    max_input_images: int


def current_limits() -> Limits:
    """Read fresh from settings on every call -- never cache a snapshot, so a
    changed env var (or a test's monkeypatched settings) takes effect at once."""
    settings = get_settings()
    return Limits(
        max_file_size_bytes=settings.max_upload_size_bytes,
        max_image_width=settings.VALIDATION_MAX_IMAGE_WIDTH,
        max_image_height=settings.VALIDATION_MAX_IMAGE_HEIGHT,
        max_bands=settings.VALIDATION_MAX_BANDS,
        max_input_images=settings.VALIDATION_MAX_INPUT_IMAGES,
    )


def check_image_count(count: int, limits: Limits | None = None) -> ValidationIssue | None:
    limits = limits or current_limits()
    if count > limits.max_input_images:
        return ValidationIssue.of(
            RESOURCE_LIMIT_EXCEEDED,
            f"At most {limits.max_input_images} images may be submitted in one request; received {count}.",
        )
    return None


def check_file_size(size_bytes: int | None, *, input_label: str, limits: Limits | None = None) -> ValidationIssue | None:
    """FILE_TOO_LARGE -- the one resource limit with its own dedicated code
    (task brief section 12); every other limit below uses RESOURCE_LIMIT_EXCEEDED."""
    limits = limits or current_limits()
    if size_bytes is not None and size_bytes > limits.max_file_size_bytes:
        max_mb = limits.max_file_size_bytes / (1024 * 1024)
        return ValidationIssue.of(
            FILE_TOO_LARGE,
            f"File is larger than the {max_mb:.0f} MB limit.",
            input=input_label,
        )
    return None


def check_dimensions(width: int | None, height: int | None, *, input_label: str, limits: Limits | None = None) -> ValidationIssue | None:
    limits = limits or current_limits()
    if width and width > limits.max_image_width:
        return ValidationIssue.of(
            RESOURCE_LIMIT_EXCEEDED,
            f"Image width {width}px exceeds the {limits.max_image_width}px limit.",
            input=input_label,
        )
    if height and height > limits.max_image_height:
        return ValidationIssue.of(
            RESOURCE_LIMIT_EXCEEDED,
            f"Image height {height}px exceeds the {limits.max_image_height}px limit.",
            input=input_label,
        )
    return None


def check_band_count(band_count: int | None, *, input_label: str, limits: Limits | None = None) -> ValidationIssue | None:
    limits = limits or current_limits()
    if band_count and band_count > limits.max_bands:
        return ValidationIssue.of(
            RESOURCE_LIMIT_EXCEEDED,
            f"Image has {band_count} bands, exceeding the {limits.max_bands}-band limit.",
            input=input_label,
        )
    return None

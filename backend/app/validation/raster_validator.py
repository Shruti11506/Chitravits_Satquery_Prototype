"""Image / Raster Structure Validation (task brief section 3).

Answers only: can this file actually be opened, and what does it contain
(width, height, band count, dtype, CRS/transform when present)? TIFF/GeoTIFF
goes through rasterio/GDAL; JPEG/PNG goes through Pillow. Nothing here
decides whether the structure is *acceptable* for a workflow -- that's
geospatial_validator / modality_validator / band_validator / limits.

A GeoTIFF whose structure was already recorded at upload time
(`imagery.metadata.raster.properties`, written by `raster_service.py`) is
read straight from that dict via `facts_from_known_properties` -- no bytes
are re-parsed. `extract_from_bytes` is the fallback (JPEG/PNG always use it;
so does a TIFF row that predates that pipeline).
"""
from __future__ import annotations

import logging
import warnings

from PIL import Image, UnidentifiedImageError

from app.validation.errors import FILE_CORRUPTED, INVALID_DIMENSIONS, ValidationIssue
from app.validation.schemas import ImageInput, RasterFacts

logger = logging.getLogger(__name__)

TIFF_EXTENSIONS = {".tif", ".tiff"}
PILLOW_EXTENSIONS = {".jpg", ".jpeg", ".png"}
SUPPORTED_EXTENSIONS = TIFF_EXTENSIONS | PILLOW_EXTENSIONS

_PILLOW_FORMAT_NAME = {"JPEG": "JPEG", "PNG": "PNG"}


def extension_of(filename: str) -> str:
    if "." not in (filename or ""):
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def extract_from_bytes(content: bytes, filename: str) -> RasterFacts:
    """Open the actual bytes and read its structure. Never raises."""
    extension = extension_of(filename)
    if extension in TIFF_EXTENSIONS:
        return _extract_tiff(content)
    if extension in PILLOW_EXTENSIONS:
        return _extract_pillow(content)
    return RasterFacts(error=f"'{extension or filename}' is not a format this validator can inspect.")


def _extract_tiff(content: bytes) -> RasterFacts:
    import rasterio
    from rasterio.errors import NotGeoreferencedWarning
    from rasterio.io import MemoryFile
    from rasterio.warp import transform_bounds

    try:
        with warnings.catch_warnings(), MemoryFile(content) as mem, mem.open() as src:
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            georeferenced = src.crs is not None
            bounds_wgs84 = None
            if georeferenced:
                try:
                    bounds_wgs84 = tuple(transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21))
                    if not all(map(_finite, bounds_wgs84)):
                        bounds_wgs84 = None  # footprint outside the CRS's valid area
                except Exception:  # noqa: BLE001 - a bad/exotic CRS shouldn't crash validation
                    logger.warning("Could not reproject raster bounds to WGS84 for validation", exc_info=True)
                    bounds_wgs84 = None
            return RasterFacts(
                format="GeoTIFF" if georeferenced else "TIFF",
                width=src.width,
                height=src.height,
                band_count=src.count,
                dtypes=list(src.dtypes),
                crs=src.crs.to_string() if georeferenced else None,
                transform=list(src.transform)[:6] if georeferenced else None,
                bounds=bounds_wgs84,
                band_descriptions=list(src.descriptions),
                color_interpretation=[ci.name for ci in src.colorinterp],
                georeferenced=georeferenced,
            )
    except Exception as exc:  # noqa: BLE001 - any unreadable/corrupt TIFF lands here
        logger.info("TIFF could not be opened for validation: %s", exc)
        return RasterFacts(error="The file could not be read as a TIFF/GeoTIFF raster.")


def _extract_pillow(content: bytes) -> RasterFacts:
    import io

    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()  # catches truncated files; the handle is unusable after this
        with Image.open(io.BytesIO(content)) as img:
            img.load()  # actually decode pixels -- verify() alone misses some corruption
            pillow_format = _PILLOW_FORMAT_NAME.get(img.format or "", img.format)
            band_count = len(img.getbands())
            return RasterFacts(
                format=pillow_format,
                width=img.width,
                height=img.height,
                band_count=band_count,
                dtypes=["uint8"],  # Pillow decodes JPEG/PNG to 8-bit-per-channel
                georeferenced=False,  # JPEG/PNG: never georeferenced by default -- section 4
            )
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        logger.info("Image could not be opened for validation: %s", exc)
        return RasterFacts(error="The file could not be read as a valid JPEG/PNG image.")


def facts_from_known_properties(properties: dict) -> RasterFacts:
    """Build RasterFacts from an already-computed `imagery.metadata.raster.properties`
    dict (see raster_service.py's `_properties`) -- no file bytes touched."""
    georeferenced = bool(properties.get("georeferenced"))
    bounds = properties.get("bounds")
    return RasterFacts(
        format="GeoTIFF" if georeferenced else "TIFF",
        width=properties.get("width"),
        height=properties.get("height"),
        band_count=properties.get("band_count"),
        dtypes=list(properties.get("dtypes") or []),
        crs=properties.get("crs"),
        transform=properties.get("transform"),
        bounds=tuple(bounds) if bounds and len(bounds) == 4 else None,
        band_descriptions=list(properties.get("band_descriptions") or []),
        color_interpretation=list(properties.get("color_interpretation") or []),
        georeferenced=georeferenced,
    )


def _finite(value: float) -> bool:
    # value == value is False for NaN; avoids importing numpy/math just for this.
    return value == value and value not in (float("inf"), float("-inf"))


def resolve_facts(image: ImageInput) -> RasterFacts:
    """Pure `ImageInput -> RasterFacts`: known_properties when present, else
    parse `content`, else "no content available". Used by callers (e.g.
    change_detection_validator's route) that want structure without also
    wanting `service.py`'s error-list-accumulating extraction flow.

    Does NOT check extension support first -- callers that care (this
    package's own `service.py`) run `file_validator.format_issues` before
    calling this; an unsupported extension here just fails to open, landing
    in `.error` like any other unreadable file.
    """
    if image.known_properties is not None:
        return facts_from_known_properties(image.known_properties)
    if image.content is not None:
        return extract_from_bytes(image.content, image.filename)
    return RasterFacts(error="No file content was available to inspect.")


def structure_issues(facts: RasterFacts, *, input_label: str) -> list[ValidationIssue]:
    """FILE_CORRUPTED / INVALID_DIMENSIONS only -- the two things this module
    alone is responsible for rejecting. Everything else (bands, CRS,
    modality) is a different validator's job, run only once structure is OK."""
    if facts.error:
        return [ValidationIssue.of(FILE_CORRUPTED, facts.error, input=input_label)]
    if not facts.width or not facts.height or facts.width <= 0 or facts.height <= 0:
        return [ValidationIssue.of(
            INVALID_DIMENSIONS, "The image has zero or invalid width/height.", input=input_label
        )]
    return []

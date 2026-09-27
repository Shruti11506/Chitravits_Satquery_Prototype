"""Server-side GeoTIFF reading: a browser-viewable preview + real georeference.

Browsers can't decode TIFF, so for .tif/.tiff uploads this renders a
downscaled PNG preview and reads the footprint from the file's own
CRS/transform. The original file is only ever READ here -- the preview is a
separate visualisation artefact; analysis always uses the original.

Everything returned comes from the raster itself: anything it doesn't carry
(no CRS, no cloud-cover tag) is left None, never estimated, and the preview
is only called "true colour" when the bands really are red/green/blue.
Georeferencing and previewing are independent -- a TIFF without a CRS still
gets a preview. No exception escapes `extract`; a file that can't be read
comes back with `preview_error` set.

No Storage/DB access here; imagery_service persists the results.
"""
import logging
import re
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, Resampling
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile
from rasterio.warp import transform, transform_bounds

logger = logging.getLogger(__name__)

# Long edge of the preview. The raster is read already downsampled to this
# size (GDAL decimated read), so a large scene never has to be decoded at
# full resolution in memory.
THUMBNAIL_MAX_EDGE = 1600
THUMBNAIL_FILENAME = "thumbnail.png"

# Percentile stretch for non-8-bit data (reflectance, SAR backscatter, DEMs):
# a plain uint16 -> uint8 cast would come out almost black.
STRETCH_LOW, STRETCH_HIGH = 2, 98

# Metadata tags that genuinely carry a scene cloud-cover percentage
# (Sentinel-2 / Landsat product metadata copied into GeoTIFF tags).
CLOUD_COVER_TAGS = ("CLOUD_COVERAGE_ASSESSMENT", "CLOUDY_PIXEL_PERCENTAGE", "CLOUD_COVER", "CLOUDCOVER")

UNREADABLE_MESSAGE = "The file could not be read as a TIFF/GeoTIFF raster, so no preview could be generated."


@dataclass
class RasterInfo:
    thumbnail_png: bytes | None
    latitude: float | None = None
    longitude: float | None = None
    bbox: dict[str, Any] | None = None
    cloud_cover: float | None = None
    # What the file is (size, bands, dtype, CRS, transform, bounds, nodata,
    # colour interpretation) and how its preview was composed. None only when
    # the file couldn't be opened at all.
    properties: dict[str, Any] | None = None
    preview: dict[str, Any] | None = None
    # Why there is no preview, when there isn't one.
    preview_error: str | None = None


def thumbnail_path_for(storage_path: str) -> str:
    """Deterministic preview location next to the original: imagery/{uuid}/thumbnail.png.

    Never collides with an original: previews are only made for .tif/.tiff
    uploads, whose own filename can't be thumbnail.png.
    """
    return f"{storage_path.rsplit('/', 1)[0]}/{THUMBNAIL_FILENAME}"


def _pick_bands(src) -> tuple[list[int], str]:
    """1-based band indexes to render, and how honest the colours are.

    mode: "true_color" (the bands really are red/green/blue), "palette" (a
    single band drawn with the file's own colour table), "grayscale" (one
    band), or "band_composite" (bands 1-2-3 of a multi-band file that doesn't
    say which band is which -- NOT true colour).
    """
    interp = list(src.colorinterp)
    if all(ci in interp for ci in (ColorInterp.red, ColorInterp.green, ColorInterp.blue)):
        return [interp.index(ci) + 1 for ci in (ColorInterp.red, ColorInterp.green, ColorInterp.blue)], "true_color"

    # Named bands: Sentinel-2 style (B4/B04 = red, B3 green, B2 blue) or plain names.
    names = [(d or "").strip().lower() for d in src.descriptions]
    aliases = {"red": ("b4", "b04", "red"), "green": ("b3", "b03", "green"), "blue": ("b2", "b02", "blue")}
    by_color = {}
    for idx, name in enumerate(names, start=1):
        for color, keys in aliases.items():
            if name in keys and color not in by_color:
                by_color[color] = idx
    if len(by_color) == 3:
        return [by_color["red"], by_color["green"], by_color["blue"]], "true_color"

    if interp and interp[0] == ColorInterp.palette:
        return [1], "palette"
    if src.count >= 3:
        return [1, 2, 3], "band_composite"
    return [1], "grayscale"  # single band (panchromatic, SAR, one S2 band, DEM) or 2-band


def _to_uint8(band: np.ma.MaskedArray, stretch: bool) -> tuple[np.ndarray, list[float] | None]:
    if not stretch:
        return np.clip(band.filled(0), 0, 255).astype(np.uint8), None
    valid = band.compressed()
    valid = valid[np.isfinite(valid)]
    if valid.size == 0:
        return np.zeros(band.shape, dtype=np.uint8), None
    low, high = np.percentile(valid, (STRETCH_LOW, STRETCH_HIGH))
    if high <= low:
        high = low + 1
    scaled = (band.filled(low).astype(np.float64) - low) / (high - low)
    return (np.clip(np.nan_to_num(scaled), 0, 1) * 255).astype(np.uint8), [float(low), float(high)]


def _render_thumbnail(src) -> tuple[bytes, dict[str, Any]]:
    scale = min(1.0, THUMBNAIL_MAX_EDGE / max(src.width, src.height))
    out_h, out_w = max(1, round(src.height * scale)), max(1, round(src.width * scale))
    bands, mode = _pick_bands(src)

    # Nearest, not average: ~15x faster on large strip-organised TIFFs (0.14s
    # vs 2s for 105 Mpx), which keeps this cheap enough to run in the request.
    data = src.read(bands, out_shape=(len(bands), out_h, out_w), masked=True, resampling=Resampling.nearest)

    stretch_ranges = []
    if mode == "palette":
        colormap = src.colormap(1)
        lut = np.zeros((max(colormap) + 1, 4), dtype=np.uint8)
        for value, rgba in colormap.items():
            lut[value] = rgba
        indexes = np.clip(data[0].filled(0).astype(np.int64), 0, len(lut) - 1)
        channels = [lut[indexes][..., i] for i in range(3)]
    else:
        stretch = src.dtypes[bands[0] - 1] != "uint8"
        channels = []
        for i in range(len(bands)):
            channel, value_range = _to_uint8(data[i], stretch)
            channels.append(channel)
            stretch_ranges.append(value_range)

    # Nodata / masked pixels become transparent instead of black.
    valid = ~np.ma.getmaskarray(data).any(axis=0)
    if not valid.all():
        channels.append(np.where(valid, 255, 0).astype(np.uint8))

    stacked = np.stack(channels)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with MemoryFile() as mem:
            with mem.open(driver="PNG", width=out_w, height=out_h, count=stacked.shape[0], dtype="uint8") as dst:
                dst.write(stacked)
            png = mem.read()

    preview = {
        "mode": mode,
        "bands": bands,
        "width": out_w,
        "height": out_h,
        "format": "png",
        # Display range per band (2nd-98th percentile) -- the original values are untouched.
        "stretch": f"p{STRETCH_LOW}-p{STRETCH_HIGH}" if any(stretch_ranges) else None,
        "stretch_ranges": stretch_ranges if any(stretch_ranges) else None,
    }
    return png, preview


def _properties(src) -> dict[str, Any]:
    """What the file is, as read from it (JSON-safe)."""
    georeferenced = src.crs is not None
    dataset_tags = dict(src.tags()) if hasattr(src, "tags") else {}
    band_tags = []
    if hasattr(src, "tags"):
        for i in range(1, src.count + 1):
            try:
                band_tags.append(dict(src.tags(i)))
            except Exception:
                band_tags.append({})
    units = list(src.units) if hasattr(src, "units") and src.units else []
    return {
        "driver": src.driver,
        "width": src.width,
        "height": src.height,
        "band_count": src.count,
        "dtypes": list(src.dtypes),
        "nodata": src.nodata if src.nodata is None or np.isfinite(src.nodata) else str(src.nodata),
        "color_interpretation": [ci.name for ci in src.colorinterp],
        "band_descriptions": [d for d in src.descriptions] if any(src.descriptions) else None,
        "crs": src.crs.to_string() if georeferenced else None,
        "transform": list(src.transform)[:6] if georeferenced else None,
        "bounds": list(src.bounds) if georeferenced else None,
        "georeferenced": georeferenced,
        "tags": dataset_tags,
        "band_tags": band_tags,
        "units": units,
    }


def _georeference(src) -> tuple[float | None, float | None, dict[str, Any] | None]:
    if src.crs is None:
        return None, None, None
    west, south, east, north = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
    center_x = (src.bounds.left + src.bounds.right) / 2
    center_y = (src.bounds.bottom + src.bounds.top) / 2
    lons, lats = transform(src.crs, "EPSG:4326", [center_x], [center_y])
    if not np.isfinite([west, south, east, north, lons[0], lats[0]]).all():
        return None, None, None  # footprint outside the CRS's valid area
    bbox = {
        "west": west,
        "south": south,
        "east": east,
        "north": north,
        "crs": "EPSG:4326",
        "source_crs": src.crs.to_string(),
    }
    return lats[0], lons[0], bbox


def _cloud_cover(src) -> float | None:
    tags = {key.upper(): value for key, value in src.tags().items()}
    for key in CLOUD_COVER_TAGS:
        if key in tags:
            try:
                value = float(tags[key])
            except (TypeError, ValueError):
                continue
            if 0 <= value <= 100:
                return value
    return None


def extract(content: bytes) -> RasterInfo:
    """Preview + georeference + raster facts for a TIFF's bytes. Never raises.

    CPU-bound -- call it from a worker thread in async routes.
    """
    try:
        with warnings.catch_warnings(), MemoryFile(content) as mem, mem.open() as src:
            # A TIFF without a CRS is still previewable; rasterio just warns about it.
            warnings.simplefilter("ignore", NotGeoreferencedWarning)
            info = RasterInfo(thumbnail_png=None, properties=_properties(src), cloud_cover=_cloud_cover(src))
            try:
                info.thumbnail_png, info.preview = _render_thumbnail(src)
            except Exception:  # noqa: BLE001 - a readable header with unrenderable pixels still has coords
                logger.warning("Could not render a preview for an uploaded TIFF", exc_info=True)
                info.preview_error = "The raster was read, but its pixels could not be rendered as a preview."
            try:
                info.latitude, info.longitude, info.bbox = _georeference(src)
            except Exception:  # noqa: BLE001
                logger.warning("Could not reproject an uploaded TIFF's bounds to WGS84", exc_info=True)
            return info
    except rasterio.errors.RasterioError:
        logger.warning("Uploaded TIFF could not be parsed; storing it without a preview or coordinates")
    except Exception:  # noqa: BLE001 - never let raster parsing break an upload
        logger.exception("Unexpected error while reading an uploaded TIFF")
    return RasterInfo(thumbnail_png=None, preview_error=UNREADABLE_MESSAGE)

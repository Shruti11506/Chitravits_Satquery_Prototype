"""Tiny, real image files for upload tests. Upload now runs full file
validation (magic bytes, readable, dimensions, dtype), so fixtures must be
genuine JPEG / PNG / TIFF bytes, not placeholder strings."""
import io
import itertools

import numpy as np
from PIL import Image
from rasterio.io import MemoryFile


_FILLS = itertools.count(1)


def unique_fill() -> int:
    """A different pixel value per call (1..250): change detection now rejects
    two images with identical pixels, so every generated test image must differ."""
    return next(_FILLS) % 250 + 1


def unique_color() -> tuple[int, int, int]:
    value = unique_fill()
    return (value, 255 - value, (value * 7) % 256)


def real_jpeg(width: int = 16, height: int = 12, color=None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color or unique_color()).save(buf, format="JPEG")
    return buf.getvalue()


def real_png(width: int = 16, height: int = 12, color=None) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=color or unique_color()).save(buf, format="PNG")
    return buf.getvalue()


def real_tiff(width: int = 16, height: int = 12, count: int = 1, dtype: str = "uint8") -> bytes:
    """A plain (not georeferenced) TIFF."""
    with MemoryFile() as mem:
        with mem.open(driver="GTiff", width=width, height=height, count=count, dtype=dtype) as dst:
            dst.write(np.full((count, height, width), unique_fill(), dtype=dtype))
        return mem.read()

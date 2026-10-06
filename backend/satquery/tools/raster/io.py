"""Raster reading/writing for the deterministic tools.

Thin wrappers over rasterio that (a) accept either a filesystem path or raw
bytes (the attachment resolver hands us bytes), (b) read bands as float64 with
nodata converted to NaN so the pure formulas stay nodata-safe, and (c) write
derived products as single-band Float32 GeoTIFFs that preserve CRS/transform —
the scientific source of truth, kept separate from any visualization (spec §53).
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import numpy as np

try:  # rasterio is a hard dependency of the tools, but keep the import guard explicit
    import rasterio
    from rasterio.io import MemoryFile
    from rasterio.transform import Affine
    _HAS_RASTERIO = True
except Exception:  # noqa: BLE001
    _HAS_RASTERIO = False


@dataclass
class RasterMeta:
    """Spatial metadata carried alongside every derived product."""

    width: int
    height: int
    count: int
    crs: str | None                 # "EPSG:32633" or None
    transform: object               # Affine
    nodata: float | None
    is_projected: bool
    units: str                      # "meters" | "degrees" | "unknown"


@contextmanager
def open_raster(source) -> Iterator["rasterio.DatasetReader"]:
    """Open a raster from a path (str/Path) or raw bytes."""
    if not _HAS_RASTERIO:
        raise RuntimeError("rasterio is not installed; deterministic raster tools are unavailable.")
    if isinstance(source, (bytes, bytearray)):
        with MemoryFile(bytes(source)) as mem, mem.open() as ds:
            yield ds
    else:
        with rasterio.open(source) as ds:
            yield ds


def meta_of(ds) -> RasterMeta:
    crs = ds.crs
    epsg = None
    is_proj = False
    units = "unknown"
    if crs is not None:
        try:
            epsg = crs.to_epsg()
        except Exception:  # noqa: BLE001
            epsg = None
        is_proj = bool(crs.is_projected)
        units = "meters" if is_proj else ("degrees" if crs.is_geographic else "unknown")
    return RasterMeta(
        width=ds.width, height=ds.height, count=ds.count,
        crs=f"EPSG:{epsg}" if epsg else (str(crs) if crs else None),
        transform=ds.transform, nodata=ds.nodata,
        is_projected=is_proj, units=units,
    )


def read_band(ds, index: int) -> np.ndarray:
    """Read one 1-based band as float64 with nodata → NaN."""
    arr = ds.read(index).astype("float64")
    nodata = ds.nodata
    if nodata is not None:
        arr[arr == nodata] = np.nan
    return arr


def pixel_area_m2(meta: RasterMeta, *, center_lat: float | None = None) -> float | None:
    """Approximate per-pixel ground area in m² (spec §26).

    Projected metric CRS → exact from the affine transform. Geographic (degrees)
    → approximated from metres-per-degree at ``center_lat`` (a geodesic-safe-enough
    estimate for prototype area figures; the approximation is recorded in
    provenance by the caller). Returns None when it cannot be determined.
    """
    t = meta.transform
    if t is None:
        return None
    px = abs(t.a)
    py = abs(t.e)
    if meta.is_projected and meta.units == "meters":
        return px * py
    if meta.units == "degrees":
        lat = center_lat if center_lat is not None else 0.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(lat))
        m_per_deg_lat = 110540.0
        return abs(px * m_per_deg_lon) * abs(py * m_per_deg_lat)
    return None


def write_raster(path, array: np.ndarray, meta: RasterMeta, *, nodata: float = float("nan")) -> str:
    """Write a single-band Float32 GeoTIFF preserving CRS/transform. Returns the path."""
    if not _HAS_RASTERIO:
        raise RuntimeError("rasterio is not installed; cannot write derived raster.")
    data = np.asarray(array, dtype="float32")
    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1,
        "height": data.shape[0], "width": data.shape[1],
        "crs": meta.crs, "transform": meta.transform, "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(str(path), "w", **profile) as dst:
        dst.write(data, 1)
    return str(path)

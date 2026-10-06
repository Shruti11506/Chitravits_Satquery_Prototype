"""NaN-aware raster statistics for derived products (spec §13)."""

from __future__ import annotations

import numpy as np


def raster_stats(array: np.ndarray) -> dict:
    """min/max/mean/std and valid-pixel counts, ignoring NaN.

    Returns zeros/None-free numbers plus ``valid_pixels`` and
    ``valid_pixel_ratio`` so callers can judge how much data backed the stats.
    """
    arr = np.asarray(array, dtype="float64")
    total = arr.size
    finite = np.isfinite(arr)
    valid = arr[finite]
    n = int(valid.size)
    if n == 0:
        return {
            "min": None, "max": None, "mean": None, "std": None,
            "valid_pixels": 0, "total_pixels": total, "valid_pixel_ratio": 0.0,
        }
    return {
        "min": float(valid.min()),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
        "std": float(valid.std()),
        "valid_pixels": n,
        "total_pixels": total,
        "valid_pixel_ratio": n / total if total else 0.0,
    }


def mask_area(mask: np.ndarray, pixel_area_m2: float | None) -> dict:
    """Foreground pixel count + area (m²/ha/km²) for a binary mask (spec §26)."""
    m = np.asarray(mask, dtype=bool)
    fg = int(m.sum())
    bg = int(m.size - fg)
    out = {"foreground_pixels": fg, "background_pixels": bg}
    if pixel_area_m2:
        area = fg * pixel_area_m2
        out.update({
            "area_m2": area, "area_ha": area / 1e4, "area_km2": area / 1e6,
            "pixel_area_m2": pixel_area_m2,
        })
    return out

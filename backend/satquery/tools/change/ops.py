"""Pure temporal-change math (no I/O): difference, ratio, threshold, stats.

Transparent bi-temporal baselines and evidence (Tools.docx §8, spec §31).
Inputs are two co-registered float arrays of equal shape (T1, T2) with nodata
as NaN. These are *baselines/diagnostics*, not a learned change detector.
"""

from __future__ import annotations

import numpy as np

from satquery.tools.spectral.formulas import safe_divide


def difference(t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """T2 − T1 (positive = increase)."""
    return np.asarray(t2, dtype="float64") - np.asarray(t1, dtype="float64")


def ratio(t1: np.ndarray, t2: np.ndarray) -> np.ndarray:
    """T2 / T1 (zero-safe)."""
    return safe_divide(t2, t1)


def threshold_change(diff: np.ndarray, threshold: float, *, mode: str = "abs") -> np.ndarray:
    """Boolean change mask from a difference image.

    ``mode='abs'`` marks |diff| ≥ threshold (change in either direction);
    ``'increase'``/'decrease' mark signed change. NaNs are False.
    """
    d = np.asarray(diff, dtype="float64")
    finite = np.isfinite(d)
    if mode == "increase":
        return finite & (d >= threshold)
    if mode == "decrease":
        return finite & (d <= -threshold)
    return finite & (np.abs(d) >= threshold)


def change_statistics(
    diff: np.ndarray, *, pixel_area_m2: float | None = None, threshold: float = 0.0
) -> dict:
    """Summarise a difference image (spec §31).

    Returns mean/min/max change, count and fraction of positive/negative pixels,
    and — when a per-pixel area is supplied — the changed area in m²/ha/km²
    for pixels whose |change| exceeds ``threshold``.
    """
    d = np.asarray(diff, dtype="float64")
    finite = np.isfinite(d)
    valid = d[finite]
    n_valid = int(valid.size)
    if n_valid == 0:
        return {"valid_pixels": 0}

    changed = np.abs(valid) > threshold
    pos = valid > threshold
    neg = valid < -threshold

    stats = {
        "valid_pixels": n_valid,
        "mean_change": float(valid.mean()),
        "min_change": float(valid.min()),
        "max_change": float(valid.max()),
        "std_change": float(valid.std()),
        "changed_pixels": int(changed.sum()),
        "changed_fraction": float(changed.mean()),
        "positive_pixels": int(pos.sum()),
        "negative_pixels": int(neg.sum()),
    }
    if pixel_area_m2:
        area_m2 = stats["changed_pixels"] * pixel_area_m2
        stats.update({
            "changed_area_m2": area_m2,
            "changed_area_ha": area_m2 / 1e4,
            "changed_area_km2": area_m2 / 1e6,
            "positive_area_ha": stats["positive_pixels"] * pixel_area_m2 / 1e4,
            "negative_area_ha": stats["negative_pixels"] * pixel_area_m2 / 1e4,
        })
    return stats

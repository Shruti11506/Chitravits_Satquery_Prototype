"""Pure SAR math (no I/O): dB conversion, VV/VH relations, RVI, Otsu.

SAR values are radar backscatter. The engine must know whether the source is
linear power or already dB and never double-convert (Tools.docx §13, §23). These
functions assume *linear* intensity inputs unless named otherwise, and are
nodata/zero-safe.
"""

from __future__ import annotations

import numpy as np

from satquery.tools.spectral.formulas import safe_divide


def to_db(linear: np.ndarray) -> np.ndarray:
    """dB = 10·log10(linear). Non-positive/invalid values -> NaN (never -inf)."""
    arr = np.asarray(linear, dtype="float64")
    out = np.full(arr.shape, np.nan, dtype="float64")
    valid = np.isfinite(arr) & (arr > 0)
    out[valid] = 10.0 * np.log10(arr[valid])
    return out


def vv_vh_ratio(vv: np.ndarray, vh: np.ndarray) -> np.ndarray:
    """Linear VV/VH ratio (surface/scattering characterization)."""
    return safe_divide(vv, vh)


def vv_vh_log_ratio(vv: np.ndarray, vh: np.ndarray) -> np.ndarray:
    """dB difference VV−VH = 10·log10(VV/VH); stable alternative to the raw ratio."""
    return to_db(vv) - to_db(vh)


def rvi_dual_pol(vv: np.ndarray, vh: np.ndarray) -> np.ndarray:
    """Dual-pol Radar Vegetation Index = 4·VH / (VV + VH). Range ~[0, 1]."""
    vv = np.asarray(vv, dtype="float64")
    vh = np.asarray(vh, dtype="float64")
    return safe_divide(4.0 * vh, vv + vh)


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    """Otsu's optimal threshold over the finite values of an array.

    Uses scikit-image when available; otherwise a self-contained histogram
    implementation. NaNs/inf are ignored. Raises ValueError if there is no
    valid data or no variance to threshold.
    """
    arr = np.asarray(values, dtype="float64").ravel()
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError("Otsu threshold: no finite values.")
    if finite.min() == finite.max():
        raise ValueError("Otsu threshold: constant image, nothing to separate.")

    try:
        from skimage.filters import threshold_otsu as _sk_otsu

        return float(_sk_otsu(finite, nbins=bins))
    except Exception:  # noqa: BLE001 - fall back to a local implementation
        return _otsu_numpy(finite, bins)


def _otsu_numpy(finite: np.ndarray, bins: int) -> float:
    hist, edges = np.histogram(finite, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    weight = np.cumsum(hist)
    total = weight[-1]
    weight_b = weight / total
    weight_f = 1.0 - weight_b
    cum_mean = np.cumsum(hist * centers)
    mean_b = np.divide(cum_mean, weight, out=np.zeros_like(cum_mean), where=weight > 0)
    total_mean = cum_mean[-1] / total
    mean_f = np.divide(
        total_mean - cum_mean, (total - weight),
        out=np.zeros_like(cum_mean), where=(total - weight) > 0,
    )
    between = weight_b * weight_f * (mean_b - mean_f) ** 2
    return float(centers[int(np.argmax(between))])


def otsu_mask(values: np.ndarray, *, foreground: str = "below", bins: int = 256) -> tuple[np.ndarray, float]:
    """Binary mask from Otsu thresholding.

    ``foreground='below'`` marks pixels *below* the threshold as foreground —
    the convention for SAR water/flood, where water has low backscatter. Returns
    (bool mask with NaN pixels False, threshold).
    """
    arr = np.asarray(values, dtype="float64")
    thr = otsu_threshold(arr, bins=bins)
    finite = np.isfinite(arr)
    if foreground == "below":
        mask = finite & (arr < thr)
    else:
        mask = finite & (arr >= thr)
    return mask, thr

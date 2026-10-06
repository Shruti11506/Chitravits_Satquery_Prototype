"""Pure spectral-index math (no I/O).

Every function takes float NumPy arrays of equal shape and returns a float
array; nodata should be passed in as NaN so it propagates rather than poisoning
statistics. Division is nodata/zero-safe: ``0/0`` and ``x/0`` become NaN, never
an exception or an ``inf`` that would wreck downstream stats.

Band assignments (Sentinel-2) are documented per function; the caller resolves
which raster band supplies NIR/RED/… (see ``tools.raster.bands``).
"""

from __future__ import annotations

import numpy as np

# Default coefficients, exposed so provenance can record them (spec §20/§21).
SAVI_L = 0.5
EVI_COEFFS = {"G": 2.5, "C1": 6.0, "C2": 7.5, "L": 1.0}
BAI_COEFFS = {"red_ref": 0.1, "nir_ref": 0.06}


def safe_divide(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Elementwise divide where the denominator is 0 or non-finite yields NaN."""
    num = np.asarray(numerator, dtype="float64")
    den = np.asarray(denominator, dtype="float64")
    out = np.full(np.broadcast(num, den).shape, np.nan, dtype="float64")
    valid = np.isfinite(num) & np.isfinite(den) & (den != 0)
    np.divide(num, den, out=out, where=valid)
    return out


def normalized_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b) — the shared form behind NDVI/NDWI/NDBI/NBR/NDMI."""
    a = np.asarray(a, dtype="float64")
    b = np.asarray(b, dtype="float64")
    return safe_divide(a - b, a + b)


def ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    """NDVI = (NIR − Red)/(NIR + Red). S2: NIR=B8, Red=B4."""
    return normalized_difference(nir, red)


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDWI = (Green − NIR)/(Green + NIR). S2: Green=B3, NIR=B8."""
    return normalized_difference(green, nir)


def mndwi(green: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """MNDWI = (Green − SWIR)/(Green + SWIR). S2: Green=B3, SWIR=B11."""
    return normalized_difference(green, swir)


def ndmi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    """NDMI = (NIR − SWIR)/(NIR + SWIR). S2: NIR=B8, SWIR=B11."""
    return normalized_difference(nir, swir)


def ndbi(swir: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """NDBI = (SWIR − NIR)/(SWIR + NIR). S2: SWIR=B11, NIR=B8."""
    return normalized_difference(swir, nir)


def nbr(nir: np.ndarray, swir2: np.ndarray) -> np.ndarray:
    """NBR = (NIR − SWIR2)/(NIR + SWIR2). S2: NIR=B8, SWIR2=B12."""
    return normalized_difference(nir, swir2)


def savi(nir: np.ndarray, red: np.ndarray, L: float = SAVI_L) -> np.ndarray:
    """SAVI = ((NIR − Red)/(NIR + Red + L)) * (1 + L). Default L=0.5."""
    nir = np.asarray(nir, dtype="float64")
    red = np.asarray(red, dtype="float64")
    return safe_divide(nir - red, nir + red + L) * (1.0 + L)


def evi(
    nir: np.ndarray, red: np.ndarray, blue: np.ndarray, coeffs: dict | None = None
) -> np.ndarray:
    """EVI = G*(NIR − Red)/(NIR + C1*Red − C2*Blue + L). Standard S2 coefficients."""
    c = coeffs or EVI_COEFFS
    nir = np.asarray(nir, dtype="float64")
    red = np.asarray(red, dtype="float64")
    blue = np.asarray(blue, dtype="float64")
    denom = nir + c["C1"] * red - c["C2"] * blue + c["L"]
    return c["G"] * safe_divide(nir - red, denom)


def bai(nir: np.ndarray, red: np.ndarray, coeffs: dict | None = None) -> np.ndarray:
    """Burn Area Index = 1 / ((red_ref − Red)² + (nir_ref − NIR)²).

    Highlights charcoal/ash; expects surface-reflectance inputs. Reference
    values default to red=0.1, nir=0.06 (spec §21). The denominator is
    zero-safe.
    """
    c = coeffs or BAI_COEFFS
    nir = np.asarray(nir, dtype="float64")
    red = np.asarray(red, dtype="float64")
    denom = (c["red_ref"] - red) ** 2 + (c["nir_ref"] - nir) ** 2
    return safe_divide(np.ones_like(denom), denom)

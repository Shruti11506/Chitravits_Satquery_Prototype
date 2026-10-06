"""Run deterministic tools on rasters and return ``ToolResult``s.

This is the bridge between the pure math (``spectral``/``sar``/``change``) and
the agent's tool contract. Each runner:

  1. resolves the bands it needs from the DataProfile (clear error if absent),
  2. reads them nodata-safe, computes the product,
  3. writes the derived GeoTIFF (scientific source of truth) when an out dir is
     given, and
  4. returns a ``ToolResult`` with measurements, optional spatial mask area, and
     metadata (formula, bands used, parameters, CRS, output path) that the
     Evidence Engine turns into provenance.

Nothing here is model inference — ``backend="deterministic"`` and the metadata
records the exact formula, so no result is ever mistaken for a mock or a model.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from satquery.tools.change import ops as change_ops
from satquery.tools.raster import (
    BandResolver,
    MissingBandError,
    mask_area,
    meta_of,
    open_raster,
    pixel_area_m2,
    raster_stats,
    read_band,
    write_raster,
)
from satquery.tools.sar import formulas as sar
from satquery.tools.schemas import Measurement, SpatialResult, ToolResult, ToolStatus
from satquery.tools.spectral import formulas as sp

# name -> (required logical bands, callable(bands)->array, formula string, params)
SPECTRAL_TOOLS = {
    "ndvi": (["NIR", "RED"], lambda b: sp.ndvi(b["NIR"], b["RED"]),
             "(NIR-RED)/(NIR+RED)", {}),
    "ndwi": (["GREEN", "NIR"], lambda b: sp.ndwi(b["GREEN"], b["NIR"]),
             "(GREEN-NIR)/(GREEN+NIR)", {}),
    "mndwi": (["GREEN", "SWIR1"], lambda b: sp.mndwi(b["GREEN"], b["SWIR1"]),
              "(GREEN-SWIR)/(GREEN+SWIR)", {}),
    "ndmi": (["NIR", "SWIR1"], lambda b: sp.ndmi(b["NIR"], b["SWIR1"]),
             "(NIR-SWIR)/(NIR+SWIR)", {}),
    "ndbi": (["SWIR1", "NIR"], lambda b: sp.ndbi(b["SWIR1"], b["NIR"]),
             "(SWIR-NIR)/(SWIR+NIR)", {}),
    "nbr": (["NIR", "SWIR2"], lambda b: sp.nbr(b["NIR"], b["SWIR2"]),
            "(NIR-SWIR2)/(NIR+SWIR2)", {}),
    "savi": (["NIR", "RED"], lambda b: sp.savi(b["NIR"], b["RED"]),
             "((NIR-RED)/(NIR+RED+L))*(1+L)", {"L": sp.SAVI_L}),
    "evi": (["NIR", "RED", "BLUE"], lambda b: sp.evi(b["NIR"], b["RED"], b["BLUE"]),
            "G*(NIR-RED)/(NIR+C1*RED-C2*BLUE+L)", sp.EVI_COEFFS),
    "bai": (["NIR", "RED"], lambda b: sp.bai(b["NIR"], b["RED"]),
            "1/((0.1-RED)^2+(0.06-NIR)^2)", sp.BAI_COEFFS),
}

_SPECTRAL_UNIT = "index"


def _failed(name: str, message: str, code: str = "TOOL_FAILED") -> ToolResult:
    return ToolResult(tool_name=name, status=ToolStatus.FAILED, execution_time_ms=0,
                      errors=[message], metadata={"error_code": code})


def _center_lat(profile) -> float | None:
    b = getattr(profile, "bounds_wgs84", None)
    return getattr(b, "center_lat", None) if b else None


def _stat_measurements(name: str, stats: dict, unit: str) -> list[Measurement]:
    out = []
    for key in ("mean", "min", "max", "std"):
        if stats.get(key) is not None:
            out.append(Measurement(name=f"{name}_{key}", value=float(stats[key]),
                                   unit=unit, source_tool=name))
    return out


# ---------------------------------------------------------------------------
# Spectral indices
# ---------------------------------------------------------------------------

def run_spectral(name: str, source, profile, *, out_dir: str | Path | None = None) -> ToolResult:
    """Compute a spectral index and return a ToolResult."""
    name = name.lower()
    if name not in SPECTRAL_TOOLS:
        return _failed(name, f"Unknown spectral tool '{name}'.", "UNKNOWN_TOOL")
    required, fn, formula, params = SPECTRAL_TOOLS[name]

    t0 = time.perf_counter()
    try:
        with open_raster(source) as ds:
            resolver = BandResolver.from_profile(profile) if profile else \
                BandResolver.from_band_count(ds.count)
            try:
                idx = resolver.require(required, tool=name.upper())
            except MissingBandError as exc:
                return _failed(name, str(exc), exc.code)
            bands = {logical: read_band(ds, i) for logical, i in idx.items()}
            meta = meta_of(ds)
            array = fn(bands)
            px_area = pixel_area_m2(meta, center_lat=_center_lat(profile))
    except Exception as exc:  # noqa: BLE001
        return _failed(name, f"{name} failed: {exc}")

    stats = raster_stats(array)
    output_path = None
    if out_dir is not None:
        output_path = write_raster(Path(out_dir) / f"{name}.tif", array, meta)

    elapsed = int((time.perf_counter() - t0) * 1000)
    mean = stats.get("mean")
    answer = (f"{name.upper()} computed (mean {mean:.3f}, "
              f"range {stats['min']:.3f}…{stats['max']:.3f})." if mean is not None
              else f"{name.upper()} produced no valid pixels.")
    return ToolResult(
        tool_name=name, status=ToolStatus.SUCCESS, execution_time_ms=elapsed,
        answer=answer,
        measurements=_stat_measurements(name, stats, _SPECTRAL_UNIT),
        metadata={
            "backend": "deterministic", "model": name, "formula": formula,
            "bands_used": {k: None for k in required} | {k: None for k in idx},
            "parameters": params, "crs": meta.crs, "output_path": output_path,
            "statistics": stats, "pixel_area_m2": px_area,
        },
    )


# ---------------------------------------------------------------------------
# SAR
# ---------------------------------------------------------------------------

def run_sar(name: str, source, profile, *, band: str = "VV",
            out_dir: str | Path | None = None) -> ToolResult:
    """Compute a SAR product: sar_db | vv_vh | rvi | sar_otsu."""
    name = name.lower()
    t0 = time.perf_counter()
    try:
        with open_raster(source) as ds:
            resolver = BandResolver.from_profile(profile) if profile else \
                BandResolver.from_band_count(ds.count)
            meta = meta_of(ds)
            px_area = pixel_area_m2(meta, center_lat=_center_lat(profile))

            if name in ("vv_vh", "rvi"):
                try:
                    idx = resolver.require(["VV", "VH"], tool=name.upper())
                except MissingBandError as exc:
                    return _failed(name, str(exc), exc.code)
                vv, vh = read_band(ds, idx["VV"]), read_band(ds, idx["VH"])
                array = sar.vv_vh_ratio(vv, vh) if name == "vv_vh" else sar.rvi_dual_pol(vv, vh)
                formula = "VV/VH" if name == "vv_vh" else "4*VH/(VV+VH)"
                params: dict = {}
            elif name == "sar_db":
                bi = resolver.index_of(band) or 1
                array = sar.to_db(read_band(ds, bi))
                formula, params = "10*log10(linear)", {"band": band}
            elif name == "sar_otsu":
                bi = resolver.index_of(band) or 1
                linear = read_band(ds, bi)
                db = sar.to_db(linear)
                try:
                    mask, thr = sar.otsu_mask(db, foreground="below")
                except ValueError as exc:
                    return _failed(name, f"Otsu failed: {exc}", "OTSU_FAILED")
                array = mask.astype("float32")
                formula, params = "Otsu(dB), water=below-threshold", {"threshold": thr, "band": band}
            else:
                return _failed(name, f"Unknown SAR tool '{name}'.", "UNKNOWN_TOOL")
    except Exception as exc:  # noqa: BLE001
        return _failed(name, f"{name} failed: {exc}")

    output_path = None
    if out_dir is not None:
        output_path = write_raster(Path(out_dir) / f"{name}.tif", array, meta)
    elapsed = int((time.perf_counter() - t0) * 1000)

    measurements: list[Measurement] = []
    spatial: list[SpatialResult] = []
    if name == "sar_otsu":
        area = mask_area(array.astype(bool), px_area)
        if "area_ha" in area:
            measurements.append(Measurement(name="water_area", value=area["area_ha"],
                                           unit="ha", source_tool=name))
            spatial.append(SpatialResult(region_id="water", area_ha=area["area_ha"],
                                         source_tool=name))
        answer = (f"SAR Otsu water mask: threshold {params['threshold']:.2f} dB, "
                  f"{area['foreground_pixels']} pixels"
                  + (f" (~{area['area_ha']:.1f} ha)." if "area_ha" in area else "."))
    else:
        stats = raster_stats(array)
        measurements = _stat_measurements(name, stats, "dB" if name == "sar_db" else "ratio")
        m = stats.get("mean")
        answer = f"{name.upper()} computed" + (f" (mean {m:.3f})." if m is not None else ".")

    return ToolResult(
        tool_name=name, status=ToolStatus.SUCCESS, execution_time_ms=elapsed,
        answer=answer, measurements=measurements, spatial_results=spatial,
        metadata={
            "backend": "deterministic", "model": name, "formula": formula,
            "parameters": params, "crs": meta.crs, "output_path": output_path,
            "pixel_area_m2": px_area,
        },
    )


# ---------------------------------------------------------------------------
# Change (bi-temporal deterministic baselines)
# ---------------------------------------------------------------------------

def run_index_difference(index_name: str, before_source, after_source,
                         before_profile, after_profile, *,
                         out_dir: str | Path | None = None, threshold: float = 0.1) -> ToolResult:
    """Difference of a spectral index between two dates (e.g. NDVI T2 − T1)."""
    index_name = index_name.lower()
    tool = f"{index_name}_difference"
    b = run_spectral(index_name, before_source, before_profile)
    a = run_spectral(index_name, after_source, after_profile)
    if b.status is ToolStatus.FAILED:
        return _failed(tool, b.errors[0] if b.errors else "before failed")
    if a.status is ToolStatus.FAILED:
        return _failed(tool, a.errors[0] if a.errors else "after failed")

    # Recompute arrays (kept out of ToolResult to stay JSON-safe) for the difference.
    t0 = time.perf_counter()
    try:
        with open_raster(before_source) as ds_b, open_raster(after_source) as ds_a:
            rb = BandResolver.from_profile(before_profile) if before_profile else \
                BandResolver.from_band_count(ds_b.count)
            ra = BandResolver.from_profile(after_profile) if after_profile else \
                BandResolver.from_band_count(ds_a.count)
            req, fn, formula, _p = SPECTRAL_TOOLS[index_name]
            ib, ia = rb.require(req, index_name.upper()), ra.require(req, index_name.upper())
            arr_b = fn({k: read_band(ds_b, i) for k, i in ib.items()})
            arr_a = fn({k: read_band(ds_a, i) for k, i in ia.items()})
            meta = meta_of(ds_a)
            px_area = pixel_area_m2(meta, center_lat=_center_lat(after_profile))
    except MissingBandError as exc:
        return _failed(tool, str(exc), exc.code)
    except Exception as exc:  # noqa: BLE001
        return _failed(tool, f"{tool} failed: {exc}")

    diff = change_ops.difference(arr_b, arr_a)
    stats = change_ops.change_statistics(diff, pixel_area_m2=px_area, threshold=threshold)
    output_path = None
    if out_dir is not None:
        output_path = write_raster(Path(out_dir) / f"{tool}.tif", diff, meta)
    elapsed = int((time.perf_counter() - t0) * 1000)

    measurements = [Measurement(name=f"{index_name}_change", value=stats["mean_change"],
                                unit="index", source_tool=tool)]
    if "changed_area_ha" in stats:
        measurements.append(Measurement(name="change_area", value=stats["changed_area_ha"],
                                        unit="ha", source_tool=tool))
    direction = "decrease" if stats["mean_change"] < 0 else "increase"
    answer = (f"{index_name.upper()} mean change {stats['mean_change']:+.3f} ({direction}); "
              f"{stats['changed_fraction']*100:.1f}% of valid pixels changed.")
    return ToolResult(
        tool_name=tool, status=ToolStatus.SUCCESS, execution_time_ms=elapsed,
        answer=answer, measurements=measurements,
        metadata={
            "backend": "deterministic", "model": tool,
            "formula": f"{index_name.upper()}(T2) - {index_name.upper()}(T1)",
            "parameters": {"threshold": threshold}, "crs": meta.crs,
            "output_path": output_path, "statistics": stats,
            "before_mean": b.metadata["statistics"]["mean"],
            "after_mean": a.metadata["statistics"]["mean"],
        },
    )

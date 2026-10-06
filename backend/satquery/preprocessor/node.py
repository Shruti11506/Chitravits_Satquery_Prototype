"""PreprocessorNode: orchestrates existing Preprocessors/ components.

Imports ``satquery_preprocessor.run_unified_preprocessor`` and
``geopandas_agent.get_vector_info`` by adding Preprocessors/ to sys.path at
import time.  Neither of those files is modified.

On environments where the EO dependencies (rasterio, cv2, geopandas, etc.) are
not installed, the node degrades gracefully: it sets empty lists for
``data_profiles`` and ``aoi_contexts`` and logs a warning instead of crashing
the graph.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

from satquery.preprocessor.schemas import (
    AOIContext,
    BandInfo,
    BandStat,
    BoundsProjected,
    BoundsWGS84,
    CRSInfo,
    DataProfile,
    GeodesicArea,
    ImageQuality,
    ROI,
    SatelliteIdentity,
)

if TYPE_CHECKING:
    from satquery.agent.state import AgentState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies (EO stack)
# ---------------------------------------------------------------------------
try:
    import numpy as np
    import rasterio
    _HAS_RASTERIO = True
except ImportError:
    _HAS_RASTERIO = False

# ---------------------------------------------------------------------------
# Dynamic import of Preprocessors/ modules (unchanged files)
# ---------------------------------------------------------------------------
_PREPROCESSORS_DIR = Path(__file__).parent.parent.parent / "Preprocessors"
_run_unified_preprocessor: Any = None
_parse_satellite_identity: Any = None
_get_vector_info: Any = None
_HAS_PREPROCESSORS = False
_PREPROCESSORS_IMPORT_ERROR: str = ""

try:
    for _d in [str(_PREPROCESSORS_DIR), str(_PREPROCESSORS_DIR / "GeoPandas")]:
        if _d not in sys.path:
            sys.path.insert(0, _d)

    from satquery_preprocessor import (  # type: ignore[import]
        parse_satellite_identity as _parse_satellite_identity,
        run_unified_preprocessor as _run_unified_preprocessor,
    )
    from geopandas_agent import get_vector_info as _get_vector_info  # type: ignore[import]
    _HAS_PREPROCESSORS = True
except Exception as _err:
    _PREPROCESSORS_IMPORT_ERROR = str(_err)
    logger.debug("Preprocessors not available: %s", _err)


# ---------------------------------------------------------------------------
# Nodata-aware band statistics
# Replaces satquery_preprocessor's arr > 0 approach with the actual nodata mask.
# ---------------------------------------------------------------------------
_DTYPE_MAX: dict[str, float] = {
    "uint8": 255.0, "uint16": 65535.0, "uint32": 4294967295.0,
    "int8": 127.0, "int16": 32767.0, "int32": 2147483647.0,
}


def _compute_nodata_aware_stats(
    path: Path,
) -> tuple[list[BandStat], ImageQuality, BoundsProjected]:
    """Compute per-band statistics and image quality using the rasterio nodata mask."""
    if not _HAS_RASTERIO:
        raise RuntimeError("rasterio is not installed; cannot compute band statistics.")

    with rasterio.open(path) as src:
        nodata = src.nodata
        total_px = src.width * src.height

        # Native (projected) bounds
        b = src.bounds
        bounds_projected = BoundsProjected(
            left=round(float(b.left), 4),
            bottom=round(float(b.bottom), 4),
            right=round(float(b.right), 4),
            top=round(float(b.top), 4),
        )

        # Scene-level valid/nodata from band 1
        b1_data = src.read(1)
        if nodata is not None:
            valid_mask_b1 = b1_data != nodata
        else:
            valid_mask_b1 = np.ones_like(b1_data, dtype=bool)
        valid_count = int(valid_mask_b1.sum())

        # Cloud cover from GDAL tags — only if a recognised tag is present
        tags = src.tags()
        cloud_pct: Optional[float] = None
        for tag_key in ("CLOUD_COVERAGE_ASSESSMENT", "CLOUD_COVER", "CLOUDY_PIXEL_PERCENTAGE"):
            raw_cloud = tags.get(tag_key)
            if raw_cloud is not None:
                try:
                    cloud_pct = float(raw_cloud)
                    break
                except (ValueError, TypeError):
                    pass

        # Saturation for band 1 (integer dtypes only)
        sat_fraction: Optional[float] = None
        dtype_max = _DTYPE_MAX.get(str(src.dtypes[0]))
        if dtype_max is not None and total_px > 0:
            sat_count = int((b1_data == dtype_max).sum())
            sat_fraction = sat_count / total_px

        quality = ImageQuality(
            valid_pixel_ratio=(valid_count / total_px) if total_px > 0 else None,
            nodata_fraction=((total_px - valid_count) / total_px) if total_px > 0 else None,
            fill_value=nodata,
            saturated_fraction=sat_fraction,
            cloud_cover_pct=cloud_pct,
        )

        band_stats: list[BandStat] = []
        for b_idx in range(1, src.count + 1):
            data = src.read(b_idx)
            dtype_str = str(src.dtypes[b_idx - 1])

            if nodata is not None:
                valid_px = data[data != nodata]
            else:
                valid_px = data.flatten()

            n_valid = int(valid_px.size)
            n_nodata = total_px - n_valid

            if n_valid > 0:
                band_stats.append(BandStat(
                    band=b_idx,
                    dtype=dtype_str,
                    min=round(float(np.min(valid_px)), 4),
                    max=round(float(np.max(valid_px)), 4),
                    mean=round(float(np.mean(valid_px)), 4),
                    std=round(float(np.std(valid_px)), 4),
                    valid_pixel_ratio=n_valid / total_px if total_px > 0 else 0.0,
                    nodata_fraction=n_nodata / total_px if total_px > 0 else 0.0,
                ))
            else:
                band_stats.append(BandStat(
                    band=b_idx, dtype=dtype_str,
                    min=None, max=None, mean=None, std=None,
                    valid_pixel_ratio=0.0, nodata_fraction=1.0,
                ))

    return band_stats, quality, bounds_projected


# ---------------------------------------------------------------------------
# Modality resolution: AttachmentRef.modality is primary; filename is fallback
# ---------------------------------------------------------------------------
_SAR_MARKERS = ("SAR", "Sentinel-1", "S1A", "S1B", "C-Band")
_MS_MARKERS = ("MSI", "Landsat", "OLI", "TIRS", "MODIS")
_THERMAL_MARKERS = ("TIRS", "thermal", "LWIR")


def _resolve_modality(attachment: Any, sat_identity_raw: dict[str, Any]) -> str:
    if attachment.modality is not None:
        return attachment.modality.value
    combined = (
        (sat_identity_raw.get("satellite") or "")
        + " "
        + (sat_identity_raw.get("sensor") or "")
    )
    for m in _SAR_MARKERS:
        if m in combined:
            return "sar"
    for m in _THERMAL_MARKERS:
        if m in combined:
            return "thermal"
    for m in _MS_MARKERS:
        if m in combined:
            return "multispectral"
    return "other"


# ---------------------------------------------------------------------------
# SAR polarization labels (heuristic; SAR only)
# ---------------------------------------------------------------------------
_SAR_POL: dict[tuple[int, int], str] = {
    (2, 1): "VV", (2, 2): "VH",
    (1, 1): "VV",
    (4, 1): "HH", (4, 2): "HV", (4, 3): "VV", (4, 4): "VH",
}


def _polarization_label(modality: str, band_idx: int, band_count: int) -> Optional[str]:
    if modality != "sar":
        return None
    return _SAR_POL.get((band_count, band_idx))


# ---------------------------------------------------------------------------
# SatelliteIdentity: only set when the filename pattern matched something
# ---------------------------------------------------------------------------
_UNKNOWN_VALUES = frozenset({"Earth Observation Satellite", "Unknown", None, ""})


def _build_satellite_identity(raw: dict[str, Any]) -> Optional[SatelliteIdentity]:
    satellite = raw.get("satellite")
    acq_date = raw.get("acquisition_date")
    tile = raw.get("tile")
    band_desig = raw.get("band_designation")

    recognized = (
        satellite not in _UNKNOWN_VALUES
        or acq_date not in _UNKNOWN_VALUES
        or tile is not None
        or band_desig is not None
    )
    if not recognized:
        return None

    return SatelliteIdentity(
        satellite=satellite if satellite not in _UNKNOWN_VALUES else None,
        sensor=raw.get("sensor") or None,
        acquisition_date=acq_date if acq_date not in _UNKNOWN_VALUES else None,
        orbit=raw.get("orbit"),
        tile=tile,
        band_designation=band_desig,
        wavelength_nm=raw.get("wavelength_nm"),
        nominal_resolution_m=raw.get("nominal_resolution_m"),
    )


# ---------------------------------------------------------------------------
# Assemble DataProfile from run_unified_preprocessor output + nodata stats
# ---------------------------------------------------------------------------
def _build_data_profile(
    raw: dict[str, Any],
    band_stats: list[BandStat],
    quality: ImageQuality,
    bounds_projected: BoundsProjected,
    attachment: Any,
    source_file: str,
    errors: list[str],
) -> DataProfile:
    meta = raw.get("metadata", {})
    sat_raw = meta.get("satellite_identity", {})
    crs_raw = meta.get("crs_info", {})
    bounds_raw = meta.get("bounds_wgs84", {})
    geo_raw = meta.get("geodesic_area", {})

    sat_identity = _build_satellite_identity(sat_raw)
    modality = _resolve_modality(attachment, sat_raw)

    crs = CRSInfo(
        epsg=crs_raw.get("epsg"),
        name=crs_raw.get("name") or "Unknown",
        crs_type=crs_raw.get("type") or "Unknown",
        datum=crs_raw.get("datum"),
        units=crs_raw.get("units") or "unknown",
        area_of_use=crs_raw.get("area_of_use"),
    )

    center = bounds_raw.get("center", {})
    bounds_wgs84 = BoundsWGS84(
        west=float(bounds_raw.get("west", 0.0)),
        south=float(bounds_raw.get("south", 0.0)),
        east=float(bounds_raw.get("east", 0.0)),
        north=float(bounds_raw.get("north", 0.0)),
        center_lat=float(center.get("lat", 0.0)),
        center_lon=float(center.get("lon", 0.0)),
        polygon_coords=bounds_raw.get("polygon_coords") or [],
    )

    geodesic_area = GeodesicArea(
        area_sqm=float(geo_raw.get("area_sqm", 0.0)),
        area_ha=float(geo_raw.get("area_ha", 0.0)),
        area_km2=float(geo_raw.get("area_km2", 0.0)),
        area_acres=float(geo_raw.get("area_acres", 0.0)),
        perimeter_m=float(geo_raw.get("perimeter_m", 0.0)),
    )

    res = meta.get("resolution") or [1.0, 1.0]
    res_desc = meta.get("resolution_desc") or ""
    # "meters" if the description contains "m" but not "deg"
    res_unit = "meters" if ("m" in res_desc and "deg" not in res_desc.lower()) else "degrees"

    band_count = meta.get("band_count", 1)
    bands: list[BandInfo] = []
    for b_idx in range(1, band_count + 1):
        stat = next((s for s in band_stats if s.band == b_idx), None)
        designation: Optional[str] = None
        wl: Optional[float] = None
        nom_res: Optional[float] = None
        if sat_identity and band_count == 1:
            designation = sat_identity.band_designation
            wl = sat_identity.wavelength_nm
            nom_res = sat_identity.nominal_resolution_m
        pol = _polarization_label(modality, b_idx, band_count)
        bands.append(BandInfo(
            band_index=b_idx,
            designation=designation,
            wavelength_nm=wl,
            nominal_resolution_m=nom_res,
            polarization=pol,
            stats=stat,
        ))

    rois: list[ROI] = []
    for r in raw.get("detected_rois", []):
        rois.append(ROI(
            roi_id=r["roi_id"],
            roi_type=r["roi_type"],
            pixel_area=int(r["pixel_area"]),
            pixel_bbox=list(r["pixel_bbox"]),
            pixel_centroid=list(r.get("pixel_centroid", [0.0, 0.0])),
            centroid_lat=r.get("centroid_lat"),
            centroid_lon=r.get("centroid_lon"),
            area_ha=r.get("area_ha"),
            area_sqm=r.get("area_sqm"),
            perimeter_m=r.get("perimeter_m"),
            bbox_wgs84=r.get("bbox_wgs84"),
            polygon_wgs84=r.get("polygon_wgs84"),
            radiometrics=r.get("radiometrics") or {},
        ))

    vl = raw.get("vector_layers") or {}

    # Acquisition date: satellite identity → AttachmentRef.timestamp
    acq_date: Optional[str] = None
    if sat_identity and sat_identity.acquisition_date:
        acq_date = sat_identity.acquisition_date
    elif attachment.timestamp is not None:
        acq_date = str(attachment.timestamp)

    return DataProfile(
        attachment_id=attachment.id,
        attachment_role=attachment.role.value if attachment.role else None,
        attachment_kind=attachment.kind.value,
        source_uri=attachment.uri,
        source_file=source_file,
        satellite_identity=sat_identity,
        sensor_modality=modality,
        width=int(meta.get("width", 0)),
        height=int(meta.get("height", 0)),
        band_count=band_count,
        data_types=list(meta.get("data_types") or []),
        driver=str(meta.get("driver") or "Unknown"),
        file_size_kb=float(meta.get("file_size_kb", 0.0)),
        crs=crs,
        resolution_x=float(res[0]),
        resolution_y=float(res[1]),
        resolution_unit=res_unit,
        bounds_wgs84=bounds_wgs84,
        bounds_projected=bounds_projected,
        geodesic_area=geodesic_area,
        acquisition_date=acq_date,
        bands=bands,
        quality=quality,
        detected_rois=rois,
        total_rois=len(rois),
        roi_extraction_mode=str(raw.get("active_mode") or "salient_anomalies"),
        spatial_query=raw.get("spatial_query_info"),
        tile_geojson=vl.get("tile_geojson"),
        rois_geojson=vl.get("objects_geojson"),
        elapsed_ms=float(raw.get("elapsed_ms", 0.0)),
        preprocessing_errors=errors,
    )


# ---------------------------------------------------------------------------
# Fallback band stats from raw preprocessor output (when rasterio fails)
# ---------------------------------------------------------------------------
def _fallback_band_stats(raw: dict[str, Any]) -> tuple[list[BandStat], ImageQuality]:
    raw_stats = (raw.get("metadata") or {}).get("band_statistics") or []
    band_stats = [
        BandStat(
            band=int(s.get("band", i + 1)),
            dtype=str(s.get("dtype", "unknown")),
            min=s.get("min"),
            max=s.get("max"),
            mean=s.get("mean"),
            std=s.get("std"),
            valid_pixel_ratio=0.0,
            nodata_fraction=0.0,
        )
        for i, s in enumerate(raw_stats)
    ]
    return band_stats, ImageQuality()


# ---------------------------------------------------------------------------
# Infer temp file suffix from attachment
# ---------------------------------------------------------------------------
def _infer_suffix(attachment: Any) -> str:
    if attachment.uri:
        suffix = Path(urlparse(attachment.uri).path).suffix.lower()
        if suffix in {".tif", ".tiff", ".jp2", ".png", ".jpg", ".jpeg", ".img"}:
            return suffix
    return ".tif"


# ---------------------------------------------------------------------------
# Process one raster attachment → DataProfile
# ---------------------------------------------------------------------------
async def _process_raster(
    attachment: Any,
    resolver: Any,
    query_text: str,
) -> DataProfile:
    errors: list[str] = []

    resolved = await resolver.resolve(attachment)

    suffix = _infer_suffix(attachment)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(resolved.data)
        tmp_path = Path(tmp.name)

    try:
        raw = _run_unified_preprocessor(
            image_path=tmp_path,
            user_query=query_text,
            extraction_mode="salient_anomalies",
        )

        try:
            band_stats, quality, bounds_projected = _compute_nodata_aware_stats(tmp_path)
        except Exception as exc:
            logger.warning("Nodata-aware stats failed for %s: %s", attachment.id, exc)
            errors.append(f"band_stats_fallback:{exc}")
            band_stats, quality = _fallback_band_stats(raw)
            # Approximate bounds from webmercator fallback
            wm = (raw.get("metadata") or {}).get("bounds_webmercator") or {}
            bounds_projected = BoundsProjected(
                left=float(wm.get("left", 0.0)),
                bottom=float(wm.get("bottom", 0.0)),
                right=float(wm.get("right", 0.0)),
                top=float(wm.get("top", 0.0)),
            )

        return _build_data_profile(
            raw, band_stats, quality, bounds_projected, attachment, tmp_path.name, errors
        )

    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Process one vector (AOI) attachment → AOIContext
# ---------------------------------------------------------------------------
async def _process_vector(
    attachment: Any,
    resolver: Any,
) -> AOIContext:
    errors: list[str] = []

    resolved = await resolver.resolve(attachment)

    # Pick a sensible suffix
    suffix = ".geojson"
    if attachment.uri:
        uri_suffix = Path(urlparse(attachment.uri).path).suffix.lower()
        if uri_suffix in {".geojson", ".json", ".gpkg", ".shp", ".kml", ".parquet"}:
            suffix = uri_suffix

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(resolved.data)
        tmp_path = Path(tmp.name)

    try:
        info = _get_vector_info(tmp_path)
        crs = info.get("crs") or {}
        bounds = info.get("wgs84_bounds") or []
        return AOIContext(
            attachment_id=attachment.id,
            attachment_role=attachment.role.value if attachment.role else None,
            source_file=tmp_path.name,
            feature_count=int(info.get("feature_count", 0)),
            crs_epsg=crs.get("epsg"),
            crs_name=crs.get("name"),
            wgs84_bounds=bounds if (isinstance(bounds, list) and len(bounds) == 4) else None,
            total_area_ha=info.get("total_area_ha"),
            total_area_km2=info.get("total_area_sqkm"),
            geojson=info.get("geojson"),
            preprocessing_errors=errors,
        )
    except Exception as exc:
        logger.warning("Vector preprocessing failed for %s: %s", attachment.id, exc)
        return AOIContext(
            attachment_id=attachment.id,
            attachment_role=attachment.role.value if attachment.role else None,
            source_file="",
            preprocessing_errors=[str(exc)],
        )
    finally:
        try:
            tmp_path.unlink()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# The LangGraph node factory
# ---------------------------------------------------------------------------
def make_preprocessor_node(resolver: Any):
    """Bind the resolver and return the async LangGraph preprocess node."""

    from satquery.agent.state import AgentError  # local import avoids any import-order issue
    from satquery.input.schemas import AttachmentKind
    from satquery.agent.tools.attachment_resolver import AttachmentResolutionError

    async def preprocess(state: "AgentState") -> dict:
        user_query = state.get("user_query")
        if user_query is None:
            return {}

        if not _HAS_PREPROCESSORS:
            logger.warning(
                "Preprocessors not available (%s); skipping preprocessing.",
                _PREPROCESSORS_IMPORT_ERROR,
            )
            return {"data_profiles": [], "aoi_contexts": []}

        query_text: str = state.get("query_text") or user_query.query
        data_profiles: list[DataProfile] = []
        aoi_contexts: list[AOIContext] = []
        node_errors: list[AgentError] = []

        for attachment in user_query.attachments:
            try:
                if attachment.kind == AttachmentKind.VECTOR:
                    aoi = await _process_vector(attachment, resolver)
                    aoi_contexts.append(aoi)
                elif attachment.kind == AttachmentKind.IMAGE:
                    profile = await _process_raster(attachment, resolver, query_text)
                    data_profiles.append(profile)
                # AttachmentKind.OTHER is silently skipped
            except AttachmentResolutionError as exc:
                logger.info(
                    "Could not resolve attachment %s [%s]: %s",
                    attachment.id, exc.code, exc.message,
                )
                node_errors.append(AgentError(
                    code=exc.code, message=exc.message, stage="preprocess"
                ))
            except Exception as exc:
                logger.warning(
                    "Preprocessing failed for attachment %s: %s", attachment.id, exc
                )
                node_errors.append(AgentError(
                    code="PREPROCESSING_FAILED",
                    message=f"Failed to preprocess attachment '{attachment.id}': {exc}",
                    stage="preprocess",
                ))

        result: dict = {
            "data_profiles": data_profiles,
            "aoi_contexts": aoi_contexts,
        }
        if node_errors:
            result["errors"] = node_errors
        return result

    return preprocess

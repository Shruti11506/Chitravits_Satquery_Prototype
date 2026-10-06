"""Pydantic models for the preprocessing layer.

``DataProfile`` is the stable, typed contract between the PreprocessorNode
and the LangGraph agent. It contains only deterministically extracted physical
facts: no semantic inferences, no VLM prompt text, no model-specific content.

``AOIContext`` carries spatial context from a vector (AOI) attachment.
It is kept separate from ``DataProfile`` because it is not a raster profile.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Band-level models
# ---------------------------------------------------------------------------

class BandStat(BaseModel):
    """Per-band radiometric statistics computed using the actual rasterio nodata mask."""

    band: int
    dtype: str
    min: Optional[float] = None
    max: Optional[float] = None
    mean: Optional[float] = None
    std: Optional[float] = None
    valid_pixel_ratio: float = 0.0   # non-nodata pixels / total pixels
    nodata_fraction: float = 0.0     # nodata pixels / total pixels


class BandInfo(BaseModel):
    """Descriptor for one raster band.  Keeps platform identity separate from modality."""

    band_index: int                         # 1-based
    designation: Optional[str] = None      # "B02 (Blue - 490nm, 10m)"
    wavelength_nm: Optional[float] = None
    nominal_resolution_m: Optional[float] = None
    polarization: Optional[str] = None     # "VV" | "VH" | "HH" | "HV" — SAR only
    stats: Optional[BandStat] = None


# ---------------------------------------------------------------------------
# Coordinate reference system
# ---------------------------------------------------------------------------

class CRSInfo(BaseModel):
    epsg: Optional[int] = None
    name: str = "Unknown"
    crs_type: str = "Unknown"           # "Projected" | "Geographic" | "Local"
    datum: Optional[str] = None
    units: str = "unknown"              # "meters" | "degrees" | "pixels"
    area_of_use: Optional[str] = None


# ---------------------------------------------------------------------------
# Spatial extent models
# ---------------------------------------------------------------------------

class BoundsWGS84(BaseModel):
    west: float
    south: float
    east: float
    north: float
    center_lat: float
    center_lon: float
    polygon_coords: List[List[float]] = Field(default_factory=list)  # [[lon, lat], ...] closed ring


class GeodesicArea(BaseModel):
    """True curved-earth geodesic area computed via PyProj Geod."""

    area_sqm: float
    area_ha: float
    area_km2: float
    area_acres: float
    perimeter_m: float


class BoundsProjected(BaseModel):
    """Extent in the raster's native CRS."""

    left: float
    bottom: float
    right: float
    top: float


# ---------------------------------------------------------------------------
# Region of Interest
# ---------------------------------------------------------------------------

class ROI(BaseModel):
    """A physically-labelled radiometric region.  No semantic class is assumed."""

    roi_id: str
    roi_type: str                                   # e.g. "High-Reflectance ROI"
    pixel_area: int
    pixel_bbox: List[int]                           # [row_min, col_min, row_max, col_max]
    pixel_centroid: List[float]                     # [row, col]
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    area_ha: Optional[float] = None
    area_sqm: Optional[float] = None
    perimeter_m: Optional[float] = None
    bbox_wgs84: Optional[List[float]] = None        # [west, south, east, north]
    polygon_wgs84: Optional[List[List[float]]] = None
    radiometrics: Dict[str, float] = Field(default_factory=dict)  # min, max, mean, std


# ---------------------------------------------------------------------------
# Image quality  (extensible — add fields here without touching DataProfile)
# ---------------------------------------------------------------------------

class ImageQuality(BaseModel):
    """
    Physical quality indicators.  All fields are Optional: a value of None means
    "not computed", never "zero" or "clear sky".  Cloud cover is only populated
    when the raster's GDAL tags carry it; it is never inferred or fabricated.
    """

    valid_pixel_ratio: Optional[float] = None   # non-nodata / total
    nodata_fraction: Optional[float] = None     # nodata / total
    fill_value: Optional[float] = None          # the nodata value reported by rasterio
    saturated_fraction: Optional[float] = None  # pixels at dtype max / total (band 1)
    cloud_cover_pct: Optional[float] = None     # from GDAL tags only; None if absent


# ---------------------------------------------------------------------------
# Platform / sensor identity  (optional — unknown GeoTIFFs leave this None)
# ---------------------------------------------------------------------------

class SatelliteIdentity(BaseModel):
    """
    Platform and sensor descriptor, kept separate from sensor modality.
    Example: Sentinel-2A / MSI / multispectral  or  Sentinel-1A / C-SAR / SAR.
    Set to None on the parent DataProfile when the filename does not match any
    known naming convention.
    """

    satellite: Optional[str] = None            # "Copernicus Sentinel-2A"
    sensor: Optional[str] = None               # "MultiSpectral Instrument (MSI) L2A"
    acquisition_date: Optional[str] = None     # ISO-8601 string
    orbit: Optional[str] = None
    tile: Optional[str] = None                 # MGRS tile for S2
    band_designation: Optional[str] = None     # "B02 (Blue - 490nm, 10m)"
    wavelength_nm: Optional[float] = None
    nominal_resolution_m: Optional[float] = None


# ---------------------------------------------------------------------------
# DataProfile  — the stable interface between preprocessing and LangGraph
# ---------------------------------------------------------------------------

class DataProfile(BaseModel):
    """
    Physical facts about one processed raster attachment.

    Design invariants:
    - One DataProfile per raster AttachmentRef.
    - Contains NO model-facing prompt text and NO semantic inferences.
    - ``satellite_identity`` is None for arbitrary/unknown GeoTIFFs.
    - ``sensor_modality`` comes from AttachmentRef.modality first; filename
      heuristics are the fallback only.
    - Band statistics use the actual rasterio nodata mask (not arr > 0).
    """

    # --- Provenance ---
    attachment_id: str
    attachment_role: Optional[str] = None       # "before" | "after" | "reference"
    attachment_kind: str = "image"
    source_uri: Optional[str] = None
    source_file: str

    # --- Platform / sensor  (modality ≠ identity) ---
    satellite_identity: Optional[SatelliteIdentity] = None
    sensor_modality: str = "other"              # from AttachmentRef.modality (primary)

    # --- Raster dimensions ---
    width: int
    height: int
    band_count: int
    data_types: List[str]
    driver: str
    file_size_kb: float

    # --- Spatial ---
    crs: CRSInfo
    resolution_x: float
    resolution_y: float
    resolution_unit: str                        # "meters" | "degrees"
    bounds_wgs84: BoundsWGS84
    bounds_projected: BoundsProjected          # native CRS bounds
    geodesic_area: GeodesicArea

    # --- Temporal ---
    acquisition_date: Optional[str] = None

    # --- Bands ---
    bands: List[BandInfo] = Field(default_factory=list)

    # --- Image quality ---
    quality: ImageQuality

    # --- Radiometric regions of interest ---
    detected_rois: List[ROI] = Field(default_factory=list)
    total_rois: int = 0
    roi_extraction_mode: str = "salient_anomalies"

    # --- Spatial query result (point-in-tile, if query contained coordinates) ---
    spatial_query: Optional[Dict[str, Any]] = None

    # --- Vector footprints for map display / downstream spatial operations ---
    tile_geojson: Optional[Dict[str, Any]] = None
    rois_geojson: Optional[Dict[str, Any]] = None

    # --- Diagnostics ---
    elapsed_ms: float = 0.0
    preprocessing_errors: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# AOIContext  — spatial context from a vector (kind="vector") attachment
# ---------------------------------------------------------------------------

class AOIContext(BaseModel):
    """
    Spatial context derived from a vector (AOI) attachment.
    Intentionally not a DataProfile: vectors are not rasters.
    """

    attachment_id: str
    attachment_role: Optional[str] = None
    source_file: str = ""
    feature_count: int = 0
    crs_epsg: Optional[int] = None
    crs_name: Optional[str] = None
    wgs84_bounds: Optional[List[float]] = None  # [west, south, east, north]
    total_area_ha: Optional[float] = None
    total_area_km2: Optional[float] = None
    geojson: Optional[Dict[str, Any]] = None
    preprocessing_errors: List[str] = Field(default_factory=list)
